# Stream Clips: Engineering Challenges & Technical Solutions

This document chronicles the real-world engineering challenges encountered during the development of Stream Clips—particularly around Windows runtime environments, Meta Graph API v22.0 integration, and secure zero-cost video delivery—along with the verified solutions implemented in the codebase.

---

## Challenge 1: Windows Python/Runtime & PATH Inconsistencies

### The Problem
Executing `python` commands from PowerShell or shell automation scripts on Windows frequently produced unexpected errors such as:
```text
Program 'python.exe' failed to run: The file cannot be accessed by the system
```
or executed an incorrect Python version (e.g., Python 3.11 instead of Python 3.12), leading to `ModuleNotFoundError` for packages installed in the application virtual environment.

### Why It Occurred
1. **Microsoft Store Execution Aliases**: Modern Windows installations place a 0-byte reparse point alias at `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`. When invoked inside restricted environments or sandboxes, this alias fails with access denied errors instead of executing Python.
2. **Multiple Python Installations & PATH Precedence**: Developers frequently have multiple Python interpreters (e.g. system Python, Python via Visual Studio, PyLauncher `py`, or uv). When launching subcommands, child processes inherited a system `PATH` where the global interpreter took precedence over the project virtual environment.

### How It Was Diagnosed
- Inspecting `where.exe python` revealed `C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\python.exe` at the top of the search path.
- Tracing child process invocations confirmed that child tasks were executing with `sys.prefix` pointing to system Python rather than `~/.streamclips/venv`.

### The Solution Implemented
1. **Automated Venv Bootstrapping**: Both `scripts/streamclips.py` and `scripts/dashboard.py` implement an automated bootstrap check:
   ```python
   VENV = Path(os.environ.get("STREAMCLIPS_ENV_HOME", Path.home() / ".streamclips")) / "venv"
   VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")

   def in_venv():
       try:
           return Path(sys.prefix).resolve() == VENV.resolve()
       except OSError:
           return False

   def main():
       if not in_venv() and VENV_PY.exists():
           env = dict(os.environ)
           bin_dir = str(VENV_PY.parent)
           env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
           env["PYTHONIOENCODING"] = "utf-8"
           env["PYTHONUTF8"] = "1"
           sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))
   ```
2. If invoked from an external or system Python, the script self-re-executes using `VENV_PY` with the virtual environment's `Scripts/` prepended to `PATH`.
3. In `setup_env.py`, `uv` or `sys.executable -m venv` is used to reliably construct the private virtual environment in `~/.streamclips/venv`.

### Verification
- Launching `scripts/dashboard.py` and `scripts/streamclips.py` directly from PowerShell correctly detects the virtual environment and seamlessly re-executes using Python 3.12.
- Verified in `test_phase2.py` and `test_phase3.py` running on Windows 11.

---

## Challenge 2: Meta Instagram Publishing Permission Missing from Initial Access Token

### The Problem
During initial Instagram Reels publishing attempts, Meta Graph API rejected the container creation request (`POST /{ig-user-id}/media`) with HTTP 400/403 `OAuthException`:
```text
(#10) Application does not have permission for this action
```

### Why It Occurred
Tokens generated through typical Facebook Login or standard Graph API Explorer presets commonly include read-only scopes (e.g. `instagram_basic`, `public_profile`, `pages_show_list`), but lack the write permission required for Instagram Reels:
`instagram_content_publish`.

### How It Was Diagnosed
- Decoded the token via Meta's Access Token Debugger endpoint (`https://graph.facebook.com/debug_token`).
- Confirmed that while `instagram_basic` was present, `instagram_content_publish` was absent from the granted scopes list.

### The Solution Implemented
1. Added pre-flight token validation in `InstagramManager.validate_token()` that queries `https://graph.facebook.com/v22.0/me/assigned_instagram_accounts` and tests account associations before allowing publishing.
2. Built token error classification (`InstagramAuthError`, `InstagramPublishError`) and token-sanitizing regexes in `sanitize_error_message()` to ensure clear troubleshooting feedback without leaking secrets:
   ```python
   def sanitize_error_message(raw_msg: str, secret_token: Optional[str] = None) -> str:
       clean = str(raw_msg)
       if secret_token and secret_token in clean:
           clean = clean.replace(secret_token, "[REDACTED_TOKEN]")
       clean = re.sub(r"EAA[A-Za-z0-9]+", "[REDACTED_TOKEN]", clean)
       clean = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", clean)
       return clean
   ```
3. Documented the exact required permission set in `docs/INSTAGRAM_SETUP.md`.

### Verification
- Verified in `scripts/uploader/test_phase3.py` (Test 2: `test_meta_token_validation_and_discovery`), confirming proper exception handling and actionable error messages when scopes are missing.

---

## Challenge 3: Generating a Replacement Token with `instagram_content_publish`

### The Problem
Standard user access tokens expire after 1 to 2 hours, and short-lived tokens require frequent interactive browser-based OAuth re-authentication. For a command-line and local desktop workflow, requiring the user to re-authorize through a browser every hour created significant friction.

### Why It Occurred
Meta's security policies require User Tokens to have short lifespans unless exchanged for 60-day long-lived tokens via an App Secret exchange. However, storing an App Secret locally on client machines violates zero-trust principles.

### How It Was Diagnosed
- Tokens used during testing expired mid-session, producing HTTP 400 with `error_subcode: 190` (AccessTokenExpired).
- Relying on interactive browser logins required managing web redirects and client secret storage on the local desktop.

### The Solution Implemented
1. Adopted Meta **System User Access Tokens (SUAT)** generated within Meta Business Portfolio / Meta Business Manager.
2. A System User token can be generated with a permanent or long-term validity period, scoped specifically to the designated Instagram Professional Account with `instagram_basic` and `instagram_content_publish` permissions.
3. Updated `InstagramManager.validate_token()` to support Unified Login SUAT resolution via:
   - Priority 1: `/me/assigned_instagram_accounts` (direct Business Portfolio asset assignment).
   - Priority 2: `/me/accounts` with `instagram_business_account` (Page-linked Instagram accounts).
   - Priority 3: `/me` (direct user node).

### Verification
- Tested and verified in `test_phase3.py` Test 1 and Test 2.
- Production validation: Successfully connected real Instagram Professional account and published Reels using SUAT.

---

## Challenge 4: Cloudflare Tunnel Integration for Temporary Public Video Delivery

### The Problem
Unlike YouTube, which supports direct binary byte streaming (`PUT /upload/youtube/v3/videos`) from client machines to YouTube servers, Meta's Instagram Graph API requires a publicly reachable HTTPS video URL (`video_url`) so Meta's crawlers can ingest the file. Local developer machines (`http://127.0.0.1`) cannot be reached by Meta's cloud servers.

### Why It Occurred
Uploading each clip to a third-party public object store (such as Amazon S3, Google Cloud Storage, or Cloudflare R2) would require cloud accounts, credit card setup, API keys, and ongoing hosting costs, violating Stream Clips' design goal: **100% free and local, no cloud subscriptions or credits required**.

### How It Was Diagnosed
- Attempting to pass `http://127.0.0.1:5050/media/video/...` to Meta Graph API resulted in HTTP 400: "Invalid media URL: URL must be publicly accessible via HTTPS".

### The Solution Implemented
1. Implemented `TunnelManager` in `scripts/uploader/instagram.py`, which integrates with Cloudflare's free Quick Tunnels (`cloudflared`).
2. Stream Clips spawns `cloudflared tunnel --url http://127.0.0.1:<media_port>` on demand as a subprocess.
3. It parses `cloudflared`'s stderr stream in real time to extract the ephemeral public HTTPS URL (e.g. `https://<random-id>.trycloudflare.com`).
4. Once Instagram publishing completes (or if an error occurs), the tunnel process is immediately terminated via `process.terminate()` and cleaned up.

### Verification
- Verified in `test_phase3.py` Test 6 and live smoke test in `test_tunnel_smoke.py`. The tunnel connects, yields an HTTPS URL, and cleanly shuts down within milliseconds of completion.

---

## Challenge 5: Preventing Public Exposure of the Dashboard and Unrelated Local Files

### The Problem
If the Cloudflare Quick Tunnel pointed to port 5050 (the dashboard server), the entire local dashboard—including clip review, metadata modification APIs, and OAuth credential management—would be exposed to the public internet without authentication.

### Why It Occurred
`cloudflared` forwards all HTTP requests received on the public tunnel directly to the target local port. Any route exposed on that port becomes accessible over the public internet.

### How It Was Diagnosed
- Threat modeling demonstrated that exposing port 5050 via a tunnel would allow anyone who guessed or intercepted the `trycloudflare.com` URL to access `/api/*` and read local files.

### The Solution Implemented
1. **Isolated Port Architecture**: The tunnel **never** points to port 5050.
2. **Hardcoded Port Guard (ValueError)**: `TunnelManager.start_tunnel` enforces a strict check:
   ```python
   if local_port == 5050:
       raise ValueError(
           "Security Violation: Cloudflare Tunnel must never point to port 5050 (dashboard). "
           "It must point strictly to an isolated ephemeral media-only server."
       )
   ```
3. **Dedicated Ephemeral Media Server**: A separate, lightweight HTTP server (`EphemeralMediaGateway`) is spawned on OS-assigned port 0 (an ephemeral port). Only this dedicated server is exposed to the tunnel, and only for the duration of the upload.

### Verification
- Verified in `test_phase3.py` Test 6: Attempting to call `start_tunnel(5050)` raises `ValueError`.
- Live smoke test (`test_tunnel_smoke.py`) probes 17 sensitive dashboard routes over the tunnel; all return `404 Not Found`.

---

## Challenge 6: Secure Temporary Media Access Using a Random Bearer Token & Restricted Routes

### The Problem
Even with an isolated media server, if the served URL used a predictable path (e.g. `https://<tunnel>.trycloudflare.com/video.mp4` or `/clip_01.mp4`), automated crawlers or scanners scanning the domain could discover and download the video during the ingestion window.

### Why It Occurred
Public tunnels can be scanned during the 30-90 seconds required for Meta's crawler to ingest the video.

### How It Was Diagnosed
- Review of web server logs showed potential vulnerability to path guessing or directory enumeration if default handlers (e.g. `SimpleHTTPRequestHandler`) were used.

### The Solution Implemented
1. **Cryptographic Random Token**: Every video hosting session generates a 32-byte URL-safe random token using Python's `secrets` module:
   ```python
   self._secret_token = secrets.token_urlsafe(32)
   expected_path = f"/video/{self._secret_token}.mp4"
   ```
2. **Strict Handler Routing**: `EphemeralMediaRequestHandler` overrides request routing:
   - Uses exact string equality: `parsed.path == expected_path`.
   - Rejects any other path with `HTTP 404 Not Found`.
   - Rejects path traversal attempts (e.g. `/video/../`, `%2e%2e`) with `HTTP 404`.
   - Rejects non-read HTTP methods (`POST`, `PUT`, `DELETE`, `OPTIONS`) with `HTTP 405 Method Not Allowed`.
3. **Context Manager Lifetime**: The server and tunnel exist only within a Python `with media_gateway.host_video(path):` context block. As soon as `publish_reel()` returns, the socket is closed.

### Verification
- Verified in `test_phase3.py` Test 6 and `test_tunnel_smoke.py`. Path traversal and non-media URLs consistently return 404; non-GET/HEAD methods return 405.

---

## Challenge 7: Supporting HTTP HEAD, GET, and Byte-Range Requests

### The Problem
During video ingestion, Meta's video crawler failed with:
```text
Video file could not be downloaded. Status: ERROR
```
even though the video file existed and was accessible via a browser.

### Why It Occurred
Meta's ingestion crawler does not perform a simple sequential GET download:
1. It first verifies the URL by issuing an `HTTP HEAD` request to inspect `Content-Length`, `Content-Type`, and `Accept-Ranges`.
2. It then downloads the video in chunks using `HTTP Range` headers (e.g. `Range: bytes=0-1048575`).
Standard Python `http.server` handlers default to `HTTP 200 OK` full responses and do not handle `HTTP 206 Partial Content`.

### How It Was Diagnosed
- Analyzing request headers from incoming Meta crawler connections showed `Range: bytes=...` headers. Naive servers returned the full file on every chunk, causing Meta's byte-counter to mismatch and fail.

### The Solution Implemented
Both `EphemeralMediaRequestHandler` and `DashboardRequestHandler` implement full RFC 7233 byte-range parsing:
1. **`do_HEAD` Support**: Generates identical headers (`Content-Type: video/mp4`, `Content-Length`, `Accept-Ranges: bytes`) without sending a body.
2. **`do_GET` Range Handling**:
   - Parses `bytes=START-END` and `bytes=START-`.
   - Returns `HTTP 206 Partial Content` with `Content-Range: bytes START-END/TOTAL`.
   - Seeks directly to `START` using `f.seek(start)` and streams exactly `(END - START + 1)` bytes in 64 KB buffers.
   - Handles client disconnections (`ConnectionResetError`, `BrokenPipeError`) gracefully.

### Verification
- Verified in `test_phase3.py` (Test 6: `Byte-range request returned HTTP 206 Partial Content for Meta crawler`).
- Verified in `test_uploader.py` (Test 3: `Video streaming with HTTP 206 Partial Content verified`).

---

## Challenge 8: Instagram Media-Container Processing & Publishing Lifecycle

### The Problem
Attempting to publish an Instagram Reel immediately after calling the container creation endpoint resulted in:
```text
Media ID is not ready for publishing (status_code: IN_PROGRESS)
```

### Why It Occurred
Meta Graph API v22.0 Content Publishing is an asynchronous three-stage pipeline:
1. **Container Creation** (`POST /{ig-user-id}/media`): Registers the video URL and returns a `creation_id`.
2. **Asynchronous Processing**: Meta's servers download the video, re-encode it, validate aspect ratio and audio specs, and generate preview thumbnails.
3. **Publishing** (`POST /{ig-user-id}/media_publish`): Takes the `creation_id` and makes the Reel live.
Calling stage 3 before stage 2 reaches `FINISHED` causes an immediate HTTP 400 failure.

### How It Was Diagnosed
- Meta Graph API documentation and response logs confirmed that container status transitions from `IN_PROGRESS` to `FINISHED` over 15 to 90 seconds depending on video length and server load.

### The Solution Implemented
1. Implemented `InstagramPublisher.poll_until_ready()`:
   - Polls `GET /{creation-id}?fields=status_code,status` every 4 seconds.
   - Monitors status transitions: `IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`.
   - Configurable timeout (default 300 seconds).
   - Emits progress updates (e.g. 35% -> 90%) to the user dashboard.
2. Implemented `InstagramPublisher.publish_container()` to commit the publication once status reaches `FINISHED`.
3. Implemented `InstagramPublisher.get_reel_permalink()` to retrieve the permanent public URL (`https://www.instagram.com/reel/<shortcode>/`) for immediate display in the dashboard.

### Verification
- Verified in `test_phase3.py` (Test 3: status polling logic; Test 4: end-to-end container publishing workflow).
- Verified with live publishing: Instagram Reels successfully created, polled, published, and recorded in `clips.json`.
