import os
import uuid
import subprocess
import threading
import json
import shutil
import glob
import time
import asyncio
import signal
import difflib
import re
import tempfile
import urllib.request
import urllib.error
from dotenv import load_dotenv
from typing import Any, Dict, Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from s3_uploader import upload_job_artifacts, list_all_clips
from job_store import (
    append_job_log,
    build_job_result,
    get_job_summary,
    list_job_summaries,
    load_job_manifest,
    read_job_logs,
    update_job_manifest,
)
from runtime_limits import MAX_CONCURRENT_JOBS, ffmpeg_thread_args, subprocess_priority_kwargs

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Configuration
MAX_FILE_SIZE_MB = 2048  # 2GB limit
JOB_RETENTION_SECONDS = int(os.environ.get("JOB_RETENTION_SECONDS", str(7 * 24 * 3600)))

# Application State
job_queue = asyncio.Queue()
jobs: Dict[str, Dict] = {}
thumbnail_sessions: Dict[str, Dict] = {}
publish_jobs: Dict[str, Dict] = {}  # {publish_id: {status, result, error}}
# Semester to limit concurrency to MAX_CONCURRENT_JOBS
concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_METADATA_UNSET = object()

def _relocate_root_job_artifacts(job_id: str, job_output_dir: str) -> bool:
    """
    Backward-compat rescue:
    If main.py accidentally wrote metadata/clips into OUTPUT_DIR root (e.g. output/<jobid>_...),
    move them into output/<job_id>/ so the API can find and serve them.
    """
    try:
        os.makedirs(job_output_dir, exist_ok=True)
        root = OUTPUT_DIR
        pattern = os.path.join(root, f"{job_id}_*_metadata.json")
        meta_candidates = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
        if not meta_candidates:
            return False

        # Move the newest metadata and its associated clips.
        metadata_path = meta_candidates[0]
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")

        # Move metadata
        dest_metadata = os.path.join(job_output_dir, os.path.basename(metadata_path))
        if os.path.abspath(metadata_path) != os.path.abspath(dest_metadata):
            shutil.move(metadata_path, dest_metadata)

        # Move any clips that match the same base_name into the job folder
        clip_pattern = os.path.join(root, f"{base_name}_clip_*.mp4")
        for clip_path in glob.glob(clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        # Also move any temp_ clips that might remain
        temp_clip_pattern = os.path.join(root, f"temp_{base_name}_clip_*.mp4")
        for clip_path in glob.glob(temp_clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        return True
    except Exception:
        return False


def _job_state_to_api_status(job_state: str) -> str:
    if job_state in {"completed", "partial"}:
        return "completed"
    if job_state == "failed":
        return "failed"
    if job_state == "cancelled":
        return "cancelled"
    if job_state in {"queued", "processing"}:
        return job_state
    return "failed"


def _load_job_from_disk(job_id: str) -> Optional[Dict]:
    summary = get_job_summary(OUTPUT_DIR, job_id)
    if not summary:
        return None
    return {
        "status": _job_state_to_api_status(summary["status"]),
        "job_state": summary["status"],
        "logs": summary.get("logs", []),
        "result": summary.get("result"),
        "error": summary.get("error"),
        "can_resume": summary.get("can_resume", False),
    }


def _get_job_output_dir(job_id: str) -> str:
    return os.path.join(OUTPUT_DIR, job_id)


def _get_job_record_or_404(job_id: str) -> Dict:
    job = jobs.get(job_id)
    if not job:
        job = _load_job_from_disk(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _get_job_result_or_400(job_id: str):
    job = _get_job_record_or_404(job_id)
    output_dir = _get_job_output_dir(job_id)
    result = job.get("result") or build_job_result(output_dir, job_id)
    if result and job_id in jobs:
        jobs[job_id]["result"] = result
    if not result or "clips" not in result:
        raise HTTPException(status_code=400, detail="Job result not available")
    return job, result, output_dir


def _find_result_clip(result: Dict, clip_index: int) -> Dict:
    clips = result.get("clips", [])
    for clip in clips:
        if clip.get("clip_index") == clip_index:
            return clip
    if 0 <= clip_index < len(clips):
        return clips[clip_index]
    raise HTTPException(status_code=404, detail="Clip not found")


def _load_job_metadata_or_404(job_id: str):
    output_dir = _get_job_output_dir(job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")
    metadata_path = json_files[0]
    with open(metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return output_dir, metadata_path, data


def _refresh_job_result(job_id: str):
    result = build_job_result(_get_job_output_dir(job_id), job_id)
    if job_id in jobs and result:
        jobs[job_id]["result"] = result
        jobs[job_id]["can_resume"] = bool(result.get("resume_available")) or jobs[job_id].get("can_resume", False)
    return result


def _write_metadata(metadata_path: str, data: Dict[str, Any]) -> None:
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _clip_video_url(job_id: str, filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    return f"/videos/{job_id}/{os.path.basename(filename)}"


def _strip_overlay_prefixes(filename: Optional[str]) -> Optional[str]:
    current = os.path.basename(filename or "")
    pattern = re.compile(r"^(?:hook|subtitled|edited|translated|trimmed)_\d+_(.+)$")
    seen = set()

    while current and current not in seen:
        seen.add(current)
        match = pattern.match(current)
        if not match:
            break
        current = match.group(1)

    return current or None


def _infer_version_operation(filename: Optional[str]) -> str:
    name = os.path.basename(filename or "").lower()
    if name.startswith("subtitled_"):
        return "subtitle"
    if name.startswith("hook_"):
        return "hook"
    if name.startswith("edited_"):
        return "edit"
    if name.startswith("translated_"):
        return "translate"
    if name.startswith("trimmed_"):
        return "trim"
    return "original"


def _operation_label(operation: str) -> str:
    return {
        "original": "Original",
        "subtitle": "Subtitles",
        "hook": "Hook",
        "edit": "Auto Edit",
        "translate": "Dub",
        "trim": "Trim",
    }.get(operation, operation.replace("_", " ").title())


def _default_transcript_source(operation: str) -> str:
    return "audio" if operation in {"translate", "edit"} else "original"


def _format_time_label(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _existing_clip_filenames(output_dir: str, clip: Dict[str, Any]) -> List[str]:
    candidates = [
        clip.get("original_video_filename"),
        clip.get("base_video_filename"),
        _strip_overlay_prefixes(clip.get("video_filename")),
        clip.get("video_filename"),
    ]
    seen = set()
    filenames: List[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        name = os.path.basename(candidate)
        if name in seen:
            continue
        seen.add(name)
        if os.path.exists(os.path.join(output_dir, name)):
            filenames.append(name)
    if not filenames:
        fallback = os.path.basename(clip.get("video_filename") or "")
        if fallback:
            filenames.append(fallback)
    return filenames


def _normalize_clip_version(
    job_id: str,
    clip: Dict[str, Any],
    version: Dict[str, Any],
    *,
    version_number: int,
) -> Optional[Dict[str, Any]]:
    filename = os.path.basename(version.get("filename") or version.get("video_filename") or "")
    if not filename:
        return None

    operation = version.get("operation") or _infer_version_operation(filename)
    transcript_source = version.get("transcript_source") or _default_transcript_source(operation)
    normalized = dict(version)
    normalized["id"] = str(version.get("id") or f"v{version_number}")
    normalized["version"] = int(version.get("version", version_number))
    normalized["filename"] = filename
    normalized["video_filename"] = filename
    normalized["video_url"] = _clip_video_url(job_id, filename)
    normalized["operation"] = operation
    normalized["label"] = version.get("label") or _operation_label(operation)
    normalized["created_at"] = float(version.get("created_at") or time.time())
    normalized["transcript_source"] = transcript_source

    if transcript_source == "original":
        clip_start = float(clip.get("start") or 0.0)
        clip_end = float(clip.get("end") or clip_start)
        normalized["transcript_start"] = float(version.get("transcript_start", clip_start))
        normalized["transcript_end"] = float(version.get("transcript_end", clip_end))
        if normalized["transcript_end"] < normalized["transcript_start"]:
            normalized["transcript_end"] = normalized["transcript_start"]
    else:
        normalized.pop("transcript_start", None)
        normalized.pop("transcript_end", None)

    return normalized


def _sync_clip_variant_fields(job_id: str, clip: Dict[str, Any]) -> Dict[str, Any]:
    versions = clip.get("versions") or []
    if not versions:
        return clip

    active_version_id = clip.get("active_version_id")
    active_version = next((item for item in versions if item.get("id") == active_version_id), None) or versions[-1]
    original_version_id = clip.get("original_version_id")
    original_version = (
        next((item for item in versions if item.get("id") == original_version_id), None)
        or next((item for item in versions if item.get("operation") == "original"), None)
        or versions[0]
    )

    clip["active_version_id"] = active_version["id"]
    clip["original_version_id"] = original_version["id"]
    clip["video_filename"] = active_version["filename"]
    clip["video_url"] = active_version["video_url"]
    clip["base_video_filename"] = original_version["filename"]
    clip["base_video_url"] = original_version["video_url"]
    clip["original_video_filename"] = original_version["filename"]
    clip["original_video_url"] = original_version["video_url"]
    clip["status"] = "completed"
    clip.pop("error", None)
    return clip


def _ensure_clip_versions(job_id: str, output_dir: str, clip: Dict[str, Any]) -> bool:
    changed = False
    existing_versions = clip.get("versions")

    if not existing_versions:
        filenames = _existing_clip_filenames(output_dir, clip)
        current_filename = os.path.basename(clip.get("video_filename") or filenames[-1])
        versions = []
        for index, filename in enumerate(filenames):
            operation = "original" if index == 0 else _infer_version_operation(filename)
            version = _normalize_clip_version(
                job_id,
                clip,
                {
                    "id": f"v{index}",
                    "version": index,
                    "filename": filename,
                    "operation": operation,
                    "label": "Original" if index == 0 else _operation_label(operation),
                    "transcript_source": _default_transcript_source(operation),
                },
                version_number=index,
            )
            if version:
                versions.append(version)

        if versions:
            clip["versions"] = versions
            active_version = next((item for item in versions if item["filename"] == current_filename), versions[-1])
            clip["active_version_id"] = active_version["id"]
            clip["original_version_id"] = versions[0]["id"]
            changed = True
    else:
        normalized_versions = []
        seen_filenames = set()
        for index, raw_version in enumerate(existing_versions):
            version = _normalize_clip_version(job_id, clip, raw_version, version_number=index)
            if not version:
                changed = True
                continue
            if version["filename"] in seen_filenames:
                changed = True
                continue
            seen_filenames.add(version["filename"])
            normalized_versions.append(version)

        if normalized_versions != existing_versions:
            clip["versions"] = normalized_versions
            changed = True

        if normalized_versions:
            if clip.get("active_version_id") not in {item["id"] for item in normalized_versions}:
                active_by_filename = next(
                    (item for item in normalized_versions if item["filename"] == os.path.basename(clip.get("video_filename") or "")),
                    None,
                )
                clip["active_version_id"] = (active_by_filename or normalized_versions[-1])["id"]
                changed = True

            if clip.get("original_version_id") not in {item["id"] for item in normalized_versions}:
                clip["original_version_id"] = next(
                    (item["id"] for item in normalized_versions if item["operation"] == "original"),
                    normalized_versions[0]["id"],
                )
                changed = True

    if clip.get("versions"):
        _sync_clip_variant_fields(job_id, clip)

    return changed


def _find_clip_version(clip: Dict[str, Any], *, version_id: Optional[str] = None, filename: Optional[str] = None) -> Optional[Dict[str, Any]]:
    versions = clip.get("versions") or []
    if version_id:
        for version in versions:
            if version.get("id") == version_id:
                return version
    if filename:
        safe_name = os.path.basename(filename)
        for version in versions:
            if version.get("filename") == safe_name:
                return version
    active_version_id = clip.get("active_version_id")
    return next((version for version in versions if version.get("id") == active_version_id), None) or (versions[-1] if versions else None)


def _find_original_clip_version(clip: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return (
        _find_clip_version(clip, version_id=clip.get("original_version_id"))
        or next((version for version in clip.get("versions", []) if version.get("operation") == "original"), None)
        or (clip.get("versions") or [None])[0]
    )


def _append_clip_version(
    job_id: str,
    output_dir: str,
    clip: Dict[str, Any],
    *,
    output_filename: str,
    operation: str,
    label: Optional[str] = None,
    transcript_source: Optional[str] = None,
    transcript_start: Optional[float] = None,
    transcript_end: Optional[float] = None,
    subtitle_settings: Any = _METADATA_UNSET,
    hook_settings: Any = _METADATA_UNSET,
) -> Dict[str, Any]:
    _ensure_clip_versions(job_id, output_dir, clip)
    versions = clip.setdefault("versions", [])
    next_version_number = max((int(item.get("version", 0)) for item in versions), default=-1) + 1
    version = _normalize_clip_version(
        job_id,
        clip,
        {
            "id": f"v{next_version_number}",
            "version": next_version_number,
            "filename": os.path.basename(output_filename),
            "operation": operation,
            "label": label or _operation_label(operation),
            "transcript_source": transcript_source or _default_transcript_source(operation),
            "transcript_start": transcript_start,
            "transcript_end": transcript_end,
            "created_at": time.time(),
        },
        version_number=next_version_number,
    )
    versions.append(version)
    clip["active_version_id"] = version["id"]

    if subtitle_settings is not _METADATA_UNSET:
        if subtitle_settings:
            clip["subtitle_settings"] = subtitle_settings
        else:
            clip.pop("subtitle_settings", None)

    if hook_settings is not _METADATA_UNSET:
        if hook_settings:
            clip["hook_settings"] = hook_settings
        else:
            clip.pop("hook_settings", None)

    _sync_clip_variant_fields(job_id, clip)
    return version


def _select_clip_version(clip: Dict[str, Any], version_id: str) -> Dict[str, Any]:
    version = _find_clip_version(clip, version_id=version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Clip version not found")
    clip["active_version_id"] = version["id"]
    return version


def _probe_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.check_output(cmd).decode().strip()
    return max(0.0, float(result))


def _build_subtitle_settings(req, clip_data: Dict) -> Optional[Dict]:
    existing = clip_data.get("subtitle_settings")
    alignment = req.position or (existing or {}).get("position") or "bottom"
    font_size = req.font_size or (existing or {}).get("font_size") or 16
    font_family = req.font_family or (existing or {}).get("font_family")
    background_style = req.background_style or (existing or {}).get("background_style")
    y_position = req.y_position if req.y_position is not None else (existing or {}).get("y_position")

    return {
        "position": alignment,
        "y_position": y_position,
        "font_size": int(font_size),
        "font_family": font_family,
        "background_style": background_style,
    }


def _build_hook_settings(req, clip_data: Dict) -> Optional[Dict]:
    existing = clip_data.get("hook_settings")
    text = (req.text or "").strip() if hasattr(req, "text") else (existing or {}).get("text", "").strip()
    if not text:
        return None

    return {
        "text": text,
        "position": req.position or (existing or {}).get("position") or "top",
        "horizontal_position": req.horizontal_position or (existing or {}).get("horizontal_position") or "center",
        "x_position": req.x_position if req.x_position is not None else (existing or {}).get("x_position"),
        "y_position": req.y_position if req.y_position is not None else (existing or {}).get("y_position"),
        "text_align": req.text_align or (existing or {}).get("text_align") or "center",
        "size": req.size or (existing or {}).get("size") or "M",
        "width_preset": req.width_preset or (existing or {}).get("width_preset") or "wide",
        "font_family": req.font_family or (existing or {}).get("font_family"),
        "background_style": req.background_style or (existing or {}).get("background_style"),
    }


def _render_subtitle_and_hook_stack(
    *,
    output_dir: str,
    base_input_path: str,
    clip_data: Dict,
    transcript: Dict,
    final_output_path: str,
    subtitle_settings: Optional[Dict],
    hook_settings: Optional[Dict],
):
    current_input = base_input_path
    temp_paths = []

    try:
        if subtitle_settings:
            subtitle_output_path = final_output_path
            if hook_settings:
                temp_handle = tempfile.NamedTemporaryFile(
                    prefix="openshorts_subtitle_stack_",
                    suffix=".mp4",
                    dir="/tmp",
                    delete=False,
                )
                temp_handle.close()
                subtitle_output_path = temp_handle.name
                temp_paths.append(subtitle_output_path)

            is_dubbed = os.path.basename(base_input_path).startswith("translated_")
            subtitle_transcript = transcript
            if is_dubbed:
                subtitle_transcript = transcribe_audio(base_input_path)

            success = burn_subtitles(
                current_input,
                subtitle_transcript,
                0 if is_dubbed else clip_data["start"],
                clip_data["end"] - clip_data["start"] if is_dubbed else clip_data["end"],
                subtitle_output_path,
                alignment=subtitle_settings.get("position", "bottom"),
                y_position=subtitle_settings.get("y_position"),
                fontsize=subtitle_settings.get("font_size", 16),
                font_family=subtitle_settings.get("font_family"),
                background_style=subtitle_settings.get("background_style"),
            )
            if not success:
                raise HTTPException(status_code=400, detail="No words found for this clip range.")
            current_input = subtitle_output_path

        if hook_settings:
            size_map = {"S": 0.8, "M": 1.0, "L": 1.3}
            add_hook_to_video(
                current_input,
                hook_settings["text"],
                final_output_path,
                position=hook_settings.get("position", "top"),
                horizontal_position=hook_settings.get("horizontal_position", "center"),
                x_position=hook_settings.get("x_position"),
                y_position=hook_settings.get("y_position"),
                text_align=hook_settings.get("text_align", "center"),
                font_scale=size_map.get(hook_settings.get("size"), 1.0),
                width_preset=hook_settings.get("width_preset", "wide"),
                font_name=hook_settings.get("font_family"),
                background_style=hook_settings.get("background_style"),
            )
        elif not subtitle_settings:
            raise HTTPException(status_code=400, detail="No overlays configured for this clip.")
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_max_clips(value, default: int = 10, minimum: int = 1, maximum: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _normalize_ollama_base_url(base_url: Optional[str]) -> str:
    return (base_url or "http://127.0.0.1:11434").strip().rstrip("/")


def _normalize_ollama_model_name(model_name: Optional[str]) -> str:
    normalized = (model_name or "").strip()
    alias_map = {
        "gemma-3-12b": "gemma3:12b",
        "gemma-3-12b:latest": "gemma3:12b",
        "gemma3-12b": "gemma3:12b",
        "gemma3-12b:latest": "gemma3:12b",
    }
    return alias_map.get(normalized.lower(), normalized)


def _list_ollama_models(base_url: str) -> List[str]:
    req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [model.get("name") for model in payload.get("models", []) if model.get("name")]


def _resolve_ollama_model_name(installed_models: List[str], requested_model: str) -> Optional[str]:
    if requested_model in installed_models:
        return requested_model

    lower_map = {name.lower(): name for name in installed_models}
    exact_lower = lower_map.get(requested_model.lower())
    if exact_lower:
        return exact_lower

    if ":" not in requested_model:
        prefixed = [
            name for name in installed_models
            if name == f"{requested_model}:latest" or name.startswith(f"{requested_model}:")
        ]
        if len(prefixed) == 1:
            return prefixed[0]

    if requested_model.endswith(":latest"):
        without_latest = requested_model[:-7]
        if without_latest in installed_models:
            return without_latest

    return None


def _validate_ollama_model_or_raise(base_url: Optional[str], model_name: Optional[str]) -> tuple[str, str]:
    normalized_base_url = _normalize_ollama_base_url(base_url)
    normalized_model_name = _normalize_ollama_model_name(model_name)

    if not normalized_model_name:
        raise HTTPException(status_code=400, detail="Missing X-Ollama-Model header")

    try:
        installed_models = _list_ollama_models(normalized_base_url)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to query Ollama models at {normalized_base_url}: HTTP {exc.code} {body or exc.reason}",
        )
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach Ollama at {normalized_base_url}: {exc.reason}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to query Ollama models at {normalized_base_url}: {exc}",
        )

    resolved_model_name = _resolve_ollama_model_name(installed_models, normalized_model_name)
    if resolved_model_name:
        return normalized_base_url, resolved_model_name

    suggestions = difflib.get_close_matches(normalized_model_name, installed_models, n=3, cutoff=0.45)
    suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    installed_text = ", ".join(installed_models[:10]) if installed_models else "none"
    raise HTTPException(
        status_code=400,
        detail=(
            f"Ollama model '{normalized_model_name}' is not installed at {normalized_base_url}."
            f"{suggestion_text} Installed models: {installed_text}"
        ),
    )


def _terminate_job_process(job: Dict, force: bool = False) -> bool:
    process = job.get("process")
    if not process or process.poll() is not None:
        return False

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(process.pid, sig)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        try:
            if force:
                process.kill()
            else:
                process.terminate()
            return True
        except Exception:
            return False


def _mark_job_cancelled(job_id: str, output_dir: str, message: str = "Job cancelled by user.") -> Dict:
    result = build_job_result(output_dir, job_id)
    if job_id in jobs:
        jobs[job_id]["status"] = "cancelled"
        jobs[job_id]["job_state"] = "cancelled"
        jobs[job_id]["error"] = message
        jobs[job_id]["can_resume"] = True
        jobs[job_id]["result"] = result
    update_job_manifest(output_dir, {
        "status": "cancelled",
        "error": message,
        "can_resume": True,
    })
    return {
        "status": "cancelled",
        "logs": jobs.get(job_id, {}).get("logs", read_job_logs(output_dir, limit=200)),
        "result": result,
        "job_state": "cancelled",
        "error": message,
        "can_resume": True,
    }

async def cleanup_jobs():
    """Background task to remove old jobs and files."""
    import time
    print("🧹 Cleanup task started.")
    while True:
        try:
            await asyncio.sleep(300) # Check every 5 minutes
            now = time.time()
            
            # Simple directory cleanup based on modification time
            # Check OUTPUT_DIR
            for job_id in os.listdir(OUTPUT_DIR):
                job_path = os.path.join(OUTPUT_DIR, job_id)
                if os.path.isdir(job_path):
                    if now - os.path.getmtime(job_path) > JOB_RETENTION_SECONDS:
                        print(f"🧹 Purging old job: {job_id}")
                        shutil.rmtree(job_path, ignore_errors=True)
                        if job_id in jobs:
                            del jobs[job_id]

            # Cleanup Uploads
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    if now - os.path.getmtime(file_path) > JOB_RETENTION_SECONDS:
                         os.remove(file_path)
                except Exception: pass

        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")

async def process_queue():
    """Background worker to process jobs from the queue with concurrency limit."""
    print(f"🚀 Job Queue Worker started with {MAX_CONCURRENT_JOBS} concurrent slots.")
    while True:
        try:
            # Wait for a job
            job_item = await job_queue.get()
            if isinstance(job_item, (list, tuple)):
                job_id, queue_token = job_item[0], job_item[1]
            else:
                job_id, queue_token = job_item, None
            job = jobs.get(job_id)
            if queue_token and job and job.get("queue_token") != queue_token:
                print(f"⏭️ Skipping stale queue entry for job: {job_id}")
                job_queue.task_done()
                continue
            if job and (job.get("cancel_requested") or job.get("status") == "cancelled"):
                print(f"⏹️ Skipping cancelled queued job: {job_id}")
                job_queue.task_done()
                continue
            
            # Acquire semaphore slot (waits if max jobs are running)
            await concurrency_semaphore.acquire()
            job = jobs.get(job_id)
            if not job:
                concurrency_semaphore.release()
                job_queue.task_done()
                continue
            if queue_token and job.get("queue_token") != queue_token:
                print(f"⏭️ Skipping stale dequeued entry for job: {job_id}")
                concurrency_semaphore.release()
                job_queue.task_done()
                continue
            if job.get("cancel_requested") or job.get("status") == "cancelled":
                print(f"⏹️ Skipping cancelled dequeued job: {job_id}")
                concurrency_semaphore.release()
                job_queue.task_done()
                continue
            print(f"🔄 Acquired slot for job: {job_id}")

            # Process in background task to not block the loop (allowing other slots to fill)
            asyncio.create_task(run_job_wrapper(job_id, queue_token))
            
        except Exception as e:
            print(f"❌ Queue dispatch error: {e}")
            await asyncio.sleep(1)

async def run_job_wrapper(job_id, queue_token=None):
    """Wrapper to run job and release semaphore"""
    try:
        job = jobs.get(job_id)
        if job:
            await run_job(job_id, job, queue_token)
    except Exception as e:
         print(f"❌ Job wrapper error {job_id}: {e}")
    finally:
        # Always release semaphore and mark queue task done
        concurrency_semaphore.release()
        job_queue.task_done()
        print(f"✅ Released slot for job: {job_id}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start worker and cleanup
    worker_task = asyncio.create_task(process_queue())
    cleanup_task = asyncio.create_task(cleanup_jobs())
    yield
    # Cleanup (optional: cancel worker)

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for serving videos
app.mount("/videos", StaticFiles(directory=OUTPUT_DIR), name="videos")

# Mount static files for serving thumbnails
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

class ProcessRequest(BaseModel):
    url: str


class ResumeJobRequest(BaseModel):
    provider: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None

def enqueue_output(out, job_id, output_dir):
    """Reads output from a subprocess and appends it to jobs logs."""
    try:
        for line in iter(out.readline, b''):
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                print(f"📝 [Job Output] {decoded_line}")
                append_job_log(output_dir, decoded_line)
                if job_id in jobs:
                    jobs[job_id]['logs'].append(decoded_line)
    except Exception as e:
        print(f"Error reading output for job {job_id}: {e}")
    finally:
        out.close()

async def run_job(job_id, job_data, queue_token=None):
    """Executes the subprocess for a specific job."""
    if queue_token and job_data.get("queue_token") != queue_token:
        print(f"⏭️ Not starting stale job {job_id}")
        return
    if job_data.get("cancel_requested") or job_data.get("status") == "cancelled":
        print(f"⏹️ Not starting cancelled job {job_id}")
        return

    cmd = job_data['cmd']
    env = job_data['env']
    output_dir = job_data['output_dir']
    
    jobs[job_id]['status'] = 'processing'
    jobs[job_id]['job_state'] = 'processing'
    jobs[job_id]['logs'].append("Job started by worker.")
    update_job_manifest(output_dir, {
        "status": "processing",
        "error": None,
        "can_resume": True,
    })
    print(f"🎬 [run_job] Executing command for {job_id}: {' '.join(cmd)}")
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr to stdout
            env=env,
            cwd=os.getcwd(),
            start_new_session=True,
            **subprocess_priority_kwargs(),
        )
        jobs[job_id]['process'] = process
        
        # We need to capture logs in a thread because Popen isn't async
        t_log = threading.Thread(target=enqueue_output, args=(process.stdout, job_id, output_dir))
        t_log.daemon = True
        t_log.start()
        
        # Async wait for process with incremental updates
        while process.poll() is None:
            if jobs[job_id].get("cancel_requested"):
                if not jobs[job_id].get("terminate_sent_at"):
                    jobs[job_id]["terminate_sent_at"] = time.time()
                    _terminate_job_process(jobs[job_id], force=False)
                elif time.time() - jobs[job_id]["terminate_sent_at"] > 10:
                    _terminate_job_process(jobs[job_id], force=True)
                await asyncio.sleep(2)
                continue

            await asyncio.sleep(2)
            
            # Check for partial results every 2 seconds
            try:
                result = build_job_result(output_dir, job_id)
                if result:
                    jobs[job_id]['result'] = result
            except Exception as e:
                # Ignore read errors during processing
                pass

        returncode = process.returncode
        t_log.join(timeout=1)

        if jobs[job_id].get("cancel_requested"):
            jobs[job_id]['logs'].append("Process cancelled.")
            append_job_log(output_dir, "Process cancelled.")
            _mark_job_cancelled(job_id, output_dir)
            return
        
        if returncode == 0:
            # Start S3 upload in background (silent, non-blocking)
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, upload_job_artifacts, output_dir, job_id)

            if not build_job_result(output_dir, job_id):
                # Backward-compat rescue if outputs were written to OUTPUT_DIR root
                _relocate_root_job_artifacts(job_id, output_dir)

            summary = get_job_summary(OUTPUT_DIR, job_id)
            if summary and summary.get("result"):
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['job_state'] = summary['status']
                jobs[job_id]['result'] = summary['result']
                jobs[job_id]['can_resume'] = summary.get('can_resume', False)
                jobs[job_id]['error'] = summary.get('error')
                jobs[job_id]['logs'].append("Process finished successfully.")
                if summary['status'] == 'partial':
                    jobs[job_id]['logs'].append("Some clips failed, but resumable outputs are available.")
            else:
                jobs[job_id]['status'] = 'failed'
                jobs[job_id]['job_state'] = 'failed'
                jobs[job_id]['can_resume'] = True
                jobs[job_id]['logs'].append("No usable output files were generated.")
                update_job_manifest(output_dir, {
                    "status": "failed",
                    "error": "No usable output files were generated.",
                    "can_resume": True,
                })
        else:
            summary = get_job_summary(OUTPUT_DIR, job_id)
            if summary and summary.get("result"):
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['job_state'] = summary['status']
                jobs[job_id]['result'] = summary['result']
                jobs[job_id]['can_resume'] = True
                jobs[job_id]['error'] = f"Process exited with code {returncode}, but usable outputs are available."
                jobs[job_id]['logs'].append(f"Process exited with code {returncode}, but usable outputs were recovered.")
                update_job_manifest(output_dir, {
                    "status": "partial",
                    "error": f"Process exited with code {returncode}, but usable outputs are available.",
                    "can_resume": True,
                })
            else:
                jobs[job_id]['status'] = 'failed'
                jobs[job_id]['job_state'] = 'failed'
                jobs[job_id]['can_resume'] = True
                jobs[job_id]['logs'].append(f"Process failed with exit code {returncode}")
                update_job_manifest(output_dir, {
                    "status": "failed",
                    "error": f"Process failed with exit code {returncode}",
                    "can_resume": True,
                })
            
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['job_state'] = 'failed'
        jobs[job_id]['can_resume'] = True
        jobs[job_id]['logs'].append(f"Execution error: {str(e)}")
        update_job_manifest(output_dir, {
            "status": "failed",
            "error": str(e),
            "can_resume": True,
        })
    finally:
        if job_id in jobs:
            jobs[job_id].pop("process", None)
            jobs[job_id].pop("terminate_sent_at", None)

@app.post("/api/process")
async def process_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    interview_mode: Optional[str] = Form(None),
    allow_long_clips: Optional[str] = Form(None),
    max_clips: Optional[str] = Form(None),
):
    provider = (request.headers.get("X-LLM-Provider") or "gemini").strip().lower()
    api_key = request.headers.get("X-Gemini-Key")
    ollama_base_url = request.headers.get("X-Ollama-Base-Url")
    ollama_model = request.headers.get("X-Ollama-Model")

    if provider == "gemini" and not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")
    if provider == "ollama":
        ollama_base_url, ollama_model = _validate_ollama_model_or_raise(ollama_base_url, ollama_model)
    
    # Handle JSON body manually for URL payload
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        url = body.get("url")
        interview_mode = body.get("interview_mode")
        allow_long_clips = body.get("allow_long_clips")
        max_clips = body.get("max_clips")

    interview_mode_enabled = _coerce_bool(interview_mode)
    allow_long_clips_enabled = _coerce_bool(allow_long_clips)
    max_clips_value = _coerce_max_clips(max_clips)
    
    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    job_id = str(uuid.uuid4())
    queue_token = uuid.uuid4().hex
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)
    request_meta = {
        "type": "url" if url else "file",
        "url": url,
        "display_name": url or getattr(file, "filename", None),
        "interview_mode": interview_mode_enabled,
        "allow_long_clips": allow_long_clips_enabled,
        "max_clips": max_clips_value,
    }
    
    # Prepare Command
    cmd = ["python", "-u", "main.py"] # -u for unbuffered
    env = os.environ.copy()
    env["LLM_PROVIDER"] = provider
    if api_key:
        env["GEMINI_API_KEY"] = api_key
    if ollama_base_url:
        env["OLLAMA_BASE_URL"] = ollama_base_url
    if ollama_model:
        env["OLLAMA_MODEL"] = ollama_model
    
    if url:
        cmd.extend(["-u", url])
    else:
        # Save uploaded file with size limit check
        safe_filename = os.path.basename(file.filename)
        input_path = os.path.join(job_output_dir, f"input_{safe_filename}")
        request_meta["original_filename"] = safe_filename
        request_meta["input_path"] = input_path
        
        # Read file in chunks to check size
        size = 0
        limit_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        
        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read 1MB chunks
                size += len(content)
                if size > limit_bytes:
                    os.remove(input_path)
                    shutil.rmtree(job_output_dir)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size {MAX_FILE_SIZE_MB}MB")
                buffer.write(content)
                
        cmd.extend(["-i", input_path])

    cmd.extend(["-o", job_output_dir])
    if interview_mode_enabled:
        cmd.append("--interview-mode")
    if allow_long_clips_enabled:
        cmd.append("--allow-long-clips")
    cmd.extend(["--max-clips", str(max_clips_value)])
    append_job_log(job_output_dir, f"Job {job_id} queued.")
    update_job_manifest(job_output_dir, {
        "job_id": job_id,
        "status": "queued",
        "error": None,
        "can_resume": True,
        "request": request_meta,
        "provider": {
            "name": provider,
            "ollama_base_url": ollama_base_url,
            "ollama_model": ollama_model,
        },
        "pipeline": {
            "output_dir": job_output_dir,
        }
    })

    # Enqueue Job
    jobs[job_id] = {
        'status': 'queued',
        'job_state': 'queued',
        'logs': [f"Job {job_id} queued."],
        'cmd': cmd,
        'env': env,
        'output_dir': job_output_dir,
        'cancel_requested': False,
        'queue_token': queue_token,
    }
    
    await job_queue.put((job_id, queue_token))
    
    return {"job_id": job_id, "status": "queued"}

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        job = _load_job_from_disk(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_id in jobs and not job.get("result"):
        job["result"] = build_job_result(_get_job_output_dir(job_id), job_id)
    if job_id in jobs and "can_resume" not in job:
        summary = get_job_summary(OUTPUT_DIR, job_id)
        if summary:
            job["can_resume"] = summary.get("can_resume", False)

    return {
        "status": job['status'],
        "logs": job['logs'],
        "result": job.get('result'),
        "job_state": job.get('job_state', job['status']),
        "error": job.get('error'),
        "can_resume": job.get('can_resume', False),
    }


@app.get("/api/jobs/history")
async def get_job_history():
    return {"jobs": list_job_summaries(OUTPUT_DIR)}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Active job not found")

    job_state = job.get("job_state", job.get("status"))
    if job_state not in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail=f"Job cannot be cancelled from state '{job_state}'")

    output_dir = job.get("output_dir") or _get_job_output_dir(job_id)
    job["cancel_requested"] = True
    job["error"] = "Job cancelled by user."
    if not job.get("logs") or job["logs"][-1] != "Cancellation requested by user.":
        job["logs"].append("Cancellation requested by user.")
        append_job_log(output_dir, "Cancellation requested by user.")

    if job_state == "queued":
        return _mark_job_cancelled(job_id, output_dir)

    _terminate_job_process(job, force=False)
    return {
        "status": "processing",
        "logs": job.get("logs", []),
        "result": job.get("result"),
        "job_state": "processing",
        "error": "Cancellation requested. Waiting for the worker to stop.",
        "can_resume": True,
    }


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    req: ResumeJobRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    output_dir = os.path.join(OUTPUT_DIR, job_id)
    manifest = load_job_manifest(output_dir)
    if not manifest:
        raise HTTPException(status_code=404, detail="Job manifest not found")

    current_job = jobs.get(job_id)
    if current_job and current_job.get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Job is already queued or processing")

    request_meta = manifest.get("request", {})
    source_type = request_meta.get("type")
    if source_type not in {"url", "file"}:
        raise HTTPException(status_code=400, detail="Job manifest is missing request source information")

    provider = (req.provider or manifest.get("provider", {}).get("name") or "gemini").strip().lower()
    ollama_base_url = req.ollama_base_url or manifest.get("provider", {}).get("ollama_base_url")
    ollama_model = req.ollama_model or manifest.get("provider", {}).get("ollama_model")

    if provider == "gemini" and not x_gemini_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")
    if provider == "ollama":
        ollama_base_url, ollama_model = _validate_ollama_model_or_raise(ollama_base_url, ollama_model)

    cmd = ["python", "-u", "main.py", "--resume", "--keep-original"]
    env = os.environ.copy()
    env["LLM_PROVIDER"] = provider
    if x_gemini_key:
        env["GEMINI_API_KEY"] = x_gemini_key
    if ollama_base_url:
        env["OLLAMA_BASE_URL"] = ollama_base_url
    if ollama_model:
        env["OLLAMA_MODEL"] = ollama_model

    if source_type == "url":
        source_url = request_meta.get("url")
        if not source_url:
            raise HTTPException(status_code=400, detail="Job manifest is missing the source URL")
        cmd.extend(["-u", source_url])
    else:
        input_path = request_meta.get("input_path")
        if not input_path or not os.path.exists(input_path):
            raise HTTPException(status_code=400, detail="Original uploaded input file is no longer available")
        cmd.extend(["-i", input_path])

    cmd.extend(["-o", output_dir])
    if request_meta.get("interview_mode"):
        cmd.append("--interview-mode")
    if request_meta.get("allow_long_clips"):
        cmd.append("--allow-long-clips")
    cmd.extend(["--max-clips", str(_coerce_max_clips(request_meta.get("max_clips")))])

    jobs[job_id] = {
        "status": "queued",
        "job_state": "queued",
        "logs": read_job_logs(output_dir, limit=200) + [f"Job {job_id} resumed and queued."],
        "result": build_job_result(output_dir, job_id),
        "can_resume": True,
        "cmd": cmd,
        "env": env,
        "output_dir": output_dir,
        "cancel_requested": False,
        "queue_token": uuid.uuid4().hex,
    }
    append_job_log(output_dir, f"Job {job_id} resumed and queued.")
    update_job_manifest(output_dir, {
        "status": "queued",
        "error": None,
        "can_resume": True,
        "provider": {
            "name": provider,
            "ollama_base_url": ollama_base_url,
            "ollama_model": ollama_model,
        }
    })
    await job_queue.put((job_id, jobs[job_id]["queue_token"]))
    return {"job_id": job_id, "status": "queued"}

from editor import VideoEditor
from subtitles import burn_subtitles, transcribe_audio
from hooks import add_hook_to_video
from translate import translate_video, get_supported_languages
from thumbnail import analyze_video_for_titles, refine_titles, generate_thumbnail, generate_youtube_description

class EditRequest(BaseModel):
    job_id: str
    clip_index: int
    api_key: Optional[str] = None
    input_filename: Optional[str] = None
    provider: Optional[str] = "gemini"
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None

@app.post("/api/edit")
async def edit_clip(
    req: EditRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    # Determine API Key
    final_api_key = req.api_key or x_gemini_key or os.environ.get("GEMINI_API_KEY")
    provider_name = (req.provider or "gemini").lower()
    
    if provider_name == "gemini" and not final_api_key:
        raise HTTPException(status_code=400, detail="Missing Gemini API Key (Header or Body)")
    if provider_name == "ollama":
        req.ollama_base_url, req.ollama_model = _validate_ollama_model_or_raise(req.ollama_base_url, req.ollama_model)

    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)
    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")
    clip = clips[req.clip_index]
    clip["clip_index"] = req.clip_index
    metadata_changed = _ensure_clip_versions(req.job_id, output_dir, clip)
    source_version = _find_clip_version(clip, filename=req.input_filename)
    if not source_version:
        raise HTTPException(status_code=404, detail="Source clip version not found")

    filename = source_version["filename"]
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    if metadata_changed:
        data["shorts"][req.clip_index] = clip
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    try:
        request_token = int(time.time() * 1000)
        edited_filename = f"edited_{request_token}_{filename}"
        output_path = os.path.join(output_dir, edited_filename)
        
        # Run editing in a thread to avoid blocking main loop
        # Since VideoEditor uses blocking calls (subprocess, API wait)
        def run_edit():
            editor = VideoEditor(
                provider=provider_name,
                api_key=final_api_key,
                base_url=(req.ollama_base_url or os.environ.get("OLLAMA_BASE_URL")) if provider_name == "ollama" else None,
                model_name=(req.ollama_model or os.environ.get("OLLAMA_MODEL")) if provider_name == "ollama" else None
            )
            
            # SAFE FILE RENAMING STRATEGY (Avoid UnicodeEncodeError in Docker)
            # Create a safe ASCII filename in the same directory
            safe_filename = f"temp_input_{req.job_id}.mp4"
            safe_input_path = os.path.join(output_dir, safe_filename)
            
            # Copy original file to safe path
            # (Copy is safer than rename if something crashes, we keep original)
            shutil.copy(input_path, safe_input_path)
            
            try:
                # 1. Upload (using safe path)
                vid_file = editor.upload_video(safe_input_path)
                
                # 2. Get duration
                import cv2
                cap = cv2.VideoCapture(safe_input_path)
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                duration = frame_count / fps if fps else 0
                cap.release()
                
                # Load transcript from metadata
                transcript = None
                try:
                    meta_files = glob.glob(os.path.join(OUTPUT_DIR, req.job_id, "*_metadata.json"))
                    if meta_files:
                        with open(meta_files[0], 'r') as f:
                            data = json.load(f)
                            transcript = data.get('transcript')
                except Exception as e:
                    print(f"⚠️ Could not load transcript for editing context: {e}")

                # 3. Get Plan (Filter String)
                filter_data = editor.get_ffmpeg_filter(vid_file, duration, fps=fps, width=width, height=height, transcript=transcript)
                
                # 4. Apply
                # Use safe output name first
                safe_output_path = os.path.join(output_dir, f"temp_output_{req.job_id}.mp4")
                editor.apply_edits(safe_input_path, safe_output_path, filter_data)
                
                # Move result to final destination (rename works even if dest name has unicode if filesystem supports it, 
                # but python might still struggle if locale is broken? No, os.rename usually handles it better than subprocess args)
                # Actually, output_path is defined above: f"edited_{filename}"
                # If filename has unicode, output_path has unicode.
                # Let's hope shutil.move / os.rename works.
                if os.path.exists(safe_output_path):
                    shutil.move(safe_output_path, output_path)
                
                return filter_data
            finally:
                # Cleanup temp safe input
                if os.path.exists(safe_input_path):
                    os.remove(safe_input_path)

        # Run in thread pool
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, run_edit)

        _append_clip_version(
            req.job_id,
            output_dir,
            clip,
            output_filename=edited_filename,
            operation="edit",
            label="Auto Edit",
            transcript_source="audio",
            subtitle_settings=None,
            hook_settings=None,
        )
        data["shorts"][req.clip_index] = clip
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

        return {
            "success": True, 
            "new_video_url": _clip_video_url(req.job_id, edited_filename),
            "clip": clip,
            "edit_plan": plan
        }

    except Exception as e:
        print(f"❌ Edit Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SubtitleRequest(BaseModel):
    job_id: str
    clip_index: int
    position: str = "bottom" # top, middle, bottom
    y_position: Optional[float] = None # 0-100, subtitle box center along y-axis
    font_size: int = 16
    font_family: Optional[str] = None
    background_style: Optional[str] = None
    input_filename: Optional[str] = None

@app.post("/api/subtitle")
async def add_subtitles(req: SubtitleRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index
    metadata_changed = _ensure_clip_versions(req.job_id, output_dir, clip_data)
    source_version = _find_clip_version(clip_data, filename=req.input_filename)
    if not source_version:
        raise HTTPException(status_code=404, detail="Source clip version not found")

    input_path = os.path.join(output_dir, source_version["filename"])
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    request_token = int(time.time() * 1000)
    output_filename = f"subtitled_{request_token}_{source_version['filename']}"
    output_path = os.path.join(output_dir, output_filename)

    if metadata_changed:
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    try:
        subtitle_settings = _build_subtitle_settings(req, clip_data)
        if source_version.get("transcript_source") == "audio":
            subtitle_transcript = transcribe_audio(input_path)
            clip_start = 0.0
            clip_end = _probe_video_duration(input_path)
        else:
            subtitle_transcript = data.get("transcript")
            if not subtitle_transcript:
                raise HTTPException(status_code=400, detail="Transcript not found in metadata. Please process a new video.")
            clip_start = float(source_version.get("transcript_start", clip_data.get("start", 0.0)))
            clip_end = float(source_version.get("transcript_end", clip_data.get("end", clip_start)))

        def run_burn():
            return burn_subtitles(
                input_path,
                subtitle_transcript,
                clip_start,
                clip_end,
                output_path,
                alignment=subtitle_settings.get("position", "bottom"),
                y_position=subtitle_settings.get("y_position"),
                fontsize=subtitle_settings.get("font_size", 16),
                font_family=subtitle_settings.get("font_family"),
                background_style=subtitle_settings.get("background_style"),
            )

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, run_burn)
        if not success:
            raise HTTPException(status_code=400, detail="No words found for this clip range.")
    except Exception as e:
        print(f"❌ Subtitle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    _append_clip_version(
        req.job_id,
        output_dir,
        clip_data,
        output_filename=output_filename,
        operation="subtitle",
        label="Subtitles",
        transcript_source=source_version.get("transcript_source"),
        transcript_start=source_version.get("transcript_start"),
        transcript_end=source_version.get("transcript_end"),
        subtitle_settings=subtitle_settings,
    )
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    return {
        "success": True,
        "new_video_url": _clip_video_url(req.job_id, output_filename),
        "clip": clip_data,
    }

class HookRequest(BaseModel):
    job_id: str
    clip_index: int
    text: str
    input_filename: Optional[str] = None
    position: Optional[str] = "top" # top, center, bottom
    horizontal_position: Optional[str] = "center" # left, center, right
    x_position: Optional[float] = None # 0-100, box center along x-axis
    y_position: Optional[float] = None # 0-100, box center along y-axis
    text_align: Optional[str] = "center" # left, center, right
    size: Optional[str] = "M" # S, M, L
    width_preset: Optional[str] = "wide" # full, wide, medium, narrow
    font_family: Optional[str] = None
    background_style: Optional[str] = None

@app.post("/api/hook")
async def add_hook(req: HookRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index
    metadata_changed = _ensure_clip_versions(req.job_id, output_dir, clip_data)
    source_version = _find_clip_version(clip_data, filename=req.input_filename)
    if not source_version:
        raise HTTPException(status_code=404, detail="Source clip version not found")

    input_path = os.path.join(output_dir, source_version["filename"])
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    request_token = int(time.time() * 1000)
    output_filename = f"hook_{request_token}_{source_version['filename']}"
    output_path = os.path.join(output_dir, output_filename)

    if metadata_changed:
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    try:
        hook_settings = _build_hook_settings(req, clip_data)
        if not hook_settings:
            raise HTTPException(status_code=400, detail="Hook text is required")

        def run_hook():
            size_map = {"S": 0.8, "M": 1.0, "L": 1.3}
            return add_hook_to_video(
                input_path,
                hook_settings["text"],
                output_path,
                position=hook_settings.get("position", "top"),
                horizontal_position=hook_settings.get("horizontal_position", "center"),
                x_position=hook_settings.get("x_position"),
                y_position=hook_settings.get("y_position"),
                text_align=hook_settings.get("text_align", "center"),
                font_scale=size_map.get(hook_settings.get("size"), 1.0),
                width_preset=hook_settings.get("width_preset", "wide"),
                font_name=hook_settings.get("font_family"),
                background_style=hook_settings.get("background_style"),
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_hook)

    except Exception as e:
        print(f"❌ Hook Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    _append_clip_version(
        req.job_id,
        output_dir,
        clip_data,
        output_filename=output_filename,
        operation="hook",
        label="Hook",
        transcript_source=source_version.get("transcript_source"),
        transcript_start=source_version.get("transcript_start"),
        transcript_end=source_version.get("transcript_end"),
        hook_settings=hook_settings,
    )
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    return {
        "success": True,
        "new_video_url": _clip_video_url(req.job_id, output_filename),
        "clip": clip_data,
    }


class SelectClipVersionRequest(BaseModel):
    job_id: str
    clip_index: int
    version_id: str


@app.post("/api/clip/version/select")
async def select_clip_version(req: SelectClipVersionRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index
    if _ensure_clip_versions(req.job_id, output_dir, clip_data):
        data["shorts"][req.clip_index] = clip_data

    _select_clip_version(clip_data, req.version_id)
    _sync_clip_variant_fields(req.job_id, clip_data)
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    return {
        "success": True,
        "new_video_url": clip_data.get("video_url"),
        "clip": clip_data,
    }


class TrimRequest(BaseModel):
    job_id: str
    clip_index: int
    input_filename: Optional[str] = None
    trim_start: float = 0.0
    trim_end: Optional[float] = None


@app.post("/api/trim")
async def trim_clip(req: TrimRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index
    metadata_changed = _ensure_clip_versions(req.job_id, output_dir, clip_data)
    source_version = _find_clip_version(clip_data, filename=req.input_filename)
    if not source_version:
        raise HTTPException(status_code=404, detail="Source clip version not found")

    input_path = os.path.join(output_dir, source_version["filename"])
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    duration = _probe_video_duration(input_path)
    trim_start = max(0.0, float(req.trim_start or 0.0))
    trim_end = duration if req.trim_end is None else min(duration, float(req.trim_end))

    if trim_end <= trim_start:
        raise HTTPException(status_code=400, detail="Trim end must be greater than trim start")
    if (trim_end - trim_start) < 0.25:
        raise HTTPException(status_code=400, detail="Trim window is too short")

    request_token = int(time.time() * 1000)
    output_filename = f"trimmed_{request_token}_{source_version['filename']}"
    output_path = os.path.join(output_dir, output_filename)

    if metadata_changed:
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    def run_trim():
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            input_path,
            "-ss",
            f"{trim_start:.3f}",
            "-to",
            f"{trim_end:.3f}",
            *ffmpeg_thread_args(),
            "-c:v",
            "libx264",
            "-preset",
            os.environ.get("OVERLAY_FFMPEG_PRESET", "veryfast").strip() or "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_path,
        ]
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_trim)
    except subprocess.CalledProcessError as e:
        error_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else "Unknown ffmpeg error"
        raise HTTPException(status_code=500, detail=error_text)

    transcript_source = source_version.get("transcript_source")
    transcript_start = source_version.get("transcript_start")
    transcript_end = source_version.get("transcript_end")
    if transcript_source == "original":
        source_start = float(transcript_start or clip_data.get("start", 0.0))
        transcript_start = source_start + trim_start
        transcript_end = source_start + trim_end
    else:
        transcript_start = None
        transcript_end = None

    label = f"Trim {_format_time_label(trim_start)}-{_format_time_label(trim_end)}"
    _append_clip_version(
        req.job_id,
        output_dir,
        clip_data,
        output_filename=output_filename,
        operation="trim",
        label=label,
        transcript_source=transcript_source,
        transcript_start=transcript_start,
        transcript_end=transcript_end,
    )
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    return {
        "success": True,
        "new_video_url": _clip_video_url(req.job_id, output_filename),
        "clip": clip_data,
        "duration": trim_end - trim_start,
    }

class TranslateRequest(BaseModel):
    job_id: str
    clip_index: int
    target_language: str
    source_language: Optional[str] = None
    input_filename: Optional[str] = None

@app.get("/api/translate/languages")
async def get_languages():
    """Return supported languages for translation."""
    return {"languages": get_supported_languages()}

@app.post("/api/translate")
async def translate_clip(
    req: TranslateRequest,
    x_elevenlabs_key: Optional[str] = Header(None, alias="X-ElevenLabs-Key")
):
    """Translate a video clip to a different language using ElevenLabs dubbing."""
    if not x_elevenlabs_key:
        raise HTTPException(status_code=400, detail="Missing X-ElevenLabs-Key header")

    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index
    metadata_changed = _ensure_clip_versions(req.job_id, output_dir, clip_data)
    source_version = _find_clip_version(clip_data, filename=req.input_filename)
    if not source_version:
        raise HTTPException(status_code=404, detail="Source clip version not found")

    filename = source_version["filename"]
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    base, ext = os.path.splitext(filename)
    request_token = int(time.time() * 1000)
    output_filename = f"translated_{request_token}_{req.target_language}_{base}{ext}"
    output_path = os.path.join(output_dir, output_filename)

    if metadata_changed:
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    try:
        def run_translate():
            return translate_video(
                video_path=input_path,
                output_path=output_path,
                target_language=req.target_language,
                api_key=x_elevenlabs_key,
                source_language=req.source_language,
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_translate)

    except Exception as e:
        print(f"❌ Translation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    _append_clip_version(
        req.job_id,
        output_dir,
        clip_data,
        output_filename=output_filename,
        operation="translate",
        label=f"Dub {req.target_language.upper()}",
        transcript_source="audio",
    )
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    return {
        "success": True,
        "new_video_url": _clip_video_url(req.job_id, output_filename),
        "clip": clip_data,
    }

class SocialPostRequest(BaseModel):
    job_id: str
    clip_index: int
    api_key: str
    user_id: str
    platforms: List[str] # ["tiktok", "instagram", "youtube"]
    # Optional overrides if frontend wants to edit them
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[str] = None # ISO-8601 string
    timezone: Optional[str] = "UTC"
    instagram_share_mode: Optional[str] = "CUSTOM"
    tiktok_post_mode: Optional[str] = "DIRECT_POST"
    tiktok_is_aigc: Optional[bool] = False
    facebook_page_id: Optional[str] = None
    pinterest_board_id: Optional[str] = None

import httpx

UPLOAD_POST_AUTH_SCHEMES = ("ApiKey", "Apikey")
SOCIAL_PLATFORM_CANONICAL = {
}
UPLOAD_POST_AUDIO_LANGUAGE_MAP = {
    "ar": "ar-SA",
    "de": "de-DE",
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "hi": "hi-IN",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "pt": "pt-BR",
    "ru": "ru-RU",
    "sv": "sv-SE",
    "tr": "tr-TR",
    "uk": "uk-UA",
    "zh": "zh-CN",
}


def _upload_post_auth_headers(api_key: str, scheme: str, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = dict(extra_headers or {})
    headers["Authorization"] = f"{scheme} {api_key}"
    return headers


async def _upload_post_async_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    api_key: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> httpx.Response:
    response = None
    for index, scheme in enumerate(UPLOAD_POST_AUTH_SCHEMES):
        response = await client.request(method, url, headers=_upload_post_auth_headers(api_key, scheme, headers), **kwargs)
        if response.status_code not in {401, 403} or index == len(UPLOAD_POST_AUTH_SCHEMES) - 1:
            return response
        print(f"⚠️ Upload-Post auth with scheme '{scheme}' failed ({response.status_code}). Retrying alternate header format...")
    return response


def _upload_post_sync_request(
    client: httpx.Client,
    method: str,
    url: str,
    api_key: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> httpx.Response:
    response = None
    for index, scheme in enumerate(UPLOAD_POST_AUTH_SCHEMES):
        response = client.request(method, url, headers=_upload_post_auth_headers(api_key, scheme, headers), **kwargs)
        if response.status_code not in {401, 403} or index == len(UPLOAD_POST_AUTH_SCHEMES) - 1:
            return response
        print(f"⚠️ Upload-Post auth with scheme '{scheme}' failed ({response.status_code}). Retrying alternate header format...")
    return response


def _normalize_social_platforms(platforms: List[str]) -> List[str]:
    normalized = []
    seen = set()
    for platform in platforms:
        resolved = SOCIAL_PLATFORM_CANONICAL.get((platform or "").strip().lower(), (platform or "").strip().lower())
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(resolved)
    return normalized


def _resolve_upload_post_language_fields(language_code: Optional[str]) -> Dict[str, str]:
    normalized = (language_code or "").strip().lower()
    if not normalized:
        return {}
    base_code = normalized.split("-")[0]
    audio_language = UPLOAD_POST_AUDIO_LANGUAGE_MAP.get(base_code, normalized)
    return {
        "defaultLanguage": base_code,
        "defaultAudioLanguage": audio_language,
    }

@app.post("/api/social/post")
async def post_to_socials(req: SocialPostRequest):
    _, result, _ = _get_job_result_or_400(req.job_id)
        
    try:
        _, _, metadata = _load_job_metadata_or_404(req.job_id)
        clip = _find_result_clip(result, req.clip_index)
        # Video URL is relative /videos/..., we need absolute file path
        # clip['video_url'] is like "/videos/{job_id}/{filename}"
        # We constructed it as: f"/videos/{job_id}/{clip_filename}"
        # And file is at f"{OUTPUT_DIR}/{job_id}/{clip_filename}"
        
        filename = clip['video_url'].split('/')[-1]
        file_path = os.path.join(OUTPUT_DIR, req.job_id, filename)
        
        if not os.path.exists(file_path):
             raise HTTPException(status_code=404, detail=f"Video file not found: {file_path}")

        # Construct parameters for Upload-Post API
        # Fallbacks
        final_title = req.title or clip.get('video_title_for_youtube_short') or clip.get('title', 'Viral Short')
        final_description = req.description or clip.get('video_description_for_instagram') or clip.get('video_description_for_tiktok') or "Check this out!"
        transcript_language = (
            metadata.get("transcript", {}).get("language")
            or metadata.get("language")
            or clip.get("language")
        )
        requested_platforms = _normalize_social_platforms(req.platforms)
        requested_platform_set = set(requested_platforms)
        
        # Prepare form data
        url = "https://api.upload-post.com/api/upload"
        
        # Prepare data as dict (httpx handles lists for multiple values)
        data_payload = {
            "user": req.user_id,
            "title": final_title,
            "platform[]": requested_platforms,
            "async_upload": "true"  # Enable async upload
        }

        # Add scheduling if present
        if req.scheduled_date:
            data_payload["scheduled_date"] = req.scheduled_date
            if req.timezone:
                data_payload["timezone"] = req.timezone
        
        # Add Platform specifics
        if "tiktok" in requested_platform_set:
             data_payload["tiktok_title"] = final_description
             data_payload["post_mode"] = req.tiktok_post_mode or "DIRECT_POST"
             data_payload["is_aigc"] = "true" if req.tiktok_is_aigc else "false"
             
        if "instagram" in requested_platform_set:
             data_payload["instagram_title"] = final_description
             data_payload["media_type"] = "REELS"
             data_payload["share_mode"] = req.instagram_share_mode or "CUSTOM"

        if "youtube" in requested_platform_set:
             yt_title = req.title or clip.get('video_title_for_youtube_short', final_title)
             data_payload["youtube_title"] = yt_title
             data_payload["youtube_description"] = final_description
             data_payload["privacyStatus"] = "public"
             data_payload.update(_resolve_upload_post_language_fields(transcript_language))

        if "facebook" in requested_platform_set:
             data_payload["facebook_title"] = final_title
             data_payload["facebook_description"] = final_description
             data_payload["facebook_media_type"] = "REELS"
             if req.facebook_page_id:
                 data_payload["facebook_page_id"] = req.facebook_page_id

        if "x" in requested_platform_set:
             data_payload["x_title"] = final_description

        if "threads" in requested_platform_set:
             data_payload["threads_title"] = final_description

        if "pinterest" in requested_platform_set:
             data_payload["pinterest_title"] = final_title
             data_payload["pinterest_description"] = final_description
             if req.pinterest_board_id:
                 data_payload["pinterest_board_id"] = req.pinterest_board_id

        # Send File
        # httpx AsyncClient requires async file reading or bytes. 
        # Since we have MAX_FILE_SIZE_MB, reading into memory is safe-ish.
        with open(file_path, "rb") as f:
            file_content = f.read()
            
        files = {
            "video": (filename, file_content, "video/mp4")
        }

        # Switch to synchronous Client to avoid "sync request with AsyncClient" error with multipart/files
        with httpx.Client(timeout=120.0) as client:
            print(f"📡 Sending to Upload-Post for platforms: {requested_platforms}")
            response = _upload_post_sync_request(client, "POST", url, req.api_key, data=data_payload, files=files)
            
        if response.status_code not in [200, 201, 202]: # Added 201
             print(f"❌ Upload-Post Error: {response.text}")
             raise HTTPException(status_code=response.status_code, detail=f"Vendor API Error: {response.text}")

        return response.json()

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Social Post Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/social/user")
async def get_social_user(api_key: str = Header(..., alias="X-Upload-Post-Key")):
    """Proxy to fetch user ID from Upload-Post"""
    if not api_key:
         raise HTTPException(status_code=400, detail="Missing X-Upload-Post-Key header")
         
    url = "https://api.upload-post.com/api/uploadposts/users"
    print(f"🔍 Fetching User ID from: {url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await _upload_post_async_request(client, "GET", url, api_key)
            if resp.status_code != 200:
                print(f"❌ Upload-Post User Fetch Error: {resp.text}")
                raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch user: {resp.text}")
            
            data = resp.json()
            print(f"🔍 Upload-Post User Response: {data}")
            
            profiles_list = []
            raw_profiles = data.get('profiles', []) if isinstance(data, dict) else data
            if isinstance(raw_profiles, list):
                for p in raw_profiles:
                    if not isinstance(p, dict):
                        continue
                    username = p.get('username') or p.get('user') or p.get('name')
                    if not username:
                        continue

                    socials = p.get('social_accounts') or p.get('accounts') or {}
                    connected = []
                    for platform in ['tiktok', 'instagram', 'youtube']:
                        account_info = socials.get(platform) if isinstance(socials, dict) else None
                        if isinstance(account_info, dict):
                            if any(value not in (None, "", [], {}) for value in account_info.values()):
                                connected.append(platform)
                        elif account_info:
                            connected.append(platform)
                    
                    profiles_list.append({
                        "username": username,
                        "connected": connected
                    })
            
            if not profiles_list:
                return {
                    "profiles": [],
                    "error": "No profiles found in Upload-Post. Check Manage Users and ensure at least one connected social profile exists."
                }
                
            return {"profiles": profiles_list}
            
        except HTTPException:
             raise
        except Exception as e:
             raise HTTPException(status_code=500, detail=str(e))

# --- Thumbnail Studio Endpoints ---

@app.post("/api/thumbnail/upload")
async def thumbnail_upload(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    """Upload video and start background Whisper transcription immediately."""
    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    session_id = str(uuid.uuid4())
    transcript_event = asyncio.Event()

    # Save file if uploaded directly
    video_path = None
    if file:
        video_path = os.path.join(UPLOAD_DIR, f"thumb_{session_id}_{file.filename}")
        with open(video_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

    # Initialize session
    thumbnail_sessions[session_id] = {
        "video_path": video_path,
        "transcript_event": transcript_event,
        "transcript_ready": False,
        "transcript": None,
        "transcript_segments": [],
        "video_duration": 0,
        "language": "en",
        "context": "",
        "titles": [],
        "conversation": [],
        "_url": url,  # Store URL for deferred download
    }

    async def run_background_whisper():
        try:
            vpath = video_path
            # Download YouTube video if URL was provided
            if not vpath and url:
                from main import download_youtube_video
                loop = asyncio.get_event_loop()
                vpath, _ = await loop.run_in_executor(None, download_youtube_video, url, UPLOAD_DIR)
                thumbnail_sessions[session_id]["video_path"] = vpath

            from main import transcribe_video
            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(None, transcribe_video, vpath)
            segments = transcript.get("segments", [])
            duration = segments[-1]["end"] if segments else 0

            thumbnail_sessions[session_id].update({
                "transcript_ready": True,
                "transcript": transcript,
                "transcript_segments": segments,
                "video_duration": duration,
                "language": transcript.get("language", "en"),
            })
            print(f"✅ [Thumbnail] Background Whisper complete for session {session_id}")
        except Exception as e:
            print(f"❌ [Thumbnail] Background Whisper failed: {e}")
            thumbnail_sessions[session_id]["transcript_error"] = str(e)
        finally:
            transcript_event.set()

    asyncio.create_task(run_background_whisper())

    return {"session_id": session_id}


@app.post("/api/thumbnail/analyze")
async def thumbnail_analyze(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Analyze a video and suggest viral YouTube titles."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    pre_transcript = None

    # Check for pre-existing session with background Whisper
    if session_id and session_id in thumbnail_sessions:
        session = thumbnail_sessions[session_id]

        # Wait for background Whisper to complete
        transcript_event = session.get("transcript_event")
        if transcript_event:
            print(f"⏳ [Thumbnail] Waiting for background Whisper to finish...")
            await transcript_event.wait()

        if session.get("transcript_error"):
            raise HTTPException(status_code=500, detail=f"Transcription failed: {session['transcript_error']}")

        video_path = session["video_path"]
        if not video_path or not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Video file not found in session")

        if session.get("transcript_ready"):
            pre_transcript = session["transcript"]
    else:
        # No pre-existing session — need file or URL
        if not url and not file:
            raise HTTPException(status_code=400, detail="Must provide URL, File, or session_id")

        session_id = str(uuid.uuid4())

        if url:
            from main import download_youtube_video
            video_path, _ = download_youtube_video(url, UPLOAD_DIR)
        else:
            video_path = os.path.join(UPLOAD_DIR, f"thumb_{session_id}_{file.filename}")
            with open(video_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)

    try:
        # Run analysis in thread pool (skips Whisper if pre_transcript is available)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, analyze_video_for_titles, api_key, video_path, pre_transcript)

        # Store/update session context
        if session_id not in thumbnail_sessions:
            thumbnail_sessions[session_id] = {}

        thumbnail_sessions[session_id].update({
            "context": result.get("transcript_summary", ""),
            "titles": result.get("titles", []),
            "language": result.get("language", "en"),
            "conversation": thumbnail_sessions[session_id].get("conversation", []),
            "video_path": video_path,
            "transcript_segments": result.get("segments", []),
            "video_duration": result.get("video_duration", 0)
        })

        return {
            "session_id": session_id,
            "titles": result.get("titles", []),
            "context": result.get("transcript_summary", ""),
            "language": result.get("language", "en"),
            "recommended": result.get("recommended", [])
        }

    except Exception as e:
        print(f"❌ Thumbnail Analyze Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ThumbnailTitlesRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    title: Optional[str] = None

@app.post("/api/thumbnail/titles")
async def thumbnail_titles(
    req: ThumbnailTitlesRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Refine title suggestions or accept a manual title."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    # Manual title mode - just create a session with the user's title
    if req.title:
        session_id = req.session_id or str(uuid.uuid4())
        if session_id not in thumbnail_sessions:
            thumbnail_sessions[session_id] = {
                "context": "",
                "titles": [req.title],
                "language": "en",
                "conversation": []
            }
        return {"session_id": session_id, "titles": [req.title]}

    # Refinement mode
    if not req.session_id or req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if not req.message:
        raise HTTPException(status_code=400, detail="Must provide message or title")

    session = thumbnail_sessions[req.session_id]

    # Add user message to conversation history
    session["conversation"].append({"role": "user", "content": req.message})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            refine_titles,
            api_key,
            session["context"],
            req.message,
            session["conversation"]
        )

        new_titles = result.get("titles", [])
        session["titles"] = new_titles
        session["conversation"].append({"role": "assistant", "content": json.dumps(new_titles)})

        return {"titles": new_titles}

    except Exception as e:
        print(f"❌ Thumbnail Titles Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thumbnail/generate")
async def thumbnail_generate(
    request: Request,
    session_id: str = Form(...),
    title: str = Form(...),
    extra_prompt: str = Form(""),
    count: int = Form(3),
    face: Optional[UploadFile] = File(None),
    background: Optional[UploadFile] = File(None),
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Generate YouTube thumbnails with Gemini image generation."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    # Clamp count
    count = min(max(1, count), 6)

    # Save optional uploaded images
    face_path = None
    bg_path = None
    thumb_upload_dir = os.path.join(UPLOAD_DIR, f"thumb_{session_id}")
    os.makedirs(thumb_upload_dir, exist_ok=True)

    try:
        if face and face.filename:
            face_path = os.path.join(thumb_upload_dir, f"face_{face.filename}")
            with open(face_path, "wb") as f:
                f.write(await face.read())

        if background and background.filename:
            bg_path = os.path.join(thumb_upload_dir, f"bg_{background.filename}")
            with open(bg_path, "wb") as f:
                f.write(await background.read())

        # Get video context from session (transcript summary from analysis step)
        video_context = ""
        if session_id in thumbnail_sessions:
            video_context = thumbnail_sessions[session_id].get("context", "")

        # Run generation in thread pool
        loop = asyncio.get_event_loop()
        thumbnails = await loop.run_in_executor(
            None,
            generate_thumbnail,
            api_key,
            title,
            session_id,
            face_path,
            bg_path,
            extra_prompt,
            count,
            video_context
        )

        return {"thumbnails": thumbnails}

    except Exception as e:
        print(f"❌ Thumbnail Generate Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ThumbnailDescribeRequest(BaseModel):
    session_id: str
    title: str

@app.post("/api/thumbnail/describe")
async def thumbnail_describe(
    req: ThumbnailDescribeRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Generate a YouTube description with chapters from the transcript."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    if req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[req.session_id]
    segments = session.get("transcript_segments", [])
    if not segments:
        raise HTTPException(status_code=400, detail="No transcript segments available. Please analyze a video first.")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            generate_youtube_description,
            api_key,
            req.title,
            segments,
            session.get("language", "en"),
            session.get("video_duration", 0)
        )
        return {"description": result.get("description", "")}

    except Exception as e:
        print(f"❌ Thumbnail Describe Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thumbnail/publish")
async def thumbnail_publish(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    thumbnail_url: str = Form(...),
    api_key: str = Form(...),
    user_id: str = Form(...),
):
    """Kick off a background upload to YouTube via Upload-Post and return immediately."""
    if session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[session_id]
    video_path = session.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Original video file not found")

    # Resolve thumbnail path from URL
    thumb_relative = thumbnail_url.lstrip("/")
    if thumb_relative.startswith("thumbnails/"):
        thumb_path = os.path.join(OUTPUT_DIR, thumb_relative)
    else:
        thumb_path = os.path.join(THUMBNAILS_DIR, thumb_relative)

    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail=f"Thumbnail file not found: {thumb_path}")

    # Generate a unique ID for this publish job so the frontend can poll
    publish_id = str(uuid.uuid4())
    publish_jobs[publish_id] = {"status": "uploading", "result": None, "error": None}

    def do_upload():
        """Runs in a thread via BackgroundTasks — does the actual multipart upload."""
        try:
            upload_url = "https://api.upload-post.com/api/upload"
            data_payload = {
                "user": user_id,
                "platform[]": ["youtube"],
                "title": title,          # required base field (fallback)
                "async_upload": "true",
                "youtube_title": title,
                "youtube_description": description,
                "privacyStatus": "public",
            }
            video_filename = os.path.basename(video_path)
            thumb_filename = os.path.basename(thumb_path)

            print(f"📡 [Thumbnail] Publishing to YouTube via Upload-Post... (publish_id={publish_id})")
            with open(video_path, "rb") as vf, open(thumb_path, "rb") as tf:
                files = {
                    "video": (video_filename, vf.read(), "video/mp4"),
                    "thumbnail": (thumb_filename, tf.read(), "image/jpeg"),
                }

            # Use a long timeout — video uploads can take several minutes
            with httpx.Client(timeout=600.0) as client:
                response = _upload_post_sync_request(client, "POST", upload_url, api_key, data=data_payload, files=files)

            if response.status_code not in [200, 201, 202]:
                err = f"Upload-Post API Error ({response.status_code}): {response.text}"
                print(f"❌ {err}")
                publish_jobs[publish_id]["status"] = "failed"
                publish_jobs[publish_id]["error"] = err
            else:
                print(f"✅ [Thumbnail] Published successfully (publish_id={publish_id})")
                publish_jobs[publish_id]["status"] = "done"
                publish_jobs[publish_id]["result"] = response.json()

        except Exception as e:
            err = str(e)
            print(f"❌ Thumbnail Publish Background Error: {err}")
            publish_jobs[publish_id]["status"] = "failed"
            publish_jobs[publish_id]["error"] = err

    background_tasks.add_task(do_upload)
    return {"publish_id": publish_id, "status": "uploading"}


@app.get("/api/thumbnail/publish/status/{publish_id}")
async def thumbnail_publish_status(publish_id: str):
    """Poll the status of a background publish job."""
    if publish_id not in publish_jobs:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return publish_jobs[publish_id]


# @app.get("/api/gallery/clips")
# async def get_gallery_clips(limit: int = 20, offset: int = 0, refresh: bool = False):
#     """
#     Fetch clips from S3 for the gallery with pagination.
#     
#     Args:
#         limit: Number of clips to return (default 20, max 100)
#         offset: Starting position for pagination
#         refresh: Force refresh cache
#     """
#     try:
#         # Clamp limit to reasonable values
#         limit = min(max(1, limit), 100)
#         
#         # Get clips (uses cache internally)
#         all_clips = list_all_clips(limit=limit + offset, force_refresh=refresh)
#         
#         # Apply offset for pagination
#         clips = all_clips[offset:offset + limit]
#         
#         return {
#             "clips": clips,
#             "total": len(all_clips),
#             "limit": limit,
#             "offset": offset,
#             "has_more": len(all_clips) > offset + limit
#         }
#     except Exception as e:
#         print(f"❌ Gallery Error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
