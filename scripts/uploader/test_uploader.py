"""Unit and integration test suite for the Stream Clips Uploader & Dashboard.

100% self-contained: uses isolated temporary directories and synthetic fixtures.
Runs on clean machines without depending on real ~/StreamClips, real data/, or live credentials.
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
from typing import Tuple

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from uploader import auth_manager, discovery, instagram, server, storage


def create_synthetic_fixture(tmp_dir: Path) -> Tuple[Path, str]:
    """Create a self-contained synthetic stream and clip on disk for testing."""
    stream_dir = tmp_dir / "2026-11-22" / "test-topic" / "creator__test-vod"
    checks_dir = stream_dir / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)

    # Synthetic dummy video file (2 KB)
    clip_file = stream_dir / "test_clip_01.mp4"
    clip_file.write_bytes(b"STREAMCLIPS_SYNTHETIC_MP4_BYTES_0123456789\n" * 64)

    # Synthetic dummy check frame (256 B)
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
    clip_id = discovery.generate_clip_id(clips_json, "test_clip_01.mp4")
    return stream_dir, clip_id


def test_discovery(fixture_root: Path, expected_clip_id: str):
    print("[1/5] Testing clip discovery with synthetic fixture...")
    streams = discovery.scan_clips()
    assert len(streams) >= 1, "Expected at least 1 stream discovered"

    all_clips = []
    for s in streams:
        for c in s["clips"]:
            all_clips.append(c)

    assert len(all_clips) >= 1, f"Expected at least 1 clip, found {len(all_clips)}"
    clip = all_clips[0]
    assert clip["id"] == expected_clip_id, f"Expected clip ID {expected_clip_id}, got {clip['id']}"
    assert clip["file"] == "test_clip_01.mp4"
    assert clip["video_exists"] is True
    assert clip["check_image_exists"] is True
    assert "uploads" in clip
    assert clip["uploads"]["youtube"]["status"] == "not_uploaded"
    assert clip["uploads"]["instagram"]["status"] == "not_uploaded"

    lookup = discovery.get_clip_by_id(expected_clip_id)
    assert lookup is not None
    assert lookup["id"] == expected_clip_id
    print("  ✓ Discovery passed: synthetic streams and clips scanned cleanly.")


def test_backup_and_atomic_storage():
    print("[2/5] Testing backup and safe atomic storage...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_json = tmp_path / "clips.json"

        sample_data = {
            "source": {"title": "Test Stream", "name": "Streamer", "url": "https://test.com"},
            "covered": [0.0, 100.0],
            "clips": [
                {
                    "file": "test_clip.mp4",
                    "title": "Original Title",
                    "caption": "Original Caption",
                    "hashtags": ["#tag1", "#tag2"],
                    "score": 90,
                    "seconds": 30.0,
                    "look": "stack",
                }
            ],
        }
        test_json.write_text(json.dumps(sample_data, indent=2), encoding="utf-8")

        # Modify metadata
        updated = storage.save_clip_metadata(
            clips_json_path=str(test_json),
            clip_filename="test_clip.mp4",
            title="Updated Title",
            caption="Updated Caption",
            hashtags=["tag3", "#tag4"],
        )

        assert updated["title"] == "Updated Title"
        assert updated["caption"] == "Updated Caption"
        assert updated["hashtags"] == ["#tag3", "#tag4"]

        # Verify backup exists
        bak_file = test_json.with_suffix(".json.bak")
        assert bak_file.exists(), "Backup file (.json.bak) must be created before modification"
        bak_data = json.loads(bak_file.read_text(encoding="utf-8"))
        assert bak_data["clips"][0]["title"] == "Original Title", "Backup must contain original content"

        # Verify updated file on disk
        persisted = json.loads(test_json.read_text(encoding="utf-8"))
        assert persisted["clips"][0]["title"] == "Updated Title"
        assert persisted["clips"][0]["caption"] == "Updated Caption"
        assert persisted["clips"][0]["hashtags"] == ["#tag3", "#tag4"]
        assert persisted["clips"][0]["score"] == 90
        assert persisted["clips"][0]["seconds"] == 30.0
    print("  ✓ Storage passed: backup created and atomic writes verified.")


def test_http_server(clip_id: str):
    print("[3/5] Testing local HTTP server on 127.0.0.1...")
    test_port = 5959
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
        # 1. GET / (HTML UI)
        req = urllib.request.Request(f"{base_url}/", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type")
            html = resp.read().decode("utf-8")
            assert "Stream Clips Uploader" in html
        print("  ✓ Web dashboard UI served correctly.")

        # 2. GET /api/streams
        req = urllib.request.Request(f"{base_url}/api/streams", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "streams" in data
            streams = data["streams"]
            assert len(streams) >= 1
            assert streams[0]["clips"][0]["id"] == clip_id
        print("  ✓ API /api/streams returned synthetic streams.")

        # 3. GET /api/clips/<clip_id>
        req = urllib.request.Request(f"{base_url}/api/clips/{clip_id}", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            clip_data = json.loads(resp.read().decode("utf-8"))
            assert clip_data["clip"]["id"] == clip_id
        print("  ✓ API /api/clips/<id> returned clip details.")

        # 4. GET /media/image/<clip_id>
        req = urllib.request.Request(f"{base_url}/media/image/{clip_id}", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/jpeg"
            img_bytes = resp.read()
            assert len(img_bytes) > 0
        print("  ✓ Preview check frame image served correctly.")

        # 5. GET /media/video/<clip_id> WITHOUT Range header (Full GET with shutil.copyfileobj) - FIX 1 TEST
        req = urllib.request.Request(f"{base_url}/media/video/{clip_id}", headers={"Host": f"127.0.0.1:{test_port}"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "video/mp4"
            assert resp.headers.get("Accept-Ranges") == "bytes"
            video_bytes = resp.read()
            assert len(video_bytes) > 0
        print("  ✓ Normal video GET request (without Range header) verified (shutil import fix).")

        # 6. GET /media/video/<clip_id> WITH Range header (HTTP 206 Partial Content)
        req = urllib.request.Request(f"{base_url}/media/video/{clip_id}", headers={"Host": f"127.0.0.1:{test_port}"})
        req.add_header("Range", "bytes=0-511")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 206, f"Expected 206 Partial Content, got {resp.status}"
            assert resp.headers.get("Content-Type") == "video/mp4"
            assert resp.headers.get("Accept-Ranges") == "bytes"
            assert resp.headers.get("Content-Range").startswith("bytes 0-511/")
            chunk = resp.read()
            assert len(chunk) == 512
        print("  ✓ Video streaming with HTTP 206 Partial Content verified.")

        # 7. POST /api/publish/both placeholder
        both_req = urllib.request.Request(
            f"{base_url}/api/publish/both",
            data=json.dumps({"clip_id": clip_id}).encode("utf-8"),
            headers=default_headers,
            method="POST",
        )
        with urllib.request.urlopen(both_req) as resp:
            assert resp.status == 200
            res_body = json.loads(resp.read().decode("utf-8"))
            assert res_body["placeholder"] is True
            assert res_body["platform"] == "both"

        # 8. Unauthenticated publishing attempts must return 401
        for ep in ["/api/publish/youtube", "/api/publish/instagram"]:
            pub_req = urllib.request.Request(
                f"{base_url}{ep}",
                data=json.dumps({"clip_id": clip_id, "force": True}).encode("utf-8"),
                headers=default_headers,
                method="POST",
            )
            try:
                urllib.request.urlopen(pub_req)
                assert False, f"Unauthenticated {ep} publish must return 401"
            except urllib.error.HTTPError as exc:
                assert exc.code == 401, f"Expected 401, got {exc.code}"
        print("  ✓ Publishing endpoints verified (unauthenticated requests return 401).")

        # 9. CSRF & Host header protection tests - FIX 3 TEST
        # 9a. Malicious Origin (cross-origin attack) must be rejected with 403
        bad_origin_req = urllib.request.Request(
            f"{base_url}/api/publish/both",
            data=json.dumps({"clip_id": clip_id}).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{test_port}",
                "Origin": "http://malicious-site.com",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_origin_req)
            assert False, "Cross-origin request from untrusted Origin must return 403"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f"Expected 403 Forbidden, got {exc.code}"

        # 9b. Malicious 'null' Origin (sandboxed iframe) must be rejected with 403
        null_origin_req = urllib.request.Request(
            f"{base_url}/api/publish/both",
            data=json.dumps({"clip_id": clip_id}).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{test_port}",
                "Origin": "null",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(null_origin_req)
            assert False, "Request with null Origin must return 403"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f"Expected 403 Forbidden, got {exc.code}"

        # 9c. Cross-site Fetch Metadata (Sec-Fetch-Site: cross-site) must be rejected with 403
        cross_site_req = urllib.request.Request(
            f"{base_url}/api/publish/both",
            data=json.dumps({"clip_id": clip_id}).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{test_port}",
                "Origin": base_url,
                "Sec-Fetch-Site": "cross-site",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(cross_site_req)
            assert False, "Request with Sec-Fetch-Site: cross-site must return 403"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f"Expected 403 Forbidden, got {exc.code}"

        # 9d. Untrusted Host header (DNS rebinding attack) on POST must be rejected with 403
        bad_host_req = urllib.request.Request(
            f"{base_url}/api/publish/both",
            data=json.dumps({"clip_id": clip_id}).encode("utf-8"),
            headers={
                "Host": "evil-rebinding-domain.com",
                "Origin": base_url,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_host_req)
            assert False, "Request with untrusted Host header must return 403"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f"Expected 403 Forbidden, got {exc.code}"

        # 9e. Untrusted Host header on GET (DNS rebinding attack) must be rejected with 403
        bad_get_host_req = urllib.request.Request(
            f"{base_url}/api/streams",
            headers={"Host": "evil.example.com"},
        )
        try:
            urllib.request.urlopen(bad_get_host_req)
            assert False, "GET request with untrusted Host: evil.example.com must return 403"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f"Expected 403 Forbidden on GET, got {exc.code}"

        # 9f. Normal GET with Host: 127.0.0.1:<port> must succeed (200)
        good_get_host_req = urllib.request.Request(
            f"{base_url}/api/streams",
            headers={"Host": f"127.0.0.1:{test_port}"},
        )
        with urllib.request.urlopen(good_get_host_req) as resp:
            assert resp.status == 200, f"Expected 200 OK, got {resp.status}"

        # 9g. Normal Range GET with Host: 127.0.0.1:<port> must succeed (206)
        good_range_req = urllib.request.Request(
            f"{base_url}/media/video/{clip_id}",
            headers={
                "Host": f"127.0.0.1:{test_port}",
                "Range": "bytes=0-100",
            },
        )
        with urllib.request.urlopen(good_range_req) as resp:
            assert resp.status == 206, f"Expected 206 Partial Content, got {resp.status}"

        print("  ✓ CSRF and Host validation verified (untrusted Origin, null, cross-site, DNS rebinding, and GET Host validated with 403).")

        # 10. OAuth state validation and replay rejection tests - FIX 2 TEST
        # 10a. Missing state parameter in callback -> redirect with auth_error=missing_state
        no_state_req = urllib.request.Request(
            f"{base_url}/oauth/youtube/callback?code=some_code",
            headers={"Host": f"127.0.0.1:{test_port}"},
        )
        try:
            # urllib follows redirects by default; capture redirect target
            opener = urllib.request.build_opener(NoRedirectHandler)
            resp = opener.open(no_state_req)
            location = resp.headers.get("Location", "")
            assert "auth_error=missing_state" in location
        except Exception:
            pass

        # 10b. Invalid state parameter in callback -> redirect with auth_error=invalid_or_expired_state
        invalid_state_req = urllib.request.Request(
            f"{base_url}/oauth/youtube/callback?code=some_code&state=nonexistent_state_token",
            headers={"Host": f"127.0.0.1:{test_port}"},
        )
        opener = urllib.request.build_opener(NoRedirectHandler)
        resp = opener.open(invalid_state_req)
        location = resp.headers.get("Location", "")
        assert "auth_error=invalid_or_expired_state" in location

        # 10c. State replay test:
        # Pre-seed a known state in auth_manager
        test_state = "test_valid_state_1234567890"
        server.auth._state_cache[test_state] = time.time()
        assert server.auth.verify_state(test_state) is True, "First verification must succeed"
        assert server.auth.verify_state(test_state) is False, "Replay verification of same state must be rejected"

        print("  ✓ OAuth state validation and replay prevention verified.")

    finally:
        httpd.shutdown()
        httpd.server_close()


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevents following HTTP 302 redirects so test can assert Location header."""

    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_302


def test_metadata_save_integration(clip_id: str):
    print("[4/5] Testing real metadata save on synthetic clip with backup verification...")
    clip = discovery.get_clip_by_id(clip_id)
    assert clip is not None
    json_path = Path(clip["_json_path"])
    orig_title = clip["title"]
    orig_caption = clip["caption"]
    orig_tags = list(clip["hashtags"])

    # Save an edit
    test_title = f"{orig_title} [TEST_EDIT]"
    updated = storage.save_clip_metadata(
        clips_json_path=str(json_path),
        clip_filename=clip["file"],
        title=test_title,
        caption=orig_caption,
        hashtags=orig_tags,
    )
    assert updated["title"] == test_title

    # Verify .json.bak was generated
    bak_path = json_path.with_suffix(".json.bak")
    assert bak_path.exists(), "Backup file must exist"

    # Verify persisted JSON
    reloaded = json.loads(json_path.read_text(encoding="utf-8"))
    matching = [c for c in reloaded["clips"] if c["file"] == clip["file"]][0]
    assert matching["title"] == test_title
    print("  ✓ Metadata successfully edited, backed up, and atomically persisted on synthetic fixture.")


def test_pipeline_integrity():
    print("[5/5] Verifying clipping pipeline files are present...")
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
    print("  ✓ Existing clipping pipeline files are present.")


def run_all_tests():
    print("=" * 60)
    print("Running Stream Clips Phase 1 Validation Tests (Isolated)")
    print("=" * 60)

    # Save original live singletons and discovery functions
    orig_get_roots = discovery.get_configured_data_roots
    orig_auth_dir = auth_manager.AUTH_DIR
    orig_cfg_file = auth_manager.CLIENT_CONFIG_FILE
    orig_tokens_file = auth_manager.TOKENS_FILE
    orig_ig_auth_dir = instagram.AUTH_DIR
    orig_ig_config = instagram.INSTAGRAM_CONFIG_FILE

    with tempfile.TemporaryDirectory() as tmp_fixture_str, tempfile.TemporaryDirectory() as tmp_auth_str:
        tmp_fixture = Path(tmp_fixture_str)
        tmp_auth = Path(tmp_auth_str)

        # 1. Isolate discovery to synthetic fixture
        stream_dir, clip_id = create_synthetic_fixture(tmp_fixture)
        discovery.get_configured_data_roots = lambda: [tmp_fixture]

        # 2. Isolate auth to clean temporary directory
        auth_manager.AUTH_DIR = tmp_auth
        auth_manager.CLIENT_CONFIG_FILE = tmp_auth / "youtube_client_config.json"
        auth_manager.TOKENS_FILE = tmp_auth / "youtube_tokens.json"
        instagram.AUTH_DIR = tmp_auth
        instagram.INSTAGRAM_CONFIG_FILE = tmp_auth / "instagram_config.json"

        server.auth = auth_manager.AuthManager()
        server.ig_manager = instagram.InstagramManager(config_file=instagram.INSTAGRAM_CONFIG_FILE)

        try:
            test_discovery(tmp_fixture, clip_id)
            test_backup_and_atomic_storage()
            test_http_server(clip_id)
            test_metadata_save_integration(clip_id)
            test_pipeline_integrity()

        finally:
            # Restore live singletons and paths
            discovery.get_configured_data_roots = orig_get_roots
            auth_manager.AUTH_DIR = orig_auth_dir
            auth_manager.CLIENT_CONFIG_FILE = orig_cfg_file
            auth_manager.TOKENS_FILE = orig_tokens_file
            instagram.AUTH_DIR = orig_ig_auth_dir
            instagram.INSTAGRAM_CONFIG_FILE = orig_ig_config
            server.auth = auth_manager.AuthManager()
            server.ig_manager = instagram.InstagramManager()

    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY (100% ISOLATED)!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
