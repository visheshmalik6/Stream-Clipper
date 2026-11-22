"""Official YouTube Data API v3 client with Resumable Video Uploads.

Follows the official Google resumable upload protocol:
https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
"""

import json
import os
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
CHUNK_SIZE = 1024 * 1024  # 1 MB chunks (must be multiple of 256 KB)


class YouTubeUploadError(Exception):
    """Raised when YouTube video upload fails."""


class YouTubeUploader:
    """Manages YouTube Shorts resumable video uploads."""

    def __init__(self, access_token: str):
        self.access_token = access_token

    def initiate_resumable_upload(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        privacy_status: str = "private",
        category_id: str = "20",  # 20 = Gaming
    ) -> str:
        """Step 1: Initiate resumable upload session with metadata."""
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        file_size = video_path.stat().st_size

        # Format hashtags and ensure #Shorts is included for vertical Shorts discovery
        clean_tags = [t.lstrip("#") for t in (tags or []) if t.strip()]
        if "Shorts" not in clean_tags and "shorts" not in clean_tags:
            clean_tags.append("Shorts")

        full_description = description.strip()
        if "#Shorts" not in full_description and "#shorts" not in full_description:
            full_description = f"{full_description}\n\n#Shorts"

        metadata = {
            "snippet": {
                "title": title[:100].strip(),
                "description": full_description[:5000].strip(),
                "tags": clean_tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status.lower() if privacy_status in ("private", "unlisted", "public") else "private",
                "selfDeclaredMadeForKids": False,
            },
        }

        body_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/mp4",
        }

        req = urllib.request.Request(
            UPLOAD_ENDPOINT,
            data=body_bytes,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                upload_url = resp.headers.get("Location")
                if not upload_url:
                    raise YouTubeUploadError("Failed to obtain resumable upload URL from YouTube.")
                return upload_url
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                msg = err_body
            raise YouTubeUploadError(f"YouTube upload initiation failed (HTTP {exc.code}): {msg}") from exc

    def upload_chunks(
        self,
        upload_url: str,
        video_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Step 2: Stream video bytes in chunks according to the official protocol."""
        file_size = video_path.stat().st_size
        uploaded_bytes = 0

        # Query existing session status in case of resume
        start_byte = self._query_upload_status(upload_url, file_size)

        with open(video_path, "rb") as f:
            f.seek(start_byte)
            uploaded_bytes = start_byte

            while uploaded_bytes < file_size:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break

                chunk_len = len(chunk)
                start = uploaded_bytes
                end = uploaded_bytes + chunk_len - 1

                headers = {
                    "Content-Length": str(chunk_len),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Type": "video/mp4",
                }

                req = urllib.request.Request(
                    upload_url,
                    data=chunk,
                    headers=headers,
                    method="PUT",
                )

                try:
                    with urllib.request.urlopen(req) as resp:
                        # Final chunk returns 200 or 201 Created
                        if resp.status in (HTTPStatus.OK, HTTPStatus.CREATED):
                            resp_data = json.loads(resp.read().decode("utf-8"))
                            video_id = resp_data.get("id")
                            if not video_id:
                                raise YouTubeUploadError("Upload completed but no video ID was returned.")
                            return {
                                "video_id": video_id,
                                "url": f"https://youtube.com/shorts/{video_id}",
                                "raw": resp_data,
                            }
                except urllib.error.HTTPError as exc:
                    # HTTP 308 Resume Incomplete is expected for intermediate chunks
                    if exc.code == 308:
                        uploaded_bytes += chunk_len
                        if progress_callback:
                            progress_callback(uploaded_bytes, file_size)
                        continue

                    # Any other error
                    err_body = exc.read().decode("utf-8", errors="replace")
                    raise YouTubeUploadError(f"Chunk upload failed (HTTP {exc.code}): {err_body}") from exc

        raise YouTubeUploadError("Upload ended without receiving confirmation from YouTube.")

    def _query_upload_status(self, upload_url: str, file_size: int) -> int:
        """Check how many bytes have been received so far if resuming an upload."""
        req = urllib.request.Request(
            upload_url,
            headers={
                "Content-Length": "0",
                "Content-Range": f"bytes */{file_size}",
            },
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status in (HTTPStatus.OK, HTTPStatus.CREATED):
                    return file_size
        except urllib.error.HTTPError as exc:
            if exc.code == 308:
                range_header = exc.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    # Format: bytes=0-1048575
                    parts = range_header.replace("bytes=", "").split("-")
                    if len(parts) == 2 and parts[1].isdigit():
                        return int(parts[1]) + 1
        return 0

    def upload_clip(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        privacy_status: str = "private",
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Perform full resumable upload: initiate session and stream video chunks."""
        upload_url = self.initiate_resumable_upload(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy_status,
        )
        return self.upload_chunks(upload_url, video_path, progress_callback=progress_callback)
