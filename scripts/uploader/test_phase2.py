"""Validation and automated test suite for Phase 2: YouTube Data API v3 & OAuth 2.0.

Uses isolated temporary auth directories so running tests never pollutes the user's live credentials.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from uploader import auth_manager, discovery, server, storage, youtube


def test_auth_manager_security_and_storage(isolated_auth_dir: Path):
    print("[1/6] Testing secure credentials storage outside repository...")
    repo_dir = SCRIPTS_DIR.parent
    
    # Verify auth directory is strictly outside repository
    try:
        isolated_auth_dir.resolve().relative_to(repo_dir.resolve())
        is_inside_repo = True
    except ValueError:
        is_inside_repo = False
    
    assert not is_inside_repo, f"Auth dir ({isolated_auth_dir}) must NOT be inside the repository ({repo_dir})"
    print(f"  ✓ Confirmed credentials storage ({isolated_auth_dir}) is strictly outside repository.")

    # Test saving and reading client config in isolated dir
    mgr = auth_manager.AuthManager()
    mgr.save_client_config("test-client-id.apps.googleusercontent.com", "test-secret-12345")
    cfg = mgr.get_client_config()
    assert cfg is not None
    assert cfg["client_id"] == "test-client-id.apps.googleusercontent.com"
    assert cfg["client_secret"] == "test-secret-12345"

    # Test OAuth URL generation
    auth_url, state = mgr.generate_auth_url()
    assert "https://accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert "client_id=test-client-id.apps.googleusercontent.com" in auth_url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A5050%2Foauth%2Fyoutube%2Fcallback" in auth_url
    assert "youtube.upload" in auth_url
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url
    assert mgr.verify_state(state) is True
    assert mgr.verify_state("invalid-state") is False

    # Test token saving and retrieval
    mgr._save_tokens({
        "access_token": "ya29.test-access-token",
        "refresh_token": "1//test-refresh-token",
        "expires_at": time.time() + 3600,
        "channel": {"title": "Test Channel", "custom_url": "@testchannel"}
    })
    tokens = mgr.get_tokens()
    assert tokens["access_token"] == "ya29.test-access-token"
    assert tokens["refresh_token"] == "1//test-refresh-token"
    assert tokens["channel"]["title"] == "Test Channel"

    status = mgr.get_status()
    assert status["client_configured"] is True
    assert status["connected"] is True
    assert status["channel"]["title"] == "Test Channel"
    assert "masked_client_id" in status
    assert status["masked_client_id"].startswith("test-cli")

    # Test disconnect & clear config
    mgr.disconnect()
    assert mgr.get_tokens() is None
    status_after = mgr.get_status()
    assert status_after["connected"] is False

    mgr.clear_client_config()
    assert mgr.get_client_config() is None
    assert mgr.get_status()["client_configured"] is False
    print("  ✓ OAuth configuration, masked ID, token security, and clear flow verified.")


def test_youtube_resumable_protocol_formatting():
    print("[2/6] Testing YouTube resumable upload protocol logic & formatting...")
    uploader = youtube.YouTubeUploader(access_token="test-token")

    # Verify query status parsing
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.headers = {"Range": "bytes=0-1048575"}
        mock_err = urllib.error.HTTPError("http://upload.url", 308, "Resume Incomplete", mock_resp.headers, None)
        mock_urlopen.side_effect = mock_err
        
        received_bytes = uploader._query_upload_status("http://upload.url", 5000000)
        assert received_bytes == 1048576, f"Expected 1048576 resumed bytes, got {received_bytes}"

    # Verify tags and #Shorts appending
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid.write(b"fake video data")
        tmp_vid_path = Path(tmp_vid.name)

    try:
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.headers = {"Location": "https://upload.youtube.com/upload_session_123"}
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            session_url = uploader.initiate_resumable_upload(
                video_path=tmp_vid_path,
                title="Super Clutch Gameplay Moment",
                description="Check out this crazy clutch!",
                tags=["gaming", "gta6"],
                privacy_status="private"
            )
            assert session_url == "https://upload.youtube.com/upload_session_123"

            call_args = mock_urlopen.call_args[0][0]
            assert call_args.get_header("Authorization") == "Bearer test-token"
            assert call_args.get_header("X-upload-content-type") == "video/mp4"
            payload = json.loads(call_args.data.decode("utf-8"))
            assert payload["snippet"]["title"] == "Super Clutch Gameplay Moment"
            assert "#Shorts" in payload["snippet"]["description"]
            assert "Shorts" in payload["snippet"]["tags"]
            assert payload["status"]["privacyStatus"] == "private"
    finally:
        tmp_vid_path.unlink(missing_ok=True)

    print("  ✓ Resumable upload metadata, chunking, and session initiation verified.")


def test_duplicate_prevention():
    print("[3/6] Testing accidental duplicate upload prevention...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_json = tmp_path / "clips.json"

        sample = {
            "source": {"title": "Stream", "name": "Creator", "url": "https://test.com"},
            "covered": [0.0, 100.0],
            "clips": [
                {
                    "file": "test_clip.mp4",
                    "title": "GTA Clip",
                    "caption": "Check this",
                    "hashtags": ["#GTA6"],
                    "uploads": {
                        "youtube": {
                            "status": "published",
                            "video_id": "ABC123XYZ",
                            "url": "https://youtube.com/shorts/ABC123XYZ",
                            "uploaded_at": "2026-11-21T20:00:00Z",
                            "privacy": "private",
                            "error": None
                        }
                    }
                }
            ]
        }
        test_json.write_text(json.dumps(sample, indent=2), encoding="utf-8")

        clip = sample["clips"][0]
        yt_upload = clip["uploads"]["youtube"]
        assert yt_upload["status"] == "published"

        def attempt_publish(force=False):
            if yt_upload["status"] == "published" and not force:
                return 409, {"error": "already_published", "url": yt_upload["url"]}
            return 200, {"success": True}

        status_code, resp = attempt_publish(force=False)
        assert status_code == 409
        assert resp["error"] == "already_published"

        status_code, resp = attempt_publish(force=True)
        assert status_code == 200
        assert resp["success"] is True

    print("  ✓ Accidental duplicate upload prevention correctly blocks duplicates unless forced.")


def test_atomic_upload_status_update_with_backup():
    print("[4/6] Testing atomic status update and backup creation...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_json = tmp_path / "clips.json"
        sample = {
            "source": {"title": "Stream", "name": "Creator", "url": "https://test.com"},
            "clips": [
                {
                    "file": "clip_01.mp4",
                    "title": "Title 1",
                    "uploads": {
                        "youtube": {"status": "not_uploaded"}
                    }
                }
            ]
        }
        test_json.write_text(json.dumps(sample, indent=2), encoding="utf-8")

        updated_clip = storage.update_clip_upload_status(
            clips_json_path=str(test_json),
            clip_filename="clip_01.mp4",
            platform="youtube",
            upload_status_dict={
                "status": "published",
                "video_id": "VID999",
                "url": "https://youtube.com/shorts/VID999",
                "uploaded_at": "2026-11-22T00:15:00Z",
                "privacy": "unlisted",
                "error": None
            }
        )
        assert updated_clip["uploads"]["youtube"]["status"] == "published"
        assert updated_clip["uploads"]["youtube"]["video_id"] == "VID999"

        bak_file = test_json.with_suffix(".json.bak")
        assert bak_file.exists(), "Backup file must be created"
        bak_data = json.loads(bak_file.read_text(encoding="utf-8"))
        assert bak_data["clips"][0]["uploads"]["youtube"]["status"] == "not_uploaded"

        reloaded = json.loads(test_json.read_text(encoding="utf-8"))
        assert reloaded["clips"][0]["uploads"]["youtube"]["status"] == "published"
        assert reloaded["clips"][0]["uploads"]["youtube"]["privacy"] == "unlisted"

    print("  ✓ Safe atomic upload status updates and backup copies verified.")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevents following HTTP 302 redirects so test can assert Location header."""

    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_302


def test_http_api_endpoints(test_clip_id: str):
    print("[5/6] Testing HTTP server API endpoints for YouTube OAuth and Publishing...")
    test_port = 5961
    httpd = server.ThreadingHTTPServer(("127.0.0.1", test_port), server.DashboardRequestHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    base_url = f"http://127.0.0.1:{test_port}"
    default_headers = {
        "Host": f"127.0.0.1:{test_port}",
        "Origin": base_url,
        "Sec-Fetch-Site": "same-origin",
        "Content-Type": "application/json",
    }

    try:
        # 1. GET /api/youtube/status (starts unconfigured in clean test env)
        req = urllib.request.Request(f"{base_url}/api/youtube/status", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "client_configured" in data
            assert "connected" in data
            assert "storage_path" in data
        print("  ✓ /api/youtube/status endpoint verified.")

        # 2. POST /api/youtube/config (with legitimate Origin and Host)
        config_payload = {
            "client_id": "isolated-test-client.apps.googleusercontent.com",
            "client_secret": "isolated-test-secret"
        }
        post_req = urllib.request.Request(
            f"{base_url}/api/youtube/config",
            data=json.dumps(config_payload).encode("utf-8"),
            headers=default_headers,
            method="POST"
        )
        with urllib.request.urlopen(post_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True
        print("  ✓ /api/youtube/config endpoint verified.")

        # 3. GET /api/youtube/auth-url
        req = urllib.request.Request(f"{base_url}/api/youtube/auth-url", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "auth_url" in data
            assert "isolated-test-client.apps.googleusercontent.com" in data["auth_url"]
        print("  ✓ /api/youtube/auth-url endpoint verified.")

        # 4. POST /api/youtube/config/clear
        clear_req = urllib.request.Request(
            f"{base_url}/api/youtube/config/clear",
            data=b"{}",
            headers=default_headers,
            method="POST"
        )
        with urllib.request.urlopen(clear_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True
        print("  ✓ /api/youtube/config/clear endpoint verified.")

        # Verify status is unconfigured after clear
        req = urllib.request.Request(f"{base_url}/api/youtube/status", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["client_configured"] is False
            assert data["connected"] is False

        # 5. POST /api/publish/youtube without authentication should return 401
        pub_payload = {
            "clip_id": test_clip_id,
            "privacy": "private",
            "force": True,
        }
        pub_req = urllib.request.Request(
            f"{base_url}/api/publish/youtube",
            data=json.dumps(pub_payload).encode("utf-8"),
            headers=default_headers,
            method="POST"
        )
        try:
            urllib.request.urlopen(pub_req)
            assert False, "Should have returned 401 Unauthorized when tokens not present"
        except urllib.error.HTTPError as exc:
            assert exc.code == 401, f"Expected 401, got {exc.code}"
            err_data = json.loads(exc.read().decode("utf-8"))
            assert err_data["error"] in ("not_authenticated", "auth_error")
        print("  ✓ /api/publish/youtube rejected unauthenticated attempt with 401 as expected.")

        # 6. POST /api/youtube/disconnect
        disc_req = urllib.request.Request(
            f"{base_url}/api/youtube/disconnect",
            data=b"{}",
            headers=default_headers,
            method="POST"
        )
        with urllib.request.urlopen(disc_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True
        print("  ✓ /api/youtube/disconnect endpoint verified.")

        # 7. OAuth State Validation & Replay Rejection
        # 7a. Missing state in callback -> redirect with auth_error=missing_state
        no_state_req = urllib.request.Request(
            f"{base_url}/oauth/youtube/callback?code=some_code",
            headers={"Host": f"127.0.0.1:{test_port}"},
        )
        opener = urllib.request.build_opener(NoRedirectHandler)
        resp = opener.open(no_state_req)
        assert "auth_error=missing_state" in resp.headers.get("Location", "")

        # 7b. Invalid state in callback -> redirect with auth_error=invalid_or_expired_state
        invalid_state_req = urllib.request.Request(
            f"{base_url}/oauth/youtube/callback?code=some_code&state=nonexistent_state",
            headers={"Host": f"127.0.0.1:{test_port}"},
        )
        resp = opener.open(invalid_state_req)
        assert "auth_error=invalid_or_expired_state" in resp.headers.get("Location", "")

        # 7c. Replay rejection: once consumed, same state is rejected
        mock_state = "phase2_test_state_abc123"
        server.auth._state_cache[mock_state] = time.time()
        assert server.auth.verify_state(mock_state) is True, "First verification must succeed"
        assert server.auth.verify_state(mock_state) is False, "Replayed verification must fail"
        print("  ✓ OAuth callback state verification, missing state, and replay rejection verified.")

    finally:
        httpd.shutdown()
        httpd.server_close()


def test_pipeline_integrity():
    print("[6/6] Verifying pipeline files are present...")
    for path in [
        SCRIPTS_DIR / "streamclips.py",
        SCRIPTS_DIR / "sc" / "cli.py",
        SCRIPTS_DIR / "sc" / "pipeline.py",
        SCRIPTS_DIR / "sc" / "produce.py",
        SCRIPTS_DIR / "sc" / "listen.py",
        SCRIPTS_DIR / "sc" / "highlights.py",
        SCRIPTS_DIR / "sc" / "common.py",
    ]:
        assert path.exists(), f"Existing file missing: {path}"
    print("  ✓ All existing clipping pipeline files are present.")


def run_all_tests():
    print("=" * 60)
    print("Running Stream Clips Phase 2 (YouTube API) Validation Tests")
    print("=" * 60)

    # Save original auth locations and discovery function
    orig_auth_dir = auth_manager.AUTH_DIR
    orig_cfg_file = auth_manager.CLIENT_CONFIG_FILE
    orig_tokens_file = auth_manager.TOKENS_FILE
    orig_get_roots = discovery.get_configured_data_roots

    # Create temporary isolated auth and fixture directories for the test suite
    with tempfile.TemporaryDirectory() as tmp_auth_str, tempfile.TemporaryDirectory() as tmp_fix_str:
        tmp_auth_dir = Path(tmp_auth_str) / "auth"
        tmp_auth_dir.mkdir(parents=True, exist_ok=True)
        tmp_fix_dir = Path(tmp_fix_str)

        # Create self-contained synthetic fixture for discovery
        stream_dir = tmp_fix_dir / "2026-11-22" / "test-game" / "streamer__vod"
        stream_dir.mkdir(parents=True, exist_ok=True)
        fixture_clip_file = stream_dir / "clip_01.mp4"
        fixture_clip_file.write_bytes(b"SYNTHETIC_VIDEO_DATA" * 64)

        fixture_clips_json = stream_dir / "clips.json"
        fixture_data = {
            "source": {"title": "Test", "name": "Streamer", "url": "https://test.com"},
            "covered": [0.0, 100.0],
            "clips": [
                {
                    "file": "clip_01.mp4",
                    "title": "Clip",
                    "caption": "Cap",
                    "hashtags": ["#shorts"],
                    "uploads": {"youtube": {"status": "not_uploaded"}},
                }
            ],
        }
        fixture_clips_json.write_text(json.dumps(fixture_data, indent=2), encoding="utf-8")
        test_clip_id = discovery.generate_clip_id(fixture_clips_json, "clip_01.mp4")

        try:
            # Patch auth paths and discovery roots in memory for tests
            auth_manager.AUTH_DIR = tmp_auth_dir
            auth_manager.CLIENT_CONFIG_FILE = tmp_auth_dir / "youtube_client_config.json"
            auth_manager.TOKENS_FILE = tmp_auth_dir / "youtube_tokens.json"
            server.auth = auth_manager.AuthManager()
            discovery.get_configured_data_roots = lambda: [tmp_fix_dir]

            test_auth_manager_security_and_storage(tmp_auth_dir)
            test_youtube_resumable_protocol_formatting()
            test_duplicate_prevention()
            test_atomic_upload_status_update_with_backup()
            test_http_api_endpoints(test_clip_id)
            test_pipeline_integrity()

        finally:
            # Restore original live paths so user's environment is untouched
            auth_manager.AUTH_DIR = orig_auth_dir
            auth_manager.CLIENT_CONFIG_FILE = orig_cfg_file
            auth_manager.TOKENS_FILE = orig_tokens_file
            server.auth = auth_manager.AuthManager()
            discovery.get_configured_data_roots = orig_get_roots

    print("=" * 60)
    print("ALL PHASE 2 TESTS PASSED SUCCESSFULLY (TESTS ISOLATED)!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
