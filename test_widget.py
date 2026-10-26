"""
test_widget.py — Unit tests for desktop widget helper methods, configuration, and timer formatting.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import widget


class TestDesktopWidgetHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass

    def test_config_save_and_load(self):
        with patch.object(widget, "CONFIG_FILE", self.tmp_path):
            cfg = {"x": 150, "y": 250, "compact": True, "opacity": 0.9}
            widget.save_config(cfg)

            loaded = widget.load_config()
            self.assertEqual(loaded["x"], 150)
            self.assertEqual(loaded["y"], 250)
            self.assertTrue(loaded["compact"])
            self.assertEqual(loaded["opacity"], 0.9)

    def test_format_helpers(self):
        # We can test widget methods via a dummy instance or direct helper logic
        class DummyWidget(widget.DesktopWidget):
            def __init__(self):
                pass

        w = DummyWidget()
        # Session timer formatting
        self.assertEqual(w._format_elapsed(0), "00m 00s")
        self.assertEqual(w._format_elapsed(75), "01m 15s")
        self.assertEqual(w._format_elapsed(3665), "1h 01m")

        # Today total duration formatting
        self.assertEqual(w._format_duration(45), "45s")
        self.assertEqual(w._format_duration(125), "2m 5s")
        self.assertEqual(w._format_duration(7300), "2h 1m")

        # Text truncators
        self.assertEqual(w._format_title("Short", 20), "Short")
        self.assertEqual(w._format_title("A very long title that exceeds the limit", 15), "A very long ...")


if __name__ == "__main__":
    unittest.main()

