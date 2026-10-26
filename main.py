import ctypes
import io
import json
import os
import queue
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None


# -------------------- CONFIG --------------------

POLL_SECONDS = 1
IDLE_SECONDS = 60
MAX_POLL_GAP_SECONDS = 5

DB_PATH = Path(os.environ.get("TIME_TRACKER_DB_PATH", Path(__file__).with_name("tracker.db")))

OLLAMA_URL = os.getenv(
    "OLLAMA_URL", "http://localhost:11434"
).rstrip("/")

VISION_MODEL = os.getenv(
    "TRACKER_VISION_MODEL", "gemma4:cloud"
)

SCREENSHOTS_ENABLED = True

SENSITIVE_APP_TOKENS = (
    # Password managers and vaults
    "keepass", "1password", "bitwarden", "lastpass", "dashlane",
    "enpass", "nordpass", "roboform", "passbolt", "authenticator",
    "password", "vault", "credential",
    # Private / Incognito browsing
    "incognito", "inprivate", "private browsing", "private window",
    # Authentication & Accounts
    "login", "log in", "sign in", "signin", "sign-in", "sign up", "signup",
    "auth", "sso", "2fa", "mfa", "two-factor", "verification code",
    "reset password", "change password", "enter credentials", "oauth",
    # Banking & Financial & Payments
    "bank", "banking", "wallet", "paypal", "stripe checkout", "checkout",
    "credit card", "billing", "chase", "wells fargo", "citi", "bank of america",
    "crypto", "binance", "coinbase", "metamask",
    # Private messaging
    "signal", "telegram", "whatsapp", "discord", "viber", "wire",
    # Medical & Health records
    "mychart", "patient portal", "medical record", "health record",
)

UNKNOWN_TITLES = {
    "", "unknown", "untitled", "untitled window", "new tab",
    "about:blank", "home", "start", "search", "loading...",
    "page", "app", "window", "document", "speed dial",
}

MUTEX_NAME = r"Local\TimeTrackerV4"

# -------------------- WINDOWS API --------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t
HHOOK = wintypes.HANDLE

HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
]
user32.SetWindowsHookExW.restype = HHOOK

user32.CallNextHookEx.argtypes = [
    HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowTextW.argtypes = [
    wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
]

user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
]

user32.GetLastInputInfo.argtypes = [ctypes.c_void_p]

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

kernel32.OpenProcess.argtypes = [
    wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

# Window Station & Desktop APIs for multi-desktop and subshell environments
user32.OpenWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
user32.OpenWindowStationW.restype = wintypes.HANDLE
user32.SetProcessWindowStation.argtypes = [wintypes.HANDLE]
user32.SetProcessWindowStation.restype = wintypes.BOOL

user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenDesktopW.restype = wintypes.HANDLE
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL

user32.GetProcessWindowStation.restype = wintypes.HANDLE
user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
user32.GetThreadDesktop.restype = wintypes.HANDLE
user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
]
user32.GetUserObjectInformationW.restype = wintypes.BOOL

# -------------------- GENERAL HELPERS --------------------


def ensure_interactive_desktop() -> bool:
    """
    Attach the calling thread to the interactive user desktop (WinSta0\\Default).
    Essential when tracker is launched by subprocesses, services, or subshells
    that do not default to the interactive desktop.
    """
    if sys.platform != "win32":
        return False
    try:
        tid = kernel32.GetCurrentThreadId()
        dt = user32.GetThreadDesktop(tid)
        if dt:
            buf = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if user32.GetUserObjectInformationW(dt, 2, buf, 512, ctypes.byref(needed)):
                if buf.value.lower() == "default":
                    return True

        h_ws = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if h_ws:
            user32.SetProcessWindowStation(h_ws)

        h_dt = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_dt:
            return bool(user32.SetThreadDesktop(h_dt))
        return False
    except Exception:
        return False


def now():
    return datetime.now(timezone.utc)


def timestamp(value):
    return value.isoformat()


def foreground_window():
    hwnd = user32.GetForegroundWindow()

    # If hwnd is NULL, ensure thread is attached to the interactive desktop
    if not hwnd:
        ensure_interactive_desktop()
        hwnd = user32.GetForegroundWindow()

    if not hwnd:
        return "Unknown", "Unknown"

    title_buffer = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    title = title_buffer.value or "Untitled window"

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    app = "Unknown"
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        handle = kernel32.OpenProcess(0x0400, False, pid.value)

    if handle:
        try:
            path_buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(path_buffer))

            if kernel32.QueryFullProcessImageNameW(
                handle, 0, path_buffer, ctypes.byref(size)
            ):
                app = Path(path_buffer.value).name
        finally:
            kernel32.CloseHandle(handle)

    return app, title


def idle_seconds():
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)

    if not user32.GetLastInputInfo(ctypes.byref(info)):
        # When workstation is locked, UAC is active, or user is disconnected,
        # GetLastInputInfo can fail. Return 0.0 rather than crashing the tracker.
        return 0.0

    elapsed = (
        kernel32.GetTickCount() - info.dwTime
    ) & 0xFFFFFFFF

    return elapsed / 1000


# -------------------- SCREENSHOT COOLDOWNS & STATE --------------------

WINDOW_COOLDOWN_SECONDS = 120.0
GLOBAL_CAPTURE_COOLDOWN_SECONDS = 10.0

_last_captured_by_window = {}
_last_global_capture_time = 0.0
_cooldown_lock = threading.Lock()

_OLLAMA_ONLINE = None
_LAST_OLLAMA_CHECK = 0.0
OLLAMA_CHECK_INTERVAL = 30.0


def reset_screenshot_cooldowns():
    """Reset cooldown tracking caches (useful for testing and restarts)."""
    global _last_global_capture_time, _OLLAMA_ONLINE, _LAST_OLLAMA_CHECK
    with _cooldown_lock:
        _last_captured_by_window.clear()
        _last_global_capture_time = 0.0
        _OLLAMA_ONLINE = None
        _LAST_OLLAMA_CHECK = 0.0


def check_screenshot_cooldown(app, title):
    """
    Check if a screenshot capture should be throttled.
    Returns (is_throttled, reason).
    """
    now_mono = time.monotonic()
    app_key = (app or "").strip().lower()
    title_key = (title or "").strip().lower()

    with _cooldown_lock:
        # Check global capture interval to avoid capture bursts
        global_elapsed = now_mono - _last_global_capture_time
        if global_elapsed < GLOBAL_CAPTURE_COOLDOWN_SECONDS:
            remaining = GLOBAL_CAPTURE_COOLDOWN_SECONDS - global_elapsed
            return True, f"global capture cooldown active ({remaining:.1f}s remaining)"

        # Check window-specific cooldown to avoid capturing unchanged window
        last_window_time = _last_captured_by_window.get((app_key, title_key), 0.0)
        window_elapsed = now_mono - last_window_time
        if window_elapsed < WINDOW_COOLDOWN_SECONDS:
            remaining = WINDOW_COOLDOWN_SECONDS - window_elapsed
            return True, f"cooldown active for {app!r} ({remaining:.1f}s remaining)"

    return False, ""


def record_screenshot_capture(app, title):
    """Update cooldown timestamps after a screenshot is queued."""
    now_mono = time.monotonic()
    app_key = (app or "").strip().lower()
    title_key = (title or "").strip().lower()

    with _cooldown_lock:
        global _last_global_capture_time
        _last_global_capture_time = now_mono
        _last_captured_by_window[(app_key, title_key)] = now_mono


def is_ollama_available():
    """Return True if Ollama service is reachable, cached for up to 30 seconds."""
    global _OLLAMA_ONLINE, _LAST_OLLAMA_CHECK
    now_mono = time.monotonic()
    if _OLLAMA_ONLINE is not None and (now_mono - _LAST_OLLAMA_CHECK) < OLLAMA_CHECK_INTERVAL:
        return _OLLAMA_ONLINE

    _LAST_OLLAMA_CHECK = now_mono
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.0)
        _OLLAMA_ONLINE = (resp.status_code == 200)
    except Exception:
        _OLLAMA_ONLINE = False
    return _OLLAMA_ONLINE


# -------------------- PRIVACY & METADATA EVALUATION --------------------


def is_sensitive_window(app, title, url=""):
    """
    Return True if the window belongs to a password manager, private browsing,
    authentication page, financial service, or other sensitive context.
    Never send screenshots of these contexts to any AI model.
    """
    combined = f"{app or ''} {title or ''} {url or ''}".lower()
    return any(token in combined for token in SENSITIVE_APP_TOKENS)


# Alias for backwards compatibility
is_sensitive_app = is_sensitive_window


def is_browser_app(app):
    """Check if app name belongs to a recognized web browser."""
    app_lower = (app or "").strip().lower()
    return any(
        token in app_lower
        for token in ("chrome", "msedge", "edge", "firefox", "brave", "opera", "vivaldi")
    )


def evaluate_visual_need(app, title, db=None):
    """
    Decide whether visual context (a screenshot) is needed to understand the activity.
    Uses existing window title, app name, and browser tracking metadata.

    Returns:
        (needs_screenshot: bool, reason: str)
    """
    app_text = (app or "").strip().lower()
    title_text = (title or "").strip()
    title_lower = title_text.lower()

    # 1. Privacy safeguard
    if is_sensitive_window(app, title):
        return False, "sensitive window (privacy safeguard)"

    # 2. Unknown or generic application container
    if not app_text or app_text in ("unknown", "unknown.exe"):
        return True, "unknown application"

    if app_text == "applicationframehost.exe":
        return True, "generic UWP container host"

    # 3. Code Editors & IDEs (VS Code, PyCharm, Sublime, etc.)
    if app_text in (
        "code.exe", "cursor.exe", "devenv.exe", "pycharm64.exe",
        "idea64.exe", "sublime_text.exe",
    ):
        has_ext = bool(re.search(r"\.[a-zA-Z0-9_-]{1,8}(?:\s*[-•—]|\Z)", title_text))
        has_workspace = " - " in title_text or " — " in title_text or " • " in title_text
        if has_ext or has_workspace:
            return False, "code editor with identifiable file/project"
        return True, "code editor on empty/generic window"

    # 4. Web Browsers (Chrome, Edge, Firefox, Brave, Opera)
    if is_browser_app(app_text):
        is_generic_tab = False
        for gen in (
            "new tab", "about:blank", "google chrome", "microsoft edge",
            "opera", "brave", "firefox", "speed dial", "home", "untitled",
        ):
            if title_lower == gen or title_lower.startswith(f"{gen} -"):
                is_generic_tab = True
                break

        # If title is specific and not generic, we have sufficient metadata
        if not is_generic_tab and len(title_text) > 8:
            clean_t = title_text
            for suff in (
                " - Google Chrome", " - Microsoft Edge", " - Chromium",
                " - Mozilla Firefox", " - Opera", " - Brave",
            ):
                if clean_t.endswith(suff):
                    clean_t = clean_t[:-len(suff)].strip()
            if len(clean_t) > 3 and clean_t.lower() not in (
                "new tab", "about:blank", "home", "untitled window", "search",
            ):
                return False, "browser with descriptive page title"

        # Tab title is generic: check if recent browser visit in db provides specific URL
        if db is not None:
            try:
                row = db.execute(
                    """
                    SELECT url, title FROM browser_visits
                    ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
                if row:
                    b_url = (row[0] or "").strip()
                    if b_url and not any(
                        b_url.startswith(p)
                        for p in ("chrome://", "edge://", "about:", "opera://", "brave://")
                    ):
                        if len(b_url) > 12 and b_url not in (
                            "https://www.google.com/", "http://www.google.com/",
                        ):
                            return False, "browser tracking provides visit URL"
            except Exception:
                pass

        return True, "browser tab lacks specific page title or URL"

    # 5. Windows Explorer (File manager / Desktop)
    if app_text == "explorer.exe":
        if re.search(r"[a-zA-Z]:\\", title_text) or title_lower in (
            "downloads", "documents", "pictures", "videos", "music", "desktop",
        ):
            return False, "explorer with specific folder path"
        return True, "explorer with generic or untitled window"

    # 6. Standard Windows utilities with unambiguous purpose
    if app_text in (
        "taskmgr.exe", "regedit.exe", "services.msc", "mmc.exe",
        "perfmon.exe", "resmon.exe", "control.exe",
    ):
        return False, "standard system tool with unambiguous purpose"

    if title_lower in (
        "task manager", "registry editor", "device manager",
        "resource monitor", "event viewer", "services",
    ):
        return False, "standard system tool with unambiguous purpose"

    # 7. Generic or untitled documents
    if not title_text or title_lower in UNKNOWN_TITLES:
        return True, "generic window title"

    if title_lower.startswith("untitled -") or title_lower.startswith("document1"):
        return True, "generic untitled document"

    # App name repeated as title (e.g. app="notepad.exe", title="Notepad")
    app_base = app_text.replace(".exe", "")
    if title_lower == app_base:
        return True, "window title is just app name"

    # 8. Descriptive window title
    if len(title_text) >= 6:
        return False, "identifiable window metadata"

    return True, "ambiguous window"


def needs_visual_context(app, title, db=None):
    """Return True when foreground metadata is generic and visual context is needed."""
    needs_ctx, _ = evaluate_visual_need(app, title, db)
    return needs_ctx


# -------------------- SCREENSHOT ANALYSIS --------------------


def capture_screenshot_bytes():
    """Capture a compressed screenshot in memory. Never write it to disk."""
    if ImageGrab is None:
        return None

    image = ImageGrab.grab(all_screens=False)

    # Resize to reduce upload size and processing time.
    image.thumbnail((1280, 900))

    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer, format="JPEG", quality=65, optimize=True
    )

    return buffer.getvalue()


def analyze_screenshot(image_bytes, app, title):
    """Send the screenshot to Ollama and return a concise activity description."""
    import base64

    encoded = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "model": VISION_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Describe the visible computer activity in one concise "
                    "sentence, around 10-25 words. Identify the visible app "
                    "or task only when supported by the image. Do not guess "
                    "hidden activity. If unclear, say what is visibly shown. "
                    f"Window metadata: app={app!r}, title={title!r}."
                ),
                "images": [encoded],
            }
        ],
    }

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        global _OLLAMA_ONLINE
        _OLLAMA_ONLINE = False
        raise

    data = response.json()
    description = data.get("message", {}).get("content", "").strip()

    if not description:
        raise ValueError("Vision model returned an empty description.")

    return description


def screenshot_worker(stop_event):
    """Analyze queued screenshots and verify database writes."""
    db = sqlite3.connect(DB_PATH, timeout=15)

    try:
        while not stop_event.is_set():
            try:
                item = screenshot_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None or stop_event.is_set():
                screenshot_queue.task_done()
                break

            observation_id, captured_at, app, title, image_bytes = item

            try:
                if not is_ollama_available():
                    print(
                        f"[vision] SKIP observation {observation_id}: "
                        "Ollama service offline."
                    )
                    continue

                print(
                    f"[vision] Analyzing observation {observation_id} "
                    f"with {VISION_MODEL}..."
                )

                description = analyze_screenshot(
                    image_bytes, app, title
                )

                with db:
                    db.execute(
                        """
                        INSERT INTO activity_screenshots
                            (observation_id, path, captured_at, description)
                        VALUES (?, '', ?, ?)
                        ON CONFLICT(observation_id) DO UPDATE SET
                            path = '',
                            captured_at = excluded.captured_at,
                            description = excluded.description
                        """,
                        (
                            observation_id,
                            timestamp(captured_at),
                            description,
                        ),
                    )

                saved = db.execute(
                    """
                    SELECT description
                    FROM activity_screenshots
                    WHERE observation_id = ?
                    """,
                    (observation_id,),
                ).fetchone()

                if saved and saved[0]:
                    print(
                        f"[vision] SAVED observation {observation_id}: "
                        f"{saved[0]}"
                    )
                else:
                    print(
                        f"[vision] ERROR: save verification failed "
                        f"for observation {observation_id}"
                    )

            except Exception as error:
                print(
                    f"[vision] FAILED observation {observation_id}: "
                    f"{type(error).__name__}: {error}"
                )

            finally:
                image_bytes = None
                screenshot_queue.task_done()

    finally:
        db.close()


def queue_unknown_screenshot(
    observation_id, app, title, captured_at, db=None
):
    """Capture only when metadata is generic; never save image files."""
    if not SCREENSHOTS_ENABLED:
        print("[vision] SKIP: screenshots disabled.")
        return

    if ImageGrab is None:
        print("[vision] SKIP: Pillow ImageGrab unavailable.")
        return

    if is_sensitive_window(app, title):
        print(
            f"[vision] SKIP: sensitive window (privacy safeguard): {app!r} | {title!r}"
        )
        return

    throttled, cd_reason = check_screenshot_cooldown(app, title)
    if throttled:
        print(f"[vision] SKIP: {cd_reason}: {app!r} | {title!r}")
        return

    needs_ctx, reason = evaluate_visual_need(app, title, db)
    if not needs_ctx:
        print(
            f"[vision] SKIP: metadata is clear ({reason}): "
            f"{app!r} | {title!r}"
        )
        return

    if not is_ollama_available():
        print(f"[vision] SKIP: Ollama vision service offline ({OLLAMA_URL})")
        return

    image_bytes = None

    try:
        image_bytes = capture_screenshot_bytes()

        if not image_bytes:
            print("[vision] FAILED: screenshot capture returned no image.")
            return

        item = (
            observation_id,
            captured_at,
            app,
            title,
            image_bytes,
        )

        try:
            screenshot_queue.put_nowait(item)
        except queue.Full:
            print("[vision] FAILED: queue full; screenshot discarded.")
            return

        image_bytes = None  # Queue now owns the image bytes.
        record_screenshot_capture(app, title)

        print(
            f"[vision] QUEUED observation {observation_id} ({reason}): "
            f"{app!r} | {title!r}"
        )

    except Exception as error:
        print(
            f"[vision] CAPTURE FAILED: "
            f"{type(error).__name__}: {error}"
        )

def close_observation(db, observation_id, end_time):
    row = db.execute(
        """
        SELECT start_time FROM observations
        WHERE id=? AND end_time IS NULL
        """,
        (observation_id,),
    ).fetchone()

    if row:
        start = datetime.fromisoformat(row[0])
        end = max(end_time, start)

        db.execute(
            """
            UPDATE observations
            SET end_time=?, duration_seconds=?
            WHERE id=? AND end_time IS NULL
            """,
            (
                timestamp(end),
                (end - start).total_seconds(),
                observation_id,
            ),
        )


# -------------------- MAIN TRACKER --------------------

screenshot_queue = queue.Queue(maxsize=5)


def main():
    # CLI command dispatcher for timeline, reports, and help
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("timeline", "--timeline", "-t"):
            import ai_timeline
            return ai_timeline.main(sys.argv[2:])
        if cmd in ("ui", "--ui", "timeline-ui", "--timeline-ui"):
            import timeline_ui
            return timeline_ui.main(sys.argv[2:])
        if cmd in ("report", "--report", "-r"):
            import report
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            return report.main()
        if cmd in ("activity-report", "--activity-report", "-ar"):
            import activity_report
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            return activity_report.main()
        if cmd in ("autostart", "--autostart"):
            import api.autostart as autostart
            return autostart.main(sys.argv[2:])
        if cmd in ("help", "--help", "-h"):
            print("Time Tracker AI — Available Commands:")
            print("  python main.py                  Start background activity tracking")
            print("  python main.py ui [date]        Open visual Activity Timeline UI")
            print("  python main.py timeline [date]  View AI activity timeline in terminal")
            print("  python main.py timeline --edit N Edit session #N description")
            print("  python main.py report [date]    View daily application time summary")
            print("  python main.py autostart        Manage Windows auto-launch (--enable/--disable)")
            print("  python timeline_ui.py [date]    Direct access to visual UI")
            print("  python timeline.py [date]       Direct access to terminal timeline")
            print("  python browser_tracker.py       Start the browser URL tracker")
            return 0

    if sys.platform != "win32":
        raise RuntimeError("This tracker requires Windows.")

    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]

    ctypes.set_last_error(0)
    mutex = kernel32.CreateMutexW(None, True, MUTEX_NAME)

    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())

    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(mutex)
        print("Tracker is already running.")
        return

    db = None
    stop_event = threading.Event()
    input_counts = Counter()
    counts_lock = threading.Lock()
    hook_errors = queue.Queue()
    current_id = None
    current_key = None
    last_poll_time = None

    def mouse_callback(code, message, data):
        if code >= 0:
            event = {
                WM_MOUSEMOVE: "mouse_move",
                WM_LBUTTONDOWN: "left_click",
                WM_RBUTTONDOWN: "right_click",
                WM_MBUTTONDOWN: "middle_click",
                WM_MOUSEWHEEL: "scroll_vertical",
                WM_MOUSEHWHEEL: "scroll_horizontal",
            }.get(message)

            if event:
                with counts_lock:
                    input_counts[event] += 1

        return user32.CallNextHookEx(None, code, message, data)

    def keyboard_callback(code, message, data):
        if code >= 0 and message in (WM_KEYDOWN, WM_SYSKEYDOWN):
            # Never store key codes or typed text.
            with counts_lock:
                input_counts["keyboard"] += 1

        return user32.CallNextHookEx(None, code, message, data)

    mouse_proc = HOOKPROC(mouse_callback)
    keyboard_proc = HOOKPROC(keyboard_callback)

    def hook_worker():
        ensure_interactive_desktop()
        mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, mouse_proc, kernel32.GetModuleHandleW(None), 0
        )
        keyboard_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, keyboard_proc,
            kernel32.GetModuleHandleW(None), 0
        )

        if not mouse_hook or not keyboard_hook:
            hook_errors.put(ctypes.get_last_error())

            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            if keyboard_hook:
                user32.UnhookWindowsHookEx(keyboard_hook)
            return

        try:
            message = wintypes.MSG()

            while not stop_event.is_set():
                while user32.PeekMessageW(
                    ctypes.byref(message), None, 0, 0, 1
                ):
                    if message.message == WM_QUIT:
                        return

                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))

                time.sleep(0.005)

        finally:
            user32.UnhookWindowsHookEx(mouse_hook)
            user32.UnhookWindowsHookEx(keyboard_hook)

    try:
        db = sqlite3.connect(DB_PATH, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")

        db.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                app TEXT NOT NULL,
                title TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds REAL,
                CHECK (end_time IS NULL OR end_time >= start_time)
            )
        """)

        columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(observations)")
        }

        if "task" not in columns:
            db.execute("ALTER TABLE observations ADD COLUMN task TEXT")

        db.execute("""
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                app TEXT NOT NULL,
                title TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_count INTEGER NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS activity_screenshots (
                observation_id INTEGER PRIMARY KEY,
                path TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT ''
            )
        """)

        db.commit()

        # Recover observations left open by an earlier run safely without stretching across shutdown gaps.
        with db:
            unfinished = db.execute(
                "SELECT id, start_time FROM observations WHERE end_time IS NULL"
            ).fetchall()

            now_dt = now()
            for obs_id, start_str in unfinished:
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    gap_to_now = (now_dt - start_dt).total_seconds()
                    last_ev = db.execute(
                        "SELECT MAX(timestamp) FROM activity_events WHERE timestamp >= ?",
                        (start_str,),
                    ).fetchone()
                    if last_ev and last_ev[0]:
                        close_end = datetime.fromisoformat(last_ev[0])
                    elif gap_to_now <= 15.0:
                        close_end = now_dt
                    else:
                        close_end = start_dt + timedelta(seconds=POLL_SECONDS)
                    close_observation(db, obs_id, close_end)
                except Exception:
                    close_observation(db, obs_id, now_dt)

        # Check for missed-activity recovery gap on startup
        try:
            import api.notification_engine as notif_engine
            notif_engine.detect_missed_activity_gap(db)
        except Exception as recovery_err:
            print(f"[recovery] Startup gap check notice: {recovery_err}")

        # AI processing runs separately from the polling loop.
        vision_thread = threading.Thread(
            target=screenshot_worker,
            args=(stop_event,),
            daemon=True,
        )
        vision_thread.start()

        worker = threading.Thread(target=hook_worker, daemon=True)
        worker.start()

        time.sleep(0.2)

        if not hook_errors.empty():
            error_code = hook_errors.get()
            raise OSError(
                f"Could not install Windows input hooks (error {error_code})."
            )

        print(f"Tracking started. Database: {DB_PATH}", flush=True)
        print(f"Vision model: {VISION_MODEL}", flush=True)
        print("Unknown-window screenshots are analyzed in memory.", flush=True)
        print("Screenshots are not saved to disk.", flush=True)
        print("Typed characters are never saved. Press Ctrl+C to stop.", flush=True)
        print("To view your activity timeline: python main.py timeline (or python timeline.py)", flush=True)

        ensure_interactive_desktop()

        while True:
            try:
                current_time = now()

                # Detect long polling gaps so they are not counted as activity.
                if last_poll_time is not None:
                    gap = (current_time - last_poll_time).total_seconds()

                    if gap > MAX_POLL_GAP_SECONDS and current_id is not None:
                        with db:
                            close_observation(
                                db,
                                current_id,
                                last_poll_time,
                            )

                        print(
                            f"[gap] {gap:.1f}s pause detected; "
                            "previous observation closed at last poll."
                        )

                        current_id = None
                        current_key = None

                last_poll_time = current_time

                is_idle = idle_seconds() >= IDLE_SECONDS

                if is_idle:
                    key = ("idle", "Idle", "Idle")
                else:
                    app, title = foreground_window()
                    key = ("active", app, title)

                with counts_lock:
                    batch = dict(input_counts)
                    input_counts.clear()

                if batch:
                    app_for_event, title_for_event = foreground_window()

                    with db:
                        for event_type, count in batch.items():
                            db.execute(
                                """
                                INSERT INTO activity_events
                                    (timestamp, app, title, event_type, event_count)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    timestamp(current_time),
                                    app_for_event,
                                    title_for_event,
                                    event_type,
                                    count,
                                ),
                            )

                if key != current_key:
                    with db:
                        if current_id is not None:
                            close_observation(db, current_id, current_time)

                        # Check for ongoing active task in app_settings
                        active_task = None
                        active_cat_id = None
                        try:
                            row_task = db.execute("SELECT value FROM app_settings WHERE key = 'current_active_task'").fetchone()
                            if row_task and row_task[0]:
                                active_task = row_task[0].strip() or None
                            row_cat = db.execute("SELECT value FROM app_settings WHERE key = 'current_active_category_id'").fetchone()
                            if row_cat and row_cat[0]:
                                active_cat_id = int(row_cat[0])
                        except Exception:
                            pass

                        cursor = db.execute(
                            """
                            INSERT INTO observations
                                (kind, app, title, task, start_time)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (*key, active_task, timestamp(current_time)),
                        )

                        current_id = cursor.lastrowid

                    current_key = key

                    print(
                        f"[{current_time.astimezone():%H:%M:%S}] "
                        f"[obs #{current_id}] {key[0]} | {key[1]} | {key[2][:100]}",
                        flush=True,
                    )

                    if key[0] == "active":
                        queue_unknown_screenshot(
                            current_id,
                            key[1],
                            key[2],
                            current_time,
                            db=db,
                        )

            except Exception as poll_error:
                print(
                    f"[poll_error] Transient exception in tracking loop: {poll_error}",
                    file=sys.stderr,
                )

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping tracker...")
    except Exception as fatal_error:
        print(f"\n[fatal] Fatal tracker exception: {fatal_error}", file=sys.stderr)
        raise

    finally:
        # 1. Close active observation in database immediately so it is never lost
        if db is not None:
            try:
                with db:
                    if current_id is not None:
                        close_observation(db, current_id, now())
            except Exception as error:
                print(f"[db] Error closing observation on shutdown: {error}")

        # 2. Signal worker thread to stop
        stop_event.set()

        # 3. Drain pending queue items so worker can exit promptly
        while not screenshot_queue.empty():
            try:
                screenshot_queue.get_nowait()
                screenshot_queue.task_done()
            except (queue.Empty, ValueError):
                break

        try:
            screenshot_queue.put_nowait(None)
        except queue.Full:
            pass

        # 4. Join vision worker with short timeout so shutdown is never blocked
        if "vision_thread" in locals() and vision_thread.is_alive():
            vision_thread.join(timeout=3.0)
            if vision_thread.is_alive():
                print(
                    "[vision] Worker did not stop within 3s; "
                    "continuing shutdown."
                )

        # 5. Close database connection
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)
        print("Tracker stopped. Database saved.")
        print("View your activity timeline with: python main.py timeline")


if __name__ == "__main__":
    main()