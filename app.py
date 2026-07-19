import os
import uuid
import subprocess
import threading
import json
import logging
import gc
import datetime
import shutil
import glob
import time
import math
import asyncio
import signal
import difflib
import re
import tempfile
import base64
import hashlib
import secrets
import zlib
import urllib.request
import urllib.error
import urllib.parse
import socket
import numpy as np
import random
import concurrent.futures
from dotenv import load_dotenv
from typing import Any, Dict, Optional, List, Tuple
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from s3_uploader import upload_job_artifacts, list_all_clips
from longform.models import active_camera_roles, build_initial_steps, normalize_ai_config, normalize_project_config
from longform.pipeline import (
    restore_orphaned_projects,
    restart_longform_pipeline_task,
    resume_longform_pipeline_task,
    start_longform_pipeline_task,
    stop_longform_pipeline,
)
from longform.storage import (
    create_project as create_longform_project,
    delete_project as delete_longform_project,
    load_project_bundle as load_longform_project_bundle,
    list_projects as list_longform_projects,
    project_subdir as longform_project_subdir,
    project_upload_tmp_dir as longform_project_upload_tmp_dir,
    register_uploaded_file as register_longform_uploaded_file,
    remove_file as remove_longform_file,
    reorder_role_files as reorder_longform_role_files,
    save_state,
    update_project as update_longform_project,
)
from longform.ffmpeg_ops import media_url_from_path, probe_media, slugify_filename
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
from tight_edit import (
    DEFAULT_TIGHT_EDIT_PRESET,
    build_tight_edit_plan,
    normalize_tight_edit_preset,
    plan_manual_keep_segments,
    render_keep_segments,
)
from google import genai

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
TRANSCRIPTION_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "transcriptions")
os.makedirs(TRANSCRIPTION_OUTPUT_DIR, exist_ok=True)

# Configuration
def _env_non_negative_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(0, value)


MAX_FILE_SIZE_MB = _env_non_negative_int("MAX_FILE_SIZE_MB", 0)
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024 if MAX_FILE_SIZE_MB > 0 else None
JOB_RETENTION_SECONDS = int(os.environ.get("JOB_RETENTION_SECONDS", str(7 * 24 * 3600)))
LEGACY_SETTINGS_SYNC_DIR = "/tmp/openshorts/settings_sync"
_settings_sync_dir_raw = str(os.environ.get("SETTINGS_SYNC_DIR", "") or "").strip()
if not _settings_sync_dir_raw or _settings_sync_dir_raw == LEGACY_SETTINGS_SYNC_DIR:
    SETTINGS_SYNC_DIR = os.path.join(OUTPUT_DIR, ".settings_sync")
else:
    SETTINGS_SYNC_DIR = _settings_sync_dir_raw
SETTINGS_SYNC_TTL_DAYS = int(os.environ.get("SETTINGS_SYNC_TTL_DAYS", "365"))
SETTINGS_SYNC_MAX_BYTES = int(os.environ.get("SETTINGS_SYNC_MAX_BYTES", str(2 * 1024 * 1024)))
os.makedirs(SETTINGS_SYNC_DIR, exist_ok=True)


def _maybe_migrate_legacy_settings_sync_dir() -> None:
    if SETTINGS_SYNC_DIR == LEGACY_SETTINGS_SYNC_DIR:
        return
    if not os.path.isdir(LEGACY_SETTINGS_SYNC_DIR):
        return
    try:
        legacy_entries = os.listdir(LEGACY_SETTINGS_SYNC_DIR)
    except OSError:
        return
    if not legacy_entries:
        return
    for entry in legacy_entries:
        src_path = os.path.join(LEGACY_SETTINGS_SYNC_DIR, entry)
        dst_path = os.path.join(SETTINGS_SYNC_DIR, entry)
        if os.path.exists(dst_path):
            continue
        try:
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
        except OSError:
            continue


_maybe_migrate_legacy_settings_sync_dir()

# Application State
job_queue = asyncio.Queue()
jobs: Dict[str, Dict] = {}
thumbnail_sessions: Dict[str, Dict] = {}
publish_jobs: Dict[str, Dict] = {}  # {publish_id: {status, result, error}}
transcription_jobs: Dict[str, Dict] = {}
# Semester to limit concurrency to MAX_CONCURRENT_JOBS
concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_METADATA_UNSET = object()

BULK_OPERATION_MODE_RENDER_AND_POST = "render+post"
BULK_OPERATION_MODE_RENDER_ONLY = "render-only"
BULK_OPERATION_MODE_POST_ONLY = "post-only"
BULK_OPERATION_RUNNING_STATUSES = {"running", "pause_requested", "stop_requested"}
BULK_OPERATION_RESUMABLE_STATUSES = {"paused", "partial", "failed"}
BULK_OPERATION_TERMINAL_STATUSES = {"completed", "stopped"}
TRANSCRIPTION_ALLOWED_EXPORT_FORMATS = {"txt", "json", "srt", "vtt", "tsv"}


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


BULK_RENDER_CONCURRENCY = _env_positive_int("BULK_RENDER_CONCURRENCY", 1)
BULK_POST_CONCURRENCY = _env_positive_int("BULK_POST_CONCURRENCY", max(2, MAX_CONCURRENT_JOBS))
BULK_AUTO_PAUSE_AFTER_CONSECUTIVE_FAILURES = _env_positive_int("BULK_AUTO_PAUSE_AFTER_CONSECUTIVE_FAILURES", 3)
BULK_POST_TRANSIENT_MAX_ATTEMPTS = _env_positive_int("BULK_POST_TRANSIENT_MAX_ATTEMPTS", 3)
BULK_RESUME_MIN_LEAD_MINUTES = _env_positive_int("BULK_RESUME_MIN_LEAD_MINUTES", 15)
SOCIAL_CALENDAR_SYNC_CONCURRENCY = _env_positive_int("SOCIAL_CALENDAR_SYNC_CONCURRENCY", 6)
BROWSER_PREVIEW_CONCURRENCY = _env_positive_int("BROWSER_PREVIEW_CONCURRENCY", 1)

bulk_render_semaphore = asyncio.Semaphore(BULK_RENDER_CONCURRENCY)
bulk_post_semaphore = asyncio.Semaphore(BULK_POST_CONCURRENCY)
social_calendar_sync_semaphore = asyncio.Semaphore(SOCIAL_CALENDAR_SYNC_CONCURRENCY)
browser_preview_semaphore = asyncio.Semaphore(BROWSER_PREVIEW_CONCURRENCY)
bulk_operation_tasks: Dict[str, asyncio.Task] = {}
bulk_operation_runtime: Dict[str, Dict[str, Any]] = {}


class _HeaderCarrier:
    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.headers = headers or {}

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


def _job_queue_item_id(item: Any) -> Optional[str]:
    if isinstance(item, (list, tuple)) and item:
        return str(item[0])
    if item:
        return str(item)
    return None


def _queue_overview() -> Dict[str, Any]:
    queued_from_memory: List[str] = []
    for item in list(getattr(job_queue, "_queue", [])):
        job_id = _job_queue_item_id(item)
        if not job_id or job_id in queued_from_memory:
            continue
        job = jobs.get(job_id)
        if not job or job.get("cancel_requested") or job.get("status") == "cancelled":
            continue
        if job.get("status") == "queued" or job.get("job_state") == "queued":
            queued_from_memory.append(job_id)

    queued_state_ids: List[str] = []
    running_ids: List[str] = []
    for job_id, job in jobs.items():
        if job.get("cancel_requested") or job.get("status") == "cancelled":
            continue
        state = job.get("job_state") or job.get("status")
        status = job.get("status")
        if status == "processing" or state == "processing":
            running_ids.append(job_id)
        elif status == "queued" or state == "queued":
            queued_state_ids.append(job_id)

    # A job should normally remain inside job_queue until a slot is free. This
    # fallback keeps positions useful for older in-memory states after hot reloads.
    queued_ids = [job_id for job_id in queued_state_ids if job_id not in queued_from_memory]
    queued_ids.extend(job_id for job_id in queued_from_memory if job_id not in queued_ids)
    positions = {job_id: index + 1 for index, job_id in enumerate(queued_ids)}
    return {
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
        "running_count": len(running_ids),
        "queued_count": len(queued_ids),
        "running_job_ids": running_ids,
        "queued_job_ids": queued_ids,
        "positions": positions,
    }


def _attach_queue_metadata(payload: Dict[str, Any], overview: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    overview = overview or _queue_overview()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return payload
    result = dict(payload)
    positions = overview.get("positions") or {}
    if job_id in positions:
        result["queue_position"] = positions[job_id]
        result["queue_status"] = "waiting"
    elif job_id in set(overview.get("running_job_ids") or []):
        result["queue_position"] = 0
        result["queue_status"] = "running"
    result["queue"] = {
        "max_concurrent_jobs": overview.get("max_concurrent_jobs", MAX_CONCURRENT_JOBS),
        "running_count": overview.get("running_count", 0),
        "queued_count": overview.get("queued_count", 0),
    }
    return result


def _resolve_safe_job_output_dir(job_id: str) -> tuple[str, str]:
    normalized_job_id = (job_id or "").strip()
    if not normalized_job_id:
        raise HTTPException(status_code=400, detail="Invalid job id")
    if normalized_job_id != os.path.basename(normalized_job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    output_root_abs = os.path.abspath(OUTPUT_DIR)
    output_dir_abs = os.path.abspath(_get_job_output_dir(normalized_job_id))
    if output_dir_abs == output_root_abs or not output_dir_abs.startswith(output_root_abs + os.sep):
        raise HTTPException(status_code=400, detail="Invalid job id")
    return normalized_job_id, output_dir_abs


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


def _bulk_operation_requires_render(mode: Optional[str]) -> bool:
    return (mode or "").strip().lower() in {BULK_OPERATION_MODE_RENDER_AND_POST, BULK_OPERATION_MODE_RENDER_ONLY}


def _bulk_operation_requires_post(mode: Optional[str]) -> bool:
    return (mode or "").strip().lower() in {BULK_OPERATION_MODE_RENDER_AND_POST, BULK_OPERATION_MODE_POST_ONLY}


def _is_retryable_bulk_post_error(exc: Exception) -> bool:
    status_code = int(getattr(exc, "status_code", 0) or 0)
    if status_code in {408, 425, 429, 499, 502, 503, 504}:
        return True
    detail = _normalize_unicode_text(getattr(exc, "detail", None) or str(exc)).lower()
    return any(marker in detail for marker in (
        "gateway timeout",
        "client closed request",
        "timed out",
        "timeout",
        "connection reset",
        "connection closed",
        "temporarily unavailable",
        "rate limit",
    ))


def _normalize_bulk_operation_mode(mode: Optional[str]) -> str:
    normalized = (mode or "").strip().lower()
    if normalized in {
        BULK_OPERATION_MODE_RENDER_AND_POST,
        BULK_OPERATION_MODE_RENDER_ONLY,
        BULK_OPERATION_MODE_POST_ONLY,
    }:
        return normalized
    raise HTTPException(status_code=400, detail="Invalid bulk operation mode.")


def _normalize_bulk_operation_item(raw_item: Any, *, mode: str, order_index: int) -> Dict[str, Any]:
    if not isinstance(raw_item, dict):
        raise HTTPException(status_code=400, detail="Invalid bulk operation item.")

    try:
        clip_index = int(raw_item.get("clip_index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Bulk operation item is missing a valid clip_index.")

    hook_text = _normalize_unicode_text(raw_item.get("hook_text") or "").strip()
    scheduled_date = (raw_item.get("scheduled_date") or "").strip() or None

    if _bulk_operation_requires_render(mode) and not hook_text:
        raise HTTPException(status_code=400, detail=f"Hook text is required for clip {clip_index + 1}.")
    if _bulk_operation_requires_post(mode) and not scheduled_date:
        raise HTTPException(status_code=400, detail=f"scheduled_date is required for clip {clip_index + 1}.")

    render_status = raw_item.get("render_status")
    post_status = raw_item.get("post_status")
    if render_status not in {"pending", "running", "completed", "failed", "skipped"}:
        render_status = "pending" if _bulk_operation_requires_render(mode) else "skipped"
    if post_status not in {"pending", "running", "completed", "failed", "skipped"}:
        post_status = "pending" if _bulk_operation_requires_post(mode) else "skipped"

    attempts = raw_item.get("attempts")
    if not isinstance(attempts, dict):
        attempts = {}

    item = {
        "id": str(raw_item.get("id") or f"item-{order_index + 1}"),
        "order": int(raw_item.get("order", order_index)),
        "clip_index": clip_index,
        "clip_label": (raw_item.get("clip_label") or f"Clip {clip_index + 1}").strip() or f"Clip {clip_index + 1}",
        "hook_text": hook_text,
        "scheduled_date": scheduled_date,
        "original_scheduled_date": (raw_item.get("original_scheduled_date") or scheduled_date),
        "upload_request_id": (raw_item.get("upload_request_id") or "").strip() or None,
        "render_status": render_status,
        "post_status": post_status,
        "status": (raw_item.get("status") or "").strip().lower() or "pending",
        "last_error": (raw_item.get("last_error") or "").strip() or None,
        "attempts": {
            "render": max(0, int(attempts.get("render") or 0)),
            "post": max(0, int(attempts.get("post") or 0)),
        },
        "updated_at": float(raw_item.get("updated_at") or time.time()),
    }
    return item


def _derive_bulk_operation_item_status(item: Dict[str, Any], *, mode: str) -> str:
    render_required = _bulk_operation_requires_render(mode)
    post_required = _bulk_operation_requires_post(mode)
    render_status = item.get("render_status")
    post_status = item.get("post_status")

    if render_status == "running" or post_status == "running":
        return "running"
    if render_required and render_status == "failed":
        return "failed"
    if post_required and post_status == "failed":
        return "partial" if (not render_required or render_status in {"completed", "skipped"}) else "failed"
    if render_required and render_status not in {"completed", "skipped"}:
        return "pending"
    if post_required and post_status not in {"completed", "skipped"}:
        return "rendered" if render_required else "pending"
    return "completed"


def _bulk_operation_progress_message(state: Dict[str, Any]) -> str:
    total = int(state.get("total_count") or 0)
    completed = int(state.get("completed_count") or 0)
    rendered = int(state.get("render_completed_count") or 0)
    posted = int(state.get("post_completed_count") or 0)
    current_phase = (state.get("current_phase") or "").strip().lower()
    current_clip_index = state.get("current_clip_index")
    if state.get("status") == "pause_requested":
        return "Pause wird nach dem aktuellen Schritt angewendet."
    if state.get("status") == "stop_requested":
        return "Stop wird nach dem aktuellen Schritt angewendet."
    if state.get("status") == "paused":
        return state.get("message") or "Multi-Post pausiert."
    if state.get("status") == "stopped":
        return state.get("message") or "Multi-Post gestoppt."
    if state.get("status") == "completed":
        return f"Multi-Post abgeschlossen. {completed}/{total} fertig."
    if state.get("status") in {"partial", "failed"}:
        return state.get("message") or f"Multi-Post mit Fehlern beendet. {completed}/{total} fertig."
    if current_phase == "render" and current_clip_index is not None:
        return f"Rendert Clip {int(current_clip_index) + 1}. {rendered}/{total} gerendert."
    if current_phase == "post" and current_clip_index is not None:
        return f"Plant Clip {int(current_clip_index) + 1}. {posted}/{total} gepostet oder eingeplant."
    if state.get("status") == "running":
        return f"Multi-Post aktiv. {completed}/{total} komplett fertig."
    return state.get("message") or ""


def _finalize_bulk_operation_state(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(state, dict):
        return None

    mode = _normalize_bulk_operation_mode(state.get("mode"))
    items = [_normalize_bulk_operation_item(item, mode=mode, order_index=index) for index, item in enumerate(state.get("items") or [])]
    for item in items:
        item["status"] = _derive_bulk_operation_item_status(item, mode=mode)

    total_count = len(items)
    completed_count = sum(1 for item in items if item.get("status") == "completed")
    failed_count = sum(1 for item in items if item.get("status") in {"failed", "partial"})
    rendered_count = sum(1 for item in items if item.get("render_status") == "completed")
    posted_count = sum(1 for item in items if item.get("post_status") == "completed")
    pending_count = max(0, total_count - completed_count - failed_count)
    running_count = sum(1 for item in items if item.get("status") == "running")

    normalized = dict(state)
    normalized["mode"] = mode
    normalized["items"] = items
    normalized["total_count"] = total_count
    normalized["completed_count"] = completed_count
    normalized["failed_count"] = failed_count
    normalized["pending_count"] = pending_count
    normalized["running_count"] = running_count
    normalized["render_completed_count"] = rendered_count
    normalized["post_completed_count"] = posted_count
    normalized["updated_at"] = float(normalized.get("updated_at") or time.time())
    normalized["message"] = _bulk_operation_progress_message(normalized)
    return normalized


def _get_bulk_operation_state(job_id: str) -> Optional[Dict[str, Any]]:
    output_dir = _get_job_output_dir(job_id)
    manifest = load_job_manifest(output_dir)
    try:
        return _finalize_bulk_operation_state(manifest.get("bulk_operation"))
    except HTTPException:
        return None


def _set_job_result_bulk_operation(job_id: str, state: Optional[Dict[str, Any]]) -> None:
    if job_id in jobs:
        result = jobs[job_id].get("result")
        if isinstance(result, dict):
            if state is None:
                result.pop("bulk_operation", None)
            else:
                result["bulk_operation"] = state


def _persist_bulk_operation_state(job_id: str, state: Dict[str, Any], *, refresh_result: bool = False) -> Dict[str, Any]:
    normalized_state = _finalize_bulk_operation_state(state) or {}
    update_job_manifest(_get_job_output_dir(job_id), {"bulk_operation": normalized_state})
    _set_job_result_bulk_operation(job_id, normalized_state)
    if refresh_result:
        refreshed = _refresh_job_result(job_id)
        if refreshed is not None:
            refreshed["bulk_operation"] = normalized_state
            _set_job_result_bulk_operation(job_id, normalized_state)
    return normalized_state


def _clear_bulk_operation_runtime(job_id: str) -> None:
    bulk_operation_runtime.pop(job_id, None)


def _store_bulk_operation_runtime(job_id: str, runtime: Dict[str, Any]) -> None:
    bulk_operation_runtime[job_id] = runtime


def _build_bulk_runtime_from_request(req: Any) -> Dict[str, Any]:
    runtime_payload = getattr(req, "runtime", None)
    runtime_data = runtime_payload.model_dump() if hasattr(runtime_payload, "model_dump") else {}
    return {
        "provider": (runtime_data.get("provider") or "gemini").strip().lower(),
        "gemini_api_key": (runtime_data.get("gemini_api_key") or "").strip() or None,
        "gemini_model": (runtime_data.get("gemini_model") or "").strip() or None,
        "openai_api_key": (runtime_data.get("openai_api_key") or "").strip() or None,
        "openai_model": (runtime_data.get("openai_model") or "").strip() or None,
        "claude_api_key": (runtime_data.get("claude_api_key") or "").strip() or None,
        "claude_model": (runtime_data.get("claude_model") or "").strip() or None,
        "minimax_api_key": (runtime_data.get("minimax_api_key") or "").strip() or None,
        "minimax_auth_mode": (runtime_data.get("minimax_auth_mode") or "").strip() or None,
        "minimax_model": (runtime_data.get("minimax_model") or "").strip() or None,
        "ollama_base_url": (runtime_data.get("ollama_base_url") or "").strip() or None,
        "ollama_model": (runtime_data.get("ollama_model") or "").strip() or None,
        "pexels_api_key": (runtime_data.get("pexels_api_key") or "").strip() or None,
        "upload_post_api_key": (runtime_data.get("upload_post_api_key") or "").strip() or None,
        "upload_post_user_id": (runtime_data.get("upload_post_user_id") or "").strip() or None,
        "podcast_dm_relay_url": (runtime_data.get("podcast_dm_relay_url") or "").strip() or None,
        "podcast_dm_relay_password": (runtime_data.get("podcast_dm_relay_password") or "").strip() or None,
    }


def _build_bulk_render_headers(runtime: Dict[str, Any]) -> Dict[str, str]:
    provider = (runtime.get("provider") or "gemini").strip().lower()
    headers: Dict[str, str] = {
        "X-LLM-Provider": provider,
    }
    if provider == "gemini" and runtime.get("gemini_api_key"):
        headers["X-Gemini-Key"] = runtime["gemini_api_key"]
        if runtime.get("gemini_model"):
            headers["X-Gemini-Model"] = runtime["gemini_model"]
    if provider == "openai" and runtime.get("openai_api_key"):
        headers["X-OpenAI-Key"] = runtime["openai_api_key"]
        if runtime.get("openai_model"):
            headers["X-OpenAI-Model"] = runtime["openai_model"]
    if provider == "claude" and runtime.get("claude_api_key"):
        headers["X-Claude-Key"] = runtime["claude_api_key"]
        if runtime.get("claude_model"):
            headers["X-Claude-Model"] = runtime["claude_model"]
    if provider == "minimax" and runtime.get("minimax_api_key"):
        headers["X-Minimax-Key"] = runtime["minimax_api_key"]
        if runtime.get("minimax_auth_mode"):
            headers["X-Minimax-Auth-Mode"] = runtime["minimax_auth_mode"]
        if runtime.get("minimax_model"):
            headers["X-Minimax-Model"] = runtime["minimax_model"]
    if provider == "ollama":
        if runtime.get("ollama_base_url"):
            headers["X-Ollama-Base-Url"] = runtime["ollama_base_url"]
        if runtime.get("ollama_model"):
            headers["X-Ollama-Model"] = runtime["ollama_model"]
    if runtime.get("pexels_api_key"):
        headers["X-Pexels-Key"] = runtime["pexels_api_key"]
    return headers


def _recover_interrupted_bulk_operations() -> None:
    if not os.path.isdir(OUTPUT_DIR):
        return
    for job_id in os.listdir(OUTPUT_DIR):
        output_dir = os.path.join(OUTPUT_DIR, job_id)
        if not os.path.isdir(output_dir):
            continue
        manifest = load_job_manifest(output_dir)
        try:
            state = _finalize_bulk_operation_state(manifest.get("bulk_operation"))
        except HTTPException:
            state = None
        if not state:
            continue
        if state.get("status") in BULK_OPERATION_RUNNING_STATUSES:
            state["status"] = "paused"
            state["current_phase"] = None
            state["message"] = "Backend-Neustart erkannt. Multi-Post kann fortgesetzt werden."
            state["updated_at"] = time.time()
            update_job_manifest(output_dir, {"bulk_operation": state})


def _write_metadata(metadata_path: str, data: Dict[str, Any]) -> None:
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _analysis_context_path(output_dir: str) -> str:
    return os.path.join(output_dir, "analysis_context.json")


def _normalize_analysis_context(value: Any) -> Dict[str, str]:
    data = value if isinstance(value, dict) else {}
    return {
        "profile_name": re.sub(r"\s+", " ", str(data.get("profile_name") or data.get("upload_post_profile") or "")).strip()[:120],
        "profile_context": str(data.get("profile_context") or "").strip()[:12000],
        "job_instructions": str(data.get("job_instructions") or "").strip()[:12000],
    }


def _write_analysis_context(output_dir: str, value: Any) -> Dict[str, str]:
    normalized = _normalize_analysis_context(value)
    path = _analysis_context_path(output_dir)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)
    return normalized


def _clamp_zoom_factor(value: Any, default: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if not math.isfinite(numeric):
        numeric = default
    return max(0.0, min(2.0, round(numeric, 2)))


DEFAULT_START_ZOOM_FACTOR = 0.0
DEFAULT_TARGET_ZOOM_FACTOR = 0.45
DEFAULT_PATTERN_FLASH_MODE = "every_30s"
PATTERN_FLASH_MODE_VALUES = {"none", "start", "every_30s", "every_20s", "every_10s", "every_8s", "every_5s"}


def _normalize_pattern_flash_mode(value: Any, default: str = DEFAULT_PATTERN_FLASH_MODE) -> str:
    normalized = _normalize_unicode_text(value).strip().lower().replace("-", "_")
    aliases = {
        "": default,
        "off": "none",
        "false": "none",
        "disabled": "none",
        "no": "none",
        "never": "none",
        "kein": "none",
        "keine": "none",
        "beginning": "start",
        "begin": "start",
        "initial": "start",
        "intro": "start",
        "only_start": "start",
        "start_only": "start",
        "anfang": "start",
        "nur_anfang": "start",
        "only_at_start": "start",
        "30": "every_30s",
        "30s": "every_30s",
        "every_30": "every_30s",
        "every30": "every_30s",
        "very_rare": "every_30s",
        "sehr_selten": "every_30s",
        "20": "every_20s",
        "20s": "every_20s",
        "every_20": "every_20s",
        "every20": "every_20s",
        "10": "every_10s",
        "10s": "every_10s",
        "every_10": "every_10s",
        "every10": "every_10s",
        "rare": "every_10s",
        "selten": "every_10s",
        "8": "every_8s",
        "8s": "every_8s",
        "every_8": "every_8s",
        "every8": "every_8s",
        "normal": "every_8s",
        "medium": "every_8s",
        "5": "every_5s",
        "5s": "every_5s",
        "every_5": "every_5s",
        "every5": "every_5s",
        "frequent": "every_5s",
        "haeufig": "every_5s",
        "häufig": "every_5s",
        "very_frequent": "every_5s",
        "sehr_haeufig": "every_5s",
        "sehr_häufig": "every_5s",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in PATTERN_FLASH_MODE_VALUES:
        return default if default in PATTERN_FLASH_MODE_VALUES else DEFAULT_PATTERN_FLASH_MODE
    return normalized


def _normalize_transcription_language(value: Any) -> str:
    if value is None:
        return ""
    normalized = str(value).strip().lower().replace("_", "-")
    if not normalized or normalized == "auto":
        return ""
    normalized = normalized.split("-")[0]
    if re.fullmatch(r"[a-z]{2,8}", normalized):
        return normalized
    return ""


def _normalize_transcription_export_formats(raw_value: Any, *, with_timestamps: bool) -> List[str]:
    if isinstance(raw_value, str):
        values = [item.strip().lower() for item in raw_value.split(",") if item.strip()]
    elif isinstance(raw_value, list):
        values = [str(item).strip().lower() for item in raw_value if str(item).strip()]
    else:
        values = []

    if not values:
        values = ["txt", "json", "srt", "vtt"] if with_timestamps else ["txt", "json"]

    normalized: List[str] = []
    for value in values:
        if value not in TRANSCRIPTION_ALLOWED_EXPORT_FORMATS:
            continue
        if not with_timestamps and value in {"srt", "vtt", "tsv"}:
            continue
        if value not in normalized:
            normalized.append(value)

    if "txt" not in normalized:
        normalized.insert(0, "txt")
    if "json" not in normalized:
        normalized.append("json")
    return normalized


def _transcription_file_url(session_id: str, filename: str) -> str:
    quoted_session = urllib.parse.quote(session_id)
    quoted_name = urllib.parse.quote(filename)
    return f"/videos/transcriptions/{quoted_session}/{quoted_name}"


def _transcription_compact_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds or 0.0) * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _transcription_srt_timestamp(seconds: float) -> str:
    return _transcription_compact_timestamp(seconds).replace(".", ",")


def _transcription_last_end(transcript: Optional[Dict[str, Any]]) -> float:
    segments = (transcript or {}).get("segments") or []
    if not segments:
        return 0.0
    try:
        return max(float((segment or {}).get("end") or 0.0) for segment in segments if isinstance(segment, dict))
    except Exception:
        return 0.0


def _prepare_media_for_transcription(input_path: str) -> str:
    temp_audio_path = f"/tmp/openshorts_transcribe_{os.getpid()}_{int(time.time() * 1000)}.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-fflags", "+discardcorrupt",
        "-err_detect", "ignore_err",
        "-i", input_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        temp_audio_path,
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 0:
            return temp_audio_path
    except Exception as exc:
        print(f"⚠️ Transcription audio normalization failed, using source container directly: {exc}")

    try:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
    except Exception:
        pass
    return input_path


def _transcribe_media_file(media_path: str, *, preferred_language: str = "", word_timestamps: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from whisper_runtime import transcribe_with_runtime

    prepared_path = _prepare_media_for_transcription(media_path)
    cleanup_prepared = prepared_path != media_path
    german_quality_override = preferred_language == "de"
    try:
        segments, info, runtime_meta = transcribe_with_runtime(
            prepared_path,
            word_timestamps=word_timestamps,
            language=preferred_language or None,
            model_override="large-v3" if german_quality_override else None,
            cpu_model_override="large-v3" if german_quality_override else None,
        )
    finally:
        if cleanup_prepared:
            try:
                if os.path.exists(prepared_path):
                    os.remove(prepared_path)
            except Exception:
                pass

    transcript_segments: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []
    for segment in segments:
        text = str(getattr(segment, "text", "") or "")
        full_text_parts.append(text.strip())
        segment_payload = {
            "text": text,
            "start": float(getattr(segment, "start", 0.0) or 0.0),
            "end": float(getattr(segment, "end", 0.0) or 0.0),
            "words": [],
        }
        if word_timestamps and getattr(segment, "words", None):
            for word in segment.words:
                segment_payload["words"].append({
                    "word": str(getattr(word, "word", "") or "").strip(),
                    "start": float(getattr(word, "start", 0.0) or 0.0),
                    "end": float(getattr(word, "end", 0.0) or 0.0),
                    "probability": float(getattr(word, "probability", 0.0) or 0.0),
                })
        transcript_segments.append(segment_payload)

    transcript = {
        "text": " ".join(part for part in full_text_parts if part).strip(),
        "segments": transcript_segments,
        "language": getattr(info, "language", "") or "",
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
    }
    return transcript, runtime_meta


def _build_transcription_text_lines(transcript: Dict[str, Any], *, with_timestamps: bool) -> List[str]:
    segments = transcript.get("segments") or []
    if not with_timestamps:
        joined = []
        for segment in segments:
            text = str((segment or {}).get("text") or "").strip()
            if text:
                joined.append(text)
        plain_text = "\n".join(joined).strip()
        return [plain_text] if plain_text else []

    lines: List[str] = []
    for segment in segments:
        text = str((segment or {}).get("text") or "").strip()
        if not text:
            continue
        start = float((segment or {}).get("start") or 0.0)
        end = float((segment or {}).get("end") or start)
        lines.append(f"[{_transcription_compact_timestamp(start)} - {_transcription_compact_timestamp(end)}] {text}")
    return lines


def _build_transcription_json_payload(
    transcript: Dict[str, Any],
    *,
    with_timestamps: bool,
    runtime_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "language": transcript.get("language"),
        "language_probability": transcript.get("language_probability"),
        "text": transcript.get("text") or "",
        "runtime": runtime_meta or {},
    }
    segments = transcript.get("segments") or []
    if with_timestamps:
        payload["segments"] = segments
    else:
        payload["segments"] = [
            {
                "text": str((segment or {}).get("text") or "").strip(),
            }
            for segment in segments
            if str((segment or {}).get("text") or "").strip()
        ]
    return payload


def _write_transcription_exports(
    session_id: str,
    transcript: Dict[str, Any],
    *,
    with_timestamps: bool,
    export_formats: List[str],
    runtime_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    from subtitles import build_subtitle_blocks

    session_dir = os.path.join(TRANSCRIPTION_OUTPUT_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    exports: List[Dict[str, Any]] = []
    duration = _transcription_last_end(transcript)
    blocks = build_subtitle_blocks(transcript, 0.0, duration, max_chars=42, max_duration=4.4) if with_timestamps else []

    def register_file(filename: str, content: str) -> None:
        path = os.path.join(session_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        exports.append({
            "format": filename.rsplit(".", 1)[-1].lower(),
            "filename": filename,
            "url": _transcription_file_url(session_id, filename),
            "size_bytes": os.path.getsize(path),
        })

    if "txt" in export_formats:
        register_file("transcript.txt", "\n".join(_build_transcription_text_lines(transcript, with_timestamps=with_timestamps)).strip() + "\n")

    if "json" in export_formats:
        register_file(
            "transcript.json",
            json.dumps(
                _build_transcription_json_payload(
                    transcript,
                    with_timestamps=with_timestamps,
                    runtime_meta=runtime_meta,
                ),
                indent=2,
                ensure_ascii=False,
            ) + "\n",
        )

    if with_timestamps and "srt" in export_formats and blocks:
        srt_lines: List[str] = []
        for index, block in enumerate(blocks, start=1):
            srt_lines.extend([
                str(index),
                f"{_transcription_srt_timestamp(block['start'])} --> {_transcription_srt_timestamp(block['end'])}",
                str(block.get("text") or "").strip(),
                "",
            ])
        register_file("transcript.srt", "\n".join(srt_lines).strip() + "\n")

    if with_timestamps and "vtt" in export_formats and blocks:
        vtt_lines = ["WEBVTT", ""]
        for block in blocks:
            vtt_lines.extend([
                f"{_transcription_compact_timestamp(block['start'])} --> {_transcription_compact_timestamp(block['end'])}",
                str(block.get("text") or "").strip(),
                "",
            ])
        register_file("transcript.vtt", "\n".join(vtt_lines).strip() + "\n")

    if with_timestamps and "tsv" in export_formats:
        tsv_lines = ["start\tend\ttext"]
        for segment in transcript.get("segments") or []:
            text = str((segment or {}).get("text") or "").replace("\t", " ").strip()
            if not text:
                continue
            start = _transcription_compact_timestamp(float((segment or {}).get("start") or 0.0))
            end = _transcription_compact_timestamp(float((segment or {}).get("end") or 0.0))
            tsv_lines.append(f"{start}\t{end}\t{text}")
        register_file("transcript.tsv", "\n".join(tsv_lines).strip() + "\n")

    return exports


async def _run_transcription_job(session_id: str) -> None:
    session = transcription_jobs.get(session_id)
    if not session:
        return

    session["status"] = "processing"
    session["message"] = "Whisper transkribiert die Datei."
    session["updated_at"] = time.time()

    input_path = session.get("input_path")
    if not input_path or not os.path.exists(input_path):
        session["status"] = "failed"
        session["error"] = "Quelldatei fuer die Transkription wurde nicht gefunden."
        session["updated_at"] = time.time()
        return

    preferred_language = _normalize_transcription_language(session.get("preferred_language"))
    with_timestamps = bool(session.get("with_timestamps"))
    export_formats = _normalize_transcription_export_formats(
        session.get("export_formats"),
        with_timestamps=with_timestamps,
    )

    loop = asyncio.get_event_loop()
    try:
        transcript, runtime_meta = await loop.run_in_executor(
            None,
            lambda: _transcribe_media_file(
                input_path,
                preferred_language=preferred_language,
                word_timestamps=with_timestamps,
            ),
        )
        exports = await loop.run_in_executor(
            None,
            lambda: _write_transcription_exports(
                session_id,
                transcript,
                with_timestamps=with_timestamps,
                export_formats=export_formats,
                runtime_meta=runtime_meta,
            ),
        )

        preview_lines = _build_transcription_text_lines(transcript, with_timestamps=with_timestamps)
        session.update({
            "status": "completed",
            "message": "Transkription abgeschlossen.",
            "error": None,
            "runtime": runtime_meta,
            "transcript": {
                "language": transcript.get("language"),
                "language_probability": transcript.get("language_probability"),
                "text": transcript.get("text") or "",
                "preview": "\n".join(preview_lines[:80]).strip(),
                "segment_count": len(transcript.get("segments") or []),
                "duration_seconds": round(_transcription_last_end(transcript), 3),
            },
            "exports": exports,
            "updated_at": time.time(),
            "completed_at": time.time(),
        })
    except Exception as exc:
        session.update({
            "status": "failed",
            "message": "Transkription fehlgeschlagen.",
            "error": str(exc),
            "updated_at": time.time(),
        })


def _serialize_transcription_session(session_id: str, session: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(session, dict):
        raise HTTPException(status_code=404, detail="Transkriptions-Session nicht gefunden.")
    return {
        "session_id": session_id,
        "status": session.get("status") or "queued",
        "message": session.get("message") or "",
        "error": session.get("error"),
        "filename": session.get("filename"),
        "preferred_language": session.get("preferred_language") or "auto",
        "with_timestamps": bool(session.get("with_timestamps")),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "completed_at": session.get("completed_at"),
        "runtime": session.get("runtime") or {},
        "transcript": session.get("transcript") or None,
        "exports": session.get("exports") or [],
    }


def _serialize_longform_file(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(item)
    payload["normalized_url"] = media_url_from_path(item.get("normalized_path"))
    payload["proxy_url"] = media_url_from_path(item.get("proxy_path"))
    return payload


def _serialize_longform_bundle(project_id: str, *, log_limit: int = 200) -> Dict[str, Any]:
    bundle = load_longform_project_bundle(project_id, log_limit=log_limit)
    project = dict(bundle["project"])
    files = project.get("files") or {}
    project["files"] = {
        role: [_serialize_longform_file(item) for item in role_files or []]
        for role, role_files in files.items()
    }
    state = dict(bundle["state"])
    state["can_start"] = state.get("status") in {"idle", "failed", "paused", "completed", "stopped"}
    state["can_resume"] = bool(state.get("resume_available"))
    return {
        "project": project,
        "state": state,
        "logs": bundle["logs"],
    }


def _longform_project_exists_or_404(project_id: str) -> Dict[str, Any]:
    try:
        return load_longform_project_bundle(project_id, log_limit=0)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Longform-Projekt nicht gefunden.")


def _resolve_longform_source_mount_root() -> str:
    return os.path.realpath(os.environ.get("LONGFORM_SOURCE_MOUNT_ROOT", "/app/output/longform_source_mount"))


def _resolve_longform_source_host_root() -> str:
    raw = str(os.environ.get("LONGFORM_SOURCE_HOST_DIR", "") or "").strip()
    return os.path.realpath(raw) if raw else ""


def _resolve_longform_allowed_source_roots() -> List[str]:
    raw = str(os.environ.get("LONGFORM_ALLOWED_SOURCE_ROOTS", _resolve_longform_source_mount_root()) or "")
    roots: List[str] = []
    for item in raw.split(os.pathsep):
        candidate = str(item or "").strip()
        if not candidate:
            continue
        candidate_real = os.path.realpath(candidate)
        if os.path.isdir(candidate_real):
            roots.append(candidate_real)
    deduped: List[str] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return deduped


_LONGFORM_MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".mts", ".m2ts", ".wmv",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff",
}


def _is_likely_longform_media_file(path: str) -> bool:
    ext = os.path.splitext(str(path or ""))[1].strip().lower()
    return ext in _LONGFORM_MEDIA_EXTENSIONS


def _search_longform_source_files(query: str, *, limit: int = 25, exact: bool = False) -> List[Dict[str, Any]]:
    query_text = str(query or "").strip()
    if not query_text:
        return []
    query_lower = query_text.lower()
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for root in _resolve_longform_allowed_source_roots():
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".")
                and name.lower() not in {"system volume information", "$recycle.bin"}
            ]
            for filename in filenames:
                if filename.startswith(".") or filename.startswith("._"):
                    continue
                if not _is_likely_longform_media_file(filename):
                    continue
                name_lower = filename.lower()
                matched = name_lower == query_lower if exact else query_lower in name_lower
                if not matched:
                    continue

                full_path = os.path.realpath(os.path.join(current_root, filename))
                if full_path in seen or not os.path.isfile(full_path):
                    continue
                try:
                    if os.path.commonpath([full_path, root]) != root:
                        continue
                except Exception:
                    continue
                seen.add(full_path)
                results.append({
                    "name": filename,
                    "path": full_path,
                    "relative_path": os.path.relpath(full_path, root),
                    "root": root,
                    "size_bytes": os.path.getsize(full_path),
                })
                if len(results) >= limit:
                    return results
    return results


def _longform_source_roots_have_media() -> bool:
    for root in _resolve_longform_allowed_source_roots():
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".")
                and name.lower() not in {"system volume information", "$recycle.bin"}
            ]
            for filename in filenames:
                if filename.startswith(".") or filename.startswith("._"):
                    continue
                if _is_likely_longform_media_file(filename):
                    return True
    return False


def _suggest_longform_export_fps(raw_fps: Any, fallback: int = 24) -> int:
    try:
        fps = float(raw_fps or 0.0)
    except Exception:
        fps = 0.0
    if fps <= 0.0:
        return fallback

    common_targets = [24, 25, 30, 50, 60]
    if abs(fps - 23.976) <= 0.2:
        return 24
    if abs(fps - 29.97) <= 0.2:
        return 30
    if abs(fps - 59.94) <= 0.3:
        return 60
    nearest = min(common_targets, key=lambda item: abs(fps - item))
    if abs(fps - nearest) <= 0.6:
        return nearest
    return max(23, min(60, int(round(fps))))


def _maybe_apply_longform_export_fps_from_metadata(project_id: str, project: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(project.get("config") or {})
    existing_files = sum(len(items or []) for items in (project.get("files") or {}).values())
    current_fps = int(config.get("export_fps") or 24)
    should_autoset = existing_files == 0 or current_fps == 24
    if not should_autoset:
        return project

    suggested_fps = _suggest_longform_export_fps(metadata.get("fps"), fallback=current_fps or 24)
    if suggested_fps == current_fps and existing_files != 0:
        return project

    config["export_fps"] = suggested_fps
    return update_longform_project(project_id, config=config)


def _resolve_longform_relative_source_path(raw_path: str) -> Optional[str]:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return None

    allowed_roots = _resolve_longform_allowed_source_roots()
    normalized = normalized.replace("\\", os.sep)

    if os.sep in normalized or "/" in normalized:
        relative_candidate = normalized.lstrip("/\\")
        for root in allowed_roots:
            candidate = os.path.realpath(os.path.join(root, relative_candidate))
            try:
                if os.path.commonpath([candidate, root]) != root:
                    continue
            except Exception:
                continue
            if os.path.isfile(candidate):
                return candidate

    exact_matches = _search_longform_source_files(normalized, limit=10, exact=True)
    if len(exact_matches) == 1:
        return exact_matches[0]["path"]
    if len(exact_matches) > 1:
        suggestions = ", ".join(item["relative_path"] for item in exact_matches[:5])
        raise HTTPException(
            status_code=409,
            detail=f"Dateiname ist nicht eindeutig: {raw_path}. Bitte einen genaueren Pfad angeben. Treffer: {suggestions}",
        )
    return None


def _translate_longform_source_path(raw_path: str) -> str:
    candidate = os.path.realpath(os.path.expanduser(str(raw_path or "").strip()))
    host_root = _resolve_longform_source_host_root()
    mount_root = _resolve_longform_source_mount_root()
    if host_root:
        try:
            if os.path.commonpath([candidate, host_root]) == host_root:
                relative = os.path.relpath(candidate, host_root)
                return os.path.realpath(os.path.join(mount_root, relative))
        except Exception:
            pass
    return candidate


def _validate_longform_source_path(raw_path: str) -> str:
    normalized_raw = str(raw_path or "").strip()
    translated: Optional[str] = None
    if normalized_raw and not os.path.isabs(os.path.expanduser(normalized_raw)):
        translated = _resolve_longform_relative_source_path(normalized_raw)
    if not translated:
        translated = _translate_longform_source_path(normalized_raw)
    if not translated or not os.path.exists(translated):
        raise HTTPException(status_code=400, detail=f"Quelldatei nicht gefunden oder nicht gemountet: {raw_path}")
    if not os.path.isfile(translated):
        raise HTTPException(status_code=400, detail=f"Pfad ist keine Datei: {raw_path}")

    allowed_roots = _resolve_longform_allowed_source_roots()
    if not allowed_roots:
        raise HTTPException(status_code=500, detail="Keine Longform-Quellordner freigegeben. Bitte LONGFORM_ALLOWED_SOURCE_ROOTS konfigurieren.")

    for root in allowed_roots:
        try:
            if os.path.commonpath([translated, root]) == root:
                return translated
        except Exception:
            continue
    raise HTTPException(status_code=400, detail=f"Pfad liegt ausserhalb der freigegebenen Longform-Quellordner: {raw_path}")


def _longform_analysis_result_path(project_id: str) -> str:
    return os.path.join(longform_project_subdir(project_id, "analysis"), "analysis_result.json")


def _load_longform_analysis_result_or_404(project_id: str) -> Dict[str, Any]:
    path = _longform_analysis_result_path(project_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Noch kein Longform-Analyseergebnis vorhanden. Bitte Pipeline zuerst erfolgreich exportieren.")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analyseergebnis konnte nicht geladen werden: {exc}")


def _resolve_longform_media_path(item: Dict[str, Any]) -> Optional[str]:
    candidate = item.get("normalized_path") or item.get("stored_path")
    if candidate and os.path.exists(candidate):
        return candidate
    return None


def _resolve_longform_role_source_at_time(project: Dict[str, Any], role: str, global_time: float) -> Optional[Dict[str, Any]]:
    for item in sorted((project.get("files") or {}).get(role) or [], key=lambda raw: float(raw.get("global_start_sec") or 0.0)):
        file_start = float(item.get("global_start_sec") or 0.0)
        file_end = float(item.get("global_end_sec") or file_start)
        if global_time < file_start or global_time > file_end:
            continue
        source_path = _resolve_longform_media_path(item)
        if not source_path:
            continue
        local_time = max(0.0, min(float(item.get("duration_sec") or 0.0), global_time - file_start))
        return {
            "file": item,
            "source_path": source_path,
            "local_time": local_time,
            "global_time": global_time,
        }
    return None


def _capture_longform_video_frame(input_path: str, output_path: str, timestamp_sec: float) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{max(0.0, float(timestamp_sec)):.3f}",
        "-i", input_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_priority_kwargs())


def _select_longform_still_candidates(project: Dict[str, Any], analysis_result: Dict[str, Any], role: str, *, count: int = 6) -> List[Dict[str, Any]]:
    import random
    turns = [
        item for item in (analysis_result.get("speaker_turns") or [])
        if str(item.get("role") or "").strip().lower() == role and float(item.get("end") or 0.0) - float(item.get("start") or 0.0) >= 1.0
    ]

    # Collect ALL possible timestamps - we'll randomize from these
    all_candidates: List[Dict[str, Any]] = []

    # From analysis: RANDOM positions within speaker turns
    for turn in turns:
        start_t = float(turn.get("start") or 0.0)
        end_t = float(turn.get("end") or 0.0)
        duration = end_t - start_t

        # Generate multiple random positions per turn
        for _ in range(max(1, int(duration / 5))):  # ~1 per 5 seconds
            random_offset = random.random() * duration
            timestamp = start_t + random_offset

            resolved = _resolve_longform_role_source_at_time(project, role, timestamp)
            if not resolved:
                continue

            all_candidates.append({
                "global_time": round(timestamp, 3),
                "local_time": round(float(resolved["local_time"]), 3),
                "source_path": resolved["source_path"],
                "file_name": resolved["file"].get("original_name"),
                "confidence": round(float(turn.get("confidence") or 0.0), 3),
            })

    # From clips: RANDOM positions (not fixed ratios)
    role_files = sorted((project.get("files") or {}).get(role) or [], key=lambda raw: float(raw.get("global_start_sec") or 0.0))
    for item in role_files:
        source_path = _resolve_longform_media_path(item)
        duration = float(item.get("duration_sec") or 0.0)
        global_start = float(item.get("global_start_sec") or 0.0)

        if not source_path or duration <= 0.2:
            continue

        # Generate MANY random candidates per clip
        num_random = max(10, int(duration / 8))  # ~1 per 8 seconds minimum
        for _ in range(num_random):
            # Pure random within the clip
            local_random = random.uniform(0.05, 0.95) * duration
            global_time = global_start + local_random

            all_candidates.append({
                "global_time": round(global_time, 3),
                "local_time": round(local_random, 3),
                "source_path": source_path,
                "file_name": item.get("original_name"),
                "confidence": 0.0,
            })

    # Shuffle - this is the key for true randomness
    random.shuffle(all_candidates)

    # Select candidates ensuring distribution
    selected: List[Dict[str, Any]] = []
    used_times: List[float] = []

    for candidate in all_candidates:
        if len(selected) >= count:
            break

        # Ensure minimum distance between selected frames
        midpoint = candidate["global_time"]
        if any(abs(midpoint - existing) < 20.0 for existing in used_times):
            continue

        selected.append(candidate)
        used_times.append(midpoint)

    return selected[:count]


def _normalize_thumbnail_provider_list(values: List[str]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        candidate = str(value or "").strip().lower()
        if candidate not in {"gemini", "openai", "midjourney"}:
            continue
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _persist_longform_artifact_patch(project_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    bundle = _longform_project_exists_or_404(project_id)
    artifacts = dict(bundle["project"].get("artifacts") or {})
    artifacts.update(patch or {})
    return update_longform_project(project_id, artifacts=artifacts)


def _normalize_longform_text_overlay_suggestions(values: Any, *, limit: int = 10) -> List[str]:
    normalized: List[str] = []
    raw_values = values if isinstance(values, list) else []
    for item in raw_values:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        text = text.strip(' "\'`')
        if not text or text in normalized:
            continue
        normalized.append(text[:80])
        if len(normalized) >= max(1, min(int(limit or 10), 20)):
            break
    return normalized


def _default_longform_text_overlay_suggestions(language: str) -> List[str]:
    normalized_language = _normalize_language_hint(language) or "de"
    if normalized_language == "en":
        return [
            "THIS CHANGED EVERYTHING",
            "THE TURNING POINT",
            "NOBODY EXPECTED THIS",
            "THE REAL REASON",
            "THAT WAS THE MOMENT",
            "WHAT REALLY HAPPENED",
            "HE DIDN'T SEE THIS COMING",
            "THIS HIT HARD",
            "THE BIG MISTAKE",
            "AFTER THAT EVERYTHING SHIFTED",
        ]
    return [
        "DAS AENDERT ALLES",
        "HIER KIPPTE ES",
        "DAS WAR DER MOMENT",
        "DIE WAHRE URSACHE",
        "DAMIT HAT NIEMAND GERECHNET",
        "AB DA WAR ALLES ANDERS",
        "DAS TRIFFT JEDEN",
        "GENAU DAS IST DER FEHLER",
        "DAS HAT ALLES VERAENDERT",
        "DER ENTSCHEIDENDE PUNKT",
    ]


def _load_longform_transcript_excerpt(project_id: str, project: Dict[str, Any], *, max_chars: int = 7000) -> str:
    config = project.get("config") or {}
    primary_role = str(
        config.get("primary_audio_camera")
        or ("host" if project.get("mode") == "interview" else "single")
    ).strip().lower()
    ordered_roles: List[str] = []
    if primary_role:
        ordered_roles.append(primary_role)
    for role in active_camera_roles(project.get("mode") or "single"):
        if role not in ordered_roles:
            ordered_roles.append(role)

    transcript_root = longform_project_subdir(project_id, "transcripts")
    chunks: List[str] = []
    total_chars = 0
    seen_file_ids = set()

    for role in ordered_roles:
        for item in (project.get("files") or {}).get(role) or []:
            file_id = str(item.get("id") or "").strip()
            if not file_id or file_id in seen_file_ids:
                continue
            seen_file_ids.add(file_id)
            candidate_paths = [
                str(item.get("transcript_path") or "").strip(),
                os.path.join(transcript_root, f"{file_id}.json"),
            ]
            transcript_payload = None
            for candidate_path in candidate_paths:
                if not candidate_path or not os.path.exists(candidate_path):
                    continue
                try:
                    with open(candidate_path, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    transcript_payload = payload.get("transcript") if isinstance(payload, dict) else None
                except Exception:
                    transcript_payload = None
                if isinstance(transcript_payload, dict):
                    break
            if not isinstance(transcript_payload, dict):
                continue
            transcript_text = str(transcript_payload.get("text") or "").strip()
            if not transcript_text:
                segments = transcript_payload.get("segments") or []
                transcript_text = " ".join(
                    str(segment.get("text") or "").strip()
                    for segment in segments
                    if isinstance(segment, dict)
                ).strip()
            if not transcript_text:
                continue
            snippet = f"[{role.upper()}] {transcript_text}"
            remaining = max_chars - total_chars
            if remaining <= 0:
                break
            if len(snippet) > remaining:
                snippet = snippet[:remaining].rstrip()
            chunks.append(snippet)
            total_chars += len(snippet) + 2
        if total_chars >= max_chars:
            break

    return "\n\n".join(chunks).strip()


def _build_longform_thumbnail_text_overlay_prompt(
    *,
    project: Dict[str, Any],
    base_prompt: str,
    transcript_excerpt: str,
    count: int,
) -> str:
    config = project.get("config") or {}
    mode = str(project.get("mode") or "single").strip().lower()
    language = _normalize_language_hint(config.get("analysis_language")) or "de"
    primary_role = str(
        config.get("primary_audio_camera")
        or ("host" if mode == "interview" else "single")
    ).strip().lower()
    project_name = str(project.get("project_name") or "").strip()
    role_labels = ", ".join(active_camera_roles(mode))
    response_language = "German" if language == "de" else "English"

    parts = [
        "You generate short high-click thumbnail text overlays for longform podcast/video thumbnails.",
        f"Return exactly {count} options as JSON only with this schema: {{\"overlays\": [\"...\"]}}",
        f"Write the overlays in {response_language}.",
        "Rules:",
        "- 2 to 8 words each.",
        "- Maximum 42 characters each.",
        "- Concrete, emotionally clear, and easy to read on a thumbnail.",
        "- No emojis, no hashtags, no quotation marks, no trailing punctuation.",
        "- Avoid generic filler like 'watch until the end'.",
        "- Make the options distinct from each other.",
        "- They should feel like overlay text, not full titles.",
        f"Project name: {project_name or 'Longform project'}",
        f"Project mode: {mode}",
        f"Available speaker roles: {role_labels}",
        f"Primary audio role: {primary_role or 'unknown'}",
    ]
    cleaned_prompt = str(base_prompt or "").strip()
    if cleaned_prompt:
        parts.extend([
            "The current thumbnail prompt template is below. Respect its intent and use the <text_overlay> placeholder as the thing you are generating:",
            cleaned_prompt,
        ])
    if transcript_excerpt:
        parts.extend([
            "Transcript excerpt for context:",
            transcript_excerpt,
        ])
    parts.append("Return JSON only.")
    return "\n".join(parts)


def _call_longform_text_overlay_provider(ai_config: Dict[str, Any], prompt: str, *, timeout_seconds: int = 45) -> Dict[str, Any]:
    provider = str(ai_config.get("provider") or "ollama").strip().lower()

    def _do_call() -> Dict[str, Any]:
        def _extract_overlay_json(text: Any) -> Optional[Dict[str, Any]]:
            if not text:
                return None
            cleaned = str(text).strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            try:
                payload = json.loads(cleaned)
                return payload if isinstance(payload, dict) else None
            except json.JSONDecodeError:
                pass
            start_idx = cleaned.find("{")
            end_idx = cleaned.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                try:
                    payload = json.loads(cleaned[start_idx:end_idx + 1])
                    return payload if isinstance(payload, dict) else None
                except json.JSONDecodeError:
                    return None
            return None

        def _extract_chat_text(payload: Any) -> str:
            if isinstance(payload, str):
                return payload
            if isinstance(payload, dict):
                return _extract_chat_text(payload.get("content"))
            if isinstance(payload, list):
                parts = []
                for item in payload:
                    if isinstance(item, str):
                        stripped = item.strip()
                        if stripped:
                            parts.append(stripped)
                        continue
                    if isinstance(item, dict):
                        candidate_text = item.get("text")
                        if candidate_text is None:
                            candidate_text = item.get("content")
                        if candidate_text is None and isinstance(item.get("output_text"), str):
                            candidate_text = item.get("output_text")
                        extracted = _extract_chat_text(candidate_text)
                        if extracted.strip():
                            parts.append(extracted.strip())
                return "\n".join(parts).strip()
            return ""

        def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], *, timeout: int = 180) -> Dict[str, Any]:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as exc:
                try:
                    error_body = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    error_body = ""
                detail = error_body[:2000] if error_body else str(exc.reason or "")
                raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {detail}") from exc

        if provider == "off":
            raise RuntimeError("KI-Provider ist deaktiviert.")
        if provider == "gemini":
            api_key = str(ai_config.get("gemini_api_key") or "").strip()
            if not api_key:
                raise RuntimeError("Gemini API-Key fehlt.")
            client = genai.Client(api_key=api_key)
            model_name = str(ai_config.get("gemini_model") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
            response = client.models.generate_content(model=model_name, contents=prompt)
            payload = _extract_overlay_json(getattr(response, "text", "") or "")
            if not isinstance(payload, dict):
                raise RuntimeError("Gemini lieferte kein gueltiges JSON fuer Text-Overlays.")
            return payload
        if provider == "openai":
            api_key = str(ai_config.get("openai_api_key") or "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY fehlt.")
            model_name = str(ai_config.get("openai_model") or "gpt-4.1-mini").strip() or "gpt-4.1-mini"
            body = _post_json(
                "https://api.openai.com/v1/chat/completions",
                {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "You are a senior short-form editor. Reply only with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                    "max_tokens": 1200,
                },
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise RuntimeError("OpenAI lieferte keine choices.")
            payload = _extract_overlay_json(_extract_chat_text((choices[0] or {}).get("message")))
            if not isinstance(payload, dict):
                raise RuntimeError("OpenAI lieferte kein gueltiges JSON fuer Text-Overlays.")
            return payload
        if provider == "claude":
            api_key = str(ai_config.get("claude_api_key") or "").strip()
            if not api_key:
                raise RuntimeError("CLAUDE_API_KEY fehlt.")
            model_name = str(ai_config.get("claude_model") or "claude-3-5-sonnet-latest").strip() or "claude-3-5-sonnet-latest"
            body = _post_json(
                "https://api.anthropic.com/v1/messages",
                {
                    "model": model_name,
                    "max_tokens": 1200,
                    "temperature": 0.2,
                    "system": "You are a senior short-form editor. Reply only with valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                {
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            payload = _extract_overlay_json(_extract_chat_text(body.get("content")))
            if not isinstance(payload, dict):
                raise RuntimeError("Claude lieferte kein gueltiges JSON fuer Text-Overlays.")
            return payload
        if provider == "minimax":
            api_key = str(ai_config.get("minimax_api_key") or "").strip()
            if not api_key:
                raise RuntimeError("MINIMAX_API_KEY fehlt.")
            auth_mode = str(ai_config.get("minimax_auth_mode") or "token_plan").strip().lower()
            requested_model = str(ai_config.get("minimax_model") or "MiniMax-M3").strip() or "MiniMax-M3"
            base_url = str(ai_config.get("minimax_base_url") or os.environ.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
            chat_url = (
                base_url
                if base_url.endswith("/chat/completions")
                else base_url[: -len("/text/chatcompletion_v2")] + "/chat/completions"
                if base_url.endswith("/text/chatcompletion_v2")
                else f"{base_url}/chat/completions"
            )
            candidate_models = [requested_model]
            if auth_mode == "token_plan":
                candidate_models.extend(["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5-highspeed", "MiniMax-M2.5", "MiniMax-M2.1-highspeed", "MiniMax-M2.1", "MiniMax-M2"])
            else:
                candidate_models.extend(["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"])
            deduped_models = []
            for candidate_model in candidate_models:
                if candidate_model and candidate_model not in deduped_models:
                    deduped_models.append(candidate_model)
            last_detail = ""
            for model_name in deduped_models:
                is_m3 = str(model_name).strip().lower() == "minimax-m3"
                thinking_type = str(os.environ.get("MINIMAX_THINKING_TYPE", "disabled") or "disabled").strip().lower()
                if thinking_type not in {"disabled", "adaptive"}:
                    thinking_type = "disabled"
                minimax_payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "You are a senior short-form editor. Reply only with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_completion_tokens": 1200,
                    "temperature": 0.2,
                    "stream": False,
                }
                if is_m3:
                    minimax_payload["thinking"] = {"type": thinking_type}
                    minimax_payload["reasoning_split"] = True
                body = _post_json(
                    chat_url,
                    minimax_payload,
                    {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )
                base_resp = body.get("base_resp") if isinstance(body, dict) else None
                status_msg = ""
                if isinstance(base_resp, dict):
                    status_msg = str(base_resp.get("status_msg") or base_resp.get("statusMessage") or "").strip()
                content_text = ""
                if isinstance(body, dict):
                    choices = body.get("choices")
                    if isinstance(choices, list) and choices:
                        first_choice = choices[0] if isinstance(choices[0], dict) else {}
                        content_text = (
                            _extract_chat_text((first_choice or {}).get("message"))
                            or _extract_chat_text((first_choice or {}).get("delta"))
                            or _extract_chat_text((first_choice or {}).get("text"))
                        )
                    if not content_text:
                        content_text = (
                            _extract_chat_text(body.get("reply"))
                            or _extract_chat_text(body.get("content"))
                            or _extract_chat_text(body.get("output_text"))
                            or _extract_chat_text(body.get("text"))
                            or _extract_chat_text(body.get("message"))
                        )
                if content_text:
                    payload = _extract_overlay_json(content_text)
                    if isinstance(payload, dict):
                        return payload
                    last_detail = "MiniMax lieferte kein gueltiges JSON fuer Text-Overlays."
                    continue
                last_detail = status_msg or "MiniMax lieferte keinen nutzbaren Antworttext."
                if "not support model" in last_detail.lower():
                    continue
                break
            raise RuntimeError(f"MiniMax-Antwort unbrauchbar: {last_detail}")
        if provider == "ollama":
            from main import _call_ollama

            base_url = str(ai_config.get("ollama_base_url") or "").strip()
            model_name = str(ai_config.get("ollama_model") or "").strip()
            if not base_url or not model_name:
                raise RuntimeError("Ollama Base-URL oder Modell fehlt.")
            _, response_text = _call_ollama(prompt, base_url, model_name)
            payload = _extract_overlay_json(response_text)
            if not isinstance(payload, dict):
                raise RuntimeError("Ollama lieferte kein gueltiges JSON fuer Text-Overlays.")
            return payload
        raise RuntimeError(f"Nicht unterstuetzter KI-Provider fuer Text-Overlays: {provider}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_call)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise RuntimeError(f"Text-Overlay-Vorschlaege haben nach {timeout_seconds}s ein Timeout erreicht.") from exc


def _reset_longform_pipeline_state(project_id: str, message: str) -> Dict[str, Any]:
    state = load_longform_project_bundle(project_id, log_limit=0)["state"]
    state["status"] = "idle"
    state["current_step"] = None
    state["message"] = message
    state["progress"] = 0.0
    state["error"] = None
    state["resume_available"] = False
    state["stop_requested"] = False
    state["completed_at"] = None
    state["steps"] = build_initial_steps()
    state["summary"] = {}
    save_state(project_id, state)
    return state


def _normalize_job_subtitle_style(style: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(style, dict):
        return None
    return _sanitize_subtitle_settings_dict(style, {}) or None


def _normalize_job_hook_style(style: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(style, dict):
        return None

    start_zoom_factor = _clamp_zoom_factor(
        style.get("start_zoom_factor") if style.get("start_zoom_factor") is not None else style.get("startZoomFactor"),
        DEFAULT_START_ZOOM_FACTOR,
    )
    zoom_factor = _clamp_zoom_factor(
        style.get("zoom_factor") if style.get("zoom_factor") is not None else style.get("zoomFactor"),
        DEFAULT_TARGET_ZOOM_FACTOR,
    )
    zoom_factor = max(zoom_factor, start_zoom_factor)

    return {
        "position": style.get("position") or "top",
        "horizontal_position": style.get("horizontal_position") or style.get("horizontalPosition") or "center",
        "x_position": style.get("x_position") if style.get("x_position") is not None else style.get("xPosition"),
        "y_position": style.get("y_position") if style.get("y_position") is not None else style.get("yPosition"),
        "text_align": style.get("text_align") or style.get("textAlign") or "center",
        "size": style.get("size") or "M",
        "width_preset": style.get("width_preset") or style.get("widthPreset") or "wide",
        "font_family": style.get("font_family") or style.get("fontFamily"),
        "background_style": style.get("background_style") or style.get("backgroundStyle"),
        "start_zoom_factor": start_zoom_factor,
        "zoom_factor": zoom_factor,
        "flash_mode": _normalize_pattern_flash_mode(style.get("flash_mode") or style.get("flashMode")),
    }


def _persist_job_overlay_defaults(
    job_id: str,
    *,
    subtitle_style: Any = _METADATA_UNSET,
    hook_style: Any = _METADATA_UNSET,
) -> Optional[Dict[str, Any]]:
    try:
        _, metadata_path, data = _load_job_metadata_or_404(job_id)
        existing = data.get("job_overlay_defaults")
        next_defaults = dict(existing) if isinstance(existing, dict) else {}

        if subtitle_style is not _METADATA_UNSET:
            normalized_subtitle_style = _normalize_job_subtitle_style(subtitle_style)
            if normalized_subtitle_style:
                next_defaults["subtitle_style"] = normalized_subtitle_style
            else:
                next_defaults.pop("subtitle_style", None)

        if hook_style is not _METADATA_UNSET:
            normalized_hook_style = _normalize_job_hook_style(hook_style)
            if normalized_hook_style:
                next_defaults["hook_style"] = normalized_hook_style
            else:
                next_defaults.pop("hook_style", None)

        if next_defaults:
            next_defaults["updated_at"] = time.time()
            data["job_overlay_defaults"] = next_defaults
        else:
            data.pop("job_overlay_defaults", None)

        _write_metadata(metadata_path, data)
        _refresh_job_result(job_id)
        return data.get("job_overlay_defaults")
    except Exception as e:
        print(f"⚠️ Failed to persist job overlay defaults for {job_id}: {e}")
        return None


def _persist_job_social_defaults(
    job_id: str,
    *,
    instagram_collaborators: Any = _METADATA_UNSET,
    podcast_youtube_url: Any = _METADATA_UNSET,
    podcast_link_url: Any = _METADATA_UNSET,
    podcast_keyword: Any = _METADATA_UNSET,
    podcast_comment_template: Any = _METADATA_UNSET,
    podcast_dm_enabled: Any = _METADATA_UNSET,
) -> Optional[Dict[str, Any]]:
    try:
        _, metadata_path, data = _load_job_metadata_or_404(job_id)
        existing = data.get("job_social_defaults")
        next_defaults = dict(existing) if isinstance(existing, dict) else {}

        if instagram_collaborators is not _METADATA_UNSET:
            normalized = _normalize_instagram_collaborators(instagram_collaborators or "")
            if normalized:
                next_defaults["instagram_collaborators"] = normalized
            else:
                next_defaults.pop("instagram_collaborators", None)

        podcast_campaign = dict(next_defaults.get("podcast_link_campaign") or {})
        requested_link = podcast_link_url if podcast_link_url is not _METADATA_UNSET else podcast_youtube_url
        if requested_link is not _METADATA_UNSET:
            normalized_url = _normalize_destination_url(requested_link or "")
            if normalized_url:
                podcast_campaign["link_url"] = normalized_url
                podcast_campaign["link_id"] = _extract_youtube_video_id(normalized_url) or hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:20]
                youtube_url = _normalize_podcast_youtube_url(normalized_url)
                if youtube_url:
                    podcast_campaign["youtube_url"] = youtube_url
                    podcast_campaign["youtube_id"] = _extract_youtube_video_id(youtube_url)
                else:
                    podcast_campaign.pop("youtube_url", None)
                    podcast_campaign.pop("youtube_id", None)
            else:
                podcast_campaign.pop("link_url", None)
                podcast_campaign.pop("link_id", None)
                podcast_campaign.pop("youtube_url", None)
                podcast_campaign.pop("youtube_id", None)

        if podcast_keyword is not _METADATA_UNSET:
            podcast_campaign["keyword"] = _normalize_podcast_keyword(podcast_keyword or "Video")

        if podcast_comment_template is not _METADATA_UNSET:
            podcast_campaign["comment_template"] = _normalize_podcast_comment_template(podcast_comment_template)

        if podcast_dm_enabled is not _METADATA_UNSET:
            podcast_campaign["enabled"] = bool(podcast_dm_enabled)

        normalized_campaign = _normalize_podcast_link_campaign(podcast_campaign)
        if normalized_campaign.get("link_url"):
            next_defaults["podcast_link_campaign"] = normalized_campaign
        else:
            next_defaults.pop("podcast_link_campaign", None)

        if next_defaults:
            next_defaults["updated_at"] = time.time()
            data["job_social_defaults"] = next_defaults
        else:
            data.pop("job_social_defaults", None)

        _write_metadata(metadata_path, data)
        _refresh_job_result(job_id)
        return data.get("job_social_defaults")
    except Exception as e:
        print(f"⚠️ Failed to persist job social defaults for {job_id}: {e}")
        return None


def _persist_clip_text_metadata(
    job_id: str,
    clip_index: int,
    *,
    video_title_for_youtube_short: Any = _METADATA_UNSET,
    video_description_for_tiktok: Any = _METADATA_UNSET,
    video_description_for_instagram: Any = _METADATA_UNSET,
    instagram_collaborators: Any = _METADATA_UNSET,
    start_zoom_factor: Any = _METADATA_UNSET,
    zoom_factor: Any = _METADATA_UNSET,
    flash_mode: Any = _METADATA_UNSET,
) -> Optional[Dict[str, Any]]:
    try:
        output_dir, metadata_path, data = _load_job_metadata_or_404(job_id)
        clips = data.get("shorts", [])
        if clip_index < 0 or clip_index >= len(clips):
            return None

        clip = dict(clips[clip_index] or {})
        clip["clip_index"] = clip_index
        _ensure_clip_versions(job_id, output_dir, clip)

        if video_title_for_youtube_short is not _METADATA_UNSET:
            clip["video_title_for_youtube_short"] = _normalize_unicode_text(video_title_for_youtube_short or "").strip()
        if video_description_for_tiktok is not _METADATA_UNSET:
            clip["video_description_for_tiktok"] = _normalize_unicode_text(video_description_for_tiktok or "").strip()
        if video_description_for_instagram is not _METADATA_UNSET:
            clip["video_description_for_instagram"] = _normalize_unicode_text(video_description_for_instagram or "").strip()
        if instagram_collaborators is not _METADATA_UNSET:
            normalized_collaborators = _normalize_instagram_collaborators(instagram_collaborators or "")
            if normalized_collaborators:
                clip["instagram_collaborators"] = normalized_collaborators
            else:
                clip.pop("instagram_collaborators", None)
        if start_zoom_factor is not _METADATA_UNSET or zoom_factor is not _METADATA_UNSET or flash_mode is not _METADATA_UNSET:
            hook_settings = dict(clip.get("hook_settings") or {})
            normalized_start_zoom_factor = _clamp_zoom_factor(
                start_zoom_factor if start_zoom_factor is not _METADATA_UNSET else hook_settings.get("start_zoom_factor"),
                DEFAULT_START_ZOOM_FACTOR,
            )
            normalized_zoom_factor = _clamp_zoom_factor(
                zoom_factor if zoom_factor is not _METADATA_UNSET else hook_settings.get("zoom_factor"),
                DEFAULT_TARGET_ZOOM_FACTOR,
            )
            normalized_zoom_factor = max(normalized_zoom_factor, normalized_start_zoom_factor)
            normalized_flash_mode = _normalize_pattern_flash_mode(
                flash_mode if flash_mode is not _METADATA_UNSET else hook_settings.get("flash_mode"),
            )
            if hook_settings or clip.get("viral_hook_text"):
                hook_settings["start_zoom_factor"] = normalized_start_zoom_factor
                hook_settings["zoom_factor"] = normalized_zoom_factor
                hook_settings["flash_mode"] = normalized_flash_mode
                clip["hook_settings"] = hook_settings
            else:
                clip["hook_settings"] = {
                    "start_zoom_factor": normalized_start_zoom_factor,
                    "zoom_factor": normalized_zoom_factor,
                    "flash_mode": normalized_flash_mode,
                }

        clips[clip_index] = clip
        data["shorts"] = clips
        _write_metadata(metadata_path, data)
        result = _refresh_job_result(job_id)
        if result:
            return _find_result_clip(result, clip_index)
        return clip
    except Exception as e:
        print(f"⚠️ Failed to persist clip text metadata for {job_id}#{clip_index}: {e}")
        return None


def _clip_video_url(job_id: str, filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    return f"/videos/{job_id}/{os.path.basename(filename)}"


def _normalize_language_hint(value: Any) -> str:
    if value is None:
        return ""
    normalized = str(value).strip().lower().replace("_", "-")
    if not normalized or normalized == "auto":
        return ""
    normalized = normalized.split("-")[0]
    if re.fullmatch(r"[a-z]{2,3}", normalized):
        return normalized
    return ""


def _language_from_translated_filename(filename: Optional[str]) -> str:
    name = os.path.basename(filename or "")
    if not name:
        return ""
    match = re.search(r"(?:^|_)translated_\d+_([A-Za-z_-]+)_", name)
    if not match:
        return ""
    return _normalize_language_hint(match.group(1))


def _normalize_unicode_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return text
    try:
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
            text = text.encode("utf-16", "surrogatepass").decode("utf-16")
    except Exception:
        pass
    return text


def _normalize_instagram_collaborators(value: Any) -> str:
    text = _normalize_unicode_text(value).strip()
    if not text:
        return ""

    normalized_parts: List[str] = []
    seen = set()
    for raw_part in text.split(","):
        candidate = raw_part.strip().lstrip("@").strip()
        if not candidate:
            continue
        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_parts.append(candidate)
    return ",".join(normalized_parts)


def _extract_youtube_video_id(value: Any) -> str:
    raw = _normalize_unicode_text(value).strip()
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", raw):
        return raw
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return ""
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = urllib.parse.parse_qs(parsed.query or "")
    if host.endswith("youtu.be"):
        candidate = path.strip("/").split("/")[0] if path.strip("/") else ""
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate) else ""
    if "youtube.com" in host:
        if query.get("v"):
            candidate = str(query["v"][0] or "").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate):
                return candidate
        parts = [part for part in path.split("/") if part]
        for marker in ("shorts", "embed", "live"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    candidate = parts[idx + 1]
                    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate):
                        return candidate
    return ""


def _normalize_podcast_keyword(value: Any) -> str:
    text = re.sub(r"\s+", " ", _normalize_unicode_text(value).strip())
    text = text.strip(" .,:;!?\"'`#")
    if not text:
        text = "Video"
    return text[:40]


def _normalize_podcast_youtube_url(value: Any) -> str:
    raw = _normalize_unicode_text(value).strip()
    video_id = _extract_youtube_video_id(raw)
    if not video_id:
        return ""
    return f"https://youtu.be/{video_id}"


def _normalize_destination_url(value: Any) -> str:
    raw = _normalize_unicode_text(value).strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return ""
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        return ""
    if "." not in host and host != "localhost" and not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return ""
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc, parsed.path or "", "", parsed.query or "", parsed.fragment or ""))


DEFAULT_PODCAST_COMMENT_TEMPLATE = 'Kommentiere "<keyword>" und wir senden dir den Link zum Podcast zu'


def _normalize_podcast_comment_template(value: Any) -> str:
    normalized = _normalize_unicode_text(value).strip()
    if not normalized:
        return DEFAULT_PODCAST_COMMENT_TEMPLATE
    return normalized[:1000]


def _build_podcast_link_cta(keyword: Any, template: Any = None) -> str:
    normalized_keyword = _normalize_podcast_keyword(keyword)
    normalized_template = _normalize_podcast_comment_template(template)
    return re.sub(r"<keyword>", normalized_keyword, normalized_template, flags=re.IGNORECASE)


def _text_contains_podcast_link_cta(text: Any, keyword: Any, template: Any = None) -> bool:
    base = _normalize_unicode_text(text).strip().lower()
    if not base:
        return False
    normalized_keyword = _normalize_podcast_keyword(keyword)
    current_cta = _build_podcast_link_cta(normalized_keyword, template).lower()
    legacy_cta = f"Kommentiere {normalized_keyword} und wir senden dir den Link zum Podcast zu".lower()
    return current_cta in base or legacy_cta in base


def _normalize_existing_podcast_link_cta_quotes(text: Any, keyword: Any, template: Any = None) -> str:
    base = _normalize_unicode_text(text).strip()
    if not base:
        return ""
    normalized_keyword = _normalize_podcast_keyword(keyword)
    current_cta = _build_podcast_link_cta(normalized_keyword, template)
    legacy_cta = f"Kommentiere {normalized_keyword} und wir senden dir den Link zum Podcast zu"
    return re.sub(re.escape(legacy_cta), current_cta, base, count=1, flags=re.IGNORECASE)


def _compose_first_comment_with_podcast_cta(
    first_comment: Any,
    *,
    keyword: Any,
    template: Any = None,
    generated_text: Any = "",
) -> str:
    cta = _build_podcast_link_cta(keyword, template)
    base = _normalize_existing_podcast_link_cta_quotes(first_comment, keyword, template)
    if _text_contains_podcast_link_cta(base, keyword, template):
        return base
    trailing = base or _normalize_unicode_text(generated_text).strip()
    if trailing:
        return f"{cta}\n\n{trailing}".strip()
    return cta


def _compose_caption_with_podcast_cta(
    caption: Any,
    *,
    keyword: Any,
    template: Any = None,
) -> str:
    cta = _build_podcast_link_cta(keyword, template)
    base = _normalize_existing_podcast_link_cta_quotes(caption, keyword, template)
    if _text_contains_podcast_link_cta(base, keyword, template):
        return base
    if base:
        return f"{cta}\n\n{base}".strip()
    return cta


def _resolve_instagram_podcast_caption(
    description: Any,
    *,
    requested_platforms: List[str],
    podcast_campaign: Optional[Dict[str, Any]],
) -> str:
    base = _normalize_unicode_text(description).strip()
    campaign = _normalize_podcast_link_campaign(podcast_campaign)
    if campaign.get("enabled") and "instagram" in _normalize_social_platforms(requested_platforms):
        return _compose_caption_with_podcast_cta(
            base,
            keyword=campaign.get("keyword") or "Video",
            template=campaign.get("comment_template"),
        )
    return base


def _normalize_podcast_link_campaign(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    link_url = _normalize_destination_url(
        data.get("link_url")
        or data.get("destination_url")
        or data.get("youtube_url")
        or data.get("url")
        or ""
    )
    youtube_url = _normalize_podcast_youtube_url(data.get("youtube_url") or link_url)
    youtube_id = _extract_youtube_video_id(data.get("youtube_id") or youtube_url)
    link_id = str(data.get("link_id") or youtube_id or hashlib.sha1(link_url.encode("utf-8")).hexdigest()[:20] if link_url else "").strip()
    keyword = _normalize_podcast_keyword(data.get("keyword") or "Video")
    comment_template = _normalize_podcast_comment_template(data.get("comment_template"))
    enabled = bool(data.get("enabled", True)) and bool(link_url)
    return {
        "enabled": enabled,
        "link_url": link_url,
        "link_id": link_id,
        "youtube_url": youtube_url,
        "youtube_id": youtube_id,
        "keyword": keyword,
        "comment_template": comment_template,
    }


def _resolve_transcription_language_hint(
    metadata_data: Optional[Dict[str, Any]] = None,
    clip_data: Optional[Dict[str, Any]] = None,
    source_version: Optional[Dict[str, Any]] = None,
    fallback_filename: Optional[str] = None,
) -> str:
    if source_version:
        from_version = _normalize_language_hint(source_version.get("language"))
        if from_version:
            return from_version
        from_version_name = _language_from_translated_filename(
            source_version.get("filename") or source_version.get("video_filename")
        )
        if from_version_name:
            return from_version_name

    from_filename = _language_from_translated_filename(fallback_filename)
    if from_filename:
        return from_filename

    metadata = metadata_data or {}
    transcript = metadata.get("transcript") if isinstance(metadata, dict) else None
    if isinstance(transcript, dict):
        from_transcript = _normalize_language_hint(transcript.get("language"))
        if from_transcript:
            return from_transcript

    if isinstance(metadata, dict):
        from_metadata = _normalize_language_hint(metadata.get("language"))
        if from_metadata:
            return from_metadata

    if clip_data:
        from_clip = _normalize_language_hint(clip_data.get("language"))
        if from_clip:
            return from_clip

    return ""


def _infer_language_from_clip_copy(clip_data: Optional[Dict[str, Any]]) -> str:
    if not isinstance(clip_data, dict):
        return ""

    text_parts = [
        clip_data.get("video_title_for_youtube_short"),
        clip_data.get("video_description_for_tiktok"),
        clip_data.get("video_description_for_instagram"),
        clip_data.get("viral_hook_text"),
    ]
    text = " ".join(str(part or "") for part in text_parts).strip().lower()
    if not text:
        return ""

    tokens = re.findall(r"[a-zA-ZäöüÄÖÜßñáéíóúàèìòùç]+", text)
    if not tokens:
        return ""

    language_markers = {
        "de": {
            "und", "nicht", "ich", "du", "der", "die", "das", "mit", "für",
            "fuer", "ist", "auf", "ein", "eine", "zum", "den", "dass",
        },
        "es": {
            "que", "para", "con", "una", "como", "pero", "esto", "esta",
            "tiktok", "viral", "haz", "sin", "más", "mas", "porque",
        },
        "fr": {
            "pour", "avec", "dans", "une", "est", "pas", "vous", "mais",
            "plus", "comment", "vidéo", "video",
        },
        "it": {
            "con", "per", "non", "una", "come", "questo", "video", "italia",
            "solo", "anche",
        },
        "pt": {
            "com", "para", "não", "nao", "uma", "como", "isso", "você",
            "voce", "mais", "video",
        },
        "en": {
            "the", "and", "you", "your", "with", "this", "that", "for",
            "from", "how", "why", "what", "viral",
        },
    }

    token_count = max(1, len(tokens))
    scores: Dict[str, float] = {}
    for language_code, markers in language_markers.items():
        hits = sum(1 for token in tokens if token in markers)
        score = hits / token_count
        if language_code == "de" and any(ch in text for ch in ("ä", "ö", "ü", "ß")):
            score += 0.08
        scores[language_code] = score

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_lang, top_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    if top_score < 0.045:
        return ""
    if (top_score - second_score) < 0.02:
        return ""
    return top_lang


def _resolve_subtitle_language_hint(
    metadata_data: Optional[Dict[str, Any]] = None,
    clip_data: Optional[Dict[str, Any]] = None,
    source_version: Optional[Dict[str, Any]] = None,
    fallback_filename: Optional[str] = None,
) -> str:
    resolved = _resolve_transcription_language_hint(
        metadata_data=metadata_data,
        clip_data=clip_data,
        source_version=source_version,
        fallback_filename=fallback_filename,
    )
    metadata_transcript_language = _normalize_language_hint(
        ((metadata_data or {}).get("transcript") or {}).get("language")
    )
    inferred_from_transcript = _infer_language_from_transcript_content(metadata_data)
    inferred_from_copy = _infer_language_from_clip_copy(clip_data)

    if (
        metadata_transcript_language
        and resolved in {"", "en"}
        and metadata_transcript_language != resolved
    ):
        print(
            "🗣️ Subtitle language hint override from metadata transcript: "
            f"{resolved or 'auto'} -> {metadata_transcript_language}"
        )
        resolved = metadata_transcript_language

    if inferred_from_transcript and resolved in {"", "en"} and inferred_from_transcript != resolved:
        print(
            "🗣️ Subtitle language hint override from transcript content: "
            f"{resolved or 'auto'} -> {inferred_from_transcript}"
        )
        resolved = inferred_from_transcript

    if inferred_from_copy and resolved in {"", "en"} and inferred_from_copy != resolved:
        print(
            "🗣️ Subtitle language hint override from clip copy: "
            f"{resolved or 'auto'} -> {inferred_from_copy}"
        )
        return inferred_from_copy

    return resolved


def _infer_language_from_transcript_content(metadata_data: Optional[Dict[str, Any]]) -> str:
    if not isinstance(metadata_data, dict):
        return ""
    transcript = metadata_data.get("transcript")
    if not isinstance(transcript, dict):
        return ""

    text = _collect_transcript_text_for_range(transcript, 0.0, 1e9).lower()
    if not text:
        return ""

    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß]+", text)
    if len(tokens) < 16:
        return ""

    english_markers = {
        "the", "and", "you", "that", "is", "to", "of", "it",
        "in", "for", "on", "with", "this", "are", "be", "your",
        "from", "as", "have", "just",
    }
    german_markers = {
        "und", "ich", "nicht", "das", "die", "der", "du", "ist",
        "es", "wir", "sie", "ein", "zu", "mit", "dass", "aber",
        "wie", "auch", "wenn", "auf", "den", "dem", "im", "für", "fuer",
    }

    english_hits = sum(1 for token in tokens if token in english_markers)
    german_hits = sum(1 for token in tokens if token in german_markers)
    has_umlaut = any(ch in text for ch in ("ä", "ö", "ü", "ß"))

    if has_umlaut and german_hits >= english_hits:
        return "de"
    if german_hits >= 6 and german_hits >= (english_hits + 2):
        return "de"
    if english_hits >= 6 and english_hits >= (german_hits + 2):
        return "en"
    return ""


def _collect_transcript_text_for_range(
    transcript: Optional[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
) -> str:
    if not isinstance(transcript, dict):
        return ""
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        return ""
    texts: List[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            seg_start = float(segment.get("start", 0.0) or 0.0)
            seg_end = float(segment.get("end", seg_start) or seg_start)
        except (TypeError, ValueError):
            continue
        if seg_end <= clip_start or seg_start >= clip_end:
            continue
        text = str(segment.get("text") or "").strip()
        if text:
            texts.append(text)
    return " ".join(texts).strip()


def _looks_mismatched_to_expected_language(
    transcript: Optional[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    expected_language: str,
) -> bool:
    lang = _normalize_language_hint(expected_language)
    if not lang:
        return False

    transcript_language = ""
    if isinstance(transcript, dict):
        transcript_language = _normalize_language_hint(transcript.get("language"))
    if lang == "de" and transcript_language == "en":
        return True

    text = _collect_transcript_text_for_range(transcript, clip_start, clip_end).lower()
    if not text:
        return False

    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß]+", text)
    if len(tokens) < 6:
        return False

    if lang != "de":
        return False

    english_markers = {
        "the", "and", "you", "that", "is", "to", "of", "it",
        "in", "for", "on", "with", "this", "are", "be", "your",
        "from", "as", "have", "just",
    }
    german_markers = {
        "und", "ich", "nicht", "das", "die", "der", "du", "ist",
        "es", "wir", "sie", "ein", "zu", "mit", "dass", "aber",
        "wie", "auch", "wenn", "auf", "den", "dem", "im",
    }

    english_hits = sum(1 for token in tokens if token in english_markers)
    german_hits = sum(1 for token in tokens if token in german_markers)
    english_ratio = english_hits / max(1, len(tokens))
    german_ratio = german_hits / max(1, len(tokens))

    return english_hits >= 4 and english_ratio > 0.06 and english_ratio > (german_ratio * 1.2)


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_transcript_window_for_range(
    transcript: Optional[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
) -> Optional[Dict[str, Any]]:
    if not isinstance(transcript, dict):
        return None
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        return None
    if clip_end <= clip_start:
        return None

    window_segments: List[Dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seg_start = _coerce_float(segment.get("start"))
        seg_end = _coerce_float(segment.get("end"))
        if seg_start is None:
            seg_start = 0.0
        if seg_end is None:
            seg_end = seg_start
        if seg_end <= clip_start or seg_start >= clip_end:
            continue

        text = str(segment.get("text") or "").strip()
        words_payload: List[Dict[str, Any]] = []
        words = segment.get("words")
        if isinstance(words, list):
            for word in words:
                if not isinstance(word, dict):
                    continue
                word_text = str(word.get("word") or "").strip()
                if not word_text:
                    continue
                word_start = _coerce_float(word.get("start"))
                word_end = _coerce_float(word.get("end"))
                if word_start is None:
                    word_start = seg_start
                if word_end is None:
                    word_end = word_start
                if word_end <= clip_start or word_start >= clip_end:
                    continue
                words_payload.append({
                    "word": word_text,
                    "start": max(clip_start, word_start),
                    "end": min(clip_end, word_end),
                })

        if not words_payload and not text:
            continue

        window_segments.append({
            "start": max(clip_start, seg_start),
            "end": min(clip_end, seg_end),
            "text": text,
            "words": words_payload,
        })

    if not window_segments:
        return None

    return {
        "language": transcript.get("language"),
        "segments": window_segments,
    }


def _resolve_subtitle_transcript_payload(
    *,
    metadata_data: Optional[Dict[str, Any]],
    clip_data: Optional[Dict[str, Any]],
    input_path: str,
    preferred_language: str,
    transcript_source_hint: Optional[str] = None,
    transcript_start: Optional[float] = None,
    transcript_end: Optional[float] = None,
) -> Tuple[Dict[str, Any], float, float, str]:
    resolved_language = _normalize_language_hint(preferred_language)
    source_hint = str(transcript_source_hint or "").strip().lower()
    original_transcript = (metadata_data or {}).get("transcript")

    range_start = _coerce_float(transcript_start)
    range_end = _coerce_float(transcript_end)
    if range_start is None and isinstance(clip_data, dict):
        range_start = _coerce_float(clip_data.get("start"))
    if range_end is None and isinstance(clip_data, dict):
        range_end = _coerce_float(clip_data.get("end"))

    if source_hint == "original":
        if range_start is not None and range_end is not None and range_end > range_start:
            window = _build_transcript_window_for_range(
                original_transcript,
                range_start,
                range_end,
            )
            if window:
                if resolved_language and _looks_mismatched_to_expected_language(window, range_start, range_end, resolved_language):
                    print(
                        "⚠️ Original transcript window language mismatch. "
                        "Falling back to fresh audio transcription."
                    )
                else:
                    print(
                        "♻️ Subtitle transcript source: original transcript window "
                        f"({range_start:.2f}s - {range_end:.2f}s)."
                    )
                    return window, float(range_start), float(range_end), "original"

    subtitle_transcript = transcribe_audio(input_path, preferred_language=resolved_language or None)
    clip_start = 0.0
    clip_end = _probe_video_duration(input_path)
    expected_language = resolved_language or _normalize_language_hint(
        (original_transcript or {}).get("language")
    )

    if expected_language and _looks_mismatched_to_expected_language(
        subtitle_transcript,
        clip_start,
        clip_end,
        expected_language,
    ):
        print(
            "⚠️ Subtitle transcript language mismatch after audio transcription. "
            "Trying stricter language fallback..."
        )
        strict_language = _normalize_language_hint((original_transcript or {}).get("language"))
        if strict_language and strict_language != resolved_language:
            print(f"🔁 Retrying subtitle transcription with strict language hint: {strict_language}")
            retried_transcript = transcribe_audio(input_path, preferred_language=strict_language)
            if not _looks_mismatched_to_expected_language(
                retried_transcript,
                clip_start,
                clip_end,
                strict_language,
            ):
                return retried_transcript, clip_start, clip_end, "audio-retry"

        if (
            source_hint == "original"
            and range_start is not None
            and range_end is not None
            and range_end > range_start
        ):
            window = _build_transcript_window_for_range(
                original_transcript,
                range_start,
                range_end,
            )
            if window:
                print("♻️ Using original transcript window fallback for subtitles.")
                return window, float(range_start), float(range_end), "original-fallback"

    return subtitle_transcript, clip_start, clip_end, "audio"


def _transcript_has_word_timestamps(transcript: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(transcript, dict):
        return False
    for segment in transcript.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for word in segment.get("words") or []:
            if not isinstance(word, dict):
                continue
            if str(word.get("word") or "").strip():
                return True
    return False


def _merge_keep_segments(
    keep_segments: List[Tuple[float, float]],
    tolerance: float = 0.01,
) -> List[Tuple[float, float]]:
    merged: List[Tuple[float, float]] = []
    for raw_start, raw_end in keep_segments:
        start = _coerce_float(raw_start)
        end = _coerce_float(raw_end)
        if start is None or end is None or end <= start:
            continue
        if merged and start >= merged[-1][0] and start <= (merged[-1][1] + tolerance):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [(round(start, 3), round(end, 3)) for start, end in merged]


def _timeline_interval_to_source_segments(
    keep_segments: List[Tuple[float, float]],
    timeline_start: float,
    timeline_end: float,
) -> List[Tuple[float, float]]:
    if timeline_end <= timeline_start:
        return []

    mapped_segments: List[Tuple[float, float]] = []
    output_cursor = 0.0

    for raw_source_start, raw_source_end in keep_segments:
        source_start = _coerce_float(raw_source_start)
        source_end = _coerce_float(raw_source_end)
        if source_start is None or source_end is None or source_end <= source_start:
            continue

        source_duration = source_end - source_start
        segment_output_start = output_cursor
        segment_output_end = output_cursor + source_duration
        overlap_start = max(timeline_start, segment_output_start)
        overlap_end = min(timeline_end, segment_output_end)

        if overlap_end > overlap_start:
            mapped_start = source_start + (overlap_start - segment_output_start)
            mapped_end = source_start + (overlap_end - segment_output_start)
            mapped_segments.append((mapped_start, mapped_end))

        output_cursor = segment_output_end

    return _merge_keep_segments(mapped_segments, tolerance=0.005)


def _remap_transcript_to_keep_segments(
    transcript: Optional[Dict[str, Any]],
    keep_segments: List[Tuple[float, float]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(transcript, dict):
        return None
    if not keep_segments:
        return None

    remapped_segments: List[Dict[str, Any]] = []
    output_cursor = 0.0

    for raw_keep_start, raw_keep_end in keep_segments:
        keep_start = _coerce_float(raw_keep_start)
        keep_end = _coerce_float(raw_keep_end)
        if keep_start is None or keep_end is None or keep_end <= keep_start:
            continue

        window = _build_transcript_window_for_range(transcript, keep_start, keep_end)
        if isinstance(window, dict):
            for segment in window.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                seg_start = _coerce_float(segment.get("start"))
                seg_end = _coerce_float(segment.get("end"))
                if seg_start is None:
                    seg_start = keep_start
                if seg_end is None:
                    seg_end = seg_start
                if seg_end <= keep_start or seg_start >= keep_end:
                    continue

                clipped_start = max(keep_start, seg_start)
                clipped_end = min(keep_end, seg_end)
                mapped_words: List[Dict[str, Any]] = []
                for word in segment.get("words") or []:
                    if not isinstance(word, dict):
                        continue
                    word_text = str(word.get("word") or "").strip()
                    if not word_text:
                        continue
                    word_start = _coerce_float(word.get("start"))
                    word_end = _coerce_float(word.get("end"))
                    if word_start is None:
                        word_start = clipped_start
                    if word_end is None:
                        word_end = word_start
                    if word_end <= keep_start or word_start >= keep_end:
                        continue
                    mapped_words.append({
                        "word": word_text,
                        "start": round(output_cursor + (max(keep_start, word_start) - keep_start), 3),
                        "end": round(output_cursor + (min(keep_end, word_end) - keep_start), 3),
                    })

                text = str(segment.get("text") or "").strip()
                if not mapped_words and not text:
                    continue

                remapped_segments.append({
                    "start": round(output_cursor + (clipped_start - keep_start), 3),
                    "end": round(output_cursor + (clipped_end - keep_start), 3),
                    "text": text,
                    "words": mapped_words,
                })

        output_cursor += keep_end - keep_start

    if not remapped_segments:
        return None

    return {
        "language": transcript.get("language"),
        "segments": remapped_segments,
    }


def _heuristic_viral_teaser_plan(
    transcript: Optional[Dict[str, Any]],
    duration: float,
    *,
    interview_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    safe_duration = max(0.0, float(duration or 0.0))
    if safe_duration < 4.0:
        return None

    min_teaser_length = 1.35 if interview_mode else 1.05
    max_teaser_length = 2.8 if interview_mode else 2.25
    preferred_min_start = safe_duration * 0.15

    candidates: List[Tuple[float, Dict[str, Any]]] = []
    if isinstance(transcript, dict):
        for segment in transcript.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            seg_start = _coerce_float(segment.get("start"))
            seg_end = _coerce_float(segment.get("end"))
            if seg_start is None or seg_end is None or seg_end <= seg_start:
                continue

            text = str(segment.get("text") or "").strip()
            if not text:
                continue

            word_count = len(re.findall(r"\w+", text))
            if word_count < 3:
                continue

            teaser_start = max(0.0, min(seg_start, max(0.0, safe_duration - min_teaser_length)))
            teaser_end = min(
                safe_duration,
                max(seg_end, teaser_start + min_teaser_length),
            )
            teaser_end = min(teaser_end, teaser_start + max_teaser_length)
            if teaser_end - teaser_start < min_teaser_length:
                continue

            score = 0.0
            if teaser_start >= preferred_min_start:
                score += 1.8
            else:
                score -= 0.6
            score += min(word_count, 12) * 0.08
            score += min(teaser_start / max(1.0, safe_duration), 0.7)
            if any(marker in text for marker in ("?", "!")):
                score += 0.55
            if re.search(r"\d|€|\$|%|k\b|million|tausend", text.lower()):
                score += 0.45
            if interview_mode and 5 <= word_count <= 14:
                score += 0.35
            if not interview_mode and word_count <= 10:
                score += 0.2

            candidates.append((score, {
                "use_teaser": True,
                "teaser_start": teaser_start,
                "teaser_end": teaser_end,
                "reason": text[:180],
                "effect_notes": (
                    "Subtle interview punch-ins on emphasis and restrained contrast pops."
                    if interview_mode
                    else "Rhythmic punch-ins, crop shifts, and short emphasis flashes on key beats."
                ),
                "pattern_interrupts": [],
            }))

    if candidates:
        best_plan = max(candidates, key=lambda item: item[0])[1]
        best_plan["source"] = "heuristic"
        return best_plan

    teaser_length = 1.6 if interview_mode else 1.25
    teaser_start = min(max(safe_duration * 0.35, preferred_min_start), max(0.0, safe_duration - teaser_length))
    teaser_end = min(safe_duration, teaser_start + teaser_length)
    if teaser_end - teaser_start < 0.9:
        return None
    return {
        "use_teaser": True,
        "teaser_start": teaser_start,
        "teaser_end": teaser_end,
        "reason": "Later clip opener chosen as cold open fallback.",
        "effect_notes": (
            "Keep the interview pacing premium with subtle punch-ins."
            if interview_mode
            else "Use clean punch-ins and one or two tasteful emphasis moments."
        ),
        "pattern_interrupts": [],
        "source": "heuristic",
    }


def _sanitize_viral_teaser_plan(
    plan: Optional[Dict[str, Any]],
    duration: float,
) -> Optional[Dict[str, Any]]:
    if not isinstance(plan, dict):
        return None

    if plan.get("use_teaser") is False or str(plan.get("use_teaser", "")).strip().lower() == "false":
        return None

    safe_duration = max(0.0, float(duration or 0.0))
    teaser_start = _coerce_float(plan.get("teaser_start"))
    teaser_end = _coerce_float(plan.get("teaser_end"))
    if teaser_start is None or teaser_end is None:
        return None

    teaser_start = max(0.0, min(safe_duration, teaser_start))
    teaser_end = max(0.0, min(safe_duration, teaser_end))
    if teaser_end - teaser_start < 0.75:
        return None

    pattern_interrupts = plan.get("pattern_interrupts")
    if not isinstance(pattern_interrupts, list):
        pattern_interrupts = []

    return {
        "use_teaser": True,
        "teaser_start": round(teaser_start, 3),
        "teaser_end": round(teaser_end, 3),
        "reason": str(plan.get("reason") or "").strip(),
        "effect_notes": str(plan.get("effect_notes") or "").strip(),
        "pattern_interrupts": pattern_interrupts[:6],
        "source": str(plan.get("source") or "").strip() or "ai",
    }


def _resolve_ai_editor_runtime(request: Request) -> Dict[str, Any]:
    provider_name = (request.headers.get("X-LLM-Provider") or "gemini").strip().lower()
    runtime = {
        "provider": provider_name,
        "api_key": request.headers.get("X-Gemini-Key") or os.environ.get("GEMINI_API_KEY"),
        "gemini_model": request.headers.get("X-Gemini-Model") or os.environ.get("GEMINI_MODEL"),
        "openai_api_key": request.headers.get("X-OpenAI-Key") or os.environ.get("OPENAI_API_KEY"),
        "openai_model": request.headers.get("X-OpenAI-Model") or os.environ.get("OPENAI_MODEL"),
        "claude_api_key": request.headers.get("X-Claude-Key") or os.environ.get("CLAUDE_API_KEY"),
        "claude_model": request.headers.get("X-Claude-Model") or os.environ.get("CLAUDE_MODEL"),
        "minimax_api_key": request.headers.get("X-Minimax-Key") or os.environ.get("MINIMAX_API_KEY"),
        "minimax_auth_mode": request.headers.get("X-Minimax-Auth-Mode") or os.environ.get("MINIMAX_AUTH_MODE"),
        "minimax_model": request.headers.get("X-Minimax-Model") or os.environ.get("MINIMAX_MODEL"),
        "ollama_base_url": request.headers.get("X-Ollama-Base-Url") or os.environ.get("OLLAMA_BASE_URL"),
        "ollama_model": request.headers.get("X-Ollama-Model") or os.environ.get("OLLAMA_MODEL"),
        "enabled": False,
        "warning": "",
    }

    if provider_name == "gemini":
        runtime["enabled"] = bool(runtime["api_key"])
        if not runtime["enabled"]:
            runtime["warning"] = "Gemini API-Key fehlt. Verwende heuristischen Teaser ohne KI-Pattern-Interrupts."
        return runtime

    if provider_name == "openai":
        runtime["enabled"] = bool(runtime["openai_api_key"])
        if not runtime["enabled"]:
            runtime["warning"] = "OpenAI API-Key fehlt. Verwende heuristischen Fallback."
        return runtime

    if provider_name == "claude":
        runtime["enabled"] = bool(runtime["claude_api_key"])
        if not runtime["enabled"]:
            runtime["warning"] = "Claude API-Key fehlt. Verwende heuristischen Fallback."
        return runtime

    if provider_name == "minimax":
        runtime["enabled"] = bool(runtime["minimax_api_key"])
        if not runtime["enabled"]:
            runtime["warning"] = "MiniMax API-Key fehlt. Verwende heuristischen Fallback."
        return runtime

    if provider_name == "ollama":
        try:
            normalized_base_url, normalized_model = _validate_ollama_model_or_raise(
                runtime["ollama_base_url"],
                runtime["ollama_model"],
            )
            runtime["ollama_base_url"] = normalized_base_url
            runtime["ollama_model"] = normalized_model
            runtime["enabled"] = True
        except HTTPException as exc:
            runtime["warning"] = str(exc.detail)
        return runtime

    runtime["warning"] = f"Unbekannter LLM-Provider '{provider_name}'. Verwende heuristischen Fallback."
    return runtime


def _extract_json_payload(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    cleaned = str(text).strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx:end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def _resolve_pexels_api_key(request: Request) -> Optional[str]:
    return request.headers.get("X-Pexels-Key") or os.environ.get("PEXELS_API_KEY")


def _build_stock_overlay_prompt(
    clip_duration: float,
    transcript: Optional[Dict[str, Any]],
    language_name: str,
    hook_text: Optional[str] = None,
) -> str:
    transcript_text = ""
    if isinstance(transcript, dict):
        transcript_text = " ".join(
            str(segment.get("text") or "").strip() for segment in transcript.get("segments") or []
        ).strip()
    prompt = [
        "You are a smart short-form video assistant.",
        f"The clip language is {language_name}.",
        "Based on the clip transcript and the viral hook text, suggest a broad, thematic Pexels search query and an insertion time for a stock image overlay.",
        "The image should appear in the lower half of the vertical video for a short attention-grabbing moment.",
        "Return only a JSON object with the following fields:",
        "- search_keywords: an array of 1-3 short keyword phrases suitable for Pexels search.",
        "- overlay_time: a single number in seconds within the final clip.",
        "- overlay_duration: a single number in seconds between 2.0 and 4.0.",
        "Do not include any extra text outside the JSON object.",
        f"CLIP_DURATION: {round(float(clip_duration or 0.0), 3)}",
    ]
    if hook_text:
        prompt.append(f"Viral hook text: {hook_text}")
    if transcript_text:
        prompt.append("Transcript text:")
        prompt.append(transcript_text)
    prompt.append(
        "Choose a search query that describes the clip's overall theme in a generic way, not a very narrow or specific product/brand detail."
    )
    prompt.append(
        "For example, if the clip is about video marketing, use something like 'social media creation' or 'content storytelling', not an exact app or brand name."
    )
    prompt.append(
        "Avoid people, faces, portraits, or identifiable characters in the search keywords. Prefer generic scenes, abstract backgrounds, workspaces, cityscapes, or calm textures."
    )
    prompt.append(
        "If possible, choose keywords that describe a non-human visual mood or environment, such as a clean workspace, stylized urban scene, soft abstract lighting, or minimal graphic background."
    )
    prompt.append(
        "Choose a moment that feels natural, attention-grabbing, and relevant to the clip."
    )
    return "\n".join(prompt)


def _call_stock_overlay_llm(ai_runtime: Dict[str, Any], prompt: str, timeout_seconds: int = 15) -> Optional[Dict[str, Any]]:
    def _do_llm_call() -> Optional[Dict[str, Any]]:
        provider = ai_runtime.get("provider", "gemini")
        if provider == "gemini":
            api_key = ai_runtime.get("api_key")
            if not api_key:
                return None
            try:
                client = genai.Client(api_key=api_key)
                model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
                response = client.models.generate_content(model=model_name, contents=prompt)
                return _extract_json_payload(response.text)
            except Exception:
                return None

        if provider in {"openai", "claude", "minimax"}:
            try:
                from main import _call_shortform_provider_json

                model_name = ai_runtime.get(f"{provider}_model")
                return _call_shortform_provider_json(provider, prompt, model_name=model_name)
            except Exception:
                return None

        if provider == "ollama":
            base_url = ai_runtime.get("ollama_base_url")
            model_name = ai_runtime.get("ollama_model")
            if not base_url or not model_name:
                return None
            try:
                from main import _call_ollama

                _, response_text = _call_ollama(prompt, base_url, model_name)
                return _extract_json_payload(response_text)
            except Exception:
                return None
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_llm_call)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            print(f"⚠️ Stock overlay LLM timed out after {timeout_seconds}s")
            return None


def _sanitize_stock_overlay_plan(payload: Any, clip_duration: float) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    keywords = payload.get("search_keywords") or payload.get("search_query") or payload.get("keywords")
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, list):
        return None
    search_keywords = [str(k).strip() for k in keywords if str(k or "").strip()]
    if not search_keywords:
        return None

    overlay_time = _coerce_float(payload.get("overlay_time") or payload.get("time") or payload.get("start"))
    if overlay_time is None:
        return None
    overlay_duration = _coerce_float(payload.get("overlay_duration") or payload.get("duration"))
    if overlay_duration is None:
        overlay_duration = 3.0
    overlay_duration = max(1.5, min(float(overlay_duration), min(4.0, float(clip_duration or 4.0))))
    overlay_time = max(0.0, min(float(clip_duration or 0.0) - overlay_duration, float(overlay_time)))
    if overlay_time < 0.0:
        overlay_time = 0.0

    if overlay_time + overlay_duration > float(clip_duration or 0.0):
        overlay_time = max(0.0, float(clip_duration or 0.0) - overlay_duration)

    return {
        "search_keywords": search_keywords,
        "overlay_time": round(overlay_time, 3),
        "overlay_duration": round(overlay_duration, 3),
    }


def _search_pexels_image(search_query: str, api_key: str) -> Optional[Dict[str, Any]]:
    if not search_query:
        return None
    query = urllib.parse.quote(search_query)
    url = f"https://api.pexels.com/v1/search?query={query}&per_page=15&orientation=portrait"
    req = urllib.request.Request(url, headers={
        "Authorization": api_key,
        "User-Agent": "OpenShorts/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    photos = data.get("photos") if isinstance(data, dict) else None
    if not isinstance(photos, list) or not photos:
        return None
    choice = random.choice(photos)
    src = choice.get("src") or {}
    for key in ["large2x", "large", "medium", "original"]:
        if isinstance(src.get(key), str) and src.get(key).strip():
            return {
                "photo_url": str(src.get(key)).strip(),
                "photographer": choice.get("photographer") or "",
                "photo_id": choice.get("id"),
            }
    return None


def _download_stock_image(image_url: str, output_path: str) -> bool:
    req = urllib.request.Request(image_url, headers={"User-Agent": "OpenShorts/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(output_path, "wb") as out_file:
                out_file.write(response.read())
        return True
    except Exception:
        return False


def _apply_pexels_overlay_to_video(
    input_path: str,
    output_path: str,
    image_path: str,
    overlay_time: float,
    overlay_duration: float,
) -> bool:
    import cv2

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return False
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)
    cap.release()

    overlay_width = max(64, min(int(width * 0.82), width))
    overlay_height = max(64, min(int(height * 0.32), height))
    x_expr = f"({width}-overlay_w)/2"
    y_expr = f"{height}-overlay_h-40"
    fade_in = 0.25
    fade_out = 0.25
    scaled_image = (
        f"[1:v]format=rgba,scale='min({overlay_width},iw)':'min({overlay_height},ih)':force_original_aspect_ratio=decrease,"
        f"fade=t=in:st=0:d={fade_in}:alpha=1,"
        f"fade=t=out:st={max(0.0, overlay_duration - fade_out)}:d={fade_out}:alpha=1[img]"
    )
    filter_complex = (
        f"{scaled_image};"
        f"[0:v][img]overlay=x={x_expr}:y={y_expr}:format=auto:enable='between(t,{overlay_time},{overlay_time + overlay_duration})'"
    )

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_path,
        "-i",
        image_path,
        "-filter_complex",
        filter_complex,
        "-c:v",
        "libx264",
        "-preset",
        os.environ.get("OVERLAY_FFMPEG_PRESET", "veryfast").strip() or "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if _video_has_audio(input_path):
        command.extend(["-c:a", "copy"])
    else:
        command.append("-an")
    command.append(output_path)

    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"⚠️ Pexels overlay FFmpeg timeout after 90s")
        return False
    except subprocess.CalledProcessError as exc:
        stderr_text = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
        print(f"⚠️ Pexels overlay FFmpeg failed: {stderr_text}")
        return False


def _build_viral_effect_style_context(
    *,
    interview_mode: bool,
    teaser_plan: Optional[Dict[str, Any]],
) -> str:
    lines = [
        "The edit must look premium and intentional, never random or meme-chaotic.",
        "Use only a few pattern interrupts, timed to meaningful beats in the speech.",
    ]

    if interview_mode:
        lines.extend([
            "Interview mode: keep it restrained and professional.",
            "Prefer subtle punch-ins, gentle crop changes, and brief emphasis flashes only on major points.",
            "Avoid aggressive constant motion, goofy glitches, and over-stylized effects.",
        ])
    else:
        lines.extend([
            "Standard short mode: keep the pacing rhythmic and retention-focused.",
            "Prefer punch-ins, selective crop changes, brief light/contrast pops, and one or two sharp emphasis moments.",
            "Do not overuse flash effects; they should feel premium, not spammy.",
        ])

    if isinstance(teaser_plan, dict):
        effect_notes = str(teaser_plan.get("effect_notes") or "").strip()
        reason = str(teaser_plan.get("reason") or "").strip()
        if reason:
            lines.append(f"Cold open context: {reason}")
        if effect_notes:
            lines.append(f"Planner notes: {effect_notes}")

        pattern_interrupts = teaser_plan.get("pattern_interrupts") or []
        readable_notes = []
        for item in pattern_interrupts[:4]:
            if not isinstance(item, dict):
                continue
            readable_notes.append(
                f"{item.get('effect') or 'effect'} around {item.get('time') or '?'}s"
                + (f" ({item.get('reason')})" if item.get("reason") else "")
            )
        if readable_notes:
            lines.append("Suggested moments: " + "; ".join(readable_notes))

    return " ".join(lines)


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
    if name.startswith("viral_rendered_"):
        return "viral_render"
    if name.startswith("rendered_"):
        return "render"
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
        "viral_render": "Viral Render",
        "render": "Rendered",
        "subtitle": "Subtitles",
        "hook": "Hook",
        "edit": "Auto Edit",
        "translate": "Dub",
        "trim": "Trim",
    }.get(operation, operation.replace("_", " ").title())


def _default_transcript_source(operation: str) -> str:
    if operation == "render":
        return "original"
    return "audio" if operation in {"translate", "edit", "viral_render"} else "original"


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
        if fallback and os.path.exists(os.path.join(output_dir, fallback)):
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
    clip_default_transcript_source = clip.get("transcript_source") if operation == "original" else None
    transcript_source = version.get("transcript_source") or clip_default_transcript_source or _default_transcript_source(operation)
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
        fallback_filename = next(iter(filenames), "")
        current_filename = os.path.basename(clip.get("video_filename") or fallback_filename)
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


def _probe_video_stream_metrics(video_path: str) -> Dict[str, float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate",
        "-of",
        "json",
        video_path,
    ]
    payload = json.loads(subprocess.check_output(cmd).decode().strip() or "{}")
    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    avg_frame_rate = str(stream.get("avg_frame_rate") or "30/1").strip()

    fps = 30.0
    if "/" in avg_frame_rate:
        numerator, denominator = avg_frame_rate.split("/", 1)
        try:
            denominator_value = float(denominator or 1.0)
            fps = float(numerator or 0.0) / (denominator_value or 1.0)
        except (TypeError, ValueError, ZeroDivisionError):
            fps = 30.0
    else:
        try:
            fps = float(avg_frame_rate)
        except (TypeError, ValueError):
            fps = 30.0

    return {
        "width": width,
        "height": height,
        "fps": max(1.0, fps or 30.0),
        "duration": _probe_video_duration(video_path),
    }


def _probe_video_codec(video_path: str) -> str:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        return (subprocess.check_output(cmd).decode().strip() or "").lower()
    except Exception:
        return ""


def _is_valid_video_source(video_path: str, *, expected_codec: Optional[str] = None) -> bool:
    if not video_path or not os.path.exists(video_path):
        return False
    try:
        if os.path.getsize(video_path) <= 0:
            return False
        codec = _probe_video_codec(video_path)
        if expected_codec and codec != expected_codec:
            return False
        metrics = _probe_video_stream_metrics(video_path)
        return (
            int(metrics.get("width") or 0) > 0
            and int(metrics.get("height") or 0) > 0
            and float(metrics.get("duration") or 0.0) > 0.0
        )
    except Exception:
        return False


def _ensure_mp4_h264_source(video_path: str, output_dir: str) -> str:
    if not video_path or not os.path.exists(video_path):
        return video_path

    ext = os.path.splitext(video_path)[1].lower()
    codec = _probe_video_codec(video_path)
    if ext == ".mp4" and codec == "h264" and _is_valid_video_source(video_path, expected_codec="h264"):
        return video_path

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    safe_base = re.sub(r"[^a-zA-Z0-9_.-]+", "_", base_name).strip("._") or "source"
    working_path = os.path.join(output_dir, f"{safe_base}_working_h264.mp4")
    if os.path.exists(working_path):
        if _is_valid_video_source(working_path, expected_codec="h264"):
            return working_path
        try:
            os.remove(working_path)
            print(f"⚠️ Removed invalid H.264 working source: {working_path}")
        except OSError:
            pass

    print(
        "⚠️ Preview source is not Safari-compatible. "
        f"Converting to H.264 MP4 ({os.path.basename(video_path)})..."
    )
    temp_working_path = f"{working_path}.tmp_{os.getpid()}_{int(time.time() * 1000)}.mp4"
    convert_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        *ffmpeg_thread_args(),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        temp_working_path,
    ]
    try:
        subprocess.run(
            convert_cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        if _is_valid_video_source(temp_working_path, expected_codec="h264"):
            os.replace(temp_working_path, working_path)
            print(f"✅ Safari-compatible source ready: {working_path}")
            return working_path
        print("⚠️ Converted H.264 working source failed validation; falling back to original input.")
    except Exception as exc:
        print(f"⚠️ Failed to convert preview source to H.264 MP4: {exc}")

    for stale_path in (temp_working_path, working_path):
        if not os.path.exists(stale_path):
            continue
        try:
            os.remove(stale_path)
        except Exception:
            pass
    return video_path


def _normalize_social_audio_loudness(input_path: str, output_path: str, *, audio_bitrate: str = "192k") -> bool:
    if not input_path or not os.path.exists(input_path) or not _video_has_audio(input_path):
        return False

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        *ffmpeg_thread_args(include_filter_threads=True),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        str(audio_bitrate or "192k"),
        "-af",
        "loudnorm=I=-14:TP=-1.5:LRA=11",
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
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def _video_has_audio(video_path: str) -> bool:
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
        result = subprocess.check_output(cmd).decode().strip()
        return bool(result)
    except Exception:
        return False


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


def _default_hook_settings_from_clip(clip_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = clip_data.get("hook_settings")
    existing = existing if isinstance(existing, dict) else {}
    raw_text = existing.get("text") or clip_data.get("viral_hook_text") or ""
    text = _normalize_unicode_text(raw_text).strip()
    if not text:
        return None

    return {
        "text": text,
        "position": existing.get("position") or "top",
        "horizontal_position": existing.get("horizontal_position") or "center",
        "x_position": existing.get("x_position") if existing.get("x_position") is not None else 50,
        "y_position": existing.get("y_position") if existing.get("y_position") is not None else 12,
        "text_align": existing.get("text_align") or "center",
        "size": existing.get("size") or "M",
        "width_preset": existing.get("width_preset") or "wide",
        "font_family": existing.get("font_family"),
        "background_style": existing.get("background_style"),
        "start_zoom_factor": _clamp_zoom_factor(existing.get("start_zoom_factor"), DEFAULT_START_ZOOM_FACTOR),
        "zoom_factor": _clamp_zoom_factor(existing.get("zoom_factor"), DEFAULT_TARGET_ZOOM_FACTOR),
        "flash_mode": _normalize_pattern_flash_mode(existing.get("flash_mode")),
    }


def _build_hook_settings(req, clip_data: Dict) -> Optional[Dict]:
    existing = _default_hook_settings_from_clip(clip_data)
    raw_text = (req.text or "") if hasattr(req, "text") else (existing or {}).get("text", "")
    text = _normalize_unicode_text(raw_text).strip()
    if not text:
        return None

    start_zoom_factor = _clamp_zoom_factor(
        req.start_zoom_factor if getattr(req, "start_zoom_factor", None) is not None else (existing or {}).get("start_zoom_factor"),
        DEFAULT_START_ZOOM_FACTOR,
    )
    zoom_factor = _clamp_zoom_factor(
        req.zoom_factor if getattr(req, "zoom_factor", None) is not None else (existing or {}).get("zoom_factor"),
        DEFAULT_TARGET_ZOOM_FACTOR,
    )
    zoom_factor = max(zoom_factor, start_zoom_factor)

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
        "start_zoom_factor": start_zoom_factor,
        "zoom_factor": zoom_factor,
        "flash_mode": _normalize_pattern_flash_mode(
            getattr(req, "flash_mode", None) if getattr(req, "flash_mode", None) is not None else (existing or {}).get("flash_mode"),
        ),
    }


def _sanitize_subtitle_settings_dict(settings: Optional[Dict[str, Any]], clip_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if settings is None:
        return clip_data.get("subtitle_settings")
    if not isinstance(settings, dict):
        return clip_data.get("subtitle_settings")
    alignment = settings.get("position") or "bottom"
    y_position = settings.get("y_position")
    font_size = settings.get("font_size") or settings.get("fontSize") or 16
    try:
        font_size = int(font_size)
    except (TypeError, ValueError):
        font_size = 16
    return {
        "position": alignment,
        "y_position": y_position,
        "font_size": max(10, min(120, font_size)),
        "font_family": settings.get("font_family") or settings.get("fontFamily"),
        "background_style": settings.get("background_style") or settings.get("backgroundStyle"),
    }


def _sanitize_hook_settings_dict(settings: Optional[Dict[str, Any]], clip_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = _default_hook_settings_from_clip(clip_data)
    if settings is None:
        return existing
    if not isinstance(settings, dict):
        return existing

    # If the caller explicitly sends an empty/whitespace hook text, treat that as
    # "do not apply a hook" instead of silently falling back to an old saved hook.
    if "text" in settings and not _normalize_unicode_text(settings.get("text") or "").strip():
        return None

    text = _normalize_unicode_text(settings.get("text") or "").strip()
    if not text:
        return existing

    start_zoom_factor = _clamp_zoom_factor(
        settings.get("start_zoom_factor") if settings.get("start_zoom_factor") is not None else settings.get("startZoomFactor") if settings.get("startZoomFactor") is not None else (existing or {}).get("start_zoom_factor"),
        DEFAULT_START_ZOOM_FACTOR,
    )
    zoom_factor = _clamp_zoom_factor(
        settings.get("zoom_factor") if settings.get("zoom_factor") is not None else settings.get("zoomFactor") if settings.get("zoomFactor") is not None else (existing or {}).get("zoom_factor"),
        DEFAULT_TARGET_ZOOM_FACTOR,
    )
    zoom_factor = max(zoom_factor, start_zoom_factor)

    return {
        "text": text,
        "position": settings.get("position") or (existing or {}).get("position") or "top",
        "horizontal_position": settings.get("horizontal_position") or settings.get("horizontalPosition") or (existing or {}).get("horizontal_position") or "center",
        "x_position": settings.get("x_position") if settings.get("x_position") is not None else settings.get("xPosition") if settings.get("xPosition") is not None else (existing or {}).get("x_position"),
        "y_position": settings.get("y_position") if settings.get("y_position") is not None else settings.get("yPosition") if settings.get("yPosition") is not None else (existing or {}).get("y_position"),
        "text_align": settings.get("text_align") or settings.get("textAlign") or (existing or {}).get("text_align") or "center",
        "size": settings.get("size") or (existing or {}).get("size") or "M",
        "width_preset": settings.get("width_preset") or settings.get("widthPreset") or (existing or {}).get("width_preset") or "wide",
        "font_family": settings.get("font_family") or settings.get("fontFamily") or (existing or {}).get("font_family"),
        "background_style": settings.get("background_style") or settings.get("backgroundStyle") or (existing or {}).get("background_style"),
        "start_zoom_factor": start_zoom_factor,
        "zoom_factor": zoom_factor,
        "flash_mode": _normalize_pattern_flash_mode(
            settings.get("flash_mode") if settings.get("flash_mode") is not None else settings.get("flashMode") if settings.get("flashMode") is not None else (existing or {}).get("flash_mode"),
        ),
    }


def _resolve_clip_source_input_path(
    job_id: str,
    output_dir: str,
    clip: Dict[str, Any],
    *,
    ensure_h264: bool = True,
) -> Optional[str]:
    candidates: List[str] = []
    manifest = load_job_manifest(output_dir)
    manifest_input = manifest.get("pipeline", {}).get("input_video")
    if manifest_input:
        candidates.append(manifest_input)
    for key in (
        "source_video_filename",
        "preview_video_filename",
        "original_video_filename",
        "base_video_filename",
        "video_filename",
    ):
        value = clip.get(key)
        if value:
            candidates.append(os.path.join(output_dir, os.path.basename(value)))

    seen = set()
    for path in candidates:
        if not path:
            continue
        normalized = os.path.abspath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return _ensure_mp4_h264_source(normalized, output_dir) if ensure_h264 else normalized
    return None


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
            preferred_language = _resolve_subtitle_language_hint(
                metadata_data={"transcript": transcript} if isinstance(transcript, dict) else None,
                clip_data=clip_data,
                fallback_filename=os.path.basename(base_input_path),
            )
            subtitle_transcript, subtitle_clip_start, subtitle_clip_end, subtitle_source_mode = _resolve_subtitle_transcript_payload(
                metadata_data={"transcript": transcript} if isinstance(transcript, dict) else None,
                clip_data=clip_data,
                input_path=base_input_path,
                preferred_language=preferred_language,
                transcript_source_hint="original",
                transcript_start=clip_data.get("start"),
                transcript_end=clip_data.get("end"),
            )
            print(f"📝 Stack subtitle transcript mode: {subtitle_source_mode}")
            if is_dubbed:
                print("🗣️ Dubbed source detected: subtitle transcription runs directly on dubbed audio.")

            success = burn_subtitles(
                current_input,
                subtitle_transcript,
                subtitle_clip_start,
                subtitle_clip_end,
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


def _coerce_max_clips(value, default: int = 10, minimum: int = 1, maximum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _coerce_tight_edit_preset(value, default: str = DEFAULT_TIGHT_EDIT_PRESET) -> str:
    return normalize_tight_edit_preset(value, default)


def _normalize_ollama_base_url(base_url: Optional[str]) -> str:
    normalized = (base_url or "http://127.0.0.1:11434").strip().rstrip("/")
    if not normalized:
        normalized = "http://127.0.0.1:11434"

    # In Docker bridge mode, localhost points to the container itself.
    # If user configured localhost/127.0.0.1 for a host Ollama daemon,
    # transparently route through host-gateway alias.
    in_docker = os.path.exists("/.dockerenv")
    network_mode = (os.environ.get("NETWORK_MODE") or "").strip().lower()
    bridge_mode = in_docker and network_mode != "host"
    if bridge_mode:
        try:
            parsed = urllib.parse.urlparse(normalized)
            host = (parsed.hostname or "").lower()
            if host in {"127.0.0.1", "localhost", "::1"}:
                port = parsed.port or 11434
                scheme = parsed.scheme or "http"
                path = parsed.path or ""
                query = f"?{parsed.query}" if parsed.query else ""
                normalized = f"{scheme}://host.docker.internal:{port}{path}{query}".rstrip("/")
        except Exception:
            pass

    return normalized


def _normalize_ollama_model_name(model_name: Optional[str]) -> str:
    normalized = (model_name or "").strip()
    alias_map = {
        "gemma-3-12b": "gemma3:12b",
        "gemma-3-12b:latest": "gemma3:12b",
        "gemma3-12b": "gemma3:12b",
        "gemma3-12b:latest": "gemma3:12b",
    }
    return alias_map.get(normalized.lower(), normalized)


NETWORK_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "failed to resolve",
    "name or service not known",
    "nodename nor servname provided",
    "getaddrinfo failed",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "connection aborted",
    "timed out",
    "timeout",
    "tls handshake timeout",
)

DNS_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "failed to resolve",
    "name or service not known",
    "nodename nor servname provided",
    "getaddrinfo failed",
)

NETWORK_DIAGNOSTIC_TARGETS = (
    ("www.youtube.com", 443),
    ("api.upload-post.com", 443),
)


def _network_error_text(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    if reason not in (None, exc):
        return str(reason)
    return str(exc)


def _is_network_resolution_error(value: Any) -> bool:
    lower = str(value or "").lower()
    if not lower:
        return False
    return any(marker in lower for marker in DNS_ERROR_MARKERS)


def _is_network_connectivity_error(value: Any) -> bool:
    lower = str(value or "").lower()
    if not lower:
        return False
    return any(marker in lower for marker in NETWORK_ERROR_MARKERS)


def _hostname_from_target(target: str) -> str:
    parsed = urllib.parse.urlparse(str(target or ""))
    return parsed.hostname or str(target or "")


def _format_outbound_network_error(service_name: str, target: str, exc: Exception) -> str:
    host = _hostname_from_target(target)
    detail = _network_error_text(exc)
    if _is_network_resolution_error(detail):
        return (
            f"DNS resolution failed while contacting {service_name} ({host}). "
            "Check the backend container DNS configuration and outbound network access, then retry. "
            f"Original error: {detail}"
        )
    if _is_network_connectivity_error(detail):
        return (
            f"{service_name} is currently unreachable ({host}). "
            "Check outbound network access, proxy/firewall settings, then retry. "
            f"Original error: {detail}"
        )
    return f"{service_name} request failed ({host}): {detail}"


def _diagnose_hostname_resolution(host: str, port: int) -> Dict[str, Any]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = sorted({item[4][0] for item in infos})
        return {
            "host": host,
            "port": port,
            "ok": True,
            "addresses": addresses[:8],
            "error": None,
        }
    except Exception as exc:
        return {
            "host": host,
            "port": port,
            "ok": False,
            "addresses": [],
            "error": str(exc),
        }


def _read_resolver_config_preview() -> List[str]:
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f.readlines()[:20]]
    except Exception as exc:
        return [f"<unavailable: {exc}>"]


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
        detail = (
            f"Could not reach Ollama at {normalized_base_url}: {exc.reason}. "
            "If Ollama runs on the host, ensure it listens on a non-loopback interface "
            "(e.g. OLLAMA_HOST=0.0.0.0:11434) or run the backend with host networking."
        )
        raise HTTPException(
            status_code=502,
            detail=detail,
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


YOUTUBE_AUTH_MODES = {"auto", "cookies_text", "cookies_file", "browser"}
YOUTUBE_BROWSER_ALIASES = {
    "edge": "edge",
    "msedge": "edge",
    "chrome": "chrome",
    "chromium": "chromium",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
    "safari": "safari",
    "vivaldi": "vivaldi",
}


def _normalize_youtube_auth_mode(value: Optional[str]) -> str:
    mode = (value or "auto").strip().lower()
    return mode if mode in YOUTUBE_AUTH_MODES else "auto"


def _normalize_youtube_browser(value: Optional[str]) -> Optional[str]:
    browser = (value or "").strip().lower()
    if not browser or browser in {"auto", "none"}:
        return None
    return YOUTUBE_BROWSER_ALIASES.get(browser)


def _youtube_cookies_file_path() -> str:
    configured = (os.environ.get("YOUTUBE_COOKIES_FILE") or "").strip()
    return configured or "/app/cookies.txt"


def _youtube_cookie_file_status() -> Dict[str, Any]:
    path = _youtube_cookies_file_path()
    exists = os.path.exists(path)
    result: Dict[str, Any] = {
        "cookies_file_path": path,
        "cookies_file_exists": exists,
        "cookies_file_size": 0,
        "cookies_file_mtime": None,
        "cookies_file_has_youtube_domain": False,
        "cookies_file_readable": False,
        "cookies_file_error": None,
    }
    if not exists:
        return result

    try:
        stat = os.stat(path)
        result["cookies_file_size"] = stat.st_size
        result["cookies_file_mtime"] = stat.st_mtime
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        lowered = content.lower()
        result["cookies_file_has_youtube_domain"] = ".youtube.com" in lowered or "youtube.com" in lowered
        result["cookies_file_readable"] = True
    except Exception as exc:
        result["cookies_file_error"] = str(exc)
    return result


def _apply_youtube_auth_env(
    env: Dict[str, str],
    mode: Optional[str],
    browser: Optional[str],
    cookies_text: Optional[str],
) -> tuple[str, Optional[str], bool]:
    resolved_mode = _normalize_youtube_auth_mode(mode)
    resolved_browser = _normalize_youtube_browser(browser)
    cleaned_cookies = (cookies_text or "").strip()

    env["YOUTUBE_AUTH_MODE"] = resolved_mode

    if resolved_browser:
        env["YOUTUBE_COOKIES_FROM_BROWSER"] = resolved_browser
    else:
        env.pop("YOUTUBE_COOKIES_FROM_BROWSER", None)

    if cleaned_cookies:
        env["YOUTUBE_COOKIES"] = cleaned_cookies
    else:
        env.pop("YOUTUBE_COOKIES", None)

    return resolved_mode, resolved_browser, bool(cleaned_cookies)


def _persist_youtube_cookies_text(cookies_text: str) -> Dict[str, Any]:
    preferred_path = _youtube_cookies_file_path()
    fallback_path = "/tmp/openshorts/cookies.txt"
    write_candidates = [preferred_path]
    if os.path.abspath(preferred_path) != os.path.abspath(fallback_path):
        write_candidates.append(fallback_path)

    saved_path = None
    last_error = None
    for target_path in write_candidates:
        target_dir = os.path.dirname(target_path) or "."
        try:
            os.makedirs(target_dir, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(cookies_text)
            try:
                os.chmod(target_path, 0o600)
            except Exception:
                pass
            saved_path = target_path
            break
        except Exception as exc:
            last_error = exc

    if not saved_path:
        raise RuntimeError(f"Failed to save cookies file: {last_error}")

    os.environ["YOUTUBE_COOKIES_FILE"] = saved_path
    status = _youtube_cookie_file_status()
    status["saved_path"] = saved_path
    return status


def _import_youtube_cookies_from_browser(browser: Optional[str]) -> Dict[str, Any]:
    normalized_browser = _normalize_youtube_browser(browser) or "chrome"

    from yt_dlp.cookies import YDLLogger, YoutubeDLCookieJar, extract_cookies_from_browser

    try:
        browser_cookies = extract_cookies_from_browser(normalized_browser, logger=YDLLogger())
    except Exception as exc:
        raise RuntimeError(
            f"Could not read cookies from browser '{normalized_browser}'. "
            f"Ensure the browser is installed locally on the host and fully closed. {exc}"
        )

    temp_cookie_path = os.path.join("/tmp", f"youtube_browser_import_{secrets.token_hex(8)}.txt")
    jar = YoutubeDLCookieJar(temp_cookie_path)
    imported_count = 0
    for cookie in browser_cookies:
        imported_count += 1
        jar.set_cookie(cookie)

    if imported_count == 0:
        raise RuntimeError(f"No cookies found in browser '{normalized_browser}'.")

    jar.save(ignore_discard=True, ignore_expires=True)
    with open(temp_cookie_path, "r", encoding="utf-8", errors="ignore") as f:
        cookie_text = f.read()
    try:
        os.remove(temp_cookie_path)
    except Exception:
        pass

    status = _persist_youtube_cookies_text(cookie_text)
    status["browser"] = normalized_browser
    status["imported_cookie_count"] = imported_count
    return status


def _settings_sync_record_path(sync_id: str) -> str:
    return os.path.join(SETTINGS_SYNC_DIR, f"{sync_id}.json")


def _settings_sync_cleanup_expired() -> None:
    if SETTINGS_SYNC_TTL_DAYS <= 0:
        return
    ttl_seconds = SETTINGS_SYNC_TTL_DAYS * 86400
    now = time.time()
    for path in glob.glob(os.path.join(SETTINGS_SYNC_DIR, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            updated_at = float(payload.get("updated_at") or payload.get("created_at") or 0.0)
            if updated_at and now - updated_at > ttl_seconds:
                os.remove(path)
        except Exception:
            continue


def _derive_settings_sync_key(secret_text: str, salt_bytes: bytes) -> bytes:
    raw_key = hashlib.pbkdf2_hmac(
        "sha256",
        secret_text.encode("utf-8"),
        salt_bytes,
        200_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw_key)


def _parse_settings_sync_code(sync_code: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", "", (sync_code or "").strip())
    if "." not in normalized:
        raise ValueError("Invalid sync code format")
    sync_id, secret_text = normalized.split(".", 1)
    if not sync_id or not secret_text:
        raise ValueError("Invalid sync code format")
    if not re.fullmatch(r"[a-f0-9]{12,64}", sync_id):
        raise ValueError("Invalid sync code id")
    return sync_id, secret_text


def _read_backend_youtube_cookies(max_bytes: int = 1024 * 1024) -> Optional[str]:
    path = _youtube_cookies_file_path()
    if not path or not os.path.exists(path):
        return None
    size = os.path.getsize(path)
    if size <= 0 or size > max_bytes:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


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
        slot_acquired = False
        try:
            # Hold a worker slot first. This keeps waiting jobs visible inside
            # job_queue until they can actually start.
            await concurrency_semaphore.acquire()
            slot_acquired = True

            # Wait for a job
            job_item = await job_queue.get()
            if isinstance(job_item, (list, tuple)):
                job_id, queue_token = job_item[0], job_item[1]
            else:
                job_id, queue_token = job_item, None
            job = jobs.get(job_id)
            if queue_token and job and job.get("queue_token") != queue_token:
                print(f"⏭️ Skipping stale queue entry for job: {job_id}")
                concurrency_semaphore.release()
                slot_acquired = False
                job_queue.task_done()
                continue
            if job and (job.get("cancel_requested") or job.get("status") == "cancelled"):
                print(f"⏹️ Skipping cancelled queued job: {job_id}")
                concurrency_semaphore.release()
                slot_acquired = False
                job_queue.task_done()
                continue

            job = jobs.get(job_id)
            if not job:
                concurrency_semaphore.release()
                slot_acquired = False
                job_queue.task_done()
                continue
            if queue_token and job.get("queue_token") != queue_token:
                print(f"⏭️ Skipping stale dequeued entry for job: {job_id}")
                concurrency_semaphore.release()
                slot_acquired = False
                job_queue.task_done()
                continue
            if job.get("cancel_requested") or job.get("status") == "cancelled":
                print(f"⏹️ Skipping cancelled dequeued job: {job_id}")
                concurrency_semaphore.release()
                slot_acquired = False
                job_queue.task_done()
                continue
            print(f"🔄 Acquired slot for job: {job_id}")
            slot_acquired = False

            # Process in background task to not block the loop (allowing other slots to fill)
            asyncio.create_task(run_job_wrapper(job_id, queue_token))

        except Exception as e:
            if slot_acquired:
                concurrency_semaphore.release()
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
    _recover_interrupted_bulk_operations()
    restore_orphaned_projects()
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
    gemini_model: Optional[str] = None
    openai_model: Optional[str] = None
    claude_model: Optional[str] = None
    minimax_model: Optional[str] = None
    tight_edit_preset: Optional[str] = None
    analysis_only: Optional[bool] = None
    force_reanalysis: Optional[bool] = None
    youtube_auth_mode: Optional[str] = None
    youtube_cookies_from_browser: Optional[str] = None
    youtube_cookies: Optional[str] = None
    upload_post_profile: Optional[str] = None
    profile_context: Optional[str] = None
    job_instructions: Optional[str] = None


class BulkOperationItemRequest(BaseModel):
    clip_index: int
    hook_text: Optional[str] = None
    scheduled_date: Optional[str] = None
    clip_label: Optional[str] = None


class BulkOperationRenderConfigRequest(BaseModel):
    apply_tight_edit: Optional[bool] = True
    tight_edit_preset: Optional[str] = None
    apply_subtitles: Optional[bool] = True
    subtitle_settings: Optional[Dict[str, Any]] = None
    apply_hook: Optional[bool] = True
    hook_style: Optional[Dict[str, Any]] = None
    pattern_flash_mode: Optional[str] = None
    apply_stock_overlay: Optional[bool] = False


class BulkOperationPostConfigRequest(BaseModel):
    platforms: List[str]
    first_comment: Optional[str] = None
    timezone: Optional[str] = "UTC"
    instagram_share_mode: Optional[str] = "CUSTOM"
    tiktok_post_mode: Optional[str] = "DIRECT_POST"
    tiktok_is_aigc: Optional[bool] = False
    facebook_page_id: Optional[str] = None
    pinterest_board_id: Optional[str] = None


class BulkOperationRuntimeRequest(BaseModel):
    provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    claude_api_key: Optional[str] = None
    claude_model: Optional[str] = None
    minimax_api_key: Optional[str] = None
    minimax_auth_mode: Optional[str] = None
    minimax_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    pexels_api_key: Optional[str] = None
    upload_post_api_key: Optional[str] = None
    upload_post_user_id: Optional[str] = None
    podcast_dm_relay_url: Optional[str] = None
    podcast_dm_relay_password: Optional[str] = None


class BulkOperationStartRequest(BaseModel):
    job_id: str
    mode: str
    items: List[BulkOperationItemRequest]
    render: Optional[BulkOperationRenderConfigRequest] = None
    post: Optional[BulkOperationPostConfigRequest] = None
    runtime: Optional[BulkOperationRuntimeRequest] = None


class BulkOperationControlRequest(BaseModel):
    runtime: Optional[BulkOperationRuntimeRequest] = None


class YouTubeCookiesSaveRequest(BaseModel):
    cookies_text: str


class YouTubeBrowserImportRequest(BaseModel):
    browser: Optional[str] = None


class SettingsSyncCreateRequest(BaseModel):
    settings: Dict[str, Any]
    include_youtube_cookies: Optional[bool] = True


class SettingsSyncLoadRequest(BaseModel):
    sync_code: str
    apply_youtube_cookies: Optional[bool] = True


class JobOverlayDefaultsRequest(BaseModel):
    job_id: str
    subtitle_style: Optional[Dict[str, Any]] = None
    hook_style: Optional[Dict[str, Any]] = None


class JobSocialDefaultsRequest(BaseModel):
    job_id: str
    instagram_collaborators: Optional[str] = None
    podcast_youtube_url: Optional[str] = None
    podcast_link_url: Optional[str] = None
    podcast_keyword: Optional[str] = None
    podcast_comment_template: Optional[str] = None
    podcast_dm_enabled: Optional[bool] = None


class JobAnalysisContextRequest(BaseModel):
    upload_post_profile: Optional[str] = None
    profile_context: Optional[str] = None
    job_instructions: Optional[str] = None


class ClipTextMetadataUpdateRequest(BaseModel):
    job_id: str
    clip_index: int
    video_title_for_youtube_short: Optional[str] = None
    video_description_for_tiktok: Optional[str] = None
    video_description_for_instagram: Optional[str] = None
    instagram_collaborators: Optional[str] = None
    start_zoom_factor: Optional[float] = None
    zoom_factor: Optional[float] = None
    flash_mode: Optional[str] = None


class ClipRangeAdjustRequest(BaseModel):
    job_id: str
    clip_index: int
    delta_start: Optional[float] = 0.0
    delta_end: Optional[float] = 0.0
    absolute_start: Optional[float] = None
    absolute_end: Optional[float] = None


class LongformProjectCreateRequest(BaseModel):
    project_name: str
    mode: Optional[str] = "single"
    config: Optional[Dict[str, Any]] = None
    ai: Optional[Dict[str, Any]] = None


class LongformProjectUpdateRequest(BaseModel):
    project_name: Optional[str] = None
    mode: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    ai: Optional[Dict[str, Any]] = None


class LongformFileReorderRequest(BaseModel):
    role: str
    ordered_ids: List[str]


class LongformFilePathImportRequest(BaseModel):
    role: str
    source_paths: List[str]


class LongformThumbnailGenerateRequest(BaseModel):
    prompt: str
    providers: List[str]
    count_per_provider: int = 3
    selected_stills: Dict[str, str]
    provider_models: Optional[Dict[str, str]] = None
    reference_order: Optional[List[str]] = None
    feedback: Optional[str] = None
    ai: Optional[Dict[str, Any]] = None


class LongformThumbnailTextOverlayRequest(BaseModel):
    prompt: Optional[str] = None
    count: int = 10
    ai: Optional[Dict[str, Any]] = None


class LongformPipelineRuntimeRequest(BaseModel):
    ai: Optional[Dict[str, Any]] = None

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


def _extract_actionable_job_error(logs: Optional[List[str]]) -> Optional[str]:
    if not logs:
        return None

    cleaned = [str(line).strip() for line in logs if str(line).strip()]
    if not cleaned:
        return None

    for line in reversed(cleaned):
        lower = line.lower()
        if lower.startswith("reason:"):
            reason = line.split(":", 1)[1].strip()
            if reason:
                return reason

    prioritized_markers = (
        "runtimeerror:",
        "unable to access a high-quality youtube source",
        "unable to download a usable high-quality youtube source",
        "unable to download api page",
        "failed to resolve",
        "temporary failure in name resolution",
        "execution error:",
        "fatal error",
    )
    for marker in prioritized_markers:
        for line in reversed(cleaned):
            lower = line.lower()
            if marker not in lower:
                continue
            if lower.startswith("runtimeerror:"):
                return line.split(":", 1)[1].strip() or line
            if lower.startswith("execution error:"):
                return line.split(":", 1)[1].strip() or line
            return line

    for line in reversed(cleaned):
        lower = line.lower()
        if "error" in lower or "failed" in lower:
            return line
    return None


async def run_job(job_id, job_data, queue_token=None):
    """Executes the subprocess for a specific job."""
    if queue_token and job_data.get("queue_token") != queue_token:
        print(f"⏭️ Not starting stale job {job_id}")
        return
    if job_data.get("cancel_requested") or job_data.get("status") == "cancelled":
        print(f"⏹️ Not starting cancelled job {job_id}")
        return

    cmd = job_data['cmd']
    base_env = dict(job_data['env'])
    output_dir = job_data['output_dir']
    whisper_retry_stage = 0

    def _should_retry_after_native_whisper_crash(returncode: int, log_lines: List[str]) -> bool:
        if returncode != -11:
            return False
        recent = "\n".join((log_lines or [])[-120:]).lower()
        whisper_markers = [
            "faster-whisper runtime ready",
            "transcribing video with faster-whisper",
            "device=cuda",
            "whisper language-aware model routing",
        ]
        return any(marker in recent for marker in whisper_markers)

    def _build_whisper_cuda_safe_retry_env(source_env: Dict[str, str]) -> Dict[str, str]:
        next_env = dict(source_env)
        next_env["WHISPER_DEVICE"] = "cuda"
        next_env["WHISPER_COMPUTE_TYPE"] = "int8"
        next_env["WHISPER_SAFE_MODE"] = "true"
        next_env.setdefault("WHISPER_MODEL", "distil-large-v3")
        if (next_env.get("WHISPER_LANGUAGE") or "").strip().lower().split("-")[0] == "de":
            de_model = (
                next_env.get("WHISPER_MODEL_DE")
                or next_env.get("WHISPER_CPU_MODEL_DE")
                or "primeline/whisper-large-v3-german"
            )
            next_env["WHISPER_MODEL_DE"] = de_model
            next_env["WHISPER_CPU_MODEL_DE"] = next_env.get("WHISPER_CPU_MODEL_DE") or de_model
            next_env["WHISPER_CUDA_MODEL_FALLBACKS"] = next_env.get(
                "WHISPER_CUDA_MODEL_FALLBACKS_DE",
                "large-v3,medium,small,base",
            )
        return next_env

    def _build_whisper_cpu_safe_retry_env(source_env: Dict[str, str]) -> Dict[str, str]:
        next_env = dict(source_env)
        next_env["WHISPER_DEVICE"] = "cpu"
        next_env["WHISPER_COMPUTE_TYPE"] = "int8"
        next_env["WHISPER_SAFE_MODE"] = "true"
        next_env["WHISPER_CPU_MODEL"] = "medium"
        if (next_env.get("WHISPER_LANGUAGE") or "").strip().lower().split("-")[0] == "de":
            de_model = (
                source_env.get("WHISPER_CPU_MODEL_DE")
                or source_env.get("WHISPER_MODEL_DE")
                or "primeline/whisper-large-v3-german"
            )
            next_env["WHISPER_MODEL_DE"] = source_env.get("WHISPER_MODEL_DE") or de_model
            next_env["WHISPER_CPU_MODEL_DE"] = de_model
            next_env["WHISPER_MODEL_FALLBACKS"] = source_env.get(
                "WHISPER_MODEL_FALLBACKS_DE",
                "large-v3,medium,small,base",
            )
        else:
            next_env["WHISPER_CPU_MODEL_DE"] = "medium"
        return next_env

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
        env = dict(base_env)
        while True:
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
                except Exception:
                    pass

            returncode = process.returncode
            t_log.join(timeout=1)

            if (
                not jobs[job_id].get("cancel_requested")
                and whisper_retry_stage < 2
                and _should_retry_after_native_whisper_crash(returncode, jobs[job_id].get("logs") or [])
            ):
                whisper_retry_stage += 1
                if whisper_retry_stage == 1:
                    env = _build_whisper_cuda_safe_retry_env(base_env)
                    retry_message = (
                        "Native Whisper/CUDA crash erkannt. "
                        "Starte denselben Job einmal mit konservativerem CUDA-Setup neu (int8)."
                    )
                else:
                    env = _build_whisper_cpu_safe_retry_env(base_env)
                    retry_message = (
                        "CUDA-Retry ist erneut abgestuerzt. "
                        "Starte denselben Job einmal mit CPU-Safe-Fallback neu."
                    )
                jobs[job_id]['logs'].append(retry_message)
                append_job_log(output_dir, retry_message)
                print(f"⚠️ [run_job] {job_id}: {retry_message}")
                jobs[job_id]['process'] = None
                continue
            break

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

            manifest = load_job_manifest(output_dir) or {}
            request_defaults = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
            if request_defaults.get("destination_url"):
                _persist_job_social_defaults(
                    job_id,
                    podcast_link_url=request_defaults.get("destination_url"),
                    podcast_keyword=request_defaults.get("destination_keyword") or "Video",
                    podcast_dm_enabled=True,
                )

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
                failure_error = (
                    _extract_actionable_job_error(jobs[job_id].get("logs"))
                    or f"Process failed with exit code {returncode}"
                )
                jobs[job_id]['error'] = failure_error
                jobs[job_id]['logs'].append(f"Process failed with exit code {returncode}")
                update_job_manifest(output_dir, {
                    "status": "failed",
                    "error": failure_error,
                    "can_resume": True,
                })

    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['job_state'] = 'failed'
        jobs[job_id]['can_resume'] = True
        jobs[job_id]['error'] = str(e)
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
    tight_edit_preset: Optional[str] = Form(None),
    analysis_only: Optional[str] = Form(None),
    youtube_auth_mode: Optional[str] = Form(None),
    youtube_cookies_from_browser: Optional[str] = Form(None),
    youtube_cookies: Optional[str] = Form(None),
    upload_post_profile: Optional[str] = Form(None),
    profile_context: Optional[str] = Form(None),
    job_instructions: Optional[str] = Form(None),
    destination_url: Optional[str] = Form(None),
    destination_keyword: Optional[str] = Form(None),
):
    provider = (request.headers.get("X-LLM-Provider") or "gemini").strip().lower()
    api_key = request.headers.get("X-Gemini-Key")
    gemini_model = request.headers.get("X-Gemini-Model")
    openai_key = request.headers.get("X-OpenAI-Key")
    openai_model = request.headers.get("X-OpenAI-Model")
    claude_key = request.headers.get("X-Claude-Key")
    claude_model = request.headers.get("X-Claude-Model")
    minimax_key = request.headers.get("X-Minimax-Key")
    minimax_auth_mode = request.headers.get("X-Minimax-Auth-Mode")
    minimax_model = request.headers.get("X-Minimax-Model")
    ollama_base_url = request.headers.get("X-Ollama-Base-Url")
    ollama_model = request.headers.get("X-Ollama-Model")
    huggingface_key = request.headers.get("X-HuggingFace-Key")

    if provider == "gemini" and not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")
    if provider == "openai" and not openai_key:
        raise HTTPException(status_code=400, detail="Missing X-OpenAI-Key header")
    if provider == "claude" and not claude_key:
        raise HTTPException(status_code=400, detail="Missing X-Claude-Key header")
    if provider == "minimax" and not minimax_key:
        raise HTTPException(status_code=400, detail="Missing X-Minimax-Key header")
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
        tight_edit_preset = body.get("tight_edit_preset")
        analysis_only = body.get("analysis_only")
        youtube_auth_mode = body.get("youtube_auth_mode")
        youtube_cookies_from_browser = body.get("youtube_cookies_from_browser")
        youtube_cookies = body.get("youtube_cookies")
        upload_post_profile = body.get("upload_post_profile")
        profile_context = body.get("profile_context")
        job_instructions = body.get("job_instructions")
        destination_url = body.get("destination_url")
        destination_keyword = body.get("destination_keyword")

    interview_mode_enabled = _coerce_bool(interview_mode)
    allow_long_clips_enabled = _coerce_bool(allow_long_clips)
    max_clips_value = _coerce_max_clips(max_clips)
    tight_edit_preset_value = _coerce_tight_edit_preset(tight_edit_preset)
    analysis_only_enabled = _coerce_bool(analysis_only)
    normalized_destination_url = _normalize_destination_url(destination_url or "")
    if destination_url and not normalized_destination_url:
        raise HTTPException(status_code=400, detail="Ziel-Link muss eine gueltige HTTP(S)-URL mit Hostname sein.")
    if youtube_cookies and len(str(youtube_cookies)) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="youtube_cookies payload is too large")

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
        "tight_edit_preset": tight_edit_preset_value,
        "analysis_only": analysis_only_enabled,
        "upload_post_profile": str(upload_post_profile or "").strip(),
        "profile_context": str(profile_context or "").strip(),
        "job_instructions": str(job_instructions or "").strip(),
        "destination_url": normalized_destination_url,
        "destination_keyword": _normalize_podcast_keyword(destination_keyword or "Video"),
    }
    analysis_context = _write_analysis_context(job_output_dir, request_meta)

    # Prepare Command
    cmd = ["python", "-u", "main.py"] # -u for unbuffered
    env = os.environ.copy()
    env["LLM_PROVIDER"] = provider
    env["SHORTFORM_ANALYSIS_CONTEXT_FILE"] = _analysis_context_path(job_output_dir)
    env["SHORTFORM_UPLOAD_PROFILE"] = analysis_context.get("profile_name") or ""
    env["SHORTFORM_PROFILE_CONTEXT"] = analysis_context.get("profile_context") or ""
    env["SHORTFORM_JOB_INSTRUCTIONS"] = analysis_context.get("job_instructions") or ""
    if api_key:
        env["GEMINI_API_KEY"] = api_key
    if gemini_model:
        env["GEMINI_MODEL"] = gemini_model
    if openai_key:
        env["OPENAI_API_KEY"] = openai_key
    if openai_model:
        env["OPENAI_MODEL"] = openai_model
    if claude_key:
        env["CLAUDE_API_KEY"] = claude_key
    if claude_model:
        env["CLAUDE_MODEL"] = claude_model
    if minimax_key:
        env["MINIMAX_API_KEY"] = minimax_key
    if minimax_auth_mode:
        env["MINIMAX_AUTH_MODE"] = minimax_auth_mode
    if minimax_model:
        env["MINIMAX_MODEL"] = minimax_model
    if ollama_base_url:
        env["OLLAMA_BASE_URL"] = ollama_base_url
    if ollama_model:
        env["OLLAMA_MODEL"] = ollama_model
    if huggingface_key:
        env["HF_TOKEN"] = huggingface_key
        env["PYANNOTE_AUTH_TOKEN"] = huggingface_key
    youtube_auth_mode_value, youtube_browser_value, youtube_inline_present = _apply_youtube_auth_env(
        env,
        youtube_auth_mode,
        youtube_cookies_from_browser,
        youtube_cookies,
    )
    request_meta["youtube_auth_mode"] = youtube_auth_mode_value
    request_meta["youtube_cookies_from_browser"] = youtube_browser_value
    request_meta["youtube_inline_cookies_present"] = youtube_inline_present

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
        limit_bytes = MAX_FILE_SIZE_BYTES

        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read 1MB chunks
                size += len(content)
                if limit_bytes is not None and size > limit_bytes:
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
    cmd.extend(["--tight-edit-preset", tight_edit_preset_value])
    if analysis_only_enabled:
        cmd.append("--analysis-only")
    if analysis_only_enabled and url:
        cmd.append("--keep-original")
    append_job_log(job_output_dir, f"Job {job_id} queued.")
    update_job_manifest(job_output_dir, {
        "job_id": job_id,
        "status": "queued",
        "error": None,
        "can_resume": True,
        "request": request_meta,
        "provider": {
            "name": provider,
            "gemini_model": gemini_model,
            "openai_model": openai_model,
            "claude_model": claude_model,
            "minimax_model": minimax_model,
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
    overview = _queue_overview()
    return _attach_queue_metadata({"job_id": job_id, "status": "queued"}, overview)


@app.get("/api/youtube/auth/status")
async def youtube_auth_status():
    file_status = _youtube_cookie_file_status()
    env_mode = _normalize_youtube_auth_mode(os.environ.get("YOUTUBE_AUTH_MODE"))
    env_browser = _normalize_youtube_browser(os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER"))
    env_inline = bool((os.environ.get("YOUTUBE_COOKIES") or "").strip())
    inferred_logged_in = bool(file_status.get("cookies_file_has_youtube_domain")) or env_inline

    return {
        "mode_default": env_mode,
        "browser_default": env_browser,
        "inline_cookies_env_present": env_inline,
        "logged_in": inferred_logged_in,
        **file_status,
    }


@app.post("/api/youtube/auth/cookies")
async def save_youtube_cookies(req: YouTubeCookiesSaveRequest):
    cookies_text = (req.cookies_text or "").strip()
    if not cookies_text:
        raise HTTPException(status_code=400, detail="cookies_text is required")
    if len(cookies_text) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="cookies_text is too large")
    try:
        status = _persist_youtube_cookies_text(cookies_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "success": True,
        "message": f"Saved cookies to {status.get('saved_path')}",
        **status,
    }


@app.post("/api/youtube/auth/import-browser")
async def import_youtube_cookies_from_browser(req: YouTubeBrowserImportRequest):
    try:
        status = _import_youtube_cookies_from_browser(req.browser)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "success": True,
        "message": f"Imported cookies from browser '{status.get('browser')}'",
        **status,
    }


@app.delete("/api/youtube/auth/cookies")
async def delete_youtube_cookies():
    target_path = _youtube_cookies_file_path()
    if os.path.exists(target_path):
        try:
            os.remove(target_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete cookies file: {exc}")
    return {
        "success": True,
        "message": "YouTube cookies file deleted.",
        **_youtube_cookie_file_status(),
    }


@app.post("/api/settings/sync/create")
async def create_settings_sync(req: SettingsSyncCreateRequest):
    settings_payload = req.settings if isinstance(req.settings, dict) else None
    if settings_payload is None:
        raise HTTPException(status_code=400, detail="settings must be an object")

    payload = dict(settings_payload)
    if req.include_youtube_cookies:
        backend_cookie_text = _read_backend_youtube_cookies()
        if backend_cookie_text:
            payload["youtube_session_cookies"] = backend_cookie_text
            youtube_settings = payload.get("youtubeAuthSettings")
            if isinstance(youtube_settings, dict):
                copied_settings = dict(youtube_settings)
                inline_cookie_text = (copied_settings.get("cookiesText") or "").strip()
                if inline_cookie_text and inline_cookie_text == backend_cookie_text.strip():
                    copied_settings["cookiesText"] = ""
                    payload["youtubeAuthSettings"] = copied_settings

    raw_payload = json.dumps(payload, ensure_ascii=False)
    raw_payload_bytes = raw_payload.encode("utf-8")
    compressed_payload = zlib.compress(raw_payload_bytes, level=6)
    if len(compressed_payload) < len(raw_payload_bytes):
        payload_blob = compressed_payload
        payload_encoding = "zlib+utf8"
    else:
        payload_blob = raw_payload_bytes
        payload_encoding = "utf8"

    payload_size = len(payload_blob)
    raw_payload_size = len(raw_payload_bytes)
    if payload_size > SETTINGS_SYNC_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "settings payload too large "
                f"({payload_size} bytes stored, raw {raw_payload_size} bytes > {SETTINGS_SYNC_MAX_BYTES} bytes)"
            ),
        )

    _settings_sync_cleanup_expired()

    try:
        from cryptography.fernet import Fernet
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Missing cryptography runtime for settings sync: {exc}")

    sync_id = secrets.token_hex(8)
    sync_secret = secrets.token_urlsafe(24)
    salt = os.urandom(16)
    fernet_key = _derive_settings_sync_key(sync_secret, salt)
    token = Fernet(fernet_key).encrypt(payload_blob).decode("utf-8")
    now = time.time()

    record = {
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "encoding": payload_encoding,
        "raw_payload_size": raw_payload_size,
        "stored_payload_size": payload_size,
        "token": token,
    }

    path = _settings_sync_record_path(sync_id)
    try:
        _write_metadata(path, record)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to persist sync profile: {exc}")

    return {
        "success": True,
        "sync_code": f"{sync_id}.{sync_secret}",
        "sync_id": sync_id,
        "payload_size": payload_size,
        "raw_payload_size": raw_payload_size,
        "payload_encoding": payload_encoding,
        "expires_in_days": SETTINGS_SYNC_TTL_DAYS,
    }


@app.post("/api/settings/sync/load")
async def load_settings_sync(req: SettingsSyncLoadRequest):
    sync_code = (req.sync_code or "").strip()
    if not sync_code:
        raise HTTPException(status_code=400, detail="sync_code is required")

    try:
        sync_id, sync_secret = _parse_settings_sync_code(sync_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    path = _settings_sync_record_path(sync_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sync profile not found")

    try:
        from cryptography.fernet import Fernet, InvalidToken
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Missing cryptography runtime for settings sync: {exc}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read sync profile: {exc}")

    ttl_seconds = SETTINGS_SYNC_TTL_DAYS * 86400
    updated_at = float(record.get("updated_at") or record.get("created_at") or 0.0)
    if SETTINGS_SYNC_TTL_DAYS > 0 and updated_at and (time.time() - updated_at) > ttl_seconds:
        try:
            os.remove(path)
        except Exception:
            pass
        raise HTTPException(status_code=410, detail="Sync profile expired")

    try:
        salt = base64.urlsafe_b64decode(record.get("salt", "").encode("ascii"))
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid sync profile salt")

    token = record.get("token")
    if not token:
        raise HTTPException(status_code=500, detail="Invalid sync profile token")

    try:
        fernet_key = _derive_settings_sync_key(sync_secret, salt)
        decrypted_payload = Fernet(fernet_key).decrypt(token.encode("utf-8"))
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid sync code")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt sync profile: {exc}")

    payload_encoding = (record.get("encoding") or "utf8").strip().lower()
    try:
        if payload_encoding in {"utf8", "utf-8"}:
            raw_payload = decrypted_payload.decode("utf-8")
        elif payload_encoding in {"zlib+utf8", "zlib"}:
            raw_payload = zlib.decompress(decrypted_payload).decode("utf-8")
        else:
            raise HTTPException(status_code=500, detail=f"Unsupported sync payload encoding: {payload_encoding}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to decode sync profile payload: {exc}")

    try:
        payload = json.loads(raw_payload)
    except Exception:
        raise HTTPException(status_code=500, detail="Sync profile payload is invalid")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Sync profile payload is invalid")

    youtube_cookies_applied = False
    if req.apply_youtube_cookies:
        sync_cookie_text = (payload.get("youtube_session_cookies") or "").strip()
        if sync_cookie_text:
            try:
                _persist_youtube_cookies_text(sync_cookie_text)
                youtube_cookies_applied = True
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to apply synced YouTube cookies: {exc}")

    payload.pop("youtube_session_cookies", None)

    return {
        "success": True,
        "settings": payload,
        "youtube_cookies_applied": youtube_cookies_applied,
    }


def _bulk_operation_has_incomplete_items(state: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(state, dict):
        return False
    mode = state.get("mode")
    for item in state.get("items") or []:
        render_done = (not _bulk_operation_requires_render(mode)) or item.get("render_status") == "completed"
        post_done = (not _bulk_operation_requires_post(mode)) or item.get("post_status") == "completed"
        if not (render_done and post_done):
            return True
    return False


def _build_bulk_operation_state_from_request(req: BulkOperationStartRequest, result: Dict[str, Any]) -> Dict[str, Any]:
    mode = _normalize_bulk_operation_mode(req.mode)
    clips_by_index = {
        int(clip.get("clip_index", index)): clip
        for index, clip in enumerate(result.get("clips") or [])
    }

    items: List[Dict[str, Any]] = []
    seen_clip_indices = set()
    for index, raw_item_model in enumerate(req.items or []):
        raw_item = raw_item_model.model_dump(exclude_none=True)
        clip_index = int(raw_item.get("clip_index"))
        if clip_index in seen_clip_indices:
            raise HTTPException(status_code=400, detail=f"Clip {clip_index + 1} is selected multiple times.")
        seen_clip_indices.add(clip_index)
        clip = clips_by_index.get(clip_index)
        if clip is None:
            raise HTTPException(status_code=404, detail=f"Clip {clip_index + 1} not found.")
        raw_item.setdefault(
            "clip_label",
            clip.get("video_title_for_youtube_short") or f"Clip {clip_index + 1}",
        )
        items.append(_normalize_bulk_operation_item(raw_item, mode=mode, order_index=index))

    if not items:
        raise HTTPException(status_code=400, detail="Select at least one clip.")

    render_cfg = req.render.model_dump(exclude_none=True) if req.render else {}
    post_cfg = req.post.model_dump(exclude_none=True) if req.post else {}

    normalized_render_cfg = {
        "apply_tight_edit": bool(render_cfg.get("apply_tight_edit", True)),
        "tight_edit_preset": _coerce_tight_edit_preset(render_cfg.get("tight_edit_preset")),
        "apply_subtitles": bool(render_cfg.get("apply_subtitles", True)),
        "subtitle_settings": render_cfg.get("subtitle_settings") if isinstance(render_cfg.get("subtitle_settings"), dict) else None,
        "apply_hook": bool(render_cfg.get("apply_hook", True)),
        "hook_style": render_cfg.get("hook_style") if isinstance(render_cfg.get("hook_style"), dict) else None,
        "pattern_flash_mode": _normalize_pattern_flash_mode(
            render_cfg.get("pattern_flash_mode")
            or ((render_cfg.get("hook_style") or {}).get("flash_mode") if isinstance(render_cfg.get("hook_style"), dict) else None)
            or ((render_cfg.get("hook_style") or {}).get("flashMode") if isinstance(render_cfg.get("hook_style"), dict) else None)
        ),
        "apply_stock_overlay": bool(render_cfg.get("apply_stock_overlay", False)),
    }

    normalized_post_cfg = {
        "platforms": _normalize_social_platforms(post_cfg.get("platforms") or []),
        "first_comment": (post_cfg.get("first_comment") or "").strip(),
        "timezone": (post_cfg.get("timezone") or "UTC").strip() or "UTC",
        "instagram_share_mode": (post_cfg.get("instagram_share_mode") or "CUSTOM").strip() or "CUSTOM",
        "tiktok_post_mode": (post_cfg.get("tiktok_post_mode") or "DIRECT_POST").strip() or "DIRECT_POST",
        "tiktok_is_aigc": bool(post_cfg.get("tiktok_is_aigc")),
        "facebook_page_id": (post_cfg.get("facebook_page_id") or "").strip() or None,
        "pinterest_board_id": (post_cfg.get("pinterest_board_id") or "").strip() or None,
    }

    if _bulk_operation_requires_post(mode):
        if not normalized_post_cfg["platforms"]:
            raise HTTPException(status_code=400, detail="Select at least one platform for bulk posting.")
        if "pinterest" in normalized_post_cfg["platforms"] and not normalized_post_cfg["pinterest_board_id"]:
            raise HTTPException(status_code=400, detail="Pinterest requires a board ID.")

    operation_id = uuid.uuid4().hex
    for item in items:
        item["upload_request_id"] = f"openshorts-{operation_id}-{item['id']}"

    state = {
        "operation_id": operation_id,
        "mode": mode,
        "status": "paused",
        "created_at": time.time(),
        "updated_at": time.time(),
        "started_at": None,
        "completed_at": None,
        "paused_at": None,
        "stopped_at": None,
        "current_phase": None,
        "current_item_index": None,
        "current_clip_index": None,
        "message": "",
        "error": None,
        "auto_paused": False,
        "items": items,
        "render": normalized_render_cfg,
        "post": normalized_post_cfg,
    }
    return _finalize_bulk_operation_state(state) or state


def _merge_bulk_operation_runtime(job_id: str, req: BulkOperationControlRequest | BulkOperationStartRequest | Any) -> Dict[str, Any]:
    existing = dict(bulk_operation_runtime.get(job_id) or {})
    incoming = _build_bulk_runtime_from_request(req)
    for key, value in incoming.items():
        if value not in (None, ""):
            existing[key] = value
    return existing


def _validate_bulk_operation_runtime(state: Dict[str, Any], runtime: Dict[str, Any]) -> None:
    if _bulk_operation_requires_post(state.get("mode")):
        if not runtime.get("upload_post_api_key") or not runtime.get("upload_post_user_id"):
            raise HTTPException(status_code=400, detail="Upload-Post API-Key und Profil sind fuer diese Multi-Post-Operation erforderlich.")


def _shift_pending_bulk_schedule_dates_if_needed(state: Dict[str, Any]) -> Dict[str, Any]:
    if not _bulk_operation_requires_post(state.get("mode")):
        return state

    pending_items = [
        item for item in state.get("items") or []
        if item.get("post_status") != "completed" and item.get("scheduled_date")
    ]
    if not pending_items:
        return state

    parsed_dates: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
    for item in pending_items:
        try:
            parsed_dates.append((datetime.datetime.fromisoformat(item["scheduled_date"]), item))
        except Exception:
            return state

    first_pending_date = min(item[0] for item in parsed_dates)
    now = datetime.datetime.now(first_pending_date.tzinfo or datetime.timezone.utc)
    if first_pending_date > now:
        return state

    shift_delta = (now + datetime.timedelta(minutes=BULK_RESUME_MIN_LEAD_MINUTES)) - first_pending_date
    if shift_delta.total_seconds() <= 0:
        return state

    for scheduled_dt, item in parsed_dates:
        shifted = scheduled_dt + shift_delta
        item["scheduled_date"] = shifted.isoformat()
        item["updated_at"] = time.time()

    state["message"] = "Vergangene Slots wurden automatisch in die Zukunft verschoben, damit der Multi-Post sauber fortgesetzt werden kann."
    state["updated_at"] = time.time()
    return state


async def _run_bulk_operation(job_id: str) -> None:
    try:
        state = _get_bulk_operation_state(job_id)
        if not state:
            return

        runtime = dict(bulk_operation_runtime.get(job_id) or {})
        _validate_bulk_operation_runtime(state, runtime)

        state["status"] = "running"
        state["started_at"] = state.get("started_at") or time.time()
        state["paused_at"] = None
        state["stopped_at"] = None
        state["error"] = None
        state["auto_paused"] = False
        _persist_bulk_operation_state(job_id, state)
        append_job_log(_get_job_output_dir(job_id), f"Multi-Post {state.get('operation_id')} started ({state.get('mode')}).")

        consecutive_failures = 0
        header_carrier = _HeaderCarrier(_build_bulk_render_headers(runtime))
        render_cfg = state.get("render") or {}
        post_cfg = state.get("post") or {}

        for item_index, item in enumerate(state.get("items") or []):
            state = _get_bulk_operation_state(job_id) or state
            if state.get("status") == "stop_requested":
                state["status"] = "stopped"
                state["stopped_at"] = time.time()
                state["current_phase"] = None
                state["current_item_index"] = item_index
                state["current_clip_index"] = item.get("clip_index")
                _persist_bulk_operation_state(job_id, state)
                append_job_log(_get_job_output_dir(job_id), "Multi-Post stopped by user.")
                _clear_bulk_operation_runtime(job_id)
                return
            if state.get("status") == "pause_requested":
                state["status"] = "paused"
                state["paused_at"] = time.time()
                state["current_phase"] = None
                state["current_item_index"] = item_index
                state["current_clip_index"] = item.get("clip_index")
                _persist_bulk_operation_state(job_id, state)
                append_job_log(_get_job_output_dir(job_id), "Multi-Post paused by user.")
                return

            needs_render = _bulk_operation_requires_render(state.get("mode")) and item.get("render_status") != "completed"
            needs_post = _bulk_operation_requires_post(state.get("mode")) and item.get("post_status") != "completed"
            if not needs_render and not needs_post:
                continue

            if needs_render:
                clip_display_label = item.get("clip_label") or f"Clip {int(item.get('clip_index', 0)) + 1}"
                item["render_status"] = "running"
                item["status"] = "running"
                item["updated_at"] = time.time()
                item.setdefault("attempts", {}).setdefault("render", 0)
                item["attempts"]["render"] += 1
                state["current_phase"] = "render"
                state["current_item_index"] = item_index
                state["current_clip_index"] = item.get("clip_index")
                state["message"] = f"Rendert {clip_display_label}."
                _persist_bulk_operation_state(job_id, state)

                render_req = RenderClipRequest(
                    job_id=job_id,
                    clip_index=int(item["clip_index"]),
                    apply_tight_edit=bool(render_cfg.get("apply_tight_edit", True)),
                    tight_edit_preset=render_cfg.get("tight_edit_preset"),
                    apply_subtitles=bool(render_cfg.get("apply_subtitles", True)),
                    subtitle_settings=render_cfg.get("subtitle_settings"),
                    apply_hook=bool(render_cfg.get("apply_hook", True)),
                    hook_settings={
                        **(render_cfg.get("hook_style") or {}),
                        "text": item.get("hook_text") or "",
                    } if render_cfg.get("apply_hook", True) else None,
                    pattern_flash_mode=render_cfg.get("pattern_flash_mode") or (render_cfg.get("hook_style") or {}).get("flash_mode") or (render_cfg.get("hook_style") or {}).get("flashMode"),
                    apply_stock_overlay=bool(render_cfg.get("apply_stock_overlay", False)),
                )

                try:
                    async with bulk_render_semaphore:
                        render_result = await render_clip_viral_original(header_carrier, render_req)
                    if render_result.get("clip"):
                        _refresh_job_result(job_id)
                    item["render_status"] = "completed"
                    item["last_error"] = None
                    consecutive_failures = 0
                    _persist_bulk_operation_state(job_id, state, refresh_result=True)
                except HTTPException as exc:
                    detail = str(exc.detail)
                    item["render_status"] = "failed"
                    item["status"] = "failed"
                    item["last_error"] = detail
                    item["updated_at"] = time.time()
                    consecutive_failures += 1
                    append_job_log(_get_job_output_dir(job_id), f"Multi-Post render failed for clip {int(item['clip_index']) + 1}: {detail}")
                    _persist_bulk_operation_state(job_id, state)
                    if consecutive_failures >= BULK_AUTO_PAUSE_AFTER_CONSECUTIVE_FAILURES:
                        state["status"] = "paused"
                        state["paused_at"] = time.time()
                        state["auto_paused"] = True
                        state["error"] = detail
                        state["message"] = "Mehrere Fehler hintereinander. Multi-Post wurde automatisch pausiert."
                        _persist_bulk_operation_state(job_id, state)
                        append_job_log(_get_job_output_dir(job_id), "Multi-Post auto-paused after repeated render failures.")
                        return
                    continue
                except Exception as exc:
                    detail = str(exc)
                    item["render_status"] = "failed"
                    item["status"] = "failed"
                    item["last_error"] = detail
                    item["updated_at"] = time.time()
                    consecutive_failures += 1
                    append_job_log(_get_job_output_dir(job_id), f"Multi-Post render exception for clip {int(item['clip_index']) + 1}: {detail}")
                    _persist_bulk_operation_state(job_id, state)
                    if consecutive_failures >= BULK_AUTO_PAUSE_AFTER_CONSECUTIVE_FAILURES:
                        state["status"] = "paused"
                        state["paused_at"] = time.time()
                        state["auto_paused"] = True
                        state["error"] = detail
                        state["message"] = "Mehrere Fehler hintereinander. Multi-Post wurde automatisch pausiert."
                        _persist_bulk_operation_state(job_id, state)
                        return
                    continue

            state = _get_bulk_operation_state(job_id) or state
            item = (state.get("items") or [])[item_index]

            if state.get("status") == "stop_requested":
                state["status"] = "stopped"
                state["stopped_at"] = time.time()
                state["current_phase"] = None
                state["current_item_index"] = item_index
                state["current_clip_index"] = item.get("clip_index")
                _persist_bulk_operation_state(job_id, state)
                append_job_log(_get_job_output_dir(job_id), "Multi-Post stopped by user.")
                _clear_bulk_operation_runtime(job_id)
                return
            if state.get("status") == "pause_requested":
                state["status"] = "paused"
                state["paused_at"] = time.time()
                state["current_phase"] = None
                state["current_item_index"] = item_index
                state["current_clip_index"] = item.get("clip_index")
                _persist_bulk_operation_state(job_id, state)
                append_job_log(_get_job_output_dir(job_id), "Multi-Post paused by user.")
                return

            if needs_post:
                clip_display_label = item.get("clip_label") or f"Clip {int(item.get('clip_index', 0)) + 1}"
                item["post_status"] = "running"
                item["status"] = "running"
                item["updated_at"] = time.time()
                item.setdefault("attempts", {}).setdefault("post", 0)
                item["attempts"]["post"] += 1
                state["current_phase"] = "post"
                state["current_item_index"] = item_index
                state["current_clip_index"] = item.get("clip_index")
                state["message"] = f"Plant {clip_display_label}."
                _persist_bulk_operation_state(job_id, state)

                post_req = SocialPostRequest(
                    job_id=job_id,
                    clip_index=int(item["clip_index"]),
                    api_key=runtime["upload_post_api_key"],
                    user_id=runtime["upload_post_user_id"],
                    platforms=post_cfg.get("platforms") or [],
                    first_comment=post_cfg.get("first_comment") or "",
                    scheduled_date=item.get("scheduled_date"),
                    timezone=post_cfg.get("timezone") or "UTC",
                    instagram_share_mode=post_cfg.get("instagram_share_mode") or "CUSTOM",
                    tiktok_post_mode=post_cfg.get("tiktok_post_mode") or "DIRECT_POST",
                    tiktok_is_aigc=bool(post_cfg.get("tiktok_is_aigc")),
                    facebook_page_id=post_cfg.get("facebook_page_id"),
                    pinterest_board_id=post_cfg.get("pinterest_board_id"),
                    podcast_dm_relay_url=runtime.get("podcast_dm_relay_url"),
                    podcast_dm_relay_password=runtime.get("podcast_dm_relay_password"),
                    request_id=(
                        item.get("upload_request_id")
                        or f"openshorts-{state.get('operation_id')}-{item.get('id')}"
                    ),
                )

                try:
                    post_result = None
                    for transient_attempt in range(1, BULK_POST_TRANSIENT_MAX_ATTEMPTS + 1):
                        try:
                            async with bulk_post_semaphore:
                                post_result = await post_to_socials(post_req)
                            break
                        except HTTPException as exc:
                            if (
                                transient_attempt >= BULK_POST_TRANSIENT_MAX_ATTEMPTS
                                or not _is_retryable_bulk_post_error(exc)
                            ):
                                raise
                            item["attempts"]["post"] += 1
                            item["last_error"] = str(exc.detail)
                            item["updated_at"] = time.time()
                            _persist_bulk_operation_state(job_id, state)
                            append_job_log(
                                _get_job_output_dir(job_id),
                                f"Multi-Post transient retry {transient_attempt + 1}/{BULK_POST_TRANSIENT_MAX_ATTEMPTS} "
                                f"for clip {int(item['clip_index']) + 1}: {exc.detail}",
                            )
                            await asyncio.sleep(min(8.0, 1.5 * (2 ** (transient_attempt - 1))))
                    if post_result.get("clip"):
                        _refresh_job_result(job_id)
                    item["post_status"] = "completed"
                    item["last_error"] = None
                    consecutive_failures = 0
                    _persist_bulk_operation_state(job_id, state, refresh_result=True)
                except HTTPException as exc:
                    detail = str(exc.detail)
                    item["post_status"] = "failed"
                    item["status"] = "partial" if item.get("render_status") == "completed" else "failed"
                    item["last_error"] = detail
                    item["updated_at"] = time.time()
                    consecutive_failures += 1
                    append_job_log(_get_job_output_dir(job_id), f"Multi-Post post failed for clip {int(item['clip_index']) + 1}: {detail}")
                    _persist_bulk_operation_state(job_id, state)
                    if consecutive_failures >= BULK_AUTO_PAUSE_AFTER_CONSECUTIVE_FAILURES:
                        state["status"] = "paused"
                        state["paused_at"] = time.time()
                        state["auto_paused"] = True
                        state["error"] = detail
                        state["message"] = "Mehrere Fehler hintereinander. Multi-Post wurde automatisch pausiert."
                        _persist_bulk_operation_state(job_id, state)
                        append_job_log(_get_job_output_dir(job_id), "Multi-Post auto-paused after repeated posting failures.")
                        return
                    continue
                except Exception as exc:
                    detail = str(exc)
                    item["post_status"] = "failed"
                    item["status"] = "partial" if item.get("render_status") == "completed" else "failed"
                    item["last_error"] = detail
                    item["updated_at"] = time.time()
                    consecutive_failures += 1
                    append_job_log(_get_job_output_dir(job_id), f"Multi-Post post exception for clip {int(item['clip_index']) + 1}: {detail}")
                    _persist_bulk_operation_state(job_id, state)
                    if consecutive_failures >= BULK_AUTO_PAUSE_AFTER_CONSECUTIVE_FAILURES:
                        state["status"] = "paused"
                        state["paused_at"] = time.time()
                        state["auto_paused"] = True
                        state["error"] = detail
                        state["message"] = "Mehrere Fehler hintereinander. Multi-Post wurde automatisch pausiert."
                        _persist_bulk_operation_state(job_id, state)
                        return
                    continue

            state = _get_bulk_operation_state(job_id) or state
            item = (state.get("items") or [])[item_index]
            item["status"] = _derive_bulk_operation_item_status(item, mode=state.get("mode"))
            item["updated_at"] = time.time()
            state["current_phase"] = None
            _persist_bulk_operation_state(job_id, state)

        state = _get_bulk_operation_state(job_id) or state
        state["current_phase"] = None
        state["current_item_index"] = None
        state["current_clip_index"] = None
        state["completed_at"] = time.time()
        state["status"] = "partial" if state.get("failed_count") else "completed"
        if state["status"] == "partial":
            state["message"] = "Multi-Post abgeschlossen, aber einige Clips brauchen noch einen Retry."
        else:
            state["message"] = "Multi-Post erfolgreich abgeschlossen."
            _clear_bulk_operation_runtime(job_id)
        _persist_bulk_operation_state(job_id, state)
        append_job_log(_get_job_output_dir(job_id), f"Multi-Post finished with status {state['status']}.")
    finally:
        task = bulk_operation_tasks.get(job_id)
        if task is asyncio.current_task():
            bulk_operation_tasks.pop(job_id, None)


def _ensure_bulk_operation_task(job_id: str) -> None:
    existing_task = bulk_operation_tasks.get(job_id)
    if existing_task and not existing_task.done():
        return
    task = asyncio.create_task(_run_bulk_operation(job_id))
    bulk_operation_tasks[job_id] = task


@app.post("/api/bulk-operation/start")
async def start_bulk_operation(req: BulkOperationStartRequest):
    _get_job_record_or_404(req.job_id)
    existing_state = _get_bulk_operation_state(req.job_id)
    if existing_state and existing_state.get("status") in BULK_OPERATION_RUNNING_STATUSES.union(BULK_OPERATION_RESUMABLE_STATUSES):
        raise HTTPException(status_code=409, detail="An unfinished multi-post operation already exists for this job. Resume or stop it first.")

    _, result, _ = _get_job_result_or_400(req.job_id)
    state = _build_bulk_operation_state_from_request(req, result)
    runtime = _merge_bulk_operation_runtime(req.job_id, req)
    _validate_bulk_operation_runtime(state, runtime)
    _store_bulk_operation_runtime(req.job_id, runtime)
    state["status"] = "running"
    state["started_at"] = state.get("started_at") or time.time()
    state["updated_at"] = time.time()
    state["message"] = "Multi-Post wird gestartet."
    persisted_state = _persist_bulk_operation_state(req.job_id, state)
    _ensure_bulk_operation_task(req.job_id)
    return {
        "success": True,
        "job_id": req.job_id,
        "bulk_operation": persisted_state,
    }


@app.get("/api/bulk-operation/{job_id}")
async def get_bulk_operation(job_id: str):
    _get_job_record_or_404(job_id)
    state = _get_bulk_operation_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="No multi-post operation found for this job.")
    return {
        "success": True,
        "job_id": job_id,
        "bulk_operation": state,
    }


@app.post("/api/bulk-operation/{job_id}/pause")
async def pause_bulk_operation(job_id: str):
    _get_job_record_or_404(job_id)
    state = _get_bulk_operation_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="No multi-post operation found for this job.")
    if state.get("status") == "paused":
        return {"success": True, "job_id": job_id, "bulk_operation": state}
    if state.get("status") not in BULK_OPERATION_RUNNING_STATUSES and state.get("status") != "running":
        raise HTTPException(status_code=409, detail="This multi-post operation is not running.")

    state["status"] = "pause_requested"
    state["updated_at"] = time.time()
    state["message"] = "Pause angefordert."
    persisted_state = _persist_bulk_operation_state(job_id, state)
    return {"success": True, "job_id": job_id, "bulk_operation": persisted_state}


@app.post("/api/bulk-operation/{job_id}/stop")
async def stop_bulk_operation(job_id: str):
    _get_job_record_or_404(job_id)
    state = _get_bulk_operation_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="No multi-post operation found for this job.")

    if state.get("status") in BULK_OPERATION_RUNNING_STATUSES or state.get("status") == "running":
        state["status"] = "stop_requested"
        state["updated_at"] = time.time()
        state["message"] = "Stop angefordert."
    else:
        state["status"] = "stopped"
        state["stopped_at"] = time.time()
        state["updated_at"] = time.time()
        state["message"] = "Multi-Post gestoppt."
        _clear_bulk_operation_runtime(job_id)
    persisted_state = _persist_bulk_operation_state(job_id, state)
    return {"success": True, "job_id": job_id, "bulk_operation": persisted_state}


@app.post("/api/bulk-operation/{job_id}/resume")
async def resume_bulk_operation(job_id: str, req: BulkOperationControlRequest):
    _get_job_record_or_404(job_id)
    state = _get_bulk_operation_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="No multi-post operation found for this job.")
    if state.get("status") in BULK_OPERATION_RUNNING_STATUSES or state.get("status") == "running":
        raise HTTPException(status_code=409, detail="This multi-post operation is already running.")
    if not _bulk_operation_has_incomplete_items(state):
        raise HTTPException(status_code=400, detail="This multi-post operation has no incomplete clips left.")

    runtime = _merge_bulk_operation_runtime(job_id, req)
    _validate_bulk_operation_runtime(state, runtime)
    _store_bulk_operation_runtime(job_id, runtime)

    state = _shift_pending_bulk_schedule_dates_if_needed(state)
    state["status"] = "paused"
    state["paused_at"] = None
    state["stopped_at"] = None
    state["completed_at"] = None
    state["auto_paused"] = False
    state["error"] = None
    state["updated_at"] = time.time()
    persisted_state = _persist_bulk_operation_state(job_id, state)
    _ensure_bulk_operation_task(job_id)
    return {
        "success": True,
        "job_id": job_id,
        "bulk_operation": persisted_state,
    }

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

    manifest = load_job_manifest(_get_job_output_dir(job_id)) or {}
    request_meta = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    payload = {
        "job_id": job_id,
        "status": job['status'],
        "logs": job['logs'],
        "result": job.get('result'),
        "bulk_operation": _get_bulk_operation_state(job_id),
        "job_state": job.get('job_state', job['status']),
        "error": job.get('error'),
        "can_resume": job.get('can_resume', False),
        "analysis_context": {
            "profile_name": request_meta.get("upload_post_profile") or "",
            "profile_context": request_meta.get("profile_context") or "",
            "job_instructions": request_meta.get("job_instructions") or "",
        },
    }
    return _attach_queue_metadata(payload)


@app.get("/api/jobs/history")
async def get_job_history(
    limit: int = Query(50, ge=1, le=500),
    include_result: bool = Query(False),
    include_logs: bool = Query(True),
    log_limit: int = Query(40, ge=0, le=200),
    upload_post_profile: Optional[str] = Query(None),
):
    overview = _queue_overview()
    summaries = list_job_summaries(
        OUTPUT_DIR,
        limit=limit,
        include_result=include_result,
        include_logs=include_logs,
        log_limit=log_limit,
    )
    requested_profile = str(upload_post_profile or "").strip()
    enriched_summaries = []
    for summary in summaries:
        manifest = load_job_manifest(_get_job_output_dir(str(summary.get("job_id") or ""))) or {}
        request_meta = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
        assigned_profile = str(request_meta.get("upload_post_profile") or "").strip()
        if requested_profile == "__unassigned__":
            if assigned_profile:
                continue
        elif requested_profile and assigned_profile != requested_profile:
            continue
        enriched_summaries.append({
            **summary,
            "upload_post_profile": assigned_profile,
            "profile_context": request_meta.get("profile_context") or "",
            "job_instructions": request_meta.get("job_instructions") or "",
        })
    return {
        "queue": overview,
        "jobs": [_attach_queue_metadata(summary, overview) for summary in enriched_summaries],
    }


@app.get("/api/queue/status")
async def get_queue_status():
    return {"queue": _queue_overview()}


@app.post("/api/transcription/upload")
async def upload_transcription_media(
    file: UploadFile = File(...),
    with_timestamps: bool = Form(True),
    preferred_language: Optional[str] = Form("de"),
    export_formats: Optional[str] = Form(None),
):
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="Bitte eine Audio- oder Videodatei hochladen.")

    session_id = uuid.uuid4().hex
    uploads_dir = os.path.join(UPLOAD_DIR, "transcriptions")
    os.makedirs(uploads_dir, exist_ok=True)

    safe_name = os.path.basename(file.filename)
    stored_name = f"{session_id}_{safe_name}"
    input_path = os.path.join(uploads_dir, stored_name)

    try:
        with open(input_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)
    finally:
        await file.close()

    session = {
        "status": "queued",
        "message": "Upload abgeschlossen. Warte auf Whisper.",
        "error": None,
        "filename": safe_name,
        "input_path": input_path,
        "preferred_language": _normalize_transcription_language(preferred_language) or "de",
        "with_timestamps": bool(with_timestamps),
        "export_formats": _normalize_transcription_export_formats(export_formats, with_timestamps=bool(with_timestamps)),
        "created_at": time.time(),
        "updated_at": time.time(),
        "completed_at": None,
        "runtime": {},
        "transcript": None,
        "exports": [],
    }
    transcription_jobs[session_id] = session
    asyncio.create_task(_run_transcription_job(session_id))
    return {
        "success": True,
        "session": _serialize_transcription_session(session_id, session),
    }


@app.get("/api/transcription/{session_id}")
async def get_transcription_session(session_id: str):
    return {
        "success": True,
        "session": _serialize_transcription_session(session_id, transcription_jobs.get(session_id)),
    }


@app.get("/api/longform/projects")
async def get_longform_projects(limit: int = Query(50, ge=1, le=200), log_limit: int = Query(60, ge=0, le=300)):
    return {
        "success": True,
        "projects": list_longform_projects(limit=limit, log_limit=log_limit),
    }


@app.get("/api/longform/source-files/search")
async def search_longform_source_files_endpoint(
    q: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=100),
):
    query = str(q or "").strip()
    roots = _resolve_longform_allowed_source_roots()
    return {
        "success": True,
        "results": _search_longform_source_files(query, limit=limit, exact=False),
        "searched_roots": roots,
        "mount_has_media": _longform_source_roots_have_media(),
    }


@app.post("/api/longform/projects")
async def create_longform_project_endpoint(req: LongformProjectCreateRequest):
    project, _ = create_longform_project(
        req.project_name,
        req.mode or "single",
        config=normalize_project_config(req.config, mode=req.mode or "single"),
        ai=normalize_ai_config(req.ai),
    )
    return {
        "success": True,
        **_serialize_longform_bundle(project["project_id"]),
    }


@app.get("/api/longform/projects/{project_id}")
async def get_longform_project(project_id: str, log_limit: int = Query(200, ge=0, le=1000)):
    _longform_project_exists_or_404(project_id)
    return {
        "success": True,
        **_serialize_longform_bundle(project_id, log_limit=log_limit),
    }


@app.post("/api/longform/projects/{project_id}")
async def update_longform_project_endpoint(project_id: str, req: LongformProjectUpdateRequest):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    if bundle["state"].get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Projekt kann waehrend der laufenden Pipeline nicht bearbeitet werden.")
    current_mode = project.get("mode") or "single"
    next_mode = req.mode or current_mode
    if next_mode != current_mode and any(project.get("files", {}).get(role) for role in project.get("files", {})):
        raise HTTPException(status_code=409, detail="Moduswechsel ist nur vor dem Dateiupload erlaubt.")
    update_longform_project(
        project_id,
        project_name=req.project_name,
        mode=req.mode,
        config=req.config,
        ai=req.ai,
    )
    _reset_longform_pipeline_state(project_id, "Projekt-Konfiguration aktualisiert.")
    return {
        "success": True,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/files")
async def upload_longform_project_files(
    project_id: str,
    role: str = Form(...),
    files: List[UploadFile] = File(...),
):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    if bundle["state"].get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Dateiupload ist waehrend der laufenden Pipeline nicht erlaubt.")
    normalized_role = (role or "").strip().lower()
    if normalized_role not in active_camera_roles(project.get("mode") or "single"):
        raise HTTPException(status_code=400, detail="Ungueltige Kamera-Rolle fuer dieses Projekt.")
    if not files:
        raise HTTPException(status_code=400, detail="Bitte mindestens eine Datei hochladen.")

    source_dir = longform_project_upload_tmp_dir(project_id)
    for upload in files:
        if not upload.filename:
            continue
        file_id = uuid.uuid4().hex
        safe_name = slugify_filename(upload.filename)
        stored_path = os.path.join(source_dir, f"{file_id}_{safe_name}")
        try:
            with open(stored_path, "wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        finally:
            await upload.close()

        try:
            metadata = probe_media(stored_path)
        except Exception as exc:
            try:
                os.remove(stored_path)
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=f"Datei konnte nicht analysiert werden: {exc}")
        project = _maybe_apply_longform_export_fps_from_metadata(project_id, project, metadata)

        file_record = {
            "id": file_id,
            "role": normalized_role,
            "order": len(project.get("files", {}).get(normalized_role) or []),
            "original_name": upload.filename,
            "stored_path": stored_path,
            "source_storage": "temporary_upload",
            "source_origin": "browser_upload",
            "source_deleted_at": None,
            "uploaded_at": time.time(),
            **metadata,
            "normalized_path": None,
            "proxy_path": None,
            "audio_path": None,
            "transcript_path": None,
        }
        project = register_longform_uploaded_file(project_id, normalized_role, file_record)

    _reset_longform_pipeline_state(project_id, "Dateien aktualisiert. Pipeline bereit.")
    return {
        "success": True,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/files/by-path")
async def import_longform_project_files_by_path(project_id: str, req: LongformFilePathImportRequest):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    if bundle["state"].get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Dateiimport ist waehrend der laufenden Pipeline nicht erlaubt.")

    normalized_role = (req.role or "").strip().lower()
    if normalized_role not in active_camera_roles(project.get("mode") or "single"):
        raise HTTPException(status_code=400, detail="Ungueltige Kamera-Rolle fuer dieses Projekt.")

    normalized_paths = [str(item or "").strip() for item in (req.source_paths or []) if str(item or "").strip()]
    if not normalized_paths:
        raise HTTPException(status_code=400, detail="Bitte mindestens einen gueltigen Dateipfad angeben.")

    for raw_path in normalized_paths:
        resolved_path = _validate_longform_source_path(raw_path)
        file_id = uuid.uuid4().hex
        original_name = os.path.basename(resolved_path)

        try:
            metadata = probe_media(resolved_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Datei konnte nicht analysiert werden: {raw_path} ({exc})")
        project = _maybe_apply_longform_export_fps_from_metadata(project_id, project, metadata)

        file_record = {
            "id": file_id,
            "role": normalized_role,
            "order": len(project.get("files", {}).get(normalized_role) or []),
            "original_name": original_name,
            "stored_path": resolved_path,
            "source_storage": "mounted_reference",
            "source_origin": "mounted_path",
            "source_deleted_at": None,
            "uploaded_at": time.time(),
            **metadata,
            "normalized_path": None,
            "proxy_path": None,
            "audio_path": None,
            "transcript_path": None,
        }
        project = register_longform_uploaded_file(project_id, normalized_role, file_record)

    _reset_longform_pipeline_state(project_id, "Dateien aktualisiert. Pipeline bereit.")
    return {
        "success": True,
        **_serialize_longform_bundle(project_id),
    }


@app.delete("/api/longform/projects/{project_id}/files/{file_id}")
async def delete_longform_project_file(project_id: str, file_id: str, role: str = Query(...)):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    if bundle["state"].get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Dateien koennen waehrend der laufenden Pipeline nicht entfernt werden.")
    normalized_role = (role or "").strip().lower()
    if normalized_role not in active_camera_roles(project.get("mode") or "single"):
        raise HTTPException(status_code=400, detail="Ungueltige Kamera-Rolle.")
    remove_longform_file(project_id, normalized_role, file_id)
    _reset_longform_pipeline_state(project_id, "Datei entfernt. Pipeline bereit.")
    return {
        "success": True,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/files/reorder")
async def reorder_longform_project_files(project_id: str, req: LongformFileReorderRequest):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    if bundle["state"].get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Reihenfolge kann waehrend der laufenden Pipeline nicht geaendert werden.")
    normalized_role = (req.role or "").strip().lower()
    if normalized_role not in active_camera_roles(project.get("mode") or "single"):
        raise HTTPException(status_code=400, detail="Ungueltige Kamera-Rolle.")
    reorder_longform_role_files(project_id, normalized_role, req.ordered_ids)
    _reset_longform_pipeline_state(project_id, "Dateireihenfolge aktualisiert.")
    return {
        "success": True,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/start")
async def start_longform_project(project_id: str, req: Optional[LongformPipelineRuntimeRequest] = None):
    _longform_project_exists_or_404(project_id)
    if req and req.ai is not None:
        update_longform_project(project_id, ai=normalize_ai_config(req.ai))
    try:
        state = start_longform_pipeline_task(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "success": True,
        "state": state,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/resume")
async def resume_longform_project(project_id: str, req: Optional[LongformPipelineRuntimeRequest] = None):
    _longform_project_exists_or_404(project_id)
    if req and req.ai is not None:
        update_longform_project(project_id, ai=normalize_ai_config(req.ai))
    try:
        state = resume_longform_pipeline_task(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "success": True,
        "state": state,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/stop")
async def stop_longform_project_endpoint(project_id: str):
    _longform_project_exists_or_404(project_id)
    state = stop_longform_pipeline(project_id)
    return {
        "success": True,
        "state": state,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/restart")
async def restart_longform_project_endpoint(project_id: str, req: Optional[LongformPipelineRuntimeRequest] = None):
    _longform_project_exists_or_404(project_id)
    if req and req.ai is not None:
        update_longform_project(project_id, ai=normalize_ai_config(req.ai))
    try:
        state = restart_longform_pipeline_task(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "success": True,
        "state": state,
        **_serialize_longform_bundle(project_id),
    }


@app.get("/api/longform/projects/{project_id}/speaker-stills")
async def get_longform_project_speaker_stills(project_id: str, count: int = Query(6, ge=1, le=12)):
    bundle = _longform_project_exists_or_404(project_id)
    analysis_result = _load_longform_analysis_result_or_404(project_id)
    project = bundle["project"]
    stills_payload: Dict[str, List[Dict[str, Any]]] = {}
    stills_patch: Dict[str, Any] = {}
    stills_root = longform_project_subdir(project_id, "stills")
    for role in active_camera_roles(project.get("mode") or "single"):
        candidates = _select_longform_still_candidates(project, analysis_result, role, count=count)
        role_dir = os.path.join(stills_root, role)
        os.makedirs(role_dir, exist_ok=True)
        role_items: List[Dict[str, Any]] = []
        cache_buster = f"ts={int(time.time() * 1000)}"
        for index, candidate in enumerate(candidates, start=1):
            # Use timestamp to ensure new images are generated each time
            timestamp_suffix = int(time.time() * 1000)
            output_path = os.path.join(role_dir, f"{role}_{index:02d}_{timestamp_suffix}.jpg")
            _capture_longform_video_frame(candidate["source_path"], output_path, candidate["local_time"])
            role_items.append({
                **candidate,
                "path": output_path,
                "url": media_url_from_path(output_path, cache_buster=cache_buster),
            })
        stills_payload[role] = role_items
    _persist_longform_artifact_patch(project_id, {"speaker_stills": stills_payload})
    return {
        "success": True,
        "speaker_stills": stills_payload,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/thumbnail-text-overlays")
async def generate_longform_project_thumbnail_text_overlays(project_id: str, req: LongformThumbnailTextOverlayRequest):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    count = max(1, min(int(req.count or 10), 20))
    merged_ai = normalize_ai_config({
        **(project.get("ai") or {}),
        **(req.ai or {}),
    })
    transcript_excerpt = _load_longform_transcript_excerpt(project_id, project)
    prompt = _build_longform_thumbnail_text_overlay_prompt(
        project=project,
        base_prompt=str(req.prompt or project.get("config", {}).get("thumbnail_prompt_text") or "").strip(),
        transcript_excerpt=transcript_excerpt,
        count=count,
    )
    try:
        payload = _call_longform_text_overlay_provider(merged_ai, prompt, timeout_seconds=45)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    suggestions = _normalize_longform_text_overlay_suggestions(
        (payload or {}).get("overlays") or (payload or {}).get("suggestions"),
        limit=count,
    )
    if len(suggestions) < count:
        for fallback in _default_longform_text_overlay_suggestions(project.get("config", {}).get("analysis_language") or "de"):
            if fallback not in suggestions:
                suggestions.append(fallback)
            if len(suggestions) >= count:
                break
    next_config = dict(project.get("config") or {})
    next_config["thumbnail_text_overlay_suggestions"] = suggestions
    if not str(next_config.get("thumbnail_text_overlay_text") or "").strip() and suggestions:
        next_config["thumbnail_text_overlay_text"] = suggestions[0]
    update_longform_project(project_id, config=next_config)
    return {
        "success": True,
        "overlays": suggestions,
        **_serialize_longform_bundle(project_id),
    }


@app.post("/api/longform/projects/{project_id}/thumbnails/generate")
async def generate_longform_project_thumbnails(project_id: str, req: LongformThumbnailGenerateRequest):
    bundle = _longform_project_exists_or_404(project_id)
    project = bundle["project"]
    providers = _normalize_thumbnail_provider_list(req.providers)
    if not providers:
        raise HTTPException(status_code=400, detail="Bitte mindestens einen Thumbnail-Provider auswaehlen.")
    prompt = str(req.prompt or "").strip()
    feedback = str(req.feedback or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Bitte einen Thumbnail-Prompt angeben.")

    merged_ai = normalize_ai_config({
        **(project.get("ai") or {}),
        **(req.ai or {}),
    })

    ordered_roles: List[str] = []
    for role in (req.reference_order or []):
        normalized_role = str(role or "").strip().lower()
        if normalized_role and normalized_role not in ordered_roles:
            ordered_roles.append(normalized_role)
    for role in (req.selected_stills or {}).keys():
        normalized_role = str(role or "").strip().lower()
        if normalized_role and normalized_role not in ordered_roles:
            ordered_roles.append(normalized_role)

    selected_reference_paths: List[str] = []
    for role in ordered_roles:
        value = (req.selected_stills or {}).get(role)
        candidate = str(value or "").strip()
        if not candidate:
            continue
        if candidate.startswith("/videos/"):
            relative = candidate[len("/videos/"):].lstrip("/")
            candidate = os.path.realpath(os.path.join(OUTPUT_DIR, relative))
        candidate = os.path.realpath(candidate)
        if not os.path.exists(candidate):
            continue
        project_root = os.path.realpath(longform_project_subdir(project_id, "stills"))
        try:
            if os.path.commonpath([candidate, project_root]) != project_root:
                continue
        except Exception:
            continue
        selected_reference_paths.append(candidate)

    generations_root = os.path.join(longform_project_subdir(project_id, "thumbnails"), datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S"))
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for provider in providers:
        provider_dir = os.path.join(generations_root, provider)
        logging.getLogger(__name__).info('longform[%s] thumbnail generation start provider=%s count=%s refs=%s', project_id, provider, req.count_per_provider, len(selected_reference_paths))
        try:
            generated_paths = await asyncio.to_thread(
                generate_longform_thumbnail_variants,
                provider=provider,
                prompt=prompt,
                output_dir=provider_dir,
                count=req.count_per_provider,
                gemini_api_key=merged_ai.get("gemini_api_key") or "",
                openai_api_key=merged_ai.get("openai_api_key") or "",
                midjourney_api_key=merged_ai.get("midjourney_api_key") or "",
                midjourney_base_url=merged_ai.get("midjourney_base_url") or "",
                reference_image_paths=selected_reference_paths,
                model_name=(req.provider_models or {}).get(provider),
            )
            cache_buster = f"ts={int(time.time() * 1000)}"
            provider_payload = [
                {
                    "provider": provider,
                    "path": path,
                    "url": media_url_from_path(path, cache_buster=cache_buster),
                    "name": os.path.basename(path),
                }
                for path in generated_paths
            ]
            results.extend(provider_payload)
            logging.getLogger(__name__).info('longform[%s] thumbnail generation success provider=%s generated=%s', project_id, provider, len(provider_payload))
        except Exception as exc:
            logging.getLogger(__name__).exception('longform[%s] thumbnail generation failed provider=%s', project_id, provider)
            errors.append({"provider": provider, "error": str(exc)})
        finally:
            gc.collect()

    if not results and errors:
        detail = " ; ".join(f"{item['provider']}: {item['error']}" for item in errors)
        lowered_errors = [str(item.get('error') or '').lower() for item in errors]
        is_configuration_error = lowered_errors and all(
            any(marker in message for marker in (
                'api key fehlt',
                'bridge url ist nicht gesetzt',
                'bitte in den app-einstellungen konfigurieren',
                'nicht gesetzt',
            ))
            for message in lowered_errors
        )
        raise HTTPException(status_code=400 if is_configuration_error else 502, detail=detail)

    _persist_longform_artifact_patch(
        project_id,
        {
            "thumbnail_generations": {
                "updated_at": time.time(),
                "prompt": prompt,
                "feedback": feedback,
                "providers": providers,
                "count_per_provider": req.count_per_provider,
                "provider_models": req.provider_models or {},
                "selected_stills": req.selected_stills or {},
                "results": results,
                "errors": errors,
            }
        },
    )
    return {
        "success": len(errors) == 0,
        "results": results,
        "errors": errors,
        **_serialize_longform_bundle(project_id),
    }


@app.delete("/api/longform/projects/{project_id}")
async def delete_longform_project_endpoint(project_id: str):
    bundle = _longform_project_exists_or_404(project_id)
    if bundle["state"].get("status") in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Laufende Longform-Projekte bitte erst pausieren oder stoppen, bevor sie geloescht werden.")
    delete_longform_project(project_id)
    return {"success": True}


@app.post("/api/job/overlay-defaults")
async def update_job_overlay_defaults(req: JobOverlayDefaultsRequest):
    _get_job_record_or_404(req.job_id)

    persisted_defaults = _persist_job_overlay_defaults(
        req.job_id,
        subtitle_style=req.subtitle_style if req.subtitle_style is not None else _METADATA_UNSET,
        hook_style=req.hook_style if req.hook_style is not None else _METADATA_UNSET,
    )
    if persisted_defaults is None:
        raise HTTPException(status_code=500, detail="Failed to persist job overlay defaults.")

    return {
        "success": True,
        "job_id": req.job_id,
        "job_overlay_defaults": persisted_defaults,
    }


@app.post("/api/job/social-defaults")
async def update_job_social_defaults(req: JobSocialDefaultsRequest):
    _get_job_record_or_404(req.job_id)

    persisted_defaults = _persist_job_social_defaults(
        req.job_id,
        instagram_collaborators=req.instagram_collaborators if req.instagram_collaborators is not None else _METADATA_UNSET,
        podcast_youtube_url=req.podcast_youtube_url if req.podcast_youtube_url is not None else _METADATA_UNSET,
        podcast_link_url=req.podcast_link_url if req.podcast_link_url is not None else _METADATA_UNSET,
        podcast_keyword=req.podcast_keyword if req.podcast_keyword is not None else _METADATA_UNSET,
        podcast_comment_template=req.podcast_comment_template if req.podcast_comment_template is not None else _METADATA_UNSET,
        podcast_dm_enabled=req.podcast_dm_enabled if req.podcast_dm_enabled is not None else _METADATA_UNSET,
    )
    if persisted_defaults is None:
        raise HTTPException(status_code=500, detail="Failed to persist job social defaults.")

    return {
        "success": True,
        "job_id": req.job_id,
        "job_social_defaults": persisted_defaults,
    }


@app.post("/api/jobs/{job_id}/analysis-context")
async def update_job_analysis_context(job_id: str, req: JobAnalysisContextRequest):
    output_dir = _get_job_output_dir(job_id)
    manifest = load_job_manifest(output_dir)
    if not manifest:
        raise HTTPException(status_code=404, detail="Job manifest not found")
    request_meta = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    context = _write_analysis_context(output_dir, {
        "upload_post_profile": req.upload_post_profile if req.upload_post_profile is not None else request_meta.get("upload_post_profile"),
        "profile_context": req.profile_context if req.profile_context is not None else request_meta.get("profile_context"),
        "job_instructions": req.job_instructions if req.job_instructions is not None else request_meta.get("job_instructions"),
    })
    next_request = {
        **request_meta,
        "upload_post_profile": context.get("profile_name") or "",
        "profile_context": context.get("profile_context") or "",
        "job_instructions": context.get("job_instructions") or "",
    }
    update_job_manifest(output_dir, {"request": next_request})
    active_job = jobs.get(job_id)
    if active_job and isinstance(active_job.get("env"), dict):
        active_job["env"]["SHORTFORM_UPLOAD_PROFILE"] = context.get("profile_name") or ""
        active_job["env"]["SHORTFORM_PROFILE_CONTEXT"] = context.get("profile_context") or ""
        active_job["env"]["SHORTFORM_JOB_INSTRUCTIONS"] = context.get("job_instructions") or ""
    return {"success": True, "job_id": job_id, "analysis_context": context}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    normalized_job_id, output_dir_abs = _resolve_safe_job_output_dir(job_id)

    active_job = jobs.get(normalized_job_id)
    if active_job:
        active_state = str(active_job.get("job_state", active_job.get("status", ""))).lower()
        if active_state in {"queued", "processing"}:
            raise HTTPException(status_code=409, detail="Cannot delete an active job. Stop it first.")

    if not os.path.isdir(output_dir_abs):
        raise HTTPException(status_code=404, detail="Job folder not found")

    try:
        shutil.rmtree(output_dir_abs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete job folder: {exc}")

    if normalized_job_id in jobs:
        del jobs[normalized_job_id]

    return {"success": True, "job_id": normalized_job_id}


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
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
    x_gemini_model: Optional[str] = Header(None, alias="X-Gemini-Model"),
    x_openai_key: Optional[str] = Header(None, alias="X-OpenAI-Key"),
    x_openai_model: Optional[str] = Header(None, alias="X-OpenAI-Model"),
    x_claude_key: Optional[str] = Header(None, alias="X-Claude-Key"),
    x_claude_model: Optional[str] = Header(None, alias="X-Claude-Model"),
    x_minimax_key: Optional[str] = Header(None, alias="X-Minimax-Key"),
    x_minimax_auth_mode: Optional[str] = Header(None, alias="X-Minimax-Auth-Mode"),
    x_minimax_model: Optional[str] = Header(None, alias="X-Minimax-Model"),
    x_huggingface_key: Optional[str] = Header(None, alias="X-HuggingFace-Key"),
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
    gemini_model = req.gemini_model or x_gemini_model or manifest.get("provider", {}).get("gemini_model")
    openai_model = req.openai_model or x_openai_model or manifest.get("provider", {}).get("openai_model")
    claude_model = req.claude_model or x_claude_model or manifest.get("provider", {}).get("claude_model")
    minimax_model = req.minimax_model or x_minimax_model or manifest.get("provider", {}).get("minimax_model")
    tight_edit_preset = _coerce_tight_edit_preset(req.tight_edit_preset or request_meta.get("tight_edit_preset"))
    analysis_only_enabled = req.analysis_only if req.analysis_only is not None else _coerce_bool(request_meta.get("analysis_only"))
    force_reanalysis_enabled = bool(req.force_reanalysis)
    youtube_auth_mode_value = req.youtube_auth_mode or request_meta.get("youtube_auth_mode")
    youtube_browser_value = req.youtube_cookies_from_browser or request_meta.get("youtube_cookies_from_browser")
    youtube_cookies_value = req.youtube_cookies
    analysis_context = _write_analysis_context(output_dir, {
        "upload_post_profile": req.upload_post_profile if req.upload_post_profile is not None else request_meta.get("upload_post_profile"),
        "profile_context": req.profile_context if req.profile_context is not None else request_meta.get("profile_context"),
        "job_instructions": req.job_instructions if req.job_instructions is not None else request_meta.get("job_instructions"),
    })
    if youtube_cookies_value and len(str(youtube_cookies_value)) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="youtube_cookies payload is too large")

    if provider == "gemini" and not x_gemini_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")
    if provider == "openai" and not x_openai_key:
        raise HTTPException(status_code=400, detail="Missing X-OpenAI-Key header")
    if provider == "claude" and not x_claude_key:
        raise HTTPException(status_code=400, detail="Missing X-Claude-Key header")
    if provider == "minimax" and not x_minimax_key:
        raise HTTPException(status_code=400, detail="Missing X-Minimax-Key header")
    if provider == "ollama":
        ollama_base_url, ollama_model = _validate_ollama_model_or_raise(ollama_base_url, ollama_model)

    cmd = ["python", "-u", "main.py", "--resume", "--keep-original"]
    env = os.environ.copy()
    env["LLM_PROVIDER"] = provider
    env["SHORTFORM_ANALYSIS_CONTEXT_FILE"] = _analysis_context_path(output_dir)
    env["SHORTFORM_UPLOAD_PROFILE"] = analysis_context.get("profile_name") or ""
    env["SHORTFORM_PROFILE_CONTEXT"] = analysis_context.get("profile_context") or ""
    env["SHORTFORM_JOB_INSTRUCTIONS"] = analysis_context.get("job_instructions") or ""
    if x_gemini_key:
        env["GEMINI_API_KEY"] = x_gemini_key
    if gemini_model:
        env["GEMINI_MODEL"] = gemini_model
    if x_openai_key:
        env["OPENAI_API_KEY"] = x_openai_key
    if openai_model:
        env["OPENAI_MODEL"] = openai_model
    if x_claude_key:
        env["CLAUDE_API_KEY"] = x_claude_key
    if claude_model:
        env["CLAUDE_MODEL"] = claude_model
    if x_minimax_key:
        env["MINIMAX_API_KEY"] = x_minimax_key
    if x_minimax_auth_mode:
        env["MINIMAX_AUTH_MODE"] = x_minimax_auth_mode
    if minimax_model:
        env["MINIMAX_MODEL"] = minimax_model
    if x_huggingface_key:
        env["HF_TOKEN"] = x_huggingface_key
        env["PYANNOTE_AUTH_TOKEN"] = x_huggingface_key
    if force_reanalysis_enabled:
        env["FORCE_CLIP_REANALYSIS"] = "1"
    if ollama_base_url:
        env["OLLAMA_BASE_URL"] = ollama_base_url
    if ollama_model:
        env["OLLAMA_MODEL"] = ollama_model
    youtube_auth_mode_value, youtube_browser_value, youtube_inline_present = _apply_youtube_auth_env(
        env,
        youtube_auth_mode_value,
        youtube_browser_value,
        youtube_cookies_value,
    )

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
    cmd.extend(["--tight-edit-preset", tight_edit_preset])
    if analysis_only_enabled:
        cmd.append("--analysis-only")
    if analysis_only_enabled and source_type == "url":
        cmd.append("--keep-original")

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
        "request": {
            **request_meta,
            "tight_edit_preset": tight_edit_preset,
            "analysis_only": analysis_only_enabled,
            "force_reanalysis": force_reanalysis_enabled,
            "youtube_auth_mode": youtube_auth_mode_value,
            "youtube_cookies_from_browser": youtube_browser_value,
            "youtube_inline_cookies_present": youtube_inline_present,
            "upload_post_profile": analysis_context.get("profile_name") or "",
            "profile_context": analysis_context.get("profile_context") or "",
            "job_instructions": analysis_context.get("job_instructions") or "",
        },
        "provider": {
            "name": provider,
            "gemini_model": gemini_model,
            "openai_model": openai_model,
            "claude_model": claude_model,
            "minimax_model": minimax_model,
            "ollama_base_url": ollama_base_url,
            "ollama_model": ollama_model,
        }
    })
    await job_queue.put((job_id, jobs[job_id]["queue_token"]))
    overview = _queue_overview()
    return _attach_queue_metadata({"job_id": job_id, "status": "queued"}, overview)

from editor import VideoEditor
from subtitles import burn_subtitles, transcribe_audio
from hooks import add_hook_to_video
from translate import translate_video, get_supported_languages
from thumbnail import (
    analyze_video_for_titles,
    refine_titles,
    generate_thumbnail,
    generate_youtube_description,
    generate_longform_thumbnail_variants,
)


def _normalize_visual_effect_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias_map = {
        "zoom": "zoom_pulse",
        "zoom_in": "zoom_pulse",
        "punch_in": "zoom_pulse",
        "punchin": "zoom_pulse",
        "flash": "light_flash",
        "lightflash": "light_flash",
        "white_flash": "light_flash",
        "zoom_and_flash": "zoom_flash",
    }
    normalized = alias_map.get(normalized, normalized)
    return normalized if normalized in {"zoom_pulse", "light_flash", "zoom_flash"} else "zoom_pulse"


def _normalize_visual_effect_strength(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"low", "light", "soft", "small"}:
        return "low"
    if normalized in {"high", "strong", "hard", "big"}:
        return "high"
    return "medium"


def _sanitize_pattern_interrupt_plan(
    plan: Optional[Dict[str, Any]],
    duration: float,
    *,
    interview_mode: bool,
) -> Optional[Dict[str, Any]]:
    if not isinstance(plan, dict):
        return None

    safe_duration = max(0.0, float(duration or 0.0))
    if safe_duration < 0.9:
        return None

    min_spacing = 1.15 if interview_mode else 0.9
    raw_interrupts = plan.get("pattern_interrupts")
    if not isinstance(raw_interrupts, list):
        raw_interrupts = []

    sanitized: List[Dict[str, Any]] = []
    for item in raw_interrupts:
        if not isinstance(item, dict):
            continue
        event_time = _coerce_float(item.get("time"))
        if event_time is None:
            continue
        event_time = max(0.4, min(safe_duration - 0.4, event_time))
        effect_type = _normalize_visual_effect_type(item.get("effect"))
        strength = _normalize_visual_effect_strength(item.get("strength"))

        duration_value = _coerce_float(item.get("duration"))
        if duration_value is None or duration_value <= 0:
            if effect_type == "light_flash":
                duration_value = 0.10 if interview_mode else 0.12
            elif effect_type == "zoom_flash":
                duration_value = 0.95 if interview_mode else 1.05
            else:
                duration_value = 0.88 if interview_mode else 1.0

        sanitized.append({
            "time": round(event_time, 3),
            "effect": effect_type,
            "strength": strength,
            "duration": round(max(0.06, min(1.4, duration_value)), 3),
            "reason": str(item.get("reason") or "").strip(),
        })

    sanitized.sort(key=lambda item: item["time"])
    filtered: List[Dict[str, Any]] = []
    for item in sanitized:
        if filtered and (item["time"] - filtered[-1]["time"]) < min_spacing:
            strength_rank = {"low": 0, "medium": 1, "high": 2}
            if strength_rank[item["strength"]] > strength_rank[filtered[-1]["strength"]]:
                filtered[-1] = item
            continue
        filtered.append(item)

    max_count = 6 if interview_mode else 8
    return {
        "source": str(plan.get("source") or "").strip() or "ai",
        "effect_notes": str(plan.get("effect_notes") or "").strip(),
        "pattern_interrupts": filtered[:max_count],
    }


def _heuristic_pattern_interrupt_plan(
    transcript: Optional[Dict[str, Any]],
    duration: float,
    *,
    interview_mode: bool,
) -> Dict[str, Any]:
    safe_duration = max(0.0, float(duration or 0.0))
    target_count = 4 if interview_mode else 5
    if safe_duration >= 18:
        target_count += 1
    if safe_duration >= 32 and not interview_mode:
        target_count += 1

    candidates: List[Tuple[float, float, str]] = []
    if isinstance(transcript, dict):
        for segment in transcript.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            seg_start = _coerce_float(segment.get("start"))
            seg_end = _coerce_float(segment.get("end"))
            text = str(segment.get("text") or "").strip()
            if seg_start is None or seg_end is None or seg_end <= seg_start or not text:
                continue
            if seg_start < 0.4 or seg_start > (safe_duration - 0.6):
                continue

            word_count = len(re.findall(r"\w+", text))
            if word_count < 3:
                continue

            score = min(word_count, 12) * 0.12
            if any(marker in text for marker in ("?", "!")):
                score += 0.5
            if re.search(r"\d|€|\$|%|k\b|million|tausend", text.lower()):
                score += 0.45
            if len(text) <= 80:
                score += 0.2
            score += min(seg_start / max(1.0, safe_duration), 0.5)
            candidates.append((score, seg_start, text))

    if not candidates:
        step = max(2.15 if interview_mode else 1.75, safe_duration / max(1, target_count + 1))
        generated = []
        cursor = min(1.2, max(0.5, safe_duration * 0.15))
        while cursor < max(0.4, safe_duration - 0.6) and len(generated) < target_count:
            generated.append((1.0, cursor, "Fallback beat"))
            cursor += step
        candidates = generated

    candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen: List[Tuple[float, float, str]] = []
    min_spacing = 1.2 if interview_mode else 0.95
    for candidate in candidates:
        if all(abs(candidate[1] - existing[1]) >= min_spacing for existing in chosen):
            chosen.append(candidate)
        if len(chosen) >= target_count:
            break

    chosen.sort(key=lambda item: item[1])
    interrupts: List[Dict[str, Any]] = []
    for index, (_, event_time, reason) in enumerate(chosen):
        if interview_mode:
            cycle = ["zoom_pulse", "light_flash", "zoom_pulse", "light_flash", "zoom_pulse"]
            effect = cycle[index % len(cycle)]
            strength = (
                "low"
                if effect == "light_flash"
                else ("high" if index == 0 else "medium")
            )
        else:
            cycle = ["zoom_flash", "light_flash", "zoom_pulse", "light_flash", "zoom_pulse", "light_flash"]
            effect = cycle[index % len(cycle)]
            strength = "high" if effect == "zoom_flash" and index == 0 else ("medium" if effect != "light_flash" else "low")

        interrupts.append({
            "time": round(event_time, 3),
            "effect": effect,
            "strength": strength,
            "reason": reason[:140],
        })

    return {
        "source": "heuristic",
        "effect_notes": (
            "Interview mode uses smoother panel zooms and slightly more frequent micro flashes."
            if interview_mode
            else "Face-aware smoother zoom holds with more frequent micro-flashes for retention."
        ),
        "pattern_interrupts": interrupts,
    }


def _build_zoom_cycle_plan(
    duration: float,
    *,
    interview_mode: bool,
    seed_key: str = "",
    start_zoom_factor: float = 0.0,
    zoom_factor: float = 1.0,
    flash_mode: str = DEFAULT_PATTERN_FLASH_MODE,
) -> Dict[str, Any]:
    safe_duration = max(0.0, float(duration or 0.0))
    start_zoom_factor = _clamp_zoom_factor(start_zoom_factor, DEFAULT_START_ZOOM_FACTOR)
    zoom_factor = _clamp_zoom_factor(zoom_factor, DEFAULT_TARGET_ZOOM_FACTOR)
    zoom_factor = max(zoom_factor, start_zoom_factor)
    flash_mode = _normalize_pattern_flash_mode(flash_mode)
    rng_seed = hashlib.sha1(
        f"{seed_key}:{safe_duration:.3f}:{start_zoom_factor:.2f}:{zoom_factor:.2f}:{'interview' if interview_mode else 'standard'}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(rng_seed)

    zoom_in_duration = 0.78 if interview_mode else 0.70
    zoom_out_duration = 0.94 if interview_mode else 0.84
    min_hold = 5.0
    max_hold = 8.0
    min_cooldown = 5.0
    max_cooldown = 6.8
    initial_start = 0.06
    initial_zoom_in_duration = 0.62 if interview_mode else 0.54
    initial_zoom_out_duration = 0.86 if interview_mode else 0.76
    initial_hold_min = 2.2 if interview_mode else 1.8
    initial_hold_max = 3.4 if interview_mode else 2.8
    initial_cooldown_min = 3.6 if interview_mode else 3.1
    initial_cooldown_max = 5.0 if interview_mode else 4.4
    end_buffer = 0.28

    zoom_cycles: List[Dict[str, Any]] = []
    flash_events: List[Dict[str, Any]] = []
    pattern_interrupts: List[Dict[str, Any]] = []
    cursor = initial_start
    cycle_index = 0

    while cursor < max(0.0, safe_duration - 1.1):
        is_initial_cycle = cycle_index == 0
        cycle_zoom_in_duration = initial_zoom_in_duration if is_initial_cycle else zoom_in_duration
        cycle_zoom_out_duration = initial_zoom_out_duration if is_initial_cycle else zoom_out_duration
        cycle_min_hold = initial_hold_min if is_initial_cycle else min_hold
        cycle_max_hold = initial_hold_max if is_initial_cycle else max_hold
        cycle_min_cooldown = initial_cooldown_min if is_initial_cycle else min_cooldown
        cycle_max_cooldown = initial_cooldown_max if is_initial_cycle else max_cooldown

        remaining = safe_duration - cursor - end_buffer
        if remaining < (cycle_zoom_in_duration + cycle_zoom_out_duration + 1.0):
            break

        hold_duration = min(
            rng.uniform(cycle_min_hold, cycle_max_hold),
            max(0.9, remaining - cycle_zoom_in_duration - cycle_zoom_out_duration),
        )
        base_zoom_delta = rng.uniform(0.22, 0.33) if interview_mode else rng.uniform(0.28, 0.40)
        max_zoom_delta = _resolve_target_zoom_delta(
            requested_zoom_factor=zoom_factor,
            base_zoom_delta=base_zoom_delta,
            start_zoom_factor=start_zoom_factor,
        )
        start_zoom_delta = min(start_zoom_factor, max_zoom_delta)
        zoom_out_start = cursor + cycle_zoom_in_duration + hold_duration
        cycle_end = zoom_out_start + cycle_zoom_out_duration
        if cycle_end > safe_duration - end_buffer:
            hold_duration = max(0.9, (safe_duration - end_buffer) - cursor - cycle_zoom_in_duration - cycle_zoom_out_duration)
            zoom_out_start = cursor + cycle_zoom_in_duration + hold_duration
            cycle_end = zoom_out_start + cycle_zoom_out_duration

        zoom_cycles.append({
            "index": cycle_index,
            "zoom_in_start": round(cursor, 3),
            "zoom_in_duration": round(cycle_zoom_in_duration, 3),
            "hold_duration": round(hold_duration, 3),
            "zoom_out_start": round(zoom_out_start, 3),
            "zoom_out_duration": round(cycle_zoom_out_duration, 3),
            "start_zoom_delta": round(start_zoom_delta, 4),
            "zoom_delta": round(max_zoom_delta, 4),
        })

        flash_in_strength = "medium" if cycle_index == 0 else ("low" if interview_mode else "medium")
        flash_events.append({
            "time": round(cursor, 3),
            "effect": "light_flash",
            "strength": flash_in_strength,
            "duration": 0.11 if interview_mode else 0.12,
            "reason": f"zoom_in_cycle_{cycle_index + 1}",
        })

        pattern_interrupts.extend([
            {
                "time": round(cursor, 3),
                "effect": "zoom_in",
                "strength": "medium" if interview_mode else "high",
                "duration": round(cycle_zoom_in_duration, 3),
                "reason": f"cycle_{cycle_index + 1}_zoom_in",
            },
            {
                "time": round(zoom_out_start, 3),
                "effect": "zoom_out",
                "strength": "low" if interview_mode else "medium",
                "duration": round(cycle_zoom_out_duration, 3),
                "reason": f"cycle_{cycle_index + 1}_zoom_out",
            },
        ])
        pattern_interrupts.append(flash_events[-1])

        cooldown = rng.uniform(cycle_min_cooldown, cycle_max_cooldown)
        cursor = cycle_end + cooldown
        cycle_index += 1

    if not zoom_cycles and safe_duration > 1.6:
        fallback_hold = max(1.0, safe_duration - initial_start - zoom_in_duration - zoom_out_duration - end_buffer)
        base_zoom_delta = 0.25 if interview_mode else 0.32
        max_zoom_delta = _resolve_target_zoom_delta(
            requested_zoom_factor=zoom_factor,
            base_zoom_delta=base_zoom_delta,
            start_zoom_factor=start_zoom_factor,
        )
        start_zoom_delta = min(start_zoom_factor, max_zoom_delta)
        zoom_out_start = initial_start + zoom_in_duration + fallback_hold
        zoom_cycles.append({
            "index": 0,
            "zoom_in_start": round(initial_start, 3),
            "zoom_in_duration": round(zoom_in_duration, 3),
            "hold_duration": round(fallback_hold, 3),
            "zoom_out_start": round(zoom_out_start, 3),
            "zoom_out_duration": round(zoom_out_duration, 3),
            "start_zoom_delta": round(start_zoom_delta, 4),
            "zoom_delta": round(max_zoom_delta, 4),
        })
        flash_events.extend([
            {
                "time": round(initial_start, 3),
                "effect": "light_flash",
                "strength": "medium",
                "duration": 0.11 if interview_mode else 0.12,
                "reason": "zoom_in_cycle_1",
            },
        ])
        pattern_interrupts = [
            {
                "time": round(initial_start, 3),
                "effect": "zoom_in",
                "strength": "medium",
                "duration": round(zoom_in_duration, 3),
                "reason": "cycle_1_zoom_in",
            },
            {
                "time": round(zoom_out_start, 3),
                "effect": "zoom_out",
                "strength": "medium",
                "duration": round(zoom_out_duration, 3),
                "reason": "cycle_1_zoom_out",
            },
            *flash_events,
        ]

    def build_flash_events_for_mode() -> List[Dict[str, Any]]:
        if flash_mode == "none" or safe_duration < 0.4:
            return []
        first_time = round(min(initial_start, max(0.0, safe_duration - 0.25)), 3)
        interval_map = {
            "start": None,
            "every_30s": 30.0,
            "every_20s": 20.0,
            "every_10s": 10.0,
            "every_8s": 8.0,
            "every_5s": 5.0,
        }
        interval = interval_map.get(flash_mode)
        events = [{
            "time": first_time,
            "effect": "light_flash",
            "strength": "medium",
            "duration": 0.10 if interview_mode else 0.11,
            "reason": "flash_start",
        }]
        if interval is None:
            return events
        cursor_time = first_time + interval
        end_time = max(0.0, safe_duration - 0.7)
        while cursor_time <= end_time:
            events.append({
                "time": round(cursor_time, 3),
                "effect": "light_flash",
                "strength": "low" if flash_mode in {"every_30s", "every_20s", "every_5s"} else "medium",
                "duration": 0.08 if flash_mode == "every_5s" else (0.09 if interview_mode else 0.10),
                "reason": f"flash_{flash_mode}",
            })
            cursor_time += interval
        return events

    flash_events = build_flash_events_for_mode()
    pattern_interrupts = [
        item
        for item in pattern_interrupts
        if item.get("effect") != "light_flash"
    ]
    pattern_interrupts = sorted(
        [*pattern_interrupts, *flash_events],
        key=lambda item: float(item.get("time") or 0.0),
    )

    return {
        "source": "cycle",
        "effect_notes": (
            "Every short starts with a quick smooth entry zoom, then repeats zoom-in, hold, and zoom-out cycles every few seconds."
        ),
        "start_zoom_factor": start_zoom_factor,
        "zoom_factor": zoom_factor,
        "flash_mode": flash_mode,
        "zoom_cycles": zoom_cycles,
        "flash_events": flash_events,
        "pattern_interrupts": pattern_interrupts,
    }


def _plan_pattern_interrupts_for_clip(
    *,
    transcript: Optional[Dict[str, Any]],
    duration: float,
    interview_mode: bool,
    ai_runtime: Dict[str, Any],
    seed_key: str = "",
    start_zoom_factor: float = 0.0,
    zoom_factor: float = 1.0,
    flash_mode: str = DEFAULT_PATTERN_FLASH_MODE,
) -> Dict[str, Any]:
    return _build_zoom_cycle_plan(
        duration,
        interview_mode=interview_mode,
        seed_key=seed_key,
        start_zoom_factor=start_zoom_factor,
        zoom_factor=zoom_factor,
        flash_mode=flash_mode,
    )


def _select_face_anchor_from_candidates(
    candidates: List[Dict[str, Any]],
    frame_width: int,
    frame_height: int,
    *,
    interview_mode: bool,
) -> Tuple[float, float]:
    if not candidates:
        return 0.5, 0.5 if interview_mode else 0.42

    if interview_mode or len(candidates) > 1:
        weighted_x = 0.0
        weighted_y = 0.0
        total_weight = 0.0
        for candidate in candidates:
            box = candidate.get("box") or [0, 0, frame_width, frame_height]
            x, y, w, h = box
            weight = max(1.0, float(candidate.get("score") or (w * h) or 1.0))
            weighted_x += (x + (w / 2.0)) * weight
            weighted_y += (y + (h * 0.45)) * weight
            total_weight += weight
        return (
            max(0.0, min(1.0, weighted_x / max(1.0, total_weight) / max(1.0, frame_width))),
            max(0.0, min(1.0, weighted_y / max(1.0, total_weight) / max(1.0, frame_height))),
        )

    biggest = max(candidates, key=lambda item: float(item.get("score") or 0.0))
    x, y, w, h = biggest.get("box") or [0, 0, frame_width, frame_height]
    return (
        max(0.0, min(1.0, (x + (w / 2.0)) / max(1.0, frame_width))),
        max(0.0, min(1.0, (y + (h * 0.42)) / max(1.0, frame_height))),
    )


def _smoothstep01(value: float) -> float:
    clamped = max(0.0, min(1.0, float(value)))
    return clamped * clamped * (3.0 - (2.0 * clamped))


def _resolve_zoom_profile(
    *,
    effect: str,
    duration_hint: float,
    interview_mode: bool,
) -> Tuple[float, float, float]:
    total_duration = max(0.25, float(duration_hint or 0.0))
    if effect == "zoom_flash":
        attack = 0.20 if interview_mode else 0.18
        hold = min(0.24 if interview_mode else 0.28, max(0.10, total_duration * 0.24))
    else:
        attack = 0.24 if interview_mode else 0.20
        hold = min(0.34 if interview_mode else 0.38, max(0.14, total_duration * 0.28))
    release = max(0.24 if interview_mode else 0.28, total_duration - attack - hold)
    return attack, hold, release


def _compute_zoom_event_strength(
    current_time: float,
    *,
    event_time: float,
    duration_hint: float,
    effect: str,
    interview_mode: bool,
) -> float:
    attack, hold, release = _resolve_zoom_profile(
        effect=effect,
        duration_hint=duration_hint,
        interview_mode=interview_mode,
    )
    start_time = event_time - (attack * 0.6)
    peak_start = start_time + attack
    peak_end = peak_start + hold
    end_time = peak_end + release

    if current_time < start_time or current_time > end_time:
        return 0.0
    if current_time <= peak_start:
        progress = (current_time - start_time) / max(attack, 1e-6)
        return _smoothstep01(progress)
    if current_time <= peak_end:
        return 1.0
    progress = (current_time - peak_end) / max(release, 1e-6)
    return 1.0 - _smoothstep01(progress)


def _compute_flash_event_strength(
    current_time: float,
    *,
    event_time: float,
    duration_hint: float,
) -> float:
    flash_duration = max(0.04, float(duration_hint or 0.08))
    attack = flash_duration * 0.35
    release = max(0.02, flash_duration - attack)
    start_time = event_time - attack
    end_time = event_time + release
    if current_time < start_time or current_time > end_time:
        return 0.0
    if current_time <= event_time:
        progress = (current_time - start_time) / max(attack, 1e-6)
        return _smoothstep01(progress)
    progress = (current_time - event_time) / max(release, 1e-6)
    return 1.0 - _smoothstep01(progress)


def _zoom_frame_to_anchor(frame, anchor_x: float, anchor_y: float, zoom_delta: float):
    import cv2

    frame_height, frame_width = frame.shape[:2]
    zoom_factor = 1.0 + max(0.0, zoom_delta)
    crop_w = max(2, min(frame_width, int(round(frame_width / zoom_factor))))
    crop_h = max(2, min(frame_height, int(round(frame_height / zoom_factor))))
    center_x = int(round(max(0.0, min(1.0, anchor_x)) * frame_width))
    center_y = int(round(max(0.0, min(1.0, anchor_y)) * frame_height))
    x1 = max(0, min(frame_width - crop_w, center_x - (crop_w // 2)))
    y1 = max(0, min(frame_height - crop_h, center_y - (crop_h // 2)))
    cropped = frame[y1:y1 + crop_h, x1:x1 + crop_w]
    if cropped.size == 0:
        return frame
    return cv2.resize(cropped, (frame_width, frame_height), interpolation=cv2.INTER_CUBIC)


def _move_anchor_towards(current: float, target: float, max_step: float) -> float:
    delta = max(-max_step, min(max_step, target - current))
    return current + delta


def _resolve_zoom_amount(strength: str, *, interview_mode: bool) -> float:
    if interview_mode:
        return {
            "low": 0.11,
            "medium": 0.16,
            "high": 0.21,
        }.get(strength, 0.16)
    return {
        "low": 0.14,
        "medium": 0.20,
        "high": 0.26,
    }.get(strength, 0.20)


def _resolve_flash_amount(strength: str, *, interview_mode: bool) -> float:
    if interview_mode:
        return {
            "low": 0.75,
            "medium": 1.05,
            "high": 1.35,
        }.get(strength, 1.05)
    return {
        "low": 0.95,
        "medium": 1.35,
        "high": 1.75,
    }.get(strength, 1.35)


def _apply_face_aware_pattern_interrupts_to_clip(
    *,
    input_path: str,
    output_path: str,
    transcript: Optional[Dict[str, Any]],
    pattern_plan: Dict[str, Any],
    interview_mode: bool,
    ai_runtime: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    zoom_cycles = list((pattern_plan or {}).get("zoom_cycles") or [])
    flash_events = list((pattern_plan or {}).get("flash_events") or [])
    if not zoom_cycles and not flash_events:
        return False, {
            "applied": False,
            "warning": "No pattern interrupts planned.",
            "pattern_plan": pattern_plan,
        }

    try:
        import cv2
        from main import detect_face_candidates
    except Exception as exc:
        return False, {
            "applied": False,
            "warning": f"Face-aware visuals unavailable: {exc}",
            "pattern_plan": pattern_plan,
        }

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return False, {
            "applied": False,
            "warning": "Could not open rendered clip for face-aware effects.",
            "pattern_plan": pattern_plan,
        }

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    sample_stride = max(1, int(round(fps / (7.5 if interview_mode else 8.0))))
    anchor_x = 0.5
    anchor_y = 0.42
    target_anchor_x = anchor_x
    target_anchor_y = anchor_y
    top_anchor_x = 0.5
    top_anchor_y = 0.44
    top_target_anchor_x = top_anchor_x
    top_target_anchor_y = top_anchor_y
    bottom_anchor_x = 0.5
    bottom_anchor_y = 0.44
    bottom_target_anchor_x = bottom_anchor_x
    bottom_target_anchor_y = bottom_anchor_y
    detection_blend = 0.07 if interview_mode else 0.085
    anchor_step = 0.045 if interview_mode else 0.06
    max_target_delta = 0.055 if interview_mode else 0.075
    detected_samples = 0

    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{width}x{height}",
        "-pix_fmt",
        "bgr24",
        "-r",
        f"{fps:.6f}",
        "-i",
        "-",
        "-i",
        input_path,
        *ffmpeg_thread_args(),
        "-map",
        "0:v:0",
    ]
    if _video_has_audio(input_path):
        command.extend(["-map", "1:a:0", "-c:a", "copy"])
    else:
        command.append("-an")
    command.extend([
        "-c:v",
        "libx264",
        "-preset",
        os.environ.get("OVERLAY_FFMPEG_PRESET", "veryfast").strip() or "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-shortest",
        output_path,
    ])

    ffmpeg_process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **subprocess_priority_kwargs(),
    )

    frame_index = 0
    try:
        while True:
            success, frame = cap.read()
            if not success:
                break

            frame = frame[:height, :width]
            if frame_index % sample_stride == 0:
                if interview_mode:
                    split_y = height // 2
                    top_frame = frame[:split_y, :]
                    bottom_frame = frame[split_y:, :]
                    try:
                        top_candidates = detect_face_candidates(top_frame)
                    except Exception:
                        top_candidates = []
                    try:
                        bottom_candidates = detect_face_candidates(bottom_frame)
                    except Exception:
                        bottom_candidates = []

                    if top_candidates:
                        detected_samples += 1
                        next_anchor_x, next_anchor_y = _select_face_anchor_from_candidates(
                            top_candidates,
                            width,
                            max(1, top_frame.shape[0]),
                            interview_mode=False,
                        )
                        top_dx = max(-max_target_delta, min(max_target_delta, next_anchor_x - top_target_anchor_x))
                        top_dy = max(-max_target_delta, min(max_target_delta, next_anchor_y - top_target_anchor_y))
                        top_target_anchor_x = top_target_anchor_x + (top_dx * detection_blend)
                        top_target_anchor_y = top_target_anchor_y + (top_dy * detection_blend)

                    if bottom_candidates:
                        detected_samples += 1
                        next_anchor_x, next_anchor_y = _select_face_anchor_from_candidates(
                            bottom_candidates,
                            width,
                            max(1, bottom_frame.shape[0]),
                            interview_mode=False,
                        )
                        bottom_dx = max(-max_target_delta, min(max_target_delta, next_anchor_x - bottom_target_anchor_x))
                        bottom_dy = max(-max_target_delta, min(max_target_delta, next_anchor_y - bottom_target_anchor_y))
                        bottom_target_anchor_x = bottom_target_anchor_x + (bottom_dx * detection_blend)
                        bottom_target_anchor_y = bottom_target_anchor_y + (bottom_dy * detection_blend)
                else:
                    try:
                        candidates = detect_face_candidates(frame)
                    except Exception:
                        candidates = []
                    if candidates:
                        detected_samples += 1
                        next_anchor_x, next_anchor_y = _select_face_anchor_from_candidates(
                            candidates,
                            width,
                            height,
                            interview_mode=False,
                        )
                        target_dx = max(-max_target_delta, min(max_target_delta, next_anchor_x - target_anchor_x))
                        target_dy = max(-max_target_delta, min(max_target_delta, next_anchor_y - target_anchor_y))
                        target_anchor_x = target_anchor_x + (target_dx * detection_blend)
                        target_anchor_y = target_anchor_y + (target_dy * detection_blend)

            if interview_mode:
                top_anchor_x = top_anchor_x + ((top_target_anchor_x - top_anchor_x) * anchor_step)
                top_anchor_y = top_anchor_y + ((top_target_anchor_y - top_anchor_y) * anchor_step)
                bottom_anchor_x = bottom_anchor_x + ((bottom_target_anchor_x - bottom_anchor_x) * anchor_step)
                bottom_anchor_y = bottom_anchor_y + ((bottom_target_anchor_y - bottom_anchor_y) * anchor_step)
            else:
                anchor_x = anchor_x + ((target_anchor_x - anchor_x) * anchor_step)
                anchor_y = anchor_y + ((target_anchor_y - anchor_y) * anchor_step)

            current_time = frame_index / max(1.0, fps)
            zoom_delta = 0.0
            flash_level = 0.0
            for cycle in zoom_cycles:
                zoom_in_start = float(cycle.get("zoom_in_start") or 0.0)
                zoom_in_duration = max(0.1, float(cycle.get("zoom_in_duration") or 0.56))
                hold_duration = max(0.0, float(cycle.get("hold_duration") or 5.0))
                zoom_out_start = float(cycle.get("zoom_out_start") or (zoom_in_start + zoom_in_duration + hold_duration))
                zoom_out_duration = max(0.1, float(cycle.get("zoom_out_duration") or 0.64))
                start_zoom_delta = max(0.0, float(cycle.get("start_zoom_delta") or 0.0))
                cycle_zoom_delta = max(0.0, float(cycle.get("zoom_delta") or 0.0))

                if current_time < zoom_in_start:
                    active_zoom = start_zoom_delta
                elif current_time <= (zoom_in_start + zoom_in_duration):
                    progress = (current_time - zoom_in_start) / max(zoom_in_duration, 1e-6)
                    active_zoom = start_zoom_delta + ((cycle_zoom_delta - start_zoom_delta) * _smoothstep01(progress))
                elif current_time <= zoom_out_start:
                    active_zoom = cycle_zoom_delta
                elif current_time <= (zoom_out_start + zoom_out_duration):
                    progress = (current_time - zoom_out_start) / max(zoom_out_duration, 1e-6)
                    active_zoom = start_zoom_delta + ((cycle_zoom_delta - start_zoom_delta) * (1.0 - _smoothstep01(progress)))
                else:
                    active_zoom = start_zoom_delta

                zoom_delta = max(zoom_delta, active_zoom)

            for event in flash_events:
                event_time = float(event.get("time") or 0.0)
                event_duration = max(0.05, float(event.get("duration") or 0.1))
                strength = event.get("strength") or "medium"
                flash_level = max(
                    flash_level,
                    _resolve_flash_amount(strength, interview_mode=interview_mode)
                    * _compute_flash_event_strength(
                        current_time,
                        event_time=event_time,
                        duration_hint=event_duration,
                    ),
                )

            processed = frame
            if zoom_delta > 0.001:
                if interview_mode:
                    split_y = height // 2
                    top_frame = frame[:split_y, :]
                    bottom_frame = frame[split_y:, :]
                    top_processed = _zoom_frame_to_anchor(top_frame, top_anchor_x, top_anchor_y, zoom_delta)
                    bottom_processed = _zoom_frame_to_anchor(bottom_frame, bottom_anchor_x, bottom_anchor_y, zoom_delta)
                    processed = np.vstack((top_processed, bottom_processed))
                    cv2.line(processed, (0, split_y), (width, split_y), (255, 255, 255), 3)
                else:
                    processed = _zoom_frame_to_anchor(frame, anchor_x, anchor_y, zoom_delta)

            if flash_level > 0.001:
                processed = cv2.convertScaleAbs(
                    processed,
                    alpha=1.0 + ((0.10 if interview_mode else 0.14) * flash_level),
                    beta=(42.0 if interview_mode else 64.0) * flash_level,
                )

            ffmpeg_process.stdin.write(processed.tobytes())
            frame_index += 1

        ffmpeg_process.stdin.close()
        ffmpeg_process.stdin = None
        stderr = ffmpeg_process.stderr.read().decode("utf-8", errors="ignore")
        return_code = ffmpeg_process.wait()
        if return_code != 0:
            raise RuntimeError(stderr or f"FFmpeg exited with code {return_code}")
    except Exception as exc:
        try:
            if ffmpeg_process.stdin:
                ffmpeg_process.stdin.close()
        except Exception:
            pass
        try:
            ffmpeg_process.kill()
        except Exception:
            pass
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        return False, {
            "applied": False,
            "warning": str(exc),
            "pattern_plan": pattern_plan,
        }
    finally:
        cap.release()

    return True, {
        "applied": True,
        "warning": ai_runtime.get("warning") or "",
        "pattern_plan": pattern_plan,
        "face_detection_samples": detected_samples,
    }

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
        subtitle_settings = _build_subtitle_settings(req, clip_data)
        clip_data["subtitle_settings"] = subtitle_settings
        clip_data["status"] = clip_data.get("status") or "draft"
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)
        return {
            "success": True,
            "settings_saved": True,
            "clip": clip_data,
        }

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
        preferred_language = _resolve_subtitle_language_hint(
            metadata_data=data,
            clip_data=clip_data,
            source_version=source_version,
            fallback_filename=source_version.get("filename"),
        )
        subtitle_transcript, clip_start, clip_end, subtitle_source_mode = _resolve_subtitle_transcript_payload(
            metadata_data=data,
            clip_data=clip_data,
            input_path=input_path,
            preferred_language=preferred_language,
            transcript_source_hint=source_version.get("transcript_source"),
            transcript_start=source_version.get("transcript_start"),
            transcript_end=source_version.get("transcript_end"),
        )
        print(f"📝 Subtitle transcript mode: {subtitle_source_mode}")

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
    start_zoom_factor: Optional[float] = None
    zoom_factor: Optional[float] = None
    flash_mode: Optional[str] = None

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
        hook_settings = _build_hook_settings(req, clip_data)
        if not hook_settings:
            raise HTTPException(status_code=400, detail="Hook text is required")
        clip_data["hook_settings"] = hook_settings
        clip_data["status"] = clip_data.get("status") or "draft"
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)
        return {
            "success": True,
            "settings_saved": True,
            "clip": clip_data,
        }

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


@app.post("/api/clip/text-metadata")
async def update_clip_text_metadata(req: ClipTextMetadataUpdateRequest):
    _get_job_record_or_404(req.job_id)

    updated_clip = _persist_clip_text_metadata(
        req.job_id,
        req.clip_index,
        video_title_for_youtube_short=req.video_title_for_youtube_short if req.video_title_for_youtube_short is not None else _METADATA_UNSET,
        video_description_for_tiktok=req.video_description_for_tiktok if req.video_description_for_tiktok is not None else _METADATA_UNSET,
        video_description_for_instagram=req.video_description_for_instagram if req.video_description_for_instagram is not None else _METADATA_UNSET,
        instagram_collaborators=req.instagram_collaborators if req.instagram_collaborators is not None else _METADATA_UNSET,
        start_zoom_factor=req.start_zoom_factor if req.start_zoom_factor is not None else _METADATA_UNSET,
        zoom_factor=req.zoom_factor if req.zoom_factor is not None else _METADATA_UNSET,
        flash_mode=req.flash_mode if req.flash_mode is not None else _METADATA_UNSET,
    )
    if updated_clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    return {
        "success": True,
        "job_id": req.job_id,
        "clip": updated_clip,
    }


@app.post("/api/clip/range-adjust")
async def adjust_clip_range(req: ClipRangeAdjustRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)
    clips = data.get("shorts", [])
    if req.clip_index < 0 or req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found.")

    clip_data = dict(clips[req.clip_index] or {})
    clip_data["clip_index"] = req.clip_index
    _ensure_clip_versions(req.job_id, output_dir, clip_data)

    source_input_path = _resolve_clip_source_input_path(req.job_id, output_dir, clip_data, ensure_h264=False)
    if not source_input_path or not os.path.exists(source_input_path):
        raise HTTPException(status_code=404, detail="Source input video for clip not found")

    source_duration = _probe_video_duration(source_input_path)
    current_start = float(
        clip_data.get("start", clip_data.get("preview_source_start", clip_data.get("preview_start", 0.0))) or 0.0
    )
    current_end = float(
        clip_data.get("end", clip_data.get("preview_source_end", clip_data.get("preview_end", current_start))) or current_start
    )

    if req.absolute_start is not None or req.absolute_end is not None:
        next_start = current_start if req.absolute_start is None else max(0.0, float(req.absolute_start))
        next_end = current_end if req.absolute_end is None else min(source_duration, float(req.absolute_end))
    else:
        next_start = max(0.0, current_start + float(req.delta_start or 0.0))
        next_end = min(source_duration, current_end + float(req.delta_end or 0.0))

    if next_end <= next_start:
        raise HTTPException(status_code=400, detail="Clipbereich wäre ungültig.")
    if (next_end - next_start) < 0.25:
        raise HTTPException(status_code=400, detail="Clipbereich wäre zu kurz.")

    source_filename = os.path.basename(source_input_path)
    old_preview_filename = os.path.basename(str(clip_data.get("preview_video_filename") or "").strip())
    old_browser_preview_filename = os.path.basename(str(clip_data.get("browser_preview_filename") or "").strip())

    clip_data["start"] = round(next_start, 3)
    clip_data["end"] = round(next_end, 3)
    clip_data["display_duration"] = round(next_end - next_start, 3)
    clip_data["source_video_filename"] = source_filename
    clip_data["preview_video_filename"] = source_filename
    clip_data["preview_video_url"] = ""
    clip_data["preview_start"] = round(next_start, 3)
    clip_data["preview_end"] = round(next_end, 3)
    clip_data["preview_source_start"] = round(next_start, 3)
    clip_data["preview_source_end"] = round(next_end, 3)
    clip_data["preview_sample_seconds"] = round(next_end - next_start, 3)
    clip_data.pop("browser_preview_url", None)
    clip_data.pop("browser_preview_filename", None)
    clip_data.pop("browser_preview_source_filename", None)
    clip_data.pop("preview_generated_at", None)
    clip_data.pop("tight_edit_preset", None)
    clip_data.pop("tight_edit_removed_ranges", None)
    clip_data.pop("video_url", None)
    clip_data.pop("video_filename", None)
    clip_data.pop("active_version_id", None)
    clip_data["status"] = "draft"
    clip_data.pop("error", None)

    for transient_filename in {old_preview_filename, old_browser_preview_filename}:
        if transient_filename and transient_filename != source_filename:
            transient_path = os.path.join(output_dir, transient_filename)
            if os.path.exists(transient_path):
                try:
                    os.remove(transient_path)
                except Exception:
                    pass

    clips[req.clip_index] = clip_data
    data["shorts"] = clips
    _write_metadata(metadata_path, data)
    result = _refresh_job_result(req.job_id)
    refreshed_clip = _find_result_clip(result, req.clip_index) if result else clip_data

    return {
        "success": True,
        "clip": refreshed_clip,
    }


class TrimRequest(BaseModel):
    job_id: str
    clip_index: int
    input_filename: Optional[str] = None
    trim_start: float = 0.0
    trim_end: Optional[float] = None
    remove_ranges: Optional[List[List[float]]] = None


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
    remove_ranges = []
    for entry in req.remove_ranges or []:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            remove_ranges.append((float(entry[0]), float(entry[1])))
    keep_segments = plan_manual_keep_segments(trim_start, trim_end, remove_ranges, min_segment_duration=0.12)
    if not keep_segments:
        raise HTTPException(status_code=400, detail="All selected cuts would remove the full clip.")

    if metadata_changed:
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    def run_trim():
        render_keep_segments(
            input_path,
            keep_segments,
            output_path,
            ffmpeg_preset=os.environ.get("OVERLAY_FFMPEG_PRESET", "veryfast").strip() or "veryfast",
            crf="18",
            audio_bitrate="192k",
            thread_args=ffmpeg_thread_args(),
            subprocess_kwargs=subprocess_priority_kwargs(),
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
    if transcript_source == "original" and len(keep_segments) == 1:
        source_start = float(transcript_start or clip_data.get("start", 0.0))
        transcript_start = source_start + keep_segments[0][0]
        transcript_end = source_start + keep_segments[0][1]
    else:
        transcript_source = "audio"
        transcript_start = None
        transcript_end = None

    label = f"Trim {_format_time_label(trim_start)}-{_format_time_label(trim_end)}"
    if remove_ranges:
        label += f" (-{len(remove_ranges)} cuts)"
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
        "duration": round(sum(segment_end - segment_start for segment_start, segment_end in keep_segments), 3),
    }


class RenderClipRequest(BaseModel):
    job_id: str
    clip_index: int
    apply_tight_edit: Optional[bool] = True
    tight_edit_preset: Optional[str] = None
    apply_subtitles: Optional[bool] = True
    subtitle_settings: Optional[Dict[str, Any]] = None
    apply_hook: Optional[bool] = True
    hook_settings: Optional[Dict[str, Any]] = None
    interview_mode: Optional[bool] = None
    pattern_flash_mode: Optional[str] = None
    apply_stock_overlay: Optional[bool] = False


class BrowserClipPreviewRequest(BaseModel):
    job_id: str
    clip_index: int
    input_filename: Optional[str] = None
    force_regenerate: Optional[bool] = False


def _browser_preview_source_path(
    *,
    job_id: str,
    output_dir: str,
    clip: Dict[str, Any],
    input_filename: Optional[str],
) -> tuple[str, bool]:
    source_input_path = _resolve_clip_source_input_path(job_id, output_dir, clip, ensure_h264=False)
    source_input_abs = os.path.abspath(source_input_path) if source_input_path else ""

    def _is_source_asset(path: str) -> bool:
        if not source_input_abs:
            return False
        try:
            return os.path.abspath(path) == source_input_abs or os.path.samefile(path, source_input_abs)
        except OSError:
            return os.path.abspath(path) == source_input_abs

    requested_name = os.path.basename(str(input_filename or "").strip())
    if requested_name:
        requested_path = os.path.abspath(os.path.join(output_dir, requested_name))
        if os.path.exists(requested_path):
            version = _find_clip_version(clip, filename=requested_name)
            return requested_path, bool(version) and not _is_source_asset(requested_path)

    active_version = _find_clip_version(clip)
    if active_version:
        active_filename = os.path.basename(active_version.get("filename") or "")
        active_path = os.path.abspath(os.path.join(output_dir, active_filename))
        if active_filename and os.path.exists(active_path):
            return active_path, not _is_source_asset(active_path)

    if not source_input_path:
        raise HTTPException(status_code=404, detail="Source input video for browser preview not found")
    return source_input_path, False


def _build_browser_preview_filename(
    *,
    source_path: str,
    source_start: float,
    source_end: float,
    clip_local_asset: bool,
    width: int,
    fps: int,
    crf: str,
) -> str:
    try:
        stat = os.stat(source_path)
        source_fingerprint = f"{os.path.basename(source_path)}:{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        source_fingerprint = os.path.basename(source_path)
    digest = hashlib.sha1(
        f"{source_fingerprint}|{source_start:.3f}|{source_end:.3f}|{int(clip_local_asset)}|{width}|{fps}|{crf}".encode("utf-8")
    ).hexdigest()[:16]
    return f"browser_preview_{digest}.mp4"


def _resolve_target_zoom_delta(
    *,
    requested_zoom_factor: float,
    base_zoom_delta: float,
    start_zoom_factor: float,
) -> float:
    del base_zoom_delta
    requested = _clamp_zoom_factor(requested_zoom_factor, DEFAULT_TARGET_ZOOM_FACTOR)
    start_delta = max(0.0, float(start_zoom_factor or 0.0))
    target = max(start_delta, requested)
    return min(2.0, target)


@app.post("/api/clip/preview/browser")
async def render_browser_clip_preview(req: BrowserClipPreviewRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index

    requested_input_filename = os.path.basename(str(req.input_filename or "").strip())
    source_path, clip_local_asset = _browser_preview_source_path(
        job_id=req.job_id,
        output_dir=output_dir,
        clip=clip_data,
        input_filename=req.input_filename,
    )
    logical_source_filename = requested_input_filename or os.path.basename(source_path)

    source_start = 0.0
    try:
        source_end = _probe_video_duration(source_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not probe preview source: {exc}") from exc

    if not clip_local_asset:
        source_start = float(clip_data.get("start", clip_data.get("preview_start", 0.0)) or 0.0)
        source_end = float(clip_data.get("end", clip_data.get("preview_end", source_start)) or source_start)

    if source_end <= source_start:
        raise HTTPException(status_code=400, detail="Invalid browser preview timestamps")

    def _env_int(name: str, default: int, minimum: int) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            value = default
        value = max(minimum, value)
        if value % 2 != 0:
            value += 1
        return value

    preview_width = _env_int("BROWSER_PREVIEW_WIDTH", 360, 180)
    preview_fps = max(8, min(30, _env_int("BROWSER_PREVIEW_FPS", 12, 8)))
    preview_preset = (os.environ.get("BROWSER_PREVIEW_PRESET", "ultrafast") or "ultrafast").strip() or "ultrafast"
    preview_crf = str((os.environ.get("BROWSER_PREVIEW_CRF", "38") or "38")).strip() or "38"
    preview_maxrate = str((os.environ.get("BROWSER_PREVIEW_MAXRATE", "600k") or "600k")).strip() or "600k"
    preview_bufsize = str((os.environ.get("BROWSER_PREVIEW_BUFSIZE", "1200k") or "1200k")).strip() or "1200k"
    preview_audio_bitrate = str((os.environ.get("BROWSER_PREVIEW_AUDIO_BITRATE", "64k") or "64k")).strip() or "64k"
    preview_threads = max(1, min(4, _env_positive_int("BROWSER_PREVIEW_THREADS", 2)))

    preview_filename = _build_browser_preview_filename(
        source_path=source_path,
        source_start=source_start,
        source_end=source_end,
        clip_local_asset=clip_local_asset,
        width=preview_width,
        fps=preview_fps,
        crf=preview_crf,
    )
    preview_path = os.path.join(output_dir, preview_filename)

    if req.force_regenerate and os.path.exists(preview_path):
        try:
            os.remove(preview_path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Existing browser preview could not be replaced: {exc}") from exc
    elif os.path.exists(preview_path):
        try:
            if os.path.getsize(preview_path) <= 0:
                os.remove(preview_path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Existing browser preview could not be checked: {exc}") from exc

    if not os.path.exists(preview_path):
        duration = max(0.15, source_end - source_start)
        filter_chain = (
            f"fps={preview_fps},"
            f"scale=w='min({preview_width},iw)':h=-2:force_original_aspect_ratio=decrease,"
            "scale=w='trunc(iw/2)*2':h='trunc(ih/2)*2'"
        )
        temp_preview_path = f"{preview_path}.tmp_{os.getpid()}_{int(time.time() * 1000)}.mp4"

        def run_browser_preview_render():
            cmd = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
            ]
            if not clip_local_asset:
                cmd += ["-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}"]
            cmd += [
                "-i",
                source_path,
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-vf",
                filter_chain,
                "-c:v",
                "libx264",
                "-preset",
                preview_preset,
                "-crf",
                preview_crf,
                "-maxrate",
                preview_maxrate,
                "-bufsize",
                preview_bufsize,
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-c:a",
                "aac",
                "-b:a",
                preview_audio_bitrate,
                "-ac",
                "1",
                "-threads",
                str(preview_threads),
                temp_preview_path,
            ]
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **subprocess_priority_kwargs(),
            )
            if not os.path.exists(temp_preview_path) or os.path.getsize(temp_preview_path) <= 0:
                raise RuntimeError("Browser preview render produced no output.")
            os.replace(temp_preview_path, preview_path)

        try:
            async with browser_preview_semaphore:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, run_browser_preview_render)
        except subprocess.CalledProcessError as exc:
            if os.path.exists(temp_preview_path):
                try:
                    os.remove(temp_preview_path)
                except OSError:
                    pass
            error_text = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
            raise HTTPException(status_code=500, detail=f"Browser preview render failed: {error_text}") from exc
        except Exception as exc:
            if os.path.exists(temp_preview_path):
                try:
                    os.remove(temp_preview_path)
                except OSError:
                    pass
            raise HTTPException(status_code=500, detail=f"Browser preview render failed: {exc}") from exc

    try:
        preview_duration = _probe_video_duration(preview_path)
    except Exception:
        preview_duration = max(0.15, source_end - source_start)

    changed = False
    if clip_data.get("browser_preview_filename") != preview_filename:
        clip_data["browser_preview_filename"] = preview_filename
        clip_data["browser_preview_url"] = _clip_video_url(req.job_id, preview_filename)
        clip_data["browser_preview_generated_at"] = time.time()
        clip_data["browser_preview_source_filename"] = logical_source_filename
        changed = True
    if changed:
        data["shorts"][req.clip_index] = clip_data
        _write_metadata(metadata_path, data)
        _refresh_job_result(req.job_id)

    return {
        "success": True,
        "preview_video_url": _clip_video_url(req.job_id, preview_filename),
        "clip_local": True,
        "duration": round(max(0.15, preview_duration), 3),
        "source_mode": "clip_asset" if clip_local_asset else "source_segment",
    }


@app.post("/api/clip/preview/render")
async def render_clip_preview(req: RenderClipRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index

    source_input_path = _resolve_clip_source_input_path(req.job_id, output_dir, clip_data, ensure_h264=False)
    if not source_input_path:
        raise HTTPException(status_code=404, detail="Source input video for preview clip not found")

    source_start = float(clip_data.get("start", clip_data.get("preview_start", 0.0)) or 0.0)
    source_end = float(clip_data.get("end", clip_data.get("preview_end", source_start)) or source_start)
    if source_end <= source_start:
        raise HTTPException(status_code=400, detail="Invalid clip timestamps")

    try:
        preview_sample_seconds = float(os.environ.get("PREVIEW_SAMPLE_SECONDS", "1.0"))
    except (TypeError, ValueError):
        preview_sample_seconds = 1.0
    preview_sample_seconds = max(0.15, preview_sample_seconds)

    preview_source_start = source_start
    preview_source_end = min(source_end, source_start + preview_sample_seconds)
    if preview_source_end <= preview_source_start:
        preview_source_end = min(source_end, preview_source_start + 0.15)
    if preview_source_end <= preview_source_start:
        raise HTTPException(status_code=400, detail="Invalid preview sample timestamps")

    def _env_int(name: str, default: int, minimum: int) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            value = default
        value = max(minimum, value)
        if value % 2 != 0:
            value += 1
        return value

    preview_render_width = _env_int("PREVIEW_RENDER_WIDTH", 360, 180)
    preview_render_height = _env_int("PREVIEW_RENDER_HEIGHT", 640, 320)
    preview_trim_preset = (os.environ.get("PREVIEW_TRIM_PRESET", "ultrafast") or "ultrafast").strip() or "ultrafast"
    preview_vertical_preset = (os.environ.get("PREVIEW_VERTICAL_PRESET", "ultrafast") or "ultrafast").strip() or "ultrafast"
    preview_render_crf = str((os.environ.get("PREVIEW_RENDER_CRF", "34") or "34")).strip() or "34"
    preview_render_maxrate = str((os.environ.get("PREVIEW_RENDER_MAXRATE", "1M") or "1M")).strip() or "1M"
    preview_render_bufsize = str((os.environ.get("PREVIEW_RENDER_BUFSIZE", "2M") or "2M")).strip() or "2M"
    preview_audio_bitrate = str((os.environ.get("PREVIEW_AUDIO_BITRATE", "96k") or "96k")).strip() or "96k"

    manifest = load_job_manifest(output_dir)
    request_meta = manifest.get("request", {})
    interview_mode = req.interview_mode if req.interview_mode is not None else bool(request_meta.get("interview_mode"))

    subtitle_settings = _sanitize_subtitle_settings_dict(req.subtitle_settings, clip_data)
    hook_settings = _sanitize_hook_settings_dict(req.hook_settings, clip_data)
    apply_subtitles = bool(req.apply_subtitles) and bool(subtitle_settings)
    apply_hook = bool(req.apply_hook) and bool(hook_settings)
    visual_start_zoom_factor = _clamp_zoom_factor((hook_settings or {}).get("start_zoom_factor"), DEFAULT_START_ZOOM_FACTOR)
    visual_zoom_factor = max(
        _clamp_zoom_factor((hook_settings or {}).get("zoom_factor"), DEFAULT_TARGET_ZOOM_FACTOR),
        visual_start_zoom_factor,
    )
    pattern_flash_mode = _normalize_pattern_flash_mode(
        req.pattern_flash_mode or (hook_settings or {}).get("flash_mode")
    )

    transcript = data.get("transcript")
    keep_segments = [(preview_source_start, preview_source_end)]

    request_token = int(time.time() * 1000)
    temp_clip_filename = f"temp_preview_source_{request_token}_{req.clip_index + 1}.mp4"
    temp_vertical_filename = f"temp_preview_vertical_{request_token}_{req.clip_index + 1}.mp4"
    final_preview_filename = f"preview_rendered_{request_token}_clip_{req.clip_index + 1}.mp4"
    temp_clip_path = os.path.join(output_dir, temp_clip_filename)
    temp_vertical_path = os.path.join(output_dir, temp_vertical_filename)
    final_preview_path = os.path.join(output_dir, final_preview_filename)

    generated_paths: List[str] = []
    current_path = temp_vertical_path

    def run_base_preview():
        render_keep_segments(
            source_input_path,
            keep_segments,
            temp_clip_path,
            ffmpeg_preset=preview_trim_preset,
            crf=preview_render_crf,
            audio_bitrate=preview_audio_bitrate,
            thread_args=ffmpeg_thread_args(),
            subprocess_kwargs=subprocess_priority_kwargs(),
        )
        from main import process_video_to_vertical
        return process_video_to_vertical(
            temp_clip_path,
            temp_vertical_path,
            interview_mode=bool(interview_mode),
            output_width=preview_render_width,
            output_height=preview_render_height,
            ffmpeg_preset_override=preview_vertical_preset,
            video_crf=preview_render_crf,
            video_maxrate=preview_render_maxrate,
            video_bufsize=preview_render_bufsize,
            audio_bitrate=preview_audio_bitrate,
        )

    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, run_base_preview)
        if not success or not os.path.exists(temp_vertical_path):
            raise HTTPException(status_code=500, detail="Preview render failed")
        generated_paths.append(temp_vertical_path)

        if apply_subtitles:
            subtitle_filename = f"preview_subtitled_{request_token}_clip_{req.clip_index + 1}.mp4"
            subtitle_path = os.path.join(output_dir, subtitle_filename)
            preferred_language = _resolve_subtitle_language_hint(
                metadata_data=data,
                clip_data=clip_data,
                fallback_filename=os.path.basename(current_path),
            )
            subtitle_transcript, subtitle_clip_start, subtitle_clip_end, subtitle_source_mode = _resolve_subtitle_transcript_payload(
                metadata_data=data,
                clip_data=clip_data,
                input_path=current_path,
                preferred_language=preferred_language,
                transcript_source_hint="original",
                transcript_start=preview_source_start,
                transcript_end=preview_source_end,
            )
            print(f"📝 Preview subtitle transcript mode: {subtitle_source_mode}")

            def run_subtitles():
                return burn_subtitles(
                    current_path,
                    subtitle_transcript,
                    subtitle_clip_start,
                    subtitle_clip_end,
                    subtitle_path,
                    alignment=subtitle_settings.get("position", "bottom"),
                    y_position=subtitle_settings.get("y_position"),
                    fontsize=subtitle_settings.get("font_size", 16),
                    font_family=subtitle_settings.get("font_family"),
                    background_style=subtitle_settings.get("background_style"),
                )

            subtitle_success = await loop.run_in_executor(None, run_subtitles)
            if not subtitle_success:
                raise HTTPException(status_code=400, detail="No words found for this clip range.")
            current_path = subtitle_path
            generated_paths.append(subtitle_path)

        if apply_hook:
            hook_filename = f"preview_hook_{request_token}_clip_{req.clip_index + 1}.mp4"
            hook_path = os.path.join(output_dir, hook_filename)
            size_map = {"S": 0.8, "M": 1.0, "L": 1.3}

            def run_hook():
                return add_hook_to_video(
                    current_path,
                    hook_settings["text"],
                    hook_path,
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

            await loop.run_in_executor(None, run_hook)
            current_path = hook_path
            generated_paths.append(hook_path)

        if os.path.abspath(current_path) != os.path.abspath(final_preview_path):
            if os.path.exists(final_preview_path):
                os.remove(final_preview_path)
            shutil.move(current_path, final_preview_path)

        if not os.path.exists(final_preview_path):
            raise HTTPException(status_code=500, detail="Preview output missing")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for path in generated_paths:
            if os.path.abspath(path) == os.path.abspath(final_preview_path):
                continue
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(temp_clip_path):
            os.remove(temp_clip_path)

    try:
        preview_duration = _probe_video_duration(final_preview_path)
    except Exception:
        preview_duration = max(0.15, preview_source_end - preview_source_start)
    preview_duration = max(0.15, preview_duration)

    clip_data["display_duration"] = round(preview_duration, 3)
    clip_data.pop("tight_edit_preset", None)
    clip_data.pop("tight_edit_removed_ranges", None)

    clip_data["source_video_filename"] = clip_data.get("source_video_filename") or os.path.basename(source_input_path)
    clip_data["preview_video_filename"] = final_preview_filename
    clip_data["preview_video_url"] = _clip_video_url(req.job_id, final_preview_filename)
    clip_data["preview_start"] = 0.0
    clip_data["preview_end"] = round(preview_duration, 3)
    clip_data["preview_generated_at"] = time.time()
    clip_data["preview_source_start"] = round(preview_source_start, 3)
    clip_data["preview_source_end"] = round(preview_source_end, 3)
    clip_data["preview_sample_seconds"] = round(preview_duration, 3)
    clip_data["preview_interview_mode"] = bool(interview_mode)

    if subtitle_settings:
        clip_data["subtitle_settings"] = subtitle_settings
    if hook_settings:
        clip_data["hook_settings"] = hook_settings

    if clip_data.get("status") in {"pending", "failed", "draft", None}:
        clip_data["status"] = "draft"

    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    audio_included = _video_has_audio(final_preview_path)

    return {
        "success": True,
        "preview_video_url": clip_data["preview_video_url"],
        "audio_included": audio_included,
        "preview_sample_seconds": clip_data["preview_sample_seconds"],
        "clip": clip_data,
    }


@app.post("/api/clip/render")
async def render_clip(req: RenderClipRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index

    source_input_path = _resolve_clip_source_input_path(req.job_id, output_dir, clip_data, ensure_h264=False)
    if not source_input_path:
        raise HTTPException(status_code=404, detail="Source input video for preview clip not found")

    source_start = float(clip_data.get("start", clip_data.get("preview_start", 0.0)) or 0.0)
    source_end = float(clip_data.get("end", clip_data.get("preview_end", source_start)) or source_start)
    if source_end <= source_start:
        raise HTTPException(status_code=400, detail="Invalid clip timestamps")

    manifest = load_job_manifest(output_dir)
    request_meta = manifest.get("request", {})
    tight_edit_preset = _coerce_tight_edit_preset(req.tight_edit_preset or request_meta.get("tight_edit_preset"))
    apply_tight_edit = req.apply_tight_edit if req.apply_tight_edit is not None else True
    interview_mode = req.interview_mode if req.interview_mode is not None else bool(request_meta.get("interview_mode"))

    subtitle_settings = _sanitize_subtitle_settings_dict(req.subtitle_settings, clip_data)
    hook_settings = _sanitize_hook_settings_dict(req.hook_settings, clip_data)
    apply_subtitles = bool(req.apply_subtitles) and bool(subtitle_settings)
    apply_hook = bool(req.apply_hook) and bool(hook_settings)

    transcript = data.get("transcript")
    keep_segments = [(source_start, source_end)]
    tight_edit_plan = None
    if apply_tight_edit and transcript:
        tight_edit_plan = build_tight_edit_plan(transcript, source_start, source_end, tight_edit_preset)
        keep_segments = tight_edit_plan.get("keep_segments") or keep_segments

    request_token = int(time.time() * 1000)
    temp_clip_filename = f"temp_render_source_{request_token}_{req.clip_index + 1}.mp4"
    temp_clip_path = os.path.join(output_dir, temp_clip_filename)
    rendered_filename = f"rendered_{request_token}_clip_{req.clip_index + 1}.mp4"
    rendered_path = os.path.join(output_dir, rendered_filename)

    def run_render_pipeline():
        render_keep_segments(
            source_input_path,
            keep_segments,
            temp_clip_path,
            ffmpeg_preset=os.environ.get("OVERLAY_FFMPEG_PRESET", "veryfast").strip() or "veryfast",
            crf="18",
            audio_bitrate="192k",
            thread_args=ffmpeg_thread_args(),
            subprocess_kwargs=subprocess_priority_kwargs(),
        )
        from main import process_video_to_vertical
        return process_video_to_vertical(temp_clip_path, rendered_path, interview_mode=bool(interview_mode))

    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, run_render_pipeline)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_clip_path):
            os.remove(temp_clip_path)

    if not success or not os.path.exists(rendered_path):
        raise HTTPException(status_code=500, detail="Clip render failed")

    if tight_edit_plan and tight_edit_plan.get("compacted"):
        clip_data["display_duration"] = tight_edit_plan.get("output_duration", round(source_end - source_start, 3))
        clip_data["tight_edit_preset"] = tight_edit_preset
        clip_data["tight_edit_removed_ranges"] = [
            {"start": round(range_start, 3), "end": round(range_end, 3)}
            for range_start, range_end in tight_edit_plan.get("remove_ranges", [])
        ]
    else:
        clip_data["display_duration"] = round(source_end - source_start, 3)
        clip_data.pop("tight_edit_preset", None)
        clip_data.pop("tight_edit_removed_ranges", None)

    clip_data["source_video_filename"] = os.path.basename(source_input_path)
    clip_data["preview_video_filename"] = os.path.basename(source_input_path)
    clip_data["preview_start"] = round(source_start, 3)
    clip_data["preview_end"] = round(source_end, 3)
    if subtitle_settings:
        clip_data["subtitle_settings"] = subtitle_settings
    if hook_settings:
        clip_data["hook_settings"] = hook_settings

    if transcript and len(keep_segments) == 1:
        active_transcript_source = "original"
        active_transcript_start = round(keep_segments[0][0], 3)
        active_transcript_end = round(keep_segments[0][1], 3)
    else:
        active_transcript_source = "audio"
        active_transcript_start = None
        active_transcript_end = None

    _append_clip_version(
        req.job_id,
        output_dir,
        clip_data,
        output_filename=rendered_filename,
        operation="render",
        label="Rendered",
        transcript_source=active_transcript_source,
        transcript_start=active_transcript_start,
        transcript_end=active_transcript_end,
        subtitle_settings=subtitle_settings if subtitle_settings else _METADATA_UNSET,
        hook_settings=hook_settings if hook_settings else _METADATA_UNSET,
    )

    current_path = rendered_path
    current_filename = rendered_filename

    if apply_subtitles:
        subtitle_filename = f"subtitled_{int(time.time() * 1000)}_{current_filename}"
        subtitle_path = os.path.join(output_dir, subtitle_filename)
        preferred_language = _resolve_subtitle_language_hint(
            metadata_data=data,
            clip_data=clip_data,
            fallback_filename=os.path.basename(current_path),
        )
        subtitle_transcript, subtitle_clip_start, subtitle_clip_end, subtitle_source_mode = _resolve_subtitle_transcript_payload(
            metadata_data=data,
            clip_data=clip_data,
            input_path=current_path,
            preferred_language=preferred_language,
            transcript_source_hint=active_transcript_source,
            transcript_start=active_transcript_start,
            transcript_end=active_transcript_end,
        )
        print(f"📝 Render subtitle transcript mode: {subtitle_source_mode}")
        if subtitle_source_mode.startswith("original"):
            active_transcript_source = "original"
        else:
            active_transcript_source = "audio"
            active_transcript_start = None
            active_transcript_end = None

        def run_subtitles():
            return burn_subtitles(
                current_path,
                subtitle_transcript,
                subtitle_clip_start,
                subtitle_clip_end,
                subtitle_path,
                alignment=subtitle_settings.get("position", "bottom"),
                y_position=subtitle_settings.get("y_position"),
                fontsize=subtitle_settings.get("font_size", 16),
                font_family=subtitle_settings.get("font_family"),
                background_style=subtitle_settings.get("background_style"),
            )

        loop = asyncio.get_event_loop()
        subtitle_success = await loop.run_in_executor(None, run_subtitles)
        if not subtitle_success:
            raise HTTPException(status_code=400, detail="No words found for this clip range.")

        _append_clip_version(
            req.job_id,
            output_dir,
            clip_data,
            output_filename=subtitle_filename,
            operation="subtitle",
            label="Subtitles",
            transcript_source=active_transcript_source,
            transcript_start=active_transcript_start,
            transcript_end=active_transcript_end,
            subtitle_settings=subtitle_settings,
        )
        current_path = subtitle_path
        current_filename = subtitle_filename

    if apply_hook:
        hook_filename = f"hook_{int(time.time() * 1000)}_{current_filename}"
        hook_path = os.path.join(output_dir, hook_filename)
        size_map = {"S": 0.8, "M": 1.0, "L": 1.3}

        def run_hook():
            return add_hook_to_video(
                current_path,
                hook_settings["text"],
                hook_path,
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

        _append_clip_version(
            req.job_id,
            output_dir,
            clip_data,
            output_filename=hook_filename,
            operation="hook",
            label="Hook",
            transcript_source=active_transcript_source,
            transcript_start=active_transcript_start,
            transcript_end=active_transcript_end,
            hook_settings=hook_settings,
        )
        current_path = hook_path
        current_filename = hook_filename

    audio_normalized = False
    social_audio_warning = ""
    if os.path.exists(current_path) and _video_has_audio(current_path):
        normalized_temp_path = os.path.join(output_dir, f"normalized_audio_{int(time.time() * 1000)}_{os.path.basename(current_path)}")
        try:
            await loop.run_in_executor(
                None,
                lambda: _normalize_social_audio_loudness(current_path, normalized_temp_path, audio_bitrate="192k"),
            )
            if os.path.exists(normalized_temp_path) and os.path.getsize(normalized_temp_path) > 0:
                os.replace(normalized_temp_path, current_path)
                audio_normalized = True
        except Exception as exc:
            social_audio_warning = f"Lautheits-Normalisierung fehlgeschlagen: {exc}"
            if os.path.exists(normalized_temp_path):
                try:
                    os.remove(normalized_temp_path)
                except Exception:
                    pass

    clip_data["status"] = "completed"
    clip_data.pop("error", None)
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    return {
        "success": True,
        "new_video_url": clip_data.get("video_url"),
        "clip": clip_data,
        "audio_normalized": audio_normalized,
        "warning": social_audio_warning,
    }


@app.post("/api/clip/render/viral-original")
async def render_clip_viral_original(request: Request, req: RenderClipRequest):
    _get_job_record_or_404(req.job_id)
    output_dir, metadata_path, data = _load_job_metadata_or_404(req.job_id)

    clips = data.get("shorts", [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]
    clip_data["clip_index"] = req.clip_index

    source_input_path = _resolve_clip_source_input_path(req.job_id, output_dir, clip_data, ensure_h264=False)
    if not source_input_path:
        raise HTTPException(status_code=404, detail="Source input video for clip not found")

    source_start = float(clip_data.get("start", clip_data.get("preview_start", 0.0)) or 0.0)
    source_end = float(clip_data.get("end", clip_data.get("preview_end", source_start)) or source_start)
    if source_end <= source_start:
        raise HTTPException(status_code=400, detail="Invalid clip timestamps")

    manifest = load_job_manifest(output_dir)
    request_meta = manifest.get("request", {})
    tight_edit_preset = _coerce_tight_edit_preset(req.tight_edit_preset or request_meta.get("tight_edit_preset"))
    apply_tight_edit = req.apply_tight_edit if req.apply_tight_edit is not None else True
    interview_mode = req.interview_mode if req.interview_mode is not None else bool(request_meta.get("interview_mode"))

    subtitle_settings = _sanitize_subtitle_settings_dict(req.subtitle_settings, clip_data)
    hook_settings = _sanitize_hook_settings_dict(req.hook_settings, clip_data)
    apply_subtitles = bool(req.apply_subtitles) and bool(subtitle_settings)
    apply_hook = bool(req.apply_hook) and bool(hook_settings)
    visual_start_zoom_factor = _clamp_zoom_factor((hook_settings or {}).get("start_zoom_factor"), DEFAULT_START_ZOOM_FACTOR)
    visual_zoom_factor = max(
        _clamp_zoom_factor((hook_settings or {}).get("zoom_factor"), DEFAULT_TARGET_ZOOM_FACTOR),
        visual_start_zoom_factor,
    )
    pattern_flash_mode = _normalize_pattern_flash_mode(
        req.pattern_flash_mode or (hook_settings or {}).get("flash_mode")
    )

    transcript = data.get("transcript")
    base_keep_segments = [(source_start, source_end)]
    tight_edit_plan = None
    if apply_tight_edit and transcript:
        tight_edit_plan = build_tight_edit_plan(transcript, source_start, source_end, tight_edit_preset)
        base_keep_segments = tight_edit_plan.get("keep_segments") or base_keep_segments

    final_keep_segments = list(base_keep_segments)
    base_output_duration = max(
        0.0,
        sum(max(0.0, float(end) - float(start)) for start, end in final_keep_segments),
    )
    final_remapped_transcript = _remap_transcript_to_keep_segments(transcript, final_keep_segments)
    ai_runtime = _resolve_ai_editor_runtime(request)
    pattern_plan = _plan_pattern_interrupts_for_clip(
        transcript=final_remapped_transcript,
        duration=base_output_duration,
        interview_mode=bool(interview_mode),
        ai_runtime=ai_runtime,
        seed_key=f"{req.job_id}:{req.clip_index}:{os.path.basename(source_input_path)}",
        start_zoom_factor=visual_start_zoom_factor,
        zoom_factor=visual_zoom_factor,
        flash_mode=pattern_flash_mode,
    )
    request_token = int(time.time() * 1000)
    temp_source_filename = f"temp_viral_source_{request_token}_{req.clip_index + 1}.mp4"
    temp_vertical_filename = f"temp_viral_vertical_{request_token}_{req.clip_index + 1}.mp4"
    viral_render_filename = f"viral_rendered_{request_token}_clip_{req.clip_index + 1}.mp4"
    temp_source_path = os.path.join(output_dir, temp_source_filename)
    temp_vertical_path = os.path.join(output_dir, temp_vertical_filename)
    viral_render_path = os.path.join(output_dir, viral_render_filename)

    def run_render_pipeline():
        render_keep_segments(
            source_input_path,
            final_keep_segments,
            temp_source_path,
            ffmpeg_preset=os.environ.get("OVERLAY_FFMPEG_PRESET", "veryfast").strip() or "veryfast",
            crf="18",
            audio_bitrate="192k",
            thread_args=ffmpeg_thread_args(),
            subprocess_kwargs=subprocess_priority_kwargs(),
        )
        from main import process_video_to_vertical
        return process_video_to_vertical(
            temp_source_path,
            temp_vertical_path,
            interview_mode=bool(interview_mode),
        )

    loop = asyncio.get_event_loop()
    try:
        render_success = await loop.run_in_executor(None, run_render_pipeline)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if os.path.exists(temp_source_path):
            os.remove(temp_source_path)

    if not render_success or not os.path.exists(temp_vertical_path):
        raise HTTPException(status_code=500, detail="Viral render failed")

    ai_visuals_applied, ai_visuals_result = await loop.run_in_executor(
        None,
        lambda: _apply_face_aware_pattern_interrupts_to_clip(
            input_path=temp_vertical_path,
            output_path=viral_render_path,
            transcript=final_remapped_transcript,
            pattern_plan=pattern_plan,
            ai_runtime=ai_runtime,
            interview_mode=bool(interview_mode),
        ),
    )

    if not ai_visuals_applied:
        if os.path.exists(viral_render_path):
            os.remove(viral_render_path)
        shutil.move(temp_vertical_path, viral_render_path)
    elif os.path.exists(temp_vertical_path):
        os.remove(temp_vertical_path)

    pexels_key = _resolve_pexels_api_key(request)
    if pexels_key and ai_runtime.get("enabled") and req.apply_stock_overlay:
        from main import describe_output_language

        language_code = "en"
        language_name = "English"
        if isinstance(final_remapped_transcript, dict):
            language_code = str(final_remapped_transcript.get("language") or "en").strip().lower()
            language_name = describe_output_language(language_code)[1]
        elif isinstance(data.get("transcript"), dict):
            language_code = str(data.get("transcript").get("language") or "en").strip().lower()
            language_name = describe_output_language(language_code)[1]

        prompt = _build_stock_overlay_prompt(
            base_output_duration,
            final_remapped_transcript,
            language_name,
            hook_text=str(clip_data.get("viral_hook_text") or "").strip() or None,
        )
        llm_payload = _call_stock_overlay_llm(ai_runtime, prompt)
        stock_overlay_plan = _sanitize_stock_overlay_plan(llm_payload, base_output_duration)
        if stock_overlay_plan:
            search_query = " ".join(stock_overlay_plan["search_keywords"][:3])
            image_info = _search_pexels_image(search_query, pexels_key)
            if image_info and image_info.get("photo_url"):
                image_path = os.path.join(output_dir, f"temp_pexels_{request_token}.jpg")
                overlay_temp_path = f"{viral_render_path}.pexels.mp4"
                try:
                    if _download_stock_image(image_info["photo_url"], image_path):
                        overlay_success = _apply_pexels_overlay_to_video(
                            viral_render_path,
                            overlay_temp_path,
                            image_path,
                            stock_overlay_plan["overlay_time"],
                            stock_overlay_plan["overlay_duration"],
                        )
                        if overlay_success and os.path.exists(overlay_temp_path):
                            os.remove(viral_render_path)
                            shutil.move(overlay_temp_path, viral_render_path)
                            clip_data["stock_overlay"] = {
                                "search_keywords": stock_overlay_plan["search_keywords"],
                                "overlay_time": stock_overlay_plan["overlay_time"],
                                "overlay_duration": stock_overlay_plan["overlay_duration"],
                                "photo_url": image_info.get("photo_url"),
                                "photographer": image_info.get("photographer"),
                            }
                finally:
                    if os.path.exists(image_path):
                        os.remove(image_path)

    current_path = viral_render_path
    current_filename = viral_render_filename

    try:
        rendered_duration = _probe_video_duration(current_path)
    except Exception:
        rendered_duration = base_output_duration or max(0.15, source_end - source_start)
    rendered_duration = max(0.15, rendered_duration)

    if tight_edit_plan and tight_edit_plan.get("compacted"):
        clip_data["display_duration"] = round(rendered_duration, 3)
        clip_data["tight_edit_preset"] = tight_edit_preset
        clip_data["tight_edit_removed_ranges"] = [
            {"start": round(range_start, 3), "end": round(range_end, 3)}
            for range_start, range_end in tight_edit_plan.get("remove_ranges", [])
        ]
    else:
        clip_data["display_duration"] = round(rendered_duration, 3)
        clip_data.pop("tight_edit_preset", None)
        clip_data.pop("tight_edit_removed_ranges", None)

    clip_data["source_video_filename"] = os.path.basename(source_input_path)
    clip_data["preview_video_filename"] = os.path.basename(source_input_path)
    clip_data["preview_start"] = round(source_start, 3)
    clip_data["preview_end"] = round(source_end, 3)
    if subtitle_settings:
        clip_data["subtitle_settings"] = subtitle_settings
    if hook_settings:
        clip_data["hook_settings"] = hook_settings

    _append_clip_version(
        req.job_id,
        output_dir,
        clip_data,
        output_filename=viral_render_filename,
        operation="viral_render",
        label="Viral Render",
        transcript_source="audio",
        transcript_start=None,
        transcript_end=None,
        subtitle_settings=subtitle_settings if subtitle_settings else _METADATA_UNSET,
        hook_settings=hook_settings if hook_settings else _METADATA_UNSET,
    )

    subtitle_transcript_for_render = final_remapped_transcript
    subtitle_clip_start = 0.0
    subtitle_clip_end = rendered_duration

    if apply_subtitles:
        preferred_language = _resolve_subtitle_language_hint(
            metadata_data=data,
            clip_data=clip_data,
            fallback_filename=os.path.basename(current_path),
        )
        if not _transcript_has_word_timestamps(subtitle_transcript_for_render):
            subtitle_transcript_for_render = transcribe_audio(
                current_path,
                preferred_language=preferred_language or None,
            )
            subtitle_clip_end = _probe_video_duration(current_path)

        subtitle_filename = f"subtitled_{int(time.time() * 1000)}_{current_filename}"
        subtitle_path = os.path.join(output_dir, subtitle_filename)

        def run_subtitles():
            return burn_subtitles(
                current_path,
                subtitle_transcript_for_render,
                subtitle_clip_start,
                subtitle_clip_end,
                subtitle_path,
                alignment=subtitle_settings.get("position", "bottom"),
                y_position=subtitle_settings.get("y_position"),
                fontsize=subtitle_settings.get("font_size", 16),
                font_family=subtitle_settings.get("font_family"),
                background_style=subtitle_settings.get("background_style"),
            )

        subtitle_success = await loop.run_in_executor(None, run_subtitles)
        if not subtitle_success:
            raise HTTPException(status_code=400, detail="No words found for this clip range.")

        _append_clip_version(
            req.job_id,
            output_dir,
            clip_data,
            output_filename=subtitle_filename,
            operation="subtitle",
            label="Subtitles",
            transcript_source="audio",
            transcript_start=None,
            transcript_end=None,
            subtitle_settings=subtitle_settings,
        )
        current_path = subtitle_path
        current_filename = subtitle_filename

    if apply_hook:
        hook_filename = f"hook_{int(time.time() * 1000)}_{current_filename}"
        hook_path = os.path.join(output_dir, hook_filename)
        size_map = {"S": 0.8, "M": 1.0, "L": 1.3}

        def run_hook():
            return add_hook_to_video(
                current_path,
                hook_settings["text"],
                hook_path,
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

        await loop.run_in_executor(None, run_hook)
        _append_clip_version(
            req.job_id,
            output_dir,
            clip_data,
            output_filename=hook_filename,
            operation="hook",
            label="Hook",
            transcript_source="audio",
            transcript_start=None,
            transcript_end=None,
            hook_settings=hook_settings,
        )
        current_path = hook_path
        current_filename = hook_filename

    audio_normalized = False
    social_audio_warning = ""
    if os.path.exists(current_path) and _video_has_audio(current_path):
        normalized_temp_path = os.path.join(output_dir, f"normalized_audio_{int(time.time() * 1000)}_{os.path.basename(current_path)}")
        try:
            await loop.run_in_executor(
                None,
                lambda: _normalize_social_audio_loudness(current_path, normalized_temp_path, audio_bitrate="192k"),
            )
            if os.path.exists(normalized_temp_path) and os.path.getsize(normalized_temp_path) > 0:
                os.replace(normalized_temp_path, current_path)
                audio_normalized = True
        except Exception as exc:
            social_audio_warning = f"Lautheits-Normalisierung fehlgeschlagen: {exc}"
            if os.path.exists(normalized_temp_path):
                try:
                    os.remove(normalized_temp_path)
                except Exception:
                    pass

    clip_data["status"] = "completed"
    clip_data.pop("error", None)
    data["shorts"][req.clip_index] = clip_data
    _write_metadata(metadata_path, data)
    _refresh_job_result(req.job_id)

    response_payload = {
        "success": True,
        "new_video_url": clip_data.get("video_url"),
        "clip": clip_data,
        "pattern_plan": pattern_plan,
        "ai_visuals": ai_visuals_result,
        "audio_normalized": audio_normalized,
    }
    warning_parts = [part for part in [ai_visuals_result.get("warning"), social_audio_warning] if part]
    if warning_parts:
        response_payload["warning"] = " | ".join(warning_parts)
    return response_payload

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
    first_comment: Optional[str] = None
    scheduled_date: Optional[str] = None # ISO-8601 string
    timezone: Optional[str] = "UTC"
    instagram_share_mode: Optional[str] = "CUSTOM"
    instagram_collaborators: Optional[str] = None
    tiktok_post_mode: Optional[str] = "DIRECT_POST"
    tiktok_is_aigc: Optional[bool] = False
    facebook_page_id: Optional[str] = None
    pinterest_board_id: Optional[str] = None
    podcast_dm_relay_url: Optional[str] = None
    podcast_dm_relay_password: Optional[str] = None
    request_id: Optional[str] = None


class SocialPostRetryRequest(BaseModel):
    job_id: str
    clip_index: int
    api_key: str
    user_id: str
    platform: str
    retry_mode: Optional[str] = "now"
    podcast_dm_relay_url: Optional[str] = None
    podcast_dm_relay_password: Optional[str] = None


class SocialSyncRequest(BaseModel):
    api_key: str


class SocialCalendarRequest(BaseModel):
    api_key: str
    sync: Optional[bool] = True
    limit_jobs: Optional[int] = 0
    user_id: Optional[str] = None


class SocialCalendarPodcastCaptionPatchRequest(BaseModel):
    api_key: str
    user_id: str
    execute: Optional[bool] = False
    job_ids: Optional[List[str]] = None
    podcast_dm_relay_url: Optional[str] = None
    podcast_dm_relay_password: Optional[str] = None


class SocialCalendarEventUpdateRequest(BaseModel):
    api_key: str
    user_id: Optional[str] = None
    job_id: Optional[str] = None
    clip_index: Optional[int] = None
    vendor_job_id: Optional[str] = None
    event_source: Optional[str] = None
    history_entry_id: Optional[str] = None
    scheduled_date: str
    timezone: Optional[str] = "UTC"
    title: Optional[str] = None
    description: Optional[str] = None
    first_comment: Optional[str] = None
    platforms: Optional[List[str]] = None
    instagram_share_mode: Optional[str] = None
    instagram_collaborators: Optional[str] = None
    tiktok_post_mode: Optional[str] = None
    tiktok_is_aigc: Optional[bool] = None
    facebook_page_id: Optional[str] = None
    pinterest_board_id: Optional[str] = None
    mode: Optional[str] = "auto"
    podcast_dm_relay_url: Optional[str] = None
    podcast_dm_relay_password: Optional[str] = None


class SocialCalendarEventDeleteRequest(BaseModel):
    api_key: str
    job_id: Optional[str] = None
    clip_index: Optional[int] = None
    vendor_job_id: Optional[str] = None
    event_source: Optional[str] = None
    history_entry_id: Optional[str] = None


class SocialCalendarEventPreviewRequest(BaseModel):
    api_key: str
    vendor_job_id: str
    user_id: Optional[str] = None


class SocialCalendarBulkRescheduleRequest(BaseModel):
    api_key: str
    user_id: str
    sync: Optional[bool] = False
    future_only: Optional[bool] = True
    podcast_dm_relay_url: Optional[str] = None
    podcast_dm_relay_password: Optional[str] = None

import httpx

UPLOAD_POST_AUTH_SCHEMES = ("ApiKey", "Apikey")
SOCIAL_PLATFORM_CANONICAL = {
    "yt": "youtube",
    "youtube": "youtube",
    "tt": "tiktok",
    "tik_tok": "tiktok",
    "tiktok": "tiktok",
    "ig": "instagram",
    "insta": "instagram",
    "instagram": "instagram",
    "fb": "facebook",
    "meta": "facebook",
    "facebook": "facebook",
    "twitter": "x",
    "x": "x",
    "thread": "threads",
    "threads": "threads",
    "pin": "pinterest",
    "pinterest": "pinterest",
}
UPLOAD_POST_STATUS_URL = "https://api.upload-post.com/api/uploadposts/status"
UPLOAD_POST_SCHEDULE_URL = "https://api.upload-post.com/api/uploadposts/schedule"
UPLOAD_POST_QUEUE_PREVIEW_URL = "https://api.upload-post.com/api/uploadposts/queue/preview"
UPLOAD_POST_CALENDAR_HORIZON_DAYS = 366
PODCAST_DM_RELAY_TIMEOUT_SECONDS = 20.0
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
PODCAST_DM_SUPPORTED_PLATFORMS = {"instagram"}


def _resolve_job_podcast_campaign(metadata_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    job_social_defaults = metadata_data.get("job_social_defaults") if isinstance(metadata_data, dict) else {}
    return _normalize_podcast_link_campaign((job_social_defaults or {}).get("podcast_link_campaign"))


def _normalize_podcast_relay_url(value: Any) -> str:
    raw = _normalize_unicode_text(value).strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


def _build_podcast_relay_posts(status_payload: Dict[str, Any], requested_platforms: List[str]) -> List[Dict[str, Any]]:
    platform_results = _normalize_social_post_platform_results(status_payload.get("platform_results") or [])
    by_platform = {item.get("platform"): item for item in platform_results if item.get("platform")}
    posts: List[Dict[str, Any]] = []
    for platform in _normalize_social_platforms(requested_platforms):
        if platform not in PODCAST_DM_SUPPORTED_PLATFORMS:
            continue
        item = by_platform.get(platform) or {"platform": platform}
        post_id = (
            item.get("post_id")
            or item.get("platform_post_id")
            or item.get("publish_id")
            or item.get("container_id")
            or ""
        )
        post_url = item.get("url") or item.get("link") or item.get("permalink") or ""
        posts.append({
            "platform": platform,
            "post_id": str(post_id or "").strip(),
            "post_url": str(post_url or "").strip(),
            "status": item.get("status") or status_payload.get("status") or "",
            "success": item.get("success"),
            "message": item.get("message") or item.get("error") or "",
        })
    return posts


async def _notify_podcast_dm_relay(
    *,
    relay_url: Any,
    relay_password: Any,
    profile_username: str,
    campaign: Dict[str, Any],
    status_payload: Dict[str, Any],
    requested_platforms: List[str],
    job_id: Optional[str] = None,
    clip_index: Optional[int] = None,
    clip_title: Optional[str] = None,
    replaces_vendor_job_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    normalized_relay_url = _normalize_podcast_relay_url(relay_url)
    password = _normalize_unicode_text(relay_password).strip()
    normalized_campaign = _normalize_podcast_link_campaign(campaign)
    supported_platforms = [
        platform
        for platform in _normalize_social_platforms(requested_platforms)
        if platform in PODCAST_DM_SUPPORTED_PLATFORMS
    ]
    if not normalized_relay_url or not password or not normalized_campaign.get("enabled") or not supported_platforms:
        return None

    request_settings = status_payload.get("request_settings") if isinstance(status_payload, dict) else {}
    if not isinstance(request_settings, dict):
        request_settings = {}
    instagram_delivery = status_payload.get("instagram_caption_delivery") if isinstance(status_payload, dict) else {}
    if not isinstance(instagram_delivery, dict):
        instagram_delivery = {}
    own_first_comment = _normalize_unicode_text(
        request_settings.get("instagram_first_comment")
        or instagram_delivery.get("first_comment")
        or ""
    ).strip()

    payload = {
        "action": "register",
        "password": password,
        "profile_username": profile_username,
        "link_url": normalized_campaign.get("link_url"),
        "link_id": normalized_campaign.get("link_id"),
        "youtube_url": normalized_campaign.get("youtube_url"),
        "youtube_id": normalized_campaign.get("youtube_id"),
        "keyword": normalized_campaign.get("keyword") or "Video",
        "comment_template": normalized_campaign.get("comment_template") or DEFAULT_PODCAST_COMMENT_TEMPLATE,
        "own_first_comment": own_first_comment,
        "dm_message": f"Hey du, danke für deinen Kommentar! Hier ist dein Link, einfach hier klicken: {normalized_campaign.get('link_url')} Viel Freude!",
        "public_replies": [
            "Ist raus, check deine Nachrichtenanfragen :)",
            "Habs dir gesendet, schau mal in deine DM-Anfragen",
            "Kommt direkt zu dir, schau kurz in deine Nachrichtenanfragen.",
            "Hab dir den Link geschickt :)",
        ],
        "openshorts_job_id": job_id,
        "clip_index": clip_index,
        "clip_title": clip_title or "",
        "vendor_job_id": status_payload.get("job_id"),
        "replaces_vendor_job_id": str(replaces_vendor_job_id or "").strip() or None,
        "request_id": status_payload.get("request_id"),
        "scheduled": bool(status_payload.get("scheduled")),
        "scheduled_date": ((status_payload.get("request_settings") or {}).get("scheduled_date") or ""),
        "posts": _build_podcast_relay_posts(status_payload, supported_platforms),
    }
    separator = "&" if "?" in normalized_relay_url else "?"
    url = f"{normalized_relay_url}{separator}action=register"
    max_attempts = 3
    last_error: Dict[str, Any] = {"success": False, "message": "Relay request failed."}
    async with httpx.AsyncClient(timeout=PODCAST_DM_RELAY_TIMEOUT_SECONDS) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(url, json=payload)
                response_text = response.text[:2000]
                retryable_status = response.status_code in {408, 425, 429} or response.status_code >= 500
                if response.status_code >= 400:
                    last_error = {
                        "success": False,
                        "status_code": response.status_code,
                        "message": response_text or f"Relay returned HTTP {response.status_code}.",
                        "attempts": attempt,
                    }
                    if retryable_status and attempt < max_attempts:
                        await asyncio.sleep(0.75 * attempt)
                        continue
                    return last_error
                try:
                    response_payload = response.json()
                except Exception:
                    response_payload = {"success": True, "message": response_text}
                if not isinstance(response_payload, dict):
                    response_payload = {"success": True, "message": response_text}
                response_payload.setdefault("success", True)
                response_payload["status_code"] = response.status_code
                response_payload["attempts"] = attempt
                return response_payload
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = {
                    "success": False,
                    "message": str(exc).strip() or repr(exc),
                    "error_type": type(exc).__name__,
                    "attempts": attempt,
                }
                if attempt < max_attempts:
                    await asyncio.sleep(0.75 * attempt)
                    continue
                return last_error
            except Exception as exc:
                return {
                    "success": False,
                    "message": str(exc).strip() or repr(exc),
                    "error_type": type(exc).__name__,
                    "attempts": attempt,
                }
    return last_error


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


def _normalize_upload_post_platform_name(value: Optional[str]) -> str:
    return SOCIAL_PLATFORM_CANONICAL.get((value or "").strip().lower(), (value or "").strip().lower())


def _normalize_upload_post_platform_result(platform: str, payload: Any) -> Dict[str, Any]:
    normalized_platform = _normalize_upload_post_platform_name(platform)
    if isinstance(payload, dict):
        success = payload.get("success")
        error_message = payload.get("error")
        status = payload.get("status")
        message = payload.get("message") or status or error_message
        if success is None and error_message:
            success = False
        result = {
            "platform": normalized_platform,
            "success": success,
            "status": status or ("failed" if success is False else None),
            "message": message or "",
            "error": error_message,
        }
        for key in ("publish_id", "post_id", "container_id", "url", "link", "upload_timestamp"):
            if payload.get(key) not in (None, ""):
                result[key] = payload.get(key)
        return result

    return {
        "platform": normalized_platform,
        "success": None,
        "status": None,
        "message": str(payload or ""),
        "error": None,
    }


def _extract_upload_post_platform_results(payload: Dict[str, Any], requested_platforms: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    requested_platforms = [_normalize_upload_post_platform_name(item) for item in (requested_platforms or [])]
    raw_results = payload.get("results")
    normalized_results: List[Dict[str, Any]] = []
    seen = set()

    if isinstance(raw_results, dict):
        for platform, item in raw_results.items():
            normalized = _normalize_upload_post_platform_result(platform, item)
            normalized_results.append(normalized)
            seen.add(normalized["platform"])
    elif isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            platform = _normalize_upload_post_platform_name(item.get("platform"))
            normalized = {
                "platform": platform,
                "success": item.get("success"),
                "status": item.get("status"),
                "message": item.get("message") or item.get("status") or item.get("error") or "",
                "error": item.get("error"),
            }
            for key in ("publish_id", "post_id", "container_id", "url", "link", "upload_timestamp"):
                if item.get(key) not in (None, ""):
                    normalized[key] = item.get(key)
            normalized_results.append(normalized)
            seen.add(platform)

    for platform in requested_platforms:
        if platform in seen:
            continue
        normalized_results.append({
            "platform": platform,
            "success": None,
            "status": "pending",
            "message": "Noch keine Rueckmeldung von Upload-Post.",
            "error": None,
        })

    return normalized_results


def _build_upload_post_summary(
    *,
    requested_platforms: List[str],
    platform_results: List[Dict[str, Any]],
    status: str,
    is_scheduled: bool,
) -> str:
    success_count = sum(1 for item in platform_results if item.get("success") is True)
    failure_count = sum(1 for item in platform_results if item.get("success") is False)
    pending_count = max(0, len(requested_platforms) - success_count - failure_count)

    if status in {"pending", "in_progress", "queued", "scheduled", "upcoming"}:
        action = "Scheduling" if is_scheduled else "Publishing"
        return f"{action} started. {success_count} done, {failure_count} failed, {pending_count} pending."
    if failure_count and success_count:
        return f"Partial success. {success_count} succeeded, {failure_count} failed."
    if failure_count and not success_count:
        return f"Upload failed on {failure_count} platform{'s' if failure_count != 1 else ''}."
    if success_count:
        return f"Upload completed on {success_count} platform{'s' if success_count != 1 else ''}."
    return "Upload accepted by vendor."


def _normalize_upload_post_response(
    payload: Dict[str, Any],
    *,
    requested_platforms: List[str],
    is_scheduled: bool,
) -> Dict[str, Any]:
    requested_platforms = [_normalize_upload_post_platform_name(item) for item in requested_platforms]
    platform_results = _extract_upload_post_platform_results(payload, requested_platforms)
    status = (
        payload.get("status")
        or ("pending" if payload.get("request_id") or payload.get("job_id") else "completed")
    )
    success_count = sum(1 for item in platform_results if item.get("success") is True)
    failure_count = sum(1 for item in platform_results if item.get("success") is False)
    pending_count = sum(1 for item in platform_results if item.get("success") not in (True, False))
    message = payload.get("message") or _build_upload_post_summary(
        requested_platforms=requested_platforms,
        platform_results=platform_results,
        status=status,
        is_scheduled=is_scheduled,
    )

    return {
        "success": bool(payload.get("success", True)),
        "status": status,
        "message": message,
        "scheduled": is_scheduled,
        "request_id": payload.get("request_id"),
        "job_id": payload.get("job_id"),
        "requested_platforms": requested_platforms,
        "platform_results": platform_results,
        "success_count": success_count,
        "failure_count": failure_count,
        "pending_count": pending_count,
        "completed": payload.get("completed"),
        "total": payload.get("total") or len(requested_platforms),
        "last_update": payload.get("last_update"),
        "usage": payload.get("usage"),
        "raw": payload,
    }


def _build_social_post_request_settings(
    *,
    final_title: str,
    final_description: str,
    first_comment: str,
    scheduled_date: Optional[str],
    timezone: Optional[str],
    instagram_share_mode: Optional[str],
    instagram_collaborators: Optional[str],
    tiktok_post_mode: Optional[str],
    tiktok_is_aigc: Optional[bool],
    facebook_page_id: Optional[str],
    pinterest_board_id: Optional[str],
    transcript_language: Optional[str],
    podcast_link_campaign: Optional[Dict[str, Any]] = None,
    instagram_caption: Optional[str] = None,
    instagram_first_comment: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "title": final_title,
        "description": final_description,
        "first_comment": first_comment,
        "scheduled_date": scheduled_date,
        "timezone": timezone or "UTC",
        "instagram_share_mode": instagram_share_mode or "CUSTOM",
        "instagram_collaborators": _normalize_instagram_collaborators(instagram_collaborators or "") or None,
        "tiktok_post_mode": tiktok_post_mode or "DIRECT_POST",
        "tiktok_is_aigc": bool(tiktok_is_aigc),
        "facebook_page_id": (facebook_page_id or "").strip() or None,
        "pinterest_board_id": (pinterest_board_id or "").strip() or None,
        "transcript_language": transcript_language,
    }
    normalized_campaign = _normalize_podcast_link_campaign(podcast_link_campaign)
    if normalized_campaign.get("link_url"):
        payload["podcast_link_campaign"] = normalized_campaign
    if instagram_caption is not None:
        payload["instagram_caption"] = _normalize_unicode_text(instagram_caption).strip()
    if instagram_first_comment is not None:
        payload["instagram_first_comment"] = _normalize_unicode_text(instagram_first_comment).strip()
    return payload


def _normalize_social_post_request_settings(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return _build_social_post_request_settings(
        final_title=(value.get("title") or "").strip(),
        final_description=(value.get("description") or "").strip(),
        first_comment=(value.get("first_comment") or "").strip(),
        scheduled_date=(value.get("scheduled_date") or "").strip() or None,
        timezone=(value.get("timezone") or "UTC").strip() or "UTC",
        instagram_share_mode=(value.get("instagram_share_mode") or "CUSTOM").strip() or "CUSTOM",
        instagram_collaborators=(value.get("instagram_collaborators") or "").strip() or None,
        tiktok_post_mode=(value.get("tiktok_post_mode") or "DIRECT_POST").strip() or "DIRECT_POST",
        tiktok_is_aigc=bool(value.get("tiktok_is_aigc")),
        facebook_page_id=(value.get("facebook_page_id") or "").strip() or None,
        pinterest_board_id=(value.get("pinterest_board_id") or "").strip() or None,
        transcript_language=(value.get("transcript_language") or "").strip() or None,
        podcast_link_campaign=value.get("podcast_link_campaign") if isinstance(value.get("podcast_link_campaign"), dict) else None,
        instagram_caption=(value.get("instagram_caption") or "").strip() if value.get("instagram_caption") is not None else None,
        instagram_first_comment=(value.get("instagram_first_comment") or "").strip() if value.get("instagram_first_comment") is not None else None,
    )


def _normalize_social_post_platform_results(items: Any) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        platform = _normalize_upload_post_platform_name(item.get("platform"))
        if not platform or platform in seen:
            continue
        normalized = dict(item)
        normalized["platform"] = platform
        results.append(normalized)
        seen.add(platform)
    return results


def _resolve_social_post_overall_status(
    *,
    fallback_status: Optional[str],
    success_count: int,
    failure_count: int,
    pending_count: int,
    is_future_scheduled: bool,
) -> str:
    normalized = (fallback_status or "").strip().lower()
    if is_future_scheduled and success_count <= 0:
        return "upcoming"
    if pending_count > 0:
        if normalized in {"pending", "in_progress", "queued", "scheduled"}:
            return normalized
        return "pending"
    if failure_count and success_count:
        return "partial"
    if failure_count:
        return "failed"
    if success_count:
        return "completed"
    return normalized or "completed"


def _finalize_social_post_status_payload(
    status_payload: Dict[str, Any],
    *,
    requested_platforms: Optional[List[str]] = None,
    platform_results: Optional[List[Dict[str, Any]]] = None,
    request_settings: Optional[Dict[str, Any]] = None,
    tracking_platforms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload = dict(status_payload or {})
    normalized_requested_platforms = _normalize_social_platforms(
        requested_platforms
        if requested_platforms is not None
        else payload.get("requested_platforms") or []
    )
    normalized_results = _normalize_social_post_platform_results(
        platform_results if platform_results is not None else payload.get("platform_results")
    )

    ordered_results: List[Dict[str, Any]] = []
    seen = set()
    by_platform = {item["platform"]: item for item in normalized_results}
    for platform in normalized_requested_platforms:
        if platform in by_platform:
            ordered_results.append(by_platform[platform])
            seen.add(platform)
    for item in normalized_results:
        platform = item["platform"]
        if platform in seen:
            continue
        ordered_results.append(item)
        seen.add(platform)
        if platform not in normalized_requested_platforms:
            normalized_requested_platforms.append(platform)

    success_count = sum(1 for item in ordered_results if item.get("success") is True)
    failure_count = sum(1 for item in ordered_results if item.get("success") is False)
    pending_count = sum(1 for item in ordered_results if item.get("success") not in (True, False))
    if pending_count > 0 or success_count > 0:
        overall_success = True
    elif failure_count > 0:
        overall_success = False
    else:
        overall_success = bool(payload.get("success", True))
    normalized_request_settings = (
        _normalize_social_post_request_settings(request_settings)
        if request_settings is not None
        else _normalize_social_post_request_settings(payload.get("request_settings"))
    )
    is_scheduled = bool(payload.get("scheduled"))
    scheduled_date = (
        (normalized_request_settings or {}).get("scheduled_date")
        or payload.get("scheduled_date")
    )
    overall_status = _resolve_social_post_overall_status(
        fallback_status=payload.get("status"),
        success_count=success_count,
        failure_count=failure_count,
        pending_count=pending_count,
        is_future_scheduled=bool(is_scheduled and _is_future_scheduled_datetime(scheduled_date)),
    )
    normalized_tracking_platforms = _normalize_social_platforms(
        tracking_platforms
        if tracking_platforms is not None
        else payload.get("tracking_platforms") or []
    )
    if pending_count <= 0:
        normalized_tracking_platforms = []
    elif not normalized_tracking_platforms:
        normalized_tracking_platforms = list(normalized_requested_platforms)

    payload.update({
        "success": overall_success,
        "status": overall_status,
        "message": _build_upload_post_summary(
            requested_platforms=normalized_requested_platforms,
            platform_results=ordered_results,
            status=overall_status,
            is_scheduled=is_scheduled,
        ),
        "scheduled": is_scheduled,
        "requested_platforms": normalized_requested_platforms,
        "platform_results": ordered_results,
        "success_count": success_count,
        "failure_count": failure_count,
        "pending_count": pending_count,
        "total": payload.get("total") or len(normalized_requested_platforms),
        "tracking_platforms": normalized_tracking_platforms,
    })
    if normalized_request_settings is not None:
        payload["request_settings"] = normalized_request_settings
    return payload


def _merge_social_post_status(
    existing_status: Any,
    incoming_status: Dict[str, Any],
    *,
    updated_platforms: Optional[List[str]] = None,
    request_settings: Optional[Dict[str, Any]] = None,
    tracking_platforms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    existing_payload = dict(existing_status or {})
    incoming_payload = dict(incoming_status or {})

    requested_platforms = _normalize_social_platforms(existing_payload.get("requested_platforms") or [])
    for platform in _normalize_social_platforms(incoming_payload.get("requested_platforms") or []):
        if platform not in requested_platforms:
            requested_platforms.append(platform)

    existing_results = _normalize_social_post_platform_results(existing_payload.get("platform_results"))
    incoming_results = _normalize_social_post_platform_results(incoming_payload.get("platform_results"))
    merged_by_platform = {item["platform"]: dict(item) for item in existing_results}
    incoming_by_platform = {item["platform"]: dict(item) for item in incoming_results}
    platforms_to_update = _normalize_social_platforms(
        updated_platforms
        if updated_platforms is not None
        else incoming_payload.get("requested_platforms") or list(incoming_by_platform.keys())
    )

    for platform in platforms_to_update:
        if platform in incoming_by_platform:
            merged_by_platform[platform] = incoming_by_platform[platform]
        elif platform not in merged_by_platform:
            merged_by_platform[platform] = {
                "platform": platform,
                "success": None,
                "status": "pending",
                "message": "Warte auf Rueckmeldung von Upload-Post.",
                "error": None,
            }

    for platform, item in incoming_by_platform.items():
        if platform not in merged_by_platform:
            merged_by_platform[platform] = item
        if platform not in requested_platforms:
            requested_platforms.append(platform)

    merged_results = [merged_by_platform[platform] for platform in requested_platforms if platform in merged_by_platform]
    merged_payload = dict(existing_payload)
    merged_payload.update(incoming_payload)

    merged_request_settings = (
        _normalize_social_post_request_settings(request_settings)
        if request_settings is not None
        else _normalize_social_post_request_settings(incoming_payload.get("request_settings"))
        or _normalize_social_post_request_settings(existing_payload.get("request_settings"))
    )
    merged_tracking_platforms = (
        tracking_platforms
        if tracking_platforms is not None
        else incoming_payload.get("tracking_platforms")
        if incoming_payload.get("tracking_platforms") is not None
        else existing_payload.get("tracking_platforms")
    )
    return _finalize_social_post_status_payload(
        merged_payload,
        requested_platforms=requested_platforms,
        platform_results=merged_results,
        request_settings=merged_request_settings,
        tracking_platforms=merged_tracking_platforms,
    )


def _parse_social_platforms_form_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_platforms = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        raw_platforms: List[str]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                raw_platforms = [str(item) for item in parsed]
            elif isinstance(parsed, str):
                raw_platforms = [parsed]
            else:
                raw_platforms = [item.strip() for item in text.split(",") if item.strip()]
        except json.JSONDecodeError:
            raw_platforms = [item.strip() for item in text.split(",") if item.strip()]
    else:
        raw_platforms = [str(value)]
    return _normalize_social_platforms(raw_platforms)


def _build_upload_post_data_payload(
    *,
    user_id: str,
    requested_platforms: List[str],
    final_title: str,
    final_description: str,
    first_comment: str = "",
    scheduled_date: Optional[str] = None,
    timezone: Optional[str] = "UTC",
    instagram_share_mode: Optional[str] = "CUSTOM",
    instagram_collaborators: Optional[str] = None,
    tiktok_post_mode: Optional[str] = "DIRECT_POST",
    tiktok_is_aigc: Optional[bool] = False,
    facebook_page_id: Optional[str] = None,
    pinterest_board_id: Optional[str] = None,
    transcript_language: Optional[str] = None,
    instagram_caption: Optional[str] = None,
    instagram_first_comment: Optional[str] = None,
) -> Dict[str, Any]:
    requested_platform_set = set(requested_platforms)
    data_payload: Dict[str, Any] = {
        "user": user_id,
        "title": final_title,
        "platform[]": requested_platforms,
        "async_upload": "true",
    }
    if first_comment:
        data_payload["first_comment"] = first_comment
    if scheduled_date:
        data_payload["scheduled_date"] = scheduled_date
        if timezone:
            data_payload["timezone"] = timezone

    if "tiktok" in requested_platform_set:
        data_payload["tiktok_title"] = final_description
        data_payload["post_mode"] = tiktok_post_mode or "DIRECT_POST"
        data_payload["is_aigc"] = "true" if tiktok_is_aigc else "false"

    if "instagram" in requested_platform_set:
        data_payload["instagram_title"] = (instagram_caption if instagram_caption is not None else final_description)
        data_payload["media_type"] = "REELS"
        data_payload["share_mode"] = instagram_share_mode or "CUSTOM"
        normalized_collaborators = _normalize_instagram_collaborators(instagram_collaborators or "")
        if normalized_collaborators and (instagram_share_mode or "CUSTOM") == "CUSTOM":
            data_payload["collaborators"] = normalized_collaborators
        effective_instagram_first_comment = (instagram_first_comment or first_comment or "").strip()
        if effective_instagram_first_comment:
            data_payload["instagram_first_comment"] = effective_instagram_first_comment

    if "youtube" in requested_platform_set:
        data_payload["youtube_title"] = final_title
        data_payload["youtube_description"] = final_description
        data_payload["privacyStatus"] = "public"
        data_payload.update(_resolve_upload_post_language_fields(transcript_language))
        if first_comment:
            data_payload["youtube_first_comment"] = first_comment

    if "facebook" in requested_platform_set:
        data_payload["facebook_title"] = final_title
        data_payload["facebook_description"] = final_description
        data_payload["facebook_media_type"] = "REELS"
        if facebook_page_id:
            data_payload["facebook_page_id"] = facebook_page_id
        if first_comment:
            data_payload["facebook_first_comment"] = first_comment

    if "x" in requested_platform_set:
        data_payload["x_title"] = final_description
        if first_comment:
            data_payload["x_first_comment"] = first_comment

    if "threads" in requested_platform_set:
        data_payload["threads_title"] = final_description
        if first_comment:
            data_payload["threads_first_comment"] = first_comment

    if "pinterest" in requested_platform_set:
        data_payload["pinterest_title"] = final_title
        data_payload["pinterest_description"] = final_description
        if pinterest_board_id:
            data_payload["pinterest_board_id"] = pinterest_board_id

    return data_payload


def _upload_post_payload_platforms(data: dict) -> list[str]:
    raw_platforms = (
        data.get("platforms")
        or data.get("platform[]")
        or data.get("platform")
        or []
    )
    if isinstance(raw_platforms, str):
        raw_platforms = [raw_platforms]
    if not isinstance(raw_platforms, (list, tuple, set)):
        return []
    return [str(platform).strip().lower() for platform in raw_platforms if str(platform).strip()]


def _enforce_instagram_upload_post_cta_payload(data: dict) -> None:
    platforms = _upload_post_payload_platforms(data)
    if "instagram" not in platforms:
        return

    instagram_title = str(data.get("instagram_title") or "").strip()
    instagram_first_comment = str(data.get("instagram_first_comment") or "").strip()
    if not instagram_title and not instagram_first_comment:
        return

    if instagram_title:
        data["instagram_title"] = instagram_title
        data.setdefault("instagram_caption", instagram_title)
        data.setdefault("instagram_description", instagram_title)

    if instagram_first_comment:
        data["instagram_first_comment"] = instagram_first_comment

    # Upload-Post's schedule list exposes global title/caption. For
    # Instagram-only jobs, mirror the platform-specific values globally so the
    # visible schedule metadata and eventual Reel caption cannot diverge.
    if platforms == ["instagram"]:
        if instagram_title:
            data["title"] = instagram_title
            data["caption"] = instagram_title
            data["description"] = instagram_title
        if instagram_first_comment:
            data["first_comment"] = instagram_first_comment


def _send_upload_post_video(
    *,
    api_key: str,
    requested_platforms: List[str],
    data_payload: Dict[str, Any],
    video_filename: str,
    video_bytes: bytes,
    video_content_type: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    url = "https://api.upload-post.com/api/upload"
    _enforce_instagram_upload_post_cta_payload(data_payload)
    files = {
        "video": (video_filename, video_bytes, video_content_type or "application/octet-stream"),
    }
    normalized_request_id = _normalize_unicode_text(request_id or "").strip()
    if normalized_request_id:
        data_payload["request_id"] = normalized_request_id
    request_headers = ({
        "Idempotency-Key": normalized_request_id,
        "X-Request-Id": normalized_request_id,
    } if normalized_request_id else None)

    try:
        with httpx.Client(timeout=300.0) as client:
            print(f"📡 Sending to Upload-Post for platforms: {requested_platforms}")
            response = _upload_post_sync_request(
                client,
                "POST",
                url,
                api_key,
                headers=request_headers,
                data=data_payload,
                files=files,
            )
    except httpx.RequestError as exc:
        detail = _format_outbound_network_error("Upload-Post", url, exc)
        print(f"⚠️ {detail}")
        raise HTTPException(status_code=502, detail=detail)

    if response.status_code == 429:
        retry_after_seconds = 0.0
        try:
            retry_after_seconds = max(
                retry_after_seconds,
                float(str(response.headers.get("Retry-After") or "").strip()),
            )
        except (TypeError, ValueError):
            pass
        try:
            retry_after_seconds = max(
                retry_after_seconds,
                float(str(response.headers.get("X-RateLimit-Reset") or "").strip()) - time.time(),
            )
        except (TypeError, ValueError):
            pass
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Vendor API Error: {response.text}",
                "retry_after_seconds": max(1.0, min(retry_after_seconds or 60.0, 120.0)),
            },
        )
    if response.status_code not in {200, 201, 202}:
        print(f"❌ Upload-Post Error: {response.text}")
        raise HTTPException(status_code=response.status_code, detail=f"Vendor API Error: {response.text}")

    try:
        vendor_payload = response.json()
    except Exception:
        vendor_payload = {
            "success": True,
            "status": "pending",
            "message": response.text,
        }

    normalized_payload = vendor_payload if isinstance(vendor_payload, dict) else {"success": True, "results": vendor_payload}
    return _normalize_upload_post_response(
        normalized_payload,
        requested_platforms=requested_platforms,
        is_scheduled=bool(data_payload.get("scheduled_date")),
    )


def _parse_iso_datetime(value: Any) -> Optional[datetime.datetime]:
    if value in (None, ""):
        return None
    try:
        normalized = str(value).strip()
        if not normalized:
            return None
        return datetime.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_future_scheduled_datetime(value: Any) -> bool:
    parsed = _parse_iso_datetime(value)
    if not parsed:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed > datetime.datetime.now(datetime.timezone.utc)


def _social_post_history_entry_identity(value: Dict[str, Any]) -> str:
    if not isinstance(value, dict):
        return f"local:{uuid.uuid4().hex}"
    existing = (value.get("history_entry_id") or "").strip()
    if existing:
        return existing
    vendor_job_id = (value.get("job_id") or "").strip()
    if vendor_job_id:
        return f"job:{vendor_job_id}"
    request_id = (value.get("request_id") or "").strip()
    if request_id:
        return f"request:{request_id}"
    created_at = value.get("created_at") or value.get("updated_at") or time.time()
    try:
        seed = int(float(created_at) * 1000)
    except (TypeError, ValueError):
        seed = int(time.time() * 1000)
    return f"local:{seed}:{uuid.uuid4().hex[:8]}"


def _normalize_social_post_history_entry(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    normalized = _finalize_social_post_status_payload(
        value,
        requested_platforms=value.get("requested_platforms") or [],
        platform_results=value.get("platform_results") or [],
        request_settings=value.get("request_settings"),
        tracking_platforms=value.get("tracking_platforms"),
    )
    normalized["history_entry_id"] = _social_post_history_entry_identity(value)
    normalized["created_at"] = float(value.get("created_at") or value.get("updated_at") or time.time())
    normalized["updated_at"] = float(value.get("updated_at") or time.time())
    normalized["hidden"] = bool(value.get("hidden"))
    normalized["deleted"] = bool(value.get("deleted"))
    if value.get("deleted_at"):
        normalized["deleted_at"] = float(value.get("deleted_at"))
    if value.get("rescheduled_from"):
        normalized["rescheduled_from"] = str(value.get("rescheduled_from"))
    if value.get("rescheduled_to"):
        normalized["rescheduled_to"] = str(value.get("rescheduled_to"))
    if value.get("source"):
        normalized["source"] = str(value.get("source"))
    if value.get("poll_error"):
        normalized["poll_error"] = str(value.get("poll_error"))
    return normalized


def _social_post_entries_match(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if a.get("history_entry_id") and b.get("history_entry_id") and a.get("history_entry_id") == b.get("history_entry_id"):
        return True
    for key in ("job_id", "request_id"):
        left = (a.get(key) or "").strip()
        right = (b.get(key) or "").strip()
        if left and right and left == right:
            return True
    return False


def _sort_social_post_history_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(item: Dict[str, Any]) -> Tuple[float, float]:
        scheduled_dt = _parse_iso_datetime(
            ((item.get("request_settings") or {}).get("scheduled_date")) or item.get("scheduled_date")
        )
        scheduled_ts = scheduled_dt.timestamp() if scheduled_dt else 0.0
        return (
            scheduled_ts or float(item.get("created_at") or 0.0),
            float(item.get("updated_at") or item.get("created_at") or 0.0),
        )

    return sorted(entries, key=sort_key)


def _get_clip_social_post_history(clip: Dict[str, Any], *, include_current_fallback: bool = True) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for raw_item in clip.get("social_post_history") or []:
        normalized = _normalize_social_post_history_entry(raw_item)
        if not normalized:
            continue
        existing_index = next((index for index, entry in enumerate(entries) if _social_post_entries_match(entry, normalized)), None)
        if existing_index is None:
            entries.append(normalized)
        else:
            merged = dict(entries[existing_index])
            merged.update(normalized)
            merged["created_at"] = float(entries[existing_index].get("created_at") or normalized.get("created_at") or time.time())
            entries[existing_index] = merged

    current_status = clip.get("social_post_status")
    if include_current_fallback and isinstance(current_status, dict):
        normalized_current = _normalize_social_post_history_entry(current_status)
        if normalized_current and not any(_social_post_entries_match(entry, normalized_current) for entry in entries):
            entries.append(normalized_current)

    return _sort_social_post_history_entries(entries)


def _upsert_social_post_history_entry(entries: List[Dict[str, Any]], status_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = _normalize_social_post_history_entry(status_payload)
    if not normalized:
        return _sort_social_post_history_entries(entries)

    next_entries = [dict(item) for item in entries]
    for index, entry in enumerate(next_entries):
        if not _social_post_entries_match(entry, normalized):
            continue
        merged = dict(entry)
        merged.update(normalized)
        merged["created_at"] = float(entry.get("created_at") or normalized.get("created_at") or time.time())
        next_entries[index] = merged
        return _sort_social_post_history_entries(next_entries)

    next_entries.append(normalized)
    return _sort_social_post_history_entries(next_entries)


def _resolve_latest_visible_social_post_entry(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    visible_entries = [item for item in entries if not item.get("hidden") and not item.get("deleted")]
    if not visible_entries:
        return None
    return max(
        visible_entries,
        key=lambda item: (
            float(item.get("updated_at") or 0.0),
            float(item.get("created_at") or 0.0),
        ),
    )


def _strip_social_post_history_entry(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    payload = dict(entry)
    for key in ("hidden", "deleted", "deleted_at", "rescheduled_from", "rescheduled_to", "source"):
        payload.pop(key, None)
    return payload


def _persist_clip_social_post_history(
    job_id: str,
    clip_index: int,
    history_entries: List[Dict[str, Any]],
    *,
    preferred_current_entry_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    try:
        _, metadata_path, data = _load_job_metadata_or_404(job_id)
        clips = data.get("shorts", [])
        if clip_index < 0 or clip_index >= len(clips):
            return None

        clip_data = dict(clips[clip_index] or {})
        clip_data["clip_index"] = clip_index
        normalized_entries = _sort_social_post_history_entries([
            item for item in (
                _normalize_social_post_history_entry(entry) for entry in history_entries or []
            ) if item
        ])
        clip_data["social_post_history"] = normalized_entries

        current_entry = None
        if preferred_current_entry_id:
            current_entry = next(
                (item for item in normalized_entries if item.get("history_entry_id") == preferred_current_entry_id and not item.get("hidden") and not item.get("deleted")),
                None,
            )
        if current_entry is None:
            current_entry = _resolve_latest_visible_social_post_entry(normalized_entries)

        current_payload = _strip_social_post_history_entry(current_entry)
        if current_payload:
            current_payload["clip_index"] = clip_index
            current_payload["openshorts_job_id"] = job_id
            current_payload["updated_at"] = float(current_entry.get("updated_at") or time.time())
            clip_data["social_post_status"] = current_payload
        else:
            clip_data.pop("social_post_status", None)

        clips[clip_index] = clip_data
        data["shorts"] = clips
        _write_metadata(metadata_path, data)
        result = _refresh_job_result(job_id)
        if result:
            return _find_result_clip(result, clip_index)
        return clip_data
    except Exception as e:
        print(f"⚠️ Failed to persist social post history for {job_id}#{clip_index}: {e}")
        return None


def _resolve_calendar_event_status(entry: Dict[str, Any]) -> str:
    normalized_status = str(entry.get("status") or "").strip().lower()
    if entry.get("deleted"):
        return "deleted"
    request_settings = _normalize_social_post_request_settings(entry.get("request_settings")) or {}
    scheduled_date = (request_settings.get("scheduled_date") or entry.get("scheduled_date") or "").strip() or None
    pending_count = int(entry.get("pending_count") or 0)
    success_count = int(entry.get("success_count") or 0)
    failure_count = int(entry.get("failure_count") or 0)
    if scheduled_date and _is_future_scheduled_datetime(scheduled_date) and success_count <= 0:
        return "upcoming"
    if failure_count > 0 and success_count > 0:
        return "partial"
    if failure_count > 0 or normalized_status in {"failed", "error"}:
        return "failed"
    if pending_count > 0 or normalized_status in {"pending", "in_progress", "queued", "scheduled"}:
        return "scheduled"
    if success_count > 0 or normalized_status == "completed":
        return "posted"
    return normalized_status or "unknown"


def _build_social_calendar_event(job_id: str, clip_index: int, clip: Dict[str, Any], entry: Dict[str, Any], source_label: str) -> Optional[Dict[str, Any]]:
    request_settings = _normalize_social_post_request_settings(entry.get("request_settings")) or {}
    scheduled_date = (request_settings.get("scheduled_date") or "").strip() or None
    if not scheduled_date:
        return None

    platform_results = _normalize_social_post_platform_results(entry.get("platform_results"))
    platform_links = [
        {
            "platform": item.get("platform"),
            "url": item.get("url") or item.get("link"),
        }
        for item in platform_results
        if item.get("url") or item.get("link")
    ]

    clip_title = (
        clip.get("video_title_for_youtube_short")
        or clip.get("title")
        or request_settings.get("title")
        or f"Clip {clip_index + 1}"
    )
    event_status = _resolve_calendar_event_status(entry)
    media_payload = _resolve_clip_local_media_payload(job_id, clip)
    return {
        "id": f"{job_id}:{clip_index}:{entry.get('history_entry_id')}",
        "history_entry_id": entry.get("history_entry_id"),
        "event_source": "local",
        "job_id": job_id,
        "job_label": source_label,
        "clip_index": clip_index,
        "clip_label": clip_title,
        "clip_title": clip_title,
        "clip_description": request_settings.get("description") or clip.get("video_description_for_instagram") or clip.get("video_description_for_tiktok") or "",
        "local_video_url": media_payload.get("local_video_url") or "",
        "local_preview_video_url": media_payload.get("local_preview_video_url") or "",
        "remote_preview_url": "",
        "has_local_media": bool(media_payload.get("has_local_media")),
        "media_origin": media_payload.get("media_origin") or "missing_local",
        "scheduled_date": scheduled_date,
        "timezone": request_settings.get("timezone") or "UTC",
        "status": event_status,
        "status_label": entry.get("message") or event_status,
        "title": request_settings.get("title") or clip_title,
        "description": request_settings.get("description") or clip.get("video_description_for_instagram") or clip.get("video_description_for_tiktok") or "",
        "first_comment": request_settings.get("first_comment") or "",
        "requested_platforms": entry.get("requested_platforms") or [],
        "platform_results": platform_results,
        "platform_links": platform_links,
        "vendor_job_id": entry.get("job_id"),
        "request_id": entry.get("request_id"),
        "scheduled": bool(entry.get("scheduled")),
        "is_rescheduled": bool(entry.get("rescheduled_from")) or str(entry.get("source") or "").strip().lower() == "calendar_reschedule",
        "rescheduled_from": entry.get("rescheduled_from"),
        "rescheduled_to": entry.get("rescheduled_to"),
        "success_count": int(entry.get("success_count") or 0),
        "failure_count": int(entry.get("failure_count") or 0),
        "pending_count": int(entry.get("pending_count") or 0),
        "request_settings": request_settings,
        "podcast_link_campaign": request_settings.get("podcast_link_campaign") or {},
        "podcast_dm_relay": entry.get("podcast_dm_relay"),
        "instagram_schedule_caption_patch": entry.get("instagram_schedule_caption_patch"),
        "instagram_caption_delivery": entry.get("instagram_caption_delivery"),
        "updated_at": float(entry.get("updated_at") or time.time()),
        "can_recreate": bool(media_payload.get("can_recreate")),
    }


def _event_sort_timestamp(value: Any) -> float:
    parsed = _parse_iso_datetime(value)
    if not parsed:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def _build_job_social_calendar_events(job_id: str) -> List[Dict[str, Any]]:
    output_dir = _get_job_output_dir(job_id)
    result = build_job_result(output_dir, job_id) or {"clips": []}
    manifest = load_job_manifest(output_dir)
    source_label = (
        manifest.get("request", {}).get("display_name")
        or manifest.get("request", {}).get("original_filename")
        or manifest.get("request", {}).get("url")
        or job_id
    )
    events: List[Dict[str, Any]] = []
    for index, clip in enumerate(result.get("clips") or []):
        clip_index = clip.get("clip_index", index)
        for entry in _get_clip_social_post_history(clip, include_current_fallback=True):
            if entry.get("hidden") or entry.get("deleted"):
                continue
            event = _build_social_calendar_event(job_id, clip_index, clip, entry, source_label)
            if event:
                events.append(event)
    events.sort(key=lambda item: _event_sort_timestamp(item.get("scheduled_date")))
    return events


def _resolve_clip_local_media_payload(job_id: str, clip: Dict[str, Any]) -> Dict[str, Any]:
    candidate_filenames: List[str] = []
    seen: set[str] = set()

    def add_filename(value: Optional[str]) -> None:
        filename = os.path.basename(str(value or "").strip())
        if not filename or filename in seen:
            return
        seen.add(filename)
        candidate_filenames.append(filename)

    active_version = _find_clip_version(clip)
    if isinstance(active_version, dict):
        add_filename(active_version.get("filename"))
    add_filename(clip.get("preview_video_filename"))
    add_filename(clip.get("video_filename"))

    for filename in candidate_filenames:
        local_path = os.path.join(OUTPUT_DIR, job_id, filename)
        if os.path.exists(local_path):
            media_url = _clip_video_url(job_id, filename) or ""
            return {
                "has_local_media": True,
                "local_video_url": media_url,
                "local_preview_video_url": media_url,
                "media_origin": "local",
                "can_recreate": True,
            }

    return {
        "has_local_media": False,
        "local_video_url": "",
        "local_preview_video_url": "",
        "media_origin": "missing_local",
        "can_recreate": False,
    }


async def _list_upload_post_scheduled_posts(api_key: str) -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with social_calendar_sync_semaphore:
                resp = await _upload_post_async_request(client, "GET", UPLOAD_POST_SCHEDULE_URL, api_key)
    except httpx.RequestError as exc:
        detail = _format_outbound_network_error("Upload-Post", UPLOAD_POST_SCHEDULE_URL, exc)
        print(f"⚠️ {detail}")
        raise HTTPException(status_code=502, detail=detail)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Vendor API Error: {resp.text}")

    try:
        payload = resp.json()
    except Exception:
        payload = []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("results") or payload.get("data") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


async def _list_upload_post_queue_scheduled_posts(api_key: str, profile_username: str, count: int = 50) -> List[Dict[str, Any]]:
    profile_username = str(profile_username or "").strip()
    if not profile_username:
        return []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with social_calendar_sync_semaphore:
                resp = await _upload_post_async_request(
                    client,
                    "GET",
                    UPLOAD_POST_QUEUE_PREVIEW_URL,
                    api_key,
                    params={
                        "profile_username": profile_username,
                        "count": max(1, min(int(count or 50), 50)),
                    },
                )
    except httpx.RequestError as exc:
        detail = _format_outbound_network_error("Upload-Post", UPLOAD_POST_QUEUE_PREVIEW_URL, exc)
        print(f"⚠️ {detail}")
        raise HTTPException(status_code=502, detail=detail)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Vendor API Error: {resp.text}")

    try:
        payload = resp.json()
    except Exception:
        payload = {}

    slots = payload.get("slots") if isinstance(payload, dict) else []
    if not isinstance(slots, list):
        return []

    items: List[Dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        scheduled_date = str(slot.get("datetime_utc") or slot.get("datetime") or "").strip()
        if not scheduled_date:
            continue
        scheduled_posts = slot.get("scheduled_posts")
        if not isinstance(scheduled_posts, list):
            scheduled_post = slot.get("scheduled_post")
            scheduled_posts = [scheduled_post] if isinstance(scheduled_post, dict) else []
        if not scheduled_posts and (slot.get("is_full") or slot.get("manually_full")):
            slot_id = hashlib.sha1(f"{profile_username}:{scheduled_date}".encode("utf-8")).hexdigest()[:20]
            items.append({
                "job_id": f"queue-slot-{slot_id}",
                "scheduled_date": scheduled_date,
                "profile_username": profile_username,
                "title": "Belegter Upload-Post Queue-Slot",
                "caption": "Dieser Queue-Slot ist bei Upload-Post als voll markiert.",
                "preview_url": "",
                "post_type": "queue_slot",
                "platforms": [],
                "source": "queue_preview",
            })
        for scheduled_post in scheduled_posts:
            if not isinstance(scheduled_post, dict):
                continue
            vendor_job_id = str(scheduled_post.get("job_id") or scheduled_post.get("id") or "").strip()
            if not vendor_job_id:
                continue
            items.append({
                "job_id": vendor_job_id,
                "scheduled_date": scheduled_date,
                "profile_username": profile_username,
                "title": scheduled_post.get("title") or scheduled_post.get("post_title") or "",
                "caption": scheduled_post.get("caption") or scheduled_post.get("post_caption") or "",
                "preview_url": scheduled_post.get("preview_url") or "",
                "post_type": scheduled_post.get("post_type") or "video",
                "platforms": scheduled_post.get("platforms") or [],
                "source": "queue_preview",
            })
    return items


def _parse_calendar_datetime(value: Any) -> Optional[datetime.datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _filter_upload_post_calendar_horizon(
    items: List[Dict[str, Any]],
    *,
    profile_username: Optional[str] = None,
    horizon_days: int = UPLOAD_POST_CALENDAR_HORIZON_DAYS,
) -> List[Dict[str, Any]]:
    normalized_profile = str(profile_username or "").strip().casefold()
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon_end = now + datetime.timedelta(days=max(1, int(horizon_days)))
    filtered: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_profile = str(item.get("profile_username") or item.get("profile") or "").strip().casefold()
        if normalized_profile and item_profile != normalized_profile:
            continue
        scheduled_at = _parse_calendar_datetime(
            item.get("scheduled_date") or item.get("datetime_utc") or item.get("datetime")
        )
        if scheduled_at is None or scheduled_at < now or scheduled_at > horizon_end:
            continue
        filtered.append(item)
    return filtered


def _merge_upload_post_schedule_sources(*sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for source in sources:
        for item in source or []:
            if not isinstance(item, dict):
                continue
            vendor_job_id = str(item.get("job_id") or item.get("id") or "").strip()
            scheduled_date = str(item.get("scheduled_date") or item.get("datetime_utc") or "").strip()
            profile = str(item.get("profile_username") or "").strip().casefold()
            key = vendor_job_id or f"{profile}:{scheduled_date}"
            if not key:
                continue
            merged[key] = {**merged.get(key, {}), **item}
    return list(merged.values())


async def _resolve_upload_post_preview_item(
    api_key: str,
    vendor_job_id: str,
    profile_username: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    normalized_job_id = str(vendor_job_id or "").strip()
    if not normalized_job_id:
        return None

    scheduled_items = await _list_upload_post_scheduled_posts(api_key)
    for item in scheduled_items:
        if str(item.get("job_id") or item.get("id") or "").strip() == normalized_job_id:
            return item

    if profile_username:
        queue_items = await _list_upload_post_queue_scheduled_posts(api_key, profile_username)
        for item in queue_items:
            if str(item.get("job_id") or item.get("id") or "").strip() == normalized_job_id:
                return item
    return None


def _build_vendor_only_social_calendar_event(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    vendor_job_id = str(item.get("job_id") or item.get("id") or "").strip()
    scheduled_date = str(item.get("scheduled_date") or item.get("datetime_utc") or item.get("queue_slot") or "").strip()
    if not vendor_job_id or not scheduled_date:
        return None

    title = str(item.get("title") or item.get("post_title") or item.get("caption") or item.get("post_caption") or f"Upload-Post Slot {vendor_job_id[:8]}").strip()
    description = str(item.get("caption") or item.get("post_caption") or "").strip()
    profile_username = str(item.get("profile_username") or "").strip()
    post_type = str(item.get("post_type") or "").strip().lower()
    is_blocked_slot = post_type == "queue_slot"
    preview_url = str(item.get("preview_url") or "").strip()
    job_label = f"Upload-Post · {profile_username}" if profile_username else "Upload-Post"

    return {
        "id": f"vendor:{vendor_job_id}",
        "history_entry_id": f"vendor:{vendor_job_id}",
        "event_source": "vendor_queue_blocked" if is_blocked_slot else "vendor_only",
        "job_id": None,
        "job_label": job_label,
        "clip_index": -1,
        "clip_label": title,
        "clip_title": title,
        "clip_description": description,
        "local_video_url": "",
        "local_preview_video_url": "",
        "remote_preview_url": preview_url,
        "has_local_media": False,
        "media_origin": "upload_post",
        "scheduled_date": scheduled_date,
        "timezone": "UTC",
        "status": "upcoming",
        "status_label": "Nur bei Upload-Post vorhanden",
        "title": title,
        "description": description,
        "first_comment": "",
        "requested_platforms": _normalize_social_platforms(item.get("platforms") or []),
        "platform_results": [],
        "platform_links": [],
        "vendor_job_id": vendor_job_id,
        "vendor_profile_username": profile_username or None,
        "vendor_post_type": post_type or None,
        "is_blocked_slot": is_blocked_slot,
        "scheduled": True,
        "is_rescheduled": False,
        "success_count": 0,
        "failure_count": 0,
        "pending_count": 1,
        "request_settings": {
            "title": title,
            "description": description,
            "first_comment": "",
            "scheduled_date": scheduled_date,
            "timezone": "UTC",
            "platforms": [],
        },
        "updated_at": time.time(),
        "can_recreate": False,
        "can_edit": not is_blocked_slot,
    }


def _merge_global_calendar_with_vendor_schedules(
    local_events: List[Dict[str, Any]],
    vendor_scheduled_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged_events = [dict(event) for event in (local_events or [])]
    local_index_by_vendor_job_id = {
        str(event.get("vendor_job_id") or "").strip(): index
        for index, event in enumerate(merged_events)
        if str(event.get("vendor_job_id") or "").strip()
    }

    for vendor_item in vendor_scheduled_items or []:
        vendor_event = _build_vendor_only_social_calendar_event(vendor_item)
        if not vendor_event:
            continue
        vendor_job_id = str(vendor_event.get("vendor_job_id") or "").strip()
        if vendor_job_id and vendor_job_id in local_index_by_vendor_job_id:
            local_event = dict(merged_events[local_index_by_vendor_job_id[vendor_job_id]])
            preview_url = vendor_event.get("remote_preview_url") or ""
            has_local_media = bool(local_event.get("has_local_media"))
            local_event["remote_preview_url"] = preview_url or local_event.get("remote_preview_url") or ""
            local_event["vendor_profile_username"] = vendor_event.get("vendor_profile_username") or local_event.get("vendor_profile_username")
            local_event["vendor_post_type"] = vendor_event.get("vendor_post_type") or local_event.get("vendor_post_type")
            if not local_event.get("title") and vendor_event.get("title"):
                local_event["title"] = vendor_event.get("title")
            if not local_event.get("description") and vendor_event.get("description"):
                local_event["description"] = vendor_event.get("description")
            if not local_event.get("requested_platforms") and vendor_event.get("requested_platforms"):
                local_event["requested_platforms"] = vendor_event.get("requested_platforms")
            if not has_local_media:
                local_event["media_origin"] = "upload_post" if preview_url else "missing_local"
                local_event["can_recreate"] = False
            merged_events[local_index_by_vendor_job_id[vendor_job_id]] = local_event
            continue
        merged_events.append(vendor_event)
        if vendor_job_id:
            local_index_by_vendor_job_id[vendor_job_id] = len(merged_events) - 1

    merged_events.sort(key=lambda item: _event_sort_timestamp(item.get("scheduled_date")))
    return merged_events


def _resolve_clip_active_version_operation(clip: Dict[str, Any]) -> str:
    active_version = _find_clip_version(clip)
    if isinstance(active_version, dict):
        operation = str(active_version.get("operation") or "").strip().lower()
        if operation:
            return operation
        filename = active_version.get("filename")
        if filename:
            return _infer_version_operation(str(filename))
    filename = clip.get("video_filename") or ""
    if filename:
        return _infer_version_operation(str(filename))
    return "original"


def _clip_is_render_ready_for_social_queue(clip: Dict[str, Any]) -> bool:
    local_video_url = (clip.get("video_url") or clip.get("preview_video_url") or "").strip()
    if not local_video_url:
        return False
    return _resolve_clip_active_version_operation(clip) != "original"


def _should_include_clip_in_social_pending_pool(clip: Dict[str, Any]) -> bool:
    if not _clip_is_render_ready_for_social_queue(clip):
        return False

    status_payload = clip.get("social_post_status")
    normalized_status = _normalize_social_post_history_entry(status_payload) if isinstance(status_payload, dict) else None
    if not normalized_status:
        return True

    if normalized_status.get("hidden") or normalized_status.get("deleted"):
        return True

    pending_count = int(normalized_status.get("pending_count") or 0)
    success_count = int(normalized_status.get("success_count") or 0)
    failure_count = int(normalized_status.get("failure_count") or 0)
    resolved_status = _resolve_calendar_event_status(normalized_status)

    if pending_count > 0 or resolved_status in {"scheduled", "upcoming"}:
        return False
    if success_count > 0 or resolved_status == "posted":
        return False
    if failure_count > 0 or resolved_status in {"failed", "partial"}:
        return success_count <= 0
    return True


def _build_social_pending_item(job_id: str, clip_index: int, clip: Dict[str, Any], source_label: str, metadata_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _should_include_clip_in_social_pending_pool(clip):
        return None

    current_status = _normalize_social_post_history_entry(clip.get("social_post_status")) if isinstance(clip.get("social_post_status"), dict) else None
    request_settings = _social_post_request_settings_from_entry(clip, metadata_data, current_status)
    pending_count = int((current_status or {}).get("pending_count") or 0)
    success_count = int((current_status or {}).get("success_count") or 0)
    failure_count = int((current_status or {}).get("failure_count") or 0)
    failed_without_success = failure_count > 0 and success_count <= 0
    active_version = _find_clip_version(clip) or {}

    title = (
        clip.get("video_title_for_youtube_short")
        or clip.get("title")
        or request_settings.get("title")
        or f"Clip {clip_index + 1}"
    )
    description = (
        clip.get("video_description_for_instagram")
        or clip.get("video_description_for_tiktok")
        or request_settings.get("description")
        or ""
    )

    return {
        "id": f"pending:{job_id}:{clip_index}",
        "kind": "pending",
        "job_id": job_id,
        "job_label": source_label,
        "clip_index": clip_index,
        "clip_label": title,
        "clip_title": title,
        "clip_description": description,
        "local_video_url": clip.get("video_url") or clip.get("preview_video_url"),
        "local_preview_video_url": clip.get("preview_video_url") or clip.get("video_url"),
        "title": request_settings.get("title") or title,
        "description": request_settings.get("description") or description,
        "first_comment": request_settings.get("first_comment") or "",
        "timezone": request_settings.get("timezone") or "UTC",
        "requested_platforms": request_settings.get("platforms") or [],
        "request_settings": request_settings,
        "podcast_link_campaign": request_settings.get("podcast_link_campaign") or {},
        "status": "failed" if failed_without_success else "ready",
        "status_label": "Posting fehlgeschlagen" if failed_without_success else "Gerendert, noch nicht geplant",
        "failure_count": failure_count,
        "success_count": success_count,
        "pending_count": pending_count,
        "active_version_id": clip.get("active_version_id"),
        "active_version_label": active_version.get("label") or _operation_label(_resolve_clip_active_version_operation(clip)),
        "active_version_operation": _resolve_clip_active_version_operation(clip),
        "history_entry_id": (current_status or {}).get("history_entry_id"),
        "last_vendor_status": (current_status or {}).get("status"),
        "updated_at": float((current_status or {}).get("updated_at") or time.time()),
    }


def _build_job_social_pending_items(job_id: str) -> List[Dict[str, Any]]:
    output_dir = _get_job_output_dir(job_id)
    result = build_job_result(output_dir, job_id) or {"clips": []}
    manifest = load_job_manifest(output_dir)
    source_label = (
        manifest.get("request", {}).get("display_name")
        or manifest.get("request", {}).get("original_filename")
        or manifest.get("request", {}).get("url")
        or job_id
    )
    try:
        _, _, metadata_data = _load_job_metadata_or_404(job_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        metadata_data = {}

    items: List[Dict[str, Any]] = []
    for index, clip in enumerate(result.get("clips") or []):
        clip_index = int(clip.get("clip_index", index))
        item = _build_social_pending_item(job_id, clip_index, clip, source_label, metadata_data)
        if item:
            items.append(item)

    items.sort(
        key=lambda item: (
            0 if item.get("status") == "failed" else 1,
            str(item.get("job_label") or "").lower(),
            int(item.get("clip_index") or 0),
        )
    )
    return items


def _build_social_pending_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    ready_count = sum(1 for item in items if item.get("status") == "ready")
    failed_count = sum(1 for item in items if item.get("status") == "failed")
    jobs = {str(item.get("job_id") or "") for item in items if item.get("job_id")}
    return {
        "total_count": len(items),
        "ready_count": ready_count,
        "failed_count": failed_count,
        "job_count": len(jobs),
    }


async def _fetch_upload_post_status_payload(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    request_id: Optional[str],
    vendor_job_id: Optional[str],
    requested_platforms: Optional[List[str]],
    scheduled: bool,
) -> Dict[str, Any]:
    if not request_id and not vendor_job_id:
        raise HTTPException(status_code=400, detail="Missing request_id or vendor_job_id")

    params: Dict[str, str] = {}
    if request_id:
        params["request_id"] = request_id
    if vendor_job_id:
        params["job_id"] = vendor_job_id

    try:
        async with social_calendar_sync_semaphore:
            resp = await _upload_post_async_request(client, "GET", UPLOAD_POST_STATUS_URL, api_key, params=params)
    except httpx.RequestError as exc:
        detail = _format_outbound_network_error("Upload-Post", UPLOAD_POST_STATUS_URL, exc)
        print(f"⚠️ {detail}")
        raise HTTPException(status_code=502, detail=detail)

    if resp.status_code != 200:
        print(f"❌ Upload-Post Status Error: {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=f"Vendor API Error: {resp.text}")

    payload = resp.json()
    normalized_payload = payload if isinstance(payload, dict) else {"success": True, "results": payload}
    return _normalize_upload_post_response(
        normalized_payload,
        requested_platforms=requested_platforms or [],
        is_scheduled=scheduled,
    )


def _social_post_request_settings_from_entry(
    clip: Dict[str, Any],
    metadata_data: Dict[str, Any],
    entry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_settings = _normalize_social_post_request_settings((entry or {}).get("request_settings"))
    if request_settings:
        requested_platforms = _normalize_social_platforms(
            (entry or {}).get("requested_platforms")
            or request_settings.get("platforms")
            or []
        )
        if "instagram" in requested_platforms and request_settings.get("podcast_link_campaign") and not request_settings.get("instagram_caption"):
            request_settings["instagram_caption"] = _resolve_instagram_podcast_caption(
                request_settings.get("description") or "",
                requested_platforms=requested_platforms,
                podcast_campaign=request_settings.get("podcast_link_campaign"),
            )
        if "instagram" in requested_platforms and request_settings.get("podcast_link_campaign") and not request_settings.get("instagram_first_comment"):
            request_settings["instagram_first_comment"] = _compose_first_comment_with_podcast_cta(
                request_settings.get("first_comment") or "",
                keyword=(request_settings.get("podcast_link_campaign") or {}).get("keyword") or "Video",
                template=(request_settings.get("podcast_link_campaign") or {}).get("comment_template"),
                generated_text=request_settings.get("description") or "",
            )
        return request_settings
    job_social_defaults = metadata_data.get("job_social_defaults") if isinstance(metadata_data, dict) else {}
    podcast_campaign = _resolve_job_podcast_campaign(metadata_data)
    description = clip.get('video_description_for_instagram') or clip.get('video_description_for_tiktok') or "Check this out!"
    return _build_social_post_request_settings(
        final_title=clip.get('video_title_for_youtube_short') or clip.get('title', 'Viral Short'),
        final_description=description,
        first_comment="",
        scheduled_date=None,
        timezone="UTC",
        instagram_share_mode="CUSTOM",
        instagram_collaborators=clip.get("instagram_collaborators") or (job_social_defaults or {}).get("instagram_collaborators"),
        tiktok_post_mode="DIRECT_POST",
        tiktok_is_aigc=False,
        facebook_page_id=None,
        pinterest_board_id=None,
        transcript_language=(
            metadata_data.get("transcript", {}).get("language")
            or metadata_data.get("language")
            or clip.get("language")
        ),
        podcast_link_campaign=podcast_campaign,
        instagram_caption=_resolve_instagram_podcast_caption(
            description,
            requested_platforms=["instagram"],
            podcast_campaign=podcast_campaign,
        ) if podcast_campaign.get("enabled") else None,
        instagram_first_comment=_compose_first_comment_with_podcast_cta(
            "",
            keyword=podcast_campaign.get("keyword") or "Video",
            template=podcast_campaign.get("comment_template"),
            generated_text=description,
        ) if podcast_campaign.get("enabled") else None,
    )


async def _submit_social_post_for_clip(
    *,
    job_id: str,
    clip_index: int,
    api_key: str,
    user_id: str,
    requested_platforms: List[str],
    title: Optional[str] = None,
    description: Optional[str] = None,
    first_comment: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    timezone: Optional[str] = "UTC",
    instagram_share_mode: Optional[str] = "CUSTOM",
    instagram_collaborators: Optional[str] = None,
    tiktok_post_mode: Optional[str] = "DIRECT_POST",
    tiktok_is_aigc: Optional[bool] = False,
    facebook_page_id: Optional[str] = None,
    pinterest_board_id: Optional[str] = None,
    merge_existing_status: Optional[Dict[str, Any]] = None,
    updated_platforms: Optional[List[str]] = None,
    tracking_platforms: Optional[List[str]] = None,
    history_source: Optional[str] = None,
    podcast_dm_relay_url: Optional[str] = None,
    podcast_dm_relay_password: Optional[str] = None,
    relay_replaces_vendor_job_id: Optional[str] = None,
    podcast_campaign_override: Optional[Dict[str, Any]] = None,
    upload_request_id: Optional[str] = None,
) -> Dict[str, Any]:
    _, result, _ = _get_job_result_or_400(job_id)
    _, _, metadata_data = _load_job_metadata_or_404(job_id)
    clip = _find_result_clip(result, clip_index)
    job_social_defaults = metadata_data.get("job_social_defaults") if isinstance(metadata_data, dict) else {}

    filename = clip['video_url'].split('/')[-1]
    file_path = os.path.join(OUTPUT_DIR, job_id, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {file_path}")

    final_title = title or clip.get('video_title_for_youtube_short') or clip.get('title', 'Viral Short')
    final_description = description or clip.get('video_description_for_instagram') or clip.get('video_description_for_tiktok') or "Check this out!"
    normalized_first_comment = (first_comment or "").strip()
    normalized_platforms = _normalize_social_platforms(requested_platforms)
    if not normalized_platforms:
        raise HTTPException(status_code=400, detail="Select at least one platform.")
    if "pinterest" in normalized_platforms and not (pinterest_board_id or "").strip():
        raise HTTPException(status_code=400, detail="Pinterest requires a board ID.")

    normalized_campaign_override = _normalize_podcast_link_campaign(podcast_campaign_override or {})
    podcast_campaign = (
        normalized_campaign_override
        if normalized_campaign_override.get("enabled")
        else _resolve_job_podcast_campaign(metadata_data)
    )
    instagram_first_comment = normalized_first_comment
    instagram_caption = final_description
    if podcast_campaign.get("enabled") and "instagram" in normalized_platforms:
        instagram_caption = _compose_caption_with_podcast_cta(
            final_description,
            keyword=podcast_campaign.get("keyword") or "Video",
            template=podcast_campaign.get("comment_template"),
        )
        instagram_first_comment = _compose_first_comment_with_podcast_cta(
            normalized_first_comment,
            keyword=podcast_campaign.get("keyword") or "Video",
            template=podcast_campaign.get("comment_template"),
            generated_text=final_description,
        )
    if instagram_collaborators is not None:
        final_instagram_collaborators = _normalize_instagram_collaborators(instagram_collaborators or "")
    else:
        final_instagram_collaborators = _normalize_instagram_collaborators(
            (clip.get("instagram_collaborators") or "").strip()
            or ((job_social_defaults or {}).get("instagram_collaborators") or "").strip()
        )
    transcript_language = (
        metadata_data.get("transcript", {}).get("language")
        or metadata_data.get("language")
        or clip.get("language")
    )
    data_payload = _build_upload_post_data_payload(
        user_id=user_id,
        requested_platforms=normalized_platforms,
        final_title=final_title,
        final_description=final_description,
        first_comment=normalized_first_comment,
        scheduled_date=scheduled_date,
        timezone=timezone,
        instagram_share_mode=instagram_share_mode,
        instagram_collaborators=final_instagram_collaborators,
        tiktok_post_mode=tiktok_post_mode,
        tiktok_is_aigc=tiktok_is_aigc,
        facebook_page_id=facebook_page_id,
        pinterest_board_id=pinterest_board_id,
        transcript_language=transcript_language,
        instagram_caption=instagram_caption,
        instagram_first_comment=instagram_first_comment,
    )
    request_settings = _build_social_post_request_settings(
        final_title=final_title,
        final_description=final_description,
        first_comment=normalized_first_comment,
        scheduled_date=scheduled_date,
        timezone=timezone,
        instagram_share_mode=instagram_share_mode,
        instagram_collaborators=final_instagram_collaborators,
        tiktok_post_mode=tiktok_post_mode,
        tiktok_is_aigc=tiktok_is_aigc,
        facebook_page_id=facebook_page_id,
        pinterest_board_id=pinterest_board_id,
        transcript_language=transcript_language,
        podcast_link_campaign=podcast_campaign,
        instagram_caption=instagram_caption,
        instagram_first_comment=instagram_first_comment,
    )
    if upload_request_id:
        request_settings["request_id"] = upload_request_id

    with open(file_path, "rb") as f:
        file_content = f.read()

    normalized = _send_upload_post_video(
        api_key=api_key,
        requested_platforms=normalized_platforms,
        data_payload=data_payload,
        video_filename=filename,
        video_bytes=file_content,
        video_content_type="video/mp4",
        request_id=upload_request_id,
    )
    if merge_existing_status is not None:
        normalized = _merge_social_post_status(
            merge_existing_status,
            normalized,
            updated_platforms=updated_platforms or normalized_platforms,
            request_settings=request_settings,
            tracking_platforms=tracking_platforms or normalized_platforms,
        )
    else:
        normalized = _finalize_social_post_status_payload(
            normalized,
            requested_platforms=normalized_platforms,
            request_settings=request_settings,
            tracking_platforms=tracking_platforms or normalized_platforms,
        )
    normalized["clip_index"] = clip_index
    if history_source:
        normalized["source"] = history_source

    # Instagram receives its own title/comment fields in the upload payload. Never
    # PATCH generic schedule title/caption here: those fields are shared by every
    # platform in a multi-platform Upload-Post job.
    if (
        scheduled_date
        and podcast_campaign.get("enabled")
        and "instagram" in normalized_platforms
        and str(normalized.get("job_id") or "").strip()
    ):
        normalized["instagram_caption_delivery"] = {
            "success": True,
            "mode": "platform_specific_upload",
            "payload_schema_version": "instagram_title_v2",
            "vendor_job_id": str(normalized.get("job_id") or "").strip(),
            "caption": instagram_caption,
            "first_comment": instagram_first_comment,
            "upload_fields": ["instagram_title", "instagram_first_comment"],
            "created_at": time.time(),
        }

    relay_result = await _notify_podcast_dm_relay(
        relay_url=podcast_dm_relay_url,
        relay_password=podcast_dm_relay_password,
        profile_username=user_id,
        campaign=podcast_campaign,
        status_payload=normalized,
        requested_platforms=normalized_platforms,
        job_id=job_id,
        clip_index=clip_index,
        clip_title=final_title,
        replaces_vendor_job_id=relay_replaces_vendor_job_id,
    )
    if relay_result is not None:
        normalized["podcast_dm_relay"] = relay_result
        if relay_result.get("success") is False:
            append_job_log(
                _get_job_output_dir(job_id),
                f"Podcast-DM-Relay failed for clip {clip_index + 1}: {relay_result.get('message') or relay_result}",
            )
        else:
            append_job_log(_get_job_output_dir(job_id), f"Podcast-DM-Relay registered clip {clip_index + 1}.")

    persisted_clip = _persist_social_post_status_to_clip(job_id, clip_index, normalized)
    if persisted_clip:
        normalized["clip"] = persisted_clip
    return normalized


def _persist_social_post_status_to_clip(job_id: str, clip_index: int, status_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        output_dir, metadata_path, data = _load_job_metadata_or_404(job_id)
        clips = data.get("shorts", [])
        if clip_index < 0 or clip_index >= len(clips):
            return None

        clip_data = dict(clips[clip_index] or {})
        clip_data["clip_index"] = clip_index

        stored_payload = dict(status_payload or {})
        stored_payload["clip_index"] = clip_index
        stored_payload["openshorts_job_id"] = job_id
        stored_payload["updated_at"] = time.time()
        history_entries = _upsert_social_post_history_entry(
            _get_clip_social_post_history(clip_data, include_current_fallback=True),
            stored_payload,
        )
        matching_entry = next((entry for entry in history_entries if _social_post_entries_match(entry, stored_payload)), None)
        if matching_entry:
            stored_payload["history_entry_id"] = matching_entry.get("history_entry_id")
        clip_data["social_post_history"] = history_entries
        clip_data["social_post_status"] = stored_payload

        clips[clip_index] = clip_data
        data["shorts"] = clips
        _write_metadata(metadata_path, data)
        _refresh_job_result(job_id)
        return clip_data
    except Exception as e:
        print(f"⚠️ Failed to persist social post status for {job_id}#{clip_index}: {e}")
        return None

@app.post("/api/social/post")
async def post_to_socials(req: SocialPostRequest):
    try:
        normalized = await _submit_social_post_for_clip(
            job_id=req.job_id,
            clip_index=req.clip_index,
            api_key=req.api_key,
            user_id=req.user_id,
            requested_platforms=req.platforms,
            title=req.title,
            description=req.description,
            first_comment=req.first_comment,
            scheduled_date=req.scheduled_date,
            timezone=req.timezone,
            instagram_share_mode=req.instagram_share_mode,
            instagram_collaborators=req.instagram_collaborators,
            tiktok_post_mode=req.tiktok_post_mode,
            tiktok_is_aigc=req.tiktok_is_aigc,
            facebook_page_id=req.facebook_page_id,
            pinterest_board_id=req.pinterest_board_id,
            history_source="direct_post",
            podcast_dm_relay_url=req.podcast_dm_relay_url,
            podcast_dm_relay_password=req.podcast_dm_relay_password,
            upload_request_id=req.request_id,
        )
        return normalized

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Social Post Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/social/post/retry")
async def retry_social_platform_post(req: SocialPostRetryRequest):
    _get_job_record_or_404(req.job_id)

    try:
        _, _, metadata_data = _load_job_metadata_or_404(req.job_id)
        clips = metadata_data.get("shorts", [])
        if req.clip_index < 0 or req.clip_index >= len(clips):
            raise HTTPException(status_code=404, detail="Clip not found.")

        clip = clips[req.clip_index]
        requested_platforms = _normalize_social_platforms([req.platform])
        if not requested_platforms:
            raise HTTPException(status_code=400, detail="Select exactly one platform to retry.")
        platform = requested_platforms[0]

        existing_status = clip.get("social_post_status") or {}
        existing_platform_results = _normalize_social_post_platform_results(existing_status.get("platform_results"))
        existing_platform_result = next((item for item in existing_platform_results if item.get("platform") == platform), None)
        existing_status_value = (existing_platform_result or {}).get("status", "").strip().lower()
        if not existing_platform_result or (
            existing_platform_result.get("success") is not False
            and existing_status_value not in {"failed", "error"}
        ):
            raise HTTPException(status_code=400, detail="Only failed platforms can be retried individually.")

        retry_mode = (req.retry_mode or "now").strip().lower()
        if retry_mode not in {"now", "scheduled"}:
            raise HTTPException(status_code=400, detail="retry_mode must be 'now' or 'scheduled'.")

        filename = clip['video_url'].split('/')[-1]
        file_path = os.path.join(OUTPUT_DIR, req.job_id, filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Video file not found: {file_path}")

        request_settings = _normalize_social_post_request_settings(existing_status.get("request_settings")) or _build_social_post_request_settings(
            final_title=clip.get('video_title_for_youtube_short') or clip.get('title', 'Viral Short'),
            final_description=clip.get('video_description_for_instagram') or clip.get('video_description_for_tiktok') or "Check this out!",
            first_comment="",
            scheduled_date=None,
            timezone="UTC",
            instagram_share_mode="CUSTOM",
            instagram_collaborators=clip.get("instagram_collaborators"),
            tiktok_post_mode="DIRECT_POST",
            tiktok_is_aigc=False,
            facebook_page_id=None,
            pinterest_board_id=None,
            transcript_language=(
                metadata_data.get("transcript", {}).get("language")
                or metadata_data.get("language")
                or clip.get("language")
            ),
        )
        stored_scheduled_date = request_settings.get("scheduled_date")
        if retry_mode == "scheduled":
            if not stored_scheduled_date:
                raise HTTPException(status_code=400, detail="No scheduled time is stored for this post.")
            effective_scheduled_date = stored_scheduled_date
        else:
            effective_scheduled_date = None

        if platform == "pinterest" and not (request_settings.get("pinterest_board_id") or "").strip():
            raise HTTPException(status_code=400, detail="Pinterest retry requires a board ID.")

        normalized = await _submit_social_post_for_clip(
            job_id=req.job_id,
            clip_index=req.clip_index,
            api_key=req.api_key,
            user_id=req.user_id,
            requested_platforms=requested_platforms,
            title=request_settings.get("title") or clip.get('video_title_for_youtube_short') or clip.get('title', 'Viral Short'),
            description=request_settings.get("description") or clip.get('video_description_for_instagram') or clip.get('video_description_for_tiktok') or "Check this out!",
            first_comment=(request_settings.get("first_comment") or "").strip(),
            scheduled_date=effective_scheduled_date,
            timezone=request_settings.get("timezone") or "UTC",
            instagram_share_mode=request_settings.get("instagram_share_mode") or "CUSTOM",
            instagram_collaborators=request_settings.get("instagram_collaborators"),
            tiktok_post_mode=request_settings.get("tiktok_post_mode") or "DIRECT_POST",
            tiktok_is_aigc=bool(request_settings.get("tiktok_is_aigc")),
            facebook_page_id=request_settings.get("facebook_page_id"),
            pinterest_board_id=request_settings.get("pinterest_board_id"),
            merge_existing_status=existing_status,
            updated_platforms=requested_platforms,
            tracking_platforms=requested_platforms,
            history_source="platform_retry",
            podcast_dm_relay_url=req.podcast_dm_relay_url,
            podcast_dm_relay_password=req.podcast_dm_relay_password,
        )
        return normalized

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Social Retry Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/social/post/upload")
async def post_uploaded_video_to_socials(
    video: UploadFile = File(...),
    api_key: str = Form(...),
    user_id: str = Form(...),
    platforms: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(""),
    first_comment: Optional[str] = Form(None),
    scheduled_date: Optional[str] = Form(None),
    timezone: Optional[str] = Form("UTC"),
    instagram_share_mode: Optional[str] = Form("CUSTOM"),
    tiktok_post_mode: Optional[str] = Form("DIRECT_POST"),
    tiktok_is_aigc: Optional[bool] = Form(False),
    facebook_page_id: Optional[str] = Form(None),
    pinterest_board_id: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    podcast_dm_enabled: bool = Form(False),
    podcast_dm_link_url: Optional[str] = Form(None),
    podcast_dm_keyword: Optional[str] = Form("Video"),
    podcast_dm_relay_url: Optional[str] = Form(None),
    podcast_dm_relay_password: Optional[str] = Form(None),
):
    requested_platforms = _parse_social_platforms_form_value(platforms)
    if not requested_platforms:
        raise HTTPException(status_code=400, detail="Select at least one platform.")
    if "pinterest" in requested_platforms and not (pinterest_board_id or "").strip():
        raise HTTPException(status_code=400, detail="Pinterest requires a board ID.")

    filename = os.path.basename(video.filename or f"upload_{uuid.uuid4().hex}.mp4")
    final_title = (title or "").strip() or "Uploaded Video"
    final_description = (description or "").strip()
    first_comment_value = (first_comment or "").strip()
    podcast_campaign = _normalize_podcast_link_campaign({
        "enabled": podcast_dm_enabled,
        "link_url": podcast_dm_link_url,
        "keyword": podcast_dm_keyword,
    })
    if podcast_dm_enabled:
        if "instagram" not in requested_platforms:
            raise HTTPException(status_code=400, detail="The comment-to-DM trigger requires Instagram.")
        if not podcast_campaign.get("enabled"):
            raise HTTPException(status_code=400, detail="A valid destination link is required for the Instagram DM trigger.")
        if not _normalize_podcast_relay_url(podcast_dm_relay_url):
            raise HTTPException(status_code=400, detail="A valid podcast DM relay URL is required.")
        if not _normalize_unicode_text(podcast_dm_relay_password).strip():
            raise HTTPException(status_code=400, detail="The podcast DM relay password is required.")

    instagram_caption = final_description
    instagram_first_comment = first_comment_value
    if podcast_campaign.get("enabled"):
        instagram_caption = _compose_caption_with_podcast_cta(
            final_description,
            keyword=podcast_campaign.get("keyword") or "Video",
            template=podcast_campaign.get("comment_template"),
        )
        instagram_first_comment = _compose_first_comment_with_podcast_cta(
            first_comment_value,
            keyword=podcast_campaign.get("keyword") or "Video",
            template=podcast_campaign.get("comment_template"),
            generated_text=final_description,
        )

    file_content = await video.read()
    if not file_content:
        raise HTTPException(status_code=400, detail="Uploaded video is empty.")

    max_bytes = MAX_FILE_SIZE_BYTES
    if max_bytes is not None and len(file_content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File too large. Max size is {MAX_FILE_SIZE_MB}MB.")

    try:
        data_payload = _build_upload_post_data_payload(
            user_id=user_id,
            requested_platforms=requested_platforms,
            final_title=final_title,
            final_description=final_description,
            first_comment=first_comment_value,
            scheduled_date=scheduled_date,
            timezone=timezone,
            instagram_share_mode=instagram_share_mode,
            instagram_collaborators=None,
            tiktok_post_mode=tiktok_post_mode,
            tiktok_is_aigc=tiktok_is_aigc,
            facebook_page_id=facebook_page_id,
            pinterest_board_id=pinterest_board_id,
            transcript_language=language,
            instagram_caption=instagram_caption,
            instagram_first_comment=instagram_first_comment,
        )
        request_settings = _build_social_post_request_settings(
            final_title=final_title,
            final_description=final_description,
            first_comment=first_comment_value,
            scheduled_date=scheduled_date,
            timezone=timezone,
            instagram_share_mode=instagram_share_mode,
            instagram_collaborators=None,
            tiktok_post_mode=tiktok_post_mode,
            tiktok_is_aigc=tiktok_is_aigc,
            facebook_page_id=facebook_page_id,
            pinterest_board_id=pinterest_board_id,
            transcript_language=language,
            podcast_link_campaign=podcast_campaign,
            instagram_caption=instagram_caption,
            instagram_first_comment=instagram_first_comment,
        )
        normalized = _send_upload_post_video(
            api_key=api_key,
            requested_platforms=requested_platforms,
            data_payload=data_payload,
            video_filename=filename,
            video_bytes=file_content,
            video_content_type=video.content_type or "application/octet-stream",
        )
        normalized = _finalize_social_post_status_payload(
            normalized,
            requested_platforms=requested_platforms,
            request_settings=request_settings,
            tracking_platforms=requested_platforms,
        )
        normalized["source"] = "uploaded_video"
        normalized["filename"] = filename
        relay_result = await _notify_podcast_dm_relay(
            relay_url=podcast_dm_relay_url,
            relay_password=podcast_dm_relay_password,
            profile_username=user_id,
            campaign=podcast_campaign,
            status_payload=normalized,
            requested_platforms=requested_platforms,
            clip_title=final_title,
        )
        if relay_result is not None:
            normalized["podcast_dm_relay"] = relay_result
        return normalized
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Social Upload Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/social/post/status")
async def get_social_post_status(
    api_key: str = Header(..., alias="X-Upload-Post-Key"),
    request_id: Optional[str] = None,
    vendor_job_id: Optional[str] = None,
    platforms: Optional[str] = None,
    scheduled: bool = False,
    job_id: Optional[str] = None,
    clip_index: Optional[int] = None,
):
    requested_platforms = _normalize_social_platforms((platforms or "").split(",")) if platforms else []
    async with httpx.AsyncClient(timeout=30.0) as client:
        normalized = await _fetch_upload_post_status_payload(
            client,
            api_key,
            request_id=request_id,
            vendor_job_id=vendor_job_id,
            requested_platforms=requested_platforms,
            scheduled=scheduled,
        )
    if job_id is not None and clip_index is not None:
        existing_status = None
        try:
            _, _, metadata_data = _load_job_metadata_or_404(job_id)
            clips = metadata_data.get("shorts", [])
            if 0 <= clip_index < len(clips):
                existing_status = clips[clip_index].get("social_post_status")
        except HTTPException:
            raise
        except Exception as exc:
            print(f"⚠️ Failed to load existing social post status for merge: {exc}")

        if existing_status:
            normalized = _merge_social_post_status(
                existing_status,
                normalized,
                updated_platforms=requested_platforms,
                tracking_platforms=requested_platforms,
            )
        else:
            normalized = _finalize_social_post_status_payload(
                normalized,
                requested_platforms=requested_platforms,
                tracking_platforms=requested_platforms,
            )
        normalized["clip_index"] = clip_index
        normalized["openshorts_job_id"] = job_id
        persisted_clip = _persist_social_post_status_to_clip(job_id, clip_index, normalized)
        if persisted_clip:
            normalized["clip"] = persisted_clip

    return normalized


def _build_social_calendar_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "total_events": len(events),
        "scheduled_count": 0,
        "posted_count": 0,
        "failed_count": 0,
        "partial_count": 0,
    }
    affected_clips = set()
    for event in events:
        status = str(event.get("status") or "").strip().lower()
        clip_key = (event.get("job_id"), int(event.get("clip_index", -1)))
        if status in {"scheduled", "upcoming"}:
            summary["scheduled_count"] += 1
        elif status == "posted":
            summary["posted_count"] += 1
        elif status == "partial":
            summary["partial_count"] += 1
            affected_clips.add(clip_key)
        elif status == "failed":
            summary["failed_count"] += 1
            affected_clips.add(clip_key)
    summary["failed_clip_count"] = len(affected_clips)
    return summary


async def _sync_single_social_history_entry(
    client: httpx.AsyncClient,
    api_key: str,
    clip_index: int,
    entry: Dict[str, Any],
) -> Tuple[int, str, Optional[Dict[str, Any]], Optional[str]]:
    request_settings = _normalize_social_post_request_settings(entry.get("request_settings")) or {}
    requested_platforms = _normalize_social_platforms(entry.get("requested_platforms") or [])
    history_entry_id = str(entry.get("history_entry_id") or "")
    try:
        normalized = await _fetch_upload_post_status_payload(
            client,
            api_key,
            request_id=(entry.get("request_id") or "").strip() or None,
            vendor_job_id=(entry.get("job_id") or "").strip() or None,
            requested_platforms=requested_platforms,
            scheduled=bool(request_settings.get("scheduled_date")),
        )
        merged = _merge_social_post_status(
            entry,
            normalized,
            updated_platforms=requested_platforms,
            request_settings=request_settings,
            tracking_platforms=entry.get("tracking_platforms") or requested_platforms,
        )
        merged["history_entry_id"] = history_entry_id
        merged["created_at"] = float(entry.get("created_at") or time.time())
        merged["updated_at"] = time.time()
        for key in ("hidden", "deleted", "deleted_at", "rescheduled_from", "rescheduled_to", "source"):
            if entry.get(key) is not None:
                merged[key] = entry.get(key)
        return clip_index, history_entry_id, _normalize_social_post_history_entry(merged), None
    except HTTPException as exc:
        failed_entry = dict(entry)
        failed_entry["poll_error"] = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
        failed_entry["updated_at"] = time.time()
        return clip_index, history_entry_id, _normalize_social_post_history_entry(failed_entry), failed_entry["poll_error"]


async def _sync_job_social_posts(job_id: str, api_key: str) -> Dict[str, Any]:
    output_dir, metadata_path, data = _load_job_metadata_or_404(job_id)
    clips = data.get("shorts", [])
    sync_tasks: List[asyncio.Task] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for clip_index, raw_clip in enumerate(clips):
            clip = dict(raw_clip or {})
            for entry in _get_clip_social_post_history(clip, include_current_fallback=True):
                if entry.get("hidden") or entry.get("deleted"):
                    continue
                if not ((entry.get("request_id") or "").strip() or (entry.get("job_id") or "").strip()):
                    continue
                sync_tasks.append(asyncio.create_task(_sync_single_social_history_entry(client, api_key, clip_index, entry)))

        sync_results = await asyncio.gather(*sync_tasks) if sync_tasks else []

    sync_result_map = {
        (clip_index, history_entry_id): {"entry": entry, "error": error}
        for clip_index, history_entry_id, entry, error in sync_results
        if history_entry_id
    }
    changed = False
    sync_errors: List[Dict[str, Any]] = []

    for clip_index, raw_clip in enumerate(clips):
        clip = dict(raw_clip or {})
        existing_history = _get_clip_social_post_history(clip, include_current_fallback=True)
        next_history: List[Dict[str, Any]] = []
        history_changed = not isinstance(clip.get("social_post_history"), list) and bool(existing_history)

        for entry in existing_history:
            replacement = sync_result_map.get((clip_index, str(entry.get("history_entry_id") or "")))
            next_entry = replacement["entry"] if replacement and replacement.get("entry") else entry
            if replacement and replacement.get("error"):
                sync_errors.append({
                    "clip_index": clip_index,
                    "history_entry_id": entry.get("history_entry_id"),
                    "error": replacement["error"],
                })
            if json.dumps(next_entry, sort_keys=True, ensure_ascii=False, default=str) != json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str):
                history_changed = True
            next_history.append(next_entry)

        if not history_changed:
            continue

        changed = True
        next_history = _sort_social_post_history_entries(next_history)
        clip["social_post_history"] = next_history
        current_entry = _resolve_latest_visible_social_post_entry(next_history)
        current_payload = _strip_social_post_history_entry(current_entry)
        if current_payload:
            current_payload["clip_index"] = clip_index
            current_payload["openshorts_job_id"] = job_id
            clip["social_post_status"] = current_payload
        else:
            clip.pop("social_post_status", None)
        clip["clip_index"] = clip_index
        clips[clip_index] = clip

    if changed:
        data["shorts"] = clips
        _write_metadata(metadata_path, data)
        result = _refresh_job_result(job_id) or build_job_result(output_dir, job_id) or {"clips": []}
    else:
        result = build_job_result(output_dir, job_id) or {"clips": []}

    events = _build_job_social_calendar_events(job_id)
    pending_items = _build_job_social_pending_items(job_id)
    summary = _build_social_calendar_summary(events)
    summary["synced_entries"] = len(sync_results)
    return {
        "success": True,
        "job_id": job_id,
        "result": result,
        "events": events,
        "pending_items": pending_items,
        "pending_summary": _build_social_pending_summary(pending_items),
        "summary": summary,
        "sync_errors": sync_errors,
    }


def _find_social_history_entry(clip: Dict[str, Any], history_entry_id: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    entries = _get_clip_social_post_history(clip, include_current_fallback=True)
    if history_entry_id:
        for entry in entries:
            if str(entry.get("history_entry_id") or "") == str(history_entry_id):
                return entries, entry
        raise HTTPException(status_code=404, detail="Kalender-Eintrag nicht gefunden.")
    entry = _resolve_latest_visible_social_post_entry(entries)
    if not entry:
        raise HTTPException(status_code=404, detail="Kein Social-Post-Tracking fuer diesen Clip gefunden.")
    return entries, entry


def _entry_is_future_scheduled(entry: Dict[str, Any]) -> bool:
    request_settings = _normalize_social_post_request_settings(entry.get("request_settings")) or {}
    scheduled_dt = _parse_iso_datetime(request_settings.get("scheduled_date"))
    if not scheduled_dt:
        return False
    if scheduled_dt.tzinfo is None:
        scheduled_dt = scheduled_dt.replace(tzinfo=datetime.timezone.utc)
    return scheduled_dt > datetime.datetime.now(datetime.timezone.utc)


def _entry_supports_vendor_patch(entry: Dict[str, Any], requested_platforms: List[str], req: SocialCalendarEventUpdateRequest) -> bool:
    if not (entry.get("job_id") or "").strip():
        return False
    if _resolve_calendar_event_status(entry) not in {"scheduled", "upcoming"}:
        return False
    if not _entry_is_future_scheduled(entry):
        return False

    existing_platforms = _normalize_social_platforms(entry.get("requested_platforms") or [])
    if requested_platforms != existing_platforms:
        return False

    request_settings = _normalize_social_post_request_settings(entry.get("request_settings")) or {}
    unsupported_changes = [
        req.title is not None and (req.title or "").strip() != (request_settings.get("title") or "").strip(),
        req.description is not None and (req.description or "").strip() != (request_settings.get("description") or "").strip(),
        req.first_comment is not None and (req.first_comment or "").strip() != (request_settings.get("first_comment") or "").strip(),
        req.instagram_share_mode is not None and (req.instagram_share_mode or "").strip() != (request_settings.get("instagram_share_mode") or "").strip(),
        req.instagram_collaborators is not None and _normalize_instagram_collaborators(req.instagram_collaborators or "") != _normalize_instagram_collaborators(request_settings.get("instagram_collaborators") or ""),
        req.tiktok_post_mode is not None and (req.tiktok_post_mode or "").strip() != (request_settings.get("tiktok_post_mode") or "").strip(),
        req.tiktok_is_aigc is not None and bool(req.tiktok_is_aigc) != bool(request_settings.get("tiktok_is_aigc")),
        req.facebook_page_id is not None and (req.facebook_page_id or "").strip() != (request_settings.get("facebook_page_id") or "").strip(),
        req.pinterest_board_id is not None and (req.pinterest_board_id or "").strip() != (request_settings.get("pinterest_board_id") or "").strip(),
    ]
    return not any(unsupported_changes)


def _mark_social_history_entry_deleted(
    entry: Dict[str, Any],
    *,
    message: str,
    replacement_entry_id: Optional[str] = None,
) -> Dict[str, Any]:
    deleted_entry = dict(entry)
    deleted_entry["deleted"] = True
    deleted_entry["hidden"] = True
    deleted_entry["deleted_at"] = time.time()
    deleted_entry["status"] = "cancelled"
    deleted_entry["message"] = message
    deleted_entry["updated_at"] = time.time()
    deleted_entry["poll_error"] = None
    if replacement_entry_id:
        deleted_entry["rescheduled_to"] = replacement_entry_id
    return _normalize_social_post_history_entry(deleted_entry)


async def _recreate_social_calendar_entry(
    *,
    job_id: str,
    clip_index: int,
    api_key: str,
    user_id: str,
    target_entry: Dict[str, Any],
    requested_platforms: List[str],
    scheduled_date: str,
    title: Optional[str],
    description: Optional[str],
    first_comment: Optional[str],
    timezone: Optional[str],
    instagram_share_mode: Optional[str],
    instagram_collaborators: Optional[str],
    tiktok_post_mode: Optional[str],
    tiktok_is_aigc: Optional[bool],
    facebook_page_id: Optional[str],
    pinterest_board_id: Optional[str],
    history_source: str = "calendar_reschedule",
    podcast_dm_relay_url: Optional[str] = None,
    podcast_dm_relay_password: Optional[str] = None,
    upload_request_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    vendor_job_id = (target_entry.get("job_id") or "").strip()
    normalized_requested_platforms = _normalize_social_platforms(requested_platforms)
    # Create the platform-specific replacement before deleting the old schedule.
    # A failed upload therefore leaves the existing slot untouched.
    normalized = await _submit_social_post_for_clip(
        job_id=job_id,
        clip_index=clip_index,
        api_key=api_key,
        user_id=user_id,
        requested_platforms=normalized_requested_platforms,
        title=title,
        description=description,
        first_comment=first_comment,
        scheduled_date=scheduled_date,
        timezone=timezone or "UTC",
        instagram_share_mode=instagram_share_mode or "CUSTOM",
        instagram_collaborators=instagram_collaborators,
        tiktok_post_mode=tiktok_post_mode or "DIRECT_POST",
        tiktok_is_aigc=bool(tiktok_is_aigc),
        facebook_page_id=facebook_page_id,
        pinterest_board_id=pinterest_board_id,
        history_source=history_source,
        podcast_campaign_override=(
            (target_entry.get("request_settings") or {}).get("podcast_link_campaign")
        ),
        upload_request_id=upload_request_id or f"recreate-{uuid.uuid4().hex}",
    )

    updated_clip = normalized.get("clip")
    new_history_entry_id = ((updated_clip or {}).get("social_post_status") or {}).get("history_entry_id")
    new_vendor_job_id = str(normalized.get("job_id") or "").strip()
    old_history_entry_id = str(target_entry.get("history_entry_id") or "")
    if not new_vendor_job_id or not updated_clip or not new_history_entry_id:
        if new_vendor_job_id:
            try:
                await _delete_upload_post_schedule(api_key, new_vendor_job_id)
            except HTTPException:
                pass
        raise HTTPException(status_code=500, detail="Replacement schedule could not be persisted locally.")

    if vendor_job_id and _entry_is_future_scheduled(target_entry):
        try:
            await _delete_upload_post_schedule(api_key, vendor_job_id)
        except HTTPException:
            # Best-effort rollback: keep the original slot authoritative if its
            # deletion failed after the replacement was accepted.
            if new_vendor_job_id:
                try:
                    await _delete_upload_post_schedule(api_key, new_vendor_job_id)
                except HTTPException:
                    pass
            if updated_clip and new_history_entry_id:
                rollback_history = _get_clip_social_post_history(updated_clip, include_current_fallback=True)
                rollback_history = [
                    _mark_social_history_entry_deleted(entry, message="Ersatz-Scheduling zurueckgerollt.")
                    if str(entry.get("history_entry_id") or "") == str(new_history_entry_id)
                    else entry
                    for entry in rollback_history
                ]
                _persist_clip_social_post_history(
                    job_id,
                    clip_index,
                    rollback_history,
                    preferred_current_entry_id=old_history_entry_id or None,
                )
            raise

    if podcast_dm_relay_url and podcast_dm_relay_password:
        delivery = normalized.get("instagram_caption_delivery")
        if isinstance(delivery, dict) and vendor_job_id:
            delivery["replaces_vendor_job_id"] = vendor_job_id
        _, _, metadata_data = _load_job_metadata_or_404(job_id)
        relay_result = await _notify_podcast_dm_relay(
            relay_url=podcast_dm_relay_url,
            relay_password=podcast_dm_relay_password,
            profile_username=user_id,
            campaign=(
                (normalized.get("request_settings") or {}).get("podcast_link_campaign")
                or _resolve_job_podcast_campaign(metadata_data)
            ),
            status_payload=normalized,
            requested_platforms=normalized_requested_platforms,
            job_id=job_id,
            clip_index=clip_index,
            clip_title=title,
            replaces_vendor_job_id=vendor_job_id,
        )
        if relay_result is not None:
            normalized["podcast_dm_relay"] = relay_result
            persisted_clip = _persist_social_post_status_to_clip(job_id, clip_index, normalized)
            if persisted_clip:
                updated_clip = persisted_clip
                normalized["clip"] = persisted_clip

    if updated_clip and new_history_entry_id:
        refreshed_history = _get_clip_social_post_history(updated_clip, include_current_fallback=True)
        next_history: List[Dict[str, Any]] = []
        for entry in refreshed_history:
            entry_history_id = str(entry.get("history_entry_id") or "")
            if entry_history_id == old_history_entry_id:
                next_history.append(_mark_social_history_entry_deleted(
                    entry,
                    message="Geplanten Post ersetzt.",
                    replacement_entry_id=new_history_entry_id,
                ))
            elif entry_history_id == str(new_history_entry_id):
                rescheduled_entry = dict(entry)
                if old_history_entry_id:
                    rescheduled_entry["rescheduled_from"] = old_history_entry_id
                rescheduled_entry["source"] = history_source
                next_history.append(_normalize_social_post_history_entry(rescheduled_entry))
            else:
                next_history.append(entry)
        updated_clip = _persist_clip_social_post_history(
            job_id,
            clip_index,
            next_history,
            preferred_current_entry_id=new_history_entry_id,
        )

    return updated_clip, new_history_entry_id


async def _patch_upload_post_schedule(api_key: str, vendor_job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{UPLOAD_POST_SCHEDULE_URL}/{urllib.parse.quote(str(vendor_job_id), safe='')}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await _upload_post_async_request(
                client,
                "PATCH",
                url,
                api_key,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
    except httpx.RequestError as exc:
        detail = _format_outbound_network_error("Upload-Post", url, exc)
        print(f"⚠️ {detail}")
        raise HTTPException(status_code=502, detail=detail)

    if resp.status_code == 429:
        retry_after_seconds = 0.0
        retry_after_header = str(resp.headers.get("Retry-After") or "").strip()
        rate_limit_reset = str(resp.headers.get("X-RateLimit-Reset") or "").strip()
        try:
            retry_after_seconds = max(retry_after_seconds, float(retry_after_header))
        except (TypeError, ValueError):
            pass
        try:
            retry_after_seconds = max(retry_after_seconds, float(rate_limit_reset) - time.time())
        except (TypeError, ValueError):
            pass
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Vendor API Error: {resp.text}",
                "retry_after_seconds": max(1.0, min(retry_after_seconds or 60.0, 120.0)),
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Vendor API Error: {resp.text}")
    try:
        response_payload = resp.json()
    except Exception:
        response_payload = {}
    if not isinstance(response_payload, dict):
        response_payload = {}
    return response_payload


def _build_podcast_caption_patch_candidates(
    profile_username: str,
    *,
    active_vendor_job_ids: set[str],
    selected_job_ids: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    normalized_profile = str(profile_username or "").strip()
    candidates: List[Dict[str, Any]] = []
    seen_vendor_job_ids: set[str] = set()
    stats = {
        "jobs_scanned": 0,
        "events_scanned": 0,
        "missing_campaign": 0,
        "not_instagram": 0,
        "not_future": 0,
        "missing_vendor_job_id": 0,
        "not_active_at_upload_post": 0,
        "cannot_recreate": 0,
        "caption_already_confirmed": 0,
        "outdated_delivery_marker": 0,
        "duplicates": 0,
    }

    job_summaries = list_job_summaries(
        OUTPUT_DIR,
        limit=0,
        include_result=False,
        include_logs=False,
        log_limit=0,
    )
    for summary in job_summaries:
        job_id = str(summary.get("job_id") or "").strip()
        if not job_id or (selected_job_ids is not None and job_id not in selected_job_ids):
            continue
        manifest = load_job_manifest(_get_job_output_dir(job_id)) or {}
        request_meta = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
        if str(request_meta.get("upload_post_profile") or "").strip() != normalized_profile:
            continue
        try:
            _, _, metadata_data = _load_job_metadata_or_404(job_id)
        except HTTPException:
            metadata_data = {}
        job_campaign = _resolve_job_podcast_campaign(metadata_data)
        stats["jobs_scanned"] += 1

        for event in _build_job_social_calendar_events(job_id):
            stats["events_scanned"] += 1
            request_settings = _normalize_social_post_request_settings(event.get("request_settings")) or {}
            requested_platforms = _normalize_social_platforms(
                event.get("requested_platforms") or request_settings.get("platforms") or []
            )
            if "instagram" not in requested_platforms:
                stats["not_instagram"] += 1
                continue
            stored_campaign = _normalize_podcast_link_campaign(
                request_settings.get("podcast_link_campaign") or event.get("podcast_link_campaign") or {}
            )
            campaign = stored_campaign if stored_campaign.get("enabled") else job_campaign
            if not campaign.get("enabled"):
                stats["missing_campaign"] += 1
                continue
            campaign_source = "history" if stored_campaign.get("enabled") else "job_default"
            vendor_job_id = str(event.get("vendor_job_id") or "").strip()
            if not vendor_job_id:
                stats["missing_vendor_job_id"] += 1
                continue
            is_future = _is_future_scheduled_datetime(event.get("scheduled_date"))
            if not is_future:
                stats["not_future"] += 1
            if is_future and vendor_job_id not in active_vendor_job_ids:
                stats["not_active_at_upload_post"] += 1
            description = request_settings.get("description") or event.get("description") or ""
            desired_caption = _resolve_instagram_podcast_caption(
                description,
                requested_platforms=requested_platforms,
                podcast_campaign=campaign,
            )
            if not desired_caption:
                continue
            desired_first_comment = _compose_first_comment_with_podcast_cta(
                request_settings.get("first_comment") or "",
                keyword=campaign.get("keyword") or "Video",
                template=campaign.get("comment_template"),
                generated_text=description,
            )
            previous_delivery = event.get("instagram_caption_delivery")
            caption_already_confirmed = bool(
                isinstance(previous_delivery, dict)
                and previous_delivery.get("success") is True
                and previous_delivery.get("mode") == "platform_specific_upload"
                and previous_delivery.get("payload_schema_version") == "instagram_title_v2"
                and str(previous_delivery.get("caption") or "") == desired_caption
                and str(previous_delivery.get("first_comment") or "") == desired_first_comment
            )
            if (
                is_future
                and isinstance(previous_delivery, dict)
                and previous_delivery.get("success") is True
                and previous_delivery.get("mode") == "platform_specific_upload"
                and previous_delivery.get("payload_schema_version") != "instagram_title_v2"
            ):
                stats["outdated_delivery_marker"] += 1
            is_active_vendor_schedule = vendor_job_id in active_vendor_job_ids
            caption_needs_recreate = bool(
                is_future and not caption_already_confirmed
            )
            can_recreate = bool(event.get("can_recreate"))
            if caption_needs_recreate and not can_recreate:
                stats["cannot_recreate"] += 1
            caption_eligible = bool(caption_needs_recreate and can_recreate)
            if is_future and caption_already_confirmed:
                stats["caption_already_confirmed"] += 1
            relay_needs_repair = bool(
                caption_eligible
                or (
                    not (
                        isinstance(event.get("podcast_dm_relay"), dict)
                        and event.get("podcast_dm_relay", {}).get("success") is True
                    )
                )
            )
            if not caption_eligible and not relay_needs_repair:
                continue
            if vendor_job_id in seen_vendor_job_ids:
                stats["duplicates"] += 1
                continue
            request_settings["podcast_link_campaign"] = campaign
            request_settings["instagram_caption"] = desired_caption
            request_settings["instagram_first_comment"] = desired_first_comment
            seen_vendor_job_ids.add(vendor_job_id)
            candidates.append({
                "job_id": job_id,
                "clip_index": event.get("clip_index"),
                "history_entry_id": event.get("history_entry_id"),
                "clip_title": event.get("clip_title") or event.get("title") or "",
                "vendor_job_id": vendor_job_id,
                "scheduled_date": event.get("scheduled_date"),
                "caption": desired_caption,
                "first_comment": desired_first_comment,
                "caption_eligible": caption_eligible,
                "keyword": campaign.get("keyword") or "Video",
                "campaign_source": campaign_source,
                "requested_platforms": requested_platforms,
                "relay_needs_repair": relay_needs_repair,
                "replaces_vendor_job_id": str(
                    (previous_delivery or {}).get("replaces_vendor_job_id") or ""
                ),
                "_campaign": campaign,
                "_request_settings": request_settings,
                "_status_payload": {
                    **event,
                    "job_id": vendor_job_id,
                    "request_settings": request_settings,
                },
                "_target_entry": {
                    **event,
                    "job_id": vendor_job_id,
                    "request_settings": request_settings,
                    "requested_platforms": requested_platforms,
                },
            })

    candidates.sort(key=lambda item: _event_sort_timestamp(item.get("scheduled_date")))
    return candidates, stats


async def _repair_podcast_campaign_candidate(
    api_key: str,
    candidate: Dict[str, Any],
    semaphore: asyncio.Semaphore,
    *,
    profile_username: str,
    relay_url: Optional[str] = None,
    relay_password: Optional[str] = None,
) -> Dict[str, Any]:
    vendor_job_id = str(candidate.get("vendor_job_id") or "").strip()
    async with semaphore:
        caption_result: Dict[str, Any] = {"success": None, "skipped": "not_future_or_not_active"}
        relay_result: Optional[Dict[str, Any]] = None
        if candidate.get("caption_eligible"):
            caption_result = {"success": False, "error": "Platform-specific schedule recreation did not run."}
            request_settings = candidate.get("_request_settings") or {}
            replacement_request_id = f"repair-{uuid.uuid4().hex}"
            for attempt in range(3):
                try:
                    updated_clip, replacement_history_entry_id = await _recreate_social_calendar_entry(
                        job_id=str(candidate.get("job_id") or ""),
                        clip_index=int(candidate.get("clip_index") or 0),
                        api_key=api_key,
                        user_id=profile_username,
                        target_entry=candidate.get("_target_entry") or {},
                        requested_platforms=candidate.get("requested_platforms") or [],
                        scheduled_date=str(candidate.get("scheduled_date") or ""),
                        title=request_settings.get("title"),
                        description=request_settings.get("description"),
                        first_comment=request_settings.get("first_comment"),
                        timezone=request_settings.get("timezone") or "UTC",
                        instagram_share_mode=request_settings.get("instagram_share_mode") or "CUSTOM",
                        instagram_collaborators=request_settings.get("instagram_collaborators"),
                        tiktok_post_mode=request_settings.get("tiktok_post_mode") or "DIRECT_POST",
                        tiktok_is_aigc=bool(request_settings.get("tiktok_is_aigc")),
                        facebook_page_id=request_settings.get("facebook_page_id"),
                        pinterest_board_id=request_settings.get("pinterest_board_id"),
                        history_source="podcast_caption_repair",
                        podcast_dm_relay_url=relay_url,
                        podcast_dm_relay_password=relay_password,
                        upload_request_id=replacement_request_id,
                    )
                    replacement_entry = next((
                        entry
                        for entry in _get_clip_social_post_history(updated_clip or {}, include_current_fallback=True)
                        if str(entry.get("history_entry_id") or "") == str(replacement_history_entry_id or "")
                    ), {})
                    delivery = replacement_entry.get("instagram_caption_delivery") or {}
                    relay_result = replacement_entry.get("podcast_dm_relay")
                    caption_result = {
                        "success": bool(
                            delivery.get("success") is True
                            and delivery.get("mode") == "platform_specific_upload"
                            and delivery.get("payload_schema_version") == "instagram_title_v2"
                            and str(delivery.get("caption") or "") == str(candidate.get("caption") or "")
                            and str(delivery.get("first_comment") or "") == str(candidate.get("first_comment") or "")
                        ),
                        "mode": "platform_specific_recreate",
                        "replacement_vendor_job_id": replacement_entry.get("job_id"),
                        "replacement_history_entry_id": replacement_history_entry_id,
                        "attempts": attempt + 1,
                    }
                    if not caption_result["success"]:
                        caption_result["error"] = "Replacement was created without an exact Instagram delivery marker."
                    await asyncio.sleep(0.8)
                    break
                except HTTPException as exc:
                    status_code = int(exc.status_code or 500)
                    retryable = status_code == 429 or status_code >= 500
                    retry_after_seconds = 0.0
                    if isinstance(exc.detail, dict):
                        try:
                            retry_after_seconds = float(exc.detail.get("retry_after_seconds") or 0)
                        except (TypeError, ValueError):
                            retry_after_seconds = 0.0
                    if not retryable or attempt >= 2:
                        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
                        caption_result = {
                            "success": False,
                            "status_code": status_code,
                            "error": detail,
                            "attempts": attempt + 1,
                        }
                        break
                    await asyncio.sleep(max(1.5 * (2 ** attempt), retry_after_seconds))

        if (
            not candidate.get("caption_eligible")
            and candidate.get("relay_needs_repair")
            and relay_url
            and relay_password
        ):
            relay_result = await _notify_podcast_dm_relay(
                relay_url=relay_url,
                relay_password=relay_password,
                profile_username=profile_username,
                campaign=candidate.get("_campaign") or {},
                status_payload=candidate.get("_status_payload") or {},
                requested_platforms=candidate.get("requested_platforms") or [],
                job_id=str(candidate.get("job_id") or ""),
                clip_index=candidate.get("clip_index"),
                clip_title=str(candidate.get("clip_title") or ""),
                replaces_vendor_job_id=str(candidate.get("replaces_vendor_job_id") or "") or None,
            )

        should_persist_result = not candidate.get("caption_eligible") and (
            candidate.get("campaign_source") == "job_default" or relay_result is not None
        )
        if should_persist_result:
            try:
                _, result, _ = _get_job_result_or_400(str(candidate.get("job_id") or ""))
                clip = _find_result_clip(result, int(candidate.get("clip_index") or 0))
                entries = _get_clip_social_post_history(clip, include_current_fallback=True)
                target_history_id = str(candidate.get("history_entry_id") or "")
                for entry in entries:
                    if str(entry.get("history_entry_id") or "") == target_history_id:
                        entry["request_settings"] = candidate.get("_request_settings") or entry.get("request_settings") or {}
                        if relay_result is not None:
                            entry["podcast_dm_relay"] = relay_result
                        entry["updated_at"] = time.time()
                        break
                _persist_clip_social_post_history(
                    str(candidate.get("job_id") or ""),
                    int(candidate.get("clip_index") or 0),
                    entries,
                    preferred_current_entry_id=target_history_id or None,
                )
            except Exception as exc:
                print(f"⚠️ Could not persist repaired podcast campaign state: {exc}")

        public_candidate = {key: value for key, value in candidate.items() if not key.startswith("_")}
        return {
            **public_candidate,
            "success": caption_result.get("success") is not False and not (
                relay_result is not None and relay_result.get("success") is False
            ),
            "caption_patch": caption_result,
            "relay_registration": relay_result,
        }


async def _delete_upload_post_schedule(api_key: str, vendor_job_id: str) -> Dict[str, Any]:
    url = f"{UPLOAD_POST_SCHEDULE_URL}/{urllib.parse.quote(str(vendor_job_id), safe='')}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await _upload_post_async_request(client, "DELETE", url, api_key)
    except httpx.RequestError as exc:
        detail = _format_outbound_network_error("Upload-Post", url, exc)
        print(f"⚠️ {detail}")
        raise HTTPException(status_code=502, detail=detail)

    if resp.status_code == 404:
        return {"success": False, "message": "Vendor-Schedule nicht mehr gefunden."}
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Vendor API Error: {resp.text}")
    try:
        response_payload = resp.json()
    except Exception:
        response_payload = {"success": True}
    if not isinstance(response_payload, dict):
        response_payload = {"success": True}
    return response_payload


@app.post("/api/jobs/{job_id}/social/sync")
async def sync_job_social_posts(job_id: str, req: SocialSyncRequest):
    _get_job_record_or_404(job_id)
    return await _sync_job_social_posts(job_id, req.api_key)


@app.post("/api/jobs/{job_id}/social/calendar")
async def get_job_social_calendar(job_id: str, req: SocialCalendarRequest):
    _get_job_record_or_404(job_id)
    if req.sync:
        try:
            payload = await _sync_job_social_posts(job_id, req.api_key)
        except HTTPException as exc:
            payload = {
                "success": True,
                "job_id": job_id,
                "result": build_job_result(_get_job_output_dir(job_id), job_id) or {"clips": []},
                "events": _build_job_social_calendar_events(job_id),
                "pending_items": _build_job_social_pending_items(job_id),
                "sync_errors": [{
                    "job_id": job_id,
                    "error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False),
                }],
                "sync_failed": True,
            }
            payload["summary"] = _build_social_calendar_summary(payload["events"])
            payload["pending_summary"] = _build_social_pending_summary(payload["pending_items"])
    else:
        payload = {
            "success": True,
            "job_id": job_id,
            "result": build_job_result(_get_job_output_dir(job_id), job_id) or {"clips": []},
            "events": _build_job_social_calendar_events(job_id),
            "pending_items": _build_job_social_pending_items(job_id),
        }
        payload["summary"] = _build_social_calendar_summary(payload["events"])
        payload["pending_summary"] = _build_social_pending_summary(payload["pending_items"])
        payload["sync_errors"] = []
    if "pending_items" not in payload:
        payload["pending_items"] = _build_job_social_pending_items(job_id)
    if "pending_summary" not in payload:
        payload["pending_summary"] = _build_social_pending_summary(payload["pending_items"])
    return payload


@app.post("/api/social/calendar")
async def get_global_social_calendar(req: SocialCalendarRequest):
    limit_jobs = int(req.limit_jobs or 0)
    job_summaries = list_job_summaries(
        OUTPUT_DIR,
        limit=limit_jobs if limit_jobs > 0 else 0,
        include_result=False,
        include_logs=False,
        log_limit=0,
    )
    events: List[Dict[str, Any]] = []
    pending_items: List[Dict[str, Any]] = []
    sync_errors: List[Dict[str, Any]] = []
    synced_jobs: List[Dict[str, Any]] = []
    vendor_calendar_complete = False

    for summary in job_summaries:
        job_id = summary.get("job_id")
        if not job_id:
            continue
        if req.user_id:
            manifest = load_job_manifest(_get_job_output_dir(str(job_id))) or {}
            request_meta = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
            if str(request_meta.get("upload_post_profile") or "").strip() != str(req.user_id).strip():
                continue
        if req.sync:
            try:
                payload = await _sync_job_social_posts(job_id, req.api_key)
                sync_errors.extend([{"job_id": job_id, **item} for item in payload.get("sync_errors") or []])
                synced_jobs.append({
                    "job_id": job_id,
                    "source_label": summary.get("source_label") or job_id,
                    "summary": payload.get("summary") or {},
                    "pending_summary": payload.get("pending_summary") or {},
                })
                events.extend(payload.get("events") or [])
                pending_items.extend(payload.get("pending_items") or [])
            except HTTPException as exc:
                job_events = _build_job_social_calendar_events(job_id)
                job_pending_items = _build_job_social_pending_items(job_id)
                sync_errors.append({
                    "job_id": job_id,
                    "error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False),
                })
                synced_jobs.append({
                    "job_id": job_id,
                    "source_label": summary.get("source_label") or job_id,
                    "summary": _build_social_calendar_summary(job_events),
                    "pending_summary": _build_social_pending_summary(job_pending_items),
                })
                events.extend(job_events)
                pending_items.extend(job_pending_items)
        else:
            job_events = _build_job_social_calendar_events(job_id)
            job_pending_items = _build_job_social_pending_items(job_id)
            synced_jobs.append({
                "job_id": job_id,
                "source_label": summary.get("source_label") or job_id,
                "summary": _build_social_calendar_summary(job_events),
                "pending_summary": _build_social_pending_summary(job_pending_items),
            })
            events.extend(job_events)
            pending_items.extend(job_pending_items)

    if req.sync and req.api_key:
        try:
            if req.user_id:
                all_vendor_schedules = await _list_upload_post_scheduled_posts(req.api_key)
                profile_schedules = _filter_upload_post_calendar_horizon(
                    all_vendor_schedules,
                    profile_username=req.user_id,
                )
                try:
                    queue_schedules = await _list_upload_post_queue_scheduled_posts(req.api_key, req.user_id)
                    vendor_calendar_complete = True
                except HTTPException as exc:
                    queue_schedules = []
                    sync_errors.append({
                        "job_id": "__upload_post_queue__",
                        "error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False),
                    })
                vendor_scheduled_items = _merge_upload_post_schedule_sources(
                    profile_schedules,
                    _filter_upload_post_calendar_horizon(queue_schedules, profile_username=req.user_id),
                )
            else:
                vendor_scheduled_items = _filter_upload_post_calendar_horizon(
                    await _list_upload_post_scheduled_posts(req.api_key)
                )
                vendor_calendar_complete = True
            events = _merge_global_calendar_with_vendor_schedules(events, vendor_scheduled_items)
        except HTTPException as exc:
            sync_errors.append({
                "job_id": "__upload_post__",
                "error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False),
            })

    events.sort(key=lambda item: _event_sort_timestamp(item.get("scheduled_date")))
    pending_items.sort(
        key=lambda item: (
            0 if item.get("status") == "failed" else 1,
            str(item.get("job_label") or "").lower(),
            int(item.get("clip_index") or 0),
        )
    )
    return {
        "success": True,
        "events": events,
        "summary": _build_social_calendar_summary(events),
        "pending_items": pending_items,
        "pending_summary": _build_social_pending_summary(pending_items),
        "jobs": synced_jobs,
        "sync_errors": sync_errors,
        "vendor_calendar_complete": vendor_calendar_complete,
        "calendar_horizon_days": UPLOAD_POST_CALENDAR_HORIZON_DAYS,
    }


@app.post("/api/social/calendar/podcast-campaign/repair")
async def repair_social_calendar_podcast_campaign(req: SocialCalendarPodcastCaptionPatchRequest):
    profile_username = str(req.user_id or "").strip()
    if not profile_username:
        raise HTTPException(status_code=400, detail="Upload-Post Profil fehlt.")
    if not str(req.api_key or "").strip():
        raise HTTPException(status_code=400, detail="Upload-Post API-Key fehlt.")

    vendor_schedules = _filter_upload_post_calendar_horizon(
        await _list_upload_post_scheduled_posts(req.api_key),
        profile_username=profile_username,
    )
    active_vendor_job_ids = {
        str(item.get("job_id") or item.get("id") or "").strip()
        for item in vendor_schedules
        if str(item.get("job_id") or item.get("id") or "").strip()
    }
    selected_job_ids = {
        str(job_id or "").strip()
        for job_id in (req.job_ids or [])
        if str(job_id or "").strip()
    } or None
    candidates, scan_stats = _build_podcast_caption_patch_candidates(
        profile_username,
        active_vendor_job_ids=active_vendor_job_ids,
        selected_job_ids=selected_job_ids,
    )
    preview_candidates = [
        {key: value for key, value in candidate.items() if not key.startswith("_")}
        for candidate in candidates
    ]
    caption_patch_count = sum(1 for candidate in candidates if candidate.get("caption_eligible"))
    relay_repair_count = sum(1 for candidate in candidates if candidate.get("relay_needs_repair"))
    relay_configured = bool(
        _normalize_podcast_relay_url(req.podcast_dm_relay_url)
        and str(req.podcast_dm_relay_password or "").strip()
    )

    base_payload = {
        "success": True,
        "execute": bool(req.execute),
        "profile_username": profile_username,
        "active_vendor_schedules": len(active_vendor_job_ids),
        "eligible_count": len(candidates),
        "caption_patch_count": caption_patch_count,
        "relay_repair_count": relay_repair_count,
        "relay_configured": relay_configured,
        "scan": scan_stats,
        "candidates": preview_candidates,
    }
    if not req.execute or not candidates:
        return base_payload

    # Replacements are deliberately serialized. Each one uploads platform-specific
    # metadata, then removes the old schedule only after the new job exists.
    semaphore = asyncio.Semaphore(1)
    results = await asyncio.gather(*[
        _repair_podcast_campaign_candidate(
            req.api_key,
            candidate,
            semaphore,
            profile_username=profile_username,
            relay_url=req.podcast_dm_relay_url,
            relay_password=req.podcast_dm_relay_password,
        )
        for candidate in candidates
    ])
    caption_patched = sum(1 for item in results if (item.get("caption_patch") or {}).get("success") is True)
    caption_failed = sum(1 for item in results if (item.get("caption_patch") or {}).get("success") is False)
    relay_registered = sum(1 for item in results if (item.get("relay_registration") or {}).get("success") is True)
    relay_failed = sum(1 for item in results if (item.get("relay_registration") or {}).get("success") is False)
    return {
        **base_payload,
        "results": results,
        "summary": {
            "caption_patched": caption_patched,
            "caption_failed": caption_failed,
            "relay_registered": relay_registered,
            "relay_failed": relay_failed,
            "relay_skipped_missing_configuration": relay_repair_count if relay_repair_count and not relay_configured else 0,
        },
    }


@app.post("/api/social/calendar/event/update")
async def update_social_calendar_event(req: SocialCalendarEventUpdateRequest):
    is_vendor_only = str(req.event_source or "").strip().lower() == "vendor_only" or (
        bool(str(req.vendor_job_id or "").strip()) and not bool(str(req.job_id or "").strip())
    )
    if is_vendor_only:
        vendor_job_id = str(req.vendor_job_id or "").strip()
        if not vendor_job_id:
            raise HTTPException(status_code=400, detail="vendor_job_id ist fuer Upload-Post-only Slots erforderlich.")
        normalized_scheduled_date = (req.scheduled_date or "").strip()
        if not normalized_scheduled_date:
            raise HTTPException(status_code=400, detail="scheduled_date ist erforderlich.")
        vendor_payload = await _patch_upload_post_schedule(
            req.api_key,
            vendor_job_id,
            {
                "scheduled_date": normalized_scheduled_date,
                "timezone": (req.timezone or "UTC").strip() or "UTC",
                "title": (req.title or "").strip(),
                "caption": req.description or "",
            },
        )
        return {
            "success": True,
            "vendor_job_id": vendor_job_id,
            "event": {
                "event_source": "vendor_only",
                "vendor_job_id": vendor_job_id,
                "scheduled_date": vendor_payload.get("scheduled_date") or normalized_scheduled_date,
                "timezone": vendor_payload.get("timezone") or (req.timezone or "UTC"),
                "title": vendor_payload.get("title") or req.title or "",
                "description": vendor_payload.get("caption") or req.description or "",
                "remote_preview_url": vendor_payload.get("preview_url") or "",
            },
        }

    _get_job_record_or_404(req.job_id)
    _, result, _ = _get_job_result_or_400(req.job_id)
    _, _, metadata_data = _load_job_metadata_or_404(req.job_id)
    clip = _find_result_clip(result, req.clip_index)
    history_entries, target_entry = _find_social_history_entry(clip, req.history_entry_id)
    request_settings = _social_post_request_settings_from_entry(clip, metadata_data, target_entry)
    requested_platforms = _normalize_social_platforms(req.platforms or target_entry.get("requested_platforms") or [])
    if not requested_platforms:
        raise HTTPException(status_code=400, detail="Keine Plattformen fuer diesen Kalender-Eintrag gespeichert.")

    normalized_scheduled_date = (req.scheduled_date or "").strip()
    if not normalized_scheduled_date:
        raise HTTPException(status_code=400, detail="scheduled_date ist erforderlich.")
    mode = (req.mode or "auto").strip().lower()
    if mode not in {"auto", "patch", "recreate"}:
        raise HTTPException(status_code=400, detail="mode muss auto, patch oder recreate sein.")

    effective_title = req.title if req.title is not None else request_settings.get("title")
    effective_description = req.description if req.description is not None else request_settings.get("description")
    effective_first_comment = req.first_comment if req.first_comment is not None else request_settings.get("first_comment")
    effective_timezone = req.timezone if req.timezone is not None else request_settings.get("timezone")
    effective_instagram_share_mode = req.instagram_share_mode if req.instagram_share_mode is not None else request_settings.get("instagram_share_mode")
    effective_instagram_collaborators = req.instagram_collaborators if req.instagram_collaborators is not None else request_settings.get("instagram_collaborators")
    effective_tiktok_post_mode = req.tiktok_post_mode if req.tiktok_post_mode is not None else request_settings.get("tiktok_post_mode")
    effective_tiktok_is_aigc = req.tiktok_is_aigc if req.tiktok_is_aigc is not None else request_settings.get("tiktok_is_aigc")
    effective_facebook_page_id = req.facebook_page_id if req.facebook_page_id is not None else request_settings.get("facebook_page_id")
    effective_pinterest_board_id = req.pinterest_board_id if req.pinterest_board_id is not None else request_settings.get("pinterest_board_id")

    patch_supported = _entry_supports_vendor_patch(target_entry, requested_platforms, req)
    if mode == "patch" and not patch_supported:
        raise HTTPException(
            status_code=400,
            detail="Text- oder Plattformeinstellungen brauchen ein neues Scheduling; PATCH ist nur fuer Datum/Zeit sicher.",
        )
    should_patch = mode == "patch" or (mode == "auto" and patch_supported)

    if should_patch:
        if not (target_entry.get("job_id") or "").strip():
            raise HTTPException(status_code=400, detail="Dieser Kalender-Eintrag ist nicht per Vendor-Schedule editierbar.")
        effective_instagram_caption = _resolve_instagram_podcast_caption(
            effective_description or "",
            requested_platforms=requested_platforms,
            podcast_campaign=request_settings.get("podcast_link_campaign"),
        )
        vendor_payload = await _patch_upload_post_schedule(
            req.api_key,
            str(target_entry.get("job_id")),
            {
                "scheduled_date": normalized_scheduled_date,
                "timezone": effective_timezone or "UTC",
            },
        )
        updated_entry = dict(target_entry)
        updated_request_settings = dict(request_settings)
        effective_instagram_first_comment = request_settings.get("instagram_first_comment")
        if request_settings.get("podcast_link_campaign") and "instagram" in requested_platforms:
            effective_instagram_first_comment = _compose_first_comment_with_podcast_cta(
                effective_first_comment or "",
                keyword=(request_settings.get("podcast_link_campaign") or {}).get("keyword") or "Video",
                template=(request_settings.get("podcast_link_campaign") or {}).get("comment_template"),
                generated_text=effective_description or "",
            )
        updated_request_settings.update({
            "title": effective_title,
            "description": effective_description,
            "first_comment": effective_first_comment,
            "scheduled_date": vendor_payload.get("scheduled_date") or normalized_scheduled_date,
            "timezone": effective_timezone or "UTC",
            "instagram_share_mode": effective_instagram_share_mode,
            "instagram_collaborators": _normalize_instagram_collaborators(effective_instagram_collaborators or "") or None,
            "tiktok_post_mode": effective_tiktok_post_mode,
            "tiktok_is_aigc": bool(effective_tiktok_is_aigc),
            "facebook_page_id": (effective_facebook_page_id or "").strip() or None,
            "pinterest_board_id": (effective_pinterest_board_id or "").strip() or None,
            "instagram_caption": effective_instagram_caption,
            "instagram_first_comment": effective_instagram_first_comment,
        })
        updated_entry["request_settings"] = updated_request_settings
        updated_entry["scheduled"] = True
        updated_entry["status"] = "scheduled"
        updated_entry["message"] = "Geplanter Post aktualisiert."
        updated_entry["updated_at"] = time.time()
        history_entries = [
            _normalize_social_post_history_entry(updated_entry) if str(entry.get("history_entry_id") or "") == str(target_entry.get("history_entry_id") or "") else entry
            for entry in history_entries
        ]
        updated_clip = _persist_clip_social_post_history(
            req.job_id,
            req.clip_index,
            history_entries,
            preferred_current_entry_id=str(target_entry.get("history_entry_id") or ""),
        )
    else:
        if mode == "patch":
            raise HTTPException(status_code=400, detail="Dieser Kalender-Eintrag braucht ein neues Scheduling statt PATCH.")
        updated_clip, _ = await _recreate_social_calendar_entry(
            job_id=req.job_id,
            clip_index=req.clip_index,
            api_key=req.api_key,
            user_id=req.user_id,
            requested_platforms=requested_platforms,
            target_entry=target_entry,
            scheduled_date=normalized_scheduled_date,
            title=effective_title,
            description=effective_description,
            first_comment=effective_first_comment,
            timezone=effective_timezone or "UTC",
            instagram_share_mode=effective_instagram_share_mode or "CUSTOM",
            instagram_collaborators=effective_instagram_collaborators,
            tiktok_post_mode=effective_tiktok_post_mode or "DIRECT_POST",
            tiktok_is_aigc=bool(effective_tiktok_is_aigc),
            facebook_page_id=effective_facebook_page_id,
            pinterest_board_id=effective_pinterest_board_id,
            history_source="calendar_reschedule",
            podcast_dm_relay_url=req.podcast_dm_relay_url,
            podcast_dm_relay_password=req.podcast_dm_relay_password,
        )

    events = _build_job_social_calendar_events(req.job_id)
    preferred_history_entry_id = str(((updated_clip or {}).get("social_post_status") or {}).get("history_entry_id") or req.history_entry_id or "")
    target_event = next(
        (
            event for event in events
            if event.get("job_id") == req.job_id
            and int(event.get("clip_index", -1)) == int(req.clip_index)
            and (not preferred_history_entry_id or str(event.get("history_entry_id") or "") == preferred_history_entry_id)
        ),
        None,
    )
    return {
        "success": True,
        "job_id": req.job_id,
        "clip": updated_clip,
        "event": target_event,
        "events": events,
        "summary": _build_social_calendar_summary(events),
    }


@app.post("/api/social/calendar/event/delete")
async def delete_social_calendar_event(req: SocialCalendarEventDeleteRequest):
    is_vendor_only = str(req.event_source or "").strip().lower() == "vendor_only" or (
        bool(str(req.vendor_job_id or "").strip()) and not bool(str(req.job_id or "").strip())
    )
    if is_vendor_only:
        vendor_job_id = str(req.vendor_job_id or "").strip()
        if not vendor_job_id:
            raise HTTPException(status_code=400, detail="vendor_job_id ist fuer Upload-Post-only Slots erforderlich.")
        await _delete_upload_post_schedule(req.api_key, vendor_job_id)
        return {
            "success": True,
            "vendor_job_id": vendor_job_id,
            "deleted_history_entry_id": f"vendor:{vendor_job_id}",
        }

    _get_job_record_or_404(req.job_id)
    _, result, _ = _get_job_result_or_400(req.job_id)
    clip = _find_result_clip(result, req.clip_index)
    history_entries, target_entry = _find_social_history_entry(clip, req.history_entry_id)

    vendor_job_id = (target_entry.get("job_id") or "").strip()
    if vendor_job_id and _entry_is_future_scheduled(target_entry):
        try:
            await _delete_upload_post_schedule(req.api_key, vendor_job_id)
        except HTTPException as exc:
            if exc.status_code not in {404}:
                raise

    next_history = [
        _mark_social_history_entry_deleted(entry, message="Im Kalender geloescht.")
        if str(entry.get("history_entry_id") or "") == str(target_entry.get("history_entry_id") or "")
        else entry
        for entry in history_entries
    ]
    updated_clip = _persist_clip_social_post_history(req.job_id, req.clip_index, next_history)
    events = _build_job_social_calendar_events(req.job_id)
    return {
        "success": True,
        "job_id": req.job_id,
        "clip": updated_clip,
        "deleted_history_entry_id": target_entry.get("history_entry_id"),
        "events": events,
        "summary": _build_social_calendar_summary(events),
    }


@app.post("/api/social/calendar/event/resolve-preview")
async def resolve_social_calendar_event_preview(req: SocialCalendarEventPreviewRequest):
    vendor_job_id = str(req.vendor_job_id or "").strip()
    if not vendor_job_id:
        raise HTTPException(status_code=400, detail="vendor_job_id ist erforderlich.")

    item = await _resolve_upload_post_preview_item(
        req.api_key,
        vendor_job_id,
        profile_username=(req.user_id or "").strip() or None,
    )
    if not item:
        return {
            "success": True,
            "vendor_job_id": vendor_job_id,
            "preview_url": "",
            "item": None,
            "message": "Upload-Post liefert fuer diesen Slot aktuell keine Preview-URL.",
        }

    event = _build_vendor_only_social_calendar_event(item) or {}
    return {
        "success": True,
        "vendor_job_id": vendor_job_id,
        "preview_url": event.get("remote_preview_url") or "",
        "item": item,
        "event": event,
    }


@app.post("/api/jobs/{job_id}/social/reschedule-all")
async def reschedule_all_job_social_calendar_events(job_id: str, req: SocialCalendarBulkRescheduleRequest):
    _get_job_record_or_404(job_id)
    sync_errors: List[Dict[str, Any]] = []
    if req.sync:
        try:
            await _sync_job_social_posts(job_id, req.api_key)
        except HTTPException as exc:
            sync_errors.append({
                "job_id": job_id,
                "error": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False),
            })

    _, result, _ = _get_job_result_or_400(job_id)
    clips = result.get("clips") or []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    processed_count = 0
    skipped_count = 0
    failed_items: List[Dict[str, Any]] = []

    for clip_index, clip in enumerate(clips):
        history_entries = _get_clip_social_post_history(clip, include_current_fallback=True)
        for entry in history_entries:
            if entry.get("hidden") or entry.get("deleted"):
                continue
            request_settings = _normalize_social_post_request_settings(entry.get("request_settings")) or {}
            scheduled_dt = _parse_iso_datetime(request_settings.get("scheduled_date"))
            if not scheduled_dt:
                skipped_count += 1
                continue
            if scheduled_dt.tzinfo is None:
                scheduled_dt = scheduled_dt.replace(tzinfo=datetime.timezone.utc)
            if bool(req.future_only) and scheduled_dt <= now_utc:
                skipped_count += 1
                continue

            requested_platforms = _normalize_social_platforms(entry.get("requested_platforms") or [])
            if not requested_platforms:
                skipped_count += 1
                continue

            try:
                await _recreate_social_calendar_entry(
                    job_id=job_id,
                    clip_index=clip_index,
                    api_key=req.api_key,
                    user_id=req.user_id,
                    target_entry=entry,
                    requested_platforms=requested_platforms,
                    scheduled_date=request_settings.get("scheduled_date") or "",
                    title=request_settings.get("title"),
                    description=request_settings.get("description"),
                    first_comment=request_settings.get("first_comment"),
                    timezone=request_settings.get("timezone") or "UTC",
                    instagram_share_mode=request_settings.get("instagram_share_mode") or "CUSTOM",
                    instagram_collaborators=request_settings.get("instagram_collaborators"),
                    tiktok_post_mode=request_settings.get("tiktok_post_mode") or "DIRECT_POST",
                    tiktok_is_aigc=bool(request_settings.get("tiktok_is_aigc")),
                    facebook_page_id=request_settings.get("facebook_page_id"),
                    pinterest_board_id=request_settings.get("pinterest_board_id"),
                    history_source="calendar_reschedule",
                    podcast_dm_relay_url=req.podcast_dm_relay_url,
                    podcast_dm_relay_password=req.podcast_dm_relay_password,
                )
                processed_count += 1
            except Exception as exc:
                failed_items.append({
                    "clip_index": clip_index,
                    "history_entry_id": entry.get("history_entry_id"),
                    "error": str(exc),
                })

    events = _build_job_social_calendar_events(job_id)
    return {
        "success": len(failed_items) == 0,
        "job_id": job_id,
        "result": build_job_result(_get_job_output_dir(job_id), job_id) or {"clips": []},
        "events": events,
        "summary": _build_social_calendar_summary(events),
        "rescheduled_count": processed_count,
        "skipped_count": skipped_count,
        "failed_count": len(failed_items),
        "failed_items": failed_items,
        "sync_errors": sync_errors,
    }


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
        except httpx.RequestError as e:
             message = _format_outbound_network_error("Upload-Post", url, e)
             print(f"⚠️ {message}")
             return {
                 "profiles": [],
                 "error": message,
                 "recoverable": True,
             }
        except Exception as e:
             raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/network/diagnostics")
async def get_network_diagnostics():
    return {
        "in_docker": os.path.exists("/.dockerenv"),
        "network_mode": (os.environ.get("NETWORK_MODE") or "").strip().lower() or "unknown",
        "resolver_config": _read_resolver_config_preview(),
        "targets": [
            _diagnose_hostname_resolution(host, port)
            for host, port in NETWORK_DIAGNOSTIC_TARGETS
        ],
    }

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
