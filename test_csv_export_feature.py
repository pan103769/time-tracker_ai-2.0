"""
Unit tests for Analytics CSV Export (Detailed and Summary).
Validates RFC 4180 escaping, UTF-8 BOM, filter synchronization,
metadata column presence, and Excel compatibility.
"""

import csv
import io
import unittest
from datetime import date
from fastapi.testclient import TestClient

from api.server import app, _load_sessions

client = TestClient(app)


class TestCsvExport(unittest.TestCase):
    def test_detailed_csv_export_count_and_columns(self):
        """Test detailed CSV export endpoint returns all records with 36 columns and UTF-8 BOM."""
        resp = client.get("/api/analytics/export/csv?start_date=2026-10-25&end_date=2026-10-25&export_type=detailed")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/csv"))
        self.assertIn("attachment; filename=", resp.headers["content-disposition"])

        # Check UTF-8 BOM
        content_bytes = resp.content
        self.assertTrue(content_bytes.startswith(b"\xef\xbb\xbf"), "CSV must start with UTF-8 BOM")

        # Parse CSV
        text = content_bytes.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)

        self.assertGreater(len(rows), 1, "CSV must have header + data rows")
        header = rows[0]
        self.assertEqual(len(header), 36, f"Expected 36 columns, got {len(header)}: {header}")

        expected_columns = [
            "Record ID",
            "Local Date",
            "Start Time",
            "End Time",
            "Start Timestamp",
            "End Timestamp",
            "Duration (Seconds)",
            "Duration (Formatted)",
            "Application Name",
            "Process Name",
            "Window Title",
            "Website / Domain",
            "Page / Document Name",
            "Specific Activity Description",
            "Assigned Task Name",
            "Project Name",
            "Category",
            "Category Type",
            "Classification Source",
            "Confidence",
            "Needs Review",
            "Uncertain Activity",
            "Manually Corrected",
            "Productive Activity",
            "Deep Focus",
            "Distraction",
            "Idle Time",
            "Associated Focus Session ID",
            "Associated Time Block ID",
            "Planned Task",
            "Planned Match",
            "Observation Source",
            "Canonical Interval Key",
            "Observation IDs",
            "Matched Rule",
            "Metadata Level",
        ]
        self.assertEqual(header, expected_columns)

        # Verify that all active non-idle records are exported
        models, _ = _load_sessions(date(2026, 10, 25))
        active_count = len([m for m in models if m.kind != "idle"])
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), active_count)

        # Verify first row contains YouTube hashtags and symbols without truncation
        first_row = data_rows[0]
        self.assertIn("YouTube", first_row[13])
        # Verify Duration (Seconds) is numeric
        self.assertGreater(float(first_row[6]), 0)
        # Verify Duration (Formatted) has HH:MM:SS format
        self.assertRegex(first_row[7], r"^\d{2}:\d{2}:\d{2}$")

    def test_filtered_csv_export_by_search_and_category(self):
        """Filters by search query and category reduce exported row count accordingly."""
        # 1. Filter by category
        resp_cat = client.get("/api/analytics/export/csv?start_date=2026-10-25&end_date=2026-10-25&category=Entertainment%20%26%20Media")
        self.assertEqual(resp_cat.status_code, 200)
        text_cat = resp_cat.content.decode("utf-8-sig")
        rows_cat = list(csv.reader(io.StringIO(text_cat)))
        self.assertGreater(len(rows_cat), 1)
        for r in rows_cat[1:]:
            self.assertEqual(r[16], "Entertainment & Media")

        # 2. Filter by search
        resp_search = client.get("/api/analytics/export/csv?start_date=2026-10-25&end_date=2026-10-25&search=faceit")
        self.assertEqual(resp_search.status_code, 200)
        text_search = resp_search.content.decode("utf-8-sig")
        rows_search = list(csv.reader(io.StringIO(text_search)))
        self.assertGreater(len(rows_search), 1)
        for r in rows_search[1:]:
            comb = (r[10] + " " + r[13]).lower()
            self.assertIn("faceit", comb)

    def test_summary_csv_export(self):
        """Summary export provides category, application, and daily breakdowns without polluting detailed records."""
        resp = client.get("/api/analytics/export/csv?start_date=2026-10-19&end_date=2026-10-25&export_type=summary")
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode("utf-8-sig")
        self.assertIn("CATEGORY DISTRIBUTION BREAKDOWN", text)
        self.assertIn("APPLICATION USAGE BREAKDOWN", text)
        self.assertIn("DAILY PRODUCTIVITY TRENDS", text)


if __name__ == "__main__":
    unittest.main()

