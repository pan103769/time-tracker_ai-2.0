"""
test_desktop_lifecycle.py — Integration test for tracking, widget status,
and database writes in desktop mode.
"""

import sqlite3
import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from api.server import app
from activity_report import DB_PATH
import api.tracker_manager as tracker_mgr


class TestDesktopLifecycle(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_widget_status_endpoint(self):
        """Test widget status endpoint responds with valid json."""
        r = self.client.get("/api/widget/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("is_running", data)
        self.assertIn("pids", data)

    def test_tracker_status_endpoint(self):
        """Test tracker status endpoint responds."""
        r = self.client.get("/api/tracker/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("is_tracking", data)
        self.assertIn("status_text", data)

    def test_database_observations_table_readable(self):
        """Verify tracker.db observations are intact and queryable."""
        self.assertTrue(DB_PATH.exists())
        conn = sqlite3.connect(str(DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.close()
        self.assertGreater(count, 0, "Historical observations must be preserved")

    def test_frontend_dist_served_via_fastapi(self):
        """Verify root and assets are served by FastAPI."""
        r_root = self.client.get("/")
        self.assertEqual(r_root.status_code, 200)
        self.assertIn("<title>Time Tracker AI", r_root.text)
        self.assertIn('id="root"', r_root.text)

        r_icon = self.client.get("/favicon.svg")
        self.assertEqual(r_icon.status_code, 200)

        # Non-existent API route returns 404, not index.html
        r_api = self.client.get("/api/nonexistent_endpoint_12345")
        self.assertEqual(r_api.status_code, 404)


if __name__ == "__main__":
    unittest.main()

