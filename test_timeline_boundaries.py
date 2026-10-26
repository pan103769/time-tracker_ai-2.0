"""
test_timeline_boundaries.py — Unit tests for Timeline Date Boundaries and Intelligent Activity Clustering.
"""

import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone

import ai_timeline as tl
from api.clustering import ChildSegment, cluster_timeline_sessions, infer_cluster_metadata


def make_tz_db():
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
    return db


class TestTimelineDateBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = make_tz_db()
        # Simulated local timezone UTC+05:30
        self.tz = timezone(timedelta(hours=5, minutes=30))

    def tearDown(self):
        self.db.close()

    def test_cross_midnight_clipping(self):
        """
        Observation starting at 23:45 on Day 1 and ending at 00:30 on Day 2
        must be clipped exactly at local midnight for each day without overlap or loss.
        """
        # Day 1: 2026-10-24
        day1_date = date(2026, 10, 24)
        day1_start = datetime(2026, 10, 24, 0, 0, 0, tzinfo=self.tz)
        day1_end = day1_start + timedelta(days=1)

        # Day 2: 2026-10-25
        day2_date = date(2026, 10, 25)
        day2_start = datetime(2026, 10, 25, 0, 0, 0, tzinfo=self.tz)
        day2_end = day2_start + timedelta(days=1)

        # Observation starts at 23:45 local on Oct 24, ends at 00:30 local on Oct 25
        # In UTC: 23:45 IST is 18:15 UTC. 00:30 IST is 19:00 UTC.
        obs_start = datetime(2026, 10, 24, 23, 45, 0, tzinfo=self.tz)
        obs_end = datetime(2026, 10, 25, 0, 30, 0, tzinfo=self.tz)

        # Stored in UTC ISO string in database
        self.db.execute(
            """
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (1, 'active', 'Code.exe', 'server.py', ?, ?, 2700.0)
            """,
            (obs_start.astimezone(timezone.utc).isoformat(), obs_end.astimezone(timezone.utc).isoformat()),
        )
        self.db.commit()

        # Query Day 1 (Oct 24)
        obs_day1 = tl.load_observations(self.db, day1_start, day1_end)
        self.assertEqual(len(obs_day1), 1)
        self.assertEqual(obs_day1[0]["start"], obs_start)
        self.assertEqual(obs_day1[0]["end"], day1_end)
        self.assertAlmostEqual(obs_day1[0]["duration_seconds"], 900.0)  # 15 minutes

        # Query Day 2 (Oct 25)
        obs_day2 = tl.load_observations(self.db, day2_start, day2_end)
        self.assertEqual(len(obs_day2), 1)
        self.assertEqual(obs_day2[0]["start"], day2_start)
        self.assertEqual(obs_day2[0]["end"], obs_end)
        self.assertAlmostEqual(obs_day2[0]["duration_seconds"], 1800.0)  # 30 minutes

        # Total duration preserved exactly
        self.assertAlmostEqual(obs_day1[0]["duration_seconds"] + obs_day2[0]["duration_seconds"], 2700.0)

    def test_utc_stored_timestamps_align_to_local_day(self):
        """
        Verify that observations recorded late at night in UTC (which correspond to early morning next day locally)
        are returned strictly on the correct local date.
        """
        # Event at 2026-10-24 20:00:00 UTC
        # In UTC+05:30, this is 2026-10-25 01:30:00 AM!
        t_utc = datetime(2026, 10, 24, 20, 0, 0, tzinfo=timezone.utc)
        t_end_utc = t_utc + timedelta(minutes=20)

        self.db.execute(
            """
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (2, 'active', 'chrome.exe', 'Dashboard', ?, ?, 1200.0)
            """,
            (t_utc.isoformat(), t_end_utc.isoformat()),
        )
        self.db.commit()

        day_oct24_start = datetime(2026, 10, 24, 0, 0, 0, tzinfo=self.tz)
        day_oct24_end = day_oct24_start + timedelta(days=1)

        day_oct25_start = datetime(2026, 10, 25, 0, 0, 0, tzinfo=self.tz)
        day_oct25_end = day_oct25_start + timedelta(days=1)

        # Must NOT appear on Oct 24 local
        obs_oct24 = tl.load_observations(self.db, day_oct24_start, day_oct24_end)
        self.assertEqual(len(obs_oct24), 0)

        # MUST appear on Oct 25 local
        obs_oct25 = tl.load_observations(self.db, day_oct25_start, day_oct25_end)
        self.assertEqual(len(obs_oct25), 1)
        self.assertEqual(obs_oct25[0]["id"], 2)


class TestIntelligentActivityClustering(unittest.TestCase):
    def test_coding_and_debugging_cluster(self):
        """Rapid switching across editor, terminal, and test runner yields 'Coding & Debugging'."""
        base = datetime(2026, 10, 24, 14, 0, 0, tzinfo=timezone.utc)
        sessions = [
            {"app": "Code.exe", "title": "server.py - time tracker", "kind": "active", "start": (base).isoformat(), "end": (base + timedelta(seconds=40)).isoformat(), "duration_seconds": 40},
            {"app": "cmd.exe", "title": "pytest test_api.py", "kind": "active", "start": (base + timedelta(seconds=40)).isoformat(), "end": (base + timedelta(seconds=80)).isoformat(), "duration_seconds": 40},
            {"app": "python.exe", "title": "test runner process", "kind": "active", "start": (base + timedelta(seconds=80)).isoformat(), "end": (base + timedelta(seconds=120)).isoformat(), "duration_seconds": 40},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(c.cluster_type, "mixed")
        self.assertIn("Coding & Debugging", c.label)
        self.assertEqual(c.category_type, "focus")

    def test_technical_research_cluster(self):
        """Rapid research switching across documentation and StackOverflow."""
        base = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)
        sessions = [
            {"app": "chrome.exe", "title": "Python SQLite documentation", "kind": "active", "start": (base).isoformat(), "end": (base + timedelta(seconds=30)).isoformat(), "duration_seconds": 30},
            {"app": "chrome.exe", "title": "StackOverflow - timezone string comparison", "kind": "active", "start": (base + timedelta(seconds=30)).isoformat(), "end": (base + timedelta(seconds=60)).isoformat(), "duration_seconds": 30},
            {"app": "chrome.exe", "title": "GitHub repository issues", "kind": "active", "start": (base + timedelta(seconds=60)).isoformat(), "end": (base + timedelta(seconds=90)).isoformat(), "duration_seconds": 30},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertIn("Technical Research", c.label)

    def test_media_watching_cluster(self):
        """Media watching cluster."""
        base = datetime(2026, 10, 24, 16, 0, 0, tzinfo=timezone.utc)
        sessions = [
            {"app": "chrome.exe", "title": "YouTube - LoFi Focus Music", "kind": "active", "start": (base).isoformat(), "end": (base + timedelta(seconds=30)).isoformat(), "duration_seconds": 30},
            {"app": "Spotify.exe", "title": "Daily Mix", "kind": "active", "start": (base + timedelta(seconds=30)).isoformat(), "end": (base + timedelta(seconds=60)).isoformat(), "duration_seconds": 30},
            {"app": "vlc.exe", "title": "movie_clip.mp4", "kind": "active", "start": (base + timedelta(seconds=60)).isoformat(), "end": (base + timedelta(seconds=90)).isoformat(), "duration_seconds": 30},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        self.assertIn("Video & Media Watching", clusters[0].label)

    def test_midnight_boundary_stops_clustering(self):
        """Clustering must never bridge across local midnight dates."""
        base = datetime(2026, 10, 24, 23, 59, 0, tzinfo=timezone.utc)
        sessions = [
            {"app": "Code.exe", "title": "task 1", "kind": "active", "start": "2026-10-24T23:59:00", "end": "2026-10-24T23:59:30", "duration_seconds": 30},
            {"app": "chrome.exe", "title": "task 2", "kind": "active", "start": "2026-10-24T23:59:30", "end": "2026-10-24T23:59:59", "duration_seconds": 29},
            # Crosses midnight into Oct 25:
            {"app": "cmd.exe", "title": "task 3", "kind": "active", "start": "2026-10-25T00:00:00", "end": "2026-10-25T00:00:30", "duration_seconds": 30},
        ]
        clusters = cluster_timeline_sessions(sessions)
        # The switch on Oct 25 must NOT be merged with Oct 24
        for c in clusters:
            start_d = c.start[:10]
            end_d = c.end[:10]
            self.assertEqual(start_d, end_d, f"Cluster {c.cluster_id} crossed midnight: {start_d} to {end_d}")


if __name__ == "__main__":
    unittest.main()
