from __future__ import annotations

import difflib
import json
import logging
import math
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
from scipy import signal

from runtime_limits import subprocess_priority_kwargs
from whisper_runtime import transcribe_with_runtime

try:
    from pyannote.audio import Pipeline as PyannotePipeline
except Exception:  # pragma: no cover - optional dependency
    PyannotePipeline = None

LOGGER = logging.getLogger(__name__)
_PYANNOTE_PIPELINE = None
_PYANNOTE_PIPELINE_TOKEN = None
_PYANNOTE_DIARIZATION_CACHE: Dict[str, List[Dict[str, Any]]] = {}

BACKCHANNEL_TOKENS = {
    'mhm', 'mhm.', 'ja', 'ja.', 'genau', 'stimmt', 'klar', 'okay', 'ok', 'yes', 'yeah', 'yep',
    'uh-huh', 'mm', 'hmm', 'hm', 'aha', 'krass', 'wow', 'nice', 'safe',
}
FILLER_TOKENS = {
    'äh', 'ähm', 'hm', 'hmm', 'also', 'so', 'quasi', 'halt', 'eigentlich', 'you', 'know', 'like', 'uh', 'um',
}
RETAKE_PREFIXES = (
    'nee', 'nein', 'anders', 'nochmal', 'ich fang', 'warte', 'lass mich',
    'sorry', 'ich meine', 'ich meinte', 'stopp', 'halt', 'noch einmal', 'ich sag',
    'ich sage', 'ich formuliere', 'ich versuch', 'falsch', 'vergiss', 'quatsch',
)
INTRO_CUE_PHRASES = (
    'hallo und herzlich willkommen',
    'herzlich willkommen',
    'willkommen zurück',
    'willkommen zu einer neuen folge',
    'willkommen zu unserem podcast',
    'willkommen zu diesem podcast',
    'willkommen auf meinem kanal',
    'willkommen auf unserem kanal',
    'schön dass du da bist',
    'schön dass ihr da seid',
    'heute sprechen wir',
    'heute reden wir',
    'in dieser folge',
    'in dieser episode',
    'los gehts',
    'lass uns rein starten',
)
OFFICIAL_INTRO_IDENTITY_PHRASES = (
    'mein name ist',
    'ich bin anna',
    'ich bin',
    'mein kanal',
    'unser kanal',
    'auf diesem kanal',
    'auf meinem kanal',
    'auf unserem kanal',
    'in diesem podcast',
    'im podcast',
    'für alle die neu hier sind',
    'wenn du neu hier bist',
    'schön dass ihr eingeschaltet habt',
    'schön dass du eingeschaltet hast',
)
SETUP_CUE_PHRASES = (
    'kamera läuft',
    'ton läuft',
    'läuft schon',
    'läuft jetzt',
    'kannst du mich hören',
    'hörst du mich',
    'mikro',
    'mikrophon',
    'mikrofon',
    'eins zwei',
    'eins zwei drei',
    'audio test',
    'soundcheck',
    'check check',
    'warte kurz',
    'warte mal',
    'eine sekunde',
    'sekunde noch',
    'gleich gehts los',
    'wir fangen gleich an',
    'klappe',
    'speicherkarte',
    'speicher voll',
    'akku',
    'batterie',
    'licht',
    'die kamera',
    'hast du aufgenommen',
    'nimmst du auf',
    'moment noch',
    'noch ein test',
    'nochmal',
    'nochmal von vorne',
    'noch ein take',
    'testaufnahme',
    'hier sind wir',
    'aufnahme läuft',
    ' Recording',
    ' Recording läuft',
    'habt ihr mich',
    'sehe ich gut',
    'hörst du das',
    'kannst hören',
    'ist das an',
    'bist du bereit',
    'bist du so weit',
    'kurz warten',
    'warte noch',
    'einen moment',
    'hallo hallo',
    'test test',
    'ist jemand',
    'geht das hier',
    'kann mich jemand',
)
CONTINUATION_CUE_PHRASES = (
    'wir machen weiter',
    'wir sind wieder da',
    'kurze unterbrechung',
    'nach einer kurzen pause',
    'wo waren wir',
    'wir waren gerade',
    'ich setz nochmal an',
    'wir schneiden das raus',
    'das nehmen wir nochmal',
    'wir machen nochmal weiter',
    'ich setze nochmal an',
)
OUTRO_CUE_PHRASES = (
    'danke fürs zuhören',
    'danke fürs zuschauen',
    'bis zum nächsten mal',
    'bis zur nächsten folge',
    'macht es gut',
    'tschüss',
    'ciao',
    'das wars',
    'das war es',
    'abonniert',
    'lasst ein like da',
)
RETAKE_CUE_PHRASES = (
    # Explicit retake requests
    'das muss ich nochmal aufnehmen',
    'das muss ich nochmal machen',
    'das muss ich neu machen',
    'das muss ich nochmal versuchen',
    'ich nehme das nochmal auf',
    'lass mich das nochmal sagen',
    'ich sag das nochmal',
    'ich sage das nochmal',
    'ich formuliere das nochmal',
    'ich formuliere das neu',
    'ich formuliere den gedanken nochmal',
    'warte ich fang nochmal an',
    'warte ich fange nochmal an',
    'ich fang nochmal an',
    'ich fange nochmal an',
    'ich setz nochmal an',
    'ich setze nochmal an',
    'das nehmen wir nochmal',
    'wir nehmen das nochmal',
    'wir schneiden das raus',
    'das schneiden wir raus',
    'das machen wir nochmal',
    'lass mich das nochmal',
    'lass mich neu anfangen',
    'ich fang nochmal von vorne an',
    'nochmal bitte',
    'nochmal von vorne',
    'nochmal kurz',
    'kurz nochmal',
    'kurz von vorne',
    'stopp mal',
    'halt stopp',
    'warte stopp',
    'nee warte',
    'nein warte',
    'nee nee',
    'nein nein',
    'quatsch warte',
    'ups warte',
    'falsch',
    'das war falsch',
    'neuer versuch',
    'neuer anlauf',
    'anderer ansatz',
    'anders gesagt',
    'so stimmts nicht',
    'so ist besser',
    'anderes wort',
    'besseres wort',
    'anderen satz',
    'anderen satz bitte',
    'ich meine eigentlich',
    'ich meinte eigentlich',
    'ich meinte anders',
    'sorry warte',
    'entschuldigung warte',
    'ups',
    'verflixt',
    'verdammt',
    ' Mist',
    'so nicht',
    ' nein ',
)
_AUDIO_ACTIVITY_CACHE: Dict[str, Dict[str, Any]] = {}
_TRANSCRIPT_EVIDENCE_CACHE: Dict[str, Dict[str, Any]] = {}


class LongformStopRequested(RuntimeError):
    pass


LoggerFn = Callable[[str], None]


def _default_logger(message: str) -> None:
    LOGGER.info(message)


def _find_local_pyannote_model_dir() -> Optional[str]:
    cache_roots = [
        os.environ.get('HF_HOME'),
        os.path.expanduser('~/.cache/huggingface/hub'),
        '/root/.cache/huggingface/hub',
        '/app/.cache/huggingface/hub',
    ]
    seen: set[str] = set()
    for root in cache_roots:
        if not root:
            continue
        normalized_root = os.path.abspath(root)
        if normalized_root in seen:
            continue
        seen.add(normalized_root)
        model_root = os.path.join(normalized_root, 'models--pyannote--speaker-diarization-3.1', 'snapshots')
        if not os.path.isdir(model_root):
            continue
        try:
            snapshot_names = sorted(os.listdir(model_root), reverse=True)
        except Exception:
            continue
        for snapshot_name in snapshot_names:
            snapshot_path = os.path.join(model_root, snapshot_name)
            if os.path.isdir(snapshot_path) and os.path.exists(os.path.join(snapshot_path, 'config.yaml')):
                return snapshot_path
    return None


def _normalize_phrase_text(text: str) -> str:
    return ' '.join(token for token in (_normalize_token(part) for part in str(text or '').split()) if token)


def _contains_any_phrase(text: str, phrases: Iterable[str]) -> bool:
    normalized = _normalize_phrase_text(text)
    if not normalized:
        return False
    for phrase in phrases:
        candidate = _normalize_phrase_text(phrase)
        if candidate and candidate in normalized:
            return True
    return False


def _project_file_identity(item: Dict[str, Any]) -> str:
    for key in ('stored_path', 'normalized_path', 'proxy_path', 'audio_path'):
        path = str(item.get(key) or '').strip()
        if not path:
            continue
        try:
            return os.path.realpath(path)
        except Exception:
            return path
    return f"id:{item.get('id') or ''}:{item.get('original_name') or ''}"


def _project_file_richness(item: Dict[str, Any]) -> int:
    score = 0
    for key in ('audio_path', 'transcript_path', 'normalized_path', 'proxy_path', 'global_start_sec', 'global_end_sec', 'sync_confidence'):
        if item.get(key) not in (None, '', []):
            score += 1
    if item.get('has_audio'):
        score += 1
    if item.get('has_video'):
        score += 1
    return score


def unique_role_files(project: Dict[str, Any], role: str, logger: Optional[LoggerFn] = None) -> List[Dict[str, Any]]:
    ordered_files = sorted((project.get('files') or {}).get(role) or [], key=lambda raw: (int(raw.get('order') or 0), str(raw.get('uploaded_at') or '')))
    identities: List[str] = []
    selected: Dict[str, Dict[str, Any]] = {}
    duplicate_count = 0
    for item in ordered_files:
        identity = _project_file_identity(item)
        if identity not in selected:
            identities.append(identity)
            selected[identity] = item
            continue
        duplicate_count += 1
        if _project_file_richness(item) > _project_file_richness(selected[identity]):
            selected[identity] = item
    if duplicate_count and logger:
        logger(f'Projekt enthaelt {duplicate_count} doppelte Datei-Eintraege fuer Rolle {role}; verwende automatisch die beste Quelle.')
    return [selected[identity] for identity in identities if identity in selected]


def ensure_not_stopped(stop_checker: Optional[Callable[[], bool]]) -> None:
    if stop_checker and stop_checker():
        raise LongformStopRequested('Longform processing stopped by user.')


def read_audio_mono(path: str, *, sample_rate: int = 16000) -> Tuple[np.ndarray, int]:
    cmd = [
        'ffmpeg',
        '-v', 'error',
        '-i', path,
        '-vn',
        '-ac', '1',
        '-ar', str(sample_rate),
        '-f', 's16le',
        '-',
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        check=True,
        **subprocess_priority_kwargs(),
    )
    samples = np.frombuffer(result.stdout or b'', dtype=np.int16)
    return samples.astype(np.float32) / 32768.0, sample_rate


def build_envelope_from_audio(path: str, *, hop_sec: float = 0.1, window_sec: float = 0.2) -> Tuple[np.ndarray, int, float]:
    samples, sample_rate = read_audio_mono(path)
    hop = max(1, int(sample_rate * hop_sec))
    window = max(hop, int(sample_rate * window_sec))
    if samples.size == 0:
        return np.zeros(1, dtype=np.float32), sample_rate, hop_sec
    values: List[float] = []
    for start in range(0, samples.size, hop):
        chunk = samples[start:start + window]
        if chunk.size == 0:
            continue
        values.append(float(np.sqrt(np.mean(np.square(chunk))) if chunk.size else 0.0))
    envelope = np.asarray(values or [0.0], dtype=np.float32)
    if envelope.size > 1:
        envelope = (envelope - float(envelope.mean())) / max(float(envelope.std()), 1e-6)
    return envelope, sample_rate, hop_sec


def _bandpass_voice_audio(samples: np.ndarray, sample_rate: int, *, low_hz: float = 90.0, high_hz: float = 1800.0) -> np.ndarray:
    if samples.size == 0 or sample_rate <= 0:
        return samples.astype(np.float32)
    nyquist_guard = max(120.0, sample_rate * 0.45)
    low = max(20.0, min(low_hz, nyquist_guard - 40.0))
    high = max(low + 40.0, min(high_hz, nyquist_guard))
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        return samples.astype(np.float32)
    try:
        sos = signal.butter(4, [low, high], btype='bandpass', fs=sample_rate, output='sos')
        filtered = signal.sosfiltfilt(sos, samples.astype(np.float32, copy=False))
        return np.asarray(filtered, dtype=np.float32)
    except Exception:
        return samples.astype(np.float32, copy=False)


def _normalize_feature_vector(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.size == 0:
        return np.zeros(1, dtype=np.float32)
    arr = arr - float(arr.mean())
    arr = arr / max(float(arr.std()), 1e-4)
    return arr.astype(np.float32, copy=False)


def build_sync_feature_sequence(
    path: str,
    *,
    sample_rate: int = 4000,
    frame_sec: float = 0.08,
    hop_sec: float = 0.02,
    min_freq_hz: float = 90.0,
    max_freq_hz: float = 1800.0,
    num_bands: int = 16,
) -> Tuple[np.ndarray, float]:
    samples, audio_sample_rate = read_audio_mono(path, sample_rate=sample_rate)
    if samples.size == 0:
        return np.zeros((1, 1), dtype=np.float32), hop_sec
    filtered = _bandpass_voice_audio(samples, audio_sample_rate, low_hz=min_freq_hz, high_hz=max_freq_hz)
    frame_size = max(64, int(audio_sample_rate * frame_sec))
    hop_size = max(8, int(audio_sample_rate * hop_sec))
    noverlap = max(0, frame_size - hop_size)
    freqs, _, stft = signal.stft(
        filtered,
        fs=audio_sample_rate,
        window='hann',
        nperseg=frame_size,
        noverlap=noverlap,
        boundary=None,
        padded=False,
    )
    magnitude = np.abs(stft).astype(np.float32)
    if magnitude.size == 0 or magnitude.shape[1] == 0:
        return np.zeros((1, 1), dtype=np.float32), hop_size / float(audio_sample_rate)
    keep_mask = (freqs >= min_freq_hz) & (freqs <= max_freq_hz)
    magnitude = magnitude[keep_mask]
    freqs = freqs[keep_mask]
    if magnitude.size == 0 or magnitude.shape[0] == 0:
        return np.zeros((1, max(1, magnitude.shape[1])), dtype=np.float32), hop_size / float(audio_sample_rate)
    log_magnitude = np.log1p(magnitude)
    band_groups = np.array_split(np.arange(log_magnitude.shape[0]), max(1, int(num_bands)))
    band_rows = [
        log_magnitude[group].mean(axis=0) if len(group) else np.zeros(log_magnitude.shape[1], dtype=np.float32)
        for group in band_groups
    ]
    bands = np.vstack(band_rows).astype(np.float32)
    spectral_flux = np.sqrt(
        np.mean(
            np.square(np.maximum(0.0, np.diff(log_magnitude, axis=1, prepend=log_magnitude[:, :1]))),
            axis=0,
            dtype=np.float64,
        )
    ).astype(np.float32)
    energy = np.sqrt(np.mean(np.square(log_magnitude), axis=0, dtype=np.float64)).astype(np.float32)
    centroid = (
        (freqs[:, None] * magnitude).sum(axis=0) / np.maximum(magnitude.sum(axis=0), 1e-6)
    ).astype(np.float32) / max(float(max_freq_hz), 1.0)
    sequence = np.vstack([bands, spectral_flux[None, :], energy[None, :], centroid[None, :]]).astype(np.float32)
    normalized_rows = [_normalize_feature_vector(row) for row in sequence]
    return np.vstack(normalized_rows).astype(np.float32), hop_size / float(audio_sample_rate)


def build_fine_sync_sequence(
    path: str,
    *,
    sample_rate: int = 2000,
    window_sec: float = 0.04,
    hop_sec: float = 0.01,
    min_freq_hz: float = 90.0,
    max_freq_hz: float = 900.0,
) -> Tuple[np.ndarray, float]:
    samples, audio_sample_rate = read_audio_mono(path, sample_rate=sample_rate)
    if samples.size == 0:
        return np.zeros(1, dtype=np.float32), hop_sec
    filtered = _bandpass_voice_audio(samples, audio_sample_rate, low_hz=min_freq_hz, high_hz=max_freq_hz)
    hop_size = max(4, int(audio_sample_rate * hop_sec))
    window_size = max(hop_size * 2, int(audio_sample_rate * window_sec))
    values: List[float] = []
    limit = max(1, filtered.size - window_size + 1)
    for start in range(0, limit, hop_size):
        chunk = filtered[start:start + window_size]
        if chunk.size == 0:
            continue
        values.append(float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64))))
    sequence = np.asarray(values or [0.0], dtype=np.float32)
    sequence = np.log1p(sequence * 20.0)
    return _normalize_feature_vector(sequence), hop_size / float(audio_sample_rate)


def _peak_confidence(scores: np.ndarray, best_index: int, *, exclusion_radius: int) -> float:
    if scores.size == 0:
        return 0.0
    best_score = float(scores[best_index])
    mean_score = float(np.mean(scores))
    std_score = max(float(np.std(scores)), 1e-6)
    zscore = max(0.0, (best_score - mean_score) / std_score)
    mask = np.ones(scores.shape[0], dtype=bool)
    low = max(0, best_index - exclusion_radius)
    high = min(scores.shape[0], best_index + exclusion_radius + 1)
    mask[low:high] = False
    second_best = float(np.max(scores[mask])) if np.any(mask) else mean_score
    separation = max(0.0, best_score - second_best) / max(abs(best_score), 1e-6)
    confidence = 0.24 + min(0.44, zscore * 0.045) + min(0.26, separation * 0.70)
    return max(0.0, min(0.98, confidence))


def correlate_feature_sequences(reference: np.ndarray, target: np.ndarray, *, hop_sec: float) -> Tuple[float, float]:
    if reference.size == 0 or target.size == 0:
        return 0.0, 0.0
    if reference.ndim == 1:
        reference = reference[None, :]
    if target.ndim == 1:
        target = target[None, :]
    feature_count = min(reference.shape[0], target.shape[0])
    if feature_count <= 0 or reference.shape[1] <= 1 or target.shape[1] <= 1:
        return 0.0, 0.0
    score_curve: Optional[np.ndarray] = None
    for index in range(feature_count):
        ref_row = _normalize_feature_vector(reference[index])
        target_row = _normalize_feature_vector(target[index])
        row_scores = signal.fftconvolve(ref_row, target_row[::-1], mode='full').astype(np.float32)
        score_curve = row_scores if score_curve is None else score_curve + row_scores
    if score_curve is None or score_curve.size == 0:
        return 0.0, 0.0
    score_curve = score_curve / float(feature_count)
    best_index = int(np.argmax(score_curve))
    lag_frames = best_index - (target.shape[1] - 1)
    confidence = _peak_confidence(score_curve, best_index, exclusion_radius=max(1, int(round(3.0 / max(hop_sec, 1e-6)))))
    return lag_frames * hop_sec, confidence


def refine_offset_with_fine_sequence(
    reference_sequence: np.ndarray,
    target_sequence: np.ndarray,
    *,
    coarse_offset_sec: float,
    hop_sec: float,
    search_radius_sec: float = 3.0,
) -> Tuple[float, float]:
    if reference_sequence.size <= 1 or target_sequence.size <= 1:
        return coarse_offset_sec, 0.0
    score_curve = signal.fftconvolve(reference_sequence, target_sequence[::-1], mode='full').astype(np.float32)
    if score_curve.size == 0:
        return coarse_offset_sec, 0.0
    base_lag = -(target_sequence.shape[0] - 1)
    coarse_lag = int(round(coarse_offset_sec / max(hop_sec, 1e-6)))
    search_radius = max(1, int(round(search_radius_sec / max(hop_sec, 1e-6))))
    lower_index = max(0, coarse_lag - search_radius - base_lag)
    upper_index = min(score_curve.shape[0], coarse_lag + search_radius - base_lag + 1)
    local_scores = score_curve[lower_index:upper_index]
    if local_scores.size == 0:
        return coarse_offset_sec, 0.0
    local_best = int(np.argmax(local_scores))
    lag_frames = base_lag + lower_index + local_best
    confidence = _peak_confidence(local_scores, local_best, exclusion_radius=max(1, int(round(0.6 / max(hop_sec, 1e-6)))))
    return lag_frames * hop_sec, confidence


def correlate_envelopes(reference: np.ndarray, target: np.ndarray, *, hop_sec: float = 0.1) -> Tuple[float, float]:
    if reference.size == 0 or target.size == 0:
        return 0.0, 0.0
    if reference.size < target.size:
        reference, target = target, reference
    n = 1
    total = reference.size + target.size
    while n < total:
        n <<= 1
    target_reversed = target[::-1]
    corr = np.fft.irfft(np.fft.rfft(reference, n) * np.conj(np.fft.rfft(target_reversed, n)), n)
    valid = corr[target.size - 1:reference.size]
    if valid.size == 0:
        return 0.0, 0.0
    best_index = int(np.argmax(valid))
    offset_sec = best_index * hop_sec
    segment = reference[best_index:best_index + target.size]
    numerator = float(np.dot(segment, target)) if segment.size == target.size else 0.0
    denominator = float(np.linalg.norm(segment) * np.linalg.norm(target)) if segment.size == target.size else 0.0
    score = numerator / denominator if denominator > 1e-6 else 0.0
    return offset_sec, score


def compute_sync_map(
    project: Dict[str, Any],
    logger: LoggerFn = _default_logger,
    *,
    stop_checker: Optional[Callable[[], bool]] = None,
    transcript_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = project.get('config') or {}
    primary_role = config.get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')
    files_by_role = project.get('files') or {}
    primary_files = unique_role_files(project, primary_role, logger=logger)
    if not primary_files:
        raise RuntimeError(f'No files found for primary audio role: {primary_role}')

    logger(f'Sync: Hauptaudio ist {primary_role}.')
    timeline_cursor = 0.0
    reference_feature_chunks: List[np.ndarray] = []
    reference_fine_chunks: List[np.ndarray] = []
    feature_hop_sec = 0.02
    fine_hop_sec = 0.01
    sync_report: Dict[str, Any] = {
        'primary_role': primary_role,
        'roles': {},
        'reference_duration_sec': 0.0,
    }

    for role in files_by_role:
        role_files = unique_role_files(project, role, logger=logger)
        sync_report['roles'][role] = {'files': []}
        if role == primary_role:
            for item in role_files:
                ensure_not_stopped(stop_checker)
                duration = float(item.get('duration_sec') or 0.0)
                item['global_start_sec'] = round(timeline_cursor, 3)
                item['global_end_sec'] = round(timeline_cursor + duration, 3)
                item['sync_offset_sec'] = round(timeline_cursor, 3)
                item['sync_confidence'] = 1.0
                item['sync_method'] = 'primary'
                if item.get('audio_path') and os.path.exists(item['audio_path']):
                    feature_sequence, feature_hop_sec = build_sync_feature_sequence(item['audio_path'])
                    fine_sequence, fine_hop_sec = build_fine_sync_sequence(item['audio_path'])
                    reference_feature_chunks.append(feature_sequence)
                    reference_fine_chunks.append(fine_sequence)
                sync_report['roles'][role]['files'].append({
                    'file_id': item.get('id'),
                    'global_start_sec': item.get('global_start_sec'),
                    'global_end_sec': item.get('global_end_sec'),
                    'sync_confidence': 1.0,
                    'sync_method': 'primary',
                })
                timeline_cursor += duration
        else:
            pass

    if reference_feature_chunks:
        reference_features = np.concatenate(reference_feature_chunks, axis=1)
    else:
        reference_features = np.zeros((1, 1), dtype=np.float32)
    if reference_fine_chunks:
        reference_fine_sequence = np.concatenate(reference_fine_chunks).astype(np.float32)
    else:
        reference_fine_sequence = np.zeros(1, dtype=np.float32)
    sync_report['reference_duration_sec'] = round(float(timeline_cursor), 3)
    reference_words: List[Dict[str, Any]] = []
    if transcript_map:
        for item in primary_files:
            reference_words.extend(_collect_transcript_words(transcript_map, item, include_global_offset=True))

    for role in files_by_role:
        if role == primary_role:
            continue
        role_files = unique_role_files(project, role, logger=logger)
        fallback_cursor = 0.0
        for item in role_files:
            ensure_not_stopped(stop_checker)
            duration = float(item.get('duration_sec') or 0.0)
            selected_confidence = 0.0
            selected_offset_sec = fallback_cursor
            selected_method = 'fallback'
            audio_confidence = 0.0
            audio_offset_sec = fallback_cursor
            audio_alignment_score = 0.0
            transcript_confidence = 0.0
            transcript_match_count = 0
            transcript_offset_sec: Optional[float] = None
            transcript_source = 'none'
            transcript_alignment_score = 0.0
            target_fine_sequence = np.zeros(1, dtype=np.float32)

            if item.get('audio_path') and os.path.exists(item['audio_path']) and reference_features.shape[1] > 4:
                target_features, target_feature_hop_sec = build_sync_feature_sequence(item['audio_path'])
                audio_offset_sec, audio_confidence = correlate_feature_sequences(reference_features, target_features, hop_sec=feature_hop_sec)
                if audio_confidence >= 0.22 and reference_fine_sequence.size > 4:
                    target_fine_sequence, target_fine_hop_sec = build_fine_sync_sequence(item['audio_path'])
                    if abs(target_fine_hop_sec - fine_hop_sec) <= 1e-6:
                        refined_offset_sec, fine_confidence = refine_offset_with_fine_sequence(
                            reference_fine_sequence,
                            target_fine_sequence,
                            coarse_offset_sec=audio_offset_sec,
                            hop_sec=fine_hop_sec,
                        )
                        if fine_confidence >= 0.18:
                            audio_offset_sec = refined_offset_sec
                            audio_confidence = max(audio_confidence, min(0.98, 0.46 + fine_confidence * 0.38))
                        audio_alignment_score = score_alignment_at_offset(
                            reference_fine_sequence,
                            target_fine_sequence,
                            offset_sec=audio_offset_sec,
                            hop_sec=fine_hop_sec,
                        )
                selected_offset_sec = audio_offset_sec
                selected_confidence = audio_confidence
                selected_method = 'audio_feature'

            if reference_words:
                target_words = _collect_transcript_words(transcript_map or {}, item, include_global_offset=False)
                if audio_confidence >= 0.45:
                    transcript_offset_sec, transcript_confidence, transcript_match_count = estimate_transcript_offset_near(
                        reference_words,
                        target_words,
                        expected_offset_sec=audio_offset_sec,
                        search_radius_sec=max(120.0, min(360.0, duration * 0.18 + 90.0)),
                    )
                    transcript_source = 'local_audio_window' if transcript_offset_sec is not None else 'none'
                else:
                    transcript_offset_sec, transcript_confidence, transcript_match_count = estimate_transcript_offset(reference_words, target_words)
                    transcript_source = 'global'
                if transcript_offset_sec is not None and target_fine_sequence.size > 4:
                    transcript_alignment_score = score_alignment_at_offset(
                        reference_fine_sequence,
                        target_fine_sequence,
                        offset_sec=transcript_offset_sec,
                        hop_sec=fine_hop_sec,
                    )

            if selected_method == 'audio_feature' and selected_confidence >= 0.45:
                if transcript_offset_sec is not None and transcript_confidence >= 0.45:
                    disagreement = abs(float(transcript_offset_sec) - float(audio_offset_sec))
                    if disagreement <= 1.0:
                        selected_confidence = max(
                            selected_confidence,
                            min(0.98, 0.52 + max(selected_confidence, transcript_confidence) * 0.40),
                        )
                        logger(
                            f"Sync: {role}/{item.get('original_name')} praezise per Audio auf {audio_offset_sec:.2f}s "
                            f"(confidence {selected_confidence:.2f}); Transkript ({transcript_source}) bestaetigt {transcript_offset_sec:.2f}s."
                        )
                    elif transcript_alignment_score >= audio_alignment_score + 0.06 and transcript_confidence > selected_confidence + 0.10:
                        selected_offset_sec = float(transcript_offset_sec)
                        selected_confidence = max(transcript_confidence, min(0.96, transcript_confidence + 0.04))
                        selected_method = 'transcript'
                        logger(
                            f"Sync: {role}/{item.get('original_name')} Audio/Transkript widersprechen "
                            f"({audio_offset_sec:.2f}s vs {transcript_offset_sec:.2f}s); lokaler Validierungs-Score spricht fuer "
                            f"Transkript ({transcript_alignment_score:.2f} > {audio_alignment_score:.2f}), nehme Transkript "
                            f"({transcript_source}, confidence {transcript_confidence:.2f}, matches {transcript_match_count})."
                        )
                    else:
                        logger(
                            f"Sync: {role}/{item.get('original_name')} praezise per Audio auf {audio_offset_sec:.2f}s "
                            f"(confidence {selected_confidence:.2f}, audio-score {audio_alignment_score:.2f}); "
                            f"Transkript ({transcript_source}) weicht auf {transcript_offset_sec:.2f}s ab "
                            f"(score {transcript_alignment_score:.2f}, matches {transcript_match_count}) und wird verworfen."
                        )
                elif transcript_source == 'local_audio_window':
                    logger(
                        f"Sync: {role}/{item.get('original_name')} praezise per Audio auf {audio_offset_sec:.2f}s "
                        f"(confidence {selected_confidence:.2f}, audio-score {audio_alignment_score:.2f}); "
                        f"im lokalen Transkriptfenster kein belastbarer Gegencheck."
                    )
                else:
                    logger(
                        f"Sync: {role}/{item.get('original_name')} praezise per Audio auf {audio_offset_sec:.2f}s "
                        f"(confidence {selected_confidence:.2f}, audio-score {audio_alignment_score:.2f})."
                    )
            elif transcript_offset_sec is not None and transcript_confidence >= 0.45:
                selected_offset_sec = float(transcript_offset_sec)
                selected_confidence = transcript_confidence
                selected_method = 'transcript'
                logger(
                    f"Sync: {role}/{item.get('original_name')} via Transkript ({transcript_source}) auf {selected_offset_sec:.2f}s "
                    f"(confidence {transcript_confidence:.2f}, matches {transcript_match_count}, audio-score {transcript_alignment_score:.2f})."
                )

            if selected_confidence < 0.18:
                if reference_words:
                    logger(
                        f"Sync: {role}/{item.get('original_name')} weder per Transkript noch Audio sicher matchbar "
                        f"(transcript {transcript_confidence:.2f}, audio {audio_confidence:.2f}), nutze konservativen Fallback."
                    )
                else:
                    logger(
                        f"Sync: {role}/{item.get('original_name')} Audio nur schwach matchbar "
                        f"({audio_confidence:.2f}), nutze konservativen Fallback."
                    )
                selected_offset_sec = fallback_cursor
                selected_method = 'fallback'
            item['global_start_sec'] = round(selected_offset_sec, 3)
            item['global_end_sec'] = round(selected_offset_sec + duration, 3)
            item['sync_offset_sec'] = round(selected_offset_sec, 3)
            item['sync_confidence'] = round(selected_confidence, 4)
            item['sync_method'] = selected_method
            fallback_cursor = max(fallback_cursor, selected_offset_sec + duration)
            sync_report['roles'][role]['files'].append({
                'file_id': item.get('id'),
                'global_start_sec': item.get('global_start_sec'),
                'global_end_sec': item.get('global_end_sec'),
                'sync_confidence': item.get('sync_confidence'),
                'sync_method': selected_method,
                'audio_alignment_score': round(audio_alignment_score, 4),
                'transcript_candidate_offset_sec': round(float(transcript_offset_sec), 3) if transcript_offset_sec is not None else None,
                'transcript_candidate_confidence': round(float(transcript_confidence), 4),
                'transcript_candidate_matches': int(transcript_match_count),
                'transcript_candidate_source': transcript_source,
                'transcript_alignment_score': round(transcript_alignment_score, 4),
            })

    min_global_start = None
    max_global_end = 0.0
    for role in files_by_role:
        for item in unique_role_files(project, role):
            start_sec = float(item.get('global_start_sec') or 0.0)
            end_sec = float(item.get('global_end_sec') or 0.0)
            min_global_start = start_sec if min_global_start is None else min(min_global_start, start_sec)
            max_global_end = max(max_global_end, end_sec)
    if min_global_start is not None and min_global_start < 0.0:
        shift_sec = -min_global_start
        logger(f'Sync: Timeline wird um {shift_sec:.2f}s nach vorne verschoben, damit der frueheste Start bei 0 liegt.')
        for role in files_by_role:
            report_entries = {
                str(entry.get('file_id') or ''): entry
                for entry in (sync_report.get('roles') or {}).get(role, {}).get('files') or []
            }
            for item in unique_role_files(project, role):
                item['global_start_sec'] = round(float(item.get('global_start_sec') or 0.0) + shift_sec, 3)
                item['global_end_sec'] = round(float(item.get('global_end_sec') or 0.0) + shift_sec, 3)
                item['sync_offset_sec'] = round(float(item.get('sync_offset_sec') or 0.0) + shift_sec, 3)
                entry = report_entries.get(str(item.get('id') or ''))
                if entry is not None:
                    entry['global_start_sec'] = item['global_start_sec']
                    entry['global_end_sec'] = item['global_end_sec']
        max_global_end += shift_sec
    sync_report['reference_duration_sec'] = round(float(max_global_end), 3)
    return sync_report


def transcribe_file_audio(
    audio_path: str,
    *,
    preferred_language: str = 'de',
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    segments, info, runtime_meta = transcribe_with_runtime(
        audio_path,
        word_timestamps=True,
        language=preferred_language or None,
        progress_cb=progress_cb,
    )
    payload_segments: List[Dict[str, Any]] = []
    full_text: List[str] = []
    for segment in segments:
        words: List[Dict[str, Any]] = []
        for word in getattr(segment, 'words', []) or []:
            words.append({
                'word': str(getattr(word, 'word', '') or '').strip(),
                'start': float(getattr(word, 'start', 0.0) or 0.0),
                'end': float(getattr(word, 'end', 0.0) or 0.0),
                'probability': float(getattr(word, 'probability', 0.0) or 0.0),
            })
        text = str(getattr(segment, 'text', '') or '').strip()
        full_text.append(text)
        payload_segments.append({
            'start': float(getattr(segment, 'start', 0.0) or 0.0),
            'end': float(getattr(segment, 'end', 0.0) or 0.0),
            'text': text,
            'words': words,
        })
    transcript = {
        'language': getattr(info, 'language', '') or '',
        'language_probability': float(getattr(info, 'language_probability', 0.0) or 0.0),
        'text': ' '.join(part for part in full_text if part).strip(),
        'segments': payload_segments,
    }
    return transcript, runtime_meta


def transcribe_project_files(
    project: Dict[str, Any],
    logger: LoggerFn = _default_logger,
    *,
    stop_checker: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    config = project.get('config') or {}
    language = str(config.get('analysis_language') or 'de')
    transcript_root = os.path.join('output', 'longform_projects', project['project_id'], 'transcripts')
    os.makedirs(transcript_root, exist_ok=True)
    result: Dict[str, Any] = {'files': {}, 'runtime': {}}
    project_files: List[Tuple[str, Dict[str, Any]]] = []
    for role in (project.get('files') or {}).keys():
        for item in unique_role_files(project, role, logger=logger):
            project_files.append((role, item))
    item_count = max(1, len(project_files))
    total_weight = max(
        1.0,
        sum(max(1.0, float((item or {}).get('duration_sec') or 0.0)) for _, item in project_files),
    )
    completed_weight = 0.0

    for item_index, (role, item) in enumerate(project_files, start=1):
        ensure_not_stopped(stop_checker)
        transcript_path = os.path.join(transcript_root, f"{item['id']}.json")
        item_duration = max(1.0, float(item.get('duration_sec') or 0.0))

        def emit_progress(
            item_stage: str,
            item_stage_progress: float,
            *,
            decoded_audio_seconds: float = 0.0,
            decoded_audio_label: Optional[str] = None,
            decoded_segments: Optional[int] = None,
            runtime: Optional[Dict[str, Any]] = None,
            extra: Optional[Dict[str, Any]] = None,
        ) -> None:
            if progress_cb is None:
                return
            effective_label = decoded_audio_label
            if effective_label is None:
                minutes = int(max(0.0, decoded_audio_seconds) // 60)
                seconds = int(max(0.0, decoded_audio_seconds) % 60)
                effective_label = f'{minutes:02d}:{seconds:02d}'
            normalized_stage_progress = max(0.0, min(1.0, float(item_stage_progress or 0.0)))
            overall_ratio = min(
                0.999,
                max(0.0, (completed_weight + item_duration * normalized_stage_progress) / total_weight),
            )
            payload: Dict[str, Any] = {
                'role': role,
                'item_id': item.get('id'),
                'item_name': item.get('original_name'),
                'item_index': item_index,
                'item_count': item_count,
                'item_stage': item_stage,
                'item_stage_progress': normalized_stage_progress,
                'item_duration_sec': item_duration,
                'decoded_audio_seconds': float(decoded_audio_seconds or 0.0),
                'decoded_audio_label': effective_label,
                'decoded_segments': int(decoded_segments or 0),
                'overall_ratio': overall_ratio,
            }
            if runtime:
                payload['runtime'] = runtime
            if extra:
                payload.update(extra)
            progress_cb(payload)

        if os.path.exists(transcript_path):
            with open(transcript_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            item['transcript_path'] = transcript_path
            item['transcript_language'] = payload.get('transcript', {}).get('language') or language
            result['files'][item['id']] = payload.get('transcript') or {}
            result['runtime'][item['id']] = payload.get('runtime') or {}
            emit_progress(
                'Bereits vorhanden',
                1.0,
                decoded_audio_seconds=item_duration,
                decoded_segments=len((payload.get('transcript') or {}).get('segments') or []),
                runtime=payload.get('runtime') or {},
            )
            completed_weight += item_duration
            continue

        logger(f"Whisper: transkribiere {item.get('original_name')} ({role})...")
        emit_progress('Vorbereitung', 0.01, decoded_audio_seconds=0.0, decoded_segments=0)

        runtime_snapshot: Dict[str, Any] = {}

        def handle_runtime_progress(event: Dict[str, Any]) -> None:
            nonlocal runtime_snapshot
            status = str(event.get('status') or '').strip().lower()
            if status == 'runtime_ready':
                runtime_snapshot = {
                    'model': event.get('model'),
                    'device': event.get('device'),
                    'compute_type': event.get('compute_type'),
                    'word_timestamps': event.get('word_timestamps'),
                }
                emit_progress(
                    'Modell bereit',
                    0.02,
                    decoded_audio_seconds=0.0,
                    decoded_segments=0,
                    runtime=runtime_snapshot,
                )
                return
            if status == 'retry':
                next_model = str(event.get('next_model') or '').strip()
                retry_reason = str(event.get('retry_mode') or 'retry').strip()
                retry_suffix = f' -> {next_model}' if next_model else ''
                if event.get('word_timestamps') is False:
                    runtime_snapshot['word_timestamps'] = False
                emit_progress(
                    f'Retry ({retry_reason}{retry_suffix})',
                    max(0.02, float(runtime_snapshot and 0.03 or 0.02)),
                    decoded_audio_seconds=0.0,
                    decoded_segments=0,
                    runtime=runtime_snapshot,
                    extra={'retry_reason': event.get('reason')},
                )
                return
            if status in {'decoding', 'completed'}:
                decoded_audio_seconds = float(event.get('audio_seconds') or 0.0)
                file_ratio = 0.0
                if item_duration > 0:
                    file_ratio = decoded_audio_seconds / item_duration
                if status == 'completed':
                    file_ratio = 1.0
                emit_progress(
                    'Dekodiere' if status == 'decoding' else 'Abgeschlossen',
                    max(0.02, min(1.0, file_ratio)),
                    decoded_audio_seconds=decoded_audio_seconds,
                    decoded_audio_label=str(event.get('audio_label') or ''),
                    decoded_segments=int(event.get('segments') or 0),
                    runtime=runtime_snapshot,
                )

        transcript, runtime_meta = transcribe_file_audio(
            item['audio_path'],
            preferred_language=language,
            progress_cb=handle_runtime_progress,
        )
        payload = {'transcript': transcript, 'runtime': runtime_meta}
        with open(transcript_path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        item['transcript_path'] = transcript_path
        item['transcript_language'] = transcript.get('language') or language
        result['files'][item['id']] = transcript
        result['runtime'][item['id']] = runtime_meta
        emit_progress(
            'Abgeschlossen',
            1.0,
            decoded_audio_seconds=item_duration,
            decoded_segments=len(transcript.get('segments') or []),
            runtime=runtime_meta,
        )
        completed_weight += item_duration
    return result


def build_combined_transcript(project: Dict[str, Any], transcript_map: Dict[str, Any]) -> Dict[str, Any]:
    combined: Dict[str, Any] = {'roles': {}, 'all_words': [], 'all_segments': []}
    for role in (project.get('files') or {}).keys():
        role_words: List[Dict[str, Any]] = []
        role_segments: List[Dict[str, Any]] = []
        for item in sorted(unique_role_files(project, role), key=lambda raw: float(raw.get('global_start_sec') or 0.0)):
            transcript = (transcript_map.get('files') or {}).get(item.get('id')) or {}
            global_offset = float(item.get('global_start_sec') or 0.0)
            for segment in transcript.get('segments') or []:
                seg_payload = {
                    'role': role,
                    'file_id': item.get('id'),
                    'start': round(global_offset + float(segment.get('start') or 0.0), 3),
                    'end': round(global_offset + float(segment.get('end') or 0.0), 3),
                    'text': str(segment.get('text') or '').strip(),
                    'local_start': float(segment.get('start') or 0.0),
                    'local_end': float(segment.get('end') or 0.0),
                }
                role_segments.append(seg_payload)
                combined['all_segments'].append(seg_payload)
                for word in segment.get('words') or []:
                    token = str(word.get('word') or '').strip()
                    if not token:
                        continue
                    word_payload = {
                        'role': role,
                        'file_id': item.get('id'),
                        'word': token,
                        'start': round(global_offset + float(word.get('start') or 0.0), 3),
                        'end': round(global_offset + float(word.get('end') or 0.0), 3),
                        'local_start': float(word.get('start') or 0.0),
                        'local_end': float(word.get('end') or 0.0),
                    }
                    role_words.append(word_payload)
                    combined['all_words'].append(word_payload)
        role_words.sort(key=lambda item: item['start'])
        role_segments.sort(key=lambda item: item['start'])
        combined['roles'][role] = {'words': role_words, 'segments': role_segments}
    combined['all_words'].sort(key=lambda item: item['start'])
    combined['all_segments'].sort(key=lambda item: item['start'])
    combined['text'] = ' '.join(item['word'] for item in combined['all_words']).strip()
    return combined


def _segment_speech_density(segment: Dict[str, Any]) -> float:
    duration = max(0.05, float(segment.get('end') or 0.0) - float(segment.get('start') or 0.0))
    return _segment_word_count(segment) / duration


def _is_editorial_setup_segment(segment: Dict[str, Any]) -> bool:
    text = str(segment.get('text') or '').strip()
    if not text:
        return True
    if _contains_any_phrase(text, SETUP_CUE_PHRASES) or _contains_any_phrase(text, CONTINUATION_CUE_PHRASES):
        return True
    if _segment_word_count(segment) <= 2 and _segment_speech_density(segment) < 2.4:
        return True
    return False


def _is_contentful_segment(segment: Dict[str, Any]) -> bool:
    text = str(segment.get('text') or '').strip()
    words = _segment_word_count(segment)
    duration = max(0.05, float(segment.get('end') or 0.0) - float(segment.get('start') or 0.0))
    if not text:
        return False
    if _contains_any_phrase(text, SETUP_CUE_PHRASES):
        return False
    if words >= 8:
        return True
    if words >= 5 and duration >= 1.1:
        return True
    if _contains_any_phrase(text, INTRO_CUE_PHRASES) or _contains_any_phrase(text, OUTRO_CUE_PHRASES):
        return True
    return False


def _official_intro_score(segment: Dict[str, Any]) -> float:
    text = str(segment.get('text') or '').strip()
    if not text or _is_editorial_setup_segment(segment):
        return 0.0
    words = _segment_word_count(segment)
    duration = max(0.05, float(segment.get('local_end') or segment.get('end') or 0.0) - float(segment.get('local_start') or segment.get('start') or 0.0))
    score = 0.0
    if _contains_any_phrase(text, INTRO_CUE_PHRASES):
        score += 4.0
    if _contains_any_phrase(text, OFFICIAL_INTRO_IDENTITY_PHRASES):
        score += 3.0
    if 'podcast' in _normalize_phrase_text(text) or 'kanal' in _normalize_phrase_text(text):
        score += 1.6
    if words >= 8:
        score += 1.0
    if duration >= 2.0:
        score += 0.8
    if _is_contentful_segment(segment):
        score += 0.8
    return score


def _find_official_intro_start(segments: List[Dict[str, Any]]) -> Optional[Tuple[float, str]]:
    if not segments:
        return None
    search_window = [segment for segment in segments if float(segment.get('local_start') or 0.0) <= 600.0]
    for index, segment in enumerate(search_window):
        score = _official_intro_score(segment)
        if score < 4.2:
            continue
        following = search_window[index + 1:index + 4]
        sustained_words = _segment_word_count(segment) + sum(_segment_word_count(item) for item in following[:2])
        sustained_hits = sum(1 for item in [segment, *following[:2]] if _is_contentful_segment(item))
        if sustained_hits >= 2 or sustained_words >= 18:
            start_sec = max(0.0, float(segment.get('local_start') or 0.0) - 0.25)
            return start_sec, 'official_intro'
    return None


def _estimate_file_lead_trim(
    item: Dict[str, Any],
    segments: List[Dict[str, Any]],
    *,
    file_index: int,
    total_files: int,
) -> Tuple[float, str]:
    duration_sec = max(0.0, float(item.get('duration_sec') or 0.0))
    if not segments:
        return 0.0, 'no_transcript'

    if file_index == 0:
        intro_candidate = _find_official_intro_start(segments)
        if intro_candidate is not None:
            start_sec, reason = intro_candidate
            return min(start_sec, max(0.0, duration_sec - 5.0)), reason

    intro_candidates = [
        segment for segment in segments[:18]
        if _contains_any_phrase(segment.get('text') or '', INTRO_CUE_PHRASES)
    ]
    if intro_candidates:
        start_sec = max(0.0, float(intro_candidates[0].get('local_start') or 0.0) - 0.2)
        return min(start_sec, max(0.0, duration_sec - 5.0)), 'intro_cue'

    trim_to = 0.0
    reason = 'first_content'
    for segment in segments[:18]:
        local_start = max(0.0, float(segment.get('local_start') or 0.0))
        local_end = max(local_start, float(segment.get('local_end') or local_start))
        if local_start > 180.0:
            break
        if _is_editorial_setup_segment(segment):
            trim_to = max(trim_to, local_end)
            reason = 'setup_trim'
            continue
        if file_index > 0 and _contains_any_phrase(segment.get('text') or '', CONTINUATION_CUE_PHRASES):
            trim_to = max(trim_to, local_end)
            reason = 'continuation_trim'
            continue
        if _is_contentful_segment(segment):
            trim_to = max(0.0, local_start - 0.12)
            break
    if trim_to <= 0.0 and segments:
        trim_to = max(0.0, float(segments[0].get('local_start') or 0.0) - 0.06)
    trim_to = min(trim_to, max(0.0, duration_sec - 5.0))
    return trim_to, reason


def _estimate_file_tail_trim(
    item: Dict[str, Any],
    segments: List[Dict[str, Any]],
    *,
    file_index: int,
    total_files: int,
) -> Tuple[float, str]:
    duration_sec = max(0.0, float(item.get('duration_sec') or 0.0))
    if not segments:
        return duration_sec, 'no_transcript'

    last_segment_end = max(float(segments[-1].get('local_end') or 0.0), 0.0)
    trim_end = min(duration_sec, last_segment_end + 0.1)
    reason = 'last_content'
    trailing = list(reversed(segments[-18:]))

    if file_index == total_files - 1:
        for segment in trailing:
            if _contains_any_phrase(segment.get('text') or '', OUTRO_CUE_PHRASES):
                trim_end = min(duration_sec, float(segment.get('local_end') or 0.0) + 0.15)
                reason = 'outro_cue'
                break

    last_meaningful_end = None
    for segment in trailing:
        if _is_editorial_setup_segment(segment):
            trim_end = min(trim_end, max(0.0, float(segment.get('local_start') or 0.0) - 0.06))
            reason = 'postroll_trim'
            continue
        if _contains_any_phrase(segment.get('text') or '', OUTRO_CUE_PHRASES):
            trim_end = min(duration_sec, float(segment.get('local_end') or 0.0) + 0.15)
            reason = 'outro_cue'
            break
        if _is_contentful_segment(segment):
            last_meaningful_end = float(segment.get('local_end') or 0.0)
            break

    if file_index < total_files - 1 and last_meaningful_end is not None:
        trim_end = max(trim_end, last_meaningful_end)

    trim_end = max(trim_end, min(duration_sec, max(0.0, float(segments[0].get('local_end') or 0.0) + 6.0)))
    trim_end = min(trim_end, duration_sec)
    return trim_end, reason


def detect_editorial_content_ranges(
    project: Dict[str, Any],
    combined: Dict[str, Any],
    primary_role: str,
    *,
    logger: LoggerFn = _default_logger,
) -> List[Dict[str, Any]]:
    primary_files = sorted(unique_role_files(project, primary_role, logger=logger), key=lambda raw: float(raw.get('global_start_sec') or 0.0))
    segments_by_file: Dict[str, List[Dict[str, Any]]] = {}
    for segment in ((combined.get('roles') or {}).get(primary_role, {}).get('segments') or []):
        segments_by_file.setdefault(str(segment.get('file_id') or ''), []).append(segment)

    ranges: List[Dict[str, Any]] = []
    for index, item in enumerate(primary_files):
        item_segments = sorted(segments_by_file.get(str(item.get('id') or ''), []), key=lambda raw: float(raw.get('local_start') or 0.0))
        lead_trim, lead_reason = _estimate_file_lead_trim(item, item_segments, file_index=index, total_files=len(primary_files))
        tail_trim, tail_reason = _estimate_file_tail_trim(item, item_segments, file_index=index, total_files=len(primary_files))
        duration_sec = max(0.0, float(item.get('duration_sec') or 0.0))
        if tail_trim - lead_trim < 12.0:
            lead_trim = max(0.0, float(item_segments[0].get('local_start') or 0.0) - 0.06) if item_segments else 0.0
            tail_trim = min(duration_sec, float(item_segments[-1].get('local_end') or duration_sec) + 0.06) if item_segments else duration_sec
            lead_reason = 'fallback_first_speech'
            tail_reason = 'fallback_last_speech'
        global_start = round(float(item.get('global_start_sec') or 0.0) + lead_trim, 3)
        global_end = round(float(item.get('global_start_sec') or 0.0) + tail_trim, 3)
        ranges.append({
            'file_id': item.get('id'),
            'file_name': item.get('original_name'),
            'global_start': global_start,
            'global_end': global_end,
            'local_start': round(lead_trim, 3),
            'local_end': round(tail_trim, 3),
            'lead_trim_sec': round(max(0.0, lead_trim), 3),
            'tail_trim_sec': round(max(0.0, duration_sec - tail_trim), 3),
            'lead_reason': lead_reason,
            'tail_reason': tail_reason,
        })
        if lead_trim > 0.25 or duration_sec - tail_trim > 0.25:
            logger(
                f"Editorial-Trim: {item.get('original_name')} Start +{lead_trim:.2f}s ({lead_reason}), "
                f"Ende -{max(0.0, duration_sec - tail_trim):.2f}s ({tail_reason})."
            )
    return ranges


def apply_llm_setup_refinement(
    project: Dict[str, Any],
    editorial_ranges: List[Dict[str, Any]],
    llm_setup_ranges: List[Dict[str, Any]],
    primary_role: str,
    *,
    logger: LoggerFn = _default_logger,
) -> List[Dict[str, Any]]:
    if not editorial_ranges or not llm_setup_ranges:
        return editorial_ranges
    primary_files = sorted(unique_role_files(project, primary_role, logger=logger), key=lambda raw: float(raw.get('global_start_sec') or 0.0))
    if not primary_files:
        return editorial_ranges
    first_file = primary_files[0]
    first_file_start = float(first_file.get('global_start_sec') or 0.0)
    first_file_end = float(first_file.get('global_end_sec') or first_file_start)
    llm_setup_end = max(
        (
            float(item.get('end') or 0.0)
            for item in llm_setup_ranges
            if first_file_start <= float(item.get('start') or 0.0) <= first_file_end
        ),
        default=0.0,
    )
    if llm_setup_end <= 0.0:
        return editorial_ranges
    refined = [dict(item) for item in editorial_ranges]
    current_start = float(refined[0].get('global_start') or 0.0)
    if llm_setup_end <= current_start + 0.35:
        return refined
    refined[0]['global_start'] = round(min(llm_setup_end, float(refined[0].get('global_end') or llm_setup_end)), 3)
    refined[0]['local_start'] = round(max(0.0, refined[0]['global_start'] - first_file_start), 3)
    refined[0]['lead_trim_sec'] = round(max(0.0, refined[0]['local_start']), 3)
    refined[0]['lead_reason'] = 'llm_setup_refine'
    logger(f'LLM-Setup-Refine: erster Inhaltsstart auf {refined[0]["local_start"]:.2f}s verschoben.')
    return refined


def _voice_frame_score(chunk: np.ndarray, sample_rate: int) -> float:
    if chunk.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64)))
    if rms <= 1e-6:
        return 0.0
    window = np.hanning(chunk.size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(chunk * window)).astype(np.float32)
    freqs = np.fft.rfftfreq(chunk.size, d=1.0 / max(sample_rate, 1))
    total = float(np.sum(spectrum)) or 1e-6
    low = float(np.sum(spectrum[(freqs >= 80.0) & (freqs < 220.0)]))
    speech = float(np.sum(spectrum[(freqs >= 220.0) & (freqs < 2200.0)]))
    brilliance = float(np.sum(spectrum[(freqs >= 2200.0) & (freqs < 3600.0)]))
    centroid = float(np.sum(freqs * spectrum) / total)
    speech_ratio = speech / total
    brilliance_ratio = brilliance / total
    low_penalty = min(0.7, low / total)
    return (
        math.log1p(rms * 36.0)
        + speech_ratio * 1.9
        + brilliance_ratio * 1.1
        + min(0.45, centroid / 4000.0)
        - low_penalty * 0.55
    )


def _audio_activity_profile(path: str) -> Dict[str, Any]:
    cache_key = os.path.realpath(path) if path else path
    cached = _AUDIO_ACTIVITY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    samples, sample_rate = read_audio_mono(path, sample_rate=16000)
    filtered = _bandpass_voice_audio(samples, sample_rate, low_hz=80.0, high_hz=3600.0)
    hop_sec = 0.04
    frame_sec = 0.10
    hop_size = max(1, int(sample_rate * hop_sec))
    frame_size = max(hop_size * 2, int(sample_rate * frame_sec))
    scores: List[float] = []
    for start in range(0, max(1, filtered.size - frame_size + 1), hop_size):
        chunk = filtered[start:start + frame_size]
        if chunk.size < frame_size:
            chunk = np.pad(chunk, (0, frame_size - chunk.size))
        scores.append(_voice_frame_score(chunk, sample_rate))
    sequence = np.asarray(scores or [0.0], dtype=np.float32)
    low = float(np.percentile(sequence, 10)) if sequence.size else 0.0
    high = float(np.percentile(sequence, 92)) if sequence.size else 1.0
    normalized = (sequence - low) / max(0.05, high - low)
    profile = {
        'hop_sec': hop_sec,
        'scores': np.clip(normalized, 0.0, 1.8).astype(np.float32),
        'duration_sec': filtered.size / float(sample_rate) if sample_rate else 0.0,
    }
    _AUDIO_ACTIVITY_CACHE[cache_key] = profile
    return profile


def _score_role_audio_activity(project: Dict[str, Any], role: str, start: float, end: float, *, logger: Optional[LoggerFn] = None) -> float:
    weighted_sum = 0.0
    total_weight = 0.0
    for item in unique_role_files(project, role, logger=logger):
        file_start = float(item.get('global_start_sec') or 0.0)
        file_end = float(item.get('global_end_sec') or file_start)
        overlap_start = max(start, file_start)
        overlap_end = min(end, file_end)
        if overlap_end <= overlap_start:
            continue
        audio_path = item.get('audio_path')
        if not audio_path or not os.path.exists(audio_path):
            continue
        profile = _audio_activity_profile(audio_path)
        hop_sec = float(profile.get('hop_sec') or 0.04)
        raw_scores = profile.get('scores')
        if raw_scores is None:
            scores = np.asarray([0.0], dtype=np.float32)
        else:
            scores = np.asarray(raw_scores, dtype=np.float32)
            if scores.size == 0:
                scores = np.asarray([0.0], dtype=np.float32)
        local_start = max(0.0, overlap_start - file_start)
        local_end = max(local_start, overlap_end - file_start)
        start_index = max(0, int(math.floor(local_start / max(hop_sec, 1e-6))))
        end_index = min(scores.shape[0], max(start_index + 1, int(math.ceil(local_end / max(hop_sec, 1e-6)))))
        window = scores[start_index:end_index]
        if window.size == 0:
            continue
        overlap_duration = overlap_end - overlap_start
        weighted_sum += float(window.mean()) * overlap_duration
        total_weight += overlap_duration
    if total_weight <= 1e-6:
        return 0.0
    return weighted_sum / total_weight


def _transcript_evidence_profile(item: Dict[str, Any]) -> Dict[str, Any]:
    transcript_path = str(item.get('transcript_path') or '').strip()
    if not transcript_path or not os.path.exists(transcript_path):
        return {
            'hop_sec': 0.08,
            'scores': np.asarray([0.0], dtype=np.float32),
            'duration_sec': float(item.get('duration_sec') or 0.0),
        }
    cache_key = os.path.realpath(transcript_path)
    cached = _TRANSCRIPT_EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    hop_sec = 0.08
    duration_sec = max(0.0, float(item.get('duration_sec') or 0.0))
    try:
        with open(transcript_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception:
        payload = {}
    transcript = payload.get('transcript') if isinstance(payload, dict) else None
    if not isinstance(transcript, dict):
        transcript = payload if isinstance(payload, dict) else {}
    segments = transcript.get('segments') or []
    if segments:
        transcript_end = max(float(segment.get('end') or segment.get('start') or 0.0) for segment in segments)
        duration_sec = max(duration_sec, transcript_end)

    frame_count = max(1, int(math.ceil(duration_sec / hop_sec)) + 2)
    scores = np.zeros(frame_count, dtype=np.float32)

    def apply_window(local_start: float, local_end: float, weight: float) -> None:
        if local_end <= local_start:
            return
        start_index = max(0, int(math.floor(local_start / hop_sec)))
        end_index = min(scores.shape[0], max(start_index + 1, int(math.ceil(local_end / hop_sec))))
        scores[start_index:end_index] += float(weight)

    for segment in segments:
        segment_start = max(0.0, float(segment.get('start') or 0.0))
        segment_end = max(segment_start, float(segment.get('end') or segment.get('start') or 0.0))
        words = segment.get('words') or []
        if words:
            for word in words:
                token_raw = str(word.get('word') or '').strip()
                token = _normalize_token(token_raw)
                if not token:
                    continue
                word_start = max(segment_start, float(word.get('start') or segment_start))
                word_end = max(word_start, float(word.get('end') or word_start or segment_end))
                probability = float(word.get('probability') or 0.0)
                token_bonus = min(0.36, max(0.0, len(token) - 2) * 0.045)
                weight = max(0.18, min(1.6, (0.55 + max(0.0, probability)) + token_bonus))
                apply_window(word_start, word_end, weight)
            continue
        tokens = [_normalize_token(token) for token in str(segment.get('text') or '').split()]
        tokens = [token for token in tokens if token]
        if not tokens:
            continue
        step = max(0.05, (segment_end - segment_start) / max(1, len(tokens)))
        for index, token in enumerate(tokens):
            token_start = segment_start + index * step
            token_end = min(segment_end, token_start + step)
            token_bonus = min(0.24, max(0.0, len(token) - 2) * 0.035)
            apply_window(token_start, token_end, 0.42 + token_bonus)

    if scores.size > 2:
        kernel = np.asarray([0.2, 0.6, 0.2], dtype=np.float32)
        scores = np.convolve(scores, kernel, mode='same').astype(np.float32, copy=False)

    positive = scores[scores > 1e-5]
    normalizer = float(np.percentile(positive, 85)) if positive.size else 1.0
    normalized = scores / max(normalizer, 1e-4)
    profile = {
        'hop_sec': hop_sec,
        'scores': np.clip(normalized, 0.0, 2.2).astype(np.float32),
        'duration_sec': duration_sec,
    }
    _TRANSCRIPT_EVIDENCE_CACHE[cache_key] = profile
    return profile


def _score_role_transcript_evidence(project: Dict[str, Any], role: str, start: float, end: float, *, logger: Optional[LoggerFn] = None) -> float:
    weighted_sum = 0.0
    total_weight = 0.0
    for item in unique_role_files(project, role, logger=logger):
        file_start = float(item.get('global_start_sec') or 0.0)
        file_end = float(item.get('global_end_sec') or file_start)
        overlap_start = max(start, file_start)
        overlap_end = min(end, file_end)
        if overlap_end <= overlap_start:
            continue
        profile = _transcript_evidence_profile(item)
        hop_sec = float(profile.get('hop_sec') or 0.08)
        raw_scores = profile.get('scores')
        if raw_scores is None:
            scores = np.asarray([0.0], dtype=np.float32)
        else:
            scores = np.asarray(raw_scores, dtype=np.float32)
            if scores.size == 0:
                scores = np.asarray([0.0], dtype=np.float32)
        local_start = max(0.0, overlap_start - file_start)
        local_end = max(local_start, overlap_end - file_start)
        start_index = max(0, int(math.floor(local_start / max(hop_sec, 1e-6))))
        end_index = min(scores.shape[0], max(start_index + 1, int(math.ceil(local_end / max(hop_sec, 1e-6)))))
        window = scores[start_index:end_index]
        if window.size == 0:
            continue
        overlap_duration = overlap_end - overlap_start
        weighted_sum += float(window.mean()) * overlap_duration
        total_weight += overlap_duration
    if total_weight <= 1e-6:
        return 0.0
    return weighted_sum / total_weight


def _score_role_window(project: Dict[str, Any], role: str, start: float, end: float, *, logger: Optional[LoggerFn] = None) -> Dict[str, float]:
    audio_score = _score_role_audio_activity(project, role, start, end, logger=logger)
    transcript_score = _score_role_transcript_evidence(project, role, start, end, logger=logger)
    if transcript_score > 0.0:
        combined = audio_score * 0.56 + transcript_score * 0.44
        combined += min(audio_score, transcript_score) * 0.08
    else:
        combined = audio_score
    return {
        'audio': round(float(audio_score), 5),
        'transcript': round(float(transcript_score), 5),
        'combined': round(float(combined), 5),
    }


def _load_pyannote_pipeline(*, token_override: Optional[str] = None, logger: Optional[LoggerFn] = None):
    if PyannotePipeline is None:
        raise RuntimeError('pyannote.audio ist nicht installiert.')
    token = (
        str(token_override or '').strip()
        or os.environ.get('PYANNOTE_AUTH_TOKEN')
        or os.environ.get('HUGGINGFACE_HUB_TOKEN')
        or os.environ.get('HF_TOKEN')
        or ''
    ).strip()
    global _PYANNOTE_PIPELINE, _PYANNOTE_PIPELINE_TOKEN
    if _PYANNOTE_PIPELINE is not None and _PYANNOTE_PIPELINE_TOKEN == token:
        return _PYANNOTE_PIPELINE
    if logger:
        logger('Pyannote: Speaker-Diarization-Modell wird geladen.')
    load_attempts: List[Dict[str, Any]] = []
    if token:
        load_attempts.append({
            'target': 'pyannote/speaker-diarization-3.1',
            'kwargs': {'use_auth_token': token},
            'label': 'authenticated',
        })
    local_model_dir = _find_local_pyannote_model_dir()
    if local_model_dir:
        load_attempts.append({
            'target': local_model_dir,
            'kwargs': {},
            'label': 'local-cache',
        })
    last_error: Optional[Exception] = None
    for attempt in load_attempts:
        try:
            _PYANNOTE_PIPELINE = PyannotePipeline.from_pretrained(
                attempt['target'],
                **attempt['kwargs'],
            )
            _PYANNOTE_PIPELINE_TOKEN = token
            if logger and attempt['label'].startswith('local-cache'):
                logger('Pyannote: Lokales Modell aus dem Cache geladen.')
            return _PYANNOTE_PIPELINE
        except Exception as exc:
            last_error = exc
    if not token:
        if local_model_dir and last_error is not None:
            raise RuntimeError(f'Kein HF/PYANNOTE Token gesetzt und lokales pyannote-Modell konnte nicht geladen werden. ({last_error})')
        raise RuntimeError('Kein HF/PYANNOTE Token fuer pyannote gesetzt und kein lokales Modell im Cache gefunden.')
    raise RuntimeError(f'Pyannote konnte nicht geladen werden. ({last_error})')


def _run_pyannote_diarization(project: Dict[str, Any], primary_role: str, *, logger: Optional[LoggerFn] = None) -> List[Dict[str, Any]]:
    ai_config = project.get('ai') or {}
    configured_token = str(ai_config.get('huggingface_token') or '').strip()
    cache_key = f"{project.get('project_id')}::{primary_role}::{configured_token[:16]}"
    cached = _PYANNOTE_DIARIZATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pipeline = _load_pyannote_pipeline(token_override=configured_token, logger=logger)
    diarized: List[Dict[str, Any]] = []
    for item in unique_role_files(project, primary_role, logger=logger):
        audio_path = str(item.get('audio_path') or '').strip()
        if not audio_path or not os.path.exists(audio_path):
            continue
        file_offset = float(item.get('global_start_sec') or 0.0)
        diarization = pipeline(audio_path)
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            start = file_offset + float(turn.start or 0.0)
            end = file_offset + float(turn.end or 0.0)
            if end - start <= 0.12:
                continue
            diarized.append({
                'speaker': str(speaker),
                'start': round(start, 3),
                'end': round(end, 3),
                'confidence': 0.74,
                'reason': 'pyannote_diarization',
            })
    diarized = sorted(diarized, key=lambda raw: (float(raw['start']), float(raw['end'])))
    merged: List[Dict[str, Any]] = []
    for item in diarized:
        if not merged:
            merged.append(dict(item))
            continue
        previous = merged[-1]
        if item['speaker'] == previous['speaker'] and float(item['start']) <= float(previous['end']) + 0.10:
            previous['end'] = round(max(float(previous['end']), float(item['end'])), 3)
            previous['confidence'] = round((float(previous['confidence']) + float(item['confidence'])) / 2.0, 3)
            continue
        merged.append(dict(item))
    _PYANNOTE_DIARIZATION_CACHE[cache_key] = merged
    return merged


def _finalize_speaker_turns(provisional: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not provisional:
        return []
    merged: List[Dict[str, Any]] = [dict(provisional[0])]
    for item in provisional[1:]:
        previous = merged[-1]
        if item['role'] == previous['role'] and item['start'] <= previous['end'] + 0.02:
            previous['end'] = item['end']
            previous['confidence'] = round((previous['confidence'] + item['confidence']) / 2.0, 3)
            continue
        merged.append(dict(item))

    hold_sec = float(config.get('speaker_switch_hold_ms') or 900) / 1000.0
    min_shot_length_sec = float(config.get('min_shot_length_sec') or 3.0)
    collapsed: List[Dict[str, Any]] = []
    for item in merged:
        if not collapsed:
            collapsed.append(dict(item))
            continue
        previous = collapsed[-1]
        duration = float(item['end'] - item['start'])
        previous_duration = float(previous['end'] - previous['start'])
        if duration < hold_sec or previous_duration < min_shot_length_sec or item['confidence'] < 0.36:
            previous['end'] = item['end']
            previous['confidence'] = round((previous['confidence'] + item['confidence']) / 2.0, 3)
            previous['reason'] = 'hysteresis_hold'
            continue
        collapsed.append(dict(item))
    return collapsed


def _build_pyannote_turns(
    project: Dict[str, Any],
    primary_role: str,
    working_ranges: List[Tuple[float, float]],
    *,
    logger: Optional[LoggerFn] = None,
) -> List[Dict[str, Any]]:
    diarized = _run_pyannote_diarization(project, primary_role, logger=logger)
    if len(diarized) < 2:
        return []

    roles = ['host', 'guest']
    provisional: List[Dict[str, Any]] = []
    current_role = primary_role if primary_role in roles else roles[0]
    for item in diarized:
        seg_start = float(item['start'])
        seg_end = float(item['end'])
        for keep_start, keep_end in working_ranges:
            overlap_start = max(seg_start, keep_start)
            overlap_end = min(seg_end, keep_end)
            if overlap_end - overlap_start <= 0.12:
                continue
            role_scores = {
                role: _score_role_window(project, role, overlap_start, overlap_end, logger=logger)
                for role in roles
            }
            ranked = sorted(
                role_scores.items(),
                key=lambda entry: (
                    float(entry[1].get('combined') or 0.0),
                    float(entry[1].get('transcript') or 0.0),
                    float(entry[1].get('audio') or 0.0),
                ),
                reverse=True,
            )
            if len(ranked) < 2:
                chosen = ranked[0][0] if ranked else current_role
                confidence = 0.55
            else:
                best_role, best_metrics = ranked[0]
                alt_role, alt_metrics = ranked[1]
                best_score = float(best_metrics.get('combined') or 0.0)
                alt_score = float(alt_metrics.get('combined') or 0.0)
                transcript_delta = float(best_metrics.get('transcript') or 0.0) - float(alt_metrics.get('transcript') or 0.0)
                audio_delta = float(best_metrics.get('audio') or 0.0) - float(alt_metrics.get('audio') or 0.0)
                chosen = best_role
                if best_score <= 0.08 and alt_score <= 0.08:
                    chosen = current_role
                elif transcript_delta <= 0.02 and audio_delta <= 0.04 and current_role != best_role and best_score < alt_score + 0.07:
                    chosen = current_role
                confidence = max(
                    0.36,
                    min(
                        0.98,
                        0.48
                        + max(0.0, best_score - alt_score) * 0.72
                        + max(0.0, transcript_delta) * 0.24
                        + max(0.0, audio_delta) * 0.12,
                    ),
                )
            current_role = chosen
            provisional.append({
                'role': chosen,
                'start': round(overlap_start, 3),
                'end': round(overlap_end, 3),
                'confidence': round(confidence, 3),
                'reason': 'pyannote_turn',
            })
    return provisional


def _normalize_token(token: str) -> str:
    return ''.join(ch for ch in token.lower().strip() if ch.isalnum() or ch in {'ä', 'ö', 'ü', 'ß', '-'})


def is_backchannel_segment(text: str, duration_sec: float, word_count: int, config: Dict[str, Any]) -> bool:
    if duration_sec * 1000 > float(config.get('backchannel_max_duration_ms') or 700):
        return False
    if word_count > int(config.get('backchannel_max_words') or 3):
        return False
    tokens = [_normalize_token(token) for token in text.split() if _normalize_token(token)]
    if not tokens:
        return False
    if all(token in BACKCHANNEL_TOKENS for token in tokens):
        return True
    return word_count <= 2 and duration_sec <= 0.55


def _segment_word_count(segment: Dict[str, Any]) -> int:
    return len([token for token in str(segment.get('text') or '').split() if _normalize_token(token)])


def detect_backchannels(combined: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    markers: List[Dict[str, Any]] = []
    for role, role_data in (combined.get('roles') or {}).items():
        for segment in role_data.get('segments') or []:
            duration = float(segment['end'] - segment['start'])
            word_count = _segment_word_count(segment)
            if is_backchannel_segment(segment.get('text') or '', duration, word_count, config):
                markers.append({
                    'role': role,
                    'start': segment['start'],
                    'end': segment['end'],
                    'text': segment.get('text') or '',
                    'type': 'backchannel',
                })
    return markers


def detect_pause_cuts(primary_words: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    threshold_sec = float(config.get('long_pause_threshold_ms') or 650) / 1000.0
    target_sec = float(config.get('pause_trim_target_ms') or 260) / 1000.0
    cuts: List[Dict[str, Any]] = []
    for previous, current in zip(primary_words, primary_words[1:]):
        gap = float(current['start']) - float(previous['end'])
        if gap <= threshold_sec:
            continue
        cuts.append({
            'start': round(previous['end'] + target_sec, 3),
            'end': round(current['start'], 3),
            'reason': 'long_pause',
            'confidence': min(0.98, 0.5 + min(1.0, gap / max(threshold_sec, 0.001)) * 0.4),
        })
    return [cut for cut in cuts if cut['end'] - cut['start'] > 0.04]


def detect_filler_cuts(primary_words: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    level = int(config.get('filler_word_cut_level') or 0)
    if level <= 0:
        return []
    padding = 0.03 if level == 1 else 0.07
    cuts: List[Dict[str, Any]] = []
    for word in primary_words:
        token = _normalize_token(word.get('word') or '')
        if token not in FILLER_TOKENS:
            continue
        cuts.append({
            'start': round(max(0.0, float(word['start']) - padding), 3),
            'end': round(float(word['end']) + padding, 3),
            'reason': 'filler',
            'confidence': 0.72 if level == 1 else 0.84,
        })
    return cuts


def detect_retake_candidates(primary_segments: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for previous, current in zip(primary_segments, primary_segments[1:]):
        previous_text = str(previous.get('text') or '').strip().lower()
        current_text = str(current.get('text') or '').strip().lower()
        if not previous_text or not current_text:
            continue
        if current_text.startswith(RETAKE_PREFIXES) or _contains_any_phrase(current_text, RETAKE_PREFIXES):
            candidates.append({
                'start': current['start'],
                'end': current['end'],
                'reason': 'restart_prefix',
                'confidence': 0.76,
                'keep': 'review',
                'text': current.get('text') or '',
                'role': current.get('role') or '',
                'previous_role': previous.get('role') or '',
                'previous_text': previous.get('text') or '',
                'current_text': current.get('text') or '',
            })
            continue
        if _contains_any_phrase(current_text, RETAKE_CUE_PHRASES):
            candidates.append({
                'start': current['start'],
                'end': current['end'],
                'reason': 'strong_retake_cue',
                'confidence': 0.88,
                'keep': 'review',
                'text': current.get('text') or '',
                'role': current.get('role') or '',
                'previous_role': previous.get('role') or '',
                'previous_text': previous.get('text') or '',
                'current_text': current.get('text') or '',
            })
            continue
        if any(token in current_text for token in ('noch mal', 'nochmal', 'sorry', 'warte', 'formuliere', 'anders gesagt', 'anders formuliert')):
            candidates.append({
                'start': current['start'],
                'end': current['end'],
                'reason': 'spoken_retake_cue',
                'confidence': 0.8,
                'keep': 'review',
                'text': current.get('text') or '',
                'role': current.get('role') or '',
                'previous_role': previous.get('role') or '',
                'previous_text': previous.get('text') or '',
                'current_text': current.get('text') or '',
            })
            continue
        similarity = difflib.SequenceMatcher(None, previous_text[:120], current_text[:120]).ratio()
        overlap_prefix = difflib.SequenceMatcher(None, previous_text[-120:], current_text[:120]).ratio()
        if similarity >= 0.82 or overlap_prefix >= 0.78:
            candidates.append({
                'start': previous['start'],
                'end': current['end'],
                'reason': 'repeated_phrase',
                'confidence': min(0.94, max(similarity, overlap_prefix)),
                'keep': 'review',
                'text': f"{previous.get('text') or ''} / {current.get('text') or ''}",
                'role': current.get('role') or '',
                'previous_role': previous.get('role') or '',
                'previous_text': previous.get('text') or '',
                'current_text': current.get('text') or '',
            })
    return candidates


def _rebuild_shot(project: Dict[str, Any], role: str, start: float, end: float, *, confidence: float, reason: str) -> Optional[Dict[str, Any]]:
    if end - start <= 0.12:
        return None
    segments = interval_segments_for_role(project, role, start, end)
    if not segments:
        return None
    return {
        'role': role,
        'start': round(start, 3),
        'end': round(end, 3),
        'duration': round(end - start, 3),
        'confidence': round(confidence, 3),
        'reason': reason,
        'segments': segments,
    }


def smooth_shots(shots: List[Dict[str, Any]], project: Dict[str, Any]) -> List[Dict[str, Any]]:
    if len(shots) <= 1:
        return shots
    config = project.get('config') or {}
    min_shot_length_sec = float(config.get('min_shot_length_sec') or 3.0)
    merge_threshold = max(1.0, min_shot_length_sec * 0.58)
    fragile_threshold = max(1.6, min_shot_length_sec * 0.82)
    working = [dict(item) for item in shots]
    changed = True
    while changed and len(working) > 1:
        changed = False
        index = 0
        while index < len(working):
            shot = working[index]
            duration = float(shot.get('duration') or 0.0)
            confidence = float(shot.get('confidence') or 0.0)
            should_merge = duration < merge_threshold or (duration < fragile_threshold and confidence < 0.52)
            if not should_merge:
                index += 1
                continue
            previous = working[index - 1] if index > 0 else None
            following = working[index + 1] if index + 1 < len(working) else None
            if previous is None and following is None:
                index += 1
                continue
            if previous is None:
                merged = _rebuild_shot(
                    project,
                    str(following.get('role') or ''),
                    float(shot.get('start') or 0.0),
                    float(following.get('end') or 0.0),
                    confidence=max(confidence, float(following.get('confidence') or 0.0)),
                    reason='smoothed_short_shot',
                )
                if merged is None:
                    index += 1
                    continue
                working[index + 1] = merged
                del working[index]
                changed = True
                continue
            if following is None:
                merged = _rebuild_shot(
                    project,
                    str(previous.get('role') or ''),
                    float(previous.get('start') or 0.0),
                    float(shot.get('end') or 0.0),
                    confidence=max(confidence, float(previous.get('confidence') or 0.0)),
                    reason='smoothed_short_shot',
                )
                if merged is None:
                    index += 1
                    continue
                working[index - 1] = merged
                del working[index]
                changed = True
                continue
            prev_score = float(previous.get('duration') or 0.0) + float(previous.get('confidence') or 0.0) * 2.0
            next_score = float(following.get('duration') or 0.0) + float(following.get('confidence') or 0.0) * 2.0
            merge_into_previous = prev_score >= next_score
            if merge_into_previous:
                merged = _rebuild_shot(
                    project,
                    str(previous.get('role') or ''),
                    float(previous.get('start') or 0.0),
                    float(shot.get('end') or 0.0),
                    confidence=max(confidence, float(previous.get('confidence') or 0.0)),
                    reason='smoothed_short_shot',
                )
                if merged is None:
                    index += 1
                    continue
                working[index - 1] = merged
                del working[index]
            else:
                merged = _rebuild_shot(
                    project,
                    str(following.get('role') or ''),
                    float(shot.get('start') or 0.0),
                    float(following.get('end') or 0.0),
                    confidence=max(confidence, float(following.get('confidence') or 0.0)),
                    reason='smoothed_short_shot',
                )
                if merged is None:
                    index += 1
                    continue
                working[index + 1] = merged
                del working[index]
            changed = True
        if changed:
            normalized: List[Dict[str, Any]] = []
            for item in working:
                if not normalized:
                    normalized.append(item)
                    continue
                previous = normalized[-1]
                if item.get('role') == previous.get('role') and abs(float(item.get('start') or 0.0) - float(previous.get('end') or 0.0)) < 0.05:
                    merged = _rebuild_shot(
                        project,
                        str(previous.get('role') or ''),
                        float(previous.get('start') or 0.0),
                        float(item.get('end') or 0.0),
                        confidence=max(float(previous.get('confidence') or 0.0), float(item.get('confidence') or 0.0)),
                        reason='smoothed_short_shot',
                    )
                    if merged is not None:
                        normalized[-1] = merged
                        continue
                normalized.append(item)
            working = normalized
    return working


def classify_retake_candidates_with_ollama(candidates: List[Dict[str, Any]], ai_config: Dict[str, Any], logger: LoggerFn = _default_logger) -> List[Dict[str, Any]]:
    if not candidates:
        return candidates
    provider = str(ai_config.get('provider') or 'ollama').strip().lower()
    if provider not in {'ollama', 'minimax'}:
        return candidates
    base_url = (ai_config.get('ollama_base_url') or 'http://127.0.0.1:11434').rstrip('/')
    model = (ai_config.get('ollama_model') or '').strip()
    api_key = ''
    if provider == 'minimax':
        api_key = str(ai_config.get('minimax_api_key') or '').strip()
        base_url = str(ai_config.get('minimax_base_url') or 'https://api.minimax.io/v1').rstrip('/')
        model = str(ai_config.get('minimax_model') or 'MiniMax-M3').strip()
        if not api_key:
            return candidates
    elif not model:
        return candidates

    llm_context = [
        {
            'index': index,
            'role': candidate.get('role') or '',
            'previous_role': candidate.get('previous_role') or '',
            'start': candidate.get('start'),
            'end': candidate.get('end'),
            'reason': candidate.get('reason') or '',
            'previous_text': candidate.get('previous_text') or '',
            'current_text': candidate.get('current_text') or candidate.get('text') or '',
        }
        for index, candidate in enumerate(candidates)
    ]
    prompt_text = (
        'Du bist ein extrem konservativer Podcast-Editor fuer Longform-Interviews. '
        'Pruefe fuer jeden Kandidaten, ob ein echter Retake/Falschstart vorliegt. '
        'Beruecksichtige Sprecherrolle, den vorherigen Satz, den neuen Satz und ob der neue Versuch inhaltlich sauberer wirkt. '
        'Antworte NUR als JSON-Liste mit Eintraegen {index, keep, confidence, short_reason}. '
        'keep darf nur keep_a, keep_b oder review sein.\n\n'
        + json.dumps(llm_context, ensure_ascii=False)
    )

    def _extract_chat_message_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return _extract_chat_message_text(payload.get('content'))
        if isinstance(payload, list):
            parts: List[str] = []
            for item in payload:
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        parts.append(stripped)
                    continue
                if isinstance(item, dict):
                    candidate_text = item.get('text')
                    if candidate_text is None:
                        candidate_text = item.get('content')
                    if candidate_text is None and isinstance(item.get('output_text'), str):
                        candidate_text = item.get('output_text')
                    extracted = _extract_chat_message_text(candidate_text)
                    if extracted.strip():
                        parts.append(extracted.strip())
            return '\n'.join(parts).strip()
        return ''

    try:
        if provider == 'ollama':
            prompt = {
                'model': model,
                'stream': False,
                'format': 'json',
                'prompt': prompt_text,
            }
            request = urllib.request.Request(
                f'{base_url}/api/generate',
                data=json.dumps(prompt).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode('utf-8', errors='replace'))
            raw_text = body.get('response') or '[]'
        else:
            request_payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'Du bist ein konservativer Podcast-Editor und antwortest nur JSON.'},
                    {'role': 'user', 'content': prompt_text},
                ],
                'max_tokens': 700,
            }
            request = urllib.request.Request(
                f'{base_url}/text/chatcompletion_v2',
                data=json.dumps(request_payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                },
                method='POST',
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode('utf-8', errors='replace'))
            if not isinstance(body, dict):
                logger('LLM-Retake-Klassifikation lieferte keine lesbare MiniMax-Antwort, bleibe heuristisch.')
                return candidates
            choices = body.get('choices')
            if not isinstance(choices, list) or not choices:
                logger(f"LLM-Retake-Klassifikation ohne MiniMax-choices, bleibe heuristisch. {((body.get('base_resp') or {}).get('status_msg') if isinstance(body, dict) else '') or ''}".strip())
                return candidates
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            raw_text = _extract_chat_message_text(first_choice.get('message')) or '[]'
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            return candidates
    except (TypeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger(f'LLM-Retake-Klassifikation fehlgeschlagen, bleibe heuristisch: {exc}')
        return candidates

    by_index = {int(item.get('index')): item for item in parsed if isinstance(item, dict) and str(item.get('index', '')).isdigit()}
    enriched: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        llm_item = by_index.get(index)
        if not llm_item:
            enriched.append(candidate)
            continue
        keep_value = str(llm_item.get('keep') or 'review').strip().lower()
        if keep_value not in {'keep_a', 'keep_b', 'review'}:
            keep_value = 'review'
        next_candidate = dict(candidate)
        next_candidate['keep'] = keep_value
        try:
            next_candidate['confidence'] = max(candidate.get('confidence', 0.0), float(llm_item.get('confidence') or 0.0))
        except Exception:
            pass
        next_candidate['llm_reason'] = str(llm_item.get('short_reason') or '').strip()
        enriched.append(next_candidate)
    return enriched


def classify_segments_with_llm(
    segments: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
    logger: LoggerFn = _default_logger,
    *,
    task: str = 'setup_vs_content',
) -> List[Dict[str, Any]]:
    """
    Use LLM to classify segments as setup or content.
    Supports: 'setup_vs_content', 'retake_classification', 'plausibility_check'
    """
    if not segments or len(segments) < 2:
        return []

    provider = ai_config.get('provider') or 'ollama'
    if provider not in {'ollama', 'minimax', 'openai', 'gemini'}:
        return []

    base_url = ai_config.get(f'{provider}_base_url')
    model = ai_config.get(f'{provider}_model') or ai_config.get('ollama_model') or ''

    if provider == 'minimax':
        api_key = ai_config.get('minimax_api_key')
        base_url = base_url or 'https://api.minimax.io/v1'
        model = model or 'minimax'
    elif provider == 'ollama':
        base_url = base_url or 'http://127.0.0.1:11434'
        model = model or 'llama3'
    elif provider == 'openai':
        api_key = ai_config.get('openai_api_key')
        base_url = base_url or 'https://api.openai.com/v1'
        model = model or 'gpt-4'
    elif provider == 'gemini':
        api_key = ai_config.get('gemini_api_key')
        base_url = base_url or 'https://generativelanguage.googleapis.com/v1beta'
        model = model or 'gemini-pro'

    if provider != 'ollama' and not any([
        ai_config.get('minimax_api_key'),
        ai_config.get('openai_api_key'),
        ai_config.get('gemini_api_key'),
    ]):
        logger('LLM-Klassifikation: Kein API-Key konfiguriert, ueberspringe.')
        return []

    if task == 'setup_vs_content':
        system_prompt = (
            'Du bist ein Video-Podcast-Editor. Analysiere die folgenden Transkript-Segmente '
            'eines Podcast-Interviews und klassifiziere jedes Segment als "setup" (technisches Setup, '
            'Soundcheck, Kameraeinstellung, lockeres Vorgespräch, Wartezeit, Neustart nach Unterbrechung) '
            'oder "content" (echter Podcast-Inhalt). Eine offizielle Einleitung des Podcasts mit Vorstellung, '
            'Kanalbezug, Themenansage oder "Willkommen" ist bereits content und darf NICHT als setup markiert werden. '
            'Antworte NUR als JSON-Liste mit Eintraegen: [{"index": 0, "type": "setup|content", "reason": "kurzeBegruendung"}].'
        )
    elif task == 'retake_classification':
        system_prompt = (
            'Du bist ein Video-Podcast-Editor. Analysiere Retake-Kandidaten und entscheide '
            'konservativ: Soll Segment A (vorheriges) behalten werden und Segment B (neuer Versuch)? '
            'Antworte NUR als JSON: [{"index": 0, "keep": "keep_a|keep_b|review", "confidence": 0.0-1.0, "reason": "text"}].'
        )
    else:
        return []

    # Prepare context with limited segments per batch
    batch_size = 10
    results: List[Dict[str, Any]] = []

    def _extract_chat_message_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return _extract_chat_message_text(payload.get('content'))
        if isinstance(payload, list):
            parts: List[str] = []
            for item in payload:
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        parts.append(stripped)
                    continue
                if isinstance(item, dict):
                    candidate_text = item.get('text')
                    if candidate_text is None:
                        candidate_text = item.get('content')
                    if candidate_text is None and isinstance(item.get('output_text'), str):
                        candidate_text = item.get('output_text')
                    extracted = _extract_chat_message_text(candidate_text)
                    if extracted.strip():
                        parts.append(extracted.strip())
            return '\n'.join(parts).strip()
        return ''

    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        context = [
            {
                'index': batch_start + i,
                'text': seg.get('text', '')[:200],
                'start': seg.get('start', 0),
                'end': seg.get('end', 0),
                'role': seg.get('role', 'unknown'),
            }
            for i, seg in enumerate(batch)
        ]

        prompt_text = system_prompt + '\n\nSegmente:\n' + json.dumps(context, ensure_ascii=False)

        try:
            if provider == 'ollama':
                request_payload = {
                    'model': model,
                    'stream': False,
                    'format': 'json',
                    'prompt': prompt_text,
                }
                request = urllib.request.Request(
                    f'{base_url}/api/generate',
                    data=json.dumps(request_payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                timeout = 90
            elif provider == 'minimax':
                request_payload = {
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)},
                    ],
                    'max_tokens': 500,
                }
                request = urllib.request.Request(
                    f'{base_url}/text/chatcompletion_v2',
                    data=json.dumps(request_payload).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {api_key}',
                    },
                    method='POST',
                )
                timeout = 60
            else:
                continue

            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode('utf-8', errors='replace'))

            if provider == 'ollama':
                raw_text = body.get('response', '[]')
            elif provider == 'minimax':
                if not isinstance(body, dict):
                    logger(f'LLM-Klassifikation: MiniMax-Antwort in Batch {batch_start}-{batch_start + len(batch)} war nicht lesbar, ueberspringe.')
                    continue
                choices = body.get('choices')
                if not isinstance(choices, list) or not choices:
                    logger(f"LLM-Klassifikation: MiniMax lieferte keine choices fuer Batch {batch_start}-{batch_start + len(batch)}, ueberspringe. {((body.get('base_resp') or {}).get('status_msg') if isinstance(body, dict) else '') or ''}".strip())
                    continue
                first_choice = choices[0] if isinstance(choices[0], dict) else {}
                raw_text = _extract_chat_message_text(first_choice.get('message')) or '[]'
            else:
                raw_text = '[]'

            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and 'index' in item:
                        item['batch_offset'] = batch_start
                        results.append(item)

            logger(f'LLM-Klassifikation: Batch {batch_start}-{batch_start + len(batch)} verarbeitet.')

        except Exception as exc:
            logger(f'LLM-Klassifikation Batch fehlgeschlagen: {exc}')
            continue

    # Map results back to global indices
    classified: List[Dict[str, Any]] = []
    for result in results:
        global_index = result.get('index', 0) + result.get('batch_offset', 0)
        if global_index < len(segments):
            classified.append({
                'segment_index': global_index,
                'type': result.get('type') or result.get('keep') or 'unknown',
                'confidence': result.get('confidence', 0.5),
                'reason': result.get('reason', ''),
            })

    return classified


def detect_setup_with_llm(
    project: Dict[str, Any],
    combined: Dict[str, Any],
    primary_role: str,
    ai_config: Dict[str, Any],
    logger: LoggerFn = _default_logger,
) -> List[Dict[str, Any]]:
    """
    Use LLM to detect setup segments at the beginning of recordings.
    Returns setup ranges that should be trimmed.
    """
    config = project.get('config') or {}
    primary_words = list((combined.get('roles') or {}).get(primary_role, {}).get('words') or [])

    if not primary_words:
        return []

    # Get first 5 minutes of content
    cutoff_time = 300.0  # 5 minutes
    early_segments = [
        seg for seg in (combined.get('roles') or {}).get(primary_role, {}).get('segments') or []
        if float(seg.get('end', 0) or 0) <= cutoff_time
    ]

    if len(early_segments) < 3:
        return []

    classified = classify_segments_with_llm(
        early_segments,
        ai_config,
        logger,
        task='setup_vs_content',
    )

    setup_ranges: List[Dict[str, Any]] = []
    for item in classified:
        if item.get('type') == 'setup':
            seg_idx = item.get('segment_index', 0)
            if seg_idx < len(early_segments):
                seg = early_segments[seg_idx]
                setup_ranges.append({
                    'start': seg.get('start', 0),
                    'end': seg.get('end', 0),
                    'reason': f"llm_setup: {item.get('reason', '')}",
                    'confidence': item.get('confidence', 0.5),
                })

    # Merge adjacent setup ranges
    if not setup_ranges:
        return []

    merged: List[Dict[str, Any]] = [dict(setup_ranges[0])]
    for item in setup_ranges[1:]:
        if item['start'] <= merged[-1]['end'] + 0.5:
            merged[-1]['end'] = max(merged[-1]['end'], item['end'])
            merged[-1]['confidence'] = max(merged[-1]['confidence'], item['confidence'])
        else:
            merged.append(dict(item))

    logger(f'LLM-Setup-Erkennung: {len(merged)} Setup-Bereiche gefunden.')
    return merged


def validate_transcript_coherence(
    combined: Dict[str, Any],
    analysis_result: Dict[str, Any],
    logger: LoggerFn = _default_logger,
) -> List[Dict[str, Any]]:
    """
    Validate that the cut transcript maintains coherence.
    Check for unnatural jumps, missing context, etc.
    """
    warnings: List[Dict[str, Any]] = []

    # Check speaker turn coherence
    speaker_turns = analysis_result.get('speaker_turns') or []
    for i, turn in enumerate(speaker_turns):
        if i == 0:
            continue
        prev = speaker_turns[i - 1]
        gap = float(turn['start']) - float(prev['end'])

        # Unusually long gap might indicate missing content
        if gap > 5.0:
            warnings.append({
                'start': prev['end'],
                'end': turn['start'],
                'type': 'large_gap_warning',
                'note': f'Groessere Luecke ({gap:.1f}s) - Moegl. fehlender Content.',
            })

        # Very short turn might be an artifact
        duration = float(turn['end']) - float(turn['start'])
        if duration < 1.0 and turn.get('reason') in {'soft_switch', 'ignore_backchannel'}:
            warnings.append({
                'start': turn['start'],
                'end': turn['end'],
                'type': 'short_turn_warning',
                'note': f'Sehr kurzer Sprecherturn ({duration:.2f}s) - Moegl. Artefakt.',
            })

    # Check that all keep_ranges are covered by speaker_turns
    keep_ranges = analysis_result.get('keep_ranges') or []
    for kr in keep_ranges:
        kr_start = float(kr.get('start', 0))
        kr_end = float(kr.get('end', 0))
        has_coverage = any(
            float(t['start']) <= kr_start and float(t['end']) >= kr_end
            for t in speaker_turns
        )
        if not has_coverage:
            warnings.append({
                'start': kr_start,
                'end': kr_end,
                'type': 'uncovered_range',
                'note': 'Keep-Range ohne Sprecherturn-Abdeckung.',
            })

    if warnings:
        logger(f'Transcript-Validierung: {len(warnings)} Warnungen gefunden.')

    return warnings


def subtract_cuts_from_ranges(base_ranges: List[Tuple[float, float]], cuts: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
    ranges = [(max(0.0, float(start)), max(0.0, float(end))) for start, end in base_ranges if end - start > 0.05]
    ordered_cuts = sorted(cuts, key=lambda item: (float(item.get('start') or 0.0), float(item.get('end') or 0.0)))
    keep_ranges: List[Tuple[float, float]] = []
    for base_start, base_end in ranges:
        cursor = base_start
        for cut in ordered_cuts:
            cut_start = max(base_start, float(cut.get('start') or 0.0))
            cut_end = min(base_end, float(cut.get('end') or 0.0))
            if cut_end <= cut_start:
                continue
            if cut_start > cursor + 0.05:
                keep_ranges.append((cursor, cut_start))
            cursor = max(cursor, cut_end)
        if base_end > cursor + 0.05:
            keep_ranges.append((cursor, base_end))
    return keep_ranges


def build_base_ranges_from_primary(
    project: Dict[str, Any],
    primary_role: str,
    editorial_ranges: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[float, float]]:
    ranges: List[Tuple[float, float]] = []
    if editorial_ranges:
        for item in editorial_ranges:
            start = float(item.get('global_start') or 0.0)
            end = float(item.get('global_end') or start)
            if end - start > 0.05:
                ranges.append((start, end))
        if ranges:
            return ranges
    for item in sorted(unique_role_files(project, primary_role), key=lambda raw: float(raw.get('global_start_sec') or 0.0)):
        start = float(item.get('global_start_sec') or 0.0)
        end = float(item.get('global_end_sec') or start)
        if end - start > 0.05:
            ranges.append((start, end))
    return ranges


def build_speaker_turns(
    combined: Dict[str, Any],
    project: Dict[str, Any],
    backchannels: List[Dict[str, Any]],
    *,
    base_ranges: Optional[List[Tuple[float, float]]] = None,
    logger: LoggerFn = _default_logger,
) -> List[Dict[str, Any]]:
    mode = project.get('mode') or 'single'
    config = project.get('config') or {}
    primary_role = config.get('primary_audio_camera') or ('host' if mode == 'interview' else 'single')
    if mode != 'interview':
        return [{
            'role': primary_role,
            'start': item[0],
            'end': item[1],
            'confidence': 1.0,
            'reason': 'single_camera',
        } for item in (base_ranges or build_base_ranges_from_primary(project, primary_role))]

    roles = ['host', 'guest']
    primary_words = list((combined.get('roles') or {}).get(primary_role, {}).get('words') or [])
    all_words = list(combined.get('all_words') or [])
    working_ranges = base_ranges or build_base_ranges_from_primary(project, primary_role)

    if bool(config.get('pyannote_diarization_enabled')):
        try:
            pyannote_turns = _build_pyannote_turns(project, primary_role, working_ranges, logger=logger)
            if pyannote_turns:
                logger(f'Pyannote: {len(pyannote_turns)} Sprecherturns aus Diarization uebernommen.')
                return _finalize_speaker_turns(pyannote_turns, config)
            logger('Pyannote: Keine verwertbaren Sprecherturns gefunden, falle auf Audio-Aktivitaet zurueck.')
        except Exception as exc:
            logger(f'Pyannote: {exc} Fallback auf Audio-Aktivitaet.')

    boundaries = {round(value, 2) for item in working_ranges for value in item}
    boundary_words = all_words or primary_words
    for word in boundary_words:
        boundaries.add(round(float(word['start']), 2))
        boundaries.add(round(float(word['end']), 2))
    for marker in backchannels:
        boundaries.add(round(float(marker['start']), 2))
        boundaries.add(round(float(marker['end']), 2))
    ordered = sorted(boundaries)
    if len(ordered) < 2:
        return []

    backchannel_windows = [(float(item['start']), float(item['end']), item['role']) for item in backchannels]

    def score_role(role: str, start: float, end: float) -> Tuple[Dict[str, float], bool]:
        window_scores = _score_role_window(project, role, start, end)
        is_backchannel = False
        for marker_start, marker_end, marker_role in backchannel_windows:
            if marker_role == role and max(0.0, min(end, marker_end) - max(start, marker_start)) > 0:
                is_backchannel = True
        return window_scores, is_backchannel

    provisional: List[Dict[str, Any]] = []
    current_role = primary_role if primary_role in roles else roles[0]
    for start, end in zip(ordered, ordered[1:]):
        if end - start < 0.12:
            continue
        if not any(max(0.0, min(end, keep_end) - max(start, keep_start)) > 0.01 for keep_start, keep_end in working_ranges):
            continue
        role_scores = {role: score_role(role, start, end) for role in roles}
        ranked = sorted(
            role_scores.items(),
            key=lambda entry: (
                float((entry[1][0] or {}).get('combined') or 0.0),
                float((entry[1][0] or {}).get('transcript') or 0.0),
                float((entry[1][0] or {}).get('audio') or 0.0),
            ),
            reverse=True,
        )

        # Guard against single-role scenarios
        if len(ranked) < 2:
            # Only one role has audio activity - use it exclusively
            best_role = ranked[0][0] if ranked else current_role
            best_scores = ranked[0][1][0] if ranked else {}
            best_score = float((best_scores or {}).get('combined') or 0.0)
            best_backchannel = ranked[0][1][1] if ranked else False
            alt_role = current_role
            alt_score = 0.0
            chosen = best_role
            reason = 'single_role_dominant'
            confidence = max(0.2, min(0.98, 0.42 + best_score * 0.9))
        else:
            best_role, (best_scores, best_backchannel) = ranked[0]
            alt_role, (alt_scores, _) = ranked[1]
            best_score = float((best_scores or {}).get('combined') or 0.0)
            alt_score = float((alt_scores or {}).get('combined') or 0.0)
            best_transcript = float((best_scores or {}).get('transcript') or 0.0)
            alt_transcript = float((alt_scores or {}).get('transcript') or 0.0)
            best_audio = float((best_scores or {}).get('audio') or 0.0)
            alt_audio = float((alt_scores or {}).get('audio') or 0.0)
            chosen = current_role
            reason = 'hold'
            if best_score <= 0.08 and alt_score <= 0.08:
                chosen = current_role
                reason = 'silence_hold'
            elif best_backchannel and alt_score >= max(0.12, best_score * 0.8):
                chosen = alt_role
                reason = 'ignore_backchannel'
            elif best_transcript >= alt_transcript + 0.08:
                chosen = best_role
                reason = 'transcript_dominant'
            elif best_audio >= alt_audio + 0.12:
                chosen = best_role
                reason = 'audio_dominant'
            elif best_score >= alt_score + 0.10:
                chosen = best_role
                reason = 'dominant_voice'
            elif current_role != best_role and best_score >= alt_score + 0.04 and (
                best_transcript >= alt_transcript + 0.03 or best_audio >= alt_audio + 0.05
            ):
                chosen = best_role
                reason = 'soft_switch'
            elif current_role == best_role or best_score >= alt_score - 0.02:
                chosen = current_role if current_role in roles else best_role
                reason = 'hysteresis_hold'
            confidence = max(
                0.2,
                min(
                    0.98,
                    0.40
                    + max(0.0, best_score - alt_score) * 0.88
                    + max(0.0, best_transcript - alt_transcript) * 0.22
                    + max(0.0, best_audio - alt_audio) * 0.12
                    + min(best_score, 0.25),
                ),
            )
        current_role = chosen
        provisional.append({
            'role': chosen,
            'start': round(start, 3),
            'end': round(end, 3),
            'confidence': round(confidence, 3),
            'reason': reason,
        })

    return _finalize_speaker_turns(provisional, config)


def interval_segments_for_role(project: Dict[str, Any], role: str, start: float, end: float) -> List[Dict[str, Any]]:
    pieces: List[Dict[str, Any]] = []
    for item in sorted(unique_role_files(project, role), key=lambda raw: float(raw.get('global_start_sec') or 0.0)):
        file_start = float(item.get('global_start_sec') or 0.0)
        file_end = float(item.get('global_end_sec') or file_start)
        overlap_start = max(start, file_start)
        overlap_end = min(end, file_end)
        if overlap_end <= overlap_start:
            continue
        pieces.append({
            'file_id': item.get('id'),
            'source_path': item.get('normalized_path') or item.get('stored_path'),
            'proxy_path': item.get('proxy_path'),
            'role': role,
            'global_start': round(overlap_start, 3),
            'global_end': round(overlap_end, 3),
            'local_start': round(overlap_start - file_start, 3),
            'local_end': round(overlap_end - file_start, 3),
            'duration': round(overlap_end - overlap_start, 3),
            'file_name': item.get('original_name'),
        })
    return pieces


def _collect_transcript_words(transcript_map: Dict[str, Any], item: Dict[str, Any], *, include_global_offset: bool) -> List[Dict[str, Any]]:
    transcript = (transcript_map.get('files') or {}).get(item.get('id')) or {}
    words: List[Dict[str, Any]] = []
    global_offset = float(item.get('global_start_sec') or 0.0) if include_global_offset else 0.0
    for segment in transcript.get('segments') or []:
        segment_words = segment.get('words') or []
        if segment_words:
            for word in segment_words:
                token = _normalize_token(str(word.get('word') or ''))
                if not token:
                    continue
                words.append({
                    'token': token,
                    'time': global_offset + float(word.get('start') or 0.0),
                })
            continue
        text_tokens = [_normalize_token(token) for token in str(segment.get('text') or '').split()]
        text_tokens = [token for token in text_tokens if token]
        if not text_tokens:
            continue
        segment_start = global_offset + float(segment.get('start') or 0.0)
        segment_end = global_offset + float(segment.get('end') or segment.get('start') or 0.0)
        duration = max(0.01, segment_end - segment_start)
        step = duration / max(1, len(text_tokens))
        for index, token in enumerate(text_tokens):
            words.append({
                'token': token,
                'time': segment_start + index * step,
            })
    return words


def _unique_ngram_index(words: List[Dict[str, Any]], *, n: int) -> Dict[Tuple[str, ...], float]:
    index: Dict[Tuple[str, ...], float] = {}
    counts: Dict[Tuple[str, ...], int] = {}
    if len(words) < n:
        return {}
    for offset in range(0, len(words) - n + 1):
        gram = tuple(word['token'] for word in words[offset:offset + n])
        if not any(len(token) >= 4 for token in gram):
            continue
        counts[gram] = counts.get(gram, 0) + 1
        index.setdefault(gram, float(words[offset]['time']))
    return {gram: index[gram] for gram, count in counts.items() if count == 1}


def estimate_transcript_offset(reference_words: List[Dict[str, Any]], target_words: List[Dict[str, Any]]) -> Tuple[Optional[float], float, int]:
    if len(reference_words) < 8 or len(target_words) < 8:
        return None, 0.0, 0
    offsets: List[float] = []
    for n in (8, 7, 6, 5):
        reference_index = _unique_ngram_index(reference_words, n=n)
        target_index = _unique_ngram_index(target_words, n=n)
        common = set(reference_index).intersection(target_index)
        if not common:
            continue
        offsets.extend(reference_index[gram] - target_index[gram] for gram in common)
        if len(offsets) >= 5:
            break
    if len(offsets) < 3:
        return None, 0.0, len(offsets)

    buckets: Dict[float, List[float]] = {}
    for offset in offsets:
        bucket_key = round(offset * 2.0) / 2.0
        buckets.setdefault(bucket_key, []).append(offset)
    best_bucket = max(buckets.values(), key=lambda values: (len(values), -abs(float(np.std(values))) if len(values) > 1 else 0.0))
    best_bucket = sorted(best_bucket)
    median_offset = float(np.median(best_bucket))
    spread = float(np.std(best_bucket)) if len(best_bucket) > 1 else 0.0
    confidence = max(0.0, min(0.98, 0.42 + min(0.42, len(best_bucket) * 0.04) - min(0.18, spread * 0.12)))
    return median_offset, confidence, len(best_bucket)


def estimate_transcript_offset_near(
    reference_words: List[Dict[str, Any]],
    target_words: List[Dict[str, Any]],
    *,
    expected_offset_sec: float,
    search_radius_sec: float = 180.0,
) -> Tuple[Optional[float], float, int]:
    if len(reference_words) < 8 or len(target_words) < 8:
        return None, 0.0, 0
    target_start = float(target_words[0].get('time') or 0.0)
    target_end = float(target_words[-1].get('time') or target_start)
    target_duration = max(0.0, target_end - target_start)
    window_start = float(expected_offset_sec) - max(45.0, float(search_radius_sec))
    window_end = float(expected_offset_sec) + target_duration + max(45.0, float(search_radius_sec))
    localized_reference_words = [
        word
        for word in reference_words
        if window_start <= float(word.get('time') or 0.0) <= window_end
    ]
    return estimate_transcript_offset(localized_reference_words, target_words)


def score_alignment_at_offset(reference_sequence: np.ndarray, target_sequence: np.ndarray, *, offset_sec: float, hop_sec: float) -> float:
    reference_sequence = np.asarray(reference_sequence, dtype=np.float32).reshape(-1)
    target_sequence = np.asarray(target_sequence, dtype=np.float32).reshape(-1)
    if reference_sequence.size <= 1 or target_sequence.size <= 1:
        return 0.0
    lag_frames = int(round(float(offset_sec) / max(float(hop_sec), 1e-6)))
    reference_start = max(0, lag_frames)
    target_start = max(0, -lag_frames)
    overlap = min(reference_sequence.size - reference_start, target_sequence.size - target_start)
    min_overlap_frames = max(12, int(round(8.0 / max(float(hop_sec), 1e-6))))
    if overlap < min_overlap_frames:
        return 0.0
    reference_slice = _normalize_feature_vector(reference_sequence[reference_start:reference_start + overlap])
    target_slice = _normalize_feature_vector(target_sequence[target_start:target_start + overlap])
    denominator = float(np.linalg.norm(reference_slice) * np.linalg.norm(target_slice))
    if denominator <= 1e-6:
        return 0.0
    score = float(np.dot(reference_slice, target_slice) / denominator)
    return max(-1.0, min(1.0, score))


def refine_sync_with_transcripts(
    project: Dict[str, Any],
    transcript_map: Dict[str, Any],
    sync_report: Optional[Dict[str, Any]] = None,
    *,
    logger: LoggerFn = _default_logger,
) -> Dict[str, Any]:
    config = project.get('config') or {}
    primary_role = config.get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')
    primary_files = unique_role_files(project, primary_role, logger=logger)
    reference_words: List[Dict[str, Any]] = []
    for item in primary_files:
        reference_words.extend(_collect_transcript_words(transcript_map, item, include_global_offset=True))
    if len(reference_words) < 8:
        return sync_report or {}

    next_sync_report = dict(sync_report or {})
    next_sync_report.setdefault('primary_role', primary_role)
    next_sync_report.setdefault('roles', {})

    for role in (project.get('files') or {}).keys():
        if role == primary_role:
            continue
        role_entries = next_sync_report.setdefault('roles', {}).setdefault(role, {'files': []})
        role_files = unique_role_files(project, role, logger=logger)
        for item in role_files:
            target_words = _collect_transcript_words(transcript_map, item, include_global_offset=False)
            offset_sec, confidence, match_count = estimate_transcript_offset(reference_words, target_words)
            if offset_sec is None or confidence < 0.45:
                continue
            existing_confidence = float(item.get('sync_confidence') or 0.0)
            existing_method = str(item.get('sync_method') or '').strip().lower()
            existing_offset = float(item.get('global_start_sec') or 0.0)
            if existing_method == 'audio_feature' and existing_confidence >= 0.55:
                if abs(existing_offset - offset_sec) <= 1.0:
                    continue
                if confidence < existing_confidence + 0.18:
                    continue
            if existing_confidence >= confidence and existing_confidence >= 0.18:
                continue
            duration = float(item.get('duration_sec') or 0.0)
            item['global_start_sec'] = round(offset_sec, 3)
            item['global_end_sec'] = round(offset_sec + duration, 3)
            item['sync_offset_sec'] = round(offset_sec, 3)
            item['sync_confidence'] = round(confidence, 4)
            item['sync_method'] = 'transcript'
            logger(
                f"Sync-Refine: {role}/{item.get('original_name')} via Transkript auf {offset_sec:.2f}s verfeinert "
                f"(confidence {confidence:.2f}, matches {match_count})."
            )
            role_entries['files'] = [
                {
                    **entry,
                    'global_start_sec': item.get('global_start_sec'),
                    'global_end_sec': item.get('global_end_sec'),
                    'sync_confidence': item.get('sync_confidence'),
                    'sync_method': 'transcript',
                } if str(entry.get('file_id') or '') == str(item.get('id') or '') else entry
                for entry in role_entries.get('files') or []
            ]
    return next_sync_report


def apply_keep_ranges_to_turns(keep_ranges: List[Tuple[float, float]], turns: List[Dict[str, Any]], project: Dict[str, Any]) -> List[Dict[str, Any]]:
    shots: List[Dict[str, Any]] = []
    config = project.get('config') or {}
    jcut_enabled = bool(config.get('jcut_enabled'))
    lcut_enabled = bool(config.get('lcut_enabled'))
    cut_adjust = 0.12
    for keep_start, keep_end in keep_ranges:
        overlapping_turns = [turn for turn in turns if float(turn['end']) > keep_start and float(turn['start']) < keep_end]
        if not overlapping_turns:
            primary_role = config.get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')
            overlapping_turns = [{'role': primary_role, 'start': keep_start, 'end': keep_end, 'confidence': 0.45, 'reason': 'fallback'}]
        intervals: List[Dict[str, Any]] = []
        for turn in overlapping_turns:
            shot_start = max(keep_start, float(turn['start']))
            shot_end = min(keep_end, float(turn['end']))
            if shot_end - shot_start <= 0.12:
                continue
            intervals.append({
                'role': str(turn['role']),
                'start': shot_start,
                'end': shot_end,
                'confidence': turn.get('confidence', 0.5),
                'reason': turn.get('reason') or 'speaker_follow',
            })
        for index in range(len(intervals) - 1):
            current = intervals[index]
            following = intervals[index + 1]
            boundary = min(current['end'], following['start'])
            if following['start'] - current['end'] > 0.02:
                boundary = (current['end'] + following['start']) / 2.0
            if jcut_enabled and not lcut_enabled:
                boundary = min(following['end'] - 0.12, boundary + cut_adjust)
            elif lcut_enabled and not jcut_enabled:
                boundary = max(current['start'] + 0.12, boundary - cut_adjust)
            boundary = max(current['start'] + 0.12, min(following['end'] - 0.12, boundary))
            current['end'] = boundary
            following['start'] = boundary
        for interval in intervals:
            shot_start = interval['start']
            shot_end = interval['end']
            if shot_end - shot_start <= 0.12:
                continue
            segments = interval_segments_for_role(project, interval['role'], shot_start, shot_end)
            if not segments:
                continue
            shots.append({
                'role': interval['role'],
                'start': round(shot_start, 3),
                'end': round(shot_end, 3),
                'duration': round(shot_end - shot_start, 3),
                'confidence': interval['confidence'],
                'reason': interval['reason'],
                'segments': segments,
            })
    merged: List[Dict[str, Any]] = []
    for shot in shots:
        if not merged:
            merged.append(shot)
            continue
        previous = merged[-1]
        if shot['role'] == previous['role'] and abs(float(shot['start']) - float(previous['end'])) < 0.05:
            previous['end'] = shot['end']
            previous['duration'] = round(float(previous['end']) - float(previous['start']), 3)
            previous['segments'].extend(shot['segments'])
            previous['confidence'] = round((float(previous['confidence']) + float(shot['confidence'])) / 2.0, 3)
            continue
        merged.append(shot)
    return merged


def build_reaction_markers(turns: List[Dict[str, Any]], backchannels: List[Dict[str, Any]], project: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not bool((project.get('config') or {}).get('reaction_marker_enabled', True)):
        return []
    markers: List[Dict[str, Any]] = []
    for turn in turns:
        opposite_role = 'guest' if turn['role'] == 'host' else 'host'
        for item in backchannels:
            if item['role'] != opposite_role:
                continue
            if item['start'] >= turn['end'] or item['end'] <= turn['start']:
                continue
            markers.append({
                'start': round(max(turn['start'], item['start']), 3),
                'end': round(min(turn['end'], item['end']), 3),
                'type': 'reaction_opportunity',
                'role': opposite_role,
                'note': f"Reaktionsmoment auf {turn['role']}: {item.get('text') or ''}".strip(),
            })
    return markers


def _merge_review_markers(markers: List[Dict[str, Any]], *, merge_gap_sec: float = 0.16) -> List[Dict[str, Any]]:
    ordered = sorted(
        [
            {
                **marker,
                'start': round(float(marker.get('start') or 0.0), 3),
                'end': round(max(float(marker.get('start') or 0.0), float(marker.get('end') or marker.get('start') or 0.0)), 3),
                'type': str(marker.get('type') or 'review'),
                'note': str(marker.get('note') or '').strip(),
                'role': str(marker.get('role') or '').strip(),
            }
            for marker in markers
        ],
        key=lambda item: (float(item['start']), float(item['end']), item['type']),
    )
    if not ordered:
        return []
    merged: List[Dict[str, Any]] = [dict(ordered[0])]
    for item in ordered[1:]:
        previous = merged[-1]
        if (
            item['type'] == previous['type']
            and item.get('role', '') == previous.get('role', '')
            and float(item['start']) <= float(previous['end']) + merge_gap_sec
        ):
            previous['end'] = round(max(float(previous['end']), float(item['end'])), 3)
            notes = [note for note in [previous.get('note', ''), item.get('note', '')] if note]
            previous['note'] = ' | '.join(dict.fromkeys(notes))
            continue
        merged.append(dict(item))
    return merged


def build_quality_review_markers(
    project: Dict[str, Any],
    speaker_turns: List[Dict[str, Any]],
    shots: List[Dict[str, Any]],
    keep_ranges: List[Tuple[float, float]],
) -> List[Dict[str, Any]]:
    config = project.get('config') or {}
    review_threshold = float(config.get('review_threshold') or 0.62)
    min_shot_length_sec = float(config.get('min_shot_length_sec') or 3.0)
    primary_role = config.get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')
    markers: List[Dict[str, Any]] = []

    for role, role_files in (project.get('files') or {}).items():
        for item in unique_role_files(project, role):
            sync_confidence = float(item.get('sync_confidence') or (1.0 if role == primary_role else 0.0))
            sync_method = str(item.get('sync_method') or ('primary' if role == primary_role else 'unknown')).strip()
            if role != primary_role and (sync_method in {'fallback', 'transcript'} or sync_confidence < 0.72):
                start_sec = float(item.get('global_start_sec') or 0.0)
                end_sec = float(item.get('global_end_sec') or start_sec)
                markers.append({
                    'start': round(start_sec, 3),
                    'end': round(min(end_sec, start_sec + 18.0), 3),
                    'type': 'sync_review',
                    'role': role,
                    'note': f"Sync pruefen: {item.get('original_name') or role}, Methode {sync_method}, confidence {sync_confidence:.2f}",
                })

    for turn in speaker_turns:
        duration = max(0.0, float(turn.get('end') or 0.0) - float(turn.get('start') or 0.0))
        confidence = float(turn.get('confidence') or 0.0)
        reason = str(turn.get('reason') or '')
        if confidence < max(0.46, review_threshold - 0.10):
            markers.append({
                'start': round(float(turn.get('start') or 0.0), 3),
                'end': round(float(turn.get('end') or 0.0), 3),
                'type': 'speaker_turn_review',
                'role': str(turn.get('role') or ''),
                'note': f"Sprecherwechsel pruefen: confidence {confidence:.2f}, reason {reason or 'unknown'}",
            })
        elif duration < max(1.1, min_shot_length_sec * 0.45) and reason in {'soft_switch', 'ignore_backchannel', 'hysteresis_hold'}:
            markers.append({
                'start': round(float(turn.get('start') or 0.0), 3),
                'end': round(float(turn.get('end') or 0.0), 3),
                'type': 'short_turn_review',
                'role': str(turn.get('role') or ''),
                'note': f"Sehr kurzer Sprecherturn ({duration:.2f}s, {reason})",
            })

    short_shot_threshold = max(0.9, min_shot_length_sec * 0.42)
    for shot in shots:
        duration = max(0.0, float(shot.get('duration') or 0.0))
        confidence = float(shot.get('confidence') or 0.0)
        if duration < short_shot_threshold:
            markers.append({
                'start': round(float(shot.get('start') or 0.0), 3),
                'end': round(float(shot.get('end') or 0.0), 3),
                'type': 'short_shot_review',
                'role': str(shot.get('role') or ''),
                'note': f"Sehr kurzer Shot ({duration:.2f}s)",
            })
        elif confidence < max(0.48, review_threshold - 0.08) and duration < max(1.6, min_shot_length_sec * 0.7):
            markers.append({
                'start': round(float(shot.get('start') or 0.0), 3),
                'end': round(float(shot.get('end') or 0.0), 3),
                'type': 'fragile_shot_review',
                'role': str(shot.get('role') or ''),
                'note': f"Fragiler Shot ({duration:.2f}s, confidence {confidence:.2f})",
            })

    ordered_ranges = sorted([(float(start), float(end)) for start, end in keep_ranges], key=lambda item: (item[0], item[1]))
    for previous, current in zip(ordered_ranges, ordered_ranges[1:]):
        gap = float(current[0]) - float(previous[1])
        if 0.035 <= gap <= 0.35:
            markers.append({
                'start': round(float(previous[1]), 3),
                'end': round(float(current[0]), 3),
                'type': 'micro_gap_review',
                'note': f"Kurze Luecke zwischen Keep-Ranges ({gap:.3f}s)",
            })

    return _merge_review_markers(markers)


def analyze_project(project: Dict[str, Any], transcript_map: Dict[str, Any], logger: LoggerFn = _default_logger, *, stop_checker: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    ensure_not_stopped(stop_checker)
    combined = build_combined_transcript(project, transcript_map)
    config = project.get('config') or {}
    primary_role = config.get('primary_audio_camera') or ('host' if project.get('mode') == 'interview' else 'single')
    primary_words = list((combined.get('roles') or {}).get(primary_role, {}).get('words') or [])
    primary_segments = list((combined.get('roles') or {}).get(primary_role, {}).get('segments') or [])
    if not primary_words:
        raise RuntimeError('No primary transcript words found. Please verify the uploaded media and audio extraction.')

    backchannels = detect_backchannels(combined, config)
    pause_cuts = detect_pause_cuts(primary_words, config)
    filler_cuts = detect_filler_cuts(primary_words, config)
    retake_candidates = detect_retake_candidates(primary_segments, config)
    retake_candidates = classify_retake_candidates_with_ollama(retake_candidates, project.get('ai') or {}, logger=logger)
    editorial_ranges = detect_editorial_content_ranges(project, combined, primary_role, logger=logger)

    # LLM-enhanced setup detection (optional, uses Ollama/MiniMax if available)
    llm_setup_ranges = []
    ai_config = project.get('ai') or {}
    if ai_config.get('provider') in {'ollama', 'minimax', 'openai', 'gemini'}:
        try:
            llm_setup_ranges = detect_setup_with_llm(project, combined, primary_role, ai_config, logger=logger)
            if llm_setup_ranges:
                logger(f'LLM-Setup-Erkennung: {len(llm_setup_ranges)} Bereiche gefunden, merge mit editorial_ranges.')
                editorial_ranges = apply_llm_setup_refinement(project, editorial_ranges, llm_setup_ranges, primary_role, logger=logger)
        except Exception as exc:
            logger(f'LLM-Setup fehlgeschlagen, nutze nur Heuristik: {exc}')

    review_markers: List[Dict[str, Any]] = []
    retake_cuts: List[Dict[str, Any]] = []
    for candidate in retake_candidates:
        review_markers.append({
            'start': candidate['start'],
            'end': candidate['end'],
            'type': 'retake_review',
            'note': f"{candidate.get('reason')}: {(candidate.get('llm_reason') or candidate.get('text') or '').strip()}".strip(),
        })
        retake_mode = str(config.get('retake_mode') or 'off').strip().lower()
        if retake_mode == 'conservative_cut' and candidate.get('keep') == 'keep_b':
            midpoint = float(candidate['start']) + min(0.8, max(0.2, float(candidate['end']) - float(candidate['start'])) / 3.0)
            retake_cuts.append({
                'start': float(candidate['start']),
                'end': midpoint,
                'reason': 'retake_prefix_cut',
                'confidence': max(0.55, float(candidate.get('confidence') or 0.0)),
            })
        elif retake_mode == 'aggressive_cut':
            keep_value = str(candidate.get('keep') or 'review').strip().lower()
            cut_end = None
            if keep_value == 'keep_b':
                cut_end = float(candidate['end'])
            elif keep_value == 'review' and float(candidate.get('confidence') or 0.0) >= 0.84:
                cut_end = float(candidate['end'])
            if cut_end is not None and cut_end - float(candidate['start']) >= 0.18:
                retake_cuts.append({
                    'start': float(candidate['start']),
                    'end': cut_end,
                    'reason': 'retake_aggressive_cut',
                    'confidence': max(0.72, float(candidate.get('confidence') or 0.0)),
                })

    cuts = sorted([*pause_cuts, *filler_cuts, *retake_cuts], key=lambda item: (float(item['start']), float(item['end'])))
    base_ranges = build_base_ranges_from_primary(project, primary_role, editorial_ranges=editorial_ranges)
    keep_ranges = subtract_cuts_from_ranges(base_ranges, cuts)
    speaker_turns = build_speaker_turns(combined, project, backchannels, base_ranges=base_ranges, logger=logger)
    shots = apply_keep_ranges_to_turns(keep_ranges, speaker_turns, project)
    shots = smooth_shots(shots, project)
    reaction_markers = build_reaction_markers(speaker_turns, backchannels, project)
    quality_review_markers = build_quality_review_markers(project, speaker_turns, shots, keep_ranges)
    coherence_warnings = validate_transcript_coherence(combined, {
        'speaker_turns': speaker_turns,
        'keep_ranges': [{'start': round(start, 3), 'end': round(end, 3)} for start, end in keep_ranges],
    }, logger=logger)

    for cut in cuts:
        if cut.get('confidence', 0.0) < float(config.get('review_threshold') or 0.62):
            review_markers.append({
                'start': cut['start'],
                'end': cut['end'],
                'type': 'cut_review',
                'note': f"Unsicherer Schnitt: {cut.get('reason')}",
            })
    review_markers.extend(quality_review_markers)
    review_markers.extend(coherence_warnings)
    review_markers = _merge_review_markers(review_markers)
    if quality_review_markers:
        logger(
            f"QC: {len(quality_review_markers)} zusaetzliche Pruefmarker "
            f"(gesamt {len(review_markers)} Review-Marker)."
        )

    return {
        'combined_transcript': combined,
        'backchannels': backchannels,
        'cuts': cuts,
        'editorial_ranges': editorial_ranges,
        'llm_setup_ranges': llm_setup_ranges,
        'keep_ranges': [{'start': round(start, 3), 'end': round(end, 3)} for start, end in keep_ranges],
        'speaker_turns': speaker_turns,
        'shots': shots,
        'reaction_markers': reaction_markers,
        'review_markers': review_markers,
        'retake_candidates': retake_candidates,
        'summary': {
            'shot_count': len(shots),
            'review_marker_count': len(review_markers),
            'reaction_marker_count': len(reaction_markers),
            'quality_review_marker_count': len(quality_review_markers),
            'coherence_warning_count': len(coherence_warnings),
            'cut_count': len(cuts),
            'primary_role': primary_role,
            'editorial_trimmed_files': len([item for item in editorial_ranges if item.get('lead_trim_sec') or item.get('tail_trim_sec')]),
        },
    }
