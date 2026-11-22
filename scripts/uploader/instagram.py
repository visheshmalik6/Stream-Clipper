"""Official Meta Graph API client for Instagram Reels publishing and SUAT management.

Follows official Meta Graph API v22.0 Content Publishing workflow:
1. Container creation: POST /{ig-user-id}/media (media_type=REELS, video_url=...)
2. Processing status polling: GET /{creation-id}?fields=status_code,status
3. Container publish: POST /{ig-user-id}/media_publish (creation_id=...)
4. Permalinks and details: GET /{media-id}?fields=id,permalink

Stores credentials securely in ~/.streamclips/auth/ outside the repository.
"""

import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

# Secure storage directory outside repository
AUTH_DIR = Path.home() / ".streamclips" / "auth"
AUTH_DIR.mkdir(parents=True, exist_ok=True)

INSTAGRAM_CONFIG_FILE = AUTH_DIR / "instagram_config.json"

# Meta Graph API configuration
GRAPH_API_VERSION = "v22.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class InstagramError(Exception):
    """Base exception for Instagram API operations."""


class InstagramAuthError(InstagramError):
    """Raised when authentication or token validation fails."""


class InstagramPublishError(InstagramError):
    """Raised when media container creation, processing, or publishing fails."""


def mask_token(token: Optional[str]) -> str:
    """Safely mask an access token for display in logs or UI."""
    if not token:
        return ""
    token_str = str(token).strip()
    if len(token_str) > 16:
        return f"{token_str[:6]}...{token_str[-6:]}"
    elif len(token_str) > 6:
        return f"{token_str[:3]}...{token_str[-2:]}"
    return "***"


def sanitize_error_message(raw_msg: str, secret_token: Optional[str] = None) -> str:
    """Ensure secret token or sensitive headers are never exposed in exception strings."""
    if not raw_msg:
        return "Unknown error"
    clean = str(raw_msg)
    if secret_token and secret_token in clean:
        clean = clean.replace(secret_token, "[REDACTED_TOKEN]")
    # Also strip common token patterns (e.g. EAAG... or Bearer ...)
    clean = re.sub(r"EAA[A-Za-z0-9]+", "[REDACTED_TOKEN]", clean)
    clean = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", clean)
    return clean


class InstagramManager:
    """Manages Instagram System-User Access Tokens (SUAT), validation, and account mapping."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or INSTAGRAM_CONFIG_FILE

    def get_credentials(self) -> Optional[Dict[str, Any]]:
        """Load stored Instagram credentials from secure storage."""
        if not self.config_file.exists():
            return None
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            if data and data.get("access_token"):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def get_valid_access_token(self) -> str:
        """Return the stored access token, raising PermissionError if missing."""
        creds = self.get_credentials()
        if not creds or not creds.get("access_token"):
            raise PermissionError("Instagram account is not configured. Please enter your Instagram Access Token first.")
        return creds["access_token"]

    def get_account_id(self) -> str:
        """Return the verified Instagram Account ID, raising PermissionError if missing."""
        creds = self.get_credentials()
        if not creds or not creds.get("account_id"):
            raise PermissionError("Instagram account ID could not be identified. Please reconnect your account.")
        return creds["account_id"]

    def validate_token(self, access_token: str) -> Dict[str, Any]:
        """Validate the System-User Access Token with Meta Graph API and resolve account details.
        
        Attempts Unified Login SUAT discovery first, followed by Page-linked accounts,
        and direct user node lookups.
        """
        token = access_token.strip()
        if not token:
            raise InstagramAuthError("Access token cannot be empty.")

        account_info = None

        # 1. Primary Unified Login SUAT endpoint: /me/assigned_instagram_accounts
        try:
            url = f"{GRAPH_API_BASE}/me/assigned_instagram_accounts?fields=id,username,name,profile_picture_url"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("data", [])
                if items:
                    account_info = items[0]
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            # If not a 400/403 with specific subcode, check if we should fall back
            try:
                err_json = json.loads(err_body)
                err_obj = err_json.get("error", {})
                # If OAuthException with code 190, the token is definitely invalid/expired
                if err_obj.get("code") == 190:
                    msg = err_obj.get("message", "Invalid or expired access token.")
                    raise InstagramAuthError(f"Meta authentication failed: {sanitize_error_message(msg, token)}")
            except json.JSONDecodeError:
                pass
        except Exception:
            pass

        # 2. Fallback: /me/accounts with instagram_business_account
        if not account_info:
            try:
                url = f"{GRAPH_API_BASE}/me/accounts?fields=id,name,instagram_business_account{{id,username,name,profile_picture_url}}"
                req = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for page in data.get("data", []):
                        ig_acc = page.get("instagram_business_account")
                        if ig_acc and ig_acc.get("id"):
                            account_info = ig_acc
                            break
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                try:
                    err_json = json.loads(err_body)
                    if err_json.get("error", {}).get("code") == 190:
                        msg = err_json.get("error", {}).get("message", "Invalid access token.")
                        raise InstagramAuthError(f"Meta authentication failed: {sanitize_error_message(msg, token)}")
                except json.JSONDecodeError:
                    pass
            except Exception:
                pass

        # 3. Fallback: Direct /me endpoint
        if not account_info:
            try:
                url = f"{GRAPH_API_BASE}/me?fields=id,username,name,profile_picture_url"
                req = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("id"):
                        account_info = data
            except Exception:
                pass

        if not account_info or not account_info.get("id"):
            raise InstagramAuthError(
                "Could not detect an Instagram Professional or Creator account associated with this token. "
                "Ensure your Meta App has instagram_basic and instagram_content_publish permissions, "
                "and your Instagram account is assigned to your System User."
            )

        return {
            "valid": True,
            "account": {
                "id": str(account_info.get("id")),
                "username": account_info.get("username", ""),
                "name": account_info.get("name", account_info.get("username", "Instagram Account")),
                "profile_picture_url": account_info.get("profile_picture_url", ""),
            },
        }

    def save_credentials(
        self,
        access_token: str,
        public_base_url: Optional[str] = None,
        account_id: Optional[str] = None,
        username: Optional[str] = None,
        skip_validation: bool = False,
    ) -> Dict[str, Any]:
        """Validate and securely persist Instagram credentials outside the repository."""
        token = access_token.strip()
        if not token:
            raise ValueError("Access token cannot be empty.")

        if not skip_validation:
            validation = self.validate_token(token)
            account_data = validation["account"]
        else:
            account_data = {
                "id": account_id or "unknown",
                "username": username or "",
                "name": username or "Instagram Account",
                "profile_picture_url": "",
            }

        data = {
            "access_token": token,
            "account_id": account_data["id"],
            "username": account_data.get("username", ""),
            "name": account_data.get("name", ""),
            "profile_picture_url": account_data.get("profile_picture_url", ""),
            "public_base_url": public_base_url.strip().rstrip("/") if public_base_url else None,
            "token_type": "SYSTEM_USER",
            "updated_at": time.time(),
        }

        # Save atomically
        tmp = self.config_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.config_file)

        return {
            "success": True,
            "masked_token": mask_token(token),
            "account": account_data,
            "public_base_url": data["public_base_url"],
        }

    def get_status(self) -> Dict[str, Any]:
        """Return Instagram connection status for dashboard UI without leaking tokens."""
        creds = self.get_credentials()
        has_creds = bool(creds and creds.get("access_token"))
        account = None
        masked = None
        public_base_url = None

        if has_creds and creds:
            masked = mask_token(creds.get("access_token"))
            public_base_url = creds.get("public_base_url")
            account = {
                "id": creds.get("account_id"),
                "username": creds.get("username") or creds.get("account_id"),
                "name": creds.get("name") or creds.get("username", "Instagram Creator"),
                "profile_picture_url": creds.get("profile_picture_url", ""),
            }

        return {
            "configured": has_creds,
            "connected": bool(has_creds and account and account.get("id")),
            "masked_token": masked,
            "account": account,
            "public_base_url": public_base_url,
            "storage_path": str(self.config_file.parent),
        }

    def disconnect(self) -> None:
        """Remove stored credentials and disconnect account."""
        if self.config_file.exists():
            self.config_file.unlink(missing_ok=True)


class EphemeralMediaRequestHandler(BaseHTTPRequestHandler):
    """Strict media-only HTTP handler serving a single video file at an unguessable URL.
    
    Exposes zero dashboard routes, zero APIs, and zero configuration.
    Accepts only GET and HEAD on the exact unguessable URL path.
    Rejects all other paths and HTTP methods with 404/405.
    """

    server_version = "StreamClipsMediaGateway/1.0"

    def log_message(self, format, *args):
        if os.environ.get("STREAMCLIPS_DEBUG"):
            super().log_message(format, *args)

    def do_HEAD(self):
        self._handle_media_request(is_head=True)

    def do_GET(self):
        self._handle_media_request(is_head=False)

    def do_POST(self):
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method Not Allowed")

    def do_PUT(self):
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method Not Allowed")

    def do_DELETE(self):
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method Not Allowed")

    def do_OPTIONS(self):
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method Not Allowed")

    def _handle_media_request(self, is_head: bool = False):
        parsed = urllib.parse.urlparse(self.path)
        expected_path = getattr(self.server, "expected_path", None)
        target_file = getattr(self.server, "target_file", None)

        # Strict exact string equality on the unguessable URL
        # Rejects /, /api/*, /oauth/*, /media/*, directory traversal (..), etc.
        if not expected_path or parsed.path != expected_path:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        if not target_file or not target_file.exists() or not target_file.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Media Not Found")
            return

        try:
            file_size = target_file.stat().st_size
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Cannot read media file")
            return

        range_header = self.headers.get("Range")
        if not range_header:
            # Full file response
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()

            if not is_head:
                try:
                    with open(target_file, "rb") as f:
                        shutil.copyfileobj(f, self.wfile, length=64 * 1024)
                except (ConnectionResetError, BrokenPipeError):
                    pass
            return

        # Partial content / Byte-range request for video seeking by Meta crawler
        match = re.match(r"^bytes=(\d+)-(\d*)$", range_header.strip())
        if not match:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return

        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1

        if start >= file_size or end >= file_size or start > end:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return

        chunk_size = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(chunk_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()

        if not is_head:
            try:
                with open(target_file, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    buf_size = 64 * 1024
                    while remaining > 0:
                        read_len = min(remaining, buf_size)
                        chunk = f.read(read_len)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (ConnectionResetError, BrokenPipeError):
                pass


class TunnelManager:
    """Manages ephemeral Cloudflare Quick Tunnels strictly pointing to isolated media servers."""

    def __init__(self, custom_base_url: Optional[str] = None):
        self.custom_base_url = custom_base_url.strip().rstrip("/") if custom_base_url else None
        self._proc: Optional[subprocess.Popen] = None
        self._active_url: Optional[str] = None
        self._lock = threading.Lock()

    def find_cloudflared(self) -> Optional[str]:
        """Locate cloudflared executable in standard system locations or PATH."""
        # Check PATH
        path_bin = shutil.which("cloudflared")
        if path_bin:
            return path_bin

        # Standard Windows locations
        candidates = [
            Path("C:/Program Files/cloudflared/cloudflared.exe"),
            Path("C:/Program Files (x86)/cloudflared/cloudflared.exe"),
            Path.home() / ".streamclips" / "bin" / "cloudflared.exe",
            Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return str(c)

        return None

    def start_tunnel(self, local_port: int, timeout: float = 30.0) -> str:
        """Start a Cloudflare Quick Tunnel pointing strictly to local_port.
        
        Strictly prohibits local_port=5050 to prevent exposing the dashboard.
        """
        if local_port == 5050:
            raise ValueError(
                "Security Violation: Cloudflare Tunnel must never point to port 5050 (dashboard). "
                "It must point strictly to an isolated ephemeral media-only server."
            )

        if self.custom_base_url:
            return self.custom_base_url

        with self._lock:
            if self._active_url and self._proc and self._proc.poll() is None:
                return self._active_url

            bin_path = self.find_cloudflared()
            if not bin_path:
                raise InstagramPublishError(
                    "Cloudflare Tunnel (cloudflared) is not installed or not found in PATH. "
                    "Install it using 'winget install Cloudflare.cloudflared' or configure a "
                    "Public Tunnel URL in Instagram Settings."
                )

            cmd = [bin_path, "tunnel", "--url", f"http://127.0.0.1:{local_port}"]

            try:
                # cloudflared logs connection info and the trycloudflare.com URL to stderr
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except Exception as e:
                raise InstagramPublishError(f"Failed to launch cloudflared tunnel: {e}") from e

            # Parse stderr to find the generated https://*.trycloudflare.com URL
            url_match = None
            start_time = time.time()
            url_regex = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

            while time.time() - start_time < timeout:
                if self._proc.poll() is not None:
                    # Process died early
                    err_out = self._proc.stderr.read() if self._proc.stderr else ""
                    raise InstagramPublishError(f"cloudflared tunnel process exited unexpectedly: {err_out[:200]}")

                line = self._proc.stderr.readline()
                if line:
                    m = url_regex.search(line)
                    if m:
                        url_match = m.group(0)
                        break
                else:
                    time.sleep(0.1)

            if not url_match:
                self.stop_tunnel()
                raise InstagramPublishError(
                    f"Timed out after {timeout}s waiting for Cloudflare Tunnel URL to be generated."
                )

            self._active_url = url_match.rstrip("/")
            return self._active_url

    def stop_tunnel(self) -> None:
        """Stop running quick tunnel process."""
        with self._lock:
            if self._proc:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=3)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None
            self._active_url = None


class EphemeralMediaGateway:
    """Orchestrates an ephemeral media-only HTTP server and an isolated Cloudflare Quick Tunnel.
    
    The Cloudflare Quick Tunnel is bound EXCLUSIVELY to the media-only server's local port.
    Port 5050 and the dashboard are completely isolated and never exposed through the tunnel.
    """

    def __init__(self, custom_base_url: Optional[str] = None):
        self.custom_base_url = custom_base_url.strip().rstrip("/") if custom_base_url else None
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._tunnel_manager: Optional[TunnelManager] = None
        self._secret_token: Optional[str] = None

    @contextlib.contextmanager
    def host_video(
        self,
        video_path: Path,
        timeout: float = 30.0,
    ) -> Generator[str, None, None]:
        """Start media-only server and tunnel, yield public HTTPS URL, and guarantee clean shutdown."""
        path = Path(video_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Video file not found for hosting: {path}")

        # 1. Generate unguessable, cryptographically random token (32 bytes)
        self._secret_token = secrets.token_urlsafe(32)
        expected_path = f"/video/{self._secret_token}.mp4"

        # 2. Start dedicated media-only HTTP server on ephemeral local port (port 0)
        server_address = ("127.0.0.1", 0)
        self._server = ThreadingHTTPServer(server_address, EphemeralMediaRequestHandler)
        self._server.target_file = path
        self._server.expected_path = expected_path
        media_port = self._server.server_address[1]

        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

        public_video_url = None
        try:
            # 3. Connect tunnel exclusively to media_port (NEVER port 5050)
            if self.custom_base_url:
                public_video_url = f"{self.custom_base_url}{expected_path}"
                yield public_video_url
            else:
                self._tunnel_manager = TunnelManager()
                tunnel_base = self._tunnel_manager.start_tunnel(local_port=media_port, timeout=timeout)
                public_video_url = f"{tunnel_base}{expected_path}"
                yield public_video_url

        finally:
            # 4. Clean shutdown of both tunnel and media-only server
            if self._tunnel_manager:
                try:
                    self._tunnel_manager.stop_tunnel()
                except Exception:
                    pass
                self._tunnel_manager = None

            if self._server:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None
                self._server_thread = None


class InstagramPublisher:
    """Manages Instagram Content Publishing for Reels via Meta Graph API."""

    def __init__(self, access_token: str, account_id: str):
        self.access_token = access_token
        self.account_id = account_id

    def create_media_container(
        self,
        video_url: str,
        caption: str = "",
        share_to_feed: bool = True,
    ) -> str:
        """Step 1: Create an Instagram Reel media container."""
        if not video_url or not video_url.startswith("https://"):
            raise InstagramPublishError("A valid public HTTPS video URL is required for Instagram publishing.")

        url = f"{GRAPH_API_BASE}/{self.account_id}/media"
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption.strip(),
            "share_to_feed": "true" if share_to_feed else "false",
        }

        body_bytes = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                creation_id = data.get("id")
                if not creation_id:
                    raise InstagramPublishError("Media container creation response did not contain a container ID.")
                return str(creation_id)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            clean_msg = sanitize_error_message(err_msg, self.access_token)
            raise InstagramPublishError(f"Container creation failed (HTTP {exc.code}): {clean_msg}") from exc

    def check_media_status(self, creation_id: str) -> Dict[str, Any]:
        """Step 2: Check processing status of the created media container."""
        url = f"{GRAPH_API_BASE}/{creation_id}?fields=status_code,status"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "status_code": data.get("status_code", "UNKNOWN"),
                    "status": data.get("status", ""),
                }
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            clean_msg = sanitize_error_message(err_msg, self.access_token)
            raise InstagramPublishError(f"Status check failed (HTTP {exc.code}): {clean_msg}") from exc

    def poll_until_ready(
        self,
        creation_id: str,
        max_wait: float = 300.0,
        poll_interval: float = 4.0,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> bool:
        """Poll container status until status_code becomes FINISHED."""
        start_time = time.time()
        elapsed = 0.0

        while elapsed < max_wait:
            status_info = self.check_media_status(creation_id)
            code = status_info.get("status_code", "UNKNOWN").upper()

            if code == "FINISHED":
                if progress_callback:
                    progress_callback("Ready to publish", 100)
                return True

            if code == "ERROR":
                err_desc = status_info.get("status") or "Meta video processing encountered an internal error."
                raise InstagramPublishError(f"Instagram video processing failed: {err_desc}")

            if code == "EXPIRED":
                raise InstagramPublishError("Media container expired before it could be published.")

            # IN_PROGRESS or UNKNOWN
            elapsed = time.time() - start_time
            # Simulated progress between 30% and 90% while polling
            pct = min(90, int(30 + (elapsed / max_wait) * 60))
            if progress_callback:
                progress_callback(f"Processing Reel ({code})...", pct)

            time.sleep(poll_interval)

        raise InstagramPublishError(
            f"Timed out after {max_wait:.0f} seconds waiting for Meta to finish processing video."
        )

    def publish_container(self, creation_id: str) -> str:
        """Step 3: Publish the ready media container."""
        url = f"{GRAPH_API_BASE}/{self.account_id}/media_publish"
        payload = {"creation_id": creation_id}
        body_bytes = urllib.parse.urlencode(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                media_id = data.get("id")
                if not media_id:
                    raise InstagramPublishError("Media publish response did not contain a published media ID.")
                return str(media_id)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            clean_msg = sanitize_error_message(err_msg, self.access_token)
            raise InstagramPublishError(f"Publish failed (HTTP {exc.code}): {clean_msg}") from exc

    def get_reel_permalink(self, media_id: str) -> Optional[str]:
        """Fetch the public permalink for a published Instagram Reel."""
        url = f"{GRAPH_API_BASE}/{media_id}?fields=id,permalink,media_type"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("permalink")
        except Exception:
            return None

    def publish_reel(
        self,
        video_url: str,
        caption: str = "",
        share_to_feed: bool = True,
        max_wait: float = 300.0,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> Dict[str, Any]:
        """Execute full Instagram Reels publishing sequence."""
        if progress_callback:
            progress_callback("Creating media container on Instagram...", 20)

        creation_id = self.create_media_container(
            video_url=video_url,
            caption=caption,
            share_to_feed=share_to_feed,
        )

        if progress_callback:
            progress_callback("Waiting for Meta video processing...", 35)

        self.poll_until_ready(
            creation_id=creation_id,
            max_wait=max_wait,
            progress_callback=progress_callback,
        )

        if progress_callback:
            progress_callback("Publishing Reel to Instagram...", 92)

        media_id = self.publish_container(creation_id=creation_id)
        permalink = self.get_reel_permalink(media_id)

        if progress_callback:
            progress_callback("Published successfully!", 100)

        return {
            "media_id": media_id,
            "url": permalink or f"https://www.instagram.com/p/{media_id}/",
            "creation_id": creation_id,
        }
