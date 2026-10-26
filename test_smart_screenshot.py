"""
test_smart_screenshot.py — Tests for smart screenshot decision process,
sensitive window exclusion, cooldown throttling, offline handling, database
persistence, and timeline integration.
"""

import io
import queue
import sqlite3
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import ai_timeline
import main as tracker_main


def _create_test_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database matching tracker.db schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            app TEXT NOT NULL,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration_seconds REAL,
            task TEXT
        );

        CREATE TABLE browser_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            browser TEXT NOT NULL,
            title TEXT,
            url TEXT NOT NULL
        );

        CREATE TABLE activity_screenshots (
            observation_id INTEGER PRIMARY KEY,
            path TEXT NOT NULL DEFAULT '',
            captured_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE timeline_edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return db


# ---------------------------------------------------------------------------
# 1. Clear vs Ambiguous Metadata Evaluation
# ---------------------------------------------------------------------------


class TestMetadataEvaluation(unittest.TestCase):
    def setUp(self):
        tracker_main.reset_screenshot_cooldowns()

    def test_clear_vscode_with_file_and_project(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "Code.exe", "main.py - time tracker ai 2 - Visual Studio Code"
        )
        self.assertFalse(needs)
        self.assertIn("identifiable file/project", reason)

    def test_clear_vscode_with_extension(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "code.exe", "ai_timeline.py — Visual Studio Code"
        )
        self.assertFalse(needs)
        self.assertIn("identifiable file/project", reason)

    def test_generic_vscode_empty_window(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "Code.exe", "Visual Studio Code"
        )
        self.assertTrue(needs)
        self.assertIn("empty/generic window", reason)

    def test_clear_browser_descriptive_page_title(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "chrome.exe", "Python 3.14 Documentation - Google Chrome"
        )
        self.assertFalse(needs)
        self.assertIn("descriptive page title", reason)

    def test_generic_browser_tab_without_browser_visits(self):
        db = _create_test_db()
        needs, reason = tracker_main.evaluate_visual_need(
            "chrome.exe", "New Tab - Google Chrome", db=db
        )
        db.close()
        self.assertTrue(needs)
        self.assertIn("lacks specific page title or URL", reason)

    def test_generic_browser_tab_with_meaningful_browser_visit(self):
        db = _create_test_db()
        db.execute(
            """
            INSERT INTO browser_visits (start_time, browser, title, url)
            VALUES ('2026-10-20T10:00:00Z', 'Chrome', 'Python Docs', 'https://docs.python.org/3/library/sqlite3.html')
            """
        )
        db.commit()
        needs, reason = tracker_main.evaluate_visual_need(
            "chrome.exe", "New Tab - Google Chrome", db=db
        )
        db.close()
        self.assertFalse(needs)
        self.assertIn("browser tracking provides visit URL", reason)

    def test_generic_browser_tab_with_newtab_url(self):
        db = _create_test_db()
        db.execute(
            """
            INSERT INTO browser_visits (start_time, browser, title, url)
            VALUES ('2026-10-20T10:00:00Z', 'Chrome', 'New Tab', 'chrome://newtab')
            """
        )
        db.commit()
        needs, reason = tracker_main.evaluate_visual_need(
            "chrome.exe", "New Tab - Google Chrome", db=db
        )
        db.close()
        self.assertTrue(needs)
        self.assertIn("lacks specific page title or URL", reason)

    def test_unknown_application(self):
        needs, reason = tracker_main.evaluate_visual_need("Unknown", "")
        self.assertTrue(needs)
        self.assertIn("unknown application", reason)

    def test_uwp_container_host(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "ApplicationFrameHost.exe", "Photos"
        )
        self.assertTrue(needs)
        self.assertIn("generic UWP container host", reason)

    def test_explorer_with_folder_path(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "explorer.exe", r"C:\Users\user\Desktop\time tracker ai 2"
        )
        self.assertFalse(needs)
        self.assertIn("specific folder path", reason)

    def test_explorer_generic_desktop(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "explorer.exe", "Untitled window"
        )
        self.assertTrue(needs)
        self.assertIn("explorer with generic or untitled window", reason)

    def test_notepad_untitled(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "notepad.exe", "Untitled - Notepad"
        )
        self.assertTrue(needs)
        self.assertIn("generic untitled document", reason)

    def test_notepad_named_document(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "notepad.exe", "todo.txt - Notepad"
        )
        self.assertFalse(needs)
        self.assertIn("identifiable window metadata", reason)

    def test_standard_system_utility(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "Taskmgr.exe", "Task Manager"
        )
        self.assertFalse(needs)
        self.assertIn("standard system tool", reason)

    def test_app_name_repeated_as_title(self):
        needs, reason = tracker_main.evaluate_visual_need(
            "notepad.exe", "Notepad"
        )
        self.assertTrue(needs)
        self.assertIn("title is just app name", reason)

    def test_backwards_compatible_needs_visual_context_wrapper(self):
        self.assertTrue(tracker_main.needs_visual_context("explorer.exe", "Untitled window"))
        self.assertFalse(tracker_main.needs_visual_context("Code.exe", "main.py - project"))


# ---------------------------------------------------------------------------
# 2. Sensitive Window Exclusion Safeguards
# ---------------------------------------------------------------------------


class TestSensitiveWindowSafeguards(unittest.TestCase):
    def test_password_managers(self):
        self.assertTrue(tracker_main.is_sensitive_window("1password.exe", "1Password"))
        self.assertTrue(tracker_main.is_sensitive_window("bitwarden.exe", "Bitwarden Vault"))
        self.assertTrue(tracker_main.is_sensitive_window("KeePass.exe", "KeePass Password Safe"))
        self.assertTrue(tracker_main.is_sensitive_window("dashlane.exe", "Dashlane"))

    def test_private_and_incognito_browsing(self):
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "New Incognito Tab - Google Chrome"))
        self.assertTrue(tracker_main.is_sensitive_window("msedge.exe", "InPrivate - Microsoft Edge"))
        self.assertTrue(tracker_main.is_sensitive_window("firefox.exe", "Private Browsing - Mozilla Firefox"))

    def test_authentication_and_sign_in(self):
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "Sign in - Google Accounts"))
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "Log in to GitHub"))
        self.assertTrue(tracker_main.is_sensitive_window("msedge.exe", "Two-Factor Authentication (2FA)"))
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "Reset your password"))

    def test_banking_and_financial(self):
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "Chase Online Banking"))
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "PayPal Checkout"))
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "Credit card payment"))

    def test_private_messaging(self):
        self.assertTrue(tracker_main.is_sensitive_window("Telegram.exe", "Telegram"))
        self.assertTrue(tracker_main.is_sensitive_window("Signal.exe", "Signal"))
        self.assertTrue(tracker_main.is_sensitive_window("WhatsApp.exe", "WhatsApp"))
        self.assertTrue(tracker_main.is_sensitive_window("Discord.exe", "Discord"))

    def test_medical_portals(self):
        self.assertTrue(tracker_main.is_sensitive_window("chrome.exe", "MyChart Patient Portal"))

    def test_normal_windows_not_sensitive(self):
        self.assertFalse(tracker_main.is_sensitive_window("Code.exe", "main.py - project"))
        self.assertFalse(tracker_main.is_sensitive_window("chrome.exe", "Python 3 Documentation"))
        self.assertFalse(tracker_main.is_sensitive_window("notepad.exe", "Shopping List - Notepad"))

    def test_queue_skips_sensitive_window(self):
        """queue_unknown_screenshot must never capture or queue for sensitive windows."""
        tracker_main.reset_screenshot_cooldowns()
        # Empty queue
        while not tracker_main.screenshot_queue.empty():
            tracker_main.screenshot_queue.get_nowait()

        with patch.object(tracker_main, "capture_screenshot_bytes") as mock_cap:
            tracker_main.queue_unknown_screenshot(
                observation_id=1,
                app="chrome.exe",
                title="Sign in - Google Accounts",
                captured_at=datetime.now(timezone.utc),
            )
            # Capture must NOT be called
            mock_cap.assert_not_called()
            # Queue must remain empty
            self.assertTrue(tracker_main.screenshot_queue.empty())


# ---------------------------------------------------------------------------
# 3. Screenshot Cooldown and Deduplication
# ---------------------------------------------------------------------------


class TestScreenshotCooldowns(unittest.TestCase):
    def setUp(self):
        tracker_main.reset_screenshot_cooldowns()

    def test_first_capture_allowed(self):
        throttled, reason = tracker_main.check_screenshot_cooldown("explorer.exe", "Untitled window")
        self.assertFalse(throttled)
        self.assertEqual(reason, "")

    def test_window_cooldown_throttles_same_window(self):
        app, title = "explorer.exe", "Untitled window"
        # Simulate capture
        tracker_main.record_screenshot_capture(app, title)

        # Immediate check should be throttled
        throttled, reason = tracker_main.check_screenshot_cooldown(app, title)
        self.assertTrue(throttled)

    def test_global_cooldown_throttles_rapid_captures(self):
        # Capture window A
        tracker_main.record_screenshot_capture("app_a.exe", "window a")

        # Rapidly attempt capture for window B (within 10s)
        throttled, reason = tracker_main.check_screenshot_cooldown("app_b.exe", "window b")
        self.assertTrue(throttled)
        self.assertIn("global capture cooldown active", reason)

    def test_cooldown_reset(self):
        tracker_main.record_screenshot_capture("app.exe", "title")
        throttled, _ = tracker_main.check_screenshot_cooldown("app.exe", "title")
        self.assertTrue(throttled)

        tracker_main.reset_screenshot_cooldowns()
        throttled, _ = tracker_main.check_screenshot_cooldown("app.exe", "title")
        self.assertFalse(throttled)


# ---------------------------------------------------------------------------
# 4. Ollama Availability & Error Handling
# ---------------------------------------------------------------------------


class TestOllamaHandling(unittest.TestCase):
    def setUp(self):
        tracker_main.reset_screenshot_cooldowns()

    def test_ollama_offline_skips_capture(self):
        with patch.object(tracker_main, "is_ollama_available", return_value=False), \
             patch.object(tracker_main, "capture_screenshot_bytes") as mock_cap:
            tracker_main.queue_unknown_screenshot(
                observation_id=1,
                app="explorer.exe",
                title="Untitled window",
                captured_at=datetime.now(timezone.utc),
            )
            mock_cap.assert_not_called()
            self.assertTrue(tracker_main.screenshot_queue.empty())

    def test_empty_vision_response_raises_value_error(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": ""}}
        mock_resp.status_code = 200

        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(ValueError):
                tracker_main.analyze_screenshot(b"dummy_bytes", "explorer.exe", "Untitled")

    def test_connection_error_updates_offline_cache(self):
        import requests
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("refused")):
            with self.assertRaises(requests.exceptions.ConnectionError):
                tracker_main.analyze_screenshot(b"dummy_bytes", "explorer.exe", "Untitled")
            self.assertFalse(tracker_main._OLLAMA_ONLINE)


# ---------------------------------------------------------------------------
# 5. Queue Overflow Handling
# ---------------------------------------------------------------------------


class TestQueueOverflow(unittest.TestCase):
    def setUp(self):
        tracker_main.reset_screenshot_cooldowns()
        while not tracker_main.screenshot_queue.empty():
            tracker_main.screenshot_queue.get_nowait()

    def tearDown(self):
        while not tracker_main.screenshot_queue.empty():
            tracker_main.screenshot_queue.get_nowait()

    def test_full_queue_discards_gracefully(self):
        # Fill the queue up to maxsize=5
        for i in range(tracker_main.screenshot_queue.maxsize):
            tracker_main.screenshot_queue.put_nowait((i, datetime.now(timezone.utc), "app", "title", b"data"))

        self.assertTrue(tracker_main.screenshot_queue.full())

        # Attempt to queue another should not raise queue.Full
        with patch.object(tracker_main, "is_ollama_available", return_value=True), \
             patch.object(tracker_main, "capture_screenshot_bytes", return_value=b"extra_data"):
            tracker_main.queue_unknown_screenshot(
                observation_id=99,
                app="explorer.exe",
                title="Untitled window",
                captured_at=datetime.now(timezone.utc),
            )
        # Still full, but application did not crash
        self.assertTrue(tracker_main.screenshot_queue.full())


# ---------------------------------------------------------------------------
# 6. Database Persistence & Worker Verification
# ---------------------------------------------------------------------------


class TestDatabasePersistence(unittest.TestCase):
    def setUp(self):
        tracker_main.reset_screenshot_cooldowns()
        while not tracker_main.screenshot_queue.empty():
            tracker_main.screenshot_queue.get_nowait()

    def test_worker_persists_screenshot_description(self):
        """Worker must analyze queued item and store description in activity_screenshots."""
        import tempfile
        import os

        stop_event = threading.Event()

        # Use a real temporary file so we can reconnect after the worker closes
        # its own connection (worker always calls db.close() in finally).
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            # Populate schema in the temp file
            setup_db = sqlite3.connect(tmp_path)
            setup_db.row_factory = sqlite3.Row
            setup_db.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_screenshots (
                    observation_id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL DEFAULT '',
                    captured_at TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT ''
                );
                """
            )
            setup_db.close()

            # Run the worker with mocked analyze and the temp DB path
            with patch.object(tracker_main, "analyze_screenshot", return_value="A desktop with PDF documents open"), \
                 patch.object(tracker_main, "is_ollama_available", return_value=True), \
                 patch.object(tracker_main, "DB_PATH", tmp_path):

                item = (42, datetime.now(timezone.utc), "explorer.exe", "Untitled window", b"fake_jpeg")
                tracker_main.screenshot_queue.put(item)
                tracker_main.screenshot_queue.put(None)  # Sentinel to exit worker

                # screenshot_worker opens its own connection using DB_PATH,
                # processes the item, writes the description, and closes it.
                tracker_main.screenshot_worker(stop_event)

            # Open a fresh connection to verify the persisted record.
            verify_db = sqlite3.connect(tmp_path)
            verify_db.row_factory = sqlite3.Row
            row = verify_db.execute(
                "SELECT observation_id, path, description FROM activity_screenshots WHERE observation_id = 42"
            ).fetchone()
            verify_db.close()

            self.assertIsNotNone(row)
            self.assertEqual(row["observation_id"], 42)
            self.assertEqual(row["path"], "")
            self.assertEqual(row["description"], "A desktop with PDF documents open")

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 7. Timeline Integration and Stored Vision Reuse
# ---------------------------------------------------------------------------


class TestTimelineReuse(unittest.TestCase):
    def test_timeline_uses_stored_vision_for_ambiguous_window(self):
        """ai_timeline must leverage stored vision description for ambiguous window."""
        db = _create_test_db()
        # Insert observation
        db.execute(
            """
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (10, 'active', 'explorer.exe', 'Untitled window', '2026-10-20T14:00:00Z', '2026-10-20T14:10:00Z', 600.0)
            """
        )
        # Insert stored vision description
        db.execute(
            """
            INSERT INTO activity_screenshots (observation_id, path, captured_at, description)
            VALUES (10, '', '2026-10-20T14:00:05Z', 'Viewing a warrior wallpaper with desktop document shortcuts')
            """
        )
        db.commit()

        session = {
            "kind": "active",
            "app": "explorer.exe",
            "title": "Untitled window",
            "titles": {"Untitled window"},
            "observation_ids": [10],
            "start": datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 10, 20, 14, 10, tzinfo=timezone.utc),
            "duration_seconds": 600.0,
            "url": "",
        }

        stored_vision = ai_timeline._stored_vision_description(db, session)
        self.assertEqual(stored_vision, "Viewing a warrior wallpaper with desktop document shortcuts")

        desc, conf, src, is_unc = ai_timeline.infer_evidence_description(session, stored_vision)
        self.assertIn("Visual context:", desc)
        self.assertIn("warrior wallpaper", desc)
        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(src, "vision")
        self.assertFalse(is_unc)
        db.close()

    def test_timeline_marks_uncertain_when_no_vision_for_ambiguous(self):
        """Without stored vision description, ambiguous window is marked uncertain."""
        session = {
            "kind": "active",
            "app": "explorer.exe",
            "title": "Untitled window",
            "titles": {"Untitled window"},
            "observation_ids": [99],
            "url": "",
        }
        desc, conf, src, is_unc = ai_timeline.infer_evidence_description(session, stored_vision=None)
        self.assertTrue(is_unc)
        self.assertIn("unclear", desc.lower())


# ---------------------------------------------------------------------------
# 8. Shutdown Responsiveness and Observation Safety
# ---------------------------------------------------------------------------


class TestShutdownResponsiveness(unittest.TestCase):
    def test_close_observation_called_safely(self):
        """Active observation must be closed with end_time and duration."""
        db = _create_test_db()
        start = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        db.execute(
            "INSERT INTO observations (id, kind, app, title, start_time) VALUES (1, 'active', 'Code.exe', 'test', ?)",
            (start.isoformat(),),
        )
        db.commit()

        end = datetime(2026, 10, 20, 10, 5, tzinfo=timezone.utc)
        tracker_main.close_observation(db, 1, end)

        row = db.execute("SELECT end_time, duration_seconds FROM observations WHERE id = 1").fetchone()
        self.assertIsNotNone(row["end_time"])
        self.assertEqual(row["duration_seconds"], 300.0)
        db.close()


if __name__ == "__main__":
    unittest.main()

