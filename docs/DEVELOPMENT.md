# Stream Clips: Developer Guide

This document details the project structure, code organization, pipeline mechanics, extension points, and test execution for contributors and developers working on Stream Clips.

---

## 1. Complete Directory Structure

```text
stream-clips/
├── .env.example                       # Environment configuration template
├── .gitignore                         # Git exclusion rules for media, venvs, and secrets
├── AGENTS.md                          # Guidance for autonomous AI agents (Claude, Codex)
├── GEMINI.md                          # Guidance for Gemini CLI agents
├── LICENSE                            # Software license
├── README.md                          # Main project overview and user documentation
├── SKILL.md                           # AI skill instructions and CLI specifications
├── watchlist.txt                      # Default template for tracked streamers/channels
├── docs/
│   ├── ARCHITECTURE.md                # System architecture, component models, and data flows
│   ├── CHALLENGES.md                  # Detailed engineering challenges and solutions
│   ├── DEVELOPMENT.md                 # This developer and contributor guide
│   ├── INSTAGRAM_SETUP.md             # End-to-end Meta app & SUAT configuration guide
│   └── SETUP.md                       # Installation, prerequisites, and troubleshooting
└── scripts/
    ├── dashboard.py                   # Entry point for the local Uploader Web Dashboard
    ├── setup_env.py                   # Bootstraps private venv, packages, and AI models
    ├── streamclips.py                 # Core CLI entry point (find, clip, doctor, setup)
    ├── sc/                            # Core video clipping pipeline package
    │   ├── __init__.py                # Package declaration
    │   ├── brains.py                  # AI moment-picker adapters (Claude, Codex, Gemini, OpenCode)
    │   ├── cli.py                     # Argument parsing and command routing
    │   ├── common.py                  # System subprocess helpers, logging tags, environment paths
    │   ├── discover.py                # YouTube public search and watchlist reader
    │   ├── frame.py                   # OpenCV YuNet face detection & layout calculation
    │   ├── highlights.py              # Volume RMS and chat velocity spike detection
    │   ├── hook.py                    # Opening punch-in, lead trimming, and title animation
    │   ├── listen.py                  # Faster-Whisper audio transcription & language detection
    │   ├── media.py                   # yt-dlp downloading and audio-video cross-correlation sync
    │   ├── pipeline.py                # High-level pipeline controller
    │   ├── produce.py                 # FFmpeg filtergraph rendering and loudness normalization
    │   ├── settings.py                # Dataclass configuration and settings.json persistence
    │   ├── sfx.py                     # Procedural audio synthesis for sound effects
    │   ├── subs.py                    # Word-level ASS subtitle formatting and timing
    │   └── titlecard.py               # Pillow-based title card generator
    └── uploader/                      # Dashboard server & multi-platform publishing package
        ├── __init__.py                # Package declaration
        ├── auth_manager.py            # Google OAuth 2.0 flow & token refresh manager
        ├── discovery.py               # Discovers clips.json and checks assets
        ├── instagram.py               # Meta Graph API client, SUAT manager & Ephemeral Media Gateway
        ├── server.py                  # Local ThreadingHTTPServer on 127.0.0.1:5050 with HTTP 206
        ├── storage.py                 # Thread-safe metadata writes with .json.bak backups
        ├── test_phase2.py             # Isolated unit/integration tests for YouTube OAuth & uploads
        ├── test_phase3.py             # Isolated unit/integration tests for Instagram & gateway
        ├── test_tunnel_smoke.py       # Live security-only smoke test for Cloudflare Tunnel
        ├── test_uploader.py           # Core discovery, HTTP server, and storage tests
        ├── youtube.py                 # Official YouTube Resumable Upload protocol implementation
        └── static/                    # Dashboard frontend assets
            ├── app.css                # Dark-mode dashboard styling
            ├── app.js                 # Frontend application logic, state, and API client
            └── index.html             # Semantic dashboard interface
```

---

## 2. Core Source Files & Responsibilities

### Core Pipeline (`scripts/sc/`)
- **`pipeline.py` (`process_stream`)**: Coordinates the sequential execution for a stream: download audio -> scan transcription -> detect energy/chat spikes -> prompt AI brain -> select top N clips -> slice video segments -> detect face position -> compose vertical layout with subtitles and SFX.
- **`highlights.py` (`scan_energy`, `merge_candidate_moments`)**: Analyzes 1-second audio chunks for volume anomalies (`<<VOLUME +N dB>>`) and correlates them with YouTube live chat replay messages per second (`<<CHAT Nx>>`).
- **`frame.py` (`detect_face`, `choose_layout`)**: Runs OpenCV YuNet on sample frames. If a face is found in a corner box, it selects `stack` layout (facecam above, gameplay below). If the face is centered or dominant, it chooses `crop` (portrait tracking). If no face is detected, it selects `blur` (landscape clip overlaid on blurred background).
- **`hook.py` (`build_hook_plan`)**: Identifies the exact timestamp of the first spoken word to trim pre-speech dead air, designs a 0.7s ease-out zoom (punch-in), and times the title slide animation.
- **`sfx.py` (`synthesize_sfx`, `plan_clip_sfx`)**: Uses sine/noise math in `numpy` to generate `.wav` files on demand without external media downloads. Ducking parameters lower SFX volume during dialogue.
- **`produce.py` (`render_clip`)**: Generates and executes the final multi-input FFmpeg command combining video slicing, layout scaling/cropping, ASS subtitle overlay (`subtitles=...`), audio mixing with ducked SFX, and `-14 LUFS` EBU R128 loudness normalization.

### Uploader & Publishing (`scripts/uploader/`)
- **`server.py` (`run_server`, `DashboardRequestHandler`)**: Implements localhost REST endpoints:
  - `GET /api/streams`: Lists all discovered streams and clips.
  - `GET /api/clips/<id>`: Returns metadata for a single clip.
  - `POST /api/clips/<id>`: Updates title, caption, hashtags (auto-creates `.json.bak`).
  - `GET /media/video/<id>`: Streams video with `HTTP 206 Partial Content` (Range headers).
  - `GET /media/image/<id>`: Serves JPEG preview frames.
  - `GET /api/youtube/status`, `POST /api/youtube/config`, `GET /api/youtube/auth-url`, `POST /api/publish/youtube`: Manages YouTube publishing.
  - `GET /api/instagram/status`, `POST /api/instagram/config`, `POST /api/publish/instagram`: Manages Instagram publishing.
- **`storage.py` (`save_clip_metadata`, `update_clip_upload_status`)**: Ensures data safety by creating a `.json.bak` copy prior to any modification, writing to a temporary `.json.tmp` file, calling `os.fsync()`, and atomically replacing `clips.json` with `os.replace()`.
- **`instagram.py` (`EphemeralMediaGateway`, `TunnelManager`, `InstagramPublisher`)**:
  - `EphemeralMediaGateway`: Spawns a dedicated HTTP server on port 0 that only responds to an unguessable 32-byte randomized path (`/video/<token>.mp4`).
  - `TunnelManager`: Spawns `cloudflared tunnel --url http://127.0.0.1:<port>` strictly on the ephemeral port (explicitly refuses port 5050).
  - `InstagramPublisher`: Orchestrates container creation (`POST /{ig-user-id}/media`), polling (`GET /{creation-id}`), container publication (`POST /{ig-user-id}/media_publish`), and permalink retrieval (`GET /{media-id}`).
- **`youtube.py` (`YouTubeUploader`)**:
  - `initiate_resumable_upload`: POSTs metadata to Google's resumable endpoint and retrieves the upload URL.
  - `upload_chunks`: Sends the file in 1 MB chunks using `PUT` with `Content-Range`. Handles HTTP 308 resumes.

---

## 3. Adding or Modifying AI Providers

AI moment-picking adapters live in `scripts/sc/brains.py`.

### How Brain Selection Works
The CLI option `--brain <name>` (or `--brain auto`) controls which picker is used:
- `claude`: Invokes `claude -p`
- `codex`: Invokes `codex exec`
- `gemini`: Invokes `gemini -p`
- `opencode`: Invokes `opencode run`
- `agent`: File-based interaction where prompt files (`part_XXXXXX.prompt.txt`) are written and the command halts with exit code 3 for an external agent or user to write answers to `part_XXXXXX.answer.json`.

### Adding a New Provider
To add a new AI CLI provider (e.g. `ollama` or `custom-cli`):
1. In `scripts/sc/brains.py`, add a new entry to the `BRAINS` dictionary:
   ```python
   def _run_custom(prompt: str, model: Optional[str] = None) -> str:
       cmd = ["custom-cli", "run"]
       if model:
           cmd.extend(["--model", model])
       # Run command passing prompt to stdin and return stdout
       return run_subcommand(cmd, input_text=prompt)
   ```
2. Register the provider name in `scripts/setup_env.py` under `check_tools()` so setup verifies its presence on `PATH`.
3. Update `scripts/sc/cli.py` to include the new provider choice in `--brain` arguments.

---

## 4. Running the Test Suite

Stream Clips includes comprehensive test suites designed to run in isolated environments without affecting live user credentials.

### Prerequisites for Running Tests
Run tests using the project's virtual environment Python:
- Windows: `& .streamclips\venv\Scripts\python.exe <test_script>`
- macOS / Linux: `~/.streamclips/venv/bin/python <test_script>`

### Running Individual Test Suites

#### 1. Core Uploader & Dashboard Tests (`test_uploader.py`)
Validates clip discovery, atomic storage with `.bak` backups, HTTP 206 video range requests, check-image serving, and pipeline file integrity.
```powershell
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_uploader.py
```

#### 2. YouTube OAuth & Resumable Upload Tests (`test_phase2.py`)
Tests Google OAuth token storage isolation, resumable upload chunking logic, duplicate upload blocking, and API endpoints using mock responses.
```powershell
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_phase2.py
```

#### 3. Instagram Reels & Ephemeral Gateway Tests (`test_phase3.py`)
Validates Meta SUAT token discovery and masking, container creation/polling/publishing workflows, Cloudflare tunnel port-isolation (guaranteeing port 5050 is never exposed), 404 rejection on unauthorized routes, and HTTP 206 Partial Content handling for crawlers.
```powershell
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_phase3.py
```

#### 4. Live Cloudflare Quick Tunnel Smoke Test (`test_tunnel_smoke.py`)
Performs an end-to-end security check over a live public Cloudflare Tunnel without calling any Meta APIs. Spawns an isolated dummy video server, starts `cloudflared`, verifies public GET/HEAD/Range requests, and verifies strict 404 rejection on traversal attempts.
```powershell
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_tunnel_smoke.py
```
*(Requires `cloudflared` to be installed on the machine).*

---

## 5. Security & Contribution Guidelines

1. **Never Commit Secrets**: Do not commit API tokens, OAuth credentials, or private configuration. All live auth files must remain in `~/.streamclips/auth/`.
2. **Never Commit Media**: Generated `.mp4` videos, `.wav` caches, and `.jpg` frames must be excluded via `.gitignore`.
3. **Preserve Atomic Operations**: Any function modifying metadata or state files on disk must follow the backup-first pattern (`.json.bak`) and use atomic replacement (`os.replace()`).
4. **Preserve Subsystem Boundaries**: The core clipping pipeline (`scripts/sc/`) must remain independent from the web uploader (`scripts/uploader/`). The CLI can be run fully offline without launching the web server.
