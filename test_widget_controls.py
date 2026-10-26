"""
test_widget_controls.py — Comprehensive test for widget controls, vector drawing,
mode transitions, custom dark menu, and activity editing dialog.
"""

import math
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import widget


class TestWidgetControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        # Prevent background threads during tests
        with patch.object(widget.DesktopWidget, "setup_window"), \
             patch("threading.Thread"):
            self.w = widget.DesktopWidget(self.root)
            self.w.running = False

    def test_expanded_control_hit_detection(self):
        self.w.is_compact = False
        self.assertEqual(self.w._detect_control(420, 70), "play")
        self.assertEqual(self.w._detect_control(422, 24), "dashboard")
        self.assertEqual(self.w._detect_control(448, 24), "collapse")
        self.assertEqual(self.w._detect_control(472, 24), "gear")
        self.assertEqual(self.w._detect_control(496, 24), "menu")
        self.assertEqual(self.w._detect_control(200, 24), "edit_task")

    def test_compact_control_hit_detection(self):
        self.w.is_compact = True
        self.assertEqual(self.w._detect_control(390, 34), "play")
        self.assertEqual(self.w._detect_control(430, 34), "expand")
        self.assertEqual(self.w._detect_control(462, 34), "gear")
        self.assertEqual(self.w._detect_control(494, 34), "menu")
        self.assertEqual(self.w._detect_control(250, 34), "edit_task")

    def test_toggle_compact_mode_transition(self):
        self.w.is_compact = False
        with patch.object(widget, "save_config"):
            self.w.toggle_compact_mode()
            self.assertTrue(self.w.is_compact)
            self.assertEqual(self.w.current_height, widget.WIDGET_HEIGHT_COMPACT)

            self.w.toggle_compact_mode()
            self.assertFalse(self.w.is_compact)
            self.assertEqual(self.w.current_height, widget.WIDGET_HEIGHT_EXPANDED)

    def test_vector_drawing_primitives(self):
        canvas = tk.Canvas(self.root, width=200, height=200)
        widget.draw_vector_dashboard(canvas, 50, 50, "#8065FF")
        widget.draw_vector_collapse(canvas, 70, 50, "#FFFFFF")
        widget.draw_vector_expand(canvas, 90, 50, "#8065FF")
        widget.draw_vector_gear(canvas, 110, 50, "#8994A8")
        widget.draw_vector_ellipsis(canvas, 130, 50, "#FFFFFF")
        widget.draw_vector_pencil_pill(canvas, 150, 50, False)
        widget.draw_pine_tree(canvas, 170, 100, 60, "#080E1B")
        self.assertGreater(len(canvas.find_all()), 10)

    def test_custom_dark_context_menu(self):
        items = [
            ("✎", "Edit Current Activity...", lambda: None),
            ("🗖", "Open Web Dashboard", lambda: None),
            ("", "---", None),
            ("✕", "Close", lambda: None),
        ]
        menu = widget.CustomDarkContextMenu(self.w, items, 100, 100)
        self.assertIsNotNone(menu.top)
        menu.close()

    def test_widget_settings_dialog(self):
        with patch.object(widget, "save_config"):
            dlg = widget.WidgetSettingsDialog(self.w)
            self.assertIsNotNone(dlg.top)
            dlg._set_op(0.85)
            self.assertAlmostEqual(self.w.cfg["opacity"], 0.85)
            dlg.close()

    def test_edit_activity_dialog(self):
        with patch("threading.Thread"):
            dlg = widget.EditActivityDialog(self.w)
            self.assertIsNotNone(dlg.top)
            dlg.entry_task.delete(0, tk.END)
            dlg.entry_task.insert(0, "Deep Architecture Coding")
            dlg._select_cat(1)
            dlg._save()
            self.assertEqual(self.w.active_task_name, "Deep Architecture Coding")
            self.assertEqual(self.w.current_category_id, 1)


if __name__ == "__main__":
    unittest.main()

