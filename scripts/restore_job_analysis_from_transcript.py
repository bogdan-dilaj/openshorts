import argparse
import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional

from job_store import _build_legacy_grouped_clips, _discover_video_files, find_metadata_path, load_job_manifest
from main import MAX_CLIP_DURATION, MAX_LONG_CLIP_DURATION, get_viral_clips


_CLIP_NUMBER_PATTERN = re.compile(r"(?:^|_)(?:clip|short)_(\d+)", re.IGNORECASE)
_FOUND_CLIPS_PATTERN = re.compile(r"Found\s+(\d+)\s+viral clips!", re.IGNORECASE)


def _parse_clip_number(value: Any) -> Optional[int]:
    text = os.path.basename(str(value or ""))
    if not text:
        return None
    match = _CLIP_NUMBER_PATTERN.search(os.path.splitext(text)[0])
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _infer_clip_index(clip: Dict[str, Any], fallback_index: int) -> int:
    direct = clip.get("clip_index")
    if isinstance(direct, int) and direct >= 0:
        return direct

    for key in ("video_filename", "original_video_filename", "base_video_filename", "source_video_filename"):
        clip_number = _parse_clip_number(clip.get(key))
        if clip_number is not None:
            return max(0, clip_number - 1)

    for version in clip.get("versions") or []:
        if not isinstance(version, dict):
            continue
        clip_number = _parse_clip_number(version.get("filename") or version.get("video_filename"))
        if clip_number is not None:
            return max(0, clip_number - 1)

    return fallback_index


def _expected_clip_count_from_log(output_dir: str) -> Optional[int]:
    log_path = os.path.join(output_dir, "job.log")
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, "r", encoding="utf-8") as handle:
            for line in reversed(handle.readlines()):
                match = _FOUND_CLIPS_PATTERN.search(line)
                if match:
                    return int(match.group(1))
    except Exception:
        return None
    return None


def _load_existing_clip_map(metadata_path: Optional[str]) -> Dict[int, Dict[str, Any]]:
    if not metadata_path or not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}

    clip_map: Dict[int, Dict[str, Any]] = {}
    for fallback_index, clip in enumerate(payload.get("shorts") or []):
        if not isinstance(clip, dict):
            continue
        clip_index = _infer_clip_index(clip, fallback_index)
        clip_map[clip_index] = clip
    return clip_map


def _discover_existing_variant_map(output_dir: str, job_id: str) -> Dict[int, Dict[str, Any]]:
    manifest = load_job_manifest(output_dir)
    excluded_filenames: List[str] = []
    source_video = manifest.get("pipeline", {}).get("input_video")
    if source_video:
        excluded_filenames.append(os.path.basename(source_video))

    grouped = _build_legacy_grouped_clips(
        output_dir,
        job_id,
        _discover_video_files(output_dir, excluded_filenames=excluded_filenames),
    )
    variant_map: Dict[int, Dict[str, Any]] = {}
    for fallback_index, clip in enumerate(grouped):
        variant_map[_infer_clip_index(clip, fallback_index)] = clip
    return variant_map


def _merge_existing_fields(target_clip: Dict[str, Any], existing_clip: Dict[str, Any], *, include_text: bool = True) -> Dict[str, Any]:
    merged = dict(target_clip)

    if include_text:
        text_fields = (
            "video_title_for_youtube_short",
            "video_description_for_tiktok",
            "video_description_for_instagram",
            "viral_hook_text",
            "instagram_collaborators",
            "hook_settings",
            "subtitle_settings",
            "social_post_status",
        )
        for field in text_fields:
            if existing_clip.get(field):
                merged[field] = existing_clip[field]

    version_fields = (
        "video_filename",
        "base_video_filename",
        "original_video_filename",
        "source_video_filename",
        "active_version_id",
        "original_version_id",
        "versions",
        "status",
        "display_duration",
        "tight_edit_preset",
        "tight_edit_removed_ranges",
        "transcript_source",
    )
    for field in version_fields:
        if existing_clip.get(field) is not None:
            merged[field] = existing_clip[field]

    return merged


def restore_job_analysis(job_id: str, output_root: str, expected_count: Optional[int] = None) -> str:
    output_dir = os.path.join(output_root, job_id)
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"Job output dir not found: {output_dir}")

    manifest = load_job_manifest(output_dir)
    transcript_path = manifest.get("pipeline", {}).get("transcript_file")
    if not transcript_path or not os.path.exists(transcript_path):
        raise FileNotFoundError(f"Transcript file missing for job {job_id}")

    with open(transcript_path, "r", encoding="utf-8") as handle:
        transcript = json.load(handle)

    provider = manifest.get("provider") or {}
    if provider.get("name"):
        os.environ["LLM_PROVIDER"] = str(provider["name"])
    if provider.get("ollama_base_url"):
        os.environ["OLLAMA_BASE_URL"] = str(provider["ollama_base_url"])
    if provider.get("ollama_model"):
        os.environ["OLLAMA_MODEL"] = str(provider["ollama_model"])

    duration = float(manifest.get("pipeline", {}).get("duration") or 0.0)
    request = manifest.get("request") or {}
    allow_long_clips = bool(request.get("allow_long_clips"))
    max_clips = int(request.get("max_clips") or 100)
    max_clip_duration = MAX_LONG_CLIP_DURATION if allow_long_clips else MAX_CLIP_DURATION

    result = get_viral_clips(
        transcript,
        duration,
        max_clip_duration=max_clip_duration,
        max_clips=max_clips,
    )
    shorts = (result or {}).get("shorts") or []
    if not shorts:
        raise RuntimeError("Analysis recovery returned no clips.")

    expected = expected_count if expected_count is not None else _expected_clip_count_from_log(output_dir)
    if expected is not None and len(shorts) < expected:
        raise RuntimeError(f"Recovered {len(shorts)} clips, expected at least {expected}. Aborting to avoid bad overwrite.")
    if expected is not None and len(shorts) > expected:
        print(f"Recovered {len(shorts)} clips. Trimming to expected {expected}.")
        shorts = shorts[:expected]

    metadata_path = find_metadata_path(output_dir) or os.path.join(output_dir, f"{job_id}_metadata.json")
    existing_clip_map = _load_existing_clip_map(metadata_path)
    existing_variant_map = _discover_existing_variant_map(output_dir, job_id)

    input_video = os.path.basename(manifest.get("pipeline", {}).get("input_video") or "")
    source_input_video = os.path.basename(manifest.get("pipeline", {}).get("source_input_video") or input_video)
    video_title = str(manifest.get("pipeline", {}).get("video_title") or job_id)

    restored_shorts: List[Dict[str, Any]] = []
    for index, clip in enumerate(shorts):
        start = round(float(clip.get("start") or 0.0), 3)
        end = round(float(clip.get("end") or start), 3)
        restored = dict(clip)
        restored["clip_index"] = index
        restored["video_filename"] = restored.get("video_filename") or f"{video_title}_clip_{index + 1}.mp4"
        restored["source_video_filename"] = restored.get("source_video_filename") or input_video
        restored["original_video_filename"] = restored.get("original_video_filename") or source_input_video
        restored["preview_start"] = start
        restored["preview_end"] = end
        restored["display_duration"] = round(max(0.0, end - start), 3)
        restored["status"] = restored.get("status") or "draft"

        merged = restored
        if index in existing_clip_map:
            merged = _merge_existing_fields(merged, existing_clip_map[index])
        if index in existing_variant_map:
            merged = _merge_existing_fields(merged, existing_variant_map[index], include_text=False)

        if merged.get("versions"):
            merged["status"] = merged.get("status") or "completed"
        elif merged.get("status") == "completed":
            merged["status"] = "draft"

        restored_shorts.append(merged)

    payload = {
        "shorts": restored_shorts,
        "transcript": transcript,
        "cost_analysis": result.get("cost_analysis"),
        "generation_mode": "analysis_only",
        "restored_from_transcript": True,
        "restored_at": time.time(),
    }

    if os.path.exists(metadata_path):
        backup_path = f"{metadata_path}.bak_restore_{int(time.time())}"
        shutil.copyfile(metadata_path, backup_path)
        print(f"Backed up previous metadata to {backup_path}")

    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    print(f"Restored {len(restored_shorts)} clips to {metadata_path}")
    return metadata_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore missing analysis clips from an existing job transcript.")
    parser.add_argument("job_id")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--expected-count", type=int, default=None)
    args = parser.parse_args()
    restore_job_analysis(args.job_id, args.output_root, expected_count=args.expected_count)


if __name__ == "__main__":
    main()
