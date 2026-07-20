import time
import copy
import cv2
import scenedetect
import subprocess
import argparse
import re
import sys
import threading
import urllib.request
import urllib.error
import math
import shutil
from scenedetect import SceneManager, open_video
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
from video_encoding import selected_h264_encoding_args
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
TRACKING_DETECTION_FPS = max(1.0, float(os.environ.get("TRACKING_DETECTION_FPS", "10")))
MIN_CLIP_DURATION = float(os.environ.get("MIN_CLIP_DURATION", "60"))
MAX_CLIP_DURATION = float(os.environ.get("MAX_CLIP_DURATION", "180"))
MIN_OVER_ONE_MINUTE_CLIP_DURATION = 60.0
MAX_LONG_CLIP_DURATION = float(os.environ.get("MAX_LONG_CLIP_DURATION", "180"))
MAX_GENERATED_CLIPS = int(os.environ.get("MAX_GENERATED_CLIPS", "10"))
PREFERRED_MIN_CLIP_DURATION = float(os.environ.get("PREFERRED_MIN_CLIP_DURATION", "90"))
SHORT_CLIP_EXCEPTION_MIN_DURATION = float(os.environ.get("SHORT_CLIP_EXCEPTION_MIN_DURATION", "18"))
OLLAMA_CHUNK_SECONDS = int(os.environ.get("OLLAMA_CHUNK_SECONDS", "180"))
OLLAMA_CHUNK_OVERLAP_SECONDS = int(os.environ.get("OLLAMA_CHUNK_OVERLAP_SECONDS", "20"))
MINIMAX_CHUNK_SECONDS = int(os.environ.get("MINIMAX_CHUNK_SECONDS", "360"))
MINIMAX_CHUNK_OVERLAP_SECONDS = int(os.environ.get("MINIMAX_CHUNK_OVERLAP_SECONDS", "45"))
MINIMAX_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("MINIMAX_REQUEST_TIMEOUT_SECONDS", "240"))
MINIMAX_CONTEXT_SUMMARY_MAX_CHARS = int(os.environ.get("MINIMAX_CONTEXT_SUMMARY_MAX_CHARS", "200000"))
MINIMAX_FORCE_CHUNKED = str(os.environ.get("MINIMAX_FORCE_CHUNKED", "true")).strip().lower() in {"1", "true", "yes", "on"}
MINIMAX_USE_REMOTE_SUMMARY = str(os.environ.get("MINIMAX_USE_REMOTE_SUMMARY", "true")).strip().lower() in {"1", "true", "yes", "on"}
MINIMAX_THINKING_TYPE = str(os.environ.get("MINIMAX_THINKING_TYPE", "disabled")).strip().lower() or "disabled"
OLLAMA_RETRIES = int(os.environ.get("OLLAMA_RETRIES", "2"))
OLLAMA_RETRY_DELAY_SECONDS = int(os.environ.get("OLLAMA_RETRY_DELAY_SECONDS", "20"))
OLLAMA_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_REQUEST_TIMEOUT_SECONDS", "1800"))
OLLAMA_WARMUP_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_WARMUP_TIMEOUT_SECONDS", "300"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_MAX_SEGMENT_LINES = int(os.environ.get("OLLAMA_MAX_SEGMENT_LINES", "90"))
OLLAMA_MAX_PROMPT_CHARS = int(os.environ.get("OLLAMA_MAX_PROMPT_CHARS", "14000"))
CLIP_BOUNDARY_CONTEXT_SECONDS = float(os.environ.get("CLIP_BOUNDARY_CONTEXT_SECONDS", "30"))
CLIP_BOUNDARY_SEARCH_SECONDS = float(os.environ.get("CLIP_BOUNDARY_SEARCH_SECONDS", "14"))
CLIP_BOUNDARY_MIN_PAUSE_SECONDS = float(os.environ.get("CLIP_BOUNDARY_MIN_PAUSE_SECONDS", "0.7"))
CLIP_BOUNDARY_START_PAD_SECONDS = float(os.environ.get("CLIP_BOUNDARY_START_PAD_SECONDS", "0.18"))
CLIP_BOUNDARY_END_PAD_SECONDS = float(os.environ.get("CLIP_BOUNDARY_END_PAD_SECONDS", "0.28"))
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
You are a senior short-form video editor. Read the ENTIRE transcript and word-level timestamps to choose up to {max_clips} high-value long shorts for TikTok/IG Reels/YouTube Shorts. Each clip must be between {min_clip_duration} and {max_clip_duration} seconds long.

⚠️ FFMPEG TIME CONTRACT — STRICT REQUIREMENTS:
- Return timestamps in ABSOLUTE SECONDS from the start of the video (usable in: ffmpeg -ss <start> -to <end> -i <input> ...).
- Only NUMBERS with decimal point, up to 3 decimals (examples: 0, 1.250, 17.350).
- Ensure 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS.
- Each clip between {min_clip_duration} and {max_clip_duration} seconds (inclusive).
- HARD LENGTH RANGE: {min_clip_duration} to {max_clip_duration} seconds. Do not return clips outside this range.
- Prefer 90 to 150 seconds when that helps the story breathe.
- The clip must cover a complete, coherent thought: setup, claim/conflict, explanation, and payoff or meaningful open loop.
- Return fewer clips when only a few moments are truly strong. Quality beats count.
- Treat start/end as editorial boundaries, not as duration targets. The maximum duration is a ceiling, never a reason to cut off a sentence or payoff.
- Before choosing start, inspect at least 15 seconds before the hook. Include missing setup or an antecedent when the opening would otherwise begin as an answer, callback, pronoun reference, or continuation of an earlier sentence.
- Before choosing end, inspect at least 20 seconds after the planned endpoint. If the speaker is still completing the same answer, explanation, list, causal chain, or payoff, include the continuation or choose a different moment.
- Start at the first word of a self-contained sentence or thought. The first spoken words must make sense to a viewer who has not seen the full video.
- End only after the final sentence, conclusion, reaction, or intentional open loop is complete. Never end on a conjunction, subordinate clause, unfinished list, or transition into the actual payoff.
- Add only 0.15–0.35 s of silence/room tone around the chosen spoken boundaries. Padding must not introduce filler before the hook.
- Use sentence punctuation and real speech pauses for natural cuts; never cut in the middle of a word, phrase, or active thought.
- STRICTLY FORBIDDEN to use time formats other than absolute seconds.
- Every clip must feel semantically meaningful as a standalone short: it must contain a clear claim, insight, story beat, confession, conflict, payoff, or an unresolved but understandable curiosity gap.
- Reject clips that are mostly isolated keywords, sentence fragments, contextless filler, or references that only make sense if the viewer already knows the previous conversation.
- The FIRST spoken words of the clip must already be the hook, claim, reveal, tension, or provocative statement. Never start with filler such as "ok", "okay", "genau", "also", "ja", "gut", "äh", "ähm", "so", or a half-finished lead-in.
- Most clips should be at least {preferred_min_clip_duration} seconds long.
- Clips between {min_clip_duration} and {preferred_min_clip_duration} seconds are acceptable only when they are dense, self-contained, and still deliver a complete high-value thought.
- Clips shorter than {min_clip_duration} seconds are forbidden.
- If the transcript only contains a few truly strong moments, return fewer clips. Do NOT force the requested count with weak filler clips.

VIDEO_DURATION_SECONDS: {video_duration}

EDITORIAL_CONTEXT:
{editorial_context}

GLOBAL_CONTEXT_SUMMARY:
{global_context_summary}

SELECTION_SCOPE:
{chunk_hint}

TRANSCRIPT_TEXT (raw):
{transcript_text}

WORDS_JSON (array of {{w, s, e, spk?}} where s/e are seconds; spk is the
speaker label for that word when diarization is available, e.g. SPEAKER_00,
SPEAKER_01, HOST, GUEST, etc. Use spk to keep host vs. guest statements
strictly separate when choosing start/end):
{words_json}

STRICT EXCLUSIONS:
- No generic intros/outros or purely sponsorship segments unless they contain the hook.
- No clips shorter than {min_clip_duration} seconds or longer than {max_clip_duration} seconds.
- No short punchline-only excerpts. The clip must have enough context to be useful without the full video.
- Return at most {max_clips} clips.
- The transcript language is {output_language_name} (code: {output_language_code}).
- ALL user-facing text fields MUST stay in {output_language_name}: `video_description_for_tiktok`, `video_description_for_instagram`, `video_title_for_youtube_short`, and `viral_hook_text`.
- NEVER translate the content into English unless the transcript itself is English.
- If the transcript is German, every title, description, and hook must be German.
- STYLE: Use "Scroll-Stopper" copywriting. No boring summaries. Use the "Curiosity Gap" technique.
- VIRAL_HOOK_TEXT: Max 5 words. Make it aggressive, controversial, or mysterious. Use "STOP doing X", "The secret to Y", or "POV: You just Z".
- VIDEO_TITLE: Max 40 characters. High-impact keywords only. No full sentences.
- VIDEO_DESCRIPTION: The FIRST sentence must instantly be interesting, provocative, surprising, or curiosity-driven. It must work as a scroll-stopper even if a viewer only reads that first sentence. Start with a punchy first line that creates FOMO (Fear Of Missing Out).

SPEAKER ATTRIBUTION — MANDATORY:
- The upload profile/channel owner in EDITORIAL_CONTEXT is editorial background only. NEVER assume that this person is the speaker or owner of a story.
- In interviews, distinguish the questioner/host from every respondent/guest and from third parties mentioned in the conversation.
- Attribute first-person experiences ("ich", "mein Bruder", "meine Familie") only to the speaker who actually says them. A host asking a question does not own the guest's biography.
- When converting first-person speech into third-person copy, preserve the speaker's actual grammatical gender: e.g. a male guest saying "mein Bruder" becomes "sein Bruder", not "ihr Bruder". A female speaker becomes "ihr Bruder".
- If speaker identity or gender is not supported by the labeled transcript, use neutral wording such as "Warum der Bruder ausgeschlossen wurde". Never guess based on the channel profile.
- Do not merge the host's identity with a guest's experience. Do not assign one speaker's claim, family, exit, trauma, or belief to another speaker.

OUTPUT — RETURN ONLY VALID JSON (no markdown, no comments). Order clips by predicted performance (best to worst). In the descriptions, ALWAYS include a CTA like "Follow me and comment X and I'll send you the workflow" (especially if discussing an n8n workflow):
{{
  "shorts": [
    {{
      "start": <number in seconds, e.g., 12.340>,
      "end": <number in seconds, e.g., 37.900>,
      "video_description_for_tiktok": "<description for TikTok oriented to get views>",
      "video_description_for_instagram": "<description for Instagram oriented to get views>",
      "video_title_for_youtube_short": "<title for YouTube Short oriented to get views 100 chars max>",
      "viral_hook_text": "<SHORT punchy text overlay (max 10 words). MUST BE IN THE SAME LANGUAGE AS THE VIDEO TRANSCRIPT. Examples: 'POV: You realized...', 'Did you know?', 'Stop doing this!'>",
      "subject_speaker": "<speaker label from transcript, or unknown>",
      "speaker_attribution_confidence": <number from 0 to 1>
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
- HARD LENGTH RANGE: {min_clip_duration} to {max_clip_duration} seconds. Do not return clips outside this range.
- Prefer 90 to 150 seconds when that helps the story breathe.
- The clip must cover a complete, coherent thought: setup, claim/conflict, explanation, and payoff or meaningful open loop.
- Return fewer clips when only a few moments are truly strong. Quality beats count.
- Prefer conflict, surprise, confession, tension, controversy, emotional payoff, concrete insights, and moments that stop the scroll.
- Avoid filler, greetings, outros, sponsor sections, and context that has no payoff.
- Treat start/end as editorial boundaries, not as duration targets. The maximum duration is a ceiling, never a reason to cut off a sentence or payoff.
- Inspect the supplied context before and after each possible moment. Include missing setup when an opening is an answer, callback, pronoun reference, or continuation.
- Start at the first word of a self-contained sentence or thought. The first spoken words must make sense without the previous conversation.
- End only after the full answer, explanation, causal chain, list, conclusion, reaction, or intentional open loop is complete.
- Inspect at least 20 seconds after a planned end. If the speaker continues the same important thought, include it or choose another candidate.
- Add only 0.15–0.35 s of silence around spoken boundaries. Never spend the opening seconds on filler or pre-hook chatter.
- Every clip must make sense as a standalone short: clear thought, conflict, insight, story beat, or understandable teaser with enough context.
- Reject clips that are just fragments, disconnected buzzwords, filler, or incomplete context without payoff.
- The FIRST spoken words of the clip must already be the hook, claim, reveal, tension, or provocative statement. Never start with filler such as "ok", "okay", "genau", "also", "ja", "gut", "äh", "ähm", "so", or a half-finished lead-in.
- Most clips should be at least {preferred_min_clip_duration} seconds long.
- Clips between {min_clip_duration} and {preferred_min_clip_duration} seconds are acceptable only when they are dense, self-contained, and still deliver a complete high-value thought.
- Clips shorter than {min_clip_duration} seconds are forbidden.
- If the transcript only contains a few truly strong moments, return fewer clips. Do NOT force the requested count with weak filler clips.
- The transcript language is {output_language_name} (code: {output_language_code}).
- ALL user-facing text fields MUST be written in {output_language_name}: `video_description_for_tiktok`, `video_description_for_instagram`, `video_title_for_youtube_short`, and `viral_hook_text`.
- NEVER translate the transcript into English unless the transcript itself is English.
- If the transcript is German, every title, description, and hook must be German.
- Return ONLY valid JSON, no markdown and no extra text.
- STYLE: Use "Scroll-Stopper" copywriting. No boring summaries. Use the "Curiosity Gap" technique.
- VIRAL_HOOK_TEXT: Max 5 words. Make it aggressive, controversial, or mysterious. Use "STOP doing X", "The secret to Y", or "POV: You just Z".
- VIDEO_TITLE: Max 40 characters. High-impact keywords only. No full sentences.
- VIDEO_DESCRIPTION: The FIRST sentence must instantly be interesting, provocative, surprising, or curiosity-driven. It must work as a scroll-stopper even if a viewer only reads that first sentence. Start with a punchy first line that creates FOMO (Fear Of Missing Out).

SPEAKER ATTRIBUTION — MANDATORY:
- The upload profile/channel owner in EDITORIAL_CONTEXT is editorial background only. NEVER assume that this person is the speaker or owner of a story.
- Use the SPEAKER labels in TRANSCRIPT_SEGMENTS to separate host/questioner, guest/respondent, and mentioned third parties.
- Attribute first-person experiences only to the labeled speaker who says them. Questions from the host do not make the guest's biography the host's biography.
- Preserve grammatical gender when rewriting first-person statements: a male speaker saying "mein Bruder" becomes "sein Bruder"; a female speaker becomes "ihr Bruder".
- If identity or gender is uncertain, avoid names and gendered possessives. Prefer neutral wording such as "Warum der Bruder ausgeschlossen wurde".
- Never combine the host's identity with the guest's family, exit, trauma, beliefs, or personal history.

VIDEO_DURATION_SECONDS: {video_duration}
CANDIDATE_FOCUS_RANGE_SECONDS: {chunk_start} - {chunk_end}
SURROUNDING_CONTEXT_RANGE_SECONDS: {context_start} - {context_end}

Choose moments whose hook/start belongs to CANDIDATE_FOCUS_RANGE_SECONDS. Use the wider surrounding context to repair setup and payoff boundaries. Do not return a clip if its complete thought is not visible in the supplied context.

EDITORIAL_CONTEXT:
{editorial_context}

GLOBAL_CONTEXT_SUMMARY:
{global_context_summary}

TRANSCRIPT_SEGMENTS (each line: [start-end SPEAKER] text; lines starting with
WORDS: contain per-word timings as token|start|end|speaker so the model can
pick exact word-aligned clip boundaries AND keep host vs. guest separate):
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
      "viral_hook_text": "<very short hook overlay in the same language as the transcript, max 10 words>",
      "subject_speaker": "<speaker label from transcript, or unknown>",
      "speaker_attribution_confidence": <number from 0 to 1>
    }}
  ]
}}
"""

TRANSCRIPT_CONTEXT_SUMMARY_PROMPT_TEMPLATE = """
You are preparing context for short-form clip selection.

Summarize the FULL transcript in {output_language_name} as plain text for another editor model.

EDITORIAL_CONTEXT (channel positioning and job-specific instructions; obey it when framing the summary):
{editorial_context}

Requirements:
- 4 to 7 short bullet points
- Capture the central topic, the main tensions/conflicts, the strongest claims, the important reveals, and the overall narrative arc
- Mention what would count as real standalone value for a short from this video
- Mention any especially controversial or emotionally charged subtopics if present
- Keep host, guests, and mentioned third parties separate. State whose experience, family, belief, or biography each point belongs to.
- The channel owner from EDITORIAL_CONTEXT is not automatically the speaker or subject.
- No markdown code fences
- No JSON

TRANSCRIPT_TEXT:
{transcript_text}
"""

HOOK_GENERATION_PROMPT_TEMPLATE = """
You are a senior short-form video hook copywriter.

Task:
- Write exactly one ultra-short on-screen hook for each clip.
- The hook must be in {output_language_name} (code: {output_language_code}).
- Preferred length: 2 to 6 words. Hard max: 8 words.
- Make it reisserisch: curiosity gap, tension, surprise, conflict, payoff.
- No hashtags. No quotes. No emojis. No generic filler like "wait for the ending".
- Return ONLY valid JSON. No markdown. No commentary.

EDITORIAL_CONTEXT:
{editorial_context}

FULL_TRANSCRIPT_CONTEXT_SUMMARY:
{global_context_summary}

CLIPS_JSON:
{clips_json}

OUTPUT JSON:
{{
  "hooks": [
    {{
      "clip_index": <integer>,
      "viral_hook_text": "<very short hook overlay>"
    }}
  ]
}}
"""

INTERVIEW_ATTRIBUTION_REVIEW_PROMPT_TEMPLATE = """
You are the final factual copy editor for interview-based short-form clips.

Review every candidate against its SPEAKER-LABELED transcript excerpt. Rewrite title, hook, and both descriptions when attribution is wrong or ambiguous. Do not change clip_index, start, or end.

STRICT RULES:
- EDITORIAL_CONTEXT describes the channel and its owner. It does NOT identify the speaker or subject of a clip.
- Keep host/questioner, guest/respondent, and mentioned third parties separate.
- A question from the host does not make the guest's experience the host's biography.
- Attribute "ich", "mein Bruder", "meine Familie", personal exits, trauma, beliefs, and experiences only to the speaker who says them.
- Preserve grammatical gender when converting first-person speech to third person. Example: a male guest saying "mein Bruder" must become "sein Bruder", never "ihr Bruder".
- If the labeled excerpt does not establish gender or identity, use neutral copy such as "Warum der Bruder ausgeschlossen wurde". Never guess from the channel profile.
- Do not invent names, relationships, events, motives, or quotes.
- Keep all copy in {output_language_name}.
- Titles: max 60 characters. Hooks: max 8 words. Descriptions: engaging but factually faithful.
- Return ONLY valid JSON.

EDITORIAL_CONTEXT:
{editorial_context}

FULL_TRANSCRIPT_CONTEXT_SUMMARY:
{global_context_summary}

CANDIDATES_JSON:
{candidates_json}

OUTPUT JSON:
{{
  "clips": [
    {{
      "clip_index": <integer>,
      "video_title_for_youtube_short": "<fact-checked title>",
      "viral_hook_text": "<fact-checked hook>",
      "video_description_for_tiktok": "<fact-checked description>",
      "video_description_for_instagram": "<fact-checked description>",
      "subject_speaker": "<speaker label or unknown>",
      "speaker_attribution_confidence": <number from 0 to 1>
    }}
  ]
}}
"""

# Load the YOLO model once (Keep for backup or scene analysis if needed)
model = YOLO(YOLO_MODEL_PATH)
YOLO_DEVICE = 0 if torch.cuda.is_available() else "cpu"


def _load_shortform_editorial_context():
    context = {}
    context_path = str(os.environ.get("SHORTFORM_ANALYSIS_CONTEXT_FILE") or "").strip()
    if context_path:
        try:
            with open(context_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                context.update(loaded)
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"⚠️ Could not read short-form analysis context: {exc}")

    context.setdefault("profile_name", os.environ.get("SHORTFORM_UPLOAD_PROFILE", ""))
    context.setdefault("profile_context", os.environ.get("SHORTFORM_PROFILE_CONTEXT", ""))
    context.setdefault("job_instructions", os.environ.get("SHORTFORM_JOB_INSTRUCTIONS", ""))
    return context


def _format_shortform_editorial_context():
    context = _load_shortform_editorial_context()
    profile_name = re.sub(r"\s+", " ", str(context.get("profile_name") or "")).strip()
    profile_context = re.sub(r"\s+", " ", str(context.get("profile_context") or "")).strip()
    job_instructions = re.sub(r"\s+", " ", str(context.get("job_instructions") or "")).strip()
    lines = []
    if profile_name:
        lines.append(f"Upload profile/channel: {profile_name}")
    if profile_context:
        lines.append(f"Channel positioning, audience and goals: {profile_context}")
    if job_instructions:
        lines.append(f"Mandatory instructions for this job: {job_instructions}")
    return "\n".join(lines) or "No additional channel or job instructions provided."


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
    minimum_long_clips=0,
    chunk_hint="",
    global_context_summary="",
):
    def _fmt_number(value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value
        return int(numeric) if numeric.is_integer() else numeric

    min_clip_duration_fmt = _fmt_number(min_clip_duration)
    max_clip_duration_fmt = _fmt_number(max_clip_duration)

    return GEMINI_PROMPT_TEMPLATE.format(
        video_duration=video_duration,
        transcript_text=json.dumps(transcript_text),
        words_json=json.dumps(words),
        output_language_code=output_language_code,
        output_language_name=output_language_name,
        max_clips=max_clips,
        min_clip_duration=min_clip_duration_fmt,
        preferred_min_clip_duration=_fmt_number(PREFERRED_MIN_CLIP_DURATION),
        max_clip_duration=max_clip_duration_fmt,
        chunk_hint=(chunk_hint or "Use the full transcript. Review local context before and after every proposed clip."),
        editorial_context=_format_shortform_editorial_context(),
        global_context_summary=(global_context_summary or "No extra summary available."),
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


def _extract_chat_message_text(payload):
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return _extract_chat_message_text(payload.get("content"))
    if isinstance(payload, list):
        parts = []
        for item in payload:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    parts.append(stripped)
                continue
            if isinstance(item, dict):
                candidate_text = item.get("text")
                if candidate_text is None:
                    candidate_text = item.get("content")
                if candidate_text is None and isinstance(item.get("output_text"), str):
                    candidate_text = item.get("output_text")
                extracted = _extract_chat_message_text(candidate_text)
                if extracted.strip():
                    parts.append(extracted.strip())
        return "\n".join(parts).strip()
    return ""


def _minimax_chat_endpoint(base_url):
    normalized = str(base_url or "https://api.minimax.io/v1").rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/text/chatcompletion_v2"):
        return normalized[: -len("/text/chatcompletion_v2")] + "/chat/completions"
    return f"{normalized}/chat/completions"


def _minimax_response_diagnostics(body):
    diagnostics = {
        "status_msg": "",
        "status_code": None,
        "finish_reason": "",
        "choices_count": 0,
        "input_sensitive": None,
        "input_sensitive_type": None,
        "output_sensitive": None,
        "output_sensitive_type": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "response_keys": [],
        "message_keys": [],
    }
    if not isinstance(body, dict):
        return diagnostics

    diagnostics["response_keys"] = sorted(str(key) for key in body.keys())
    base_resp = body.get("base_resp")
    if isinstance(base_resp, dict):
        diagnostics["status_msg"] = str(base_resp.get("status_msg") or base_resp.get("statusMessage") or "").strip()
        diagnostics["status_code"] = base_resp.get("status_code")
    for key in ("input_sensitive", "input_sensitive_type", "output_sensitive", "output_sensitive_type"):
        if key in body:
            diagnostics[key] = body.get(key)
    usage = body.get("usage")
    if isinstance(usage, dict):
        diagnostics["prompt_tokens"] = usage.get("prompt_tokens")
        diagnostics["completion_tokens"] = usage.get("completion_tokens")
        diagnostics["total_tokens"] = usage.get("total_tokens")
    choices = body.get("choices")
    if isinstance(choices, list):
        diagnostics["choices_count"] = len(choices)
        if choices and isinstance(choices[0], dict):
            diagnostics["finish_reason"] = str(choices[0].get("finish_reason") or "").strip()
            message = choices[0].get("message")
            if isinstance(message, dict):
                diagnostics["message_keys"] = sorted(str(key) for key in message.keys())
    return diagnostics


def _format_minimax_diagnostics(diagnostics):
    parts = []
    for key in (
        "status_code",
        "status_msg",
        "finish_reason",
        "choices_count",
        "input_sensitive",
        "input_sensitive_type",
        "output_sensitive",
        "output_sensitive_type",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        value = diagnostics.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    if diagnostics.get("message_keys"):
        parts.append(f"message_keys={','.join(diagnostics['message_keys'])}")
    if diagnostics.get("response_keys"):
        parts.append(f"response_keys={','.join(diagnostics['response_keys'])}")
    return "; ".join(parts) or "keine Diagnosefelder"


def _is_minimax_sensitive_empty_response(diagnostics):
    if diagnostics.get("input_sensitive") is True or diagnostics.get("output_sensitive") is True:
        return True
    status_msg = str(diagnostics.get("status_msg") or "").lower()
    return "sensitive" in status_msg or "violation" in status_msg or "content" in status_msg and "empty" in status_msg


def _extract_minimax_response_text(body):
    status_msg = ""
    raw_text = ""
    diagnostics = _minimax_response_diagnostics(body)
    if isinstance(body, dict):
        base_resp = body.get("base_resp")
        if isinstance(base_resp, dict):
            status_msg = str(base_resp.get("status_msg") or base_resp.get("statusMessage") or "").strip()
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            raw_text = (
                _extract_chat_message_text((first_choice or {}).get("message"))
                or _extract_chat_message_text((first_choice or {}).get("delta"))
                or _extract_chat_message_text((first_choice or {}).get("text"))
            )
        if not raw_text:
            raw_text = (
                _extract_chat_message_text(body.get("reply"))
                or _extract_chat_message_text(body.get("content"))
                or _extract_chat_message_text(body.get("output_text"))
                or _extract_chat_message_text(body.get("text"))
                or _extract_chat_message_text(body.get("message"))
            )
    return raw_text.strip(), status_msg, diagnostics


def _post_json(url, payload, headers, timeout_seconds=120):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        detail = body[:2000] if body else str(exc.reason or "")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {detail}") from exc


def _call_openai_json(prompt, model_name):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ClipSelectionConfigurationError("OPENAI_API_KEY fehlt.")

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a senior short-form editor. Reply only with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 4000,
    }
    body = _post_json(
        "https://api.openai.com/v1/chat/completions",
        payload,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        timeout_seconds=180,
    )
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI lieferte keine choices.")
    raw_text = _extract_chat_message_text((choices[0] or {}).get("message"))
    return _extract_json_payload(raw_text)


def _call_claude_json(prompt, model_name):
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ClipSelectionConfigurationError("CLAUDE_API_KEY fehlt.")

    payload = {
        "model": model_name,
        "max_tokens": 4000,
        "temperature": 0.2,
        "system": "You are a senior short-form editor. Reply only with valid JSON.",
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }
    body = _post_json(
        "https://api.anthropic.com/v1/messages",
        payload,
        {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        timeout_seconds=180,
    )
    raw_text = _extract_chat_message_text(body.get("content"))
    return _extract_json_payload(raw_text)


def _default_minimax_model():
    auth_mode = str(os.getenv("MINIMAX_AUTH_MODE") or "token_plan").strip().lower()
    if auth_mode in {"token_plan", "payg"}:
        return "MiniMax-M3"
    return "MiniMax-M3"


def _candidate_minimax_models(requested_model):
    auth_mode = str(os.getenv("MINIMAX_AUTH_MODE") or "token_plan").strip().lower()
    alias_map = {
        "minimax-text-01": "MiniMax-M3",
        "minimax-m1": "MiniMax-M3",
        "minimax-m2.7": "MiniMax-M2.7",
        "minimax-m3": "MiniMax-M3",
    }
    normalized_requested = str(requested_model or "").strip()
    if normalized_requested:
        normalized_requested = alias_map.get(normalized_requested.lower(), normalized_requested)
    if not normalized_requested:
        normalized_requested = _default_minimax_model()

    candidates = [normalized_requested]
    if auth_mode == "token_plan":
        candidates.extend([
            "MiniMax-M3",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.5",
            "MiniMax-M2.1-highspeed",
            "MiniMax-M2.1",
            "MiniMax-M2",
        ])
    else:
        candidates.extend([
            "MiniMax-M3",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.1",
            "MiniMax-M2.1-highspeed",
            "MiniMax-M2",
        ])

    deduped = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _call_minimax_json(prompt, model_name):
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ClipSelectionConfigurationError("MINIMAX_API_KEY fehlt.")

    base_url = str(os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
    last_detail = ""
    for candidate_model in _candidate_minimax_models(model_name):
        is_m3 = str(candidate_model).strip().lower() == "minimax-m3"
        default_max_tokens = 8000 if is_m3 else 6000
        try:
            max_tokens = int(os.getenv("MINIMAX_JSON_MAX_TOKENS", str(default_max_tokens)))
        except (TypeError, ValueError):
            max_tokens = default_max_tokens
        completion_tokens = max(1000, max_tokens)
        payload = {
            "model": candidate_model,
            "messages": [
                {"role": "system", "content": "You are a senior short-form editor. Reply only with valid JSON. Do not include markdown."},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": completion_tokens,
            "temperature": 0.2,
            "stream": False,
        }
        if is_m3:
            payload["thinking"] = {"type": MINIMAX_THINKING_TYPE if MINIMAX_THINKING_TYPE in {"disabled", "adaptive"} else "disabled"}
            payload["reasoning_split"] = True
        request_started_at = time.time()
        print(
            f"🌐 MiniMax request started: model={candidate_model}, "
            f"timeout={MINIMAX_REQUEST_TIMEOUT_SECONDS}s, max_completion_tokens={payload['max_completion_tokens']}, "
            f"prompt_chars={len(prompt)}"
        )
        body = _post_json(
            _minimax_chat_endpoint(base_url),
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout_seconds=MINIMAX_REQUEST_TIMEOUT_SECONDS,
        )
        print(f"✅ MiniMax response received from {candidate_model} after {time.time() - request_started_at:.1f}s")
        raw_text, status_msg, diagnostics = _extract_minimax_response_text(body)
        print(f"🔎 MiniMax response diagnostics: {_format_minimax_diagnostics(diagnostics)}")
        if raw_text:
            parsed = _extract_json_payload(raw_text)
            if parsed is not None:
                return parsed
            last_detail = f"MiniMax lieferte kein gueltiges JSON. {_format_minimax_diagnostics(diagnostics)}"
            break

        last_detail = status_msg or f"MiniMax lieferte keinen nutzbaren Antworttext. {_format_minimax_diagnostics(diagnostics)}"
        if _is_minimax_sensitive_empty_response(diagnostics):
            break
        if "not support model" in last_detail.lower():
            continue
        break

    raise RuntimeError(f"MiniMax-Antwort unbrauchbar: {last_detail}")


def _call_minimax_text(prompt, model_name):
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ClipSelectionConfigurationError("MINIMAX_API_KEY fehlt.")

    base_url = str(os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
    last_detail = ""
    for candidate_model in _candidate_minimax_models(model_name):
        is_m3 = str(candidate_model).strip().lower() == "minimax-m3"
        payload = {
            "model": candidate_model,
            "messages": [
                {"role": "system", "content": "You are a senior transcript analyst. Reply with plain text only."},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": 2500,
            "temperature": 0.2,
            "stream": False,
        }
        if is_m3:
            payload["thinking"] = {"type": MINIMAX_THINKING_TYPE if MINIMAX_THINKING_TYPE in {"disabled", "adaptive"} else "disabled"}
            payload["reasoning_split"] = True
        body = _post_json(
            _minimax_chat_endpoint(base_url),
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout_seconds=MINIMAX_REQUEST_TIMEOUT_SECONDS,
        )
        raw_text, status_msg, diagnostics = _extract_minimax_response_text(body)
        if raw_text:
            return raw_text.strip()

        last_detail = status_msg or f"MiniMax lieferte keinen nutzbaren Antworttext. {_format_minimax_diagnostics(diagnostics)}"
        if _is_minimax_sensitive_empty_response(diagnostics):
            break
        if "not support model" in last_detail.lower():
            continue
        break

    raise RuntimeError(f"MiniMax-Textantwort unbrauchbar: {last_detail}")


def _call_shortform_provider_json(provider_name, prompt, *, model_name=None):
    normalized_provider = (provider_name or "gemini").strip().lower()
    if normalized_provider == "openai":
        return _call_openai_json(prompt, model_name or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    if normalized_provider == "claude":
        return _call_claude_json(prompt, model_name or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest"))
    if normalized_provider == "minimax":
        return _call_minimax_json(prompt, model_name or os.getenv("MINIMAX_MODEL", _default_minimax_model()))
    raise ClipSelectionConfigurationError(f"Unsupported provider '{normalized_provider}'")


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
            "viral_hook_text": "",
        }
    if normalized == "es":
        return {
            "video_description_for_tiktok": "Clip viral del video.",
            "video_description_for_instagram": "Fragmento potente del video.",
            "video_title_for_youtube_short": "Short generado para YouTube",
            "viral_hook_text": "",
        }
    return {
        "video_description_for_tiktok": "Generated TikTok caption.",
        "video_description_for_instagram": "Generated Instagram caption.",
        "video_title_for_youtube_short": "Generated YouTube Short",
        "viral_hook_text": "",
    }


HOOK_PLACEHOLDER_TEXTS = {
    "",
    "wait for the ending",
    "warte bis zum ende",
    "espera hasta el final",
    "pov:",
    "pov: ...",
    "pov: das darfst du nicht verpassen",
    "text hier eingeben",
    "text hier eingeben...",
}


def _sanitize_hook_candidate_text(value, max_words=8, max_chars=80):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.strip("\"'` ")
    if not text:
        return ""

    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).strip()

    if len(text) > max_chars:
        text = text[:max_chars].rstrip(" ,.;:-!?")
    return text


def _normalize_hook_text_for_compare(value):
    text = _sanitize_hook_candidate_text(value)
    text = text.lower().strip()
    text = re.sub(r"[!?.,:;]+$", "", text)
    return text


def _is_placeholder_hook_text(value):
    return _normalize_hook_text_for_compare(value) in HOOK_PLACEHOLDER_TEXTS


def _collect_transcript_excerpt_for_range(transcript_result, clip_start, clip_end, max_chars=320):
    if not isinstance(transcript_result, dict):
        return ""

    segments = transcript_result.get("speaker_segments") or transcript_result.get("segments")
    if not isinstance(segments, list):
        return ""

    parts = []
    total_chars = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seg_start = _coerce_float(segment.get("start"))
        seg_end = _coerce_float(segment.get("end"))
        if seg_start is None:
            seg_start = 0.0
        if seg_end is None:
            seg_end = seg_start
        if seg_end <= clip_start or seg_start >= clip_end:
            continue

        text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
        if not text:
            continue
        speaker = re.sub(r"\s+", " ", str(segment.get("speaker") or "")).strip()
        part = f"[{speaker}] {text}" if speaker else text
        parts.append(part)
        total_chars += len(part) + 1
        if total_chars >= max_chars:
            break

    excerpt = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 3].rstrip() + "..."
    return excerpt


def _build_heuristic_transcript_context_summary(transcript_result, output_language_name="English"):
    if not isinstance(transcript_result, dict):
        return f"- No transcript summary available.\n- Language: {output_language_name}"

    text = re.sub(r"\s+", " ", str(transcript_result.get("text") or "")).strip()
    segments = transcript_result.get("segments") or []
    if not text:
        return f"- No transcript summary available.\n- Language: {output_language_name}"

    bullet_sources = []
    if isinstance(segments, list) and segments:
        sample_indices = sorted({0, max(0, len(segments) // 3), max(0, (2 * len(segments)) // 3), len(segments) - 1})
        for idx in sample_indices:
            segment = segments[idx] if 0 <= idx < len(segments) else None
            if not isinstance(segment, dict):
                continue
            snippet = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
            if snippet:
                bullet_sources.append(snippet)

    if not bullet_sources:
        bullet_sources.append(text[:800])

    bullets = []
    for snippet in bullet_sources:
        cleaned = snippet[:220].rstrip(" ,.;:-")
        if cleaned and cleaned not in bullets:
            bullets.append(f"- {cleaned}")
        if len(bullets) >= 5:
            break
    if not bullets:
        bullets = [f"- {text[:220].rstrip(' ,.;:-')}"]
    return "\n".join(bullets)


def _build_transcript_context_summary(transcript_result, *, provider_name, model_name, output_language_code="en", output_language_name="English"):
    speaker_segments = (transcript_result or {}).get("speaker_segments") or []
    if speaker_segments:
        text = "\n".join(
            f"[{segment.get('speaker') or 'UNKNOWN'} {float(segment.get('start') or 0.0):.2f}-{float(segment.get('end') or 0.0):.2f}] "
            f"{' '.join(str(segment.get('text') or '').split())}"
            for segment in speaker_segments
            if str(segment.get("text") or "").strip()
        )
    else:
        text = re.sub(r"\s+", " ", str((transcript_result or {}).get("text") or "")).strip()
    if not text:
        return _build_heuristic_transcript_context_summary(transcript_result, output_language_name=output_language_name)

    normalized_provider = (provider_name or "").strip().lower()
    if normalized_provider == "minimax" and not MINIMAX_USE_REMOTE_SUMMARY:
        return _build_heuristic_transcript_context_summary(transcript_result, output_language_name=output_language_name)

    summary_max_chars = 28000
    if normalized_provider == "minimax" and _is_minimax_m3(model_name):
        summary_max_chars = max(summary_max_chars, MINIMAX_CONTEXT_SUMMARY_MAX_CHARS)

    prompt = TRANSCRIPT_CONTEXT_SUMMARY_PROMPT_TEMPLATE.format(
        output_language_code=output_language_code,
        output_language_name=output_language_name,
        transcript_text=text[:summary_max_chars],
        editorial_context=_format_shortform_editorial_context(),
    )
    if normalized_provider == "minimax":
        try:
            summary = _call_minimax_text(prompt, model_name)
            summary = re.sub(r"\s+\n", "\n", str(summary or "")).strip()
            if summary:
                return summary
        except Exception as exc:
            print(f"⚠️  MiniMax transcript summary failed, using heuristic context summary: {exc}")

    return _build_heuristic_transcript_context_summary(transcript_result, output_language_name=output_language_name)


def _build_hook_generation_contexts(clips, transcript_result):
    contexts = []
    for clip_index, clip in enumerate(clips or []):
        if not isinstance(clip, dict):
            continue
        if not _is_placeholder_hook_text(clip.get("viral_hook_text")):
            continue

        start = _coerce_float(clip.get("start"))
        end = _coerce_float(clip.get("end"))
        if start is None:
            start = 0.0
        if end is None:
            end = start

        contexts.append(
            {
                "clip_index": clip_index,
                "start": round(start, 3),
                "end": round(end, 3),
                "title": str(clip.get("video_title_for_youtube_short") or "").strip(),
                "description": str(
                    clip.get("video_description_for_tiktok")
                    or clip.get("video_description_for_instagram")
                    or ""
                ).strip(),
                "transcript_excerpt": _collect_transcript_excerpt_for_range(
                    transcript_result,
                    start,
                    end,
                ),
            }
        )
    return contexts


def _build_hook_generation_prompt(
    clip_contexts,
    output_language_code="en",
    output_language_name="English",
    global_context_summary="",
):
    return HOOK_GENERATION_PROMPT_TEMPLATE.format(
        output_language_code=output_language_code,
        output_language_name=output_language_name,
        clips_json=json.dumps(clip_contexts, ensure_ascii=False),
        editorial_context=_format_shortform_editorial_context(),
        global_context_summary=(global_context_summary or "No full-transcript summary available."),
    )


def _apply_generated_hook_payload(clips, payload):
    if not isinstance(payload, dict):
        return 0

    raw_hooks = payload.get("hooks")
    if not isinstance(raw_hooks, list):
        return 0

    updated = 0
    for item in raw_hooks:
        if not isinstance(item, dict):
            continue
        try:
            clip_index = int(item.get("clip_index"))
        except (TypeError, ValueError):
            continue
        if clip_index < 0 or clip_index >= len(clips):
            continue

        hook_text = _sanitize_hook_candidate_text(item.get("viral_hook_text"))
        if not hook_text:
            continue
        clips[clip_index]["viral_hook_text"] = hook_text
        updated += 1
    return updated


def _ensure_generated_clip_hooks(
    result_json,
    transcript_result,
    *,
    provider_name,
    output_language_code="en",
    output_language_name="English",
    gemini_client=None,
    gemini_model_name=None,
    ollama_base_url=None,
    ollama_model_name=None,
):
    if not isinstance(result_json, dict):
        return result_json

    clips = result_json.get("shorts")
    if not isinstance(clips, list) or not clips:
        return result_json

    clip_contexts = _build_hook_generation_contexts(clips, transcript_result)
    if not clip_contexts:
        return result_json

    batch_size = max(1, _env_int("HOOK_GENERATION_BATCH_SIZE", 20))
    global_context_summary = str(result_json.get("analysis_context_summary") or "").strip()
    if not global_context_summary:
        global_context_summary = _build_heuristic_transcript_context_summary(
            transcript_result,
            output_language_name=output_language_name,
        )
    print(f"🪝 Generating AI hook suggestions for {len(clip_contexts)} clips...")

    for batch_start in range(0, len(clip_contexts), batch_size):
        batch = clip_contexts[batch_start : batch_start + batch_size]
        prompt = _build_hook_generation_prompt(
            batch,
            output_language_code=output_language_code,
            output_language_name=output_language_name,
            global_context_summary=global_context_summary,
        )

        try:
            if provider_name == "ollama":
                if not ollama_base_url or not ollama_model_name:
                    continue
                _, response_text = _call_ollama_with_retries(prompt, ollama_base_url, ollama_model_name)
                payload = _extract_json_payload(response_text)
            elif provider_name == "gemini":
                if gemini_client is None or not gemini_model_name:
                    continue
                response = gemini_client.models.generate_content(
                    model=gemini_model_name,
                    contents=prompt,
                )
                payload = _extract_json_payload(response.text)
            else:
                provider_model = None
                if provider_name == "openai":
                    provider_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
                elif provider_name == "claude":
                    provider_model = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")
                elif provider_name == "minimax":
                    provider_model = os.getenv("MINIMAX_MODEL", _default_minimax_model())
                payload = _call_shortform_provider_json(provider_name, prompt, model_name=provider_model)

            updated = _apply_generated_hook_payload(clips, payload)
            print(f"🪝 Hook suggestions updated for {updated}/{len(batch)} clips in batch.")
        except Exception as exc:
            print(f"⚠️ Failed to generate hook suggestions for clip batch: {exc}")

    return result_json


def _clip_overlap_ratio(a_start, a_end, b_start, b_end):
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    min_len = max(0.001, min(a_end - a_start, b_end - b_start))
    return overlap / min_len


SEMANTIC_WEAK_EDGE_TOKENS = {
    "und", "oder", "aber", "also", "dann", "halt", "eben", "eigentlich", "quasi", "so",
    "weil", "dass", "wenn", "nur", "noch", "mal", "ja", "ne", "nee", "hm", "okay",
    "the", "and", "or", "but", "so", "then", "like", "just", "well", "okay", "yeah",
}

OPENING_FILLER_TOKENS = {
    "ok", "okay", "genau", "also", "ja", "gut", "äh", "aeh", "ähm", "aehm", "hm", "hmm",
    "mhm", "so", "und", "aber", "nee", "ne", "nun", "well", "yeah",
}

CONTEXT_DEPENDENT_OPENING_TOKENS = {
    "er", "ihm", "dessen", "deren", "davon", "dadurch", "darauf", "dabei", "trotzdem",
    "deshalb", "deswegen", "danach", "he", "she", "him", "her", "them", "therefore",
    "afterwards", "because",
}

ENDING_CONTINUATION_TOKENS = {
    "und", "oder", "aber", "weil", "dass", "wenn", "obwohl", "während", "waehrend",
    "bevor", "nachdem", "damit", "denn", "sondern", "wie", "als", "and", "or", "but",
    "because", "if", "although", "while", "before", "after", "that", "so",
}


def _timed_transcript_words(transcript_result):
    segments = (transcript_result or {}).get("segments", [])
    if not isinstance(segments, list):
        return []

    words = []
    for segment_index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        segment_words = segment.get("words") or []
        for word in segment_words:
            if not isinstance(word, dict):
                continue
            start = _coerce_float(word.get("start"))
            end = _coerce_float(word.get("end"))
            text = re.sub(r"\s+", " ", str(word.get("word") or "")).strip()
            if start is None or end is None or end <= start or not text:
                continue
            words.append({
                "text": text,
                "start": start,
                "end": end,
                "segment_index": segment_index,
                "segment_fallback": False,
            })

    if not words:
        for segment_index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            start = _coerce_float(segment.get("start"))
            end = _coerce_float(segment.get("end"))
            text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
            if start is None or end is None or end <= start or not text:
                continue
            words.append({
                "text": text,
                "start": start,
                "end": end,
                "segment_index": segment_index,
                "segment_fallback": True,
            })

    words.sort(key=lambda item: (item["start"], item["end"]))
    deduped = []
    seen = set()
    for word in words:
        key = (round(word["start"], 3), round(word["end"], 3), word["text"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(word)
    return deduped


def _has_terminal_punctuation(value):
    return bool(re.search(r"[.!?…][\"'”’)}\]]*$", str(value or "").strip()))


def _edge_alpha_token(value, *, first=True):
    tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", str(value or "").lower())
    if not tokens:
        return ""
    return tokens[0] if first else tokens[-1]


def _word_gap(words, left_index, right_index):
    if left_index < 0 or right_index >= len(words):
        return float("inf")
    return max(0.0, words[right_index]["start"] - words[left_index]["end"])


def _is_natural_start_boundary(words, index):
    if index <= 0:
        return True
    previous = words[index - 1]
    current = words[index]
    if _has_terminal_punctuation(previous["text"]):
        return True
    if _word_gap(words, index - 1, index) >= CLIP_BOUNDARY_MIN_PAUSE_SECONDS:
        return True
    return bool(previous.get("segment_fallback") or current.get("segment_fallback"))


def _is_natural_end_boundary(words, index):
    if index >= len(words) - 1:
        return True
    current = words[index]
    following = words[index + 1]
    if _has_terminal_punctuation(current["text"]):
        return True
    if _word_gap(words, index, index + 1) >= CLIP_BOUNDARY_MIN_PAUSE_SECONDS:
        return True
    return bool(current.get("segment_fallback") or following.get("segment_fallback"))


def _clip_edge_word_indices(words, start, end):
    included = [
        index
        for index, word in enumerate(words)
        if word["end"] > start and word["start"] < end
    ]
    if not included:
        return None, None
    return included[0], included[-1]


def _refine_clip_boundaries(
    transcript_result,
    start,
    end,
    video_duration,
    min_clip_duration,
    max_clip_duration,
):
    words = _timed_transcript_words(transcript_result)
    if not words:
        return None

    raw_start = max(0.0, min(float(start), float(video_duration)))
    raw_end = max(0.0, min(float(end), float(video_duration)))
    if raw_end <= raw_start:
        return None

    search = max(2.0, CLIP_BOUNDARY_SEARCH_SECONDS)
    start_targets = (raw_start, max(0.0, raw_end - max_clip_duration), max(0.0, raw_end - min_clip_duration))
    end_targets = (raw_end, min(video_duration, raw_start + min_clip_duration), min(video_duration, raw_start + max_clip_duration))

    start_candidates = []
    end_candidates = []
    for index, word in enumerate(words):
        near_start_target = any(abs(word["start"] - target) <= search for target in start_targets)
        near_end_target = any(abs(word["end"] - target) <= search for target in end_targets)
        if near_start_target and _is_natural_start_boundary(words, index):
            padded_start = max(0.0, word["start"] - CLIP_BOUNDARY_START_PAD_SECONDS)
            if index > 0:
                padded_start = max(padded_start, min(word["start"], words[index - 1]["end"] + 0.02))
            start_candidates.append((index, padded_start))
        if near_end_target and _is_natural_end_boundary(words, index):
            padded_end = min(video_duration, word["end"] + CLIP_BOUNDARY_END_PAD_SECONDS)
            if index < len(words) - 1:
                padded_end = min(padded_end, max(word["end"], words[index + 1]["start"] - 0.02))
            end_candidates.append((index, padded_end))

    if not start_candidates or not end_candidates:
        return None

    raw_duration = raw_end - raw_start
    target_duration = min(max(raw_duration, min_clip_duration), max_clip_duration)
    minimum_core_overlap = min(raw_duration, max_clip_duration) * 0.5
    best = None
    for start_index, candidate_start in start_candidates:
        opening_token = _edge_alpha_token(words[start_index]["text"], first=True)
        opening_penalty = 0.0
        if opening_token in OPENING_FILLER_TOKENS:
            opening_penalty = 100.0
        elif opening_token in CONTEXT_DEPENDENT_OPENING_TOKENS:
            opening_penalty = 55.0

        for end_index, candidate_end in end_candidates:
            if end_index < start_index:
                continue
            duration = candidate_end - candidate_start
            if duration + 0.001 < min_clip_duration or duration - 0.001 > max_clip_duration:
                continue

            core_overlap = max(0.0, min(candidate_end, raw_end) - max(candidate_start, raw_start))
            if core_overlap + 0.001 < minimum_core_overlap:
                continue

            ending_token = _edge_alpha_token(words[end_index]["text"], first=False)
            has_terminal_punctuation = _has_terminal_punctuation(words[end_index]["text"])
            ending_penalty = 100.0 if ending_token in ENDING_CONTINUATION_TOKENS and not has_terminal_punctuation else 0.0
            if not has_terminal_punctuation:
                ending_penalty += 3.0

            trimmed_start = max(0.0, candidate_start - raw_start)
            trimmed_end = max(0.0, raw_end - candidate_end)
            added_start = max(0.0, raw_start - candidate_start)
            added_end = max(0.0, candidate_end - raw_end)
            score = (
                opening_penalty
                + ending_penalty
                + (trimmed_start * 4.0)
                + (trimmed_end * 7.0)
                + (added_start * 0.7)
                + (added_end * 0.45)
                + (abs(duration - target_duration) * 0.05)
            )
            if best is None or score < best[0]:
                best = (score, candidate_start, candidate_end, words[start_index], words[end_index])

    if best is None:
        return None

    _, refined_start, refined_end, first_word, last_word = best
    return {
        "start": round(refined_start, 3),
        "end": round(refined_end, 3),
        "adjustment": {
            "method": "transcript_sentence_pause_boundaries",
            "original_start": round(raw_start, 3),
            "original_end": round(raw_end, 3),
            "start_shift": round(refined_start - raw_start, 3),
            "end_shift": round(refined_end - raw_end, 3),
            "opening_words": re.sub(r"\s+", " ", first_word["text"]).strip()[:120],
            "closing_words": re.sub(r"\s+", " ", last_word["text"]).strip()[-120:],
        },
    }


def _extract_transcript_window_text(transcript_result, start, end):
    return " ".join(_extract_transcript_window_words(transcript_result, start, end)).strip()


def _extract_transcript_window_words(transcript_result, start, end):
    return [
        word["text"]
        for word in _timed_transcript_words(transcript_result)
        if word["end"] > start and word["start"] < end
    ]


def _normalize_alpha_tokens(tokens):
    normalized = []
    for token in tokens:
        normalized.extend(re.findall(r"[A-Za-zÄÖÜäöüß]+", str(token or "").lower()))
    return normalized


def _assess_clip_opening_quality(transcript_result, start, end):
    words = _timed_transcript_words(transcript_result)
    first_index, _ = _clip_edge_word_indices(words, start, end)
    if first_index is None:
        return False, "too_few_opening_words"
    if not _is_natural_start_boundary(words, first_index):
        return False, "starts_mid_thought"

    first_token = _edge_alpha_token(words[first_index]["text"], first=True)
    if first_token in CONTEXT_DEPENDENT_OPENING_TOKENS:
        return False, f"contextless_opening:{first_token}"

    alpha_tokens = _normalize_alpha_tokens(_extract_transcript_window_words(transcript_result, start, min(end, start + 6.0)))
    if len(alpha_tokens) < 4:
        return False, "too_few_opening_words"

    if alpha_tokens[0] in OPENING_FILLER_TOKENS:
        return False, f"starts_with_filler:{alpha_tokens[0]}"

    lead_tokens = alpha_tokens[:5]
    strong_lead_tokens = [token for token in lead_tokens if token not in OPENING_FILLER_TOKENS and len(token) > 2]
    if len(strong_lead_tokens) < 2:
        return False, "weak_opening_hook"
    return True, "ok"


def _assess_clip_ending_quality(transcript_result, start, end):
    words = _timed_transcript_words(transcript_result)
    _, last_index = _clip_edge_word_indices(words, start, end)
    if last_index is None:
        return False, "too_few_closing_words"
    if not _is_natural_end_boundary(words, last_index):
        return False, "ends_mid_thought"

    last_token = _edge_alpha_token(words[last_index]["text"], first=False)
    if last_token in ENDING_CONTINUATION_TOKENS and not _has_terminal_punctuation(words[last_index]["text"]):
        return False, f"incomplete_ending:{last_token}"
    return True, "ok"


def _collect_clip_quality_flags(transcript_result, start, end):
    if not transcript_result:
        return []

    flags = []
    opening_ok, opening_detail = _assess_clip_opening_quality(transcript_result, start, end)
    if not opening_ok:
        if opening_detail == "starts_mid_thought":
            flags.append({
                "type": "starts_mid_thought",
                "detail": "",
                "label": "Startet mitten im Gedanken",
            })
        elif opening_detail.startswith("contextless_opening:"):
            opening_token = opening_detail.split(":", 1)[1].strip() or "unknown"
            flags.append({
                "type": "contextless_opening",
                "detail": opening_token,
                "label": f"Unklarer Einstieg ohne Bezug ({opening_token})",
            })
        elif opening_detail.startswith("starts_with_filler:"):
            filler_token = opening_detail.split(":", 1)[1].strip() or "unknown"
            flags.append({
                "type": "starts_with_filler",
                "detail": filler_token,
                "label": f"Startet mit Fuellwort ({filler_token})",
            })
        elif opening_detail == "weak_opening_hook":
            flags.append({
                "type": "weak_opening_hook",
                "detail": "",
                "label": "Schwacher Einstieg",
            })
        elif opening_detail == "too_few_opening_words":
            flags.append({
                "type": "too_few_opening_words",
                "detail": "",
                "label": "Zu wenig klare Einstiegswoerter",
            })

    ending_ok, ending_detail = _assess_clip_ending_quality(transcript_result, start, end)
    if not ending_ok:
        if ending_detail == "ends_mid_thought":
            flags.append({
                "type": "ends_mid_thought",
                "detail": "",
                "label": "Endet mitten im Gedanken",
            })
        elif ending_detail.startswith("incomplete_ending:"):
            ending_token = ending_detail.split(":", 1)[1].strip() or "unknown"
            flags.append({
                "type": "incomplete_ending",
                "detail": ending_token,
                "label": f"Unvollstaendiger Schluss ({ending_token})",
            })
        elif ending_detail == "too_few_closing_words":
            flags.append({
                "type": "too_few_closing_words",
                "detail": "",
                "label": "Kein klarer Abschluss erkennbar",
            })
    return flags


def _qualifies_short_clip_exception(transcript_result, start, end):
    duration = max(0.0, end - start)
    if duration < SHORT_CLIP_EXCEPTION_MIN_DURATION:
        return False

    opening_ok, _ = _assess_clip_opening_quality(transcript_result, start, end)
    if not opening_ok:
        return False

    window_text = _extract_transcript_window_text(transcript_result, start, end)
    alpha_tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", window_text.lower())
    content_tokens = [token for token in alpha_tokens if len(token) > 2 and token not in OPENING_FILLER_TOKENS]
    longest_sentence = max(
        (
            len(re.findall(r"[A-Za-zÄÖÜäöüß]+", sentence))
            for sentence in re.split(r"[.!?…]+", window_text)
            if sentence.strip()
        ),
        default=0,
    )

    return len(content_tokens) >= 14 and longest_sentence >= 8


def _assess_clip_semantic_quality(transcript_result, start, end):
    window_text = _extract_transcript_window_text(transcript_result, start, end)
    if not window_text:
        return False, "empty_context"

    alpha_tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", window_text.lower())
    if len(alpha_tokens) < 8:
        return False, "too_few_words"

    content_tokens = [token for token in alpha_tokens if len(token) > 2]
    if len(content_tokens) < 5:
        return False, "too_little_content"

    unique_ratio = len(set(content_tokens)) / max(1, len(content_tokens))
    longest_sentence = max(
        (
            len(re.findall(r"[A-Za-zÄÖÜäöüß]+", sentence))
            for sentence in re.split(r"[.!?…]+", window_text)
            if sentence.strip()
        ),
        default=0,
    )
    weak_edge_hits = int(alpha_tokens[0] in SEMANTIC_WEAK_EDGE_TOKENS) + int(alpha_tokens[-1] in SEMANTIC_WEAK_EDGE_TOKENS)

    if unique_ratio < 0.34 and longest_sentence < 7:
        return False, "fragmentary_context"
    if longest_sentence < 5 and weak_edge_hits >= 1:
        return False, "incomplete_thought"

    return True, window_text


def sanitize_clip_candidates(
    raw_data,
    video_duration,
    transcript_result=None,
    language_code="en",
    max_clips=MAX_GENERATED_CLIPS,
    min_clip_duration=MIN_CLIP_DURATION,
    max_clip_duration=MAX_CLIP_DURATION,
    min_over_one_minute_clip_duration=None,
    preferred_min_clip_duration=PREFERRED_MIN_CLIP_DURATION,
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

        boundary_adjustment = None
        duration = end - start
        short_exception = False
        if transcript_result:
            refined = _refine_clip_boundaries(
                transcript_result,
                start,
                end,
                video_duration,
                min_clip_duration,
                max_clip_duration,
            )
            if not refined:
                print(
                    "⚠️  Rejecting clip candidate without viable complete-thought boundaries: "
                    f"{start:.2f}-{end:.2f}s"
                )
                continue
            start = refined["start"]
            end = refined["end"]
            boundary_adjustment = refined["adjustment"]
            duration = end - start
        else:
            if duration < min_clip_duration:
                midpoint = start + (duration / 2.0)
                start = max(0.0, midpoint - (min_clip_duration / 2.0))
                end = min(video_duration, start + min_clip_duration)
                start = max(0.0, end - min_clip_duration)
                if (end - start) < min_clip_duration:
                    continue
            elif duration > max_clip_duration:
                end = min(video_duration, start + max_clip_duration)
                duration = end - start

        if (
            not transcript_result
            and min_over_one_minute_clip_duration
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

        effective_duration = end - start
        if effective_duration < min_clip_duration:
            continue

        duplicate = False
        for existing in sanitized:
            if _clip_overlap_ratio(start, end, existing["start"], existing["end"]) > 0.85:
                duplicate = True
                break
        if duplicate:
            continue

        if transcript_result:
            quality_flags = _collect_clip_quality_flags(transcript_result, start, end)
            fatal_boundary_flags = {
                "starts_mid_thought",
                "contextless_opening",
                "starts_with_filler",
                "too_few_opening_words",
                "ends_mid_thought",
                "incomplete_ending",
                "too_few_closing_words",
            }
            fatal_flags = [
                flag.get("type")
                for flag in quality_flags
                if flag.get("type") in fatal_boundary_flags
            ]
            if fatal_flags:
                print(
                    "⚠️  Rejecting clip candidate with incomplete or contextless edges: "
                    f"{start:.2f}-{end:.2f}s ({', '.join(fatal_flags)})"
                )
                continue
            semantic_ok, semantic_detail = _assess_clip_semantic_quality(transcript_result, start, end)
            if not semantic_ok:
                print(
                    "⚠️  Rejecting clip candidate without enough standalone meaning: "
                    f"{start:.2f}-{end:.2f}s ({semantic_detail})"
                )
                continue
            if effective_duration < preferred_min_clip_duration and not short_exception:
                content_token_count = len(re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", semantic_detail))
                if content_token_count < 18:
                    print(
                        "⚠️  Rejecting short low-context clip candidate: "
                        f"{start:.2f}-{end:.2f}s (content_tokens={content_token_count})"
                    )
                    continue

        sanitized.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "video_description_for_tiktok": clip.get("video_description_for_tiktok") or defaults["video_description_for_tiktok"],
            "video_description_for_instagram": clip.get("video_description_for_instagram") or clip.get("video_description_for_tiktok") or defaults["video_description_for_instagram"],
            "video_title_for_youtube_short": clip.get("video_title_for_youtube_short") or defaults["video_title_for_youtube_short"],
            "viral_hook_text": _sanitize_hook_candidate_text(clip.get("viral_hook_text")) or defaults["viral_hook_text"],
            "subject_speaker": re.sub(r"\s+", " ", str(clip.get("subject_speaker") or "unknown")).strip()[:80],
            "speaker_attribution_confidence": max(
                0.0,
                min(1.0, _coerce_float(clip.get("speaker_attribution_confidence")) or 0.0),
            ),
            "quality_flags": quality_flags if transcript_result else [],
            "boundary_adjustment": boundary_adjustment,
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


def _count_long_clip_candidates(result_json):
    if not isinstance(result_json, dict):
        return 0
    shorts = result_json.get("shorts")
    if not isinstance(shorts, list):
        return 0
    total = 0
    for clip in shorts:
        if not isinstance(clip, dict):
            continue
        start = _coerce_float(clip.get("start"))
        end = _coerce_float(clip.get("end"))
        if start is None or end is None:
            continue
        if end - start > MAX_CLIP_DURATION:
            total += 1
    return total


def _target_long_clip_count(max_clip_duration, max_clips):
    if max_clip_duration <= MAX_CLIP_DURATION:
        return 0
    if max_clips >= 20:
        return 20
    return min(max_clips, max(4, math.ceil(max_clips * 0.4)))


def _should_retry_for_long_clips(result_json, max_clip_duration, max_clips):
    target = _target_long_clip_count(max_clip_duration, max_clips)
    return target > 0 and _count_long_clip_candidates(result_json) < target


def _build_long_clip_retry_prompt(prompt, current_long_count, target_long_count):
    return (
        f"{prompt}\n\n"
        "RETRY REQUIREMENT:\n"
        f"Your previous output only produced {current_long_count} clips longer than 60 seconds.\n"
        f"Search again and add more strong >60s candidates until you reach around {target_long_count} long clips, if the transcript truly supports that many.\n"
        "Focus on longer story beats, explanations, conflicts, reveals, debates, emotional arcs, or multi-part payoffs that justify 60s+ runtime.\n"
        "Keep the quality bar high. Do not invent timestamps, and do not pad weak moments just to make them longer.\n"
        "Return a fresh JSON list of strong clips, with special attention to additional long-form-worthy moments.\n"
    )


def _merge_long_clip_results(base_result, supplemental_result, max_clips):
    if not isinstance(base_result, dict):
        return supplemental_result
    if not isinstance(supplemental_result, dict):
        return base_result

    base_clips = list(base_result.get("shorts") or [])
    supplemental_clips = list(supplemental_result.get("shorts") or [])
    if not supplemental_clips:
        return base_result

    merged = list(base_clips)
    for candidate in supplemental_clips:
        if not isinstance(candidate, dict):
            continue
        duration = float(candidate.get("end", 0) or 0) - float(candidate.get("start", 0) or 0)
        if duration <= MAX_CLIP_DURATION:
            continue
        duplicate = False
        for existing in merged:
            if _clip_overlap_ratio(
                float(candidate.get("start", 0) or 0),
                float(candidate.get("end", 0) or 0),
                float(existing.get("start", 0) or 0),
                float(existing.get("end", 0) or 0),
            ) > 0.85:
                duplicate = True
                break
        if duplicate:
            continue
        merged.append(candidate)
        if len(merged) >= max_clips:
            break

    next_result = dict(base_result)
    next_result["shorts"] = merged[:max_clips]
    return next_result


def _should_use_chunked_chat_provider(provider_name, transcript_result, model_name=None):
    provider_name = (provider_name or "").strip().lower()
    text_length = len(str(transcript_result.get("text") or ""))
    segment_count = len(transcript_result.get("segments") or [])
    if provider_name == "minimax":
        return MINIMAX_FORCE_CHUNKED or text_length > 6000 or segment_count > 20
    return False


def _is_minimax_m3(model_name) -> bool:
    return str(model_name or "").strip().lower() == "minimax-m3"


def _call_shortform_provider_json_with_retries(provider_name, prompt, *, model_name=None, max_attempts=2, retry_label="provider"):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _call_shortform_provider_json(provider_name, prompt, model_name=model_name)
        except ClipSelectionConfigurationError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            wait_seconds = 1.25 * attempt
            print(
                f"⚠️  {provider_name.title()} {retry_label} attempt {attempt}/{max_attempts} failed: "
                f"{exc}. Retrying in {wait_seconds:.2f}s..."
            )
            time.sleep(wait_seconds)
    if last_exc:
        raise last_exc
    return None


def _active_shortform_provider_model(provider_name):
    provider_name = str(provider_name or "").strip().lower()
    if provider_name == "minimax":
        return os.getenv("MINIMAX_MODEL", "MiniMax-M3")
    if provider_name == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if provider_name == "claude":
        return os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")
    if provider_name == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if provider_name == "ollama":
        return os.getenv("OLLAMA_MODEL", "")
    return None


def review_interview_clip_attribution(result_json, transcript_result, output_language_code="de", output_language_name="German (Deutsch)"):
    if not isinstance(result_json, dict) or not isinstance(result_json.get("shorts"), list):
        return result_json

    clips = result_json["shorts"]
    if not clips:
        return result_json

    provider_name = str(os.getenv("LLM_PROVIDER") or "gemini").strip().lower()
    model_name = _active_shortform_provider_model(provider_name)
    global_context_summary = str(result_json.get("analysis_context_summary") or "").strip()
    if not global_context_summary:
        global_context_summary = _build_heuristic_transcript_context_summary(
            transcript_result,
            output_language_name=output_language_name,
        )

    batch_size = max(1, _env_int("INTERVIEW_ATTRIBUTION_REVIEW_BATCH_SIZE", 8))
    reviewed_count = 0
    print(f"🧭 Reviewing speaker attribution for {len(clips)} interview clips...")
    for batch_start in range(0, len(clips), batch_size):
        candidates = []
        for clip_index in range(batch_start, min(len(clips), batch_start + batch_size)):
            clip = clips[clip_index]
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or start)
            candidates.append({
                "clip_index": clip_index,
                "start": start,
                "end": end,
                "video_title_for_youtube_short": clip.get("video_title_for_youtube_short") or "",
                "viral_hook_text": clip.get("viral_hook_text") or "",
                "video_description_for_tiktok": clip.get("video_description_for_tiktok") or "",
                "video_description_for_instagram": clip.get("video_description_for_instagram") or "",
                "speaker_labeled_transcript_excerpt": _collect_transcript_excerpt_for_range(
                    transcript_result,
                    start,
                    end,
                    max_chars=6000,
                ),
            })

        prompt = INTERVIEW_ATTRIBUTION_REVIEW_PROMPT_TEMPLATE.format(
            output_language_code=output_language_code,
            output_language_name=output_language_name,
            editorial_context=_format_shortform_editorial_context(),
            global_context_summary=global_context_summary,
            candidates_json=json.dumps(candidates, ensure_ascii=False),
        )
        try:
            payload = _call_shortform_provider_json_with_retries(
                provider_name,
                prompt,
                model_name=model_name,
                max_attempts=1 if provider_name == "minimax" else 2,
                retry_label=f"speaker attribution batch {batch_start // batch_size + 1}",
            )
        except Exception as exc:
            print(f"⚠️ Speaker attribution review batch failed; keeping original copy: {exc}")
            continue

        reviewed = payload.get("clips") if isinstance(payload, dict) else None
        if not isinstance(reviewed, list):
            print("⚠️ Speaker attribution review returned no clip list; keeping original copy.")
            continue
        for item in reviewed:
            if not isinstance(item, dict):
                continue
            try:
                clip_index = int(item.get("clip_index"))
            except (TypeError, ValueError):
                continue
            if clip_index < 0 or clip_index >= len(clips):
                continue
            clip = clips[clip_index]
            for field in (
                "video_title_for_youtube_short",
                "video_description_for_tiktok",
                "video_description_for_instagram",
            ):
                value = re.sub(r"\s+", " ", str(item.get(field) or "")).strip()
                if value:
                    clip[field] = value
            hook = _sanitize_hook_candidate_text(item.get("viral_hook_text"))
            if hook:
                clip["viral_hook_text"] = hook
            clip["subject_speaker"] = re.sub(r"\s+", " ", str(item.get("subject_speaker") or "unknown")).strip()[:80]
            clip["speaker_attribution_confidence"] = max(
                0.0,
                min(1.0, _coerce_float(item.get("speaker_attribution_confidence")) or 0.0),
            )
            reviewed_count += 1
    print(f"✅ Speaker attribution review updated {reviewed_count}/{len(clips)} clips.")
    return result_json


def _get_viral_clips_via_chat_provider_chunked(provider_name, transcript_result, video_duration, *, model_name, language_code, language_name, max_clip_duration, max_clips):
    provider_name = (provider_name or "").strip().lower()
    window_seconds = OLLAMA_CHUNK_SECONDS
    overlap_seconds = OLLAMA_CHUNK_OVERLAP_SECONDS
    if provider_name == "minimax":
        window_seconds = MINIMAX_CHUNK_SECONDS
        overlap_seconds = MINIMAX_CHUNK_OVERLAP_SECONDS

    windows = split_transcript_for_ollama(
        transcript_result,
        window_seconds=window_seconds,
        overlap_seconds=overlap_seconds,
    )
    if not windows:
        return None

    print(f"🧩 {provider_name.title()} chunked analysis over {len(windows)} transcript windows.")
    global_context_summary = _build_transcript_context_summary(
        transcript_result,
        provider_name=provider_name,
        model_name=model_name,
        output_language_code=language_code,
        output_language_name=language_name,
    )
    target_long_count = _target_long_clip_count(max_clip_duration, max_clips)
    all_clips = []
    chunk_divisor = max(1, min(len(windows), 5))
    chunk_limit = max_clips if len(windows) == 1 else max(3, min(6, math.ceil(max_clips / chunk_divisor)))

    for idx, window in enumerate(windows):
        if provider_name == "minimax":
            prompt = build_ollama_prompt(
                video_duration,
                window,
                output_language_code=language_code,
                output_language_name=language_name,
                max_clips=chunk_limit,
                max_clip_duration=max_clip_duration,
                min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
                minimum_long_clips=min(target_long_count, chunk_limit) if target_long_count else 0,
                global_context_summary=global_context_summary,
            )
        else:
            prompt = build_viral_prompt(
                video_duration,
                window.get("text") or "",
                window.get("words") or [],
                output_language_code=language_code,
                output_language_name=language_name,
                max_clips=chunk_limit,
                max_clip_duration=max_clip_duration,
                min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
                minimum_long_clips=min(target_long_count, chunk_limit) if target_long_count else 0,
                chunk_hint=(
                    f"Candidate hooks/starts must belong to {window['start']:.2f}-{window['end']:.2f}s. "
                    f"Use the supplied surrounding transcript context from "
                    f"{window.get('context_start', window['start']):.2f}-{window.get('context_end', window['end']):.2f}s "
                    "to include necessary setup and the complete payoff. Return nothing whose full thought is not visible."
                ),
                global_context_summary=global_context_summary,
            )
        chunk_started_at = time.time()
        print(
            f"🧩 {provider_name.title()} chunk {idx + 1}/{len(windows)}: "
            f"{window['start']:.1f}s - {window['end']:.1f}s, prompt_chars={len(prompt)}"
        )
        try:
            result_json = _call_shortform_provider_json_with_retries(
                provider_name,
                prompt,
                model_name=model_name,
                max_attempts=1 if provider_name == "minimax" else 2,
                retry_label=f"chunk {idx + 1}/{len(windows)}",
            )
        except Exception as exc:
            print(f"⚠️  {provider_name.title()} chunk {idx + 1} failed: {exc}")
            continue

        result_json = sanitize_clip_candidates(
            result_json,
            video_duration,
            transcript_result=transcript_result,
            language_code=language_code,
            max_clips=chunk_limit,
            max_clip_duration=max_clip_duration,
            min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        )
        if not result_json:
            print(f"⚠️  {provider_name.title()} chunk {idx + 1}/{len(windows)} completed in {time.time() - chunk_started_at:.1f}s but returned no viable clips.")
            continue
        chunk_clips = result_json.get("shorts") or []
        all_clips.extend(chunk_clips)
        print(
            f"✅ {provider_name.title()} chunk {idx + 1}/{len(windows)} completed in "
            f"{time.time() - chunk_started_at:.1f}s with {len(chunk_clips)} viable clips."
        )

    if not all_clips:
        return None

    combined_result = sanitize_clip_candidates(
        {"shorts": all_clips},
        video_duration,
        transcript_result=transcript_result,
        language_code=language_code,
        max_clips=max_clips,
        max_clip_duration=max_clip_duration,
        min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
    )
    if combined_result:
        combined_result["analysis_context_summary"] = global_context_summary
    return combined_result


def split_transcript_for_ollama(
    transcript_result,
    window_seconds=OLLAMA_CHUNK_SECONDS,
    overlap_seconds=OLLAMA_CHUNK_OVERLAP_SECONDS,
    context_seconds=CLIP_BOUNDARY_CONTEXT_SECONDS,
):
    segments = transcript_result.get("speaker_segments") or transcript_result.get("segments", [])
    if not segments:
        return []

    windows = []
    total_duration = segments[-1]["end"]
    start_time = 0.0
    while start_time < total_duration:
        end_time = min(total_duration, start_time + window_seconds)
        context_start = max(0.0, start_time - max(0.0, context_seconds))
        context_end = min(total_duration, end_time + max(0.0, context_seconds))
        chunk_segments = [
            segment for segment in segments
            if segment["end"] >= context_start and segment["start"] <= context_end
        ]
        if chunk_segments:
            chunk_words = []
            chunk_text_parts = []
            for segment in chunk_segments:
                chunk_text_parts.append(segment["text"])
                speaker_label = re.sub(r"\s+", " ", str(segment.get("speaker") or "")).strip()
                for word in segment.get("words", []):
                    if word["end"] >= context_start and word["start"] <= context_end:
                        w_entry = {
                            "w": word["word"],
                            "s": word["start"],
                            "e": word["end"],
                        }
                        if speaker_label:
                            w_entry["spk"] = speaker_label
                        chunk_words.append(w_entry)
            windows.append({
                "start": start_time,
                "end": end_time,
                "context_start": context_start,
                "context_end": context_end,
                "text": " ".join(chunk_text_parts).strip(),
                "words": chunk_words,
                "segments": chunk_segments,
            })

        if end_time >= total_duration:
            break
        start_time = max(0.0, end_time - overlap_seconds)

    return windows


def build_ollama_segment_lines(segments, max_lines=OLLAMA_MAX_SEGMENT_LINES, max_chars=OLLAMA_MAX_PROMPT_CHARS):
    """Render transcript segments for Ollama chunked prompts.

    Each line keeps both:
    - the segment-level speaker label (e.g. SPEAKER_00), and
    - the per-word timing of Whisper (``s``/``e`` in seconds) with the same
      speaker attached via ``spk`` so the model can pick exact word boundaries
      while still knowing which speaker is talking.
    """
    lines = []
    total_chars = 0

    for segment in segments:
        text = re.sub(r"\s+", " ", (segment.get("text") or "").strip())
        if not text:
            continue

        if len(text) > 220:
            text = text[:217].rstrip() + "..."

        speaker = re.sub(r"\s+", " ", str(segment.get("speaker") or "")).strip()
        speaker_prefix = f" {speaker}" if speaker else ""
        line = f"[{segment['start']:.2f}-{segment['end']:.2f}{speaker_prefix}] {text}"
        if lines and (len(lines) >= max_lines or (total_chars + len(line) + 1) > max_chars):
            break

        lines.append(line)
        total_chars += len(line) + 1

        # Word-level timings (with speaker) so the chunked model can pick
        # exact word-aligned clip boundaries without losing attribution.
        word_pieces = []
        for word in segment.get("words") or []:
            start = word.get("start")
            end = word.get("end")
            token = str(word.get("word") or "").strip()
            if not token or start is None or end is None:
                continue
            spk = speaker or "UNKNOWN"
            word_pieces.append(f"{token}|{float(start):.3f}|{float(end):.3f}|{spk}")
        if word_pieces:
            word_line = "WORDS: " + " ".join(word_pieces)
            if total_chars + len(word_line) + 1 <= max_chars:
                lines.append(word_line)
                total_chars += len(word_line) + 1

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
    minimum_long_clips=0,
    global_context_summary="",
):
    segment_lines = build_ollama_segment_lines(transcript_window.get("segments", []))
    return OLLAMA_PROMPT_TEMPLATE.format(
        video_duration=video_duration,
        chunk_start=f"{transcript_window['start']:.2f}",
        chunk_end=f"{transcript_window['end']:.2f}",
        context_start=f"{transcript_window.get('context_start', transcript_window['start']):.2f}",
        context_end=f"{transcript_window.get('context_end', transcript_window['end']):.2f}",
        segment_lines=segment_lines or "[0.00-0.00] No transcript available.",
        output_language_code=output_language_code,
        output_language_name=output_language_name,
        max_clips=max_clips,
        min_clip_duration=int(min_clip_duration) if float(min_clip_duration).is_integer() else min_clip_duration,
        preferred_min_clip_duration=int(PREFERRED_MIN_CLIP_DURATION) if float(PREFERRED_MIN_CLIP_DURATION).is_integer() else PREFERRED_MIN_CLIP_DURATION,
        max_clip_duration=int(max_clip_duration) if float(max_clip_duration).is_integer() else max_clip_duration,
        editorial_context=_format_shortform_editorial_context(),
        global_context_summary=(global_context_summary or "No extra summary available."),
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


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def _env_float(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _build_yt_dlp_js_runtimes():
    configured = [item.lower() for item in _split_env_values(os.environ.get("YOUTUBE_JS_RUNTIMES"))]
    detected_paths = {}
    runtime_bins = {
        "node": ["node"],
        "deno": ["deno"],
        "quickjs": ["qjs", "quickjs"],
        "bun": ["bun"],
    }

    for runtime_name, bin_candidates in runtime_bins.items():
        for bin_name in bin_candidates:
            path = shutil.which(bin_name)
            if path:
                detected_paths[runtime_name] = path
                break

    selected = configured or ["node", "deno", "quickjs", "bun"]
    runtimes = {}
    for runtime_name in selected:
        if runtime_name in detected_paths:
            runtimes[runtime_name] = {}

    return runtimes or None


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


YOUTUBE_NETWORK_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "failed to resolve",
    "name or service not known",
    "nodename nor servname provided",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "connection aborted",
    "timed out",
    "timeout",
    "tls handshake timeout",
    "proxyerror",
)

YOUTUBE_DNS_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "failed to resolve",
    "name or service not known",
    "nodename nor servname provided",
    "getaddrinfo failed",
)


def _is_youtube_network_failure(message):
    lower = str(message or "").lower()
    if not lower:
        return False
    return any(marker in lower for marker in YOUTUBE_NETWORK_ERROR_MARKERS)


def _is_youtube_dns_failure(message):
    lower = str(message or "").lower()
    if not lower:
        return False
    return any(marker in lower for marker in YOUTUBE_DNS_ERROR_MARKERS)


def _youtube_download_format_profiles():
    profiles = []
    seen = set()

    def add(label, expr):
        key = (label, expr)
        if key in seen:
            return
        seen.add(key)
        profiles.append((label, expr))

    add(
        "target-1080-720-avc1",
        (
            f"bestvideo[vcodec^=avc1][ext=mp4][height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]+bestaudio[ext=m4a]/"
            f"bestvideo[vcodec^=avc1][ext=mp4][height<={PREFERRED_DOWNLOAD_HEIGHT}]+bestaudio/"
            f"bestvideo[vcodec^=avc1][height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]+bestaudio"
        ),
    )
    add(
        "target-1080-720-mp4",
        (
            f"bestvideo[ext=mp4][height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]+bestaudio[ext=m4a]/"
            f"best[ext=mp4][height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]/"
            f"bestvideo[ext=mp4][height>={MIN_SOURCE_EDGE}]+bestaudio/"
            f"bestvideo[height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]+bestaudio/"
            f"best[height<={PREFERRED_DOWNLOAD_HEIGHT}][height>={MIN_SOURCE_EDGE}]"
        ),
    )
    add(
        "target-max-1080-mp4",
        (
            f"bestvideo[ext=mp4][height<={PREFERRED_DOWNLOAD_HEIGHT}]+bestaudio[ext=m4a]/"
            f"best[ext=mp4][height<={PREFERRED_DOWNLOAD_HEIGHT}]/"
            f"bestvideo[height<={PREFERRED_DOWNLOAD_HEIGHT}]+bestaudio/"
            f"best[height<={PREFERRED_DOWNLOAD_HEIGHT}]"
        ),
    )
    # Final fallback: pick the best downloadable stream combo regardless of height;
    # final quality gate below still rejects anything below MIN_SOURCE_EDGE.
    add("best-available", "bestvideo+bestaudio/best")
    return profiles

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed
mp_face_detection = mp.solutions.face_detection
_face_detection_local = threading.local()


def _new_face_detector():
    return mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)


def _close_face_detector(detector):
    if detector is None:
        return
    try:
        detector.close()
    except Exception:
        pass


def _get_thread_face_detector():
    detector = getattr(_face_detection_local, "detector", None)
    if detector is None:
        detector = _new_face_detector()
        _face_detection_local.detector = detector
    return detector


def _reset_thread_face_detector():
    detector = getattr(_face_detection_local, "detector", None)
    _close_face_detector(detector)
    detector = _new_face_detector()
    _face_detection_local.detector = detector
    return detector

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
        self.velocity_x = 0.0
        
        # Calculate crop dimensions once
        self.crop_height = video_height
        self.crop_width = int(self.crop_height * ASPECT_RATIO)
        if self.crop_width > video_width:
             self.crop_width = video_width
             self.crop_height = int(self.crop_width / ASPECT_RATIO)
             
        # Safe Zone: 20% of the video width
        # As long as the target is within this zone relative to current center, DO NOT MOVE.
        self.safe_zone_radius = self.crop_width * 0.18

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
            self.velocity_x = 0.0
        else:
            diff = self.target_center_x - self.current_center_x
            abs_diff = abs(diff)
            dead_zone = self.safe_zone_radius
            if abs_diff <= dead_zone:
                desired_velocity = diff * 0.035
            else:
                overflow = abs_diff - dead_zone
                desired_velocity = math.copysign(max(1.2, overflow * 0.12), diff)

            max_speed = 12.0 if abs_diff > self.crop_width * 0.42 else 5.5
            desired_velocity = max(-max_speed, min(max_speed, desired_velocity))
            damping = 0.78 if abs_diff > dead_zone else 0.68
            self.velocity_x = (self.velocity_x * damping) + (desired_velocity * (1.0 - damping))
            self.current_center_x += self.velocity_x

            if abs(self.target_center_x - self.current_center_x) < 0.9 and abs(self.velocity_x) < 0.12:
                self.current_center_x = self.target_center_x
                self.velocity_x = 0.0
                
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

    def _smooth_box(self, previous_box, new_box, alpha=0.18):
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
    active_detector = _get_thread_face_detector()

    try:
        results = active_detector.process(rgb_frame)
    except Exception as e:
        message = str(e)
        if "Packet timestamp mismatch" not in message and "InputStreamHandler" not in message:
            raise

        # Recover by recreating detector state to avoid stale graph timestamps.
        active_detector = _reset_thread_face_detector()

        try:
            results = active_detector.process(rgb_frame)
        except Exception:
            return []
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
    results = model.predict(
        frame,
        verbose=False,
        classes=[0],
        device=YOLO_DEVICE,
        half=YOLO_DEVICE != "cpu",
    )
    
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
    
    # Crop before scaling so landscape frames do not create a huge throwaway image.
    target_ratio = output_width / output_height
    source_crop_width = int(round(orig_h * target_ratio))
    if source_crop_width <= orig_w:
        source_x = max(0, (orig_w - source_crop_width) // 2)
        background_source = frame[:, source_x:source_x + source_crop_width]
    else:
        source_crop_height = max(1, int(round(orig_w / target_ratio)))
        source_y = max(0, (orig_h - source_crop_height) // 2)
        background_source = frame[source_y:source_y + source_crop_height, :]

    # A low-resolution blur is visually equivalent here and much cheaper per frame.
    blur_width = max(96, output_width // 4)
    blur_height = max(160, output_height // 4)
    background_small = cv2.resize(
        background_source,
        (blur_width, blur_height),
        interpolation=cv2.INTER_AREA,
    )
    background_small = cv2.GaussianBlur(background_small, (15, 15), 0)
    background = cv2.resize(
        background_small,
        (output_width, output_height),
        interpolation=cv2.INTER_LINEAR,
    )
    
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

    samples_by_frame = {}
    for scene_index, (start, end) in enumerate(scenes):
        start_frame = start.get_frames()
        end_frame = max(start_frame + 1, end.get_frames())
        frames_to_check = sorted({
            min(end_frame - 1, start_frame + 5),
            min(end_frame - 1, max(start_frame, int((start_frame + end_frame) / 2))),
            max(start_frame, end_frame - 5),
        })
        for frame_index in frames_to_check:
            samples_by_frame.setdefault(frame_index, []).append(scene_index)

    face_counts_by_scene = [[] for _ in scenes]
    current_frame = -1
    for target_frame in tqdm(sorted(samples_by_frame), desc="   Analyzing Scenes"):
        grabbed = True
        while current_frame < target_frame and grabbed:
            grabbed = cap.grab()
            current_frame += 1
        if not grabbed:
            break
        retrieved, frame = cap.retrieve()
        if not retrieved:
            continue
        face_count = len(detect_face_candidates(frame))
        for scene_index in samples_by_frame[target_frame]:
            face_counts_by_scene[scene_index].append(face_count)

    for face_counts in face_counts_by_scene:
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
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.auto_downscale = True
    scene_manager.detect_scenes(video=video)
    scene_list = scene_manager.get_scene_list()
    fps = video.frame_rate
    return scene_list, fps


def probe_video_stream(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,pix_fmt",
        "-of", "json",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **subprocess_priority_kwargs(),
        )
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        if streams:
            stream = streams[0] or {}
            return {
                "codec_name": (stream.get("codec_name") or "").lower(),
                "width": int(stream.get("width") or 0),
                "height": int(stream.get("height") or 0),
                "pix_fmt": stream.get("pix_fmt") or "",
            }
    except Exception:
        pass
    return {}


def validate_input_video(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration:stream=index,codec_type,codec_name",
        "-of", "json",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **subprocess_priority_kwargs(),
        )
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or "").strip()
        if "moov atom not found" in stderr_text.lower():
            return {
                "valid": False,
                "reason": (
                    "Die Eingabedatei ist unvollstaendig oder defekt "
                    "(MP4 moov atom fehlt). Bitte die Quelldatei neu exportieren oder neu hochladen."
                ),
                "technical_detail": stderr_text,
            }
        return {
            "valid": False,
            "reason": "Die Eingabedatei konnte von ffprobe nicht gelesen werden.",
            "technical_detail": stderr_text or str(exc),
        }
    except Exception as exc:
        return {
            "valid": False,
            "reason": "Die Eingabedatei konnte nicht validiert werden.",
            "technical_detail": str(exc),
        }

    try:
        payload = json.loads(result.stdout or "{}")
    except Exception:
        payload = {}
    streams = payload.get("streams") or []
    has_video = any(str((stream or {}).get("codec_type") or "").lower() == "video" for stream in streams)
    if not has_video:
        return {
            "valid": False,
            "reason": "Die Eingabedatei enthaelt keinen lesbaren Videostream.",
            "technical_detail": "ffprobe fand keinen Videostream.",
        }
    return {
        "valid": True,
        "reason": "",
        "technical_detail": "",
    }


def get_video_resolution(video_path):
    stream_info = probe_video_stream(video_path)
    width = int(stream_info.get("width") or 0)
    height = int(stream_info.get("height") or 0)
    if width > 0 and height > 0:
        return width, height

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height


def ensure_cv2_compatible_video(video_path, output_dir):
    stream_info = probe_video_stream(video_path)
    codec_name = (stream_info.get("codec_name") or "").lower()
    ext = os.path.splitext(video_path)[1].lower()
    needs_safari_safe_source = ext != ".mp4" or codec_name != "h264"
    if not needs_safari_safe_source:
        return video_path

    base_name = sanitize_filename(os.path.splitext(os.path.basename(video_path))[0])
    working_path = os.path.join(output_dir, f"{base_name}_working_h264.mp4")

    if os.path.exists(working_path) and os.path.getsize(working_path) > 0:
        print(f"♻️  Reusing H.264 working source: {working_path}")
        return working_path

    reason_parts = []
    if codec_name and codec_name != "h264":
        reason_parts.append(f"codec={codec_name}")
    if ext and ext != ".mp4":
        reason_parts.append(f"container={ext}")
    reason = ", ".join(reason_parts) if reason_parts else "unsupported source"
    print(
        "⚠️  Source is not Safari/OpenCV-friendly "
        f"({reason}). Creating H.264 MP4 working copy..."
    )
    conversion_encoder, conversion_encoder_args = selected_h264_encoding_args(
        cpu_preset="veryfast",
        crf="18",
        pixel_format="yuv420p",
    )
    print(f"   Video encoder (working copy): {conversion_encoder}")
    convert_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        *ffmpeg_thread_args(),
        *conversion_encoder_args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        working_path,
    ]

    try:
        subprocess.run(
            convert_cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_priority_kwargs(),
        )
        width, height = get_video_resolution(working_path)
        print(f"✅ H.264 working source ready: {working_path} ({width}x{height})")
        return working_path
    except subprocess.CalledProcessError as exc:
        if os.path.exists(working_path):
            os.remove(working_path)
        err = exc.stderr.decode("utf-8", errors="ignore")[-500:]
        print(f"⚠️ Failed to convert source to H.264 MP4. Continuing with original input. Details: {err}")
        return video_path


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
        cookie_sources = []
        for path in [cookies_file_path, "/tmp/openshorts/cookies.txt", "/app/cookies.txt"]:
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in cookie_sources:
                continue
            cookie_sources.append(norm)

        existing_sources = [path for path in cookie_sources if os.path.exists(path)]
        existing_sources.sort(key=lambda path: os.path.getmtime(path), reverse=True)

        for source_path in existing_sources:
            try:
                temp_path = _copy_cookies_file_to_temp(source_path)
                temp_files.append(temp_path)
                candidates.append({
                    "label": f"cookies-file:{source_path}",
                    "opts": {"cookiefile": temp_path},
                })
            except Exception as exc:
                print(f"⚠️ Failed to copy cookies file {source_path}: {exc}")

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

    has_authenticated_candidate = any(bool(candidate.get("opts")) for candidate in candidates)
    allow_unauth_fallback = _env_flag("YOUTUBE_ALLOW_UNAUTH_FALLBACK", not has_authenticated_candidate)
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
    js_runtimes = _build_yt_dlp_js_runtimes()
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
    if js_runtimes:
        common_ydl_opts["js_runtimes"] = js_runtimes
        print("🧠 yt-dlp JS runtimes enabled: " + ", ".join(js_runtimes.keys()))
    else:
        print("⚠️ No JS runtime detected for yt-dlp challenge solving (node/deno/quickjs/bun).")

    viable_candidates = []
    preflight_errors = []
    probe_attempts = max(1, _env_int("YOUTUBE_PROBE_ATTEMPTS", 3))
    probe_retry_delay_seconds = max(0.0, _env_float("YOUTUBE_PROBE_RETRY_DELAY_SECONDS", 1.5))

    try:
        for candidate in auth_candidates:
            probe_opts = {**common_ydl_opts, **candidate["opts"]}
            print(f"🔑 Probing YouTube formats using auth={candidate['label']}")
            info = None
            best_format = None
            best_edge = 0
            for attempt in range(1, probe_attempts + 1):
                try:
                    with yt_dlp.YoutubeDL(probe_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                    best_format, best_edge = _best_accessible_source_edge(info)
                    break
                except Exception as exc:
                    err_text = str(exc)
                    if attempt < probe_attempts and _is_youtube_network_failure(err_text):
                        wait_seconds = max(0.0, probe_retry_delay_seconds * attempt)
                        print(
                            "⚠️ Transient YouTube probe/network failure "
                            f"(auth={candidate['label']} attempt={attempt}/{probe_attempts}): {err_text}"
                        )
                        if wait_seconds > 0:
                            print(f"🔁 Retrying probe in {wait_seconds:.1f}s...")
                            time.sleep(wait_seconds)
                        continue
                    preflight_errors.append(f"{candidate['label']}: {err_text}")
                    break

            if info is None:
                continue

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

            viable_candidates.append(
                {
                    "candidate": candidate,
                    "info": info,
                    "best_format": best_format,
                    "best_edge": best_edge,
                }
            )

        if not viable_candidates:
            detail = "\n".join(preflight_errors[-5:]) if preflight_errors else "No auth candidate succeeded."
            lower_errors = "\n".join(preflight_errors).lower()
            network_failure = _is_youtube_network_failure(lower_errors)
            dns_failure = _is_youtube_dns_failure(lower_errors)
            rotated_cookie_hint = (
                "Detected invalid/rotated YouTube cookies. Export a fresh cookies.txt from a logged-in browser and retry.\n"
                if (not network_failure) and ("no longer valid" in lower_errors or "sign in to confirm you’re not a bot" in lower_errors)
                else ""
            )
            network_hint = (
                (
                    "Detected DNS resolution failure while contacting YouTube. "
                    "Check container/host DNS and outbound network access, then retry.\n"
                )
                if dns_failure
                else (
                    "Detected temporary network failure while contacting YouTube. "
                    "Check outbound network/proxy/firewall access, then retry.\n"
                    if network_failure
                    else ""
                )
            )
            remediation = (
                "Retry after network access is restored, or upload the source file manually."
                if network_failure
                else "Set valid cookies (cookies.txt or pasted cookies), optional visitor data/PO token, or upload the source file manually."
            )
            raise RuntimeError(
                "Unable to access a high-quality YouTube source.\n"
                f"{network_hint}"
                f"{rotated_cookie_hint}"
                f"Details:\n{detail}\n"
                f"{remediation}"
            )

        video_title = viable_candidates[0]["info"].get("title", "youtube_video")
        sanitized_title = sanitize_filename(video_title)
        output_template = os.path.join(output_dir, f"{sanitized_title}.%(ext)s")
        existing_file = _find_downloaded_video_file(output_dir, sanitized_title)
        if existing_file and os.path.exists(existing_file):
            os.remove(existing_file)
            print("🗑️  Removed existing file to re-download highest available quality")

        format_profiles = _youtube_download_format_profiles()
        download_errors = []

        for candidate_entry in viable_candidates:
            candidate = candidate_entry["candidate"]
            probe_info = candidate_entry["info"]
            candidate_label = candidate["label"]

            for profile_label, format_expr in format_profiles:
                stale_file = _find_downloaded_video_file(output_dir, sanitized_title)
                if stale_file and os.path.exists(stale_file):
                    os.remove(stale_file)

                ydl_opts = {
                    **common_ydl_opts,
                    **candidate["opts"],
                    "format": format_expr,
                    "outtmpl": output_template,
                    "merge_output_format": "mp4",
                    "overwrites": True,
                }

                print(
                    "⬇️ Downloading with "
                    f"auth={candidate_label} format_profile={profile_label}"
                )
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # Reuse successfully probed info to avoid a second extraction race.
                        ydl.process_ie_result(copy.deepcopy(probe_info), download=True)
                except Exception as exc:
                    msg = str(exc)
                    download_errors.append(f"{candidate_label}/{profile_label}: {msg}")
                    if "Requested format is not available" in msg:
                        print(
                            "⚠️ Requested format vanished during download. "
                            f"Retrying next profile (auth={candidate_label}, profile={profile_label})."
                        )
                    else:
                        print(
                            f"⚠️ Download attempt failed "
                            f"(auth={candidate_label}, profile={profile_label}): {msg}"
                        )
                    continue

                downloaded_file = _find_downloaded_video_file(output_dir, sanitized_title)
                if not downloaded_file:
                    download_errors.append(
                        f"{candidate_label}/{profile_label}: yt-dlp finished without a usable video file."
                    )
                    print(
                        "⚠️ Download completed but no usable file was found. "
                        f"Trying next profile (auth={candidate_label}, profile={profile_label})."
                    )
                    continue

                width, height = get_video_resolution(downloaded_file)
                short_edge = min(width, height)
                print(f"🎞️  Downloaded source resolution: {width}x{height}")
                if short_edge < MIN_SOURCE_EDGE:
                    if os.path.exists(downloaded_file):
                        os.remove(downloaded_file)
                    download_errors.append(
                        f"{candidate_label}/{profile_label}: downloaded source too small ({width}x{height})"
                    )
                    print(
                        "⚠️ Downloaded source below minimum quality gate "
                        f"({width}x{height}, required short edge >= {MIN_SOURCE_EDGE})."
                    )
                    continue

                step_end_time = time.time()
                print(f"✅ Video downloaded in {step_end_time - step_start_time:.2f}s: {downloaded_file}")
                return downloaded_file, sanitized_title

        detail = "\n".join(download_errors[-8:]) if download_errors else "All download attempts failed."
        lower_download_errors = "\n".join(download_errors).lower()
        network_download_hint = (
            (
                "Detected DNS resolution failure while downloading from YouTube. "
                "Check container/host DNS and outbound network access, then retry.\n"
            )
            if _is_youtube_dns_failure(lower_download_errors)
            else (
                "Detected temporary network failure while downloading from YouTube. "
                "Check outbound network/proxy/firewall access, then retry.\n"
                if _is_youtube_network_failure(lower_download_errors)
                else ""
            )
        )
        remediation = (
            "Retry after network access is restored, or upload the source file manually."
            if network_download_hint
            else "Set valid cookies (cookies.txt or pasted cookies), optional visitor data/PO token, or upload the source file manually."
        )
        raise RuntimeError(
            "Unable to download a usable high-quality YouTube source after retries.\n"
            f"{network_download_hint}"
            f"Details:\n{detail}\n"
            f"{remediation}"
        )

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
3. Ensure a JS runtime is available for yt-dlp (recommended: node) to pass YouTube JS challenges.
4. If YouTube still only exposes low quality or blocks access, upload the original source file directly.
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

def _smoothstep01(value):
    progress = max(0.0, min(1.0, float(value)))
    return progress * progress * (3.0 - (2.0 * progress))


def _zoom_frame_to_anchor(frame, anchor_x, anchor_y, zoom_delta):
    frame_height, frame_width = frame.shape[:2]
    zoom_factor = 1.0 + max(0.0, float(zoom_delta or 0.0))
    crop_width = max(2, min(frame_width, int(round(frame_width / zoom_factor))))
    crop_height = max(2, min(frame_height, int(round(frame_height / zoom_factor))))
    center_x = int(round(max(0.0, min(1.0, anchor_x)) * frame_width))
    center_y = int(round(max(0.0, min(1.0, anchor_y)) * frame_height))
    x1 = max(0, min(frame_width - crop_width, center_x - (crop_width // 2)))
    y1 = max(0, min(frame_height - crop_height, center_y - (crop_height // 2)))
    cropped = frame[y1:y1 + crop_height, x1:x1 + crop_width]
    if cropped.size == 0:
        return frame
    return cv2.resize(cropped, (frame_width, frame_height), interpolation=cv2.INTER_LINEAR)


def _pattern_flash_strength(current_time, event_time, duration_hint):
    flash_duration = max(0.04, float(duration_hint or 0.08))
    attack = flash_duration * 0.35
    release = max(0.02, flash_duration - attack)
    start_time = event_time - attack
    end_time = event_time + release
    if current_time < start_time or current_time > end_time:
        return 0.0
    if current_time <= event_time:
        return _smoothstep01((current_time - start_time) / max(attack, 1e-6))
    return 1.0 - _smoothstep01((current_time - event_time) / max(release, 1e-6))


def _pattern_zoom_delta(current_time, zoom_cycles):
    zoom_delta = 0.0
    for cycle in zoom_cycles:
        zoom_in_start = float(cycle.get("zoom_in_start") or 0.0)
        zoom_in_duration = max(0.1, float(cycle.get("zoom_in_duration") or 0.56))
        hold_duration = max(0.0, float(cycle.get("hold_duration") or 5.0))
        zoom_out_start = float(
            cycle.get("zoom_out_start")
            or (zoom_in_start + zoom_in_duration + hold_duration)
        )
        zoom_out_duration = max(0.1, float(cycle.get("zoom_out_duration") or 0.64))
        start_delta = max(0.0, float(cycle.get("start_zoom_delta") or 0.0))
        target_delta = max(0.0, float(cycle.get("zoom_delta") or 0.0))

        if current_time < zoom_in_start:
            active_delta = start_delta
        elif current_time <= zoom_in_start + zoom_in_duration:
            progress = (current_time - zoom_in_start) / max(zoom_in_duration, 1e-6)
            active_delta = start_delta + ((target_delta - start_delta) * _smoothstep01(progress))
        elif current_time <= zoom_out_start:
            active_delta = target_delta
        elif current_time <= zoom_out_start + zoom_out_duration:
            progress = (current_time - zoom_out_start) / max(zoom_out_duration, 1e-6)
            active_delta = start_delta + ((target_delta - start_delta) * (1.0 - _smoothstep01(progress)))
        else:
            active_delta = start_delta
        zoom_delta = max(zoom_delta, active_delta)
    return zoom_delta


def apply_pattern_interrupts_to_frame(frame, current_time, pattern_plan, interview_mode=False):
    zoom_cycles = list((pattern_plan or {}).get("zoom_cycles") or [])
    flash_events = list((pattern_plan or {}).get("flash_events") or [])
    if not zoom_cycles and not flash_events:
        return frame

    zoom_delta = _pattern_zoom_delta(current_time, zoom_cycles)
    processed = frame
    if zoom_delta > 0.001:
        if interview_mode:
            split_y = frame.shape[0] // 2
            top = _zoom_frame_to_anchor(frame[:split_y, :], 0.5, 0.44, zoom_delta)
            bottom = _zoom_frame_to_anchor(frame[split_y:, :], 0.5, 0.44, zoom_delta)
            processed = np.vstack((top, bottom))
            cv2.line(processed, (0, split_y), (frame.shape[1], split_y), (255, 255, 255), 3)
        else:
            processed = _zoom_frame_to_anchor(frame, 0.5, 0.42, zoom_delta)

    flash_level = 0.0
    for event in flash_events:
        strength = str(event.get("strength") or "medium")
        amount_map = (
            {"low": 0.75, "medium": 1.05, "high": 1.35}
            if interview_mode
            else {"low": 0.95, "medium": 1.35, "high": 1.75}
        )
        flash_level = max(
            flash_level,
            amount_map.get(strength, amount_map["medium"])
            * _pattern_flash_strength(
                current_time,
                float(event.get("time") or 0.0),
                float(event.get("duration") or 0.1),
            ),
        )
    if flash_level > 0.001:
        processed = cv2.convertScaleAbs(
            processed,
            alpha=1.0 + ((0.10 if interview_mode else 0.14) * flash_level),
            beta=(42.0 if interview_mode else 64.0) * flash_level,
        )
    return processed


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
    pattern_plan=None,
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

    encoder_name, encoder_args = selected_h264_encoding_args(
        cpu_preset=encode_preset,
        crf=encode_crf,
        maxrate=encode_maxrate,
        bufsize=encode_bufsize,
        profile="high",
        level="4.1",
        pixel_format="yuv420p",
    )
    print(f"   Video encoder: {encoder_name}")
    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-',
        *ffmpeg_thread_args(),
        *encoder_args,
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
    detection_stride = max(1, int(round(float(fps) / TRACKING_DETECTION_FPS)))

    with tqdm(total=total_frames, desc="   Processing", file=sys.stdout) as pbar:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if interview_mode:
                if frame_number % detection_stride == 0:
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
                    
                    # Snap camera on scene change to avoid panning from previous scene position
                    is_scene_start = (frame_number == scene_boundaries[current_scene_index][0])
                    if frame_number % detection_stride == 0 or is_scene_start:
                        candidates = detect_face_candidates(frame)
                        target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                        if target_box:
                            cameraman.update_target(target_box)
                        else:
                            person_box = detect_person_yolo(frame)
                            if person_box:
                                cameraman.update_target(person_box)
                    
                    x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=is_scene_start)
                    
                    # Crop
                    if y2 > y1 and x2 > x1:
                        cropped = frame[y1:y2, x1:x2]
                        output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_CUBIC)
                    else:
                        output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_CUBIC)

            output_frame = apply_pattern_interrupts_to_frame(
                output_frame,
                frame_number / max(float(fps), 1.0),
                pattern_plan,
                interview_mode=bool(interview_mode),
            )
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


def _normalize_transcript_language(raw):
    value = str(raw or "").strip().lower()
    if not value or value == "auto":
        return ""
    return value.split("-")[0]


def _is_english_biased_whisper_model(model_name):
    lowered = str(model_name or "").strip().lower()
    if not lowered:
        return False
    if "german" in lowered or lowered.endswith(".de"):
        return False
    return "distil-large-v3" in lowered


def _looks_like_mismatched_german_transcript(transcript):
    if not isinstance(transcript, dict):
        return False
    language = _normalize_transcript_language(transcript.get("language"))
    if language != "de":
        return False
    text = re.sub(r"\s+", " ", str(transcript.get("text") or "")).strip().lower()
    if len(text) < 120:
        return False

    window = f" {text[:5000]} "
    english_markers = re.findall(
        r"\b(the|and|with|that|this|there|have|has|had|was|were|you|your|people|from|when|where|because|just|really|week|cool)\b",
        window,
    )
    german_markers = re.findall(
        r"\b(ich|und|der|die|das|nicht|wir|ihr|euch|ist|war|waren|haben|hat|mit|fuer|für|dass|weil|also|dann|ein|eine|so|ja|genau|aber|oder|wenn|man)\b",
        window,
    )
    umlaut_count = sum(window.count(ch) for ch in ("ä", "ö", "ü", "ß"))
    if len(english_markers) >= 12 and len(english_markers) > max(6, len(german_markers) * 2 + umlaut_count):
        return True
    return False


def _should_refresh_resume_transcript(transcript, expected_language):
    if not isinstance(transcript, dict):
        return True, "Transcript-Datei ist unlesbar."
    expected = _normalize_transcript_language(expected_language)
    transcript_language = _normalize_transcript_language(transcript.get("language"))
    runtime = transcript.get("runtime") or {}
    runtime_model = runtime.get("model") or runtime.get("resolved_model") or ""
    if expected == "de" and transcript_language == "de":
        if _is_english_biased_whisper_model(runtime_model):
            return True, f"Deutsch-Transcript wurde mit englisch-biased Whisper-Modell erstellt ({runtime_model})."
        if _looks_like_mismatched_german_transcript(transcript):
            return True, "Deutsch-Transcript sieht nach englisch/phonetic Fehltranskription aus."
    return False, ""


def transcribe_video(video_path):
    print("🎙️  Transcribing video with Faster-Whisper...")
    transcription_input = _prepare_transcription_input(video_path)
    cleanup_input = transcription_input != video_path
    forced_language = (os.environ.get("WHISPER_LANGUAGE") or "de").strip() or "de"
    try:
        segments, info, runtime_meta = transcribe_with_runtime(
            transcription_input,
            word_timestamps=True,
            language=forced_language,
        )
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
    if runtime_meta.get("word_timestamps") is False:
        print("⚠️  Whisper word timestamps are disabled for this run; clip boundaries may be less precise.")
    
    # Convert to openai-whisper compatible format
    transcript_segments = []
    full_text = ""
    word_timestamp_count = 0
    
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
                word_timestamp_count += 1
        
        transcript_segments.append(seg_dict)
        full_text += segment.text + " "
    if word_timestamp_count:
        print(f"   Word-level timestamps: {word_timestamp_count} words available for precise clip boundaries.")
    else:
        print("⚠️  No word-level timestamps were produced; MiniMax will only see segment-level timing.")

    return {
        'text': full_text.strip(),
        'segments': transcript_segments,
        'language': info.language,
        'language_probability': float(getattr(info, "language_probability", 0.0) or 0.0),
        'runtime': {
            'model': runtime_meta.get('model'),
            'resolved_model': runtime_meta.get('resolved_model'),
            'device': runtime_meta.get('device'),
            'compute_type': runtime_meta.get('compute_type'),
            'beam_size': runtime_meta.get('beam_size'),
            'vad_filter': runtime_meta.get('vad_filter'),
            'requested_language': runtime_meta.get('requested_language'),
            'word_timestamps': runtime_meta.get('word_timestamps'),
        },
        'word_timestamp_count': word_timestamp_count,
    }


def _speaker_for_interval(turns, start, end, start_index=0):
    while start_index < len(turns) and float(turns[start_index]["end"]) <= start:
        start_index += 1
    best_speaker = "UNKNOWN"
    best_overlap = 0.0
    index = start_index
    while index < len(turns) and float(turns[index]["start"]) < end:
        turn = turns[index]
        overlap = max(0.0, min(end, float(turn["end"])) - max(start, float(turn["start"])))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(turn.get("speaker") or "UNKNOWN")
        index += 1
    return best_speaker, start_index


def _build_speaker_segments(transcript, turns):
    speaker_segments = []
    turn_index = 0

    def append_piece(speaker, start, end, text, words=None):
        normalized_text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized_text or end <= start:
            return
        if (
            speaker_segments
            and speaker_segments[-1]["speaker"] == speaker
            and start <= float(speaker_segments[-1]["end"]) + 0.8
        ):
            previous = speaker_segments[-1]
            previous["end"] = round(max(float(previous["end"]), end), 3)
            previous["text"] = f"{previous['text']} {normalized_text}".strip()
            if words:
                previous.setdefault("words", []).extend(words)
            return
        speaker_segments.append({
            "speaker": speaker,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": normalized_text,
            "words": list(words or []),
        })

    for segment in transcript.get("segments") or []:
        words = [word for word in (segment.get("words") or []) if word.get("start") is not None and word.get("end") is not None]
        if not words:
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or start)
            speaker, turn_index = _speaker_for_interval(turns, start, end, turn_index)
            append_piece(speaker, start, end, segment.get("text") or "")
            continue

        current_speaker = None
        current_words = []
        for word in words:
            start = float(word.get("start") or 0.0)
            end = float(word.get("end") or start)
            speaker, turn_index = _speaker_for_interval(turns, start, end, turn_index)
            if current_words and speaker != current_speaker:
                append_piece(
                    current_speaker or "UNKNOWN",
                    float(current_words[0]["start"]),
                    float(current_words[-1]["end"]),
                    "".join(str(item.get("word") or "") for item in current_words),
                    current_words,
                )
                current_words = []
            current_speaker = speaker
            current_words.append(dict(word))
        if current_words:
            append_piece(
                current_speaker or "UNKNOWN",
                float(current_words[0]["start"]),
                float(current_words[-1]["end"]),
                "".join(str(item.get("word") or "") for item in current_words),
                current_words,
            )
    return speaker_segments


def ensure_shortform_speaker_diarization(video_path, transcript):
    if not isinstance(transcript, dict):
        return transcript, False
    if transcript.get("speaker_segments") and transcript.get("speaker_turns"):
        return transcript, False

    audio_path = video_path
    cleanup_audio = False
    try:
        from longform.analysis import _load_pyannote_pipeline

        audio_path = _prepare_transcription_input(video_path)
        cleanup_audio = audio_path != video_path
        token = (
            os.environ.get("PYANNOTE_AUTH_TOKEN")
            or os.environ.get("HUGGINGFACE_HUB_TOKEN")
            or os.environ.get("HF_TOKEN")
            or ""
        ).strip()
        pipeline = _load_pyannote_pipeline(token_override=token, logger=lambda message: print(f"🗣️ {message}"))
        try:
            diarization = pipeline(audio_path, min_speakers=2, max_speakers=4)
        except TypeError:
            diarization = pipeline(audio_path)

        turns = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            start = float(turn.start or 0.0)
            end = float(turn.end or start)
            if end - start < 0.08:
                continue
            turns.append({
                "speaker": str(speaker),
                "start": round(start, 3),
                "end": round(end, 3),
            })
        turns.sort(key=lambda item: (item["start"], item["end"]))
        if not turns:
            raise RuntimeError("Pyannote returned no speaker turns.")

        speaker_segments = _build_speaker_segments(transcript, turns)
        if not speaker_segments:
            raise RuntimeError("Speaker turns could not be aligned to Whisper words.")

        enriched = dict(transcript)
        enriched["speaker_turns"] = turns
        enriched["speaker_segments"] = speaker_segments
        enriched["diarization_runtime"] = {
            "provider": "pyannote",
            "speaker_count": len({item["speaker"] for item in turns}),
            "turn_count": len(turns),
            "status": "completed",
        }
        print(
            "✅ Shortform speaker diarization complete: "
            f"speakers={enriched['diarization_runtime']['speaker_count']}, turns={len(turns)}, "
            f"speaker_segments={len(speaker_segments)}"
        )
        return enriched, True
    except Exception as exc:
        print(f"⚠️ Shortform speaker diarization unavailable; continuing with strict neutral attribution rules: {exc}")
        enriched = dict(transcript)
        enriched["diarization_runtime"] = {
            "provider": "pyannote",
            "status": "failed",
            "error": str(exc)[:500],
        }
        return enriched, True
    finally:
        if cleanup_audio:
            try:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass

def _word_speaker_lookup(transcript_result):
    """Build a mapping of word identity (text|start|end) -> speaker label.

    Uses speaker_segments from diarization when available. Each word is matched
    by (text, rounded start, rounded end) to the words stored inside
    speaker_segments during _build_speaker_segments. Words that cannot be
    matched remain absent from the lookup.
    """
    lookup = {}
    if not isinstance(transcript_result, dict):
        return lookup
    speaker_segments = transcript_result.get("speaker_segments") or []
    if not speaker_segments:
        return lookup
    for segment in speaker_segments:
        speaker = re.sub(r"\s+", " ", str(segment.get("speaker") or "")).strip() or "UNKNOWN"
        for word in segment.get("words") or []:
            text = str(word.get("word") or "").strip()
            start = word.get("start")
            end = word.get("end")
            if not text or start is None or end is None:
                continue
            key = (text, round(float(start), 3), round(float(end), 3))
            lookup[key] = speaker
    return lookup


def _extract_words(transcript_result, include_speaker=False):
    words = []
    speaker_lookup = _word_speaker_lookup(transcript_result) if include_speaker else {}
    for segment in transcript_result.get('segments') or []:
        for word in segment.get('words') or []:
            entry = {
                'w': word.get('word'),
                's': word.get('start'),
                'e': word.get('end'),
            }
            if include_speaker and speaker_lookup:
                text = str(word.get('word') or '').strip()
                start = word.get('start')
                end = word.get('end')
                if text and start is not None and end is not None:
                    speaker = speaker_lookup.get(
                        (text, round(float(start), 3), round(float(end), 3))
                    )
                    if speaker:
                        entry['spk'] = speaker
            words.append(entry)
    return words


def get_viral_clips(transcript_result, video_duration, max_clip_duration=MAX_CLIP_DURATION, max_clips=MAX_GENERATED_CLIPS):
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider == "ollama":
        return get_viral_clips_via_ollama(transcript_result, video_duration, max_clip_duration=max_clip_duration, max_clips=max_clips)
    if provider in {"openai", "claude", "minimax"}:
        return get_viral_clips_via_chat_provider(
            provider,
            transcript_result,
            video_duration,
            max_clip_duration=max_clip_duration,
            max_clips=max_clips,
        )
    return get_viral_clips_via_gemini(transcript_result, video_duration, max_clip_duration=max_clip_duration, max_clips=max_clips)


def get_viral_clips_via_chat_provider(provider_name, transcript_result, video_duration, max_clip_duration=MAX_CLIP_DURATION, max_clips=MAX_GENERATED_CLIPS):
    print(f"🤖  Analyzing with {provider_name.title()}...")
    language_code, language_name = describe_output_language(transcript_result.get("language"))
    target_long_count = _target_long_clip_count(max_clip_duration, max_clips)
    model_env_map = {
        "openai": ("OPENAI_MODEL", "gpt-4.1-mini"),
        "claude": ("CLAUDE_MODEL", "claude-3-5-sonnet-latest"),
        "minimax": ("MINIMAX_MODEL", _default_minimax_model()),
    }
    model_env, default_model = model_env_map.get(provider_name, ("", ""))
    model_name = os.getenv(model_env, default_model) if model_env else default_model
    if provider_name == "minimax":
        print(f"🤖  MiniMax model selected: {model_name or _default_minimax_model()}")
    global_context_summary = _build_transcript_context_summary(
        transcript_result,
        provider_name=provider_name,
        model_name=model_name,
        output_language_code=language_code,
        output_language_name=language_name,
    )
    prompt = build_viral_prompt(
        video_duration,
        transcript_result["text"],
        _extract_words(transcript_result, include_speaker=True),
        output_language_code=language_code,
        output_language_name=language_name,
        max_clips=max_clips,
        max_clip_duration=max_clip_duration,
        min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        minimum_long_clips=target_long_count,
        global_context_summary=global_context_summary,
    )

    def _sanitize_provider_result(payload):
        payload = sanitize_clip_candidates(
            payload,
            video_duration,
            transcript_result=transcript_result,
            language_code=language_code,
            max_clips=max_clips,
            max_clip_duration=max_clip_duration,
            min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        )
        if not payload:
            return None
        return payload

    prefer_chunked = _should_use_chunked_chat_provider(provider_name, transcript_result, model_name=model_name)
    if prefer_chunked:
        if provider_name == "minimax" and not _is_minimax_m3(model_name):
            print(f"🧩 MiniMax model {model_name} is not MiniMax-M3; using chunked transcript analysis first for reliability.")
        else:
            print(f"🧩 {provider_name.title()} will use chunked transcript analysis first for reliability.")
        result_json = _get_viral_clips_via_chat_provider_chunked(
            provider_name,
            transcript_result,
            video_duration,
            model_name=model_name,
            language_code=language_code,
            language_name=language_name,
            max_clip_duration=max_clip_duration,
            max_clips=max_clips,
        )
        result_json = _sanitize_provider_result(result_json)
        if result_json:
            result_json["analysis_context_summary"] = global_context_summary
            return _ensure_generated_clip_hooks(
                result_json,
                transcript_result,
                provider_name=provider_name,
                output_language_code=language_code,
                output_language_name=language_name,
            )
        if provider_name == "minimax" and not _env_flag("MINIMAX_ALLOW_FULL_FALLBACK", False):
            raise RuntimeError(
                "MiniMax chunked analysis returned no usable clips. "
                "Full-transcript fallback is disabled to protect MiniMax token-plan limits."
            )

    try:
        result_json = _call_shortform_provider_json_with_retries(
            provider_name,
            prompt,
            model_name=model_name,
            max_attempts=1 if provider_name == "minimax" else 2,
            retry_label="full transcript",
        )
        if not result_json:
            print(f"❌ {provider_name.title()} returned invalid JSON.")
            raise RuntimeError(f"{provider_name.title()} returned invalid JSON.")
        result_json = _sanitize_provider_result(result_json)
        if not result_json:
            raise RuntimeError(f"{provider_name.title()} returned no viable clip candidates.")
        result_json["analysis_context_summary"] = global_context_summary
        if _should_retry_for_long_clips(result_json, max_clip_duration, max_clips):
            current_long_count = _count_long_clip_candidates(result_json)
            print(f"🔁 {provider_name.title()} returned only {current_long_count} long clips. Gathering additional >60s candidates toward ~{target_long_count}...")
            retry_prompt = _build_long_clip_retry_prompt(prompt, current_long_count, target_long_count)
            supplement_attempts = 0 if provider_name == "minimax" else 2
            for attempt in range(supplement_attempts):
                retry_json = _call_shortform_provider_json_with_retries(
                    provider_name,
                    retry_prompt,
                    model_name=model_name,
                    max_attempts=2,
                    retry_label=f"long-clip supplement {attempt + 1}/2",
                )
                retry_json = _sanitize_provider_result(retry_json)
                if retry_json:
                    result_json = _merge_long_clip_results(result_json, retry_json, max_clips)
                current_long_count = _count_long_clip_candidates(result_json)
                if current_long_count >= target_long_count:
                    break
        return _ensure_generated_clip_hooks(
            result_json,
            transcript_result,
            provider_name=provider_name,
            output_language_code=language_code,
            output_language_name=language_name,
        )
    except Exception as e:
        print(f"❌ {provider_name.title()} Error: {e}")
        if not prefer_chunked:
            print(f"🧩 {provider_name.title()} falling back to chunked transcript analysis after full-pass failure.")
            chunked_result = _get_viral_clips_via_chat_provider_chunked(
                provider_name,
                transcript_result,
                video_duration,
                model_name=model_name,
                language_code=language_code,
                language_name=language_name,
                max_clip_duration=max_clip_duration,
                max_clips=max_clips,
            )
            chunked_result = _sanitize_provider_result(chunked_result)
            if chunked_result:
                chunked_result["analysis_context_summary"] = global_context_summary
                return _ensure_generated_clip_hooks(
                    chunked_result,
                    transcript_result,
                    provider_name=provider_name,
                    output_language_code=language_code,
                    output_language_name=language_name,
                )
        return None


def get_viral_clips_via_gemini(transcript_result, video_duration, max_clip_duration=MAX_CLIP_DURATION, max_clips=MAX_GENERATED_CLIPS):
    print("🤖  Analyzing with Gemini...")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None

    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    language_code, language_name = describe_output_language(transcript_result.get("language"))
    target_long_count = _target_long_clip_count(max_clip_duration, max_clips)
    global_context_summary = _build_transcript_context_summary(
        transcript_result,
        provider_name="gemini",
        model_name=model_name,
        output_language_code=language_code,
        output_language_name=language_name,
    )
    prompt = build_viral_prompt(
        video_duration,
        transcript_result["text"],
        _extract_words(transcript_result, include_speaker=True),
        output_language_code=language_code,
        output_language_name=language_name,
        max_clips=max_clips,
        max_clip_duration=max_clip_duration,
        min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        minimum_long_clips=target_long_count,
        global_context_summary=global_context_summary,
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

        result_json = sanitize_clip_candidates(
            result_json,
            video_duration,
            transcript_result=transcript_result,
            language_code=language_code,
            max_clips=max_clips,
            max_clip_duration=max_clip_duration,
            min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        )
        if not result_json:
            return None
        result_json["analysis_context_summary"] = global_context_summary
        if _should_retry_for_long_clips(result_json, max_clip_duration, max_clips):
            current_long_count = _count_long_clip_candidates(result_json)
            print(f"🔁 Gemini returned only {current_long_count} long clips. Gathering additional >60s candidates toward ~{target_long_count}...")
            retry_prompt = _build_long_clip_retry_prompt(prompt, current_long_count, target_long_count)
            for attempt in range(2):
                retry_response = client.models.generate_content(
                    model=model_name,
                    contents=retry_prompt
                )
                retry_json = _extract_json_payload(retry_response.text)
                retry_json = sanitize_clip_candidates(
                    retry_json,
                    video_duration,
                    transcript_result=transcript_result,
                    language_code=language_code,
                    max_clips=max_clips,
                    max_clip_duration=max_clip_duration,
                    min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
                )
                if retry_json:
                    result_json = _merge_long_clip_results(result_json, retry_json, max_clips)
                current_long_count = _count_long_clip_candidates(result_json)
                if current_long_count >= target_long_count:
                    break
        return _ensure_generated_clip_hooks(
            result_json,
            transcript_result,
            provider_name="gemini",
            output_language_code=language_code,
            output_language_name=language_name,
            gemini_client=client,
            gemini_model_name=model_name,
        )
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None


def _call_ollama(prompt, base_url, model_name):
    disable_thinking = str(os.environ.get("OLLAMA_DISABLE_THINKING", "true")).strip().lower() in {"1", "true", "yes", "on"}
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0.2},
    }
    # Some reasoning models (e.g. qwen3.*) may put JSON into `thinking` and keep `response` empty.
    # Disabling thinking keeps output in `response` and avoids empty chunk results.
    if disable_thinking:
        payload["think"] = False

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS) as response:
        outer = json.loads(response.read().decode("utf-8"))

    text = ""
    if isinstance(outer.get("response"), str):
        text = outer.get("response", "").strip()
    if not text:
        message = outer.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            text = message.get("content", "").strip()
    if not text and isinstance(outer.get("thinking"), str):
        text = outer.get("thinking", "").strip()
        if text:
            print("ℹ️  Ollama returned content in `thinking`; using it as fallback.")

    return outer, text


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
    disable_thinking = str(os.environ.get("OLLAMA_DISABLE_THINKING", "true")).strip().lower() in {"1", "true", "yes", "on"}
    payload = {
        "model": model_name,
        "prompt": "Reply only with {\"ok\":true}.",
        "stream": False,
        "format": "json",
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0,
            "num_predict": 8,
        },
    }
    if disable_thinking:
        payload["think"] = False

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
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
    target_long_count = _target_long_clip_count(max_clip_duration, max_clips)
    global_context_summary = _build_transcript_context_summary(
        transcript_result,
        provider_name="ollama",
        model_name=model_name,
        output_language_code=language_code,
        output_language_name=language_name,
    )

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
                minimum_long_clips=min(target_long_count, chunk_limit) if target_long_count else 0,
                global_context_summary=global_context_summary,
            )
            print(f"🦙  Ollama chunk {idx + 1}/{len(windows)}: {window['start']:.1f}s - {window['end']:.1f}s")
            outer, text = _call_ollama_with_retries(prompt, base_url, model_name)
            total_prompt_tokens += outer.get("prompt_eval_count") or 0
            total_output_tokens += outer.get("eval_count") or 0

            if not text:
                done_reason = outer.get("done_reason") or "unknown"
                thinking_size = len(outer.get("thinking") or "") if isinstance(outer.get("thinking"), str) else 0
                print(
                    f"⚠️  Ollama chunk {idx + 1} returned an empty response "
                    f"(done_reason={done_reason}, thinking_chars={thinking_size})."
                )
                continue

            result_json = _extract_json_payload(text)
            if not result_json:
                print(f"⚠️  Ollama chunk {idx + 1} returned invalid JSON.")
                continue

            chunk_result = sanitize_clip_candidates(
                result_json,
                video_duration,
                transcript_result=transcript_result,
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
            transcript_result=transcript_result,
            language_code=language_code,
            max_clips=max_clips,
            max_clip_duration=max_clip_duration,
            min_over_one_minute_clip_duration=MIN_OVER_ONE_MINUTE_CLIP_DURATION if max_clip_duration > MAX_CLIP_DURATION else None,
        )
        if not result_json:
            return None
        result_json["analysis_context_summary"] = global_context_summary

        result_json["cost_analysis"] = {
            "model": model_name,
            "provider": "ollama",
            "input_tokens": total_prompt_tokens,
            "output_tokens": total_output_tokens,
            "input_cost": 0,
            "output_cost": 0,
            "total_cost": 0
        }
        return _ensure_generated_clip_hooks(
            result_json,
            transcript_result,
            provider_name="ollama",
            output_language_code=language_code,
            output_language_name=language_name,
            ollama_base_url=base_url,
            ollama_model_name=model_name,
        )
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
    parser.add_argument('--allow-long-clips', action='store_true', help="Compatibility flag. Shorts are generated as 60-180s value clips by default.")
    parser.add_argument('--max-clips', type=int, default=MAX_GENERATED_CLIPS, help=f"Maximum number of generated clips to keep (default: {MAX_GENERATED_CLIPS}).")
    parser.add_argument('--tight-edit-preset', type=str, default=DEFAULT_TIGHT_EDIT_PRESET_ENV, choices=sorted(TIGHT_EDIT_PRESETS.keys()), help=f"Automatically remove pauses and filler words using the selected preset (default: {DEFAULT_TIGHT_EDIT_PRESET_ENV}).")
    
    args = parser.parse_args()
    force_clip_reanalysis = str(os.getenv("FORCE_CLIP_REANALYSIS", "")).strip().lower() in {"1", "true", "yes", "on"}
    args.max_clips = max(1, args.max_clips or MAX_GENERATED_CLIPS)
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

    if args.resume:
        resume_source_video = pipeline.get("source_input_video")
        resume_working_video = pipeline.get("input_video")
        if resume_source_video and os.path.exists(resume_source_video):
            input_video = resume_source_video
        elif resume_working_video and os.path.exists(resume_working_video):
            input_video = resume_working_video
    if input_video:
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

    validation = validate_input_video(input_video)
    if not validation.get("valid"):
        reason = validation.get("reason") or "Die Eingabedatei ist ungueltig."
        technical_detail = validation.get("technical_detail") or ""
        print(f"❌ {reason}")
        if technical_detail:
            print(f"   Details: {technical_detail}")
        update_job_manifest(output_dir, {
            "status": "failed",
            "error": f"{reason}{f' Details: {technical_detail}' if technical_detail else ''}",
            "can_resume": False,
        })
        sys.exit(1)

    source_input_video = input_video
    if args.skip_analysis:
        input_video = ensure_cv2_compatible_video(input_video, output_dir)
    else:
        source_stream = probe_video_stream(source_input_video)
        source_codec = (source_stream.get("codec_name") or "").lower()
        source_ext = os.path.splitext(source_input_video)[1].lower()
        if source_ext != ".mp4" or source_codec != "h264":
            reason_parts = []
            if source_codec and source_codec != "h264":
                reason_parts.append(f"codec={source_codec}")
            if source_ext and source_ext != ".mp4":
                reason_parts.append(f"container={source_ext}")
            reason = ", ".join(reason_parts) if reason_parts else "unsupported source"
            print(
                "⏩ Source is not Safari/OpenCV-friendly "
                f"({reason}), but full H.264 working-copy creation is skipped for clip analysis. "
                "Audio extraction and per-clip previews/renders use FFmpeg directly."
            )

    update_job_manifest(output_dir, {
        "status": "processing",
        "error": None,
        "can_resume": True,
        "pipeline": {
            "input_video": input_video,
            "source_input_video": source_input_video,
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
    force_transcription_reanalysis = str(os.getenv("FORCE_TRANSCRIPTION_REANALYSIS", "")).strip().lower() in {"1", "true", "yes", "on"}
    transcript_file_rejected = False

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
            if force_transcription_reanalysis:
                print("♻️  FORCE_TRANSCRIPTION_REANALYSIS active. Re-transcribing source on resume.")
            else:
                transcript = load_json_file(transcript_file)
                refresh_transcript, refresh_reason = _should_refresh_resume_transcript(
                    transcript,
                    os.environ.get("WHISPER_LANGUAGE") or "de",
                )
                if refresh_transcript:
                    print(f"♻️  Existing transcript will be regenerated: {refresh_reason}")
                    transcript = None
                    transcript_file_rejected = True
                elif transcript:
                    print(f"♻️  Reusing transcript: {transcript_file}")

        clips_data = None
        clip_plan_generated = False
        metadata_transcript_rejected = False
        if args.resume and os.path.exists(metadata_file):
            clips_data = load_json_file(metadata_file)
            if clips_data:
                print(f"♻️  Reusing clip plan: {metadata_file}")
                if not transcript:
                    candidate_transcript = clips_data.get("transcript")
                    refresh_transcript, refresh_reason = _should_refresh_resume_transcript(
                        candidate_transcript,
                        os.environ.get("WHISPER_LANGUAGE") or "de",
                    )
                    if refresh_transcript:
                        print(f"♻️  Metadata transcript will be regenerated: {refresh_reason}")
                        metadata_transcript_rejected = True
                    else:
                        transcript = candidate_transcript
                if force_clip_reanalysis:
                    print("♻️  FORCE_CLIP_REANALYSIS active. Re-running clip analysis on resume.")
                    clips_data = None
                elif transcript_file_rejected:
                    print("♻️  Existing clip plan depends on rejected transcript file. Re-running clip analysis on resume.")
                    clips_data = None
                elif metadata_transcript_rejected:
                    print("♻️  Existing clip plan depends on rejected transcript. Re-running clip analysis on resume.")
                    clips_data = None
                elif (
                    args.resume
                    and clips_data.get("generation_mode") == "fallback_full_video"
                    and clips_data.get("fallback_reason") in {"clip_analysis_failed", "all_clip_renders_failed"}
                ):
                    print("♻️  Existing metadata is fallback-only. Re-running clip analysis on resume.")
                    clips_data = None
                elif not isinstance(clips_data.get("shorts"), list) or not clips_data.get("shorts"):
                    print("♻️  Existing metadata has no viable clips. Re-running clip analysis on resume.")
                    clips_data = None

        if not transcript:
            transcript = transcribe_video(input_video)
            save_json_file(transcript_file, transcript)
            update_job_manifest(output_dir, {
                "pipeline": {
                    "transcript_file": transcript_file,
                }
            })

        if args.interview_mode:
            transcript, diarization_updated = ensure_shortform_speaker_diarization(input_video, transcript)
            if diarization_updated:
                save_json_file(transcript_file, transcript)

        if not clips_data:
            try:
                clips_data = get_viral_clips(
                    transcript,
                    duration,
                    max_clip_duration=target_max_clip_duration,
                    max_clips=args.max_clips,
                )
                if args.interview_mode and clips_data:
                    transcript_language = str(transcript.get("language") or os.environ.get("WHISPER_LANGUAGE") or "de").strip().lower()
                    clips_data = review_interview_clip_attribution(
                        clips_data,
                        transcript,
                        output_language_code=transcript_language,
                        output_language_name=LANGUAGE_LABELS.get(transcript_language, transcript_language or "German (Deutsch)"),
                    )
                clip_plan_generated = bool(clips_data and clips_data.get("shorts"))
            except ClipSelectionConfigurationError as exc:
                print(f"❌ {exc}")
                update_job_manifest(output_dir, {
                    "status": "failed",
                    "error": str(exc),
                    "can_resume": True,
                })
                sys.exit(1)

        if not clips_data or 'shorts' not in clips_data or not clips_data['shorts']:
            print("❌ Failed to identify clips. Aborting without whole-video fallback.")
            analysis_failed = True
            failed_outputs += 1
        else:
            print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
            clips_data['transcript'] = transcript
            clips_data['generation_mode'] = 'clips'

            analysis_revision = str(clips_data.get('analysis_revision') or '')
            if clip_plan_generated:
                analysis_revision = str(int(time.time() * 1000))
                clips_data['analysis_revision'] = analysis_revision

            source_video_filename = os.path.basename(input_video)
            for i, clip in enumerate(clips_data['shorts']):
                if analysis_revision:
                    clip['analysis_revision'] = analysis_revision
                default_clip_filename = (
                    f"{video_title}_plan_{analysis_revision}_clip_{i+1}.mp4"
                    if clip_plan_generated and analysis_revision
                    else f"{video_title}_clip_{i+1}.mp4"
                )
                clip_filename = clip.get('video_filename') or default_clip_filename
                clip['video_filename'] = clip_filename
                clip['source_video_filename'] = clip.get('source_video_filename') or source_video_filename
                clip['original_video_filename'] = clip.get('original_video_filename') or os.path.basename(source_input_video)
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
                    print("❌ No clip outputs succeeded. Aborting without whole-video fallback.")
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
            "source_input_video": source_input_video,
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
    if args.url and not args.keep_original and not args.analysis_only and manifest_status == "completed":
        cleanup_targets = [source_input_video]
        if input_video != source_input_video:
            cleanup_targets.append(input_video)
        cleaned = 0
        for cleanup_path in cleanup_targets:
            try:
                if cleanup_path and os.path.exists(cleanup_path):
                    os.remove(cleanup_path)
                    cleaned += 1
            except Exception as cleanup_exc:
                print(f"⚠️  Failed to remove temporary source '{cleanup_path}': {cleanup_exc}")
        if cleaned:
            print(f"🗑️  Cleaned up downloaded video source files ({cleaned}).")

    total_time = time.time() - script_start_time
    print(f"\n⏱️  Total execution time: {total_time:.2f}s")
    sys.exit(0 if overall_success else 1)
