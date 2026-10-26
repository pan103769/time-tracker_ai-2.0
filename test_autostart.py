"""
test_autostart.py — Unit tests for Windows startup auto-launch configuration in api/autostart.py.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

import api.autostart as autostart


class TestAutostart(unittest.TestCase):
    def test_get_autostart_command_quoted(self):
        """Autostart command must contain quoted executable and script paths."""
        cmd = autostart.get_autostart_command()
        self.assertTrue(cmd.startswith('"'))
        self.assertIn("main.py", cmd)

    def test_is_autostart_enabled_when_present(self):
        """Should return True when registry value is present."""
        mock_winreg = MagicMock()
        mock_winreg.QueryValueEx.return_value = ('"python.exe" "main.py"', 1)
        mock_winreg.OpenKey.return_value.__enter__.return_value = MagicMock()

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("sys.platform", "win32"):
            self.assertTrue(autostart.is_autostart_enabled())

    def test_is_autostart_enabled_when_missing(self):
        """Should return False when registry key or value is not found."""
        mock_winreg = MagicMock()
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError()
        mock_winreg.OpenKey.return_value.__enter__.return_value = MagicMock()

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("sys.platform", "win32"):
            self.assertFalse(autostart.is_autostart_enabled())

    def test_enable_autostart_success(self):
        """Should call SetValueEx with command string."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("sys.platform", "win32"):
            success, cmd = autostart.enable_autostart()
            self.assertTrue(success)
            mock_winreg.SetValueEx.assert_called_once()
            args = mock_winreg.SetValueEx.call_args[0]
            self.assertEqual(args[1], autostart.REG_VALUE_NAME)
            self.assertEqual(args[4], cmd)

    def test_disable_autostart_success(self):
        """Should call DeleteValue with registry value name."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("sys.platform", "win32"):
            success, msg = autostart.disable_autostart()
            self.assertTrue(success)
            mock_winreg.DeleteValue.assert_called_once_with(mock_key, autostart.REG_VALUE_NAME)

    def test_cli_status(self):
        with patch("api.autostart.is_autostart_enabled", return_value=True):
            code = autostart.main(["--status"])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

