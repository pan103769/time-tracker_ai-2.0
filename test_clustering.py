"""
test_clustering.py - Comprehensive Unit Tests for Timeline Clustering and Debounce Engine.

Covers all 13 required test cases specified in Master Implementation Prompt:
1. A short switch followed by a return to the dominant app.
2. A switch shorter than 60 seconds.
3. A switch lasting exactly 60 seconds.
4. A switch longer than 60 seconds.
5. Repeated switching among multiple apps.
6. Apps classified within the same category.
7. A genuine switch to a distraction.
8. Idle periods and long gaps.
9. Missing application metadata.
10. Clusters crossing a time-window boundary.
11. Zooming into and out of an identical time period.
12. Preservation of original observations and exact durations.
13. Reconciliation of overview and detailed timeline totals.
"""

import unittest
from datetime import datetime, timedelta, timezone

from api.clustering import (
    TimelineCluster,
    cluster_timeline_sessions,
    calculate_app_breakdown,
)


def make_iso(base_hour: int, minute: int, second: int = 0) -> str:
    dt = datetime(2026, 10, 23, base_hour, minute, second, tzinfo=timezone.utc)
    return dt.isoformat()


class TestTimelineClustering(unittest.TestCase):
    def test_01_short_switch_and_return_to_dominant_app(self):
        """Case 1: VS Code (300s) -> Chrome (20s) -> VS Code (180s) -> absorbed into VS Code with 1 interruption."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(10, 0), "end": make_iso(10, 5), "duration_seconds": 300},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(10, 5), "end": make_iso(10, 5, 20), "duration_seconds": 20},
            {"app": "Code.exe", "kind": "active", "start": make_iso(10, 5, 20), "end": make_iso(10, 8, 20), "duration_seconds": 180},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(c.cluster_type, "absorbed")
        self.assertEqual(c.dominant_app, "Code.exe")
        self.assertEqual(c.duration_seconds, 500)
        self.assertEqual(c.interruption_count, 1)
        self.assertEqual(len(c.child_segments), 3)
        self.assertTrue(c.child_segments[1].is_interruption)
        self.assertEqual(c.child_segments[1].app, "chrome.exe")

    def test_02_switch_shorter_than_60_seconds(self):
        """Case 2: 45s switch is strictly < 60s, so it is absorbed."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(11, 0), "end": make_iso(11, 10), "duration_seconds": 600},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(11, 10), "end": make_iso(11, 10, 45), "duration_seconds": 45},
            {"app": "Code.exe", "kind": "active", "start": make_iso(11, 10, 45), "end": make_iso(11, 15), "duration_seconds": 255},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].cluster_type, "absorbed")
        self.assertEqual(clusters[0].duration_seconds, 900)

    def test_03_switch_lasting_exactly_60_seconds_not_absorbed(self):
        """Case 3: Switch lasting exactly 60s must NOT be absorbed by debounce rule."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(12, 0), "end": make_iso(12, 5), "duration_seconds": 300},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(12, 5), "end": make_iso(12, 6), "duration_seconds": 60},
            {"app": "Code.exe", "kind": "active", "start": make_iso(12, 6), "end": make_iso(12, 10), "duration_seconds": 240},
        ]
        clusters = cluster_timeline_sessions(sessions)
        # Should remain distinct or not absorbed by the < 60s rule
        self.assertNotEqual(len(clusters), 1)
        types = [c.cluster_type for c in clusters]
        self.assertNotIn("absorbed", types)

    def test_04_switch_longer_than_60_seconds_not_absorbed(self):
        """Case 4: Switch of 120s must NOT be absorbed into the previous app."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(13, 0), "end": make_iso(13, 5), "duration_seconds": 300},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(13, 5), "end": make_iso(13, 7), "duration_seconds": 120},
            {"app": "Code.exe", "kind": "active", "start": make_iso(13, 7), "end": make_iso(13, 12), "duration_seconds": 300},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertGreater(len(clusters), 1)
        types = [c.cluster_type for c in clusters]
        self.assertNotIn("absorbed", types)

    def test_05_repeated_switching_among_multiple_apps(self):
        """Case 5: Repeated rapid switches across VS Code, Slack, Chrome, Terminal -> Mixed Activity."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(14, 0), "end": make_iso(14, 1), "duration_seconds": 60},
            {"app": "Slack.exe", "kind": "active", "start": make_iso(14, 1), "end": make_iso(14, 2), "duration_seconds": 60},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(14, 2), "end": make_iso(14, 3), "duration_seconds": 60},
            {"app": "cmd.exe", "kind": "active", "start": make_iso(14, 3), "end": make_iso(14, 4), "duration_seconds": 60},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(c.cluster_type, "mixed")
        self.assertIn("Mixed Activity", c.label)
        self.assertEqual(c.duration_seconds, 240)
        self.assertEqual(len(c.child_segments), 4)

    def test_06_apps_classified_within_same_category(self):
        """Case 6: Segments preserve their category metadata cleanly."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "category_name": "Development", "category_type": "focus", "start": make_iso(15, 0), "end": make_iso(15, 5), "duration_seconds": 300},
            {"app": "Terminal.exe", "kind": "active", "category_name": "Development", "category_type": "focus", "start": make_iso(15, 5), "end": make_iso(15, 10), "duration_seconds": 300},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(clusters[0].child_segments[0].category_name, "Development")
        self.assertEqual(clusters[1].child_segments[0].category_name, "Development")

    def test_07_genuine_switch_to_a_distraction(self):
        """Case 7: Genuine distraction of 15 minutes is not absorbed, stands out clearly."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "category_type": "focus", "start": make_iso(16, 0), "end": make_iso(16, 30), "duration_seconds": 1800},
            {"app": "YouTube", "kind": "active", "category_type": "distraction", "start": make_iso(16, 30), "end": make_iso(16, 45), "duration_seconds": 900},
            {"app": "Code.exe", "kind": "active", "category_type": "focus", "start": make_iso(16, 45), "end": make_iso(17, 15), "duration_seconds": 1800},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 3)
        self.assertEqual(clusters[1].dominant_app, "YouTube")
        self.assertEqual(clusters[1].category_type, "distraction")

    def test_08_idle_periods_and_long_gaps(self):
        """Case 8: Excursions do not bridge across idle sessions or gaps."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(17, 0), "end": make_iso(17, 10), "duration_seconds": 600},
            {"app": "Idle", "kind": "idle", "start": make_iso(17, 10), "end": make_iso(17, 10, 30), "duration_seconds": 30},
            {"app": "Code.exe", "kind": "active", "start": make_iso(17, 10, 30), "end": make_iso(17, 20), "duration_seconds": 570},
        ]
        clusters = cluster_timeline_sessions(sessions)
        # Idle block must be kept independent, not absorbed into Code.exe
        self.assertEqual(len(clusters), 3)
        self.assertTrue(clusters[1].is_idle)
        self.assertEqual(clusters[1].label, "Idle / Away")

    def test_09_missing_application_metadata(self):
        """Case 9: Sessions with empty or null app name fallback to 'Unknown' gracefully."""
        sessions = [
            {"app": None, "kind": "active", "start": make_iso(18, 0), "end": make_iso(18, 5), "duration_seconds": 300},
            {"app": "", "kind": "active", "start": make_iso(18, 5), "end": make_iso(18, 10), "duration_seconds": 300},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0].dominant_app, "Unknown")
        self.assertEqual(clusters[1].dominant_app, "Unknown")

    def test_10_clusters_crossing_time_window_boundary(self):
        """Case 10: Multi-session sequence crossing hour boundary clusters correctly."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(19, 58), "end": make_iso(20, 2), "duration_seconds": 240},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(20, 2), "end": make_iso(20, 2, 30), "duration_seconds": 30},
            {"app": "Code.exe", "kind": "active", "start": make_iso(20, 2, 30), "end": make_iso(20, 10), "duration_seconds": 450},
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].cluster_type, "absorbed")
        self.assertEqual(clusters[0].duration_seconds, 720)

    def test_11_zooming_in_and_out_of_identical_period(self):
        """Case 11: Clustering is deterministic; calling clustering twice on same sessions yields identical results."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(9, 0), "end": make_iso(9, 30), "duration_seconds": 1800},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(9, 30), "end": make_iso(9, 30, 25), "duration_seconds": 25},
            {"app": "Code.exe", "kind": "active", "start": make_iso(9, 30, 25), "end": make_iso(10, 0), "duration_seconds": 1775},
        ]
        c1 = cluster_timeline_sessions(sessions)
        c2 = cluster_timeline_sessions(sessions)
        self.assertEqual(len(c1), len(c2))
        self.assertEqual(c1[0].duration_seconds, c2[0].duration_seconds)
        self.assertEqual(c1[0].interruption_count, c2[0].interruption_count)

    def test_12_preservation_of_original_observations_and_exact_durations(self):
        """Case 12: Sum of child segment durations exactly equals cluster duration and input durations."""
        sessions = [
            {"app": "Code.exe", "kind": "active", "start": make_iso(8, 0), "end": make_iso(8, 10), "duration_seconds": 600},
            {"app": "Notion.exe", "kind": "active", "start": make_iso(8, 10), "end": make_iso(8, 10, 30), "duration_seconds": 30},
            {"app": "Code.exe", "kind": "active", "start": make_iso(8, 10, 30), "end": make_iso(8, 25), "duration_seconds": 870},
        ]
        input_total = sum(s["duration_seconds"] for s in sessions)
        clusters = cluster_timeline_sessions(sessions)
        cluster_total = sum(c.duration_seconds for c in clusters)
        child_total = sum(
            sum(seg.duration_seconds for seg in c.child_segments) for c in clusters
        )
        self.assertEqual(input_total, cluster_total)
        self.assertEqual(input_total, child_total)

    def test_13_reconciliation_of_overview_and_detailed_totals(self):
        """Case 13: Mixed and single clusters total matches raw sum."""
        sessions = [
            {"app": "Slack.exe", "kind": "active", "start": make_iso(7, 0), "end": make_iso(7, 1), "duration_seconds": 60},
            {"app": "chrome.exe", "kind": "active", "start": make_iso(7, 1), "end": make_iso(7, 2), "duration_seconds": 60},
            {"app": "Spotify.exe", "kind": "active", "start": make_iso(7, 2), "end": make_iso(7, 3), "duration_seconds": 60},
            {"app": "Code.exe", "kind": "active", "start": make_iso(7, 3), "end": make_iso(7, 33), "duration_seconds": 1800},
        ]
        raw_seconds = sum(s["duration_seconds"] for s in sessions)
        clusters = cluster_timeline_sessions(sessions)
        clustered_seconds = sum(c.duration_seconds for c in clusters)
        self.assertEqual(raw_seconds, clustered_seconds)

    def test_14_entertainment_streak_not_merged_into_coding(self):
        """Case 14: YouTube gaming shorts and entertainment videos do not merge into Coding & Debugging."""
        sessions = [
            {
                "app": "Code.exe",
                "title": "browser_tracker.py - time tracker ai 2 - Visual Studio Code",
                "kind": "active",
                "category_name": "Coding & Development",
                "category_type": "focus",
                "category_color": "#35D68A",
                "start": make_iso(19, 52),
                "end": make_iso(19, 53, 9),
                "duration_seconds": 69,
            },
            {
                "app": "chrome.exe",
                "title": "INDIA'S GOT LATENT S2 EP8 ft. MC Stan, Tanmay Bhat",
                "kind": "active",
                "category_name": "Entertainment & Media",
                "category_type": "distraction",
                "category_color": "#FA5275",
                "start": make_iso(19, 53, 9),
                "end": make_iso(19, 55, 48),
                "duration_seconds": 159,
            },
            {
                "app": "chrome.exe",
                "title": "YouTube - Google Chrome",
                "kind": "active",
                "category_name": "Entertainment & Media",
                "category_type": "distraction",
                "category_color": "#FA5275",
                "start": make_iso(19, 55, 48),
                "end": make_iso(19, 56, 21),
                "duration_seconds": 33,
            },
            {
                "app": "chrome.exe",
                "title": "Cyberpunk 2077 vs RTX 5060Ti – 1 FPS vs 60 FPS Performance Test!",
                "kind": "active",
                "category_name": "Entertainment & Media",
                "category_type": "distraction",
                "category_color": "#FA5275",
                "start": make_iso(19, 56, 21),
                "end": make_iso(19, 56, 47),
                "duration_seconds": 26,
            },
            {
                "app": "chrome.exe",
                "title": "A GIRL WAS ON MY TEAM… SO I DROPPED AN ACE 💀 #valorant #gaming #shorts",
                "kind": "active",
                "category_name": "Entertainment & Media",
                "category_type": "distraction",
                "category_color": "#FA5275",
                "start": make_iso(19, 56, 47),
                "end": make_iso(19, 57, 1),
                "duration_seconds": 14,
            },
        ]
        raw_dur = sum(s["duration_seconds"] for s in sessions)
        clusters = cluster_timeline_sessions(sessions)

        # Must split into separate coding and entertainment clusters
        self.assertEqual(len(clusters), 2)

        # Cluster 0 is coding
        c0 = clusters[0]
        self.assertIn(c0.dominant_app, ("Code.exe", "Code"))
        self.assertEqual(c0.dominant_category, "Coding & Development")
        self.assertEqual(c0.category_type, "focus")
        self.assertEqual(c0.duration_seconds, 69)

        # Cluster 1 is entertainment, NEVER Coding & Debugging
        c1 = clusters[1]
        self.assertEqual(c1.dominant_category, "Entertainment & Media")
        self.assertEqual(c1.category_type, "distraction")
        self.assertNotIn("Coding & Debugging", c1.label)
        self.assertIn("Entertainment", c1.label)
        self.assertEqual(c1.duration_seconds, 232)

        # Reconcile exact durations
        total_cluster_dur = sum(c.duration_seconds for c in clusters)
        self.assertEqual(raw_dur, total_cluster_dur)

    def test_15_coding_task_retains_ide_terminal_and_dev_documentation(self):
        """Case 15: VS Code, terminal test execution, and API docs for the same task coalesce cleanly."""
        sessions = [
            {
                "app": "Code.exe",
                "title": "server.py - time tracker ai 2 - Visual Studio Code",
                "kind": "active",
                "category_name": "Coding & Development",
                "category_type": "focus",
                "start": make_iso(10, 0),
                "end": make_iso(10, 2),
                "duration_seconds": 120,
            },
            {
                "app": "cmd.exe",
                "title": "pytest test_clustering.py",
                "kind": "active",
                "category_name": "Coding & Development",
                "category_type": "focus",
                "start": make_iso(10, 2),
                "end": make_iso(10, 2, 45),
                "duration_seconds": 45,
            },
            {
                "app": "chrome.exe",
                "title": "FastAPI Documentation - Endpoints",
                "kind": "active",
                "category_name": "Research & Learning",
                "category_type": "focus",
                "start": make_iso(10, 2, 45),
                "end": make_iso(10, 3, 35),
                "duration_seconds": 50,
            },
        ]
        clusters = cluster_timeline_sessions(sessions)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(c.dominant_category, "Coding & Development")
        self.assertEqual(c.category_type, "focus")
        self.assertIn("Coding & Debugging", c.label)
        self.assertEqual(c.duration_seconds, 215)



if __name__ == "__main__":
    unittest.main()

