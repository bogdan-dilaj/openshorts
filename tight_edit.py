import os
import re
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple


RangeTuple = Tuple[float, float]


TIGHT_EDIT_PRESETS: Dict[str, Dict[str, float | int | bool | str]] = {
    "off": {
        "label": "Off",
        "pause_threshold": 999.0,
        "pause_after_keep": 0.0,
        "pause_before_keep": 0.0,
        "edge_keep": 0.0,
        "filler_padding_before": 0.0,
        "filler_padding_after": 0.0,
        "max_filler_duration": 0.0,
        "min_segment_duration": 0.0,
        "min_removed_range": 0.0,
        "enabled": False,
    },
    "balanced": {
        "label": "Balanced",
        "pause_threshold": 0.42,
        "pause_after_keep": 0.06,
        "pause_before_keep": 0.09,
        "edge_keep": 0.08,
        "filler_padding_before": 0.03,
        "filler_padding_after": 0.03,
        "max_filler_duration": 0.75,
        "min_segment_duration": 0.18,
        "min_removed_range": 0.08,
        "enabled": True,
    },
    "aggressive": {
        "label": "Aggressive",
        "pause_threshold": 0.28,
        "pause_after_keep": 0.04,
        "pause_before_keep": 0.06,
        "edge_keep": 0.06,
        "filler_padding_before": 0.02,
        "filler_padding_after": 0.02,
        "max_filler_duration": 0.70,
        "min_segment_duration": 0.16,
        "min_removed_range": 0.06,
        "enabled": True,
    },
    "very_aggressive": {
        "label": "Very Aggressive",
        "pause_threshold": 0.22,
        "pause_after_keep": 0.03,
        "pause_before_keep": 0.05,
        "edge_keep": 0.05,
        "filler_padding_before": 0.02,
        "filler_padding_after": 0.02,
        "max_filler_duration": 0.65,
        "min_segment_duration": 0.14,
        "min_removed_range": 0.05,
        "enabled": True,
    },
}

DEFAULT_TIGHT_EDIT_PRESET = "aggressive"
MIN_LONG_CLIP_OUTPUT_DURATION = 60.0

FILLER_WORDS = {
    "ah",
    "aeh",
    "aehm",
    "eh",
    "em",
    "erm",
    "hm",
    "hmm",
    "mm",
    "mmm",
    "uh",
    "uhh",
    "um",
    "umm",
    "a",
}


def normalize_tight_edit_preset(value: Optional[str], default: str = DEFAULT_TIGHT_EDIT_PRESET) -> str:
    normalized = (value or default).strip().lower().replace("-", "_")
    if normalized not in TIGHT_EDIT_PRESETS:
        return default
    return normalized


def get_tight_edit_preset(value: Optional[str]) -> Dict[str, float | int | bool | str]:
    return TIGHT_EDIT_PRESETS[normalize_tight_edit_preset(value)]


def _round_time(value: float) -> float:
    return round(max(0.0, float(value)), 3)


def _normalize_token(word: str) -> str:
    token = (word or "").strip().lower()
    token = token.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    token = re.sub(r"^[^\w]+|[^\w]+$", "", token)
    return token


def merge_ranges(ranges: Sequence[RangeTuple], min_gap: float = 0.01) -> List[RangeTuple]:
    normalized = sorted(
        (
            (_round_time(start), _round_time(end))
            for start, end in ranges
            if end > start
        ),
        key=lambda item: item[0],
    )
    if not normalized:
        return []

    merged: List[RangeTuple] = [normalized[0]]
    for start, end in normalized[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + min_gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def invert_ranges(window_start: float, window_end: float, remove_ranges: Sequence[RangeTuple], min_segment_duration: float = 0.0) -> List[RangeTuple]:
    keep_segments: List[RangeTuple] = []
    cursor = _round_time(window_start)
    safe_end = _round_time(window_end)

    for start, end in merge_ranges(remove_ranges):
        clamped_start = max(cursor, _round_time(start))
        clamped_end = min(safe_end, _round_time(end))
        if clamped_end <= cursor:
            continue
        if clamped_start - cursor >= min_segment_duration:
            keep_segments.append((_round_time(cursor), _round_time(clamped_start)))
        cursor = max(cursor, clamped_end)

    if safe_end - cursor >= min_segment_duration:
        keep_segments.append((_round_time(cursor), safe_end))

    return keep_segments


def _sum_range_duration(ranges: Sequence[RangeTuple]) -> float:
    return _round_time(sum(max(0.0, float(end) - float(start)) for start, end in ranges))


def _build_gap_candidates(window_start: float, window_end: float, keep_segments: Sequence[RangeTuple]) -> List[Dict[str, float | int | None]]:
    merged_keep_segments = merge_ranges(keep_segments)
    if not merged_keep_segments:
        return []

    gaps: List[Dict[str, float | int | None]] = []

    leading_gap = merged_keep_segments[0][0] - window_start
    if leading_gap > 0:
        gaps.append({
            "start": _round_time(window_start),
            "end": _round_time(merged_keep_segments[0][0]),
            "duration": _round_time(leading_gap),
            "left_index": None,
            "right_index": 0,
        })

    for index in range(1, len(merged_keep_segments)):
        gap_start = merged_keep_segments[index - 1][1]
        gap_end = merged_keep_segments[index][0]
        gap_duration = gap_end - gap_start
        if gap_duration <= 0:
            continue
        gaps.append({
            "start": _round_time(gap_start),
            "end": _round_time(gap_end),
            "duration": _round_time(gap_duration),
            "left_index": index - 1,
            "right_index": index,
        })

    trailing_gap = window_end - merged_keep_segments[-1][1]
    if trailing_gap > 0:
        gaps.append({
            "start": _round_time(merged_keep_segments[-1][1]),
            "end": _round_time(window_end),
            "duration": _round_time(trailing_gap),
            "left_index": len(merged_keep_segments) - 1,
            "right_index": None,
        })

    return gaps


def _expand_keep_segments_to_min_duration(
    window_start: float,
    window_end: float,
    keep_segments: Sequence[RangeTuple],
    min_output_duration: float,
) -> List[RangeTuple]:
    expanded_keep_segments = merge_ranges(keep_segments)
    if not expanded_keep_segments:
        return []

    target_duration = min(float(min_output_duration), float(window_end) - float(window_start))
    current_duration = _sum_range_duration(expanded_keep_segments)
    if current_duration >= target_duration:
        return expanded_keep_segments

    while current_duration < target_duration:
        gap_candidates = _build_gap_candidates(window_start, window_end, expanded_keep_segments)
        if not gap_candidates:
            break

        gap = min(gap_candidates, key=lambda item: (float(item["duration"]), float(item["start"])))
        gap_duration = float(gap["duration"])
        if gap_duration <= 0:
            break

        restore_duration = min(gap_duration, target_duration - current_duration)
        left_index = gap["left_index"]
        right_index = gap["right_index"]

        if left_index is None and right_index is not None:
            start, end = expanded_keep_segments[int(right_index)]
            expanded_keep_segments[int(right_index)] = (
                _round_time(max(window_start, start - restore_duration)),
                end,
            )
        elif right_index is None and left_index is not None:
            start, end = expanded_keep_segments[int(left_index)]
            expanded_keep_segments[int(left_index)] = (
                start,
                _round_time(min(window_end, end + restore_duration)),
            )
        elif left_index is not None and right_index is not None:
            left_restore = restore_duration / 2.0
            right_restore = restore_duration - left_restore
            left_start, left_end = expanded_keep_segments[int(left_index)]
            right_start, right_end = expanded_keep_segments[int(right_index)]
            expanded_keep_segments[int(left_index)] = (
                left_start,
                _round_time(min(window_end, left_end + left_restore)),
            )
            expanded_keep_segments[int(right_index)] = (
                _round_time(max(window_start, right_start - right_restore)),
                right_end,
            )
        else:
            break

        expanded_keep_segments = merge_ranges(expanded_keep_segments)
        current_duration = _sum_range_duration(expanded_keep_segments)

    return expanded_keep_segments


def _remove_ranges_from_keep_segments(window_start: float, window_end: float, keep_segments: Sequence[RangeTuple]) -> List[RangeTuple]:
    remove_ranges: List[RangeTuple] = []
    cursor = _round_time(window_start)
    safe_end = _round_time(window_end)

    for start, end in merge_ranges(keep_segments):
        clamped_start = max(cursor, _round_time(start))
        clamped_end = min(safe_end, _round_time(end))
        if clamped_end <= cursor:
            continue
        if clamped_start > cursor:
            remove_ranges.append((_round_time(cursor), _round_time(clamped_start)))
        cursor = max(cursor, clamped_end)

    if safe_end > cursor:
        remove_ranges.append((_round_time(cursor), safe_end))

    return remove_ranges


def plan_manual_keep_segments(
    trim_start: float,
    trim_end: float,
    remove_ranges: Sequence[RangeTuple],
    *,
    min_segment_duration: float = 0.10,
) -> List[RangeTuple]:
    clamped_ranges = []
    for start, end in remove_ranges:
        clamped_start = max(trim_start, min(trim_end, float(start)))
        clamped_end = max(trim_start, min(trim_end, float(end)))
        if clamped_end > clamped_start:
            clamped_ranges.append((clamped_start, clamped_end))
    return invert_ranges(trim_start, trim_end, clamped_ranges, min_segment_duration=min_segment_duration)


def _extract_words(transcript: Optional[Dict], clip_start: float, clip_end: float) -> List[Dict]:
    if not transcript:
        return []

    words: List[Dict] = []
    for segment in transcript.get("segments", []):
        for word in segment.get("words", []):
            start = float(word.get("start", 0.0))
            end = float(word.get("end", start))
            if end <= clip_start or start >= clip_end:
                continue
            token = _normalize_token(word.get("word", ""))
            if not token:
                continue
            words.append({
                "word": word.get("word", ""),
                "token": token,
                "start": max(clip_start, start),
                "end": min(clip_end, end),
            })
    return words


def build_tight_edit_plan(transcript: Optional[Dict], clip_start: float, clip_end: float, preset_name: Optional[str]) -> Dict:
    preset_key = normalize_tight_edit_preset(preset_name)
    preset = TIGHT_EDIT_PRESETS[preset_key]
    safe_start = float(clip_start)
    safe_end = float(clip_end)
    base_segment = [(_round_time(safe_start), _round_time(safe_end))]

    if safe_end <= safe_start:
        return {
            "preset": preset_key,
            "remove_ranges": [],
            "keep_segments": [],
            "compacted": False,
            "requires_audio_transcript": False,
            "output_duration": 0.0,
        }

    if not preset.get("enabled"):
        return {
            "preset": preset_key,
            "remove_ranges": [],
            "keep_segments": base_segment,
            "compacted": False,
            "requires_audio_transcript": False,
            "output_duration": _round_time(safe_end - safe_start),
        }

    words = _extract_words(transcript, safe_start, safe_end)
    if not words:
        return {
            "preset": preset_key,
            "remove_ranges": [],
            "keep_segments": base_segment,
            "compacted": False,
            "requires_audio_transcript": False,
            "output_duration": _round_time(safe_end - safe_start),
        }

    remove_ranges: List[RangeTuple] = []
    spoken_words: List[Dict] = []
    max_filler_duration = float(preset["max_filler_duration"])
    filler_padding_before = float(preset["filler_padding_before"])
    filler_padding_after = float(preset["filler_padding_after"])
    min_removed_range = float(preset["min_removed_range"])

    for word in words:
        duration = word["end"] - word["start"]
        is_filler = word["token"] in FILLER_WORDS and duration <= max_filler_duration
        if is_filler:
            start = max(safe_start, word["start"] - filler_padding_before)
            end = min(safe_end, word["end"] + filler_padding_after)
            if end - start >= min_removed_range:
                remove_ranges.append((start, end))
        else:
            spoken_words.append(word)

    if spoken_words:
        edge_keep = float(preset["edge_keep"])
        pause_threshold = float(preset["pause_threshold"])
        pause_after_keep = float(preset["pause_after_keep"])
        pause_before_keep = float(preset["pause_before_keep"])

        leading_gap = spoken_words[0]["start"] - safe_start
        if leading_gap > pause_threshold:
            end = spoken_words[0]["start"] - edge_keep
            if end - safe_start >= min_removed_range:
                remove_ranges.append((safe_start, end))

        for previous, current in zip(spoken_words, spoken_words[1:]):
            gap = current["start"] - previous["end"]
            if gap > pause_threshold:
                start = previous["end"] + pause_after_keep
                end = current["start"] - pause_before_keep
                if end - start >= min_removed_range:
                    remove_ranges.append((start, end))

        trailing_gap = safe_end - spoken_words[-1]["end"]
        if trailing_gap > pause_threshold:
            start = spoken_words[-1]["end"] + edge_keep
            if safe_end - start >= min_removed_range:
                remove_ranges.append((start, safe_end))

    merged_remove_ranges = merge_ranges(remove_ranges)
    keep_segments = invert_ranges(
        safe_start,
        safe_end,
        merged_remove_ranges,
        min_segment_duration=float(preset["min_segment_duration"]),
    )

    if not keep_segments:
        keep_segments = base_segment
        merged_remove_ranges = []

    original_duration = safe_end - safe_start
    if original_duration > MIN_LONG_CLIP_OUTPUT_DURATION:
        keep_segments = _expand_keep_segments_to_min_duration(
            safe_start,
            safe_end,
            keep_segments,
            MIN_LONG_CLIP_OUTPUT_DURATION,
        )
        merged_remove_ranges = _remove_ranges_from_keep_segments(safe_start, safe_end, keep_segments)

    compacted = len(keep_segments) != 1 or keep_segments[0] != base_segment[0]
    output_duration = _sum_range_duration(keep_segments)

    return {
        "preset": preset_key,
        "remove_ranges": merge_ranges(merged_remove_ranges),
        "keep_segments": keep_segments,
        "compacted": compacted,
        "requires_audio_transcript": len(keep_segments) > 1,
        "output_duration": output_duration,
    }


def _has_audio_stream(video_path: str) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        video_path,
    ]
    try:
        output = subprocess.check_output(cmd).decode().strip()
        return bool(output)
    except Exception:
        return False


def render_keep_segments(
    input_video: str,
    keep_segments: Sequence[RangeTuple],
    output_path: str,
    *,
    ffmpeg_preset: str = "fast",
    crf: str = "18",
    audio_bitrate: str = "192k",
    thread_args: Optional[Sequence[str]] = None,
    subprocess_kwargs: Optional[Dict] = None,
) -> None:
    safe_segments = [(float(start), float(end)) for start, end in keep_segments if end > start]
    if not safe_segments:
        raise ValueError("No keep segments provided")

    args = list(thread_args or [])
    run_kwargs = dict(subprocess_kwargs or {})

    if len(safe_segments) == 1:
        start, end = safe_segments[0]
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            input_video,
            *args,
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            ffmpeg_preset,
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            output_path,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **run_kwargs)
        return

    has_audio = _has_audio_stream(input_video)
    filter_parts: List[str] = []
    concat_inputs: List[str] = []

    for index, (start, end) in enumerate(safe_segments):
        filter_parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
        concat_inputs.append(f"[v{index}]")
        if has_audio:
            filter_parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]")
            concat_inputs.append(f"[a{index}]")

    if has_audio:
        filter_parts.append("".join(concat_inputs) + f"concat=n={len(safe_segments)}:v=1:a=1[vout][aout]")
    else:
        filter_parts.append("".join(concat_inputs) + f"concat=n={len(safe_segments)}:v=1:a=0[vout]")

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        input_video,
        *args,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
    ]

    if has_audio:
        cmd.extend(["-map", "[aout]"])

    cmd.extend([
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        ffmpeg_preset,
    ])

    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])

    cmd.extend(["-movflags", "+faststart", output_path])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **run_kwargs)
