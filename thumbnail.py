import os
import uuid
import time
import json
import base64
import io
import mimetypes
import gc
from google import genai
from google.genai import types
from PIL import Image
import httpx

DEPRECATED_GEMINI_IMAGE_MODELS = set()

PREFERRED_GEMINI_IMAGE_MODELS = [
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
    "gemini-2.5-flash-image",
    "nano-banana-pro-preview",
    "gemini-2.0-flash-preview-image-generation",
]

MAX_REFERENCE_IMAGE_EDGE = 1280


def _timestamp_filename(base_name: str, extension: str) -> str:
    """Generate a filename with timestamp to prevent browser caching."""
    ts = int(time.time())
    return f"{base_name}_{ts}.{extension}"


def analyze_video_for_titles(api_key, video_path, transcript=None):
    """
    Transcribes a video and uses Gemini to suggest viral YouTube titles.
    If transcript is provided, skips Whisper transcription.
    Returns: { "titles": [...], "transcript_summary": "...", "language": "...", "segments": [...], "video_duration": ... }
    """
    if transcript is None:
        from main import transcribe_video
        print("🎬 [Thumbnail] Transcribing video...")
        transcript = transcribe_video(video_path)
    else:
        print("🎬 [Thumbnail] Using pre-computed transcript (Whisper already done)...")

    print("📤 [Thumbnail] Uploading video to Gemini...")
    client = genai.Client(api_key=api_key)

    file_upload = client.files.upload(file=video_path)
    while True:
        file_info = client.files.get(name=file_upload.name)
        if file_info.state == "ACTIVE":
            break
        elif file_info.state == "FAILED":
            raise Exception("Video processing failed by Gemini.")
        time.sleep(2)

    prompt = f"""You are a YouTube title expert who creates viral, click-worthy titles.

Analyze this video and its transcript, then suggest 10 YouTube titles that would maximize CTR (click-through rate).

TRANSCRIPT:
{transcript['text']}

RULES:
- Titles must be under 70 characters
- Use power words, curiosity gaps, and emotional triggers
- Mix styles: how-to, listicle, story-driven, controversial, question-based
- Make them specific to the actual content, not generic
- Include numbers where appropriate
- Consider the language of the video (detected: {transcript['language']})
- Titles should be in the SAME LANGUAGE as the video transcript

Also provide a brief summary of the video content (2-3 sentences).

After generating all 10 titles, pick the TOP 2 you most recommend and explain concisely WHY (CTR potential, emotional hook, uniqueness, etc.). Reference them by their 0-based index in the titles array.

OUTPUT JSON:
{{
    "titles": ["title1", "title2", ...],
    "transcript_summary": "Brief summary of the video content...",
    "language": "{transcript['language']}",
    "recommended": [
        {{"index": 0, "reason": "Why this title is best..."}},
        {{"index": 3, "reason": "Why this title is second best..."}}
    ]
}}"""

    print("🤖 [Thumbnail] Asking Gemini for title suggestions...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[file_upload, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    # Extract segments and duration from transcript for later use
    segments = transcript.get("segments", [])
    video_duration = segments[-1]["end"] if segments else 0

    try:
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]

        result = json.loads(text)
        result["transcript_summary"] = result.get("transcript_summary", "")
        result["language"] = result.get("language", transcript["language"])
        result["segments"] = segments
        result["video_duration"] = video_duration
        return result
    except json.JSONDecodeError:
        print(f"❌ [Thumbnail] Failed to parse titles JSON: {response.text}")
        return {
            "titles": ["Could not generate titles - please try again"],
            "transcript_summary": transcript["text"][:500],
            "language": transcript["language"],
            "segments": segments,
            "video_duration": video_duration
        }


def refine_titles(api_key, context, user_message, conversation_history=None):
    """
    Takes video context + user feedback and returns refined title suggestions.
    """
    client = genai.Client(api_key=api_key)

    history_text = ""
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "user")
            history_text += f"\n{role.upper()}: {msg['content']}"

    prompt = f"""You are a YouTube title expert. Based on the video context and the user's feedback, suggest 8 new refined YouTube titles.

VIDEO CONTEXT:
{context}

CONVERSATION HISTORY:{history_text}

USER'S NEW REQUEST:
{user_message}

RULES:
- Titles must be under 70 characters
- Incorporate the user's feedback/direction
- Keep titles viral and click-worthy
- If the user asks for a specific style, follow it
- Titles should be in the same language as the original content

OUTPUT JSON:
{{
    "titles": ["title1", "title2", ...]
}}"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    try:
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]

        return json.loads(text)
    except json.JSONDecodeError:
        print(f"❌ [Thumbnail] Failed to parse refined titles: {response.text}")
        return {"titles": ["Could not refine titles - please try again"]}


def generate_thumbnail(api_key, title, session_id, face_image_path=None, bg_image_path=None, extra_prompt="", count=3, video_context=""):
    """
    Generates YouTube thumbnails using Gemini image generation.
    Returns list of saved image paths (relative URLs).
    """
    client = genai.Client(api_key=api_key)

    output_dir = os.path.join("output", "thumbnails", session_id)
    os.makedirs(output_dir, exist_ok=True)

    prompt_parts = []

    # Add face image if provided
    if face_image_path and os.path.exists(face_image_path):
        face_img = Image.open(face_image_path)
        prompt_parts.append(face_img)

    # Add background image if provided
    if bg_image_path and os.path.exists(bg_image_path):
        bg_img = Image.open(bg_image_path)
        prompt_parts.append(bg_img)

    # Build video context block
    context_block = ""
    if video_context:
        context_block = f"""
VIDEO CONTEXT (use this to understand the video and design a relevant thumbnail):
{video_context}
"""

    # Build extra instructions block (high priority)
    extra_block = ""
    if extra_prompt:
        extra_block = f"""
⚠️ MANDATORY USER INSTRUCTIONS (MUST follow these exactly — they override any default behavior):
{extra_prompt}
"""

    text_prompt = f"""Generate a professional, eye-catching YouTube thumbnail image.

VIDEO TITLE (for reference — do NOT put the full title on the thumbnail): "{title}"
{context_block}
TEXT ON THE THUMBNAIL:
- Based on the title AND the video context, create a SHORT visual hook: 1 to 5 words maximum
- It should capture the core emotion, surprise, or promise of the video
- The thumbnail text should COMPLEMENT the YouTube title (which appears below), not repeat it
- Examples: "$10K EN 30 DÍAS", "ESTO FUNCIONA", "NO LO SABÍAS", "GRATIS 🔥"
- Use ALL CAPS for maximum impact, split into 2-3 lines
{extra_block}
DESIGN REQUIREMENTS:
- The text MUST be large, bold, and high-contrast (readable at small sizes)
- Use vibrant, eye-catching colors that match the video's mood
- Professional YouTube thumbnail aesthetic
- Clean composition — text and face/subject as clear focal points
- NO clutter, NO small text, NO watermarks"""

    if face_image_path and os.path.exists(face_image_path):
        text_prompt += "\n- Include the provided face/person prominently with an exaggerated expression (surprise, excitement, shock)"

    if bg_image_path and os.path.exists(bg_image_path):
        text_prompt += "\n- Use the provided background image as the base/backdrop"

    prompt_parts.append(text_prompt)

    thumbnails = []
    for i in range(count):
        print(f"🎨 [Thumbnail] Generating thumbnail {i + 1}/{count}...")
        try:
            response = client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=prompt_parts,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="16:9",
                        image_size="2K"
                    )
                )
            )

            for part in response.parts:
                if part.text is not None:
                    print(f"📝 [Thumbnail] Gemini text: {part.text}")
                elif image := part.as_image():
                    filename = _timestamp_filename(f"thumb_{i + 1}", "jpg")
                    filepath = os.path.join(output_dir, filename)
                    image.save(filepath)
                    thumbnails.append(f"/thumbnails/{session_id}/{filename}")
                    print(f"✅ [Thumbnail] Saved: {filepath}")
                    break

        except Exception as e:
            print(f"❌ [Thumbnail] Generation {i + 1} failed: {e}")

    return thumbnails


def generate_longform_thumbnail_variants(
    *,
    provider,
    prompt,
    output_dir,
    count=1,
    gemini_api_key="",
    openai_api_key="",
    midjourney_api_key="",
    midjourney_base_url="",
    reference_image_paths=None,
    model_name=None,
):
    normalized_provider = str(provider or "").strip().lower()
    refs = [path for path in (reference_image_paths or []) if path and os.path.exists(path)]
    os.makedirs(output_dir, exist_ok=True)
    if normalized_provider == "gemini":
        return _generate_longform_thumbnail_variants_gemini(
            api_key=gemini_api_key,
            prompt=prompt,
            output_dir=output_dir,
            count=count,
            reference_image_paths=refs,
            model_name=model_name or "gemini-3.1-flash-image-preview",
        )
    if normalized_provider == "openai":
        return _generate_longform_thumbnail_variants_openai(
            api_key=openai_api_key,
            prompt=prompt,
            output_dir=output_dir,
            count=count,
            reference_image_paths=refs,
            model_name=model_name or "gpt-image-1",
        )
    if normalized_provider == "midjourney":
        return _generate_longform_thumbnail_variants_midjourney(
            api_key=midjourney_api_key,
            base_url=midjourney_base_url,
            prompt=prompt,
            output_dir=output_dir,
            count=count,
            reference_image_paths=refs,
            model_name=model_name or "auto",
        )
    raise ValueError(f"Unsupported thumbnail provider: {provider}")


def _prepare_reference_image(path, *, max_edge=MAX_REFERENCE_IMAGE_EDGE, prefer_format="JPEG"):
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        longest_edge = max(width, height)
        if longest_edge > max_edge:
            scale = max_edge / float(longest_edge)
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            image = image.resize(new_size, Image.LANCZOS)
        buffer = io.BytesIO()
        fmt = "PNG" if str(prefer_format or "").upper() == "PNG" else "JPEG"
        save_kwargs = {"format": fmt}
        mime_type = "image/png" if fmt == "PNG" else "image/jpeg"
        if fmt == "JPEG":
            save_kwargs.update({"quality": 90, "optimize": True})
        image.save(buffer, **save_kwargs)
        return buffer.getvalue(), mime_type


def _read_image_inline_data(path):
    raw, mime_type = _prepare_reference_image(path)
    encoded = base64.b64encode(raw).decode("utf-8")
    return {"mimeType": mime_type, "data": encoded}


def _extract_gemini_images_from_response(payload):
    generated = []
    candidates = payload.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not inline_data:
                continue
            data = inline_data.get("data")
            if not data:
                continue
            try:
                generated.append(base64.b64decode(data))
            except Exception:
                continue
    return generated


def _list_gemini_generate_content_image_models(api_key):
    with httpx.Client(timeout=60.0) as client:
        response = client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
        )
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models") or []
    available = []
    for model in models:
        methods = [str(item or "") for item in (model.get("supportedGenerationMethods") or [])]
        if "generateContent" not in methods:
            continue
        name = str(model.get("name") or "")
        normalized_name = name.replace("models/", "").strip()
        searchable = " ".join([
            normalized_name.lower(),
            str(model.get("displayName") or "").lower(),
            str(model.get("description") or "").lower(),
        ])
        if "image" not in searchable:
            continue
        if normalized_name:
            available.append(normalized_name)
    deduped = []
    for item in available:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _normalize_gemini_model_name(model_name):
    normalized = str(model_name or "").strip()
    if not normalized:
        return "auto"
    lowered = normalized.lower()
    if lowered == "gemini-2.5-flash":
        return "gemini-2.5-flash-image"
    if lowered == "gemini-3.1-flash-image":
        return "gemini-3.1-flash-image-preview"
    if lowered == "auto" or lowered in DEPRECATED_GEMINI_IMAGE_MODELS:
        return "auto"
    return normalized


def _rank_gemini_models(models):
    available = []
    seen = set()
    for preferred in PREFERRED_GEMINI_IMAGE_MODELS:
        if preferred in models and preferred not in seen:
            available.append(preferred)
            seen.add(preferred)
    for model in models:
        if model not in seen:
            available.append(model)
            seen.add(model)
    return available


def _post_gemini_image_generation_sdk(*, api_key, model_name, prompt, reference_image_paths):
    client = genai.Client(api_key=api_key)
    parts = []
    for ref_path in reference_image_paths[:8]:
        raw, _ = _prepare_reference_image(ref_path, prefer_format="PNG")
        parts.append(Image.open(io.BytesIO(raw)).copy())
    parts.append(prompt)
    response = client.models.generate_content(
        model=model_name,
        contents=parts,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
                image_size="2K",
            ),
        ),
    )
    generated = []
    for part in getattr(response, "parts", []) or []:
        image = None
        try:
            image = part.as_image() if getattr(part, "as_image", None) else None
        except Exception:
            image = None
        if image is None:
            continue
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        generated.append(buffer.getvalue())
    if not generated:
        raise ValueError("Gemini SDK hat kein Bild zurueckgegeben.")
    return generated


def _post_gemini_image_generation(*, api_key, model_name, prompt, reference_image_paths):
    parts = [{"text": prompt}]
    for ref_path in reference_image_paths[:8]:
        parts.append({"inlineData": _read_image_inline_data(ref_path)})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": "16:9",
                "imageSize": "2K",
            },
        },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    with httpx.Client(timeout=180.0) as client:
        response = client.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        detail = response.text.strip()
        try:
            parsed = response.json()
            detail = (
                parsed.get("error", {}).get("message")
                or parsed.get("detail")
                or detail
            )
        except Exception:
            pass
        raise ValueError(f"Gemini {response.status_code}: {detail}")

    payload = response.json()
    raw_images = _extract_gemini_images_from_response(payload)
    if not raw_images:
        raise ValueError("Gemini hat kein Bild zurueckgegeben.")
    return raw_images


def _generate_longform_thumbnail_variants_gemini(*, api_key, prompt, output_dir, count, reference_image_paths, model_name):
    if not api_key:
        raise ValueError("Gemini API key fehlt. Bitte in den App-Einstellungen konfigurieren.")
    generated = []
    requested_model = _normalize_gemini_model_name(model_name)
    requested_count = max(1, int(count or 1))
    discovered_models = []
    discovery_error = None
    try:
        discovered_models = _list_gemini_generate_content_image_models(api_key)
    except Exception as exc:
        discovery_error = str(exc)

    candidate_models = []
    if requested_model != "auto":
        candidate_models.append(requested_model)
    candidate_models.extend(_rank_gemini_models(discovered_models))
    fallback_models = []
    for candidate in candidate_models:
        if candidate and candidate not in fallback_models:
            fallback_models.append(candidate)

    if not fallback_models:
        detail = "Fuer diesen Gemini-Key wurden keine Bildmodelle mit generateContent gefunden."
        if discovery_error:
            detail = f"{detail} ListModels fehlgeschlagen: {discovery_error}"
        raise ValueError(detail)

    provider_errors = []
    for index in range(requested_count):
        attempt_errors = []
        for candidate_model in fallback_models:
            try:
                raw_images = _post_gemini_image_generation(
                    api_key=api_key,
                    model_name=candidate_model,
                    prompt=prompt,
                    reference_image_paths=reference_image_paths,
                )
                raw = raw_images[0]
                filename = _timestamp_filename(f"gemini_{index + 1}", "png")
                filepath = os.path.join(output_dir, filename)
                with open(filepath, "wb") as handle:
                    handle.write(raw)
                generated.append(filepath)
                attempt_errors = []
                break
            except Exception as exc:
                attempt_errors.append(f"{candidate_model} REST: {exc}")
                try:
                    raw_images = _post_gemini_image_generation_sdk(
                        api_key=api_key,
                        model_name=candidate_model,
                        prompt=prompt,
                        reference_image_paths=reference_image_paths,
                    )
                    raw = raw_images[0]
                    filename = _timestamp_filename(f"gemini_{index + 1}", "png")
                    filepath = os.path.join(output_dir, filename)
                    with open(filepath, "wb") as handle:
                        handle.write(raw)
                    generated.append(filepath)
                    attempt_errors = []
                    break
                except Exception as sdk_exc:
                    attempt_errors.append(f"{candidate_model} SDK: {sdk_exc}")
        if attempt_errors:
            provider_errors.extend(attempt_errors)

    if not generated and provider_errors:
        available_hint = f" Verfuegbar fuer diesen Key: {', '.join(discovered_models[:8])}." if discovered_models else ""
        raise ValueError(f"{' ; '.join(provider_errors[:8])}{available_hint}")
    return generated


def _generate_longform_thumbnail_variants_openai(*, api_key, prompt, output_dir, count, reference_image_paths, model_name):
    if not api_key:
        raise ValueError("OpenAI API key fehlt. Bitte in den App-Einstellungen konfigurieren.")
    files = []
    opened_handles = []
    try:
        for ref_path in reference_image_paths[:16]:
            handle = open(ref_path, "rb")
            opened_handles.append(handle)
            files.append(("image[]", (os.path.basename(ref_path), handle, "image/png")))

        # YouTube thumbnail: 16:9 aspect ratio
        # 1280x720 (720p) or 1920x1080 (1080p)
        # GPT-image-1 supports: 1024x1024, 1536x1024 (3:2), 1024x1536 (2:3), 1024x1792, 1792x1024
        # Use 1792x1024 for 16:9 aspect ratio
        data = {
            "model": model_name,
            "prompt": prompt,
            "quality": "high",
            "size": "1792x1024",  # 16:9 YouTube thumbnail resolution
            "output_format": "png",
            "n": str(max(1, int(count or 1))),
        }
        with httpx.Client(timeout=180.0) as client:
            response = client.post(
                "https://api.openai.com/v1/images/edits" if files else "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files=files or None,
            )
            response.raise_for_status()
        payload = response.json()
        images = payload.get("data") or []
        generated = []
        for index, item in enumerate(images, start=1):
            image_b64 = item.get("b64_json")
            image_url = item.get("url")
            if image_b64:
                raw = base64.b64decode(image_b64)
            elif image_url:
                with httpx.Client(timeout=180.0) as http_client:
                    raw = http_client.get(image_url).content
            else:
                continue
            filename = _timestamp_filename(f"openai_{index}", "png")
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as handle:
                handle.write(raw)
            generated.append(filepath)
        return generated
    finally:
        for handle in opened_handles:
            try:
                handle.close()
            except Exception:
                pass


def _encode_reference_image_payload(ref_path):
    raw, mime_type = _prepare_reference_image(ref_path)
    return {
        "filename": os.path.basename(ref_path),
        "mime_type": mime_type,
        "data_url": f"data:{mime_type};base64,{base64.b64encode(raw).decode('utf-8')}",
    }


def _extract_midjourney_images(payload):
    candidate_groups = []
    if isinstance(payload, dict):
        candidate_groups.extend([
            payload.get("data"),
            payload.get("images"),
            payload.get("output"),
            payload.get("results"),
        ])
    extracted = []
    for group in candidate_groups:
        if isinstance(group, list):
            extracted.extend(group)
    return extracted


def _decode_midjourney_image_item(item):
    if isinstance(item, str):
        return {"url": item}
    if not isinstance(item, dict):
        return None
    if item.get("url"):
        return {"url": item["url"]}
    if item.get("data_url"):
        data_url = str(item["data_url"])
        if "," in data_url:
            return {"raw": base64.b64decode(data_url.split(",", 1)[1])}
    image_b64 = item.get("b64_json") or item.get("base64")
    if image_b64:
        return {"raw": base64.b64decode(image_b64)}
    return None


def _generate_longform_thumbnail_variants_midjourney(*, api_key, base_url, prompt, output_dir, count, reference_image_paths, model_name):
    bridge_url = str(base_url or "").strip()
    if not bridge_url:
        raise ValueError("Midjourney Bridge URL ist nicht gesetzt. Bitte global in den Einstellungen hinterlegen.")

    # Append YouTube 16:9 requirement to prompt text
    prompt_with_ratio = prompt.strip()
    if "--ar 16:9" not in prompt_with_ratio.lower():
        prompt_with_ratio += "\n\nIMPORTANT: Generate this image in 16:9 aspect ratio for YouTube thumbnails (1280x720 or 1920x1080 pixels)."
    if "--ar" not in prompt_with_ratio.lower():
        prompt_with_ratio += " --ar 16:9"

    payload = {
        "prompt": prompt_with_ratio,
        "model": model_name,
        "count": max(1, int(count or 1)),
        "aspect_ratio": "16:9",  # YouTube thumbnail standard
        "resolution": "1920x1080",  # Full HD YouTube thumbnail
        "reference_images": [_encode_reference_image_payload(ref_path) for ref_path in reference_image_paths[:12]],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=300.0) as client:
        response = client.post(bridge_url, headers=headers, json=payload)
        response.raise_for_status()
        result_payload = response.json()

    images = _extract_midjourney_images(result_payload)
    if not images:
        raise ValueError("Midjourney-Bridge hat keine Bilder zurueckgegeben.")

    generated = []
    with httpx.Client(timeout=300.0) as client:
        for index, item in enumerate(images[: max(1, int(count or 1))], start=1):
            decoded = _decode_midjourney_image_item(item)
            if not decoded:
                continue
            if decoded.get("raw") is not None:
                raw = decoded["raw"]
            else:
                raw = client.get(decoded["url"]).content
            filename = _timestamp_filename(f"midjourney_{index}", "png")
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as handle:
                handle.write(raw)
            generated.append(filepath)
    if not generated:
        raise ValueError("Midjourney-Bridge hat nur unlesbare Bilddaten geliefert.")
    return generated


def generate_youtube_description(api_key, title, transcript_segments, language, video_duration):
    """
    Uses Gemini to generate a YouTube description with chapter markers from transcript segments.
    Returns: { "description": "full description text with chapters" }
    """
    client = genai.Client(api_key=api_key)

    # Format segments for the prompt
    formatted_segments = []
    for seg in transcript_segments:
        start = seg.get("start", 0)
        mins = int(start // 60)
        secs = int(start % 60)
        timestamp = f"{mins}:{secs:02d}"
        formatted_segments.append(f"[{timestamp}] {seg.get('text', '').strip()}")

    segments_text = "\n".join(formatted_segments)

    # Format total duration
    dur_mins = int(video_duration // 60)
    dur_secs = int(video_duration % 60)
    duration_str = f"{dur_mins}:{dur_secs:02d}"

    prompt = f"""You are a YouTube SEO expert. Generate a complete YouTube video description for the following video.

VIDEO TITLE: "{title}"
VIDEO LANGUAGE: {language}
VIDEO DURATION: {duration_str}

TRANSCRIPT WITH TIMESTAMPS:
{segments_text}

REQUIREMENTS:
1. Write the description in the SAME LANGUAGE as the video ({language})
2. Start with a compelling 2-3 sentence summary/hook
3. Add relevant CTAs (subscribe, like, comment)
4. Generate YouTube CHAPTERS based on the transcript timestamps:
   - First chapter MUST start at 0:00
   - Minimum 3 chapters, each at least 10 seconds apart
   - Chapter titles should be concise and descriptive
   - Format: 0:00 Chapter Title
   - Place chapters in their own section with a blank line before and after
5. Add 5-10 relevant hashtags at the end
6. Keep the total description under 5000 characters

OUTPUT: Return ONLY the description text (no JSON wrapper, no markdown code blocks). The description should be ready to paste directly into YouTube."""

    print("🤖 [Thumbnail] Generating YouTube description with chapters...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt],
    )

    description = response.text.strip()
    # Clean up any accidental markdown wrappers
    if description.startswith("```"):
        lines = description.split("\n")
        description = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return {"description": description}
