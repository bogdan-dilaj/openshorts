from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any, Dict, List

CAMERA_ROLES_BY_MODE = {
    'single': ['single'],
    'interview': ['host', 'guest'],
}

PRESET_DEFAULTS: Dict[str, Dict[str, Any]] = {
    'conservative': {
        'min_shot_length_sec': 4.5,
        'speaker_switch_hold_ms': 1600,
        'long_pause_threshold_ms': 900,
        'pause_trim_target_ms': 380,
        'filler_word_cut_level': 0,
        'remove_umms': False,
        'backchannel_max_duration_ms': 900,
        'backchannel_max_words': 3,
        'reaction_marker_enabled': True,
        'retake_mode': 'mark',
        'review_threshold': 0.72,
    },
    'balanced': {
        'min_shot_length_sec': 3.0,
        'speaker_switch_hold_ms': 900,
        'long_pause_threshold_ms': 650,
        'pause_trim_target_ms': 260,
        'filler_word_cut_level': 1,
        'remove_umms': False,
        'backchannel_max_duration_ms': 700,
        'backchannel_max_words': 3,
        'reaction_marker_enabled': True,
        'retake_mode': 'aggressive_cut',
        'review_threshold': 0.62,
    },
    'aggressive': {
        'min_shot_length_sec': 2.2,
        'speaker_switch_hold_ms': 520,
        'long_pause_threshold_ms': 450,
        'pause_trim_target_ms': 160,
        'filler_word_cut_level': 2,
        'remove_umms': True,
        'backchannel_max_duration_ms': 500,
        'backchannel_max_words': 2,
        'reaction_marker_enabled': True,
        'retake_mode': 'aggressive_cut',
        'review_threshold': 0.55,
    },
}

BASE_CONFIG: Dict[str, Any] = {
    'preset': 'balanced',
    'primary_audio_camera': 'single',
    'cfr_transcode_enabled': False,
    'proxy_enabled': False,
    'analysis_language': 'de',
    'export_fps': 24,
    'min_shot_length_sec': 3.0,
    'speaker_switch_hold_ms': 900,
    'long_pause_threshold_ms': 650,
    'pause_trim_target_ms': 260,
    'filler_word_cut_level': 1,
    'remove_umms': False,
    'backchannel_max_duration_ms': 700,
    'backchannel_max_words': 3,
    'reaction_marker_enabled': True,
    'retake_mode': 'aggressive_cut',
    'jcut_enabled': True,
    'lcut_enabled': True,
    'pyannote_diarization_enabled': True,
    'export_loudness_adjustment_enabled': False,
    'export_primary_audio_stereo_enabled': True,
    'review_threshold': 0.62,
    'target_sample_rate': 48000,
    'proxy_height': 720,
    'thumbnail_reference_role_order': 'host_guest',
    'thumbnail_text_overlay_text': '',
    'thumbnail_text_overlay_suggestions': [],
}

BASE_AI_CONFIG: Dict[str, Any] = {
    'provider': 'ollama',
    'ollama_base_url': 'http://127.0.0.1:11434',
    'ollama_model': 'gemma3:12b',
    'gemini_api_key': '',
    'gemini_model': 'gemini-2.5-flash',
    'huggingface_token': '',
    'openai_api_key': '',
    'openai_model': 'gpt-4.1-mini',
    'claude_api_key': '',
    'claude_model': 'claude-3-5-sonnet-latest',
    'minimax_api_key': '',
    'minimax_auth_mode': 'token_plan',
    'minimax_model': 'MiniMax-M3',
    'midjourney_api_key': '',
    'midjourney_base_url': '',
}


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = float(default)
    return max(minimum, min(maximum, numeric))


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value)
    except Exception:
        numeric = int(default)
    return max(minimum, min(maximum, numeric))


def active_camera_roles(mode: str) -> List[str]:
    normalized = (mode or 'single').strip().lower()
    return list(CAMERA_ROLES_BY_MODE.get(normalized, CAMERA_ROLES_BY_MODE['single']))


def normalize_ai_config(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = deepcopy(BASE_AI_CONFIG)
    if not isinstance(raw, dict):
        return payload
    for key in payload:
        if key in raw and raw[key] is not None:
            payload[key] = str(raw[key]).strip()
    if payload['provider'] not in {'off', 'ollama', 'gemini', 'openai', 'claude', 'minimax'}:
        payload['provider'] = 'ollama'
    if payload.get('minimax_auth_mode') not in {'token_plan', 'payg'}:
        payload['minimax_auth_mode'] = 'token_plan'
    minimax_model = str(payload.get('minimax_model') or '').strip().lower()
    minimax_model_aliases = {
        'minimax-text-01': 'MiniMax-M3',
        'minimax-m1': 'MiniMax-M3',
        'minimax-m3': 'MiniMax-M3',
    }
    if minimax_model in minimax_model_aliases:
        payload['minimax_model'] = minimax_model_aliases[minimax_model]
    return payload


def normalize_project_config(raw: Dict[str, Any] | None, *, mode: str = 'single') -> Dict[str, Any]:
    normalized_mode = 'interview' if str(mode).strip().lower() == 'interview' else 'single'
    payload = deepcopy(BASE_CONFIG)
    if isinstance(raw, dict):
        payload.update({k: v for k, v in raw.items() if v is not None})

    preset = str(payload.get('preset') or 'balanced').strip().lower()
    if preset not in PRESET_DEFAULTS:
        preset = 'balanced'
    payload['preset'] = preset
    payload.update({**PRESET_DEFAULTS[preset], **payload})

    valid_roles = active_camera_roles(normalized_mode)
    primary_role = str(payload.get('primary_audio_camera') or valid_roles[0]).strip().lower()
    if primary_role not in valid_roles:
        primary_role = valid_roles[0]
    payload['primary_audio_camera'] = primary_role
    payload['analysis_language'] = (str(payload.get('analysis_language') or 'de').strip().lower() or 'de')[:8]
    payload['cfr_transcode_enabled'] = bool(payload.get('cfr_transcode_enabled', False))
    payload['proxy_enabled'] = bool(payload.get('proxy_enabled', False))
    payload['reaction_marker_enabled'] = bool(payload.get('reaction_marker_enabled', True))
    payload['remove_umms'] = bool(payload.get('remove_umms', False))
    payload['jcut_enabled'] = bool(payload.get('jcut_enabled', True))
    payload['lcut_enabled'] = bool(payload.get('lcut_enabled', True))
    payload['pyannote_diarization_enabled'] = bool(payload.get('pyannote_diarization_enabled', True))
    payload['export_loudness_adjustment_enabled'] = bool(payload.get('export_loudness_adjustment_enabled', False))
    payload['export_primary_audio_stereo_enabled'] = bool(payload.get('export_primary_audio_stereo_enabled', True))
    payload['export_fps'] = _clamp_int(payload.get('export_fps'), 24, 23, 60)
    payload['min_shot_length_sec'] = _clamp_float(payload.get('min_shot_length_sec'), 3.0, 1.0, 20.0)
    payload['speaker_switch_hold_ms'] = _clamp_int(payload.get('speaker_switch_hold_ms'), 900, 0, 5000)
    payload['long_pause_threshold_ms'] = _clamp_int(payload.get('long_pause_threshold_ms'), 650, 150, 5000)
    payload['pause_trim_target_ms'] = _clamp_int(payload.get('pause_trim_target_ms'), 260, 0, 3000)
    payload['filler_word_cut_level'] = _clamp_int(payload.get('filler_word_cut_level'), 1, 0, 2)
    payload['backchannel_max_duration_ms'] = _clamp_int(payload.get('backchannel_max_duration_ms'), 700, 100, 3000)
    payload['backchannel_max_words'] = _clamp_int(payload.get('backchannel_max_words'), 3, 1, 10)
    payload['review_threshold'] = _clamp_float(payload.get('review_threshold'), 0.62, 0.1, 0.99)
    payload['target_sample_rate'] = _clamp_int(payload.get('target_sample_rate'), 48000, 16000, 96000)
    payload['proxy_height'] = _clamp_int(payload.get('proxy_height'), 720, 360, 1080)
    retake_mode = str(payload.get('retake_mode') or 'aggressive_cut').strip().lower()
    if retake_mode not in {'off', 'mark', 'conservative_cut', 'aggressive_cut'}:
        retake_mode = 'aggressive_cut'
    payload['retake_mode'] = retake_mode
    role_order = str(payload.get('thumbnail_reference_role_order') or 'host_guest').strip().lower()
    if role_order not in {'host_guest', 'guest_host'}:
        role_order = 'host_guest'
    payload['thumbnail_reference_role_order'] = role_order
    payload['thumbnail_text_overlay_text'] = str(payload.get('thumbnail_text_overlay_text') or '').strip()
    raw_suggestions = payload.get('thumbnail_text_overlay_suggestions')
    if not isinstance(raw_suggestions, list):
        raw_suggestions = []
    normalized_suggestions: List[str] = []
    for item in raw_suggestions:
        text = str(item or '').strip()
        if not text or text in normalized_suggestions:
            continue
        normalized_suggestions.append(text[:80])
        if len(normalized_suggestions) >= 10:
            break
    payload['thumbnail_text_overlay_suggestions'] = normalized_suggestions
    return payload


def build_initial_steps() -> Dict[str, Dict[str, Any]]:
    steps: Dict[str, Dict[str, Any]] = {}
    for step in ('ingest', 'transcription', 'sync', 'analysis', 'export'):
        steps[step] = {
            'status': 'pending',
            'started_at': None,
            'completed_at': None,
            'error': None,
            'message': '',
        }
    return steps


def build_initial_state() -> Dict[str, Any]:
    now = time.time()
    return {
        'status': 'idle',
        'current_step': None,
        'message': 'Bereit.',
        'progress': 0.0,
        'step_progress': 0.0,
        'eta_seconds': None,
        'step_eta_seconds': None,
        'timings': {
            'step_started_at': None,
            'step_elapsed_seconds': 0.0,
            'elapsed_seconds': 0.0,
        },
        'created_at': now,
        'updated_at': now,
        'started_at': None,
        'completed_at': None,
        'error': None,
        'resume_available': False,
        'stop_requested': False,
        'steps': build_initial_steps(),
        'summary': {},
    }


def build_initial_project_record(project_name: str, mode: str = 'single', *, config: Dict[str, Any] | None = None, ai: Dict[str, Any] | None = None) -> Dict[str, Any]:
    normalized_mode = 'interview' if str(mode).strip().lower() == 'interview' else 'single'
    now = time.time()
    return {
        'project_id': uuid.uuid4().hex,
        'project_name': (project_name or 'Longform Project').strip() or 'Longform Project',
        'mode': normalized_mode,
        'created_at': now,
        'updated_at': now,
        'files': {role: [] for role in active_camera_roles(normalized_mode)},
        'config': normalize_project_config(config, mode=normalized_mode),
        'ai': normalize_ai_config(ai),
        'artifacts': {},
    }
