# Stream Clips 🎬

> **Turn hours of livestreams into viral vertical clips (YouTube Shorts, Instagram Reels, TikTok) with local AI and zero cloud costs.**

Stream Clips is an end-to-end automated clipping and multi-platform publishing engine. It monitors and searches livestreams (YouTube, Twitch, Kick), transcribes speech locally using OpenAI Whisper, identifies viral emotional and chat moments, frames footage into 9:16 vertical video using OpenCV facial tracking, renders animated captions and sound effects, and publishes directly to YouTube Shorts and Instagram Reels via a local web dashboard.

---

## The Problem It Solves

- **Manual Video Editing is Slow**: Scanning through a 4-hour livestream to find 30 seconds of high-energy gameplay or funny banter typically takes hours of manual scrubbing.
- **Expensive Cloud SaaS Services**: Most AI clipping services charge steep monthly subscriptions, place usage credit caps, or require cloud API tokens.
- **Privacy & Bandwidth Overhead**: Uploading multi-gigabyte recordings to remote cloud processing services consumes massive network bandwidth.
- **Fragmented Publishing**: Content creators must manually export, transfer to mobile devices, write tags, and upload across different social media platforms.

**Stream Clips solves this locally**: Speech recognition and computer vision run entirely on your local computer. AI moment selection uses your existing local AI CLI (Claude Code, Codex, Gemini CLI, OpenCode) or human agent mode with zero API fees. Downloads are bandwidth-efficient (only audio is ingested for scanning; video is sliced on-demand for picked clips).

---

## Key Features

- 🎯 **Topic & Watchlist Discovery**: Search livestreams on any topic or monitor creators across YouTube, Twitch, and Kick without API keys.
- 🎙️ **Offline Speech Recognition**: Local transcription powered by `faster-whisper` (`tiny` for full-stream indexing, `base` for high-accuracy subtitles).
- 📈 **Multimodal Energy Detection**: Correlates audio volume spikes (shouts, laughter, explosions) with real-time live chat velocity spikes.
- 🤖 **Flexible AI Moment Picking**: Leverages local AI tooling (`--brain claude`, `--brain codex`, `--brain gemini`, `--brain opencode`, or `--brain agent`) to score clips from 1 to 100 with titles, viral hooks, and hashtags.
- 📐 **Dynamic 9:16 Framing**:
  - **Stack**: Facecam in top panel, gameplay in bottom panel (auto-detected via OpenCV YuNet).
  - **Crop**: Centers and tracks speaker faces for podcasts and IRL streams.
  - **Blur**: Clean landscape video centered over a blurred vertical backdrop.
- ⚡ **Hook Optimization & Procedural SFX**: Trims pre-speech dead air, applies a 0.7s punch-in opening zoom, animates sliding title cards, and layers procedurally synthesized sound effects (`whoosh`, `impact`, `hit`).
- 📊 **Local Web Dashboard (`127.0.0.1:5050`)**: Review clips, inspect vertical video playback with timeline seeking, edit captions/hashtags with automated backups, and track upload status.
- 🚀 **Direct Multi-Platform Publishing**:
  - **YouTube Shorts**: Resumable chunked video upload via Google OAuth 2.0 and YouTube Data API v3.
  - **Instagram Reels**: Asynchronous container creation, polling, and publishing via Meta Graph API v22.0.
  - **Ephemeral Cloudflare Media Gateway**: Serves video securely to Meta's crawler via an ephemeral, randomized token route over a temporary Cloudflare Quick Tunnel (`cloudflared`) with zero dashboard exposure.

---

## Technology Stack

| Domain | Technologies & Libraries |
|---|---|
| **Core Runtime** | Python 3.12 (compatible with 3.9+), Windows PowerShell / POSIX Shell |
| **Media & Audio** | FFmpeg, FFprobe, `yt-dlp`, `numpy`, `wave` |
| **Speech-to-Text** | `faster-whisper` (CTranslate2 backend) |
| **Computer Vision** | `opencv-python-headless` (YuNet ONNX facial detection), `Pillow` |
| **Web Dashboard** | Python `ThreadingHTTPServer` (strict `127.0.0.1` binding), HTML5, CSS3, Vanilla ES6+ |
| **Distribution & Gateways** | Google OAuth 2.0, Meta Graph API v22.0, Cloudflare Quick Tunnels (`cloudflared`) |

---

## Architecture Overview

```text
 Livestream URL / Topic
           │
           ▼
 1. Audio Download (yt-dlp) ──> 2. Faster-Whisper Scan + RMS Volume / Chat Analysis
                                                        │
                                                        ▼
 4. Video Segment Slicing <── 3. AI Moment Picking (Claude / Codex / Gemini / Agent)
           │
           ▼
 5. Face Detection (YuNet) ──> 6. FFmpeg Compositor (9:16 + Subtitles + SFX + -14 LUFS)
                                                        │
                                                        ▼
                                       Local Output (~/StreamClips/)
                                                        │
                         ┌──────────────────────────────┴──────────────────────────────┐
                         ▼                                                             ▼
             YouTube Data API v3                                              Meta Graph API v22.0
       (Google OAuth 2.0 Resumable)                                       (System User Access Token)
                         │                                                             │
                         ▼                                                             ▼
                   YouTube Shorts                                           Ephemeral Media Gateway
                                                                         (cloudflared + HTTP 206 Range)
                                                                                       │
                                                                                       ▼
                                                                                Instagram Reels
```

For complete technical specifications, sequence diagrams, and module responsibilities, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Dashboard Preview

```text
+--------------------------------------------------------------------------------------------------+
|  Stream Clips Uploader                 [YouTube: Connected]  [Instagram: Connected]  [Refresh]   |
+--------------------------------------------------------------------------------------------------+
|  Discovered Streams        |  Clip Preview & Publishing Editor                                   |
|                            |                                                                     |
|  Valorant (2026-11-22)     |    +----------------------+   Title: Epic Clutch Moment!            |
|  - 01_epic-clutch...  [92] |    |      [Facecam]       |   Caption: Check out this 1v5 clutch!   |
|  - 02_funny-reaction..[88] |    |                      |   Tags: #gaming #clutch #shorts #viral  |
|                            |    |----------------------|                                         |
|  GTA Highlights            |    |      [Gameplay]      |   Status: Ready to Publish              |
|  - 01_fast-escape...  [89] |    |                      |                                         |
|                            |    +----------------------+   [ Upload to YouTube Shorts ]          |
|                            |    Score: 92 | 45s | Stack    [ Upload to Instagram Reels ]         |
+--------------------------------------------------------------------------------------------------+
```
*(Live interface available locally at `http://127.0.0.1:5050` when running `scripts/dashboard.py`)*.

---

## Quick Start

### 1. Prerequisites (Windows)
Install Python 3.12, FFmpeg, Deno, and Cloudflare Tunnel via WinGet:
```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install DenoLand.Deno
winget install Cloudflare.cloudflared
```
*(Restart your terminal window after installation).*

### 2. Automated Setup
Run the self-bootstrapping installer to create the isolated virtual environment and fetch AI models:
```powershell
python scripts/streamclips.py setup
```

### 3. Verify Installation
```powershell
python scripts/streamclips.py doctor
# Or invoke directly with the virtualenv Python:
# & .streamclips\venv\Scripts\python.exe scripts/streamclips.py doctor
```

---

## Basic Usage

### Finding Streams
```powershell
# Search for top streams on a topic
python scripts/streamclips.py find --topic "GTA 6" --keywords "gta 6,gta vi,gta6"
```

### Clipping Streams
```powershell
# Clip a specific livestream or VOD URL
python scripts/streamclips.py clip https://www.youtube.com/watch?v=QQV-0OUGxGs --topic "GTA 6"

# Create 4 clips focused on funny moments
python scripts/streamclips.py clip <URL> --topic "Valorant" --clips 4 --focus "funny reactions and fails"
```

### Launching the Dashboard
```powershell
python scripts/dashboard.py
```
Open `http://127.0.0.1:5050` in your web browser.

---

## Publishing Integration Overview

### YouTube Shorts
- Uses Google OAuth 2.0 Web Application flow.
- Stores credentials securely in `~/.streamclips/auth/youtube_tokens.json`.
- Uses Google's official Resumable Video Upload Protocol in 1 MB chunks.
- Automatically handles token refresh and appends `#Shorts` for vertical discovery.

### Instagram Reels
- Uses Meta Graph API v22.0 Content Publishing with System User Access Tokens (SUAT).
- Stores configuration in `~/.streamclips/auth/instagram_config.json`.
- Uses an **Ephemeral Media Gateway**: Launches a temporary, single-route HTTP server on port 0, opens a Cloudflare Quick Tunnel, serves video bytes to Meta's crawler with HTTP 206 Partial Content, polls container completion, and terminates the tunnel immediately.
- For complete setup instructions, see [docs/INSTAGRAM_SETUP.md](docs/INSTAGRAM_SETUP.md).

---

## Running the Automated Test Suite

Stream Clips includes comprehensive test suites running against isolated directories:

```powershell
# Core discovery, atomic storage, and HTTP server tests
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_uploader.py

# YouTube Data API v3 and OAuth 2.0 unit/mock tests
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_phase2.py

# Instagram Reels, SUAT validation, and Ephemeral Gateway tests
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_phase3.py

# Security-only smoke test over live Cloudflare Tunnel
& .streamclips\venv\Scripts\python.exe scripts\uploader\test_tunnel_smoke.py
```

---

## Security Considerations

1. **Zero Repository Secrets**: Tokens, client secrets, and authentication files are stored in `~/.streamclips/auth/` in your user home directory, strictly outside the repository tree.
2. **Dashboard Isolation**: The dashboard server binds strictly to `127.0.0.1` and is never exposed to the public internet.
3. **Tunnel Port Protection**: `TunnelManager` raises a `ValueError` refusing to tunnel port 5050. Only the ephemeral, random-route media gateway can be reached via public tunnels.
4. **Local Dashboard CSRF & DNS Rebinding Protection**: Dashboard endpoints strictly validate `Host` (on both GET and POST requests), `Origin`, and `Sec-Fetch-Site` metadata against allowed local hostnames and the server's listening port. Cross-origin POST requests, port mismatches, and untrusted hostnames are rejected with HTTP 403 Forbidden.
5. **OAuth State Verification & Anti-Replay**: The YouTube OAuth callback enforces one-time consumable state tokens, preventing state replay and authorization injection.
6. **Token Masking**: All UI displays and log outputs mask sensitive keys (e.g. `EAAGte...uvwxyz`).
7. **Atomic Data Safety**: Clip metadata writes always create `.json.bak` backup files prior to modification.

---

## Current Limitations & Future Improvements

### Current Limitations
- **Instagram Publishing Frequency**: Meta limits publishing to 25 API posts per 24 hours per Instagram account.
- **Hardware Acceleration**: Encoding defaults to CPU `libx264` unless `--fast` is specified with compatible GPU hardware drivers.
- **Simultaneous Multi-Platform Post**: Simultaneous publishing to both YouTube and Instagram in a single click is scheduled for Phase 4.

### Future Improvements
- Direct publishing support for TikTok Content Posting API.
- Live progress webhooks and desktop notifications.
- Automatic multilingual translation for international vertical subtitles.
- Direct Twitch / Kick stream recording integration.

---

## Documentation Index

- [Architecture & System Design](docs/ARCHITECTURE.md)
- [Installation & Prerequisites Guide](docs/SETUP.md)
- [Developer & Contributor Guide](docs/DEVELOPMENT.md)
- [Engineering Challenges & Solutions](docs/CHALLENGES.md)
- [Instagram Reels Meta API Setup Guide](docs/INSTAGRAM_SETUP.md)
- [Software License](LICENSE)
