"""Safe storage and backup manager for clip metadata.

Creates backups before modifying clips.json and uses atomic writes.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


def backup_clips_json(clips_json_path: Path) -> Path:
    """Create a backup of clips.json before any modifications."""
    bak_path = clips_json_path.with_suffix(".json.bak")
    shutil.copy2(clips_json_path, bak_path)
    return bak_path


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Perform a safe atomic write to a JSON file via a temporary file in the same directory."""
    path = Path(path)
    tmp_path = path.with_suffix(".json.tmp")
    
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    # Atomically replace destination
    os.replace(tmp_path, path)


def save_clip_metadata(
    clips_json_path: str,
    clip_filename: str,
    title: Optional[str] = None,
    caption: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
    uploads: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update metadata for a specific clip in clips.json.
    
    Creates a backup first and performs an atomic write.
    """
    json_path = Path(clips_json_path).resolve()
    if not json_path.exists():
        raise FileNotFoundError(f"clips.json not found at {json_path}")

    # Read current data
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    clips = data.get("clips", [])
    target_clip = None

    for clip in clips:
        if clip.get("file") == clip_filename:
            target_clip = clip
            break

    if target_clip is None:
        raise ValueError(f"Clip '{clip_filename}' not found in {json_path}")

    # Create backup before modification
    backup_clips_json(json_path)

    # Apply updates
    if title is not None:
        target_clip["title"] = title.strip()
    if caption is not None:
        target_clip["caption"] = caption.strip()
    if hashtags is not None:
        # Normalize hashtags list: clean and prefix with '#' if missing
        cleaned_tags = []
        for tag in hashtags:
            clean = tag.strip().lstrip("#")
            if clean:
                cleaned_tags.append(f"#{clean}")
        target_clip["hashtags"] = cleaned_tags
    if uploads is not None:
        target_clip["uploads"] = uploads

    # Atomic write back to clips.json
    atomic_write_json(json_path, data)

    # Also update POSTING.md if present
    update_posting_sheet(json_path.parent, data)

    return target_clip


def update_clip_upload_status(
    clips_json_path: str,
    clip_filename: str,
    platform: str,
    upload_status_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """Atomically update upload status for a specific platform in clips.json.
    
    Creates a backup first.
    """
    json_path = Path(clips_json_path).resolve()
    if not json_path.exists():
        raise FileNotFoundError(f"clips.json not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_clip = None
    for clip in data.get("clips", []):
        if clip.get("file") == clip_filename:
            target_clip = clip
            break

    if target_clip is None:
        raise ValueError(f"Clip '{clip_filename}' not found in {json_path}")

    # Create backup before modification
    backup_clips_json(json_path)

    # Ensure uploads dict exists
    if "uploads" not in target_clip or not isinstance(target_clip["uploads"], dict):
        target_clip["uploads"] = {}

    target_clip["uploads"][platform] = upload_status_dict

    # Atomic write back to clips.json
    atomic_write_json(json_path, data)

    return target_clip


def update_posting_sheet(folder_dir: Path, data: Dict[str, Any]) -> None:
    """Synchronize POSTING.md with the updated clips.json metadata if POSTING.md exists."""
    posting_md = folder_dir / "POSTING.md"
    if not posting_md.exists():
        return

    source = data.get("source", {})
    clips = data.get("clips", [])
    covered = data.get("covered", [0.0, 0.0])

    def clock(seconds: float) -> str:
        s = int(seconds)
        h, m, sec = s // 3600, (s % 3600) // 60, s % 60
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    lines = [
        f"# {source.get('name', 'Streamer')}: {source.get('title', 'Stream')}",
        "",
        f"Source: {source.get('url', '')}  ",
        f"Covered: {clock(covered[0])} to {clock(covered[1])}  ",
        "",
        "Watch every clip before posting. Only clip creators who allow it (many run paid clipping programs).",
        "",
    ]

    for c in clips:
        lines += [
            f"## {c.get('file', '')}",
            "",
            f"**{c.get('title') or ''}**  ",
            f"{c.get('type', 'clip')} · {c.get('seconds', 0):.0f}s · score {c.get('score', 0)} · from {clock(c.get('start', 0))} · look: {c.get('look', 'stack')}",
            "",
            "Caption to paste:",
            "",
            "```",
            (c.get("caption") or "") + "\n" + " ".join(c.get("hashtags") or []),
            "```",
            "",
            f"_Why it should work: {c.get('why') or ''}_",
            "",
            "---",
            "",
        ]

    try:
        posting_md.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
