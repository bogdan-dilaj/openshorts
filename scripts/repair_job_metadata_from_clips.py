import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Optional

from job_store import _build_legacy_grouped_clips, _discover_video_files, find_metadata_path, load_job_manifest
from subtitles import transcribe_audio


def _ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").strip()
    try:
        return max(0.0, float(output))
    except (TypeError, ValueError):
        return 0.0


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None

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


def _call_ollama_json(prompt: str, *, base_url: str, model_name: str) -> Dict[str, Any]:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0.35,
        },
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1800) as response:
        body = json.loads(response.read().decode("utf-8"))
    parsed = _extract_json_payload(body.get("response", ""))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Ollama returned invalid JSON: {body.get('response', '')[:500]}")
    return parsed


def _generate_clip_copy(
    transcript_text: str,
    *,
    clip_label: str,
    language_hint: str,
    base_url: str,
    model_name: str,
) -> Dict[str, str]:
    safe_text = (transcript_text or "").strip()[:5000]
    prompt = f"""Du bist ein Shortform-Copywriter fuer virale Reels, TikToks und YouTube Shorts.

Erstelle fuer den folgenden Clip genau EIN JSON-Objekt.

CLIP:
{clip_label}

SPRACHE:
{language_hint or 'Deutsch'}

TRANSKRIPT:
{safe_text}

REGELN:
- Schreibe alles auf Deutsch.
- `title`: maximal 55 Zeichen, konkret, klickstark, keine Dateinamen, keine Platzhalter.
- `description_tiktok`: 1 bis 3 kurze Saetze fuer TikTok, aufmerksamkeitsstark und inhaltlich passend.
- `description_instagram`: 1 bis 3 kurze Saetze fuer Instagram Reels, etwas nativer formuliert.
- `hook`: maximal 6 Woerter, kurz und reisserisch.
- Keine Hashtag-Wand. Keine generischen Phrasen wie "Generated video".
- Bleib eng am Inhalt des Transkripts.

OUTPUT JSON:
{{
  "title": "...",
  "description_tiktok": "...",
  "description_instagram": "...",
  "hook": "..."
}}
"""
    payload = _call_ollama_json(prompt, base_url=base_url, model_name=model_name)
    title = str(payload.get("title") or "").strip()
    description_tiktok = str(payload.get("description_tiktok") or "").strip()
    description_instagram = str(payload.get("description_instagram") or "").strip()
    hook = str(payload.get("hook") or "").strip()
    if not title:
        raise RuntimeError(f"Missing title in Ollama response for {clip_label}")
    return {
        "title": title,
        "description_tiktok": description_tiktok or "Starker Ausschnitt aus dem Interview.",
        "description_instagram": description_instagram or "Spannender Reel-Moment aus dem Interview.",
        "hook": hook,
    }


def _load_transcript_language(output_dir: str) -> str:
    manifest = load_job_manifest(output_dir)
    transcript_path = manifest.get("pipeline", {}).get("transcript_file")
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as handle:
                transcript_data = json.load(handle)
            language = str(transcript_data.get("language") or "").strip()
            if language:
                return language
        except Exception:
            pass
    return "de"


def _flatten_transcript_text(transcript: Dict[str, Any]) -> str:
    if not isinstance(transcript, dict):
        return ""
    raw_text = str(transcript.get("text") or "").strip()
    if raw_text:
        return raw_text
    parts = [
        str(segment.get("text") or "").strip()
        for segment in (transcript.get("segments") or [])
        if isinstance(segment, dict) and str(segment.get("text") or "").strip()
    ]
    return " ".join(parts).strip()


def _discover_repair_clips(output_dir: str, job_id: str) -> List[Dict[str, Any]]:
    manifest = load_job_manifest(output_dir)
    excluded_filenames: List[str] = []
    source_video = manifest.get("pipeline", {}).get("input_video")
    if source_video:
        excluded_filenames.append(os.path.basename(source_video))
    video_files = _discover_video_files(output_dir, excluded_filenames=excluded_filenames)
    return _build_legacy_grouped_clips(output_dir, job_id, video_files)


def repair_job_metadata(job_id: str, output_root: str, base_url: str, model_name: str, limit: Optional[int] = None) -> str:
    output_dir = os.path.join(output_root, job_id)
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"Job output dir not found: {output_dir}")

    clips = _discover_repair_clips(output_dir, job_id)
    if not clips:
        raise RuntimeError(f"No clips found for job {job_id}")

    if limit:
        clips = clips[: max(1, int(limit))]

    language_hint = _load_transcript_language(output_dir)
    repaired_clips: List[Dict[str, Any]] = []

    for position, clip in enumerate(clips, start=1):
        source_filename = (
            clip.get("original_video_filename")
            or clip.get("base_video_filename")
            or clip.get("video_filename")
        )
        if not source_filename:
            raise RuntimeError(f"Clip {position} has no source filename")
        source_path = os.path.join(output_dir, os.path.basename(source_filename))
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Clip source missing: {source_path}")

        print(f"[{position}/{len(clips)}] Transcribing {os.path.basename(source_path)}")
        transcript = transcribe_audio(source_path, preferred_language=language_hint or None)
        transcript_text = _flatten_transcript_text(transcript)
        if not transcript_text:
            raise RuntimeError(f"Empty transcript for {source_filename}")

        clip_label = clip.get("video_title_for_youtube_short") or f"Clip {clip.get('clip_index', position - 1) + 1}"
        print(f"[{position}/{len(clips)}] Generating copy for {clip_label}")
        copy_payload = _generate_clip_copy(
            transcript_text,
            clip_label=str(clip_label),
            language_hint=language_hint,
            base_url=base_url,
            model_name=model_name,
        )

        repaired_clip = dict(clip)
        repaired_clip["start"] = 0.0
        repaired_clip["end"] = round(_ffprobe_duration(source_path), 3)
        repaired_clip["video_title_for_youtube_short"] = copy_payload["title"]
        repaired_clip["video_description_for_tiktok"] = copy_payload["description_tiktok"]
        repaired_clip["video_description_for_instagram"] = copy_payload["description_instagram"]
        repaired_clip["viral_hook_text"] = copy_payload["hook"]
        repaired_clip["transcript_source"] = "audio"
        repaired_clips.append(repaired_clip)

    metadata_path = find_metadata_path(output_dir) or os.path.join(output_dir, f"{job_id}_repaired_metadata.json")
    if os.path.exists(metadata_path):
        backup_path = f"{metadata_path}.bak_{int(time.time())}"
        shutil.copyfile(metadata_path, backup_path)
        print(f"Backed up previous metadata to {backup_path}")

    payload = {
        "shorts": repaired_clips,
        "generation_mode": "recovered_from_rendered_clips",
        "repair_note": "Recovered from rendered clip files because original metadata was missing or unreadable.",
        "language": language_hint,
    }
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    print(f"Repaired metadata written to {metadata_path}")
    return metadata_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair missing job metadata from existing rendered clip files.")
    parser.add_argument("job_id")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--ollama-base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "qwen3.5:9b"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    repair_job_metadata(
        args.job_id,
        output_root=args.output_root,
        base_url=args.ollama_base_url,
        model_name=args.ollama_model,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
