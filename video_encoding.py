import os
import subprocess
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Sequence, Tuple


def _normalized_encoder_preference(value: Optional[str] = None) -> str:
    configured = str(
        value
        or os.environ.get("SHORTFORM_VIDEO_ENCODER")
        or os.environ.get("VIDEO_ENCODER")
        or "auto"
    ).strip().lower()
    aliases = {
        "gpu": "h264_nvenc",
        "nvenc": "h264_nvenc",
        "nvidia": "h264_nvenc",
        "cpu": "libx264",
        "x264": "libx264",
    }
    normalized = aliases.get(configured, configured)
    return normalized if normalized in {"auto", "h264_nvenc", "libx264"} else "auto"


@lru_cache(maxsize=1)
def _nvenc_preflight() -> bool:
    """Verify that NVENC is usable, not merely compiled into FFmpeg."""
    if str(os.environ.get("NVIDIA_VISIBLE_DEVICES") or "").strip().lower() in {"none", "void"}:
        return False

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=size=256x256:rate=1",
        "-frames:v",
        "1",
        "-an",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p1",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def h264_encoder_candidates(preference: Optional[str] = None) -> List[str]:
    preferred = _normalized_encoder_preference(preference)
    if preferred == "libx264":
        return ["libx264"]
    if _nvenc_preflight():
        return ["h264_nvenc", "libx264"]
    return ["libx264"]


def selected_h264_encoder(preference: Optional[str] = None) -> str:
    return h264_encoder_candidates(preference)[0]


def h264_encoding_args(
    *,
    encoder: str,
    cpu_preset: str = "fast",
    crf: str = "18",
    maxrate: Optional[str] = None,
    bufsize: Optional[str] = None,
    profile: Optional[str] = None,
    level: Optional[str] = None,
    pixel_format: Optional[str] = "yuv420p",
) -> List[str]:
    if encoder == "h264_nvenc":
        nvenc_preset = str(os.environ.get("NVENC_PRESET") or "p4").strip() or "p4"
        nvenc_cq = str(os.environ.get("NVENC_CQ") or crf or "19").strip() or "19"
        args = [
            "-c:v",
            "h264_nvenc",
            "-preset",
            nvenc_preset,
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            nvenc_cq,
            "-b:v",
            "0",
            "-spatial_aq",
            "1",
            "-temporal_aq",
            "1",
        ]
    else:
        args = [
            "-c:v",
            "libx264",
            "-preset",
            str(cpu_preset or "fast"),
            "-crf",
            str(crf or "18"),
        ]

    if maxrate:
        args.extend(["-maxrate", str(maxrate)])
    if bufsize:
        args.extend(["-bufsize", str(bufsize)])
    if profile:
        args.extend(["-profile:v", str(profile)])
    if level:
        args.extend(["-level", str(level)])
    if pixel_format:
        args.extend(["-pix_fmt", str(pixel_format)])
    return args


def selected_h264_encoding_args(
    *,
    preference: Optional[str] = None,
    **kwargs,
) -> Tuple[str, List[str]]:
    encoder = selected_h264_encoder(preference)
    return encoder, h264_encoding_args(encoder=encoder, **kwargs)


def run_h264_ffmpeg(
    command_builder: Callable[[Sequence[str], str], Sequence[str]],
    *,
    preference: Optional[str] = None,
    cpu_preset: str = "fast",
    crf: str = "18",
    maxrate: Optional[str] = None,
    bufsize: Optional[str] = None,
    profile: Optional[str] = None,
    level: Optional[str] = None,
    pixel_format: Optional[str] = "yuv420p",
    run_kwargs: Optional[Dict] = None,
    label: str = "video",
) -> subprocess.CompletedProcess:
    """Run an FFmpeg encode and retry once with x264 after an NVENC failure."""
    kwargs = dict(run_kwargs or {})
    kwargs.pop("check", None)
    last_result: Optional[subprocess.CompletedProcess] = None

    for encoder in h264_encoder_candidates(preference):
        encoder_args = h264_encoding_args(
            encoder=encoder,
            cpu_preset=cpu_preset,
            crf=crf,
            maxrate=maxrate,
            bufsize=bufsize,
            profile=profile,
            level=level,
            pixel_format=pixel_format,
        )
        command = list(command_builder(encoder_args, encoder))
        result = subprocess.run(command, **kwargs)
        last_result = result
        if result.returncode == 0:
            print(f"Video encoder ({label}): {encoder}")
            return result
        if encoder == "h264_nvenc":
            stderr = getattr(result, "stderr", b"") or b""
            if isinstance(stderr, bytes):
                detail = stderr.decode("utf-8", errors="replace")
            else:
                detail = str(stderr)
            print(f"NVENC failed for {label}; retrying with libx264: {detail[-600:]}")

    if last_result is None:
        raise RuntimeError("No H.264 encoder candidate was available")
    raise subprocess.CalledProcessError(
        last_result.returncode,
        last_result.args,
        output=getattr(last_result, "stdout", None),
        stderr=getattr(last_result, "stderr", None),
    )
