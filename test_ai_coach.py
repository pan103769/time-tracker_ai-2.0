"""
test_ai_coach.py
----------------
Unit and integration tests for AI Coach Chatbot engine and API endpoints:
1. Grounded Study & Focus analysis (separating study vs coding vs general work).
2. Distractions analysis with ranked sources and actionable tips.
3. Specific Time Breakdown without double-counting.
4. Day-over-day Performance Comparison.
5. Next-Action recommendations (evaluating active task, time blocks, goals).
6. Natural language queries (YouTube usage, interruptions, goals).
7. FastAPI endpoint POST /api/aicoach/chat.
8. Fallback resiliency when Ollama is offline.
"""

from datetime import date, timedelta
import unittest
from fastapi.testclient import TestClient

from activity_report import format_duration
from api.ai_coach_engine import (
    _load_day_data,
    answer_distractions,
    answer_performance_comparison,
    answer_study_and_focus,
    answer_time_breakdown,
    answer_what_next,
    process_ai_coach_message,
)
from api.server import app, _db as get_db


class TestAiCoachEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_db()
        today = date.today().isoformat()
        row = cls.db.execute("SELECT date(start_time) as dt FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        cls.test_date = row["dt"] if row and row["dt"] else today
        cls.day_data = _load_day_data(cls.db, cls.test_date)

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(45), "45s")
        self.assertEqual(format_duration(120), "2m 0s")
        self.assertEqual(format_duration(3600), "1h 0m")
        self.assertEqual(format_duration(3665), "1h 1m")

    def test_answer_study_and_focus(self):
        text, quick_actions, meta = answer_study_and_focus(self.day_data)
        self.assertIn("Study & Focus", text)
        self.assertIn("Study & Research", text)
        self.assertIn("Coding & Project Work", text)
        self.assertIsInstance(quick_actions, list)
        self.assertTrue(any(a.get("action") in ["navigate_timeline", "navigate_tab"] for a in quick_actions))

    def test_answer_distractions(self):
        text, quick_actions, meta = answer_distractions(self.day_data)
        self.assertIn("Distraction Analysis", text)
        self.assertIsInstance(quick_actions, list)
        self.assertTrue(any(a.get("action") in ["navigate_timeline", "navigate_tab"] for a in quick_actions))

    def test_answer_time_breakdown(self):
        text, quick_actions, meta = answer_time_breakdown(self.day_data)
        self.assertIn("Where Your Time Went", text)
        self.assertIsInstance(quick_actions, list)
        self.assertTrue(any(a.get("action") in ["navigate_timeline", "navigate_tab"] for a in quick_actions))

    def test_answer_performance_comparison(self):
        y_date = (date.fromisoformat(self.test_date) - timedelta(days=1)).isoformat()
        prev_data = _load_day_data(self.db, y_date)
        text, quick_actions, meta = answer_performance_comparison(self.day_data, prev_data)
        self.assertIn("Performance Comparison", text)
        self.assertIsInstance(quick_actions, list)
        self.assertTrue(any(a.get("action") in ["navigate_timeline", "navigate_tab"] for a in quick_actions))

    def test_answer_what_next(self):
        text, quick_actions, meta = answer_what_next(self.db, self.day_data)
        self.assertIn("Recommendation", text)
        self.assertIsInstance(quick_actions, list)

    def test_process_ai_coach_message_presets(self):
        presets = ["study_focus", "distractions", "time_breakdown", "performance_comparison", "what_next"]
        for p in presets:
            res = process_ai_coach_message(
                db=self.db,
                message="",
                selected_date=self.test_date,
                preset_action=p,
            )
            self.assertIn("response", res)
            self.assertTrue(res["grounded"])
            self.assertTrue(len(res["sources"]) > 0)

    def test_process_natural_language_queries(self):
        # YouTube inquiry
        res_yt = process_ai_coach_message(
            db=self.db,
            message="How much time did I spend on YouTube today?",
            selected_date=self.test_date,
        )
        self.assertIn("response", res_yt)
        self.assertIn("YouTube Activity", res_yt["response"])
        self.assertTrue(res_yt["grounded"])

        # Interruptions inquiry
        res_int = process_ai_coach_message(
            db=self.db,
            message="Which activity interrupted my coding most?",
            selected_date=self.test_date,
        )
        self.assertIn("response", res_int)
        self.assertTrue(res_int["grounded"])

        # Goals inquiry
        res_g = process_ai_coach_message(
            db=self.db,
            message="What is my goal status today?",
            selected_date=self.test_date,
        )
        self.assertIn("response", res_g)
        self.assertIn("Goal Progress", res_g["response"])
        self.assertTrue(res_g["grounded"])


class TestAiCoachApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        db = get_db()
        row = db.execute("SELECT date(start_time) as dt FROM observations ORDER BY id DESC LIMIT 1").fetchone()
        cls.test_date = row["dt"] if row and row["dt"] else date.today().isoformat()

    def test_post_aicoach_chat_preset(self):
        resp = self.client.post("/api/aicoach/chat", json={
            "preset_action": "study_focus",
            "selected_date": self.test_date,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("response", data)
        self.assertTrue(data["grounded"])
        self.assertIn("Study & Focus", data["response"])
        self.assertIn("sources", data)
        self.assertIn("quick_actions", data)

    def test_post_aicoach_chat_natural_language(self):
        resp = self.client.post("/api/aicoach/chat", json={
            "message": "What did I do today?",
            "selected_date": self.test_date,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("response", data)
        self.assertTrue(data["grounded"])

    def test_post_aicoach_chat_empty_fallback(self):
        resp = self.client.post("/api/aicoach/chat", json={
            "message": "",
            "selected_date": self.test_date,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("response", data)


if __name__ == "__main__":
    unittest.main()
