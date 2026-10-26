"""
test_tracker_manager.py — Unit tests for tracking process manager in api/tracker_manager.py.
Validates process detection, mutex checking, starting, stopping, duplicate prevention,
and observation recovery without corrupting tracker.db.
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import api.tracker_manager as tm


class TestTrackerManager(unittest.TestCase):
    def setUp(self):
        # Reset internal manager references
        tm._managed_tracker_proc = None
        tm._managed_browser_proc = None
        tm._intentional_stop = False
        tm._last_exit_code = None
        tm._last_exit_message = None

    def test_get_tracking_status_structure(self):
        with patch.object(tm, "is_tracking_active", return_value=False):
            status = tm.get_tracking_status()
            self.assertFalse(status["is_tracking"])
            self.assertIsNone(status["pid"])
            self.assertEqual(status["status_text"], "Tracking OFF")
            self.assertIn("message", status)

    def test_get_active_task(self):
        """get_active_task should return the most recent observation dict."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = Path(f.name)
        try:
            conn = sqlite3.connect(tmp_db)
            conn.execute(
                """
                CREATE TABLE observations (
                    id INTEGER PRIMARY KEY,
                    kind TEXT,
                    app TEXT,
                    title TEXT,
                    start_time TEXT,
                    end_time TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO observations VALUES (42, 'active', 'Code.exe', 'server.py', '2026-10-22T10:00:00', NULL)"
            )
            conn.commit()
            conn.close()

            with patch.object(tm, "DB_PATH", tmp_db):
                task = tm.get_active_task()
                self.assertIsNotNone(task)
                self.assertEqual(task["observation_id"], 42)
                self.assertEqual(task["app"], "Code.exe")
                self.assertEqual(task["title"], "server.py")
                self.assertTrue(task["is_open"])
        finally:
            try:
                os.unlink(tmp_db)
            except OSError:
                pass

    def test_unexpected_exit_message(self):
        """When tracker process crashes, status must return unexpected exit message."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.return_value = 1
        mock_proc.returncode = 1
        tm._managed_tracker_proc = mock_proc
        tm._intentional_stop = False

        with patch.object(tm, "is_mutex_active", return_value=False), \
             patch.object(tm, "find_tracker_processes", return_value=[]):
            status = tm.get_tracking_status()
            self.assertFalse(status["is_tracking"])
            self.assertIn("unexpectedly", status["message"].lower())
            self.assertIn("1", status["message"])

    def test_find_tracker_processes_filtering(self):
        """CLI invocations of main.py (e.g. main.py ui) must not be treated as background tracker."""
        tracker_mock = MagicMock(pid=1001)
        tracker_mock.info = {"cmdline": ["python.exe", "C:\\project\\main.py"]}

        cli_mock = MagicMock(pid=1002)
        cli_mock.info = {"cmdline": ["python.exe", "C:\\project\\main.py", "timeline"]}

        with patch("psutil.process_iter", return_value=[tracker_mock, cli_mock]), \
             patch("os.getpid", return_value=9999):
            procs = tm.find_tracker_processes()
            pids = [p.pid for p in procs]
            self.assertIn(1001, pids)
            self.assertNotIn(1002, pids)

    def test_get_python_executable_prefers_venv(self):
        """Must prefer .venv/Scripts/python.exe if present."""
        with patch.object(Path, "exists", return_value=True):
            exe = tm.get_python_executable()
            self.assertTrue(exe.endswith("python.exe"))

    def test_get_tracking_status_active(self):
        with patch.object(tm, "is_tracking_active", return_value=True), \
             patch.object(tm, "find_tracker_processes", return_value=[MagicMock(pid=12345)]):
            status = tm.get_tracking_status()
            self.assertTrue(status["is_tracking"])
            self.assertEqual(status["pid"], 12345)
            self.assertEqual(status["status_text"], "Tracking ON")

    def test_prevent_duplicate_tracking_on_start(self):
        """When tracker is already active, start_tracking must not spawn duplicate process."""
        with patch.object(tm, "is_tracking_active", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            res = tm.start_tracking()
            self.assertTrue(res["is_tracking"])
            self.assertIn("already running", res["message"].lower())
            mock_popen.assert_not_called()

    def test_stop_tracking_when_already_stopped(self):
        """When tracker is stopped, stop_tracking must return safely."""
        with patch.object(tm, "is_tracking_active", return_value=False), \
             patch.object(tm, "_recover_dangling_observations", return_value=0):
            res = tm.stop_tracking()
            self.assertFalse(res["is_tracking"])
            self.assertIn("already stopped", res["message"].lower())

    def test_recover_dangling_observations(self):
        """Dangling observations with end_time NULL must be closed with non-null duration."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = Path(f.name)

        try:
            conn = sqlite3.connect(tmp_db)
            conn.execute(
                """
                CREATE TABLE observations (
                    id INTEGER PRIMARY KEY,
                    kind TEXT,
                    app TEXT,
                    title TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    duration_seconds REAL
                )
                """
            )
            # Insert unfinished observation
            start_iso = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds) VALUES (1, 'active', 'Code.exe', 'test', ?, NULL, NULL)",
                (start_iso,),
            )
            conn.commit()
            conn.close()

            with patch.object(tm, "DB_PATH", tmp_db):
                recovered = tm._recover_dangling_observations()
                self.assertEqual(recovered, 1)

                verify_conn = sqlite3.connect(tmp_db)
                row = verify_conn.execute("SELECT end_time, duration_seconds FROM observations WHERE id = 1").fetchone()
                verify_conn.close()

                self.assertIsNotNone(row[0])  # end_time
                self.assertIsNotNone(row[1])  # duration_seconds
                self.assertGreaterEqual(row[1], 0.0)

        finally:
            try:
                os.unlink(tmp_db)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()

