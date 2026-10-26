"""
test_activity_classification.py — Comprehensive test suite for activity classification,
metadata extraction, context disambiguation, precedence hierarchy, persistence, and metric reconciliation.
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ai_timeline as tl
import api.categories as ac
import api.goals as ag
import api.insights as ai
import api.migrations as am


class TestActivityClassificationSuite(unittest.TestCase):
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

    # ---------------------------------------------------------------------------
    # 1. Classification & Domain/Context Disambiguation Tests
    # ---------------------------------------------------------------------------

    def test_chrome_youtube_technical_vs_entertainment(self):
        """Technical/programming YouTube video matches Research & Learning, vlog matches Entertainment."""
        # Tech keynote / tutorial
        tech_title = "Rails World 2026 Opening Keynote - DHH - YouTube - Google Chrome"
        match_tech = ac.match_category(self.db, "chrome.exe", tech_title)
        self.assertEqual(match_tech["name"], "Research & Learning")
        self.assertEqual(match_tech["type"], "focus")
        self.assertEqual(match_tech["source"], "content")
        self.assertEqual(match_tech["domain"], "youtube.com")

        # Python tutorial
        py_title = "Python Full Course for Beginners [Tutorial] - YouTube - Google Chrome"
        match_py = ac.match_category(self.db, "chrome.exe", py_title)
        self.assertEqual(match_py["name"], "Research & Learning")
        self.assertEqual(match_py["type"], "focus")

        # Entertainment vlog / comedy / gaming stream
        vlog_title = "Shifted To Mumbai In Our New House - YouTube - Google Chrome"
        match_vlog = ac.match_category(self.db, "chrome.exe", vlog_title)
        self.assertEqual(match_vlog["name"], "Entertainment & Media")
        self.assertEqual(match_vlog["type"], "distraction")

        # Gaming live stream
        gaming_title = "VALORANT LIVE | SATURDAY LATE NIGHT GAMINGS - YouTube - Google Chrome"
        match_gaming = ac.match_category(self.db, "chrome.exe", gaming_title)
        self.assertEqual(match_gaming["name"], "Entertainment & Media")
        self.assertEqual(match_gaming["type"], "distraction")

    def test_chrome_chatgpt_coding_vs_research(self):
        """ChatGPT with coding project context matches Coding & Development; general study matches Research."""
        # Coding project conversation in ChatGPT
        coding_title = "time tracking project 🌟 - Google Chrome"
        match_code = ac.match_category(self.db, "chrome.exe", coding_title)
        self.assertEqual(match_code["name"], "Coding & Development")
        self.assertEqual(match_code["type"], "focus")

        # Academic / CS study topic in ChatGPT or Gemini
        study_title = "Understanding DNS Iterative Resolution - Google Gemini - Google Chrome"
        match_study = ac.match_category(self.db, "chrome.exe", study_title)
        self.assertEqual(match_study["name"], "Research & Learning")
        self.assertEqual(match_study["type"], "focus")
        self.assertEqual(match_study["domain"], "gemini.google.com")

        # Generic ChatGPT window
        gen_title = "ChatGPT - Google Chrome"
        match_gen = ac.match_category(self.db, "chrome.exe", gen_title)
        self.assertEqual(match_gen["name"], "Research & Learning")
        self.assertEqual(match_gen["domain"], "chatgpt.com")

    def test_technical_documentation_and_github(self):
        """Technical documentation, MDN, Stack Overflow, and GitHub must match appropriately."""
        # GitHub
        gh_title = "GitHub - pan103769/time_tracker_gg - Google Chrome"
        match_gh = ac.match_category(self.db, "chrome.exe", gh_title)
        self.assertEqual(match_gh["name"], "Coding & Development")
        self.assertEqual(match_gh["domain"], "github.com")

        # Python documentation
        docs_title = "3.11.0 Documentation - docs.python.org - Google Chrome"
        match_docs = ac.match_category(self.db, "chrome.exe", docs_title)
        self.assertEqual(match_docs["name"], "Research & Learning")
        self.assertEqual(match_docs["domain"], "docs.python.org")

        # Stack Overflow
        so_title = "python - How to parse JSON safely - Stack Overflow - Google Chrome"
        match_so = ac.match_category(self.db, "chrome.exe", so_title)
        self.assertEqual(match_so["name"], "Coding & Development")
        self.assertEqual(match_so["domain"], "stackoverflow.com")

        # DEV Community
        dev_title = "A Structured Workflow for Vibe Coding Full-Stack Apps - DEV Community - Google Chrome"
        match_dev = ac.match_category(self.db, "chrome.exe", dev_title)
        self.assertEqual(match_dev["name"], "Coding & Development")

    def test_document_and_pdf_study(self):
        """PDF books and documents open in browsers match Research & Learning."""
        pdf_title = "The Art of Seduction - Robert Greene _Worldfreebooks.com_ (1).pdf - School - Microsoft​ Edge"
        match_pdf = ac.match_category(self.db, "msedge.exe", pdf_title)
        self.assertEqual(match_pdf["name"], "Research & Learning")
        self.assertEqual(match_pdf["source"], "document")

    def test_communication_and_messaging_sites(self):
        """WhatsApp, Discord, and Slack match Communication & Meetings."""
        # WhatsApp Web in browser
        wa_title = "(1) WhatsApp - Google Chrome"
        match_wa = ac.match_category(self.db, "chrome.exe", wa_title)
        self.assertEqual(match_wa["name"], "Communication & Meetings")
        self.assertEqual(match_wa["domain"], "web.whatsapp.com")

        # Discord desktop executable
        match_discord = ac.match_category(self.db, "Discord.exe", "Discord - #general")
        self.assertEqual(match_discord["name"], "Communication & Meetings")

        # Slack executable
        match_slack = ac.match_category(self.db, "slack.exe", "Engineering - Slack")
        self.assertEqual(match_slack["name"], "Communication & Meetings")

    def test_ide_and_terminal_sessions(self):
        """VS Code and terminal sessions match Coding & Development or Utilities."""
        match_code = ac.match_category(self.db, "Code.exe", "server.py - time tracker ai")
        self.assertEqual(match_code["name"], "Coding & Development")

        match_terminal = ac.match_category(self.db, "WindowsTerminal.exe", "Administrator: Windows PowerShell")
        self.assertEqual(match_terminal["name"], "Utilities & System")

    def test_gaming_and_entertainment(self):
        """Chess.com, Netflix, Spotify, and gaming exes match Entertainment or Gaming."""
        # Chess.com in browser
        chess_title = "Play Chess Online for FREE - 2 Player Chess - Chess.com - Google Chrome"
        match_chess = ac.match_category(self.db, "chrome.exe", chess_title)
        self.assertIn("Entertainment", match_chess["name"])
        self.assertEqual(match_chess["domain"], "chess.com")

        # Netflix
        netflix_title = "Netflix - Google Chrome"
        match_netflix = ac.match_category(self.db, "chrome.exe", netflix_title)
        self.assertEqual(match_netflix["name"], "Entertainment & Media")
        self.assertEqual(match_netflix["domain"], "netflix.com")

        # Spotify app
        match_spotify = ac.match_category(self.db, "Spotify.exe", "Spotify Free")
        self.assertEqual(match_spotify["name"], "Entertainment & Media")

    def test_generic_and_honest_uncertain_fallback(self):
        """Generic or uninformative titles must produce an honest uncertain fallback, not blind guesses."""
        new_tab_title = "New Tab - Google Chrome"
        match_nt = ac.match_category(self.db, "chrome.exe", new_tab_title)
        self.assertTrue(match_nt["is_uncertain"])
        self.assertEqual(match_nt["source"], "uncertain")
        self.assertLess(match_nt["confidence"], 0.45)
        self.assertTrue("Needs Review" in match_nt["name"] or "Uncategorized" in match_nt["name"])

        empty_title = ""
        match_empty = ac.match_category(self.db, "chrome.exe", empty_title)
        self.assertTrue(match_empty["is_uncertain"])
        self.assertEqual(match_empty["source"], "uncertain")

        unknown_app = ac.match_category(self.db, "random_program.exe", "Untitled Window")
        self.assertTrue(unknown_app["is_uncertain"])

    # ---------------------------------------------------------------------------
    # 2. Strict Precedence Hierarchy Tests
    # ---------------------------------------------------------------------------

    def test_precedence_hierarchy(self):
        """
        Verify strict precedence order:
        1. Manual session override > 2. User rules > 3. Explicit task > 4. Domain > 5. Title > 6. App
        """
        session_key = "test-prec-session-1"
        app = "chrome.exe"
        title = "Rails World 2026 Opening Keynote - DHH - YouTube - Google Chrome"
        url = "https://youtube.com/watch?v=123"

        # Baseline: Technical YouTube keynote matches Research & Learning
        base = ac.match_category(self.db, app, title, url=url, session_key=session_key)
        self.assertEqual(base["name"], "Research & Learning")

        # Precedence Level 3: Explicit user task "DSA Practice" takes precedence
        with_task = ac.match_category(self.db, app, title, url=url, session_key=session_key, task="DSA Practice")
        self.assertEqual(with_task["source"], "task")

        # Precedence Level 2: User custom rule for this domain takes precedence over generic parsing
        planning_cat = next(c for c in ac.get_all_categories(self.db) if "Planning" in c["name"])
        custom_rule = ac.create_rule(self.db, planning_cat["id"], "domain", "youtube.com", priority=50)
        with_rule = ac.match_category(self.db, app, title, url=url, session_key=session_key)
        self.assertEqual(with_rule["name"], planning_cat["name"])
        self.assertEqual(with_rule["source"], "rule")

        # Precedence Level 1: Explicit manual session override beats EVERYTHING (rules, tasks, domains)
        comm_cat = next(c for c in ac.get_all_categories(self.db) if "Communication" in c["name"])
        ac.set_session_category_override(self.db, session_key, comm_cat["id"])
        with_override = ac.match_category(
            self.db, app, title, url=url, session_key=session_key, task="DSA Practice"
        )
        self.assertEqual(with_override["name"], comm_cat["name"])
        self.assertEqual(with_override["source"], "manual")

        # Cleanup rule & override
        ac.delete_rule(self.db, custom_rule["id"])
        ac.remove_session_category_override(self.db, session_key)

    def test_constituent_observation_override_lookup(self):
        """Manual category override keyed by app_targetId or obs_targetId must be matched."""
        target_obs_id = 9988
        app = "chrome.exe"
        title = "Random Page - Google Chrome"
        coding_cat = next(c for c in ac.get_all_categories(self.db) if "Coding" in c["name"])

        # Override stored under f"{app}_{target_obs_id}"
        ac.set_session_category_override(self.db, f"{app}_{target_obs_id}", coding_cat["id"])

        match = ac.match_category(
            self.db, app, title, session_key="different-sha-hash", obs_ids=[target_obs_id]
        )
        self.assertEqual(match["name"], coding_cat["name"])
        self.assertEqual(match["source"], "manual")

    # ---------------------------------------------------------------------------
    # 3. Persistence & Rule Edits Tests
    # ---------------------------------------------------------------------------

    def test_rule_edits_affect_only_matching_activities(self):
        """Creating a custom rule for a specific domain should only affect that domain."""
        social_cat = next(c for c in ac.get_all_categories(self.db) if "Social" in c["name"])
        rule = ac.create_rule(self.db, social_cat["id"], "domain", "mycustomforum.org", priority=45)

        # Activity on mycustomforum.org matches Social
        match_forum = ac.match_category(self.db, "chrome.exe", "Home - mycustomforum.org - Google Chrome")
        self.assertEqual(match_forum["name"], social_cat["name"])

        # Other activities remain unaffected
        match_gh = ac.match_category(self.db, "chrome.exe", "GitHub - pan103769/repo - Google Chrome")
        self.assertEqual(match_gh["name"], "Coding & Development")

        # Delete rule
        ac.delete_rule(self.db, rule["id"])
        match_forum_after = ac.match_category(self.db, "chrome.exe", "Home - mycustomforum.org - Google Chrome")
        self.assertNotEqual(match_forum_after["name"], social_cat["name"])

    # ---------------------------------------------------------------------------
    # 4. Metrics Reconciliation & Timeline Integrity Tests
    # ---------------------------------------------------------------------------

    def test_category_totals_reconcile_with_session_durations(self):
        """The sum of category breakdown seconds must equal total active seconds without double-counting."""
        now = datetime.now().astimezone()
        day_start = datetime.combine(now.date(), datetime.min.time()).astimezone()
        day_end = day_start + timedelta(days=1)
        t1 = day_start + timedelta(hours=1)
        t2 = t1 + timedelta(minutes=45)
        t3 = t2 + timedelta(minutes=30)
        t4 = t3 + timedelta(minutes=15)

        # Insert 3 observations: Code, YouTube tutorial, and Chess
        self.db.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES 
                ('active', 'Code.exe', 'server.py', ?, ?, 2700.0),
                ('active', 'chrome.exe', 'Python Full Course Tutorial - YouTube - Google Chrome', ?, ?, 1800.0),
                ('active', 'chrome.exe', 'Play Chess Online - Chess.com - Google Chrome', ?, ?, 900.0)
            """,
            (t1.isoformat(), t2.isoformat(), t2.isoformat(), t3.isoformat(), t3.isoformat(), t4.isoformat()),
        )
        self.db.commit()

        obs = tl.load_observations(self.db, day_start, day_end)
        sessions = tl.group_into_sessions(obs)

        # Enrich with categories
        for s in sessions:
            s["category"] = ac.match_category(self.db, s["app"], s["title"], session_key=s["session_key"])
            s["category_name"] = s["category"]["name"]
            s["category_type"] = s["category"]["type"]
            s["category_id"] = s["category"]["id"]

        prod = ai.compute_daily_productivity(self.db, now.date().isoformat(), sessions)

        total_active = sum(s["duration_seconds"] for s in sessions if s["kind"] != "idle")
        breakdown_total = sum(c["seconds"] for c in prod["category_breakdown"])

        # Exactly 5400 seconds (45m + 30m + 15m)
        self.assertEqual(total_active, 5400.0)
        self.assertEqual(breakdown_total, 5400.0)
        self.assertEqual(round(prod["total_tracked_seconds"], 1), 5400.0)
        # Productive work excludes Chess (900s distraction): 2700s + 1800s = 4500s
        self.assertEqual(round(prod["productive_work_seconds"], 1), 4500.0)
        self.assertEqual(round(prod["total_work_seconds"], 1), 4500.0)

        # Focus time: Code (2700s) + YouTube Tutorial (1800s) = 4500s
        self.assertEqual(prod["focus_seconds"], 4500.0)

        # Distraction time: Chess (900s) = 900s
        self.assertEqual(prod["distraction_seconds"], 900.0)

    def test_goals_and_time_blocks_use_corrected_categories(self):
        """Goal evaluation correctly registers focus and distraction times from corrected categories."""
        # Create a focus goal for 1 hour (3600s) and distraction max limit of 30 mins (1800s)
        ag.create_goal(self.db, "Daily Focus", "focus_time", 3600, is_inversion=False)
        ag.create_goal(self.db, "Limit Distraction", "distraction_time", 1800, is_inversion=True)

        sessions = [
            {
                "kind": "active",
                "duration_seconds": 3600.0,
                "category_type": "focus",
                "category": {"type": "focus", "name": "Coding & Development"},
            },
            {
                "kind": "active",
                "duration_seconds": 600.0,
                "category_type": "distraction",
                "category": {"type": "distraction", "name": "Entertainment & Media"},
            },
        ]

        goals_res = ag.evaluate_goals(self.db, "2026-10-25", sessions)
        self.assertGreaterEqual(len(goals_res), 2)

        focus_goal = next(g for g in goals_res if g["title"] == "Daily Focus")
        self.assertTrue(focus_goal["is_achieved"])
        self.assertEqual(focus_goal["actual_seconds"], 3600.0)

        dist_goal = next(g for g in goals_res if g["title"] == "Limit Distraction")
        self.assertTrue(dist_goal["is_achieved"])  # Under 1800s limit
        self.assertEqual(dist_goal["actual_seconds"], 600.0)


if __name__ == "__main__":
    unittest.main()
