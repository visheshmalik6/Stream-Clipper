# Stream Clips: Setup & Installation Guide

This guide provides end-to-end instructions for installing and running Stream Clips on Windows (with notes for macOS/Linux).

---

## 1. System Prerequisites

Stream Clips requires:
1. **Python 3.9 or newer** (Python 3.12 recommended; tested on Python 3.12.10).
2. **FFmpeg & FFprobe**: Required for media extraction, audio analysis, subtitle burning, and video encoding.
3. **JavaScript Runtime (Deno or Node.js)**: Required by `yt-dlp` to solve streaming challenges on YouTube.
4. **Cloudflare Tunnel (`cloudflared`)** *(Optional, needed for Instagram Reels publishing)*: Creates an ephemeral secure gateway for Meta's crawlers to fetch videos.
5. **Disk Space**: ~1 GB free for Python virtual environment and offline Whisper/YuNet AI models, plus ~0.15 GB per hour of processed stream footage.

### Installing Prerequisites on Windows

Open PowerShell as Administrator (or standard user if using WinGet) and run:

```powershell
# 1. Install Python 3.12 (if not already installed)
winget install Python.Python.3.12

# 2. Install FFmpeg
winget install Gyan.FFmpeg

# 3. Install Deno (or Node.js)
winget install DenoLand.Deno

# 4. Install Cloudflare Tunnel (required for Instagram Reels publishing)
winget install Cloudflare.cloudflared
```

> [!IMPORTANT]
> After running `winget install`, close and reopen your PowerShell terminal window so the new paths are added to your environment `PATH`.

### Windows Python Executable Paths & Execution Aliases

On Windows, multiple Python paths can cause PATH precedence issues:
- **Project Virtual Environment Python**: `.streamclips\venv\Scripts\python.exe` (or `~\.streamclips\venv\Scripts\python.exe`). This is the interpreter where all Stream Clips dependencies, Whisper models, and OpenCV libraries are installed.
- **Real Installed Python**: `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` or `C:\Program Files\Python312\python.exe`.
- **Windows Store Execution Alias**: `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`. This 0-byte reparse point can fail with `"The file cannot be accessed by the system"` inside restricted environments or automated tasks.

> [!TIP]
> If `python` attempts to launch the Microsoft Store or fails with access denied, either:
> 1. Invoke the project virtual environment Python directly: `& .streamclips\venv\Scripts\python.exe <command>`
> 2. Or disable the alias in Windows Settings: *Settings > Apps > Advanced app settings > App execution aliases* (toggle off both `App Installer: python.exe` and `python3.exe`).

### Verifying Prerequisites

Run the following commands in PowerShell to verify your tools:

```powershell
# Verify Python
python --version
# Output should show: Python 3.12.x (or 3.9+)

# Verify FFmpeg
ffmpeg -version
ffprobe -version

# Verify JavaScript Runtime
deno --version
# or node --version

# Verify cloudflared (for Instagram)
cloudflared --version
```

---

## 2. Automated Project Setup

Stream Clips features an automated bootstrapping script (`scripts/setup_env.py`) that sets up everything in a self-contained environment:
- Checks system tools and available disk space.
- Creates an isolated Python virtual environment in `~/.streamclips/venv` (keeps your system Python clean).
- Installs necessary libraries: `faster-whisper`, `opencv-python-headless`, `pillow`, `numpy`, and `yt-dlp[default]`.
- Downloads offline Whisper models (`tiny` for stream scanning, `base` for captioning, ~220 MB total) into `~/.streamclips/models/whisper`.
- Downloads the OpenCV YuNet face detection ONNX model (`face_detection_yunet_2023mar.onnx`) into `~/.streamclips/models/`.
- Initializes the output directory at `~/StreamClips/` with `watchlist.txt`.

### Running Setup

From the project root:

```powershell
# Using the CLI launcher
python scripts/streamclips.py setup

# Or running setup directly
python scripts/setup_env.py
```

Wait until the script finishes and prints:
```
============================================================
READY
============================================================
```

### Checking Environment Health (`doctor`)

You can verify the setup status at any time:

```powershell
python scripts/streamclips.py doctor
```

---

## 3. Environment Configuration

Copy the provided `.env.example` file to create your local `.env`:

```powershell
Copy-Item .env.example .env
```

Available configuration options:
- `STREAMCLIPS_HOME`: Custom path for output clips and discovery (defaults to `~/StreamClips`).
- `STREAMCLIPS_ENV_HOME`: Custom path for private virtualenv and downloaded models (defaults to `~/.streamclips`).
- `STREAMCLIPS_PUBLIC_URL`: Optional custom public HTTPS tunnel URL for Instagram media delivery (e.g., `https://my-tunnel.example.com`). If not set, Stream Clips spawns a Cloudflare Quick Tunnel automatically using `cloudflared`.
- `STREAMCLIPS_DEBUG`: Set to `1` to enable verbose debug logging for local server and media gateway.
- `PYTHONIOENCODING`: Character encoding fallback (`utf-8`).
- `PYTHONUTF8`: Enables Python UTF-8 mode (`1`).

---

## 4. Launching the Local Dashboard

Stream Clips includes a local web-based dashboard for reviewing discovered clips, inspecting vertical framing, editing captions/hashtags, and publishing to YouTube and Instagram.

```powershell
# Launch on default port 5050
python scripts/dashboard.py

# Or specify a custom port
python scripts/dashboard.py 8080
```

Open your browser and navigate to:
```
http://127.0.0.1:5050
```

---

## 5. Authentication Setup

### 5.1 YouTube Data API v3 (OAuth 2.0)
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a Project and enable **YouTube Data API v3**.
3. Configure the **OAuth Consent Screen** (User Type: External, Publishing Status: Testing, add your Google account email under Test Users).
4. Go to **Credentials** -> **Create Credentials** -> **OAuth client ID**.
   - Application Type: **Web application**
   - Authorized redirect URIs: `http://127.0.0.1:5050/oauth/youtube/callback`
5. Copy your **Client ID** and **Client Secret** (or download `client_secrets.json`).
6. In the Stream Clips Dashboard (`http://127.0.0.1:5050`), click **YouTube Settings** (gear icon) and paste your credentials.
7. Click **Connect YouTube** to sign in and grant upload permissions. Tokens are saved securely to `~/.streamclips/auth/youtube_tokens.json`.

### 5.2 Instagram Reels (Meta Graph API)
For detailed step-by-step instructions with screenshots and Meta app configuration, see [docs/INSTAGRAM_SETUP.md](INSTAGRAM_SETUP.md).

Quick setup summary:
1. Ensure your Instagram account is an **Instagram Creator or Business** account connected to a Facebook Page.
2. In [Meta for Developers](https://developers.facebook.com/), create a Business app.
3. In **Business Portfolio Settings**, create a **System User** and assign the Instagram Account with full control.
4. Generate a **System User Access Token (SUAT)** with permissions:
   - `instagram_basic`
   - `instagram_content_publish`
5. In the Stream Clips Dashboard, click **Instagram Settings** (gear icon) and paste your System User Access Token.
6. The dashboard verifies your account and saves credentials securely to `~/.streamclips/auth/instagram_config.json`.

---

## 6. Basic Usage

### Finding Streams
Discover active streams or recent VODs across YouTube and your watchlist:

```powershell
# Search YouTube for top streams today
python scripts/streamclips.py find --topic "Valorant"

# Search with specific title keywords
python scripts/streamclips.py find --topic "GTA 6" --keywords "gta 6,gta vi,gta6"
```

### Clipping a Stream
Process a stream into ready-to-post vertical clips:

```powershell
# Clip a specific stream URL (defaults to 3 clips)
python scripts/streamclips.py clip https://www.youtube.com/watch?v=QQV-0OUGxGs --topic "GTA 6"

# Create 5 clips focusing on clutch moments
python scripts/streamclips.py clip https://www.youtube.com/watch?v=QQV-0OUGxGs --topic "Valorant" --clips 5 --focus "clutch 1v5s and funny reactions"

# Clip only a specific section of a long stream (HH:MM:SS-HH:MM:SS)
python scripts/streamclips.py clip <URL> --topic "chess" --section "1:00:00-2:30:00"

# Find streams and automatically clip them
python scripts/streamclips.py clip --find --topic "Fortnite" --count 3
```

---

## 7. Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `Program 'python.exe' failed to run: The file cannot be accessed by the system` | Windows Store app execution alias interfering with PATH | Run using the virtualenv Python directly: `& .streamclips\venv\Scripts\python.exe <command>` or disable the alias in Windows Settings: *Apps > Advanced app settings > App execution aliases* (turn off Python). |
| `YouTube needs a login` / `Bot detected` / `HTTP 403` | Age-restricted stream or Twitch subscriber VOD | Add browser cookies flag: `--cookies chrome` (or `--cookies edge`, `--cookies firefox`). |
| `cloudflared not found` when publishing Instagram Reel | Cloudflare Tunnel is not installed or not in PATH | Install via `winget install Cloudflare.cloudflared` and reopen PowerShell, or supply a static `STREAMCLIPS_PUBLIC_URL` in `.env`. |
| `Instagram publish error: OAuthException (code 190)` | Meta access token has expired or was revoked | Re-generate your System User Access Token in Meta Business Settings and reconnect in the dashboard. |
| `Meta video processing timed out or failed` | Meta crawler could not fetch the temporary media URL | Ensure your network allows outbound Cloudflare Tunnel traffic. Run `python scripts/uploader/test_tunnel_smoke.py` to verify tunnel accessibility. |
| Subtitles are in wrong language | Multi-language stream | Add `--language en` (e.g. for Hinglish) or `--language hi` (for Hindi). In `settings.json`, set `"scan_model": "base"` for better non-English accuracy. |
