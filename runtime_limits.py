import os


def _cpu_count() -> int:
    return os.cpu_count() or 4


def _env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


CPU_COUNT = _cpu_count()
MAX_CONCURRENT_JOBS = _env_int("MAX_CONCURRENT_JOBS", 1, minimum=1, maximum=max(1, CPU_COUNT))
JOB_NICE_LEVEL = _env_int("JOB_NICE_LEVEL", 10, minimum=0, maximum=19)
FFMPEG_THREADS = _env_int("FFMPEG_THREADS", min(2, CPU_COUNT), minimum=1, maximum=max(1, CPU_COUNT))
FFMPEG_FILTER_THREADS = _env_int(
    "FFMPEG_FILTER_THREADS",
    1,
    minimum=1,
    maximum=max(1, min(FFMPEG_THREADS, CPU_COUNT)),
)
FFMPEG_PRESET = (os.environ.get("FFMPEG_PRESET") or "fast").strip()
WHISPER_CPU_THREADS = _env_int("WHISPER_CPU_THREADS", min(4, CPU_COUNT), minimum=1, maximum=max(1, CPU_COUNT))


def apply_process_niceness() -> None:
    if os.name != "posix":
        return
    try:
        os.nice(JOB_NICE_LEVEL)
    except Exception:
        pass


def subprocess_priority_kwargs() -> dict:
    if os.name == "posix":
        return {"preexec_fn": apply_process_niceness}
    return {}


def ffmpeg_thread_args(include_filter_threads: bool = False) -> list[str]:
    args: list[str] = []
    if include_filter_threads:
        args.extend([
            "-filter_threads", str(FFMPEG_FILTER_THREADS),
            "-filter_complex_threads", str(FFMPEG_FILTER_THREADS),
        ])
    args.extend(["-threads", str(FFMPEG_THREADS)])
    return args
