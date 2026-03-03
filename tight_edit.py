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

    compacted = len(keep_segments) != 1 or keep_segments[0] != base_segment[0]
    output_duration = _round_time(sum(end - start for start, end in keep_segments))

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
