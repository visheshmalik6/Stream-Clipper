"""Security-only smoke test of the Instagram Ephemeral Media Gateway and Cloudflare Quick Tunnel.

Validates end-to-end security over the live public Cloudflare Tunnel without publishing
or calling any Meta APIs:
1. Python 3.12 runtime verification.
2. Harmless dummy video file hosting.
3. Isolated ephemeral server port verification (ensures port != 5050).
4. Public tunnel GET/HEAD/Range media retrieval.
5. Strict 404 rejection on all non-media/dashboard routes.
6. Strict 404 rejection on raw URL-encoded path traversal (%2e%2e).
7. Strict 405 rejection on POST, PUT, DELETE methods.
8. Complete cleanup of tunnel process, server socket, and temporary file.
9. Redaction of public URLs and tokens from all logs and output.
"""

import http.client
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import List, Tuple

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from uploader import instagram


def redact_url(raw: str) -> str:
    """Mask the quick tunnel hostname and random video bearer token."""
    if not raw:
        return ""
    text = re.sub(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", "https://[REDACTED].trycloudflare.com", str(raw))
    text = re.sub(r"/video/[a-zA-Z0-9_-]+\.mp4", "/video/[REDACTED].mp4", text)
    return text


def run_smoke_test() -> bool:
    test_results: List[Tuple[str, str, str]] = []
    firm_timeout_seconds = 75.0
    start_time = time.time()

    print("====================================================================")
    print(" STREAM CLIPS: EPHEMERAL MEDIA GATEWAY SECURITY SMOKE TEST")
    print("====================================================================")

    # 1. Verify Python 3.12
    py_ver = sys.version_info
    print(f"Interpreter: {sys.executable}")
    print(f"Version:     {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    if (py_ver.major, py_ver.minor) == (3, 12):
        test_results.append(("Python 3.12 Runtime Verification", "PASS", f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}"))
    else:
        test_results.append(("Python 3.12 Runtime Verification", "FAIL", f"Expected 3.12, got {py_ver.major}.{py_ver.minor}"))
        print(f"[FAIL] Expected Python 3.12 interpreter, found {py_ver.major}.{py_ver.minor}")
        return False

    # Create dummy harmless payload
    dummy_payload = b"STREAMCLIPS_SECURITY_TEST_SYNTHETIC_DUMMY_MP4_PAYLOAD_BYTES_0123456789\n" * 16
    temp_video_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temp_video_path = Path(temp_video_file.name)
    temp_video_file.write(dummy_payload)
    temp_video_file.close()

    gateway = instagram.EphemeralMediaGateway()
    gateway_holder = [gateway]

    # Emergency watchdog thread
    def emergency_watchdog():
        time.sleep(firm_timeout_seconds)
        if gateway_holder[0]:
            print("\n[WATCHDOG TRIGGERED] Overall test timeout exceeded. Forcing emergency shutdown.")
            try:
                if gateway_holder[0]._tunnel_manager:
                    gateway_holder[0]._tunnel_manager.stop_tunnel()
            except Exception:
                pass

    watchdog_thread = threading.Thread(target=emergency_watchdog, daemon=True)
    watchdog_thread.start()

    try:
        print("\nStarting Ephemeral Media Gateway & Cloudflare Quick Tunnel...")
        with gateway.host_video(video_path=temp_video_path, timeout=35.0) as public_url:
            masked_url = redact_url(public_url)
            print(f"  ✓ Gateway active at: {masked_url}")

            # 2. Check allocated local port != 5050
            local_port = gateway._server.server_address[1]
            if local_port != 5050 and local_port > 0:
                test_results.append(("Local Port Isolation (!= 5050)", "PASS", f"Bound to port {local_port} (OS allocated)"))
            else:
                test_results.append(("Local Port Isolation (!= 5050)", "FAIL", f"Unsafe port {local_port}"))
                raise AssertionError(f"Port security violation: Gateway bound to {local_port}")

            parsed = urllib.parse.urlparse(public_url)
            tunnel_host = parsed.netloc
            media_path = parsed.path

            # 3. Wait for Cloudflare edge propagation
            print("  Waiting for Cloudflare edge routing propagation...")
            edge_ready = False
            edge_deadline = time.time() + 25.0
            last_edge_status = None

            while time.time() < edge_deadline:
                try:
                    conn = http.client.HTTPSConnection(tunnel_host, timeout=8)
                    conn.request("HEAD", media_path)
                    res = conn.getresponse()
                    last_edge_status = res.status
                    conn.close()
                    if res.status == 200:
                        edge_ready = True
                        break
                except Exception as e:
                    last_edge_status = str(e)
                time.sleep(1.5)

            if edge_ready:
                test_results.append(("Cloudflare Edge Reachability", "PASS", "Edge routing established, HTTP 200 ready"))
            else:
                test_results.append(("Cloudflare Edge Reachability", "FAIL", f"Edge did not ready in time (last status: {last_edge_status})"))
                raise RuntimeError(f"Cloudflare Edge failed to route within deadline. Last status: {last_edge_status}")

            # 4. Public HEAD request verification
            conn = http.client.HTTPSConnection(tunnel_host, timeout=10)
            conn.request("HEAD", media_path)
            res = conn.getresponse()
            ct = res.getheader("Content-Type")
            cl = int(res.getheader("Content-Length", "0"))
            ar = res.getheader("Accept-Ranges")
            conn.close()

            if res.status == 200 and ct == "video/mp4" and cl == len(dummy_payload) and ar == "bytes":
                test_results.append(("HTTP HEAD Request on Media URL", "PASS", "HTTP 200, Content-Type video/mp4, Accept-Ranges bytes"))
            else:
                test_results.append(("HTTP HEAD Request on Media URL", "FAIL", f"Status: {res.status}, Type: {ct}, Length: {cl}"))

            # 5. Public GET request verification
            conn = http.client.HTTPSConnection(tunnel_host, timeout=10)
            conn.request("GET", media_path)
            res = conn.getresponse()
            body = res.read()
            conn.close()

            if res.status == 200 and body == dummy_payload:
                test_results.append(("HTTP GET Full Payload Verification", "PASS", f"HTTP 200, received exact {len(body)} dummy bytes"))
            else:
                test_results.append(("HTTP GET Full Payload Verification", "FAIL", f"Status: {res.status}, Size match: {body == dummy_payload}"))

            # 6. Public Range request verification (HTTP 206)
            conn = http.client.HTTPSConnection(tunnel_host, timeout=10)
            conn.request("GET", media_path, headers={"Range": "bytes=0-15"})
            res = conn.getresponse()
            range_header = res.getheader("Content-Range")
            chunk = res.read()
            conn.close()

            if res.status == 206 and chunk == dummy_payload[:16] and range_header == f"bytes 0-15/{len(dummy_payload)}":
                test_results.append(("HTTP Range Request (Partial Content)", "PASS", "HTTP 206, Content-Range bytes 0-15/..."))
            else:
                test_results.append(("HTTP Range Request (Partial Content)", "FAIL", f"Status: {res.status}, Range: {range_header}"))

            # 7. Unrelated & Dashboard Route Rejection (Must return 404)
            forbidden_routes = [
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
                "/media/video/fake_id",
                "/media/image/fake_id",
                "/video/wrong_token.mp4",
                f"{media_path}/subpath",
            ]
            all_forbidden_404 = True
            forbidden_failures = []

            for f_route in forbidden_routes:
                try:
                    conn = http.client.HTTPSConnection(tunnel_host, timeout=8)
                    conn.request("GET", f_route)
                    res = conn.getresponse()
                    conn.close()
                    if res.status != 404:
                        all_forbidden_404 = False
                        forbidden_failures.append(f"{f_route} -> {res.status}")
                except Exception as ex:
                    forbidden_failures.append(f"{f_route} -> exc {ex}")
                    all_forbidden_404 = False

            if all_forbidden_404:
                test_results.append(("Dashboard & Non-Media Routes Rejection", "PASS", f"All {len(forbidden_routes)} forbidden paths returned 404 Not Found"))
            else:
                test_results.append(("Dashboard & Non-Media Routes Rejection", "FAIL", f"Non-404 responses: {forbidden_failures}"))

            # 8. URL-Encoded Traversal Rejection (%2e%2e sent without client normalization)
            traversal_routes = [
                "/%2e%2e",
                "/%2e%2e/",
                "/%2e%2e/%2e%2e",
                "/video/%2e%2e/clips.json",
                "/video/%2e%2e/%2e%2e/clips.json",
                "/video/..%2fclips.json",
                "/video/%2e%2e%2fclips.json",
                "/%2e%2e%2f",
                "/..",
                "/../",
            ]
            all_traversal_blocked = True
            traversal_failures = []

            for t_route in traversal_routes:
                try:
                    conn = http.client.HTTPSConnection(tunnel_host, timeout=8)
                    conn.request("GET", t_route)
                    res = conn.getresponse()
                    conn.close()
                    # Must be 404 (or 400 rejected by edge); must NEVER be 200 or 206
                    if res.status in (404, 400):
                        pass
                    else:
                        all_traversal_blocked = False
                        traversal_failures.append(f"{t_route} -> {res.status}")
                except Exception as ex:
                    traversal_failures.append(f"{t_route} -> exc {ex}")
                    all_traversal_blocked = False

            if all_traversal_blocked:
                test_results.append(("URL-Encoded Path Traversal Protection", "PASS", f"All {len(traversal_routes)} raw traversal paths rejected (404/400)"))
            else:
                test_results.append(("URL-Encoded Path Traversal Protection", "FAIL", f"Unexpected statuses: {traversal_failures}"))

            # 9. Disallowed HTTP Methods Rejection (405 Method Not Allowed)
            disallowed_methods = ["POST", "PUT", "DELETE"]
            all_methods_blocked = True
            method_failures = []

            for m in disallowed_methods:
                try:
                    conn = http.client.HTTPSConnection(tunnel_host, timeout=8)
                    conn.request(m, media_path, body=b"{}")
                    res = conn.getresponse()
                    conn.close()
                    if res.status != 405:
                        all_methods_blocked = False
                        method_failures.append(f"{m} -> {res.status}")
                except Exception as ex:
                    method_failures.append(f"{m} -> exc {ex}")
                    all_methods_blocked = False

            if all_methods_blocked:
                test_results.append(("HTTP Method Enforcement (POST/PUT/DELETE)", "PASS", "All disallowed methods returned 405 Method Not Allowed"))
            else:
                test_results.append(("HTTP Method Enforcement (POST/PUT/DELETE)", "FAIL", f"Unexpected statuses: {method_failures}"))

    finally:
        # 10. Teardown and Cleanup Verification
        print("\nShutting down Gateway and cleaning up test resources...")
        gateway_holder[0] = None

        # Verify gateway server is shut down
        server_stopped = gateway._server is None
        tunnel_stopped = gateway._tunnel_manager is None

        # Clean up temp dummy file
        try:
            if temp_video_path.exists():
                temp_video_path.unlink(missing_ok=True)
            temp_file_deleted = not temp_video_path.exists()
        except Exception:
            temp_file_deleted = False

        if server_stopped and tunnel_stopped and temp_file_deleted:
            test_results.append(("Teardown & Cleanup Verification", "PASS", "Tunnel killed, server socket closed, dummy file deleted"))
        else:
            test_results.append((
                "Teardown & Cleanup Verification",
                "FAIL",
                f"server_stopped={server_stopped}, tunnel_stopped={tunnel_stopped}, temp_deleted={temp_file_deleted}"
            ))

    # Print summary report
    elapsed = time.time() - start_time
    print("\n====================================================================")
    print(f" SMOKE TEST SUMMARY REPORT (Completed in {elapsed:.2f}s)")
    print("====================================================================")
    all_passed = True
    for name, status, detail in test_results:
        print(f" [{status}] {name}")
        print(f"         Detail: {detail}")
        if status != "PASS":
            all_passed = False
    print("====================================================================")

    return all_passed


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
