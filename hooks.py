import os
import subprocess
import tempfile
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from overlay_styles import (
    DEFAULT_BACKGROUND_STYLE,
    DEFAULT_HOOK_FONT,
    get_background_preset,
    get_font_path,
)
from runtime_limits import FFMPEG_PRESET, ffmpeg_thread_args, subprocess_priority_kwargs

OVERLAY_FFMPEG_PRESET = (os.environ.get("OVERLAY_FFMPEG_PRESET") or "veryfast").strip() or FFMPEG_PRESET

WIDTH_PRESETS = {
    "full": 0.96,
    "wide": 0.82,
    "medium": 0.64,
    "narrow": 0.48,
}

SIZE_PRESETS = {
    "S": 44,
    "M": 56,
    "L": 76,
}

LEGACY_X_POSITIONS = {
    "left": 18.0,
    "center": 50.0,
    "right": 82.0,
}

LEGACY_Y_POSITIONS = {
    "top": 12.0,
    "center": 50.0,
    "bottom": 88.0,
}


def _load_font(font_name, font_size):
    font_path = get_font_path(font_name)
    try:
        if not font_path:
            raise FileNotFoundError("Font file unavailable")
        return ImageFont.truetype(font_path, font_size)
    except Exception as e:
        print(f"⚠️ Warning: Could not load font {font_name}, using default. Error: {e}")
        return ImageFont.load_default()


def _wrap_text(text, font, max_text_width):
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    paragraphs = text.split('\n')
    lines = []

    for paragraph in paragraphs:
        if not paragraph.strip():
            lines.append("")
            continue

        words = paragraph.split()
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            if width <= max_text_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []

        if current_line:
            lines.append(' '.join(current_line))

    return lines


def _clamp_percent(value, default):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _normalize_align(value):
    if value in {"left", "center", "right"}:
        return value
    return "center"


def create_hook_image(
    text,
    video_width,
    video_height,
    output_image_path="hook_overlay.png",
    position="top",
    horizontal_position="center",
    x_position=None,
    y_position=None,
    text_align="center",
    font_scale=1.0,
    width_preset="wide",
    font_name=DEFAULT_HOOK_FONT,
    background_style=DEFAULT_BACKGROUND_STYLE,
):
    """
    Generates a full-frame transparent overlay whose hook layout matches the UI preview closely.
    """
    style = get_background_preset(background_style)

    target_ratio = WIDTH_PRESETS.get(width_preset, WIDTH_PRESETS["wide"])
    box_width = int(video_width * target_ratio)
    box_width = max(int(video_width * 0.32), min(box_width, int(video_width * 0.96)))

    base_font_size = SIZE_PRESETS.get("M")
    if font_scale <= 0.85:
        base_font_size = SIZE_PRESETS["S"]
    elif font_scale >= 1.2:
        base_font_size = SIZE_PRESETS["L"]

    font_size = max(28, int((video_width / 1080.0) * base_font_size * font_scale))
    font = _load_font(font_name, font_size)

    padding_x = max(24, int(font_size * 0.75))
    padding_y = max(18, int(font_size * 0.52))
    line_spacing = max(10, int(font_size * 0.28))
    corner_radius = max(18, int(font_size * 0.45))
    shadow_offset = max(4, int(font_size * 0.12))
    shadow_blur = max(8, int(font_size * 0.22))
    side_margin = int(video_width * 0.04)

    max_text_width = max(120, box_width - (2 * padding_x))
    lines = _wrap_text(text, font, max_text_width)

    probe = Image.new('RGBA', (1, 1))
    probe_draw = ImageDraw.Draw(probe)
    line_metrics = []
    max_line_width = 0
    total_text_height = 0
    for line in lines:
        if not line:
            line_height = font_size
            line_width = 0
        else:
            bbox = probe_draw.textbbox((0, 0), line, font=font, stroke_width=style.get("hook_stroke_width", 0))
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]
        line_metrics.append((line, line_width, line_height))
        max_line_width = max(max_line_width, line_width)
        total_text_height += line_height

    if line_metrics:
        total_text_height += line_spacing * (len(line_metrics) - 1)

    content_width = max(max_line_width, int(box_width * 0.3))
    final_box_width = max(content_width + (2 * padding_x), int(box_width * 0.46))
    final_box_width = min(final_box_width, video_width - (2 * side_margin))
    box_height = total_text_height + (2 * padding_y)

    x_position = _clamp_percent(x_position, LEGACY_X_POSITIONS.get(horizontal_position, 50.0))
    y_position = _clamp_percent(y_position, LEGACY_Y_POSITIONS.get(position, 12.0))
    text_align = _normalize_align(text_align or horizontal_position)

    desired_center_x = int(round((x_position / 100.0) * video_width))
    desired_center_y = int(round((y_position / 100.0) * video_height))
    box_x = desired_center_x - (final_box_width // 2)
    box_y = desired_center_y - (box_height // 2)

    box_x = max(0, min(video_width - final_box_width, box_x))
    box_y = max(0, min(video_height - box_height, box_y))

    overlay = Image.new('RGBA', (video_width, video_height), (0, 0, 0, 0))
    box_layer = Image.new('RGBA', (video_width, video_height), (0, 0, 0, 0))
    box_draw = ImageDraw.Draw(box_layer)

    if style.get("hook_draw_box", True):
        shadow_rect = [
            box_x + shadow_offset,
            box_y + shadow_offset,
            box_x + final_box_width + shadow_offset,
            box_y + box_height + shadow_offset,
        ]
        box_draw.rounded_rectangle(shadow_rect, radius=corner_radius, fill=(0, 0, 0, 120))
        box_layer = box_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        box_draw = ImageDraw.Draw(box_layer)
        main_rect = [
            box_x,
            box_y,
            box_x + final_box_width,
            box_y + box_height,
        ]
        box_draw.rounded_rectangle(main_rect, radius=corner_radius, fill=style["hook_box"])

    overlay = Image.alpha_composite(overlay, box_layer)
    draw = ImageDraw.Draw(overlay)

    current_y = box_y + padding_y
    if text_align == "left":
        text_anchor_x = box_x + padding_x
    elif text_align == "right":
        text_anchor_x = box_x + final_box_width - padding_x
    else:
        text_anchor_x = box_x + (final_box_width / 2)

    for line, _, line_height in line_metrics:
        if line:
            draw.text(
                (text_anchor_x, current_y),
                line,
                font=font,
                fill=style["hook_text"],
                align=text_align,
                anchor={"left": "lt", "center": "mt", "right": "rt"}[text_align],
                stroke_width=style.get("hook_stroke_width", 0),
                stroke_fill=style.get("hook_stroke_fill"),
            )
        current_y += line_height + line_spacing

    overlay.save(output_image_path)
    return output_image_path

def add_hook_to_video(
    video_path,
    text,
    output_path,
    position="top",
    horizontal_position="center",
    x_position=None,
    y_position=None,
    text_align="center",
    font_scale=1.0,
    width_preset="wide",
    font_name=DEFAULT_HOOK_FONT,
    background_style=DEFAULT_BACKGROUND_STYLE,
):
    """
    Overlays text hook onto video.
    position: 'top', 'center', 'bottom'
    font_scale: float multiplier (1.0 = default)
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")

    # 1. Probe video width to scale text properly
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', video_path]
        res = subprocess.check_output(cmd).decode().strip()
        # Takes first stream if multiple
        dims = res.split('\n')[0].split('x')
        video_width = int(dims[0])
        video_height = int(dims[1])
    except Exception as e:
        print(f"⚠️ FFprobe failed: {e}. Assuming 1080x1920")
        video_width = 1080
        video_height = 1920
        
    temp_fd, hook_filename = tempfile.mkstemp(
        prefix=f"openshorts_hook_{int(time.time() * 1000)}_",
        suffix=".png",
        dir="/tmp",
    )
    os.close(temp_fd)
    
    try:
        img_path = create_hook_image(
            text,
            video_width,
            video_height,
            hook_filename,
            position=position,
            horizontal_position=horizontal_position,
            x_position=x_position,
            y_position=y_position,
            text_align=text_align,
            font_scale=font_scale,
            width_preset=width_preset,
            font_name=font_name,
            background_style=background_style,
        )
        
        # 4. FFmpeg Command
        print(f"🎬 Overlaying hook: '{text}' with preview-matched layout")
        
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-loglevel', 'error',
            '-i', video_path,
            '-i', img_path,
            *ffmpeg_thread_args(include_filter_threads=True),
            '-filter_complex', "[0:v][1:v]overlay=0:0[vout]",
            '-map', '[vout]',
            '-map', '0:a?',
            '-c:a', 'copy',
            '-c:v', 'libx264', '-preset', OVERLAY_FFMPEG_PRESET, '-crf', '18',
            '-movflags', '+faststart',
            output_path
        ]
        
        subprocess.run(
            ffmpeg_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        print(f"✅ Hook added to {output_path}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg Error: {e.stderr.decode() if e.stderr else 'Unknown'}")
        raise e
    except Exception as e:
        print(f"❌ Hook Gen Error: {e}")
        raise e
    finally:
        # Cleanup temp image
        if os.path.exists(hook_filename):
            os.remove(hook_filename)
