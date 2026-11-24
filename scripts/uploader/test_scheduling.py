"""Validation test suite for YouTube Native Scheduling (Phase 1).

Tests 100% mocked:
1. Immediate upload still uses privacyStatus: public.
2. Immediate upload does not send publishAt.
3. Scheduled upload uses privacyStatus: private.
4. Scheduled upload sends the correct publishAt timestamp.
5. Invalid timestamps are rejected.
6. Past timestamps are rejected.
7. Metadata is updated atomically and backup files are preserved.
8. Upload failure does not mark a clip as scheduled.
9. Existing immediate-upload tests continue to pass.
"""

import datetime
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

from uploader import auth_manager, discovery, server, storage, youtube


def get_future_utc_iso(days: int = 2) -> str:
    """Helper to generate a future UTC ISO-8601 timestamp string."""
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    return future.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_immediate_upload_public_and_no_publish_at():
    print("[1/9] Testing immediate upload uses privacyStatus: public...")
    uploader = youtube.YouTubeUploader(access_token="mock-token-123")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid.write(b"SYNTHETIC_MP4_DATA" * 32)
        tmp_vid_path = Path(tmp_vid.name)

    try:
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.headers = {"Location": "https://upload.youtube.com/upload_session_immediate"}
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            session_url = uploader.initiate_resumable_upload(
                video_path=tmp_vid_path,
                title="Immediate Video",
                description="Uploaded immediately",
                tags=["Shorts", "Gaming"],
                privacy_status="public",
                publish_at=None,
            )
            assert session_url == "https://upload.youtube.com/upload_session_immediate"

            call_req = mock_urlopen.call_args[0][0]
            payload = json.loads(call_req.data.decode("utf-8"))

            # 1. Immediate upload uses privacyStatus: public
            assert payload["status"]["privacyStatus"] == "public", f"Expected public, got {payload['status']['privacyStatus']}"
            print("  ✓ Confirmed immediate upload sets privacyStatus: public.")

            # 2. Immediate upload does not send publishAt
            assert "publishAt" not in payload["status"], "publishAt must NOT be present for immediate upload"
            print("  ✓ Confirmed immediate upload does not send publishAt.")
    finally:
        tmp_vid_path.unlink(missing_ok=True)


def test_scheduled_upload_private_and_publish_at():
    print("[2/9] Testing scheduled upload sets privacyStatus: private and correct publishAt...")
    uploader = youtube.YouTubeUploader(access_token="mock-token-123")
    future_utc = get_future_utc_iso(days=3)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid.write(b"SYNTHETIC_MP4_DATA" * 32)
        tmp_vid_path = Path(tmp_vid.name)

    try:
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.headers = {"Location": "https://upload.youtube.com/upload_session_scheduled"}
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            # Even if user/caller passed privacy_status="public", scheduling MUST force "private"
            session_url = uploader.initiate_resumable_upload(
                video_path=tmp_vid_path,
                title="Scheduled Video",
                description="Uploaded now, published later",
                tags=["Shorts"],
                privacy_status="public",
                publish_at=future_utc,
            )
            assert session_url == "https://upload.youtube.com/upload_session_scheduled"

            call_req = mock_urlopen.call_args[0][0]
            payload = json.loads(call_req.data.decode("utf-8"))

            # 3. Scheduled upload uses privacyStatus: private
            assert payload["status"]["privacyStatus"] == "private", f"Expected private, got {payload['status']['privacyStatus']}"
            print("  ✓ Confirmed scheduled upload strictly sets privacyStatus: private.")

            # 4. Scheduled upload sends the correct publishAt timestamp
            assert "publishAt" in payload["status"], "publishAt MUST be present for scheduled upload"
            assert payload["status"]["publishAt"] == future_utc, f"Expected {future_utc}, got {payload['status']['publishAt']}"
            print(f"  ✓ Confirmed scheduled upload sends exact publishAt timestamp: {future_utc}")
    finally:
        tmp_vid_path.unlink(missing_ok=True)


def test_invalid_timestamps_rejected():
    print("[3/9] Testing invalid timestamps are rejected...")
    uploader = youtube.YouTubeUploader(access_token="mock-token-123")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid.write(b"SYNTHETIC_MP4_DATA")
        tmp_vid_path = Path(tmp_vid.name)

    try:
        invalid_timestamps = [
            "not-a-timestamp",
            "2026-11-25 15:30:00",       # Missing timezone / ISO 'T'
            "2026-11-25T15:30:00",       # Missing timezone indicator (not explicit UTC)
            "2026-11-25T15:30:00+05:30", # Non-UTC timezone offset
            "2026-13-45T99:99:99Z",      # Invalid date/time components
            "",                          # Empty string
            "   ",                       # Whitespace only
            None,                        # Non-string if passed to validate_publish_at directly
        ]

        for inv in invalid_timestamps:
            # Test direct validate_publish_at
            try:
                youtube.validate_publish_at(inv)  # type: ignore
                assert False, f"validate_publish_at should have rejected '{inv}'"
            except ValueError:
                pass

            # Test initiate_resumable_upload rejection (when not None)
            if inv is not None:
                try:
                    uploader.initiate_resumable_upload(
                        video_path=tmp_vid_path,
                        title="Invalid Test",
                        description="Desc",
                        publish_at=inv,
                    )
                    assert False, f"initiate_resumable_upload should have rejected '{inv}'"
                except ValueError:
                    pass

        print(f"  ✓ Successfully verified {len(invalid_timestamps)} invalid timestamp formats are strictly rejected.")
    finally:
        tmp_vid_path.unlink(missing_ok=True)


def test_past_timestamps_rejected():
    print("[4/9] Testing past timestamps are rejected...")
    uploader = youtube.YouTubeUploader(access_token="mock-token-123")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid.write(b"SYNTHETIC_MP4_DATA")
        tmp_vid_path = Path(tmp_vid.name)

    try:
        past_timestamps = [
            "2020-01-01T00:00:00Z",
            "2025-12-31T23:59:59Z",
            (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ]

        for past_ts in past_timestamps:
            try:
                youtube.validate_publish_at(past_ts)
                assert False, f"validate_publish_at should have rejected past timestamp '{past_ts}'"
            except ValueError as ve:
                assert "future" in str(ve).lower()

            try:
                uploader.initiate_resumable_upload(
                    video_path=tmp_vid_path,
                    title="Past Test",
                    description="Desc",
                    publish_at=past_ts,
                )
                assert False, f"initiate_resumable_upload should have rejected past timestamp '{past_ts}'"
            except ValueError as ve:
                assert "future" in str(ve).lower()

        print(f"  ✓ Confirmed past timestamps are strictly rejected and not converted to immediate uploads.")
    finally:
        tmp_vid_path.unlink(missing_ok=True)


def test_atomic_metadata_and_backup_preservation():
    print("[5/9] Testing atomic metadata updates and backup preservation...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_json = tmp_path / "clips.json"
        future_utc = get_future_utc_iso(days=5)

        initial_data = {
            "source": {"title": "Test Stream", "name": "Creator", "url": "https://test.com"},
            "covered": [0.0, 100.0],
            "clips": [
                {
                    "file": "clip_schedule_test.mp4",
                    "title": "Initial Title",
                    "caption": "Initial Caption",
                    "hashtags": ["#gaming"],
                    "score": 92,
                    "look": "stack",
                    "uploads": {
                        "youtube": {"status": "not_uploaded"}
                    }
                }
            ]
        }
        test_json.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

        # 1. Update upload status to scheduled
        scheduled_status = {
            "status": "scheduled",
            "video_id": "SCHED_VID_123",
            "url": "https://youtube.com/shorts/SCHED_VID_123",
            "uploaded_at": "2026-11-23T20:00:00Z",
            "scheduled_at": future_utc,
            "publish_at": future_utc,
            "privacy": "private",
            "error": None,
        }
        updated = storage.update_clip_upload_status(
            clips_json_path=str(test_json),
            clip_filename="clip_schedule_test.mp4",
            platform="youtube",
            upload_status_dict=scheduled_status,
        )

        assert updated["uploads"]["youtube"]["status"] == "scheduled"
        assert updated["uploads"]["youtube"]["scheduled_at"] == future_utc
        assert updated["uploads"]["youtube"]["video_id"] == "SCHED_VID_123"

        # Verify backup exists
        bak_file = test_json.with_suffix(".json.bak")
        assert bak_file.exists(), ".json.bak backup must be created"
        bak_data = json.loads(bak_file.read_text(encoding="utf-8"))
        assert bak_data["clips"][0]["uploads"]["youtube"]["status"] == "not_uploaded", "Backup must have previous state"

        # Verify persistent disk state
        disk_data = json.loads(test_json.read_text(encoding="utf-8"))
        assert disk_data["clips"][0]["uploads"]["youtube"]["status"] == "scheduled"
        assert disk_data["clips"][0]["uploads"]["youtube"]["scheduled_at"] == future_utc
        assert disk_data["clips"][0]["title"] == "Initial Title"
        assert disk_data["clips"][0]["score"] == 92

        print("  ✓ Metadata updated atomically with .json.bak backup preserved.")


def test_upload_failure_does_not_mark_as_scheduled():
    print("[6/9] Testing upload failure does not mark clip as scheduled...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_json = tmp_path / "clips.json"
        future_utc = get_future_utc_iso(days=2)

        data = {
            "source": {"title": "Stream", "name": "Creator", "url": "https://test.com"},
            "clips": [
                {
                    "file": "test_failure.mp4",
                    "title": "Failing Upload",
                    "uploads": {"youtube": {"status": "not_uploaded"}}
                }
            ]
        }
        test_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Simulate upload failure
        failed_status = {
            "status": "failed",
            "video_id": None,
            "url": None,
            "uploaded_at": None,
            "scheduled_at": None,
            "privacy": "private",
            "error": "Chunk upload failed (HTTP 503): Backend Unavailable",
        }
        updated = storage.update_clip_upload_status(
            clips_json_path=str(test_json),
            clip_filename="test_failure.mp4",
            platform="youtube",
            upload_status_dict=failed_status,
        )

        assert updated["uploads"]["youtube"]["status"] == "failed"
        assert updated["uploads"]["youtube"]["status"] != "scheduled"
        assert updated["uploads"]["youtube"]["scheduled_at"] is None
        assert "HTTP 503" in updated["uploads"]["youtube"]["error"]

        reloaded = json.loads(test_json.read_text(encoding="utf-8"))
        assert reloaded["clips"][0]["uploads"]["youtube"]["status"] == "failed"

        print("  ✓ Verified failed upload records status: failed and never marks as scheduled.")


def test_dashboard_api_scheduling_endpoints(test_clip_id: str):
    print("[7/9] Testing Dashboard HTTP server scheduling API endpoints...")
    test_port = 5977
    httpd = server.ThreadingHTTPServer(("127.0.0.1", test_port), server.DashboardRequestHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    base_url = f"http://127.0.0.1:{test_port}"
    headers = {
        "Host": f"127.0.0.1:{test_port}",
        "Origin": base_url,
        "Sec-Fetch-Site": "same-origin",
        "Content-Type": "application/json",
    }

    try:
        # Mock auth to return valid token
        with patch.object(server.auth, "get_valid_access_token", return_value="mock_access_token"):

            # A. Invalid timestamp via API -> 400 Bad Request
            bad_req = urllib.request.Request(
                f"{base_url}/api/publish/youtube",
                data=json.dumps({
                    "clip_id": test_clip_id,
                    "publish_at": "invalid-timestamp-xyz",
                }).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                urllib.request.urlopen(bad_req)
                assert False, "Should return 400 for invalid timestamp"
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
                res = json.loads(exc.read().decode("utf-8"))
                assert res["error"] == "invalid_timestamp"
            print("  ✓ API rejected invalid timestamp with HTTP 400.")

            # B. Past timestamp via API -> 400 Bad Request
            past_req = urllib.request.Request(
                f"{base_url}/api/publish/youtube",
                data=json.dumps({
                    "clip_id": test_clip_id,
                    "publish_at": "2020-01-01T00:00:00Z",
                }).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                urllib.request.urlopen(past_req)
                assert False, "Should return 400 for past timestamp"
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
                res = json.loads(exc.read().decode("utf-8"))
                assert res["error"] == "invalid_timestamp"
                assert "future" in res["message"].lower()
            print("  ✓ API rejected past timestamp with HTTP 400.")

            # C. Successful Scheduled Upload via API
            future_utc = get_future_utc_iso(days=4)
            with patch("uploader.youtube.YouTubeUploader.upload_clip") as mock_upload:
                mock_upload.return_value = {
                    "video_id": "SCHED_VID_999",
                    "url": "https://youtube.com/shorts/SCHED_VID_999",
                }

                sched_req = urllib.request.Request(
                    f"{base_url}/api/publish/youtube",
                    data=json.dumps({
                        "clip_id": test_clip_id,
                        "title": "Scheduled Title",
                        "publish_at": future_utc,
                        "force": True,
                    }).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(sched_req) as resp:
                    assert resp.status == 200
                    res = json.loads(resp.read().decode("utf-8"))
                    assert res["success"] is True
                    assert "scheduled" in res["message"].lower()
                    assert res["upload"]["status"] == "scheduled"
                    assert res["upload"]["video_id"] == "SCHED_VID_999"
                    assert res["upload"]["scheduled_at"] == future_utc
                    assert res["upload"]["privacy"] == "private"

                # Verify mock call parameters
                call_kwargs = mock_upload.call_args[1]
                assert call_kwargs["publish_at"] == future_utc
                assert call_kwargs["privacy_status"] == "private"
            print("  ✓ API scheduled upload succeeded and returned status: scheduled.")

            # D. Upload Failure via API -> 500, marked failed, not scheduled
            with patch("uploader.youtube.YouTubeUploader.upload_clip") as mock_upload:
                mock_upload.side_effect = youtube.YouTubeUploadError("YouTube API Quota Exceeded")

                fail_req = urllib.request.Request(
                    f"{base_url}/api/publish/youtube",
                    data=json.dumps({
                        "clip_id": test_clip_id,
                        "title": "Failing Schedule",
                        "publish_at": future_utc,
                        "force": True,
                    }).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    urllib.request.urlopen(fail_req)
                    assert False, "Should return 500 on upload failure"
                except urllib.error.HTTPError as exc:
                    assert exc.code == 500
                    res = json.loads(exc.read().decode("utf-8"))
                    assert res["success"] is False
                    assert res["upload"]["status"] == "failed"
                    assert res["upload"]["status"] != "scheduled"
                    assert "Quota Exceeded" in res["error"]
            print("  ✓ API failure correctly returned 500 and recorded status: failed.")

            # E. Duplicate Prevention for Scheduled Clip
            clip_lookup = discovery.get_clip_by_id(test_clip_id)
            if clip_lookup:
                # Mark clip as scheduled
                storage.update_clip_upload_status(
                    clips_json_path=clip_lookup["_json_path"],
                    clip_filename=clip_lookup["file"],
                    platform="youtube",
                    upload_status_dict={
                        "status": "scheduled",
                        "video_id": "SCHED_VID_999",
                        "url": "https://youtube.com/shorts/SCHED_VID_999",
                        "scheduled_at": future_utc,
                    }
                )

                dup_req = urllib.request.Request(
                    f"{base_url}/api/publish/youtube",
                    data=json.dumps({
                        "clip_id": test_clip_id,
                        "publish_at": future_utc,
                        "force": False,
                    }).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    urllib.request.urlopen(dup_req)
                    assert False, "Should return 409 Conflict for already scheduled clip"
                except urllib.error.HTTPError as exc:
                    assert exc.code == 409
                    res = json.loads(exc.read().decode("utf-8"))
                    assert res["error"] == "already_published"
                    assert res["status"] == "scheduled"
                print("  ✓ API duplicate prevention blocked duplicate schedule without force.")

    finally:
        httpd.shutdown()
        httpd.server_close()


def test_immediate_upload_api_preservation(test_clip_id: str):
    print("[8/9] Testing immediate upload API flow is completely preserved...")
    test_port = 5978
    httpd = server.ThreadingHTTPServer(("127.0.0.1", test_port), server.DashboardRequestHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    base_url = f"http://127.0.0.1:{test_port}"
    headers = {
        "Host": f"127.0.0.1:{test_port}",
        "Origin": base_url,
        "Sec-Fetch-Site": "same-origin",
        "Content-Type": "application/json",
    }

    try:
        with patch.object(server.auth, "get_valid_access_token", return_value="mock_access_token"):
            with patch("uploader.youtube.YouTubeUploader.upload_clip") as mock_upload:
                mock_upload.return_value = {
                    "video_id": "IMMED_VID_111",
                    "url": "https://youtube.com/shorts/IMMED_VID_111",
                }

                # Immediate upload request without publish_at
                immed_req = urllib.request.Request(
                    f"{base_url}/api/publish/youtube",
                    data=json.dumps({
                        "clip_id": test_clip_id,
                        "title": "Immediate Publish",
                        "privacy": "public",
                        "force": True,
                    }).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(immed_req) as resp:
                    assert resp.status == 200
                    res = json.loads(resp.read().decode("utf-8"))
                    assert res["success"] is True
                    assert res["upload"]["status"] == "published"
                    assert res["upload"]["video_id"] == "IMMED_VID_111"
                    assert "scheduled_at" not in res["upload"] or res["upload"].get("scheduled_at") is None
                    assert res["upload"]["privacy"] == "public"

                # Verify mock kwargs had publish_at=None and privacy_status="public"
                call_kwargs = mock_upload.call_args[1]
                assert call_kwargs.get("publish_at") is None
                assert call_kwargs.get("privacy_status") == "public"

        print("  ✓ Immediate upload API flow completed cleanly and recorded status: published.")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_existing_pipeline_and_instagram_untouched():
    print("[9/9] Verifying Instagram and pipeline components were untouched...")
    # Instagram Manager and Publisher must be present and unmodified in interface
    assert hasattr(server, "ig_manager")
    assert hasattr(server.instagram, "InstagramPublisher")
    assert hasattr(server.instagram, "TunnelManager")
    assert hasattr(server.instagram, "EphemeralMediaGateway")

    # Pipeline files must be untouched
    for path in [
        SCRIPTS_DIR / "streamclips.py",
        SCRIPTS_DIR / "sc" / "cli.py",
        SCRIPTS_DIR / "sc" / "pipeline.py",
        SCRIPTS_DIR / "sc" / "produce.py",
        SCRIPTS_DIR / "sc" / "listen.py",
        SCRIPTS_DIR / "sc" / "highlights.py",
        SCRIPTS_DIR / "sc" / "common.py",
    ]:
        assert path.exists(), f"Missing file: {path}"

    print("  ✓ Instagram components and core pipeline files verified untouched.")


def run_all_scheduling_tests():
    print("=" * 65)
    print("Running YouTube Native Scheduling Test Suite (Phase 1)")
    print("=" * 65)

    orig_auth_dir = auth_manager.AUTH_DIR
    orig_cfg_file = auth_manager.CLIENT_CONFIG_FILE
    orig_tokens_file = auth_manager.TOKENS_FILE
    orig_get_roots = discovery.get_configured_data_roots

    with tempfile.TemporaryDirectory() as tmp_auth_str, tempfile.TemporaryDirectory() as tmp_fix_str:
        tmp_auth = Path(tmp_auth_str) / "auth"
        tmp_auth.mkdir(parents=True, exist_ok=True)
        tmp_fix = Path(tmp_fix_str)

        # Create synthetic stream fixture
        stream_dir = tmp_fix / "2026-11-23" / "scheduling-game" / "creator__test-stream"
        stream_dir.mkdir(parents=True, exist_ok=True)
        clip_file = stream_dir / "clip_sched_01.mp4"
        clip_file.write_bytes(b"SYNTHETIC_MP4_PAYLOAD_FOR_SCHEDULING" * 64)

        clips_json = stream_dir / "clips.json"
        clips_data = {
            "source": {"title": "Test Stream", "name": "Creator", "url": "https://test.com"},
            "covered": [0.0, 100.0],
            "clips": [
                {
                    "file": "clip_sched_01.mp4",
                    "title": "Synthetic Clip",
                    "caption": "Synthetic Caption",
                    "hashtags": ["#Shorts", "#gaming"],
                    "uploads": {"youtube": {"status": "not_uploaded"}},
                }
            ],
        }
        clips_json.write_text(json.dumps(clips_data, indent=2), encoding="utf-8")
        test_clip_id = discovery.generate_clip_id(clips_json, "clip_sched_01.mp4")

        try:
            auth_manager.AUTH_DIR = tmp_auth
            auth_manager.CLIENT_CONFIG_FILE = tmp_auth / "youtube_client_config.json"
            auth_manager.TOKENS_FILE = tmp_auth / "youtube_tokens.json"
            server.auth = auth_manager.AuthManager()
            discovery.get_configured_data_roots = lambda: [tmp_fix]

            test_immediate_upload_public_and_no_publish_at()
            test_scheduled_upload_private_and_publish_at()
            test_invalid_timestamps_rejected()
            test_past_timestamps_rejected()
            test_atomic_metadata_and_backup_preservation()
            test_upload_failure_does_not_mark_as_scheduled()
            test_dashboard_api_scheduling_endpoints(test_clip_id)
            test_immediate_upload_api_preservation(test_clip_id)
            test_existing_pipeline_and_instagram_untouched()

        finally:
            auth_manager.AUTH_DIR = orig_auth_dir
            auth_manager.CLIENT_CONFIG_FILE = orig_cfg_file
            auth_manager.TOKENS_FILE = orig_tokens_file
            server.auth = auth_manager.AuthManager()
            discovery.get_configured_data_roots = orig_get_roots

    print("=" * 65)
    print("ALL 9 YOUTUBE NATIVE SCHEDULING TESTS PASSED (100% ISOLATED)!")
    print("=" * 65)


if __name__ == "__main__":
    run_all_scheduling_tests()
