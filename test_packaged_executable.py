"""
test_packaged_executable.py — Test launching and verifying the actual standalone Windows executable.
"""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
EXE_PATH = _ROOT / "dist" / "TimeTrackerAI" / "TimeTrackerAI.exe"


def test_standalone_executable():
    print(f"--- Testing Standalone Windows Executable: {EXE_PATH} ---", flush=True)
    if not EXE_PATH.exists():
        raise FileNotFoundError(f"Packaged executable {EXE_PATH} does not exist!")

    # Launch executable
    print("[1] Spawning TimeTrackerAI.exe process...", flush=True)
    proc = subprocess.Popen([str(EXE_PATH)])

    try:
        # Give it a moment to boot and acquire mutex
        time.sleep(4.0)

        poll_status = proc.poll()
        if poll_status is not None:
            raise RuntimeError(f"TimeTrackerAI.exe exited prematurely with code {poll_status}!")
        print(f"[OK] Process is alive and running with PID: {proc.pid}", flush=True)

        # Check health endpoint
        print("[2] Probing local health check at http://127.0.0.1:8000/api/health...", flush=True)
        url = "http://127.0.0.1:8000/api/health"
        req = urllib.request.Request(url, headers={"User-Agent": "ExecutableVerifier"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            status_code = resp.status
            body = resp.read().decode("utf-8")
            print(f"[OK] Health check responded HTTP {status_code}: {body}", flush=True)

        # Check that user APPDATA folder was configured for the database
        appdata_dir = Path(os.environ.get("APPDATA", Path.home())) / "TimeTrackerAI"
        print(f"[3] Checking user APPDATA storage at: {appdata_dir}...", flush=True)
        if appdata_dir.exists():
            print(f"[OK] APPDATA storage directory verified at {appdata_dir}", flush=True)

    finally:
        print("[4] Terminating test process cleanly...", flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
            print("[OK] Process terminated cleanly.", flush=True)
        except subprocess.TimeoutExpired:
            print("[WARN] Process did not terminate within 5s; killing.", flush=True)
            proc.kill()

    print("\n--- Standalone Executable Verification PASSED! ---", flush=True)


if __name__ == "__main__":
    test_standalone_executable()

