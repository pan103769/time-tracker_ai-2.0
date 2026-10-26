"""
test_goals.py — Unit tests for productivity goals evaluation and time block analysis.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import api.goals as ag
import api.migrations as am


class TestGoalsAndTimeBlocks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.tmp_path = Path(self._tmp.name)
        self.db = sqlite3.connect(self.tmp_path)
        self.db.row_factory = sqlite3.Row
        am.run_migrations(self.db)

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass

    def test_default_goals_seeded(self):
        goals = ag.get_goals(self.db)
        titles = [g["title"] for g in goals]
        self.assertIn("Daily Work Time", titles)
        self.assertIn("Deep Focus Time", titles)
        self.assertIn("Distraction Limit", titles)

    def test_inversion_goal_evaluation(self):
        """Inversion goal: success is staying below the target limit."""
        # Setup sessions with 30 mins distraction (target is 1 hour = 3600s)
        sessions_under_limit = [
            {"kind": "active", "duration_seconds": 1800, "category_type": "distraction"},
        ]
        results = ag.evaluate_goals(self.db, "2026-10-22", sessions_under_limit)
        dist_goal = next(r for r in results if r["metric"] == "distraction_time")
        self.assertTrue(dist_goal["is_inversion"])
        self.assertTrue(dist_goal["is_achieved"])
        self.assertEqual(dist_goal["actual_seconds"], 1800)

        # Setup sessions with 2 hours distraction (exceeding limit)
        sessions_over_limit = [
            {"kind": "active", "duration_seconds": 7200, "category_type": "distraction"},
        ]
        results_over = ag.evaluate_goals(self.db, "2026-10-22", sessions_over_limit)
        dist_goal_over = next(r for r in results_over if r["metric"] == "distraction_time")
        self.assertFalse(dist_goal_over["is_achieved"])

    def test_standard_goal_evaluation(self):
        """Standard goal: target is minimum desired (e.g. 5 hours work)."""
        sessions = [
            {"kind": "active", "duration_seconds": 18000, "category_type": "work"}, # exactly 5h
        ]
        results = ag.evaluate_goals(self.db, "2026-10-22", sessions)
        work_goal = next(r for r in results if r["metric"] == "work_time")
        self.assertFalse(work_goal["is_inversion"])
        self.assertTrue(work_goal["is_achieved"])
        self.assertEqual(work_goal["progress_pct"], 100.0)

    def test_time_block_analysis(self):
        """Planned time block vs actual tracked activity."""
        date_str = "2026-10-22"
        # Create block: 10:00 to 12:00 (2 hours = 7200s)
        block = ag.create_time_block(self.db, date_str, "10:00", "12:00", "Feature Development")

        # Session 1: 10:00 - 11:30 (5400s) of focus coding
        # Session 2: 11:30 - 11:45 (900s) of distraction
        # Session 3: 11:45 - 12:00 (900s) of focus coding
        sessions = [
            {
                "kind": "active",
                "start": f"{date_str}T10:00:00+00:00",
                "end": f"{date_str}T11:30:00+00:00",
                "duration_seconds": 5400,
                "category_type": "focus",
                "app": "Code.exe",
            },
            {
                "kind": "active",
                "start": f"{date_str}T11:30:00+00:00",
                "end": f"{date_str}T11:45:00+00:00",
                "duration_seconds": 900,
                "category_type": "distraction",
                "app": "chrome.exe",
            },
            {
                "kind": "active",
                "start": f"{date_str}T11:45:00+00:00",
                "end": f"{date_str}T12:00:00+00:00",
                "duration_seconds": 900,
                "category_type": "focus",
                "app": "Code.exe",
            },
        ]

        analysis = ag.analyze_time_blocks(self.db, date_str, sessions)
        self.assertEqual(len(analysis), 1)
        res = analysis[0]
        self.assertEqual(res["block_id"], block["id"])
        self.assertEqual(res["matching_seconds"], 6300) # 5400 + 900 = 6300s (87.5%)
        self.assertEqual(res["distraction_seconds"], 900)
        self.assertEqual(res["status"], "Completed")


if __name__ == "__main__":
    unittest.main()

