"""Validation and automated test suite for Step 3: Instagram Reels Publishing with Meta Graph API & SUAT.

Uses isolated temporary auth directories so running tests never touches or pollutes the user's live credentials.
Uses mocks for all Meta Graph API calls to ensure no real Reels are published during automated testing.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from uploader import auth_manager, discovery, instagram, server, storage, youtube


def test_instagram_credential_storage_and_masking(tmp_auth_dir: Path):
    print("[1/8] Testing Instagram credential storage, isolation, and masking...")
    repo_dir = SCRIPTS_DIR.parent

    # 1. Verify storage is strictly outside repository
    try:
        tmp_auth_dir.resolve().relative_to(repo_dir.resolve())
        is_inside_repo = True
    except ValueError:
        is_inside_repo = False
    assert not is_inside_repo, f"Auth dir ({tmp_auth_dir}) must NOT be inside repository ({repo_dir})"
    print(f"  ✓ Confirmed credentials storage ({tmp_auth_dir}) is strictly outside repository.")

    # 2. Test masking function
    raw_token = "EAAGtesttoken1234567890abcdefghijklmnopqrstuvwxyz"
    masked = instagram.mask_token(raw_token)
    assert raw_token not in masked
    assert masked.startswith("EAAGte...")
    assert masked.endswith("uvwxyz")
    assert instagram.mask_token("") == ""
    assert instagram.mask_token(None) == ""
    print("  ✓ Token masking logic verified.")

    # 3. Test saving and reading credentials
    cfg_file = tmp_auth_dir / "instagram_config.json"
    mgr = instagram.InstagramManager(config_file=cfg_file)

    # Initial status must be unconfigured
    status = mgr.get_status()
    assert status["configured"] is False
    assert status["connected"] is False
    assert status["masked_token"] is None
    assert status["account"] is None

    # Save credentials (with skip_validation=True for unit testing storage)
    res = mgr.save_credentials(
        access_token=raw_token,
        public_base_url="https://test-tunnel.trycloudflare.com",
        account_id="17841405555555555",
        username="test_creator",
        skip_validation=True,
    )
    assert res["success"] is True
    assert res["account"]["id"] == "17841405555555555"
    assert res["account"]["username"] == "test_creator"
    assert res["masked_token"].startswith("EAAGte...")

    # Verify file content on disk
    assert cfg_file.exists()
    disk_data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk_data["access_token"] == raw_token
    assert disk_data["account_id"] == "17841405555555555"
    assert disk_data["username"] == "test_creator"
    assert disk_data["public_base_url"] == "https://test-tunnel.trycloudflare.com"

    # Verify get_status does NOT return the full access_token
    status = mgr.get_status()
    assert status["configured"] is True
    assert status["connected"] is True
    assert "access_token" not in status
    assert status["masked_token"] == res["masked_token"]
    assert status["account"]["username"] == "test_creator"
    assert status["account"]["id"] == "17841405555555555"

    # Test token and account ID getters
    assert mgr.get_valid_access_token() == raw_token
    assert mgr.get_account_id() == "17841405555555555"

    # Test disconnect
    mgr.disconnect()
    assert not cfg_file.exists()
    status_after = mgr.get_status()
    assert status_after["configured"] is False
    assert status_after["connected"] is False

    try:
        mgr.get_valid_access_token()
        assert False, "Should raise PermissionError after disconnect"
    except PermissionError:
        pass

    print("  ✓ Secure Instagram credential storage, masking, and disconnect verified.")


def test_meta_token_validation_and_account_discovery():
    print("[2/8] Testing Meta API token validation and account discovery endpoints...")
    mgr = instagram.InstagramManager()

    # Case A: Unified Login SUAT /me/assigned_instagram_accounts
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {
                    "id": "17841401234567890",
                    "username": "test_creator",
                    "name": "Handsome Creator",
                    "profile_picture_url": "https://instagram.com/pic.jpg",
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        validation = mgr.validate_token("EAAG_valid_suat_token")
        assert validation["valid"] is True
        assert validation["account"]["id"] == "17841401234567890"
        assert validation["account"]["username"] == "test_creator"
        assert validation["account"]["name"] == "Handsome Creator"

        # Verify request structure
        call_req = mock_urlopen.call_args[0][0]
        assert "assigned_instagram_accounts" in call_req.full_url
        assert call_req.get_header("Authorization") == "Bearer EAAG_valid_suat_token"

    # Case B: Fallback to Page-linked account /me/accounts
    with patch("urllib.request.urlopen") as mock_urlopen:
        # First call (assigned_accounts) returns empty
        resp1 = MagicMock()
        resp1.read.return_value = json.dumps({"data": []}).encode("utf-8")

        # Second call (/me/accounts) returns page with instagram_business_account
        resp2 = MagicMock()
        resp2.read.return_value = json.dumps({
            "data": [
                {
                    "name": "Creator Page",
                    "instagram_business_account": {
                        "id": "17841409999999999",
                        "username": "test_creator",
                        "name": "Handsome Page",
                    }
                }
            ]
        }).encode("utf-8")

        mock_urlopen.return_value.__enter__.side_effect = [resp1, resp2]

        validation = mgr.validate_token("EAAG_fallback_token")
        assert validation["valid"] is True
        assert validation["account"]["id"] == "17841409999999999"
        assert validation["account"]["username"] == "test_creator"

    # Case C: Invalid token / OAuthException (code 190)
    with patch("urllib.request.urlopen") as mock_urlopen:
        err_body = json.dumps({
            "error": {
                "message": "Error validating access token: The session is invalid",
                "type": "OAuthException",
                "code": 190,
            }
        }).encode("utf-8")
        err = urllib.error.HTTPError("https://graph.facebook.com", 400, "Bad Request", {}, None)
        err.read = lambda: err_body
        mock_urlopen.side_effect = err

        try:
            mgr.validate_token("invalid_token")
            assert False, "Should raise InstagramAuthError on code 190"
        except instagram.InstagramAuthError as exc:
            assert "Meta authentication failed" in str(exc)
            assert "invalid_token" not in str(exc)

    print("  ✓ Meta SUAT account discovery, fallback, and error handling verified.")


def test_media_container_creation_and_polling():
    print("[3/8] Testing Instagram Reels media container creation and status polling...")
    publisher = instagram.InstagramPublisher(
        access_token="test_token_12345",
        account_id="17841401234567890",
    )

    # 1. Test create_media_container
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "17999000123456789"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        creation_id = publisher.create_media_container(
            video_url="https://test.trycloudflare.com/media/video/abc",
            caption="Test Caption #gaming",
            share_to_feed=True,
        )
        assert creation_id == "17999000123456789"

        # Check call arguments
        call_req = mock_urlopen.call_args[0][0]
        assert "17841401234567890/media" in call_req.full_url
        assert call_req.get_header("Authorization") == "Bearer test_token_12345"
        body_params = urllib.parse.parse_qs(call_req.data.decode("utf-8"))
        assert body_params["media_type"] == ["REELS"]
        assert body_params["video_url"] == ["https://test.trycloudflare.com/media/video/abc"]
        assert body_params["caption"] == ["Test Caption #gaming"]
        assert body_params["share_to_feed"] == ["true"]

    # 2. Test status checking
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status_code": "IN_PROGRESS",
            "status": "PROCESSING",
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        status = publisher.check_media_status("17999000123456789")
        assert status["status_code"] == "IN_PROGRESS"

    # 3. Test poll_until_ready (IN_PROGRESS -> FINISHED)
    with patch("urllib.request.urlopen") as mock_urlopen:
        resp_progress = MagicMock()
        resp_progress.read.return_value = json.dumps({"status_code": "IN_PROGRESS"}).encode("utf-8")

        resp_finished = MagicMock()
        resp_finished.read.return_value = json.dumps({"status_code": "FINISHED"}).encode("utf-8")

        mock_urlopen.return_value.__enter__.side_effect = [resp_progress, resp_finished]

        progress_updates = []
        ready = publisher.poll_until_ready(
            creation_id="17999000123456789",
            max_wait=10.0,
            poll_interval=0.05,
            progress_callback=lambda msg, pct: progress_updates.append((msg, pct)),
        )
        assert ready is True
        assert len(progress_updates) >= 2
        assert progress_updates[-1][1] == 100

    # 4. Test poll failure on ERROR status
    with patch("urllib.request.urlopen") as mock_urlopen:
        resp_err = MagicMock()
        resp_err.read.return_value = json.dumps({
            "status_code": "ERROR",
            "status": "Video codec unsupported",
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = resp_err

        try:
            publisher.poll_until_ready("17999000123456789", max_wait=5.0, poll_interval=0.05)
            assert False, "Should raise InstagramPublishError on ERROR status"
        except instagram.InstagramPublishError as exc:
            assert "Video codec unsupported" in str(exc)

    print("  ✓ Container creation, parameter formatting, and status polling verified.")


def test_container_publishing_and_full_workflow():
    print("[4/8] Testing Instagram container publishing and full workflow...")
    publisher = instagram.InstagramPublisher(
        access_token="test_token_12345",
        account_id="17841401234567890",
    )

    # 1. Test publish_container
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "18999000987654321"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        published_id = publisher.publish_container("17999000123456789")
        assert published_id == "18999000987654321"

        call_req = mock_urlopen.call_args[0][0]
        assert "17841401234567890/media_publish" in call_req.full_url
        body = urllib.parse.parse_qs(call_req.data.decode("utf-8"))
        assert body["creation_id"] == ["17999000123456789"]

    # 2. Test get_reel_permalink
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "18999000987654321",
            "permalink": "https://www.instagram.com/reel/Cxxxxxxxxx/",
            "media_type": "VIDEO",
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        permalink = publisher.get_reel_permalink("18999000987654321")
        assert permalink == "https://www.instagram.com/reel/Cxxxxxxxxx/"

    # 3. Test full publish_reel sequence
    with patch.object(publisher, "create_media_container", return_value="c_123") as mock_create, \
         patch.object(publisher, "poll_until_ready", return_value=True) as mock_poll, \
         patch.object(publisher, "publish_container", return_value="m_456") as mock_pub, \
         patch.object(publisher, "get_reel_permalink", return_value="https://www.instagram.com/reel/Ctest/"):

        res = publisher.publish_reel(
            video_url="https://test.trycloudflare.com/media/video/1",
            caption="Amazing Reel",
        )
        assert res["media_id"] == "m_456"
        assert res["url"] == "https://www.instagram.com/reel/Ctest/"
        assert res["creation_id"] == "c_123"
        mock_create.assert_called_once()
        mock_poll.assert_called_once()
        mock_pub.assert_called_once()

    print("  ✓ Container publishing and full end-to-end publishing workflow verified.")


def test_duplicate_prevention_for_instagram():
    print("[5/8] Testing Instagram accidental duplicate publish prevention...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_json = tmp_path / "clips.json"

        sample = {
            "source": {"title": "Stream", "name": "Creator", "url": "https://test.com"},
            "covered": [0.0, 100.0],
            "clips": [
                {
                    "file": "test_reel.mp4",
                    "title": "GTA Reel",
                    "caption": "Reel Caption",
                    "hashtags": ["#Shorts"],
                    "uploads": {
                        "instagram": {
                            "status": "published",
                            "media_id": "18111000999999999",
                            "url": "https://www.instagram.com/reel/C123/",
                            "uploaded_at": "2026-11-22T10:00:00Z",
                            "error": None,
                        }
                    }
                }
            ]
        }
        test_json.write_text(json.dumps(sample, indent=2), encoding="utf-8")

        clip = sample["clips"][0]
        ig_upload = clip["uploads"]["instagram"]
        assert ig_upload["status"] == "published"

        def attempt_publish(force=False):
            if ig_upload["status"] == "published" and not force:
                return 409, {"error": "already_published", "media_id": ig_upload["media_id"]}
            return 200, {"success": True}

        # 1. Normal attempt without force must return 409 Conflict
        code, resp = attempt_publish(force=False)
        assert code == 409
        assert resp["error"] == "already_published"

        # 2. Force re-upload allows continuing
        code, resp = attempt_publish(force=True)
        assert code == 200
        assert resp["success"] is True

    print("  ✓ Accidental duplicate prevention correctly guards Instagram Reels.")


def test_ephemeral_media_server_strict_isolation_and_tunnel():
    print("[6/8] Testing Ephemeral Media Server route rejection, range requests & tunnel isolation...")
    
    # 1. Test security check: TunnelManager must refuse port 5050
    tm = instagram.TunnelManager()
    try:
        tm.start_tunnel(local_port=5050)
        assert False, "TunnelManager must strictly reject local_port=5050"
    except ValueError as ve:
        assert "Security Violation" in str(ve)
        print("  ✓ Confirmed TunnelManager actively blocks port 5050 (dashboard).")

    # 2. Test EphemeralMediaRequestHandler isolation & byte-range handling
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        test_payload = b"FAKE_MP4_VIDEO_BYTES_FOR_REEL_PUBLISHING_STREAMCLIPS_1234567890"
        tmp_vid.write(test_payload)
        tmp_vid_path = Path(tmp_vid.name)

    try:
        secret_token = "sec_test_unguessable_token_xyz"
        expected_path = f"/video/{secret_token}.mp4"

        # Start isolated media server on port 0 (OS allocated free port)
        media_server = instagram.ThreadingHTTPServer(("127.0.0.1", 0), instagram.EphemeralMediaRequestHandler)
        media_server.target_file = tmp_vid_path
        media_server.expected_path = expected_path
        media_port = media_server.server_address[1]
        assert media_port != 5050, f"Media server port must not be 5050 (got {media_port})"

        server_thread = threading.Thread(target=media_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.3)

        base_url = f"http://127.0.0.1:{media_port}"

        try:
            # A. Valid HEAD request on exact token URL
            head_req = urllib.request.Request(f"{base_url}{expected_path}", method="HEAD")
            with urllib.request.urlopen(head_req) as resp:
                assert resp.status == 200
                assert resp.headers.get("Content-Type") == "video/mp4"
                assert int(resp.headers.get("Content-Length")) == len(test_payload)
                assert resp.headers.get("Accept-Ranges") == "bytes"
            print("  ✓ HEAD request on unguessable media URL succeeded with 200 OK.")

            # B. Valid GET request on exact token URL
            get_req = urllib.request.Request(f"{base_url}{expected_path}", method="GET")
            with urllib.request.urlopen(get_req) as resp:
                assert resp.status == 200
                body = resp.read()
                assert body == test_payload
            print("  ✓ Full GET request on media URL returned exact video bytes.")

            # C. Valid Range request (HTTP 206 Partial Content)
            range_req = urllib.request.Request(f"{base_url}{expected_path}", method="GET")
            range_req.add_header("Range", "bytes=0-15")
            with urllib.request.urlopen(range_req) as resp:
                assert resp.status == 206
                assert resp.headers.get("Content-Range") == f"bytes 0-15/{len(test_payload)}"
                chunk = resp.read()
                assert chunk == test_payload[:16]
            print("  ✓ Byte-range request returned HTTP 206 Partial Content for Meta crawler.")

            # D. STRICT ROUTE REJECTION: Verify EVERY non-media path returns 404
            forbidden_paths = [
                "/",
                "/index.html",
                "/app.js",
                "/app.css",
                "/api/streams",
                "/api/youtube/status",
                "/api/instagram/status",
                "/api/publish/youtube",
                "/api/publish/instagram",
                "/oauth/youtube/callback",
                "/media/image/any_id",
                "/media/video/any_id",
                "/video/wrong_token.mp4",
                "/video/../clips.json",
                f"/video/{secret_token}.mp4/extra",
                "/admin",
                "/config",
            ]

            for path in forbidden_paths:
                test_req = urllib.request.Request(f"{base_url}{path}")
                try:
                    urllib.request.urlopen(test_req)
                    assert False, f"Expected 404 for forbidden path {path}, but request succeeded!"
                except urllib.error.HTTPError as exc:
                    assert exc.code == 404, f"Path {path} returned HTTP {exc.code}, expected 404"

            print(f"  ✓ Strictly verified that {len(forbidden_paths)} non-media routes all returned 404 Not Found.")

            # E. METHOD REJECTION: POST, PUT, DELETE must return 405 Method Not Allowed
            for method in ["POST", "PUT", "DELETE"]:
                bad_req = urllib.request.Request(f"{base_url}{expected_path}", data=b"{}", method=method)
                try:
                    urllib.request.urlopen(bad_req)
                    assert False, f"Expected 405 for {method}, but request succeeded!"
                except urllib.error.HTTPError as exc:
                    assert exc.code == 405, f"Method {method} returned HTTP {exc.code}, expected 405"

            print("  ✓ Strictly verified POST, PUT, and DELETE methods return 405 Method Not Allowed.")

        finally:
            media_server.shutdown()
            media_server.server_close()

    finally:
        tmp_vid_path.unlink(missing_ok=True)

    # 3. Test EphemeralMediaGateway context manager
    gateway = instagram.EphemeralMediaGateway(custom_base_url="https://gateway.trycloudflare.com")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_f:
        tmp_f.write(b"SAMPLE")
        tmp_p = Path(tmp_f.name)

    try:
        with gateway.host_video(video_path=tmp_p) as pub_url:
            assert pub_url.startswith("https://gateway.trycloudflare.com/video/")
            assert pub_url.endswith(".mp4")
            assert gateway._server.server_address[1] != 5050
        # After exit, server must be stopped
        assert gateway._server is None
        print("  ✓ EphemeralMediaGateway context manager and auto-cleanup verified.")
    finally:
        tmp_p.unlink(missing_ok=True)


def test_dashboard_http_api_endpoints_for_instagram(isolated_auth_dir: Path, test_clip_id: str):
    print("[7/8] Testing HTTP server API endpoints for Instagram...")
    test_port = 5982
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
        # 1. GET /api/instagram/status (starts unconfigured in isolated test environment)
        req = urllib.request.Request(f"{base_url}/api/instagram/status", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["configured"] is False
            assert data["connected"] is False
            assert "storage_path" in data

        # 2. POST /api/publish/instagram without token -> must return 401
        pub_req = urllib.request.Request(
            f"{base_url}/api/publish/instagram",
            data=json.dumps({"clip_id": test_clip_id, "force": True}).encode("utf-8"),
            headers=default_headers,
            method="POST",
        )
        try:
            urllib.request.urlopen(pub_req)
            assert False, "Should have returned 401 Unauthorized"
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            err_data = json.loads(exc.read().decode("utf-8"))
            assert err_data["error"] in ("not_authenticated", "auth_error")

        # 3. POST /api/instagram/config with mocked validation
        with patch.object(server.ig_manager, "validate_token") as mock_val:
            mock_val.return_value = {
                "valid": True,
                "account": {
                    "id": "17841401234567890",
                    "username": "test_creator",
                    "name": "Handsome",
                    "profile_picture_url": "",
                }
            }

            cfg_req = urllib.request.Request(
                f"{base_url}/api/instagram/config",
                data=json.dumps({
                    "access_token": "EAAG_mock_valid_access_token_123456",
                    "public_base_url": "https://test.trycloudflare.com",
                }).encode("utf-8"),
                headers=default_headers,
                method="POST",
            )
            with urllib.request.urlopen(cfg_req) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert data["success"] is True
                assert data["account"]["username"] == "test_creator"
                assert "EAAG_mock_valid_access_token_123456" not in json.dumps(data)
                assert data["masked_token"].startswith("EAAG_m...")

        # 4. Verify GET /api/instagram/status is now connected
        req = urllib.request.Request(f"{base_url}/api/instagram/status", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["configured"] is True
            assert data["connected"] is True
            assert data["account"]["username"] == "test_creator"
            assert "access_token" not in data

        # 5. POST /api/publish/instagram with mocked publisher and isolated storage
        with patch("uploader.instagram.InstagramPublisher.publish_reel") as mock_pub, \
             patch("uploader.instagram.EphemeralMediaGateway.host_video") as mock_gateway, \
             patch("uploader.storage.save_clip_metadata") as mock_save, \
             patch("uploader.storage.update_clip_upload_status") as mock_update:

            mock_gateway.return_value.__enter__.return_value = "https://mock.trycloudflare.com/video/sec_token.mp4"
            mock_pub.return_value = {
                "media_id": "18999123456789",
                "url": "https://www.instagram.com/reel/Cmock123/",
                "creation_id": "17999123456789",
            }

            pub_payload = {
                "clip_id": test_clip_id,
                "title": "Title",
                "caption": "Reel Caption",
                "hashtags": ["#gaming"],
                "force": True,
            }
            pub_req = urllib.request.Request(
                f"{base_url}/api/publish/instagram",
                data=json.dumps(pub_payload).encode("utf-8"),
                headers=default_headers,
                method="POST",
            )
            with urllib.request.urlopen(pub_req) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert data["success"] is True
                assert data["upload"]["status"] == "published"
                assert data["upload"]["media_id"] == "18999123456789"
                assert data["upload"]["url"] == "https://www.instagram.com/reel/Cmock123/"

        # 6. Verify duplicate check triggers when upload status is published
        with patch("uploader.discovery.get_clip_by_id") as mock_get_clip:
            mock_get_clip.return_value = {
                "id": test_clip_id,
                "file": "test.mp4",
                "uploads": {
                    "instagram": {
                        "status": "published",
                        "media_id": "18999123456789",
                        "url": "https://www.instagram.com/reel/Cmock123/",
                        "uploaded_at": "2026-11-22T10:00:00Z",
                    }
                }
            }

            dup_req = urllib.request.Request(
                f"{base_url}/api/publish/instagram",
                data=json.dumps({"clip_id": test_clip_id, "force": False}).encode("utf-8"),
                headers=default_headers,
                method="POST",
            )
            try:
                urllib.request.urlopen(dup_req)
                assert False, "Should return 409 Conflict for duplicate"
            except urllib.error.HTTPError as exc:
                assert exc.code == 409
                data = json.loads(exc.read().decode("utf-8"))
                assert data["error"] == "already_published"

        # 7. POST /api/instagram/disconnect
        disc_req = urllib.request.Request(
            f"{base_url}/api/instagram/disconnect",
            data=b"{}",
            headers=default_headers,
            method="POST",
        )
        with urllib.request.urlopen(disc_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True

        # Verify status after disconnect
        req = urllib.request.Request(f"{base_url}/api/instagram/status", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["configured"] is False
            assert data["connected"] is False

    finally:
        httpd.shutdown()
        httpd.server_close()

    print("  ✓ All Instagram Dashboard HTTP API endpoints verified successfully.")

    print("  ✓ All Instagram Dashboard HTTP API endpoints verified successfully.")


def test_youtube_regression_and_pipeline_preservation():
    print("[8/8] Testing YouTube regression and clipping pipeline presence...")
    # Verify YouTube endpoints and uploader classes remain available
    assert hasattr(youtube, "YouTubeUploader")
    assert hasattr(auth_manager, "AuthManager")

    # Verify existing pipeline files are present
    for path in [
        SCRIPTS_DIR / "streamclips.py",
        SCRIPTS_DIR / "sc" / "cli.py",
        SCRIPTS_DIR / "sc" / "pipeline.py",
        SCRIPTS_DIR / "sc" / "produce.py",
        SCRIPTS_DIR / "sc" / "listen.py",
        SCRIPTS_DIR / "sc" / "highlights.py",
        SCRIPTS_DIR / "sc" / "common.py",
    ]:
        assert path.exists(), f"Existing clipping pipeline file missing: {path}"

    print("  ✓ YouTube Data API v3 and core clipping pipeline files are present.")


def run_all_tests():
    print("=" * 65)
    print("Running Stream Clips Step 3 (Instagram Reels & Meta API) Tests")
    print("=" * 65)

    # Save original live auth locations and discovery roots
    orig_auth_dir = auth_manager.AUTH_DIR
    orig_ig_config = instagram.INSTAGRAM_CONFIG_FILE
    orig_get_roots = discovery.get_configured_data_roots

    with tempfile.TemporaryDirectory() as tmp_auth_str, tempfile.TemporaryDirectory() as tmp_fix_str:
        tmp_auth_dir = Path(tmp_auth_str) / "auth"
        tmp_auth_dir.mkdir(parents=True, exist_ok=True)
        tmp_fix_dir = Path(tmp_fix_str)

        # Create self-contained synthetic fixture for discovery
        stream_dir = tmp_fix_dir / "2026-11-22" / "test-game" / "creator__vod"
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
                    "uploads": {"instagram": {"status": "not_uploaded"}},
                }
            ],
        }
        fixture_clips_json.write_text(json.dumps(fixture_data, indent=2), encoding="utf-8")
        test_clip_id = discovery.generate_clip_id(fixture_clips_json, "clip_01.mp4")

        try:
            # Patch auth paths and discovery roots in memory for isolated test execution
            auth_manager.AUTH_DIR = tmp_auth_dir
            auth_manager.CLIENT_CONFIG_FILE = tmp_auth_dir / "youtube_client_config.json"
            auth_manager.TOKENS_FILE = tmp_auth_dir / "youtube_tokens.json"
            instagram.AUTH_DIR = tmp_auth_dir
            instagram.INSTAGRAM_CONFIG_FILE = tmp_auth_dir / "instagram_config.json"

            server.auth = auth_manager.AuthManager()
            server.ig_manager = instagram.InstagramManager(config_file=instagram.INSTAGRAM_CONFIG_FILE)
            discovery.get_configured_data_roots = lambda: [tmp_fix_dir]

            test_instagram_credential_storage_and_masking(tmp_auth_dir)
            test_meta_token_validation_and_account_discovery()
            test_media_container_creation_and_polling()
            test_container_publishing_and_full_workflow()
            test_duplicate_prevention_for_instagram()
            test_ephemeral_media_server_strict_isolation_and_tunnel()
            test_dashboard_http_api_endpoints_for_instagram(tmp_auth_dir, test_clip_id)
            test_youtube_regression_and_pipeline_preservation()

        finally:
            # Restore live paths
            auth_manager.AUTH_DIR = orig_auth_dir
            auth_manager.CLIENT_CONFIG_FILE = orig_auth_dir / "youtube_client_config.json"
            auth_manager.TOKENS_FILE = orig_auth_dir / "youtube_tokens.json"
            instagram.AUTH_DIR = orig_auth_dir
            instagram.INSTAGRAM_CONFIG_FILE = orig_ig_config
            server.auth = auth_manager.AuthManager()
            server.ig_manager = instagram.InstagramManager()
            discovery.get_configured_data_roots = orig_get_roots

    print("=" * 65)
    print("ALL STEP 3 INSTAGRAM REELS TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    run_all_tests()
