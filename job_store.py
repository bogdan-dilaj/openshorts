import glob
import json
import os
import time
from typing import Any, Dict, List, Optional


MANIFEST_FILENAME = "job_manifest.json"
LOG_FILENAME = "job.log"


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, path)


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_manifest_path(output_dir: str) -> str:
    return os.path.join(output_dir, MANIFEST_FILENAME)


def get_log_path(output_dir: str) -> str:
    return os.path.join(output_dir, LOG_FILENAME)


def load_job_manifest(output_dir: str) -> Dict[str, Any]:
    path = get_manifest_path(output_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_job_manifest(output_dir: str, data: Dict[str, Any]) -> Dict[str, Any]:
    manifest = dict(data)
    manifest["updated_at"] = time.time()
    if "created_at" not in manifest:
        manifest["created_at"] = manifest["updated_at"]
    _atomic_write_json(get_manifest_path(output_dir), manifest)
    return manifest


def update_job_manifest(output_dir: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    manifest = load_job_manifest(output_dir)
    merged = _deep_merge(manifest, updates)
    return save_job_manifest(output_dir, merged)


def append_job_log(output_dir: str, line: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    with open(get_log_path(output_dir), "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def read_job_logs(output_dir: str, limit: int = 200) -> List[str]:
    path = get_log_path(output_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]
        if limit <= 0:
            return lines
        return lines[-limit:]
    except Exception:
        return []


def find_metadata_path(output_dir: str) -> Optional[str]:
    matches = sorted(glob.glob(os.path.join(output_dir, "*_metadata.json")))
    return matches[0] if matches else None


def _existing_video_url(output_dir: str, job_id: str, filename: str) -> Optional[str]:
    if not filename:
        return None
    path = os.path.join(output_dir, filename)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return f"/videos/{job_id}/{filename}"
    return None


def _expand_preview_filename_candidates(filename: str) -> List[str]:
    if not filename:
        return []
    base = os.path.basename(filename)
    stem, ext = os.path.splitext(base)
    ext = ext.lower()

    candidates = [base]
    if ext in {".mkv", ".webm", ".avi", ".ts"}:
        candidates.append(f"{stem}_working_h264.mp4")
        candidates.append(f"{stem}.mp4")

    deduped: List[str] = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.basename(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _enrich_clip_versions(output_dir: str, job_id: str, clip: Dict[str, Any]) -> List[Dict[str, Any]]:
    versions: List[Dict[str, Any]] = []
    for index, raw_version in enumerate(clip.get("versions") or []):
        filename = os.path.basename(raw_version.get("filename") or raw_version.get("video_filename") or "")
        if not filename:
            continue
        video_url = _existing_video_url(output_dir, job_id, filename)
        if not video_url:
            continue
        version = dict(raw_version)
        version["id"] = str(version.get("id") or f"v{index}")
        version["version"] = int(version.get("version", index))
        version["filename"] = filename
        version["video_filename"] = filename
        version["video_url"] = video_url
        versions.append(version)
    return versions


def _discover_video_files(output_dir: str, excluded_filenames: Optional[List[str]] = None) -> List[str]:
    excluded = {name for name in (excluded_filenames or []) if name}
    files: List[str] = []
    for path in sorted(glob.glob(os.path.join(output_dir, "*.mp4"))):
        name = os.path.basename(path)
        if name.startswith("temp_"):
            continue
        if name.startswith("input_"):
            continue
        if name in excluded:
            continue
        if os.path.getsize(path) <= 0:
            continue
        files.append(name)
    return files


def build_job_result(output_dir: str, job_id: str) -> Optional[Dict[str, Any]]:
    manifest = load_job_manifest(output_dir)
    excluded_filenames: List[str] = []
    source_video = manifest.get("pipeline", {}).get("input_video")
    if source_video:
        excluded_filenames.append(os.path.basename(source_video))

    metadata_path = find_metadata_path(output_dir)
    if metadata_path:
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")
        clips = data.get("shorts", [])
        ready_clips: List[Dict[str, Any]] = []
        resume_available = False

        for i, clip in enumerate(clips):
            clip_copy = dict(clip)
            status = clip_copy.get("status", "completed")
            if status in {"failed", "pending", "draft"}:
                resume_available = True

            versions = _enrich_clip_versions(output_dir, job_id, clip_copy)
            if versions:
                clip_copy["versions"] = versions
                if clip_copy.get("active_version_id") not in {item["id"] for item in versions}:
                    clip_copy["active_version_id"] = versions[-1]["id"]
                if clip_copy.get("original_version_id") not in {item["id"] for item in versions}:
                    clip_copy["original_version_id"] = versions[0]["id"]

            filename = clip_copy.get("video_filename") or f"{base_name}_clip_{i + 1}.mp4"
            video_url = _existing_video_url(output_dir, job_id, filename)
            if video_url:
                clip_copy["clip_index"] = i
                clip_copy["video_url"] = video_url
                clip_copy["video_filename"] = filename
                ready_clips.append(clip_copy)
                continue

            source_filename = (
                clip_copy.get("preview_video_filename")
                or clip_copy.get("source_video_filename")
                or os.path.basename(manifest.get("pipeline", {}).get("input_video") or "")
                or os.path.basename(manifest.get("pipeline", {}).get("source_input_video") or "")
            )
            preview_url = None
            resolved_preview_filename = ""
            for candidate in _expand_preview_filename_candidates(source_filename):
                maybe_url = _existing_video_url(output_dir, job_id, candidate)
                if maybe_url:
                    preview_url = maybe_url
                    resolved_preview_filename = candidate
                    break
            if preview_url:
                clip_copy["clip_index"] = i
                clip_copy["preview_video_filename"] = resolved_preview_filename or source_filename
                clip_copy["preview_video_url"] = preview_url
                clip_copy["status"] = status or "draft"
                ready_clips.append(clip_copy)

        fallback_filename = data.get("fallback_output")
        if not ready_clips and fallback_filename:
            fallback_url = _existing_video_url(output_dir, job_id, fallback_filename)
            if fallback_url:
                ready_clips.append({
                    "clip_index": 0,
                    "start": 0,
                    "end": 0,
                    "video_title_for_youtube_short": os.path.splitext(fallback_filename)[0].replace("_", " "),
                    "video_description_for_tiktok": "Fallback vertical render",
                    "video_description_for_instagram": "Fallback vertical render",
                    "video_filename": fallback_filename,
                    "video_url": fallback_url,
                    "status": "completed",
                })

        if ready_clips:
            return {
                "clips": ready_clips,
                "cost_analysis": data.get("cost_analysis"),
                "generation_mode": data.get("generation_mode", "clips"),
                "job_overlay_defaults": data.get("job_overlay_defaults"),
                "resume_available": resume_available,
            }

    video_files = _discover_video_files(output_dir, excluded_filenames=excluded_filenames)
    if not video_files:
        return None

    clips = []
    for i, filename in enumerate(video_files):
        label = os.path.splitext(filename)[0].replace("_", " ")
        clips.append({
            "clip_index": i,
            "start": 0,
            "end": 0,
            "video_title_for_youtube_short": label,
            "video_description_for_tiktok": "Generated video",
            "video_description_for_instagram": "Generated video",
            "video_filename": filename,
            "video_url": f"/videos/{job_id}/{filename}",
            "status": "completed",
        })

    return {
        "clips": clips,
        "cost_analysis": None,
        "generation_mode": "legacy",
        "job_overlay_defaults": None,
        "resume_available": False,
    }


def _estimate_clip_count(output_dir: str) -> int:
    metadata_path = find_metadata_path(output_dir)
    if metadata_path:
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            shorts = data.get("shorts")
            if isinstance(shorts, list):
                return len(shorts)
        except Exception:
            pass
    # Fallback: count discoverable output videos without loading full clip metadata.
    return len(_discover_video_files(output_dir))


def _build_job_summary(
    output_root: str,
    job_id: str,
    include_result: bool = True,
    include_logs: bool = True,
    log_limit: int = 80,
) -> Optional[Dict[str, Any]]:
    output_dir = os.path.join(output_root, job_id)
    if not os.path.isdir(output_dir):
        return None

    manifest = load_job_manifest(output_dir)
    result = build_job_result(output_dir, job_id) if include_result else None
    clip_count = len((result or {}).get("clips") or []) if result else _estimate_clip_count(output_dir)

    if not manifest and not result and clip_count <= 0:
        return None

    status = manifest.get("status", "completed" if (result or clip_count > 0) else "failed")
    updated_at = manifest.get("updated_at", os.path.getmtime(output_dir))
    created_at = manifest.get("created_at", updated_at)
    request = manifest.get("request", {})
    source_label = (
        request.get("display_name")
        or request.get("original_filename")
        or request.get("url")
        or job_id
    )

    can_resume = (
        status not in {"queued", "processing"}
        and (
            bool(manifest.get("can_resume"))
            or bool(result and result.get("resume_available"))
            or status in {"failed", "partial", "cancelled"}
        )
    )

    return {
        "job_id": job_id,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "source_label": source_label,
        "clip_count": clip_count,
        "request": request,
        "provider": manifest.get("provider", {}),
        "error": manifest.get("error"),
        "can_resume": can_resume,
        "generation_mode": (result or {}).get("generation_mode"),
        "result": result if include_result else None,
        "logs": read_job_logs(output_dir, limit=log_limit) if include_logs else [],
    }


def get_job_summary(output_root: str, job_id: str) -> Optional[Dict[str, Any]]:
    return _build_job_summary(output_root, job_id)


def list_job_summaries(
    output_root: str,
    limit: int = 50,
    include_result: bool = False,
    include_logs: bool = True,
    log_limit: int = 40,
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    if not os.path.isdir(output_root):
        return summaries

    candidates: List[tuple[float, str]] = []
    for name in os.listdir(output_root):
        if name == "thumbnails":
            continue
        output_dir = os.path.join(output_root, name)
        if not os.path.isdir(output_dir):
            continue
        try:
            candidates.append((os.path.getmtime(output_dir), name))
        except Exception:
            candidates.append((0.0, name))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if limit > 0:
        candidates = candidates[:limit]

    for _, name in candidates:
        summary = _build_job_summary(
            output_root,
            name,
            include_result=include_result,
            include_logs=include_logs,
            log_limit=log_limit,
        )
        if summary:
            summaries.append(summary)

    summaries.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return summaries
