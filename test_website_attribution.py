"""
Unit tests for Website-Level Time Attribution, Hierarchical Activity Aggregation,
Browser Title Normalization, Category Rule Isolation, and AI Coach Inquiries.
"""

import unittest
from unittest.mock import patch
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.activity_intelligence import (
    clean_browser_window_title,
    derive_specific_activity,
    aggregate_hierarchical_usage,
    aggregate_browser_containers,
)
from api.categories import (
    clean_browser_title,
    match_category,
)
from api.ai_coach_engine import process_ai_coach_message


class TestBrowserTitleNormalization(unittest.TestCase):
    def test_clean_edge_zero_width_space_and_school_profile(self):
        # Edge inserts \u200b in "Microsoft\u200b Edge"
        title = "Courtesan Vs Prostitute and 4 more pages - School - Microsoft\u200b Edge"
        cleaned = clean_browser_window_title(title)
        self.assertEqual(cleaned, "Courtesan Vs Prostitute")

    def test_clean_chrome_profile_and_notifications(self):
        title = "(3) YouTube - 1v4 Clutch - Watch till end - Profile 1 - Google Chrome"
        cleaned = clean_browser_window_title(title)
        self.assertNotIn("Profile 1", cleaned)
        self.assertNotIn("Google Chrome", cleaned)
        self.assertTrue(cleaned.startswith("YouTube - 1v4 Clutch"))

    def test_clean_edge_pdf_document(self):
        title = "The Art of Seduction - Robert Greene(1).pdf - School - Microsoft\u200b Edge"
        cleaned = clean_browser_window_title(title)
        self.assertEqual(cleaned, "The Art of Seduction - Robert Greene(1).pdf")


class TestSpecificActivityAttribution(unittest.TestCase):
    def test_netflix_attribution(self):
        res = derive_specific_activity(
            app="chrome.exe",
            title="Stranger Things Season 4 - Netflix - Google Chrome",
            url="https://www.netflix.com/watch/80057281",
        )
        self.assertEqual(res["site_name"], "Netflix")
        self.assertEqual(res["app_display_name"], "Google Chrome")
        self.assertIn("Stranger Things Season 4", res["activity_name"])
        self.assertTrue(res["is_browser"])

    def test_youtube_entertainment(self):
        res = derive_specific_activity(
            app="chrome.exe",
            title="VALORANT LIVE | SATURDAY LATE NIGHT GAMING - YouTube - Google Chrome",
            url="https://www.youtube.com/watch?v=xyz",
        )
        self.assertEqual(res["site_name"], "YouTube")
        self.assertIn("VALORANT LIVE", res["activity_name"])
        self.assertTrue(res["is_browser"])

    def test_chatgpt_coding_task(self):
        res = derive_specific_activity(
            app="msedge.exe",
            title="FastAPI CORS debugging and token auth - ChatGPT - Microsoft\u200b Edge",
            url="https://chatgpt.com/c/123",
        )
        self.assertEqual(res["site_name"], "ChatGPT")
        self.assertIn("Coding & Debugging", res["specific_task"])

    def test_document_viewer_pdf(self):
        res = derive_specific_activity(
            app="msedge.exe",
            title="complete chess strategy - jeremy silman.pdf - School - Microsoft\u200b Edge",
            url="",
        )
        self.assertEqual(res["site_name"], "Document Viewer")
        self.assertIn("complete chess strategy", res["activity_name"])

    def test_chess_attribution(self):
        res = derive_specific_activity(
            app="chrome.exe",
            title="Chess.com - Play Chess Online for FREE - 2 Player Chess - Google Chrome",
            url="https://www.chess.com/play/online",
        )
        self.assertEqual(res["site_name"], "Chess.com")


class TestCategoryClassification(unittest.TestCase):
    def test_edge_school_profile_does_not_poison_entertainment(self):
        # Previously "- school -" in title forced category to Research & Learning
        cat = match_category(
            db=None,
            app="msedge.exe",
            title="Courtesan Vs Prostitute and 4 more pages - School - Microsoft\u200b Edge",
        )
        self.assertNotEqual(cat["name"], "Research & Learning")

    def test_youtube_educational_lecture(self):
        cat = match_category(
            db=None,
            app="chrome.exe",
            title="YouTube — Eulogy for the Software Engineer - Google Chrome",
        )
        self.assertEqual(cat["name"], "Research & Learning")
        self.assertEqual(cat["type"], "focus")

    def test_youtube_gaming_shorts(self):
        cat = match_category(
            db=None,
            app="chrome.exe",
            title="YouTube — 1v4 Clutch - Watch till end 🔥 #shorts #standoff2 #gaming - Google Chrome",
        )
        self.assertEqual(cat["name"], "Entertainment & Media")
        self.assertEqual(cat["type"], "distraction")

    def test_netflix_category(self):
        cat = match_category(
            db=None,
            app="chrome.exe",
            title="Netflix - Google Chrome",
        )
        self.assertEqual(cat["name"], "Entertainment & Media")
        self.assertEqual(cat["type"], "distraction")


class TestHierarchicalAccountingZeroDoubleCounting(unittest.TestCase):
    def setUp(self):
        # Create a synthetic dataset representing a day of tracking
        self.sessions = [
            # YouTube Entertainment 1
            {
                "session_key": "s1",
                "app": "chrome.exe",
                "title": "YouTube — 1v4 Clutch - Watch till end 🔥 #shorts - Google Chrome",
                "url": "https://www.youtube.com/shorts/123",
                "duration_seconds": 120.0,
                "category_name": "Entertainment & Media",
                "category_color": "#FF4D4D",
                "category_type": "distraction",
                "kind": "active",
            },
            # YouTube Entertainment 2
            {
                "session_key": "s2",
                "app": "chrome.exe",
                "title": "YouTube — INDIA'S GOT LATENT S2 EP8 - Google Chrome",
                "url": "https://www.youtube.com/watch?v=456",
                "duration_seconds": 300.0,
                "category_name": "Entertainment & Media",
                "category_color": "#FF4D4D",
                "category_type": "distraction",
                "kind": "active",
            },
            # YouTube Learning
            {
                "session_key": "s3",
                "app": "chrome.exe",
                "title": "YouTube — Eulogy for the Software Engineer - Google Chrome",
                "url": "https://www.youtube.com/watch?v=789",
                "duration_seconds": 600.0,
                "category_name": "Research & Learning",
                "category_color": "#16D5E2",
                "category_type": "focus",
                "kind": "active",
            },
            # ChatGPT Coding
            {
                "session_key": "s4",
                "app": "chrome.exe",
                "title": "ChatGPT — Python FastAPI async endpoint debugging - Google Chrome",
                "url": "https://chatgpt.com/c/abc",
                "duration_seconds": 450.0,
                "category_name": "Coding & Development",
                "category_color": "#8065FF",
                "category_type": "focus",
                "kind": "active",
            },
            # Netflix
            {
                "session_key": "s5",
                "app": "chrome.exe",
                "title": "Stranger Things - Netflix - Google Chrome",
                "url": "https://netflix.com/watch/1",
                "duration_seconds": 900.0,
                "category_name": "Entertainment & Media",
                "category_color": "#FF4D4D",
                "category_type": "distraction",
                "kind": "active",
            },
            # VS Code Desktop App
            {
                "session_key": "s6",
                "app": "code.exe",
                "title": "server.py - time tracker ai 2 - Visual Studio Code",
                "url": "",
                "duration_seconds": 1200.0,
                "category_name": "Coding & Development",
                "category_color": "#8065FF",
                "category_type": "focus",
                "kind": "active",
            },
        ]
        self.total_active_seconds = sum(s["duration_seconds"] for s in self.sessions)

    def test_perfect_mathematical_sum_reconciliation(self):
        breakdown = aggregate_hierarchical_usage(self.sessions, self.total_active_seconds)
        level1_sum = sum(r["duration_seconds"] for r in breakdown)
        self.assertAlmostEqual(level1_sum, self.total_active_seconds, places=4)

        # Verify parent row = sum of children
        for r in breakdown:
            if r["children"]:
                children_sum = sum(c["duration_seconds"] for c in r["children"])
                self.assertAlmostEqual(r["duration_seconds"], children_sum, places=4)

    def test_youtube_separated_by_category(self):
        breakdown = aggregate_hierarchical_usage(self.sessions, self.total_active_seconds)
        youtube_rows = [r for r in breakdown if r["site_name"] == "YouTube"]

        # Must have exactly 2 YouTube rows: Entertainment (420s) and Research (600s)
        self.assertEqual(len(youtube_rows), 2)

        yt_ent = next(r for r in youtube_rows if r["category"] == "Entertainment & Media")
        self.assertEqual(yt_ent["duration_seconds"], 420.0)
        self.assertEqual(len(yt_ent["children"]), 2)

        yt_res = next(r for r in youtube_rows if r["category"] == "Research & Learning")
        self.assertEqual(yt_res["duration_seconds"], 600.0)
        self.assertEqual(len(yt_res["children"]), 1)

    def test_browser_diagnostics_neutral_label(self):
        containers = aggregate_browser_containers(self.sessions, self.total_active_seconds)
        chrome_container = next((c for c in containers if "chrome" in c["id"].lower()), None)
        self.assertIsNotNone(chrome_container)
        self.assertEqual(chrome_container["category"], "Mixed Browser Activity")

        # Sum of containers must also equal total active seconds
        container_sum = sum(c["duration_seconds"] for c in containers)
        self.assertAlmostEqual(container_sum, self.total_active_seconds, places=4)


class TestAiCoachAttributionQueries(unittest.TestCase):
    @patch("api.ai_coach_engine._load_day_data")
    def test_youtube_learning_vs_entertainment_inquiry(self, mock_load):
        mock_load.return_value = {
            "date_str": "2026-10-25",
            "total_active_seconds": 1020.0,
            "productive_work_seconds": 600.0,
            "focus_seconds": 600.0,
            "distraction_seconds": 420.0,
            "study_seconds": 600.0,
            "study_label": "10m",
            "coding_seconds": 0.0,
            "coding_label": "0s",
            "sessions": [
                {
                    "app": "chrome.exe",
                    "title": "YouTube — Eulogy for the Software Engineer - Google Chrome",
                    "url": "https://youtube.com/watch?v=1",
                    "category_name": "Research & Learning",
                    "duration_seconds": 600.0,
                },
                {
                    "app": "chrome.exe",
                    "title": "YouTube — VALORANT LIVE SATURDAY - Google Chrome",
                    "url": "https://youtube.com/watch?v=2",
                    "category_name": "Entertainment & Media",
                    "duration_seconds": 420.0,
                },
            ],
            "categories": {},
            "top_apps": [],
            "goals": [],
            "blocks": [],
            "focus_sessions": [],
            "day_trends": [],
        }

        res = process_ai_coach_message(
            db=None,
            message="How much time did I spend on YouTube for entertainment vs learning?",
            selected_date="2026-10-25",
        )
        reply = res["response"]
        self.assertIn("YouTube", reply)
        self.assertIn("Entertainment & Gaming", reply)
        self.assertIn("Research & Learning", reply)
        self.assertIn("10m", reply)
        self.assertIn("7m", reply)

    @patch("api.ai_coach_engine._load_day_data")
    def test_netflix_inquiry(self, mock_load):
        mock_load.return_value = {
            "date_str": "2026-10-25",
            "total_active_seconds": 900.0,
            "productive_work_seconds": 0.0,
            "focus_seconds": 0.0,
            "distraction_seconds": 900.0,
            "study_seconds": 0.0,
            "study_label": "0s",
            "coding_seconds": 0.0,
            "coding_label": "0s",
            "sessions": [
                {
                    "app": "chrome.exe",
                    "title": "Stranger Things Season 4 - Netflix - Google Chrome",
                    "url": "https://netflix.com/watch/1",
                    "category_name": "Entertainment & Media",
                    "duration_seconds": 900.0,
                },
            ],
            "categories": {},
            "top_apps": [],
            "goals": [],
            "blocks": [],
            "focus_sessions": [],
            "day_trends": [],
        }

        res = process_ai_coach_message(
            db=None,
            message="How much time did I spend on Netflix?",
            selected_date="2026-10-25",
        )
        reply = res["response"]
        self.assertIn("Netflix", reply)
        self.assertIn("15m", reply)

    @patch("api.ai_coach_engine._load_day_data")
    def test_coding_vs_research_inquiry(self, mock_load):
        mock_load.return_value = {
            "date_str": "2026-10-25",
            "total_active_seconds": 3600.0,
            "productive_work_seconds": 3600.0,
            "focus_seconds": 3600.0,
            "distraction_seconds": 0.0,
            "coding_seconds": 2400.0,
            "coding_label": "40m",
            "study_seconds": 1200.0,
            "study_label": "20m",
            "sessions": [
                {
                    "app": "code.exe",
                    "title": "server.py - time tracker ai 2 - Visual Studio Code",
                    "url": "",
                    "category_name": "Coding & Development",
                    "duration_seconds": 2400.0,
                },
                {
                    "app": "chrome.exe",
                    "title": "Understanding DNS Iterative Resolution - Google Gemini",
                    "url": "https://gemini.google.com",
                    "category_name": "Research & Learning",
                    "duration_seconds": 1200.0,
                },
            ],
            "categories": {},
            "top_apps": [],
            "goals": [],
            "blocks": [],
            "focus_sessions": [],
            "day_trends": [],
        }

        res = process_ai_coach_message(
            db=None,
            message="Compare my coding vs research time today",
            selected_date="2026-10-25",
        )
        reply = res["response"]
        self.assertIn("Coding", reply)
        self.assertIn("Research", reply)


if __name__ == "__main__":
    unittest.main()

