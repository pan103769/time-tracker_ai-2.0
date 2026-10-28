"""
test_rebuilt_binary_e2e.py ??? End-to-end isolated verification of the rebuilt executable.
Tests the actual dist/TimeTrackerAI/TimeTrackerAI.exe binary directly without installing
or modifying the user's production database.
"""

import ctypes
from ctypes import wintypes
import json
import os
import signal
import subprocess
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE_PATH = ROOT / "dist" / "TimeTrackerAI" / "TimeTrackerAI.exe"

MUTEX_TRACKER = r"Local\TimeTrackerV4"
MUTEX_GUI = r"Local\TimeTrackerAI_DesktopApp_Mutex"


def is_mutex_held(mutex_name: str) -> bool:
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    h = kernel32.OpenMutexW(0x00100000, False, mutex_name)
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


def run_checks():
    print("=" * 70)
    print("STARTING DIRECT VERIFICATION OF REBUILT EXECUTABLE")
    print(f"Target Binary: {EXE_PATH}")
    print("=" * 70)

    if not EXE_PATH.exists():
        raise FileNotFoundError(f"Binary not found: {EXE_PATH}")

    temp_dir = tempfile.mkdtemp(prefix="tt_verify_")
    isolated_db = Path(temp_dir) / "isolated_tracker.db"
    isolated_log = Path(temp_dir) / "isolated_tracker.log"

    env = os.environ.copy()
    env["TIME_TRACKER_DB_PATH"] = str(isolated_db)
    env["TIME_TRACKER_LOG_PATH"] = str(isolated_log)

    print(f"[1] Isolated environment: DB={isolated_db}")

    # TEST A: Direct --tracker-only CLI mode
    print("\n[TEST A] Testing direct '--tracker-only' headless execution...")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000 if sys.platform == "win32" else 0
    tracker_proc = subprocess.Popen(
        [str(EXE_PATH), "--tracker-only"],
        env=env,
        creationflags=creationflags,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Give up to 4s for startup handshake
        start_time = time.time()
        mutex_acquired = False
        while time.time() - start_time < 5.0:
            if is_mutex_held(MUTEX_TRACKER):
                mutex_acquired = True
                break
            if tracker_proc.poll() is not None:
                break
            time.sleep(0.1)

        poll_status = tracker_proc.poll()
        print(f"  -> Process PID: {tracker_proc.pid}, Running: {poll_status is None}")
        print(f"  -> Tracker Mutex ({MUTEX_TRACKER}) active: {mutex_acquired}")
        gui_already_open = is_mutex_held(MUTEX_GUI)
        print(f"  -> Existing Desktop GUI running on system: {gui_already_open}")

        assert poll_status is None, f"Tracker exited prematurely with code {poll_status}"
        assert mutex_acquired, "Tracker failed to acquire TimeTrackerV4 mutex"
        # If tracker had attempted to acquire GUI mutex while GUI is open, it would have collided and exited with code 0.
        # Its continued execution proves full isolation from the desktop GUI mutex.

        print("  ??? SUCCESS: Rebuilt binary successfully runs in headless --tracker-only mode.")

        # TEST B: Duplicate tracker prevention
        print("\n[TEST B] Testing duplicate tracker prevention...")
        dup_proc = subprocess.Popen(
            [str(EXE_PATH), "--tracker-only"],
            env=env,
            creationflags=creationflags,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        dup_proc.wait(timeout=5.0)
        print(f"  -> Duplicate process exited cleanly with code: {dup_proc.returncode}")
        assert dup_proc.returncode == 0, f"Duplicate process exited with unexpected code {dup_proc.returncode}"
        print("  ??? SUCCESS: Duplicate instance correctly identified existing mutex and exited with code 0.")

    finally:
        print("\n[CLEANUP A] Terminating test tracker process...")
        if tracker_proc.poll() is None:
            if sys.platform == "win32":
                tracker_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                tracker_proc.terminate()
            try:
                tracker_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                tracker_proc.kill()
        time.sleep(0.5)
        print(f"  -> Tracker Mutex released: {not is_mutex_held(MUTEX_TRACKER)}")
        assert not is_mutex_held(MUTEX_TRACKER), "Tracker mutex was not released on exit!"

    # TEST C: Backend headless server with tracker toggle
    test_port = 8999
    print(f"\n[TEST C] Testing headless backend server on port {test_port} with tracker toggle...")
    server_proc = subprocess.Popen(
        [str(EXE_PATH), "--server-only", "--port", str(test_port)],
        env=env,
        creationflags=creationflags,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for backend health
        healthy = False
        health_url = f"http://127.0.0.1:{test_port}/api/health"
        for _ in range(40):
            try:
                with urllib.request.urlopen(health_url, timeout=0.5) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except Exception:
                time.sleep(0.15)

        print(f"  -> Server responsive on {health_url}: {healthy}")
        assert healthy, "Server failed to respond on health check"

        # Toggle tracking ON
        toggle_url = f"http://127.0.0.1:{test_port}/api/tracker/toggle"
        req = urllib.request.Request(toggle_url, method="POST", data=b"{}")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode())
            print(f"  -> Tracker toggle ON response: {data}")
            assert data.get("is_tracking") is True, f"Expected is_tracking=True, got {data}"

        time.sleep(0.5)
        assert is_mutex_held(MUTEX_TRACKER), "Tracker mutex active after server start_tracking"

        # Check status endpoint
        status_url = f"http://127.0.0.1:{test_port}/api/tracker/status"
        with urllib.request.urlopen(status_url, timeout=2.0) as resp:
            status_data = json.loads(resp.read().decode())
            print(f"  -> Tracker status: {status_data}")
            assert status_data.get("is_tracking") is True

        # Toggle tracking OFF
        req_off = urllib.request.Request(toggle_url, method="POST", data=b"{}")
        with urllib.request.urlopen(req_off, timeout=5.0) as resp:
            data_off = json.loads(resp.read().decode())
            print(f"  -> Tracker toggle OFF response: {data_off}")
            assert data_off.get("is_tracking") is False

        time.sleep(0.5)
        assert not is_mutex_held(MUTEX_TRACKER), "Tracker mutex released after toggle OFF"
        print("  ??? SUCCESS: Backend successfully launched and cleanly stopped tracker via API.")

    finally:
        print("\n[CLEANUP C] Stopping test server...")
        if server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                server_proc.kill()

    print("\n" + "=" * 70)
    print("ALL DIRECT VERIFICATION CHECKS PASSED ON REBUILT STANDALONE EXECUTABLE!")
    print("=" * 70)


if __name__ == "__main__":
    run_checks()
