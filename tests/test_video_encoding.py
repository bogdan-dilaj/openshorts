import subprocess

import video_encoding


def test_nvenc_args_use_constant_quality_and_gpu_encoder(monkeypatch):
    monkeypatch.setenv("NVENC_PRESET", "p4")
    monkeypatch.setenv("NVENC_CQ", "20")

    args = video_encoding.h264_encoding_args(
        encoder="h264_nvenc",
        cpu_preset="fast",
        crf="18",
        maxrate="12M",
        bufsize="24M",
    )

    assert args[:2] == ["-c:v", "h264_nvenc"]
    assert args[args.index("-preset") + 1] == "p4"
    assert args[args.index("-cq") + 1] == "20"
    assert args[args.index("-maxrate") + 1] == "12M"
    assert "libx264" not in args


def test_x264_args_preserve_cpu_quality_settings():
    args = video_encoding.h264_encoding_args(
        encoder="libx264",
        cpu_preset="veryfast",
        crf="22",
    )

    assert args[:2] == ["-c:v", "libx264"]
    assert args[args.index("-preset") + 1] == "veryfast"
    assert args[args.index("-crf") + 1] == "22"


def test_ffmpeg_runner_retries_with_x264(monkeypatch):
    monkeypatch.setattr(video_encoding, "h264_encoder_candidates", lambda _preference=None: ["h264_nvenc", "libx264"])
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1 if "h264_nvenc" in command else 0,
            stderr=b"encoder unavailable" if "h264_nvenc" in command else b"",
        )

    monkeypatch.setattr(video_encoding.subprocess, "run", fake_run)

    result = video_encoding.run_h264_ffmpeg(
        lambda encoder_args, _encoder: ["ffmpeg", *encoder_args, "out.mp4"],
        run_kwargs={"stderr": subprocess.PIPE},
        label="test",
    )

    assert result.returncode == 0
    assert len(calls) == 2
    assert "h264_nvenc" in calls[0]
    assert "libx264" in calls[1]
