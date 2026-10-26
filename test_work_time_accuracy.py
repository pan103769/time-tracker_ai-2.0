"""
test_work_time_accuracy.py — Verification suite for Daily Work Time, Focus Time,
and Productivity Metric calculations across the engine, goals, and API.
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from ai_timeline import group_into_sessions, load_observations
from api.categories import match_category
from api.goals import create_goal, evaluate_goals, get_goals
from api.insights import compute_daily_productivity, generate_daily_ai_summary
from api.migrations import now_iso, run_migrations


class TestWorkTimeAccuracy(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        run_migrations(self.db)
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER,
                path TEXT,
                captured_at TEXT,
                description TEXT
            )
            """
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_productive_work_time_excludes_distraction_and_personal(self):
        """
        Verify that Productive Work Time counts ONLY focus and work categories,
        and excludes idle, entertainment (distractions), and uncategorized (personal).
        """
        date_str = "2026-10-25"
        sessions = [
            # 1. Focus: Coding (2 hours = 7200s)
            {
                "kind": "active",
                "duration_seconds": 7200.0,
                "category_name": "Coding & Development",
                "category_type": "focus",
                "category_color": "#8065FF",
            },
            # 2. Focus: Study / Research (1 hour = 3600s)
            {
                "kind": "active",
                "duration_seconds": 3600.0,
                "category_name": "Research & Learning",
                "category_type": "focus",
                "category_color": "#38BDF8",
            },
            # 3. Work: Planning & Meetings (1 hour = 3600s)
            {
                "kind": "active",
                "duration_seconds": 3600.0,
                "category_name": "Planning & Management",
                "category_type": "work",
                "category_color": "#16D5E2",
            },
            # 4. Distraction: YouTube & Gaming (2.5 hours = 9000s)
            {
                "kind": "active",
                "duration_seconds": 9000.0,
                "category_name": "Entertainment & Media",
                "category_type": "distraction",
                "category_color": "#FA5275",
            },
            # 5. Personal / Uncategorized: (0.5 hours = 1800s)
            {
                "kind": "active",
                "duration_seconds": 1800.0,
                "category_name": "Other / Uncategorized",
                "category_type": "personal",
                "category_color": "#6B7280",
            },
            # 6. Idle gap: (1 hour = 3600s)
            {
                "kind": "idle",
                "duration_seconds": 3600.0,
                "category_name": "Idle",
                "category_type": "idle",
                "category_color": "#4B5563",
            },
        ]

        metrics = compute_daily_productivity(self.db, date_str, sessions)

        # Total Active Tracked Time: 7200 + 3600 + 3600 + 9000 + 1800 = 25200s (7.0 hours)
        self.assertEqual(metrics["total_tracked_seconds"], 25200.0)
        self.assertEqual(metrics["total_tracked_label"], "7h 0m")

        # Productive Work Time: 7200 (Coding) + 3600 (Research) + 3600 (Planning) = 14400s (4.0 hours)
        # MUST NOT include the 9000s distraction or 1800s uncategorized or 3600s idle!
        self.assertEqual(metrics["productive_work_seconds"], 14400.0)
        self.assertEqual(metrics["total_work_seconds"], 14400.0)
        self.assertEqual(metrics["productive_work_label"], "4h 0m")
        self.assertEqual(metrics["total_work_label"], "4h 0m")

        # Focus Time: 7200 + 3600 = 10800s (3.0 hours)
        self.assertEqual(metrics["focus_seconds"], 10800.0)
        self.assertEqual(metrics["focus_label"], "3h 0m")

        # Study Time: 3600s (1.0 hour)
        self.assertEqual(metrics["study_seconds"], 3600.0)
        self.assertEqual(metrics["study_label"], "1h 0m")

        # Distraction Time: 9000s (2.5 hours)
        self.assertEqual(metrics["distraction_seconds"], 9000.0)
        self.assertEqual(metrics["distraction_label"], "2h 30m")

        # Unclassified Time: 1800s (30m)
        self.assertEqual(metrics["unclassified_seconds"], 1800.0)
        self.assertEqual(metrics["unclassified_label"], "30m 0s")

        # Mathematical reconciliation check:
        # Total Tracked == Productive Work + Distraction + Unclassified
        self.assertEqual(
            metrics["total_tracked_seconds"],
            metrics["productive_work_seconds"] + metrics["distraction_seconds"] + metrics["unclassified_seconds"],
        )

    def test_goals_use_productive_work_time_not_total_screen_time(self):
        """
        Verify that the Daily Work Time goal calculates progress based solely on
        Productive Work Time (e.g. 2h productive work on a 5h goal = 40% progress),
        ignoring non-work activities like entertainment.
        """
        date_str = "2026-10-25"

        # Clear any seeded goals to test explicitly
        self.db.execute("DELETE FROM goals")
        self.db.commit()

        # Goal: 5 hours of work (18,000s)
        create_goal(self.db, "Daily Work Time", "work_time", 18000, is_inversion=False)
        # Goal: Max 1 hour distraction (3,600s inversion)
        create_goal(self.db, "Limit Distraction", "distraction_time", 3600, is_inversion=True)

        sessions = [
            # 2 hours of Coding (Productive)
            {
                "kind": "active",
                "duration_seconds": 7200.0,
                "category_type": "focus",
                "category_name": "Coding & Development",
            },
            # 4 hours of Netflix & Gaming (Distraction)
            {
                "kind": "active",
                "duration_seconds": 14400.0,
                "category_type": "distraction",
                "category_name": "Entertainment & Media",
            },
        ]

        goal_results = evaluate_goals(self.db, date_str, sessions)
        self.assertEqual(len(goal_results), 2)

        work_goal = [g for g in goal_results if g["metric"] == "work_time"][0]
        # Actual work seconds should be 7200s (2h), NOT 21600s (6h)!
        self.assertEqual(work_goal["actual_seconds"], 7200.0)
        self.assertEqual(work_goal["actual_label"], "2h 0m")
        self.assertEqual(work_goal["progress_pct"], 40.0)
        self.assertFalse(work_goal["is_achieved"])
        self.assertIn("3h 0m to target", work_goal["status_text"])

        distraction_goal = [g for g in goal_results if g["metric"] == "distraction_time"][0]
        self.assertEqual(distraction_goal["actual_seconds"], 14400.0)
        self.assertFalse(distraction_goal["is_achieved"])
        self.assertIn("over limit", distraction_goal["status_text"])

    def test_interval_deduplication_and_overlap_in_load_observations(self):
        """
        Verify that duplicate interval submissions (e.g. repeated manual entries)
        and overlapping idle observations during manual entry are deduplicated.
        """
        start_time = "2026-10-25T14:00:00+00:00"
        end_time = "2026-10-25T14:30:00+00:00"

        # Insert 3 identical manual entry rows
        for _ in range(3):
            self.db.execute(
                """
                INSERT INTO observations (app, title, start_time, end_time, duration_seconds, kind, task)
                VALUES ('Manual Entry', 'Project Architecture', ?, ?, 1800, 'active', 'Design Review')
                """,
                (start_time, end_time),
            )

        # Insert an overlapping idle observation during that window
        self.db.execute(
            """
            INSERT INTO observations (app, title, start_time, end_time, duration_seconds, kind)
            VALUES ('Idle', 'Idle', '2026-10-25T14:10:00+00:00', '2026-10-25T14:20:00+00:00', 600, 'idle')
            """
        )
        self.db.commit()

        range_start = datetime(2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc)
        range_end = datetime(2026, 10, 25, 23, 59, 59, tzinfo=timezone.utc)

        obs = load_observations(self.db, range_start, range_end)
        # Should have deduplicated the 3 manual entries down to 1
        manual_obs = [o for o in obs if o["app"] == "Manual Entry"]
        self.assertEqual(len(manual_obs), 1)
        self.assertEqual(manual_obs[0]["duration_seconds"], 1800.0)

        # Overlapping idle observation inside manual window must be suppressed/discarded
        idle_obs = [o for o in obs if o["kind"] == "idle"]
        self.assertEqual(len(idle_obs), 0)

    def test_session_extension_non_overlapping_duration(self):
        """
        Verify that session merging does not double-count overlapping time intervals.
        """
        start_dt = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        obs_list = [
            {
                "id": 1,
                "app": "Code.exe",
                "title": "server.py - VS Code",
                "start": start_dt,
                "end": start_dt + timedelta(minutes=20),
                "duration_seconds": 1200.0,
                "kind": "active",
                "task": "Backend Development",
            },
            # Second observation starts at 10:15 (overlapping by 5 min) and ends at 10:30 (15 min extension)
            {
                "id": 2,
                "app": "Code.exe",
                "title": "server.py - VS Code",
                "start": start_dt + timedelta(minutes=15),
                "end": start_dt + timedelta(minutes=30),
                "duration_seconds": 900.0,
                "kind": "active",
                "task": "Backend Development",
            },
        ]

        sessions = group_into_sessions(obs_list, [])
        self.assertEqual(len(sessions), 1)
        # Total span is 10:00 to 10:30 = 30 minutes = 1800s.
        # With naive summation it would have been 1200 + 900 = 2100s (35 min).
        self.assertEqual(sessions[0]["duration_seconds"], 1800.0)
        self.assertEqual(sessions[0]["end"], start_dt + timedelta(minutes=30))

    def test_api_stats_and_weekly_endpoints(self):
        """
        Verify that FastAPI stats and weekly endpoints return explicit productive_work_seconds
        alongside total active_seconds.
        """
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import api.server as server_mod

        test_date = "2026-10-25"
        # Seed observations for test_date in self.db
        start_dt = f"{test_date}T10:00:00+00:00"
        end_dt = f"{test_date}T11:00:00+00:00"
        self.db.execute(
            """
            INSERT INTO observations (app, title, start_time, end_time, duration_seconds, kind)
            VALUES ('Code.exe', 'server.py - Visual Studio Code', ?, ?, 3600, 'active')
            """,
            (start_dt, end_dt),
        )
        # Seed a distraction observation
        self.db.execute(
            """
            INSERT INTO observations (app, title, start_time, end_time, duration_seconds, kind)
            VALUES ('chrome.exe', 'YouTube - Watch funny cats', '2026-10-25T11:00:00+00:00', '2026-10-25T12:00:00+00:00', 3600, 'active')
            """
        )
        self.db.commit()

        # Patch DB_PATH in api.server to point to our test database file
        with patch.object(server_mod, "DB_PATH", Path(self.db_path)):
            client = TestClient(server_mod.app)

            # 1. /api/stats/{date_str}
            resp = client.get(f"/api/stats/{test_date}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            # Total tracked: 7200s (2h)
            self.assertEqual(data["active_seconds"], 7200.0)
            # Productive work: only Code.exe (3600s), NOT YouTube!
            self.assertEqual(data["productive_work_seconds"], 3600.0)
            self.assertEqual(data["distraction_seconds"], 3600.0)

            # 2. /api/stats/weekly/{date_str}
            resp_weekly = client.get(f"/api/stats/weekly/{test_date}")
            self.assertEqual(resp_weekly.status_code, 200)
            w_data = resp_weekly.json()
            self.assertEqual(len(w_data["days"]), 7)
            today_day = [d for d in w_data["days"] if d["date"] == test_date][0]
            self.assertEqual(today_day["active_seconds"], 7200.0)
            self.assertEqual(today_day["productive_work_seconds"], 3600.0)
            self.assertEqual(today_day["distraction_seconds"], 3600.0)

            # 3. /api/productivity/{date_str}
            with patch("api.insights.evaluate_goals", return_value=[]):
                resp_prod = client.get(f"/api/productivity/{test_date}")
                self.assertEqual(resp_prod.status_code, 200)
                p_data = resp_prod.json()
                self.assertEqual(p_data["productive_work_seconds"], 3600.0)
                self.assertEqual(p_data["total_work_seconds"], 3600.0)
                self.assertEqual(p_data["total_tracked_seconds"], 7200.0)
                self.assertEqual(p_data["distraction_seconds"], 3600.0)


if __name__ == "__main__":
    unittest.main()
