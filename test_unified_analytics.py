"""
test_unified_analytics.py
-------------------------
Tests for Unified Analytics, Browser Intelligence & Task-Level Activity Tracking:
1. Specific Activity Attribution for browsers, web apps, and desktop tools.
2. Honest uncertain fallback for missing metadata.
3. Precedence of user edits / overrides over inferred labels.
4. Hierarchical Browser Usage aggregation with ZERO double-counting.
5. Date range queries, period comparisons, and input validation.
"""

from datetime import date, datetime, timedelta
import unittest
from fastapi.testclient import TestClient

from api.activity_intelligence import (
    aggregate_browser_containers,
    aggregate_hierarchical_usage,
    clean_browser_window_title,
    derive_specific_activity,
    extract_domain_from_url,
)
from api.server import app, get_analytics_range


class TestActivityIntelligence(unittest.TestCase):
    def test_youtube_entertainment_vs_tutorial(self):
        # Entertainment video
        ent = derive_specific_activity(
            app="chrome.exe",
            title="AAI BO - GhAatak, Encore ABJ | Prod. Jzey | ‪AAI BO | DL91 - YouTube - Google Chrome",
            url="https://youtube.com/watch",
            category_name="Entertainment & Media",
        )
        self.assertIn("YouTube", ent["activity_name"])
        self.assertIn("AAI BO", ent["activity_name"])
        self.assertEqual(ent["specific_task"], "Entertainment / Media")
        self.assertFalse(ent["is_uncertain"])

        # Programming tutorial
        tut = derive_specific_activity(
            app="chrome.exe",
            title="Python Tutorial for Beginners - Full Course - YouTube - Google Chrome",
            url="https://youtube.com/watch",
            category_name="Research & Learning",
        )
        self.assertIn("YouTube", tut["activity_name"])
        self.assertIn("Python Tutorial for Beginners", tut["activity_name"])
        self.assertEqual(tut["specific_task"], "Educational Video")
        self.assertFalse(tut["is_uncertain"])

    def test_chatgpt_topic_extraction(self):
        chat = derive_specific_activity(
            app="chrome.exe",
            title="time tracking project 🌟 - Google Chrome",
            url="https://chatgpt.com/c/6acdd605",
            category_name="Coding & Development",
        )
        self.assertEqual(chat["activity_name"], "ChatGPT — time tracking project")
        self.assertIn("ChatGPT", chat["specific_task"])
        self.assertEqual(chat["site_name"], "ChatGPT")
        self.assertFalse(chat["is_uncertain"])

    def test_pdf_document_reading(self):
        pdf = derive_specific_activity(
            app="msedge.exe",
            title="The Art of Seduction - Robert Greene _Worldfreebooks.com_ (1).pdf - School - Microsoft Edge",
            url="",
            category_name="Research & Learning",
        )
        self.assertIn("Reading —", pdf["activity_name"])
        self.assertIn("The Art of Seduction", pdf["activity_name"])
        self.assertEqual(pdf["document_name"], "The Art of Seduction - Robert Greene _Worldfreebooks.com_ (1).pdf")
        self.assertFalse(pdf["is_uncertain"])

    def test_google_search_research(self):
        srch = derive_specific_activity(
            app="chrome.exe",
            title="fastapi background tasks - Google Search - Google Chrome",
            url="https://google.com/search?q=fastapi",
            category_name="Research & Learning",
        )
        self.assertEqual(srch["activity_name"], "Google Search — fastapi background tasks")
        self.assertEqual(srch["specific_task"], "Search: fastapi background tasks")
        self.assertFalse(srch["is_uncertain"])

    def test_desktop_vscode_extraction(self):
        code = derive_specific_activity(
            app="Code.exe",
            title="server.py - time tracker ai 2 - Visual Studio Code",
            task="API Debugging",
            category_name="Coding & Development",
        )
        self.assertEqual(code["activity_name"], "VS Code — time tracker ai 2 (server.py)")
        self.assertEqual(code["site_name"], "VS Code")
        self.assertFalse(code["is_browser"])

    def test_desktop_spotify_extraction(self):
        spot = derive_specific_activity(
            app="Spotify.exe",
            title="Avenxir - MONTAGEM GUERREIRO - Spotify.exe",
            category_name="Entertainment & Media",
        )
        self.assertEqual(spot["activity_name"], "Spotify — Avenxir - MONTAGEM GUERREIRO")
        self.assertFalse(spot["is_browser"])

    def test_honest_uncertain_fallback(self):
        unc = derive_specific_activity(
            app="chrome.exe",
            title="New Tab - Google Chrome",
            url="",
            category_name="Other / Needs Review",
        )
        self.assertEqual(unc["activity_name"], "Browser Activity — Needs Review")
        self.assertTrue(unc["is_uncertain"])

    def test_user_description_precedence(self):
        # Even if window title is generic or automated, explicit user description must rule
        ovr = derive_specific_activity(
            app="chrome.exe",
            title="AAI BO - YouTube - Google Chrome",
            url="https://youtube.com",
            user_description="Auditing Background Soundtrack for Video Project",
            category_name="Coding & Development",
        )
        self.assertEqual(ovr["activity_name"], "Auditing Background Soundtrack for Video Project")
        self.assertFalse(ovr["is_uncertain"])


class TestHierarchicalAccounting(unittest.TestCase):
    def test_zero_double_counting_in_aggregation(self):
        sample_sessions = [
            {
                "app": "chrome.exe",
                "title": "ChatGPT — Project Debugging - Google Chrome",
                "url": "https://chatgpt.com",
                "duration_seconds": 3600.0,
                "category_name": "Coding & Development",
                "category_color": "#35D68A",
                "category_type": "focus",
                "kind": "active",
            },
            {
                "app": "chrome.exe",
                "title": "YouTube — Tutorial - Google Chrome",
                "url": "https://youtube.com",
                "duration_seconds": 1800.0,
                "category_name": "Research & Learning",
                "category_color": "#16D5E2",
                "category_type": "work",
                "kind": "active",
            },
            {
                "app": "Code.exe",
                "title": "server.py - time tracker ai 2 - Visual Studio Code",
                "duration_seconds": 7200.0,
                "category_name": "Coding & Development",
                "category_color": "#35D68A",
                "category_type": "focus",
                "kind": "active",
            },
        ]

        total_tracked = sum(s["duration_seconds"] for s in sample_sessions)
        rows = aggregate_hierarchical_usage(sample_sessions, total_tracked)

        # Verification 1: Sum of top rows must EXACTLY equal total tracked time
        sum_top_rows = sum(r["duration_seconds"] for r in rows)
        self.assertAlmostEqual(sum_top_rows, total_tracked, places=2)

        # Verification 2: Parent row duration must equal sum of its children
        for r in rows:
            if r.get("children"):
                child_sum = sum(c["duration_seconds"] for c in r["children"])
                self.assertAlmostEqual(r["duration_seconds"], child_sum, places=2)

        # Verification 3: Browser containers grouping preserves process container
        containers = aggregate_browser_containers(sample_sessions, total_tracked)
        browser_row = next(r for r in containers if r["is_browser"])
        self.assertEqual(browser_row["app"], "Google Chrome")
        child_sum = sum(c["duration_seconds"] for c in browser_row["children"])
        self.assertAlmostEqual(browser_row["duration_seconds"], child_sum, places=2)
        self.assertAlmostEqual(child_sum, 5400.0, places=2)


class TestAnalyticsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_range_validation(self):
        # Start date after end date should return 422
        resp = self.client.get("/api/analytics/range?start_date=2026-10-25&end_date=2026-10-20")
        self.assertEqual(resp.status_code, 422)

    def test_analytics_range_response_structure(self):
        # Test valid range endpoint
        resp = self.client.get("/api/analytics/range?start_date=2026-10-15&end_date=2026-10-17")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Check KPIs exist and are formatted
        self.assertIn("kpi", data)
        self.assertIn("productive_work_label", data["kpi"])
        self.assertIn("deep_focus_label", data["kpi"])
        self.assertIn("distraction_label", data["kpi"])
        self.assertIn("total_tracked_label", data["kpi"])
        self.assertIn("comparison", data["kpi"])

        # Check Productivity Score & AI synthesis
        self.assertIn("productivity_score", data)
        self.assertIn("score", data["productivity_score"])
        self.assertIn("ai_synthesis", data)
        self.assertIn("key_takeaway", data["ai_synthesis"])

        # Check Hierarchical App breakdown & Daily Trends
        self.assertIn("app_breakdown", data)
        self.assertIn("daily_trends", data)
        self.assertIn("category_breakdown", data)
        self.assertIn("detailed_sessions", data)


if __name__ == "__main__":
    unittest.main()

