"""Pytest configuration and shared fixtures for scripts/uploader test suite."""

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from uploader import auth_manager, discovery, instagram, server, storage


@pytest.fixture
def tmp_auth_dir(tmp_path):
    """Provide an isolated auth directory outside the repo for testing."""
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    orig_auth_dir = auth_manager.AUTH_DIR
    orig_cfg = auth_manager.CLIENT_CONFIG_FILE
    orig_tokens = auth_manager.TOKENS_FILE
    orig_ig_auth_dir = instagram.AUTH_DIR
    orig_ig_cfg = instagram.INSTAGRAM_CONFIG_FILE

    auth_manager.AUTH_DIR = auth_dir
    auth_manager.CLIENT_CONFIG_FILE = auth_dir / "youtube_client_config.json"
    auth_manager.TOKENS_FILE = auth_dir / "youtube_tokens.json"
    instagram.AUTH_DIR = auth_dir
    instagram.INSTAGRAM_CONFIG_FILE = auth_dir / "instagram_config.json"

    server.auth = auth_manager.AuthManager()
    server.ig_manager = instagram.InstagramManager(config_file=instagram.INSTAGRAM_CONFIG_FILE)

    yield auth_dir

    auth_manager.AUTH_DIR = orig_auth_dir
    auth_manager.CLIENT_CONFIG_FILE = orig_cfg
    auth_manager.TOKENS_FILE = orig_tokens
    instagram.AUTH_DIR = orig_ig_auth_dir
    instagram.INSTAGRAM_CONFIG_FILE = orig_ig_cfg
    server.auth = auth_manager.AuthManager()
    server.ig_manager = instagram.InstagramManager()


@pytest.fixture
def isolated_auth_dir(tmp_auth_dir):
    """Alias for isolated auth directory fixture."""
    return tmp_auth_dir


@pytest.fixture
def synthetic_fixture_data(tmp_path, tmp_auth_dir):
    """Create a synthetic stream and clip for discovery and dashboard HTTP tests."""
    stream_dir = tmp_path / "2026-11-23" / "test-topic" / "creator__test-vod"
    checks_dir = stream_dir / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)

    clip_file = stream_dir / "test_clip_01.mp4"
    clip_file.write_bytes(b"STREAMCLIPS_SYNTHETIC_MP4_BYTES_0123456789\n" * 64)

    check_img = checks_dir / "test_clip_01.jpg"
    check_img.write_bytes(b"STREAMCLIPS_SYNTHETIC_JPEG_PREVIEW_FRAME\n" * 8)

    clips_data = {
        "source": {
            "title": "Synthetic Test Stream",
            "name": "TestCreator",
            "url": "https://www.youtube.com/watch?v=TEST_VOD_123",
            "topic": "test-topic",
            "focus": None,
        },
        "covered": [0.0, 100.0],
        "clips": [
            {
                "file": "test_clip_01.mp4",
                "type": "skill",
                "title": "Original Synthetic Title",
                "caption": "Original Synthetic Caption",
                "hashtags": ["#test", "#gaming"],
                "score": 90,
                "why": "High energy test moment",
                "look": "stack",
                "start": 10.0,
                "end": 40.0,
                "seconds": 30.0,
                "sync": 1.0,
                "uploads": {
                    "youtube": {
                        "status": "not_uploaded",
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
                },
            }
        ],
    }
    clips_json = stream_dir / "clips.json"
    clips_json.write_text(json.dumps(clips_data, indent=2), encoding="utf-8")

    orig_get_roots = discovery.get_configured_data_roots
    discovery.get_configured_data_roots = lambda: [tmp_path]

    cid = discovery.generate_clip_id(clips_json, "test_clip_01.mp4")

    yield {"root": tmp_path, "clip_id": cid}

    discovery.get_configured_data_roots = orig_get_roots


@pytest.fixture
def fixture_root(synthetic_fixture_data):
    return synthetic_fixture_data["root"]


@pytest.fixture
def expected_clip_id(synthetic_fixture_data):
    return synthetic_fixture_data["clip_id"]


@pytest.fixture
def clip_id(synthetic_fixture_data):
    return synthetic_fixture_data["clip_id"]


@pytest.fixture
def test_clip_id(synthetic_fixture_data):
    return synthetic_fixture_data["clip_id"]
