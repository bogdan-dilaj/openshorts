import hashlib
import glob
import os
import re
import shutil
import threading
import time
import ctypes
import gc
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

from runtime_limits import WHISPER_CPU_THREADS

try:
    import torch
except Exception:  # pragma: no cover - torch is available in runtime, keep fallback defensive
    torch = None


_MODEL_CACHE: Dict[Tuple[str, str, str, int, int], Any] = {}
_MODEL_META: Dict[Tuple[str, str, str, int, int], Dict[str, Any]] = {}
_MODEL_LOCK = threading.Lock()
_MODEL_RESOLUTION_CACHE: Dict[str, str] = {}
_MODEL_RESOLUTION_LOCK = threading.Lock()
_VALID_LANGUAGE_TOKEN = set("abcdefghijklmnopqrstuvwxyz-")
_FASTER_WHISPER_MODEL_CLASS = None
_CUDA_RUNTIME_READY: Optional[bool] = None
_CUDA_RUNTIME_LOCK = threading.Lock()
_LEGACY_MODEL_MAPPINGS = {
    "primeline/distil-whisper-large-v3-german": "primeline/whisper-large-v3-german",
}
_MODEL_SUPPORT_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "preprocessor_config.json",
    "generation_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "normalizer.json",
    "vocab.json",
    "merges.txt",
)


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


def _normalize_model_hint(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    return _LEGACY_MODEL_MAPPINGS.get(value, value)


def _is_english_biased_distil_model(model_name: Any) -> bool:
    lowered = str(model_name or "").strip().lower()
    if not lowered:
        return False
    if "german" in lowered or lowered.endswith(".de"):
        return False
    return "distil-large-v3" in lowered


def _get_whisper_model_class():
    global _FASTER_WHISPER_MODEL_CLASS
    if _FASTER_WHISPER_MODEL_CLASS is not None:
        return _FASTER_WHISPER_MODEL_CLASS
    from faster_whisper import WhisperModel as FasterWhisperModel
    _FASTER_WHISPER_MODEL_CLASS = FasterWhisperModel
    return _FASTER_WHISPER_MODEL_CLASS


def _is_memory_pressure_error(exc: Exception) -> bool:
    if isinstance(exc, MemoryError):
        return True
    text = str(exc or "").strip().lower()
    return any(
        needle in text
        for needle in (
            "std::bad_alloc",
            "bad_alloc",
            "cannot allocate memory",
            "out of memory",
            "insufficient memory",
        )
    )


def _release_cached_whisper_runtime(meta: Dict[str, Any]) -> None:
    key = _runtime_key(
        str(meta.get("resolved_model") or ""),
        str(meta.get("device") or ""),
        str(meta.get("compute_type") or ""),
        int(meta.get("cpu_threads") or 1),
        int(meta.get("num_workers") or 1),
    )
    model = _MODEL_CACHE.pop(key, None)
    _MODEL_META.pop(key, None)
    if model is not None:
        try:
            del model
        except Exception:
            pass
    gc.collect()
    if torch is not None and torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass


def _memory_retry_model_candidates(language_hint: str, attempted_models: List[str]) -> List[str]:
    attempted = {str(item or "").strip() for item in attempted_models if str(item or "").strip()}
    candidates: List[str] = []
    if _normalize_language_code(language_hint) == "de":
        candidates.extend([
            "primeline/whisper-large-v3-german",
            "large-v3",
            "medium",
            "small",
            "base",
        ])
    else:
        candidates.extend([
            "distil-large-v3",
            "medium",
            "small",
            "base",
        ])
    ordered: List[str] = []
    for item in candidates:
        normalized = str(item or "").strip()
        if not normalized or normalized in attempted or normalized in ordered:
            continue
        ordered.append(normalized)
    return ordered


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
    model: Any,
    audio_path: str,
    *,
    word_timestamps: bool,
    beam_size: int,
    vad_filter: bool,
    language: str = "",
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
):
    kwargs = {
        "task": "transcribe",
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
            if progress_cb is not None:
                try:
                    progress_cb(
                        {
                            "status": "decoding",
                            "segments": idx,
                            "audio_seconds": seg_end,
                            "audio_label": f"{minutes:02d}:{seconds:02d}",
                        }
                    )
                except Exception:
                    pass
            last_progress_log = now

    if segments:
        minutes = int(last_audio_second // 60)
        seconds = int(last_audio_second % 60)
        print(
            "✅ Whisper decoding finished. "
            f"segments={len(segments)}, audio={minutes:02d}:{seconds:02d}"
        )
        if progress_cb is not None:
            try:
                progress_cb(
                    {
                        "status": "completed",
                        "segments": len(segments),
                        "audio_seconds": last_audio_second,
                        "audio_label": f"{minutes:02d}:{seconds:02d}",
                    }
                )
            except Exception:
                pass
    else:
        print("⚠️ Whisper decoding finished with no segments.")
        if progress_cb is not None:
            try:
                progress_cb(
                    {
                        "status": "completed",
                        "segments": 0,
                        "audio_seconds": 0.0,
                        "audio_label": "00:00",
                    }
                )
            except Exception:
                pass

    return segments, info


def _resolve_device() -> str:
    configured = (os.environ.get("WHISPER_DEVICE") or "auto").strip().lower()
    if configured in {"cpu", "cuda"}:
        if configured == "cuda" and not _cuda_runtime_libraries_available():
            print("⚠️ Whisper CUDA requested, but libcublas.so.12 is unavailable. Falling back to CPU.")
            return "cpu"
        return configured
    if torch is not None and torch.cuda.is_available() and _cuda_runtime_libraries_available():
        return "cuda"
    return "cpu"


def _candidate_cuda_library_dirs() -> List[str]:
    candidates: List[str] = []
    patterns = [
        "/opt/venv/lib/python*/site-packages/nvidia/*/lib",
        "/opt/venv/lib64/python*/site-packages/nvidia/*/lib",
        "/usr/local/lib/openshorts-nvidia",
        "/usr/local/nvidia/lib64",
        "/usr/local/nvidia/lib",
    ]
    for pattern in patterns:
        if "*" in pattern or "?" in pattern or "[" in pattern:
            matches = glob.glob(pattern)
        else:
            matches = [pattern]
        for path in matches:
            normalized = str(path or "").strip()
            if not normalized or not os.path.isdir(normalized):
                continue
            if normalized not in candidates:
                candidates.append(normalized)
    return candidates


def _load_cuda_runtime_libraries() -> bool:
    required_by_priority = [
        "libcudart.so.12",
        "libnvrtc.so.12",
        "libcublasLt.so.12",
        "libcublas.so.12",
        "libcudnn.so.9",
    ]
    optional = [
        "libcufft.so.11",
        "libcurand.so.10",
        "libcusolver.so.11",
        "libcusparse.so.12",
        "libnccl.so.2",
        "libnvJitLink.so.12",
    ]
    library_dirs = _candidate_cuda_library_dirs()
    if not library_dirs:
        return False
    loaded_any = False
    for name in [*required_by_priority, *optional]:
        loaded = False
        for directory in library_dirs:
            candidate = os.path.join(directory, name)
            if not os.path.exists(candidate):
                continue
            try:
                ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
                loaded = True
                loaded_any = True
                break
            except OSError:
                continue
        if name in required_by_priority and not loaded:
            return False
    return loaded_any


def _cuda_runtime_libraries_available() -> bool:
    global _CUDA_RUNTIME_READY
    if torch is None or not torch.cuda.is_available():
        return False
    with _CUDA_RUNTIME_LOCK:
        if _CUDA_RUNTIME_READY is True:
            return True
        try:
            ctypes.CDLL("libcublas.so.12")
            _CUDA_RUNTIME_READY = True
            return True
        except OSError:
            pass
        try:
            if _load_cuda_runtime_libraries():
                ctypes.CDLL("libcublas.so.12")
                _CUDA_RUNTIME_READY = True
                return True
        except OSError:
            pass
        _CUDA_RUNTIME_READY = False
        return False


def _compute_candidates(device: str, safe_mode: bool) -> List[str]:
    configured = (os.environ.get("WHISPER_COMPUTE_TYPE") or "auto").strip().lower()
    if configured and configured != "auto":
        if device == "cpu" and configured in {"float16", "int8_float16", "bfloat16"}:
            return ["int8"] if safe_mode else ["float32"]
        if device == "cuda" and safe_mode:
            preferred_order = ["float16", "int8_float16", "int8"]
            if configured in preferred_order:
                return [configured, *[item for item in preferred_order if item != configured]]
        return [configured]
    if device == "cuda":
        return ["float16", "int8_float16", "int8"] if safe_mode else ["float16"]
    return ["int8"]


def _model_candidates(
    safe_mode: bool,
    device: str,
    *,
    log_cpu_optimization: bool = True,
    primary_override: str = "",
    cpu_primary_override: str = "",
    language_hint: str = "",
) -> List[str]:
    primary = (primary_override or os.environ.get("WHISPER_MODEL") or "distil-large-v3").strip() or "distil-large-v3"
    cpu_primary = (cpu_primary_override or os.environ.get("WHISPER_CPU_MODEL") or "").strip()
    cpu_auto_distil = _env_bool("WHISPER_CPU_AUTO_DISTIL", True)
    normalized_language_hint = _normalize_language_code(language_hint)
    non_english_requested = bool(normalized_language_hint and normalized_language_hint != "en")

    ordered_primary: List[str] = []
    if safe_mode and device == "cpu":
        if cpu_primary:
            ordered_primary.append(cpu_primary)
        elif (
            cpu_auto_distil
            and not non_english_requested
            and "large-v3" in primary.lower()
            and "distil" not in primary.lower()
        ):
            ordered_primary.append("distil-large-v3")
        if log_cpu_optimization and ordered_primary and ordered_primary[0] != primary:
            print(
                "⚙️ Whisper CPU optimization: "
                f"prioritizing {ordered_primary[0]} before {primary}."
            )
    ordered_primary.append(primary)

    if not safe_mode:
        return [ordered_primary[-1]]
    if device == "cuda":
        fallbacks = _csv_env("WHISPER_CUDA_MODEL_FALLBACKS", ["distil-large-v3", "medium", "small", "base"])
    else:
        fallbacks = _csv_env("WHISPER_MODEL_FALLBACKS", ["medium", "small", "base"])
    seen = set()
    ordered: List[str] = []
    for model in [*ordered_primary, *fallbacks]:
        if non_english_requested and _is_english_biased_distil_model(model):
            print(
                "⚠️ Whisper model candidate ignored for non-English transcription: "
                f"{model} (language={normalized_language_hint})"
            )
            continue
        if model in seen:
            continue
        seen.add(model)
        ordered.append(model)
    return ordered


def _estimated_vram_mb(model_name: str) -> int:
    lowered = model_name.lower()
    if "distil-large-v3" in lowered:
        return 2600
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


def _is_remote_hf_model_name(model_name: str) -> bool:
    model_name = (model_name or "").strip()
    if not model_name:
        return False
    if os.path.exists(model_name):
        return False
    # whisper built-in aliases like large-v3, distil-large-v3, ...
    if "/" not in model_name:
        return False
    return True


def _slugify_model_name(model_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", model_name).strip("._-")
    return slug or "model"


def _hf_convert_enabled() -> bool:
    value = (os.environ.get("WHISPER_HF_CONVERT_ENABLED") or "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _sync_model_support_files(source_dir: str, target_dir: str) -> List[str]:
    """Copy feature-extractor/tokenizer metadata missing from some CT2 conversions."""
    copied: List[str] = []
    os.makedirs(target_dir, exist_ok=True)
    for file_name in _MODEL_SUPPORT_FILES:
        source_path = os.path.join(source_dir, file_name)
        if not os.path.isfile(source_path):
            continue

        target_path = os.path.join(target_dir, file_name)
        try:
            if os.path.isfile(target_path) and os.path.getsize(target_path) == os.path.getsize(source_path):
                continue
        except OSError:
            pass

        temp_path = f"{target_path}.tmp-{os.getpid()}-{threading.get_ident()}"
        try:
            shutil.copyfile(source_path, temp_path)
            os.replace(temp_path, target_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        copied.append(file_name)
    return copied


def _resolve_model_reference(model_name: str) -> str:
    normalized = (model_name or "").strip()
    if not normalized:
        return normalized

    with _MODEL_RESOLUTION_LOCK:
        cached = _MODEL_RESOLUTION_CACHE.get(normalized)
        if cached:
            return cached

    if not _is_remote_hf_model_name(normalized):
        with _MODEL_RESOLUTION_LOCK:
            _MODEL_RESOLUTION_CACHE[normalized] = normalized
        return normalized

    if not _hf_convert_enabled():
        with _MODEL_RESOLUTION_LOCK:
            _MODEL_RESOLUTION_CACHE[normalized] = normalized
        return normalized

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        raise RuntimeError(f"huggingface_hub unavailable for model '{normalized}': {exc}") from exc

    try:
        snapshot_dir = snapshot_download(
            repo_id=normalized,
            resume_download=True,
        )
    except Exception as exc:
        raise RuntimeError(f"failed to download model '{normalized}' from Hugging Face: {exc}") from exc

    if os.path.isfile(os.path.join(snapshot_dir, "model.bin")):
        with _MODEL_RESOLUTION_LOCK:
            _MODEL_RESOLUTION_CACHE[normalized] = snapshot_dir
        return snapshot_dir

    cache_root = (
        os.environ.get("WHISPER_HF_CONVERT_CACHE_DIR")
        or "/app/output/.cache/whisper_ct2"
    ).strip() or "/app/output/.cache/whisper_ct2"
    os.makedirs(cache_root, exist_ok=True)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    target_dir = os.path.join(cache_root, f"{_slugify_model_name(normalized)}-{digest}")

    if os.path.isfile(os.path.join(target_dir, "model.bin")):
        copied_files = _sync_model_support_files(snapshot_dir, target_dir)
        if copied_files:
            print(
                "Whisper converted-model metadata repaired: "
                + ", ".join(copied_files)
            )
        with _MODEL_RESOLUTION_LOCK:
            _MODEL_RESOLUTION_CACHE[normalized] = target_dir
        return target_dir

    copy_files = [
        file_name
        for file_name in _MODEL_SUPPORT_FILES
        if os.path.isfile(os.path.join(snapshot_dir, file_name))
    ]

    quantization = (os.environ.get("WHISPER_HF_CONVERT_QUANTIZATION") or "").strip() or None

    try:
        from ctranslate2.converters import TransformersConverter
    except Exception as exc:
        raise RuntimeError(
            "ctranslate2 TransformersConverter unavailable; install transformers/sentencepiece dependencies"
        ) from exc

    print(
        "🔧 Converting HuggingFace Whisper model for faster-whisper (one-time): "
        f"{normalized} -> {target_dir}"
    )

    converter = TransformersConverter(
        model_name_or_path=snapshot_dir,
        copy_files=copy_files or None,
        low_cpu_mem_usage=True,
    )
    converter.convert(
        output_dir=target_dir,
        quantization=quantization,
        force=False,
    )

    if not os.path.isfile(os.path.join(target_dir, "model.bin")):
        raise RuntimeError(
            f"conversion finished but model.bin missing for '{normalized}' at {target_dir}"
        )

    copied_files = _sync_model_support_files(snapshot_dir, target_dir)
    if copied_files:
        print(
            "Whisper converted-model metadata copied: "
            + ", ".join(copied_files)
        )

    with _MODEL_RESOLUTION_LOCK:
        _MODEL_RESOLUTION_CACHE[normalized] = target_dir
    return target_dir


def get_whisper_model(
    language_hint: str = "",
    *,
    model_override: str = "",
    cpu_model_override: str = "",
) -> Tuple[Any, Dict[str, Any]]:
    safe_mode = _env_bool("WHISPER_SAFE_MODE", True)
    device = _resolve_device()
    configured_device = (os.environ.get("WHISPER_DEVICE") or "auto").strip().lower()
    cpu_threads = _env_int("WHISPER_CPU_THREADS", WHISPER_CPU_THREADS, minimum=1)
    num_workers = _env_int("WHISPER_NUM_WORKERS", 1, minimum=1)
    vram_margin_mb = _env_int("WHISPER_SAFE_VRAM_MARGIN_MB", 512, minimum=0)
    normalized_language_hint = _normalize_language_code(language_hint)

    non_english_requested = bool(normalized_language_hint and normalized_language_hint != "en")
    primary_override = _normalize_model_hint(model_override)
    cpu_primary_override = _normalize_model_hint(cpu_model_override)
    if primary_override:
        print(
            "🗣️ Whisper explicit model override: "
            f"language={normalized_language_hint or 'auto'}, target_model={primary_override}"
        )
    elif non_english_requested:
        configured_primary = _normalize_model_hint(os.environ.get("WHISPER_MODEL"))
        configured_de = _normalize_model_hint(os.environ.get("WHISPER_MODEL_DE"))
        configured_non_en = _normalize_model_hint(os.environ.get("WHISPER_MODEL_NON_EN"))
        configured_cpu_de = _normalize_model_hint(os.environ.get("WHISPER_CPU_MODEL_DE"))
        configured_cpu_non_en = _normalize_model_hint(os.environ.get("WHISPER_CPU_MODEL_NON_EN"))

        if normalized_language_hint == "de" and configured_de:
            primary_override = configured_de
        elif configured_non_en:
            primary_override = configured_non_en
        elif "distil-large-v3" in configured_primary.lower():
            primary_override = "large-v3"

        if device == "cpu":
            if normalized_language_hint == "de" and configured_cpu_de:
                cpu_primary_override = configured_cpu_de
            elif configured_cpu_non_en:
                cpu_primary_override = configured_cpu_non_en
            elif not primary_override:
                cpu_primary_override = "medium"

        target_model_log = primary_override or configured_primary or "distil-large-v3"
        if target_model_log:
            print(
                "🗣️ Whisper language-aware model routing: "
                f"language={normalized_language_hint}, target_model={target_model_log}"
            )

    attempts: List[Tuple[str, str, str]] = []
    cuda_models = _model_candidates(
        safe_mode,
        "cuda",
        primary_override=primary_override,
        cpu_primary_override=cpu_primary_override,
        language_hint=normalized_language_hint,
    )
    cpu_models = _model_candidates(
        safe_mode,
        "cpu",
        log_cpu_optimization=(device == "cpu"),
        primary_override=primary_override,
        cpu_primary_override=cpu_primary_override,
        language_hint=normalized_language_hint,
    )
    seen_attempts = set()

    if device == "cuda":
        for model_name in cuda_models:
            for compute_type in _compute_candidates("cuda", safe_mode):
                attempt = (model_name, "cuda", compute_type)
                if attempt in seen_attempts:
                    continue
                seen_attempts.add(attempt)
                attempts.append(attempt)
        if safe_mode:
            for model_name in cpu_models:
                for compute_type in _compute_candidates("cpu", safe_mode):
                    attempt = (model_name, "cpu", compute_type)
                    if attempt in seen_attempts:
                        continue
                    seen_attempts.add(attempt)
                    attempts.append(attempt)
    else:
        for model_name in cpu_models:
            for compute_type in _compute_candidates("cpu", safe_mode):
                attempt = (model_name, "cpu", compute_type)
                if attempt in seen_attempts:
                    continue
                seen_attempts.add(attempt)
                attempts.append(attempt)

    errors: List[str] = []
    had_cuda_failure = False
    logged_cpu_fallback = False
    last_cuda_failure_detail = ""

    with _MODEL_LOCK:
        for model_name, attempt_device, compute_type in attempts:
            if (
                attempt_device == "cpu"
                and configured_device == "cuda"
                and had_cuda_failure
                and not logged_cpu_fallback
            ):
                detail = f" Reason: {last_cuda_failure_detail}" if last_cuda_failure_detail else ""
                print(f"⚠️ Whisper GPU unavailable/unstable. Falling back to CPU safe mode.{detail}")
                logged_cpu_fallback = True

            if attempt_device == "cuda" and safe_mode:
                free_mb = _cuda_free_mb()
                required_mb = _estimated_vram_mb(model_name) + vram_margin_mb
                if free_mb and free_mb < required_mb:
                    message = f"free VRAM {free_mb}MB < required {required_mb}MB"
                    print(f"⚠️ Whisper CUDA candidate skipped: {model_name}/{compute_type} ({message})")
                    errors.append(f"{model_name}/{attempt_device}/{compute_type}: skipped ({message})")
                    last_cuda_failure_detail = f"{model_name}/{compute_type} skipped because {message}"
                    had_cuda_failure = True
                    continue

            try:
                resolved_model_name = _resolve_model_reference(model_name)
            except Exception as exc:
                errors.append(f"{model_name}/{attempt_device}/{compute_type}: model resolve failed ({exc})")
                if attempt_device == "cuda":
                    last_cuda_failure_detail = f"{model_name}/{compute_type} resolve failed: {exc}"
                    had_cuda_failure = True
                continue

            key = _runtime_key(resolved_model_name, attempt_device, compute_type, cpu_threads, num_workers)
            cached = _MODEL_CACHE.get(key)
            if cached:
                return cached, _MODEL_META[key]

            try:
                WhisperModel = _get_whisper_model_class()
                model = WhisperModel(
                    resolved_model_name,
                    device=attempt_device,
                    compute_type=compute_type,
                    cpu_threads=cpu_threads,
                    num_workers=num_workers,
                )
                meta = {
                    "model": model_name,
                    "resolved_model": resolved_model_name,
                    "device": attempt_device,
                    "compute_type": compute_type,
                    "safe_mode": safe_mode,
                    "cpu_threads": cpu_threads,
                    "num_workers": num_workers,
                }
                _MODEL_CACHE[key] = model
                _MODEL_META[key] = meta
                model_display = model_name
                if resolved_model_name != model_name:
                    model_display = f"{model_name} ({resolved_model_name})"
                print(
                    "🎙️ Faster-Whisper runtime ready: "
                    f"model={model_display}, device={attempt_device}, compute={compute_type}, safe_mode={safe_mode}"
                )
                return model, meta
            except Exception as exc:
                errors.append(f"{model_name}/{attempt_device}/{compute_type}: {exc}")
                if attempt_device == "cuda":
                    last_cuda_failure_detail = f"{model_name}/{compute_type} failed: {exc}"
                    had_cuda_failure = True

    raise RuntimeError("Failed to initialize Whisper model. Attempts: " + " | ".join(errors[-8:]))


def transcribe_with_runtime(
    audio_path: str,
    *,
    word_timestamps: bool = True,
    language: Any = None,
    model_override: Any = None,
    cpu_model_override: Any = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
):
    safe_mode = _env_bool("WHISPER_SAFE_MODE", True)
    beam_size = _env_int("WHISPER_BEAM_SIZE", 5, minimum=1)
    if safe_mode:
        beam_size = min(beam_size, 4)
    vad_filter = _env_bool("WHISPER_VAD_FILTER", safe_mode)

    requested_language = _normalize_language_code(language)
    if not requested_language:
        requested_language = _normalize_language_code(os.environ.get("WHISPER_LANGUAGE") or "de")
    hints = _language_hints()
    lang_retry_enabled = _env_bool("WHISPER_LANGUAGE_RETRY_ENABLED", True)
    lang_retry_max_probability = _env_float("WHISPER_LANGUAGE_RETRY_MAX_PROBABILITY", 0.92)

    explicit_model_override = str(model_override).strip() if model_override else ""
    explicit_cpu_model_override = str(cpu_model_override).strip() if cpu_model_override else ""
    attempted_models: List[str] = []
    active_word_timestamps = bool(word_timestamps)
    word_timestamp_fallback_used = not active_word_timestamps
    retry_candidates = _memory_retry_model_candidates(
        requested_language,
        [explicit_model_override, explicit_cpu_model_override],
    )

    while True:
        model, runtime_meta = get_whisper_model(
            requested_language,
            model_override=explicit_model_override,
            cpu_model_override=explicit_cpu_model_override,
        )
        if progress_cb is not None:
            try:
                progress_cb(
                    {
                        "status": "runtime_ready",
                        "device": runtime_meta.get("device"),
                        "model": runtime_meta.get("resolved_model") or runtime_meta.get("model"),
                        "compute_type": runtime_meta.get("compute_type"),
                        "word_timestamps": active_word_timestamps,
                    }
                )
            except Exception:
                pass
        try:
            segments, info = _transcribe_once(
                model,
                audio_path,
                word_timestamps=active_word_timestamps,
                beam_size=beam_size,
                vad_filter=vad_filter,
                language=requested_language,
                progress_cb=progress_cb,
            )
            break
        except Exception as exc:
            if not _is_memory_pressure_error(exc):
                raise
            attempted_models.append(str(runtime_meta.get("model") or ""))
            _release_cached_whisper_runtime(runtime_meta)
            next_model = ""
            while retry_candidates and not next_model:
                candidate = retry_candidates.pop(0)
                if candidate and candidate not in attempted_models:
                    next_model = candidate
            if not next_model:
                if active_word_timestamps and not word_timestamp_fallback_used:
                    active_word_timestamps = False
                    word_timestamp_fallback_used = True
                    retry_candidates = _memory_retry_model_candidates(
                        requested_language,
                        attempted_models,
                    )
                    print(
                        "⚠️ Whisper memory pressure detected "
                        f"({exc}). Retrying without word timestamps."
                    )
                    if progress_cb is not None:
                        try:
                            progress_cb(
                                {
                                    "status": "retry",
                                    "reason": str(exc),
                                    "retry_mode": "word_timestamps_disabled",
                                    "word_timestamps": False,
                                }
                            )
                        except Exception:
                            pass
                    continue
                raise RuntimeError(
                    "Whisper memory retry exhausted. Last error: "
                    f"{exc}"
                ) from exc
            print(
                "⚠️ Whisper memory pressure detected "
                f"({exc}). Retrying with smaller model: {next_model}"
                + ("" if active_word_timestamps else " (word timestamps disabled)")
            )
            if progress_cb is not None:
                try:
                    progress_cb(
                        {
                            "status": "retry",
                            "reason": str(exc),
                            "retry_mode": "smaller_model",
                            "next_model": next_model,
                            "word_timestamps": active_word_timestamps,
                        }
                    )
                except Exception:
                    pass
            explicit_model_override = next_model
            explicit_cpu_model_override = next_model

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
                word_timestamps=active_word_timestamps,
                beam_size=beam_size,
                vad_filter=vad_filter,
                language=retry_language,
                progress_cb=progress_cb,
            )
            segments = retry_segments
            info = retry_info
            requested_language = retry_language

    meta = dict(runtime_meta)
    meta["beam_size"] = beam_size
    meta["vad_filter"] = vad_filter
    meta["word_timestamps"] = active_word_timestamps
    meta["requested_language"] = requested_language or "auto"
    meta["language_hints"] = hints
    meta["language_retry_enabled"] = lang_retry_enabled
    meta["language_retry_max_probability"] = lang_retry_max_probability
    return segments, info, meta
