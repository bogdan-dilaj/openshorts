import os
import re
import subprocess
import tempfile
import time
import urllib.request
from typing import Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from overlay_styles import (
    DEFAULT_BACKGROUND_STYLE,
    DEFAULT_HOOK_FONT,
    FONT_DIR,
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

EMOJI_FONT_FILE = os.environ.get("EMOJI_FONT_FILE", "").strip()
EMOJI_FONT_URL = os.environ.get(
    "EMOJI_FONT_URL",
    "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf",
).strip()
EMOJI_FONT_FILENAME = os.environ.get("EMOJI_FONT_FILENAME", "NotoColorEmoji.ttf").strip() or "NotoColorEmoji.ttf"
EMOJI_FONT_FALLBACK_URLS = [
    "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji-emojicompat.ttf",
    "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji_WindowsCompatible.ttf",
]
EMOJI_SYSTEM_FONT_PATHS = [
    "/tmp/openshorts_fonts/NotoColorEmoji.ttf",
    os.path.join(FONT_DIR, "NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-color-emoji/NotoColorEmoji.ttf",
]
EMOJI_NATIVE_SIZE_HINTS = [109, 128, 72]
_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
_EMOJI_GLYPH_CACHE: Dict[Tuple[str, int], Optional[Image.Image]] = {}

_EMOJI_JOINERS = {0x200D, 0xFE0F, 0xFE0E, 0x20E3}
_EMOJI_SKIN_TONE_MIN = 0x1F3FB
_EMOJI_SKIN_TONE_MAX = 0x1F3FF


def _load_font(font_name, font_size):
    font_path = get_font_path(font_name)
    try:
        if not font_path:
            raise FileNotFoundError("Font file unavailable")
        return ImageFont.truetype(font_path, font_size)
    except Exception as e:
        print(f"⚠️ Warning: Could not load font {font_name}, using default. Error: {e}")
        return ImageFont.load_default()


def _normalize_emoji_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""

    try:
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
            text = text.encode("utf-16", "surrogatepass").decode("utf-16")
    except Exception:
        pass

    if re.search(r"\\u[0-9a-fA-F]{4}", text):
        try:
            decoded = text.encode("utf-8").decode("unicode_escape")
            if decoded and any(ord(ch) > 127 for ch in decoded):
                text = decoded
        except Exception:
            pass

    return text


def _ensure_emoji_font_file():
    if EMOJI_FONT_FILE and os.path.exists(EMOJI_FONT_FILE):
        return EMOJI_FONT_FILE

    for candidate in EMOJI_SYSTEM_FONT_PATHS:
        if candidate and os.path.exists(candidate):
            return candidate

    os.makedirs(FONT_DIR, exist_ok=True)
    target_path = os.path.join(FONT_DIR, EMOJI_FONT_FILENAME)
    if os.path.exists(target_path):
        return target_path

    sources = []
    if EMOJI_FONT_URL:
        sources.append(EMOJI_FONT_URL)
    sources.extend(EMOJI_FONT_FALLBACK_URLS)
    if not sources:
        return None

    for source in sources:
        print(f"⬇️ Downloading emoji font from {source}...")
        try:
            req = urllib.request.Request(
                source,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as response, open(target_path, "wb") as out_file:
                out_file.write(response.read())
            print(f"✅ Emoji font downloaded to {target_path}")
            return target_path
        except Exception as e:
            print(f"⚠️ Failed to download emoji font from {source}: {e}")
    return None


def _load_emoji_font(font_size):
    emoji_font_path = _ensure_emoji_font_file()
    if not emoji_font_path:
        return None
    size_candidates = [max(16, int(font_size))]
    for size_hint in EMOJI_NATIVE_SIZE_HINTS:
        if size_hint not in size_candidates:
            size_candidates.append(size_hint)

    for size_candidate in size_candidates:
        try:
            return ImageFont.truetype(emoji_font_path, size_candidate)
        except Exception:
            continue

    print("⚠️ Could not load emoji font, continuing without emoji fallback.")
    return None


def _render_emoji_cluster(cluster: str, emoji_font, target_height: int) -> Optional[Image.Image]:
    if not cluster or not emoji_font:
        return None

    normalized_target = max(12, int(target_height or 12))
    cache_key = (cluster, normalized_target)
    if cache_key in _EMOJI_GLYPH_CACHE:
        cached = _EMOJI_GLYPH_CACHE[cache_key]
        return cached.copy() if cached is not None else None

    native_size = max(16, int(getattr(emoji_font, "size", 109) or 109))
    canvas_size = max(256, native_size * 4)

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # `embedded_color=True` is required for color emoji fonts.
    draw.text((0, 0), cluster, font=emoji_font, embedded_color=True)
    bbox = canvas.getbbox()
    if not bbox:
        _EMOJI_GLYPH_CACHE[cache_key] = None
        return None

    glyph = canvas.crop(bbox)
    source_width, source_height = glyph.size
    if source_width < 1 or source_height < 1:
        _EMOJI_GLYPH_CACHE[cache_key] = None
        return None

    scale = normalized_target / float(source_height)
    out_width = max(1, int(round(source_width * scale)))
    out_height = max(1, int(round(source_height * scale)))
    resized = glyph.resize((out_width, out_height), _RESAMPLE)
    _EMOJI_GLYPH_CACHE[cache_key] = resized
    return resized.copy()


def _is_emoji_codepoint(value):
    return (
        0x1F300 <= value <= 0x1FAFF or
        0x2600 <= value <= 0x27BF or
        0x1F1E6 <= value <= 0x1F1FF
    )


def _split_graphemeish(text):
    clusters = []
    index = 0
    length = len(text)
    while index < length:
        cluster = text[index]
        index += 1
        while index < length:
            codepoint = ord(text[index])
            if (
                codepoint in _EMOJI_JOINERS
                or _EMOJI_SKIN_TONE_MIN <= codepoint <= _EMOJI_SKIN_TONE_MAX
            ):
                cluster += text[index]
                index += 1
                if codepoint == 0x200D and index < length:
                    cluster += text[index]
                    index += 1
                continue
            break
        clusters.append(cluster)
    return clusters


def _cluster_contains_emoji(cluster):
    for character in cluster:
        if _is_emoji_codepoint(ord(character)):
            return True
    return False


def _line_segments_with_fonts(line, base_font, emoji_font):
    if not line:
        return [("", base_font, False)]
    if not emoji_font:
        return [(line, base_font, False)]

    clusters = _split_graphemeish(line)
    segments = []
    buffer = ""
    current_font = None
    current_is_emoji = False

    for cluster in clusters:
        use_emoji_font = _cluster_contains_emoji(cluster)
        font = emoji_font if use_emoji_font else base_font
        if current_font is None:
            buffer = cluster
            current_font = font
            current_is_emoji = use_emoji_font
            continue
        if font is current_font and use_emoji_font == current_is_emoji:
            buffer += cluster
            continue
        segments.append((buffer, current_font, current_is_emoji))
        buffer = cluster
        current_font = font
        current_is_emoji = use_emoji_font

    if buffer or not segments:
        segments.append((buffer, current_font or base_font, current_is_emoji))
    return segments


def _measure_text(draw, text, font, stroke_width=0):
    if not text:
        return 0, 0
    try:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        fallback_width = int(max(1, len(text)) * max(8, getattr(font, "size", 18)) * 0.55)
        fallback_height = int(max(12, getattr(font, "size", 18)))
        return fallback_width, fallback_height


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
    text = _normalize_emoji_text(text)
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
    emoji_font = _load_emoji_font(font_size)

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
            line_segments = [("", font, False)]
        else:
            line_segments = _line_segments_with_fonts(line, font, emoji_font)
            segment_widths = []
            segment_heights = []
            for segment_text, segment_font, is_emoji_segment in line_segments:
                if is_emoji_segment and emoji_font:
                    emoji_target_height = max(18, int(font_size * 1.02))
                    cluster_width = 0
                    cluster_height = emoji_target_height
                    for cluster in _split_graphemeish(segment_text):
                        emoji_glyph = _render_emoji_cluster(cluster, emoji_font, emoji_target_height)
                        if emoji_glyph:
                            glyph_width, glyph_height = emoji_glyph.size
                            cluster_width += glyph_width
                            cluster_height = max(cluster_height, glyph_height)
                        else:
                            fallback_width, fallback_height = _measure_text(
                                probe_draw,
                                cluster,
                                font,
                                stroke_width=style.get("hook_stroke_width", 0),
                            )
                            cluster_width += fallback_width
                            cluster_height = max(cluster_height, fallback_height)
                    segment_width = cluster_width
                    segment_height = cluster_height
                else:
                    segment_stroke_width = 0 if is_emoji_segment else style.get("hook_stroke_width", 0)
                    segment_width, segment_height = _measure_text(
                        probe_draw,
                        segment_text,
                        segment_font,
                        stroke_width=segment_stroke_width,
                    )
                segment_widths.append(segment_width)
                segment_heights.append(segment_height)
            line_width = sum(segment_widths)
            line_height = max(segment_heights) if segment_heights else font_size
        line_metrics.append((line_segments, line_width, line_height))
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

    for line_segments, line_width, line_height in line_metrics:
        if line_segments and any(segment_text for segment_text, _, _ in line_segments):
            if text_align == "left":
                segment_x = text_anchor_x
            elif text_align == "right":
                segment_x = text_anchor_x - line_width
            else:
                segment_x = text_anchor_x - (line_width / 2.0)

            for segment_text, segment_font, is_emoji_segment in line_segments:
                if not segment_text:
                    continue
                if is_emoji_segment and emoji_font:
                    emoji_target_height = max(18, int(font_size * 1.02))
                    for cluster in _split_graphemeish(segment_text):
                        emoji_glyph = _render_emoji_cluster(cluster, emoji_font, emoji_target_height)
                        if emoji_glyph:
                            glyph_x = int(round(segment_x))
                            glyph_y = int(round(current_y + max(0.0, (line_height - emoji_glyph.height) / 2.0)))
                            overlay.alpha_composite(emoji_glyph, (glyph_x, glyph_y))
                            segment_x += emoji_glyph.width
                            continue

                        fallback_stroke = style.get("hook_stroke_width", 0)
                        draw.text(
                            (segment_x, current_y),
                            cluster,
                            font=font,
                            fill=style["hook_text"],
                            align="left",
                            anchor="lt",
                            stroke_width=fallback_stroke,
                            stroke_fill=style.get("hook_stroke_fill"),
                        )
                        fallback_width, _ = _measure_text(
                            draw,
                            cluster,
                            font,
                            stroke_width=fallback_stroke,
                        )
                        segment_x += fallback_width
                else:
                    segment_stroke_width = 0 if is_emoji_segment else style.get("hook_stroke_width", 0)
                    draw.text(
                        (segment_x, current_y),
                        segment_text,
                        font=segment_font,
                        fill=style["hook_text"],
                        align="left",
                        anchor="lt",
                        stroke_width=segment_stroke_width,
                        stroke_fill=style.get("hook_stroke_fill"),
                    )
                    segment_width, _ = _measure_text(
                        draw,
                        segment_text,
                        segment_font,
                        stroke_width=segment_stroke_width,
                    )
                    segment_x += segment_width
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
    text = _normalize_emoji_text(text)

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
