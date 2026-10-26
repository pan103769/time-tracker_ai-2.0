"""
test_ai_timeline.py — Tests for ai_timeline.py

Covers: duration calculation, session grouping, session-key stability,
        user-edit persistence, URL selection, uncertainty marking,
        observation loading/clipping, and idempotency of DB helpers.

Run with:
    python test_ai_timeline.py
or:
    python -m pytest test_ai_timeline.py -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Make the project root importable.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import ai_timeline as tl  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DATE = datetime(2026, 10, 20, tzinfo=timezone.utc)


def _dt(hour: int, minute: int = 0, second: int = 0) -> datetime:
    """Timezone-aware UTC datetime fixed to 2026-10-20."""
    return _DATE.replace(hour=hour, minute=minute, second=second)


def _obs(id_: int, kind: str, app: str, start: datetime, end: datetime) -> dict:
    secs = (end - start).total_seconds()
    return {
        "id": id_,
        "kind": kind,
        "app": app,
        "title": f"{app} window",
        "start": start,
        "end": end,
        "duration_seconds": secs,
    }


def _mem_db() -> sqlite3.Connection:
    """In-memory SQLite DB with the minimal schema used by ai_timeline."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE observations (
            id               INTEGER PRIMARY KEY,
            kind             TEXT    NOT NULL,
            app              TEXT    NOT NULL,
            title            TEXT    NOT NULL,
            start_time       TEXT    NOT NULL,
            end_time         TEXT,
            duration_seconds REAL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE activity_screenshots (
            observation_id INTEGER PRIMARY KEY,
            path           TEXT    NOT NULL DEFAULT '',
            captured_at    TEXT    NOT NULL DEFAULT '',
            description    TEXT    NOT NULL DEFAULT ''
        )
        """
    )
    return db


def _insert_obs(
    db: sqlite3.Connection,
    id_: int,
    kind: str,
    app: str,
    start: datetime,
    end: datetime,
) -> None:
    secs = (end - start).total_seconds()
    db.execute(
        "INSERT INTO observations "
        "(id, kind, app, title, start_time, end_time, duration_seconds) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_, kind, app, f"{app} window",
         start.isoformat(), end.isoformat(), secs),
    )
    db.commit()


# ---------------------------------------------------------------------------
# 1. Session grouping
# ---------------------------------------------------------------------------


class TestGroupIntoSessions(unittest.TestCase):

    def test_empty_input(self):
        self.assertEqual(tl.group_into_sessions([]), [])

    def test_single_observation(self):
        sessions = tl.group_into_sessions([_obs(1, "active", "code.exe", _dt(10), _dt(11))])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["app"], "code.exe")

    def test_same_app_consecutive_merges(self):
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0),  _dt(10, 20)),
            _obs(2, "active", "code.exe", _dt(10, 20), _dt(10, 40)),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1, "Same consecutive app must merge")

    def test_different_apps_separate(self):
        obs = [
            _obs(1, "active", "code.exe",   _dt(10, 0),  _dt(10, 20)),
            _obs(2, "active", "chrome.exe", _dt(10, 20), _dt(10, 40)),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 2, "Different apps must not merge")

    def test_large_gap_same_app_breaks_session(self):
        gap = tl.SESSION_GAP_SECONDS + 60   # beyond threshold
        start2 = _dt(10, 10) + timedelta(seconds=gap)
        end2   = start2 + timedelta(minutes=10)
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0), _dt(10, 10)),
            _obs(2, "active", "code.exe", start2, end2),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 2, "Gap > SESSION_GAP_SECONDS must break session")

    def test_small_gap_same_app_still_merges(self):
        gap = tl.SESSION_GAP_SECONDS - 10   # within threshold
        start2 = _dt(10, 10) + timedelta(seconds=gap)
        end2   = start2 + timedelta(minutes=10)
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0), _dt(10, 10)),
            _obs(2, "active", "code.exe", start2, end2),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1, "Gap <= SESSION_GAP_SECONDS must still merge")

    def test_idle_never_merges_with_active(self):
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0),  _dt(10, 10)),
            _obs(2, "idle",   "Idle",     _dt(10, 10), _dt(10, 20)),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["kind"], "active")
        self.assertEqual(sessions[1]["kind"], "idle")

    def test_consecutive_idle_merges(self):
        obs = [
            _obs(1, "idle", "Idle", _dt(10, 0),  _dt(10, 10)),
            _obs(2, "idle", "Idle", _dt(10, 10), _dt(10, 20)),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["kind"], "idle")

    def test_session_keys_are_assigned_and_unique(self):
        obs = [
            _obs(1, "active", "app1.exe", _dt(10), _dt(11)),
            _obs(2, "active", "app2.exe", _dt(11), _dt(12)),
        ]
        sessions = tl.group_into_sessions(obs)
        keys = [s["session_key"] for s in sessions]
        self.assertEqual(len(set(keys)), 2, "Each session must have a unique key")
        for k in keys:
            self.assertEqual(len(k), 16)

    def test_observation_ids_tracked(self):
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0),  _dt(10, 10)),
            _obs(2, "active", "code.exe", _dt(10, 10), _dt(10, 20)),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(sessions[0]["observation_ids"], [1, 2])

    def test_titles_set_populated(self):
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0),  _dt(10, 10)),
            _obs(2, "active", "code.exe", _dt(10, 10), _dt(10, 20)),
        ]
        # Override title on second obs so we can check the set.
        obs[1]["title"] = "other_title"
        sessions = tl.group_into_sessions(obs)
        self.assertIn("code.exe window", sessions[0]["titles"])
        self.assertIn("other_title",     sessions[0]["titles"])

    def test_ongoing_observation_preserves_flag(self):
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0), _dt(10, 10)),
            {**_obs(2, "active", "code.exe", _dt(10, 10), _dt(10, 20)), "is_ongoing": True},
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["is_ongoing"])


# ---------------------------------------------------------------------------
# 2. Duration calculation
# ---------------------------------------------------------------------------


class TestDurationCalculation(unittest.TestCase):
    """Duration must be the SUM of observation durations, never wall-clock."""

    def test_no_double_counting_with_gap(self):
        # Two 10-minute observations with a 1-minute gap — well within SESSION_GAP_SECONDS.
        # Wall-clock = 21 min = 1260 s; correct sum = 600 + 600 = 1200 s.
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0),  _dt(10, 10)),  # 600 s
            _obs(2, "active", "code.exe", _dt(10, 11), _dt(10, 21)),  # 600 s
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1,
                         "1-minute gap must still merge (< SESSION_GAP_SECONDS)")
        self.assertAlmostEqual(sessions[0]["duration_seconds"], 1200.0,
                               msg="Gap must not be counted in duration")

    def test_multiple_merged_observations(self):
        # Five 2-minute observations = 5 * 120 = 600 s total.
        obs = [
            _obs(i, "active", "app.exe", _dt(10, i * 2), _dt(10, i * 2 + 2))
            for i in range(5)
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1)
        self.assertAlmostEqual(sessions[0]["duration_seconds"], 600.0)

    def test_separate_sessions_sum_correctly(self):
        obs = [
            _obs(1, "active", "app1.exe", _dt(10, 0),  _dt(10, 10)),  # 600 s
            _obs(2, "active", "app2.exe", _dt(10, 10), _dt(10, 20)),  # 600 s
        ]
        sessions = tl.group_into_sessions(obs)
        total = sum(s["duration_seconds"] for s in sessions)
        self.assertAlmostEqual(total, 1200.0)

    def test_idle_duration_counted_separately(self):
        obs = [
            _obs(1, "active", "code.exe", _dt(10, 0),  _dt(10, 10)),  # 600 s
            _obs(2, "idle",   "Idle",     _dt(10, 10), _dt(10, 20)),  # 600 s
        ]
        sessions = tl.group_into_sessions(obs)
        active_total = sum(s["duration_seconds"] for s in sessions if s["kind"] == "active")
        idle_total   = sum(s["duration_seconds"] for s in sessions if s["kind"] == "idle")
        self.assertAlmostEqual(active_total, 600.0)
        self.assertAlmostEqual(idle_total,   600.0)


# ---------------------------------------------------------------------------
# 3. Session key stability
# ---------------------------------------------------------------------------


class TestSessionKey(unittest.TestCase):

    def test_identical_inputs_produce_identical_key(self):
        self.assertEqual(
            tl.make_session_key("active", "code.exe", 42),
            tl.make_session_key("active", "code.exe", 42),
        )

    def test_different_obs_id_gives_different_key(self):
        self.assertNotEqual(
            tl.make_session_key("active", "code.exe", 1),
            tl.make_session_key("active", "code.exe", 2),
        )

    def test_different_app_gives_different_key(self):
        self.assertNotEqual(
            tl.make_session_key("active", "code.exe",   1),
            tl.make_session_key("active", "chrome.exe", 1),
        )

    def test_different_kind_gives_different_key(self):
        self.assertNotEqual(
            tl.make_session_key("active", "Idle", 1),
            tl.make_session_key("idle",   "Idle", 1),
        )

    def test_key_length(self):
        k = tl.make_session_key("active", "code.exe", 99)
        self.assertEqual(len(k), 16)

    def test_first_obs_id_used_as_key(self):
        """Grouped sessions must use the FIRST observation id in the group."""
        obs = [
            _obs(7, "active", "code.exe", _dt(10, 0),  _dt(10, 10)),
            _obs(8, "active", "code.exe", _dt(10, 10), _dt(10, 20)),
        ]
        sessions = tl.group_into_sessions(obs)
        expected_key = tl.make_session_key("active", "code.exe", 7)
        self.assertEqual(sessions[0]["session_key"], expected_key)


# ---------------------------------------------------------------------------
# 4. User-edit persistence
# ---------------------------------------------------------------------------


class TestTimelineEdits(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        tl.ensure_timeline_edits(self.db)

    def tearDown(self):
        self.db.close()

    def test_ensure_creates_table(self):
        tables = [r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )]
        self.assertIn("timeline_edits", tables)

    def test_ensure_idempotent(self):
        tl.ensure_timeline_edits(self.db)   # second call must not raise
        tl.ensure_timeline_edits(self.db)

    def test_save_and_retrieve(self):
        tl.save_user_edit(self.db, "abc123", "Writing unit tests in VS Code")
        self.assertEqual(
            tl.get_user_edit(self.db, "abc123"),
            "Writing unit tests in VS Code",
        )

    def test_missing_key_returns_none(self):
        self.assertIsNone(tl.get_user_edit(self.db, "does_not_exist"))

    def test_overwrite_keeps_latest(self):
        tl.save_user_edit(self.db, "abc123", "First description")
        tl.save_user_edit(self.db, "abc123", "Updated description")
        self.assertEqual(tl.get_user_edit(self.db, "abc123"), "Updated description")

    def test_save_strips_whitespace(self):
        tl.save_user_edit(self.db, "k", "  trimmed  ")
        self.assertEqual(tl.get_user_edit(self.db, "k"), "trimmed")

    def test_delete_returns_true_when_deleted(self):
        tl.save_user_edit(self.db, "k", "desc")
        self.assertTrue(tl.delete_user_edit(self.db, "k"))

    def test_delete_returns_false_when_nothing_to_delete(self):
        self.assertFalse(tl.delete_user_edit(self.db, "nonexistent"))

    def test_delete_removes_edit(self):
        tl.save_user_edit(self.db, "k", "desc")
        tl.delete_user_edit(self.db, "k")
        self.assertIsNone(tl.get_user_edit(self.db, "k"))

    def test_multiple_keys_independent(self):
        tl.save_user_edit(self.db, "k1", "Description for session 1")
        tl.save_user_edit(self.db, "k2", "Description for session 2")
        self.assertEqual(tl.get_user_edit(self.db, "k1"), "Description for session 1")
        self.assertEqual(tl.get_user_edit(self.db, "k2"), "Description for session 2")

    def test_persistence_across_connections(self):
        """Edits written to a real file must be readable after reconnecting."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            conn1 = sqlite3.connect(path)
            conn1.row_factory = sqlite3.Row
            tl.ensure_timeline_edits(conn1)
            tl.save_user_edit(conn1, "key1", "Persistent description")
            conn1.close()

            conn2 = sqlite3.connect(path)
            conn2.row_factory = sqlite3.Row
            self.assertEqual(tl.get_user_edit(conn2, "key1"), "Persistent description")
            conn2.close()
        finally:
            os.unlink(path)

    def test_raw_observations_table_untouched(self):
        """Saving/deleting user edits must not alter the observations table."""
        db = _mem_db()
        tl.ensure_timeline_edits(db)
        _insert_obs(db, 1, "active", "code.exe", _dt(10), _dt(11))

        tl.save_user_edit(db, "k", "some edit")
        tl.delete_user_edit(db, "k")

        count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        self.assertEqual(count, 1)
        db.close()


# ---------------------------------------------------------------------------
# 5. URL selection
# ---------------------------------------------------------------------------


class TestBestUrlForSession(unittest.TestCase):

    def _visit(self, start_h: int, start_m: int, end_h: int, end_m: int, url: str) -> dict:
        return {
            "start": _dt(start_h, start_m),
            "end":   _dt(end_h, end_m),
            "url":   url,
            "title": "",
        }

    def test_best_overlap_wins(self):
        session = {"start": _dt(10, 0), "end": _dt(10, 30)}
        visits = [
            self._visit(9, 50, 10, 5,  "https://short.example.com"),  # 5 min overlap
            self._visit(10, 0, 10, 30, "https://long.example.com"),   # 30 min overlap
        ]
        self.assertEqual(tl._best_url_for_session(session, visits),
                         "https://long.example.com")

    def test_no_overlap_returns_empty(self):
        session = {"start": _dt(10, 0), "end": _dt(10, 30)}
        visits  = [self._visit(11, 0, 11, 30, "https://unrelated.com")]
        self.assertEqual(tl._best_url_for_session(session, visits), "")

    def test_empty_visits(self):
        session = {"start": _dt(10), "end": _dt(11)}
        self.assertEqual(tl._best_url_for_session(session, []), "")

    def test_partial_overlap(self):
        # Visit starts before and ends during the session.
        session = {"start": _dt(10, 10), "end": _dt(10, 30)}
        visits  = [self._visit(10, 0, 10, 20, "https://partial.com")]
        result  = tl._best_url_for_session(session, visits)
        self.assertEqual(result, "https://partial.com")


# ---------------------------------------------------------------------------
# 6. Uncertainty marking
# ---------------------------------------------------------------------------


class TestUncertaintyMarking(unittest.TestCase):

    def _make_session(self, first_obs_id: int = 1) -> dict:
        return {
            "kind":             "active",
            "app":              "chrome.exe",
            "title":            "New Tab",
            "start":            _dt(10),
            "end":              _dt(10, 30),
            "duration_seconds": 1800.0,
            "titles":           {"New Tab"},
            "observation_ids":  [first_obs_id],
            "ai_description":   None,
            "user_description": None,
            "confidence":       None,
            "is_uncertain":     False,
            "source":           None,
            "url":              None,
            "session_key":      "test_key",
        }

    def _db_with_screenshots(self) -> sqlite3.Connection:
        db = _mem_db()
        tl.ensure_timeline_edits(db)
        return db

    def test_low_confidence_marks_uncertain(self):
        db = self._db_with_screenshots()
        session = self._make_session()

        with patch("ai_timeline.classify_activity") as mock_cls, \
             patch("ai_timeline.use_visual_fallback", side_effect=lambda db, oid, r: r):
            mock_cls.return_value = {
                "activity":   "Uncertain — activity could not be classified",
                "confidence": 0.1,
                "reason":     "Insufficient metadata.",
                "source":     "fallback",
            }
            tl.enrich_session(db, session, [], [], 0)

        self.assertTrue(session["is_uncertain"])
        db.close()

    def test_high_confidence_not_uncertain(self):
        db = self._db_with_screenshots()
        session = self._make_session()

        with patch("ai_timeline.classify_activity") as mock_cls, \
             patch("ai_timeline.use_visual_fallback", side_effect=lambda db, oid, r: r):
            mock_cls.return_value = {
                "activity":   "Researching Python database libraries in Chrome",
                "confidence": 0.88,
                "reason":     "URL indicates docs site.",
                "source":     "AI",
            }
            tl.enrich_session(db, session, [], [], 0)

        self.assertFalse(session["is_uncertain"])
        self.assertEqual(session["ai_description"],
                         "Researching Python database libraries in Chrome")
        db.close()

    def test_uncertain_text_marks_uncertain_regardless_of_confidence(self):
        db = self._db_with_screenshots()
        session = self._make_session()

        with patch("ai_timeline.classify_activity") as mock_cls, \
             patch("ai_timeline.use_visual_fallback", side_effect=lambda db, oid, r: r):
            # confidence is above threshold but text contains "uncertain"
            mock_cls.return_value = {
                "activity":   "Uncertain activity — app metadata too generic",
                "confidence": 0.6,
                "reason":     "Window title is empty.",
                "source":     "AI",
            }
            tl.enrich_session(db, session, [], [], 0)

        self.assertTrue(session["is_uncertain"])
        db.close()

    def test_idle_session_not_uncertain(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        session = {
            "kind": "idle", "app": "Idle", "title": "Idle",
            "start": _dt(10), "end": _dt(10, 30),
            "duration_seconds": 1800.0,
            "observation_ids": [99],
            "ai_description": None, "confidence": None,
            "is_uncertain": False, "source": None,
        }
        tl.enrich_session(db, session, [], [], 0)
        self.assertFalse(session["is_uncertain"])
        self.assertEqual(session["ai_description"], "Idle — no input detected.")
        self.assertAlmostEqual(session["confidence"], 1.0)
        db.close()

    def test_vision_description_used_when_low_confidence(self):
        """Stored vision description must be used when AI confidence is low."""
        db = _mem_db()
        tl.ensure_timeline_edits(db)
        # Store a vision description for obs_id=1.
        db.execute(
            "INSERT INTO activity_screenshots (observation_id, path, captured_at, description) "
            "VALUES (1, '', '2026-10-20', 'User is editing Python code in VS Code')"
        )
        db.commit()
        session = self._make_session(first_obs_id=1)

        with patch("ai_timeline.classify_activity") as mock_cls, \
             patch("ai_timeline.use_visual_fallback", side_effect=lambda db, oid, r: r):
            mock_cls.return_value = {
                "activity":   "Uncertain — could not classify",
                "confidence": 0.05,
                "reason":     "Generic window.",
                "source":     "fallback",
            }
            tl.enrich_session(db, session, [], [], 0)

        self.assertIn("Visual context", session["ai_description"])
        self.assertIn("VS Code", session["ai_description"])
        db.close()


# ---------------------------------------------------------------------------
# 7. Observation loading and clipping
# ---------------------------------------------------------------------------


class TestLoadObservations(unittest.TestCase):

    def setUp(self):
        self.db = _mem_db()
        self.day_start = _dt(0, 0)
        self.day_end   = _dt(0, 0) + timedelta(days=1)

    def tearDown(self):
        self.db.close()

    def test_clips_observation_starting_before_day(self):
        # Observation starts 1 hour before midnight and ends 2 hours into the day.
        start = self.day_start - timedelta(hours=1)
        end   = self.day_start + timedelta(hours=2)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["start"], self.day_start)

    def test_clips_observation_ending_after_day(self):
        start = self.day_end - timedelta(hours=2)
        end   = self.day_end + timedelta(hours=1)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["end"], self.day_end)

    def test_excludes_observation_entirely_outside_day(self):
        start = self.day_end + timedelta(hours=1)
        end   = self.day_end + timedelta(hours=2)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(len(obs), 0)

    def test_includes_observation_within_day(self):
        start = _dt(10)
        end   = _dt(11)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0]["duration_seconds"], 3600.0)

    def test_excludes_very_short_observations(self):
        # 1-second observation — below MIN_SESSION_SECONDS (2.0)
        start = _dt(10)
        end   = start + timedelta(seconds=1)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(len(obs), 0)

    def test_includes_short_ongoing_observation(self):
        # Ongoing observation (end_time is NULL) must not be dropped even if < 2s old
        now_dt = datetime.now().astimezone()
        start = now_dt - timedelta(seconds=0.5)
        self.db.execute(
            "INSERT INTO observations (id, kind, app, title, start_time, end_time) VALUES (?, ?, ?, ?, ?, NULL)",
            (99, "active", "code.exe", "code.exe window", start.isoformat()),
        )
        self.db.commit()
        today_start = datetime.combine(now_dt.date(), datetime.min.time()).astimezone()
        today_end = today_start + timedelta(days=1)
        obs = tl.load_observations(self.db, today_start, today_end)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["id"], 99)
        self.assertTrue(obs[0]["is_ongoing"])

    def test_includes_observations_at_threshold(self):
        start = _dt(10)
        end   = start + timedelta(seconds=tl.MIN_SESSION_SECONDS)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(len(obs), 1)

    def test_clipped_duration_correct(self):
        """Duration of a cross-midnight observation must be clipped to the day."""
        start = self.day_start - timedelta(hours=1)
        end   = self.day_start + timedelta(hours=3)
        _insert_obs(self.db, 1, "active", "code.exe", start, end)

        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertAlmostEqual(obs[0]["duration_seconds"], 3 * 3600.0)

    def test_orders_by_start_time(self):
        _insert_obs(self.db, 2, "active", "b.exe", _dt(12), _dt(13))
        _insert_obs(self.db, 1, "active", "a.exe", _dt(10), _dt(11))
        obs = tl.load_observations(self.db, self.day_start, self.day_end)
        self.assertEqual(obs[0]["app"], "a.exe")
        self.assertEqual(obs[1]["app"], "b.exe")


# ---------------------------------------------------------------------------
# 8. Argument parsing
# ---------------------------------------------------------------------------


class TestParseArgs(unittest.TestCase):

    def test_no_args_uses_today_no_edit(self):
        args = tl._parse_args([])
        self.assertIsNone(args.selected_date)
        self.assertIsNone(args.edit)
        self.assertFalse(args.refresh_ai)
        self.assertTrue(args.show_idle)

    def test_date_arg_parsed(self):
        args = tl._parse_args(["2026-10-15"])
        from datetime import date
        self.assertEqual(args.selected_date, date(2026, 10, 15))

    def test_edit_flag(self):
        args = tl._parse_args(["--edit", "5"])
        self.assertEqual(args.edit, 5)

    def test_edit_equals_syntax(self):
        args = tl._parse_args(["--edit=3"])
        self.assertEqual(args.edit, 3)

    def test_no_idle_flag(self):
        args = tl._parse_args(["--no-idle"])
        self.assertFalse(args.show_idle)

    def test_refresh_ai_flag(self):
        args = tl._parse_args(["--refresh-ai"])
        self.assertTrue(args.refresh_ai)

    def test_invalid_date_returns_none(self):
        args = tl._parse_args(["not-a-date"])
        self.assertIsNone(args)

    def test_unknown_flag_returns_none(self):
        args = tl._parse_args(["--unknown"])
        self.assertIsNone(args)

    def test_combined_flags(self):
        args = tl._parse_args(["2026-10-20", "--no-idle", "--refresh-ai"])
        from datetime import date
        self.assertEqual(args.selected_date, date(2026, 10, 20))
        self.assertFalse(args.show_idle)
        self.assertTrue(args.refresh_ai)


# ---------------------------------------------------------------------------
# 9. Syntax / import sanity
# ---------------------------------------------------------------------------


class TestSyntaxAndImport(unittest.TestCase):

    def test_module_imports_without_error(self):
        """The module must be importable with no side effects."""
        import importlib
        importlib.reload(tl)

    def test_all_public_functions_callable(self):
        for name in (
            "ensure_timeline_edits", "get_user_edit", "save_user_edit",
            "delete_user_edit", "make_session_key", "load_observations",
            "group_into_sessions", "enrich_session", "enrich_all_sessions",
            "print_timeline", "prompt_edit", "main",
        ):
            self.assertTrue(callable(getattr(tl, name)), f"{name} must be callable")


# ---------------------------------------------------------------------------
# 10. Advanced Evidence Descriptions & Domain Specialization
# ---------------------------------------------------------------------------


class TestEvidenceDescriptions(unittest.TestCase):
    """Verify specific, evidence-grounded descriptions for VS Code, Chrome, ChatGPT, docs, etc."""

    def test_vscode_differentiation(self):
        # AI timeline file
        s1 = {"kind": "active", "app": "Code.exe", "title": "ai_timeline.py - time tracker ai 2 - Visual Studio Code", "url": ""}
        desc1, conf1, src1, unc1 = tl.infer_evidence_description(s1)
        self.assertEqual(desc1, "Editing the AI timeline implementation in Python")
        self.assertFalse(unc1)
        self.assertGreaterEqual(conf1, 0.9)

        # browser_tracker file
        s2 = {"kind": "active", "app": "Code.exe", "title": "browser_tracker.py - time tracker ai 2 - Visual Studio Code", "url": ""}
        desc2, conf2, src2, unc2 = tl.infer_evidence_description(s2)
        self.assertEqual(desc2, "Editing the browser tracker implementation in Python")
        self.assertFalse(unc2)

        # main.py
        s3 = {"kind": "active", "app": "Code.exe", "title": "main.py - time tracker ai 2 - Visual Studio Code", "url": ""}
        desc3, conf3, src3, unc3 = tl.infer_evidence_description(s3)
        self.assertIn("Editing main.py in Python", desc3)
        self.assertFalse(unc3)

    def test_chatgpt_distinguished_from_vscode(self):
        # ChatGPT with specific conversation title
        s_chat = {
            "kind": "active",
            "app": "chrome.exe",
            "title": "time tracking project 🌟 - Google Chrome",
            "url": "https://chatgpt.com/c/6acdd605-f4f4-83ee-be86-38d12457d438",
        }
        desc_chat, conf_chat, src_chat, unc_chat = tl.infer_evidence_description(s_chat)
        self.assertIn("ChatGPT", desc_chat)
        self.assertIn("time-tracking project", desc_chat)
        self.assertNotIn("Code.exe", desc_chat)
        self.assertNotIn("Python", desc_chat)
        self.assertFalse(unc_chat)

        # ChatGPT with generic title
        s_generic_chat = {
            "kind": "active",
            "app": "chrome.exe",
            "title": "ChatGPT - Google Chrome",
            "url": "https://chatgpt.com/",
        }
        desc_gc, _, _, unc_gc = tl.infer_evidence_description(s_generic_chat)
        self.assertIn("Working in ChatGPT", desc_gc)
        self.assertFalse(unc_gc)

    def test_different_chrome_pages_produce_different_descriptions(self):
        # Hacktoberfest activities
        s_act = {"kind": "active", "app": "chrome.exe", "title": "Activities | Hacktoberfest 2026 - Google Chrome", "url": ""}
        desc_act, _, _, _ = tl.infer_evidence_description(s_act)
        self.assertEqual(desc_act, "Reading the Hacktoberfest 2026 activities page")

        # Hacktoberfest schedule
        s_sch = {"kind": "active", "app": "chrome.exe", "title": "October Schedule | Hacktoberfest 2026 - Google Chrome", "url": ""}
        desc_sch, _, _, _ = tl.infer_evidence_description(s_sch)
        self.assertIn("Hacktoberfest 2026", desc_sch)
        self.assertIn("schedule", desc_sch.lower())

        # YouTube
        s_yt = {"kind": "active", "app": "chrome.exe", "title": "bhojpuri song - YouTube - Google Chrome", "url": "https://youtube.com/watch"}
        desc_yt, _, _, _ = tl.infer_evidence_description(s_yt)
        self.assertIn("YouTube", desc_yt)
        self.assertIn("bhojpuri song", desc_yt)

        # Google Search
        s_search = {"kind": "active", "app": "chrome.exe", "title": "how to make vibe coded projects - Google Search - Google Chrome", "url": ""}
        desc_search, _, _, _ = tl.infer_evidence_description(s_search)
        self.assertIn("Searching Google for 'how to make vibe coded projects'", desc_search)

        # All four are distinct
        self.assertEqual(len({desc_act, desc_sch, desc_yt, desc_search}), 4)

    def test_documentation_classification(self):
        s_doc = {
            "kind": "active",
            "app": "chrome.exe",
            "title": "sqlite3 — DB-API 2.0 interface for SQLite databases — Python documentation",
            "url": "https://docs.python.org/3/library/sqlite3.html",
        }
        desc, conf, _, unc = tl.infer_evidence_description(s_doc)
        self.assertEqual(desc, "Reading Python documentation about SQLite")
        self.assertFalse(unc)

    def test_insufficient_evidence_marks_uncertain(self):
        s_empty = {"kind": "active", "app": "chrome.exe", "title": "New Tab - Google Chrome", "url": ""}
        desc, conf, _, unc = tl.infer_evidence_description(s_empty)
        self.assertEqual(desc, "Browsing in Chrome — specific activity unclear")
        self.assertTrue(unc)
        self.assertLess(conf, tl.UNCERTAIN_CONFIDENCE)

        s_unknown = {"kind": "active", "app": "Unknown", "title": "Unknown", "url": ""}
        desc_u, conf_u, _, unc_u = tl.infer_evidence_description(s_unknown)
        self.assertIn("unclear", desc_u)
        self.assertTrue(unc_u)

    def test_stored_vision_description_used_only_when_available(self):
        # When available on generic app/title
        s_gen = {"kind": "active", "app": "explorer.exe", "title": "Untitled window", "url": ""}
        desc_v, conf_v, src_v, unc_v = tl.infer_evidence_description(
            s_gen, stored_vision="A user is viewing a web browser window displaying a ChatGPT conversation about making code edits"
        )
        self.assertIn("Visual context", desc_v)
        self.assertIn("ChatGPT", desc_v)
        self.assertEqual(src_v, "vision")
        self.assertFalse(unc_v)

        # When NOT available
        desc_nov, _, src_nov, unc_nov = tl.infer_evidence_description(s_gen, stored_vision=None)
        self.assertNotIn("Visual context", desc_nov)
        self.assertNotEqual(src_nov, "vision")
        self.assertTrue(unc_nov)

    def test_sensitive_app_safeguard(self):
        s_pw = {"kind": "active", "app": "Bitwarden.exe", "title": "My Vault - Bitwarden", "url": ""}
        desc, conf, src, unc = tl.infer_evidence_description(s_pw)
        self.assertIn("sensitive application", desc)
        self.assertEqual(src, "privacy")
        self.assertFalse(unc)


# ---------------------------------------------------------------------------
# 11. Advanced Browser Visit Association & Fingerprinting
# ---------------------------------------------------------------------------


class TestBrowserVisitAssociationAndGrouping(unittest.TestCase):

    def test_visit_matched_by_title_and_time(self):
        session = {
            "start": _dt(13, 30, 20),
            "end": _dt(13, 30, 40),
            "title": "time tracking project 🌟 - Google Chrome",
            "titles": {"time tracking project 🌟 - Google Chrome"},
        }
        visits = [
            {
                "start": _dt(13, 30, 0),
                "end": _dt(13, 30, 30),
                "title": "time tracking project 🌟 - Google Chrome",
                "url": "https://chatgpt.com/c/6acdd605-f4f4-83ee-be86-38d12457d438",
            },
            {
                "start": _dt(10, 0, 0),
                "end": _dt(10, 5, 0),
                "title": "Google Gemini - Google Chrome",
                "url": "https://gemini.google.com/app",
            },
        ]
        matched = tl.find_matching_browser_visit(session, visits)
        self.assertIsNotNone(matched)
        self.assertIn("chatgpt.com", matched["url"])

    def test_different_browser_activities_do_not_merge(self):
        obs = [
            {
                "id": 1,
                "kind": "active",
                "app": "chrome.exe",
                "title": "Activities | Hacktoberfest 2026 - Google Chrome",
                "start": _dt(13, 29, 20),
                "end": _dt(13, 29, 30),
                "duration_seconds": 10.0,
            },
            {
                "id": 2,
                "kind": "active",
                "app": "chrome.exe",
                "title": "time tracking project 🌟 - Google Chrome",
                "start": _dt(13, 29, 30),
                "end": _dt(13, 29, 45),
                "duration_seconds": 15.0,
            },
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 2, "Hacktoberfest and ChatGPT in Chrome must NOT merge")

    def test_same_browser_site_pages_do_merge(self):
        obs = [
            {
                "id": 1,
                "kind": "active",
                "app": "chrome.exe",
                "title": "Activities | Hacktoberfest 2026 - Google Chrome",
                "start": _dt(13, 29, 20),
                "end": _dt(13, 29, 30),
                "duration_seconds": 10.0,
            },
            {
                "id": 2,
                "kind": "active",
                "app": "chrome.exe",
                "title": "October Schedule | Hacktoberfest 2026 - Google Chrome",
                "start": _dt(13, 29, 30),
                "end": _dt(13, 29, 50),
                "duration_seconds": 20.0,
            },
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 1, "Different pages on Hacktoberfest should merge into one session")
        self.assertEqual(sessions[0]["duration_seconds"], 30.0)

    def test_vscode_and_chrome_do_not_merge(self):
        obs = [
            _obs(1, "active", "Code.exe", _dt(10, 0), _dt(10, 10)),
            _obs(2, "active", "chrome.exe", _dt(10, 10), _dt(10, 20)),
        ]
        sessions = tl.group_into_sessions(obs)
        self.assertEqual(len(sessions), 2)


# ---------------------------------------------------------------------------
# 12. User Edits Integrity Across Refreshes
# ---------------------------------------------------------------------------


class TestUserEditsIntegrity(unittest.TestCase):

    def setUp(self):
        self.db = _mem_db()
        tl.ensure_timeline_edits(self.db)

    def tearDown(self):
        self.db.close()

    def test_user_edit_preserved_across_refresh(self):
        obs = [_obs(1, "active", "chrome.exe", _dt(10, 0), _dt(10, 30))]
        sessions = tl.group_into_sessions(obs)
        session = sessions[0]

        # User provides manual correction
        tl.save_user_edit(self.db, session["session_key"], "Custom user correction")

        # Enrich session (even with refresh=True)
        tl.enrich_session(self.db, session, [], sessions, 0, refresh=True)
        session["user_description"] = tl.get_user_edit(self.db, session["session_key"])

        # Display description must prioritize user_description
        desc = session.get("user_description") or session.get("ai_description")
        self.assertEqual(desc, "Custom user correction")

    def test_raw_observations_strictly_unchanged(self):
        _insert_obs(self.db, 100, "active", "code.exe", _dt(10), _dt(11))
        initial_row = dict(self.db.execute("SELECT * FROM observations WHERE id = 100").fetchone())

        # Save an edit, delete an edit, create a table
        tl.save_user_edit(self.db, "sample_key", "New desc")
        tl.delete_user_edit(self.db, "sample_key")

        after_row = dict(self.db.execute("SELECT * FROM observations WHERE id = 100").fetchone())
        self.assertEqual(initial_row, after_row, "Raw observations must never be modified by timeline edits")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
