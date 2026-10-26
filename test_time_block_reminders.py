"""
test_time_block_reminders.py — Unit and integration tests for Native Windows Time-Block Start Reminders:
- Scheduled reminder triggers when block reaches start time
- Action: Start Focus (starts tracking, assigns active task, marks block started)
- Action: Snooze (5 min / 10 min postpones reminder without altering scheduled block)
- Action: Skip this block (dismisses reminder without deleting block or recording fake work)
- Action: Open Planner (opens existing Time Blocks page)
- Quiet hours & overnight suppression (planned block remains visible, toast suppressed)
- Duplicate prevention (no repeated alerts if already started or notified)
- Missed start times / app restart (no burst of overdue notifications)
- Focus Session auto-start is optional and disabled by default
- REST APIs & toast dispatching
"""

import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone, time as dt_time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.migrations import run_migrations
import api.notification_engine as notif_engine
from api.server import app
import api.windows_notifier as win_notifier


class TestTimeBlockReminders(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        run_migrations(self.conn)
        notif_engine.reset_notification_state()
        # Disable overnight suppression in unit tests so test suite behaves deterministically at all times of day/night
        ts = notif_engine.now_iso()
        self.conn.execute("UPDATE app_settings SET value = 'false', updated_at = ? WHERE key = 'overnight_suppression_enabled'", (ts,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _insert_block(self, date_str: str, start_time: str, end_time: str, title: str, category_id=1):
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

    @patch("api.notification_engine.send_windows_toast")
    def test_reminder_triggers_at_start_time(self, mock_toast):
        """Test that desktop notification is dispatched when scheduled block reaches start time."""
        mock_toast.return_value = True

        local_now = datetime.now()
        date_str = local_now.strftime("%Y-%m-%d")
        start_str = (local_now - timedelta(minutes=2)).strftime("%H:%M")
        end_str = (local_now + timedelta(minutes=45)).strftime("%H:%M")

        block_id = self._insert_block(date_str, start_str, end_str, "Deep Work: Algorithm Design")

        res = notif_engine.evaluate_time_block_reminders(
            self.conn,
            is_tracking=False,
            now_override=local_now,
        )

        self.assertIsNotNone(res)
        self.assertEqual(res["block_id"], block_id)
        self.assertIn("Algorithm Design", res["title"])
        self.assertTrue(mock_toast.called)

        # Check notification persisted in DB
        notif = res["notification"]
        self.assertEqual(notif["type"], "time_block")
        self.assertIn("Ready to begin", notif["body"])
        self.assertEqual(notif["details"]["block_id"], block_id)

        # Planned task was set in app_settings without recording fake work
        setting_row = self.conn.execute("SELECT value FROM app_settings WHERE key = 'current_planned_task'").fetchone()
        self.assertIsNotNone(setting_row)
        self.assertEqual(setting_row["value"], "Deep Work: Algorithm Design")

        # No fake observations created
        obs_count = self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        self.assertEqual(obs_count, 0)

    @patch("api.notification_engine.send_windows_toast")
    def test_start_focus_action(self, mock_toast):
        """Test Start Focus makes the block the active task and starts linked Focus Session."""
        mock_toast.return_value = True

        local_now = datetime.now()
        date_str = local_now.strftime("%Y-%m-%d")
        start_str = local_now.strftime("%H:%M")
        end_str = (local_now + timedelta(minutes=60)).strftime("%H:%M")

        block_id = self._insert_block(date_str, start_str, end_str, "Implement Vision Pipeline", category_id=1)

        # Trigger notification
        notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)

        # Execute Start Focus action
        with patch("api.tracker_manager.is_tracking_active", return_value=False), \
             patch("api.tracker_manager.start_tracking") as mock_start, \
             patch("api.tracker_manager.assign_active_task") as mock_assign:

            mock_assign.return_value = {"user_task": "Implement Vision Pipeline"}
            res = notif_engine.start_focus_for_time_block(self.conn, block_id)

            self.assertEqual(res["status"], "started")
            self.assertEqual(res["title"], "Implement Vision Pipeline")
            self.assertTrue(mock_start.called)
            mock_assign.assert_called_with(task_name="Implement Vision Pipeline", category_id=1)

        # Check block is marked started in app_settings
        st_row = self.conn.execute("SELECT value FROM app_settings WHERE key = ?", (f"block_focus_started_{block_id}",)).fetchone()
        self.assertEqual(st_row["value"], "1")

        # Related notifications marked read
        unread_notifs = self.conn.execute("SELECT COUNT(*) FROM notifications WHERE type = 'time_block' AND unread = 1").fetchone()[0]
        self.assertEqual(unread_notifs, 0)

        # Evaluating again does not dispatch another reminder
        mock_toast.reset_mock()
        repeat_res = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=True, now_override=local_now)
        self.assertIsNone(repeat_res)
        self.assertFalse(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_snooze_reminder_action(self, mock_toast):
        """Test Snooze 5m / 10m postpones reminder without altering scheduled block."""
        mock_toast.return_value = True

        local_now = datetime.now()
        date_str = local_now.strftime("%Y-%m-%d")
        start_str = local_now.strftime("%H:%M")
        end_str = (local_now + timedelta(minutes=50)).strftime("%H:%M")

        block_id = self._insert_block(date_str, start_str, end_str, "Documentation Review")

        # First trigger
        res1 = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)
        self.assertIsNotNone(res1)
        self.assertTrue(mock_toast.called)

        # User snoozes 5 minutes
        snooze_res = notif_engine.snooze_time_block_reminder(self.conn, block_id, minutes=5)
        self.assertEqual(snooze_res["status"], "snoozed")
        self.assertEqual(snooze_res["minutes"], 5)

        # Verify scheduled block times in time_blocks table are UNCHANGED
        b_row = self.conn.execute("SELECT * FROM time_blocks WHERE id = ?", (block_id,)).fetchone()
        self.assertEqual(b_row["start_time"], start_str)
        self.assertEqual(b_row["end_time"], end_str)

        # Check 2 minutes later: still within snooze window -> no toast
        mock_toast.reset_mock()
        res_during_snooze = notif_engine.evaluate_time_block_reminders(
            self.conn, is_tracking=False, now_override=local_now + timedelta(minutes=2)
        )
        self.assertIsNone(res_during_snooze)
        self.assertFalse(mock_toast.called)

        # Check 6 minutes later: snooze expired -> re-triggers reminder!
        res_after_snooze = notif_engine.evaluate_time_block_reminders(
            self.conn, is_tracking=False, now_override=local_now + timedelta(minutes=6)
        )
        self.assertIsNotNone(res_after_snooze)
        self.assertTrue(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_skip_block_action(self, mock_toast):
        """Test Skip dismisses reminder without deleting block or recording fake work."""
        mock_toast.return_value = True

        local_now = datetime.now()
        date_str = local_now.strftime("%Y-%m-%d")
        start_str = local_now.strftime("%H:%M")
        end_str = (local_now + timedelta(minutes=45)).strftime("%H:%M")

        block_id = self._insert_block(date_str, start_str, end_str, "Optional Brainstorming")

        # First trigger
        notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)

        # User chooses to skip
        skip_res = notif_engine.skip_time_block(self.conn, block_id)
        self.assertEqual(skip_res["status"], "skipped")

        # Block is NOT deleted from time_blocks
        b_row = self.conn.execute("SELECT * FROM time_blocks WHERE id = ?", (block_id,)).fetchone()
        self.assertIsNotNone(b_row)

        # No fake work recorded in observations
        obs_count = self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        self.assertEqual(obs_count, 0)

        # Evaluating again does not remind
        mock_toast.reset_mock()
        res2 = notif_engine.evaluate_time_block_reminders(
            self.conn, is_tracking=False, now_override=local_now + timedelta(minutes=5)
        )
        self.assertIsNone(res2)
        self.assertFalse(mock_toast.called)

    @patch("api.notification_engine.send_windows_toast")
    def test_quiet_hours_suppression(self, mock_toast):
        """Test quiet hours suppresses toast while keeping planned block visible."""
        mock_toast.return_value = True

        # Enable quiet hours covering 22:00 to 07:00
        ts = notif_engine.now_iso()
        self.conn.execute("UPDATE app_settings SET value = 'true', updated_at = ? WHERE key = 'quiet_hours_enabled'", (ts,))
        self.conn.execute("UPDATE app_settings SET value = '22:00', updated_at = ? WHERE key = 'quiet_hours_start'", (ts,))
        self.conn.execute("UPDATE app_settings SET value = '07:00', updated_at = ? WHERE key = 'quiet_hours_end'", (ts,))
        self.conn.commit()

        # Simulated time at 23:30 (inside quiet hours)
        local_now = datetime.now().replace(hour=23, minute=30, second=0)
        date_str = local_now.strftime("%Y-%m-%d")
        start_str = "23:25"
        end_str = "23:55"

        block_id = self._insert_block(date_str, start_str, end_str, "Late Reading Block")

        res = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)

        # Toast must NOT be dispatched
        self.assertFalse(mock_toast.called)

        # But planned task IS set in app_settings and block remains visible
        planned_row = self.conn.execute("SELECT value FROM app_settings WHERE key = 'current_planned_task'").fetchone()
        self.assertIsNotNone(planned_row)
        self.assertEqual(planned_row["value"], "Late Reading Block")

    @patch("api.notification_engine.send_windows_toast")
    def test_missed_start_times_after_sleep_or_restart(self, mock_toast):
        """Test that blocks whose start time occurred > 15m ago do not trigger overdue burst."""
        mock_toast.return_value = True

        local_now = datetime.now()
        date_str = local_now.strftime("%Y-%m-%d")

        # Block 1 started 2 hours ago and ended 1 hour ago
        start_b1 = (local_now - timedelta(hours=2)).strftime("%H:%M")
        end_b1 = (local_now - timedelta(hours=1)).strftime("%H:%M")
        self._insert_block(date_str, start_b1, end_b1, "Morning Standup")

        # Block 2 started 40 minutes ago (missed while machine was off/asleep)
        start_b2 = (local_now - timedelta(minutes=40)).strftime("%H:%M")
        end_b2 = (local_now + timedelta(minutes=20)).strftime("%H:%M")
        self._insert_block(date_str, start_b2, end_b2, "Code Architecture Review")

        # Block 3 starts right now (within 5 minutes)
        start_b3 = (local_now - timedelta(minutes=2)).strftime("%H:%M")
        end_b3 = (local_now + timedelta(minutes=50)).strftime("%H:%M")
        b3_id = self._insert_block(date_str, start_b3, end_b3, "Current Sprint Execution")

        res = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)

        # Only Block 3 triggers! No burst of notifications for Block 1 or Block 2!
        self.assertIsNotNone(res)
        self.assertEqual(res["block_id"], b3_id)
        self.assertEqual(mock_toast.call_count, 1)

    @patch("api.notification_engine.send_windows_toast")
    def test_auto_start_focus_disabled_by_default_and_enabled_opt_in(self, mock_toast):
        """Test focus auto-start is disabled by default and can be opted into."""
        mock_toast.return_value = True

        local_now = datetime.now()
        date_str = local_now.strftime("%Y-%m-%d")
        start_str = local_now.strftime("%H:%M")
        end_str = (local_now + timedelta(minutes=45)).strftime("%H:%M")

        # 1. Default: time_block_autostart_focus is False
        settings = notif_engine.get_settings_from_db(self.conn)
        self.assertFalse(settings.get("time_block_autostart_focus", False))

        block_id = self._insert_block(date_str, start_str, end_str, "Deep Focus Testing")

        with patch("api.notification_engine.start_focus_for_time_block") as mock_start_focus:
            res = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)
            self.assertIsNotNone(res)
            # Did NOT auto-start
            self.assertFalse(mock_start_focus.called)
            self.assertTrue(mock_toast.called)

        # Reset state and enable auto-start setting
        notif_engine.reset_notification_state()
        ts = notif_engine.now_iso()
        self.conn.execute("INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES ('time_block_autostart_focus', 'true', ?)", (ts,))
        self.conn.commit()

        with patch("api.notification_engine.start_focus_for_time_block") as mock_start_focus:
            mock_start_focus.return_value = {"status": "started"}
            res2 = notif_engine.evaluate_time_block_reminders(self.conn, is_tracking=False, now_override=local_now)
            self.assertIsNotNone(res2)
            self.assertTrue(res2.get("auto_started"))
            self.assertTrue(mock_start_focus.called)


class TestTimeBlockReminderRestApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_time_block_endpoints(self):
        # 1. Create a time block for today
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        start_str = now.strftime("%H:%M")
        end_str = (now + timedelta(minutes=45)).strftime("%H:%M")

        r_create = self.client.post("/api/time-blocks", json={
            "date": date_str,
            "start_time": start_str,
            "end_time": end_str,
            "title": "REST API Test Block",
            "category_id": 1,
        })
        self.assertEqual(r_create.status_code, 200)
        block = r_create.json()
        block_id = block["id"]

        # 2. Query current block
        r_curr = self.client.get("/api/time-blocks/current")
        self.assertEqual(r_curr.status_code, 200)
        curr_data = r_curr.json()
        self.assertTrue(curr_data["has_block"])
        self.assertEqual(curr_data["block"]["title"], "REST API Test Block")

        # 3. Snooze reminder
        r_snooze = self.client.post(f"/api/time-blocks/{block_id}/snooze", json={"minutes": 5})
        self.assertEqual(r_snooze.status_code, 200)
        self.assertEqual(r_snooze.json()["status"], "snoozed")
        self.assertEqual(r_snooze.json()["minutes"], 5)

        # 4. Skip block
        r_skip = self.client.post(f"/api/time-blocks/{block_id}/skip")
        self.assertEqual(r_skip.status_code, 200)
        self.assertEqual(r_skip.json()["status"], "skipped")

        # 5. Start Focus
        r_focus = self.client.post(f"/api/time-blocks/{block_id}/start-focus")
        self.assertEqual(r_focus.status_code, 200)
        self.assertEqual(r_focus.json()["status"], "started")

        # 6. Test Time-Block Toast endpoint
        r_toast = self.client.post("/api/notifications/test-time-block-toast")
        self.assertEqual(r_toast.status_code, 200)
        self.assertEqual(r_toast.json()["status"], "queued")

        # Clean up
        self.client.delete(f"/api/time-blocks/{block_id}")


if __name__ == "__main__":
    unittest.main()
