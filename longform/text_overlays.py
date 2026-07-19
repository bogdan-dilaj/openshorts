from __future__ import annotations

import concurrent.futures
import json
import os
import urllib.request
from typing import Any, Dict, List, Optional

from google import genai

from .models import active_camera_roles


def normalize_language_hint(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("de"):
        return "de"
    if text.startswith("en"):
        return "en"
    return text[:8]


def normalize_text_overlay_suggestions(values: Any, *, limit: int = 10) -> List[str]:
    normalized: List[str] = []
    for item in values if isinstance(values, list) else []:
        text = str(item or "").strip()
        if not text:
            continue
        cleaned = text.replace("\n", " ").strip()[:80]
        if not cleaned or cleaned in normalized:
            continue
        normalized.append(cleaned)
        if len(normalized) >= limit:
            break
    return normalized


def default_text_overlay_suggestions(language: str) -> List[str]:
    normalized_language = normalize_language_hint(language) or "de"
    if normalized_language == "de":
        return [
            "Das wusste niemand",
            "Hier lief alles falsch",
            "Die bittere Wahrheit",
            "Warum das eskalierte",
            "So hat alles begonnen",
            "Was dann passierte",
            "Darueber spricht niemand",
            "Das veraendert alles",
            "Hier wurde es kritisch",
            "Der echte Grund",
        ]
    return [
        "Nobody saw this coming",
        "Where it went wrong",
        "The hard truth",
        "Why it escalated",
        "How it really started",
        "What happened next",
        "No one talks about this",
        "This changes everything",
        "Where it got serious",
        "The real reason",
    ]


def build_text_overlay_prompt(*, project: Dict[str, Any], base_prompt: str, transcript_excerpt: str, count: int) -> str:
    config = project.get("config") or {}
    mode = str(project.get("mode") or "single").strip().lower()
    language = normalize_language_hint(config.get("analysis_language")) or "de"
    primary_role = str(config.get("primary_audio_camera") or ("host" if mode == "interview" else "single")).strip().lower()
    project_name = str(project.get("project_name") or "").strip()
    role_labels = ", ".join(active_camera_roles(mode))
    response_language = "German" if language == "de" else "English"
    parts = [
        "You generate short high-click thumbnail text overlays for longform podcast/video thumbnails.",
        f"Return exactly {count} options as JSON only with this schema: {{\"overlays\": [\"...\"]}}",
        f"Write the overlays in {response_language}.",
        "Rules:",
        "- 2 to 8 words each.",
        "- Maximum 42 characters each.",
        "- Concrete, emotionally clear, and easy to read on a thumbnail.",
        "- No emojis, no hashtags, no quotation marks, no trailing punctuation.",
        "- Avoid generic filler like 'watch until the end'.",
        "- Make the options distinct from each other.",
        "- They should feel like overlay text, not full titles.",
        f"Project name: {project_name or 'Longform project'}",
        f"Project mode: {mode}",
        f"Available speaker roles: {role_labels}",
        f"Primary audio role: {primary_role or 'unknown'}",
    ]
    cleaned_prompt = str(base_prompt or "").strip()
    if cleaned_prompt:
        parts.extend([
            "The current thumbnail prompt template is below. Respect its intent and use the <text_overlay> placeholder as the thing you are generating:",
            cleaned_prompt,
        ])
    if transcript_excerpt:
        parts.extend(["Transcript excerpt for context:", transcript_excerpt])
    parts.append("Return JSON only.")
    return "\n".join(parts)


def build_transcript_excerpt_from_map(project: Dict[str, Any], transcript_map: Dict[str, Any], *, max_chars: int = 7000) -> str:
    project_files = project.get("files") or {}
    chunks: List[str] = []
    for role in active_camera_roles(project.get("mode") or "single"):
        for item in project_files.get(role) or []:
            transcript = ((transcript_map.get("files") or {}).get(item.get("id")) or {})
            text = str(transcript.get("text") or "").strip()
            if text:
                chunks.append(f"[{role}] {text}")
    excerpt = "\n\n".join(chunks).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rsplit(" ", 1)[0].strip()
    return excerpt


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
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
        payload = json.loads(cleaned)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        try:
            payload = json.loads(cleaned[start_idx:end_idx + 1])
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _extract_chat_message_text(payload: Any) -> str:
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


def _extract_minimax_response_text(body: Dict[str, Any]) -> str:
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            text = _extract_chat_message_text(choice.get("message"))
            if text.strip():
                return text.strip()
            text = _extract_chat_message_text(choice.get("delta"))
            if text.strip():
                return text.strip()

    for key in ("reply", "response", "output", "text"):
        value = body.get(key)
        text = _extract_chat_message_text(value)
        if text.strip():
            return text.strip()

    output = body.get("output")
    if isinstance(output, dict):
        for key in ("text", "content", "message"):
            text = _extract_chat_message_text(output.get(key))
            if text.strip():
                return text.strip()

    return ""


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], *, timeout_seconds: int = 120) -> Dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _call_openai_json(ai_config: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    api_key = str(ai_config.get("openai_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY fehlt.")
    model_name = str(ai_config.get("openai_model") or "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    body = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "You are a senior short-form editor. Reply only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1200,
        },
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout_seconds=180,
    )
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI lieferte keine choices.")
    payload = _extract_json_payload(_extract_chat_message_text((choices[0] or {}).get("message")))
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI lieferte kein gueltiges JSON fuer Text-Overlays.")
    return payload


def _call_claude_json(ai_config: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    api_key = str(ai_config.get("claude_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("CLAUDE_API_KEY fehlt.")
    model_name = str(ai_config.get("claude_model") or "claude-3-5-sonnet-latest").strip() or "claude-3-5-sonnet-latest"
    body = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": model_name,
            "max_tokens": 1200,
            "temperature": 0.2,
            "system": "You are a senior short-form editor. Reply only with valid JSON.",
            "messages": [{"role": "user", "content": prompt}],
        },
        {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
        timeout_seconds=180,
    )
    payload = _extract_json_payload(_extract_chat_message_text(body.get("content")))
    if not isinstance(payload, dict):
        raise RuntimeError("Claude lieferte kein gueltiges JSON fuer Text-Overlays.")
    return payload


def _call_minimax_json(ai_config: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    api_key = str(ai_config.get("minimax_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY fehlt.")
    model_name = str(ai_config.get("minimax_model") or "MiniMax-M3").strip() or "MiniMax-M3"
    base_url = str(ai_config.get("minimax_base_url") or os.environ.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
    body = _post_json(
        f"{base_url}/text/chatcompletion_v2",
        {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "You are a senior short-form editor. Reply only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 4000,
            "temperature": 0.2,
        },
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout_seconds=180,
    )
    payload = _extract_json_payload(_extract_minimax_response_text(body))
    if not isinstance(payload, dict):
        raise RuntimeError("MiniMax lieferte kein gueltiges JSON fuer Text-Overlays.")
    return payload


def _call_ollama_json(ai_config: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    base_url = str(ai_config.get("ollama_base_url") or "").strip()
    model_name = str(ai_config.get("ollama_model") or "").strip()
    if not base_url or not model_name:
        raise RuntimeError("Ollama Base-URL oder Modell fehlt.")
    body = _post_json(
        f"{base_url.rstrip('/')}/api/generate",
        {"model": model_name, "prompt": prompt, "stream": False, "format": "json"},
        {"Content-Type": "application/json"},
        timeout_seconds=180,
    )
    payload = _extract_json_payload(str(body.get("response") or ""))
    if not isinstance(payload, dict):
        raise RuntimeError("Ollama lieferte kein gueltiges JSON fuer Text-Overlays.")
    return payload


def _call_gemini_json(ai_config: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    api_key = str(ai_config.get("gemini_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("Gemini API-Key fehlt.")
    model_name = str(ai_config.get("gemini_model") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model_name, contents=prompt)
    payload = _extract_json_payload(getattr(response, "text", "") or "")
    if not isinstance(payload, dict):
        raise RuntimeError("Gemini lieferte kein gueltiges JSON fuer Text-Overlays.")
    return payload


def call_text_overlay_provider(ai_config: Dict[str, Any], prompt: str, *, timeout_seconds: int = 45) -> Dict[str, Any]:
    provider = str(ai_config.get("provider") or "ollama").strip().lower()

    def _do_call() -> Dict[str, Any]:
        if provider == "off":
            raise RuntimeError("KI-Provider ist deaktiviert.")
        if provider == "gemini":
            return _call_gemini_json(ai_config, prompt)
        if provider == "openai":
            return _call_openai_json(ai_config, prompt)
        if provider == "claude":
            return _call_claude_json(ai_config, prompt)
        if provider == "minimax":
            return _call_minimax_json(ai_config, prompt)
        if provider == "ollama":
            return _call_ollama_json(ai_config, prompt)
        raise RuntimeError(f"Nicht unterstuetzter KI-Provider fuer Text-Overlays: {provider}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_call)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise RuntimeError(f"Text-Overlay-Vorschlaege haben nach {timeout_seconds}s ein Timeout erreicht.") from exc
