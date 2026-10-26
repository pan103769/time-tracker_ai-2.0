"""
test_integration.py — Integration tests for timeline accessibility and command dispatching.

Covers:
- main.py CLI command dispatching (timeline, report, help).
- timeline.py default delegation to ai_timeline.
- timeline.py --raw legacy support.
- Date selection and argument forwarding.
- Mutex isolation (viewing timeline does not start or block tracking).
- Offline Ollama resilience through entry points.
- Preservation of user-edited descriptions and raw observations.
"""

import io
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import ai_timeline
import main as tracker_main
import timeline


class TestMainCliIntegration(unittest.TestCase):
    """Test main.py command-line dispatcher."""

    def test_main_help_prints_commands_and_returns_zero(self):
        with patch("sys.argv", ["main.py", "help"]), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            exit_code = tracker_main.main()
            self.assertEqual(exit_code, 0)
            output = mock_out.getvalue()
            self.assertIn("timeline", output)
            self.assertIn("report", output)
            self.assertIn("browser_tracker.py", output)

    def test_main_help_flag_variants(self):
        for flag in ("--help", "-h"):
            with patch("sys.argv", ["main.py", flag]), \
                 patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                exit_code = tracker_main.main()
                self.assertEqual(exit_code, 0)
                self.assertIn("Available Commands", mock_out.getvalue())

    def test_main_timeline_dispatches_to_ai_timeline(self):
        with patch("sys.argv", ["main.py", "timeline", "2026-10-20", "--no-idle"]), \
             patch("ai_timeline.main", return_value=0) as mock_ai_main:
            exit_code = tracker_main.main()
            self.assertEqual(exit_code, 0)
            mock_ai_main.assert_called_once_with(["2026-10-20", "--no-idle"])

    def test_main_timeline_flag_variants(self):
        for flag in ("--timeline", "-t"):
            with patch("sys.argv", ["main.py", flag, "2026-10-18"]), \
                 patch("ai_timeline.main", return_value=0) as mock_ai_main:
                exit_code = tracker_main.main()
                self.assertEqual(exit_code, 0)
                mock_ai_main.assert_called_once_with(["2026-10-18"])

    def test_main_timeline_does_not_acquire_mutex_or_start_tracker(self):
        """Viewing timeline must never acquire the tracker mutex or start threads."""
        with patch("sys.argv", ["main.py", "timeline"]), \
             patch("ai_timeline.main", return_value=0), \
             patch.object(tracker_main.kernel32, "CreateMutexW") as mock_mutex:
            tracker_main.main()
            mock_mutex.assert_not_called()

    def test_main_report_dispatches_to_report(self):
        with patch("sys.argv", ["main.py", "report", "2026-10-20"]), \
             patch("report.main", return_value=0) as mock_rep_main:
            exit_code = tracker_main.main()
            mock_rep_main.assert_called_once()


class TestTimelineEntrypoint(unittest.TestCase):
    """Test timeline.py entry point behavior."""

    def test_timeline_defaults_to_ai_timeline(self):
        with patch("ai_timeline.main", return_value=0) as mock_ai:
            exit_code = timeline.main(["2026-10-20"])
            self.assertEqual(exit_code, 0)
            mock_ai.assert_called_once_with(["2026-10-20"])

    def test_timeline_forwards_edit_flag(self):
        with patch("ai_timeline.main", return_value=0) as mock_ai:
            exit_code = timeline.main(["--edit", "2", "2026-10-20"])
            self.assertEqual(exit_code, 0)
            mock_ai.assert_called_once_with(["--edit", "2", "2026-10-20"])

    def test_timeline_raw_flag_runs_legacy(self):
        with patch("timeline.raw_timeline", return_value=0) as mock_raw:
            exit_code = timeline.main(["--raw", "2026-10-20"])
            self.assertEqual(exit_code, 0)
            mock_raw.assert_called_once_with(date(2026, 10, 20))

    def test_timeline_raw_invalid_date(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            exit_code = timeline.main(["--raw", "not-a-date"])
            self.assertEqual(exit_code, 1)
            self.assertIn("Invalid date", mock_out.getvalue())

    def test_timeline_format_duration_backward_compatibility(self):
        self.assertEqual(timeline.format_duration(45), "45s")
        self.assertEqual(timeline.format_duration(125), "2m 5s")
        self.assertEqual(timeline.format_duration(3665), "1h 1m 5s")


class TestIntegrationEndToEnd(unittest.TestCase):
    """End-to-end integration test against temporary database."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tracker.db"

        # Create minimal database
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                app TEXT NOT NULL,
                title TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds REAL
            )
        """)
        self.db.execute("""
            CREATE TABLE activity_screenshots (
                observation_id INTEGER PRIMARY KEY,
                path TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT ''
            )
        """)
        self.db.execute("""
            CREATE TABLE browser_visits (
                id INTEGER PRIMARY KEY,
                start_time TEXT NOT NULL,
                end_time TEXT,
                browser TEXT NOT NULL,
                title TEXT,
                url TEXT NOT NULL
            )
        """)

        # Insert sample activity
        t_base = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.db.execute("""
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (1, 'active', 'Code.exe', 'ai_timeline.py - time tracker ai 2 - Visual Studio Code',
                    ?, ?, 300.0)
        """, (t_base.isoformat(), (t_base + timedelta(minutes=5)).isoformat()))

        self.db.execute("""
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (2, 'active', 'chrome.exe', 'Activities | Hacktoberfest 2026 - Google Chrome',
                    ?, ?, 120.0)
        """, ((t_base + timedelta(minutes=5)).isoformat(), (t_base + timedelta(minutes=7)).isoformat()))
        self.db.commit()

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_timeline_renders_expected_descriptions_via_entrypoint(self):
        with patch.object(ai_timeline, "DB_PATH", self.db_path), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            exit_code = timeline.main(["2026-10-20", "--no-idle"])
            self.assertEqual(exit_code, 0)
            output = mock_out.getvalue()
            self.assertIn("AI ACTIVITY TIMELINE  2026-10-20", output)
            self.assertIn("Editing the AI timeline implementation in Python", output)
            self.assertIn("Reading the Hacktoberfest 2026 activities page", output)

    def test_user_edit_displayed_via_timeline_entrypoint(self):
        # Insert user edit
        ai_timeline.ensure_timeline_edits(self.db)
        key = ai_timeline.make_session_key("active", "Code.exe", 1)
        ai_timeline.save_user_edit(self.db, key, "Refactoring timeline CLI integration")

        with patch.object(ai_timeline, "DB_PATH", self.db_path), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            exit_code = timeline.main(["2026-10-20", "--no-idle"])
            self.assertEqual(exit_code, 0)
            output = mock_out.getvalue()
            self.assertIn("Refactoring timeline CLI integration [edited]", output)

    def test_raw_timeline_renders_via_timeline_entrypoint(self):
        with patch.object(timeline, "DB_PATH", self.db_path), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            exit_code = timeline.main(["--raw", "2026-10-20"])
            self.assertEqual(exit_code, 0)
            output = mock_out.getvalue()
            self.assertIn("RAW OBSERVATION TIMELINE", output)
            self.assertIn("Code.exe", output)
            self.assertIn("chrome.exe", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
