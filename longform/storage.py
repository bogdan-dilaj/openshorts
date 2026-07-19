from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import build_initial_project_record, build_initial_state, normalize_ai_config, normalize_project_config

LOGGER = logging.getLogger(__name__)
LONGFORM_ROOT = os.path.join('output', 'longform_projects')
LONGFORM_UPLOAD_TMP_ROOT = os.environ.get('LONGFORM_UPLOAD_TMP_ROOT', os.path.join('output', '.longform_uploads'))


def ensure_longform_root() -> str:
    os.makedirs(LONGFORM_ROOT, exist_ok=True)
    return LONGFORM_ROOT


def ensure_longform_upload_tmp_root() -> str:
    os.makedirs(LONGFORM_UPLOAD_TMP_ROOT, exist_ok=True)
    return LONGFORM_UPLOAD_TMP_ROOT


def project_dir(project_id: str) -> str:
    return os.path.join(ensure_longform_root(), project_id)


def project_json_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), 'project.json')


def state_json_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), 'state.json')


def log_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), 'logs.txt')


def project_subdir(project_id: str, name: str) -> str:
    path = os.path.join(project_dir(project_id), name)
    os.makedirs(path, exist_ok=True)
    return path


def project_upload_tmp_dir(project_id: str) -> str:
    path = os.path.join(ensure_longform_upload_tmp_root(), project_id)
    os.makedirs(path, exist_ok=True)
    return path


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        LOGGER.exception('Failed to read JSON: %s', path)
        return default


def _write_json(path: str, payload: Any) -> None:
    tmp_path = f'{path}.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def create_project(project_name: str, mode: str = 'single', *, config: Optional[Dict[str, Any]] = None, ai: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    project = build_initial_project_record(project_name, mode, config=config, ai=ai)
    state = build_initial_state()
    root = project_dir(project['project_id'])
    os.makedirs(root, exist_ok=True)
    for subdir in ('source', 'normalized', 'audio', 'transcripts', 'analysis', 'exports', 'debug', 'proxies'):
        os.makedirs(os.path.join(root, subdir), exist_ok=True)
    save_project(project)
    save_state(project['project_id'], state)
    append_log(project['project_id'], f"Projekt erstellt: {project['project_name']}")
    return project, state


def load_project(project_id: str) -> Dict[str, Any]:
    project = _read_json(project_json_path(project_id), None)
    if not isinstance(project, dict):
        raise FileNotFoundError(f'Longform project not found: {project_id}')
    project['config'] = normalize_project_config(project.get('config'), mode=project.get('mode', 'single'))
    project['ai'] = normalize_ai_config(project.get('ai'))
    project.setdefault('artifacts', {})
    project.setdefault('files', {})
    return project


def save_project(project: Dict[str, Any]) -> None:
    project['updated_at'] = time.time()
    root = project_dir(project['project_id'])
    os.makedirs(root, exist_ok=True)
    _write_json(project_json_path(project['project_id']), project)


def load_state(project_id: str) -> Dict[str, Any]:
    state = _read_json(state_json_path(project_id), None)
    if not isinstance(state, dict):
        state = build_initial_state()
    state.setdefault('steps', build_initial_state()['steps'])
    state.setdefault('summary', {})
    return state


def save_state(project_id: str, state: Dict[str, Any]) -> None:
    state['updated_at'] = time.time()
    _write_json(state_json_path(project_id), state)


def load_project_bundle(project_id: str, *, log_limit: int = 400) -> Dict[str, Any]:
    project = load_project(project_id)
    state = load_state(project_id)
    return {
        'project': project,
        'state': state,
        'logs': read_logs(project_id, limit=log_limit),
    }


def read_logs(project_id: str, *, limit: int = 400) -> List[str]:
    path = log_path(project_id)
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        lines = [line.rstrip('\n') for line in handle]
    if limit <= 0:
        return lines
    return lines[-limit:]


def append_log(project_id: str, message: str) -> None:
    os.makedirs(project_dir(project_id), exist_ok=True)
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(log_path(project_id), 'a', encoding='utf-8') as handle:
        handle.write(f'[{timestamp}] {message}\n')


def list_projects(*, limit: int = 100, log_limit: int = 80) -> List[Dict[str, Any]]:
    ensure_longform_root()
    projects: List[Dict[str, Any]] = []
    for project_id in os.listdir(LONGFORM_ROOT):
        path = project_dir(project_id)
        if not os.path.isdir(path):
            continue
        try:
            bundle = load_project_bundle(project_id, log_limit=log_limit)
        except Exception:
            LOGGER.exception('Failed to load longform project %s', project_id)
            continue
        project = bundle['project']
        state = bundle['state']
        projects.append({
            'project_id': project['project_id'],
            'project_name': project.get('project_name'),
            'mode': project.get('mode'),
            'status': state.get('status'),
            'current_step': state.get('current_step'),
            'message': state.get('message'),
            'progress': state.get('progress'),
            'updated_at': max(project.get('updated_at') or 0, state.get('updated_at') or 0),
            'created_at': project.get('created_at') or state.get('created_at'),
            'summary': state.get('summary') or {},
            'artifacts': project.get('artifacts') or {},
            'logs': bundle['logs'],
        })
    projects.sort(key=lambda item: item.get('updated_at') or 0, reverse=True)
    return projects[:limit]


def register_uploaded_file(project_id: str, role: str, file_record: Dict[str, Any]) -> Dict[str, Any]:
    project = load_project(project_id)
    files_by_role = project.setdefault('files', {})
    role_files = list(files_by_role.get(role) or [])
    new_stored_path = str(file_record.get('stored_path') or '').strip()
    new_real_path = ''
    if new_stored_path:
        try:
            new_real_path = os.path.realpath(new_stored_path)
        except Exception:
            new_real_path = new_stored_path
    for existing in role_files:
        existing_path = str(existing.get('stored_path') or '').strip()
        existing_real_path = ''
        if existing_path:
            try:
                existing_real_path = os.path.realpath(existing_path)
            except Exception:
                existing_real_path = existing_path
        if new_real_path and existing_real_path and new_real_path == existing_real_path:
            append_log(project_id, f"Datei bereits vorhanden ({role}): {file_record.get('original_name')}")
            return project
    role_files.append(file_record)
    role_files.sort(key=lambda item: (int(item.get('order') or 0), str(item.get('uploaded_at') or '')))
    for index, item in enumerate(role_files):
        item['order'] = index
    files_by_role[role] = role_files
    save_project(project)
    append_log(project_id, f"Datei hinzugefügt ({role}): {file_record.get('original_name')}")
    return project


def update_project(project_id: str, *, project_name: Optional[str] = None, mode: Optional[str] = None, config: Optional[Dict[str, Any]] = None, ai: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None, artifacts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    project = load_project(project_id)
    if project_name is not None:
        project['project_name'] = (project_name or project.get('project_name') or 'Longform Project').strip() or 'Longform Project'
    if mode is not None:
        project['mode'] = 'interview' if str(mode).strip().lower() == 'interview' else 'single'
    if config is not None:
        project['config'] = normalize_project_config(config, mode=project.get('mode', 'single'))
    else:
        project['config'] = normalize_project_config(project.get('config'), mode=project.get('mode', 'single'))
    if ai is not None:
        project['ai'] = normalize_ai_config(ai)
    else:
        project['ai'] = normalize_ai_config(project.get('ai'))
    if files is not None:
        project['files'] = files
    if artifacts is not None:
        project['artifacts'] = artifacts
    save_project(project)
    return project


def reorder_role_files(project_id: str, role: str, ordered_ids: List[str]) -> Dict[str, Any]:
    project = load_project(project_id)
    role_files = list(project.get('files', {}).get(role) or [])
    order_map = {value: index for index, value in enumerate(ordered_ids)}
    role_files.sort(key=lambda item: (order_map.get(item.get('id'), 10**9), int(item.get('order') or 0)))
    for index, item in enumerate(role_files):
        item['order'] = index
    project['files'][role] = role_files
    save_project(project)
    append_log(project_id, f'Reihenfolge aktualisiert: {role}')
    return project


def remove_file(project_id: str, role: str, file_id: str) -> Dict[str, Any]:
    project = load_project(project_id)
    role_files = list(project.get('files', {}).get(role) or [])
    removed = None
    remaining: List[Dict[str, Any]] = []
    for item in role_files:
        if item.get('id') == file_id:
            removed = item
        else:
            remaining.append(item)
    for index, item in enumerate(remaining):
        item['order'] = index
    project['files'][role] = remaining
    save_project(project)
    if removed:
        project_root_real = os.path.realpath(project_dir(project_id))
        temp_root_real = os.path.realpath(os.path.join(ensure_longform_upload_tmp_root(), project_id))
        source_storage = str(removed.get('source_storage') or '').strip().lower()
        source_path = removed.get('stored_path')
        delete_source_path = False
        if source_path:
            try:
                source_real = os.path.realpath(source_path)
                delete_source_path = (
                    source_storage.startswith('temporary_upload')
                    or os.path.commonpath([source_real, project_root_real]) == project_root_real
                    or os.path.commonpath([source_real, temp_root_real]) == temp_root_real
                )
            except Exception:
                delete_source_path = source_storage.startswith('temporary_upload')

        for key in ('stored_path', 'normalized_path', 'proxy_path', 'audio_path', 'transcript_path'):
            path = removed.get(key)
            if path and os.path.exists(path):
                if key == 'stored_path' and not delete_source_path:
                    continue
                try:
                    os.remove(path)
                except Exception:
                    LOGGER.exception('Failed to delete file artifact %s', path)
        append_log(project_id, f"Datei entfernt ({role}): {removed.get('original_name')}")
    return project


def delete_project(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
    shutil.rmtree(os.path.join(ensure_longform_upload_tmp_root(), project_id), ignore_errors=True)


def clear_project_derived_artifacts(project_id: str) -> Dict[str, int]:
    project = load_project(project_id)
    removed_counts = {
        'files': 0,
        'directories': 0,
    }
    for subdir in ('normalized', 'audio', 'transcripts', 'analysis', 'exports', 'debug', 'proxies'):
        shutil.rmtree(os.path.join(project_dir(project_id), subdir), ignore_errors=True)
        os.makedirs(os.path.join(project_dir(project_id), subdir), exist_ok=True)
        removed_counts['directories'] += 1

    for role_files in (project.get('files') or {}).values():
        for item in role_files or []:
            for key in ('normalized_path', 'proxy_path', 'audio_path', 'transcript_path'):
                if item.get(key):
                    removed_counts['files'] += 1
                item[key] = None

    project.setdefault('artifacts', {})
    for artifact_key in (
        'sync_report',
        'analysis_result',
        'analysis_json',
        'fcpxml',
        'markers_csv',
        'decisions_json',
        'sync_json',
        'primary_audio_stereo',
        'primary_audio_left',
        'primary_audio_right',
    ):
        project['artifacts'][artifact_key] = None
    save_project(project)
    append_log(project_id, 'Abgeleitete Projektartefakte wurden zurueckgesetzt.')
    return removed_counts


def mark_running_projects_paused() -> None:
    for item in list_projects(limit=500, log_limit=0):
        if item.get('status') not in {'processing', 'queued'}:
            continue
        try:
            state = load_state(item['project_id'])
            state['status'] = 'paused'
            state['message'] = 'Projekt wurde nach einem Neustart pausiert und kann fortgesetzt werden.'
            state['resume_available'] = True
            state['stop_requested'] = False
            save_state(item['project_id'], state)
            append_log(item['project_id'], 'Projekt nach Backend-Neustart automatisch auf pausiert gesetzt.')
        except Exception:
            LOGGER.exception('Failed to mark running project paused: %s', item['project_id'])
