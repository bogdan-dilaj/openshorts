import os
import urllib.request


FONT_DIR = os.environ.get("FONT_DIR", "/tmp/openshorts_fonts")

FONT_PRESETS = {
    "Noto Sans": {
        "filename": "NotoSans-Bold.ttf",
        "url": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
        "ass_name": "Noto Sans",
    },
    "Noto Serif": {
        "filename": "NotoSerif-Bold.ttf",
        "url": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSerif/NotoSerif-Bold.ttf",
        "ass_name": "Noto Serif",
    },
    "Montserrat": {
        "filename": "Montserrat-Bold.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf",
        "ass_name": "Montserrat",
    },
    "Anton": {
        "filename": "Anton-Regular.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
        "ass_name": "Anton",
    },
    "Poppins": {
        "filename": "Poppins-Bold.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf",
        "ass_name": "Poppins",
    },
    "Bebas Neue": {
        "filename": "BebasNeue-Regular.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
        "ass_name": "Bebas Neue",
    },
    "Archivo Black": {
        "filename": "ArchivoBlack-Regular.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
        "ass_name": "Archivo Black",
    },
    "Barlow Condensed": {
        "filename": "BarlowCondensed-Bold.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf",
        "ass_name": "Barlow Condensed",
    },
    "Merriweather": {
        "filename": "Merriweather-Bold.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/merriweather/Merriweather-Bold.ttf",
        "ass_name": "Merriweather",
    },
}

BACKGROUND_PRESETS = {
    "dark-box": {
        "hook_box": (20, 20, 20, 220),
        "hook_text": (255, 255, 255, 255),
        "hook_draw_box": True,
        "hook_stroke_width": 0,
        "hook_stroke_fill": (0, 0, 0, 0),
        "subtitle_box": (20, 20, 20, 214),
        "subtitle_text": (255, 255, 255, 255),
        "subtitle_border": (255, 255, 255, 28),
        "subtitle_shadow": (0, 0, 0, 120),
        "subtitle_draw_box": True,
        "subtitle_text_stroke_width": 0,
        "subtitle_text_stroke_fill": (0, 0, 0, 0),
        "subtitle_primary": "&H00FFFFFF",
        "subtitle_outline": "&H10FFFFFF",
        "subtitle_back": "&H00141414",
        "border_style": 3,
        "outline_width": 2,
        "shadow": 0,
    },
    "light-box": {
        "hook_box": (255, 255, 255, 240),
        "hook_text": (0, 0, 0, 255),
        "hook_draw_box": True,
        "hook_stroke_width": 0,
        "hook_stroke_fill": (0, 0, 0, 0),
        "subtitle_box": (255, 255, 255, 220),
        "subtitle_text": (17, 17, 17, 255),
        "subtitle_border": (255, 255, 255, 35),
        "subtitle_shadow": (0, 0, 0, 95),
        "subtitle_draw_box": True,
        "subtitle_text_stroke_width": 0,
        "subtitle_text_stroke_fill": (0, 0, 0, 0),
        "subtitle_primary": "&H00000000",
        "subtitle_outline": "&H22000000",
        "subtitle_back": "&H00FFFFFF",
        "border_style": 3,
        "outline_width": 2,
        "shadow": 0,
    },
    "yellow-box": {
        "hook_box": (255, 228, 92, 240),
        "hook_text": (0, 0, 0, 255),
        "hook_draw_box": True,
        "hook_stroke_width": 0,
        "hook_stroke_fill": (0, 0, 0, 0),
        "subtitle_box": (255, 228, 92, 232),
        "subtitle_text": (17, 17, 17, 255),
        "subtitle_border": (255, 238, 148, 40),
        "subtitle_shadow": (0, 0, 0, 95),
        "subtitle_draw_box": True,
        "subtitle_text_stroke_width": 0,
        "subtitle_text_stroke_fill": (0, 0, 0, 0),
        "subtitle_primary": "&H00000000",
        "subtitle_outline": "&H22000000",
        "subtitle_back": "&H0000E4FF",
        "border_style": 3,
        "outline_width": 2,
        "shadow": 0,
    },
    "transparent": {
        "hook_box": (0, 0, 0, 0),
        "hook_text": (255, 255, 255, 255),
        "hook_draw_box": False,
        "hook_stroke_width": 4,
        "hook_stroke_fill": (0, 0, 0, 255),
        "subtitle_box": (0, 0, 0, 0),
        "subtitle_text": (255, 255, 255, 255),
        "subtitle_border": None,
        "subtitle_shadow": (0, 0, 0, 0),
        "subtitle_draw_box": False,
        "subtitle_text_stroke_width": 4,
        "subtitle_text_stroke_fill": (0, 0, 0, 255),
        "subtitle_primary": "&H00FFFFFF",
        "subtitle_outline": "&H00000000",
        "subtitle_back": "&HFF000000",
        "border_style": 1,
        "outline_width": 3,
        "shadow": 0,
    },
}

DEFAULT_SUBTITLE_FONT = "Noto Sans"
DEFAULT_HOOK_FONT = "Noto Serif"
DEFAULT_BACKGROUND_STYLE = "dark-box"


def _font_config(font_name: str):
    return FONT_PRESETS.get(font_name) or FONT_PRESETS[DEFAULT_SUBTITLE_FONT]


def ensure_font_file(font_name: str) -> str | None:
    config = _font_config(font_name)
    os.makedirs(FONT_DIR, exist_ok=True)
    font_path = os.path.join(FONT_DIR, config["filename"])
    if os.path.exists(font_path):
        return font_path

    print(f"⬇️ Downloading font {font_name} from {config['url']}...")
    try:
        req = urllib.request.Request(
            config["url"],
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req) as response, open(font_path, "wb") as out_file:
            out_file.write(response.read())
        print(f"✅ Font {font_name} downloaded.")
        return font_path
    except Exception as e:
        print(f"⚠️ Failed to download font {font_name}: {e}")
        return None


def get_font_path(font_name: str) -> str | None:
    return ensure_font_file(font_name)


def get_ass_font_name(font_name: str) -> str:
    return _font_config(font_name)["ass_name"]


def get_background_preset(background_style: str):
    return BACKGROUND_PRESETS.get(background_style) or BACKGROUND_PRESETS[DEFAULT_BACKGROUND_STYLE]
