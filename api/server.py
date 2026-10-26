"""
api/server.py — FastAPI backend for Time Tracker AI 2 web UI & desktop widget.

Binds to 127.0.0.1 only. Reuses existing ai_timeline.py functions.
Never touches tracker.db destructively.
"""

from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
import io
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Bootstrap: make the project root importable
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    _ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    _ROOT = Path(__file__).resolve().parent.parent

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import ai_timeline as tl
import api.activity_intelligence as activity_intel
import api.ai_coach_engine as ai_coach_engine
import api.autostart as autostart
import api.categories as categories_engine
import api.goals as goals_engine
import api.insights as insights_engine
import api.migrations as migrations
import api.notification_engine as notif_engine
import api.tracker_manager as tracker_manager
import api.windows_notifier as win_notifier
from activity_report import DB_PATH, format_duration, load_browser_visits

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Time Tracker AI 2 — API",
    description="Local-only backend for the Time Tracker AI web dashboard & desktop widget.",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

# Allow localhost origins for Vite dev and preview servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


_supervisor_stop_event = threading.Event()
_supervisor_thread: Optional[threading.Thread] = None


def _notification_supervisor_worker():
    """Background worker for schedule-mismatch, idle alerting, and missed-activity recovery."""
    time.sleep(1.0)
    # Check for inactive gaps on startup
    try:
        if DB_PATH.exists():
            c = sqlite3.connect(str(DB_PATH), timeout=5)
            c.row_factory = sqlite3.Row
            notif_engine.detect_missed_activity_gap(c)
            c.close()
    except Exception:
        pass

    while not _supervisor_stop_event.is_set():
        try:
            if DB_PATH.exists():
                c = sqlite3.connect(str(DB_PATH), timeout=5)
                c.row_factory = sqlite3.Row
                try:
                    is_tracking = tracker_manager.is_tracking_active()
                    if is_tracking:
                        idle_s = tracker_manager.get_idle_seconds()
                        active_task = tracker_manager.get_active_task()
                        notif_engine.evaluate_idle_condition(c, idle_s, is_tracking=True)
                        notif_engine.evaluate_schedule_mismatch(c, active_task, is_tracking=True)
                    # Evaluate time-block start reminders (active whether tracking is on or off)
                    notif_engine.evaluate_time_block_reminders(c, is_tracking=is_tracking)
                    # Evaluate missed-block recovery prompts
                    notif_engine.evaluate_missed_block_recovery(c, is_tracking=is_tracking)
                finally:
                    c.close()
        except Exception:
            pass
        _supervisor_stop_event.wait(3.0)


@app.on_event("startup")
def on_startup():
    try:
        migrations.run_migrations()
    except Exception as e:
        logger.warning("Database migration during startup warning: %s", e)
    try:
        win_notifier.register_windows_app_identity()
    except Exception as e:
        logger.debug("Windows identity registration warning: %s", e)
    global _supervisor_thread
    _supervisor_stop_event.clear()
    _supervisor_thread = threading.Thread(
        target=_notification_supervisor_worker,
        daemon=True,
        name="notif_supervisor",
    )
    _supervisor_thread.start()


@app.on_event("shutdown")
def on_shutdown():
    _supervisor_stop_event.set()


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    """Open a read/write connection to tracker.db."""
    if not DB_PATH.exists():
        try:
            migrations.run_migrations()
        except Exception:
            pass
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=f"tracker.db not found at {DB_PATH}. Start the tracker first.",
        )
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Pydantic response & request models
# ---------------------------------------------------------------------------

class SessionModel(BaseModel):
    display_number: int
    session_key: str
    kind: str                       # "active" | "idle"
    app: str
    title: str
    start: str                      # ISO-8601
    end: str
    duration_seconds: float
    duration_label: str
    description: Optional[str]      # user_description preferred, else ai_description
    ai_description: Optional[str]
    user_description: Optional[str]
    is_uncertain: bool
    confidence: Optional[float]
    source: Optional[str]
    url: Optional[str]
    observation_ids: list[int]
    is_ongoing: bool = False

    task_category: Optional[str] = None
    task_confidence: Optional[float] = None

    # Custom category & classification fields
    domain: Optional[str] = None
    task: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_color: Optional[str] = None
    category_type: Optional[str] = None
    category_source: Optional[str] = None

    # Activity Intelligence & Specific Attribution
    activity_name: Optional[str] = None
    specific_task: Optional[str] = None
    site_name: Optional[str] = None
    document_name: Optional[str] = None
    context_label: Optional[str] = None
    is_browser: bool = False


class StatsModel(BaseModel):
    date: str
    active_seconds: float
    idle_seconds: float
    active_label: str
    idle_label: str
    session_count: int
    app_breakdown: list[dict]       # [{app, seconds, label, pct}]
    has_data: bool

    # Explicit productive work metrics
    productive_work_seconds: float = 0.0
    productive_work_label: str = "0s"
    total_tracked_seconds: float = 0.0
    total_tracked_label: str = "0s"
    focus_seconds: float = 0.0
    focus_label: str = "0s"
    distraction_seconds: float = 0.0
    distraction_label: str = "0s"
    unclassified_seconds: float = 0.0
    unclassified_label: str = "0s"


class WeeklyDayItem(BaseModel):
    date: str
    active_seconds: float
    label: str
    productive_work_seconds: float = 0.0
    productive_work_label: str = "0s"
    focus_seconds: float = 0.0
    distraction_seconds: float = 0.0


class WeeklyStatsModel(BaseModel):
    days: list[dict]                # [{date, active_seconds, label, productive_work_seconds, ...}]


class EditRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)


class ActiveTaskModel(BaseModel):
    observation_id: int
    kind: str
    app: str
    title: str
    start_time: str
    is_open: bool = True
    user_task: Optional[str] = None
    activity_name: Optional[str] = None
    specific_task: Optional[str] = None
    site_name: Optional[str] = None
    context_label: Optional[str] = None
    is_browser: bool = False
    category_id: Optional[int] = None
    category_name: Optional[str] = None


class AssignTaskRequest(BaseModel):
    task_name: str = Field(..., min_length=1, max_length=200)
    category_id: Optional[int] = None
    observation_id: Optional[int] = None


class TrackingStatusResponse(BaseModel):
    is_tracking: bool
    pid: Optional[int] = None
    status_text: str
    message: str
    active_task: Optional[ActiveTaskModel] = None


class AutostartStatusResponse(BaseModel):
    enabled: bool
    command: str
    supported: bool = True
    message: str = ""


# Custom Category Models
class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field("#8b5cf6", min_length=4, max_length=20)
    type: str = Field("work", pattern="^(focus|work|personal|distraction)$")


class CategoryUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field("#8b5cf6", min_length=4, max_length=20)
    type: str = Field("work", pattern="^(focus|work|personal|distraction)$")


class RuleCreateRequest(BaseModel):
    category_id: int
    match_type: str = Field(..., pattern="^(domain|url|app|title_contains)$")
    pattern: str = Field(..., min_length=1, max_length=300)
    priority: int = 10


class SessionCategoryRequest(BaseModel):
    category_id: int


# Goal & Time-Block Models
class GoalCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    metric: str = Field(..., pattern="^(work_time|focus_time|distraction_time|category_time)$")
    target_seconds: int = Field(..., gt=0)
    is_inversion: bool = False
    category_id: Optional[int] = None
    period: str = "daily"


class GoalUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    target_seconds: int = Field(..., gt=0)
    is_inversion: bool = False
    is_active: bool = True


class TimeBlockCreateRequest(BaseModel):
    date: str
    start_time: str
    end_time: str
    title: str = Field(..., min_length=1, max_length=150)
    category_id: Optional[int] = None


class TimeBlockUpdateRequest(BaseModel):
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    title: Optional[str] = None
    category_id: Optional[int] = None


class TimeBlockDuplicateRequest(BaseModel):
    target_date: Optional[str] = None
    time_offset_minutes: Optional[int] = 0


class TimeBlockOverlapCheckRequest(BaseModel):
    date: str
    start_time: str
    end_time: str
    exclude_id: Optional[int] = None


class ManualEntryRequest(BaseModel):
    task_name: str = Field(..., min_length=1, max_length=200)
    start_time: str
    end_time: str
    category_id: Optional[int] = None
    notes: Optional[str] = None
    recovery_gap_id: Optional[int] = None


class RecoveryPromptResolveRequest(BaseModel):
    gap_id: int
    action: str = "skip"  # "skip" | "snooze"


class SnoozeAlertRequest(BaseModel):
    alert_type: str = "focus"  # "focus" | "idle"
    minutes: int = 15


class SettingsUpdateRequest(BaseModel):
    user_name: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    windows_toasts_enabled: Optional[bool] = None
    notification_sound: Optional[str] = None  # "default" | "silent" | "custom"
    idle_alert_threshold_minutes: Optional[int] = None
    idle_alerts_enabled: Optional[bool] = None
    focus_mismatch_alerts_enabled: Optional[bool] = None
    mismatch_grace_minutes: Optional[int] = None
    distraction_cooldown_minutes: Optional[int] = None
    missed_recovery_threshold_minutes: Optional[int] = None
    missed_recovery_enabled: Optional[bool] = None
    missed_block_recovery_enabled: Optional[bool] = None
    time_block_reminders_enabled: Optional[bool] = None
    time_block_autostart_focus: Optional[bool] = None
    default_snooze_minutes: Optional[int] = None
    notification_rate_limit_seconds: Optional[int] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    overnight_suppression_enabled: Optional[bool] = None
    overnight_sleep_start: Optional[str] = None
    overnight_sleep_end: Optional[str] = None


class TimeBlockSnoozeRequest(BaseModel):
    minutes: int = Field(5, ge=1, le=60)


class TimeBlockRescheduleRequest(BaseModel):
    date: str
    start_time: str
    end_time: str


class AiCoachChatRequest(BaseModel):
    message: Optional[str] = Field(default="")
    selected_date: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None
    preset_action: Optional[str] = None


class AiCoachChatResponse(BaseModel):
    response: str
    grounded: bool = True
    sources: List[str] = []
    quick_actions: List[Dict[str, Any]] = []
    date_scope: str = ""
    meta: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Helper: convert session dict → SessionModel
# ---------------------------------------------------------------------------

def _session_to_model(s: dict, num: int) -> SessionModel:
    user_d = s.get("user_description")
    ai_d   = s.get("ai_description")
    cat    = s.get("category") or {}
    domain = s.get("domain") or cat.get("domain") or None
    task   = s.get("task")

    act = s.get("activity_meta") or activity_intel.derive_specific_activity(
        app=s.get("app", ""),
        title=s.get("title", ""),
        url=s.get("url", ""),
        task=task,
        category_name=cat.get("name") or s.get("category_name"),
        user_description=user_d,
    )
    act_name = act.get("activity_name")

    return SessionModel(
        display_number   = num,
        session_key      = s.get("session_key") or "",
        kind             = s.get("kind", "active"),
        app              = s.get("app", "Unknown"),
        title            = s.get("title", ""),
        start            = s["start"].isoformat(),
        end              = s["end"].isoformat(),
        duration_seconds = s.get("duration_seconds", 0.0),
        duration_label   = format_duration(s.get("duration_seconds", 0.0)),
        description      = user_d or ai_d or act_name,
        ai_description   = ai_d,
        user_description = user_d,
        is_uncertain     = bool(s.get("is_uncertain", act.get("is_uncertain", cat.get("is_uncertain", False)))),
        confidence       = s.get("confidence", cat.get("confidence")),
        source           = s.get("source") or cat.get("source"),
        url              = s.get("url") or None,
        observation_ids  = s.get("observation_ids", []),
        is_ongoing       = bool(s.get("is_ongoing", False)),
        domain           = domain,
        task             = task,
        task_category    = cat.get("name") or s.get("category_name"),
        task_confidence  = s.get("confidence", cat.get("confidence")),
        category_id      = cat.get("id") or s.get("category_id"),
        category_name    = cat.get("name") or s.get("category_name"),
        category_color   = cat.get("color") or s.get("category_color"),
        category_type    = cat.get("type") or s.get("category_type"),
        category_source  = cat.get("source") or s.get("category_source"),
        activity_name    = act_name,
        specific_task    = act.get("specific_task"),
        site_name        = act.get("site_name"),
        document_name    = act.get("document_name"),
        context_label    = act.get("context_label"),
        is_browser       = bool(act.get("is_browser", False)),
    )


# ---------------------------------------------------------------------------
# Helper: load + enrich sessions for a date
# ---------------------------------------------------------------------------

def _load_sessions(
    selected: date,
    refresh_ai: bool = False,
) -> tuple[list[SessionModel], list[dict]]:
    """Return (session_models, raw_sessions_for_stats)."""
    day_start = datetime.combine(selected, datetime.min.time()).astimezone()
    day_end   = day_start + timedelta(days=1)

    db = _db()
    try:
        observations = tl.load_observations(db, day_start, day_end)
        if not observations:
            return [], []

        visits   = load_browser_visits(db, day_start, day_end, datetime.now().astimezone())
        sessions = tl.group_into_sessions(observations, visits)
        tl.enrich_all_sessions(
            db,
            sessions,
            visits,
            refresh=refresh_ai,
            verbose=False,
            allow_network=refresh_ai,
        )

        # Preload categories, rules, and manual overrides
        cached_rules = categories_engine.get_all_rules(db)
        cat_rows = db.execute("SELECT id, name, color, type FROM categories").fetchall()
        cached_categories = {r["id"]: dict(r) for r in cat_rows}
        override_rows = db.execute("SELECT session_key, category_id FROM session_categories").fetchall()
        cached_overrides = {r["session_key"]: r["category_id"] for r in override_rows}

        for s in sessions:
            s["user_description"] = tl.get_user_edit(db, s["session_key"])
            cat = categories_engine.match_category(
                db,
                s.get("app", ""),
                s.get("title", ""),
                s.get("url", ""),
                session_key=s.get("session_key"),
                rules=cached_rules,
                categories_by_id=cached_categories,
                manual_overrides=cached_overrides,
                task=s.get("task"),
                obs_ids=s.get("observation_ids", []),
            )
            s["category"] = cat
            s["category_id"] = cat.get("id")
            s["category_name"] = cat.get("name")
            s["category_color"] = cat.get("color")
            s["category_type"] = cat.get("type")
            s["category_source"] = cat.get("source")
            if cat.get("domain") and not s.get("domain"):
                s["domain"] = cat.get("domain")
            if cat.get("is_uncertain") is not None and not s.get("is_uncertain"):
                s["is_uncertain"] = cat.get("is_uncertain")
            if s.get("confidence") is None and cat.get("confidence") is not None:
                s["confidence"] = cat.get("confidence")

            # Activity intelligence attribution
            act = activity_intel.derive_specific_activity(
                app=s.get("app", ""),
                title=s.get("title", ""),
                url=s.get("url", ""),
                task=s.get("task"),
                category_name=s.get("category_name"),
                user_description=s.get("user_description"),
            )
            s["activity_meta"] = act
            s["activity_name"] = act["activity_name"]
            s["specific_task"] = act["specific_task"]
            s["site_name"] = act["site_name"]
            s["document_name"] = act["document_name"]
            s["context_label"] = act["context_label"]
            s["is_browser"] = act["is_browser"]
            if act["is_uncertain"] and not s.get("is_uncertain"):
                s["is_uncertain"] = True

        models = []
        num = 1
        for s in sessions:
            s["_display_number"] = num
            models.append(_session_to_model(s, num))
            num += 1

        return models, sessions
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Core Timeline & Stats Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "db": str(DB_PATH), "db_exists": DB_PATH.exists()}


@app.get("/api/timeline/{date_str}", response_model=list[SessionModel])
def get_timeline(
    date_str: str,
    refresh_ai: bool = Query(False, description="Force AI re-classification"),
):
    """Return enriched session list for the requested date (YYYY-MM-DD)."""
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {date_str!r}. Use YYYY-MM-DD.")

    models, _ = _load_sessions(selected, refresh_ai=refresh_ai)
    return models


@app.get("/api/stats/{date_str}", response_model=StatsModel)
def get_stats(date_str: str):
    """Return daily summary stats for the requested date."""
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {date_str!r}.")

    _, raw = _load_sessions(selected)

    active_secs = sum(s["duration_seconds"] for s in raw if s["kind"] != "idle")
    idle_secs   = sum(s["duration_seconds"] for s in raw if s["kind"] == "idle")

    # Productive work strictly includes "focus" and "work" categories, excluding distractions and personal
    productive_work_secs = sum(
        s["duration_seconds"]
        for s in raw
        if s["kind"] != "idle" and (
            s.get("category_type") in ("focus", "work") or
            (s.get("category") or {}).get("type") in ("focus", "work")
        )
    )
    focus_secs = sum(
        s["duration_seconds"]
        for s in raw
        if s["kind"] != "idle" and (
            s.get("category_type") == "focus" or
            (s.get("category") or {}).get("type") == "focus"
        )
    )
    distraction_secs = sum(
        s["duration_seconds"]
        for s in raw
        if s["kind"] != "idle" and (
            s.get("category_type") == "distraction" or
            (s.get("category") or {}).get("type") == "distraction"
        )
    )
    unclassified_secs = max(0.0, active_secs - productive_work_secs - distraction_secs)

    # App breakdown (top apps by time, active only)
    app_totals: dict[str, float] = {}
    for s in raw:
        if s["kind"] == "idle":
            continue
        app_totals[s["app"]] = app_totals.get(s["app"], 0.0) + s["duration_seconds"]

    sorted_apps = sorted(app_totals.items(), key=lambda x: x[1], reverse=True)
    breakdown = []
    for app_name, secs in sorted_apps[:10]:
        pct = round(secs / active_secs * 100, 1) if active_secs > 0 else 0.0
        breakdown.append({
            "app":     app_name,
            "seconds": secs,
            "label":   format_duration(secs),
            "pct":     pct,
        })

    active_sessions = [s for s in raw if s["kind"] != "idle"]
    return StatsModel(
        date                    = date_str,
        active_seconds          = round(active_secs, 1),
        idle_seconds            = round(idle_secs, 1),
        active_label            = format_duration(active_secs),
        idle_label              = format_duration(idle_secs),
        session_count           = len(active_sessions),
        app_breakdown           = breakdown,
        has_data                = len(raw) > 0,
        productive_work_seconds = round(productive_work_secs, 1),
        productive_work_label   = format_duration(productive_work_secs),
        total_tracked_seconds   = round(active_secs, 1),
        total_tracked_label     = format_duration(active_secs),
        focus_seconds           = round(focus_secs, 1),
        focus_label             = format_duration(focus_secs),
        distraction_seconds     = round(distraction_secs, 1),
        distraction_label       = format_duration(distraction_secs),
        unclassified_seconds    = round(unclassified_secs, 1),
        unclassified_label      = format_duration(unclassified_secs),
    )


@app.get("/api/stats/weekly/{date_str}", response_model=WeeklyStatsModel)
def get_weekly_stats(date_str: str):
    """Return active-time and productive-work totals for the 7 days ending on date_str."""
    try:
        end_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {date_str!r}.")

    if not DB_PATH.exists():
        return WeeklyStatsModel(days=[])

    db = _db()
    try:
        cached_rules = categories_engine.get_all_rules(db)
        cat_rows = db.execute("SELECT id, name, color, type FROM categories").fetchall()
        cached_categories = {r["id"]: dict(r) for r in cat_rows}
        override_rows = db.execute("SELECT session_key, category_id FROM session_categories").fetchall()
        cached_overrides = {r["session_key"]: r["category_id"] for r in override_rows}

        days = []
        for i in range(6, -1, -1):
            d = end_date - timedelta(days=i)
            day_start = datetime.combine(d, datetime.min.time()).astimezone()
            day_end   = day_start + timedelta(days=1)
            observations = tl.load_observations(db, day_start, day_end)

            active_secs = 0.0
            productive_secs = 0.0
            focus_secs = 0.0
            distraction_secs = 0.0

            for o in observations:
                if o.get("kind") == "idle":
                    continue
                dur = o.get("duration_seconds", 0.0)
                active_secs += dur

                cat = categories_engine.match_category(
                    db,
                    o.get("app", ""),
                    o.get("title", ""),
                    o.get("url", ""),
                    rules=cached_rules,
                    categories_by_id=cached_categories,
                    manual_overrides=cached_overrides,
                    obs_ids=[o.get("id")] if o.get("id") else [],
                )
                c_type = cat.get("type", "work")
                if c_type in ("focus", "work"):
                    productive_secs += dur
                if c_type == "focus":
                    focus_secs += dur
                elif c_type == "distraction":
                    distraction_secs += dur

            days.append({
                "date":                    d.isoformat(),
                "active_seconds":          round(active_secs, 1),
                "label":                   format_duration(active_secs),
                "productive_work_seconds": round(productive_secs, 1),
                "productive_work_label":   format_duration(productive_secs),
                "focus_seconds":           round(focus_secs, 1),
                "distraction_seconds":     round(distraction_secs, 1),
            })
    finally:
        db.close()

    return WeeklyStatsModel(days=days)


@app.post("/api/timeline/{date_str}/sessions/{session_key}/edit")
def edit_session(date_str: str, session_key: str, body: EditRequest):
    """Persist a user-written description for a session."""
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {date_str!r}.")

    db = _db()
    try:
        tl.ensure_timeline_edits(db)
        tl.save_user_edit(db, session_key, body.description)
    finally:
        db.close()

    return {"status": "saved", "session_key": session_key}


@app.delete("/api/timeline/{date_str}/sessions/{session_key}/edit")
def delete_session_edit(date_str: str, session_key: str):
    """Remove a user description so the AI description is shown again."""
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {date_str!r}.")

    db = _db()
    try:
        tl.ensure_timeline_edits(db)
        deleted = tl.delete_user_edit(db, session_key)
    finally:
        db.close()

    return {"status": "deleted" if deleted else "not_found", "session_key": session_key}


@app.get("/api/dates/active")
def get_active_dates(limit: int = Query(30, ge=1, le=365)):
    """Return the most recent dates that have recorded observations in local calendar days."""
    if not DB_PATH.exists():
        return {"dates": []}
    db = _db()
    try:
        rows = db.execute(
            """
            SELECT DISTINCT date(start_time, 'localtime') as d
            FROM observations
            WHERE kind = 'active'
            ORDER BY d DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        db.close()
    return {"dates": [r["d"] for r in rows if r["d"]]}


# ---------------------------------------------------------------------------
# Categories & Rules Routes
# ---------------------------------------------------------------------------

@app.get("/api/categories")
def get_categories():
    """Return all defined activity categories."""
    db = _db()
    try:
        return categories_engine.get_all_categories(db)
    finally:
        db.close()


@app.post("/api/categories")
def create_category(body: CategoryCreateRequest):
    """Create a new custom category."""
    db = _db()
    try:
        return categories_engine.create_category(db, body.name, body.color, body.type)
    finally:
        db.close()


@app.put("/api/categories/{cat_id}")
def update_category(cat_id: int, body: CategoryUpdateRequest):
    """Update an existing category."""
    db = _db()
    try:
        updated = categories_engine.update_category(db, cat_id, body.name, body.color, body.type)
        if not updated:
            raise HTTPException(status_code=404, detail="Category not found.")
        return updated
    finally:
        db.close()


@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    """Delete a category and its associated rules."""
    db = _db()
    try:
        deleted = categories_engine.delete_category(db, cat_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Category not found.")
        return {"status": "deleted", "id": cat_id}
    finally:
        db.close()


@app.get("/api/categories/rules")
def get_rules():
    """Return all category classification rules."""
    db = _db()
    try:
        return categories_engine.get_all_rules(db)
    finally:
        db.close()


@app.post("/api/categories/rules")
def create_rule(body: RuleCreateRequest):
    """Create a new category matching rule."""
    db = _db()
    try:
        return categories_engine.create_rule(
            db, body.category_id, body.match_type, body.pattern, body.priority
        )
    finally:
        db.close()


@app.delete("/api/categories/rules/{rule_id}")
def delete_rule(rule_id: int):
    """Delete a rule."""
    db = _db()
    try:
        deleted = categories_engine.delete_rule(db, rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Rule not found.")
        return {"status": "deleted", "id": rule_id}
    finally:
        db.close()


@app.post("/api/timeline/{date_str}/sessions/{session_key}/category")
def override_session_category(date_str: str, session_key: str, body: SessionCategoryRequest):
    """Explicitly assign a category to a specific session."""
    db = _db()
    try:
        categories_engine.set_session_category_override(db, session_key, body.category_id)
        return {"status": "assigned", "session_key": session_key, "category_id": body.category_id}
    finally:
        db.close()


@app.delete("/api/timeline/{date_str}/sessions/{session_key}/category")
def remove_session_category_override(date_str: str, session_key: str):
    """Revert session category to rule-based classification."""
    db = _db()
    try:
        deleted = categories_engine.remove_session_category_override(db, session_key)
        return {"status": "reverted" if deleted else "not_overridden", "session_key": session_key}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Goals & Time-Block Routes
# ---------------------------------------------------------------------------

@app.get("/api/goals")
def get_goals():
    """Return all configured productivity goals."""
    db = _db()
    try:
        return goals_engine.get_goals(db)
    finally:
        db.close()


@app.post("/api/goals")
def create_goal(body: GoalCreateRequest):
    """Create a new goal."""
    db = _db()
    try:
        return goals_engine.create_goal(
            db,
            body.title,
            body.metric,
            body.target_seconds,
            is_inversion=body.is_inversion,
            category_id=body.category_id,
            period=body.period,
        )
    finally:
        db.close()


@app.put("/api/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalUpdateRequest):
    """Update goal settings."""
    db = _db()
    try:
        updated = goals_engine.update_goal(
            db, goal_id, body.title, body.target_seconds, body.is_inversion, body.is_active
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Goal not found.")
        return updated
    finally:
        db.close()


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int):
    """Delete a goal."""
    db = _db()
    try:
        deleted = goals_engine.delete_goal(db, goal_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Goal not found.")
        return {"status": "deleted", "id": goal_id}
    finally:
        db.close()


@app.get("/api/goals/progress/{date_str}")
def get_goals_progress(date_str: str):
    """Evaluate progress for all active goals on date_str."""
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    _, raw = _load_sessions(selected)
    db = _db()
    try:
        return goals_engine.evaluate_goals(db, date_str, [dict(s) for s in raw])
    finally:
        db.close()


@app.get("/api/time-blocks/current")
def get_current_time_block():
    """Return currently active scheduled time block for current local time."""
    db = _db()
    try:
        current = notif_engine.get_current_planned_block(db)
        return {"has_block": current is not None, "block": current}
    finally:
        db.close()


@app.get("/api/time-blocks/{date_str}")
def get_time_blocks(date_str: str):
    """Return all scheduled time blocks for date_str."""
    db = _db()
    try:
        return goals_engine.get_time_blocks(db, date_str)
    finally:
        db.close()


@app.post("/api/time-blocks")
def create_time_block(body: TimeBlockCreateRequest):
    """Create a planned time block schedule commitment."""
    db = _db()
    try:
        return goals_engine.create_time_block(
            db, body.date, body.start_time, body.end_time, body.title, body.category_id
        )
    finally:
        db.close()


@app.put("/api/time-blocks/{block_id}")
def update_time_block(block_id: int, body: TimeBlockUpdateRequest):
    """Update an existing time block (edit title/category or reschedule)."""
    db = _db()
    try:
        updated = goals_engine.update_time_block(
            db,
            block_id,
            block_date=body.date,
            start_time=body.start_time,
            end_time=body.end_time,
            title=body.title,
            category_id=body.category_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Time block not found.")
        return updated
    finally:
        db.close()


@app.post("/api/time-blocks/{block_id}/duplicate")
def duplicate_time_block(block_id: int, body: Optional[TimeBlockDuplicateRequest] = None):
    """Intentionally duplicate a time block commitment."""
    db = _db()
    try:
        target_date = body.target_date if body else None
        offset = body.time_offset_minutes if body else 0
        duplicated = goals_engine.duplicate_time_block(
            db, block_id, target_date=target_date, time_offset_minutes=offset
        )
        if not duplicated:
            raise HTTPException(status_code=404, detail="Time block not found.")
        return duplicated
    finally:
        db.close()


@app.post("/api/time-blocks/check-overlap")
def check_time_block_overlap(body: TimeBlockOverlapCheckRequest):
    """Check if a time window overlaps existing scheduled blocks."""
    db = _db()
    try:
        overlaps = goals_engine.check_time_block_overlaps(
            db, body.date, body.start_time, body.end_time, exclude_id=body.exclude_id
        )
        return {"has_overlap": len(overlaps) > 0, "overlaps": overlaps}
    finally:
        db.close()


@app.get("/api/time-blocks/summary/{date_str}")
def get_time_blocks_daily_summary(date_str: str):
    """Return unified 4-metric summary (Planned Time, Focus in Blocks, Plan Adherence, Distraction in Blocks)."""
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    _, raw = _load_sessions(selected)
    db = _db()
    try:
        return goals_engine.calculate_time_blocks_daily_summary(
            db, date_str, [dict(s) for s in raw]
        )
    finally:
        db.close()


@app.delete("/api/time-blocks/{block_id}")
def delete_time_block(block_id: int):
    """Delete a time block."""
    db = _db()
    try:
        deleted = goals_engine.delete_time_block(db, block_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Time block not found.")
        return {"status": "deleted", "id": block_id}
    finally:
        db.close()


@app.post("/api/time-blocks/{block_id}/start-focus")
def start_focus_for_time_block(block_id: int):
    """
    Make the block the active task and start a linked Focus Session using existing tracking/session functionality.
    """
    db = _db()
    try:
        return notif_engine.start_focus_for_time_block(db, block_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


@app.post("/api/time-blocks/{block_id}/snooze")
def snooze_time_block_reminder(block_id: int, body: Optional[TimeBlockSnoozeRequest] = None):
    """Postpone the reminder for this block without changing the scheduled block."""
    mins = body.minutes if body else 5
    db = _db()
    try:
        return notif_engine.snooze_time_block_reminder(db, block_id, minutes=mins)
    finally:
        db.close()


@app.post("/api/time-blocks/{block_id}/skip")
def skip_time_block(block_id: int):
    """Dismiss the reminder without deleting the block or recording fake work."""
    db = _db()
    try:
        return notif_engine.skip_time_block(db, block_id)
    finally:
        db.close()


@app.post("/api/time-blocks/{block_id}/reschedule")
def reschedule_time_block(block_id: int, body: TimeBlockRescheduleRequest):
    """Reschedule a time block to a new date and time window, resetting reminders."""
    db = _db()
    try:
        return notif_engine.reschedule_time_block(
            db,
            block_id,
            new_date=body.date,
            new_start_time=body.start_time,
            new_end_time=body.end_time,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


@app.get("/api/time-blocks/analysis/{date_str}")
def get_time_blocks_analysis(date_str: str):
    """Compare planned time blocks with actual tracked activity."""
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    _, raw = _load_sessions(selected)
    db = _db()
    try:
        return goals_engine.analyze_time_blocks(db, date_str, [dict(s) for s in raw])
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Productivity Analysis & Daily AI Insights Routes
# ---------------------------------------------------------------------------

@app.get("/api/productivity/{date_str}")
def get_productivity_analysis(date_str: str):
    """
    Return comprehensive daily productivity metrics:
    - Total work, focus, and distraction breakdown
    - Longest uninterrupted focus streak
    - True focus interruptions & top interrupting apps
    - Day-over-day comparison
    - Goals evaluation & time block adherence
    """
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    _, raw = _load_sessions(selected)

    # Load yesterday's sessions for day-over-day comparison
    prev_date = selected - timedelta(days=1)
    try:
        _, prev_raw = _load_sessions(prev_date)
    except Exception:
        prev_raw = []

    db = _db()
    try:
        return insights_engine.compute_daily_productivity(
            db, date_str, [dict(s) for s in raw], [dict(s) for s in prev_raw]
        )
    finally:
        db.close()


@app.get("/api/insights/summary/{date_str}")
def get_daily_ai_summary(
    date_str: str,
    refresh_ai: bool = Query(False, description="Re-run AI summary generation"),
):
    """
    Return cached or generated daily AI summary.
    Falls back to deterministic insights if AI is offline.
    """
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    _, raw = _load_sessions(selected)
    db = _db()
    try:
        prod = insights_engine.compute_daily_productivity(db, date_str, [dict(s) for s in raw])
        return insights_engine.generate_daily_ai_summary(db, date_str, prod, refresh=refresh_ai)
    finally:
        db.close()


@app.get("/api/analytics/range")
def get_analytics_range(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    refresh_ai: bool = Query(False, description="Re-run AI synthesis"),
):
    """
    Unified Analytics & Reports endpoint supporting arbitrary date ranges.
    Returns:
    - 4 primary KPIs with prior equivalent period comparisons
    - Productivity Score & AI Productivity Synthesis
    - Daily Trends & Work Volume points
    - Top Application & Tool Usage with Expandable Browser Rows (Zero double-counting)
    - Primary Focus Interruptors
    - Category Allocation Breakdown
    - Canonical Detailed Sessions for date-wise drilldown and filtered CSV export
    """
    try:
        start_d = date.fromisoformat(start_date)
        end_d = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    if start_d > end_d:
        raise HTTPException(status_code=422, detail="Start date cannot be after end date.")

    num_days = (end_d - start_d).days + 1
    if num_days > 366:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 366 days.")

    # 1. Load active sessions across selected range
    all_models: List[SessionModel] = []
    all_raw: List[Dict[str, Any]] = []
    daily_stats_map: Dict[str, Dict[str, float]] = {}

    curr = start_d
    while curr <= end_d:
        ds = curr.isoformat()
        daily_stats_map[ds] = {
            "active": 0.0,
            "productive": 0.0,
            "focus": 0.0,
            "distraction": 0.0,
        }
        try:
            m, r = _load_sessions(curr)
            all_models.extend(m)
            all_raw.extend(r)
            for s in r:
                dur = s.get("duration_seconds", 0.0)
                if s.get("kind") == "idle":
                    continue
                daily_stats_map[ds]["active"] += dur
                c_type = s.get("category_type") or "uncategorized"
                if c_type in ("focus", "work"):
                    daily_stats_map[ds]["productive"] += dur
                if c_type == "focus":
                    daily_stats_map[ds]["focus"] += dur
                elif c_type == "distraction":
                    daily_stats_map[ds]["distraction"] += dur
        except Exception:
            pass
        curr += timedelta(days=1)

    # 2. Load prior equivalent period for comparison
    prior_end = start_d - timedelta(days=1)
    prior_start = prior_end - timedelta(days=num_days - 1)
    prior_raw: List[Dict[str, Any]] = []
    p_curr = prior_start
    while p_curr <= prior_end:
        try:
            _, pr = _load_sessions(p_curr)
            prior_raw.extend(pr)
        except Exception:
            pass
        p_curr += timedelta(days=1)

    # 3. Canonical Non-overlapping Duration Totals
    total_active_seconds = sum(s.get("duration_seconds", 0.0) for s in all_raw if s.get("kind") != "idle")
    total_idle_seconds = sum(s.get("duration_seconds", 0.0) for s in all_raw if s.get("kind") == "idle")

    type_totals = {"focus": 0.0, "work": 0.0, "personal": 0.0, "distraction": 0.0, "uncategorized": 0.0}
    category_totals: Dict[str, Dict[str, Any]] = {}

    for s in all_raw:
        if s.get("kind") == "idle":
            continue
        c_name = s.get("category_name") or "Other / Needs Review"
        c_type = s.get("category_type")
        if not c_type or (c_type == "personal" and any(w in c_name.lower() for w in ("uncategorized", "other", "review"))):
            c_type = "uncategorized"
        c_color = s.get("category_color") or "#9ca3af"
        dur = s.get("duration_seconds", 0.0)

        if c_type in type_totals:
            type_totals[c_type] += dur
        else:
            type_totals["uncategorized"] += dur

        if c_name not in category_totals:
            category_totals[c_name] = {
                "name": c_name,
                "type": c_type,
                "color": c_color,
                "seconds": 0.0,
            }
        category_totals[c_name]["seconds"] += dur

    productive_work_seconds = type_totals["focus"] + type_totals["work"]
    deep_focus_seconds = type_totals["focus"]
    distraction_seconds = type_totals["distraction"]

    # 4. Prior period totals & comparisons
    prev_active = sum(s.get("duration_seconds", 0.0) for s in prior_raw if s.get("kind") != "idle")
    prev_productive = sum(s.get("duration_seconds", 0.0) for s in prior_raw if s.get("kind") != "idle" and s.get("category_type") in ("focus", "work"))
    prev_focus = sum(s.get("duration_seconds", 0.0) for s in prior_raw if s.get("kind") != "idle" and s.get("category_type") == "focus")
    prev_distraction = sum(s.get("duration_seconds", 0.0) for s in prior_raw if s.get("kind") != "idle" and s.get("category_type") == "distraction")

    def calc_comp(curr_sec: float, prev_sec: float, higher_is_better: bool = True):
        diff = curr_sec - prev_sec
        pct = round((diff / prev_sec) * 100, 1) if prev_sec > 0 else (100.0 if curr_sec > 0 else 0.0)
        improved = (diff >= 0) if higher_is_better else (diff <= 0)
        sign = "+" if diff > 0 else ("-" if diff < 0 else "")
        return {
            "change_seconds": round(diff, 1),
            "change_label": format_duration(abs(diff)),
            "change_pct": pct,
            "display_str": f"{sign}{pct}%" if prev_sec > 0 else ("N/A (No prior data)" if curr_sec == 0 else "New baseline"),
            "improved": improved,
            "previous_seconds": round(prev_sec, 1),
            "previous_label": format_duration(prev_sec),
        }

    # Format period label
    if num_days == 1:
        prior_period_label = f"vs prior day ({prior_start.isoformat()})"
    elif num_days == 7:
        prior_period_label = f"vs prior 7 days ({prior_start.strftime('%b %d')} – {prior_end.strftime('%b %d')})"
    else:
        prior_period_label = f"vs prior {num_days} days ({prior_start.strftime('%b %d')} – {prior_end.strftime('%b %d')})"

    # 5. Interruption & streak detection
    total_interruptions, top_interruptors, longest_streak = insights_engine.detect_interruptions_and_streaks(all_raw)

    # 6. Productivity Score
    if total_active_seconds > 0:
        focus_ratio = deep_focus_seconds / total_active_seconds
        distraction_ratio = distraction_seconds / total_active_seconds
        interruption_penalty = min(0.3, total_interruptions * 0.02)
        score = max(5, min(100, int((focus_ratio * 60) + (max(0.0, 1.0 - distraction_ratio) * 40) - (interruption_penalty * 100))))
    else:
        focus_ratio = 0.0
        distraction_ratio = 0.0
        score = 0

    score_color = (
        "#35D68A" if score >= 75 else
        ("#16D5E2" if score >= 50 else
        ("#FFB23E" if score >= 30 else "#FA5275"))
    )
    score_label = (
        "Hyper-Focused" if score >= 80 else
        ("High Productivity" if score >= 65 else
        ("Balanced" if score >= 50 else
        ("Moderate" if score >= 35 else "Fragmented")))
    )

    # 7. Category breakdown sorted descending
    cat_breakdown = []
    for c in sorted(category_totals.values(), key=lambda x: x["seconds"], reverse=True):
        c_pct = round(c["seconds"] / total_active_seconds * 100, 1) if total_active_seconds > 0 else 0.0
        cat_breakdown.append({
            "name": c["name"],
            "type": c["type"],
            "color": c["color"],
            "seconds": round(c["seconds"], 1),
            "label": format_duration(c["seconds"]),
            "pct": c_pct,
        })

    # 8. Hierarchical Top Application & Tool Usage (Website-first)
    app_breakdown = activity_intel.aggregate_hierarchical_usage(all_raw, total_active_seconds)
    browser_breakdown = activity_intel.aggregate_browser_containers(all_raw, total_active_seconds)

    # 9. Daily Trends points
    daily_trends = []
    curr = start_d
    while curr <= end_d:
        ds = curr.isoformat()
        st = daily_stats_map.get(ds, {"active": 0.0, "productive": 0.0, "focus": 0.0, "distraction": 0.0})
        day_name = curr.strftime("%a")
        daily_trends.append({
            "date": ds,
            "day_name": day_name,
            "active_seconds": round(st["active"], 1),
            "active_label": format_duration(st["active"]),
            "productive_seconds": round(st["productive"], 1),
            "productive_label": format_duration(st["productive"]),
            "distraction_seconds": round(st["distraction"], 1),
            "distraction_label": format_duration(st["distraction"]),
            "focus_seconds": round(st["focus"], 1),
            "focus_label": format_duration(st["focus"]),
        })
        curr += timedelta(days=1)

    # 10. AI Productivity Synthesis
    focus_pct = round(focus_ratio * 100, 1)
    distraction_pct = round(distraction_ratio * 100, 1)

    top_app_name = app_breakdown[0]["app"] if app_breakdown else "Applications"
    top_app_time = app_breakdown[0]["duration_label"] if app_breakdown else "0s"

    takeaway = (
        f"Across {num_days} day{'s' if num_days > 1 else ''} ({start_date} to {end_date}), you logged "
        f"{format_duration(productive_work_seconds)} of productive work ({focus_pct}% focus ratio) out of "
        f"{format_duration(total_active_seconds)} total tracked screen time. "
        f"Primary activity was {top_app_name} with {top_app_time}."
    ) if total_active_seconds > 0 else f"No tracked computer activity found between {start_date} and {end_date}."

    focus_continuity = (
        f"Your deep focus accounted for {format_duration(deep_focus_seconds)} with {total_interruptions} switch events. "
        + (f"Longest continuous streak reached {longest_streak['duration_label']} on {longest_streak.get('app', 'tool')}." if longest_streak else "No extended focus blocks were logged.")
    )

    interruption_analysis = (
        f"{format_duration(distraction_seconds)} ({distraction_pct}% of screen time) was spent on distracting or non-work activities. "
        + (f"Top interruption source was {top_interruptors[0]['app']} ({top_interruptors[0]['lost_label']} lost across {top_interruptors[0]['count']} switches)." if top_interruptors else "Zero major interruptions recorded.")
    )

    recommendations = []
    if distraction_ratio > 0.25:
        recommendations.append(f"Entertainment & media represents {distraction_pct}% of your time. Consider grouping non-work browsing into designated breaks.")
    if total_interruptions > 8:
        recommendations.append(f"High task switching detected ({total_interruptions} switches). Try using 25-minute Pomodoro focus blocks to protect continuity.")
    if focus_ratio >= 0.5:
        recommendations.append(f"Excellent deep focus discipline sustained ({focus_pct}% focus ratio). Maintain this structured work momentum.")
    else:
        recommendations.append("Increase dedicated single-task focus periods by muting non-essential notifications.")
    if len(recommendations) < 2:
        recommendations.append("Review uncategorized items in the detailed table to ensure all development activities are correctly classified.")

    ai_synthesis = {
        "key_takeaway": takeaway,
        "focus_streak_summary": focus_continuity,
        "interruption_analysis": interruption_analysis,
        "recommendations": recommendations[:3],
        "source": "deterministic",
        "generated_at": datetime.now().astimezone().isoformat(),
    }

    return {
        "start_date": start_date,
        "end_date": end_date,
        "days_count": num_days,
        "kpi": {
            "productive_work_seconds": round(productive_work_seconds, 1),
            "productive_work_label": format_duration(productive_work_seconds),
            "deep_focus_seconds": round(deep_focus_seconds, 1),
            "deep_focus_label": format_duration(deep_focus_seconds),
            "distraction_seconds": round(distraction_seconds, 1),
            "distraction_label": format_duration(distraction_seconds),
            "total_tracked_seconds": round(total_active_seconds, 1),
            "total_tracked_label": format_duration(total_active_seconds),
            "total_idle_seconds": round(total_idle_seconds, 1),
            "total_idle_label": format_duration(total_idle_seconds),
            "comparison": {
                "productive_work": calc_comp(productive_work_seconds, prev_productive, True),
                "deep_focus": calc_comp(deep_focus_seconds, prev_focus, True),
                "distraction": calc_comp(distraction_seconds, prev_distraction, False),
                "total_tracked": calc_comp(total_active_seconds, prev_active, True),
                "prior_period_label": prior_period_label,
            },
        },
        "productivity_score": {
            "score": score,
            "label": score_label,
            "color": score_color,
            "focus_ratio_pct": focus_pct,
            "distraction_ratio_pct": distraction_pct,
            "explanation": f"Computed from your {focus_pct}% focus ratio, distraction minimization, and {total_interruptions} context-switch interruptions.",
            "longest_streak": longest_streak,
            "total_interruptions": total_interruptions,
        },
        "ai_synthesis": ai_synthesis,
        "category_breakdown": cat_breakdown,
        "app_breakdown": app_breakdown,
        "browser_breakdown": browser_breakdown,
        "daily_trends": daily_trends,
        "top_interruptors": top_interruptors,
        "detailed_sessions": all_models,
    }


@app.get("/api/analytics/export/csv")
def export_analytics_csv(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    category: Optional[str] = Query("all", description="Category filter or 'all'"),
    search: Optional[str] = Query("", description="Search term filter"),
    export_type: Optional[str] = Query("detailed", description="'detailed' or 'summary'"),
):
    """
    Export verified canonical activity records or executive summary to Excel-compatible CSV.
    Features:
    - Zero data URI truncation bugs (supports hashtags like #shorts, emojis, and quotes).
    - UTF-8 with BOM (\uFEFF) for immediate Excel compatibility without mangling characters.
    - 36 rich columns of time, application, classification, productivity, and planning context.
    - Strict filter synchronization with the Analytics & Reports table.
    """
    try:
        start_d = date.fromisoformat(start_date)
        end_d = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")

    if start_d > end_d:
        raise HTTPException(status_code=422, detail="start_date cannot be after end_date.")

    num_days = (end_d - start_d).days + 1
    if num_days > 366:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 366 days.")

    db = _db()
    time_blocks: List[Dict[str, Any]] = []
    try:
        block_rows = db.execute(
            """
            SELECT id, title, start_time, end_time, date
            FROM time_blocks
            WHERE date BETWEEN ? AND ?
            ORDER BY date, start_time
            """,
            (start_date, end_date),
        ).fetchall()
        time_blocks = [dict(b) for b in block_rows]
    except Exception:
        pass
    finally:
        db.close()

    # Load sessions across range
    all_models: List[SessionModel] = []
    curr = start_d
    while curr <= end_d:
        m, _ = _load_sessions(curr)
        all_models.extend(m)
        curr += timedelta(days=1)

    # Filter out idle intervals
    active_sessions = [s for s in all_models if s.kind != "idle"]

    # Category filter
    if category and category.lower() != "all":
        cat_lower = category.lower()
        active_sessions = [s for s in active_sessions if (s.category_name or "").lower() == cat_lower]

    # Search filter
    if search and search.strip():
        q = search.strip().lower()
        active_sessions = [
            s for s in active_sessions
            if q in (s.activity_name or "").lower()
            or q in (s.specific_task or "").lower()
            or q in s.app.lower()
            or q in s.title.lower()
            or q in (s.category_name or "").lower()
            or q in (s.domain or "").lower()
            or q in (s.task or "").lower()
        ]

    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    APP_NAME_MAP = {
        "chrome.exe": "Google Chrome",
        "msedge.exe": "Microsoft Edge",
        "firefox.exe": "Mozilla Firefox",
        "code.exe": "Visual Studio Code",
        "explorer.exe": "Windows Explorer",
        "cmd.exe": "Command Prompt",
        "powershell.exe": "Windows PowerShell",
        "windowsterminal.exe": "Windows Terminal",
        "notepad.exe": "Notepad",
        "slack.exe": "Slack",
        "discord.exe": "Discord",
        "spotify.exe": "Spotify",
    }

    if export_type == "summary":
        filename = f"analytics-summary-{start_date}-to-{end_date}.csv"
        # 1. Period KPI Overview
        writer.writerow(["=== TIME TRACKER AI 2 — ANALYTICS EXECUTIVE SUMMARY ==="])
        writer.writerow(["Date Range", f"{start_date} to {end_date} ({num_days} days)"])
        writer.writerow(["Generated At", datetime.now().astimezone().isoformat()])
        writer.writerow([])

        # Summary KPIs
        tot_active = sum(s.duration_seconds for s in active_sessions)
        prod_active = sum(s.duration_seconds for s in active_sessions if s.category_type in ("focus", "work"))
        focus_active = sum(s.duration_seconds for s in active_sessions if s.category_type == "focus")
        dist_active = sum(s.duration_seconds for s in active_sessions if s.category_type == "distraction")

        writer.writerow(["Metric", "Duration (Formatted)", "Duration (Seconds)", "% of Active Time"])
        writer.writerow(["Productive Work Time", format_duration(prod_active), round(prod_active, 1), f"{(prod_active / tot_active * 100):.1f}%" if tot_active > 0 else "0%"])
        writer.writerow(["Deep Focus Time", format_duration(focus_active), round(focus_active, 1), f"{(focus_active / tot_active * 100):.1f}%" if tot_active > 0 else "0%"])
        writer.writerow(["Distraction Time", format_duration(dist_active), round(dist_active, 1), f"{(dist_active / tot_active * 100):.1f}%" if tot_active > 0 else "0%"])
        writer.writerow(["Total Tracked Active Time", format_duration(tot_active), round(tot_active, 1), "100.0%"])
        writer.writerow([])

        # 2. Category Breakdown
        writer.writerow(["=== CATEGORY DISTRIBUTION BREAKDOWN ==="])
        writer.writerow(["Category", "Type", "Duration (Formatted)", "Duration (Seconds)", "Percentage", "Session Count"])
        cat_map: Dict[str, Dict[str, Any]] = {}
        for s in active_sessions:
            c = s.category_name or "Other / Needs Review"
            if c not in cat_map:
                cat_map[c] = {"name": c, "type": s.category_type or "uncategorized", "seconds": 0.0, "count": 0}
            cat_map[c]["seconds"] += s.duration_seconds
            cat_map[c]["count"] += 1

        for c_info in sorted(cat_map.values(), key=lambda x: x["seconds"], reverse=True):
            pct_str = f"{(c_info['seconds'] / tot_active * 100):.1f}%" if tot_active > 0 else "0%"
            writer.writerow([
                c_info["name"],
                c_info["type"],
                format_duration(c_info["seconds"]),
                round(c_info["seconds"], 1),
                pct_str,
                c_info["count"],
            ])
        writer.writerow([])

        # 3. Application Breakdown
        writer.writerow(["=== APPLICATION USAGE BREAKDOWN ==="])
        writer.writerow(["Application", "Process", "Duration (Formatted)", "Duration (Seconds)", "Percentage", "Session Count"])
        app_map: Dict[str, Dict[str, Any]] = {}
        for s in active_sessions:
            a = s.app
            if a not in app_map:
                display_name = APP_NAME_MAP.get(a.lower(), "Python Background" if "python" in a.lower() else a.replace(".exe", "").capitalize())
                app_map[a] = {"name": display_name, "process": a, "seconds": 0.0, "count": 0}
            app_map[a]["seconds"] += s.duration_seconds
            app_map[a]["count"] += 1

        for a_info in sorted(app_map.values(), key=lambda x: x["seconds"], reverse=True):
            pct_str = f"{(a_info['seconds'] / tot_active * 100):.1f}%" if tot_active > 0 else "0%"
            writer.writerow([
                a_info["name"],
                a_info["process"],
                format_duration(a_info["seconds"]),
                round(a_info["seconds"], 1),
                pct_str,
                a_info["count"],
            ])
        writer.writerow([])

        # 4. Daily Trends Breakdown
        writer.writerow(["=== DAILY PRODUCTIVITY TRENDS ==="])
        writer.writerow(["Date", "Total Active (Formatted)", "Total Active (Seconds)", "Productive (Seconds)", "Focus (Seconds)", "Distraction (Seconds)", "Interval Count"])
        daily_groups: Dict[str, List[SessionModel]] = {}
        for s in active_sessions:
            d_key = s.start[:10]
            daily_groups.setdefault(d_key, []).append(s)

        for d_key in sorted(daily_groups.keys()):
            d_sessions = daily_groups[d_key]
            d_tot = sum(s.duration_seconds for s in d_sessions)
            d_prod = sum(s.duration_seconds for s in d_sessions if s.category_type in ("focus", "work"))
            d_foc = sum(s.duration_seconds for s in d_sessions if s.category_type == "focus")
            d_dist = sum(s.duration_seconds for s in d_sessions if s.category_type == "distraction")
            writer.writerow([
                d_key,
                format_duration(d_tot),
                round(d_tot, 1),
                round(d_prod, 1),
                round(d_foc, 1),
                round(d_dist, 1),
                len(d_sessions),
            ])

    else:
        filename = f"detailed-activity-report-{start_date}-to-{end_date}.csv"
        headers = [
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
        writer.writerow(headers)

        for s in active_sessions:
            s_dt = s.start
            e_dt = s.end
            local_date = s_dt[:10]
            start_time = s_dt[11:19]
            end_time = e_dt[11:19]
            dur = s.duration_seconds
            dur_hms = f"{int(dur // 3600):02d}:{int((dur % 3600) // 60):02d}:{int(dur % 60):02d}"

            app_lower = s.app.lower()
            app_display = APP_NAME_MAP.get(app_lower, "Python Background" if "python" in app_lower else s.app.replace(".exe", "").capitalize())

            # Correlate scheduled time block
            matched_block_id = ""
            matched_block_title = ""
            planned_match = "Unplanned"
            s_hhmm = start_time[:5]
            for b in time_blocks:
                if b.get("date") == local_date:
                    s_b = (b.get("start_time") or "")[:5]
                    e_b = (b.get("end_time") or "")[:5]
                    if s_b <= s_hhmm <= e_b:
                        matched_block_id = str(b.get("id", ""))
                        matched_block_title = b.get("title", "")
                        b_title_lower = matched_block_title.lower()
                        act_lower = (s.activity_name or "").lower()
                        if s.category_type in ("focus", "work") or b_title_lower in act_lower:
                            planned_match = "Yes"
                        else:
                            planned_match = "No"
                        break

            # Correlate active focus session / block ID
            matched_fs_id = matched_block_id or (f"task-{s.task}" if s.task else "")

            cat_type = s.category_type or "uncategorized"
            is_prod = "Yes" if cat_type in ("focus", "work") else "No"
            is_focus = "Yes" if cat_type == "focus" else "No"
            is_dist = "Yes" if cat_type == "distraction" else "No"
            needs_rev = "Yes" if (cat_type == "uncategorized" or s.is_uncertain) else "No"
            uncertain = "Yes" if s.is_uncertain else "No"
            manual = "Yes" if bool(s.user_description or s.category_source == "manual_override") else "No"

            meta_level = (
                "Full" if s.domain and (s.document_name or s.site_name) else
                ("Domain Only" if s.domain else
                ("Title Only" if s.title else "Process Only"))
            )

            writer.writerow([
                f"REC-{s.display_number:05d}",
                local_date,
                start_time,
                end_time,
                s_dt,
                e_dt,
                round(dur, 2),
                dur_hms,
                app_display,
                s.app,
                s.title,
                s.domain or "",
                s.document_name or s.site_name or "",
                s.activity_name or s.title,
                s.task or "",
                "",  # Project Name
                s.category_name or "Other / Needs Review",
                cat_type,
                s.category_source or "inference",
                f"{s.confidence:.2f}" if s.confidence is not None else "",
                needs_rev,
                uncertain,
                manual,
                is_prod,
                is_focus,
                is_dist,
                "No",
                matched_fs_id,
                matched_block_id,
                matched_block_title,
                planned_match,
                "Automatic Tracking",
                s.session_key,
                ";".join(str(x) for x in s.observation_ids),
                "",
                meta_level,
            ])

    csv_bytes = ("\uFEFF" + out.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@app.post("/api/aicoach/chat", response_model=AiCoachChatResponse)
def aicoach_chat(payload: AiCoachChatRequest):
    """
    Real AI Coach Chatbot grounded in SQLite tracking observations, Time Blocks, and Goals.
    Answers the 5 suggested question presets and natural-language productivity queries.
    """
    db = _db()
    try:
        date_str = payload.selected_date or date.today().isoformat()
        if not (payload.message or "").strip() and not payload.preset_action:
            return AiCoachChatResponse(
                response="Please ask a question or select one of the suggested inquiries above.",
                grounded=True,
                sources=["System"],
                quick_actions=[],
                date_scope=date_str,
            )
        res = ai_coach_engine.process_ai_coach_message(
            db=db,
            message=payload.message or "",
            selected_date=date_str,
            history=payload.history,
            preset_action=payload.preset_action,
        )
        return AiCoachChatResponse(**res)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tracker Control & Status Routes
# ---------------------------------------------------------------------------

@app.get("/api/tracker/status", response_model=TrackingStatusResponse)
def get_tracker_status():
    """Return whether the background tracking process is currently running and active task."""
    return tracker_manager.get_tracking_status()


@app.get("/api/tracker/active-task", response_model=Optional[ActiveTaskModel])
def get_active_task():
    """Return currently active task observation from tracker.db."""
    return tracker_manager.get_active_task()


@app.post("/api/tracker/start", response_model=TrackingStatusResponse)
def start_tracker():
    """Start background activity tracking."""
    try:
        return tracker_manager.start_tracking()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tracker/stop", response_model=TrackingStatusResponse)
def stop_tracker():
    """Stop background activity tracking and close current observation cleanly."""
    try:
        return tracker_manager.stop_tracking()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tracker/toggle", response_model=TrackingStatusResponse)
def toggle_tracker():
    """Toggle background activity tracking ON or OFF."""
    try:
        if tracker_manager.is_tracking_active():
            return tracker_manager.stop_tracking()
        else:
            return tracker_manager.start_tracking()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tracker/assign-task", response_model=Optional[ActiveTaskModel])
def assign_active_task(payload: AssignTaskRequest):
    """Manually assign a meaningful user activity name to the current observation."""
    res = tracker_manager.assign_active_task(
        task_name=payload.task_name,
        category_id=payload.category_id,
        observation_id=payload.observation_id,
    )
    if not res:
        raise HTTPException(status_code=400, detail="Failed to assign task to active observation")
    return res


@app.post("/api/tracker/clear-task")
def clear_active_task():
    """Clear active task and active focus block settings."""
    ok = tracker_manager.clear_active_task()
    return {"status": "ok" if ok else "failed"}


# ---------------------------------------------------------------------------
# Desktop Widget Launcher Route
# ---------------------------------------------------------------------------

@app.get("/api/widget/status")
def get_widget_status():
    """Check if the floating widget process is running."""
    import psutil
    widget_pids = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or []).lower()
            if "widget.py" in cmd:
                widget_pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {"is_running": len(widget_pids) > 0, "pids": widget_pids}


@app.post("/api/widget/launch")
def launch_widget():
    """Launch the floating desktop widget if not already open."""
    import psutil
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or []).lower()
            if "widget.py" in cmd:
                return {"status": "already_running", "pid": proc.info["pid"]}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    python_exe = sys.executable
    if sys.platform == "win32":
        pythonw_candidate = Path(sys.executable).parent / "pythonw.exe"
        if pythonw_candidate.exists():
            python_exe = str(pythonw_candidate)

    widget_script = str(_ROOT / "widget.py")
    try:
        creationflags = 0
        if sys.platform == "win32":
            # 0x08000000 = CREATE_NO_WINDOW prevents Windows Terminal / conhost from creating any blank window
            creationflags = 0x08000000
        proc = subprocess.Popen(
            [python_exe, widget_script],
            cwd=str(_ROOT),
            creationflags=creationflags,
        )
        return {"status": "launched", "pid": proc.pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch widget: {e}")


# ---------------------------------------------------------------------------
# Notifications & Recovery Routes
# ---------------------------------------------------------------------------

@app.get("/api/notifications")
def get_notifications(
    limit: int = Query(50, ge=1, le=200),
    filter_type: Optional[str] = Query(None, description="all | unread | focus | idle | recovery | warning"),
):
    """Return stored notifications and live unread badge count."""
    db = _db()
    try:
        return notif_engine.get_notifications(db, limit=limit, filter_type=filter_type)
    finally:
        db.close()


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int):
    """Mark a notification as read."""
    db = _db()
    try:
        updated = notif_engine.mark_notification_read(db, notification_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Notification not found.")
        return {"status": "success", "id": notification_id}
    finally:
        db.close()


@app.post("/api/notifications/read-all")
def mark_all_notifications_read():
    """Mark all unread notifications as read."""
    db = _db()
    try:
        count = notif_engine.mark_all_read(db)
        return {"status": "success", "marked_read_count": count}
    finally:
        db.close()


@app.delete("/api/notifications/{notification_id}")
def dismiss_notification(notification_id: int):
    """Dismiss a notification from the notification center."""
    db = _db()
    try:
        deleted = notif_engine.dismiss_notification(db, notification_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Notification not found.")
        return {"status": "dismissed", "id": notification_id}
    finally:
        db.close()


@app.post("/api/notifications/test-toast")
def test_desktop_toast():
    """Trigger an immediate sample Windows desktop toast for verification matching the reference layout."""
    now_local = datetime.now()
    toast_time_str = now_local.strftime("%I:%M %p").lstrip("0")
    test_actions = [
        {
            "content": "Return to Task",
            "arguments": "http://localhost:5173/?action=return_to_task",
            "icon": "btn_play.png",
        },
        {
            "content": "Review Activity",
            "arguments": "http://localhost:5173/?action=review_activity",
        },
        {
            "content": "Snooze 15 min",
            "arguments": "http://localhost:5173/?action=snooze_mismatch_15",
            "icon": "btn_clock.png",
        },
    ]
    diag = win_notifier.dispatch_test_toast(
        title="[TEST] Focus Check-in Preview",
        message="Preview: Your recent activity looks unrelated to the current task. Check your activity before treating it as a distraction.",
        scenario="reminder",
        actions=test_actions,
    )
    return {
        "status": "submitted" if diag.get("success") else "failed",
        "supported": sys.platform == "win32",
        "diagnostics": diag,
    }


@app.get("/api/notifications/diagnostics")
def get_notification_diagnostics():
    """Return comprehensive health and readiness diagnostics for Windows toast notifications."""
    return win_notifier.get_windows_notification_diagnostics()


@app.post("/api/notifications/test-desktop-toast")
def test_desktop_notification_toast():
    """Trigger an immediate sample test toast with full diagnostic delivery verification."""
    diag = win_notifier.dispatch_test_toast(
        title="[TEST] Time Tracker AI Notification Test",
        message="Desktop notification banner is working properly with full action support.",
        scenario="reminder",
    )
    full_diag = win_notifier.get_windows_notification_diagnostics()
    return {
        "status": "submitted" if diag.get("success") else "failed",
        "supported": sys.platform == "win32",
        "result": diag,
        "diagnostics": full_diag,
    }


@app.post("/api/notifications/test-time-block-toast")
def test_time_block_toast():
    """Trigger an immediate sample scheduled Time Block reminder toast clearly badged as a test."""
    now_local = datetime.now()
    toast_time_str = now_local.strftime("%I:%M %p").lstrip("0")
    test_actions = [
        {
            "content": "Start Focus",
            "arguments": "timetracker://navigate?action=start_focus_block&block_id=999",
            "icon": "btn_play.png",
        },
        {
            "content": "Snooze 5 min",
            "arguments": "timetracker://action?name=snooze_block&block_id=999&minutes=5",
            "icon": "btn_clock.png",
        },
        {
            "content": "Skip this block",
            "arguments": "timetracker://action?name=skip_block&block_id=999",
            "icon": "btn_cross.png",
        },
        {
            "content": "Open Planner",
            "arguments": "timetracker://navigate?action=open_planner&block_id=999",
        },
    ]
    success = win_notifier.send_windows_toast(
        title="[TEST] Time-Block Reminder Preview",
        message="Preview: Scheduled session starting soon · 9:30 AM – 11:00 AM (Sample Task)",
        timestamp_str=toast_time_str,
        launch_url="timetracker://navigate?action=open_planner&block_id=999",
        actions=test_actions,
        scenario="reminder",
        tag="test_notification",
        group="time_tracker",
        force=True,
    )
    return {"status": "queued" if success else "failed", "supported": sys.platform == "win32"}


@app.post("/api/notifications/snooze")
def snooze_notification_alert(body: SnoozeAlertRequest):
    """Snooze idle or schedule-mismatch alerts for N minutes."""
    if body.alert_type == "idle":
        notif_engine.snooze_idle_alerts(body.minutes)
    else:
        notif_engine.snooze_mismatch_alerts(body.minutes)
    return {"status": "snoozed", "alert_type": body.alert_type, "minutes": body.minutes}


@app.get("/api/notifications/recovery-prompt")
def get_pending_recovery_prompt():
    """Return pending missed activity gap if one exists."""
    db = _db()
    try:
        pending = notif_engine.get_pending_recovery_gap(db)
        return {"has_pending": pending is not None, "gap": pending}
    finally:
        db.close()


@app.post("/api/notifications/recovery-prompt/resolve")
def resolve_recovery_prompt(body: RecoveryPromptResolveRequest):
    """Resolve a pending recovery prompt with 'skip' or 'snooze'."""
    db = _db()
    try:
        resolved = notif_engine.resolve_recovery_gap(db, body.gap_id, body.action)
        if not resolved:
            raise HTTPException(status_code=404, detail="Recovery gap not found.")
        return {"status": "resolved", "action": body.action, "gap_id": body.gap_id}
    finally:
        db.close()


@app.post("/api/activity/manual-entry")
def record_manual_activity(body: ManualEntryRequest):
    """
    Record manual activity entry for a missed interval.
    Validates interval, prevents double-counting, never fabricates executable names.
    """
    db = _db()
    try:
        return notif_engine.record_manual_activity(
            db=db,
            task_name=body.task_name,
            start_time=body.start_time,
            end_time=body.end_time,
            category_id=body.category_id,
            notes=body.notes,
            recovery_gap_id=body.recovery_gap_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Settings Routes
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def get_app_settings():
    """Return all persistent application and notification settings."""
    return win_notifier.get_notification_settings()


@app.put("/api/settings")
def update_app_settings(body: SettingsUpdateRequest):
    """Update application and notification settings."""
    db = _db()
    try:
        ts = notif_engine.now_iso()
        fields = body.model_dump(exclude_unset=True)
        for k, v in fields.items():
            if v is not None:
                str_val = str(v).lower() if isinstance(v, bool) else str(v)
                db.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (k, str_val, ts),
                )
        db.commit()
        return win_notifier.get_notification_settings()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Windows Startup (Autostart) routes
# ---------------------------------------------------------------------------

@app.get("/api/autostart/status", response_model=AutostartStatusResponse)
def get_autostart_status():
    """Return whether Time Tracker AI is configured to launch at Windows login."""
    enabled = autostart.is_autostart_enabled()
    cmd = autostart.get_autostart_command()
    return AutostartStatusResponse(
        enabled=enabled,
        command=cmd,
        supported=sys.platform == "win32",
        message="Launches automatically on user sign-in." if enabled else "Manual start only.",
    )


@app.post("/api/autostart/enable", response_model=AutostartStatusResponse)
def enable_autostart():
    """Enable automatic launch at Windows login via HKCU Run registry."""
    success, detail = autostart.enable_autostart()
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to enable autostart: {detail}")
    return AutostartStatusResponse(
        enabled=True,
        command=detail,
        supported=True,
        message="Autostart enabled successfully.",
    )


@app.post("/api/autostart/disable", response_model=AutostartStatusResponse)
def disable_autostart():
    """Disable automatic launch at Windows login."""
    success, detail = autostart.disable_autostart()
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to disable autostart: {detail}")
    return AutostartStatusResponse(
        enabled=False,
        command=autostart.get_autostart_command(),
        supported=True,
        message="Autostart disabled successfully.",
    )


@app.post("/api/autostart/toggle", response_model=AutostartStatusResponse)
def toggle_autostart():
    """Toggle autostart between enabled and disabled."""
    if autostart.is_autostart_enabled():
        return disable_autostart()
    else:
        return enable_autostart()


# ---------------------------------------------------------------------------
# Desktop App Protocol & Action Activation Endpoints
# ---------------------------------------------------------------------------

class DesktopActionRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=100)
    params: Dict[str, Any] = Field(default_factory=dict)


_pending_desktop_actions: List[Dict[str, Any]] = []
_pending_actions_lock = threading.Lock()


@app.post("/api/desktop/activate")
def activate_desktop_action(payload: DesktopActionRequest):
    """
    Handle forwarded notification activation or custom protocol request.
    Executes silent actions directly in the backend and queues UI actions for the desktop window.
    """
    action = payload.action.strip().lower()
    params = payload.params or {}

    # 1. Silent block snooze
    if action == "snooze_block":
        block_id = params.get("block_id")
        minutes = params.get("minutes", 5)
        if block_id:
            try:
                b_id = int(block_id)
                mins = int(minutes)
                with _db() as conn:
                    notif_engine.snooze_time_block_reminder(conn, b_id, minutes=mins)
                return {"status": "ok", "executed": "snooze_block", "block_id": b_id, "minutes": mins}
            except Exception as e:
                logger.warning("Failed to snooze block from notification action: %s", e)
                raise HTTPException(status_code=400, detail=str(e))

    # 2. Silent block skip
    elif action in ("skip_block", "dismiss_missed_block"):
        block_id = params.get("block_id")
        if block_id:
            try:
                b_id = int(block_id)
                with _db() as conn:
                    notif_engine.skip_time_block(conn, b_id)
                return {"status": "ok", "executed": "skip_block", "block_id": b_id}
            except Exception as e:
                logger.warning("Failed to skip block from notification action: %s", e)
                raise HTTPException(status_code=400, detail=str(e))

    # 3. Silent notification snooze (idle or mismatch)
    elif action in ("snooze_idle_5", "snooze_mismatch_15", "snooze_mismatch_30"):
        category = "idle" if "idle" in action else "focus"
        minutes = 30 if "30" in action else (15 if "15" in action else 5)
        try:
            if category == "idle":
                notif_engine.snooze_idle_alerts(minutes)
            else:
                notif_engine.snooze_mismatch_alerts(minutes)
            return {"status": "ok", "executed": "snooze_notification", "category": category, "minutes": minutes}
        except Exception as e:
            logger.warning("Failed to snooze notification: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    # 4. Silent gap skip or dismiss
    elif action in ("skip_gap", "snooze_gap", "dismiss"):
        return {"status": "ok", "executed": action, "params": params}

    # 5. Interactive UI actions: queue for active desktop window
    with _pending_actions_lock:
        if len(_pending_desktop_actions) >= 10:
            _pending_desktop_actions.pop(0)
        _pending_desktop_actions.append({
            "action": action,
            "params": params,
            "timestamp": time.time(),
        })

    return {"status": "ok", "queued": True, "action": action}


@app.get("/api/desktop/pending-action")
def get_pending_desktop_action():
    """Retrieve and pop the next pending desktop action for the active UI."""
    with _pending_actions_lock:
        if _pending_desktop_actions:
            return _pending_desktop_actions.pop(0)
    return None


def _get_user32():
    u = ctypes.windll.user32
    u.FindWindowW.restype = wintypes.HWND
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.IsWindow.restype = wintypes.BOOL
    u.IsWindow.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    return u


def _find_desktop_window_hwnd() -> int:
    """Locate the HWND of the running Time Tracker AI desktop window."""
    if sys.platform != "win32":
        return 0
    try:
        user32 = _get_user32()
        hwnd = user32.FindWindowW(None, "Time Tracker AI")
        if hwnd and user32.IsWindow(hwnd):
            return int(hwnd)

        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(h, lparam):
            try:
                if user32.IsWindowVisible(h):
                    length = user32.GetWindowTextLengthW(h)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(h, buf, length + 1)
                        if "Time Tracker AI" in buf.value:
                            found.append(int(h))
                            return False
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found[0] if found else 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        return 0


@app.post("/api/desktop/window/minimize")
def desktop_window_minimize():
    hwnd = _find_desktop_window_hwnd()
    if hwnd:
        user32 = _get_user32()
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return {"status": "ok", "action": "minimize"}
    return {"status": "error", "message": "Desktop window not found"}


@app.post("/api/desktop/window/maximize")
def desktop_window_maximize():
    hwnd = _find_desktop_window_hwnd()
    if hwnd:
        user32 = _get_user32()
        work_rc = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rc), 0)
        work_w = work_rc.right - work_rc.left
        work_h = work_rc.bottom - work_rc.top
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, 0, work_rc.left, work_rc.top, work_w, work_h, 0x0040)
        return {"status": "ok", "action": "maximize", "is_maximized": True}
    return {"status": "error", "message": "Desktop window not found"}


@app.post("/api/desktop/window/restore")
def desktop_window_restore():
    hwnd = _find_desktop_window_hwnd()
    if hwnd:
        user32 = _get_user32()
        work_rc = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rc), 0)
        work_w = work_rc.right - work_rc.left
        work_h = work_rc.bottom - work_rc.top
        norm_w, norm_h = 1320, 860
        norm_x = work_rc.left + (work_w - norm_w) // 2
        norm_y = work_rc.top + (work_h - norm_h) // 2
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, 0, norm_x, norm_y, norm_w, norm_h, 0x0004 | 0x0040)
        return {"status": "ok", "action": "restore", "is_maximized": False}
    return {"status": "error", "message": "Desktop window not found"}


@app.post("/api/desktop/window/toggle-maximize")
def desktop_window_toggle_maximize():
    hwnd = _find_desktop_window_hwnd()
    if not hwnd:
        return {"status": "error", "message": "Desktop window not found"}
    user32 = _get_user32()
    is_zoomed = bool(user32.IsZoomed(hwnd))

    rc = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    curr_w = rc.right - rc.left
    curr_h = rc.bottom - rc.top

    work_rc = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rc), 0)
    work_w = work_rc.right - work_rc.left
    work_h = work_rc.bottom - work_rc.top

    is_at_work_area = (abs(curr_w - work_w) <= 12 and abs(curr_h - work_h) <= 12)

    if is_zoomed or is_at_work_area:
        norm_w, norm_h = 1320, 860
        norm_x = work_rc.left + (work_w - norm_w) // 2
        norm_y = work_rc.top + (work_h - norm_h) // 2
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, 0, norm_x, norm_y, norm_w, norm_h, 0x0004 | 0x0040)
        return {"status": "ok", "action": "restore", "is_maximized": False}
    else:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, 0, work_rc.left, work_rc.top, work_w, work_h, 0x0040)
        return {"status": "ok", "action": "maximize", "is_maximized": True}


@app.post("/api/desktop/window/close")
def desktop_window_close():
    hwnd = _find_desktop_window_hwnd()
    if hwnd:
        user32 = _get_user32()
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return {"status": "ok", "action": "close"}
    return {"status": "error", "message": "Desktop window not found"}


@app.get("/api/desktop/window/state")
def desktop_window_state():
    hwnd = _find_desktop_window_hwnd()
    if hwnd:
        user32 = _get_user32()
        is_zoomed = bool(user32.IsZoomed(hwnd))
        is_iconic = bool(user32.IsIconic(hwnd))

        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        curr_w = rc.right - rc.left
        curr_h = rc.bottom - rc.top

        work_rc = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rc), 0)
        work_w = work_rc.right - work_rc.left
        work_h = work_rc.bottom - work_rc.top

        is_at_work_area = (abs(curr_w - work_w) <= 12 and abs(curr_h - work_h) <= 12)

        return {
            "is_desktop": True,
            "is_maximized": is_zoomed or is_at_work_area,
            "is_minimized": is_iconic,
        }
    return {"is_desktop": False, "is_maximized": False, "is_minimized": False}


# ---------------------------------------------------------------------------
# Static frontend distribution serving (production & standalone desktop app)
# ---------------------------------------------------------------------------
DIST_DIR = _ROOT / "web" / "dist"
if not DIST_DIR.exists():
    alt_dist = _ROOT / "_internal" / "web" / "dist"
    if alt_dist.exists():
        DIST_DIR = alt_dist

if DIST_DIR.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend_dist(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        requested_file = DIST_DIR / full_path
        if requested_file.is_file():
            return FileResponse(str(requested_file))
        index_file = DIST_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        raise HTTPException(status_code=404, detail="Frontend distribution index.html not found")


# ---------------------------------------------------------------------------
# Dev server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "api.server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(_ROOT / "api")],
    )
