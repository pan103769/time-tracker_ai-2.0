
import ctypes
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psutil
from pywinauto import Desktop


DB_PATH = Path(__file__).resolve().parent / "tracker.db"
POLL_INTERVAL = 2

BROWSER_PROCESSES = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "opera_gx.exe": "Opera GX",
    "vivaldi.exe": "Vivaldi",
    "firefox.exe": "Firefox",
}

user32 = ctypes.windll.user32


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_active_window():
    hwnd = user32.GetForegroundWindow()

    if not hwnd:
        return None, None, None

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    try:
        process_name = psutil.Process(pid.value).name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return hwnd, None, None

    title_buffer = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

    return hwnd, process_name, title_buffer.value


def get_browser_url(hwnd):
    try:
        window = Desktop(backend="uia").window(handle=hwnd)

        for control in window.descendants():
            try:
                info = control.element_info

                ctrl_name = (info.name or "").lower()
                is_address_bar = (
                    info.control_type == "Edit"
                    and (
                        "address and search bar" in ctrl_name
                        or "search or enter address" in ctrl_name
                        or "search with" in ctrl_name
                        or "address field" in ctrl_name
                        or "location" in ctrl_name
                    )
                )
                if is_address_bar:
                    raw_url = (control.get_value() or "").strip()

                    if not raw_url:
                        continue

                    if "://" not in raw_url:
                        raw_url = "https://" + raw_url

                    parts = urlsplit(raw_url)

                    if (
                        parts.scheme in ("http", "https")
                        and parts.netloc
                    ):
                        # Remove query parameters and fragments.
                        return urlunsplit(
                            (
                                parts.scheme,
                                parts.netloc,
                                parts.path,
                                "",
                                "",
                            )
                        )

            except Exception:
                continue

    except Exception:
        pass

    return None


def initialize_database(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS browser_visits (
            id INTEGER PRIMARY KEY,
            start_time TEXT NOT NULL,
            end_time TEXT,
            browser TEXT NOT NULL,
            title TEXT,
            url TEXT NOT NULL
        )
        """
    )
    connection.commit()

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(browser_visits)"
        ).fetchall()
    }

    required = {
        "id",
        "start_time",
        "end_time",
        "browser",
        "title",
        "url",
    }

    if not required.issubset(columns):
        raise RuntimeError(
            "The browser_visits table does not have the expected schema. "
            f"Found columns: {sorted(columns)}"
        )


def close_visit(connection, visit_id, end_time):
    connection.execute(
        """
        UPDATE browser_visits
        SET end_time = ?
        WHERE id = ?
        """,
        (end_time, visit_id),
    )
    connection.commit()


def main():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    try:
        initialize_database(connection)

        active_visit_id = None
        active_key = None

        print(f"Database: {DB_PATH}")
        print("Browser URL tracking started.")
        print("Tracking active Chrome and Edge windows.")
        print("Press Ctrl+C to stop.\n")

        while True:
            hwnd, process_name, title = get_active_window()
            current_key = None

            if process_name in BROWSER_PROCESSES:
                url = get_browser_url(hwnd)

                if url:
                    browser = BROWSER_PROCESSES[process_name]
                    current_key = (browser, title, url)

            current_time = now()

            if current_key != active_key:
                if active_visit_id is not None:
                    close_visit(
                        connection,
                        active_visit_id,
                        current_time,
                    )
                    active_visit_id = None

                active_key = current_key

                if current_key is not None:
                    browser, title, url = current_key

                    cursor = connection.execute(
                        """
                        INSERT INTO browser_visits
                            (start_time, end_time, browser, title, url)
                        VALUES (?, NULL, ?, ?, ?)
                        """,
                        (current_time, browser, title, url),
                    )
                    connection.commit()

                    active_visit_id = cursor.lastrowid

                    print(f"[{current_time}] {browser} | {title}")
                    print(f"  URL: {url}")

            elif current_key is not None and active_visit_id is not None:
                # Update the end time while this page remains active.
                connection.execute(
                    """
                    UPDATE browser_visits
                    SET end_time = ?
                    WHERE id = ?
                    """,
                    (current_time, active_visit_id),
                )
                connection.commit()

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nStopping browser tracker.")

    finally:
        if "active_visit_id" in locals() and active_visit_id is not None:
            close_visit(connection, active_visit_id, now())

        connection.close()
        print("Browser tracker stopped.")


if __name__ == "__main__":
    main()
