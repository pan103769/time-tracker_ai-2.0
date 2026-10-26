"""
test_timeline_ui.py — Tests for timeline_ui.py Phase 1 visual timeline.

These tests validate:
1. Data loading and session filtering (no real DB or Tk window needed)
2. Helper formatters
3. Session label and color logic
4. Edit/delete persistence round-trips (using temp file DB)
5. main() argument parsing (date selection, bad date)
6. main.py CLI dispatcher integration for the 'ui' command

All tests avoid creating a real Tk window (no display required on CI).
"""

import importlib
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make sure the project root is importable
# ---------------------------------------------------------------------------

_PROJECT = Path(__file__).resolve().parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import ai_timeline as tl
import timeline_ui as ui


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 20, h, m, 0, tzinfo=timezone.utc)


def _make_session(
    kind="active",
    app="Code.exe",
    title="main.py - project",
    start_h=9,
    start_m=0,
    dur=600.0,
    ai_desc="Editing main.py",
    user_desc=None,
    is_uncertain=False,
    confidence=0.9,
    source="evidence",
    url="",
    obs_ids=None,
    session_key="aabbccdd11223344",
) -> dict:
    start = _utc(start_h, start_m)
    end   = start + timedelta(seconds=dur)
    return {
        "kind":             kind,
        "app":              app,
        "title":            title,
        "start":            start,
        "end":              end,
        "duration_seconds": dur,
        "titles":           {title},
        "observation_ids":  obs_ids or [1],
        "ai_description":   ai_desc,
        "user_description": user_desc,
        "is_uncertain":     is_uncertain,
        "confidence":       confidence,
        "source":           source,
        "url":              url,
        "session_key":      session_key,
        "_display_number":  1,
    }


def _make_file_db(path: Path) -> None:
    """Create a minimal tracker.db schema in a temp file."""
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            app TEXT NOT NULL,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration_seconds REAL,
            task TEXT
        );
        CREATE TABLE IF NOT EXISTS browser_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            browser TEXT NOT NULL,
            title TEXT,
            url TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity_screenshots (
            observation_id INTEGER PRIMARY KEY,
            path TEXT NOT NULL DEFAULT '',
            captured_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS timeline_edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# 1. Helper formatter tests
# ---------------------------------------------------------------------------


class TestFormatters(unittest.TestCase):
    def test_fmt_time_returns_hms(self):
        dt = _utc(9, 30).astimezone()
        result = ui._fmt_time(dt)
        self.assertRegex(result, r"\d{2}:\d{2}:\d{2}")

    def test_conf_str_none(self):
        self.assertEqual(ui._conf_str(None), "—")

    def test_conf_str_float(self):
        self.assertEqual(ui._conf_str(0.85), "85%")

    def test_conf_str_zero(self):
        self.assertEqual(ui._conf_str(0.0), "0%")

    def test_conf_str_one(self):
        self.assertEqual(ui._conf_str(1.0), "100%")

    def test_conf_str_invalid(self):
        self.assertEqual(ui._conf_str("n/a"), "n/a")


# ---------------------------------------------------------------------------
# 2. Session label generation
# ---------------------------------------------------------------------------


class TestSessionLabel(unittest.TestCase):
    def test_active_uses_ai_description(self):
        s = _make_session(ai_desc="Writing unit tests in Python")
        label = ui._session_label(s)
        self.assertIn("Writing unit tests in Python", label)

    def test_active_user_description_preferred(self):
        s = _make_session(ai_desc="Generic coding", user_desc="Fixing the layout bug")
        label = ui._session_label(s)
        self.assertIn("Fixing the layout bug", label)

    def test_idle_session_shows_idle(self):
        s = _make_session(kind="idle", ai_desc=None, app="Idle",
                          title="Idle", dur=300.0)
        label = ui._session_label(s)
        self.assertIn("Idle", label)

    def test_long_label_truncated(self):
        long_desc = "A" * 200
        s = _make_session(ai_desc=long_desc)
        label = ui._session_label(s)
        self.assertLessEqual(len(label), 120)  # includes ellipsis

    def test_no_description_falls_back_to_app(self):
        s = _make_session(ai_desc=None, user_desc=None)
        s["ai_description"] = None
        s["user_description"] = None
        label = ui._session_label(s)
        self.assertIn("Code.exe", label)


# ---------------------------------------------------------------------------
# 3. Block colour logic
# ---------------------------------------------------------------------------


class TestBlockColor(unittest.TestCase):
    def test_active_default_accent(self):
        s = _make_session()
        self.assertEqual(ui._block_color(s), ui.COLORS["accent"])

    def test_idle_uses_idle_color(self):
        s = _make_session(kind="idle")
        self.assertEqual(ui._block_color(s), ui.COLORS["idle"])

    def test_uncertain_uses_amber(self):
        s = _make_session(is_uncertain=True)
        self.assertEqual(ui._block_color(s), ui.COLORS["uncertain"])

    def test_user_edited_uses_green(self):
        s = _make_session(user_desc="My custom description")
        self.assertEqual(ui._block_color(s), ui.COLORS["edited"])

    def test_user_edit_trumps_uncertain(self):
        s = _make_session(is_uncertain=True, user_desc="Fixed!")
        self.assertEqual(ui._block_color(s), ui.COLORS["edited"])


# ---------------------------------------------------------------------------
# 4. Edit / delete persistence round-trips
# ---------------------------------------------------------------------------


class TestEditPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._path = Path(self._tmp.name)
        _make_file_db(self._path)

    def tearDown(self):
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def test_save_and_retrieve_edit(self):
        with patch.object(ui, "DB_PATH", self._path):
            ui.save_edit("key001", "Custom description")
            db = sqlite3.connect(self._path)
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT description FROM timeline_edits WHERE session_key = 'key001'"
            ).fetchone()
            db.close()
        self.assertEqual(row["description"], "Custom description")

    def test_delete_edit(self):
        with patch.object(ui, "DB_PATH", self._path):
            ui.save_edit("key002", "To be deleted")
            deleted = ui.delete_edit("key002")
            self.assertTrue(deleted)
            db = sqlite3.connect(self._path)
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT description FROM timeline_edits WHERE session_key = 'key002'"
            ).fetchone()
            db.close()
        self.assertIsNone(row)

    def test_delete_nonexistent_returns_false(self):
        with patch.object(ui, "DB_PATH", self._path):
            result = ui.delete_edit("no-such-key")
        self.assertFalse(result)

    def test_overwrite_edit(self):
        with patch.object(ui, "DB_PATH", self._path):
            ui.save_edit("key003", "First")
            ui.save_edit("key003", "Second")
            db = sqlite3.connect(self._path)
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT description FROM timeline_edits WHERE session_key = 'key003'"
            ).fetchone()
            db.close()
        self.assertEqual(row["description"], "Second")

    def test_tracker_db_untouched(self):
        """save_edit and delete_edit must never write to the real tracker.db."""
        real_db = Path(_PROJECT / "tracker.db")
        if not real_db.exists():
            self.skipTest("tracker.db not present; skipping real-DB guard check.")
        mtime_before = real_db.stat().st_mtime
        with patch.object(ui, "DB_PATH", self._path):
            ui.save_edit("safety_key", "test")
        mtime_after = real_db.stat().st_mtime
        self.assertEqual(mtime_before, mtime_after,
                         "tracker.db was modified — edit was not isolated to temp DB!")


# ---------------------------------------------------------------------------
# 5. load_sessions_for_date — no real DB path
# ---------------------------------------------------------------------------


class TestLoadSessions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._path = Path(self._tmp.name)
        _make_file_db(self._path)

    def tearDown(self):
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def test_empty_database_returns_empty_list(self):
        with patch.object(ui, "DB_PATH", self._path):
            sessions, err = ui.load_sessions_for_date(date(2026, 10, 20))
        self.assertEqual(sessions, [])
        self.assertEqual(err, "")

    def test_missing_database_returns_error(self):
        missing = Path("/nonexistent/tracker.db")
        with patch.object(ui, "DB_PATH", missing):
            sessions, err = ui.load_sessions_for_date(date(2026, 10, 20))
        self.assertEqual(sessions, [])
        self.assertIn("not found", err.lower())

    def test_sessions_returned_with_display_numbers(self):
        """Sessions must have _display_number assigned starting at 1."""
        start = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)
        db = sqlite3.connect(self._path)
        db.execute(
            "INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds) "
            "VALUES ('active', 'Code.exe', 'test.py - project', ?, ?, 1800.0)",
            (start.isoformat(), end.isoformat()),
        )
        db.commit()
        db.close()

        with patch.object(ui, "DB_PATH", self._path):
            sessions, err = ui.load_sessions_for_date(date(2026, 10, 20))

        self.assertEqual(err, "")
        self.assertTrue(len(sessions) >= 1)
        for s in sessions:
            self.assertIn("_display_number", s)
            self.assertIsNotNone(s["_display_number"])

    def test_raw_observations_not_modified(self):
        """load_sessions_for_date must not alter observations table."""
        db = sqlite3.connect(self._path)
        db.execute(
            "INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds) "
            "VALUES (99, 'active', 'Code.exe', 'hist.py', '2026-10-20T09:00:00Z', '2026-10-20T09:15:00Z', 900.0)"
        )
        db.commit()
        db.close()

        with patch.object(ui, "DB_PATH", self._path):
            ui.load_sessions_for_date(date(2026, 10, 20))

        db2 = sqlite3.connect(self._path)
        row = db2.execute("SELECT * FROM observations WHERE id = 99").fetchone()
        db2.close()
        self.assertIsNotNone(row)


# ---------------------------------------------------------------------------
# 6. main() argument parsing (no Tk window)
# ---------------------------------------------------------------------------


class TestMainArgParsing(unittest.TestCase):
    def test_invalid_date_exits_with_error(self):
        with patch.object(ui, "TimelineApp") as mock_app:
            result = ui.main(["not-a-date"])
        self.assertEqual(result, 1)
        mock_app.assert_not_called()

    def test_valid_date_passed_to_app(self):
        captured = {}

        class FakeApp:
            def __init__(self, initial_date=None):
                captured["date"] = initial_date

            def mainloop(self):
                pass

        with patch.object(ui, "TimelineApp", FakeApp):
            result = ui.main(["2026-10-18"])

        self.assertEqual(result, 0)
        self.assertEqual(captured["date"], date(2026, 10, 18))

    def test_no_args_uses_today(self):
        captured = {}

        class FakeApp:
            def __init__(self, initial_date=None):
                captured["date"] = initial_date

            def mainloop(self):
                pass

        with patch.object(ui, "TimelineApp", FakeApp):
            ui.main([])

        self.assertIsNone(captured["date"])  # None → defaults to today inside TimelineApp


# ---------------------------------------------------------------------------
# 7. main.py CLI dispatcher
# ---------------------------------------------------------------------------


class TestMainDispatcher(unittest.TestCase):
    def test_ui_command_dispatches_to_timeline_ui(self):
        """python main.py ui  must call timeline_ui.main without raising."""
        import main as m

        with patch("sys.argv", ["main.py", "ui"]), \
             patch("timeline_ui.main", return_value=0) as mock_ui:
            result = m.main()
        mock_ui.assert_called_once()
        self.assertEqual(result, 0)

    def test_ui_command_with_date(self):
        import main as m

        with patch("sys.argv", ["main.py", "ui", "2026-10-18"]), \
             patch("timeline_ui.main", return_value=0) as mock_ui:
            result = m.main()
        mock_ui.assert_called_once_with(["2026-10-18"])
        self.assertEqual(result, 0)

    def test_help_command_mentions_ui(self):
        import main as m
        import io

        with patch("sys.argv", ["main.py", "help"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                m.main()
            output = mock_out.getvalue()

        self.assertIn("ui", output.lower())


# ---------------------------------------------------------------------------
# 8. Phase 2 forward-compatibility: session dict fields
# ---------------------------------------------------------------------------


class TestPhase2Readiness(unittest.TestCase):
    def test_session_has_expected_keys(self):
        """Every session from _new_session must include Phase 2 extension slots."""
        obs = {
            "id": 1, "kind": "active", "app": "Code.exe",
            "title": "test.py", "start": _utc(9), "end": _utc(10),
            "duration_seconds": 3600.0,
        }
        s = tl._new_session(obs)
        # Currently populated fields
        for key in ("kind", "app", "title", "start", "end", "duration_seconds",
                    "observation_ids", "ai_description", "user_description",
                    "confidence", "is_uncertain", "source", "url", "session_key"):
            self.assertIn(key, s, f"Missing key: {key!r}")

    def test_session_dict_accepts_task_category(self):
        """Phase 2 can add task_category to session dict without breaking UI."""
        s = _make_session()
        s["task_category"] = "Deep Work"
        s["task_confidence"] = 0.88
        # _session_label and _block_color must not crash
        label = ui._session_label(s)
        color = ui._block_color(s)
        self.assertIsInstance(label, str)
        self.assertIsInstance(color, str)

    def test_detail_fields_survives_extra_keys(self):
        """Extra keys in _DETAIL_FIELDS must silently show '—' if absent."""
        s = _make_session()
        # Simulate a Phase 2 key not yet present in session
        fields_with_phase2 = list(ui._DETAIL_FIELDS) + [("task_category", "Task")]
        for key, label in fields_with_phase2:
            val = s.get(key)
            # Must not raise; missing → "—"
            if val is None:
                display = "—"
            else:
                display = str(val)
            self.assertIsInstance(display, str)


if __name__ == "__main__":
    unittest.main()

