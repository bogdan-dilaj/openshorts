import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as openshorts


def make_transcript(sentences, *, word_duration=0.42, word_gap=0.08, sentence_gap=0.8):
    cursor = 0.0
    segments = []
    ranges = []
    for sentence in sentences:
        words = []
        sentence_start = cursor
        for token in sentence.split():
            word_start = cursor
            word_end = word_start + word_duration
            words.append({"word": token, "start": word_start, "end": word_end})
            cursor = word_end + word_gap
        sentence_end = words[-1]["end"]
        segments.append({
            "text": sentence,
            "start": sentence_start,
            "end": sentence_end,
            "words": words,
        })
        ranges.append((sentence_start, sentence_end))
        cursor = sentence_end + sentence_gap
    return {
        "text": " ".join(sentences),
        "language": "de",
        "segments": segments,
    }, ranges


def candidate(start, end):
    return {
        "shorts": [{
            "start": start,
            "end": end,
            "video_title_for_youtube_short": "Test",
            "video_description_for_tiktok": "Test",
            "video_description_for_instagram": "Test",
            "viral_hook_text": "Der entscheidende Punkt",
        }]
    }


def test_repairs_start_and_end_to_complete_sentences():
    transcript, ranges = make_transcript([
        "Die Vorgeschichte liefert nur den notwendigen Rahmen.",
        "Der eigentliche Fehler beginnt mit einer falschen Annahme.",
        "Deshalb bauen wir zuerst Vertrauen auf und loesen danach das Problem vollstaendig.",
    ])
    raw_start = ranges[1][0] + 0.7
    raw_end = ranges[2][0] + 2.0

    result = openshorts.sanitize_clip_candidates(
        candidate(raw_start, raw_end),
        ranges[-1][1] + 1.0,
        transcript_result=transcript,
        min_clip_duration=8.0,
        max_clip_duration=20.0,
        preferred_min_clip_duration=8.0,
    )

    assert result is not None
    clip = result["shorts"][0]
    assert clip["start"] <= ranges[1][0]
    assert clip["end"] >= ranges[2][1]
    assert clip["boundary_adjustment"]["start_shift"] < 0
    assert clip["boundary_adjustment"]["end_shift"] > 0
    assert not clip["quality_flags"]


def test_overlong_candidate_keeps_payoff_without_hard_cut():
    transcript, ranges = make_transcript(
        [
            "Der alte Ansatz kostet jeden Tag sehr viel Zeit.",
            "Der neue Ablauf entfernt genau diesen unnoetigen Schritt.",
            "Am Ende bleibt mehr Zeit fuer die wirklich wichtige Arbeit.",
        ],
        word_duration=0.48,
    )

    result = openshorts.sanitize_clip_candidates(
        candidate(ranges[0][0] + 0.2, ranges[2][1] - 0.2),
        ranges[-1][1] + 1.0,
        transcript_result=transcript,
        min_clip_duration=5.0,
        max_clip_duration=11.3,
        preferred_min_clip_duration=5.0,
    )

    assert result is not None
    clip = result["shorts"][0]
    assert clip["end"] >= ranges[2][1], (clip, ranges)
    assert clip["start"] >= ranges[1][0] - 0.25, (clip, ranges)
    assert clip["end"] - clip["start"] <= 11.3


def test_rejects_range_when_no_complete_boundary_fits():
    words = []
    cursor = 0.0
    tokens = ["dieser", "gedanke", "laeuft"] * 12
    for token in tokens:
        words.append({"word": token, "start": cursor, "end": cursor + 0.34})
        cursor += 0.42
    transcript = {
        "text": " ".join(tokens),
        "language": "de",
        "segments": [{"text": " ".join(tokens), "start": 0.0, "end": words[-1]["end"], "words": words}],
    }

    result = openshorts.sanitize_clip_candidates(
        candidate(4.0, 11.0),
        words[-1]["end"] + 0.5,
        transcript_result=transcript,
        min_clip_duration=5.0,
        max_clip_duration=8.0,
        preferred_min_clip_duration=5.0,
    )

    assert result is None


def test_window_text_uses_only_words_inside_exact_range():
    transcript, ranges = make_transcript([
        "Erster Satz bleibt draussen.",
        "Nur dieser zweite Satz gehoert hinein.",
        "Dritter Satz bleibt ebenfalls draussen.",
    ])

    text = openshorts._extract_transcript_window_text(
        transcript,
        ranges[1][0] - 0.05,
        ranges[1][1] + 0.05,
    )

    assert "Erster" not in text
    assert "zweite" in text
    assert "Dritter" not in text


def test_chunk_windows_include_surrounding_boundary_context():
    transcript, _ = make_transcript(
        [f"Satz Nummer {index} liefert weiteren Kontext." for index in range(12)],
        sentence_gap=1.0,
    )
    windows = openshorts.split_transcript_for_ollama(
        transcript,
        window_seconds=12.0,
        overlap_seconds=3.0,
        context_seconds=5.0,
    )

    assert len(windows) > 1
    assert windows[0]["start"] == 0.0
    assert windows[0]["end"] == 12.0
    assert windows[0]["context_start"] == 0.0
    assert windows[0]["context_end"] == 17.0
    assert windows[1]["context_start"] < windows[1]["start"]
    assert windows[1]["context_end"] > windows[1]["end"]

    prompt = openshorts.build_ollama_prompt(
        video_duration=windows[-1]["context_end"],
        transcript_window=windows[0],
        min_clip_duration=5.0,
        max_clip_duration=20.0,
    )
    assert "CANDIDATE_FOCUS_RANGE_SECONDS: 0.00 - 12.00" in prompt
    assert "SURROUNDING_CONTEXT_RANGE_SECONDS: 0.00 - 17.00" in prompt


def test_full_prompt_exposes_selection_scope():
    prompt = openshorts.build_viral_prompt(
        90.0,
        "Ein vollstaendiger Testgedanke.",
        [{"w": "Testgedanke.", "s": 1.0, "e": 1.5}],
        min_clip_duration=5.0,
        max_clip_duration=20.0,
        chunk_hint="Focus 10-30s and use context 0-45s.",
    )

    assert "SELECTION_SCOPE:" in prompt
    assert "Focus 10-30s and use context 0-45s." in prompt
    assert "HARD LENGTH RANGE: 5 to 20 seconds" in prompt


def test_complete_connector_word_and_formal_sie_are_not_false_positives():
    transcript, ranges = make_transcript([
        "Sie muessen diesen Fehler wirklich vermeiden.",
        "Das bleibt nun einmal so.",
    ])

    opening_ok, opening_detail = openshorts._assess_clip_opening_quality(
        transcript,
        ranges[0][0],
        ranges[0][1],
    )
    ending_ok, ending_detail = openshorts._assess_clip_ending_quality(
        transcript,
        ranges[1][0],
        ranges[1][1] + 0.1,
    )

    assert opening_ok, opening_detail
    assert ending_ok, ending_detail


def run_tests():
    test_repairs_start_and_end_to_complete_sentences()
    test_overlong_candidate_keeps_payoff_without_hard_cut()
    test_rejects_range_when_no_complete_boundary_fits()
    test_window_text_uses_only_words_inside_exact_range()
    test_chunk_windows_include_surrounding_boundary_context()
    test_full_prompt_exposes_selection_scope()
    test_complete_connector_word_and_formal_sie_are_not_false_positives()
    print("Clip boundary tests passed.")


if __name__ == "__main__":
    run_tests()
