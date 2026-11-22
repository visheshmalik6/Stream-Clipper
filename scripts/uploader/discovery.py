"""Clip discovery service.

Discovers generated clips and clips.json files within the configured DATA directory
from sc.common and STREAMCLIPS_HOME without scanning unrelated directories or
creating duplicate entries.
"""

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from sc.common import DATA
except ImportError:
    DATA = Path(os.environ.get("STREAMCLIPS_HOME", Path.home() / "StreamClips"))


def get_configured_data_roots() -> List[Path]:
    """Return configured data root directories without scanning unrelated paths."""
    roots: List[Path] = []
    seen: set = set()

    # 1. sc.common.DATA (which respects STREAMCLIPS_HOME or defaults to ~/StreamClips)
    if DATA.exists():
        resolved = DATA.resolve()
        if resolved not in seen:
            roots.append(resolved)
            seen.add(resolved)

    # 2. Workspace data directory if present (e.g. repo/data)
    repo_data = (SCRIPTS_DIR.parent / "data").resolve()
    if repo_data.exists() and repo_data not in seen:
        roots.append(repo_data)
        seen.add(repo_data)

    return roots


def generate_clip_id(clips_json_path: Path, clip_filename: str) -> str:
    """Generate a stable, unique ID for a clip based on its canonical path and filename."""
    norm_path = str(clips_json_path.resolve()).replace("\\", "/")
    key = f"{norm_path}::{clip_filename}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def default_upload_status() -> Dict[str, Any]:
    """Default upload tracking status for each platform."""
    return {
        "youtube": {
          "status": "not_uploaded",  # not_uploaded | in_progress | published | failed
          "video_id": None,
          "url": None,
          "uploaded_at": None,
          "error": None,
        },
        "instagram": {
          "status": "not_uploaded",
          "media_id": None,
          "url": None,
          "uploaded_at": None,
          "error": None,
        },
    }


def scan_clips() -> List[Dict[str, Any]]:
    """Scan configured data directories for clips.json and return structured stream items."""
    roots = get_configured_data_roots()
    streams: List[Dict[str, Any]] = []
    seen_json_paths: set = set()

    for root in roots:
        # Find all clips.json in the data directory
        for json_path in sorted(root.glob("**/clips.json"), reverse=True):
            resolved_path = json_path.resolve()
            if resolved_path in seen_json_paths:
                continue
            seen_json_paths.add(resolved_path)

            try:
                data = json.loads(resolved_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            folder_dir = resolved_path.parent
            source = data.get("source", {})
            covered = data.get("covered", [0.0, 0.0])
            raw_clips = data.get("clips", [])

            processed_clips = []
            checks_dir = folder_dir / "checks"

            for raw_clip in raw_clips:
                clip_filename = raw_clip.get("file", "")
                if not clip_filename:
                    continue

                video_path = folder_dir / clip_filename
                stem = Path(clip_filename).stem
                check_image_path = checks_dir / f"{stem}.jpg"

                clip_id = generate_clip_id(resolved_path, clip_filename)

                # Ensure upload status tracking exists
                uploads = raw_clip.get("uploads")
                if not isinstance(uploads, dict):
                    uploads = default_upload_status()
                else:
                    if "youtube" not in uploads:
                        uploads["youtube"] = default_upload_status()["youtube"]
                    if "instagram" not in uploads:
                        uploads["instagram"] = default_upload_status()["instagram"]

                processed_clip = {
                    "id": clip_id,
                    "file": clip_filename,
                    "video_exists": video_path.exists(),
                    "video_size_bytes": video_path.stat().st_size if video_path.exists() else 0,
                    "check_image_exists": check_image_path.exists(),
                    "title": raw_clip.get("title", ""),
                    "caption": raw_clip.get("caption", ""),
                    "hashtags": raw_clip.get("hashtags", []),
                    "type": raw_clip.get("type", "clip"),
                    "score": raw_clip.get("score", 0),
                    "why": raw_clip.get("why", ""),
                    "look": raw_clip.get("look", "stack"),
                    "start": raw_clip.get("start", 0.0),
                    "end": raw_clip.get("end", 0.0),
                    "seconds": raw_clip.get("seconds", 0.0),
                    "sync": raw_clip.get("sync", 1.0),
                    "opening": raw_clip.get("opening", {}),
                    "sfx": raw_clip.get("sfx", []),
                    "uploads": uploads,
                    # Internal file references for API streaming
                    "_json_path": str(resolved_path),
                    "_video_path": str(video_path),
                    "_check_image_path": str(check_image_path) if check_image_path.exists() else None,
                    "_folder_dir": str(folder_dir),
                }
                processed_clips.append(processed_clip)

            if processed_clips:
                stream_entry = {
                    "id": hashlib.sha1(str(resolved_path).encode("utf-8")).hexdigest()[:12],
                    "title": source.get("title", folder_dir.name),
                    "name": source.get("name", "Unknown Creator"),
                    "url": source.get("url", ""),
                    "topic": source.get("topic", ""),
                    "focus": source.get("focus"),
                    "covered": covered,
                    "folder": str(folder_dir),
                    "clips_json_path": str(resolved_path),
                    "clips": processed_clips,
                }
                streams.append(stream_entry)

    return streams


def get_clip_by_id(clip_id: str) -> Optional[Dict[str, Any]]:
    """Look up a clip by its unique ID."""
    for stream in scan_clips():
        for clip in stream["clips"]:
            if clip["id"] == clip_id:
                return clip
    return None
