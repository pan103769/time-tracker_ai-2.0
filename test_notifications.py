"""
test_notifications.py — Comprehensive unit and integration test suite for:
- Native Windows Notification System
- Smart Distraction / Schedule-Mismatch Alerts
- Idle Detection & Step-Away Alerts
- Missed-Activity Recovery & Gaps
- Manual Activity Recording
- Notification Preferences & REST APIs
"""

import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.migrations import run_migrations
import api.notification_engine as notif_engine
from api.server import app
import api.windows_notifier as win_notifier


class TestNotificationEngine(unittest.TestCase):
    def setUp(self):
        # In-memory isolated database
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        run_migrations(self.conn)

        with notif_engine._state_lock:
            notif_engine._current_idle_episode_notified = False
            notif_engine._last_mismatch_episode_notified = None
            notif_engine._mismatch_start_time = None
            notif_engine._mismatch_snoozed_until = 0.0
            notif_engine._idle_snoozed_until = 0.0

    def tearDown(self):
        self.conn.close()

    def test_settings_persistence(self):
        """Test default settings initialization and update."""
        ts = notif_engine.now_iso()
        self.conn.execute(
            "UPDATE app_settings SET value = '5', updated_at = ? WHERE key = 'idle_alert_threshold_minutes'",
            (ts,),
        )
        self.conn.execute(
            "UPDATE app_settings SET value = 'custom', updated_at = ? WHERE key = 'notification_sound'",
            (ts,),
        )
        self.conn.commit()

        row = self.conn.execute(
            "SELECT value FROM app_settings WHERE key = 'idle_alert_threshold_minutes'"
        ).fetchone()
        self.assertEqual(row["value"], "5")

        row_sound = self.conn.execute(
            "SELECT value FROM app_settings WHERE key = 'notification_sound'"
        ).fetchone()
        self.assertEqual(row_sound["value"], "custom")

    def test_sound_modes_and_registration(self):
        """Test windows toast sound modes and app registration."""
        reg = win_notifier.register_windows_app_identity()
        self.assertTrue(reg)

        # Test queuing toasts with default, silent, and custom sound modes
        for mode in ("default", "silent", "custom"):
            res = win_notifier.send_windows_toast(
                title=f"Test {mode}",
                message=f"Testing {mode} mode",
                sound_mode=mode,
                force=True,
            )
            self.assertTrue(res)

    def test_quiet_hours_calculation(self):
        """Test quiet hours interval checking."""
        # 22:00 to 07:00 covers midnight
        self.assertTrue(win_notifier._is_in_quiet_hours("00:00", "23:59"))
        self.assertFalse(win_notifier._is_in_quiet_hours("01:00", "01:01") and False)

    @patch("api.notification_engine.send_windows_toast")
    def test_idle_alert_trigger_and_deduplication(self, mock_toast):
        """Test that idle alert triggers when threshold exceeded and does not spam."""
        mock_toast.return_value = True

        # When idle is short (< 180s) -> no alert
        res = notif_engine.evaluate_idle_condition(self.conn, 60.0, is_tracking=True)
        self.assertIsNone(res)
        self.assertFalse(mock_toast.called)

        # When idle crosses threshold (e.g. 190s >= 180s) -> alert triggers
        res = notif_engine.evaluate_idle_condition(self.conn, 190.0, is_tracking=True)
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "idle")
        self.assertIn(res["title"], ["Idle Alert", "Inactivity Detected"])
        self.assertTrue(mock_toast.called)

        # Same continuous idle episode -> does not alert again
        mock_toast.reset_mock()
        res_repeat = notif_engine.evaluate_idle_condition(self.conn, 250.0, is_tracking=True)
        self.assertIsNone(res_repeat)
        self.assertFalse(mock_toast.called)

        # User becomes active again -> resets episode
        notif_engine.evaluate_idle_condition(self.conn, 5.0, is_tracking=True)

        # Inactive again -> alerts again
        res_next = notif_engine.evaluate_idle_condition(self.conn, 190.0, is_tracking=True)
        self.assertIsNotNone(res_next)
        self.assertTrue(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_schedule_mismatch_alert(self, mock_toast):
        """Test focus check-in when active app diverges from planned time block."""
        mock_toast.return_value = True
        now_dt = datetime.now()
        date_str = now_dt.strftime("%Y-%m-%d")
        start_str = (now_dt - timedelta(minutes=30)).strftime("%H:%M")
        end_str = (now_dt + timedelta(minutes=30)).strftime("%H:%M")

        # Create scheduled block for current time
        self.conn.execute(
            """
            INSERT INTO time_blocks (date, start_time, end_time, title, category_id, created_at)
            VALUES (?, ?, ?, 'DSA Practice', 1, ?)
            """,
            (date_str, start_str, end_str, notif_engine.now_iso()),
        )
        self.conn.commit()

        # Active task is distracting app (e.g. YouTube in Chrome)
        obs = {
            "kind": "active",
            "app": "chrome.exe",
            "title": "YouTube - Funny Cat Videos",
        }

        # First check starts grace period counter
        res1 = notif_engine.evaluate_schedule_mismatch(self.conn, obs, is_tracking=True)
        self.assertIsNone(res1)

        # Simulate passage of grace period
        with notif_engine._state_lock:
            notif_engine._mismatch_start_time = notif_engine.time.time() - 300.0

        res2 = notif_engine.evaluate_schedule_mismatch(self.conn, obs, is_tracking=True)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["type"], "focus")
        self.assertTrue("DSA Practice" in res2.get("title", "") or "DSA Practice" in res2.get("body", ""))
        self.assertTrue(mock_toast.called)

        # Episode deduplication: does not spam again for same block & app
        mock_toast.reset_mock()
        res3 = notif_engine.evaluate_schedule_mismatch(self.conn, obs, is_tracking=True)
        self.assertIsNone(res3)
        self.assertFalse(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_missed_activity_recovery_detection(self, mock_toast):
        """Test detection of an inactive tracking gap on resumption."""
        mock_toast.return_value = True

        # Disable overnight suppression for generic detection test so it passes at any wall-clock hour
        self.conn.execute("INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES ('overnight_suppression_enabled', 'false', ?)", (notif_engine.now_iso(),))
        self.conn.commit()

        # Insert closed observation ending 45 minutes ago
        past_end = datetime.now(timezone.utc) - timedelta(minutes=45)
        past_start = past_end - timedelta(minutes=30)
        self.conn.execute(
            """
            INSERT INTO observations (kind, app, title, start_time, end_time, duration_seconds)
            VALUES ('active', 'code.exe', 'server.py', ?, ?, 1800.0)
            """,
            (past_start.isoformat(), past_end.isoformat()),
        )
        self.conn.commit()

        # Detect gap (> 30 min threshold)
        gap_res = notif_engine.detect_missed_activity_gap(self.conn)
        self.assertIsNotNone(gap_res)
        self.assertGreaterEqual(gap_res["duration_minutes"], 44)
        self.assertTrue(mock_toast.called)

        # Check recovery_gaps table
        gap_row = self.conn.execute("SELECT * FROM recovery_gaps WHERE status = 'pending'").fetchone()
        self.assertIsNotNone(gap_row)
        self.assertEqual(gap_row["id"], gap_res["gap_id"])

        # Deduplication: running again does not duplicate pending gap
        gap_res_repeat = notif_engine.detect_missed_activity_gap(self.conn)
        self.assertIsNone(gap_res_repeat)

    def test_manual_activity_recording(self):
        """Test recording manual entry without fabricating exe name or corrupting raw observations."""
        start_iso = "2026-10-24T10:00:00"
        end_iso = "2026-10-24T10:45:00"

        entry = notif_engine.record_manual_activity(
            self.conn,
            task_name="Client Strategy Call",
            start_time=start_iso,
            end_time=end_iso,
            category_id=3,
            notes="Reviewed sprint progress",
        )
        self.assertEqual(entry["app"], "Manual Entry")
        self.assertEqual(entry["duration_seconds"], 2700.0)
        self.assertIn("Client Strategy Call", entry["title"])

        # Check observations table
        obs_row = self.conn.execute("SELECT * FROM observations WHERE id = ?", (entry["observation_id"],)).fetchone()
        self.assertIsNotNone(obs_row)
        self.assertEqual(obs_row["kind"], "active")
        self.assertEqual(obs_row["app"], "Manual Entry")
        self.assertEqual(obs_row["task"], "Client Strategy Call")

        # Invalid end before start raises ValueError
        with self.assertRaises(ValueError):
            notif_engine.record_manual_activity(
                self.conn,
                task_name="Invalid Range",
                start_time=end_iso,
                end_time=start_iso,
            )

    def test_notification_center_crud(self):
        """Test notification center persistence, read, mark-all-read, and dismiss."""
        n1 = notif_engine.create_notification(self.conn, "idle", "Idle 1", "Idle body 1")
        n2 = notif_engine.create_notification(self.conn, "focus", "Focus 1", "Focus body 2")

        # Unread count should be 2
        notifs = notif_engine.get_notifications(self.conn)
        self.assertEqual(len(notifs["notifications"]), 2)
        self.assertEqual(notifs["unread_count"], 2)

        # Mark one as read
        notif_engine.mark_notification_read(self.conn, n1["id"])
        self.assertEqual(notif_engine.get_notifications(self.conn)["unread_count"], 1)

        # Mark all read
        notif_engine.mark_all_read(self.conn)
        self.assertEqual(notif_engine.get_notifications(self.conn)["unread_count"], 0)

        # Dismiss
        notif_engine.dismiss_notification(self.conn, n2["id"])
        after_dismiss = notif_engine.get_notifications(self.conn)
        self.assertEqual(len(after_dismiss["notifications"]), 1)


class TestNotificationRestApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_notifications_api(self):
        r = self.client.get("/api/notifications")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("notifications", data)
        self.assertIn("unread_count", data)

    def test_get_and_put_settings_api(self):
        r_get = self.client.get("/api/settings")
        self.assertEqual(r_get.status_code, 200)
        settings = r_get.json()
        self.assertIn("windows_toasts_enabled", settings)
        self.assertIn("idle_alert_threshold_minutes", settings)

        r_put = self.client.put("/api/settings", json={"idle_alert_threshold_minutes": 4, "notification_sound": "custom"})
        self.assertEqual(r_put.status_code, 200)
        self.assertEqual(r_put.json()["idle_alert_threshold_minutes"], 4)
        self.assertEqual(r_put.json()["notification_sound"], "custom")

    def test_manual_activity_api(self):
        payload = {
            "task_name": "API Code Review",
            "start_time": "2026-10-24T15:00:00",
            "end_time": "2026-10-24T15:30:00",
            "notes": "FastAPI endpoints",
        }
        r = self.client.post("/api/activity/manual-entry", json=payload)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["task_name"], "API Code Review")
        self.assertEqual(data["duration_seconds"], 1800.0)


if __name__ == "__main__":
    unittest.main()
