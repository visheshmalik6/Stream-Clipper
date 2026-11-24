"""Local web server for the Stream Clips Uploader Dashboard.

Binds exclusively to 127.0.0.1.
Supports media streaming with HTTP 206 Partial Content (range requests) and REST APIs.
Includes YouTube Data API v3 OAuth 2.0 flow and Resumable Video Publishing.
"""

import datetime
import json
import mimetypes
import os
import re
import shutil
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from uploader import auth_manager, discovery, instagram, storage, youtube

STATIC_DIR = Path(__file__).resolve().parent / "static"
auth = auth_manager.AuthManager()
ig_manager = instagram.InstagramManager()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local uploader dashboard."""

    server_version = "StreamClipsDashboard/1.0"
    ALLOWED_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}

    def log_message(self, format, *args):
        # Keep console output concise
        if os.environ.get("STREAMCLIPS_DEBUG"):
            super().log_message(format, *args)

    def validate_request_origin_and_host(self, check_origin: bool = True) -> Tuple[bool, str]:
        """Validate Host, Origin, and Fetch Metadata headers to prevent CSRF and DNS rebinding."""
        # 1. Host header validation
        host_header = self.headers.get("Host", "").strip()
        if not host_header:
            return False, "Missing Host header"

        try:
            parsed_host = urllib.parse.urlsplit(f"//{host_header}")
            host_name = (parsed_host.hostname or "").lower()
            host_port = parsed_host.port
        except Exception:
            return False, f"Malformed Host header: {host_header}"

        if host_name not in self.ALLOWED_LOCAL_HOSTNAMES:
            return False, f"Untrusted Host header: {host_header}"

        # Enforce server listening port
        expected_port = getattr(self.server, "server_address", (None, None))[1]
        if expected_port is not None:
            if host_port is not None and host_port != expected_port:
                return False, f"Host port {host_port} does not match server port {expected_port}"

        if not check_origin:
            return True, ""

        # 2. Fetch Metadata validation (Sec-Fetch-Site)
        sec_fetch_site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        if sec_fetch_site == "cross-site":
            return False, "Cross-site request rejected via Sec-Fetch-Site"

        # 3. Origin header validation
        origin_header = self.headers.get("Origin", "").strip()
        if origin_header:
            if origin_header.lower() == "null":
                return False, "Untrusted null origin rejected"
            try:
                parsed_origin = urllib.parse.urlparse(origin_header)
                origin_host = (parsed_origin.hostname or "").lower()
                origin_port = parsed_origin.port
                if origin_host not in self.ALLOWED_LOCAL_HOSTNAMES:
                    return False, f"Untrusted Origin header: {origin_header}"
                if expected_port is not None and origin_port is not None and origin_port != expected_port:
                    return False, f"Origin port {origin_port} does not match server port {expected_port}"
            except Exception:
                return False, "Malformed Origin header"
            return True, ""

        # 4. Fallback to Referer header if Origin is absent
        referer_header = self.headers.get("Referer", "").strip()
        if referer_header:
            try:
                parsed_ref = urllib.parse.urlparse(referer_header)
                ref_host = (parsed_ref.hostname or "").lower()
                ref_port = parsed_ref.port
                if ref_host not in self.ALLOWED_LOCAL_HOSTNAMES:
                    return False, f"Untrusted Referer header: {referer_header}"
                if expected_port is not None and ref_port is not None and ref_port != expected_port:
                    return False, f"Referer port {ref_port} does not match server port {expected_port}"
            except Exception:
                return False, "Malformed Referer header"
            return True, ""

        return True, ""

    def send_cors_and_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin", "").strip()
        if origin and origin.lower() != "null":
            try:
                parsed = urllib.parse.urlparse(origin)
                expected_port = getattr(self.server, "server_address", (None, None))[1]
                if (parsed.hostname or "").lower() in self.ALLOWED_LOCAL_HOSTNAMES:
                    if expected_port is None or parsed.port is None or parsed.port == expected_port:
                        self.send_header("Access-Control-Allow-Origin", f"{parsed.scheme}://{parsed.netloc}")
            except Exception:
                pass
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        is_valid, reason = self.validate_request_origin_and_host(check_origin=True)
        if not is_valid:
            self.send_response(HTTPStatus.FORBIDDEN)
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        origin = self.headers.get("Origin", "").strip()
        if origin and origin.lower() != "null":
            try:
                parsed = urllib.parse.urlparse(origin)
                expected_port = getattr(self.server, "server_address", (None, None))[1]
                if (parsed.hostname or "").lower() in self.ALLOWED_LOCAL_HOSTNAMES:
                    if expected_port is None or parsed.port is None or parsed.port == expected_port:
                        self.send_header("Access-Control-Allow-Origin", f"{parsed.scheme}://{parsed.netloc}")
            except Exception:
                pass
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.end_headers()

    def send_redirect(self, location: str):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        # Validate Host header against DNS rebinding attacks
        is_valid, reason = self.validate_request_origin_and_host(check_origin=False)
        if not is_valid:
            self.send_error(HTTPStatus.FORBIDDEN, f"Forbidden: {reason}")
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. API: List all discovered streams and clips
        if path == "/api/streams":
            streams = discovery.scan_clips()
            client_streams = []
            for s in streams:
                cleaned_stream = dict(s)
                cleaned_clips = []
                for c in s["clips"]:
                    client_clip = {k: v for k, v in c.items() if not k.startswith("_")}
                    cleaned_clips.append(client_clip)
                cleaned_stream["clips"] = cleaned_clips
                client_streams.append(cleaned_stream)
            return self.send_cors_and_json({"streams": client_streams})

        # 2. API: Get details for a single clip
        if path.startswith("/api/clips/"):
            clip_id = path.replace("/api/clips/", "").strip()
            clip = discovery.get_clip_by_id(clip_id)
            if not clip:
                return self.send_cors_and_json({"error": "Clip not found"}, status=404)
            client_clip = {k: v for k, v in clip.items() if not k.startswith("_")}
            return self.send_cors_and_json({"clip": client_clip})

        # 3. API: YouTube OAuth status and connection
        if path == "/api/youtube/status":
            return self.send_cors_and_json(auth.get_status())

        # 3b. API: Instagram SUAT status and connection
        if path == "/api/instagram/status":
            return self.send_cors_and_json(ig_manager.get_status())

        # 4. API: Generate Google OAuth Consent URL
        if path == "/api/youtube/auth-url":
            try:
                auth_url, state = auth.generate_auth_url()
                return self.send_cors_and_json({"auth_url": auth_url, "state": state})
            except Exception as e:
                return self.send_cors_and_json({"error": str(e)}, status=400)

        # 5. OAuth Callback from Google
        if path == "/oauth/youtube/callback":
            error = query.get("error", [None])[0]
            if error:
                return self.send_redirect(f"/?auth_error={urllib.parse.quote(error)}")

            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]

            if not state:
                return self.send_redirect("/?auth_error=missing_state")

            if not auth.verify_state(state):
                return self.send_redirect("/?auth_error=invalid_or_expired_state")

            if not code:
                return self.send_redirect("/?auth_error=missing_code")

            try:
                auth.exchange_code_for_tokens(code)
                return self.send_redirect("/?auth=youtube_success")
            except Exception as e:
                return self.send_redirect(f"/?auth_error={urllib.parse.quote(str(e))}")

        # 6. Media: Stream MP4 video with HTTP 206 Partial Content (Range requests)
        if path.startswith("/media/video/"):
            clip_id = path.replace("/media/video/", "").strip()
            clip = discovery.get_clip_by_id(clip_id)
            if not clip or not clip.get("_video_path"):
                self.send_error(HTTPStatus.NOT_FOUND, "Clip video not found")
                return
            video_path = Path(clip["_video_path"])
            if not video_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Video file missing on disk")
                return
            return self.serve_file_with_range(video_path, content_type="video/mp4")

        # 7. Media: Serve check preview frame image
        if path.startswith("/media/image/"):
            clip_id = path.replace("/media/image/", "").strip()
            clip = discovery.get_clip_by_id(clip_id)
            if not clip or not clip.get("_check_image_path"):
                self.send_error(HTTPStatus.NOT_FOUND, "Preview image not found")
                return
            image_path = Path(clip["_check_image_path"])
            if not image_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Image file missing on disk")
                return
            return self.serve_file(image_path, content_type="image/jpeg")

        # 8. Static files & dashboard UI
        if path == "/" or path == "/index.html":
            return self.serve_file(STATIC_DIR / "index.html", content_type="text/html; charset=utf-8")

        # Static assets (app.css, app.js, etc.)
        try:
            asset_path = (STATIC_DIR / path.lstrip("/")).resolve()
            is_contained = asset_path.is_relative_to(STATIC_DIR.resolve())
        except (ValueError, AttributeError):
            is_contained = False

        if is_contained and asset_path.is_file():
            content_type, _ = mimetypes.guess_type(str(asset_path))
            return self.serve_file(asset_path, content_type=content_type or "application/octet-stream")

        self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")

    def do_POST(self):
        # Validate Host, Origin, and Fetch Metadata against CSRF / DNS rebinding
        is_valid, reason = self.validate_request_origin_and_host()
        if not is_valid:
            return self.send_cors_and_json(
                {"error": "Forbidden", "message": f"Cross-origin request rejected: {reason}"},
                status=HTTPStatus.FORBIDDEN
            )

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except json.JSONDecodeError:
            return self.send_cors_and_json({"error": "Invalid JSON"}, status=400)

        # 1. API: Update clip metadata
        if path.startswith("/api/clips/"):
            clip_id = path.replace("/api/clips/", "").strip()
            clip = discovery.get_clip_by_id(clip_id)
            if not clip:
                return self.send_cors_and_json({"error": "Clip not found"}, status=404)

            title = body.get("title")
            caption = body.get("caption")
            hashtags = body.get("hashtags")

            try:
                updated_clip = storage.save_clip_metadata(
                    clips_json_path=clip["_json_path"],
                    clip_filename=clip["file"],
                    title=title,
                    caption=caption,
                    hashtags=hashtags,
                )
                return self.send_cors_and_json({
                    "success": True,
                    "message": "Metadata saved successfully with backup created",
                    "clip": updated_clip,
                })
            except Exception as e:
                return self.send_cors_and_json({"error": str(e)}, status=500)

        # 2. API: Save Google OAuth Client Configuration
        if path == "/api/youtube/config":
            raw_secrets = body.get("client_secrets_json")
            client_id = body.get("client_id")
            client_secret = body.get("client_secret")

            try:
                if raw_secrets:
                    saved = auth.save_client_secrets_json(raw_secrets)
                elif client_id and client_secret:
                    auth.save_client_config(client_id, client_secret)
                    saved = {"client_id": client_id}
                else:
                    return self.send_cors_and_json({"error": "Missing client_id/client_secret or client_secrets_json"}, status=400)

                return self.send_cors_and_json({
                    "success": True,
                    "message": "Google Client configuration saved securely.",
                    "config": saved,
                })
            except Exception as e:
                return self.send_cors_and_json({"error": str(e)}, status=400)

        # 3. API: Clear Google OAuth Client Configuration
        if path == "/api/youtube/config/clear":
            auth.clear_client_config()
            auth.disconnect()
            return self.send_cors_and_json({
                "success": True,
                "message": "Google Client configuration and tokens cleared.",
            })

        # 4. API: Disconnect YouTube Account
        if path == "/api/youtube/disconnect":
            auth.disconnect()
            return self.send_cors_and_json({"success": True, "message": "YouTube disconnected."})

        # 4b. API: Configure Instagram Credentials
        if path == "/api/instagram/config":
            access_token = body.get("access_token", "").strip()
            public_base_url = body.get("public_base_url")
            if not access_token:
                return self.send_cors_and_json({"error": "Missing access_token"}, status=400)
            try:
                res = ig_manager.save_credentials(
                    access_token=access_token,
                    public_base_url=public_base_url,
                )
                return self.send_cors_and_json({
                    "success": True,
                    "message": "Instagram System-User Access Token configured securely.",
                    "account": res.get("account"),
                    "masked_token": res.get("masked_token"),
                    "public_base_url": res.get("public_base_url"),
                })
            except Exception as e:
                return self.send_cors_and_json({"error": str(e)}, status=400)

        # 4c. API: Disconnect Instagram Account
        if path == "/api/instagram/disconnect":
            ig_manager.disconnect()
            return self.send_cors_and_json({"success": True, "message": "Instagram disconnected."})

        # 5. API: Publish or Schedule to YouTube Shorts (Official Resumable Upload)
        if path == "/api/publish/youtube":
            clip_id = body.get("clip_id")
            if not clip_id:
                return self.send_cors_and_json({"error": "Missing clip_id"}, status=400)

            clip = discovery.get_clip_by_id(clip_id)
            if not clip:
                return self.send_cors_and_json({"error": "Clip not found"}, status=404)

            # Extract and validate optional publish_at timestamp
            raw_publish_at = body.get("publish_at")
            publish_at = raw_publish_at.strip() if isinstance(raw_publish_at, str) and raw_publish_at.strip() else None

            if raw_publish_at is not None and not publish_at:
                return self.send_cors_and_json({
                    "error": "invalid_timestamp",
                    "message": "publish_at must be a non-empty UTC ISO-8601 string.",
                }, status=400)

            if publish_at is not None:
                try:
                    youtube.validate_publish_at(publish_at)
                except ValueError as ve:
                    return self.send_cors_and_json({
                        "error": "invalid_timestamp",
                        "message": str(ve),
                    }, status=400)

            # Check duplicate upload prevention (guards both published and scheduled states)
            force = body.get("force", False)
            existing_upload = clip.get("uploads", {}).get("youtube", {})
            existing_status = existing_upload.get("status")
            if existing_status in ("published", "scheduled") and not force:
                status_desc = "published to" if existing_status == "published" else "scheduled for"
                return self.send_cors_and_json({
                    "error": "already_published",
                    "status": existing_status,
                    "message": f"This clip has already been {status_desc} YouTube Shorts.",
                    "video_id": existing_upload.get("video_id"),
                    "url": existing_upload.get("url"),
                    "uploaded_at": existing_upload.get("uploaded_at"),
                    "scheduled_at": existing_upload.get("scheduled_at") or existing_upload.get("publish_at"),
                }, status=409)

            # Check authentication
            try:
                access_token = auth.get_valid_access_token()
            except PermissionError as pe:
                return self.send_cors_and_json({
                    "error": "not_authenticated",
                    "message": str(pe),
                }, status=401)
            except Exception as e:
                return self.send_cors_and_json({
                    "error": "auth_error",
                    "message": f"Failed to authenticate with YouTube: {e}",
                }, status=401)

            # Read latest metadata from request or fallback to clip metadata
            title = body.get("title", clip.get("title", ""))
            caption = body.get("caption", clip.get("caption", ""))
            hashtags = body.get("hashtags", clip.get("hashtags", []))
            privacy = "private" if publish_at else body.get("privacy", "public")

            # Save any metadata edits first
            storage.save_clip_metadata(
                clips_json_path=clip["_json_path"],
                clip_filename=clip["file"],
                title=title,
                caption=caption,
                hashtags=hashtags,
            )

            # Mark status in progress
            upload_in_progress = {
                "status": "in_progress",
                "video_id": None,
                "url": None,
                "uploaded_at": None,
                "privacy": privacy,
                "error": None,
            }
            if publish_at:
                upload_in_progress["scheduled_at"] = publish_at
                upload_in_progress["publish_at"] = publish_at

            storage.update_clip_upload_status(
                clips_json_path=clip["_json_path"],
                clip_filename=clip["file"],
                platform="youtube",
                upload_status_dict=upload_in_progress,
            )

            # Perform resumable upload
            video_file = Path(clip["_video_path"])
            uploader = youtube.YouTubeUploader(access_token)

            try:
                result = uploader.upload_clip(
                    video_path=video_file,
                    title=title,
                    description=caption,
                    tags=hashtags,
                    privacy_status=privacy,
                    publish_at=publish_at,
                )

                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if publish_at:
                    final_status = {
                        "status": "scheduled",
                        "video_id": result["video_id"],
                        "url": result["url"],
                        "uploaded_at": now_iso,
                        "scheduled_at": publish_at,
                        "publish_at": publish_at,
                        "privacy": "private",
                        "error": None,
                    }
                    success_msg = "Successfully scheduled for YouTube Shorts!"
                else:
                    final_status = {
                        "status": "published",
                        "video_id": result["video_id"],
                        "url": result["url"],
                        "uploaded_at": now_iso,
                        "privacy": privacy,
                        "error": None,
                    }
                    success_msg = "Successfully published to YouTube Shorts!"

                storage.update_clip_upload_status(
                    clips_json_path=clip["_json_path"],
                    clip_filename=clip["file"],
                    platform="youtube",
                    upload_status_dict=final_status,
                )

                return self.send_cors_and_json({
                    "success": True,
                    "message": success_msg,
                    "upload": final_status,
                })

            except Exception as exc:
                failed_status = {
                    "status": "failed",
                    "video_id": None,
                    "url": None,
                    "uploaded_at": None,
                    "privacy": privacy,
                    "error": str(exc),
                }
                if publish_at:
                    failed_status["scheduled_at"] = None
                    failed_status["publish_at"] = None

                storage.update_clip_upload_status(
                    clips_json_path=clip["_json_path"],
                    clip_filename=clip["file"],
                    platform="youtube",
                    upload_status_dict=failed_status,
                )
                return self.send_cors_and_json({
                    "success": False,
                    "error": str(exc),
                    "upload": failed_status,
                }, status=500)

        # 6. API: Publish to Instagram Reels
        if path == "/api/publish/instagram":
            clip_id = body.get("clip_id")
            if not clip_id:
                return self.send_cors_and_json({"error": "Missing clip_id"}, status=400)

            clip = discovery.get_clip_by_id(clip_id)
            if not clip:
                return self.send_cors_and_json({"error": "Clip not found"}, status=404)

            # Check duplicate upload prevention
            force = body.get("force", False)
            existing_upload = clip.get("uploads", {}).get("instagram", {})
            if existing_upload.get("status") == "published" and not force:
                return self.send_cors_and_json({
                    "error": "already_published",
                    "message": "This clip has already been published to Instagram Reels.",
                    "media_id": existing_upload.get("media_id"),
                    "url": existing_upload.get("url"),
                    "uploaded_at": existing_upload.get("uploaded_at"),
                }, status=409)

            # Check authentication
            try:
                access_token = ig_manager.get_valid_access_token()
                account_id = ig_manager.get_account_id()
            except PermissionError as pe:
                return self.send_cors_and_json({
                    "error": "not_authenticated",
                    "message": str(pe),
                }, status=401)
            except Exception as e:
                return self.send_cors_and_json({
                    "error": "auth_error",
                    "message": f"Failed to authenticate with Instagram: {e}",
                }, status=401)

            # Read latest metadata from request or fallback to clip metadata
            title = body.get("title", clip.get("title", ""))
            caption = body.get("caption", clip.get("caption", ""))
            hashtags = body.get("hashtags", clip.get("hashtags", []))

            # Save any metadata edits first
            storage.save_clip_metadata(
                clips_json_path=clip["_json_path"],
                clip_filename=clip["file"],
                title=title,
                caption=caption,
                hashtags=hashtags,
            )

            # Mark status in progress
            storage.update_clip_upload_status(
                clips_json_path=clip["_json_path"],
                clip_filename=clip["file"],
                platform="instagram",
                upload_status_dict={
                    "status": "in_progress",
                    "media_id": None,
                    "url": None,
                    "uploaded_at": None,
                    "error": None,
                },
            )

            clean_tags = " ".join([f"#{t.lstrip('#')}" for t in hashtags if t.strip()])
            full_caption = f"{caption}\n\n{clean_tags}".strip() if clean_tags else caption.strip()

            video_file = Path(clip["_video_path"])
            if not video_file.exists():
                return self.send_cors_and_json({"error": "Video file missing on disk"}, status=404)

            publisher = instagram.InstagramPublisher(access_token=access_token, account_id=account_id)
            creds = ig_manager.get_credentials() or {}
            custom_url = body.get("public_base_url") or creds.get("public_base_url") or os.environ.get("STREAMCLIPS_PUBLIC_URL")

            # Dedicated media gateway on separate ephemeral port (tunnel NEVER points to port 5050)
            media_gateway = instagram.EphemeralMediaGateway(custom_base_url=custom_url)

            try:
                with media_gateway.host_video(video_path=video_file) as public_video_url:
                    pub_result = publisher.publish_reel(
                        video_url=public_video_url,
                        caption=full_caption,
                        share_to_feed=True,
                    )

                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                final_status = {
                    "status": "published",
                    "media_id": pub_result["media_id"],
                    "url": pub_result["url"],
                    "uploaded_at": now_iso,
                    "error": None,
                }
                storage.update_clip_upload_status(
                    clips_json_path=clip["_json_path"],
                    clip_filename=clip["file"],
                    platform="instagram",
                    upload_status_dict=final_status,
                )

                return self.send_cors_and_json({
                    "success": True,
                    "message": "Successfully published to Instagram Reels!",
                    "upload": final_status,
                })

            except Exception as exc:
                failed_status = {
                    "status": "failed",
                    "media_id": None,
                    "url": None,
                    "uploaded_at": None,
                    "error": str(exc),
                }
                storage.update_clip_upload_status(
                    clips_json_path=clip["_json_path"],
                    clip_filename=clip["file"],
                    platform="instagram",
                    upload_status_dict=failed_status,
                )
                return self.send_cors_and_json({
                    "success": False,
                    "error": str(exc),
                    "upload": failed_status,
                }, status=500)

        if path == "/api/publish/both":
            return self.send_cors_and_json({
                "success": False,
                "placeholder": True,
                "platform": "both",
                "message": "Multi-platform publishing to Both platforms will be enabled in Phase 4.",
            })

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def serve_file(self, file_path: Path, content_type: str):
        """Serve a full file directly."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error reading file")

    def serve_file_with_range(self, file_path: Path, content_type: str):
        """Serve file with HTTP 206 Partial Content support for seeking in HTML5 video."""
        try:
            file_size = file_path.stat().st_size
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not accessible")
            return

        range_header = self.headers.get("Range")
        if not range_header:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return

        match = re.match(r"bytes=(\d+)-(\d*)", range_header.strip())
        if not match:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
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
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(chunk_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_left = chunk_size
            buffer_size = 64 * 1024
            while bytes_left > 0:
                read_amount = min(bytes_left, buffer_size)
                chunk = f.read(read_amount)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError):
                    break
                bytes_left -= len(chunk)


def run_server(host: str = "127.0.0.1", port: int = 5050):
    """Start local dashboard server bound strictly to 127.0.0.1."""
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, DashboardRequestHandler)
    print(f"\n=======================================================")
    print(f"  Stream Clips Dashboard is running at:")
    print(f"  http://{host}:{port}")
    print(f"=======================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
    run_server(host="127.0.0.1", port=port)
