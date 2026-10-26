"""
test_categories.py — Unit tests for category management and rule matching precedence.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import api.categories as ac
import api.migrations as am


class TestCategoriesAndRules(unittest.TestCase):
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

    def test_default_categories_seeded(self):
        cats = ac.get_all_categories(self.db)
        names = [c["name"] for c in cats]
        self.assertIn("Coding & Development", names)
        self.assertIn("Entertainment & Media", names)
        self.assertGreaterEqual(len(cats), 8)

    def test_create_and_delete_category(self):
        cat = ac.create_category(self.db, "3D Modeling", "#f43f5e", "focus")
        self.assertEqual(cat["name"], "3D Modeling")
        self.assertEqual(cat["type"], "focus")

        # Verify in list
        cats = ac.get_all_categories(self.db)
        self.assertTrue(any(c["id"] == cat["id"] for c in cats))

        # Delete
        success = ac.delete_category(self.db, cat["id"])
        self.assertTrue(success)
        cats_after = ac.get_all_categories(self.db)
        self.assertFalse(any(c["id"] == cat["id"] for c in cats_after))

    def test_rule_precedence_url_over_app(self):
        """A specific URL/domain rule on a browser must override generic browser app rule."""
        # By default chrome.exe has no direct rule, but youtube.com domain matches Entertainment
        match = ac.match_category(self.db, "chrome.exe", "Watching Tutorial", "https://youtube.com/watch?v=123")
        self.assertEqual(match["name"], "Entertainment & Media")
        self.assertEqual(match["type"], "distraction")

        # If we visit github.com on chrome.exe, it matches Coding & Development
        match_gh = ac.match_category(self.db, "chrome.exe", "Repository", "https://github.com/my/repo")
        self.assertEqual(match_gh["name"], "Coding & Development")
        self.assertEqual(match_gh["type"], "focus")

    def test_rule_app_match(self):
        """Code.exe must match Coding & Development by app rule."""
        match = ac.match_category(self.db, "Code.exe", "server.py - project")
        self.assertEqual(match["name"], "Coding & Development")
        self.assertEqual(match["type"], "focus")

    def test_manual_override_precedence(self):
        """Manual session override must take precedence over any rule."""
        session_key = "test-session-key-1"
        # First check normal match for Code.exe -> Coding
        match_normal = ac.match_category(self.db, "Code.exe", "server.py", session_key=session_key)
        self.assertEqual(match_normal["name"], "Coding & Development")

        # Now find 'Planning & Management' category
        cats = ac.get_all_categories(self.db)
        planning_cat = next(c for c in cats if "Planning" in c["name"])

        # Set manual override
        ac.set_session_category_override(self.db, session_key, planning_cat["id"])

        # Verify manual override wins
        match_overridden = ac.match_category(self.db, "Code.exe", "server.py", session_key=session_key)
        self.assertEqual(match_overridden["name"], planning_cat["name"])
        self.assertEqual(match_overridden["source"], "manual")

        # Revert override
        ac.remove_session_category_override(self.db, session_key)
        match_reverted = ac.match_category(self.db, "Code.exe", "server.py", session_key=session_key)
        self.assertEqual(match_reverted["name"], "Coding & Development")


if __name__ == "__main__":
    unittest.main()

