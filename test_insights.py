"""
test_insights.py — Unit tests for productivity analysis, interruption detection, and deterministic insights.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import api.insights as ai
import api.migrations as am


class TestInsightsAndInterruptions(unittest.TestCase):
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

    def test_interruption_detection(self):
        """User in 20 min focus session gets interrupted by WhatsApp for 2 minutes."""
        sessions = [
            # 20 min focus (1200s)
            {"kind": "active", "duration_seconds": 1200, "category_type": "focus", "app": "Code.exe", "title": "Editor"},
            # 2 min interruption (120s)
            {"kind": "active", "duration_seconds": 120, "category_type": "work", "app": "WhatsApp.exe", "title": "Chat"},
            # Back to 15 min focus (900s)
            {"kind": "active", "duration_seconds": 900, "category_type": "focus", "app": "Code.exe", "title": "Editor"},
            # 1 min distraction (60s)
            {"kind": "active", "duration_seconds": 60, "category_type": "distraction", "app": "Spotify.exe", "title": "Music"},
            # Back to focus
            {"kind": "active", "duration_seconds": 600, "category_type": "focus", "app": "Code.exe", "title": "Editor"},
        ]

        interruptions, top_int, longest_streak = ai.detect_interruptions_and_streaks(sessions)
        self.assertEqual(interruptions, 2)
        apps = [item["app"] for item in top_int]
        self.assertIn("WhatsApp.exe", apps)
        self.assertIn("Spotify.exe", apps)
        self.assertIsNotNone(longest_streak)
        self.assertEqual(longest_streak["duration_seconds"], 1200)

    def test_deterministic_insights_generation(self):
        """When AI is offline or not requested, deterministic summary must be rich and grounded."""
        sessions = [
            {"kind": "active", "duration_seconds": 7200, "category_type": "focus", "app": "Code.exe", "title": "Dev"},
            {"kind": "active", "duration_seconds": 1800, "category_type": "distraction", "app": "YouTube.exe", "title": "Video"},
        ]
        prod = ai.compute_daily_productivity(self.db, "2026-10-22", sessions)
        self.assertGreater(prod["productivity_score"], 0)
        self.assertEqual(prod["focus_label"], "2h 0m")
        self.assertEqual(prod["distraction_label"], "30m 0s")

        summary = ai.generate_daily_ai_summary(self.db, "2026-10-22", prod, refresh=False)
        self.assertEqual(summary["source"], "deterministic")
        self.assertIn("2h 30m", summary["key_takeaway"])
        self.assertGreaterEqual(len(summary["recommendations"]), 1)


if __name__ == "__main__":
    unittest.main()

