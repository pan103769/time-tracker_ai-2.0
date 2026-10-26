"""
test_windows_notifier.py — Unit tests for Windows Toast Notification system:
- ToastGeneric XML schema compliance (scenario, activationType on action tags only, logo override)
- App identity registration (AUMID, Start Menu shortcut targeting pythonw.exe, registry ShowBanner=1)
- Diagnostics inspection & state tracking
- Quiet hours evaluation (including overnight cross-midnight windows)
- API endpoint integration (/api/notifications/diagnostics, /api/notifications/test-desktop-toast)
"""

import os
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, time as dtime
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.server import app
import api.windows_notifier as win_notifier


class TestWindowsNotifier(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_build_toast_xml_schema_validity(self):
        """Test that build_toast_xml produces well-formed, schema-compliant XML."""
        actions = [
            {"content": "Start Focus", "arguments": "http://localhost:5173/?action=start", "icon": "btn_play.png"},
            {"content": "Snooze 5 min", "arguments": "http://localhost:5173/?action=snooze&min=5"},
        ]
        xml_str = win_notifier.build_toast_xml(
            title="Focus Session — Deep Work",
            message="Your planned time block is starting now.",
            timestamp_str="10:30 AM",
            attribution="Time Tracker AI",
            launch_url="http://localhost:5173/?action=open",
            actions=actions,
            sound_mode="default",
            scenario="reminder",
        )

        # 1. Must parse cleanly as XML
        root = ET.fromstring(xml_str)
        self.assertEqual(root.tag, "toast")

        # 2. Root toast attributes
        self.assertEqual(root.attrib.get("scenario"), "reminder")
        self.assertEqual(root.attrib.get("launch"), "http://localhost:5173/?action=open")
        # Critical schema rule: activationType must NOT be on root <toast> tag
        self.assertNotIn("activationType", root.attrib)

        # 3. Visual & Binding
        visual = root.find("visual")
        self.assertIsNotNone(visual)
        binding = visual.find("binding")
        self.assertIsNotNone(binding)
        self.assertEqual(binding.attrib.get("template"), "ToastGeneric")

        # 4. Text tags
        texts = [t.text for t in binding.findall("text")]
        self.assertIn("Focus Session — Deep Work", texts)
        self.assertIn("Your planned time block is starting now.", texts)
        self.assertIn("10:30 AM · Time Tracker AI", texts)

        # 5. AppLogoOverride
        images = binding.findall("image")
        self.assertTrue(len(images) >= 1)
        self.assertEqual(images[0].attrib.get("placement"), "appLogoOverride")
        self.assertEqual(images[0].attrib.get("hint-crop"), "circle")

        # 6. Action tags
        actions_tag = root.find("actions")
        self.assertIsNotNone(actions_tag)
        action_elements = actions_tag.findall("action")
        self.assertEqual(len(action_elements), 2)

        self.assertEqual(action_elements[0].attrib.get("content"), "Start Focus")
        self.assertEqual(action_elements[0].attrib.get("arguments"), "http://localhost:5173/?action=start")
        self.assertEqual(action_elements[0].attrib.get("activationType"), "protocol")
        self.assertTrue(action_elements[0].attrib.get("imageUri", "").endswith("btn_play.png"))

        self.assertEqual(action_elements[1].attrib.get("content"), "Snooze 5 min")
        self.assertEqual(action_elements[1].attrib.get("arguments"), "http://localhost:5173/?action=snooze&min=5")
        self.assertEqual(action_elements[1].attrib.get("activationType"), "protocol")

    def test_build_toast_xml_escaping(self):
        """Test special character XML escaping (amps, quotes, brackets)."""
        xml_str = win_notifier.build_toast_xml(
            title="Design & <Research> \"Testing\"",
            message="Time & Task > 50% & 'quotes'",
            scenario="reminder",
        )
        root = ET.fromstring(xml_str)
        binding = root.find("visual").find("binding")
        texts = [t.text for t in binding.findall("text")]
        self.assertEqual(texts[0], "Design & <Research> \"Testing\"")
        self.assertEqual(texts[1], "Time & Task > 50% & 'quotes'")

    def test_build_toast_xml_silent_sound(self):
        """Test silent audio attribute when sound_mode='silent'."""
        xml_str = win_notifier.build_toast_xml(
            title="Silent Alert",
            message="Quiet notification",
            sound_mode="silent",
        )
        root = ET.fromstring(xml_str)
        audio = root.find("audio")
        self.assertIsNotNone(audio)
        self.assertEqual(audio.attrib.get("silent"), "true")

    def test_is_in_quiet_hours(self):
        """Test daytime and overnight cross-midnight quiet hours calculation."""
        # 1. Disabled
        settings_off = {"quiet_hours_enabled": False, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"}
        self.assertFalse(win_notifier._is_in_quiet_hours(settings_off, now_time=dtime(23, 30)))

        # 2. Overnight window: 22:00 to 07:00
        settings_overnight = {"quiet_hours_enabled": True, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"}
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(22, 0)))
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(23, 45)))
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(0, 0)))
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(3, 15)))
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(6, 59)))
        self.assertFalse(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(7, 1)))
        self.assertFalse(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(12, 0)))
        self.assertFalse(win_notifier._is_in_quiet_hours(settings_overnight, now_time=dtime(21, 59)))

        # 3. Same-day window: 13:00 to 15:00
        settings_day = {"quiet_hours_enabled": True, "quiet_hours_start": "13:00", "quiet_hours_end": "15:00"}
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_day, now_time=dtime(13, 0)))
        self.assertTrue(win_notifier._is_in_quiet_hours(settings_day, now_time=dtime(14, 30)))
        self.assertFalse(win_notifier._is_in_quiet_hours(settings_day, now_time=dtime(12, 59)))
        self.assertFalse(win_notifier._is_in_quiet_hours(settings_day, now_time=dtime(15, 1)))

    def test_get_windows_notification_diagnostics_structure(self):
        """Test get_windows_notification_diagnostics returns all expected keys."""
        diag = win_notifier.get_windows_notification_diagnostics()
        self.assertIsInstance(diag, dict)
        expected_keys = [
            "platform",
            "is_windows",
            "notifications_enabled",
            "windows_toasts_enabled",
            "aumid",
            "aumid_registered",
            "show_banner_registry",
            "shortcut_installed",
            "shortcut_target",
            "notifier_setting",
            "user_notification_state",
            "action_center_count",
            "troubleshooting_hints",
            "total_dispatched",
            "total_failed",
        ]
        for k in expected_keys:
            self.assertIn(k, diag, f"Missing diagnostic key: {k}")

        self.assertEqual(diag["aumid"], win_notifier.AUMID)
        self.assertIsInstance(diag["troubleshooting_hints"], list)

    def test_dispatch_test_toast_tracks_state(self):
        """Test dispatch_test_toast updates diagnostics state correctly."""
        with patch.object(win_notifier, "_dispatch_powershell_toast") as mock_ps:
            mock_ps.return_value = {
                "success": True,
                "status": "submitted",
                "notifier_setting": "Enabled",
                "error": None,
            }
            res = win_notifier.dispatch_test_toast(
                title="Mock Test Toast",
                message="Testing delivery tracking",
                scenario="reminder",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "submitted")

            diag = win_notifier.get_windows_notification_diagnostics()
            self.assertIsNotNone(diag["last_attempt_time"])
            self.assertEqual(diag["last_submission_result"], "submitted")

    def test_api_diagnostics_endpoint(self):
        """Test GET /api/notifications/diagnostics endpoint."""
        response = self.client.get("/api/notifications/diagnostics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("aumid", data)
        self.assertEqual(data["aumid"], "TimeTrackerAI.App")
        self.assertIn("notifier_setting", data)
        self.assertIn("troubleshooting_hints", data)

    def test_api_test_desktop_toast_endpoint(self):
        """Test POST /api/notifications/test-desktop-toast endpoint."""
        with patch.object(win_notifier, "dispatch_test_toast") as mock_test:
            mock_test.return_value = {
                "success": True,
                "status": "submitted",
                "notifier_setting": "Enabled",
                "error": None,
            }
            response = self.client.post("/api/notifications/test-desktop-toast")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "submitted")
            self.assertTrue(data["result"]["success"])
            self.assertIn("diagnostics", data)


if __name__ == "__main__":
    unittest.main()
