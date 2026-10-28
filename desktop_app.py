"""
desktop_app.py — Standalone Native Desktop Window Wrapper for Time Tracker AI 2.

Displays the React dashboard inside a dedicated Windows desktop window using PyWebView.
Preserves existing FastAPI backend, tracking architecture, database, and dev workflows.

Usage:
    python desktop_app.py          # Launches desktop window using production built UI
    python desktop_app.py --dev    # Launches desktop window pointing to Vite dev server (5173)
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
import subprocess
import urllib.request
import urllib.error
import urllib.parse

# Bootstrap project root
if getattr(sys, "frozen", False):
    _ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    _ROOT = Path(__file__).resolve().parent

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("desktop_app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MUTEX_NAME = r"Local\TimeTrackerAI_DesktopApp_Mutex"
DEFAULT_BACKEND_PORT = 8000
VITE_DEV_PORT = 5173
WINDOW_TITLE = "Time Tracker AI"
WINDOW_WIDTH = 1320
WINDOW_HEIGHT = 860
WINDOW_MIN_WIDTH = 1024
WINDOW_MIN_HEIGHT = 680
BG_COLOR = "#080D17"

SILENT_ACTIONS = {
    "snooze_block",
    "skip_block",
    "dismiss_missed_block",
    "complete_block",
    "snooze_idle_5",
    "snooze_mismatch_15",
    "snooze_mismatch_30",
    "snooze_gap",
    "skip_gap",
    "dismiss",
}


def parse_protocol_uri(raw_uri: str) -> tuple[str, dict, bool]:
    """
    Parse a timetracker:// URI into (action, params_dict, is_silent).
    Examples:
        timetracker://navigate?action=open_planner&date=2026-10-26
        timetracker://action?name=snooze_block&block_id=123&minutes=5
        timetracker://action/snooze_idle_5
    """
    s = raw_uri.strip().strip('"').strip("'")
    if not s.lower().startswith("timetracker:"):
        return ("overview", {}, False)

    parsed = urllib.parse.urlparse(s)
    query = urllib.parse.parse_qs(parsed.query)
    params = {k: v[0] if len(v) == 1 else v for k, v in query.items()}

    # Determine action name
    action = params.get("action") or params.get("name")
    if not action:
        path_clean = parsed.path.strip("/")
        if path_clean:
            action = path_clean
        elif parsed.netloc and parsed.netloc not in ("navigate", "action"):
            action = parsed.netloc
        else:
            action = "overview"

    action = action.strip().lower()
    is_silent = action in SILENT_ACTIONS
    return (action, params, is_silent)


def find_desktop_window_hwnd() -> int:
    """Locate the HWND of the running Time Tracker AI desktop window."""
    if sys.platform != "win32":
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd and user32.IsWindow(hwnd):
            return int(hwnd)

        # Fallback to EnumWindows to find matching title
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(h, lparam):
            if user32.IsWindowVisible(h):
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buf, length + 1)
                    if WINDOW_TITLE in buf.value:
                        found.append(int(h))
                        return False
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found[0] if found else 0
    except Exception:
        return 0


def force_foreground_window(hwnd: int):
    """Bring the existing Time Tracker AI window to foreground reliably."""
    if not hwnd or sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)

        curr_thread_id = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread_id = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_thread_id = user32.GetWindowThreadProcessId(hwnd, None)

        attached = False
        if fg_thread_id and fg_thread_id != curr_thread_id:
            attached = bool(user32.AttachThreadInput(curr_thread_id, target_thread_id, True))

        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)

        if attached:
            user32.AttachThreadInput(curr_thread_id, target_thread_id, False)
        logger.info("Brought desktop app window HWND %s to foreground.", hwnd)
    except Exception as e:
        logger.warning("Could not bring window to foreground: %s", e)


def forward_activation_request(action: str, params: dict, port: int = DEFAULT_BACKEND_PORT) -> bool:
    """Forward an activation or notification action to the running FastAPI server."""
    url = f"http://127.0.0.1:{port}/api/desktop/activate"
    data = json.dumps({"action": action, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "TimeTrackerAI-DesktopForwarder",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Could not forward action '%s' to %s: %s", action, url, e)
        return False


def execute_silent_action_direct(action: str, params: dict, port: int = DEFAULT_BACKEND_PORT):
    """Execute a silent action directly against running backend or SQLite."""
    # First attempt: if backend is running on port, forward to HTTP endpoint
    if is_backend_healthy(port, timeout=0.5):
        forward_activation_request(action, params, port)
        return

    # Second attempt: backend is not running, so update SQLite directly
    try:
        import sqlite3
        from activity_report import DB_PATH
        import api.notification_engine as notif_engine

        db_path = DB_PATH
        if os.environ.get("TIME_TRACKER_DB_PATH"):
            db_path = Path(os.environ["TIME_TRACKER_DB_PATH"])

        with sqlite3.connect(str(db_path), timeout=5) as conn:
            if action == "snooze_block":
                b_id = int(params.get("block_id", 0))
                mins = int(params.get("minutes", 5))
                if b_id:
                    notif_engine.snooze_time_block_reminder(conn, b_id, minutes=mins)
            elif action in ("skip_block", "dismiss_missed_block"):
                b_id = int(params.get("block_id", 0))
                if b_id:
                    notif_engine.skip_time_block(conn, b_id)
            elif action in ("snooze_idle_5", "snooze_mismatch_15", "snooze_mismatch_30"):
                mins = 30 if "30" in action else (15 if "15" in action else 5)
                if "idle" in action:
                    notif_engine.snooze_idle_alerts(mins)
                else:
                    notif_engine.snooze_mismatch_alerts(mins)
        logger.info("Directly executed silent action '%s' in SQLite.", action)
    except Exception as e:
        logger.warning("Could not directly execute silent action '%s': %s", action, e)


def get_work_area() -> tuple[int, int, int, int] | None:
    """Retrieve the Windows primary monitor work area (screen minus taskbar)."""
    if sys.platform != "win32":
        return None
    try:
        rc = wintypes.RECT()
        user32 = ctypes.windll.user32
        SPI_GETWORKAREA = 0x0030
        if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rc), 0):
            return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top
    except Exception:
        pass
    return None


def setup_environment():
    """Configure database and storage paths for frozen vs development mode."""
    if getattr(sys, "frozen", False):
        custom_db = os.environ.get("TIME_TRACKER_DB_PATH")
        if custom_db:
            db_path = Path(custom_db)
            db_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            appdata = Path(os.environ.get("APPDATA", Path.home())) / "TimeTrackerAI"
            appdata.mkdir(parents=True, exist_ok=True)
            db_path = appdata / "tracker.db"
            # Seed user database from existing repository/install files if fresh install
            if not db_path.exists() or db_path.stat().st_size == 0:
                for candidate in [
                    _ROOT / "tracker.db",
                    _ROOT / "_internal" / "tracker.db",
                ]:
                    if candidate.exists() and candidate.stat().st_size > 0:
                        try:
                            import shutil
                            shutil.copy2(candidate, db_path)
                            logger.info("Initialized user database from %s", candidate)
                            break
                        except Exception as e:
                            logger.warning("Could not seed database from %s: %s", candidate, e)
            os.environ["TIME_TRACKER_DB_PATH"] = str(db_path)
        logger.info("Running packaged executable. User database: %s", db_path)
    else:
        # Development mode: preserve repository tracker.db
        logger.info("Running in development mode from repository root: %s", _ROOT)

    # Ensure Windows AUMID and custom timetracker:// URI protocol are registered
    try:
        from api.windows_notifier import register_windows_app_identity
        register_windows_app_identity()
    except Exception as e:
        logger.debug("Notice: Could not register windows identity: %s", e)


def acquire_single_instance_mutex(mutex_name: str = MUTEX_NAME):
    """Ensure only one instance of the desktop window runs at a time."""
    if sys.platform != "win32":
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    mutex = kernel32.CreateMutexW(None, True, mutex_name)
    last_error = kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183

    if last_error == ERROR_ALREADY_EXISTS:
        if mutex:
            kernel32.CloseHandle(mutex)
        return None

    return mutex


def is_backend_healthy(port: int = DEFAULT_BACKEND_PORT, timeout: float = 1.0) -> bool:
    """Check if FastAPI backend health check responds successfully."""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TimeTrackerAI-DesktopWrapper"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_embedded_backend(port: int = DEFAULT_BACKEND_PORT):
    """Start uvicorn server in a background daemon thread if not already running."""
    import uvicorn
    from api.server import app as fastapi_app

    config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(
        target=server.run,
        name="embedded_uvicorn",
        daemon=True,
    )
    server_thread.start()
    return server, server_thread


def start_backend_service(port: int = DEFAULT_BACKEND_PORT):
    """Launch the backend service as a separate background process with thread fallback."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        cmd = [exe, "--server-only", "--port", str(port)]
    else:
        py_exe = sys.executable
        script = str(_ROOT / "desktop_app.py")
        cmd = [py_exe, script, "--server-only", "--port", str(port)]

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = 0x08000000  # CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        logger.info("Spawned background backend process PID %d", proc.pid)
        return proc
    except Exception as e:
        logger.warning("Could not spawn background process (%s). Falling back to embedded thread.", e)
        start_embedded_backend(port)
        return None


def wait_for_backend(port: int = DEFAULT_BACKEND_PORT, max_wait_seconds: float = 10.0) -> bool:
    """Wait until backend responds to health check or timeout expires."""
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        if is_backend_healthy(port, timeout=0.5):
            return True
        time.sleep(0.15)
    return False


def show_error_dialog(message: str, title: str = "Time Tracker AI Startup Error"):
    """Display a native Windows error dialog if startup encounters an unrecoverable issue."""
    if sys.platform == "win32":
        MB_OK = 0x00000000
        MB_ICONERROR = 0x00000010
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_OK | MB_ICONERROR)
    else:
        print(f"[{title}] {message}", file=sys.stderr)


class DesktopAppApi:
    """Python API exposed to the JavaScript frontend via window.pywebview.api."""
    def __init__(self, window=None):
        # NOTE: Attributes MUST start with an underscore so PyWebView's introspection
        # engine does not recursively crawl into native WinForms / COM object graphs.
        self._window = window
        self._is_maximized = True

    def get_window_state(self) -> dict:
        if self._window:
            form = getattr(self._window, "native", None)
            hwnd = int(form.Handle.ToInt64()) if (form and hasattr(form.Handle, "ToInt64")) else (int(form.Handle) if form else 0)
            if not hwnd:
                hwnd = find_desktop_window_hwnd()
            if hwnd:
                try:
                    rc = wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc))
                    curr_w = rc.right - rc.left
                    curr_h = rc.bottom - rc.top
                    work = get_work_area()
                    if work:
                        _, _, work_w, work_h = work
                        is_max = (abs(curr_w - work_w) <= 12 and abs(curr_h - work_h) <= 12)
                        is_min = bool(ctypes.windll.user32.IsIconic(hwnd))
                        self._is_maximized = is_max
                        return {
                            "is_desktop": True,
                            "is_maximized": is_max,
                            "is_minimized": is_min,
                        }
                except Exception:
                    pass
        return {
            "is_desktop": True,
            "is_maximized": self._is_maximized,
            "is_minimized": False,
        }

    def minimize_window(self) -> dict:
        if self._window:
            self._window.minimize()
        return {"status": "ok", "action": "minimize"}

    def maximize_window(self) -> dict:
        if self._window:
            form = getattr(self._window, "native", None)
            hwnd = int(form.Handle.ToInt64()) if (form and hasattr(form.Handle, "ToInt64")) else (int(form.Handle) if form else 0)
            if not hwnd:
                hwnd = find_desktop_window_hwnd()
            if hwnd:
                work_area = get_work_area()
                if work_area:
                    x, y, w, h = work_area
                    ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, w, h, 0x0040)
                    self._is_maximized = True
                    return {"status": "ok", "action": "maximize", "is_maximized": True}
            self._window.maximize()
            self._is_maximized = True
        return {"status": "ok", "action": "maximize", "is_maximized": True}

    def restore_window(self) -> dict:
        if self._window:
            form = getattr(self._window, "native", None)
            hwnd = int(form.Handle.ToInt64()) if (form and hasattr(form.Handle, "ToInt64")) else (int(form.Handle) if form else 0)
            if not hwnd:
                hwnd = find_desktop_window_hwnd()
            if hwnd:
                work_area = get_work_area()
                if work_area:
                    x, y, w, h = work_area
                    norm_w, norm_h = 1320, 860
                    norm_x = x + (w - norm_w) // 2
                    norm_y = y + (h - norm_h) // 2
                    ctypes.windll.user32.SetWindowPos(hwnd, 0, norm_x, norm_y, norm_w, norm_h, 0x0040)
                    self._is_maximized = False
                    return {"status": "ok", "action": "restore", "is_maximized": False}
            self._window.restore()
            self._is_maximized = False
        return {"status": "ok", "action": "restore", "is_maximized": False}

    def toggle_maximize_window(self) -> dict:
        if self._is_maximized:
            return self.restore_window()
        else:
            return self.maximize_window()

    def close_window(self) -> dict:
        if self._window:
            form = getattr(self._window, "native", None)
            if form:
                try:
                    form.Close()
                    return {"status": "ok", "action": "close"}
                except Exception:
                    pass
            self._window.destroy()
        return {"status": "ok", "action": "close"}

    def quit_app(self):
        """Cleanly stop tracking and close the desktop app."""
        try:
            import api.tracker_manager as tracker_mgr
            tracker_mgr.stop_tracking()
        except Exception:
            pass
        if self._window:
            self._window.destroy()


def main():
    parser = argparse.ArgumentParser(description="Time Tracker AI Desktop Window")
    parser.add_argument("--dev", action="store_true", help="Connect to Vite dev server on port 5173")
    parser.add_argument("--port", type=int, default=DEFAULT_BACKEND_PORT, help="Backend port (default 8000)")
    parser.add_argument("--server-only", action="store_true", help="Run FastAPI backend headlessly without GUI")
    parser.add_argument("--tracker-only", action="store_true", help="Run background tracking daemon headlessly")
    parser.add_argument("--browser-tracker-only", action="store_true", help="Run browser URL tracking daemon headlessly")
    args, unknown = parser.parse_known_args()

    setup_environment()

    # If invoked in headless server mode, run FastAPI immediately
    if args.server_only:
        import uvicorn
        from api.server import app as fastapi_app
        logger.info("Starting headless Time Tracker AI backend on port %d...", args.port)
        uvicorn.run(fastapi_app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
        sys.exit(0)

    # If invoked in headless tracker mode, run tracking engine immediately
    if args.tracker_only:
        logger.info("Starting headless Time Tracker AI activity tracker...")
        import main
        sys.argv = [sys.argv[0]]
        main.main()
        sys.exit(0)

    # If invoked in headless browser tracker mode, run browser tracker immediately
    if args.browser_tracker_only:
        logger.info("Starting headless Time Tracker AI browser tracker...")
        import browser_tracker
        sys.argv = [sys.argv[0]]
        browser_tracker.main()
        sys.exit(0)

    # Detect custom protocol URI argument (e.g. from Windows toast click or timetracker://)
    protocol_arg = None
    all_args = list(sys.argv[1:]) + list(unknown)
    for item in all_args:
        item_str = str(item).strip().strip('"').strip("'")
        if item_str.lower().startswith("timetracker:"):
            protocol_arg = item_str
            break

    # Enforce single instance for GUI
    mutex = acquire_single_instance_mutex()
    if mutex is None and sys.platform == "win32":
        logger.info("Another instance of Time Tracker AI Desktop is already running.")
        if protocol_arg:
            action, params, is_silent = parse_protocol_uri(protocol_arg)
            logger.info("Forwarding action '%s' to active instance...", action)
            forward_activation_request(action, params, port=args.port)
            if not is_silent:
                hwnd = find_desktop_window_hwnd()
                if hwnd:
                    force_foreground_window(hwnd)
        else:
            hwnd = find_desktop_window_hwnd()
            if hwnd:
                force_foreground_window(hwnd)
        sys.exit(0)

    # Primary instance running
    action = None
    params = {}
    if protocol_arg:
        action, params, is_silent = parse_protocol_uri(protocol_arg)
        if is_silent:
            logger.info("Executing silent action '%s' for primary instance without opening GUI...", action)
            execute_silent_action_direct(action, params, port=args.port)
            if mutex and sys.platform == "win32":
                ctypes.windll.kernel32.ReleaseMutex(mutex)
                ctypes.windll.kernel32.CloseHandle(mutex)
            sys.exit(0)

    try:
        import webview
    except ImportError:
        show_error_dialog(
            "PyWebView is not installed in the Python environment.\n"
            "Please run: pip install pywebview"
        )
        sys.exit(1)

    port = args.port
    spawned_backend_proc = None

    # 1. Check or start backend
    if not is_backend_healthy(port):
        logger.info("FastAPI backend is not running. Starting backend service on port %d...", port)
        spawned_backend_proc = start_backend_service(port)
        if not wait_for_backend(port, max_wait_seconds=12.0):
            show_error_dialog(
                f"Failed to connect to local Time Tracker AI service at 127.0.0.1:{port}.\n"
                "The server did not respond within 12 seconds. Check tracker.log for details."
            )
            sys.exit(1)
        logger.info("Backend service is healthy.")
    else:
        logger.info("Found existing healthy Time Tracker AI service on 127.0.0.1:%d.", port)

    # 2. Determine target URL with query params if interactive action was requested
    query_str = ""
    if action and action != "overview":
        q = dict(params)
        q["action"] = action
        query_str = "?" + urllib.parse.urlencode(q)
    elif params:
        query_str = "?" + urllib.parse.urlencode(params)

    base_port = VITE_DEV_PORT if args.dev else port
    target_url = f"http://127.0.0.1:{base_port}/{query_str}"
    logger.info("Desktop window target URL: %s", target_url)

    # 3. Locate icon asset
    icon_path = _ROOT / "assets" / "time_tracker_ai.ico"
    if not icon_path.exists():
        alt_icon = _ROOT / "_internal" / "assets" / "time_tracker_ai.ico"
        if alt_icon.exists():
            icon_path = alt_icon
    icon_arg = str(icon_path) if icon_path.exists() else None

    # 4. Define window lifecycle callbacks
    def on_closing():
        """Handle window close event with sensible productivity lifecycle policy."""
        try:
            import api.tracker_manager as tracker_mgr
            if tracker_mgr.is_tracking_active():
                MB_YESNOCANCEL = 0x00000003
                MB_ICONQUESTION = 0x00000020
                IDYES = 6
                IDNO = 7
                IDCANCEL = 2
                choice = ctypes.windll.user32.MessageBoxW(
                    0,
                    "Activity tracking is currently active.\n\n"
                    "Do you want to stop tracking and exit Time Tracker AI completely?\n\n"
                    "• Click 'Yes' to stop tracking and quit completely.\n"
                    "• Click 'No' to keep tracking running in the background.\n"
                    "• Click 'Cancel' to keep the window open.",
                    WINDOW_TITLE,
                    MB_YESNOCANCEL | MB_ICONQUESTION,
                )
                if choice == IDCANCEL:
                    return False  # Prevent closing window
                elif choice == IDYES:
                    logger.info("User requested full shutdown. Stopping tracking...")
                    tracker_mgr.stop_tracking()
                    if spawned_backend_proc:
                        try:
                            spawned_backend_proc.terminate()
                        except Exception:
                            pass
                    return True
                elif choice == IDNO:
                    logger.info("Window closed. Background tracking continues.")
                    return True
            else:
                # Tracking was stopped; clean exit immediately
                if spawned_backend_proc:
                    try:
                        spawned_backend_proc.terminate()
                    except Exception:
                        pass
                return True
        except Exception as e:
            logger.warning("Error in closing handler: %s", e)
            return True

    # 5. Determine window positioning: launch maximized to Windows work area (taskbar remains visible)
    work_area = get_work_area()
    if work_area:
        init_x, init_y, init_w, init_h = work_area
        logger.info("Initializing desktop window to Windows work area: %dx%d at (%d, %d)", init_w, init_h, init_x, init_y)
    else:
        init_x, init_y, init_w, init_h = None, None, WINDOW_WIDTH, WINDOW_HEIGHT

    desktop_api = DesktopAppApi()

    # 6. Create frameless PyWebView Window with custom integrated title bar
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=target_url,
        x=init_x,
        y=init_y,
        width=init_w,
        height=init_h,
        min_size=(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT),
        background_color=BG_COLOR,
        frameless=True,
        easy_drag=False,
        shadow=True,
        js_api=desktop_api,
        confirm_close=False,
        text_select=True,
    )
    desktop_api._window = window
    window.events.closing += on_closing

    def on_shown():
        """Configure native Win32 window properties once visible."""
        try:
            form = getattr(window, "native", None)
            if form:
                import clr
                clr.AddReference("System.Windows.Forms")
                clr.AddReference("System.Drawing")
                from System.Windows.Forms import Screen, FormWindowState
                from System.Drawing import ColorTranslator

                # Ensure form background color matches dark theme to eliminate any white edge or flash
                form.BackColor = ColorTranslator.FromHtml("#080D17")

                area = Screen.FromControl(form).WorkingArea
                hwnd = int(form.Handle.ToInt64()) if hasattr(form.Handle, "ToInt64") else int(form.Handle)
                if hwnd:
                    user32 = ctypes.windll.user32
                    GWL_STYLE = -16
                    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                    WS_CAPTION = 0x00C00000
                    clean_style = style & ~WS_CAPTION
                    user32.SetWindowLongW(hwnd, GWL_STYLE, clean_style)
                    # Position exactly to work area so taskbar is visible and no padding gap exists
                    user32.SetWindowPos(hwnd, 0, area.X, area.Y, area.Width, area.Height, 0x0040)
        except Exception as e:
            logger.debug("on_shown styling notice: %s", e)

    window.events.shown += on_shown

    # 6. Run GUI loop
    logger.info("Opening Time Tracker AI desktop window...")
    webview.start(
        icon=icon_arg,
        gui="edgechromium",
        debug=args.dev,
        private_mode=False,
    )

    # 7. Cleanup mutex on exit
    if mutex and sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)
    logger.info("Time Tracker AI desktop window closed cleanly.")


if __name__ == "__main__":
    main()

