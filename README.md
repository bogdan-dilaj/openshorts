# OpenShorts

OpenShorts is a local-first pipeline for turning long videos into vertical short-form clips, editing them, versioning them, and publishing them to social platforms from a web dashboard.

It supports:
- YouTube URLs and local uploads
- Gemini or local Ollama models for clip selection and AI edit flows
- Vertical reframing for single-speaker, group, and interview footage
- Subtitle, hook, dub, trim, and auto-edit post-processing
- Job history, resume, cancel, and partial recovery
- Direct posting via Upload-Post

## Features

### Clip generation
- Faster-Whisper transcription with word timestamps
- AI clip selection with `gemini` or `ollama`
- Configurable maximum clip count in the form
- Default short clip mode up to `60s`
- Optional long-clip mode that allows clips up to `75s`
- Automatic speech tightening for pauses and simple filler words
- Language-aware metadata generation for titles, hooks, and descriptions

### Vertical video processing
- Smart reframing for 9:16 output
- 1080x1920 export target for TikTok, Reels, and Shorts
- Interview mode for two-person footage
- Scene analysis and speaker-focused cropping

### Post-processing
- Auto Edit
- Subtitle burn-in with configurable font, size, background, and Y position
- Hook overlay with free X/Y positioning, width presets, alignment, and styling
- Voice dubbing via ElevenLabs
- Manual trim with preview, scrub bar, start/end controls, and new version creation
- Non-destructive clip version chain per short

### Workflow and reliability
- Job history tab
- Resume failed or partial jobs
- Stop queued or running jobs
- Disk-backed job state and metadata persistence
- Fallback handling for partial runs

### Publishing
- Upload-Post integration
- Multi-profile support
- Posting to TikTok, Instagram, YouTube, Facebook, X, Pinterest, and Threads
- Instagram Trial Reels support
- TikTok `post_mode` and `is_aigc`
- Language forwarding where supported by Upload-Post

## Requirements

- Docker and Docker Compose
- For Gemini mode: a Gemini API key
- For Ollama mode: a local Ollama instance and at least one pulled model
- Optional: Upload-Post API key for posting
- Optional: ElevenLabs API key for dubbing

## Quick start

### 1. Clone
```bash
git clone <your-repo-url>
cd openshorts
```

### 2. Optional local Ollama setup
```bash
ollama serve
ollama pull gemma3:12b
```

Other reasonable local models for this project are for example:
- `qwen2.5:7b`
- `llama3.1:8b`
- `gemma3:12b`

### 3. Start the stack
```bash
docker compose up --build -d
```

### 4. Open the dashboard
- Frontend: `http://localhost:5175`
- Backend API is proxied through the frontend (`/api`, `/videos`, `/thumbnails`) in local dev.

### 5. Optional: access from other devices in the same WLAN
OpenShorts uses same-origin API proxying in the frontend, so LAN clients only need frontend port `5175`.

1. Find your host IP:
```bash
hostname -I
```
2. Open from another device:
- Frontend: `http://<HOST_IP>:5175`

If access fails, check local firewall rules for port `5175`.

## First use

1. Open `Settings`.
2. Choose `Gemini` or `Ollama`.
3. If using Ollama, set:
   - Base URL: `http://127.0.0.1:11434`
   - Model: for example `gemma3:12b`
4. Optionally add:
   - Upload-Post API key
   - ElevenLabs API key
5. Start a job from a YouTube URL or a local file.

## Input form options

The main form supports:
- YouTube URL or local file upload
- `Interview mode`
- `Allow clips over 1 minute`
- `Maximum clip count`

Long-clip behavior:
- Normal clips can always be shorter than one minute
- If a generated clip goes above 60 seconds, it is limited to a maximum of 75 seconds

Global settings also control:
- automatic pause/filler-word removal preset for newly generated shorts

## AI providers

### Gemini
- Used for clip selection and AI editing
- Requires a Gemini API key in Settings

### Ollama
- Local LLM option
- Used for clip selection and AI editing
- Requires:
  - running Ollama daemon
  - valid local model name

Configured defaults:
- Base URL: `http://127.0.0.1:11434`

## YouTube downloads and cookies

YouTube can restrict high-quality formats for server-like traffic. OpenShorts supports multiple auth modes and now probes quality before download to avoid silent 360p outputs.

### Recommended setup (Dashboard)
1. Open `Settings` -> `YouTube Download Quality`.
2. Keep `Auth Mode` on `auto`.
3. Prefer `Browser-Login importieren` (automatic host-browser import).
4. If browser import is unavailable, paste Netscape `cookies.txt` content and click `Cookies speichern (Backend)`.
5. Click `Status pruefen` and ensure `Login erkannt` is shown.
6. Start your job from the dashboard.

### How to get `cookies.txt`
1. Log into YouTube in your browser account.
2. Export cookies in **Netscape cookies.txt** format (for example with a cookies.txt exporter extension).
3. Use a fresh export if downloads start failing again.

### Auth modes
- `auto`: tries inline cookies -> `cookies.txt` file -> browser profile.
- `cookies_file`: only file-based cookies (`YOUTUBE_COOKIES_FILE`).
- `cookies_text`: only the pasted cookie content.
- `browser`: use `yt-dlp --cookies-from-browser` style profile access.

### Environment-based setup (optional)
```env
YOUTUBE_AUTH_MODE=auto
YOUTUBE_COOKIES_FILE=/app/cookies.txt
# YOUTUBE_COOKIES_FROM_BROWSER=chrome
# YOUTUBE_COOKIES=
```

### Notes and troubleshooting
- Use Netscape format only. JSON cookie dumps are not valid.
- If `/app/cookies.txt` is not writable in your setup, the backend falls back to `/tmp/openshorts/cookies.txt`.
- OpenShorts now aborts cleanly if no source meeting `MIN_SOURCE_EDGE` is available (instead of continuing with blurry output).
- Browser profile import reads cookies from the machine where Docker runs. Mobile Safari/Chrome cookies on another device cannot be auto-read directly.
- Browser profile mode can fail if the browser is running; close it before import.

## Device settings sync

OpenShorts can sync dashboard settings across devices via an encrypted sync profile stored in the backend.

Workflow:
1. On device A open `Settings` -> `Device Sync`.
2. Click `Sync-Key erstellen`.
3. Copy the generated sync key.
4. On device B open the same section, paste the key, click `Vom Sync-Key laden`.

What is synced:
- AI provider settings (Gemini/Ollama)
- API keys (Gemini, Upload-Post, ElevenLabs)
- Overlay defaults
- Tight edit defaults
- Social posting defaults
- YouTube auth settings
- Optional backend YouTube session cookies (if checkbox enabled when creating the sync key)

Notes:
- The sync key is required to decrypt the stored profile.
- The sync profile expires automatically (default: 365 days).

## Job history, stop, and resume

OpenShorts stores job metadata on disk and exposes a `History` tab in the dashboard.

You can:
- reopen completed jobs
- resume partial or failed jobs
- stop queued or running jobs

The backend keeps:
- job manifest
- job log
- persisted result metadata

## Clip versioning

Each generated short now has an explicit version chain.

Examples:
- `V0 Original`
- `V1 Hook`
- `V2 Subtitles`
- `V3 Trim`

Rules:
- Every editing step creates a new version
- The selected active version is used for the next step
- `Original wiederherstellen` switches back to the original version

Current version-producing actions:
- Auto Edit
- Subtitles
- Hook
- Dub Voice
- Trim

## Trim workflow

Each short can be manually trimmed from the dashboard.

Trim UI includes:
- preview video
- scrub bar
- play/pause and seek controls
- current time display
- start slider and numeric input
- end slider and numeric input
- stackable middle cut ranges
- `Use Current` for start and end

Trimming creates a new clip version instead of overwriting the current one.

## Subtitle options

Subtitle styling can be configured globally and per render.

Supported options:
- font family
- font size
- background style
- free Y-axis positioning

Background styles:
- `dark-box`
- `light-box`
- `yellow-box`
- `transparent`

## Hook options

Hook overlays support:
- free X/Y positioning
- width presets
- text alignment
- font family
- background style
- size presets
- manual line breaks

Background styles:
- `dark-box`
- `light-box`
- `yellow-box`
- `transparent`

## Social posting

Upload-Post integration can be configured in `Settings`.

Supported platforms:
- TikTok
- Instagram
- YouTube
- Facebook
- X
- Pinterest
- Threads

### Global social defaults

Settings allow defaults for:
- active Upload-Post profile
- enabled platforms
- Instagram share mode
- TikTok post mode
- TikTok `is_aigc`
- Facebook page ID
- Pinterest board ID

### Per-short posting options

Each generated short can override:
- title
- description
- selected platforms
- schedule date
- Instagram share mode
- TikTok post mode
- TikTok `is_aigc`
- Facebook page ID
- Pinterest board ID

### Instagram share modes
- `CUSTOM`
- `TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED`
- `TRIAL_REELS_DONT_SHARE_TO_FOLLOWERS`

### TikTok options
- `DIRECT_POST`
- `MEDIA_UPLOAD`
- `is_aigc`

## Upload-Post setup

1. Create an Upload-Post account.
2. Create at least one user profile.
3. Connect your social accounts to that profile.
4. Generate an API key.
5. Paste the key into `Settings`.
6. Load profiles and select the active one.

## ElevenLabs dubbing

Dub Voice uses ElevenLabs.

Requirements:
- valid ElevenLabs API key

Behavior:
- creates a new version
- dubbed clips can be further processed like other versions

## Runtime limits

The backend currently uses conservative defaults to avoid freezing the machine during heavy processing.

Notable runtime controls:
- `MAX_CONCURRENT_JOBS`
- `FFMPEG_THREADS`
- `FFMPEG_FILTER_THREADS`
- `FFMPEG_PRESET`
- `OVERLAY_FFMPEG_PRESET`
- `WHISPER_CPU_THREADS`

Current defaults are tuned for desktop responsiveness rather than maximum throughput.

## Security and execution model

- Containers run non-root
- Writable caches are redirected away from `/app`
- Job data is stored under `output/<job_id>/`
- Large temporary processing artifacts are created under `/tmp`

## Output structure

Typical output layout:
```text
output/<job_id>/
  *_metadata.json
  job_manifest.json
  job.log
  <clip>.mp4
  hook_<timestamp>_<clip>.mp4
  subtitled_<timestamp>_<clip>.mp4
  trimmed_<timestamp>_<clip>.mp4
  translated_<timestamp>_<lang>_<clip>.mp4
```

## Development notes

Useful commands:
```bash
docker compose ps
docker compose logs -f backend
docker compose restart backend
```

Stop the stack:
```bash
docker compose down
```

## Current dashboard areas

- Dashboard
- History
- Settings
- YouTube Studio

## Known practical constraints

- Some YouTube videos still require cookies or additional YouTube-side session data to access high-quality formats
- Local Ollama performance depends heavily on the chosen model and available VRAM/RAM
- Subtitle and hook rendering are CPU-heavy compared to plain transcoding, even with reduced thread limits

## License

MIT
