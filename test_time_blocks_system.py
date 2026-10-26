import sqlite3
import unittest
from datetime import datetime, date, timedelta
from fastapi.testclient import TestClient

import api.goals as goals_engine
from api.server import app


class TestTimeBlocksSystem(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Create minimal required schema
        self.conn.executescript(
            """
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE time_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                title TEXT NOT NULL,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                metric TEXT NOT NULL,
                target_seconds INTEGER NOT NULL,
                is_inversion INTEGER NOT NULL DEFAULT 0,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                period TEXT NOT NULL DEFAULT 'daily',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            INSERT INTO categories (name, color, type, created_at)
            VALUES ('Coding', '#8065FF', 'focus', '2026-10-25T00:00:00');
            """
        )
        self.cat_id = self.conn.execute("SELECT id FROM categories WHERE name = 'Coding'").fetchone()["id"]

    def tearDown(self):
        self.conn.close()

    def test_normalize_time_strings(self):
        # Test ISO string handling
        iso_str = "2026-10-25T08:40:00"
        self.assertEqual(goals_engine._normalize_time_str(iso_str), "08:40")

        # Test seconds handling
        sec_str = "09:30:15"
        self.assertEqual(goals_engine._normalize_time_str(sec_str), "09:30")

        # Test standard HH:MM
        clean_str = "14:15"
        self.assertEqual(goals_engine._normalize_time_str(clean_str), "14:15")

        # Test time range formatting
        range_str = goals_engine._format_time_range("09:00", "09:45")
        self.assertEqual(range_str, "9:00 AM - 9:45 AM")

        cross_meridiem = goals_engine._format_time_range("11:30", "13:00")
        self.assertEqual(cross_meridiem, "11:30 AM - 1:00 PM")

    def test_create_time_block_normalizes(self):
        # Create block with ISO start time
        b = goals_engine.create_time_block(
            self.conn,
            block_date="2026-10-25",
            start_time="2026-10-25T09:00:00",
            end_time="2026-10-25T10:30:00",
            title="Deep Work Plan",
            category_id=self.cat_id,
        )
        self.assertEqual(b["start_time"], "09:00")
        self.assertEqual(b["end_time"], "10:30")
        self.assertEqual(b["title"], "Deep Work Plan")

    def test_overlap_detection(self):
        # Block 1: 09:00 to 10:00
        goals_engine.create_time_block(
            self.conn,
            block_date="2026-10-25",
            start_time="09:00",
            end_time="10:00",
            title="Block 1",
            category_id=self.cat_id,
        )

        # Overlapping: 09:30 to 10:30
        overlaps = goals_engine.check_time_block_overlaps(
            self.conn,
            block_date="2026-10-25",
            start_time="09:30",
            end_time="10:30",
        )
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["title"], "Block 1")

        # Non-overlapping: 10:00 to 11:00 (adjacent edges do not conflict)
        no_overlaps = goals_engine.check_time_block_overlaps(
            self.conn,
            block_date="2026-10-25",
            start_time="10:00",
            end_time="11:00",
        )
        self.assertEqual(len(no_overlaps), 0)

    def test_update_and_reschedule(self):
        b = goals_engine.create_time_block(
            self.conn,
            block_date="2026-10-25",
            start_time="09:00",
            end_time="10:00",
            title="Initial Title",
        )

        updated = goals_engine.update_time_block(
            self.conn,
            block_id=b["id"],
            block_date="2026-10-26",
            start_time="14:00",
            end_time="15:30",
            title="Rescheduled Title",
            category_id=self.cat_id,
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["date"], "2026-10-26")
        self.assertEqual(updated["start_time"], "14:00")
        self.assertEqual(updated["end_time"], "15:30")
        self.assertEqual(updated["title"], "Rescheduled Title")
        self.assertEqual(updated["category_id"], self.cat_id)

    def test_duplicate_time_block(self):
        b = goals_engine.create_time_block(
            self.conn,
            block_date="2026-10-25",
            start_time="09:00",
            end_time="10:00",
            title="Sprint Planning",
            category_id=self.cat_id,
        )

        # Duplicate to next day
        dup = goals_engine.duplicate_time_block(
            self.conn,
            block_id=b["id"],
            target_date="2026-10-26",
            time_offset_minutes=0,
        )
        self.assertIsNotNone(dup)
        self.assertNotEqual(dup["id"], b["id"])
        self.assertEqual(dup["date"], "2026-10-26")
        self.assertEqual(dup["title"], "Sprint Planning")

        # Duplicate with offset (e.g. +60 minutes)
        dup_offset = goals_engine.duplicate_time_block(
            self.conn,
            block_id=b["id"],
            target_date="2026-10-25",
            time_offset_minutes=60,
        )
        self.assertEqual(dup_offset["start_time"], "10:00")
        self.assertEqual(dup_offset["end_time"], "11:00")

    def test_daily_summary_canonical_adherence(self):
        # Create block from 09:00 to 10:00 (3600 seconds)
        goals_engine.create_time_block(
            self.conn,
            block_date="2026-10-25",
            start_time="09:00",
            end_time="10:00",
            title="Dev Block",
            category_id=self.cat_id,
        )

        # Observations: 30 minutes of focus in that block window
        raw_sessions = [
            {
                "start": "2026-10-25T09:00:00",
                "end": "2026-10-25T09:30:00",
                "kind": "active",
                "app": "Code.exe",
                "category_id": self.cat_id,
                "category_name": "Coding",
                "category_type": "focus",
            },
            {
                "start": "2026-10-25T09:30:00",
                "end": "2026-10-25T09:40:00",
                "kind": "active",
                "app": "chrome.exe",
                "category_type": "distraction",
                "category_name": "Entertainment",
            },
        ]

        summary = goals_engine.calculate_time_blocks_daily_summary(
            self.conn, "2026-10-25", raw_sessions
        )
        self.assertEqual(summary["total_blocks"], 1)
        self.assertEqual(summary["planned_seconds"], 3600)
        self.assertEqual(summary["focus_seconds"], 1800)
        self.assertEqual(summary["adherence_pct"], 50.0)
        self.assertEqual(summary["distraction_seconds"], 600)
        self.assertIn("10m", summary["distraction_label"])


class TestTimeBlocksFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_endpoints_crud(self):
        test_date = "2026-10-25"
        # 1. Create block
        create_resp = self.client.post(
            "/api/time-blocks",
            json={
                "date": test_date,
                "start_time": "14:15",
                "end_time": "15:00",
                "title": "API Test Focus Block",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        data = create_resp.json()
        block_id = data["id"]
        self.assertEqual(data["title"], "API Test Focus Block")
        self.assertEqual(data["start_time"], "14:15")

        # 2. Check overlap
        overlap_resp = self.client.post(
            "/api/time-blocks/check-overlap",
            json={
                "date": test_date,
                "start_time": "14:30",
                "end_time": "15:30",
            },
        )
        self.assertEqual(overlap_resp.status_code, 200)
        overlap_data = overlap_resp.json()
        self.assertTrue(overlap_data["has_overlap"])

        # 3. Update block
        update_resp = self.client.put(
            f"/api/time-blocks/{block_id}",
            json={
                "title": "Updated API Test Focus Block",
                "start_time": "14:20",
                "end_time": "15:05",
            },
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["title"], "Updated API Test Focus Block")

        # 4. Duplicate block
        dup_resp = self.client.post(
            f"/api/time-blocks/{block_id}/duplicate",
            json={
                "target_date": "2026-10-26",
                "time_offset_minutes": 0,
            },
        )
        self.assertEqual(dup_resp.status_code, 200)
        dup_id = dup_resp.json()["id"]

        # 5. Get summary
        summary_resp = self.client.get(f"/api/time-blocks/summary/{test_date}")
        self.assertEqual(summary_resp.status_code, 200)
        summary = summary_resp.json()
        self.assertIn("planned_seconds", summary)
        self.assertIn("adherence_pct", summary)

        # Cleanup test blocks
        self.client.delete(f"/api/time-blocks/{block_id}")
        self.client.delete(f"/api/time-blocks/{dup_id}")


if __name__ == "__main__":
    unittest.main()
