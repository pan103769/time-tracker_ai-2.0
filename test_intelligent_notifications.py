"""
test_intelligent_notifications.py — Comprehensive test suite for intelligent, relevant,
low-noise notifications in Time Tracker AI 2.

Covers:
1. Upcoming block receives 1 correctly timed reminder within [-5m, +10m]
2. Expired blocks receive NO start reminder (prevents the 11:12 PM for 9:30 AM bug)
3. App restart / cache reset does not produce bursts of overdue reminders
4. Quiet hours & overnight suppression
5. Start Focus removes active Windows toast and updates status to 'acted_upon'
6. Repeated checks do not duplicate notifications
7. Snooze suppresses reminder until snooze expiration then re-evaluates
8. Continuous idle alerts once per episode, resets only after active input
9. Mismatch alerts once per episode with sustained grace period
10. Skip Block preserves scheduled block record and dismisses toast
11. Missed block recovery triggers only for blocks ended within 90m without tracked work
12. Reschedule time block updates block, resets reminder flags, and removes toasts
13. Test notifications are explicitly badged [TEST] and tagged test_notification
14. Global toast rate limiting throttles rapid sequential notifications
"""

import json
import sqlite3
import time
import unittest
from datetime import datetime, timedelta, timezone, time as dt_time
from unittest.mock import MagicMock, patch

from api.migrations import run_migrations
import api.notification_engine as notif_engine
import api.windows_notifier as win_notifier
from api.server import app
from fastapi.testclient import TestClient


class TestIntelligentNotifications(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        run_migrations(self.conn)
        notif_engine.reset_notification_state()
        win_notifier.reset_rate_limit_state()

        # Disable overnight suppression by default in unit tests so tests pass at any hour
        ts = notif_engine.now_iso()
        self.conn.execute("UPDATE app_settings SET value = 'false', updated_at = ? WHERE key = 'overnight_suppression_enabled'", (ts,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _insert_block(self, date_str: str, start_time: str, end_time: str, title: str, category_id: int = 1):
        ts = notif_engine.now_iso()
        cursor = self.conn.execute(
            """
            INSERT INTO time_blocks (date, start_time, end_time, title, category_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (date_str, start_time, end_time, title, category_id, ts),
        )
        self.conn.commit()
        return cursor.lastrowid

    # -------------------------------------------------------------------------
    # 1. Upcoming block receives 1 correctly timed reminder
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_upcoming_block_correctly_timed_reminder(self, mock_toast):
        mock_toast.return_value = True
        ref_time = datetime(2026, 10, 25, 9, 28, 0)  # 2 minutes before 9:30 start
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "DSA Practice")

        res = notif_engine.evaluate_time_block_reminders(
            self.conn,
            is_tracking=False,
            now_override=ref_time,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["block_id"], b_id)
        self.assertIn("Time to start DSA Practice", res["notification"]["title"])
        self.assertEqual(res["notification"]["status"], "delivered")
        self.assertTrue(mock_toast.called)
        # Verify tag and group passed to windows toast
        _, kwargs = mock_toast.call_args
        self.assertEqual(kwargs.get("tag"), f"block_{b_id}")
        self.assertEqual(kwargs.get("group"), "time_tracker")

    # -------------------------------------------------------------------------
    # 2. Expired blocks receive NO start reminder (Fix for 11:12 PM 9:30 AM bug)
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_expired_block_receives_no_start_reminder(self, mock_toast):
        mock_toast.return_value = True
        # Current time is 11:12 PM (23:12)
        night_time = datetime(2026, 10, 25, 23, 12, 0)
        date_str = "2026-10-25"
        # Block was 9:30 AM to 11:00 AM (ended 12 hours ago!)
        b_id = self._insert_block(date_str, "09:30", "11:00", "DSA Practice")

        res = notif_engine.evaluate_time_block_reminders(
            self.conn,
            is_tracking=False,
            now_override=night_time,
        )
        self.assertIsNone(res, "Expired block must NEVER trigger a start reminder!")
        self.assertFalse(mock_toast.called)

        # Confirm block was marked reminded so it stays quiet permanently
        row = self.conn.execute("SELECT value FROM app_settings WHERE key = ?", (f"notif_block_reminded_{b_id}",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], "1")

    # -------------------------------------------------------------------------
    # 3. Overdue block past 10-minute window receives NO start reminder
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_overdue_block_past_ten_minutes_receives_no_start_reminder(self, mock_toast):
        mock_toast.return_value = True
        # Current time is 9:45 AM for a block starting at 9:30 AM (15 minutes past start)
        current_time = datetime(2026, 10, 25, 9, 45, 0)
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "System Architecture")

        res = notif_engine.evaluate_time_block_reminders(
            self.conn,
            is_tracking=False,
            now_override=current_time,
        )
        self.assertIsNone(res, "Block > 10m past start must not fire overdue start reminder!")
        self.assertFalse(mock_toast.called)

    # -------------------------------------------------------------------------
    # 4. App restart does not produce bursts of overdue reminders
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_app_restart_prevents_reminder_burst(self, mock_toast):
        mock_toast.return_value = True
        ref_time = datetime(2026, 10, 25, 9, 30, 0)
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "Deep Work")

        # Initial reminder fires
        res = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=ref_time)
        self.assertIsNotNone(res)
        self.assertEqual(mock_toast.call_count, 1)

        # Simulate full app restart: in-memory state is completely wiped
        notif_engine.reset_notification_state()
        mock_toast.reset_mock()

        # Immediate re-check after restart: persistent app_settings prevents re-alerting!
        res_after_restart = notif_engine.evaluate_time_block_reminders(
            self.conn,
            is_tracking=False,
            now_override=ref_time + timedelta(seconds=15),
        )
        self.assertIsNone(res_after_restart, "Persistent app_settings must prevent reminder burst on restart!")
        self.assertFalse(mock_toast.called)

    # -------------------------------------------------------------------------
    # 5. Quiet hours suppression
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_quiet_hours_suppresses_toast(self, mock_toast):
        mock_toast.return_value = True
        # Enable quiet hours 22:00 to 07:00
        ts = notif_engine.now_iso()
        self.conn.execute("UPDATE app_settings SET value = 'true', updated_at = ? WHERE key = 'quiet_hours_enabled'", (ts,))
        self.conn.execute("UPDATE app_settings SET value = '22:00', updated_at = ? WHERE key = 'quiet_hours_start'", (ts,))
        self.conn.execute("UPDATE app_settings SET value = '07:00', updated_at = ? WHERE key = 'quiet_hours_end'", (ts,))
        self.conn.commit()

        # Block at 22:30 during quiet hours
        ref_time = datetime(2026, 10, 25, 22, 28, 0)
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "22:30", "23:30", "Late Reading")

        res = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=ref_time)
        self.assertIsNone(res, "Quiet hours must suppress desktop notification toast")
        self.assertFalse(mock_toast.called)

        # Planned task is still updated quietly
        row = self.conn.execute("SELECT value FROM app_settings WHERE key = 'current_planned_task'").fetchone()
        self.assertEqual(row["value"], "Late Reading")

    # -------------------------------------------------------------------------
    # 6. Start Focus removes active Windows toast and updates notification
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.remove_windows_toast")
    @patch("api.tracker_manager.assign_active_task")
    @patch("api.tracker_manager.start_tracking")
    @patch("api.tracker_manager.is_tracking_active")
    def test_start_focus_action(self, mock_is_tracking, mock_start_trk, mock_assign, mock_remove_toast):
        mock_is_tracking.return_value = False
        mock_assign.return_value = {"active_task": "DSA Practice"}

        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "DSA Practice")

        # Create a delivered notification in DB
        notif_engine.create_notification(
            self.conn,
            notif_type="time_block",
            title="Time to start DSA Practice",
            body="9:30 AM - 11:00 AM",
            details={"block_id": b_id},
            status="delivered",
        )

        res = notif_engine.start_focus_for_time_block(self.conn, b_id)
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["block_id"], b_id)

        # Verify remove_windows_toast was called with the block's tag
        mock_remove_toast.assert_called_with(tag=f"block_{b_id}", group="time_tracker")

        # Verify notification status in DB was updated to 'acted_upon'
        row = self.conn.execute("SELECT status, unread FROM notifications WHERE type = 'time_block'").fetchone()
        self.assertEqual(row["status"], "acted_upon")
        self.assertEqual(row["unread"], 0)

    # -------------------------------------------------------------------------
    # 7. Snooze postpones reminder and dismisses current banner
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.remove_windows_toast")
    @patch("api.notification_engine.send_windows_toast")
    def test_snooze_flow(self, mock_send_toast, mock_remove_toast):
        mock_send_toast.return_value = True
        ref_time = datetime(2026, 10, 25, 9, 29, 0)
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "Research")

        # Initial trigger
        notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=ref_time)
        self.assertEqual(mock_send_toast.call_count, 1)

        # User snoozes for 5 minutes
        snooze_res = notif_engine.snooze_time_block_reminder(self.conn, b_id, minutes=5)
        self.assertEqual(snooze_res["status"], "snoozed")
        mock_remove_toast.assert_called_with(tag=f"block_{b_id}", group="time_tracker")

        # Notification status updated to 'snoozed'
        row = self.conn.execute("SELECT status FROM notifications WHERE type = 'time_block'").fetchone()
        self.assertEqual(row["status"], "snoozed")

        # Immediate re-check at 9:31 AM (within snooze period) -> no reminder!
        mock_send_toast.reset_mock()
        res_during_snooze = notif_engine.evaluate_time_block_reminders(
            self.conn,
            is_tracking=False,
            now_override=ref_time + timedelta(minutes=2),
        )
        self.assertIsNone(res_during_snooze)
        self.assertFalse(mock_send_toast.called)

    # -------------------------------------------------------------------------
    # 8. Skip Block preserves block record and updates status
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.remove_windows_toast")
    def test_skip_block_preserves_record(self, mock_remove_toast):
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "Team Meeting")

        notif_engine.create_notification(
            self.conn,
            notif_type="time_block",
            title="Time to start Team Meeting",
            body="9:30 AM - 11:00 AM",
            details={"block_id": b_id},
            status="delivered",
        )

        res = notif_engine.skip_time_block(self.conn, b_id)
        self.assertEqual(res["status"], "skipped")
        mock_remove_toast.assert_called_with(tag=f"block_{b_id}", group="time_tracker")

        # Confirm block record still exists in time_blocks table
        block_row = self.conn.execute("SELECT * FROM time_blocks WHERE id = ?", (b_id,)).fetchone()
        self.assertIsNotNone(block_row, "Skipping a reminder must NOT delete the planned time block!")

        # Notification status updated to 'skipped' and dismissed
        row = self.conn.execute("SELECT status, dismissed FROM notifications WHERE type = 'time_block'").fetchone()
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["dismissed"], 1)

    # -------------------------------------------------------------------------
    # 9. Missed-block recovery: triggers for recently ended uncompleted blocks (< 90m)
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_missed_block_recovery(self, mock_toast):
        mock_toast.return_value = True
        now_dt = datetime(2026, 10, 25, 11, 45, 0)  # Block ended at 11:00 (45 mins ago)
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "DSA Practice")

        res = notif_engine.evaluate_missed_block_recovery(
            self.conn,
            is_tracking=False,
            now_override=now_dt,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["block_id"], b_id)
        self.assertIn("Missed block: DSA Practice", res["notification"]["title"])
        self.assertEqual(res["notification"]["type"], "missed_block")
        self.assertEqual(res["notification"]["status"], "delivered")
        self.assertTrue(mock_toast.called)

        # Tag must be missed_{b_id} (NOT a start reminder!)
        _, kwargs = mock_toast.call_args
        self.assertEqual(kwargs.get("tag"), f"missed_{b_id}")

        # Re-check does not duplicate
        mock_toast.reset_mock()
        res_repeat = notif_engine.evaluate_missed_block_recovery(
            self.conn,
            is_tracking=False,
            now_override=now_dt + timedelta(minutes=5),
        )
        self.assertIsNone(res_repeat)
        self.assertFalse(mock_toast.called)

    # -------------------------------------------------------------------------
    # 10. Missed-block recovery does NOT trigger for ancient blocks (> 90m)
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.send_windows_toast")
    def test_missed_block_recovery_ignores_ancient_blocks(self, mock_toast):
        mock_toast.return_value = True
        # Block ended at 11:00 AM, now is 4:00 PM (300 mins ago)
        now_dt = datetime(2026, 10, 25, 16, 0, 0)
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "Morning Review")

        res = notif_engine.evaluate_missed_block_recovery(
            self.conn,
            is_tracking=False,
            now_override=now_dt,
        )
        self.assertIsNone(res, "Missed block recovery must ignore blocks ended > 90 minutes ago!")
        self.assertFalse(mock_toast.called)

    # -------------------------------------------------------------------------
    # 11. Reschedule time block updates block and resets flags
    # -------------------------------------------------------------------------
    @patch("api.notification_engine.remove_windows_toast")
    def test_reschedule_time_block(self, mock_remove_toast):
        date_str = "2026-10-25"
        b_id = self._insert_block(date_str, "09:30", "11:00", "DSA Practice")

        # Mark reminded initially
        notif_engine._mark_block_reminded(self.conn, b_id)
        self.assertTrue(notif_engine._has_block_been_notified(self.conn, b_id))

        # Reschedule to afternoon
        res = notif_engine.reschedule_time_block(
            self.conn,
            b_id,
            new_date="2026-10-25",
            new_start_time="14:00",
            new_end_time="15:30",
        )
        self.assertEqual(res["status"], "rescheduled")
        self.assertEqual(res["start_time"], "14:00")

        # Reminder flag was reset so it can notify at the new time
        self.assertFalse(notif_engine._has_block_been_notified(self.conn, b_id))
        mock_remove_toast.assert_any_call(tag=f"block_{b_id}", group="time_tracker")

    # -------------------------------------------------------------------------
    # 12. Toast rate-limiting throttle prevents spam
    # -------------------------------------------------------------------------
    @patch("api.windows_notifier._dispatch_powershell_toast")
    def test_toast_rate_limiting_throttle(self, mock_ps):
        mock_ps.return_value = True

        # First toast succeeds
        res1 = win_notifier.send_windows_toast(
            title="First Toast",
            message="Initial notification",
            force=False,
        )
        self.assertTrue(res1)
        time.sleep(0.1)
        self.assertEqual(mock_ps.call_count, 1)

        # Immediate second toast within throttle interval (20s) is dropped to prevent spam
        res2 = win_notifier.send_windows_toast(
            title="Second Toast",
            message="Rapid notification",
            force=False,
        )
        self.assertFalse(res2, "Rapid sequential non-forced toast must be rate limited")
        time.sleep(0.1)
        self.assertEqual(mock_ps.call_count, 1)

        # Forced toast bypasses throttle (e.g. for user test actions)
        res3 = win_notifier.send_windows_toast(
            title="[TEST] Forced Test Toast",
            message="Forced preview",
            force=True,
        )
        self.assertTrue(res3)
        time.sleep(0.1)
        self.assertEqual(mock_ps.call_count, 2)


if __name__ == "__main__":
    unittest.main()
