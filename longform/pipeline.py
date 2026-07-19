from __future__ import annotations

import json
import logging
import os
import random
import shutil
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .analysis import LongformStopRequested, analyze_project, compute_sync_map, refine_sync_with_transcripts, transcribe_project_files
from .export_fcpxml import export_fcpxml, export_json, export_markers_csv
from .ffmpeg_ops import (
    create_proxy,
    export_audio_channel_stem,
    export_audio_stereo_program,
    extract_audio_analysis,
    extract_thumbnail_frames,
    media_url_from_path,
    probe_media,
    slugify_filename,
    transcode_to_cfr,
)
from .models import build_initial_state
from .storage import (
    append_log,
    clear_project_derived_artifacts,
    load_project,
    load_state,
    mark_running_projects_paused,
    project_dir,
    project_subdir,
    save_project,
    save_state,
)

LOGGER = logging.getLogger(__name__)

_pipeline_threads: Dict[str, threading.Thread] = {}
_pipeline_stop_events: Dict[str, threading.Event] = {}
_pipeline_lock = threading.Lock()
STEP_BASE_PROGRESS = {
    'ingest': 0.12,
    'transcription': 0.42,
    'sync': 0.68,
    'analysis': 0.82,
    'export': 0.94,
}
STEP_PROGRESS_SPAN = {
    'ingest': 0.24,
    'transcription': 0.22,
    'sync': 0.08,
    'analysis': 0.12,
    'export': 0.06,
}
STEP_DURATION_HINTS = {
    'ingest': 0.55,
    'transcription': 0.22,
    'sync': 0.08,
    'analysis': 0.10,
    'export': 0.05,
}


def _log(project_id: str, message: str) -> None:
    LOGGER.info('longform[%s] %s', project_id, message)
    append_log(project_id, message)


def _stop_requested(project_id: str) -> bool:
    event = _pipeline_stop_events.get(project_id)
    return bool(event and event.is_set())


def _set_state(project_id: str, **updates: Any) -> Dict[str, Any]:
    state = load_state(project_id)
    state.update(updates)
    save_state(project_id, state)
    return state


def _format_eta(seconds: Optional[float]) -> str:
    if seconds is None:
        return '—'
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours:d}:{minutes:02d}:{secs:02d}'
    return f'{minutes:02d}:{secs:02d}'


def _set_step(project_id: str, step_name: str, *, status: str, message: str = '', error: Optional[str] = None) -> Dict[str, Any]:
    state = load_state(project_id)
    step = (state.get('steps') or {}).get(step_name) or {}
    now = time.time()
    step['status'] = status
    step['message'] = message
    step['error'] = error
    if status == 'processing':
        step['started_at'] = step.get('started_at') or now
        step['completed_at'] = None
    elif status in {'completed', 'failed', 'skipped'}:
        step['completed_at'] = now
    state.setdefault('steps', {})[step_name] = step
    state['current_step'] = step_name if status == 'processing' else state.get('current_step')
    state['updated_at'] = now
    save_state(project_id, state)
    return state


def _mark_processing(project_id: str, step_name: str, message: str, progress: float) -> None:
    state = load_state(project_id)
    now = time.time()
    state['status'] = 'processing'
    state['current_step'] = step_name
    state['message'] = message
    state['progress'] = progress
    state['step_progress'] = 0.0
    state['step_eta_seconds'] = None
    state['eta_seconds'] = None
    state['error'] = None
    state['resume_available'] = False
    state['stop_requested'] = False
    state['started_at'] = state.get('started_at') or now
    timings = dict(state.get('timings') or {})
    timings['step_started_at'] = now
    timings['step_elapsed_seconds'] = 0.0
    timings['elapsed_seconds'] = max(0.0, now - float(state['started_at']))
    state['timings'] = timings
    save_state(project_id, state)
    _set_step(project_id, step_name, status='processing', message=message)


def _update_progress(project_id: str, step_name: str, step_progress: float, message: Optional[str] = None, *, detail: Optional[Dict[str, Any]] = None) -> None:
    state = load_state(project_id)
    now = time.time()
    started_at = float(state.get('started_at') or now)
    step_started_at = float(((state.get('timings') or {}).get('step_started_at')) or now)
    normalized_step_progress = max(0.0, min(1.0, float(step_progress or 0.0)))
    base_progress = STEP_BASE_PROGRESS.get(step_name, 0.0)
    step_span = STEP_PROGRESS_SPAN.get(step_name, 0.0)
    total_progress = max(state.get('progress') or 0.0, min(0.995, base_progress + normalized_step_progress * step_span))

    step_elapsed = max(0.0, now - step_started_at)
    total_elapsed = max(0.0, now - started_at)
    step_eta = None
    if normalized_step_progress > 0.001:
      step_eta = max(0.0, step_elapsed * (1.0 - normalized_step_progress) / normalized_step_progress)

    remaining_weight = max(0.0, 1.0 - normalized_step_progress) * STEP_DURATION_HINTS.get(step_name, 0.0)
    for candidate_step, weight in STEP_DURATION_HINTS.items():
        if STEP_BASE_PROGRESS.get(candidate_step, 0.0) > STEP_BASE_PROGRESS.get(step_name, 0.0):
            remaining_weight += weight
    total_eta = None
    if normalized_step_progress > 0.001:
        total_eta = max(0.0, step_elapsed * remaining_weight / max(0.001, normalized_step_progress * STEP_DURATION_HINTS.get(step_name, 0.0)))

    state['status'] = 'processing'
    state['current_step'] = step_name
    state['progress'] = total_progress
    state['step_progress'] = normalized_step_progress
    state['step_eta_seconds'] = step_eta
    state['eta_seconds'] = total_eta
    if message:
        state['message'] = message
    timings = dict(state.get('timings') or {})
    timings['step_started_at'] = step_started_at
    timings['step_elapsed_seconds'] = step_elapsed
    timings['elapsed_seconds'] = total_elapsed
    state['timings'] = timings
    if detail is not None:
        state['step_detail'] = detail
    save_state(project_id, state)
    step_message = message or state.get('message') or ''
    _set_step(project_id, step_name, status='processing', message=step_message)


def _mark_completed(project_id: str, summary: Dict[str, Any], project: Dict[str, Any]) -> None:
    state = load_state(project_id)
    state['status'] = 'completed'
    state['current_step'] = None
    state['message'] = 'Longform-Rohschnitt fertig.'
    state['progress'] = 1.0
    state['error'] = None
    state['resume_available'] = False
    state['completed_at'] = time.time()
    state['summary'] = summary or {}
    save_state(project_id, state)
    save_project(project)
    _log(project_id, 'Pipeline abgeschlossen.')


def _mark_paused(project_id: str, message: str) -> None:
    state = load_state(project_id)
    state['status'] = 'paused'
    state['message'] = message
    state['resume_available'] = True
    state['stop_requested'] = False
    state['current_step'] = None
    save_state(project_id, state)
    _log(project_id, message)


def _mark_failed(project_id: str, error: str) -> None:
    state = load_state(project_id)
    state['status'] = 'failed'
    state['message'] = error
    state['error'] = error
    state['resume_available'] = True
    state['current_step'] = None
    save_state(project_id, state)
    _log(project_id, f'Fehler: {error}')


def _remove_invalid_artifact(project_id: str, path: Optional[str], label: str) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
            _log(project_id, f'Ingest: Defektes {label}-Artefakt verworfen ({os.path.basename(path)})')
    except Exception:
        LOGGER.exception('Failed to remove invalid longform artifact %s', path)


def _validated_reusable_media_path(project_id: str, candidate_path: Optional[str], label: str) -> Optional[str]:
    if not candidate_path or not os.path.exists(candidate_path):
        return None
    try:
        probe_media(candidate_path)
        return candidate_path
    except Exception as exc:
        _log(project_id, f'Ingest: {label} ungueltig ({os.path.basename(candidate_path)}): {exc}')
        _remove_invalid_artifact(project_id, candidate_path, label)
        return None


def _run_ingest(project: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project['project_id']
    config = project.get('config') or {}
    fps = int(config.get('export_fps') or 25)
    sample_rate = int(config.get('target_sample_rate') or 48000)
    proxy_height = int(config.get('proxy_height') or 720)
    cfr_enabled = bool(config.get('cfr_transcode_enabled', True))
    proxy_enabled = bool(config.get('proxy_enabled', False))
    ingest_items = []
    for role, role_files in (project.get('files') or {}).items():
        for item in sorted(role_files or [], key=lambda raw: int(raw.get('order') or 0)):
            ingest_items.append((role, item))
    total_units = max(1.0, sum(max(1.0, float((item or {}).get('duration_sec') or 0.0)) for _, item in ingest_items))
    completed_units = 0.0

    for index, (role, item) in enumerate(ingest_items, start=1):
            if _stop_requested(project_id):
                raise LongformStopRequested('Longform processing stopped by user.')
            source_path = item.get('stored_path')
            safe_base = slugify_filename(os.path.splitext(item.get('original_name') or item.get('id') or 'clip')[0])
            safe_original_name = slugify_filename(item.get('original_name') or f"{item.get('id') or 'clip'}.bin")
            project_source_path = os.path.join(project_subdir(project_id, 'source'), f"{item['id']}_{safe_original_name}")
            normalized_path = os.path.join(project_subdir(project_id, 'normalized'), f"{item['id']}_{safe_base}.mp4")
            proxy_path = os.path.join(project_subdir(project_id, 'proxies'), f"{item['id']}_{safe_base}_proxy.mp4")
            audio_path = os.path.join(project_subdir(project_id, 'audio'), f"{item['id']}.flac")
            source_is_temporary = str(item.get('source_storage') or '').strip().lower().startswith('temporary_upload')
            source_exists = bool(source_path and os.path.exists(source_path))
            reusable_media_path = _validated_reusable_media_path(project_id, item.get('normalized_path'), 'normalized')
            if reusable_media_path is None:
                reusable_media_path = _validated_reusable_media_path(project_id, normalized_path, 'normalized')
            item_duration = max(1.0, float(item.get('duration_sec') or 0.0))

            def ingest_progress(stage_label: str, stage_ratio: float, *, speed: str = '') -> None:
                per_item_share = item_duration / total_units
                overall_ratio = min(0.999, (completed_units + item_duration * max(0.0, min(1.0, stage_ratio))) / total_units)
                speed_suffix = f' · speed {speed}' if speed else ''
                _update_progress(
                    project_id,
                    'ingest',
                    overall_ratio,
                    f'Ingest {index}/{len(ingest_items)} · {stage_label} · {item.get("original_name")}{speed_suffix}',
                    detail={
                        'item_index': index,
                        'item_count': len(ingest_items),
                        'item_name': item.get('original_name'),
                        'item_stage': stage_label,
                        'item_stage_progress': max(0.0, min(1.0, stage_ratio)),
                    },
                )

            if not source_exists and not reusable_media_path:
                raise RuntimeError(f"Quelldatei fehlt: {item.get('original_name')}")

            if source_exists and source_is_temporary and not cfr_enabled:
                if not os.path.exists(project_source_path):
                    _log(project_id, f"Ingest: Originaldatei wird ohne Normalisierung ins Projekt uebernommen fuer {item.get('original_name')}")
                    os.makedirs(os.path.dirname(project_source_path), exist_ok=True)
                    shutil.move(source_path, project_source_path)
                source_path = project_source_path
                source_exists = True
                source_is_temporary = False
                item['stored_path'] = project_source_path
                item['source_storage'] = 'project_source'
                item['source_deleted_at'] = None
                item['normalized_path'] = None

            if source_exists and (cfr_enabled or source_is_temporary):
                normalized_ready = _validated_reusable_media_path(project_id, normalized_path, 'normalized')
                if not normalized_ready:
                    if cfr_enabled:
                        _log(project_id, f"Ingest: CFR-Transcode fuer {item.get('original_name')}")
                        transcode_to_cfr(
                            source_path,
                            normalized_path,
                            fps=fps,
                            sample_rate=sample_rate,
                            duration_sec=item_duration,
                            progress_cb=lambda payload, name=item.get('original_name'): ingest_progress('CFR-Transcode', payload.get('ratio', 0.0) * 0.62, speed=str(payload.get('speed') or '')),
                        )
                    else:
                        _log(project_id, f"Ingest: Temporaeren Upload in Arbeitskopie uebernehmen fuer {item.get('original_name')}")
                        shutil.copy2(source_path, normalized_path)
                active_media_path = normalized_path
                item['normalized_path'] = normalized_path
            elif source_exists:
                active_media_path = source_path
                item['normalized_path'] = None
            else:
                active_media_path = reusable_media_path
                item['normalized_path'] = reusable_media_path

            metadata = probe_media(active_media_path)
            item.update(metadata)
            item['duration_sec'] = float(metadata.get('duration_sec') or item.get('duration_sec') or 0.0)
            item['fps'] = float(metadata.get('fps') or fps or 25)

            audio_ready = _validated_reusable_media_path(project_id, item.get('audio_path') or audio_path, 'audio')
            if not audio_ready:
                _log(project_id, f"Ingest: Audio-Extraktion fuer {item.get('original_name')}")
                extract_audio_analysis(
                    active_media_path,
                    audio_path,
                    sample_rate=16000,
                    duration_sec=item_duration,
                    progress_cb=lambda payload: ingest_progress('Audio-Extraktion', 0.62 + payload.get('ratio', 0.0) * 0.18, speed=str(payload.get('speed') or '')),
                )
            item['audio_path'] = audio_path

            if proxy_enabled:
                proxy_ready = _validated_reusable_media_path(project_id, item.get('proxy_path') or proxy_path, 'proxy')
                if not proxy_ready:
                    _log(project_id, f"Ingest: Proxy-Erzeugung fuer {item.get('original_name')}")
                    create_proxy(
                        active_media_path,
                        proxy_path,
                        fps=fps,
                        height=proxy_height,
                        duration_sec=item_duration,
                        progress_cb=lambda payload: ingest_progress('Proxy-Erzeugung', 0.80 + payload.get('ratio', 0.0) * 0.18, speed=str(payload.get('speed') or '')),
                    )
                item['proxy_path'] = proxy_path
            else:
                item['proxy_path'] = None

            if source_exists and source_is_temporary and active_media_path != source_path:
                try:
                    os.remove(source_path)
                    item['stored_path'] = None
                    item['source_storage'] = 'temporary_upload_purged'
                    item['source_deleted_at'] = time.time()
                    _log(project_id, f"Ingest: Original-Upload freigegeben fuer {item.get('original_name')}")
                except OSError:
                    LOGGER.exception('Failed to remove temporary longform source %s', source_path)
            completed_units += item_duration
            ingest_progress('Abgeschlossen', 1.0)

    save_project(project)
    return project


def _sync_report_path(project_id: str) -> str:
    return os.path.join(project_subdir(project_id, 'analysis'), 'sync_report.json')


def _analysis_result_path(project_id: str) -> str:
    return os.path.join(project_subdir(project_id, 'analysis'), 'analysis_result.json')


def _run_sync(project: Dict[str, Any], transcript_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    project_id = project['project_id']
    report = compute_sync_map(
        project,
        logger=lambda msg: _log(project_id, msg),
        stop_checker=lambda: _stop_requested(project_id),
        transcript_map=transcript_map,
    )
    with open(_sync_report_path(project_id), 'w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    save_project(project)
    return report


def _run_transcription(project: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project['project_id']

    def handle_transcription_progress(payload: Dict[str, Any]) -> None:
        role = str(payload.get('role') or '').strip()
        role_label = role or 'clip'
        item_name = str(payload.get('item_name') or 'Datei').strip()
        item_stage = str(payload.get('item_stage') or 'Dekodiere').strip()
        decoded_audio_label = str(payload.get('decoded_audio_label') or '00:00').strip()
        runtime = payload.get('runtime') or {}
        runtime_bits: List[str] = []
        if runtime.get('device'):
            runtime_bits.append(str(runtime.get('device')))
        if runtime.get('model'):
            runtime_bits.append(str(runtime.get('model')))
        if runtime.get('word_timestamps') is False:
            runtime_bits.append('ohne Wort-Timestamps')
        runtime_label = ' · '.join(bit for bit in runtime_bits if bit)
        message = f"Whisper: {item_name} ({role_label}) · {item_stage}"
        if item_stage.lower() in {'dekodiere', 'abgeschlossen', 'bereits vorhanden'}:
            message += f" · {decoded_audio_label}"
        if runtime_label:
            message += f" · {runtime_label}"
        _update_progress(
            project_id,
            'transcription',
            float(payload.get('overall_ratio') or 0.0),
            message,
            detail={
                'item_name': item_name,
                'item_role': role_label,
                'item_stage': item_stage,
                'item_stage_progress': float(payload.get('item_stage_progress') or 0.0),
                'item_index': int(payload.get('item_index') or 0),
                'item_count': int(payload.get('item_count') or 0),
                'decoded_audio_seconds': float(payload.get('decoded_audio_seconds') or 0.0),
                'decoded_audio_label': decoded_audio_label,
                'decoded_segments': int(payload.get('decoded_segments') or 0),
                'runtime_label': runtime_label,
                'retry_reason': str(payload.get('retry_reason') or '').strip(),
            },
        )

    result = transcribe_project_files(
        project,
        logger=lambda msg: _log(project_id, msg),
        stop_checker=lambda: _stop_requested(project_id),
        progress_cb=handle_transcription_progress,
    )
    save_project(project)
    return result


def _run_analysis(project: Dict[str, Any], transcript_map: Dict[str, Any], sync_report: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project['project_id']
    sync_report = refine_sync_with_transcripts(
        project,
        transcript_map,
        sync_report,
        logger=lambda msg: _log(project_id, msg),
    )
    with open(_sync_report_path(project_id), 'w', encoding='utf-8') as handle:
        json.dump(sync_report, handle, ensure_ascii=False, indent=2)
    save_project(project)
    analysis = analyze_project(project, transcript_map, logger=lambda msg: _log(project_id, msg), stop_checker=lambda: _stop_requested(project_id))
    analysis['sync_report'] = sync_report
    with open(_analysis_result_path(project_id), 'w', encoding='utf-8') as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2)
    return analysis


def _export_primary_audio_stereo_artifacts(project: Dict[str, Any], exports_dir: str, base_name: str) -> Dict[str, Dict[str, Any]]:
    config = project.get('config') or {}
    if not bool(config.get('export_primary_audio_stereo_enabled')):
        return {}

    primary_role = str(config.get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')).strip().lower()
    role_items = sorted((project.get('files') or {}).get(primary_role) or [], key=lambda raw: int(raw.get('order') or 0))
    source_paths = [
        str(item.get('normalized_path') or item.get('stored_path') or '').strip()
        for item in role_items
        if str(item.get('normalized_path') or item.get('stored_path') or '').strip()
    ]
    if not source_paths:
        return {}

    stereo_path = os.path.join(exports_dir, f'{base_name}_primary_audio_stereo.wav')
    left_path = os.path.join(exports_dir, f'{base_name}_primary_audio_left.wav')
    right_path = os.path.join(exports_dir, f'{base_name}_primary_audio_right.wav')

    export_audio_stereo_program(source_paths, stereo_path)
    export_audio_channel_stem(stereo_path, left_path, channel='left')
    export_audio_channel_stem(stereo_path, right_path, channel='right')

    return {
        'primary_audio_stereo': {
            'path': stereo_path,
            'url': media_url_from_path(stereo_path),
            'name': os.path.basename(stereo_path),
        },
        'primary_audio_left': {
            'path': left_path,
            'url': media_url_from_path(left_path),
            'name': os.path.basename(left_path),
        },
        'primary_audio_right': {
            'path': right_path,
            'url': media_url_from_path(right_path),
            'name': os.path.basename(right_path),
        },
    }


def _run_export(project: Dict[str, Any], analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    project_id = project['project_id']
    exports_dir = project_subdir(project_id, 'exports')
    base_name = slugify_filename(project.get('project_name') or project_id)

    def update_export_progress(progress_ratio: float, message: str, *, detail: Optional[Dict[str, Any]] = None) -> None:
        _update_progress(project_id, 'export', progress_ratio, message, detail=detail)

    def handle_fcpxml_progress(payload: Dict[str, Any]) -> None:
        stage = str(payload.get('stage') or '').strip().lower()
        ratio = max(0.0, min(1.0, float(payload.get('ratio') or 0.0)))
        message = str(payload.get('message') or 'Export laeuft.')
        step_ratio = 0.12
        if stage == 'assets':
            step_ratio = 0.14
        elif stage == 'loudness':
            step_ratio = 0.14 + ratio * 0.52
        elif stage == 'rough_cut':
            step_ratio = 0.70
        elif stage == 'stringouts':
            step_ratio = 0.82
        elif stage == 'write':
            step_ratio = 0.88
        detail = {
            'item_stage': payload.get('message') or message,
            'item_name': payload.get('item_name') or '',
            'item_index': payload.get('item_index') or 0,
            'item_count': payload.get('item_count') or 0,
            'speed': payload.get('speed') or '',
        }
        update_export_progress(step_ratio, message, detail=detail)

    update_export_progress(0.12, 'Export: FCPXML wird aufgebaut.')
    fcpxml_meta = export_fcpxml(
        project,
        analysis_result,
        os.path.join(exports_dir, f'{base_name}.fcpxml'),
        logger=lambda msg: _log(project_id, msg),
        progress_cb=handle_fcpxml_progress,
    )
    update_export_progress(0.90, 'Export: Analyse-Dateien werden geschrieben.')
    _log(project_id, f"Export: Analyseentscheidungen werden gespeichert ({base_name}_decisions.json).")
    decisions_meta = export_json(analysis_result, os.path.join(exports_dir, f'{base_name}_decisions.json'))
    markers_payload = [*(analysis_result.get('review_markers') or []), *(analysis_result.get('reaction_markers') or [])]
    update_export_progress(0.94, 'Export: Marker-CSV wird geschrieben.')
    _log(project_id, f"Export: Marker werden gespeichert ({base_name}_markers.csv).")
    markers_meta = export_markers_csv(markers_payload, os.path.join(exports_dir, f'{base_name}_markers.csv'))
    update_export_progress(0.97, 'Export: Sync-Report wird geschrieben.')
    _log(project_id, f"Export: Sync-Report wird gespeichert ({base_name}_sync.json).")
    sync_meta = export_json(analysis_result.get('sync_report') or {}, os.path.join(exports_dir, f'{base_name}_sync.json'))
    stereo_artifacts = {}
    if bool((project.get('config') or {}).get('export_primary_audio_stereo_enabled')):
        update_export_progress(0.985, 'Export: Hauptaudio wird als Stereo/Links/Rechts exportiert.')
        _log(project_id, f"Export: Stereo-Hauptaudio wird geschrieben ({base_name}_primary_audio_stereo.wav).")
        stereo_artifacts = _export_primary_audio_stereo_artifacts(project, exports_dir, base_name)
    update_export_progress(1.0, 'Export abgeschlossen.')

    # Include loudness normalize settings in artifacts
    loudness_normalize = fcpxml_meta.get('loudness_normalize_settings')
    loudness_json_meta = fcpxml_meta.get('loudness_json')

    project['artifacts'] = {
        'fcpxml': fcpxml_meta,
        'decisions_json': decisions_meta,
        'markers_csv': markers_meta,
        'sync_json': sync_meta,
        'analysis_json': {
            'path': _analysis_result_path(project_id),
            'url': None,
            'name': os.path.basename(_analysis_result_path(project_id)),
        },
        **stereo_artifacts,
    }

    # Store loudness normalization settings for DaVinci Resolve
    if loudness_normalize:
        project['artifacts']['loudness_normalize'] = loudness_normalize
        project['loudness_normalize_settings'] = loudness_normalize
        _log(project_id, f"Export: Lautheits-Info verfuegbar fuer Resolve ({loudness_normalize.get('primary_role')}: {loudness_normalize.get('primary_role_avg_lufs')} LUFS)")
    else:
        project['artifacts'].pop('loudness_normalize', None)
        project.pop('loudness_normalize_settings', None)
    save_project(project)
    return project['artifacts']


def _run_thumbnail_extraction(project: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract thumbnail frames from video files for AI thumbnail generation.
    Creates 5 evenly spaced frames from each camera source.
    """
    project_id = project['project_id']
    config = project.get('config') or {}
    mode = project.get('mode') or 'single'
    primary_role = config.get('primary_audio_camera') or ('host' if mode == 'interview' else 'single')

    thumbs_dir = project_subdir(project_id, 'thumbnails')
    os.makedirs(thumbs_dir, exist_ok=True)

    extracted_thumbs: Dict[str, List[str]] = {}
    total_videos = 0
    completed_videos = 0

    # Count total videos to process
    for role in (project.get('files') or {}).keys():
        if mode == 'interview' and role not in ('host', primary_role):
            continue  # Skip guest for thumbnails in interview mode
        for _ in (project.get('files') or {}).get(role) or []:
            total_videos += 1

    for role in (project.get('files') or {}).keys():
        if mode == 'interview' and role not in ('host', primary_role):
            continue  # Skip guest for thumbnails in interview mode

        role_thumbs: List[str] = []
        for item in sorted((project.get('files') or {}).get(role) or [], key=lambda r: int(r.get('order') or 0)):
            if _stop_requested(project_id):
                raise LongformStopRequested('Longform processing stopped by user.')

            completed_videos += 1
            _update_progress(
                project_id,
                'export',
                0.98 + (completed_videos / max(1, total_videos)) * 0.02,
                f'Thumbnails: Extrahiere Frames von {item.get("original_name")}... ({completed_videos}/{total_videos})',
            )

            # Use normalized video if available, otherwise stored path
            video_path = item.get('normalized_path') or item.get('stored_path')
            if not video_path or not os.path.exists(video_path):
                continue

            role_dir = os.path.join(thumbs_dir, role)
            try:
                frames = extract_thumbnail_frames(
                    video_path=video_path,
                    output_dir=role_dir,
                    num_frames=5,
                    width=640,
                    quality=85,
                    seek_offset_sec=5.0,
                )
                # Convert to relative URLs for the frontend
                relative_paths = [f'/thumbnails/{project_id}/{role}/{os.path.basename(p)}' for p in frames]
                role_thumbs.extend(relative_paths)
                _log(project_id, f'Thumbnail: {len(frames)} Frames extrahiert aus {item.get("original_name")} ({role})')
            except Exception as exc:
                LOGGER.warning(f'Failed to extract thumbnails from {video_path}: {exc}')

        if role_thumbs:
            extracted_thumbs[role] = role_thumbs

    # Save thumbnail manifest
    manifest_path = os.path.join(thumbs_dir, 'manifest.json')
    manifest = {
        'project_id': project_id,
        'extracted_thumbs': extracted_thumbs,
        'primary_role': primary_role,
    }
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    _log(project_id, f'Thumbnail-Extraktion abgeschlossen: {len(extracted_thumbs)} Rollen, verfuerfuegbar fuer AI-Generierung.')
    return manifest


def _auto_generate_thumbnail_text_overlays(project: Dict[str, Any], *, count: int = 10) -> Dict[str, Any]:
    project_id = project['project_id']
    config = project.get('config') or {}
    existing = config.get('thumbnail_text_overlay_suggestions') or []
    if existing:
        _log(project_id, 'Thumbnail-Text-Overlays bereits vorhanden, ueberspringe Initial-Generierung.')
        return {'success': True, 'overlays': existing, 'skipped': True}

    prompt = str(config.get('thumbnail_prompt_text') or '').strip()
    if not prompt:
        _log(project_id, 'Thumbnail-Text-Overlays uebersprungen: kein Thumbnail-Prompt konfiguriert.')
        return {'success': False, 'skipped': True, 'reason': 'missing_prompt'}

    payload = json.dumps({
        'prompt': prompt,
        'count': max(1, min(int(count or 10), 20)),
        'ai': project.get('ai') or {},
    }).encode('utf-8')
    request = urllib.request.Request(
        f'http://127.0.0.1:8000/api/longform/projects/{project_id}/thumbnail-text-overlays',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read().decode('utf-8', errors='replace')
        parsed = json.loads(body or '{}')
        overlays = parsed.get('overlays') or []
        _log(project_id, f'Thumbnail-Text-Overlays automatisch generiert ({len(overlays)} Vorschlaege).')
        return parsed
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Thumbnail-Text-Overlays HTTP {exc.code}: {detail or exc.reason}') from exc
    except Exception as exc:
        raise RuntimeError(f'Thumbnail-Text-Overlays konnten nicht automatisch generiert werden: {exc}') from exc


def _load_existing_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _pipeline_runner(project_id: str) -> None:
    try:
        project = load_project(project_id)
        state = load_state(project_id)
        _log(project_id, 'Pipeline gestartet.')

        if not any((project.get('files') or {}).values()):
            raise RuntimeError('Es wurden noch keine Quelldateien hochgeladen.')

        steps = [
            ('ingest', 0.12, 'Material wird vorbereitet.'),
            ('transcription', 0.42, 'Whisper transkribiert die Spuren.'),
            ('sync', 0.68, 'Kameras werden ueber Sprach-Timestamps und Audio synchronisiert.'),
            ('analysis', 0.82, 'Decision Engine baut den Rohschnitt.'),
            ('export', 0.94, 'FCPXML und Marker werden exportiert.'),
        ]

        sync_report: Dict[str, Any] = {}
        transcript_map: Dict[str, Any] = {'files': {}, 'runtime': {}}
        analysis_result: Dict[str, Any] = {}

        for step_name, progress, message in steps:
            if _stop_requested(project_id):
                raise LongformStopRequested('Longform processing stopped by user.')
            step_state = (load_state(project_id).get('steps') or {}).get(step_name) or {}
            if step_state.get('status') == 'completed':
                _log(project_id, f'Schritt wird uebersprungen (bereits fertig): {step_name}')
                if step_name == 'transcription':
                    transcript_map = _run_transcription(project)
                elif step_name == 'sync' and os.path.exists(_sync_report_path(project_id)):
                    sync_report = _load_existing_json(_sync_report_path(project_id))
                elif step_name == 'analysis' and os.path.exists(_analysis_result_path(project_id)):
                    analysis_result = _load_existing_json(_analysis_result_path(project_id))
                continue

            _mark_processing(project_id, step_name, message, progress)
            if step_name == 'ingest':
                project = _run_ingest(project)
            elif step_name == 'transcription':
                _update_progress(project_id, 'transcription', 0.05, 'Whisper startet.')
                transcript_map = _run_transcription(project)
                _update_progress(project_id, 'transcription', 1.0, 'Transkription abgeschlossen.')
            elif step_name == 'sync':
                if not transcript_map.get('files'):
                    transcript_map = _run_transcription(project)
                _update_progress(project_id, 'sync', 0.05, 'Sync startet.')
                sync_report = _run_sync(project, transcript_map)
                _update_progress(project_id, 'sync', 1.0, 'Sync abgeschlossen.')
            elif step_name == 'analysis':
                if not transcript_map.get('files'):
                    transcript_map = _run_transcription(project)
                if not sync_report and os.path.exists(_sync_report_path(project_id)):
                    sync_report = _load_existing_json(_sync_report_path(project_id))
                _update_progress(project_id, 'analysis', 0.08, 'Analyse startet.')
                analysis_result = _run_analysis(project, transcript_map, sync_report)
                _update_progress(project_id, 'analysis', 1.0, 'Analyse abgeschlossen.')
            elif step_name == 'export':
                if not analysis_result and os.path.exists(_analysis_result_path(project_id)):
                    analysis_result = _load_existing_json(_analysis_result_path(project_id))
                _update_progress(project_id, 'export', 0.1, 'Export startet.')
                _run_export(project, analysis_result)
                _update_progress(project_id, 'export', 1.0, 'Export abgeschlossen.')

                # Extract thumbnail frames after export
                _update_progress(project_id, 'export', 0.98, 'Thumbnail-Frames werden extrahiert...')
                try:
                    thumbnail_manifest = _run_thumbnail_extraction(project)
                    project['thumbnail_manifest'] = thumbnail_manifest

                    # Auto-load speaker stills: 6 per role (host + guest for interview, single for single mode)
                    _update_progress(project_id, 'export', 0.99, 'Sprecher-Stills werden geladen...')
                    project = load_project(project_id)
                    try:
                        _auto_load_speaker_stills(project)
                        _log(project_id, 'Sprecher-Stills automatisch geladen (6 pro Rolle).')
                    except Exception as stills_exc:
                        LOGGER.warning(f'Auto speaker stills failed: {stills_exc}')
                        _log(project_id, f'Sprecher-Stills automatisch laden fehlgeschlagen (optional): {stills_exc}')

                    try:
                        _update_progress(project_id, 'export', 0.995, 'Text-Overlay-Vorschlaege werden generiert...')
                        _auto_generate_thumbnail_text_overlays(project, count=10)
                        project = load_project(project_id)
                    except Exception as overlay_exc:
                        LOGGER.warning(f'Auto thumbnail text overlays failed: {overlay_exc}')
                        _log(project_id, f'Text-Overlay-Vorschlaege automatisch generieren fehlgeschlagen (optional): {overlay_exc}')

                    save_project(project)
                except Exception as exc:
                    LOGGER.warning(f'Thumbnail extraction failed: {exc}')
                    _log(project_id, f'Thumbnail-Extraktion fehlgeschlagen (optional): {exc}')
            _set_step(project_id, step_name, status='completed', message=message)

        if not analysis_result and os.path.exists(_analysis_result_path(project_id)):
            analysis_result = _load_existing_json(_analysis_result_path(project_id))
        summary = (analysis_result or {}).get('summary') or {}
        _mark_completed(project_id, summary, project)
    except LongformStopRequested:
        _mark_paused(project_id, 'Longform-Pipeline pausiert. Resume verfuegbar.')
    except Exception as exc:
        LOGGER.exception('Longform pipeline failed for %s', project_id)
        _mark_failed(project_id, str(exc))
    finally:
        with _pipeline_lock:
            _pipeline_threads.pop(project_id, None)
            _pipeline_stop_events.pop(project_id, None)


def _spawn_pipeline(project_id: str) -> Dict[str, Any]:
    with _pipeline_lock:
        thread = _pipeline_threads.get(project_id)
        if thread and thread.is_alive():
            raise RuntimeError('Longform pipeline is already running for this project.')
        stop_event = threading.Event()
        _pipeline_stop_events[project_id] = stop_event
        thread = threading.Thread(target=_pipeline_runner, args=(project_id,), daemon=True)
        _pipeline_threads[project_id] = thread
        thread.start()
    return load_state(project_id)


def start_longform_pipeline_task(project_id: str) -> Dict[str, Any]:
    state = load_state(project_id)
    if state.get('status') == 'processing':
        raise RuntimeError('Longform pipeline is already running.')
    state['status'] = 'queued'
    state['message'] = 'Longform pipeline wird gestartet.'
    state['resume_available'] = False
    state['stop_requested'] = False
    save_state(project_id, state)
    return _spawn_pipeline(project_id)


def resume_longform_pipeline_task(project_id: str) -> Dict[str, Any]:
    state = load_state(project_id)
    if state.get('status') == 'processing':
        raise RuntimeError('Longform pipeline is already running.')
    state['status'] = 'queued'
    state['message'] = 'Longform pipeline wird fortgesetzt.'
    state['resume_available'] = False
    state['stop_requested'] = False
    save_state(project_id, state)
    return _spawn_pipeline(project_id)


def restart_longform_pipeline_task(project_id: str) -> Dict[str, Any]:
    state = load_state(project_id)
    if state.get('status') == 'processing':
        raise RuntimeError('Longform pipeline laeuft bereits. Bitte erst stoppen oder pausieren.')
    clear_project_derived_artifacts(project_id)
    state = build_initial_state()
    state['message'] = 'Pipeline sauber zurueckgesetzt. Bereit fuer Neustart.'
    save_state(project_id, state)
    _log(project_id, 'Pipeline per Restart sauber zurueckgesetzt.')
    return state


def stop_longform_pipeline(project_id: str) -> Dict[str, Any]:
    state = load_state(project_id)
    event = _pipeline_stop_events.get(project_id)
    if event:
        event.set()
    state['stop_requested'] = True
    state['message'] = 'Stop angefordert. Der aktuelle Schritt wird sauber beendet.'
    state['resume_available'] = True
    save_state(project_id, state)
    return state


def _auto_load_speaker_stills(project: Dict[str, Any], *, count: int = 6) -> None:
    """
    Automatically load speaker stills after pipeline completes.
    Uses random timestamps across all clips for maximum variety.
    """
    project_id = project['project_id']
    mode = project.get('mode') or 'single'
    roles = ['host', 'guest'] if mode == 'interview' else ['single']

    from longform.ffmpeg_ops import probe_media, media_url_from_path
    from longform.storage import project_subdir

    # Load analysis result if available
    analysis_result = {}
    analysis_path = _analysis_result_path(project_id)
    if os.path.exists(analysis_path):
        with open(analysis_path, 'r', encoding='utf-8') as f:
            analysis_result = json.load(f)

    stills_root = project_subdir(project_id, 'stills')
    os.makedirs(stills_root, exist_ok=True)

    stills_payload = {}

    for role in roles:
        role_files = sorted(
            (project.get('files') or {}).get(role) or [],
            key=lambda raw: float(raw.get('global_start_sec') or 0.0)
        )

        if not role_files:
            continue

        # Collect ALL possible timestamps - we'll randomize from these
        all_candidates = []

        # From analysis: speaker turn midpoints
        if analysis_result:
            turns = [
                item for item in (analysis_result.get('speaker_turns') or [])
                if str(item.get('role') or '').strip().lower() == role
                and float(item.get('end') or 0.0) - float(item.get('start') or 0.0) >= 1.0
            ]
            for turn in turns:
                start_t = float(turn.get('start') or 0.0)
                end_t = float(turn.get('end') or 0.0)
                duration = end_t - start_t
                # Use RANDOM position within the turn (not always 45%)
                random_offset = random.random() * duration
                midpoint = start_t + random_offset

                resolved = _resolve_longform_role_source_at_time(project, role, midpoint)
                if not resolved:
                    continue

                all_candidates.append({
                    'global_time': round(midpoint, 3),
                    'local_time': round(float(resolved['local_time']), 3),
                    'source_path': resolved['source_path'],
                    'file_name': resolved['file'].get('original_name'),
                    'confidence': round(float(turn.get('confidence') or 0.0), 3),
                    'file_index': next((i for i, f in enumerate(role_files) if f.get('id') == resolved['file'].get('id')), 0),
                })

        # From clips: RANDOM positions (not fixed ratios)
        for file_idx, item in enumerate(role_files):
            source_path = item.get('normalized_path') or item.get('stored_path')
            duration = float(item.get('duration_sec') or 0.0)
            global_start = float(item.get('global_start_sec') or 0.0)

            if not source_path or duration <= 0.2:
                continue

            # Generate MANY random candidates per clip
            num_random = max(10, int(duration / 10))  # ~1 per 10 seconds minimum
            for _ in range(num_random):
                # Pure random within the clip
                local_random = random.uniform(0.1, 0.95) * duration
                global_time = global_start + local_random

                all_candidates.append({
                    'global_time': round(global_time, 3),
                    'local_time': round(local_random, 3),
                    'source_path': source_path,
                    'file_name': item.get('original_name'),
                    'confidence': 0.0,
                    'file_index': file_idx,
                })

        # Shuffle - this is the key for true randomness
        random.shuffle(all_candidates)

        # Select candidates ensuring some distribution
        selected = []
        used_times = []
        used_file_indices = set()

        for candidate in all_candidates:
            if len(selected) >= count:
                break

            # Ensure minimum distance between selected frames
            midpoint = candidate['global_time']
            if any(abs(midpoint - existing) < 20.0 for existing in used_times):
                continue

            selected.append(candidate)
            used_times.append(midpoint)
            used_file_indices.add(candidate['file_index'])

        # Save frames
        role_dir = os.path.join(stills_root, role)
        os.makedirs(role_dir, exist_ok=True)

        role_items = []
        for idx, candidate in enumerate(selected, start=1):
            output_path = os.path.join(role_dir, f'{role}_{idx:02d}.jpg')
            try:
                _capture_longform_video_frame(candidate['source_path'], output_path, candidate['local_time'])
                role_items.append({
                    **candidate,
                    'path': output_path,
                    'url': media_url_from_path(output_path),
                })
            except Exception as exc:
                LOGGER.warning(f'Failed to capture frame at {candidate["local_time"]}s: {exc}')
                continue

        if role_items:
            stills_payload[role] = role_items

    # Persist to project artifacts
    if stills_payload:
        artifacts = dict(project.get('artifacts') or {})
        artifacts['speaker_stills'] = stills_payload
        project['artifacts'] = artifacts

        # Also update thumbnail_selected_stills with first still per role
        thumbnail_selected = {}
        for role, items in stills_payload.items():
            if items and items[0].get('path'):
                thumbnail_selected[role] = items[0]['path']
        if thumbnail_selected:
            project_config = project.get('config') or {}
            project_config['thumbnail_selected_stills'] = thumbnail_selected
            project['config'] = project_config


def _resolve_longform_role_source_at_time(project: Dict[str, Any], role: str, global_time_sec: float) -> Optional[Dict[str, Any]]:
    """Resolve which source file and local time corresponds to a global time."""
    role_files = sorted(
        (project.get('files') or {}).get(role) or [],
        key=lambda raw: float(raw.get('global_start_sec') or 0.0)
    )

    for item in role_files:
        start = float(item.get('global_start_sec') or 0.0)
        duration = float(item.get('duration_sec') or 0.0)

        if start <= global_time_sec <= start + duration:
            source_path = item.get('normalized_path') or item.get('stored_path')
            if source_path and os.path.exists(source_path):
                local_time = global_time_sec - start
                return {
                    'source_path': source_path,
                    'local_time': local_time,
                    'file': item,
                }
    return None


def _capture_longform_video_frame(input_path: str, output_path: str, timestamp_sec: float) -> None:
    """Capture a single frame from video at the given timestamp."""
    import subprocess
    from runtime_limits import subprocess_priority_kwargs

    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-ss', f'{timestamp_sec:.3f}',
        '-i', input_path,
        '-vframes', '1',
        '-vf', 'scale=640:-2',
        '-q:v', '3',
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, **subprocess_priority_kwargs())


def restore_orphaned_projects() -> None:
    mark_running_projects_paused()
