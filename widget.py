"""
widget.py — High-fidelity floating desktop focus widget for Time Tracker AI 2.
Features:
- Full Expanded Mode (520px x 190px) matching the Dashboard Widget (Image 0 & Image 4):
  - Deep midnight navy surface (#0F1420), rounded corners (r=18).
  - Cyan-to-purple illuminated gradient border with soft outer neon glow.
  - Atmospheric dark forest and pine tree silhouettes matching forest-artwork.svg.
  - Top header row matching dashboard widget:
    * "FOCUS SESSION" in bold cyan (#16D5E2) with green live status dot (#35D68A).
    * Active task label with rounded purple edit button [ ✎ ].
    * Dedicated vector header buttons on the top-right:
      1. Dashboard icon (crisp vector monitor -> opens browser to http://localhost:5173).
      2. Compact / Minimize icon (crisp vector horizontal bar -> collapses to single strip).
      3. Settings gear (crisp vector 8-tooth gear -> opens dedicated widget settings dialog).
      4. Three-dot menu (crisp 3 vertical dots -> opens dark-glass action context menu).
  - Main timer row:
    * 6-dot drag handle (2 columns of 3 dots).
    * Large tabular digital display (HH:MM:SS) in crisp white bold Segoe UI typography.
    * Prominent circular royal purple play/pause button (#5D6BFF) with soft glowing halo.
    * Three vertical dots to the right of the action button.
  - Segmented progress bar: Exactly 14 rounded pill segments with cyan-to-purple gradient.
  - Bottom 3-column metrics row: "Today work", "Daily goal" with mini-bar, "Current block" pill.
- Compact Strip Mode (520px x 68px):
  - Narrow horizontal timer strip with 6-dot drag handle, digital readout, task name & [ ✎ ] pill,
    play/pause button, vector expand button, vector settings gear, and vector 3-dots menu.
- Reversible collapse / restore state persisted in widget_config.json.
- Distinct event handlers for dashboard, settings, menu, collapse/expand, edit activity, and tracking.
- Custom dark-glass context menu (CustomDarkContextMenu) and settings dialog (WidgetSettingsDialog).
- Manual activity renaming & categorization (EditActivityDialog) with /api/tracker/assign-task.
- Single-instance protection on port 49281 (focuses existing window on duplicate launch).
- Preserves all historical observations and backend tracking logic.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, simpledialog
import tkinter.font as tkfont
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from generate_widget_assets import ensure_widget_assets

# Enable Per-Monitor or System DPI Awareness on Windows so Tkinter coordinates and GDI regions match 1:1
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

CONFIG_FILE = Path(__file__).resolve().parent / "widget_config.json"
API_BASE = "http://127.0.0.1:8000/api"
DASHBOARD_URL = "http://localhost:5173"
WIDGET_PORT = 49281

# Color Tokens (Matching Web Dashboard index.css)
BG_SURFACE = "#0F1420"
BG_OUTER = "#0F1420"
BORDER_CYAN = "#16D5E2"
BORDER_BLUE = "#3B82F6"
BORDER_PURPLE = "#8065FF"
TEXT_PRIMARY = "#FFFFFF"
TEXT_OFFWHITE = "#EDF0F7"
TEXT_SECONDARY = "#8994A8"
TEXT_MUTED = "#5A6679"
ACCENT_CYAN = "#16D5E2"
ACCENT_GREEN = "#35D68A"
ACCENT_PURPLE = "#5D6BFF"
ACCENT_PURPLE_HOVER = "#6D7BFF"
ACCENT_RED = "#FA5275"
PROGRESS_BG = "#1C2433"
DIVIDER_COLOR = "#1C2536"
PILL_BG = "#161E2D"
PILL_BORDER = "#222D3E"

WIDGET_WIDTH = 520
WIDGET_HEIGHT_EXPANDED = 190
WIDGET_HEIGHT_COMPACT = 68


def interpolate_color(c1_hex: str, c2_hex: str, factor: float) -> str:
    """Linearly interpolate between two RGB hex colors."""
    factor = max(0.0, min(1.0, factor))
    c1 = [int(c1_hex[i : i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(c2_hex[i : i + 2], 16) for i in (1, 3, 5)]
    res = [int(c1[i] + (c2[i] - c1[i]) * factor) for i in range(3)]
    return f"#{res[0]:02x}{res[1]:02x}{res[2]:02x}"


def load_config() -> Dict[str, Any]:
    defaults = {
        "x": -1,
        "y": -1,
        "opacity": 0.98,
        "topmost": True,
        "compact": False,
        "autohide": False,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def api_get(endpoint: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(
            f"{API_BASE}{endpoint}",
            headers={"User-Agent": "TimeTrackerWidget/2.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


def api_post(endpoint: str, data: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    try:
        body = json.dumps(data).encode("utf-8") if data else b""
        req = urllib.request.Request(
            f"{API_BASE}{endpoint}",
            data=body if body else None,
            headers={"Content-Type": "application/json", "User-Agent": "TimeTrackerWidget/2.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 201):
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


# ==============================================================================
# Vector Drawing Primitives (Matching Dashboard Icons.tsx)
# ==============================================================================

def draw_vector_dashboard(canvas: tk.Canvas, cx: float, cy: float, color: str):
    """Draw crisp vector monitor matching dashboard WidgetIcon."""
    canvas.create_rectangle(cx - 6.5, cy - 5.5, cx + 6.5, cy + 2.5, outline=color, width=1.4)
    canvas.create_rectangle(cx + 1.5, cy - 3.5, cx + 4.5, cy - 0.5, fill=color, outline="")
    canvas.create_line(cx, cy + 2.5, cx, cy + 5.5, fill=color, width=1.4)
    canvas.create_line(cx - 3.5, cy + 5.5, cx + 3.5, cy + 5.5, fill=color, width=1.4)


def draw_vector_collapse(canvas: tk.Canvas, cx: float, cy: float, color: str):
    """Draw clean horizontal minimize bar."""
    canvas.create_line(cx - 4.5, cy, cx + 4.5, cy, fill=color, width=1.8, capstyle="round")


def draw_vector_expand(canvas: tk.Canvas, cx: float, cy: float, color: str):
    """Draw crisp expand icon with corner brackets."""
    canvas.create_line(cx + 1, cy - 5, cx + 5, cy - 5, fill=color, width=1.4, capstyle="round")
    canvas.create_line(cx + 5, cy - 5, cx + 5, cy - 1, fill=color, width=1.4, capstyle="round")
    canvas.create_line(cx, cy, cx + 5, cy - 5, fill=color, width=1.4, capstyle="round")
    canvas.create_line(cx - 1, cy + 5, cx - 5, cy + 5, fill=color, width=1.4, capstyle="round")
    canvas.create_line(cx - 5, cy + 5, cx - 5, cy + 1, fill=color, width=1.4, capstyle="round")
    canvas.create_line(cx, cy, cx - 5, cy + 5, fill=color, width=1.4, capstyle="round")


def draw_vector_gear(canvas: tk.Canvas, cx: float, cy: float, color: str):
    """Draw crisp vector mechanical gear matching dashboard SettingsIcon."""
    for deg in (0, 45, 90, 135, 180, 225, 270, 315):
        rad = math.radians(deg)
        x_in = cx + 2.5 * math.cos(rad)
        y_in = cy + 2.5 * math.sin(rad)
        x_out = cx + 5.5 * math.cos(rad)
        y_out = cy + 5.5 * math.sin(rad)
        canvas.create_line(x_in, y_in, x_out, y_out, fill=color, width=1.8)
    canvas.create_oval(cx - 3.2, cy - 3.2, cx + 3.2, cy + 3.2, fill=color, outline="")
    canvas.create_oval(cx - 1.4, cy - 1.4, cx + 1.4, cy + 1.4, fill=BG_SURFACE, outline="")


def draw_vector_ellipsis(canvas: tk.Canvas, cx: float, cy: float, color: str):
    """Draw 3 crisp solid separated vertical round dots."""
    for dy in (-5.5, 0, 5.5):
        canvas.create_oval(cx - 1.5, cy + dy - 1.5, cx + 1.5, cy + dy + 1.5, fill=color, outline="")


def draw_vector_close(canvas: tk.Canvas, cx: float, cy: float, color: str):
    """Draw crisp vector close ✕ icon."""
    d = 4.0
    canvas.create_line(cx - d, cy - d, cx + d, cy + d, fill=color, width=1.5, capstyle="round")
    canvas.create_line(cx - d, cy + d, cx + d, cy - d, fill=color, width=1.5, capstyle="round")


def draw_vector_pencil_pill(canvas: tk.Canvas, x1: float, cy: float, is_hover: bool = False):
    """Draw rounded pill button [ ✎ ] matching dashboard widget task edit button."""
    w, h = 24, 18
    x2 = x1 + w
    y1 = cy - h / 2
    y2 = cy + h / 2
    r = 4
    pts = [
        x1 + r, y1,  x2 - r, y1,
        x2, y1,      x2, y1 + r,
        x2, y2 - r,  x2, y2,
        x2 - r, y2,  x1 + r, y2,
        x1, y2,      x1, y2 - r,
        x1, y1 + r,  x1, y1
    ]
    fill_col = "#252048" if is_hover else "#181A32"
    border_col = "#8065FF" if is_hover else "#4E4882"
    canvas.create_polygon(pts, smooth=True, fill=fill_col, outline=border_col, width=1)

    pcx = (x1 + x2) / 2
    pcy = cy
    pad_col = "#9D8AFF" if is_hover else "#8065FF"
    pen_col = "#FFFFFF" if is_hover else "#C4B5FD"
    # Small notepad rectangle
    canvas.create_rectangle(pcx - 5, pcy - 4, pcx + 2, pcy + 4, outline=pad_col, width=1.2)
    # Diagonal pencil angled into pad
    canvas.create_line(pcx - 1, pcy + 2, pcx + 5, pcy - 4, fill=pen_col, width=1.5, capstyle="round")


def draw_pine_tree(canvas: tk.Canvas, cx: float, base_y: float, height: float, color: str):
    """Draw multi-tiered pine tree silhouette matching forest-artwork.svg."""
    num_tiers = 4
    tier_h = height / num_tiers
    for i in range(num_tiers):
        top_y = base_y - height + i * (tier_h * 0.7)
        bot_y = top_y + tier_h * 1.3
        w = 6 + i * 5
        canvas.create_polygon(cx, top_y, cx - w, bot_y, cx + w, bot_y, fill=color, outline="")


# ==============================================================================
# Custom Dark Glass Popups & Dialogs
# ==============================================================================

class CustomDarkContextMenu:
    """Sleek dark-glass popup context menu matching Time Tracker AI 2 aesthetic."""
    def __init__(self, parent_widget: "DesktopWidget", items: List[Tuple[str, str, Any]], x: int, y: int):
        self.parent = parent_widget
        self.top = tk.Toplevel(parent_widget.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.config(bg="#0B101B")

        screen_w = self.top.winfo_screenwidth()
        screen_h = self.top.winfo_screenheight()
        menu_w = 230
        row_h = 30
        menu_h = len(items) * row_h + 12
        if x + menu_w > screen_w - 8:
            x = screen_w - menu_w - 8
        if y + menu_h > screen_h - 8:
            y = screen_h - menu_h - 8
        self.top.geometry(f"{menu_w}x{menu_h}+{x}+{y}")

        container = tk.Frame(self.top, bg="#0F1420", highlightthickness=1.5, highlightbackground="#8065FF")
        container.pack(fill="both", expand=True)

        for icon_symbol, label, cmd in items:
            if label == "---":
                sep = tk.Frame(container, bg="#1C2536", height=1)
                sep.pack(fill="x", padx=10, pady=4)
                continue

            row = tk.Frame(container, bg="#0F1420", height=row_h, cursor="hand2")
            row.pack(fill="x", padx=4, pady=1)

            lbl_icon = tk.Label(row, text=icon_symbol, font=("Segoe UI", 10), fg="#8065FF", bg="#0F1420", width=2)
            lbl_icon.pack(side="left", padx=(8, 4))

            lbl_text = tk.Label(row, text=label, font=("Segoe UI", 9), fg="#EDF0F7", bg="#0F1420", anchor="w")
            lbl_text.pack(side="left", fill="x", expand=True)

            def make_handler(c=cmd):
                def _exec(e=None):
                    self.close()
                    if c:
                        c()
                return _exec

            action = make_handler()

            def on_enter(e, r=row, li=lbl_icon, lt=lbl_text):
                r.config(bg="#1E283D")
                li.config(bg="#1E283D", fg="#16D5E2")
                lt.config(bg="#1E283D", fg="#FFFFFF")

            def on_leave(e, r=row, li=lbl_icon, lt=lbl_text):
                r.config(bg="#0F1420")
                li.config(bg="#0F1420", fg="#8065FF")
                lt.config(bg="#0F1420", fg="#EDF0F7")

            for w in (row, lbl_icon, lbl_text):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<Button-1>", action)

        self.top.bind("<FocusOut>", lambda e: self.close())
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.focus_force()

    def close(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class WidgetSettingsDialog:
    """Dedicated sleek dark settings dialog for the desktop widget."""
    def __init__(self, parent_widget: "DesktopWidget"):
        self.parent = parent_widget
        self.top = tk.Toplevel(parent_widget.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.config(bg="#0A0E17")

        dlg_w = 330
        dlg_h = 280
        px = parent_widget.root.winfo_x() + (WIDGET_WIDTH - dlg_w) // 2
        py = parent_widget.root.winfo_y() + max(10, (parent_widget.current_height - dlg_h) // 2)
        self.top.geometry(f"{dlg_w}x{dlg_h}+{px}+{py}")

        container = tk.Frame(self.top, bg="#0F1420", highlightthickness=1.5, highlightbackground="#8065FF")
        container.pack(fill="both", expand=True, padx=2, pady=2)

        # Header
        hdr = tk.Frame(container, bg="#0F1420")
        hdr.pack(fill="x", padx=16, pady=(14, 10))

        lbl_title = tk.Label(hdr, text="Widget Settings", font=("Segoe UI", 11, "bold"), fg="#EDF0F7", bg="#0F1420")
        lbl_title.pack(side="left")

        btn_close = tk.Label(hdr, text="✕", font=("Segoe UI", 10, "bold"), fg="#8994A8", bg="#0F1420", cursor="hand2")
        btn_close.pack(side="right")
        btn_close.bind("<Button-1>", lambda e: self.close())
        btn_close.bind("<Enter>", lambda e: btn_close.config(fg="#FA5275"))
        btn_close.bind("<Leave>", lambda e: btn_close.config(fg="#8994A8"))

        tk.Frame(container, bg="#1C2536", height=1).pack(fill="x", padx=16, pady=4)

        # 1. Opacity section
        tk.Label(container, text="WINDOW OPACITY", font=("Segoe UI", 8, "bold"), fg="#8994A8", bg="#0F1420").pack(anchor="w", padx=16, pady=(6, 4))
        op_frame = tk.Frame(container, bg="#0F1420")
        op_frame.pack(fill="x", padx=16, pady=2)

        cur_op = parent_widget.cfg.get("opacity", 0.98)
        self.op_buttons = {}
        for val, lbl in [(1.0, "100%"), (0.95, "95%"), (0.85, "85%"), (0.75, "75%")]:
            is_active = abs(cur_op - val) < 0.03
            btn = tk.Label(
                op_frame, text=lbl,
                font=("Segoe UI", 9, "bold" if is_active else "normal"),
                fg="#FFFFFF" if is_active else "#8994A8",
                bg="#8065FF" if is_active else "#161E2D",
                padx=10, pady=4, cursor="hand2",
                highlightthickness=1,
                highlightbackground="#8065FF" if is_active else "#222D3E"
            )
            btn.pack(side="left", padx=3)
            btn.bind("<Button-1>", lambda e, v=val: self._set_op(v))
            self.op_buttons[val] = btn

        # 2. Always on top
        topmost_frame = tk.Frame(container, bg="#0F1420", cursor="hand2")
        topmost_frame.pack(fill="x", padx=16, pady=(12, 4))
        cur_top = parent_widget.cfg.get("topmost", True)
        self.lbl_topmost_val = tk.Label(
            topmost_frame,
            text="ON" if cur_top else "OFF",
            font=("Segoe UI", 8, "bold"),
            fg="#FFFFFF",
            bg="#35D68A" if cur_top else "#222D3E",
            padx=8, pady=2
        )
        self.lbl_topmost_val.pack(side="right")
        tk.Label(topmost_frame, text="Always on Top", font=("Segoe UI", 9), fg="#EDF0F7", bg="#0F1420").pack(side="left")
        topmost_frame.bind("<Button-1>", lambda e: self._toggle_topmost())
        self.lbl_topmost_val.bind("<Button-1>", lambda e: self._toggle_topmost())

        # 3. Compact mode
        compact_frame = tk.Frame(container, bg="#0F1420", cursor="hand2")
        compact_frame.pack(fill="x", padx=16, pady=4)
        self.lbl_compact_val = tk.Label(
            compact_frame,
            text="COMPACT" if parent_widget.is_compact else "EXPANDED",
            font=("Segoe UI", 8, "bold"),
            fg="#FFFFFF",
            bg="#8065FF" if parent_widget.is_compact else "#222D3E",
            padx=8, pady=2
        )
        self.lbl_compact_val.pack(side="right")
        tk.Label(compact_frame, text="Display Mode", font=("Segoe UI", 9), fg="#EDF0F7", bg="#0F1420").pack(side="left")
        compact_frame.bind("<Button-1>", lambda e: self._toggle_compact())
        self.lbl_compact_val.bind("<Button-1>", lambda e: self._toggle_compact())

        # Action Buttons
        act_row = tk.Frame(container, bg="#0F1420")
        act_row.pack(fill="x", padx=16, pady=(14, 10))

        btn_reset = tk.Label(
            act_row, text="↺ Reset Position",
            font=("Segoe UI", 8, "bold"), fg="#8994A8", bg="#161E2D",
            padx=10, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground="#222D3E"
        )
        btn_reset.pack(side="left")
        btn_reset.bind("<Button-1>", lambda e: (parent_widget.reset_position(), self.close()))

        btn_done = tk.Label(
            act_row, text="Done",
            font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#8065FF",
            padx=14, pady=5, cursor="hand2"
        )
        btn_done.pack(side="right")
        btn_done.bind("<Button-1>", lambda e: self.close())

        self.top.bind("<Escape>", lambda e: self.close())
        self.top.focus_force()

    def _set_op(self, val: float):
        self.parent.set_opacity(val)
        for v, b in self.op_buttons.items():
            is_active = abs(v - val) < 0.03
            b.config(
                font=("Segoe UI", 9, "bold" if is_active else "normal"),
                fg="#FFFFFF" if is_active else "#8994A8",
                bg="#8065FF" if is_active else "#161E2D",
                highlightbackground="#8065FF" if is_active else "#222D3E"
            )

    def _toggle_topmost(self):
        self.parent.toggle_topmost()
        cur = self.parent.cfg.get("topmost", True)
        self.lbl_topmost_val.config(
            text="ON" if cur else "OFF",
            bg="#35D68A" if cur else "#222D3E"
        )

    def _toggle_compact(self):
        self.parent.toggle_compact_mode()
        self.lbl_compact_val.config(
            text="COMPACT" if self.parent.is_compact else "EXPANDED",
            bg="#8065FF" if self.parent.is_compact else "#222D3E"
        )

    def close(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class EditActivityDialog:
    """Manual activity renaming and categorization dialog in Desktop Widget."""
    def __init__(self, parent_widget: "DesktopWidget"):
        self.parent = parent_widget
        self.top = tk.Toplevel(parent_widget.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.config(bg="#0A0E17")

        dlg_w = 380
        dlg_h = 310
        px = parent_widget.root.winfo_x() + (WIDGET_WIDTH - dlg_w) // 2
        py = parent_widget.root.winfo_y() + max(10, (parent_widget.current_height - dlg_h) // 2)
        self.top.geometry(f"{dlg_w}x{dlg_h}+{px}+{py}")

        container = tk.Frame(self.top, bg="#0F1420", highlightthickness=1.5, highlightbackground="#8065FF")
        container.pack(fill="both", expand=True, padx=2, pady=2)

        # Header
        hdr = tk.Frame(container, bg="#0F1420")
        hdr.pack(fill="x", padx=16, pady=(14, 10))

        lbl_title = tk.Label(hdr, text="Edit Current Activity", font=("Segoe UI", 11, "bold"), fg="#EDF0F7", bg="#0F1420")
        lbl_title.pack(side="left")

        btn_close = tk.Label(hdr, text="✕", font=("Segoe UI", 10, "bold"), fg="#8994A8", bg="#0F1420", cursor="hand2")
        btn_close.pack(side="right")
        btn_close.bind("<Button-1>", lambda e: self.close())
        btn_close.bind("<Enter>", lambda e: btn_close.config(fg="#FA5275"))
        btn_close.bind("<Leave>", lambda e: btn_close.config(fg="#8994A8"))

        tk.Frame(container, bg="#1C2536", height=1).pack(fill="x", padx=16, pady=4)

        # Detected App Info Chip
        raw_app = getattr(parent_widget, "current_raw_app", "") or "Active Window"
        app_chip = tk.Frame(container, bg="#161E2D", padx=8, pady=4)
        app_chip.pack(fill="x", padx=16, pady=(6, 10))
        tk.Label(app_chip, text=f"Detected: {raw_app}", font=("Segoe UI", 8), fg="#8994A8", bg="#161E2D", anchor="w").pack(fill="x")

        # Activity Name Field
        tk.Label(container, text="TASK / ACTIVITY NAME", font=("Segoe UI", 8, "bold"), fg="#8994A8", bg="#0F1420").pack(anchor="w", padx=16, pady=(4, 2))
        self.entry_task = tk.Entry(
            container,
            font=("Segoe UI", 10),
            fg="#FFFFFF",
            bg="#161E2D",
            insertbackground="#8065FF",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#222D3E",
            highlightcolor="#8065FF"
        )
        self.entry_task.pack(fill="x", padx=16, pady=(2, 10), ipady=4)
        self.entry_task.insert(0, parent_widget.active_task_name)
        self.entry_task.select_range(0, tk.END)

        # Category Selector
        tk.Label(container, text="CATEGORY", font=("Segoe UI", 8, "bold"), fg="#8994A8", bg="#0F1420").pack(anchor="w", padx=16, pady=(4, 2))
        self.selected_cat_id = getattr(parent_widget, "current_category_id", None)

        cats_frame = tk.Frame(container, bg="#0F1420")
        cats_frame.pack(fill="x", padx=16, pady=2)

        standard_cats = [
            (1, "Development", "#35D68A"),
            (2, "Communication", "#8065FF"),
            (3, "Study", "#FFB23E"),
            (4, "Entertainment", "#FA5275"),
            (5, "Other", "#93C5FD"),
        ]
        self.cat_buttons = {}
        for cid, cname, col in standard_cats:
            is_active = (self.selected_cat_id == cid)
            b = tk.Label(
                cats_frame, text=cname,
                font=("Segoe UI", 8, "bold" if is_active else "normal"),
                fg="#FFFFFF" if is_active else "#8994A8",
                bg="#8065FF" if is_active else "#161E2D",
                padx=6, pady=3, cursor="hand2",
                highlightthickness=1,
                highlightbackground="#8065FF" if is_active else "#222D3E"
            )
            b.pack(side="left", padx=2, pady=2)
            b.bind("<Button-1>", lambda e, c=cid: self._select_cat(c))
            self.cat_buttons[cid] = b

        # Action Buttons
        act_row = tk.Frame(container, bg="#0F1420")
        act_row.pack(fill="x", padx=16, pady=(16, 10))

        btn_cancel = tk.Label(
            act_row, text="Cancel",
            font=("Segoe UI", 9), fg="#8994A8", bg="#161E2D",
            padx=12, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground="#222D3E"
        )
        btn_cancel.pack(side="left")
        btn_cancel.bind("<Button-1>", lambda e: self.close())

        btn_save = tk.Label(
            act_row, text="Save Activity",
            font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#8065FF",
            padx=14, pady=5, cursor="hand2"
        )
        btn_save.pack(side="right")
        btn_save.bind("<Button-1>", lambda e: self._save())

        self.top.bind("<Return>", lambda e: self._save())
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.focus_force()
        self.entry_task.focus_set()

    def _select_cat(self, cid: int):
        self.selected_cat_id = cid
        for c, b in self.cat_buttons.items():
            is_active = (c == cid)
            b.config(
                font=("Segoe UI", 8, "bold" if is_active else "normal"),
                fg="#FFFFFF" if is_active else "#8994A8",
                bg="#8065FF" if is_active else "#161E2D",
                highlightbackground="#8065FF" if is_active else "#222D3E"
            )

    def _save(self):
        new_name = self.entry_task.get().strip()
        if not new_name:
            return
        self.parent.active_task_name = new_name
        self.parent.current_category_id = self.selected_cat_id
        obs_id = getattr(self.parent, "current_observation_id", None)

        threading.Thread(
            target=lambda: api_post(
                "/tracker/assign-task",
                {"task_name": new_name, "category_id": self.selected_cat_id, "observation_id": obs_id}
            ),
            daemon=True
        ).start()

        self.parent.render_all()
        self.close()

    def close(self):
        try:
            self.top.destroy()
        except Exception:
            pass


# ==============================================================================
# Main Desktop Widget
# ==============================================================================

class DesktopWidget:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()

        # State
        self.is_tracking = True
        self.is_compact = bool(self.cfg.get("compact", False))
        self.current_height = WIDGET_HEIGHT_COMPACT if self.is_compact else WIDGET_HEIGHT_EXPANDED

        self.active_task_name = "chrome — Time Tracker ..."
        self.current_raw_app = "chrome.exe"
        self.current_observation_id: Optional[int] = None
        self.current_category_id: Optional[int] = None
        self.session_elapsed_seconds = 1     # Representative initial 00:00:01 matching Image 0
        self.today_work_seconds = 16320.0    # 4h 32m
        self.today_work_label = "4h 32m"
        self.daily_goal_target_seconds = 5 * 3600
        self.daily_goal_pct = 91.0
        self.current_block_name = "Deep Work"
        self.manual_focus_session = None

        # Drag and interaction tracking
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.mouse_down_x = 0
        self.mouse_down_y = 0
        self.is_dragging = False
        self.mouse_pressed_control: Optional[str] = None

        # Button hover state & exact hit boundaries
        self.hovered_control: Optional[str] = None
        self.edit_pill_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)

        # Cached progress bar image
        self._cached_progress_photo: Optional[ImageTk.PhotoImage] = None
        self._cached_progress_key: Optional[Tuple[int, int, float]] = None

        self.setup_background_assets()
        self.setup_window()
        self.build_canvas()
        self.apply_window_region()
        self.render_all()

        # Background sync loop and UI tick
        self.running = True
        self.sync_thread = threading.Thread(target=self._background_sync_loop, daemon=True)
        self.sync_thread.start()

        self.root.after(1000, self._local_tick)

    def setup_background_assets(self):
        """Load and cache the pre-rendered high-fidelity background assets."""
        ensure_widget_assets()
        assets_dir = Path(__file__).resolve().parent / "assets"
        self.bg_expanded_img = Image.open(assets_dir / "widget_bg_expanded.png")
        self.bg_expanded_photo = ImageTk.PhotoImage(self.bg_expanded_img)
        self.bg_compact_img = Image.open(assets_dir / "widget_bg_compact.png")
        self.bg_compact_photo = ImageTk.PhotoImage(self.bg_compact_img)

    def apply_window_region(self):
        """
        Shape the native Windows window to smooth rounded corners without rectangular backing.
        Uses SetWindowRgn with exact radius to eliminate black corners and border clipping.
        """
        try:
            self.root.update_idletasks()
            w_id = self.root.winfo_id()
            p_id = ctypes.windll.user32.GetParent(w_id)
            r_diam = 40 if not self.is_compact else 36
            for h in (p_id, w_id):
                if h:
                    rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                        0, 0, WIDGET_WIDTH + 1, self.current_height + 1, r_diam, r_diam
                    )
                    ctypes.windll.user32.SetWindowRgn(h, rgn, True)
        except Exception:
            pass

    def setup_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.cfg.get("topmost", True))
        try:
            self.root.attributes("-alpha", self.cfg.get("opacity", 0.98))
        except Exception:
            pass

        self.root.config(bg=BG_SURFACE)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        cfg_x = self.cfg.get("x", -1)
        cfg_y = self.cfg.get("y", -1)

        if cfg_x < 0 or cfg_y < 0:
            x = max(10, screen_w - WIDGET_WIDTH - 32)
            y = 32
        else:
            x = max(10, min(screen_w - WIDGET_WIDTH - 10, cfg_x))
            y = max(10, min(screen_h - self.current_height - 10, cfg_y))

        self.root.geometry(f"{WIDGET_WIDTH}x{self.current_height}+{x}+{y}")

    def build_canvas(self):
        self.canvas = tk.Canvas(
            self.root,
            width=WIDGET_WIDTH,
            height=self.current_height,
            bg=BG_SURFACE,
            highlightthickness=0,
            cursor="arrow",
        )
        self.canvas.pack(fill="both", expand=True)

        # Mouse event bindings
        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-3>", self.show_context_menu)

    def draw_rounded_rectangle(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        r: float,
        fill: str = "",
        outline: str = "",
        width: int = 1,
    ) -> int:
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, fill=fill, outline=outline, width=width)

    def draw_illuminated_border(self, x1: int, y1: int, x2: int, y2: int, r: int):
        """Draw gradient border with soft outer glow matching dashboard widget (Image 0 & 4)."""
        # 1. Soft outer neon glow halos
        self.draw_rounded_rectangle(x1 - 2, y1 - 2, x2 + 2, y2 + 2, r + 2, fill="", outline="#12182E", width=1)
        self.draw_rounded_rectangle(x1 - 1, y1 - 1, x2 + 1, y2 + 1, r + 1, fill="", outline="#16203D", width=1)

        # 2. Main surface
        self.draw_rounded_rectangle(x1, y1, x2, y2, r, fill=BG_SURFACE, outline="", width=0)

        # 3. Illuminated perimeter segments (cyan -> blue -> purple)
        steps = 20
        top_w = (x2 - r) - (x1 + r)
        for s in range(steps):
            sx1 = x1 + r + (top_w * s) / steps
            sx2 = x1 + r + (top_w * (s + 1)) / steps
            frac = s / steps
            col = interpolate_color(BORDER_CYAN, BORDER_PURPLE, frac)
            self.canvas.create_line(sx1, y1, sx2, y1, fill=col, width=1.5)

        # Left edge: bright cyan
        self.canvas.create_line(x1, y1 + r, x1, y2 - r, fill=BORDER_CYAN, width=1.5)

        # Right edge: bright purple
        self.canvas.create_line(x2, y1 + r, x2, y2 - r, fill=BORDER_PURPLE, width=1.5)

        # Bottom edge: cyan fading through blue to purple
        bot_w = (x2 - r) - (x1 + r)
        for s in range(steps):
            sx1 = x1 + r + (bot_w * s) / steps
            sx2 = x1 + r + (bot_w * (s + 1)) / steps
            frac = s / steps
            col = interpolate_color(BORDER_CYAN, BORDER_PURPLE, frac)
            self.canvas.create_line(sx1, y2, sx2, y2, fill=col, width=1.5)

        # Corner arcs
        self.canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="arc", outline=BORDER_CYAN, width=1.5)
        self.canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="arc", outline=BORDER_PURPLE, width=1.5)
        self.canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="arc", outline=BORDER_PURPLE, width=1.5)
        self.canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="arc", outline=BORDER_CYAN, width=1.5)

    def render_all(self):
        """Render widget based on mode (Compact Strip vs Full Expanded)."""
        self.canvas.delete("all")
        if self.is_compact:
            self._render_compact_mode()
        else:
            self._render_expanded_mode()

    def _get_progress_bar_photo(self, width: int = 472, height: int = 8, pct: float = 0.0) -> ImageTk.PhotoImage:
        """
        Generate a 14-segmented rounded pill progress bar matching the Dashboard Widget reference design.
        Each segment is an anti-aliased rounded capsule with cyan-to-purple gradient,
        soft radiant glow for lit segments, muted dark track for unlit segments, and NO stray underlines.
        """
        clamped_pct = max(0.0, min(100.0, pct))
        cache_key = (width, height, round(clamped_pct, 1))
        if self._cached_progress_key == cache_key and self._cached_progress_photo is not None:
            return self._cached_progress_photo

        SCALE = 3
        W = width * SCALE
        H = height * SCALE
        R = H // 2
        glow_pad = 4 * SCALE
        num_segments = 14

        total_h = H + glow_pad * 2
        img = Image.new("RGBA", (W, total_h), (0, 0, 0, 0))
        glow_layer = Image.new("RGBA", (W, total_h), (0, 0, 0, 0))
        gldraw = ImageDraw.Draw(glow_layer)
        draw = ImageDraw.Draw(img)

        gradient_palette = [
            (22, 213, 226),  # 0: Cyan #16D5E2
            (22, 213, 226),  # 1: Cyan
            (25, 211, 230),  # 2: Cyan #19D3E6
            (31, 209, 234),  # 3: Cyan #1FD1EA
            (56, 189, 248),  # 4: Sky blue #38BDF8
            (79, 156, 248),  # 5: Blue #4F9CF8
            (99, 133, 248),  # 6: Royal blue #6385F8
            (129, 140, 248), # 7: Indigo #818CF8
            (167, 139, 250), # 8: Lavender #A78BFA
            (181, 117, 236), # 9: Purple #B575EC
            (192, 132, 252), # 10: Violet #C084FC
            (128, 101, 255), # 11: Purple #8065FF
            (128, 101, 255), # 12: Purple
            (128, 101, 255), # 13: Purple
        ]

        active_count = min(num_segments, int(round((clamped_pct / 100.0) * num_segments)))
        if clamped_pct > 0 and active_count == 0:
            active_count = 1

        total_gaps = num_segments - 1
        gap_w = 5.0 * SCALE
        seg_w = (W - total_gaps * gap_w) / num_segments
        y_offset = glow_pad

        for i in range(num_segments):
            sx1 = int(round(i * (seg_w + gap_w)))
            sx2 = int(round(sx1 + seg_w))
            sy1 = y_offset
            sy2 = y_offset + H

            is_lit = (i < active_count)
            if is_lit:
                rgb = gradient_palette[min(i, len(gradient_palette) - 1)]
                # Soft ambient glow behind the segment (clean halo, no underlines!)
                gldraw.rounded_rectangle(
                    [sx1 - int(1.5 * SCALE), sy1 - int(1.5 * SCALE), sx2 + int(1.5 * SCALE), sy2 + int(1.5 * SCALE)],
                    radius=R + int(1.5 * SCALE),
                    fill=rgb + (95,),
                )
                # Lit pill capsule
                draw.rounded_rectangle([sx1, sy1, sx2, sy2], radius=R, fill=rgb + (255,))
            else:
                # Unlit muted dark track capsule matching reference
                draw.rounded_rectangle(
                    [sx1, sy1, sx2, sy2],
                    radius=R,
                    fill=(20, 26, 40, 255),
                    outline=(31, 41, 60, 255),
                    width=1 * SCALE,
                )

        # Soft blur for glow
        glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(SCALE * 1.5))
        final_img = Image.alpha_composite(glow_blurred, img)

        out_h = height + int(round(glow_pad * 2 / SCALE))
        result = final_img.resize((width, out_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(result)
        self._cached_progress_photo = photo
        self._cached_progress_key = cache_key
        return photo

    def _draw_header_button(self, cx: float, cy: float, ctrl_name: str, draw_fn, default_col: str = "#8E9BB5"):
        is_hover = (self.hovered_control == ctrl_name)
        if is_hover:
            self.draw_rounded_rectangle(cx - 11, cy - 11, cx + 11, cy + 11, 4, fill="#1B2436", outline="#2A3850", width=1)
            col = "#FFFFFF"
        else:
            col = default_col
        draw_fn(self.canvas, cx, cy, col)

    def _render_compact_mode(self):
        """Render narrow horizontal single-strip timer widget (520x68)."""
        # 1. High-fidelity Pre-rendered Background
        self.canvas.create_image(0, 0, image=self.bg_compact_photo, anchor="nw")

        # 2. 6-Dot Drag Handle on left (Y=26, 34, 42)
        for col in (18, 24):
            for y in (26, 34, 42):
                self.canvas.create_oval(col, y, col + 3, y + 3, fill=TEXT_MUTED, outline="")

        # 3. Main Digital Timer (HH:MM:SS)
        timer_str = self._format_timer_display(self.session_elapsed_seconds)
        self.canvas.create_text(
            38, 34,
            text=timer_str,
            fill=TEXT_PRIMARY,
            font=("Segoe UI", 20, "bold"),
            anchor="w",
        )

        # 4. Vertical Divider
        self.canvas.create_line(145, 18, 145, 50, fill=DIVIDER_COLOR, width=1)

        # 5. Live Status Dot
        dot_col = ACCENT_GREEN if self.is_tracking else ACCENT_RED
        self.canvas.create_oval(157, 30.5, 164, 37.5, fill=dot_col, outline="")

        # 6. Active Task / Current Context Label & Edit Pill [ ✎ ]
        task_left = 172
        task_label = self._format_title(self.active_task_name, 16)
        self.canvas.create_text(
            task_left, 34,
            text=task_label,
            fill=TEXT_OFFWHITE,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        try:
            f = tkfont.Font(family="Segoe UI", size=9, weight="bold")
            tw = f.measure(task_label)
        except Exception:
            tw = len(task_label) * 8
        pill_x = min(345, task_left + tw + 8)
        is_edit_hover = (self.hovered_control == "edit_task")
        draw_vector_pencil_pill(self.canvas, pill_x, 34, is_edit_hover)
        self.edit_pill_rect = (task_left - 2, 22, pill_x + 26, 46)

        # 7. Circular Royal Purple Play/Pause Button
        btn_cx = 405
        btn_cy = 34
        btn_r = 17

        is_play_hover = (self.hovered_control == "play")
        halo_col = "#252458" if not is_play_hover else "#323078"
        self.canvas.create_oval(
            btn_cx - btn_r - 3, btn_cy - btn_r - 3,
            btn_cx + btn_r + 3, btn_cy + btn_r + 3,
            fill=halo_col, outline="",
        )

        btn_fill = ACCENT_PURPLE_HOVER if is_play_hover else ACCENT_PURPLE
        self.canvas.create_oval(
            btn_cx - btn_r, btn_cy - btn_r,
            btn_cx + btn_r, btn_cy + btn_r,
            fill=btn_fill, outline="",
        )

        if self.is_tracking:
            self.canvas.create_rectangle(btn_cx - 5, btn_cy - 5, btn_cx - 2, btn_cy + 5, fill="#FFFFFF", outline="")
            self.canvas.create_rectangle(btn_cx + 2, btn_cy - 5, btn_cx + 5, btn_cy + 5, fill="#FFFFFF", outline="")
        else:
            self.canvas.create_polygon(btn_cx - 4, btn_cy - 6, btn_cx - 4, btn_cy + 6, btn_cx + 6, btn_cy, fill="#FFFFFF", outline="")

        # 8. Vector Expand / Restore Button
        self._draw_header_button(442, 34, "expand", draw_vector_expand, ACCENT_PURPLE)

        # 9. Vector Settings Gear Button
        self._draw_header_button(468, 34, "gear", draw_vector_gear, TEXT_SECONDARY)

        # 10. Vector Menu Ellipsis Button
        self._draw_header_button(494, 34, "menu", draw_vector_ellipsis, TEXT_SECONDARY)

    def _render_expanded_mode(self):
        """Render full widget matching the Dashboard Widget with polished hierarchy."""
        # 1. High-fidelity Pre-rendered Background
        self.canvas.create_image(0, 0, image=self.bg_expanded_photo, anchor="nw")

        # 2. Top Header Row (Y ≈ 22)
        session_title = "FOCUS SESSION" if self.is_tracking else "TRACKING PAUSED"
        session_col = ACCENT_CYAN if self.is_tracking else ACCENT_RED
        self.canvas.create_text(
            24, 22,
            text=session_title,
            fill=session_col,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )

        try:
            f_hdr = tkfont.Font(family="Segoe UI", size=9, weight="bold")
            title_w = f_hdr.measure(session_title)
        except Exception:
            title_w = len(session_title) * 8
        sep_x = 24 + title_w + 12
        self.canvas.create_line(sep_x, 14, sep_x, 30, fill=DIVIDER_COLOR, width=1)

        # Green/Red Live Status Dot with soft glow
        dot_x = sep_x + 14
        dot_col = ACCENT_GREEN if self.is_tracking else ACCENT_RED
        aura_col = "#123B2B" if self.is_tracking else "#3B1218"
        self.canvas.create_oval(dot_x - 5, 17, dot_x + 5, 27, fill="", outline=aura_col, width=1)
        self.canvas.create_oval(dot_x - 3.5, 18.5, dot_x + 3.5, 25.5, fill=dot_col, outline="")

        # Active Context / Task Label
        task_left = dot_x + 12
        max_task_w = 405 - task_left - 34
        task_text = self._format_title(self.active_task_name, 22)
        try:
            f_task = tkfont.Font(family="Segoe UI", size=9)
            text_w = f_task.measure(task_text)
            if text_w > max_task_w:
                while text_w > max_task_w and len(task_text) > 4:
                    task_text = task_text[:-4].strip() + "..."
                    text_w = f_task.measure(task_text)
        except Exception:
            text_w = len(task_text) * 7

        self.canvas.create_text(
            task_left, 22,
            text=task_text,
            fill=TEXT_OFFWHITE,
            font=("Segoe UI", 9),
            anchor="w",
        )

        # Task Edit Button [ ✎ ] pill
        pill_x = task_left + text_w + 8
        is_edit_hover = (self.hovered_control == "edit_task")
        draw_vector_pencil_pill(self.canvas, pill_x, 22, is_edit_hover)
        self.edit_pill_rect = (task_left - 2, 11, pill_x + 26, 33)

        # 4 Header Buttons (Aligned on top-right, Y=22):
        self._draw_header_button(424, 22, "dashboard", draw_vector_dashboard, "#8065FF")
        self._draw_header_button(448, 22, "collapse", draw_vector_collapse, TEXT_SECONDARY)
        self._draw_header_button(472, 22, "gear", draw_vector_gear, TEXT_SECONDARY)
        self._draw_header_button(496, 22, "menu", draw_vector_ellipsis, TEXT_SECONDARY)

        # 3. Main Timer Row (Y ≈ 75)
        # 6-Dot Drag Handle (left of timer)
        for col in (24, 30):
            for y in (67, 75, 83):
                self.canvas.create_oval(col, y, col + 3, y + 3, fill=TEXT_MUTED, outline="")

        # Large Digital Timer (HH:MM:SS) in pure white Segoe UI Bold
        timer_str = self._format_timer_display(self.session_elapsed_seconds)
        self.canvas.create_text(
            46, 75,
            text=timer_str,
            fill=TEXT_PRIMARY,
            font=("Segoe UI", 36, "bold"),
            anchor="w",
        )

        # Large Circular Play/Pause Button (#5D6BFF) with Glowing Halo
        btn_cx = 420
        btn_cy = 75
        btn_r = 23

        is_play_hover = (self.hovered_control == "play")
        halo_col = "#252458" if not is_play_hover else "#323078"
        self.canvas.create_oval(
            btn_cx - btn_r - 4, btn_cy - btn_r - 4,
            btn_cx + btn_r + 4, btn_cy + btn_r + 4,
            fill=halo_col, outline="",
        )

        btn_fill = ACCENT_PURPLE_HOVER if is_play_hover else ACCENT_PURPLE
        self.canvas.create_oval(
            btn_cx - btn_r, btn_cy - btn_r,
            btn_cx + btn_r, btn_cy + btn_r,
            fill=btn_fill, outline="",
        )

        if self.is_tracking:
            self.canvas.create_rectangle(
                btn_cx - 5.5, btn_cy - 8, btn_cx - 1.5, btn_cy + 8,
                fill="#FFFFFF", outline="",
            )
            self.canvas.create_rectangle(
                btn_cx + 1.5, btn_cy - 8, btn_cx + 5.5, btn_cy + 8,
                fill="#FFFFFF", outline="",
            )
        else:
            self.canvas.create_polygon(
                btn_cx - 4.5, btn_cy - 8,
                btn_cx - 4.5, btn_cy + 8,
                btn_cx + 7, btn_cy,
                fill="#FFFFFF", outline="",
            )

        # Three-dot icon to right of button with hover feedback
        is_menu_play_hover = (self.hovered_control == "menu_play")
        if is_menu_play_hover:
            self.draw_rounded_rectangle(456, 63, 476, 87, 4, fill="#1B2436", outline="#2A3850", width=1)
            menu_play_col = "#FFFFFF"
        else:
            menu_play_col = TEXT_MUTED
        draw_vector_ellipsis(self.canvas, 466, 75, menu_play_col)

        # 4. Slim, Smoothly Connected Progress Bar (Y ≈ 113 to 119)
        pct = max(0.0, min(100.0, self.daily_goal_pct))
        bar_photo = self._get_progress_bar_photo(width=472, height=8, pct=pct)
        # Position so 8px capsules are vertically centered between timer row and divider line
        self.canvas.create_image(24, 111 - 4, image=bar_photo, anchor="nw")

        # 5. Horizontal Divider Line (Y = 130)
        self.canvas.create_line(24, 130, 496, 130, fill=DIVIDER_COLOR, width=1)

        # 6. Bottom 3-Column Metrics Row
        # Column 1: Today's Work
        self.canvas.create_text(
            24, 143,
            text="Today's Work",
            fill=TEXT_SECONDARY,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.canvas.create_text(
            24, 166,
            text=self.today_work_label or "0s",
            fill=TEXT_PRIMARY,
            font=("Segoe UI", 15, "bold"),
            anchor="w",
        )

        # Vertical Divider 1
        self.canvas.create_line(164, 136, 164, 178, fill=DIVIDER_COLOR, width=1)

        # Column 2: Daily Goal
        self.canvas.create_text(
            180, 143,
            text="Daily Goal",
            fill=TEXT_SECONDARY,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.canvas.create_text(
            180, 162,
            text=f"{int(round(self.daily_goal_pct))}%",
            fill=TEXT_PRIMARY,
            font=("Segoe UI", 15, "bold"),
            anchor="w",
        )

        # Mini Progress Bar
        bar_w = 98
        self.draw_rounded_rectangle(180, 171, 180 + bar_w, 175, 2, fill="#141A28", outline="#1F293C", width=1)
        fill_w = max(3, int((pct / 100.0) * bar_w))
        self.draw_rounded_rectangle(180, 171, 180 + fill_w, 175, 2, fill="#16D5E2", outline="")

        # Vertical Divider 2
        self.canvas.create_line(298, 136, 298, 178, fill=DIVIDER_COLOR, width=1)

        # Column 3: Current Block
        self.canvas.create_text(
            314, 143,
            text="Current Block",
            fill=TEXT_SECONDARY,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )

        pill_x1 = 314
        pill_y1 = 152
        pill_x2 = 496
        pill_y2 = 176
        is_block_hover = (self.hovered_control == "current_block")
        pill_fill = "#172033" if is_block_hover else PILL_BG
        pill_border = "#5D6BFF" if is_block_hover else PILL_BORDER
        self.draw_rounded_rectangle(pill_x1, pill_y1, pill_x2, pill_y2, 5, fill=pill_fill, outline=pill_border, width=1)

        self.canvas.create_text(
            pill_x1 + 14, 164,
            text="</>",
            fill=ACCENT_CYAN,
            font=("Consolas", 8, "bold"),
            anchor="center",
        )

        block_title = self._format_title(self.current_block_name, 16)
        self.canvas.create_text(
            pill_x1 + 28, 164,
            text=block_title,
            fill=TEXT_OFFWHITE,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )

    # ---------------- Interactive Hit Detection & Handlers ----------------
    def _detect_control(self, x: int, y: int) -> Optional[str]:
        """Detect which specific interactive button the mouse is hovering or clicking."""
        if self.is_compact:
            # Drag handle (left of timer)
            if (14 <= x <= 30) and (20 <= y <= 48):
                return "drag_handle"

            # Edit task area (strictly around task text and pencil pill)
            ep_x1, ep_y1, ep_x2, ep_y2 = self.edit_pill_rect
            if ep_x1 > 0:
                if (ep_x1 <= x <= max(ep_x2, 280)) and (18 <= y <= 50):
                    return "edit_task"
            elif (170 <= x <= 280) and (18 <= y <= 50):
                return "edit_task"

            # Play button at cx=405, cy=34, r=17
            if ((x - 405) ** 2 + (y - 34) ** 2) <= (20 ** 2):
                return "play"

            # Expand button at cx=442, cy=34
            if (425 <= x <= 454) and (18 <= y <= 50):
                return "expand"

            # Settings gear at cx=468, cy=34
            if (456 <= x <= 480) and (18 <= y <= 50):
                return "gear"

            # Menu button at cx=494, cy=34
            if (482 <= x <= 508) and (18 <= y <= 50):
                return "menu"

            return None

        # Expanded Mode controls
        # 1. Drag handle (left of timer)
        if (18 <= x <= 34) and (62 <= y <= 88):
            return "drag_handle"

        # 2. Play button at cx=420, cy=75, r=23
        if ((x - 420) ** 2 + (y - 75) ** 2) <= (26 ** 2):
            return "play"

        # 3. Three-dot icon next to timer button at cx=466, cy=75
        if (454 <= x <= 478) and (63 <= y <= 87):
            return "menu_play"

        # 4. Top header buttons (Y ≈ 11 to 33):
        if 11 <= y <= 33:
            # Edit task button & task text (strictly bounded)
            ep_x1, ep_y1, ep_x2, ep_y2 = self.edit_pill_rect
            if ep_x1 > 0 and (ep_x1 <= x <= ep_x2):
                return "edit_task"

            # Dashboard button at cx=424
            if 413 <= x <= 435:
                return "dashboard"
            # Collapse button at cx=448
            if 437 <= x <= 459:
                return "collapse"
            # Settings gear at cx=472
            if 461 <= x <= 483:
                return "gear"
            # Context menu at cx=496
            if 485 <= x <= 507:
                return "menu"

        # 5. Progress Bar (24 <= x <= 496, 108 <= y <= 124)
        if (24 <= x <= 496) and (108 <= y <= 124):
            return "progress_bar"

        # 6. Current Block Pill (314 <= x <= 496, 150 <= y <= 178)
        if (314 <= x <= 496) and (150 <= y <= 178):
            return "current_block"

        return None

    def _on_mouse_move(self, event):
        ctrl = self._detect_control(event.x, event.y)
        if ctrl != self.hovered_control:
            self.hovered_control = ctrl
            self.render_all()

        if ctrl in ("play", "dashboard", "collapse", "expand", "gear", "menu", "menu_play", "edit_task", "current_block", "close", "progress_bar"):
            self.canvas.config(cursor="hand2")
        elif ctrl == "drag_handle":
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="arrow")

    def _on_mouse_down(self, event):
        ctrl = self._detect_control(event.x, event.y)
        self.mouse_pressed_control = ctrl
        self.mouse_down_x = event.x_root
        self.mouse_down_y = event.y_root
        self.drag_start_x = event.x_root - self.root.winfo_x()
        self.drag_start_y = event.y_root - self.root.winfo_y()
        self.is_dragging = False

        # If user pressed down on empty area or explicit drag handle, start dragging immediately
        if ctrl is None or ctrl == "drag_handle":
            self.is_dragging = True

    def _on_mouse_drag(self, event):
        dx = abs(event.x_root - self.mouse_down_x)
        dy = abs(event.y_root - self.mouse_down_y)

        # Drag threshold: if user moved more than 4 pixels, switch to dragging window
        if not self.is_dragging and (dx > 4 or dy > 4):
            self.is_dragging = True
            self.mouse_pressed_control = None  # Cancel button click

        if self.is_dragging:
            x = event.x_root - self.drag_start_x
            y = event.y_root - self.drag_start_y
            self.root.geometry(f"+{x}+{y}")

    def _on_mouse_up(self, event):
        was_dragging = self.is_dragging
        self.is_dragging = False

        if was_dragging:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            save_config(self.cfg)
            self.mouse_pressed_control = None
            return

        pressed = self.mouse_pressed_control
        self.mouse_pressed_control = None

        if not pressed or pressed == "drag_handle":
            return

        # Only execute if mouse is released within the same control
        released_ctrl = self._detect_control(event.x, event.y)
        if released_ctrl != pressed:
            return  # User moved away to cancel

        if pressed == "play":
            self.toggle_tracking()
        elif pressed == "dashboard":
            self.open_dashboard()
        elif pressed in ("collapse", "expand"):
            self.toggle_compact_mode()
        elif pressed == "gear":
            self.show_settings_dialog()
        elif pressed in ("menu", "menu_play"):
            self.show_context_menu(event)
        elif pressed == "edit_task":
            self.show_edit_activity_dialog()
        elif pressed == "current_block":
            self.open_time_blocks_planner()
        elif pressed == "progress_bar":
            self.open_dashboard()
        elif pressed == "close":
            self.close_widget()

    # ---------------- Actions & Menus ----------------
    def toggle_compact_mode(self):
        """Toggle between Full Expanded (520x190) and Compact Strip (520x68)."""
        self.is_compact = not self.is_compact
        self.cfg["compact"] = self.is_compact
        save_config(self.cfg)
        self.current_height = WIDGET_HEIGHT_COMPACT if self.is_compact else WIDGET_HEIGHT_EXPANDED

        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{WIDGET_WIDTH}x{self.current_height}+{x}+{y}")
        self.canvas.config(width=WIDGET_WIDTH, height=self.current_height)
        self.apply_window_region()
        self.render_all()

    def open_dashboard(self):
        """Open web dashboard in user's default browser."""
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception as e:
            messagebox.showerror("Dashboard Error", f"Could not open dashboard: {e}")

    def open_time_blocks_planner(self):
        """Open web dashboard to the Time Blocks planner view."""
        try:
            webbrowser.open(f"{DASHBOARD_URL}/?action=open_planner")
        except Exception as e:
            messagebox.showerror("Planner Error", f"Could not open planner: {e}")

    def show_settings_dialog(self):
        """Open dedicated widget settings dialog (distinct from context menu)."""
        WidgetSettingsDialog(self)

    def show_edit_activity_dialog(self):
        """Open manual activity editing & categorization dialog."""
        EditActivityDialog(self)

    def show_context_menu(self, event=None):
        """Open custom dark glass action context menu."""
        items = [
            ("✎", "Edit Current Activity...", self.show_edit_activity_dialog),
            ("🗖", "Open Web Dashboard", self.open_dashboard),
            ("📅", "Open Time Blocks Planner", self.open_time_blocks_planner),
            ("▶", "Start Named Focus Session...", self.start_focus_session),
            ("", "---", None),
            ("⏸" if self.is_tracking else "▶", "Pause Tracking" if self.is_tracking else "Resume Tracking", self.toggle_tracking),
            ("⊟" if not self.is_compact else "⤢", "Compact Strip" if not self.is_compact else "Expand Widget", self.toggle_compact_mode),
            ("⚙", "Widget Settings...", self.show_settings_dialog),
            ("↺", "Reset Position (Top-Right)", self.reset_position),
            ("", "---", None),
            ("✕", "Close Widget", self.close_widget),
        ]
        x = event.x_root if event else self.root.winfo_x() + WIDGET_WIDTH - 120
        y = event.y_root if event else self.root.winfo_y() + 30
        CustomDarkContextMenu(self, items, x, y)

    def toggle_tracking(self):
        target_endpoint = "/tracker/stop" if self.is_tracking else "/tracker/start"
        threading.Thread(target=self._exec_toggle, args=(target_endpoint,), daemon=True).start()

    def _exec_toggle(self, endpoint: str):
        res = api_post(endpoint)
        if res:
            self.is_tracking = bool(res.get("is_tracking"))
            self.root.after(0, self.render_all)

    def set_opacity(self, alpha: float):
        self.cfg["opacity"] = alpha
        save_config(self.cfg)
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass

    def toggle_topmost(self):
        cur = self.cfg.get("topmost", True)
        self.cfg["topmost"] = not cur
        save_config(self.cfg)
        self.root.attributes("-topmost", self.cfg["topmost"])

    def start_focus_session(self):
        name = simpledialog.askstring("New Focus Session", "Enter task name:", parent=self.root)
        if name and name.strip():
            self.manual_focus_session = name.strip()
            self.active_task_name = self.manual_focus_session
            self.current_block_name = self.manual_focus_session
            self.session_elapsed_seconds = 0
            if not self.is_tracking:
                self.toggle_tracking()
            self.render_all()

    def reset_position(self):
        screen_w = self.root.winfo_screenwidth()
        x = max(10, screen_w - WIDGET_WIDTH - 32)
        y = 32
        self.root.geometry(f"+{x}+{y}")
        self.cfg["x"] = x
        self.cfg["y"] = y
        save_config(self.cfg)

    def close_widget(self):
        self.running = False
        self.root.destroy()
        sys.exit(0)

    def wake_up(self):
        """Bring widget to top when pinged by another launch attempt."""
        try:
            self.root.after(0, lambda: (self.root.lift(), self.root.focus_force()))
        except Exception:
            pass

    # ---------------- Periodic Updates ----------------
    def _local_tick(self):
        if not self.running:
            return

        if self.is_tracking:
            self.session_elapsed_seconds += 1
            self.today_work_seconds += 1
            self.today_work_label = self._format_duration(self.today_work_seconds)
            if self.daily_goal_target_seconds > 0:
                self.daily_goal_pct = min(100.0, (self.today_work_seconds / self.daily_goal_target_seconds) * 100)

        self.render_all()
        self.root.after(1000, self._local_tick)

    def _background_sync_loop(self):
        while self.running:
            try:
                today_str = datetime.now().strftime("%Y-%m-%d")

                # 1. Fetch tracker status
                st = api_get("/tracker/status")
                if st:
                    self.is_tracking = bool(st.get("is_tracking"))
                    act = st.get("active_task")
                    if act and not self.manual_focus_session:
                        self.current_observation_id = act.get("observation_id")
                        self.current_category_id = act.get("category_id")
                        app = act.get("app", "")
                        self.current_raw_app = app
                        title = act.get("title", "")
                        user_task = act.get("user_task")

                        activity_name = act.get("activity_name")
                        if user_task:
                            self.active_task_name = user_task
                        elif activity_name:
                            self.active_task_name = activity_name
                        else:
                            clean_app = app.replace(".exe", "")
                            if clean_app and title and clean_app != title:
                                self.active_task_name = f"{clean_app} — {title}"
                            else:
                                self.active_task_name = clean_app or title or "chrome — Time Tracker ..."

                        self.current_block_name = clean_app or "Deep Work"

                        start_iso = act.get("start_time")
                        if start_iso:
                            try:
                                dt = datetime.fromisoformat(start_iso)
                                elapsed = int((datetime.now(dt.tzinfo) - dt).total_seconds())
                                if abs(elapsed - self.session_elapsed_seconds) > 3:
                                    self.session_elapsed_seconds = max(0, elapsed)
                            except Exception:
                                pass
                    elif not act and not self.manual_focus_session:
                        if not self.is_tracking:
                            self.active_task_name = "Tracking paused"
                        else:
                            self.active_task_name = "chrome — Time Tracker ..."

                # 2. Fetch today stats (prioritize productive work time over total screen time)
                stats = api_get(f"/stats/{today_str}")
                if stats:
                    sec = stats.get("productive_work_seconds", stats.get("active_seconds", 0.0))
                    if sec > 0:
                        self.today_work_seconds = sec
                        self.today_work_label = stats.get("productive_work_label", stats.get("active_label", self._format_duration(sec)))

                # 3. Fetch goals
                goals = api_get(f"/goals/progress/{today_str}")
                if goals and isinstance(goals, list):
                    for g in goals:
                        if g.get("metric") == "work_time":
                            pct = g.get("progress_pct", 0.0)
                            if pct > 0:
                                self.daily_goal_pct = pct
                            tgt = g.get("target_seconds", 0)
                            if tgt > 0:
                                self.daily_goal_target_seconds = tgt
                            break

                # 4. Fetch active time block
                cur_block_resp = api_get("/time-blocks/current")
                if cur_block_resp and cur_block_resp.get("has_block") and cur_block_resp.get("block"):
                    self.current_block_name = cur_block_resp["block"].get("title", "Deep Work")
                else:
                    blocks = api_get(f"/time-blocks/{today_str}")
                    if blocks and isinstance(blocks, list) and len(blocks) > 0:
                        now_hhmm = datetime.now().strftime("%H:%M")
                        for b in blocks:
                            s_raw = b.get("start_time", "")
                            e_raw = b.get("end_time", "")
                            s_time = s_raw[-8:-3] if "T" in s_raw else s_raw[:5]
                            e_time = e_raw[-8:-3] if "T" in e_raw else e_raw[:5]
                            if s_time <= now_hhmm <= e_time:
                                self.current_block_name = b.get("title", "Deep Work")
                                break
            except Exception:
                pass

            time.sleep(3.0)

    # ---------------- Formatters (Preserved for compatibility & unit tests) ----------------
    def _format_timer_display(self, seconds: int) -> str:
        s = max(0, int(seconds))
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    def _format_elapsed(self, seconds: int) -> str:
        s = max(0, int(seconds))
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m:02d}m"
        return f"{m:02d}m {sec:02d}s"

    def _format_title(self, text: str, max_len: int = 30) -> str:
        t = text.strip()
        if len(t) <= max_len:
            return t
        return t[: max_len - 3] + "..."

    def _format_duration(self, seconds: float) -> str:
        s = max(0, int(seconds))
        h, remainder = divmod(s, 3600)
        m, sec = divmod(remainder, 60)
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {sec}s"
        return f"{sec}s"


def setup_single_instance_listener(widget_inst: DesktopWidget):
    """Listens on local port WIDGET_PORT to focus window on duplicate launch attempts."""
    def listener():
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", WIDGET_PORT))
            srv.listen(2)
            while True:
                conn, _ = srv.accept()
                data = conn.recv(1024)
                conn.close()
                if b"WAKE" in data:
                    widget_inst.wake_up()
        except Exception:
            pass

    t = threading.Thread(target=listener, daemon=True)
    t.start()


def check_and_wake_existing() -> bool:
    """Returns True if an existing instance was pinged and this process should exit."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        s.connect(("127.0.0.1", WIDGET_PORT))
        s.sendall(b"WAKE\n")
        s.close()
        return True
    except Exception:
        return False


def ensure_interactive_desktop() -> bool:
    """Attach calling thread to interactive desktop WinSta0\\Default."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        tid = kernel32.GetCurrentThreadId()
        dt = user32.GetThreadDesktop(tid)
        if dt:
            buf = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if user32.GetUserObjectInformationW(dt, 2, buf, 512, ctypes.byref(needed)):
                if buf.value.lower() == "default":
                    return True

        h_ws = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if h_ws:
            user32.SetProcessWindowStation(h_ws)

        h_dt = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_dt:
            return bool(user32.SetThreadDesktop(h_dt))
        return False
    except Exception:
        return False


def main():
    if check_and_wake_existing():
        sys.exit(0)

    ensure_interactive_desktop()
    root = tk.Tk()
    widget_inst = DesktopWidget(root)
    setup_single_instance_listener(widget_inst)
    root.mainloop()


if __name__ == "__main__":
    main()
