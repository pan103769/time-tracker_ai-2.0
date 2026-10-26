"""
test_edit_profile.py — Test suite for editable username profile feature.
Verifies:
- Default display name ('pant')
- Updating display name via /api/settings
- Persistence across application restart / fresh DB connections
- Preserving tracking observations, goals, and categories
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from api.migrations import run_migrations
import api.windows_notifier as win_notifier
from api.server import app


class TestEditProfile(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tracker.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        run_migrations(conn)

        # Seed sample tracking observation & goal to verify they are unaffected
        conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, duration_seconds)
            VALUES ('active', 'code.exe', 'server.py', '2026-10-25T10:00:00', 3600.0)
            """
        )
        conn.execute(
            """
            INSERT INTO goals (title, metric, target_seconds, created_at)
            VALUES ('Coding Practice', 'focus_time', 14400, '2026-10-25T10:00:00')
            """
        )
        conn.commit()
        conn.close()

        self.client = TestClient(app)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_default_username(self):
        """Verify default username is 'pant' when no user_name has been saved."""
        settings = win_notifier.get_notification_settings(self.db_path)
        self.assertEqual(settings.get("user_name"), "pant")

    def test_update_username_and_persistence(self):
        """Verify updating username persists to DB and survives restart."""
        # 1. Update username directly in db settings
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('user_name', 'Alex Mercer', '2026-10-25T10:00:00')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """
        )
        conn.commit()
        conn.close()

        # 2. Simulate application restart: load settings from scratch
        settings_after_restart = win_notifier.get_notification_settings(self.db_path)
        self.assertEqual(settings_after_restart.get("user_name"), "Alex Mercer")

    def test_update_username_via_api(self):
        """Test PUT /api/settings updates user_name properly."""
        orig_win_db = win_notifier.DB_PATH
        import api.server as server_mod
        orig_server_db = server_mod.DB_PATH

        try:
            win_notifier.DB_PATH = self.db_path
            server_mod.DB_PATH = self.db_path

            # Update username
            res_put = self.client.put("/api/settings", json={"user_name": "Hero Coder"})
            self.assertEqual(res_put.status_code, 200)
            data = res_put.json()
            self.assertEqual(data.get("user_name"), "Hero Coder")

            # Verify persistent in fresh get
            res_verify = self.client.get("/api/settings")
            self.assertEqual(res_verify.status_code, 200)
            self.assertEqual(res_verify.json().get("user_name"), "Hero Coder")

            # 3. Verify tracking data & goals are completely untouched
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            obs_row = conn.execute("SELECT * FROM observations WHERE app = 'code.exe'").fetchone()
            self.assertIsNotNone(obs_row)
            self.assertEqual(obs_row["duration_seconds"], 3600.0)

            goal_row = conn.execute("SELECT * FROM goals WHERE title = 'Coding Practice'").fetchone()
            self.assertIsNotNone(goal_row)
            self.assertEqual(goal_row["target_seconds"], 14400)
            conn.close()
        finally:
            win_notifier.DB_PATH = orig_win_db
            server_mod.DB_PATH = orig_server_db


if __name__ == "__main__":
    unittest.main()

