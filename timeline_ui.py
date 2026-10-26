"""
timeline_ui.py — Visual Activity Timeline for Time Tracker AI 2.

Displays a clean, desktop-friendly chronological timeline for any selected
date. Reuses all existing ai_timeline.py logic for loading, grouping, enriching
sessions, and persisting user edits. Adds no new database tables or columns.

Phase 2 extension points
------------------------
Each session dict already contains:
    - "kind"              str      "active" | "idle"
    - "app"               str      process name
    - "title"             str      window title
    - "start" / "end"     datetime UTC-aware
    - "duration_seconds"  float
    - "ai_description"    str | None
    - "user_description"  str | None   (user correction, persisted in DB)
    - "confidence"        float | None (0.0–1.0)
    - "is_uncertain"      bool
    - "source"            str | None   ("evidence" | "AI" | "vision" | …)
    - "url"               str | None
    - "observation_ids"   list[int]
    - "session_key"       str          (stable 16-char hash, DB PK for edits)

Phase 2 can add "task_category" (str) and "task_confidence" (float) to any
session without touching this file — the detail panel reads all session keys
dynamically via _DETAIL_FIELDS.

Usage
-----
    python timeline_ui.py              # Today
    python timeline_ui.py 2026-10-18   # Specific date
    python main.py ui [YYYY-MM-DD]     # Via main dispatcher

Keyboard shortcuts
------------------
    F5                Refresh / re-enrich current day
    Ctrl+E / Enter    Edit selected session description
    Ctrl+D            Delete user edit (restore AI description)
    Escape            Close edit panel
    ←/→               Previous / next day
"""

from __future__ import annotations

import sqlite3
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tkinter import (
    BooleanVar,
    END,
    Event,
    StringVar,
    Text,
    Tk,
    messagebox,
    simpledialog,
)
from tkinter import ttk

# ---------------------------------------------------------------------------
# Resolve project root and import ai_timeline helpers
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import ai_timeline as tl
from activity_report import DB_PATH, format_duration

# ---------------------------------------------------------------------------
# Colours & layout constants
# ---------------------------------------------------------------------------

COLORS = {
    "bg":           "#1e1e2e",   # main background (dark)
    "surface":      "#2a2a3e",   # card / panel background
    "border":       "#3a3a55",   # subtle border
    "accent":       "#7c6af7",   # purple accent (active sessions)
    "idle":         "#3d5066",   # muted blue-grey (idle)
    "uncertain":    "#c9a227",   # amber (uncertain description)
    "edited":       "#3ba55c",   # green (user-corrected)
    "text":         "#cdd6f4",   # main text
    "subtext":      "#8899aa",   # secondary text
    "highlight_bg": "#3a3a55",   # selected row
    "header":       "#11111b",   # header/footer
    "danger":       "#f38ba8",   # error/danger
    "white":        "#ffffff",
}

FONT_BODY   = ("Segoe UI", 10)
FONT_MONO   = ("Cascadia Code", 9)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_SMALL  = ("Segoe UI", 9)
FONT_HEADER = ("Segoe UI", 12, "bold")
FONT_TITLE  = ("Segoe UI", 14, "bold")

ROW_HEIGHT      = 52    # pixels per timeline row
MIN_BLOCK_H     = 8     # minimum drawn block height (px)
CANVAS_PAD_L    = 120   # left margin for time labels (px)
CANVAS_PAD_R    = 20
CANVAS_PAD_TOP  = 10
BLOCK_W_FRAC    = 0.72  # fraction of canvas width used for blocks

# Phase 2 extension: fields shown in detail panel
# Add ("task_category", "Task Category") etc. here when Phase 2 is wired in.
_DETAIL_FIELDS: list[tuple[str, str]] = [
    ("kind",            "Kind"),
    ("app",             "Application"),
    ("url",             "URL"),
    ("source",          "Description source"),
    ("confidence",      "AI confidence"),
    ("is_uncertain",    "Uncertain"),
    ("observation_ids", "Observation IDs"),
    ("session_key",     "Session key"),
    # Phase 2 slots (will show "—" if key absent):
    # ("task_category",  "Task category"),
    # ("task_confidence","Task confidence"),
]


# ---------------------------------------------------------------------------
# Data loading (runs on a background thread to keep UI responsive)
# ---------------------------------------------------------------------------


def load_sessions_for_date(
    selected: date,
    refresh_ai: bool = False,
) -> tuple[list[dict], str]:
    """
    Load, group and enrich sessions for `selected`.
    Returns (sessions, error_message).  error_message is "" on success.
    """
    if not DB_PATH.exists():
        return [], f"Database not found:\n{DB_PATH}\n\nStart the tracker first."

    day_start = datetime.combine(selected, datetime.min.time()).astimezone()
    day_end   = day_start + timedelta(days=1)

    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        tl.ensure_timeline_edits(db)
        observations = tl.load_observations(db, day_start, day_end)

        if not observations:
            return [], ""

        visits   = tl.load_browser_visits(db, day_start, day_end, datetime.now().astimezone())
        sessions = tl.group_into_sessions(observations, visits)

        tl.enrich_all_sessions(db, sessions, visits, refresh=refresh_ai, verbose=False)

        for s in sessions:
            s["user_description"] = tl.get_user_edit(db, s["session_key"])

        num = 1
        for s in sessions:
            s["_display_number"] = num
            num += 1

        return sessions, ""
    finally:
        db.close()


def save_edit(session_key: str, description: str) -> None:
    """Persist a user description correction to the database."""
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        tl.ensure_timeline_edits(db)
        tl.save_user_edit(db, session_key, description)
    finally:
        db.close()


def delete_edit(session_key: str) -> bool:
    """Remove a user correction; returns True if a row was deleted."""
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        tl.ensure_timeline_edits(db)
        return tl.delete_user_edit(db, session_key)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helper formatters
# ---------------------------------------------------------------------------


def _fmt_time(dt: datetime) -> str:
    return dt.astimezone().strftime("%H:%M:%S")


def _conf_str(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.0%}"
    except (TypeError, ValueError):
        return str(val)


def _session_label(s: dict) -> str:
    """Single-line label for the canvas block."""
    if s["kind"] == "idle":
        return f"  Idle  ({format_duration(s['duration_seconds'])})"
    desc = s.get("user_description") or s.get("ai_description") or ""
    if not desc:
        return f"  {s.get('app', 'Unknown')}"
    max_chars = 80
    if len(desc) > max_chars:
        desc = desc[:max_chars - 1] + "…"
    return f"  {desc}"


def _block_color(s: dict) -> str:
    if s["kind"] == "idle":
        return COLORS["idle"]
    if s.get("user_description"):
        return COLORS["edited"]
    if s.get("is_uncertain"):
        return COLORS["uncertain"]
    return COLORS["accent"]


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------


class TimelineApp(Tk):
    def __init__(self, initial_date: date | None = None):
        super().__init__()

        self._selected_date = initial_date or date.today()
        self._sessions: list[dict] = []
        self._selected_idx: int | None = None
        self._loading = False

        self.title("Time Tracker AI — Activity Timeline")
        self.configure(bg=COLORS["bg"])
        self.geometry("1100x720")
        self.minsize(820, 500)

        # Apply a consistent dark ttk theme
        self._apply_theme()
        self._build_ui()

        self.bind("<F5>", lambda _: self._refresh())
        self.bind("<Left>", lambda _: self._prev_day())
        self.bind("<Right>", lambda _: self._next_day())
        self.bind("<Return>", lambda _: self._edit_selected())
        self.bind("<Control-e>", lambda _: self._edit_selected())
        self.bind("<Control-d>", lambda _: self._delete_edit_selected())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.after(50, self._refresh)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame",       background=COLORS["bg"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Header.TFrame", background=COLORS["header"])
        style.configure("TLabel",        background=COLORS["bg"],
                        foreground=COLORS["text"], font=FONT_BODY)
        style.configure("Header.TLabel", background=COLORS["header"],
                        foreground=COLORS["text"], font=FONT_BOLD)
        style.configure("Title.TLabel",  background=COLORS["header"],
                        foreground=COLORS["white"], font=FONT_TITLE)
        style.configure("Sub.TLabel",    background=COLORS["bg"],
                        foreground=COLORS["subtext"], font=FONT_SMALL)
        style.configure("Surface.TLabel", background=COLORS["surface"],
                        foreground=COLORS["text"], font=FONT_BODY)
        style.configure("TButton",       font=FONT_BODY,
                        background=COLORS["surface"], foreground=COLORS["text"],
                        borderwidth=0, relief="flat")
        style.map("TButton",
                  background=[("active", COLORS["accent"])],
                  foreground=[("active", COLORS["white"])])
        style.configure("Accent.TButton", background=COLORS["accent"],
                        foreground=COLORS["white"], font=FONT_BOLD, borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#6a58e0")])
        style.configure("TScrollbar",    background=COLORS["surface"],
                        troughcolor=COLORS["bg"], borderwidth=0, arrowsize=12)
        style.configure("TCheckbutton",  background=COLORS["bg"],
                        foreground=COLORS["text"], font=FONT_BODY)
        style.configure("TSeparator",    background=COLORS["border"])

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────
        hdr = ttk.Frame(self, style="Header.TFrame", padding=(12, 8))
        hdr.pack(fill="x", side="top")

        ttk.Button(hdr, text="◀", width=3, style="TButton",
                   command=self._prev_day).pack(side="left", padx=(0, 4))
        ttk.Button(hdr, text="▶", width=3, style="TButton",
                   command=self._next_day).pack(side="left", padx=(0, 12))

        self._date_var = StringVar()
        ttk.Label(hdr, textvariable=self._date_var,
                  style="Title.TLabel").pack(side="left")

        self._status_var = StringVar(value="Loading…")
        ttk.Label(hdr, textvariable=self._status_var,
                  style="Header.TLabel",
                  foreground=COLORS["subtext"]).pack(side="left", padx=(16, 0))

        ttk.Button(hdr, text="⟳  Refresh", style="TButton",
                   command=self._refresh).pack(side="right", padx=(8, 0))

        self._idle_var = BooleanVar(value=True)
        ttk.Checkbutton(hdr, text="Show Idle", variable=self._idle_var,
                        command=self._render_canvas,
                        style="TCheckbutton").pack(side="right", padx=(0, 8))

        ttk.Button(hdr, text="✎  Edit", style="TButton",
                   command=self._edit_selected).pack(side="right", padx=(0, 4))

        # ── Main pane: canvas on left, detail on right ───────────────
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=0, pady=0)

        # Canvas column
        canvas_frame = ttk.Frame(pane, style="TFrame")
        pane.add(canvas_frame, weight=3)

        self._canvas_scroll = ttk.Scrollbar(canvas_frame, orient="vertical")
        self._canvas_scroll.pack(side="right", fill="y")

        from tkinter import Canvas
        self._canvas = Canvas(
            canvas_frame,
            bg=COLORS["bg"],
            highlightthickness=0,
            yscrollcommand=self._canvas_scroll.set,
            cursor="arrow",
        )
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas_scroll.config(command=self._canvas.yview)
        self._canvas.bind("<Configure>", lambda _: self._render_canvas())
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)

        # Detail column
        detail_outer = ttk.Frame(pane, style="Surface.TFrame")
        pane.add(detail_outer, weight=1)

        ttk.Label(detail_outer, text="Session Detail",
                  style="Surface.TLabel",
                  font=FONT_HEADER,
                  background=COLORS["surface"]).pack(
            fill="x", padx=12, pady=(12, 4))
        ttk.Separator(detail_outer, orient="horizontal").pack(
            fill="x", padx=8, pady=4)

        self._detail_text = Text(
            detail_outer,
            wrap="word",
            font=FONT_SMALL,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=8,
            cursor="arrow",
            state="disabled",
        )
        self._detail_text.pack(fill="both", expand=True)

        # Tags for coloured text in detail pane
        self._detail_text.tag_configure("heading",  foreground=COLORS["accent"],
                                        font=FONT_BOLD)
        self._detail_text.tag_configure("value",    foreground=COLORS["text"],
                                        font=FONT_BODY)
        self._detail_text.tag_configure("subtext",  foreground=COLORS["subtext"],
                                        font=FONT_SMALL)
        self._detail_text.tag_configure("edited",   foreground=COLORS["edited"],
                                        font=FONT_BOLD)
        self._detail_text.tag_configure("uncertain",foreground=COLORS["uncertain"],
                                        font=FONT_BOLD)
        self._detail_text.tag_configure("error",    foreground=COLORS["danger"],
                                        font=FONT_BODY)

        # Edit / delete buttons in detail pane
        btn_bar = ttk.Frame(detail_outer, style="Surface.TFrame", padding=(8, 6))
        btn_bar.pack(fill="x", side="bottom")
        ttk.Button(btn_bar, text="✎  Edit description",
                   style="Accent.TButton",
                   command=self._edit_selected).pack(side="left")
        ttk.Button(btn_bar, text="✕  Clear edit",
                   style="TButton",
                   command=self._delete_edit_selected).pack(side="left", padx=(6, 0))

        # ── Footer ──────────────────────────────────────────────────
        foot = ttk.Frame(self, style="Header.TFrame", padding=(12, 5))
        foot.pack(fill="x", side="bottom")
        ttk.Label(
            foot,
            text="F5 Refresh   ←/→ Change day   Enter/Ctrl+E Edit   Ctrl+D Clear edit",
            style="Header.TLabel",
            foreground=COLORS["subtext"],
            font=FONT_SMALL,
        ).pack(side="left")

    # ------------------------------------------------------------------
    # Data loading (threaded)
    # ------------------------------------------------------------------

    def _refresh(self, *, refresh_ai: bool = False):
        if self._loading:
            return
        self._loading = True
        self._date_var.set(str(self._selected_date))
        self._status_var.set("  Loading…")
        self._sessions = []
        self._selected_idx = None
        self._render_canvas()
        self._show_detail(None)

        def _worker():
            sessions, err = load_sessions_for_date(
                self._selected_date, refresh_ai=refresh_ai
            )
            self.after(0, lambda: self._on_data_ready(sessions, err))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_data_ready(self, sessions: list[dict], err: str):
        self._loading = False
        if err:
            self._status_var.set("  ⚠  Error loading data")
            self._show_error(err)
            return

        self._sessions = sessions
        active = sum(1 for s in sessions if s["kind"] != "idle")
        idle   = sum(1 for s in sessions if s["kind"] == "idle")
        total  = format_duration(sum(s["duration_seconds"] for s in sessions if s["kind"] != "idle"))
        self._status_var.set(
            f"  {active} sessions · {idle} idle gap(s) · {total} active"
        )
        if not sessions:
            self._status_var.set("  No activity recorded for this date.")

        self._render_canvas()

    # ------------------------------------------------------------------
    # Canvas rendering
    # ------------------------------------------------------------------

    def _visible_sessions(self) -> list[dict]:
        show_idle = self._idle_var.get()
        return [s for s in self._sessions if show_idle or s["kind"] != "idle"]

    def _render_canvas(self):
        c = self._canvas
        c.delete("all")

        sessions = self._visible_sessions()
        if not sessions:
            c.create_text(
                max(c.winfo_width(), 200) // 2, 60,
                text="No sessions to display." if self._sessions
                     else "Loading…" if self._loading
                     else "No activity recorded.",
                fill=COLORS["subtext"], font=FONT_HEADER, anchor="center"
            )
            c.configure(scrollregion=(0, 0, c.winfo_width(), 120))
            return

        # Calculate time bounds
        day_start = sessions[0]["start"]
        day_end   = sessions[-1]["end"]
        total_secs = max(1.0, (day_end - day_start).total_seconds())

        cw = max(c.winfo_width(), 400)
        block_w = int(cw * BLOCK_W_FRAC)
        block_x = CANVAS_PAD_L
        total_h = CANVAS_PAD_TOP + len(sessions) * ROW_HEIGHT + 20

        c.configure(scrollregion=(0, 0, cw, total_h))

        # Draw each session block
        for idx, s in enumerate(sessions):
            y_top    = CANVAS_PAD_TOP + idx * ROW_HEIGHT
            y_bottom = y_top + ROW_HEIGHT - 4
            mid_y    = (y_top + y_bottom) // 2

            is_selected = (idx == self._selected_idx)
            bg = _block_color(s)

            # Selection highlight extends full width
            if is_selected:
                c.create_rectangle(
                    0, y_top, cw, y_bottom + 4,
                    fill=COLORS["highlight_bg"], outline="", tags=f"row{idx}"
                )

            # Duration bar (proportional width inside block area)
            dur_frac = min(1.0, s["duration_seconds"] / total_secs)
            bar_w    = max(MIN_BLOCK_H, int(block_w * dur_frac))
            bar_h    = y_bottom - y_top

            c.create_rectangle(
                block_x, y_top + 2,
                block_x + bar_w, y_bottom - 2,
                fill=bg, outline="", tags=f"row{idx}"
            )

            # Time labels on the left
            c.create_text(
                CANVAS_PAD_L - 6, mid_y,
                text=_fmt_time(s["start"]),
                fill=COLORS["subtext"], font=FONT_SMALL, anchor="e",
                tags=f"row{idx}"
            )

            # Session label inside / beside bar
            label = _session_label(s)
            label_x = block_x + min(bar_w + 6, block_w - 4)
            anchor   = "w" if bar_w < block_w * 0.4 else "w"
            text_fill = COLORS["text"] if is_selected else COLORS["text"]
            c.create_text(
                label_x, mid_y,
                text=label,
                fill=text_fill, font=FONT_BODY,
                anchor="w", width=cw - label_x - CANVAS_PAD_R,
                tags=f"row{idx}"
            )

            # Uncertainty / edited badge on the right edge
            badge = ""
            if s.get("user_description"):
                badge = "✎"
                badge_color = COLORS["edited"]
            elif s.get("is_uncertain"):
                badge = "?"
                badge_color = COLORS["uncertain"]
            else:
                badge_color = COLORS["subtext"]

            if badge:
                c.create_text(
                    cw - CANVAS_PAD_R - 4, mid_y,
                    text=badge, fill=badge_color, font=FONT_BOLD,
                    anchor="e", tags=f"row{idx}"
                )

            # Thin separator line
            c.create_line(
                0, y_bottom + 3, cw, y_bottom + 3,
                fill=COLORS["border"], width=1, tags=f"row{idx}"
            )

    def _row_index_at(self, y: int) -> int | None:
        """Return the session index at canvas pixel y, or None."""
        sessions = self._visible_sessions()
        for idx in range(len(sessions)):
            y_top    = CANVAS_PAD_TOP + idx * ROW_HEIGHT
            y_bottom = y_top + ROW_HEIGHT
            if y_top <= y < y_bottom:
                return idx
        return None

    def _on_canvas_click(self, event: Event):
        # Adjust for scroll position
        canvas_y = self._canvas.canvasy(event.y)
        idx = self._row_index_at(int(canvas_y))
        if idx is None:
            return
        self._selected_idx = idx
        self._render_canvas()
        sessions = self._visible_sessions()
        self._show_detail(sessions[idx] if idx < len(sessions) else None)

    def _on_canvas_double_click(self, event: Event):
        self._on_canvas_click(event)
        self._edit_selected()

    def _on_mousewheel(self, event: Event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------

    def _show_detail(self, session: dict | None):
        t = self._detail_text
        t.config(state="normal")
        t.delete("1.0", END)

        if session is None:
            t.insert(END, "Select a session to inspect its details.\n", "subtext")
            t.config(state="disabled")
            return

        def _write(label: str, value: str, tag: str = "value"):
            t.insert(END, f"{label}\n", "heading")
            t.insert(END, f"  {value}\n\n", tag)

        # Description (most prominent)
        user_desc = session.get("user_description")
        ai_desc   = session.get("ai_description") or "—"

        if user_desc:
            _write("Description (user-edited)", user_desc, "edited")
        else:
            tag = "uncertain" if session.get("is_uncertain") else "value"
            _write("Description (AI-inferred)", ai_desc, tag)
            if session.get("is_uncertain"):
                t.insert(END, "  ⚠ Uncertain — evidence was insufficient.\n\n", "uncertain")

        # Timing
        start_s = _fmt_time(session["start"])
        end_s   = _fmt_time(session["end"])
        dur_s   = format_duration(session["duration_seconds"])
        _write("Time", f"{start_s} → {end_s}  ({dur_s})")

        # Structured fields from _DETAIL_FIELDS
        for key, label in _DETAIL_FIELDS:
            val = session.get(key)
            if val is None or val == "" or val == []:
                display = "—"
            elif key == "confidence":
                display = _conf_str(val)
            elif key == "observation_ids":
                display = ", ".join(str(i) for i in val)
            elif isinstance(val, bool):
                display = "Yes" if val else "No"
            else:
                display = str(val)
            _write(label, display)

        t.config(state="disabled")

    def _show_error(self, msg: str):
        t = self._detail_text
        t.config(state="normal")
        t.delete("1.0", END)
        t.insert(END, "Error\n", "heading")
        t.insert(END, msg, "error")
        t.config(state="disabled")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _prev_day(self):
        self._selected_date -= timedelta(days=1)
        self._selected_idx = None
        self._refresh()

    def _next_day(self):
        self._selected_date += timedelta(days=1)
        self._selected_idx = None
        self._refresh()

    # ------------------------------------------------------------------
    # Edit / delete
    # ------------------------------------------------------------------

    def _edit_selected(self):
        sessions = self._visible_sessions()
        if self._selected_idx is None or not sessions:
            messagebox.showinfo("No selection", "Click a session row first.")
            return
        if self._selected_idx >= len(sessions):
            return

        s = sessions[self._selected_idx]
        if s["kind"] == "idle":
            messagebox.showinfo("Idle period", "Idle periods cannot be edited.")
            return

        current = (
            s.get("user_description")
            or s.get("ai_description")
            or ""
        )
        new_desc = simpledialog.askstring(
            "Edit Description",
            f"Session #{s['_display_number']}  "
            f"{_fmt_time(s['start'])} – {_fmt_time(s['end'])}\n"
            f"App: {s.get('app', 'Unknown')}\n\n"
            "Enter a corrected activity description\n"
            "(leave blank to cancel, type 'clear' to remove edit):",
            initialvalue=current,
            parent=self,
        )

        if new_desc is None:
            return  # cancelled

        new_desc = new_desc.strip()

        if new_desc.lower() == "clear":
            deleted = delete_edit(s["session_key"])
            s["user_description"] = None
            msg = "User edit removed." if deleted else "No user edit existed."
            self._status_var.set(f"  {msg}")
        elif new_desc:
            save_edit(s["session_key"], new_desc)
            s["user_description"] = new_desc
            self._status_var.set("  Description saved.")
        else:
            return  # blank = cancel

        self._render_canvas()
        self._show_detail(s)

    def _delete_edit_selected(self):
        sessions = self._visible_sessions()
        if self._selected_idx is None or not sessions:
            return
        if self._selected_idx >= len(sessions):
            return
        s = sessions[self._selected_idx]
        if not s.get("user_description"):
            self._status_var.set("  No user edit to clear.")
            return
        if messagebox.askyesno(
            "Clear Edit",
            f"Remove your custom description and restore AI description?\n\n"
            f"Current: {s['user_description']}",
            parent=self,
        ):
            delete_edit(s["session_key"])
            s["user_description"] = None
            self._status_var.set("  User edit cleared.")
            self._render_canvas()
            self._show_detail(s)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self):
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    selected = None
    for arg in argv:
        if arg.startswith("-"):
            continue  # ignore flags silently for now
        # Every non-flag argument must be a valid YYYY-MM-DD date
        try:
            selected = date.fromisoformat(arg)
        except ValueError:
            print(f"Invalid date: {arg!r}. Use YYYY-MM-DD.")
            return 1

    app = TimelineApp(initial_date=selected)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
