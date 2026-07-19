from __future__ import annotations

import json
import logging
import math
import os
import re
import shlex
import subprocess
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from runtime_limits import ffmpeg_thread_args, subprocess_priority_kwargs, FFMPEG_PRESET

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[Dict[str, Any]], None]


def _ffmpeg_supports_encoder(encoder_name: str) -> bool:
    if not encoder_name:
        return False
    try:
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True,
            text=True,
            check=True,
            **subprocess_priority_kwargs(),
        )
        return encoder_name in (result.stdout or '')
    except Exception:
        return False


def resolve_longform_video_encoder() -> tuple[str, list[str]]:
    preferred = (os.environ.get('LONGFORM_VIDEO_ENCODER') or 'auto').strip().lower()
    if preferred in {'h264_nvenc', 'nvenc', 'gpu', 'auto'} and _ffmpeg_supports_encoder('h264_nvenc'):
        # p5 is a strong speed/quality tradeoff on Ada GPUs.
        return 'h264_nvenc', ['-preset', (os.environ.get('LONGFORM_NVENC_PRESET') or 'p5').strip(), '-cq', str(os.environ.get('LONGFORM_NVENC_CQ') or '19')]
    return 'libx264', ['-preset', FFMPEG_PRESET, '-crf', str(os.environ.get('LONGFORM_X264_CRF') or '18')]


def _run_ffmpeg_with_progress(
    cmd: List[str],
    *,
    duration_sec: Optional[float] = None,
    progress_cb: Optional[ProgressCallback] = None,
) -> str:
    full_cmd = list(cmd)
    full_cmd[1:1] = ['-nostats', '-progress', 'pipe:1']
    process = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
        **subprocess_priority_kwargs(),
    )
    progress_payload: Dict[str, str] = {}
    try:
        if process.stdout:
            for raw_line in process.stdout:
                line = str(raw_line or '').strip()
                if not line or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                progress_payload[key.strip()] = value.strip()
                if key.strip() == 'progress':
                    out_time_us = progress_payload.get('out_time_us') or progress_payload.get('out_time_ms')
                    try:
                        out_time_seconds = float(out_time_us) / 1000000.0 if out_time_us is not None else 0.0
                    except Exception:
                        out_time_seconds = 0.0
                    ratio = 0.0
                    if duration_sec and duration_sec > 0:
                        ratio = max(0.0, min(1.0, out_time_seconds / duration_sec))
                    if progress_cb:
                        progress_cb({
                            'out_time_seconds': out_time_seconds,
                            'ratio': ratio,
                            'speed': progress_payload.get('speed') or '',
                            'fps': progress_payload.get('fps') or '',
                            'frame': progress_payload.get('frame') or '',
                            'bitrate': progress_payload.get('bitrate') or '',
                            'status': progress_payload.get('progress') or '',
                        })
                    progress_payload = {}
        stderr_text = process.stderr.read() if process.stderr else ''
        return_code = process.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, full_cmd, output='', stderr=stderr_text)
        return stderr_text
    finally:
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass
        try:
            if process.stderr:
                process.stderr.close()
        except Exception:
            pass


def probe_media(path: str) -> Dict[str, Any]:
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, **subprocess_priority_kwargs())
    payload = json.loads(result.stdout or '{}')
    streams = payload.get('streams') or []
    format_info = payload.get('format') or {}
    video_stream = next((stream for stream in streams if stream.get('codec_type') == 'video'), {})
    audio_stream = next((stream for stream in streams if stream.get('codec_type') == 'audio'), {})
    frame_rate = _parse_ratio(video_stream.get('avg_frame_rate')) or _parse_ratio(video_stream.get('r_frame_rate')) or 0.0
    duration_sec = _safe_float(format_info.get('duration'))
    return {
        'duration_sec': duration_sec,
        'size_bytes': _safe_int(format_info.get('size')),
        'bit_rate': _safe_int(format_info.get('bit_rate')),
        'width': _safe_int(video_stream.get('width')),
        'height': _safe_int(video_stream.get('height')),
        'fps': frame_rate,
        'sample_rate': _safe_int(audio_stream.get('sample_rate')),
        'channels': _safe_int(audio_stream.get('channels')),
        'has_audio': bool(audio_stream),
        'has_video': bool(video_stream),
        'video_codec': video_stream.get('codec_name') or '',
        'audio_codec': audio_stream.get('codec_name') or '',
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _parse_ratio(value: Any) -> float:
    text = str(value or '').strip()
    if not text or text == '0/0':
        return 0.0
    if '/' not in text:
        return _safe_float(text)
    left, right = text.split('/', 1)
    denominator = _safe_float(right)
    if abs(denominator) < 1e-9:
        return 0.0
    return _safe_float(left) / denominator


def slugify_filename(value: str) -> str:
    slug = re.sub(r'[^A-Za-z0-9._-]+', '_', value or '').strip('._')
    return slug or 'file'


def transcode_to_cfr(input_path: str, output_path: str, *, fps: int, sample_rate: int = 48000, duration_sec: Optional[float] = None, progress_cb: Optional[ProgressCallback] = None) -> None:
    video_encoder, video_encoder_args = resolve_longform_video_encoder()
    cmd = [
        'ffmpeg', '-y', '-v', 'error', '-fflags', '+discardcorrupt', '-err_detect', 'ignore_err',
        '-i', input_path,
        '-r', str(fps),
        '-vsync', 'cfr',
        '-pix_fmt', 'yuv420p',
        '-c:v', video_encoder,
        *video_encoder_args,
        '-c:a', 'aac',
        '-ar', str(sample_rate),
        '-b:a', '192k',
        '-movflags', '+faststart',
        *ffmpeg_thread_args(include_filter_threads=True),
        output_path,
    ]
    _run_ffmpeg_with_progress(cmd, duration_sec=duration_sec, progress_cb=progress_cb)


def create_proxy(input_path: str, output_path: str, *, fps: int, height: int = 720, duration_sec: Optional[float] = None, progress_cb: Optional[ProgressCallback] = None) -> None:
    video_encoder, video_encoder_args = resolve_longform_video_encoder()
    scale = f'scale=-2:{max(240, height)}:flags=lanczos'
    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-i', input_path,
        '-vf', scale,
        '-r', str(fps),
        '-c:v', video_encoder,
        *video_encoder_args,
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        *ffmpeg_thread_args(include_filter_threads=True),
        output_path,
    ]
    _run_ffmpeg_with_progress(cmd, duration_sec=duration_sec, progress_cb=progress_cb)


def extract_audio_analysis(input_path: str, output_path: str, *, sample_rate: int = 16000, duration_sec: Optional[float] = None, progress_cb: Optional[ProgressCallback] = None) -> None:
    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-i', input_path,
        '-vn', '-ac', '1', '-ar', str(sample_rate), '-c:a', 'flac',
        *ffmpeg_thread_args(),
        output_path,
    ]
    _run_ffmpeg_with_progress(cmd, duration_sec=duration_sec, progress_cb=progress_cb)


def extract_audio_wav(input_path: str, output_path: str, *, sample_rate: int = 16000, duration_sec: Optional[float] = None, progress_cb: Optional[ProgressCallback] = None) -> None:
    extract_audio_analysis(
        input_path,
        output_path,
        sample_rate=sample_rate,
        duration_sec=duration_sec,
        progress_cb=progress_cb,
    )


def measure_loudness_stats(
    input_path: str,
    *,
    duration_sec: Optional[float] = None,
    progress_cb: Optional[ProgressCallback] = None,
) -> Dict[str, float]:
    cmd = [
        'ffmpeg', '-hide_banner', '-nostats', '-i', input_path,
        '-vn',
        '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json',
        '-f', 'null',
        '-',
    ]
    stderr_text = _run_ffmpeg_with_progress(cmd, duration_sec=duration_sec, progress_cb=progress_cb) or ''
    start = stderr_text.rfind('{')
    end = stderr_text.rfind('}')
    if start < 0 or end <= start:
        raise RuntimeError('Could not parse loudnorm output.')
    payload = json.loads(stderr_text[start:end + 1])
    return {
        'input_i': _safe_float(payload.get('input_i')),
        'input_tp': _safe_float(payload.get('input_tp')),
        'input_lra': _safe_float(payload.get('input_lra')),
        'input_thresh': _safe_float(payload.get('input_thresh')),
        'target_offset': _safe_float(payload.get('target_offset')),
    }


def recommend_volume_adjustment_db(
    input_path: str,
    *,
    target_lufs: float = -14.0,
    max_true_peak_db: float = -1.5,
    clamp_db: float = 12.0,
    duration_sec: Optional[float] = None,
    progress_cb: Optional[ProgressCallback] = None,
) -> Tuple[float, Dict[str, float]]:
    stats = measure_loudness_stats(input_path, duration_sec=duration_sec, progress_cb=progress_cb)
    gain_db = target_lufs - float(stats.get('input_i') or target_lufs)
    input_tp = float(stats.get('input_tp') or max_true_peak_db)
    if input_tp + gain_db > max_true_peak_db:
        gain_db = max_true_peak_db - input_tp
    gain_db = max(-abs(clamp_db), min(abs(clamp_db), gain_db))
    return round(gain_db, 2), stats


def concat_audio_wavs(input_paths: Iterable[str], output_path: str) -> None:
    input_paths = [path for path in input_paths if path and os.path.exists(path)]
    if not input_paths:
        raise RuntimeError('No audio files available for concat.')
    if len(input_paths) == 1:
        if os.path.abspath(input_paths[0]) != os.path.abspath(output_path):
            with open(input_paths[0], 'rb') as source, open(output_path, 'wb') as target:
                target.write(source.read())
        return
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as handle:
        list_path = handle.name
        for path in input_paths:
            handle.write(f"file {shlex.quote(os.path.abspath(path))}\n")
    try:
        cmd = [
            'ffmpeg', '-y', '-v', 'error',
            '-f', 'concat', '-safe', '0', '-i', list_path,
            '-c', 'copy',
            output_path,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_priority_kwargs())
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def export_audio_stereo_program(input_paths: Iterable[str], output_path: str, *, sample_rate: int = 48000) -> None:
    input_paths = [path for path in input_paths if path and os.path.exists(path)]
    if not input_paths:
        raise RuntimeError('No audio files available for stereo export.')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix='openshorts_longform_stereo_')
    try:
        temp_wavs: List[str] = []
        for index, path in enumerate(input_paths, start=1):
            temp_wav = os.path.join(temp_dir, f'source_{index:03d}.wav')
            cmd = [
                'ffmpeg', '-y', '-v', 'error',
                '-i', path,
                '-vn',
                '-ac', '2',
                '-ar', str(sample_rate),
                '-c:a', 'pcm_s16le',
                temp_wav,
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_priority_kwargs())
            temp_wavs.append(temp_wav)
        concat_audio_wavs(temp_wavs, output_path)
    finally:
        try:
            for name in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, name))
            os.rmdir(temp_dir)
        except Exception:
            pass


def export_audio_channel_stem(input_path: str, output_path: str, *, channel: str, sample_rate: int = 48000) -> None:
    if channel not in {'left', 'right'}:
        raise ValueError('channel must be left or right')
    pan_expr = 'pan=mono|c0=c0' if channel == 'left' else 'pan=mono|c0=c1'
    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-i', input_path,
        '-vn',
        '-af', pan_expr,
        '-ar', str(sample_rate),
        '-c:a', 'pcm_s16le',
        output_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_priority_kwargs())


def media_url_from_path(path: Optional[str], *, cache_buster: Optional[str] = None) -> Optional[str]:
    if not path:
        return None
    normalized = os.path.normpath(path)
    if normalized.startswith('output' + os.sep):
        relative = normalized[len('output' + os.sep):].replace(os.sep, '/')
        url = f'/videos/{relative}'
        if cache_buster:
            separator = '&' if '?' in url else '?'
            url = f'{url}{separator}{cache_buster}'
        return url
    return None


def extract_thumbnail_frames(
    video_path: str,
    output_dir: str,
    *,
    num_frames: int = 5,
    width: int = 640,
    quality: int = 85,
    seek_offset_sec: float = 5.0,
) -> List[str]:
    """
    Extract evenly distributed thumbnail frames from a video for AI thumbnail generation.

    Args:
        video_path: Path to the video file
        output_dir: Directory to save thumbnail images
        num_frames: Number of frames to extract (default 5)
        width: Output width in pixels (default 640)
        quality: JPEG quality 1-100 (default 85)
        seek_offset_sec: Offset from start/end to avoid intro/outro

    Returns:
        List of saved thumbnail file paths
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    os.makedirs(output_dir, exist_ok=True)

    # Get video duration
    probe = probe_media(video_path)
    duration_sec = probe.get('duration_sec', 0.0)

    if duration_sec <= 10.0:
        # Short video: just extract one frame
        timestamps = [duration_sec / 2.0]
    else:
        # Calculate evenly spaced timestamps
        min_ts = seek_offset_sec
        max_ts = duration_sec - seek_offset_sec
        timestamps = []
        for i in range(num_frames):
            ts = min_ts + (max_ts - min_ts) * i / max(1, num_frames - 1)
            timestamps.append(ts)

    saved_paths = []
    for idx, ts in enumerate(timestamps, start=1):
        output_path = os.path.join(output_dir, f"frame_{idx:02d}.jpg")
        cmd = [
            'ffmpeg', '-y', '-v', 'error',
            '-ss', f'{ts:.2f}',
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={width}:-2',
            '-q:v', str(26 - quality // 4),  # Convert quality to ffmpeg qscale
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, **subprocess_priority_kwargs())
            if os.path.exists(output_path):
                saved_paths.append(output_path)
        except subprocess.CalledProcessError as e:
            LOGGER.warning(f"Failed to extract frame at {ts:.2f}s: {e}")
            continue

    return saved_paths
