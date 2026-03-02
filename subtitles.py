import os
import subprocess
import tempfile

from overlay_styles import (
    DEFAULT_BACKGROUND_STYLE,
    DEFAULT_SUBTITLE_FONT,
    FONT_DIR,
    get_ass_font_name,
    get_background_preset,
    get_font_path,
)
from runtime_limits import FFMPEG_PRESET, WHISPER_CPU_THREADS, ffmpeg_thread_args, subprocess_priority_kwargs

OVERLAY_FFMPEG_PRESET = (os.environ.get("OVERLAY_FFMPEG_PRESET") or "veryfast").strip() or FFMPEG_PRESET

PLAY_RES_X = int(os.environ.get("TARGET_VERTICAL_WIDTH", "1080"))
PLAY_RES_Y = int(os.environ.get("TARGET_VERTICAL_HEIGHT", "1920"))

LEGACY_SUBTITLE_Y_POSITIONS = {
    "top": 14.0,
    "middle": 50.0,
    "bottom": 86.0,
}


def transcribe_audio(video_path):
    """
    Transcribe audio from a video file using faster-whisper.
    Returns transcript in the same format as main.py for compatibility.
    """
    from faster_whisper import WhisperModel

    print(f"🎙️  Transcribing audio from: {video_path}")

    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=WHISPER_CPU_THREADS, num_workers=1)
    segments, info = model.transcribe(video_path, word_timestamps=True)

    transcript = {
        "segments": [],
        "language": info.language,
    }

    for segment in segments:
        seg_data = {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": [],
        }
        if segment.words:
            for word in segment.words:
                seg_data["words"].append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                })
        transcript["segments"].append(seg_data)

    print(f"✅ Transcription complete. Language: {info.language}")
    return transcript


def build_subtitle_blocks(transcript, clip_start, clip_end, max_chars=20, max_duration=2.0):
    """Build time-coded subtitle blocks suitable for export."""
    words = []
    for segment in transcript.get("segments", []):
        for word_info in segment.get("words", []):
            if word_info["end"] > clip_start and word_info["start"] < clip_end:
                words.append(word_info)

    if not words:
        return []

    blocks = []
    current_block = []
    block_start = None

    for word in words:
        start = max(0, word["start"] - clip_start)
        end = max(0, word["end"] - clip_start)

        if not current_block:
            current_block.append(word)
            block_start = start
            continue

        current_text_len = sum(len(item["word"]) + 1 for item in current_block)
        duration = end - block_start

        if current_text_len + len(word["word"]) > max_chars or duration > max_duration:
            block_end = current_block[-1]["end"] - clip_start
            blocks.append({
                "start": block_start,
                "end": block_end,
                "text": " ".join(item["word"] for item in current_block).strip(),
            })
            current_block = [word]
            block_start = start
        else:
            current_block.append(word)

    if current_block:
        block_end = current_block[-1]["end"] - clip_start
        blocks.append({
            "start": block_start,
            "end": block_end,
            "text": " ".join(item["word"] for item in current_block).strip(),
        })

    return blocks


def _probe_video_dimensions(video_path):
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            video_path,
        ]
        res = subprocess.check_output(cmd).decode().strip()
        dims = res.split("\n")[0].split("x")
        return int(dims[0]), int(dims[1])
    except Exception as e:
        print(f"⚠️ FFprobe failed for subtitles: {e}. Assuming 1080x1920")
        return PLAY_RES_X, PLAY_RES_Y


def _clamp_percent(value, default):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _wrap_text_for_ass(text, max_chars=20):
    words = text.split()
    if not words:
        return text

    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_length = len(word)
        projected = current_length + word_length + (1 if current_line else 0)
        if current_line and projected > max_chars:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_length = word_length
        else:
            current_line.append(word)
            current_length = projected

    if current_line:
        lines.append(" ".join(current_line))

    return r"\N".join(lines)


def _rgba_to_ass_color(rgba):
    r, g, b, a = rgba
    alpha = 255 - a
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_timestamp(seconds):
    total_centiseconds = max(0, int(round(seconds * 100)))
    hours = total_centiseconds // 360000
    minutes = (total_centiseconds % 360000) // 6000
    secs = (total_centiseconds % 6000) // 100
    centis = total_centiseconds % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text):
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def _build_ass_content(
    blocks,
    video_width,
    video_height,
    alignment="bottom",
    y_position=None,
    fontsize=24,
    font_family=DEFAULT_SUBTITLE_FONT,
    background_style=DEFAULT_BACKGROUND_STYLE,
):
    style = get_background_preset(background_style)
    font_path = get_font_path(font_family)
    font_name = get_ass_font_name(font_family) if font_path else get_ass_font_name(DEFAULT_SUBTITLE_FONT)
    font_size = max(28, int(round(fontsize * (video_height / 900.0))))
    y_percent = _clamp_percent(y_position, LEGACY_SUBTITLE_Y_POSITIONS.get(alignment, LEGACY_SUBTITLE_Y_POSITIONS["bottom"]))
    y_pixels = int(round((y_percent / 100.0) * video_height))

    margin_l = int(video_width * 0.10)
    margin_r = int(video_width * 0.10)
    margin_v = max(24, int(video_height * 0.03))

    dialogue_lines = []
    for block in blocks:
        wrapped = _wrap_text_for_ass(_ass_escape(block["text"]))
        dialogue_lines.append(
            "Dialogue: 0,{start},{end},Subtitle,,0,0,0,,{{\\an5\\pos({x},{y})}}{text}".format(
                start=_ass_timestamp(block["start"]),
                end=_ass_timestamp(block["end"]),
                x=video_width // 2,
                y=y_pixels,
                text=wrapped,
            )
        )

    return "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_width}",
        f"PlayResY: {video_height}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Subtitle,{font_name},{font_size},{primary},{secondary},{outline},{back},"
        "-1,0,0,0,100,100,0,0,{border_style},{outline_width},{shadow},5,{margin_l},{margin_r},{margin_v},1".format(
            font_name=font_name,
            font_size=font_size,
            primary=_rgba_to_ass_color(style["subtitle_text"]),
            secondary=_rgba_to_ass_color(style["subtitle_text"]),
            outline=_rgba_to_ass_color(style.get("subtitle_border") or style.get("subtitle_shadow") or (0, 0, 0, 255)),
            back=_rgba_to_ass_color(style["subtitle_box"]),
            border_style=style.get("border_style", 3),
            outline_width=style.get("outline_width", 2),
            shadow=style.get("shadow", 0),
            margin_l=margin_l,
            margin_r=margin_r,
            margin_v=margin_v,
        ),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        *dialogue_lines,
        "",
    ])


def burn_subtitles(
    video_path,
    transcript,
    clip_start,
    clip_end,
    output_path,
    alignment="bottom",
    y_position=None,
    fontsize=24,
    font_family=DEFAULT_SUBTITLE_FONT,
    background_style=DEFAULT_BACKGROUND_STYLE,
    temp_dir="/tmp",
    max_chars=20,
    max_duration=2.0,
):
    """
    Burns subtitles via a single ASS subtitle track.
    This is much lighter than overlaying one PNG per subtitle block.
    """
    blocks = build_subtitle_blocks(transcript, clip_start, clip_end, max_chars=max_chars, max_duration=max_duration)
    if not blocks:
        return False

    video_width, video_height = _probe_video_dimensions(video_path)
    get_font_path(font_family)

    temp_handle = tempfile.NamedTemporaryFile(
        prefix="openshorts_subtitles_",
        suffix=".ass",
        dir=temp_dir if os.path.isdir(temp_dir) else "/tmp",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    ass_path = temp_handle.name

    try:
        temp_handle.write(
            _build_ass_content(
                blocks,
                video_width,
                video_height,
                alignment=alignment,
                y_position=y_position,
                fontsize=fontsize,
                font_family=font_family,
                background_style=background_style,
            )
        )
        temp_handle.close()

        filter_expr = f"ass={ass_path}:fontsdir={FONT_DIR}"
        cmd = [
            "ffmpeg", "-y",
            "-loglevel", "error",
            "-i", video_path,
            *ffmpeg_thread_args(include_filter_threads=True),
            "-vf", filter_expr,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v", "libx264", "-preset", OVERLAY_FFMPEG_PRESET, "-crf", "18",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

        print(f"🎬 Burning subtitles with ASS pipeline: {' '.join(cmd[:12])} ...")
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        if result.returncode != 0:
            error_text = result.stderr.decode()
            print(f"❌ FFmpeg Subtitle Error: {error_text}")
            raise Exception(f"FFmpeg failed: {error_text}")

        return True
    finally:
        if os.path.exists(ass_path):
            os.remove(ass_path)
