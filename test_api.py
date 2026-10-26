"""
test_api.py — Unit and integration tests for FastAPI backend routes in api/server.py.
Uses a temporary isolated database to verify endpoints, validation, and editing without
touching tracker.db.
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api.server as server_module
from api.server import app


def _create_test_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
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

    # Run migrations to ensure categories, rules, goals, time_blocks exist
    import api.migrations as migrations
    migrations.run_migrations(conn)

    # Insert test observation
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc).isoformat()
    end = datetime(2026, 10, 20, 10, 15, 0, tzinfo=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
        VALUES (1, 'active', 'Code.exe', 'server.py - project - Visual Studio Code', ?, ?, 900.0)
        """,
        (start, end),
    )
    conn.commit()
    conn.close()


class TestApiServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.tmp_path = Path(self._tmp.name)
        _create_test_db(self.tmp_path)
        self.client = TestClient(app)

    def tearDown(self):
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass

    def test_health_endpoint(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            resp = self.client.get("/api/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["db_exists"])

    def test_active_dates_endpoint(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            resp = self.client.get("/api/dates/active")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("dates", data)
            self.assertIn("2026-10-20", data["dates"])

    def test_timeline_endpoint_success(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            resp = self.client.get("/api/timeline/2026-10-20")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            session = data[0]
            self.assertEqual(session["app"], "Code.exe")
            self.assertIn("Visual Studio Code", session["title"])
            self.assertEqual(session["display_number"], 1)
            self.assertIn("is_ongoing", session)
            self.assertFalse(session["is_ongoing"])

    def test_timeline_endpoint_with_ongoing_session(self):
        # Insert an ongoing observation (end_time is NULL)
        conn = sqlite3.connect(self.tmp_path)
        start = datetime(2026, 10, 20, 10, 20, 0, tzinfo=timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO observations (kind, app, title, start_time, end_time) VALUES ('active', 'Chrome.exe', 'Google Search', ?, NULL)",
            (start,),
        )
        conn.commit()
        conn.close()

        with patch.object(server_module, "DB_PATH", self.tmp_path):
            resp = self.client.get("/api/timeline/2026-10-20")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(len(data), 2)
            ongoing = next((s for s in data if s["app"] == "Chrome.exe"), None)
            self.assertIsNotNone(ongoing)
            self.assertTrue(ongoing["is_ongoing"])

    def test_timeline_endpoint_invalid_date(self):
        resp = self.client.get("/api/timeline/invalid-date")
        self.assertEqual(resp.status_code, 422)

    def test_stats_endpoint_success(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            resp = self.client.get("/api/stats/2026-10-20")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["date"], "2026-10-20")
            self.assertTrue(data["has_data"])
            self.assertGreater(data["active_seconds"], 0)
            self.assertEqual(len(data["app_breakdown"]), 1)
            self.assertEqual(data["app_breakdown"][0]["app"], "Code.exe")

    def test_weekly_stats_endpoint(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            resp = self.client.get("/api/stats/weekly/2026-10-20")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(len(data["days"]), 7)
            last_day = data["days"][-1]
            self.assertEqual(last_day["date"], "2026-10-20")
            self.assertGreater(last_day["active_seconds"], 0)

    def test_edit_and_delete_session_description(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            # 1. Fetch session key
            t_resp = self.client.get("/api/timeline/2026-10-20")
            session_key = t_resp.json()[0]["session_key"]
            self.assertTrue(session_key)

            # 2. Edit session description
            edit_resp = self.client.post(
                f"/api/timeline/2026-10-20/sessions/{session_key}/edit",
                json={"description": "Refactoring API routes"},
            )
            self.assertEqual(edit_resp.status_code, 200)
            self.assertEqual(edit_resp.json()["status"], "saved")

            # 3. Verify updated description in timeline
            t_updated = self.client.get("/api/timeline/2026-10-20").json()
            self.assertEqual(t_updated[0]["user_description"], "Refactoring API routes")
            self.assertEqual(t_updated[0]["description"], "Refactoring API routes")

            # 4. Delete user edit
            del_resp = self.client.delete(
                f"/api/timeline/2026-10-20/sessions/{session_key}/edit"
            )
            self.assertEqual(del_resp.status_code, 200)
            self.assertEqual(del_resp.json()["status"], "deleted")

            # 5. Verify restored to original AI description
            t_restored = self.client.get("/api/timeline/2026-10-20").json()
            self.assertIsNone(t_restored[0]["user_description"])

    def test_tracker_status_endpoint(self):
        resp = self.client.get("/api/tracker/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("is_tracking", data)
        self.assertIn("status_text", data)
        self.assertIn("message", data)

    def test_tracker_active_task_endpoint(self):
        with patch("api.tracker_manager.get_active_task", return_value={
            "observation_id": 99,
            "kind": "active",
            "app": "Code.exe",
            "title": "server.py",
            "start_time": "2026-10-22T12:00:00",
            "is_open": True,
        }):
            resp = self.client.get("/api/tracker/active-task")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["observation_id"], 99)
            self.assertEqual(data["app"], "Code.exe")
            self.assertEqual(data["title"], "server.py")
            self.assertTrue(data["is_open"])

    def test_tracker_start_stop_toggle_endpoints(self):
        with patch("api.tracker_manager.start_tracking", return_value={"is_tracking": True, "pid": 9999, "status_text": "Tracking ON", "message": "Started."}) as mock_start, \
             patch("api.tracker_manager.stop_tracking", return_value={"is_tracking": False, "pid": None, "status_text": "Tracking OFF", "message": "Stopped."}) as mock_stop, \
             patch("api.tracker_manager.is_tracking_active", side_effect=[False, True]):

            # 1. Start tracker
            start_resp = self.client.post("/api/tracker/start")
            self.assertEqual(start_resp.status_code, 200)
            self.assertTrue(start_resp.json()["is_tracking"])
            mock_start.assert_called_once()

            # 2. Stop tracker
            stop_resp = self.client.post("/api/tracker/stop")
            self.assertEqual(stop_resp.status_code, 200)
            self.assertFalse(stop_resp.json()["is_tracking"])
            mock_stop.assert_called_once()

            # 3. Toggle when inactive -> should start
            toggle_1 = self.client.post("/api/tracker/toggle")
            self.assertEqual(toggle_1.status_code, 200)
            self.assertEqual(mock_start.call_count, 2)

            # 4. Toggle when active -> should stop
            toggle_2 = self.client.post("/api/tracker/toggle")
            self.assertEqual(toggle_2.status_code, 200)
            self.assertEqual(mock_stop.call_count, 2)

    def test_autostart_endpoints(self):
        with patch("api.autostart.is_autostart_enabled", side_effect=[False, True, False]), \
             patch("api.autostart.get_autostart_command", return_value='"pythonw.exe" "main.py"'), \
             patch("api.autostart.enable_autostart", return_value=(True, '"pythonw.exe" "main.py"')), \
             patch("api.autostart.disable_autostart", return_value=(True, "Autostart disabled successfully.")):

            # 1. Status when disabled
            resp_status = self.client.get("/api/autostart/status")
            self.assertEqual(resp_status.status_code, 200)
            self.assertFalse(resp_status.json()["enabled"])

            # 2. Enable
            resp_enable = self.client.post("/api/autostart/enable")
            self.assertEqual(resp_enable.status_code, 200)
            self.assertTrue(resp_enable.json()["enabled"])

            # 3. Disable
            resp_disable = self.client.post("/api/autostart/disable")
            self.assertEqual(resp_disable.status_code, 200)
            self.assertFalse(resp_disable.json()["enabled"])

            # 4. Toggle when disabled -> should enable
            resp_toggle = self.client.post("/api/autostart/toggle")
            self.assertEqual(resp_toggle.status_code, 200)

    def test_categories_endpoints(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            # 1. GET /api/categories
            cats_resp = self.client.get("/api/categories")
            self.assertEqual(cats_resp.status_code, 200)
            cats = cats_resp.json()
            self.assertGreaterEqual(len(cats), 1)

            # 2. POST /api/categories
            new_cat_resp = self.client.post(
                "/api/categories",
                json={"name": "UI/UX Design", "color": "#06b6d4", "type": "focus"},
            )
            self.assertEqual(new_cat_resp.status_code, 200)
            new_cat = new_cat_resp.json()
            cat_id = new_cat["id"]

            # 3. GET /api/categories/rules
            rules_resp = self.client.get("/api/categories/rules")
            self.assertEqual(rules_resp.status_code, 200)

            # 4. POST /api/categories/rules
            new_rule_resp = self.client.post(
                "/api/categories/rules",
                json={"category_id": cat_id, "match_type": "app", "pattern": "figma.exe", "priority": 25},
            )
            self.assertEqual(new_rule_resp.status_code, 200)
            rule_id = new_rule_resp.json()["id"]

            # 5. DELETE rule
            del_rule_resp = self.client.delete(f"/api/categories/rules/{rule_id}")
            self.assertEqual(del_rule_resp.status_code, 200)

            # 6. DELETE category
            del_cat_resp = self.client.delete(f"/api/categories/{cat_id}")
            self.assertEqual(del_cat_resp.status_code, 200)

    def test_goals_and_time_blocks_endpoints(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            # 1. GET /api/goals
            goals_resp = self.client.get("/api/goals")
            self.assertEqual(goals_resp.status_code, 200)
            goals = goals_resp.json()
            self.assertGreaterEqual(len(goals), 1)

            # 2. POST /api/goals
            new_goal_resp = self.client.post(
                "/api/goals",
                json={"title": "Test Goal", "metric": "work_time", "target_seconds": 7200, "is_inversion": False},
            )
            self.assertEqual(new_goal_resp.status_code, 200)
            goal_id = new_goal_resp.json()["id"]

            # 3. GET /api/goals/progress/2026-10-20
            prog_resp = self.client.get("/api/goals/progress/2026-10-20")
            self.assertEqual(prog_resp.status_code, 200)

            # 4. POST /api/time-blocks
            block_resp = self.client.post(
                "/api/time-blocks",
                json={"date": "2026-10-20", "start_time": "10:00", "end_time": "11:00", "title": "Test Block"},
            )
            self.assertEqual(block_resp.status_code, 200)
            block_id = block_resp.json()["id"]

            # 5. GET /api/time-blocks/analysis/2026-10-20
            analysis_resp = self.client.get("/api/time-blocks/analysis/2026-10-20")
            self.assertEqual(analysis_resp.status_code, 200)
            self.assertEqual(len(analysis_resp.json()), 1)

            # 6. Clean up
            self.client.delete(f"/api/time-blocks/{block_id}")
            self.client.delete(f"/api/goals/{goal_id}")

    def test_productivity_and_insights_endpoints(self):
        with patch.object(server_module, "DB_PATH", self.tmp_path):
            prod_resp = self.client.get("/api/productivity/2026-10-20")
            self.assertEqual(prod_resp.status_code, 200)
            prod = prod_resp.json()
            self.assertIn("productivity_score", prod)
            self.assertIn("total_work_label", prod)

            insights_resp = self.client.get("/api/insights/summary/2026-10-20")
            self.assertEqual(insights_resp.status_code, 200)
            insights = insights_resp.json()
            self.assertIn("key_takeaway", insights)
            self.assertIn("recommendations", insights)

    def test_widget_status_endpoint(self):
        resp = self.client.get("/api/widget/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("is_running", resp.json())


if __name__ == "__main__":
    unittest.main()

