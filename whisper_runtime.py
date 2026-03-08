import os
import threading
import time
from typing import Any, Dict, List, Tuple

from faster_whisper import WhisperModel

from runtime_limits import WHISPER_CPU_THREADS

try:
    import torch
except Exception:  # pragma: no cover - torch is available in runtime, keep fallback defensive
    torch = None


_MODEL_CACHE: Dict[Tuple[str, str, str, int, int], WhisperModel] = {}
_MODEL_META: Dict[Tuple[str, str, str, int, int], Dict[str, Any]] = {}
_MODEL_LOCK = threading.Lock()
_VALID_LANGUAGE_TOKEN = set("abcdefghijklmnopqrstuvwxyz-")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _csv_env(name: str, default: List[str]) -> List[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_language_code(raw: Any) -> str:
    if raw is None:
        return ""
    value = str(raw).strip().lower()
    if not value or value == "auto":
        return ""
    if not all(ch in _VALID_LANGUAGE_TOKEN for ch in value):
        return ""
    return value.split("-")[0]


def _language_hints() -> List[str]:
    hints = _csv_env("WHISPER_LANGUAGE_HINTS", [])
    normalized: List[str] = []
    seen = set()
    for hint in hints:
        code = _normalize_language_code(hint)
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def _transcribe_once(
    model: WhisperModel,
    audio_path: str,
    *,
    word_timestamps: bool,
    beam_size: int,
    vad_filter: bool,
    language: str = "",
):
    kwargs = {
        "word_timestamps": word_timestamps,
        "beam_size": beam_size,
        "vad_filter": vad_filter,
        "condition_on_previous_text": False,
    }
    if language:
        kwargs["language"] = language
    segments_iter, info = model.transcribe(audio_path, **kwargs)
    segments = []
    last_progress_log = time.time()
    last_audio_second = 0.0

    for idx, segment in enumerate(segments_iter, start=1):
        segments.append(segment)
        seg_end = float(getattr(segment, "end", 0.0) or 0.0)
        last_audio_second = seg_end
        now = time.time()
        if idx == 1 or idx % 25 == 0 or (now - last_progress_log) >= 20:
            minutes = int(seg_end // 60)
            seconds = int(seg_end % 60)
            print(
                "⏳ Whisper decoding... "
                f"segments={idx}, audio={minutes:02d}:{seconds:02d}"
            )
            last_progress_log = now

    if segments:
        minutes = int(last_audio_second // 60)
        seconds = int(last_audio_second % 60)
        print(
            "✅ Whisper decoding finished. "
            f"segments={len(segments)}, audio={minutes:02d}:{seconds:02d}"
        )
    else:
        print("⚠️ Whisper decoding finished with no segments.")

    return segments, info


def _resolve_device() -> str:
    configured = (os.environ.get("WHISPER_DEVICE") or "auto").strip().lower()
    if configured in {"cpu", "cuda"}:
        return configured
    if torch is not None and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _compute_candidates(device: str, safe_mode: bool) -> List[str]:
    configured = (os.environ.get("WHISPER_COMPUTE_TYPE") or "auto").strip().lower()
    if configured and configured != "auto":
        if device == "cpu" and configured in {"float16", "int8_float16", "bfloat16"}:
            return ["int8"] if safe_mode else ["float32"]
        return [configured]
    if device == "cuda":
        return ["float16", "int8_float16", "int8"] if safe_mode else ["float16"]
    return ["int8"]


def _model_candidates(safe_mode: bool, device: str) -> List[str]:
    primary = (os.environ.get("WHISPER_MODEL") or "distil-large-v3").strip() or "distil-large-v3"
    cpu_primary = (os.environ.get("WHISPER_CPU_MODEL") or "").strip()
    cpu_auto_distil = _env_bool("WHISPER_CPU_AUTO_DISTIL", True)

    ordered_primary: List[str] = []
    if safe_mode and device == "cpu":
        if cpu_primary:
            ordered_primary.append(cpu_primary)
        elif cpu_auto_distil and "large-v3" in primary.lower() and "distil" not in primary.lower():
            ordered_primary.append("distil-large-v3")
        if ordered_primary and ordered_primary[0] != primary:
            print(
                "⚙️ Whisper CPU optimization: "
                f"prioritizing {ordered_primary[0]} before {primary}."
            )
    ordered_primary.append(primary)

    if not safe_mode:
        return [ordered_primary[-1]]
    fallbacks = _csv_env("WHISPER_MODEL_FALLBACKS", ["medium", "small", "base"])
    seen = set()
    ordered: List[str] = []
    for model in [*ordered_primary, *fallbacks]:
        if model in seen:
            continue
        seen.add(model)
        ordered.append(model)
    return ordered


def _estimated_vram_mb(model_name: str) -> int:
    lowered = model_name.lower()
    if "large-v3" in lowered:
        return 6200
    if "large" in lowered:
        return 5500
    if "medium" in lowered:
        return 2800
    if "small" in lowered:
        return 1600
    return 900


def _cuda_free_mb() -> int:
    if torch is None or not torch.cuda.is_available():
        return 0
    try:
        free_bytes, _ = torch.cuda.mem_get_info()
        return int(free_bytes / (1024 * 1024))
    except Exception:
        return 0


def _runtime_key(model_name: str, device: str, compute_type: str, cpu_threads: int, num_workers: int) -> Tuple[str, str, str, int, int]:
    return (model_name, device, compute_type, cpu_threads, num_workers)


def get_whisper_model() -> Tuple[WhisperModel, Dict[str, Any]]:
    safe_mode = _env_bool("WHISPER_SAFE_MODE", True)
    device = _resolve_device()
    configured_device = (os.environ.get("WHISPER_DEVICE") or "auto").strip().lower()
    cpu_threads = _env_int("WHISPER_CPU_THREADS", WHISPER_CPU_THREADS, minimum=1)
    num_workers = _env_int("WHISPER_NUM_WORKERS", 1, minimum=1)
    vram_margin_mb = _env_int("WHISPER_SAFE_VRAM_MARGIN_MB", 1800, minimum=0)

    attempts: List[Tuple[str, str, str]] = []
    models = _model_candidates(safe_mode, device)
    for model_name in models:
        if device == "cuda":
            for compute_type in _compute_candidates("cuda", safe_mode):
                attempts.append((model_name, "cuda", compute_type))
        if safe_mode or device == "cpu":
            for compute_type in _compute_candidates("cpu", safe_mode):
                attempts.append((model_name, "cpu", compute_type))

    errors: List[str] = []
    had_cuda_failure = False
    logged_cpu_fallback = False

    with _MODEL_LOCK:
        for model_name, attempt_device, compute_type in attempts:
            if (
                attempt_device == "cpu"
                and configured_device == "cuda"
                and had_cuda_failure
                and not logged_cpu_fallback
            ):
                print("⚠️ Whisper GPU unavailable/unstable. Falling back to CPU safe mode.")
                logged_cpu_fallback = True

            if attempt_device == "cuda" and safe_mode:
                free_mb = _cuda_free_mb()
                required_mb = _estimated_vram_mb(model_name) + vram_margin_mb
                if free_mb and free_mb < required_mb:
                    errors.append(
                        f"{model_name}/{attempt_device}/{compute_type}: skipped (free VRAM {free_mb}MB < required {required_mb}MB)"
                    )
                    had_cuda_failure = True
                    continue

            key = _runtime_key(model_name, attempt_device, compute_type, cpu_threads, num_workers)
            cached = _MODEL_CACHE.get(key)
            if cached:
                return cached, _MODEL_META[key]

            try:
                model = WhisperModel(
                    model_name,
                    device=attempt_device,
                    compute_type=compute_type,
                    cpu_threads=cpu_threads,
                    num_workers=num_workers,
                )
                meta = {
                    "model": model_name,
                    "device": attempt_device,
                    "compute_type": compute_type,
                    "safe_mode": safe_mode,
                    "cpu_threads": cpu_threads,
                    "num_workers": num_workers,
                }
                _MODEL_CACHE[key] = model
                _MODEL_META[key] = meta
                print(
                    "🎙️ Whisper runtime ready: "
                    f"model={model_name}, device={attempt_device}, compute={compute_type}, safe_mode={safe_mode}"
                )
                return model, meta
            except Exception as exc:
                errors.append(f"{model_name}/{attempt_device}/{compute_type}: {exc}")
                if attempt_device == "cuda":
                    had_cuda_failure = True

    raise RuntimeError("Failed to initialize Whisper model. Attempts: " + " | ".join(errors[-8:]))


def transcribe_with_runtime(audio_path: str, *, word_timestamps: bool = True):
    safe_mode = _env_bool("WHISPER_SAFE_MODE", True)
    beam_size = _env_int("WHISPER_BEAM_SIZE", 5, minimum=1)
    if safe_mode:
        beam_size = min(beam_size, 4)
    vad_filter = _env_bool("WHISPER_VAD_FILTER", safe_mode)

    requested_language = _normalize_language_code(os.environ.get("WHISPER_LANGUAGE"))
    hints = _language_hints()
    lang_retry_enabled = _env_bool("WHISPER_LANGUAGE_RETRY_ENABLED", True)
    lang_retry_max_probability = _env_float("WHISPER_LANGUAGE_RETRY_MAX_PROBABILITY", 0.92)

    model, runtime_meta = get_whisper_model()
    segments, info = _transcribe_once(
        model,
        audio_path,
        word_timestamps=word_timestamps,
        beam_size=beam_size,
        vad_filter=vad_filter,
        language=requested_language,
    )

    detected_language = _normalize_language_code(getattr(info, "language", ""))
    detected_probability = float(getattr(info, "language_probability", 0.0) or 0.0)

    if requested_language:
        if detected_language and detected_language != requested_language:
            print(
                "⚠️ Whisper language mismatch: "
                f"forced={requested_language}, detected={detected_language} ({detected_probability:.2f})."
            )
    elif hints and lang_retry_enabled:
        allowed = set(hints)
        if detected_language and detected_language not in allowed and detected_probability <= lang_retry_max_probability:
            retry_language = hints[0]
            print(
                "🔁 Whisper language retry: "
                f"detected={detected_language} ({detected_probability:.2f}), retrying with language={retry_language}."
            )
            retry_segments, retry_info = _transcribe_once(
                model,
                audio_path,
                word_timestamps=word_timestamps,
                beam_size=beam_size,
                vad_filter=vad_filter,
                language=retry_language,
            )
            segments = retry_segments
            info = retry_info
            requested_language = retry_language

    meta = dict(runtime_meta)
    meta["beam_size"] = beam_size
    meta["vad_filter"] = vad_filter
    meta["requested_language"] = requested_language or "auto"
    meta["language_hints"] = hints
    meta["language_retry_enabled"] = lang_retry_enabled
    meta["language_retry_max_probability"] = lang_retry_max_probability
    return segments, info, meta
