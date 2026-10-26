"""
tests/test_missed_activity_recovery.py — Test suite for missed-activity recovery,
overnight sleep suppression, quiet hours, and relative date context.
"""

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api import notification_engine as ne


class TestMissedActivityRecovery(unittest.TestCase):
    def setUp(self):
        """Set up an in-memory database with required schema."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def tearDown(self):
        self.conn.close()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                app TEXT NOT NULL,
                title TEXT,
                task TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds REAL,
                created_at TEXT
            );

            CREATE TABLE recovery_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gap_start TEXT NOT NULL,
                gap_end TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                details TEXT,
                unread INTEGER DEFAULT 1,
                dismissed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'delivered',
                created_at TEXT NOT NULL
            );

            CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            CREATE TABLE session_categories (
                session_key TEXT PRIMARY KEY,
                category_id INTEGER,
                updated_at TEXT
            );
            """
        )

    def _set_setting(self, key: str, val: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, str(val), ne.now_iso()),
        )
        self.conn.commit()

    @patch("api.notification_engine.send_windows_toast")
    def test_same_day_gap_triggers_prompt(self, mock_toast):
        """A 60-minute gap during daytime on the same day should trigger a prompt with 'Today at' context."""
        now_utc = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)  # 3:00 PM UTC
        last_end_utc = now_utc - timedelta(minutes=60)
        last_start_utc = last_end_utc - timedelta(minutes=30)

        # Set sleep window outside this daytime period
        self._set_setting("overnight_suppression_enabled", "true")
        self._set_setting("overnight_sleep_start", "23:00")
        self._set_setting("overnight_sleep_end", "07:00")
        self._set_setting("missed_recovery_threshold_minutes", "30")

        self.conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES ('active', 'Code.exe', 'editor.py', ?, ?, 1800.0)
            """,
            (last_start_utc.isoformat(), last_end_utc.isoformat()),
        )
        self.conn.commit()

        gap = ne.detect_missed_activity_gap(self.conn, now_override=now_utc)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["duration_minutes"], 60)
        self.assertIn("Today at", gap["notification"]["body"])
        self.assertTrue(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_overnight_gap_suppressed_during_sleep_hours(self, mock_toast):
        """A gap evaluated at 4:27 AM while inside the overnight sleep period should be suppressed."""
        # Assume local timezone is same as UTC for deterministic test (or calculate relative)
        # Using now_local inside overnight sleep: 04:27
        # Let's configure sleep window around current local time
        now_local = datetime.now()
        cur_h = now_local.hour
        # Set sleep window covering current hour
        sleep_start = f"{(cur_h - 2) % 24:02d}:00"
        sleep_end = f"{(cur_h + 2) % 24:02d}:00"

        self._set_setting("overnight_suppression_enabled", "true")
        self._set_setting("overnight_sleep_start", sleep_start)
        self._set_setting("overnight_sleep_end", sleep_end)

        now_utc = datetime.now(timezone.utc)
        last_end = now_utc - timedelta(hours=6)
        last_start = last_end - timedelta(hours=1)

        self.conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES ('active', 'Code.exe', 'editor.py', ?, ?, 3600.0)
            """,
            (last_start.isoformat(), last_end.isoformat()),
        )
        self.conn.commit()

        gap = ne.detect_missed_activity_gap(self.conn, now_override=now_utc)
        self.assertIsNone(gap, "Prompt should be suppressed when current time is in sleep hours")
        self.assertFalse(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_waking_gap_across_midnight_shows_previous_day_context(self, mock_toast):
        """When user stops at 9:00 PM yesterday and opens app after waking up at 8:00 AM, shows Yesterday."""
        now_local = datetime.now()
        cur_h = now_local.hour

        # Ensure current hour is NOT in sleep window
        sleep_start = f"{(cur_h + 4) % 24:02d}:00"
        sleep_end = f"{(cur_h + 8) % 24:02d}:00"

        self._set_setting("overnight_suppression_enabled", "true")
        self._set_setting("overnight_sleep_start", sleep_start)
        self._set_setting("overnight_sleep_end", sleep_end)
        self._set_setting("missed_recovery_threshold_minutes", "30")

        # Gap from yesterday in local time (e.g. 26 hours ago)
        now_utc = datetime.now(timezone.utc)
        last_end = now_utc - timedelta(hours=26)
        last_start = last_end - timedelta(hours=1)

        self.conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES ('active', 'chrome.exe', 'dashboard', ?, ?, 3600.0)
            """,
            (last_start.isoformat(), last_end.isoformat()),
        )
        self.conn.commit()

        gap = ne.detect_missed_activity_gap(self.conn, now_override=now_utc)
        self.assertIsNotNone(gap)
        self.assertIn("Yesterday at", gap["notification"]["body"])

    @patch("api.notification_engine.send_windows_toast")
    def test_configurable_overnight_suppression_toggle(self, mock_toast):
        """When overnight suppression is disabled, prompts are NOT suppressed by sleep hours."""
        now_local = datetime.now()
        cur_h = now_local.hour
        sleep_start = f"{(cur_h - 1) % 24:02d}:00"
        sleep_end = f"{(cur_h + 1) % 24:02d}:00"

        # Explicitly disable overnight suppression
        self._set_setting("overnight_suppression_enabled", "false")
        self._set_setting("overnight_sleep_start", sleep_start)
        self._set_setting("overnight_sleep_end", sleep_end)
        self._set_setting("missed_recovery_threshold_minutes", "30")

        now_utc = datetime.now(timezone.utc)
        last_end = now_utc - timedelta(minutes=45)
        last_start = last_end - timedelta(minutes=30)

        self.conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES ('active', 'chrome.exe', 'dashboard', ?, ?, 1800.0)
            """,
            (last_start.isoformat(), last_end.isoformat()),
        )
        self.conn.commit()

        gap = ne.detect_missed_activity_gap(self.conn, now_override=now_utc)
        self.assertIsNotNone(gap, "With suppression disabled, prompt should be allowed")

    @patch("api.notification_engine.send_windows_toast")
    def test_quiet_hours_suppresses_prompt(self, mock_toast):
        """When quiet hours is enabled and active, prompt should be suppressed."""
        now_local = datetime.now()
        cur_h = now_local.hour
        qh_start = f"{(cur_h - 1) % 24:02d}:00"
        qh_end = f"{(cur_h + 1) % 24:02d}:00"

        self._set_setting("quiet_hours_enabled", "true")
        self._set_setting("quiet_hours_start", qh_start)
        self._set_setting("quiet_hours_end", qh_end)
        self._set_setting("overnight_suppression_enabled", "false")

        now_utc = datetime.now(timezone.utc)
        last_end = now_utc - timedelta(hours=2)
        last_start = last_end - timedelta(hours=1)

        self.conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES ('active', 'chrome.exe', 'dashboard', ?, ?, 3600.0)
            """,
            (last_start.isoformat(), last_end.isoformat()),
        )
        self.conn.commit()

        gap = ne.detect_missed_activity_gap(self.conn, now_override=now_utc)
        self.assertIsNone(gap, "Quiet hours should suppress prompt")

    def test_chronological_ordering_not_tricked_by_high_id(self):
        """
        Verify that an older record with a higher ID (e.g. manual entry or out-of-order write)
        does not cause the engine to pick the wrong end_time.
        """
        now_utc = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
        recent_end = now_utc - timedelta(minutes=10)
        recent_start = recent_end - timedelta(minutes=20)

        older_end = now_utc - timedelta(hours=8)
        older_start = older_end - timedelta(hours=1)

        # Insert recent observation with ID 10
        self.conn.execute(
            """
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (10, 'active', 'Code.exe', 'work', ?, ?, 1200.0)
            """,
            (recent_start.isoformat(), recent_end.isoformat()),
        )
        # Insert older observation with ID 99 (simulating manual entry with high auto-increment ID)
        self.conn.execute(
            """
            INSERT INTO observations (id, kind, app, title, start_time, end_time, duration_seconds)
            VALUES (99, 'active', 'Manual Entry', 'retro', ?, ?, 3600.0)
            """,
            (older_start.isoformat(), older_end.isoformat()),
        )
        self.conn.commit()

        # Because recent observation was only 10 minutes ago, no gap should be detected
        gap = ne.detect_missed_activity_gap(self.conn, now_override=now_utc)
        self.assertIsNone(gap, "Should not report gap since latest activity was only 10m ago")

    def test_record_manual_activity_preserves_raw_data(self):
        """Manual activity recording should add clean entry without corrupting raw observations."""
        res = ne.record_manual_activity(
            self.conn,
            task_name="Architecture Review",
            start_time="2026-10-25T09:00:00",
            end_time="2026-10-25T10:00:00",
            notes="Reviewed database schema",
        )
        self.assertEqual(res["app"], "Manual Entry")
        self.assertEqual(res["task_name"], "Architecture Review")
        self.assertEqual(res["duration_seconds"], 3600.0)

        # Check DB
        row = self.conn.execute("SELECT * FROM observations WHERE id = ?", (res["observation_id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["app"], "Manual Entry")
        self.assertEqual(row["kind"], "active")


if __name__ == "__main__":
    unittest.main()

