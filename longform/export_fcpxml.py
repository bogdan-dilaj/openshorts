from __future__ import annotations

import csv
import json
import math
import os
import subprocess
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote
from xml.etree import ElementTree as ET

import numpy as np

from runtime_limits import subprocess_priority_kwargs
from .ffmpeg_ops import media_url_from_path, recommend_volume_adjustment_db

ExportProgressCallback = Callable[[Dict[str, Any]], None]
LoggerFn = Callable[[str], None]
_SEGMENT_LEVEL_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}


def seconds_to_fcpx_time(value: float, fps: int) -> str:
    frames = seconds_to_frames(value, fps)
    return frames_to_fcpx_time(frames, fps)


def seconds_to_frames(value: float, fps: int, *, minimum: int = 0) -> int:
    frames = max(minimum, int(round(float(value) * fps)))
    return frames


def frames_to_fcpx_time(frames: int, fps: int) -> str:
    frames = max(0, int(frames))
    if frames == 0:
        return '0s'
    return f'{frames}/{fps}s'


def _file_src(path: str) -> str:
    absolute = os.path.abspath(path)
    return 'file://' + quote(absolute)


def _decode_audio_analysis_levels(path: str, *, sample_rate: int = 16000, frame_sec: float = 0.25, hop_sec: float = 0.10) -> Dict[str, Any]:
    cache_key = f'{os.path.abspath(path)}::{sample_rate}:{frame_sec}:{hop_sec}'
    cached = _SEGMENT_LEVEL_PROFILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cmd = [
        'ffmpeg',
        '-v', 'error',
        '-i', path,
        '-vn',
        '-ac', '1',
        '-ar', str(sample_rate),
        '-f', 'f32le',
        '-',
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        check=True,
        **subprocess_priority_kwargs(),
    )
    samples = np.frombuffer(result.stdout or b'', dtype=np.float32)
    if samples.size <= 0:
        profile = {
            'hop_sec': hop_sec,
            'levels_db': np.asarray([-60.0], dtype=np.float32),
            'global_active_db': -60.0,
        }
        _SEGMENT_LEVEL_PROFILE_CACHE[cache_key] = profile
        return profile
    frame_size = max(64, int(sample_rate * frame_sec))
    hop_size = max(16, int(sample_rate * hop_sec))
    levels: List[float] = []
    for start in range(0, max(1, samples.size - frame_size + 1), hop_size):
        chunk = samples[start:start + frame_size]
        if chunk.size < frame_size:
            chunk = np.pad(chunk, (0, frame_size - chunk.size))
        rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64)))
        levels.append(20.0 * math.log10(max(rms, 1e-6)))
    if not levels:
        levels = [-60.0]
    levels_db = np.asarray(levels, dtype=np.float32)
    active_floor = float(np.percentile(levels_db, 35))
    active_candidates = levels_db[levels_db >= active_floor]
    if active_candidates.size <= 0:
        active_candidates = levels_db
    global_active_db = float(np.percentile(active_candidates, 72))
    profile = {
        'hop_sec': hop_size / float(sample_rate),
        'levels_db': levels_db,
        'global_active_db': global_active_db,
    }
    _SEGMENT_LEVEL_PROFILE_CACHE[cache_key] = profile
    return profile


def _estimate_segment_gain_db(segment: Dict[str, Any], base_gain_db: float) -> float:
    analysis_audio_path = str(segment.get('analysis_audio_path') or '').strip()
    if not analysis_audio_path or not os.path.exists(analysis_audio_path):
        return round(base_gain_db, 2)
    try:
        profile = _decode_audio_analysis_levels(analysis_audio_path)
    except Exception:
        return round(base_gain_db, 2)
    raw_levels = profile.get('levels_db')
    if raw_levels is None:
        levels_db = np.asarray([-60.0], dtype=np.float32)
    else:
        levels_db = np.asarray(raw_levels, dtype=np.float32)
        if levels_db.size <= 0:
            levels_db = np.asarray([-60.0], dtype=np.float32)
    if levels_db.size <= 0:
        return round(base_gain_db, 2)
    hop_sec = float(profile.get('hop_sec') or 0.10)
    global_active_db = float(profile.get('global_active_db') or -60.0)
    local_start = max(0.0, float(segment.get('local_start') or 0.0))
    local_end = max(local_start, float(segment.get('local_end') or local_start))
    duration = max(0.05, local_end - local_start)
    center = (local_start + local_end) / 2.0
    window_duration = max(1.4, min(4.0, duration + 0.9))
    window_start = max(0.0, center - window_duration / 2.0)
    window_end = max(window_start + 0.4, center + window_duration / 2.0)
    start_index = max(0, int(math.floor(window_start / max(hop_sec, 1e-6))))
    end_index = min(levels_db.shape[0], max(start_index + 1, int(math.ceil(window_end / max(hop_sec, 1e-6)))))
    local_levels = levels_db[start_index:end_index]
    if local_levels.size <= 0:
        return round(base_gain_db, 2)
    active_floor = float(np.percentile(local_levels, 35))
    active_candidates = local_levels[local_levels >= active_floor]
    if active_candidates.size <= 0:
        active_candidates = local_levels
    local_active_db = float(np.percentile(active_candidates, 72))
    delta_db = global_active_db - local_active_db
    influence = min(1.0, max(0.35, duration / 1.6))
    nuanced_delta = max(-3.5, min(3.5, delta_db * 0.75 * influence))
    return round(base_gain_db + nuanced_delta, 2)


def _indent(elem: ET.Element, level: int = 0) -> None:
    indent = '\n' + level * '  '
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + '  '
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def _resolve_asset_ref(asset_ids: Dict[str, Dict[str, str]], source_path: str, media_type: str) -> Optional[str]:
    payload = asset_ids.get(source_path) or {}
    media_key = str(media_type or 'video').strip().lower()
    if media_key in payload:
        return payload[media_key]
    if media_key == 'audio':
        return payload.get('video')
    return payload.get('audio')


def _build_asset_resources(resources: ET.Element, project: Dict[str, Any], fps: int) -> Tuple[str, Dict[str, Dict[str, str]]]:
    all_files: List[Dict[str, Any]] = []
    for role_files in (project.get('files') or {}).values():
        all_files.extend(role_files or [])
    first_video = next((item for item in all_files if item.get('normalized_path') or item.get('stored_path')), None)
    width = int((first_video or {}).get('width') or 1920)
    height = int((first_video or {}).get('height') or 1080)
    format_id = 'r_format_main'
    ET.SubElement(resources, 'format', {
        'id': format_id,
        'name': f'FFVideoFormat{height}p{fps}',
        'frameDuration': f'1/{fps}s',
        'width': str(width),
        'height': str(height),
        'colorSpace': '1-1-1 (Rec. 709)',
    })
    asset_ids: Dict[str, Dict[str, str]] = {}
    for index, item in enumerate(all_files, start=1):
        source_path = _source_path_for_item(item)
        if not source_path or source_path in asset_ids:
            continue
        asset_ids[source_path] = {}
        video_asset_id = f'r_asset_v_{index}'
        asset_ids[source_path]['video'] = video_asset_id
        ET.SubElement(resources, 'asset', {
            'id': video_asset_id,
            'name': item.get('original_name') or f'Clip {index}',
            'uid': f"{item.get('id') or video_asset_id}:video",
            'src': _file_src(source_path),
            'start': '0s',
            'duration': seconds_to_fcpx_time(float(item.get('duration_sec') or 0.0), fps),
            'hasVideo': '1',
            'hasAudio': '0',
            'format': format_id,
        })
        if item.get('has_audio', True):
            audio_asset_id = f'r_asset_a_{index}'
            asset_ids[source_path]['audio'] = audio_asset_id
            ET.SubElement(resources, 'asset', {
                'id': audio_asset_id,
                'name': f"{item.get('original_name') or f'Clip {index}'} Audio",
                'uid': f"{item.get('id') or audio_asset_id}:audio",
                'src': _file_src(source_path),
                'start': '0s',
                'duration': seconds_to_fcpx_time(float(item.get('duration_sec') or 0.0), fps),
                'hasVideo': '0',
                'hasAudio': '1',
                'audioSources': '1',
                'audioChannels': str(int(item.get('channels') or 1) or 1),
                'audioRate': '48k',
            })
    return format_id, asset_ids


def _add_audio_children(
    parent: ET.Element,
    *,
    fps: int,
    clip_start_global: float,
    audio_segments: List[Dict[str, Any]],
    asset_ids: Dict[str, Dict[str, str]],
    gain_cache: Dict[str, float],
) -> None:
    if not audio_segments:
        return

    split_segments = _split_audio_segments_for_mix(audio_segments)
    segment_gains: List[Optional[float]] = []
    for segment in split_segments:
        source_path = str(segment.get('source_path') or '')
        base_gain_db = gain_cache.get(source_path)
        gain_db = _estimate_segment_gain_db(segment, base_gain_db) if base_gain_db is not None else None
        segment_gains.append(gain_db)

    smoothed_gains: List[Optional[float]] = []
    for index, gain_db in enumerate(segment_gains):
        if gain_db is None:
            smoothed_gains.append(None)
            continue
        values = [float(gain_db)]
        if index > 0 and segment_gains[index - 1] is not None:
            values.append(float(segment_gains[index - 1]))
        if index + 1 < len(segment_gains) and segment_gains[index + 1] is not None:
            values.append(float(segment_gains[index + 1]))
        smoothed_gains.append(round(sum(values) / len(values), 2))

    for index, segment in enumerate(split_segments, start=1):
        source_path = segment.get('source_path')
        asset_ref = _resolve_asset_ref(asset_ids, str(source_path or ''), 'audio') if source_path else None
        if not source_path or not asset_ref:
            continue
        offset_frames = seconds_to_frames(float(segment.get('global_start') or 0.0) - clip_start_global, fps)
        duration_frames = seconds_to_frames(float(segment.get('duration') or 0.0), fps, minimum=1)
        audio_el = ET.SubElement(parent, 'audio', {
            'ref': asset_ref,
            'lane': '-1',
            'offset': frames_to_fcpx_time(offset_frames, fps),
            'start': seconds_to_fcpx_time(float(segment.get('local_start') or 0.0), fps),
            'duration': frames_to_fcpx_time(duration_frames, fps),
            'role': f'dialogue.primary.{index}',
        })
        gain_db = smoothed_gains[index - 1]
        if gain_db is not None and abs(gain_db) >= 0.1:
            ET.SubElement(audio_el, 'adjust-volume', {'amount': f'{gain_db:.2f}dB'})


def _split_audio_segments_for_mix(
    audio_segments: List[Dict[str, Any]],
    *,
    max_chunk_sec: float = 1.6,
    min_chunk_sec: float = 0.55,
) -> List[Dict[str, Any]]:
    pieces: List[Dict[str, Any]] = []
    for segment in audio_segments:
        duration = max(0.0, float(segment.get('duration') or 0.0))
        if duration <= 0.0:
            continue
        if duration <= max_chunk_sec + 0.12:
            pieces.append(dict(segment))
            continue
        chunk_count = max(1, int(math.ceil(duration / max_chunk_sec)))
        chunk_length = max(min_chunk_sec, duration / max(chunk_count, 1))
        cursor = 0.0
        while cursor < duration - 0.02:
            next_cursor = min(duration, cursor + chunk_length)
            piece = dict(segment)
            piece['global_start'] = round(float(segment.get('global_start') or 0.0) + cursor, 3)
            piece['global_end'] = round(float(segment.get('global_start') or 0.0) + next_cursor, 3)
            piece['local_start'] = round(float(segment.get('local_start') or 0.0) + cursor, 3)
            piece['local_end'] = round(float(segment.get('local_start') or 0.0) + next_cursor, 3)
            piece['duration'] = round(next_cursor - cursor, 3)
            pieces.append(piece)
            cursor = next_cursor
    return pieces


def _add_project(
    event: ET.Element,
    *,
    name: str,
    format_id: str,
    fps: int,
    clips: List[Dict[str, Any]],
    asset_ids: Dict[str, Dict[str, str]],
    gain_cache: Optional[Dict[str, float]] = None,
) -> None:
    project_el = ET.SubElement(event, 'project', {'name': name})
    total_duration_frames = sum(seconds_to_frames(float(item.get('duration') or 0.0), fps, minimum=1) for item in clips)
    sequence = ET.SubElement(project_el, 'sequence', {
        'format': format_id,
        'duration': frames_to_fcpx_time(total_duration_frames, fps),
        'tcStart': '0s',
        'tcFormat': 'NDF',
        'audioLayout': 'stereo',
        'audioRate': '48k',
    })
    spine = ET.SubElement(sequence, 'spine')
    cursor_frames = 0
    gain_cache = gain_cache or {}
    for index, clip in enumerate(clips, start=1):
        duration_frames = seconds_to_frames(float(clip.get('duration') or 0.0), fps, minimum=1)
        attributes = {
            'name': clip.get('name') or f'Clip {index}',
            'ref': clip['asset_id'],
            'offset': frames_to_fcpx_time(cursor_frames, fps),
            'start': seconds_to_fcpx_time(float(clip.get('source_start') or 0.0), fps),
            'duration': frames_to_fcpx_time(duration_frames, fps),
        }
        if clip.get('lane'):
            attributes['lane'] = str(clip['lane'])
        if clip.get('src_enable'):
            attributes['srcEnable'] = clip['src_enable']
        clip_el = ET.SubElement(spine, 'asset-clip', attributes)
        _add_audio_children(
            clip_el,
            fps=fps,
            clip_start_global=float(clip.get('global_start') or 0.0),
            audio_segments=list(clip.get('audio_segments') or []),
            asset_ids=asset_ids,
            gain_cache=gain_cache,
        )
        cursor_frames += duration_frames


def _add_resolve_rough_cut_project(
    event: ET.Element,
    *,
    name: str,
    format_id: str,
    fps: int,
    clips: List[Dict[str, Any]],
    asset_ids: Dict[str, Dict[str, str]],
    gain_cache: Optional[Dict[str, float]] = None,
    enable_gain_adjustments: bool = False,
) -> None:
    project_el = ET.SubElement(event, 'project', {'name': name})
    sequence = ET.SubElement(project_el, 'sequence', {
        'format': format_id,
        'duration': '0s',
        'tcStart': '0s',
        'tcFormat': 'NDF',
        'audioLayout': 'stereo',
        'audioRate': '48k',
    })
    spine = ET.SubElement(sequence, 'spine')

    gain_cache = gain_cache or {}
    sequence_items: List[Dict[str, Any]] = []
    cursor_frames = 0

    for index, clip in enumerate(clips, start=1):
        duration_frames = seconds_to_frames(float(clip.get('duration') or 0.0), fps, minimum=1)
        clip_offset_frames = cursor_frames

        sequence_items.append({
            'kind': 'video',
            'name': clip.get('name') or f'Clip {index}',
            'ref': clip['asset_id'],
            'offset_frames': clip_offset_frames,
            'start_frames': seconds_to_frames(float(clip.get('source_start') or 0.0), fps),
            'duration_frames': duration_frames,
            'lane': '1',
            'src_enable': 'video',
        })

        split_segments = _split_audio_segments_for_mix(list(clip.get('audio_segments') or []))
        clip_duration_sec = max(0.0, float(clip.get('duration') or 0.0))
        if split_segments:
            covered_audio_end_sec = max(float(segment.get('global_end') or segment.get('global_start') or 0.0) for segment in split_segments)
            clip_global_end_sec = float(clip.get('global_start') or 0.0) + clip_duration_sec
            tail_gap_sec = max(0.0, clip_global_end_sec - covered_audio_end_sec)
            if 0.0 < tail_gap_sec <= min(0.32, max(0.06, 3.0 / max(fps, 1))):
                last_segment = split_segments[-1]
                last_segment['global_end'] = round(float(last_segment.get('global_end') or covered_audio_end_sec) + tail_gap_sec, 3)
                last_segment['local_end'] = round(float(last_segment.get('local_end') or last_segment.get('local_start') or 0.0) + tail_gap_sec, 3)
                last_segment['duration'] = round(float(last_segment.get('duration') or 0.0) + tail_gap_sec, 3)
        segment_gains: List[Optional[float]] = []
        for segment in split_segments:
            source_path = str(segment.get('source_path') or '')
            base_gain_db = gain_cache.get(source_path) if enable_gain_adjustments else None
            gain_db = _estimate_segment_gain_db(segment, base_gain_db) if base_gain_db is not None else None
            segment_gains.append(gain_db)

        smoothed_gains: List[Optional[float]] = []
        for segment_index, gain_db in enumerate(segment_gains):
            if gain_db is None:
                smoothed_gains.append(None)
                continue
            values = [float(gain_db)]
            if segment_index > 0 and segment_gains[segment_index - 1] is not None:
                values.append(float(segment_gains[segment_index - 1]))
            if segment_index + 1 < len(segment_gains) and segment_gains[segment_index + 1] is not None:
                values.append(float(segment_gains[segment_index + 1]))
            smoothed_gains.append(round(sum(values) / len(values), 2))

        for segment_index, segment in enumerate(split_segments, start=1):
            source_path = str(segment.get('source_path') or '')
            asset_ref = _resolve_asset_ref(asset_ids, source_path, 'audio') if source_path else None
            if not source_path or not asset_ref:
                continue
            relative_sec = max(0.0, float(segment.get('global_start') or 0.0) - float(clip.get('global_start') or 0.0))
            offset_frames = clip_offset_frames + seconds_to_frames(relative_sec, fps)
            sequence_items.append({
                'kind': 'audio',
                'name': f"{clip.get('name') or f'Clip {index}'} Audio {segment_index}",
                'ref': asset_ref,
                'offset_frames': offset_frames,
                'start_frames': seconds_to_frames(float(segment.get('local_start') or 0.0), fps),
                'duration_frames': seconds_to_frames(float(segment.get('duration') or 0.0), fps, minimum=1),
                'gain_db': smoothed_gains[segment_index - 1] if segment_index - 1 < len(smoothed_gains) else None,
            })

        clip_end_frames = clip_offset_frames + duration_frames
        clip_audio_items = [item for item in sequence_items if item.get('kind') == 'audio' and clip_offset_frames <= int(item.get('offset_frames') or 0) < clip_end_frames]
        if clip_audio_items:
            last_audio_item = max(
                clip_audio_items,
                key=lambda raw: int(raw.get('offset_frames') or 0) + int(raw.get('duration_frames') or 0),
            )
            audio_end_frames = int(last_audio_item.get('offset_frames') or 0) + int(last_audio_item.get('duration_frames') or 0)
            frame_gap = clip_end_frames - audio_end_frames
            if 0 < frame_gap <= max(1, int(round(fps * 0.20))):
                last_audio_item['duration_frames'] = int(last_audio_item.get('duration_frames') or 0) + frame_gap

        cursor_frames += duration_frames

    total_duration_frames = max(
        [cursor_frames] + [int(item['offset_frames']) + int(item['duration_frames']) for item in sequence_items]
    ) if sequence_items else 0
    sequence.set('duration', frames_to_fcpx_time(total_duration_frames, fps))

    for item in sorted(sequence_items, key=lambda raw: (int(raw['offset_frames']), 0 if raw['kind'] == 'audio' else 1)):
        attributes = {
            'name': item['name'],
            'ref': item['ref'],
            'offset': frames_to_fcpx_time(int(item['offset_frames']), fps),
            'start': frames_to_fcpx_time(int(item['start_frames']), fps),
            'duration': frames_to_fcpx_time(int(item['duration_frames']), fps),
        }
        if item['kind'] == 'video':
            attributes['lane'] = str(item.get('lane') or '1')
            if item.get('src_enable'):
                attributes['srcEnable'] = str(item['src_enable'])
        clip_el = ET.SubElement(spine, 'asset-clip', attributes)
        gain_db = item.get('gain_db')
        if item['kind'] == 'audio' and gain_db is not None and abs(float(gain_db)) >= 0.1:
            ET.SubElement(clip_el, 'adjust-volume', {'amount': f'{float(gain_db):.2f}dB'})


def _source_path_for_item(item: Dict[str, Any]) -> Optional[str]:
    source_path = item.get('normalized_path') or item.get('stored_path')
    return str(source_path).strip() if source_path else None


def _interval_segments_for_role(project: Dict[str, Any], role: str, start: float, end: float, *, match_file_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get audio segments for a role within a time range.

    If match_file_id is provided, prefer segments from the same source file
    when the role matches, to ensure correct audio-video alignment.
    """
    pieces: List[Dict[str, Any]] = []
    role_files = (project.get('files') or {}).get(role) or []

    # If matching a specific file_id, try to find that file first
    if match_file_id:
        for item in role_files:
            if str(item.get('id') or '') == str(match_file_id):
                source_path = _source_path_for_item(item)
                if not source_path:
                    continue
                file_start = float(item.get('global_start_sec') or 0.0)
                file_end = float(item.get('global_end_sec') or file_start)
                overlap_start = max(start, file_start)
                overlap_end = min(end, file_end)
                if overlap_end > overlap_start:
                    pieces.append({
                        'source_path': source_path,
                        'analysis_audio_path': item.get('audio_path') or source_path,
                        'file_id': item.get('id'),
                        'global_start': round(overlap_start, 3),
                        'global_end': round(overlap_end, 3),
                        'local_start': round(overlap_start - file_start, 3),
                        'local_end': round(overlap_end - file_start, 3),
                        'duration': round(overlap_end - overlap_start, 3),
                    })
                break

    # Also add any other overlapping files for this role (for multi-cam)
    for item in sorted(role_files, key=lambda raw: float(raw.get('global_start_sec') or 0.0)):
        if str(item.get('id') or '') == str(match_file_id):
            continue  # Already added
        source_path = _source_path_for_item(item)
        if not source_path:
            continue
        file_start = float(item.get('global_start_sec') or 0.0)
        file_end = float(item.get('global_end_sec') or file_start)
        overlap_start = max(start, file_start)
        overlap_end = min(end, file_end)
        if overlap_end <= overlap_start:
            continue
        pieces.append({
            'source_path': source_path,
            'analysis_audio_path': item.get('audio_path') or source_path,
            'file_id': item.get('id'),
            'global_start': round(overlap_start, 3),
            'global_end': round(overlap_end, 3),
            'local_start': round(overlap_start - file_start, 3),
            'local_end': round(overlap_end - file_start, 3),
            'duration': round(overlap_end - overlap_start, 3),
        })
    return pieces


def _build_primary_audio_gain_cache(
    project: Dict[str, Any],
    primary_role: str,
    *,
    logger: Optional[LoggerFn] = None,
    progress_cb: Optional[ExportProgressCallback] = None,
) -> Tuple[Dict[str, float], Optional[Dict[str, Any]]]:
    """
    Build gain cache for all audio sources.

    Returns:
        - gain_cache: Dict mapping source_path -> gain_db for loudness normalization
        - normalize_settings: Dict with normalize_target_lufs for DaVinci Resolve
    """
    cache: Dict[str, float] = {}
    all_stats: Dict[str, Dict[str, Any]] = {}

    # Analyze ALL roles, not just primary_role
    source_items: List[Dict[str, Any]] = []
    for role, role_files in (project.get('files') or {}).items():
        for item in sorted(role_files or [], key=lambda f: int(f.get('order') or 0)):
            if _source_path_for_item(item):
                item['audio_role'] = role  # Track which role this file belongs to
                source_items.append(item)

    total_items = len(source_items)
    if total_items <= 0:
        if progress_cb:
            progress_cb({'stage': 'loudness', 'ratio': 1.0, 'message': 'Keine Audio-Dateien fuer Lautheitsanalyse.'})
        return cache, None

    for index, item in enumerate(source_items, start=1):
        source_path = _source_path_for_item(item)
        role = item.get('audio_role') or 'unknown'
        if not source_path or source_path in cache or not os.path.exists(source_path):
            continue
        try:
            item_name = item.get('original_name') or os.path.basename(source_path)
            if logger:
                logger(f'Export: Lautheit analysiere {index}/{total_items} · [{role}] {item_name}')

            def handle_progress(payload: Dict[str, Any], idx=index, name=item_name, r=role) -> None:
                if not progress_cb:
                    return
                ratio = (idx - 1 + float(payload.get('ratio') or 0.0)) / max(total_items, 1)
                progress_cb({
                    'stage': 'loudness',
                    'ratio': ratio,
                    'item_index': idx,
                    'item_count': total_items,
                    'item_name': name,
                    'item_role': r,
                    'speed': payload.get('speed') or '',
                    'message': f'Lautheit analysiere [{r}] {name}',
                })

            gain_db, stats = recommend_volume_adjustment_db(
                source_path,
                duration_sec=float(item.get('duration_sec') or 0.0),
                progress_cb=handle_progress,
            )
            cache[source_path] = gain_db
            all_stats[source_path] = {
                'gain_db': gain_db,
                'stats': stats,
                'role': role,
                'item': item,
            }
            item['loudness_gain_db'] = gain_db
            item['loudness_stats'] = stats
            if logger:
                logger(f'Export: Lautheit fertig fuer [{role}] {item_name} ({gain_db:+.2f} dB, {stats.get("input_i", -23):.1f} LUFS)')
            if progress_cb:
                progress_cb({
                    'stage': 'loudness',
                    'ratio': index / max(total_items, 1),
                    'item_index': index,
                    'item_count': total_items,
                    'item_name': item_name,
                    'item_role': role,
                    'message': f'Lautheit fertig fuer [{role}] {item_name}',
                })
        except Exception:
            continue

    # Calculate normalize settings for DaVinci Resolve
    # This helps Resolve understand relative loudness differences between roles
    normalize_settings = _calculate_loudness_normalize_settings(all_stats, primary_role, logger=logger)

    return cache, normalize_settings


def _calculate_loudness_normalize_settings(
    all_stats: Dict[str, Dict[str, Any]],
    primary_role: str,
    *,
    logger: Optional[LoggerFn] = None,
) -> Optional[Dict[str, Any]]:
    """
    Calculate loudness normalization settings for DaVinci Resolve.

    This creates a settings dict that Resolve can use to understand
    the relative loudness differences between roles (e.g., host vs guest).
    """
    if not all_stats:
        return None

    # Group by role and calculate average loudness
    role_loudness: Dict[str, List[float]] = {}
    for source_path, data in all_stats.items():
        role = data.get('role') or 'unknown'
        stats = data.get('stats') or {}
        input_lufs = float(stats.get('input_i') or -23.0)
        if role not in role_loudness:
            role_loudness[role] = []
        role_loudness[role].append(input_lufs)

    if not role_loudness:
        return None

    # Calculate average loudness per role
    role_avg_lufs: Dict[str, float] = {}
    for role, lufs_values in role_loudness.items():
        role_avg_lufs[role] = sum(lufs_values) / len(lufs_values)

    # Calculate relative difference between primary role and others
    primary_lufs = role_avg_lufs.get(primary_role)
    if primary_lufs is None:
        return None

    role_adjustments: Dict[str, float] = {}
    for role, avg_lufs in role_avg_lufs.items():
        if role != primary_role:
            # How much quieter is this role compared to primary?
            diff_db = primary_lufs - avg_lufs
            role_adjustments[role] = round(diff_db, 2)

    settings = {
        'normalize_target_lufs': -14.0,  # YouTube standard
        'primary_role': primary_role,
        'primary_role_avg_lufs': round(primary_lufs, 2),
        'role_adjustments_db': role_adjustments,
        'role_avg_lufs': {role: round(lufs, 2) for role, lufs in role_avg_lufs.items()},
    }

    if logger:
        for role, diff in role_adjustments.items():
            logger(f'Export: [{role}] ist {diff:+.1f} dB {("leiser" if diff > 0 else "lauter")} als [{primary_role}]')

    return settings


def export_fcpxml(
    project: Dict[str, Any],
    analysis_result: Dict[str, Any],
    output_path: str,
    *,
    logger: Optional[LoggerFn] = None,
    progress_cb: Optional[ExportProgressCallback] = None,
) -> Dict[str, Any]:
    fps = int((project.get('config') or {}).get('export_fps') or 25)
    primary_role = str((project.get('config') or {}).get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')).strip().lower()
    loudness_enabled = bool((project.get('config') or {}).get('export_loudness_adjustment_enabled'))
    root = ET.Element('fcpxml', {'version': '1.10'})
    resources = ET.SubElement(root, 'resources')
    format_id, asset_ids = _build_asset_resources(resources, project, fps)
    if progress_cb:
        progress_cb({'stage': 'assets', 'ratio': 0.08, 'message': 'Resolve-Assets vorbereitet.'})
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', {'name': project.get('project_name') or 'OpenShorts Longform'})
    if loudness_enabled:
        gain_cache, normalize_settings = _build_primary_audio_gain_cache(project, primary_role, logger=logger, progress_cb=progress_cb)
        if progress_cb:
            progress_cb({'stage': 'loudness', 'ratio': 0.60, 'message': 'Lautheitsanalyse abgeschlossen.'})
    else:
        gain_cache, normalize_settings = {}, None
        if progress_cb:
            progress_cb({'stage': 'loudness', 'ratio': 0.60, 'message': 'Lautheitsanpassung deaktiviert.'})

    rough_cut_clips: List[Dict[str, Any]] = []
    for shot_index, shot in enumerate(analysis_result.get('shots') or [], start=1):
        shot_role = str(shot.get('role', 'host')).strip().lower()
        for segment_index, segment in enumerate(shot.get('segments') or [], start=1):
            source_path = segment.get('source_path')
            asset_ref = _resolve_asset_ref(asset_ids, str(source_path or ''), 'video') if source_path else None
            if not source_path or not asset_ref:
                continue
            global_start = float(segment.get('global_start') or shot.get('start') or 0.0)
            global_end = float(segment.get('global_end') or (global_start + float(segment.get('duration') or 0.0)))
            rough_cut_clips.append({
                'name': f"{shot_role.upper()} Shot {shot_index}.{segment_index}",
                'asset_id': asset_ref,
                'source_start': float(segment.get('local_start') or 0.0),
                'duration': float(segment.get('duration') or 0.0),
                'global_start': global_start,
                'src_enable': 'video',
                'audio_segments': _interval_segments_for_role(
                    project,
                    primary_role,
                    global_start,
                    global_end,
                ),
            })
    if logger:
        logger(f"Export: Rough Cut wird aufgebaut ({len(rough_cut_clips)} Clips).")
    if progress_cb:
        progress_cb({'stage': 'rough_cut', 'ratio': 0.78, 'message': f'Rough Cut mit {len(rough_cut_clips)} Clips aufgebaut.'})
    _add_resolve_rough_cut_project(
        event,
        name=f"{project.get('project_name')} Rough Cut",
        format_id=format_id,
        fps=fps,
        clips=rough_cut_clips,
        asset_ids=asset_ids,
        gain_cache=gain_cache,
        enable_gain_adjustments=loudness_enabled,
    )

    stringout_project_count = 0
    for role, role_files in (project.get('files') or {}).items():
        stringout_clips: List[Dict[str, Any]] = []
        for item in sorted(role_files or [], key=lambda raw: int(raw.get('order') or 0)):
            source_path = _source_path_for_item(item)
            asset_ref = _resolve_asset_ref(asset_ids, str(source_path or ''), 'video') if source_path else None
            if not source_path or not asset_ref:
                continue
            stringout_clips.append({
                'name': f"{role.upper()} {item.get('original_name') or item.get('id')}",
                'asset_id': asset_ref,
                'source_start': 0.0,
                'duration': float(item.get('duration_sec') or 0.0),
            })
        if stringout_clips:
            stringout_project_count += 1
            _add_project(
                event,
                name=f"{project.get('project_name')} {role.title()} Stringout",
                format_id=format_id,
                fps=fps,
                clips=stringout_clips,
                asset_ids=asset_ids,
            )
    if logger:
        logger(f'Export: {stringout_project_count} Stringout-Timelines angelegt.')
    if progress_cb:
        progress_cb({'stage': 'stringouts', 'ratio': 0.92, 'message': f'{stringout_project_count} Stringouts angelegt.'})

    _indent(root)
    tree = ET.ElementTree(root)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tree.write(output_path, encoding='utf-8', xml_declaration=True)
    if logger:
        logger(f'Export: FCPXML geschrieben ({os.path.basename(output_path)}).')
    if progress_cb:
        progress_cb({'stage': 'write', 'ratio': 1.0, 'message': f'FCPXML geschrieben: {os.path.basename(output_path)}'})

    # Build return metadata
    result = {
        'path': output_path,
        'url': media_url_from_path(output_path),
        'name': os.path.basename(output_path),
    }

    normalize_json_path = output_path.replace('.fcpxml', '_loudness.json')

    # Include loudness normalization settings for DaVinci Resolve
    # This helps Resolve understand relative differences between roles
    if loudness_enabled and normalize_settings:
        result['loudness_normalize_settings'] = normalize_settings

        # Save as separate JSON for easy access by Resolve scripts or frontend
        with open(normalize_json_path, 'w', encoding='utf-8') as f:
            json.dump(normalize_settings, f, ensure_ascii=False, indent=2)
        result['loudness_json'] = {
            'path': normalize_json_path,
            'url': media_url_from_path(normalize_json_path),
            'name': os.path.basename(normalize_json_path),
        }
        if logger:
            logger(f'Export: Lautheits-Info gespeichert ({os.path.basename(normalize_json_path)})')
            logger(f'  -> [{primary_role}]: {normalize_settings.get("primary_role_avg_lufs")} LUFS (Referenz)')
            for role, diff in normalize_settings.get('role_adjustments_db', {}).items():
                logger(f'  -> [{role}]: +{diff:.1f} dB Lautstaerke-Empfehlung')
    elif os.path.exists(normalize_json_path):
        try:
            os.remove(normalize_json_path)
        except OSError:
            pass

    return result


def export_markers_csv(markers: Iterable[Dict[str, Any]], output_path: str) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['start', 'end', 'type', 'role', 'note'])
        writer.writeheader()
        for marker in markers:
            writer.writerow({
                'start': marker.get('start'),
                'end': marker.get('end'),
                'type': marker.get('type'),
                'role': marker.get('role', ''),
                'note': marker.get('note', ''),
            })
    return {
        'path': output_path,
        'url': media_url_from_path(output_path),
        'name': os.path.basename(output_path),
    }


def export_json(payload: Dict[str, Any], output_path: str) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return {
        'path': output_path,
        'url': media_url_from_path(output_path),
        'name': os.path.basename(output_path),
    }
