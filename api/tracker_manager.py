"""
api/tracker_manager.py — Process lifecycle manager for Time Tracker AI.

Safely starts, stops, and queries the background tracking engine (main.py).
Prevents duplicate instances using Windows mutex inspection and process scanning.
Ensures observations are closed cleanly in tracker.db upon stopping.
"""

from __future__ import annotations

import ctypes
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
from api.activity_intelligence import derive_specific_activity

_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("TIME_TRACKER_DB_PATH", _ROOT / "tracker.db"))
TRACKER_LOG_PATH = Path(os.environ.get("TIME_TRACKER_LOG_PATH", DB_PATH.parent / "tracker.log"))
MUTEX_NAME = r"Local\TimeTrackerV4"

# Global lock to synchronize start/stop operations within the API server
_manager_lock = threading.Lock()

# Reference to the subprocess if launched by this manager
_managed_tracker_proc: Optional[subprocess.Popen] = None
_managed_browser_proc: Optional[subprocess.Popen] = None

# Crash and unexpected exit tracking
_intentional_stop: bool = False
_last_exit_code: Optional[int] = None
_last_exit_message: Optional[str] = None


def get_python_executable() -> str:
    """
    Return the project virtual environment Python executable if available.
    Prevents running with base system Python which may lack installed dependencies.
    """
    venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _read_last_log_error(max_lines: int = 5) -> str:
    """Read trailing non-empty lines from tracker.log to capture error context."""
    if not TRACKER_LOG_PATH.exists():
        return ""
    try:
        with open(TRACKER_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]
        return " | ".join(lines[-max_lines:]) if lines else ""
    except Exception:
        return ""


def get_idle_seconds() -> float:
    """Return user inactivity time in seconds via Windows GetLastInputInfo."""
    if sys.platform != "win32":
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        elapsed = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        return elapsed / 1000.0
    except Exception:
        return 0.0


def is_mutex_active() -> bool:
    """Check if the named Windows mutex for the tracker is currently held."""
    if sys.platform != "win32":
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE

    # SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenMutexW(0x00100000, False, MUTEX_NAME)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def find_tracker_processes() -> list[psutil.Process]:
    """Find any processes running background tracking (main.py in dev or --tracker-only in packaged)."""
    matches = []
    current_pid = os.getpid()

    cli_subcommands = {
        "timeline", "--timeline", "-t",
        "report", "--report", "-r",
        "activity-report", "--activity-report", "-ar",
        "ui", "--ui", "timeline-ui", "--timeline-ui",
        "help", "--help", "-h",
    }

    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.pid == current_pid:
                continue
            cmd = p.info.get("cmdline") or []
            if not cmd:
                continue

            # 1. Dedicated packaged/headless tracker process
            if any(arg == "--tracker-only" for arg in cmd):
                matches.append(p)
                continue

            # 2. Must run main.py without CLI subcommands (which are one-shot utilities)
            is_main = False
            args_after_main: list[str] = []
            for idx, arg in enumerate(cmd):
                base_name = Path(arg).name.lower() if arg else ""
                if base_name == "main.py":
                    is_main = True
                    args_after_main = [a.lower() for a in cmd[idx + 1:]]
                    break

            if is_main:
                if not any(arg in cli_subcommands for arg in args_after_main):
                    matches.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Prioritize worker processes (children in process tree or processes with active threads)
    def _safe_sort_key(proc):
        try:
            ppid = proc.ppid()
            is_child = ppid in [m.pid for m in matches]
        except Exception:
            is_child = False
        try:
            threads = proc.num_threads() if callable(getattr(proc, "num_threads", None)) else 1
            if not isinstance(threads, (int, float)):
                threads = 1
        except Exception:
            threads = 1
        return (1 if is_child else 0, threads)

    matches.sort(key=_safe_sort_key, reverse=True)

    return matches


def find_browser_tracker_processes() -> list[psutil.Process]:
    """Find any processes running browser tracker (browser_tracker.py in dev or --browser-tracker-only in packaged)."""
    matches = []
    current_pid = os.getpid()

    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.pid == current_pid:
                continue
            cmd = p.info.get("cmdline") or []
            if not cmd:
                continue
            if any(arg == "--browser-tracker-only" for arg in cmd) or any(Path(arg).name.lower() == "browser_tracker.py" for arg in cmd):
                matches.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return matches


def is_tracking_active() -> bool:
    """Return True if background tracking is actively running."""
    global _managed_tracker_proc, _last_exit_code, _last_exit_message

    # 1. Check managed process object
    if _managed_tracker_proc is not None:
        if _managed_tracker_proc.poll() is None:
            return True
        else:
            code = _managed_tracker_proc.returncode
            _managed_tracker_proc = None
            if not _intentional_stop:
                _last_exit_code = code
                detail = _read_last_log_error()
                _last_exit_message = (
                    f"Tracker process exited unexpectedly with code {code}."
                    + (f" Error: {detail}" if detail else "")
                )

    # 2. Check Windows mutex
    if is_mutex_active():
        return True

    # 3. Check for any running main.py process
    if find_tracker_processes():
        return True

    return False


def get_active_task() -> Optional[dict]:
    """
    Return the most recent observation from tracker.db to detect active task changes.
    Fast indexed query (ORDER BY id DESC LIMIT 1).
    """
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM observations
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.close()
            return None

        cat_id = None
        cat_name = None
        try:
            cat_row = conn.execute(
                """
                SELECT c.id, c.name
                FROM session_categories sc
                JOIN categories c ON c.id = sc.category_id
                WHERE sc.session_key = ?
                """,
                (f"{row['app']}_{row['id']}",)
            ).fetchone()
            if cat_row:
                cat_id = cat_row["id"]
                cat_name = cat_row["name"]
        except Exception:
            pass

        conn.close()
        user_task = None
        if "task" in row.keys() and row["task"]:
            user_task = str(row["task"]).strip() or None

        act_info = derive_specific_activity(
            app=row["app"] or "",
            title=row["title"] or "",
            task=user_task,
            category_name=cat_name,
        )

        return {
            "observation_id": row["id"],
            "kind": row["kind"],
            "app": row["app"],
            "title": row["title"],
            "start_time": row["start_time"],
            "is_open": row["end_time"] is None,
            "user_task": user_task,
            "activity_name": act_info["activity_name"],
            "specific_task": act_info["specific_task"],
            "site_name": act_info["site_name"],
            "context_label": act_info["context_label"],
            "is_browser": act_info["is_browser"],
            "category_id": cat_id,
            "category_name": cat_name,
        }
    except Exception:
        return None


def assign_active_task(task_name: str, category_id: Optional[int] = None, observation_id: Optional[int] = None) -> Optional[dict]:
    """
    Assign a meaningful user-defined task/activity name to the active observation.
    Preserves raw observations, raw app, raw window title, and timestamps.
    """
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3)
        conn.row_factory = sqlite3.Row
        
        if observation_id is None:
            latest = conn.execute("SELECT id, app, title FROM observations ORDER BY id DESC LIMIT 1").fetchone()
            if not latest:
                conn.close()
                return None
            target_id = latest["id"]
            app = latest["app"]
        else:
            target = conn.execute("SELECT id, app, title FROM observations WHERE id = ?", (observation_id,)).fetchone()
            if not target:
                conn.close()
                return None
            target_id = target["id"]
            app = target["app"]

        clean_name = task_name.strip()
        conn.execute("UPDATE observations SET task = ? WHERE id = ?", (clean_name, target_id))
        
        now_iso = datetime.now(timezone.utc).isoformat()
        if clean_name:
            try:
                conn.execute("INSERT OR IGNORE INTO tasks (name) VALUES (?)", (clean_name,))
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES ('current_active_task', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (clean_name, now_iso),
                )
            except Exception:
                pass
        else:
            try:
                conn.execute("DELETE FROM app_settings WHERE key IN ('current_active_task', 'current_planned_task', 'current_focus_block_id', 'current_active_category_id')")
            except Exception:
                pass
                
        if category_id is not None:
            try:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES ('current_active_category_id', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (str(category_id), now_iso),
                )
            except Exception:
                pass
            keys_to_save = [f"{app}_{target_id}", f"obs_{target_id}"]
            try:
                from ai_timeline import make_session_key
                keys_to_save.append(make_session_key("active", app, target_id))
            except Exception:
                pass

            for s_key in set(keys_to_save):
                try:
                    conn.execute(
                        """
                        INSERT INTO session_categories (session_key, category_id, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(session_key) DO UPDATE SET category_id = excluded.category_id, updated_at = excluded.updated_at
                        """,
                        (s_key, category_id, now_iso),
                    )
                except Exception:
                    pass

        conn.commit()
        conn.close()
        return get_active_task()
    except Exception:
        return None


def clear_active_task() -> bool:
    """Clear active task and active focus block settings."""
    if not DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3)
        conn.execute("DELETE FROM app_settings WHERE key IN ('current_active_task', 'current_planned_task', 'current_focus_block_id', 'current_active_category_id')")
        latest = conn.execute("SELECT id FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        if latest:
            conn.execute("UPDATE observations SET task = NULL WHERE id = ?", (latest[0],))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_tracking_status() -> dict:
    """Return comprehensive status of the tracking engine."""
    active = is_tracking_active()
    pid = None

    if _managed_tracker_proc is not None and _managed_tracker_proc.poll() is None:
        pid = _managed_tracker_proc.pid
    else:
        procs = find_tracker_processes()
        if procs:
            pid = procs[0].pid

    active_task = get_active_task() if active else None

    if active:
        return {
            "is_tracking": True,
            "pid": pid,
            "status_text": "Tracking ON",
            "message": "Tracking is active and recording observations.",
            "active_task": active_task,
        }

    # If tracking stopped unexpectedly:
    if _last_exit_code is not None and _last_exit_code != 0:
        return {
            "is_tracking": False,
            "pid": None,
            "status_text": "Tracking OFF",
            "message": _last_exit_message or f"Tracker stopped unexpectedly (exit code {_last_exit_code}).",
            "active_task": None,
        }

    return {
        "is_tracking": False,
        "pid": None,
        "status_text": "Tracking OFF",
        "message": "Tracking is stopped.",
        "active_task": None,
    }


def _recover_dangling_observations() -> int:
    """Close any unclosed observations in tracker.db to ensure data integrity."""
    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    closed_count = 0
    try:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        rows = conn.execute(
            "SELECT id, start_time FROM observations WHERE end_time IS NULL"
        ).fetchall()

        for obs_id, start_str in rows:
            try:
                start_dt = datetime.fromisoformat(start_str)
                gap_to_now = (now_dt - start_dt).total_seconds()

                # Check for activity events during this observation before shutdown
                last_ev = conn.execute(
                    "SELECT MAX(timestamp) FROM activity_events WHERE timestamp >= ? AND timestamp <= ?",
                    (start_str, now_iso),
                ).fetchone()

                if last_ev and last_ev[0]:
                    last_ev_dt = datetime.fromisoformat(last_ev[0])
                    dur = max(1.0, (last_ev_dt - start_dt).total_seconds())
                    end_iso = last_ev[0]
                elif gap_to_now <= 15.0:
                    # Recently started in an ongoing tracker session
                    dur = max(1.0, gap_to_now)
                    end_iso = now_iso
                else:
                    # Stale observation from earlier run/shutdown: cap to polling heartbeat (3.0s)
                    dur = 3.0
                    end_iso = (start_dt + timedelta(seconds=3)).isoformat()
            except Exception:
                dur = 3.0
                end_iso = now_iso

            conn.execute(
                "UPDATE observations SET end_time = ?, duration_seconds = ? WHERE id = ?",
                (end_iso, dur, obs_id),
            )
            closed_count += 1

        if closed_count > 0:
            conn.commit()
    except sqlite3.OperationalError:
        # Table observations does not exist yet (e.g. fresh install or pre-migration database)
        return 0
    finally:
        conn.close()

    return closed_count


def wait_for_tracker_startup(proc: subprocess.Popen, timeout: float = 4.0) -> bool:
    """
    Perform a bounded startup handshake to verify tracking engine initialization.
    Confirms that the tracker has acquired its system mutex without prematurely exiting.
    If the process exits prematurely (including exit code 0) or times out, collects diagnostics,
    cleans up the process, and raises a descriptive RuntimeError.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # 1. Detect premature process exit
        poll_res = proc.poll()
        if poll_res is not None:
            err_code = proc.returncode
            detail = _read_last_log_error()
            err_msg = f"Tracker process exited prematurely with code {err_code}." + (f" Details: {detail}" if detail else "")
            raise RuntimeError(err_msg)

        # 2. Check if tracker initialized by holding its named mutex
        if is_mutex_active():
            if proc.poll() is None:
                return True

        # Fallback for non-Windows or testing environments where mutex is mocked or unavailable
        if sys.platform != "win32" and proc.poll() is None:
            return True

        time.sleep(0.08)

    # 3. Timeout handling
    if proc.poll() is not None:
        err_code = proc.returncode
        detail = _read_last_log_error()
        raise RuntimeError(f"Tracker process exited with code {err_code} before completing startup." + (f" Details: {detail}" if detail else ""))

    # Process is still running but did not acquire mutex within bounded timeout; terminate cleanly
    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:
        pass

    detail = _read_last_log_error()
    raise RuntimeError(f"Tracker process failed to initialize within {timeout:.1f}s." + (f" Details: {detail}" if detail else ""))


def start_tracking() -> dict:
    """
    Start the background tracking process if not already running.
    Prevents duplicate instances.
    """
    global _managed_tracker_proc, _managed_browser_proc
    global _intentional_stop, _last_exit_code, _last_exit_message

    with _manager_lock:
        if is_tracking_active():
            status = get_tracking_status()
            status["message"] = "Tracker is already running."
            return status

        _intentional_stop = False
        _last_exit_code = None
        _last_exit_message = None

        # Close any previous unclosed observations before starting
        _recover_dangling_observations()

        is_frozen = getattr(sys, "frozen", False)
        python_exe = get_python_executable()
        main_script = str(_ROOT / "main.py")
        browser_script = str(_ROOT / "browser_tracker.py")

        env = os.environ.copy()
        env["TIME_TRACKER_DB_PATH"] = str(DB_PATH)

        if is_frozen:
            # In packaged mode, invoke frozen executable with dedicated headless flags
            tracker_cmd = [sys.executable, "--tracker-only"]
            browser_cmd = [sys.executable, "--browser-tracker-only"]
            cwd = str(Path(sys.executable).parent)
        else:
            # In development mode, invoke python scripts directly
            tracker_cmd = [python_exe, main_script]
            browser_cmd = [python_exe, browser_script]
            cwd = str(_ROOT)

        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP is required to handle CTRL_BREAK_EVENT
            # 0x08000000 = CREATE_NO_WINDOW ensures no stray console interference
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000

        proc = None
        try:
            # Append output to tracker.log to preserve crash tracebacks and diagnostic logs
            log_file = open(TRACKER_LOG_PATH, "a", encoding="utf-8", buffering=1)
            log_file.write(f"\n--- Tracking started at {datetime.now(timezone.utc).isoformat()} (Command: {' '.join(tracker_cmd)}) ---\n")
            log_file.flush()

            # Launch main activity tracker
            proc = subprocess.Popen(
                tracker_cmd,
                cwd=cwd,
                env=env,
                creationflags=creationflags,
                stdout=log_file,
                stderr=log_file,
            )

            # Perform reliable startup handshake (waits for mutex acquisition)
            wait_for_tracker_startup(proc, timeout=4.0)

            # Only assign to managed reference once verified active and initialized
            _managed_tracker_proc = proc

            # Optionally launch browser tracker if not already running
            if not find_browser_tracker_processes():
                if is_frozen or Path(browser_script).exists():
                    try:
                        _managed_browser_proc = subprocess.Popen(
                            browser_cmd,
                            cwd=cwd,
                            env=env,
                            creationflags=creationflags,
                            stdout=log_file,
                            stderr=log_file,
                        )
                    except Exception:
                        _managed_browser_proc = None

            # Trigger non-blocking missed-activity recovery check
            try:
                def _check_gap():
                    try:
                        import api.notification_engine as notif_engine
                        c = sqlite3.connect(str(DB_PATH), timeout=5)
                        c.row_factory = sqlite3.Row
                        notif_engine.detect_missed_activity_gap(c)
                        c.close()
                    except Exception:
                        pass
                threading.Thread(target=_check_gap, daemon=True).start()
            except Exception:
                pass

            return {
                "is_tracking": True,
                "pid": _managed_tracker_proc.pid,
                "status_text": "Tracking ON",
                "message": "Tracking started successfully.",
            }

        except Exception as e:
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            _managed_tracker_proc = None
            raise RuntimeError(f"Failed to start tracker: {e}") from e


def stop_tracking() -> dict:
    """
    Stop all running tracking processes cleanly.
    Ensures observations are closed in database and mutex is released.
    """
    global _managed_tracker_proc, _managed_browser_proc
    global _intentional_stop, _last_exit_code, _last_exit_message

    with _manager_lock:
        _intentional_stop = True
        _last_exit_code = None
        _last_exit_message = None

        if not is_tracking_active():
            _recover_dangling_observations()
            return {
                "is_tracking": False,
                "pid": None,
                "status_text": "Tracking OFF",
                "message": "Tracker is already stopped.",
            }

        # 1. Stop managed tracker process if active
        if _managed_tracker_proc is not None:
            try:
                if _managed_tracker_proc.poll() is None:
                    if sys.platform == "win32":
                        _managed_tracker_proc.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        _managed_tracker_proc.send_signal(signal.SIGINT)

                    try:
                        _managed_tracker_proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        _managed_tracker_proc.terminate()
                        _managed_tracker_proc.wait(timeout=2.0)
            except Exception:
                pass
            finally:
                _managed_tracker_proc = None

        # 2. Stop managed browser tracker if active
        if _managed_browser_proc is not None:
            try:
                if _managed_browser_proc.poll() is None:
                    _managed_browser_proc.terminate()
                    _managed_browser_proc.wait(timeout=2.0)
            except Exception:
                pass
            finally:
                _managed_browser_proc = None

        # 3. Stop any unmanaged tracker processes found running main.py
        for p in find_tracker_processes():
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # 4. Stop any unmanaged browser_tracker processes
        for p in find_browser_tracker_processes():
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Wait up to 1 second for OS to release mutex
        for _ in range(10):
            if not is_mutex_active():
                break
            time.sleep(0.1)

        # 5. Clean up any unclosed observation in tracker.db
        _recover_dangling_observations()

        return {
            "is_tracking": False,
            "pid": None,
            "status_text": "Tracking OFF",
            "message": "Tracking stopped successfully.",
        }

