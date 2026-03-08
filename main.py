import time
import cv2
import scenedetect
import subprocess
import argparse
import re
import sys
import urllib.request
import urllib.error
import math
from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector
from ultralytics import YOLO
import torch
import os
import numpy as np
from tqdm import tqdm
import yt_dlp
import mediapipe as mp
# import whisper (replaced by faster_whisper inside function)
from google import genai
from dotenv import load_dotenv
import json
from job_store import load_job_manifest, update_job_manifest
from runtime_limits import FFMPEG_PRESET, ffmpeg_thread_args, subprocess_priority_kwargs
from tight_edit import (
    DEFAULT_TIGHT_EDIT_PRESET,
    TIGHT_EDIT_PRESETS,
    build_tight_edit_plan,
    normalize_tight_edit_preset,
    render_keep_segments,
)
from whisper_runtime import transcribe_with_runtime

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')

# Load environment variables
load_dotenv()

# --- Constants ---
ASPECT_RATIO = 9 / 16
YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH", "/tmp/Ultralytics/yolov8n.pt")
TARGET_VERTICAL_WIDTH = int(os.environ.get("TARGET_VERTICAL_WIDTH", "1080"))
TARGET_VERTICAL_HEIGHT = int(os.environ.get("TARGET_VERTICAL_HEIGHT", "1920"))
MIN_CLIP_DURATION = 15.0
MAX_CLIP_DURATION = 60.0
MIN_OVER_ONE_MINUTE_CLIP_DURATION = 61.0
MAX_LONG_CLIP_DURATION = float(os.environ.get("MAX_LONG_CLIP_DURATION", "75"))
MAX_GENERATED_CLIPS = int(os.environ.get("MAX_GENERATED_CLIPS", "10"))
OLLAMA_CHUNK_SECONDS = int(os.environ.get("OLLAMA_CHUNK_SECONDS", "180"))
OLLAMA_CHUNK_OVERLAP_SECONDS = int(os.environ.get("OLLAMA_CHUNK_OVERLAP_SECONDS", "20"))
OLLAMA_RETRIES = int(os.environ.get("OLLAMA_RETRIES", "2"))
OLLAMA_RETRY_DELAY_SECONDS = int(os.environ.get("OLLAMA_RETRY_DELAY_SECONDS", "20"))
OLLAMA_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_REQUEST_TIMEOUT_SECONDS", "1800"))
OLLAMA_WARMUP_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_WARMUP_TIMEOUT_SECONDS", "300"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_MAX_SEGMENT_LINES = int(os.environ.get("OLLAMA_MAX_SEGMENT_LINES", "90"))
OLLAMA_MAX_PROMPT_CHARS = int(os.environ.get("OLLAMA_MAX_PROMPT_CHARS", "14000"))
PREFERRED_DOWNLOAD_HEIGHT = int(os.environ.get("PREFERRED_DOWNLOAD_HEIGHT", "1080"))
MIN_SOURCE_EDGE = int(os.environ.get("MIN_SOURCE_EDGE", "720"))
DEFAULT_TIGHT_EDIT_PRESET_ENV = normalize_tight_edit_preset(os.environ.get("TIGHT_EDIT_PRESET", DEFAULT_TIGHT_EDIT_PRESET))
DOWNLOADABLE_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".m4v")


class ClipSelectionConfigurationError(RuntimeError):
    pass


LANGUAGE_LABELS = {
    "de": "German (Deutsch)",
    "en": "English",
    "ru": "Russian (Русский)",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "it": "Italian (Italiano)",
    "pt": "Portuguese (Português)",
    "nl": "Dutch (Nederlands)",
    "tr": "Turkish (Türkçe)",
    "pl": "Polish (Polski)",
}

GEMINI_PROMPT_TEMPLATE = """
You are a senior short-form video editor. Read the ENTIRE transcript and word-level timestamps to choose the 3-{max_clips} MOST VIRAL moments for TikTok/IG Reels/YouTube Shorts. Each clip must be between {min_clip_duration} and {max_clip_duration} seconds long.

⚠️ FFMPEG TIME CONTRACT — STRICT REQUIREMENTS:
- Return timestamps in ABSOLUTE SECONDS from the start of the video (usable in: ffmpeg -ss <start> -to <end> -i <input> ...).
- Only NUMBERS with decimal point, up to 3 decimals (examples: 0, 1.250, 17.350).
- Ensure 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS.
- Each clip between {min_clip_duration} and {max_clip_duration} seconds (inclusive).
- {over_one_minute_rule_1}
- {over_one_minute_rule_2}
- {over_one_minute_rule_3}
- Prefer starting 0.2–0.4 s BEFORE the hook and ending 0.2–0.4 s AFTER the payoff.
- Use silence moments for natural cuts; never cut in the middle of a word or phrase.
- STRICTLY FORBIDDEN to use time formats other than absolute seconds.

VIDEO_DURATION_SECONDS: {video_duration}

TRANSCRIPT_TEXT (raw):
{transcript_text}

WORDS_JSON (array of {{w, s, e}} where s/e are seconds):
{words_json}

STRICT EXCLUSIONS:
- No generic intros/outros or purely sponsorship segments unless they contain the hook.
- No clips shorter than {min_clip_duration} seconds or longer than {max_clip_duration} seconds.
- {over_one_minute_exclusion}
- Return at most {max_clips} clips.
- The transcript language is {output_language_name} (code: {output_language_code}).
- ALL user-facing text fields MUST stay in {output_language_name}: `video_description_for_tiktok`, `video_description_for_instagram`, `video_title_for_youtube_short`, and `viral_hook_text`.
- NEVER translate the content into English unless the transcript itself is English.
- If the transcript is German, every title, description, and hook must be German.
- STYLE: Use "Scroll-Stopper" copywriting. No boring summaries. Use the "Curiosity Gap" technique.
- VIRAL_HOOK_TEXT: Max 5 words. Make it aggressive, controversial, or mysterious. Use "STOP doing X", "The secret to Y", or "POV: You just Z".
- VIDEO_TITLE: Max 40 characters. High-impact keywords only. No full sentences.
- VIDEO_DESCRIPTION: Start with a punchy first line that creates FOMO (Fear Of Missing Out).

OUTPUT — RETURN ONLY VALID JSON (no markdown, no comments). Order clips by predicted performance (best to worst). In the descriptions, ALWAYS include a CTA like "Follow me and comment X and I'll send you the workflow" (especially if discussing an n8n workflow):
{{
  "shorts": [
    {{
      "start": <number in seconds, e.g., 12.340>,
      "end": <number in seconds, e.g., 37.900>,
      "video_description_for_tiktok": "<description for TikTok oriented to get views>",
      "video_description_for_instagram": "<description for Instagram oriented to get views>",
      "video_title_for_youtube_short": "<title for YouTube Short oriented to get views 100 chars max>",
      "viral_hook_text": "<SHORT punchy text overlay (max 10 words). MUST BE IN THE SAME LANGUAGE AS THE VIDEO TRANSCRIPT. Examples: 'POV: You realized...', 'Did you know?', 'Stop doing this!'>"
    }}
  ]
}}
"""

OLLAMA_PROMPT_TEMPLATE = """
You are a senior short-form video editor working on a long-form transcript chunk.

Task:
- Find the most viral moments for TikTok / Reels / Shorts.
- Return up to {max_clips} clips.
- Use ABSOLUTE seconds from the full video.
- Every clip must be between {min_clip_duration} and {max_clip_duration} seconds.
- {over_one_minute_rule_1}
- {over_one_minute_rule_2}
- {over_one_minute_rule_3}
- Prefer conflict, surprise, confession, tension, controversy, emotional payoff, concrete insights, and moments that stop the scroll.
- Avoid filler, greetings, outros, sponsor sections, and context that has no payoff.
- Prefer starting slightly before the hook and ending slightly after the payoff.
- The transcript language is {output_language_name} (code: {output_language_code}).
- ALL user-facing text fields MUST be written in {output_language_name}: `video_description_for_tiktok`, `video_description_for_instagram`, `video_title_for_youtube_short`, and `viral_hook_text`.
- NEVER translate the transcript into English unless the transcript itself is English.
- If the transcript is German, every title, description, and hook must be German.
- Return ONLY valid JSON, no markdown and no extra text.
- STYLE: Use "Scroll-Stopper" copywriting. No boring summaries. Use the "Curiosity Gap" technique.
- VIRAL_HOOK_TEXT: Max 5 words. Make it aggressive, controversial, or mysterious. Use "STOP doing X", "The secret to Y", or "POV: You just Z".
- VIDEO_TITLE: Max 40 characters. High-impact keywords only. No full sentences.
- VIDEO_DESCRIPTION: Start with a punchy first line that creates FOMO (Fear Of Missing Out).

VIDEO_DURATION_SECONDS: {video_duration}
CHUNK_RANGE_SECONDS: {chunk_start} - {chunk_end}

TRANSCRIPT_SEGMENTS:
{segment_lines}

OUTPUT JSON SCHEMA:
{{
  "shorts": [
    {{
      "start": <absolute seconds>,
      "end": <absolute seconds>,
      "video_description_for_tiktok": "<short tiktok caption>",
      "video_description_for_instagram": "<short instagram caption>",
      "video_title_for_youtube_short": "<youtube short title, max 100 chars>",
      "viral_hook_text": "<very short hook overlay in the same language as the transcript, max 10 words>"
    }}
  ]
}}
"""

# Load the YOLO model once (Keep for backup or scene analysis if needed)
model = YOLO(YOLO_MODEL_PATH)


def build_viral_prompt(
    video_duration,
    transcript_text,
    words,
    output_language_code="en",
    output_language_name="English",
    max_clips=MAX_GENERATED_CLIPS,
    min_clip_duration=MIN_CLIP_DURATION,
    max_clip_duration=MAX_CLIP_DURATION,
    min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION,
    chunk_hint="",
):
    def _fmt_number(value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value
        return int(numeric) if numeric.is_integer() else numeric

    over_one_minute_enabled = max_clip_duration > MAX_CLIP_DURATION and min_over_one_minute_clip_duration is not None
    min_clip_duration_fmt = _fmt_number(min_clip_duration)
    max_clip_duration_fmt = _fmt_number(max_clip_duration)
    min_over_one_minute_fmt = _fmt_number(min_over_one_minute_clip_duration)
    over_one_minute_exclusion = (
        f"No clips between 60.001 and {min_over_one_minute_clip_duration - 0.001:.3f} seconds."
        if over_one_minute_enabled
        else "No clips over 60 seconds."
    )

    return GEMINI_PROMPT_TEMPLATE.format(
        video_duration=video_duration,
        transcript_text=json.dumps(transcript_text),
        words_json=json.dumps(words),
        output_language_code=output_language_code,
        output_language_name=output_language_name,
        max_clips=max_clips,
        min_clip_duration=min_clip_duration_fmt,
        min_over_one_minute_clip_duration=min_over_one_minute_fmt,
        max_clip_duration=max_clip_duration_fmt,
        over_one_minute_rule_1="Clips up to 60 seconds are always allowed." if over_one_minute_enabled else "Prefer staying near the strongest payoff and avoid unnecessary padding.",
        over_one_minute_rule_2=(
            "Only create a clip longer than 60 seconds when the moment clearly needs more room."
            if over_one_minute_enabled
            else "Do not exceed 60 seconds."
        ),
        over_one_minute_rule_3=(
            f"If a clip is longer than 60 seconds, it MUST be at least {min_over_one_minute_fmt} seconds and at most {max_clip_duration_fmt} seconds."
            if over_one_minute_enabled
            else "Shorter clips are fine if the moment is strongest that way."
        ),
        over_one_minute_exclusion=over_one_minute_exclusion,
        chunk_hint=chunk_hint,
    )


def _extract_json_payload(text):
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx:end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def _coerce_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        try:
            return float(value)
        except ValueError:
            return None
    return None


def describe_output_language(language_code):
    normalized = (language_code or "en").strip().lower()
    return normalized, LANGUAGE_LABELS.get(normalized, normalized)


def get_default_clip_texts(language_code):
    normalized = (language_code or "en").strip().lower()
    if normalized == "de":
        return {
            "video_description_for_tiktok": "Viral Clip aus dem Video.",
            "video_description_for_instagram": "Starker Ausschnitt aus dem Video.",
            "video_title_for_youtube_short": "Generierter YouTube Short",
            "viral_hook_text": "Warte bis zum Ende",
        }
    if normalized == "es":
        return {
            "video_description_for_tiktok": "Clip viral del video.",
            "video_description_for_instagram": "Fragmento potente del video.",
            "video_title_for_youtube_short": "Short generado para YouTube",
            "viral_hook_text": "Espera hasta el final",
        }
    return {
        "video_description_for_tiktok": "Generated TikTok caption.",
        "video_description_for_instagram": "Generated Instagram caption.",
        "video_title_for_youtube_short": "Generated YouTube Short",
        "viral_hook_text": "Wait for the ending",
    }


def _clip_overlap_ratio(a_start, a_end, b_start, b_end):
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    min_len = max(0.001, min(a_end - a_start, b_end - b_start))
    return overlap / min_len


def sanitize_clip_candidates(
    raw_data,
    video_duration,
    language_code="en",
    max_clips=MAX_GENERATED_CLIPS,
    min_clip_duration=MIN_CLIP_DURATION,
    max_clip_duration=MAX_CLIP_DURATION,
    min_over_one_minute_clip_duration=None,
):
    if not raw_data:
        return None

    raw_clips = raw_data.get("shorts")
    if not isinstance(raw_clips, list):
        return None

    sanitized = []
    defaults = get_default_clip_texts(language_code)
    for clip in raw_clips:
        if not isinstance(clip, dict):
            continue

        start = _coerce_float(clip.get("start"))
        end = _coerce_float(clip.get("end"))
        if start is None or end is None:
            continue

        if math.isnan(start) or math.isnan(end):
            continue

        start = max(0.0, min(start, video_duration))
        end = max(0.0, min(end, video_duration))
        if end <= start:
            continue

        duration = end - start
        if duration < min_clip_duration:
            midpoint = start + (duration / 2.0)
            start = max(0.0, midpoint - (min_clip_duration / 2.0))
            end = min(video_duration, start + min_clip_duration)
            start = max(0.0, end - min_clip_duration)
        elif duration > max_clip_duration:
            end = min(video_duration, start + max_clip_duration)
            duration = end - start

        if (
            min_over_one_minute_clip_duration
            and max_clip_duration > MAX_CLIP_DURATION
            and duration > MAX_CLIP_DURATION
            and duration < min_over_one_minute_clip_duration
        ):
            desired_duration = min(max_clip_duration, min_over_one_minute_clip_duration)
            if start + desired_duration <= video_duration:
                end = start + desired_duration
            else:
                end = video_duration
                start = max(0.0, end - desired_duration)

            duration = end - start
            if duration > MAX_CLIP_DURATION and duration < min_over_one_minute_clip_duration:
                end = min(video_duration, start + MAX_CLIP_DURATION)
                duration = end - start

        if end - start < min_clip_duration * 0.8:
            continue

        duplicate = False
        for existing in sanitized:
            if _clip_overlap_ratio(start, end, existing["start"], existing["end"]) > 0.85:
                duplicate = True
                break
        if duplicate:
            continue

        sanitized.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "video_description_for_tiktok": clip.get("video_description_for_tiktok") or defaults["video_description_for_tiktok"],
            "video_description_for_instagram": clip.get("video_description_for_instagram") or clip.get("video_description_for_tiktok") or defaults["video_description_for_instagram"],
            "video_title_for_youtube_short": clip.get("video_title_for_youtube_short") or defaults["video_title_for_youtube_short"],
            "viral_hook_text": clip.get("viral_hook_text") or defaults["viral_hook_text"],
            "status": "pending",
        })

    if not sanitized:
        return None

    if len(sanitized) > max_clips:
        print(f"⚠️  Model proposed {len(sanitized)} clips. Trimming to top {max_clips}.")
        sanitized = sanitized[:max_clips]

    result = dict(raw_data)
    result["shorts"] = sanitized
    return result


def split_transcript_for_ollama(transcript_result, window_seconds=OLLAMA_CHUNK_SECONDS, overlap_seconds=OLLAMA_CHUNK_OVERLAP_SECONDS):
    segments = transcript_result.get("segments", [])
    if not segments:
        return []

    windows = []
    total_duration = segments[-1]["end"]
    start_time = 0.0
    while start_time < total_duration:
        end_time = min(total_duration, start_time + window_seconds)
        chunk_segments = [
            segment for segment in segments
            if segment["end"] >= start_time and segment["start"] <= end_time
        ]
        if chunk_segments:
            chunk_words = []
            chunk_text_parts = []
            for segment in chunk_segments:
                chunk_text_parts.append(segment["text"])
                for word in segment.get("words", []):
                    if word["end"] >= start_time and word["start"] <= end_time:
                        chunk_words.append({
                            "w": word["word"],
                            "s": word["start"],
                            "e": word["end"],
                        })
            windows.append({
                "start": start_time,
                "end": end_time,
                "text": " ".join(chunk_text_parts).strip(),
                "words": chunk_words,
                "segments": chunk_segments,
            })

        if end_time >= total_duration:
            break
        start_time = max(0.0, end_time - overlap_seconds)

    return windows


def build_ollama_segment_lines(segments, max_lines=OLLAMA_MAX_SEGMENT_LINES, max_chars=OLLAMA_MAX_PROMPT_CHARS):
    lines = []
    total_chars = 0

    for segment in segments:
        text = re.sub(r"\s+", " ", (segment.get("text") or "").strip())
        if not text:
            continue

        if len(text) > 220:
            text = text[:217].rstrip() + "..."

        line = f"[{segment['start']:.2f}-{segment['end']:.2f}] {text}"
        if lines and (len(lines) >= max_lines or (total_chars + len(line) + 1) > max_chars):
            break

        lines.append(line)
        total_chars += len(line) + 1

    return "\n".join(lines)


def build_ollama_prompt(
    video_duration,
    transcript_window,
    output_language_code="en",
    output_language_name="English",
    max_clips=MAX_GENERATED_CLIPS,
    min_clip_duration=MIN_CLIP_DURATION,
    max_clip_duration=MAX_CLIP_DURATION,
    min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION,
):
    over_one_minute_enabled = max_clip_duration > MAX_CLIP_DURATION and min_over_one_minute_clip_duration is not None
    segment_lines = build_ollama_segment_lines(transcript_window.get("segments", []))
    return OLLAMA_PROMPT_TEMPLATE.format(
        video_duration=video_duration,
        chunk_start=f"{transcript_window['start']:.2f}",
        chunk_end=f"{transcript_window['end']:.2f}",
        segment_lines=segment_lines or "[0.00-0.00] No transcript available.",
        output_language_code=output_language_code,
        output_language_name=output_language_name,
        max_clips=max_clips,
        min_clip_duration=int(min_clip_duration) if float(min_clip_duration).is_integer() else min_clip_duration,
        max_clip_duration=int(max_clip_duration) if float(max_clip_duration).is_integer() else max_clip_duration,
        over_one_minute_rule_1="Clips up to 60 seconds are always allowed." if over_one_minute_enabled else "Do not exceed 60 seconds.",
        over_one_minute_rule_2=(
            "Only create a clip longer than 60 seconds when the moment clearly needs more room."
            if over_one_minute_enabled
            else "Shorter clips are fine if the moment is strongest that way."
        ),
        over_one_minute_rule_3=(
            f"If a clip is longer than 60 seconds, it MUST be at least {int(min_over_one_minute_clip_duration) if float(min_over_one_minute_clip_duration).is_integer() else min_over_one_minute_clip_duration} seconds and at most {int(max_clip_duration) if float(max_clip_duration).is_integer() else max_clip_duration} seconds."
            if over_one_minute_enabled
            else "Keep the clip tight and payoff-focused."
        ),
    )


def load_json_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _split_env_values(value):
    if not value:
        return []
    parts = []
    for raw in re.split(r"[\n,]", value):
        item = raw.strip()
        if item:
            parts.append(item)
    return parts


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _build_youtube_extractor_args():
    youtube_args = {}

    player_clients = _split_env_values(os.environ.get("YOUTUBE_PLAYER_CLIENTS"))
    player_skip = _split_env_values(os.environ.get("YOUTUBE_PLAYER_SKIP"))
    legacy_mode = _env_flag("YOUTUBE_LEGACY_EXTRACTOR_ARGS", False)

    # Legacy compatibility switch:
    # keep old forced-client behavior only when explicitly enabled.
    if legacy_mode and not player_clients:
        player_clients = ["tv_embed", "android", "mweb", "web"]
    if legacy_mode and not player_skip:
        player_skip = ["webpage", "configs"]

    if player_clients:
        youtube_args["player_client"] = player_clients
    if player_skip:
        youtube_args["player_skip"] = player_skip

    visitor_data = os.environ.get("YOUTUBE_VISITOR_DATA")
    if visitor_data:
        youtube_args["visitor_data"] = [visitor_data.strip()]

    po_tokens = []
    for client_name in ("web", "mweb", "android"):
        token_value = os.environ.get(f"YOUTUBE_PO_TOKEN_{client_name.upper()}")
        if token_value:
            po_tokens.append(f"{client_name}.gvs+{token_value.strip()}")

    po_tokens.extend(_split_env_values(os.environ.get("YOUTUBE_PO_TOKENS")))
    if po_tokens:
        youtube_args["po_token"] = po_tokens

    if not youtube_args:
        return None
    return {"youtube": youtube_args}


def _find_downloaded_video_file(output_dir, sanitized_title):
    matches = []
    for entry in os.listdir(output_dir):
        entry_path = os.path.join(output_dir, entry)
        if not os.path.isfile(entry_path):
            continue
        if not entry.startswith(sanitized_title):
            continue
        if os.path.splitext(entry)[1].lower() not in DOWNLOADABLE_VIDEO_EXTENSIONS:
            continue
        matches.append(entry_path)

    if not matches:
        return None

    matches.sort(key=os.path.getmtime, reverse=True)
    return matches[0]


def _best_accessible_source_edge(info):
    best_format = None
    best_edge = 0

    for fmt in info.get("formats", []):
        if fmt.get("vcodec") == "none":
            continue
        if not fmt.get("url"):
            continue

        width = fmt.get("width") or 0
        height = fmt.get("height") or 0
        short_edge = min(width, height) if width and height else (height or width or 0)
        if short_edge > best_edge:
            best_edge = short_edge
            best_format = fmt

    return best_format, best_edge

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

class SmoothedCameraman:
    """
    Handles smooth camera movement.
    Simplified Logic: "Heavy Tripod"
    Only moves if the subject leaves the center safe zone.
    Moves slowly and linearly.
    """
    def __init__(self, output_width, output_height, video_width, video_height):
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height
        
        # Initial State
        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2
        
        # Calculate crop dimensions once
        self.crop_height = video_height
        self.crop_width = int(self.crop_height * ASPECT_RATIO)
        if self.crop_width > video_width:
             self.crop_width = video_width
             self.crop_height = int(self.crop_width / ASPECT_RATIO)
             
        # Safe Zone: 20% of the video width
        # As long as the target is within this zone relative to current center, DO NOT MOVE.
        self.safe_zone_radius = self.crop_width * 0.25

    def update_target(self, face_box):
        """
        Updates the target center based on detected face/person.
        """
        if face_box:
            x, y, w, h = face_box
            self.target_center_x = x + w / 2
    
    def get_crop_box(self, force_snap=False):
        """
        Returns the (x1, y1, x2, y2) for the current frame.
        """
        if force_snap:
            self.current_center_x = self.target_center_x
        else:
            diff = self.target_center_x - self.current_center_x
            
            # SIMPLIFIED LOGIC:
            # 1. Is the target outside the safe zone?
            if abs(diff) > self.safe_zone_radius:
                # 2. If yes, move towards it slowly (Linear Speed)
                # Determine direction
                direction = 1 if diff > 0 else -1
                
                # Speed: 2 pixels per frame (Slow pan)
                # If the distance is HUGE (scene change or fast movement), speed up slightly
                if abs(diff) > self.crop_width * 0.5:
                    speed = 15.0 # Fast re-frame
                else:
                    speed = 3.0  # Slow, steady pan
                
                self.current_center_x += direction * speed
                
                # Check if we overshot (prevent oscillation)
                new_diff = self.target_center_x - self.current_center_x
                if (direction == 1 and new_diff < 0) or (direction == -1 and new_diff > 0):
                    self.current_center_x = self.target_center_x
            
            # If inside safe zone, DO NOTHING (Stationary Camera)
                
        # Clamp center
        half_crop = self.crop_width / 2
        
        if self.current_center_x - half_crop < 0:
            self.current_center_x = half_crop
        if self.current_center_x + half_crop > self.video_width:
            self.current_center_x = self.video_width - half_crop
            
        x1 = int(self.current_center_x - half_crop)
        x2 = int(self.current_center_x + half_crop)
        
        x1 = max(0, x1)
        x2 = min(self.video_width, x2)
        
        y1 = 0
        y2 = self.video_height
        
        return x1, y1, x2, y2

class SpeakerTracker:
    """
    Tracks speakers over time to prevent rapid switching and handle temporary obstructions.
    """
    def __init__(self, stabilization_frames=15, cooldown_frames=30):
        self.active_speaker_id = None
        self.speaker_scores = {}  # {id: score}
        self.last_seen = {}       # {id: frame_number}
        self.locked_counter = 0   # How long we've been locked on current speaker
        
        # Hyperparameters
        self.stabilization_threshold = stabilization_frames # Frames needed to confirm a new speaker
        self.switch_cooldown = cooldown_frames              # Minimum frames before switching again
        self.last_switch_frame = -1000
        
        # ID tracking
        self.next_id = 0
        self.known_faces = [] # [{'id': 0, 'center': x, 'last_frame': 123}]

    def get_target(self, face_candidates, frame_number, width):
        """
        Decides which face to focus on.
        face_candidates: list of {'box': [x,y,w,h], 'score': float}
        """
        current_candidates = []
        
        # 1. Match faces to known IDs (simple distance tracking)
        for face in face_candidates:
            x, y, w, h = face['box']
            center_x = x + w / 2
            
            best_match_id = -1
            min_dist = width * 0.15 # Reduced matching radius to avoid jumping in groups
            
            # Try to match with known faces seen recently
            for kf in self.known_faces:
                if frame_number - kf['last_frame'] > 30: # Forgot faces older than 1s (was 2s)
                    continue
                    
                dist = abs(center_x - kf['center'])
                if dist < min_dist:
                    min_dist = dist
                    best_match_id = kf['id']
            
            # If no match, assign new ID
            if best_match_id == -1:
                best_match_id = self.next_id
                self.next_id += 1
            
            # Update known face
            self.known_faces = [kf for kf in self.known_faces if kf['id'] != best_match_id]
            self.known_faces.append({'id': best_match_id, 'center': center_x, 'last_frame': frame_number})
            
            current_candidates.append({
                'id': best_match_id,
                'box': face['box'],
                'score': face['score']
            })

        # 2. Update Scores with decay
        for pid in list(self.speaker_scores.keys()):
             self.speaker_scores[pid] *= 0.85 # Faster decay (was 0.9)
             if self.speaker_scores[pid] < 0.1:
                 del self.speaker_scores[pid]

        # Add new scores
        for cand in current_candidates:
            pid = cand['id']
            # Score is purely based on size (proximity) now that we don't have mouth
            raw_score = cand['score'] / (width * width * 0.05)
            self.speaker_scores[pid] = self.speaker_scores.get(pid, 0) + raw_score

        # 3. Determine Best Speaker
        if not current_candidates:
            # If no one found, maintain last active speaker if cooldown allows
            # to avoid black screen or jump to 0,0
            return None 
            
        best_candidate = None
        max_score = -1
        
        for cand in current_candidates:
            pid = cand['id']
            total_score = self.speaker_scores.get(pid, 0)
            
            # Hysteresis: HUGE Bonus for current active speaker
            if pid == self.active_speaker_id:
                total_score *= 3.0 # Sticky factor
                
            if total_score > max_score:
                max_score = total_score
                best_candidate = cand

        # 4. Decide Switch
        if best_candidate:
            target_id = best_candidate['id']
            
            if target_id == self.active_speaker_id:
                self.locked_counter += 1
                return best_candidate['box']
            
            # New person
            if frame_number - self.last_switch_frame < self.switch_cooldown:
                old_cand = next((c for c in current_candidates if c['id'] == self.active_speaker_id), None)
                if old_cand:
                    return old_cand['box']
            
            self.active_speaker_id = target_id
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return best_candidate['box']
            
        return None


class InterviewLayoutTracker:
    """
    Tracks two stable face regions for top/bottom interview framing.
    """
    def __init__(self, video_width, video_height):
        half_width = max(1, video_width // 2)
        self.boxes = [
            [0, 0, half_width, video_height],
            [video_width - half_width, 0, half_width, video_height],
        ]

    def _smooth_box(self, previous_box, new_box, alpha=0.35):
        return [
            int(round(previous_box[i] * (1 - alpha) + new_box[i] * alpha))
            for i in range(4)
        ]

    def update(self, face_candidates, video_width):
        candidates = sorted(face_candidates, key=lambda item: item["score"], reverse=True)
        boxes = [candidate["box"] for candidate in candidates[:2]]
        if len(boxes) >= 2:
            boxes = sorted(boxes, key=lambda box: box[0] + (box[2] / 2))
            self.boxes[0] = self._smooth_box(self.boxes[0], boxes[0])
            self.boxes[1] = self._smooth_box(self.boxes[1], boxes[1])
        elif len(boxes) == 1:
            target_index = 0 if (boxes[0][0] + boxes[0][2] / 2) < (video_width / 2) else 1
            self.boxes[target_index] = self._smooth_box(self.boxes[target_index], boxes[0])

    def get_boxes(self):
        return self.boxes

def detect_face_candidates(frame):
    """
    Returns list of all detected faces using lightweight FaceDetection.
    """
    height, width, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_detection.process(rgb_frame)
    
    candidates = []
    
    if not results.detections:
        return []
        
    for detection in results.detections:
        bboxC = detection.location_data.relative_bounding_box
        x = int(bboxC.xmin * width)
        y = int(bboxC.ymin * height)
        w = int(bboxC.width * width)
        h = int(bboxC.height * height)
        
        candidates.append({
            'box': [x, y, w, h],
            'score': w * h # Area as score
        })
            
    return candidates

def detect_person_yolo(frame):
    """
    Fallback: Detect largest person using YOLO when face detection fails.
    Returns [x, y, w, h] of the person's 'upper body' approximation.
    """
    # Use the globally loaded model
    results = model(frame, verbose=False, classes=[0]) # class 0 is person
    
    if not results:
        return None
        
    best_box = None
    max_area = 0
    
    for result in results:
        boxes = result.boxes
        for box in boxes:
            x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
            w = x2 - x1
            h = y2 - y1
            area = w * h
            
            if area > max_area:
                max_area = area
                # Focus on the top 40% of the person (head/chest) for framing
                # This approximates where the face is if we can't detect it directly
                face_h = int(h * 0.4)
                best_box = [x1, y1, w, face_h]
                
    return best_box

def create_general_frame(frame, output_width, output_height):
    """
    Creates a 'General Shot' frame: 
    - Background: Blurred zoom of original
    - Foreground: Original video scaled to fit width, centered vertically.
    """
    orig_h, orig_w = frame.shape[:2]
    
    # 1. Background (Fill Height)
    # Crop center to aspect ratio
    bg_scale = output_height / orig_h
    bg_w = int(orig_w * bg_scale)
    bg_resized = cv2.resize(frame, (bg_w, output_height), interpolation=cv2.INTER_CUBIC)
    
    # Crop center of background
    start_x = (bg_w - output_width) // 2
    if start_x < 0: start_x = 0
    background = bg_resized[:, start_x:start_x+output_width]
    if background.shape[1] != output_width:
        background = cv2.resize(background, (output_width, output_height), interpolation=cv2.INTER_CUBIC)
        
    # Blur background
    background = cv2.GaussianBlur(background, (51, 51), 0)
    
    # 2. Foreground (Fit Width)
    scale = output_width / orig_w
    fg_h = int(orig_h * scale)
    foreground = cv2.resize(frame, (output_width, fg_h), interpolation=cv2.INTER_CUBIC)
    
    # 3. Overlay
    y_offset = (output_height - fg_h) // 2
    
    # Clone background to avoid modifying it
    final_frame = background.copy()
    final_frame[y_offset:y_offset+fg_h, :] = foreground
    
    return final_frame


def crop_focus_panel(frame, face_box, output_width, output_height):
    orig_h, orig_w = frame.shape[:2]
    target_ratio = output_width / output_height

    crop_h = orig_h
    crop_w = int(crop_h * target_ratio)
    if crop_w > orig_w:
        crop_w = orig_w
        crop_h = int(crop_w / target_ratio)

    x, y, w, h = face_box
    center_x = x + (w / 2)
    center_y = y + (h / 2) + (h * 0.8)

    x1 = int(round(center_x - (crop_w / 2)))
    y1 = int(round(center_y - (crop_h * 0.35)))
    x1 = max(0, min(orig_w - crop_w, x1))
    y1 = max(0, min(orig_h - crop_h, y1))

    cropped = frame[y1:y1 + crop_h, x1:x1 + crop_w]
    if cropped.size == 0:
        return cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_CUBIC)

    return cv2.resize(cropped, (output_width, output_height), interpolation=cv2.INTER_CUBIC)


def create_interview_frame(frame, output_width, output_height, subject_boxes):
    top_height = output_height // 2
    bottom_height = output_height - top_height

    top_box = subject_boxes[0] if len(subject_boxes) > 0 else [0, 0, frame.shape[1], frame.shape[0]]
    bottom_box = subject_boxes[1] if len(subject_boxes) > 1 else top_box

    top_panel = crop_focus_panel(frame, top_box, output_width, top_height)
    bottom_panel = crop_focus_panel(frame, bottom_box, output_width, bottom_height)

    final_frame = np.vstack((top_panel, bottom_panel))
    cv2.line(final_frame, (0, top_height), (output_width, top_height), (255, 255, 255), 3)
    return final_frame

def analyze_scenes_strategy(video_path, scenes):
    """
    Analyzes each scene to determine if it should be TRACK (Single person) or GENERAL (Group/Wide).
    Returns list of strategies corresponding to scenes.
    """
    cap = cv2.VideoCapture(video_path)
    strategies = []
    
    if not cap.isOpened():
        return ['TRACK'] * len(scenes)
        
    for start, end in tqdm(scenes, desc="   Analyzing Scenes"):
        # Sample 3 frames (start, middle, end)
        frames_to_check = [
            start.get_frames() + 5,
            int((start.get_frames() + end.get_frames()) / 2),
            end.get_frames() - 5
        ]
        
        face_counts = []
        for f_idx in frames_to_check:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret: continue
            
            # Detect faces
            candidates = detect_face_candidates(frame)
            face_counts.append(len(candidates))
            
        # Decision Logic
        if not face_counts:
            avg_faces = 0
        else:
            avg_faces = sum(face_counts) / len(face_counts)
            
        # Strategy:
        # 0 faces -> GENERAL (Landscape/B-roll)
        # 1 face -> TRACK
        # > 1.2 faces -> GENERAL (Group)
        
        if avg_faces > 1.2 or avg_faces < 0.5:
            strategies.append('GENERAL')
        else:
            strategies.append('TRACK')
            
    cap.release()
    return strategies

def detect_scenes(video_path):
    video_manager = VideoManager([video_path])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    video_manager.set_downscale_factor()
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list()
    fps = video_manager.get_framerate()
    video_manager.release()
    return scene_list, fps

def get_video_resolution(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = filename.replace(' ', '_')
    return filename[:100]


def _write_temp_cookies_file(content):
    temp_path = f"/tmp/youtube_cookies_{os.getpid()}_{int(time.time() * 1000)}.txt"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
    return temp_path


def _copy_cookies_file_to_temp(cookies_path):
    with open(cookies_path, "r", encoding="utf-8", errors="ignore") as src:
        return _write_temp_cookies_file(src.read())


def _browser_profile_roots(browser_name):
    home = os.path.expanduser("~")
    roots = []

    override_roots = _split_env_values(os.environ.get("YOUTUBE_BROWSER_PROFILE_ROOTS"))
    if override_roots:
        roots.extend(os.path.expanduser(path) for path in override_roots)

    if browser_name in {"chrome", "brave", "edge", "chromium", "opera", "vivaldi"}:
        roots.extend(
            [
                os.path.join(home, ".config", "google-chrome"),
                os.path.join(home, ".config", "chromium"),
                os.path.join(home, ".config", "BraveSoftware", "Brave-Browser"),
                os.path.join(home, ".config", "microsoft-edge"),
                os.path.join(home, ".config", "opera"),
                os.path.join(home, ".config", "vivaldi"),
                os.path.join(home, ".var", "app", "com.google.Chrome", "config", "google-chrome"),
                os.path.join(home, ".var", "app", "org.chromium.Chromium", "config", "chromium"),
            ]
        )
    elif browser_name == "firefox":
        roots.extend(
            [
                os.path.join(home, ".mozilla", "firefox"),
                os.path.join(home, ".var", "app", "org.mozilla.firefox", "config", "mozilla", "firefox"),
            ]
        )
    elif browser_name == "safari":
        roots.append(os.path.join(home, "Library", "Safari"))

    unique = []
    seen = set()
    for path in roots:
        if not path:
            continue
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(norm)
    return unique


def _browser_profile_available(browser_name):
    return any(os.path.exists(path) for path in _browser_profile_roots(browser_name))


def _build_youtube_auth_candidates():
    mode = (os.environ.get("YOUTUBE_AUTH_MODE") or "auto").strip().lower()
    cookies_file_path = os.environ.get("YOUTUBE_COOKIES_FILE", "/app/cookies.txt")
    cookies_env = (os.environ.get("YOUTUBE_COOKIES") or "").strip()
    browser = (os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER") or "").strip().lower()

    candidates = []
    temp_files = []

    def add_inline():
        if not cookies_env:
            return
        try:
            temp_path = _write_temp_cookies_file(cookies_env)
            temp_files.append(temp_path)
            candidates.append({
                "label": "inline-cookies",
                "opts": {"cookiefile": temp_path},
            })
        except Exception as exc:
            print(f"⚠️ Failed to materialize YOUTUBE_COOKIES env var: {exc}")

    def add_file():
        if not cookies_file_path or not os.path.exists(cookies_file_path):
            return
        try:
            temp_path = _copy_cookies_file_to_temp(cookies_file_path)
            temp_files.append(temp_path)
            candidates.append({
                "label": f"cookies-file:{cookies_file_path}",
                "opts": {"cookiefile": temp_path},
            })
        except Exception as exc:
            print(f"⚠️ Failed to copy cookies file {cookies_file_path}: {exc}")

    def add_browser():
        browser_name = browser or "chrome"
        if not _browser_profile_available(browser_name):
            print(
                f"⚠️ Skipping browser auth candidate '{browser_name}': "
                "no browser profile directory found in this runtime."
            )
            return
        candidates.append({
            "label": f"browser:{browser_name}",
            "opts": {"cookiesfrombrowser": (browser_name,)},
        })

    if mode == "cookies_text":
        add_inline()
    elif mode == "cookies_file":
        add_file()
    elif mode == "browser":
        add_browser()
    else:
        add_inline()
        add_file()
        if browser:
            add_browser()

    allow_unauth_fallback = _env_flag("YOUTUBE_ALLOW_UNAUTH_FALLBACK", True)
    if allow_unauth_fallback:
        candidates.append({"label": "unauthenticated", "opts": {}})

    if not candidates:
        candidates.append({"label": "unauthenticated", "opts": {}})

    deduped = []
    seen_labels = set()
    for candidate in candidates:
        label = candidate.get("label") or ""
        if label in seen_labels:
            continue
        seen_labels.add(label)
        deduped.append(candidate)

    return deduped, temp_files


def download_youtube_video(url, output_dir="."):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the path to the downloaded video and the video title.
    """
    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading video from YouTube...")
    step_start_time = time.time()
    auth_candidates, temp_files = _build_youtube_auth_candidates()
    extractor_args = _build_youtube_extractor_args()
    print(
        "🔐 YouTube auth candidates (in order): "
        + ", ".join(candidate["label"] for candidate in auth_candidates)
    )

    common_ydl_opts = {
        "quiet": False,
        "verbose": True,
        "no_warnings": False,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "nocheckcertificate": True,
        "cachedir": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Sec-Fetch-Mode": "navigate",
        },
    }
    if extractor_args:
        common_ydl_opts["extractor_args"] = extractor_args

    selected_candidate = None
    selected_info = None
    preflight_errors = []

    try:
        for candidate in auth_candidates:
            probe_opts = {**common_ydl_opts, **candidate["opts"]}
            print(f"🔑 Probing YouTube formats using auth={candidate['label']}")
            try:
                with yt_dlp.YoutubeDL(probe_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                best_format, best_edge = _best_accessible_source_edge(info)
                if best_format:
                    print(
                        "🎞️  Best accessible source before download: "
                        f"auth={candidate['label']} "
                        f"format={best_format.get('format_id')} "
                        f"{best_format.get('width') or '?'}x{best_format.get('height') or '?'} "
                        f"ext={best_format.get('ext')}"
                    )
                if best_edge < MIN_SOURCE_EDGE:
                    preflight_errors.append(
                        f"{candidate['label']}: best short edge {best_edge}px < required {MIN_SOURCE_EDGE}px"
                    )
                    continue

                selected_candidate = candidate
                selected_info = info
                break
            except Exception as exc:
                preflight_errors.append(f"{candidate['label']}: {exc}")

        if not selected_candidate or not selected_info:
            detail = "\n".join(preflight_errors[-5:]) if preflight_errors else "No auth candidate succeeded."
            raise RuntimeError(
                "Unable to access a high-quality YouTube source.\n"
                f"Details:\n{detail}\n"
                "Set valid cookies (cookies.txt or pasted cookies), optional visitor data/PO token, or upload the source file manually."
            )

        video_title = selected_info.get("title", "youtube_video")
        sanitized_title = sanitize_filename(video_title)
        output_template = os.path.join(output_dir, f"{sanitized_title}.%(ext)s")
        existing_file = _find_downloaded_video_file(output_dir, sanitized_title)
        if existing_file and os.path.exists(existing_file):
            os.remove(existing_file)
            print("🗑️  Removed existing file to re-download highest available quality")

        ydl_opts = {
            **common_ydl_opts,
            **selected_candidate["opts"],
            "format": (
                f"bestvideo[height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]+bestaudio/"
                f"best[height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]/"
                f"bestvideo[height>={MIN_SOURCE_EDGE}]+bestaudio/best[height>={MIN_SOURCE_EDGE}]"
            ),
            "outtmpl": output_template,
            "merge_output_format": "mkv",
            "overwrites": True,
        }

        print(f"⬇️ Downloading with auth={selected_candidate['label']}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        downloaded_file = _find_downloaded_video_file(output_dir, sanitized_title)
        if not downloaded_file:
            raise RuntimeError("yt-dlp finished without a usable video file.")

        width, height = get_video_resolution(downloaded_file)
        short_edge = min(width, height)
        print(f"🎞️  Downloaded source resolution: {width}x{height}")
        if short_edge < MIN_SOURCE_EDGE:
            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
            raise RuntimeError(
                f"Downloaded source is only {width}x{height}. "
                "Aborting to avoid a low-quality 1080x1920 upscale. "
                "Provide valid YouTube auth cookies/tokens or upload the source video manually."
            )

        step_end_time = time.time()
        print(f"✅ Video downloaded in {step_end_time - step_start_time:.2f}s: {downloaded_file}")
        return downloaded_file, sanitized_title

    except Exception as e:
        import sys

        print("🚨 YOUTUBE DOWNLOAD ERROR 🚨", file=sys.stderr)
        reason = str(e)

        error_msg = f"""
            
❌ ================================================================= ❌
❌ FATAL ERROR: YOUTUBE DOWNLOAD FAILED
❌ ================================================================= ❌
            
REASON: {reason}

👇 SOLUTION FOR USER 👇
---------------------------------------------------------------------
1. Save a fresh cookies.txt from a logged-in browser and configure mode `cookies_file` or `cookies_text`.
2. Optionally set YOUTUBE_VISITOR_DATA and YOUTUBE_PO_TOKEN_* to unlock blocked streams.
3. If YouTube still only exposes low quality, upload the original source file directly.
---------------------------------------------------------------------
"""
        print(error_msg, file=sys.stdout)
        print(error_msg, file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(0.5)
        raise e
    finally:
        for temp_path in temp_files:
            try:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

def process_video_to_vertical(
    input_video,
    final_output_video,
    interview_mode=False,
    output_width=None,
    output_height=None,
    ffmpeg_preset_override=None,
    video_crf="18",
    video_maxrate="12M",
    video_bufsize="24M",
    audio_bitrate="192k",
):
    """
    Core logic to convert horizontal video to vertical using scene detection and Active Speaker Tracking (MediaPipe).
    """
    script_start_time = time.time()
    
    # Define temporary file paths based on the output name
    base_name = os.path.splitext(final_output_video)[0]
    temp_video_output = f"{base_name}_temp_video.mp4"
    temp_audio_output = f"{base_name}_temp_audio.aac"
    
    # Clean up previous temp files if they exist
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    if os.path.exists(final_output_video): os.remove(final_output_video)

    print(f"🎬 Processing clip: {input_video}")
    original_width, original_height = get_video_resolution(input_video)
    
    OUTPUT_WIDTH = int(output_width or TARGET_VERTICAL_WIDTH)
    OUTPUT_HEIGHT = int(output_height or TARGET_VERTICAL_HEIGHT)
    if OUTPUT_WIDTH % 2 != 0:
        OUTPUT_WIDTH += 1
    if OUTPUT_HEIGHT % 2 != 0:
        OUTPUT_HEIGHT += 1
    encode_preset = (ffmpeg_preset_override or FFMPEG_PRESET).strip() or FFMPEG_PRESET
    encode_crf = str(video_crf or "18")
    encode_maxrate = str(video_maxrate or "12M")
    encode_bufsize = str(video_bufsize or "24M")
    encode_audio_bitrate = str(audio_bitrate or "192k")
    scene_boundaries = []
    scene_strategies = []
    current_scene_index = 0
    speaker_tracker = None
    cameraman = None
    interview_tracker = None

    if interview_mode:
        print("   🤝 Interview mode enabled. Creating a two-speaker stacked layout.")
        cap = cv2.VideoCapture(input_video)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        interview_tracker = InterviewLayoutTracker(original_width, original_height)
        print("\n   ✂️ Step 1: Processing interview layout...")
    else:
        print("   Step 1: Detecting scenes...")
        scenes, fps = detect_scenes(input_video)
        
        if not scenes:
            print("   ❌ No scenes were detected. Using full video as one scene.")
            cap = cv2.VideoCapture(input_video)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            from scenedetect import FrameTimecode
            scenes = [(FrameTimecode(0, fps), FrameTimecode(total_frames, fps))]
        else:
            cap = cv2.VideoCapture(input_video)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(f"   ✅ Found {len(scenes)} scenes.")
        print("\n   🧠 Step 2: Preparing Active Tracking...")

        # Initialize Cameraman
        cameraman = SmoothedCameraman(OUTPUT_WIDTH, OUTPUT_HEIGHT, original_width, original_height)
        
        # --- New Strategy: Per-Scene Analysis ---
        print("\n   🤖 Step 3: Analyzing Scenes for Strategy (Single vs Group)...")
        scene_strategies = analyze_scenes_strategy(input_video, scenes)
        print("\n   ✂️ Step 4: Processing video frames...")

        # Pre-calculate scene boundaries
        for s_start, s_end in scenes:
            scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

        # Global tracker for single-person shots
        speaker_tracker = SpeakerTracker(cooldown_frames=30)

    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-',
        *ffmpeg_thread_args(),
        '-c:v', 'libx264',
        '-preset', encode_preset, '-crf', encode_crf,
        '-maxrate', encode_maxrate, '-bufsize', encode_bufsize,
        '-profile:v', 'high', '-level', '4.1',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        '-an', temp_video_output
    ]

    ffmpeg_process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **subprocess_priority_kwargs(),
    )
    
    frame_number = 0

    with tqdm(total=total_frames, desc="   Processing", file=sys.stdout) as pbar:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if interview_mode:
                if frame_number % 2 == 0:
                    interview_tracker.update(detect_face_candidates(frame), original_width)
                output_frame = create_interview_frame(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT, interview_tracker.get_boxes())
            else:
                # Update Scene Index
                if current_scene_index < len(scene_boundaries):
                    start_f, end_f = scene_boundaries[current_scene_index]
                    if frame_number >= end_f and current_scene_index < len(scene_boundaries) - 1:
                        current_scene_index += 1
                
                # Determine Strategy for current frame based on scene
                current_strategy = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
                
                # Apply Strategy
                if current_strategy == 'GENERAL':
                    # "Plano General" -> Blur Background + Fit Width
                    output_frame = create_general_frame(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                    
                    # Reset cameraman/tracker so they don't drift while inactive
                    cameraman.current_center_x = original_width / 2
                    cameraman.target_center_x = original_width / 2
                    
                else:
                    # "Single Speaker" -> Track & Crop
                    
                    # Detect every 2nd frame for performance
                    if frame_number % 2 == 0:
                        candidates = detect_face_candidates(frame)
                        target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                        if target_box:
                            cameraman.update_target(target_box)
                        else:
                            person_box = detect_person_yolo(frame)
                            if person_box:
                                cameraman.update_target(person_box)

                    # Snap camera on scene change to avoid panning from previous scene position
                    is_scene_start = (frame_number == scene_boundaries[current_scene_index][0])
                    
                    x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=is_scene_start)
                    
                    # Crop
                    if y2 > y1 and x2 > x1:
                        cropped = frame[y1:y2, x1:x2]
                        output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_CUBIC)
                    else:
                        output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_CUBIC)

            ffmpeg_process.stdin.write(output_frame.tobytes())
            frame_number += 1
            pbar.update(1)
    
    ffmpeg_process.stdin.close()
    stderr_output = ffmpeg_process.stderr.read().decode()
    ffmpeg_process.wait()
    cap.release()

    if ffmpeg_process.returncode != 0:
        print("\n   ❌ FFmpeg frame processing failed.")
        print("   Stderr:", stderr_output)
        return False

    print("\n   🔊 Step 5: Extracting audio...")
    audio_extract_command = [
        'ffmpeg', '-y', '-i', input_video, '-vn',
        *ffmpeg_thread_args(),
        '-c:a', 'aac', '-b:a', encode_audio_bitrate, temp_audio_output
    ]
    try:
        subprocess.run(
            audio_extract_command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
    except subprocess.CalledProcessError:
        print("\n   ❌ Audio extraction failed (maybe no audio?). Proceeding without audio.")
        pass

    print("\n   ✨ Step 6: Merging...")
    if os.path.exists(temp_audio_output):
        merge_command = [
            'ffmpeg', '-y', '-i', temp_video_output, '-i', temp_audio_output,
            *ffmpeg_thread_args(),
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', encode_audio_bitrate, '-movflags', '+faststart', final_output_video
        ]
    else:
         merge_command = [
            'ffmpeg', '-y', '-i', temp_video_output,
            *ffmpeg_thread_args(),
            '-c:v', 'copy', '-movflags', '+faststart', final_output_video
        ]
        
    try:
        subprocess.run(
            merge_command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        print(f"   ✅ Clip saved to {final_output_video}")
    except subprocess.CalledProcessError as e:
        print("\n   ❌ Final merge failed.")
        print("   Stderr:", e.stderr.decode())
        return False

    # Clean up temp files
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    
    return True

def _prepare_transcription_input(video_path):
    temp_audio_path = f"/tmp/openshorts_whisper_{os.getpid()}_{int(time.time() * 1000)}.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-fflags", "+discardcorrupt",
        "-err_detect", "ignore_err",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        temp_audio_path,
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 0:
            print("🎧 Prepared clean PCM audio for transcription.")
            return temp_audio_path
    except Exception as exc:
        print(f"⚠️ Audio pre-normalization failed, using source container directly: {exc}")

    try:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
    except Exception:
        pass
    return video_path

def transcribe_video(video_path):
    print("🎙️  Transcribing video with Faster-Whisper...")
    transcription_input = _prepare_transcription_input(video_path)
    cleanup_input = transcription_input != video_path
    try:
        segments, info, runtime_meta = transcribe_with_runtime(transcription_input, word_timestamps=True)
    finally:
        if cleanup_input:
            try:
                if os.path.exists(transcription_input):
                    os.remove(transcription_input)
            except Exception:
                pass
    
    print(
        "   Runtime: "
        f"{runtime_meta.get('model')} on {runtime_meta.get('device')} ({runtime_meta.get('compute_type')}), "
        f"beam={runtime_meta.get('beam_size')}, vad={runtime_meta.get('vad_filter')}, "
        f"lang={runtime_meta.get('requested_language', 'auto')}"
    )
    print(f"   Detected language '{info.language}' with probability {info.language_probability:.2f}")
    
    # Convert to openai-whisper compatible format
    transcript_segments = []
    full_text = ""
    
    for segment in segments:
        # Print progress to keep user informed (and prevent timeouts feeling)
        print(f"   [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
        
        seg_dict = {
            'text': segment.text,
            'start': segment.start,
            'end': segment.end,
            'words': []
        }
        
        if segment.words:
            for word in segment.words:
                seg_dict['words'].append({
                    'word': word.word,
                    'start': word.start,
                    'end': word.end,
                    'probability': word.probability
                })
        
        transcript_segments.append(seg_dict)
        full_text += segment.text + " "
        
    return {
        'text': full_text.strip(),
        'segments': transcript_segments,
        'language': info.language
    }

def _extract_words(transcript_result):
    words = []
    for segment in transcript_result['segments']:
        for word in segment.get('words', []):
            words.append({
                'w': word['word'],
                's': word['start'],
                'e': word['end']
            })
    return words


def get_viral_clips(transcript_result, video_duration, max_clip_duration=MAX_CLIP_DURATION, max_clips=MAX_GENERATED_CLIPS):
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider == "ollama":
        return get_viral_clips_via_ollama(transcript_result, video_duration, max_clip_duration=max_clip_duration, max_clips=max_clips)
    return get_viral_clips_via_gemini(transcript_result, video_duration, max_clip_duration=max_clip_duration, max_clips=max_clips)


def get_viral_clips_via_gemini(transcript_result, video_duration, max_clip_duration=MAX_CLIP_DURATION, max_clips=MAX_GENERATED_CLIPS):
    print("🤖  Analyzing with Gemini...")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None

    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    language_code, language_name = describe_output_language(transcript_result.get("language"))
    prompt = build_viral_prompt(
        video_duration,
        transcript_result["text"],
        _extract_words(transcript_result),
        output_language_code=language_code,
        output_language_name=language_name,
        max_clips=max_clips,
        max_clip_duration=max_clip_duration,
        min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
    )

    print(f"🤖  Initializing Gemini with model: {model_name}")

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        # --- Cost Calculation ---
        try:
            usage = response.usage_metadata
            if usage:
                # Gemini 2.5 Flash Pricing (Dec 2025)
                # Input: $0.10 per 1M tokens
                # Output: $0.40 per 1M tokens
                
                input_price_per_million = 0.10
                output_price_per_million = 0.40
                
                prompt_tokens = usage.prompt_token_count
                output_tokens = usage.candidates_token_count
                
                input_cost = (prompt_tokens / 1_000_000) * input_price_per_million
                output_cost = (output_tokens / 1_000_000) * output_price_per_million
                total_cost = input_cost + output_cost
                
                cost_analysis = {
                    "input_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "total_cost": total_cost,
                    "model": model_name
                }

                print(f"💰 Token Usage ({model_name}):")
                print(f"   - Input Tokens: {prompt_tokens} (${input_cost:.6f})")
                print(f"   - Output Tokens: {output_tokens} (${output_cost:.6f})")
                print(f"   - Total Estimated Cost: ${total_cost:.6f}")
                
        except Exception as e:
            print(f"⚠️ Could not calculate cost: {e}")
            cost_analysis = None
        # ------------------------

        result_json = _extract_json_payload(response.text)
        if not result_json:
            print(f"❌ Gemini returned invalid JSON.")
            return None
        if cost_analysis:
            result_json['cost_analysis'] = cost_analysis

        return sanitize_clip_candidates(
            result_json,
            video_duration,
            language_code=language_code,
            max_clips=max_clips,
            max_clip_duration=max_clip_duration,
            min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        )
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None


def _call_ollama(prompt, base_url, model_name):
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps({
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0.2}
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS) as response:
        outer = json.loads(response.read().decode("utf-8"))
    return outer, (outer.get("response") or "").strip()


def _read_http_error_body(exc):
    cached_body = getattr(exc, "_cached_body", None)
    if cached_body is not None:
        return cached_body
    try:
        cached_body = exc.read().decode("utf-8", errors="ignore")
    except Exception:
        cached_body = ""
    setattr(exc, "_cached_body", cached_body)
    return cached_body


def _ollama_model_not_found(exc, body, model_name):
    if not isinstance(exc, urllib.error.HTTPError) or exc.code != 404:
        return False
    lowered = (body or "").lower()
    return "model" in lowered and "not found" in lowered and model_name.lower() in lowered


def _warmup_ollama_model(base_url, model_name):
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps({
            "model": model_name,
            "prompt": "Reply only with {\"ok\":true}.",
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0,
                "num_predict": 8,
            },
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_WARMUP_TIMEOUT_SECONDS) as response:
        outer = json.loads(response.read().decode("utf-8"))
    return outer


def _call_ollama_with_retries(prompt, base_url, model_name):
    max_attempts = max(1, OLLAMA_RETRIES + 1)
    for attempt in range(1, max_attempts + 1):
        try:
            return _call_ollama(prompt, base_url, model_name)
        except urllib.error.HTTPError as exc:
            body = _read_http_error_body(exc)
            if _ollama_model_not_found(exc, body, model_name):
                raise ClipSelectionConfigurationError(
                    f"Ollama model '{model_name}' was not found at {base_url}. "
                    "Update the model name in Settings to an installed Ollama tag."
                ) from exc
            if attempt >= max_attempts:
                raise
            sleep_seconds = OLLAMA_RETRY_DELAY_SECONDS * attempt
            print(
                f"⚠️  Ollama request attempt {attempt}/{max_attempts} failed with "
                f"HTTPError: HTTP Error {exc.code}: {body or exc.reason}. Retrying in {sleep_seconds}s..."
            )
            time.sleep(sleep_seconds)
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            sleep_seconds = OLLAMA_RETRY_DELAY_SECONDS * attempt
            print(
                f"⚠️  Ollama request attempt {attempt}/{max_attempts} failed with "
                f"{type(exc).__name__}: {exc}. Retrying in {sleep_seconds}s..."
            )
            time.sleep(sleep_seconds)


def get_viral_clips_via_ollama(transcript_result, video_duration, max_clip_duration=MAX_CLIP_DURATION, max_clips=MAX_GENERATED_CLIPS):
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model_name = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    language_code, language_name = describe_output_language(transcript_result.get("language"))

    print(f"🦙  Analyzing with Ollama: {model_name} @ {base_url}")
    print(f"🗣️  Required output language: {language_name}")

    try:
        try:
            print(f"🔥 Warming up Ollama model {model_name} (timeout {OLLAMA_WARMUP_TIMEOUT_SECONDS}s)...")
            _warmup_ollama_model(base_url, model_name)
            print("✅ Ollama model is warm.")
        except urllib.error.HTTPError as warmup_exc:
            body = _read_http_error_body(warmup_exc)
            if _ollama_model_not_found(warmup_exc, body, model_name):
                raise ClipSelectionConfigurationError(
                    f"Ollama model '{model_name}' was not found at {base_url}. "
                    "Update the model name in Settings to an installed Ollama tag."
                ) from warmup_exc
            print(f"⚠️  Ollama warmup failed: HTTPError: HTTP Error {warmup_exc.code}: {body or warmup_exc.reason}. Continuing with direct request.")
        except Exception as warmup_exc:
            print(f"⚠️  Ollama warmup failed: {type(warmup_exc).__name__}: {warmup_exc}. Continuing with direct request.")

        windows = split_transcript_for_ollama(transcript_result)
        if not windows:
            return None

        if len(windows) > 1:
            print(f"🧩 Transcript is long. Running chunked Ollama analysis over {len(windows)} windows.")

        all_clips = []
        total_prompt_tokens = 0
        total_output_tokens = 0

        for idx, window in enumerate(windows):
            chunk_limit = max_clips if len(windows) == 1 else max(2, min(max_clips, math.ceil(max_clips / max(1, len(windows)))))
            prompt = build_ollama_prompt(
                video_duration,
                window,
                output_language_code=language_code,
                output_language_name=language_name,
                max_clips=chunk_limit,
                max_clip_duration=max_clip_duration,
                min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
            )
            print(f"🦙  Ollama chunk {idx + 1}/{len(windows)}: {window['start']:.1f}s - {window['end']:.1f}s")
            outer, text = _call_ollama_with_retries(prompt, base_url, model_name)
            total_prompt_tokens += outer.get("prompt_eval_count") or 0
            total_output_tokens += outer.get("eval_count") or 0

            if not text:
                print(f"⚠️  Ollama chunk {idx + 1} returned an empty response.")
                continue

            result_json = _extract_json_payload(text)
            if not result_json:
                print(f"⚠️  Ollama chunk {idx + 1} returned invalid JSON.")
                continue

            chunk_result = sanitize_clip_candidates(
                result_json,
                video_duration,
                language_code=language_code,
                max_clips=chunk_limit,
                max_clip_duration=max_clip_duration,
                min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
            )
            if not chunk_result:
                continue
            all_clips.extend(chunk_result["shorts"])

        if not all_clips:
            print("❌ Ollama did not return any valid clip candidates.")
            return None

        result_json = sanitize_clip_candidates(
            {"shorts": all_clips},
            video_duration,
            language_code=language_code,
            max_clips=max_clips,
            max_clip_duration=max_clip_duration,
            min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        )
        if not result_json:
            return None

        result_json["cost_analysis"] = {
            "model": model_name,
            "provider": "ollama",
            "input_tokens": total_prompt_tokens,
            "output_tokens": total_output_tokens,
            "input_cost": 0,
            "output_cost": 0,
            "total_cost": 0
        }
        return result_json
    except ClipSelectionConfigurationError:
        raise
    except urllib.error.HTTPError as e:
        body = _read_http_error_body(e)
        print(f"❌ Ollama HTTP Error: {e.code} {body}")
        return None
    except Exception as e:
        print(f"❌ Ollama Error: {e}")
        return None


def probe_video_stats(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0.0
    cap.release()
    return {
        "fps": fps,
        "frame_count": frame_count,
        "duration": duration,
    }


def resolve_whole_video_output(output_arg, output_dir, video_title):
    if output_arg and output_arg.lower().endswith(".mp4"):
        return output_arg
    return os.path.join(output_dir, f"{video_title}_vertical.mp4")


def build_fallback_metadata(video_title, duration, transcript, output_filename, reason):
    return {
        "generation_mode": "fallback_full_video",
        "fallback_reason": reason,
        "transcript": transcript,
        "shorts": [
            {
                "start": 0.0,
                "end": round(duration, 3),
                "video_title_for_youtube_short": f"{video_title} | Vertical Edit",
                "video_description_for_tiktok": "Full vertical fallback render generated after clip analysis failed.",
                "video_description_for_instagram": "Full vertical fallback render generated after clip analysis failed.",
                "viral_hook_text": "",
                "video_filename": os.path.basename(output_filename),
                "status": "completed",
            }
        ],
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="AutoCrop-Vertical with Viral Clip Detection.")
    
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('-i', '--input', type=str, help="Path to the input video file.")
    input_group.add_argument('-u', '--url', type=str, help="YouTube URL to download and process.")
    
    parser.add_argument('-o', '--output', type=str, help="Output directory or file (if processing whole video).")
    parser.add_argument('--keep-original', action='store_true', help="Keep the downloaded YouTube video.")
    parser.add_argument('--skip-analysis', action='store_true', help="Skip AI analysis and convert the whole video.")
    parser.add_argument('--resume', action='store_true', help="Resume a previous job using existing artifacts in the output directory.")
    parser.add_argument('--analysis-only', action='store_true', help="Run transcript + AI clip detection only. Do not render clips yet.")
    parser.add_argument('--interview-mode', action='store_true', help="Render in two-person interview layout with one detected speaker on top and one on bottom.")
    parser.add_argument('--allow-long-clips', action='store_true', help="Allow generated clips to exceed 60 seconds.")
    parser.add_argument('--max-clips', type=int, default=MAX_GENERATED_CLIPS, help=f"Maximum number of generated clips to keep (default: {MAX_GENERATED_CLIPS}).")
    parser.add_argument('--tight-edit-preset', type=str, default=DEFAULT_TIGHT_EDIT_PRESET_ENV, choices=sorted(TIGHT_EDIT_PRESETS.keys()), help=f"Automatically remove pauses and filler words using the selected preset (default: {DEFAULT_TIGHT_EDIT_PRESET_ENV}).")
    
    args = parser.parse_args()
    args.max_clips = max(1, min(50, args.max_clips or MAX_GENERATED_CLIPS))
    args.tight_edit_preset = normalize_tight_edit_preset(args.tight_edit_preset, DEFAULT_TIGHT_EDIT_PRESET_ENV)

    script_start_time = time.time()
    target_max_clip_duration = MAX_LONG_CLIP_DURATION if args.allow_long_clips else MAX_CLIP_DURATION
    
    def _ensure_dir(path: str) -> str:
        """Create directory if missing and return the same path."""
        if path:
            os.makedirs(path, exist_ok=True)
        return path
    
    # 1. Resolve output directory first
    if args.url:
        # For multi-clip runs, treat --output as an OUTPUT DIRECTORY (create it if needed).
        # For whole-video runs (--skip-analysis), --output can be a file path.
        if args.output and not args.skip_analysis:
            output_dir = _ensure_dir(args.output)
        else:
            # If output is a directory, use it; if it's a filename, use its directory; else default "."
            if args.output and os.path.isdir(args.output):
                output_dir = args.output
            elif args.output and not os.path.isdir(args.output):
                output_dir = os.path.dirname(args.output) or "."
            else:
                output_dir = "."
    else:
        input_video_hint = args.input
        
        if args.output and not args.skip_analysis:
            # For multi-clip runs, treat --output as an OUTPUT DIRECTORY (create it if needed).
            output_dir = _ensure_dir(args.output)
        else:
            # If output is a directory, use it; if it's a filename, use its directory; else default to input dir.
            if args.output and os.path.isdir(args.output):
                output_dir = args.output
            elif args.output and not os.path.isdir(args.output):
                output_dir = os.path.dirname(args.output) or os.path.dirname(input_video_hint)
            else:
                output_dir = os.path.dirname(input_video_hint)

    manifest = load_job_manifest(output_dir)
    pipeline = manifest.get("pipeline", {})
    input_video = None
    video_title = None

    if args.resume and pipeline.get("input_video") and os.path.exists(pipeline["input_video"]):
        input_video = pipeline["input_video"]
        video_title = pipeline.get("video_title") or os.path.splitext(os.path.basename(input_video))[0]
        print(f"♻️  Resuming from existing source video: {input_video}")
    elif args.url:
        input_video, video_title = download_youtube_video(args.url, output_dir)
    else:
        input_video = args.input
        video_title = os.path.splitext(os.path.basename(input_video))[0]

    if not input_video or not os.path.exists(input_video):
        print(f"❌ Input file not found: {input_video}")
        update_job_manifest(output_dir, {
            "status": "failed",
            "error": f"Input file not found: {input_video}",
            "can_resume": True,
        })
        sys.exit(1)

    update_job_manifest(output_dir, {
        "status": "processing",
        "error": None,
        "can_resume": True,
        "pipeline": {
            "input_video": input_video,
            "video_title": video_title,
            "mode": "whole_video" if args.skip_analysis else "clips",
            "analysis_only": bool(args.analysis_only),
            "layout_mode": "interview" if args.interview_mode else "auto",
            "max_clip_duration": target_max_clip_duration,
        }
    })

    video_stats = probe_video_stats(input_video)
    duration = video_stats["duration"]
    metadata_file = os.path.join(output_dir, f"{video_title}_metadata.json")
    transcript_file = os.path.join(output_dir, f"{video_title}_transcript.json")

    update_job_manifest(output_dir, {
        "pipeline": {
            "duration": duration,
            "metadata_file": metadata_file,
            "transcript_file": transcript_file,
        }
    })

    overall_success = False
    failed_outputs = 0
    completed_outputs = 0
    used_fallback = False
    analysis_failed = False
    transcript = None

    if args.skip_analysis:
        print("⏩ Skipping analysis, processing entire video...")
        output_file = resolve_whole_video_output(args.output, output_dir, video_title)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"♻️  Reusing existing vertical render: {output_file}")
            success = True
        else:
            success = process_video_to_vertical(input_video, output_file, interview_mode=args.interview_mode)

        if success:
            metadata = build_fallback_metadata(video_title, duration, None, output_file, "analysis_skipped")
            save_json_file(metadata_file, metadata)
            completed_outputs = 1
            overall_success = True
            used_fallback = True
    else:
        if args.resume and os.path.exists(transcript_file):
            transcript = load_json_file(transcript_file)
            if transcript:
                print(f"♻️  Reusing transcript: {transcript_file}")

        clips_data = None
        if args.resume and os.path.exists(metadata_file):
            clips_data = load_json_file(metadata_file)
            if clips_data:
                print(f"♻️  Reusing clip plan: {metadata_file}")
                if not transcript:
                    transcript = clips_data.get("transcript")
                if (
                    args.resume
                    and clips_data.get("generation_mode") == "fallback_full_video"
                    and clips_data.get("fallback_reason") in {"clip_analysis_failed", "all_clip_renders_failed"}
                ):
                    print("♻️  Existing metadata is fallback-only. Re-running clip analysis on resume.")
                    clips_data = None

        if not transcript:
            transcript = transcribe_video(input_video)
            save_json_file(transcript_file, transcript)
            update_job_manifest(output_dir, {
                "pipeline": {
                    "transcript_file": transcript_file,
                }
            })

        if not clips_data:
            try:
                clips_data = get_viral_clips(
                    transcript,
                    duration,
                    max_clip_duration=target_max_clip_duration,
                    max_clips=args.max_clips,
                )
            except ClipSelectionConfigurationError as exc:
                print(f"❌ {exc}")
                update_job_manifest(output_dir, {
                    "status": "failed",
                    "error": str(exc),
                    "can_resume": True,
                })
                sys.exit(1)

        if not clips_data or 'shorts' not in clips_data or not clips_data['shorts']:
            print("❌ Failed to identify clips. Converting whole video as fallback.")
            analysis_failed = True
            output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
            fallback_success = process_video_to_vertical(input_video, output_file, interview_mode=args.interview_mode)
            if fallback_success:
                metadata = build_fallback_metadata(video_title, duration, transcript, output_file, "clip_analysis_failed")
                save_json_file(metadata_file, metadata)
                completed_outputs = 1
                overall_success = True
                used_fallback = True
            else:
                failed_outputs += 1
        else:
            print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
            clips_data['transcript'] = transcript
            clips_data['generation_mode'] = 'clips'

            source_video_filename = os.path.basename(input_video)
            for i, clip in enumerate(clips_data['shorts']):
                clip_filename = clip.get('video_filename') or f"{video_title}_clip_{i+1}.mp4"
                clip['video_filename'] = clip_filename
                clip['source_video_filename'] = clip.get('source_video_filename') or source_video_filename
                clip['preview_start'] = round(float(clip.get('start', 0.0)), 3)
                clip['preview_end'] = round(float(clip.get('end', clip.get('start', 0.0))), 3)
                clip['display_duration'] = round(max(0.0, clip['preview_end'] - clip['preview_start']), 3)
                if clip.get('status') == 'completed':
                    continue
                clip['status'] = clip.get('status', 'pending')

            save_json_file(metadata_file, clips_data)
            print(f"   Saved metadata to {metadata_file}")

            if args.analysis_only:
                print("🧾 Analysis-only mode active: skipping clip rendering. Draft clips are ready for preview + on-demand render.")
                clips_data['generation_mode'] = 'analysis_only'
                for clip in clips_data['shorts']:
                    if clip.get('status') != 'completed':
                        clip['status'] = 'draft'
                save_json_file(metadata_file, clips_data)
                overall_success = True
                completed_outputs = len(clips_data['shorts'])
            else:
                for i, clip in enumerate(clips_data['shorts']):
                    start = clip['start']
                    end = clip['end']
                    clip_filename = clip['video_filename']
                    clip_temp_path = os.path.join(output_dir, f"temp_{clip_filename}")
                    clip_final_path = os.path.join(output_dir, clip_filename)

                    if os.path.exists(clip_final_path) and os.path.getsize(clip_final_path) > 0:
                        print(f"\n♻️  Skipping Clip {i+1}; output already exists: {clip_final_path}")
                        clip['status'] = 'completed'
                        clip.pop('error', None)
                        completed_outputs += 1
                        save_json_file(metadata_file, clips_data)
                        continue

                    print(f"\n🎬 Processing Clip {i+1}: {start}s - {end}s")
                    print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")

                    try:
                        tight_edit_plan = build_tight_edit_plan(transcript, start, end, args.tight_edit_preset)
                        keep_segments = tight_edit_plan.get("keep_segments") or [(start, end)]
                        if tight_edit_plan.get("compacted"):
                            print(
                                "   ✂️ Tight edit applied: "
                                f"{len(keep_segments)} keep segment(s), preset={args.tight_edit_preset}, "
                                f"new duration ≈ {tight_edit_plan.get('output_duration', end - start):.2f}s"
                            )
                        render_keep_segments(
                            input_video,
                            keep_segments,
                            clip_temp_path,
                            ffmpeg_preset=FFMPEG_PRESET,
                            crf="17",
                            audio_bitrate="192k",
                            thread_args=ffmpeg_thread_args(),
                            subprocess_kwargs=subprocess_priority_kwargs(),
                        )

                        if tight_edit_plan.get("compacted"):
                            clip["display_duration"] = tight_edit_plan.get("output_duration", round(end - start, 3))
                            clip["tight_edit_preset"] = args.tight_edit_preset
                            clip["tight_edit_removed_ranges"] = [
                                {"start": round(range_start, 3), "end": round(range_end, 3)}
                                for range_start, range_end in tight_edit_plan.get("remove_ranges", [])
                            ]
                            if len(keep_segments) == 1:
                                clip["start"] = round(keep_segments[0][0], 3)
                                clip["end"] = round(keep_segments[0][1], 3)
                                clip.pop("transcript_source", None)
                            else:
                                clip["transcript_source"] = "audio"
                        else:
                            clip["display_duration"] = round(end - start, 3)
                            clip.pop("tight_edit_preset", None)
                            clip.pop("tight_edit_removed_ranges", None)
                            clip.pop("transcript_source", None)

                        success = process_video_to_vertical(clip_temp_path, clip_final_path, interview_mode=args.interview_mode)
                        if success and os.path.exists(clip_final_path) and os.path.getsize(clip_final_path) > 0:
                            clip['status'] = 'completed'
                            clip.pop('error', None)
                            completed_outputs += 1
                            print(f"   ✅ Clip {i+1} ready: {clip_final_path}")
                        else:
                            clip['status'] = 'failed'
                            clip['error'] = 'Vertical processing failed'
                            failed_outputs += 1
                    except subprocess.CalledProcessError as e:
                        clip['status'] = 'failed'
                        clip['error'] = e.stderr.decode(errors='ignore')[-500:]
                        failed_outputs += 1
                        print(f"   ❌ Clip {i+1} cut failed.")
                    finally:
                        if os.path.exists(clip_temp_path):
                            os.remove(clip_temp_path)
                        save_json_file(metadata_file, clips_data)

                if completed_outputs > 0:
                    overall_success = True
                else:
                    print("⚠️  No clip outputs succeeded. Generating whole-video fallback.")
                    output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
                    fallback_success = process_video_to_vertical(input_video, output_file, interview_mode=args.interview_mode)
                    if fallback_success:
                        clips_data["fallback_output"] = os.path.basename(output_file)
                        clips_data["fallback_reason"] = "all_clip_renders_failed"
                        save_json_file(metadata_file, clips_data)
                        completed_outputs = 1
                        overall_success = True
                        used_fallback = True
                    else:
                        failed_outputs += 1

    manifest_status = "completed"
    if overall_success and (failed_outputs > 0 or (used_fallback and not args.skip_analysis and analysis_failed)):
        manifest_status = "partial"
    elif not overall_success:
        manifest_status = "failed"

    update_job_manifest(output_dir, {
        "status": manifest_status,
        "can_resume": failed_outputs > 0 or not overall_success or (used_fallback and not args.skip_analysis and analysis_failed),
        "error": None if overall_success else "Pipeline finished without any usable outputs.",
        "pipeline": {
            "input_video": input_video,
            "video_title": video_title,
            "metadata_file": metadata_file,
            "transcript_file": transcript_file if os.path.exists(transcript_file) else None,
            "completed_outputs": completed_outputs,
            "failed_outputs": failed_outputs,
            "used_fallback": used_fallback,
            "analysis_failed": analysis_failed,
            "analysis_only": bool(args.analysis_only),
            "layout_mode": "interview" if args.interview_mode else "auto",
            "max_clip_duration": target_max_clip_duration,
        }
    })

    # Clean up original only after a fully successful, non-resumable run.
    if args.url and not args.keep_original and not args.analysis_only and manifest_status == "completed" and os.path.exists(input_video):
        os.remove(input_video)
        print(f"🗑️  Cleaned up downloaded video.")

    total_time = time.time() - script_start_time
    print(f"\n⏱️  Total execution time: {total_time:.2f}s")
    sys.exit(0 if overall_success else 1)
