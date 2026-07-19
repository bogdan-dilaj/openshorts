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
- Longform Video Editor with resumable ingest, sync, transcription, rough-cut decisions, and FCPXML export

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

### 3. Start the stack (GPU default)
```bash
docker compose up --build -d
```
`docker-compose.gpu.yml` is no longer required for normal GPU usage.

Force CPU explicitly (for troubleshooting or lower power mode):
```bash
docker compose -f docker-compose.cpu.yml up --build -d
```

### 4. Open the dashboard
- Frontend: `http://localhost:5175`
- Backend API is proxied through the frontend (`/api`, `/videos`, `/thumbnails`) in local dev.

### Windows (Docker Desktop)

Windows uses a dedicated bridge-network Compose file instead of Linux host networking:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

Use `.\scripts\setup_windows.ps1 -Gpu` for optional NVIDIA GPU passthrough. Full Codex migration instructions are in [`docs/WINDOWS_CODEX_SETUP.md`](docs/WINDOWS_CODEX_SETUP.md).

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

## Longform Video Editor

Open the `Longform Video Editor` tab to create local podcast rough-cut projects for DaVinci Resolve.

Current MVP workflow:
- create a `Single Camera` or `Interview` project
- upload one or more files per camera
- reorder file segments per camera
- choose the primary audio camera
- adjust conservative / balanced / aggressive cut behavior
- optional: load 6 suggested speaker stills per role and generate thumbnail variants from Gemini / OpenAI / Midjourney bridge
- start the pipeline
- export:
  - Resolve-compatible `FCPXML`
  - `decisions.json`
  - `markers.csv`
  - sync/debug JSON

Pipeline steps:
- ingest and optional CFR normalization
- audio extraction
- interview sync using audio-envelope matching
- Whisper transcription with word timestamps
- conservative decision engine:
  - leading / trailing editorial trim detection for setup chatter, restart chatter and post-roll
  - pause trimming
  - filler-word trimming
  - backchannel suppression
  - stronger retake / false-start review markers
  - reaction opportunity markers
- FCPXML export for manual finishing in Resolve with the selected primary audio laid under all rough-cut shots

Notes:
- Longform projects are stored locally under `output/longform_projects/<project_id>`.
- Browser uploads for Longform are stored only temporarily under `output/.longform_uploads` and are released after ingest.
- `Normalisierung (CFR)` is now disabled by default.
  - with mounted/reference media and normalization disabled, the pipeline works directly on the original source files
  - the exported `FCPXML` then references the original media instead of generated MP4 working copies
  - enable normalization only for problematic sources such as variable-frame-rate phone, webcam, or screen recordings
- when normalization stays disabled, the pipeline stores only compact mono analysis audio in `output/longform_projects/<project_id>/audio`
  - this audio is used for sync and Whisper/transcription
  - the edit export still points to the original video files
- if you upload files through the browser and keep normalization disabled, the original uploaded media is moved into the project instead of being transcoded into a duplicate MP4
- Longform source files can also be referenced directly via `Per Pfad hinzufügen`.
  - works immediately with files placed under `output/longform_source_mount`
  - for a real external drive mount, recreate Docker with `LONGFORM_SOURCE_HOST_DIR=/media/...`
- If currently no external SSD / USB stick / SD card is mounted, there is still a fallback:
  - browser upload keeps working
  - or copy/source files into `output/longform_source_mount` and add them via `Per Pfad hinzufügen`
- The pipeline is resumable and can be paused/stopped from the UI.
- In interview mode, the rough-cut export now uses the selected `Hauptaudio` under every visual shot.
  - the camera angle can switch between host / guest
  - the exported timeline audio stays anchored to the chosen primary audio source
- The Longform editor can generate speaker stills after analysis:
  - `6 Stills pro Sprecher laden` samples good frames per role from the analyzed material
  - you can choose one still per speaker and send those references into Gemini / OpenAI / Midjourney bridge thumbnail generation
  - named thumbnail prompt presets are managed globally in `Einstellungen`
  - API keys and image model defaults are also managed globally in `Einstellungen`
  - Midjourney is integrated through a configurable bridge URL; OpenShorts sends prompt, selected model, count and reference images to that endpoint
- MiniMax keys are also managed globally in `Einstellungen`.
  - `Token Plan` expects the separate Token-Plan-Key from MiniMax
  - `Pay-as-you-go` expects the regular Open-Platform API key
  - those two key types are intentionally treated as different modes in the UI
- The system is intentionally conservative: uncertain cases are marked for review instead of being cut blindly.

### How Longform Storage Works

Recommended default:
- keep `Normalisierung (CFR)` disabled for normal camera files such as `.MOV` from mirrorless / cinema / action cameras
- let OpenShorts analyze compact extracted audio only
- let the exported `FCPXML` reference the original video files directly

What gets stored then:
- original referenced videos stay where they already are
- compact analysis audio under `output/longform_projects/<project_id>/audio`
- transcript / sync / marker / decision JSON
- exported `FCPXML`

What does **not** get stored in that mode:
- no large normalized MP4 duplicates

When to enable normalization:
- phone footage
- screen recordings
- webcam recordings
- variable-frame-rate material
- any source that shows drift, broken timestamps or unstable sync

### Importing Into DaVinci Resolve

After a successful Longform pipeline run:

1. Open the Longform project in OpenShorts
2. In `Exporte & Summary`, download or open the generated `FCPXML`
3. Keep the original source video files reachable at the same paths used during analysis
4. Open DaVinci Resolve
5. Create a new project with the same timeline FPS as `Export-FPS`
6. Import the `FCPXML`
7. If Resolve asks to relink media, point it to the original source files

Important:
- the XML file itself can be stored anywhere
- what matters is that Resolve can still access the referenced original media paths
- if your originals are still on a removable SD card, keep that card mounted while importing
- in practice an SSD or a stable mounted media path is safer than editing directly from a transient SD mount

Typical files you may use:
- `*.fcpxml`: main rough-cut import into Resolve
  - contains the visual rough cut
  - references the selected primary audio under the whole cut
- `*_markers.csv`: optional review/marker reference
- `*_decisions.json`: optional debugging / understanding why cuts were suggested
- `*_sync.json`: optional sync diagnostics

### Storage and Docker recreate safety

- `docker compose up -d --force-recreate backend frontend` does not delete existing jobs under `output/`.
- Browser-side settings stored in `localStorage` also survive a recreate.
- Backend settings sync files now default to `output/.settings_sync`, so they are no longer tied to the container's `/tmp`.
- Longform temporary uploads default to `output/.longform_uploads`, not the container layer.
- Avoid destructive Docker commands such as `docker compose down -v` if you want to keep data untouched.

### External drives for Longform

- Best practice: use one stable mount path and keep reusing it.
- The easiest setup is to mount the external SSD / USB stick / SD card on the host directly to `output/longform_source_mount`.
- Because the project directory is already bind-mounted into Docker, this path is then immediately visible inside the container as `/app/output/longform_source_mount` without another recreate.
- Without any recreate, place source files under `output/longform_source_mount` and add them via `Per Pfad hinzufügen`.
- If you want to process directly from an external SSD, USB stick or SD card, bind-mount that host path to one fixed in-container path such as `/mnt/longform-source`.
- In practice that means:
  - set `LONGFORM_SOURCE_HOST_DIR` to the host mountpoint of the external drive
  - keep `LONGFORM_SOURCE_MOUNT_ROOT=/mnt/longform-source`
  - recreate Docker once so the bind mount becomes active
- For future cards/disks, it is better to mount them on the host to the same path instead of changing the container path every time.
- Only when the host-side mount path changes do you need to adjust `LONGFORM_SOURCE_HOST_DIR` and recreate again.
- The exported XML can still be downloaded and stored wherever you want afterwards.

### USB / SD remount helper

If your desktop auto-mounts removable media somewhere under `/run/media/...`, `/media/...` or a similar temporary path, you do not need to keep changing Docker config for every card.

Recommended setup:
- Keep `LONGFORM_SOURCE_HOST_DIR` stable, ideally on the default `./output/longform_source_mount`
- Let Docker keep using that same host path
- When you insert a new card, remount that card onto the same stable host path

Helper script:
```bash
bash scripts/remount_longform_source.sh
```

What it does:
- lists suitable mounted/removable partitions
- asks which one you want to use via letter selection (`a`, `b`, `c`, ...)
- unmounts the current automount location
- remounts the selected partition onto your configured `LONGFORM_SOURCE_HOST_DIR`
- treats the target path as a real mount only if it is actually mounted there, so a normal project path inside `/home` is no longer mistaken for its parent filesystem

Details:
- By default, the script uses the current `.env` value of `LONGFORM_SOURCE_HOST_DIR`
- If that is unset, it falls back to `./output/longform_source_mount`
- It needs `sudo`, because remounting devices requires root privileges

Optional custom target:
```bash
bash scripts/remount_longform_source.sh /absolute/host/path
```

Typical workflow:
1. Insert SSD / USB stick / SD card
2. Run `bash scripts/remount_longform_source.sh`
3. Choose the listed device by letter
4. Run `docker compose restart backend`
5. Open `Longform Video Editor`
6. Add files via `Per Pfad hinzufügen`

Important:
- If you keep reusing the same `LONGFORM_SOURCE_HOST_DIR`, you usually do not need `docker compose up -d --force-recreate`
- If you change `LONGFORM_SOURCE_HOST_DIR` itself to a different host path, then Docker needs one recreate so the new bind mount becomes active
- The longform source bind mount now uses shared propagation.
  - after updating to this version, run one `docker compose up -d --force-recreate backend frontend`
  - afterwards, remounting a card onto the same stable host path is visible to the container much more reliably
- After remounting a new external drive onto the same host path, a simple `docker compose restart backend` is enough in the current setup so the backend container sees the new files.

## Input form options

The main form supports:
- YouTube URL or local file upload
- `Interview mode`
- `Maximum clip count`

Short suggestion behavior:
- Suggested shorts default to coherent value clips between 60 and 180 seconds
- The AI may return fewer clips than requested when the transcript has fewer strong standalone moments

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
- API keys (Gemini, OpenAI, Claude, Minimax, Midjourney bridge, Upload-Post, ElevenLabs)
- MiniMax auth mode (`Token Plan` vs `Pay-as-you-go`)
- Longform thumbnail image-model defaults per provider
- Overlay defaults
- Tight edit defaults
- Social posting defaults
- YouTube auth settings
- Optional backend YouTube session cookies (if checkbox enabled when creating the sync key)

Notes:
- The sync key is required to decrypt the stored profile.
- The sync profile expires automatically (default: 365 days).

### Portable settings file (without projects)

`Settings -> Device Sync` also provides `Export settings` and `Import settings` buttons for moving to another computer without a shared backend.

The file contains API keys, provider/model choices, Upload-Post profile contexts, social/relay settings, overlay/edit defaults, longform AI defaults, and optional pasted YouTube cookies. It never contains projects, jobs, videos, or render data.

Security: the JSON file contains secrets in plain text. Store and transfer it securely, never commit it, and delete it after a successful import.

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

Switch backend mode:
```bash
# GPU (default)
docker compose up -d --force-recreate backend

# CPU (explicit override)
docker compose -f docker-compose.cpu.yml up -d --force-recreate backend
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
- Upload Post

## Known practical constraints

- Some YouTube videos still require cookies or additional YouTube-side session data to access high-quality formats
- Local Ollama performance depends heavily on the chosen model and available VRAM/RAM
- Subtitle and hook rendering are CPU-heavy compared to plain transcoding, even with reduced thread limits

## License

MIT
