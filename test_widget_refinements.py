"""
test_widget_refinements.py — Unit tests for the refined Focus Session Widget:
- Precise hitboxes for all interactive elements (edit pill, header buttons, play/pause, current block, progress bar, drag handle)
- Empty space clicks do not trigger edit or other buttons
- Drag threshold prevents accidental button clicks during window drag
- Mouse down + move outside + release cancels button click
- Slim, smoothly connected progress bar generator handles 0% to 100%
- Visual hierarchy and mode transitions
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk

import widget


class TestWidgetRefinements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.geometry(f"{widget.WIDGET_WIDTH}x{widget.WIDGET_HEIGHT_EXPANDED}+50+50")
        with patch.object(widget.DesktopWidget, "setup_window"), \
             patch("threading.Thread"):
            cls.w = widget.DesktopWidget(cls.root)
            cls.w.running = False

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.w.is_compact = False
        self.w.active_task_name = "Testing Widget Focus"
        self.w.daily_goal_pct = 43.0
        self.w.render_all()

    def test_edit_button_hitbox_is_exact_and_empty_space_is_not_captured(self):
        """Verify task edit button is strictly bounded and nearby empty space does NOT trigger edit."""
        self.w.is_compact = False
        self.w.render_all()

        ep_x1, ep_y1, ep_x2, ep_y2 = self.w.edit_pill_rect
        self.assertGreater(ep_x1, 0)
        self.assertGreater(ep_x2, ep_x1)

        # 1. Inside edit button / task text -> "edit_task"
        mid_x = (ep_x1 + ep_x2) // 2
        mid_y = (ep_y1 + ep_y2) // 2
        self.assertEqual(self.w._detect_control(mid_x, mid_y), "edit_task")

        # 2. Empty space to the right of edit pill (e.g. x = ep_x2 + 20) -> MUST be None!
        empty_x = min(400, ep_x2 + 25)
        self.assertIsNone(
            self.w._detect_control(empty_x, 22),
            f"Click at empty space ({empty_x}, 22) should NOT trigger any control"
        )

        # 3. Another empty space point at x = 360, y = 22 -> MUST be None!
        if ep_x2 < 340:
            self.assertIsNone(self.w._detect_control(360, 22))

    def test_header_buttons_exact_bounds_and_no_overlap(self):
        """Verify Dashboard, Collapse, Settings, Menu buttons have non-overlapping exact bounds."""
        self.w.is_compact = False

        # Dashboard cx = 424
        self.assertEqual(self.w._detect_control(424, 22), "dashboard")
        # Collapse cx = 448
        self.assertEqual(self.w._detect_control(448, 22), "collapse")
        # Settings cx = 472
        self.assertEqual(self.w._detect_control(472, 22), "gear")
        # Menu cx = 496
        self.assertEqual(self.w._detect_control(496, 22), "menu")

    def test_play_pause_and_menu_play_hitboxes(self):
        """Verify circular play/pause button and 3-dots next to it."""
        self.w.is_compact = False
        # Play center (420, 75)
        self.assertEqual(self.w._detect_control(420, 75), "play")
        self.assertEqual(self.w._detect_control(405, 75), "play")
        self.assertEqual(self.w._detect_control(435, 75), "play")

        # Three-dot next to play button (466, 75)
        self.assertEqual(self.w._detect_control(466, 75), "menu_play")

    def test_current_block_and_progress_bar_hitboxes(self):
        """Verify Current Block pill and Progress Bar hitboxes."""
        self.w.is_compact = False
        # Progress bar (x=200, y=115)
        self.assertEqual(self.w._detect_control(200, 115), "progress_bar")

        # Current block pill (x=400, y=164)
        self.assertEqual(self.w._detect_control(400, 164), "current_block")

        # Drag handle (x=26, y=75)
        self.assertEqual(self.w._detect_control(26, 75), "drag_handle")

    def test_click_vs_drag_behavior(self):
        """Verify button action executes on mouse-up if not dragged; drag cancels click."""
        event = MagicMock()
        event.x = 420
        event.y = 75
        event.x_root = 100
        event.y_root = 100

        # 1. Mouse down on play button
        self.w._on_mouse_down(event)
        self.assertEqual(self.w.mouse_pressed_control, "play")
        self.assertFalse(self.w.is_dragging)

        # 2. Small motion (2px) -> still not dragging
        event_move_small = MagicMock()
        event_move_small.x_root = 102
        event_move_small.y_root = 101
        self.w._on_mouse_drag(event_move_small)
        self.assertEqual(self.w.mouse_pressed_control, "play")
        self.assertFalse(self.w.is_dragging)

        # 3. Mouse up without dragging -> executes action!
        with patch.object(self.w, "toggle_tracking") as mock_toggle:
            self.w._on_mouse_up(event)
            self.assertTrue(mock_toggle.called)
            self.assertIsNone(self.w.mouse_pressed_control)

        # 4. Large motion (> 4px) -> switches to window drag and cancels button click!
        self.w._on_mouse_down(event)
        event_drag = MagicMock()
        event_drag.x_root = 130
        event_drag.y_root = 140
        with patch.object(self.w.root, "geometry") as mock_geom:
            self.w._on_mouse_drag(event_drag)
            self.assertTrue(self.w.is_dragging)
            self.assertIsNone(self.w.mouse_pressed_control)  # Click was cancelled!

        # Mouse up after dragging -> does NOT toggle tracking!
        with patch.object(self.w, "toggle_tracking") as mock_toggle:
            self.w._on_mouse_up(event_drag)
            self.assertFalse(mock_toggle.called)
            self.assertFalse(self.w.is_dragging)

    def test_smooth_progress_bar_photo_generation(self):
        """Verify _get_progress_bar_photo generates valid PhotoImage for 0%, 50%, 100%."""
        photo_0 = self.w._get_progress_bar_photo(width=472, height=6, pct=0.0)
        self.assertIsNotNone(photo_0)
        self.assertEqual(photo_0.width(), 472)

        photo_50 = self.w._get_progress_bar_photo(width=472, height=6, pct=50.0)
        self.assertIsNotNone(photo_50)

        photo_100 = self.w._get_progress_bar_photo(width=472, height=6, pct=100.0)
        self.assertIsNotNone(photo_100)

    def test_compact_mode_interactions(self):
        """Verify hitboxes and rendering in compact strip mode."""
        self.w.is_compact = True
        self.w.render_all()

        # Drag handle
        self.assertEqual(self.w._detect_control(22, 34), "drag_handle")
        # Play button
        self.assertEqual(self.w._detect_control(405, 34), "play")
        # Expand button
        self.assertEqual(self.w._detect_control(442, 34), "expand")
        # Gear
        self.assertEqual(self.w._detect_control(468, 34), "gear")
        # Menu
        self.assertEqual(self.w._detect_control(494, 34), "menu")


if __name__ == "__main__":
    unittest.main()

