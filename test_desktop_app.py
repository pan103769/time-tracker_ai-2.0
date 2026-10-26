"""
test_desktop_app.py — Unit and integration tests for desktop_app.py wrapper.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import desktop_app


class TestDesktopApp(unittest.TestCase):
    def test_backend_health_check(self):
        """Test health check against running local server."""
        healthy = desktop_app.is_backend_healthy(port=8000)
        self.assertTrue(healthy, "Backend on port 8000 should be healthy")

    def test_environment_setup_dev(self):
        """In development mode, TIME_TRACKER_DB_PATH is not forced to APPDATA."""
        with patch.object(sys, "frozen", False, create=True):
            if "TIME_TRACKER_DB_PATH" in os.environ:
                del os.environ["TIME_TRACKER_DB_PATH"]
            desktop_app.setup_environment()
            self.assertNotIn("TIME_TRACKER_DB_PATH", os.environ)

    def test_environment_setup_frozen(self):
        """In frozen/packaged mode, TIME_TRACKER_DB_PATH is configured to user APPDATA."""
        with patch.object(sys, "frozen", True, create=True):
            desktop_app.setup_environment()
            self.assertIn("TIME_TRACKER_DB_PATH", os.environ)
            self.assertIn("TimeTrackerAI", os.environ["TIME_TRACKER_DB_PATH"])

    def test_mutex_acquisition(self):
        """Test single instance mutex creation and collision detection."""
        if sys.platform != "win32":
            self.skipTest("Windows-only test")

        test_mutex = f"Local\\TimeTrackerAI_Test_Mutex_{os.getpid()}"
        m1 = desktop_app.acquire_single_instance_mutex(test_mutex)
        self.assertIsNotNone(m1, "First instance should acquire mutex")

        m2 = desktop_app.acquire_single_instance_mutex(test_mutex)
        self.assertIsNone(m2, "Second instance should be rejected by mutex")

        # Cleanup
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex(m1)
        kernel32.CloseHandle(m1)

    def test_parse_protocol_uri_interactive(self):
        """Test parsing interactive navigation URI from toast notifications."""
        uri = "timetracker://navigate?action=open_planner&block_id=42&date=2026-10-26"
        action, params, is_silent = desktop_app.parse_protocol_uri(uri)
        self.assertEqual(action, "open_planner")
        self.assertEqual(params.get("block_id"), "42")
        self.assertEqual(params.get("date"), "2026-10-26")
        self.assertFalse(is_silent, "open_planner should be interactive")

    def test_parse_protocol_uri_silent(self):
        """Test parsing silent action URIs (snooze, skip)."""
        uri = "timetracker://action?name=snooze_block&block_id=10&minutes=5"
        action, params, is_silent = desktop_app.parse_protocol_uri(uri)
        self.assertEqual(action, "snooze_block")
        self.assertEqual(params.get("block_id"), "10")
        self.assertEqual(params.get("minutes"), "5")
        self.assertTrue(is_silent, "snooze_block should be marked silent")

        uri_skip = "timetracker://action?name=skip_block&block_id=15"
        action, params, is_silent = desktop_app.parse_protocol_uri(uri_skip)
        self.assertEqual(action, "skip_block")
        self.assertTrue(is_silent, "skip_block should be marked silent")

    def test_desktop_activate_and_pending_endpoints(self):
        """Test POST /api/desktop/activate queues interactive actions and GET /api/desktop/pending-action pops them."""
        from fastapi.testclient import TestClient
        from api.server import app

        client = TestClient(app)
        res = client.post("/api/desktop/activate", json={
            "action": "open_planner",
            "params": {"block_id": 99}
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("queued"))

        # Retrieve pending action
        res_pending = client.get("/api/desktop/pending-action")
        self.assertEqual(res_pending.status_code, 200)
        item = res_pending.json()
        self.assertIsNotNone(item)
        self.assertEqual(item.get("action"), "open_planner")
        self.assertEqual(item.get("params", {}).get("block_id"), 99)

    def test_desktop_window_control_endpoints(self):
        """Test desktop window control endpoints (state, minimize, restore, toggle, close)."""
        from fastapi.testclient import TestClient
        from api.server import app

        client = TestClient(app)
        res = client.get("/api/desktop/window/state")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("is_desktop", data)
        self.assertIn("is_maximized", data)
        self.assertIn("is_minimized", data)

        # Minimize, restore, toggle, close should return 200 OK without crashing even if headless
        for endpoint in ["minimize", "maximize", "restore", "toggle-maximize", "close"]:
            resp = client.post(f"/api/desktop/window/{endpoint}")
            self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()

