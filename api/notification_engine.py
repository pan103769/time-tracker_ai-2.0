"""
api/notification_engine.py — Core notification coordinator, smart distraction detector,
and missed-activity recovery engine for Time Tracker AI 2.

Evaluates idle time, schedule-distraction mismatches against planned time blocks,
and inactive tracking gaps for missed activity recovery.
Persists notifications to tracker.db and triggers Windows desktop toasts.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from api.categories import match_category
from api.windows_notifier import get_notification_settings, send_windows_toast, remove_windows_toast

logger = logging.getLogger("notification_engine")
_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("TIME_TRACKER_DB_PATH", _ROOT / "tracker.db"))

# State cache for deduplication and cooldowns within process
_state_lock = threading.Lock()
_current_idle_episode_notified: bool = False
_last_mismatch_episode_notified: Optional[str] = None
_mismatch_start_time: Optional[float] = None
_mismatch_snoozed_until: float = 0.0
_idle_snoozed_until: float = 0.0
_block_reminders_notified: set[int] = set()
_block_snoozed_until: Dict[int, float] = {}
_block_skipped: set[int] = set()
_block_started: set[int] = set()
_missed_blocks_notified: set[int] = set()


def reset_notification_state():
    """Reset in-memory notification state caches (used for tests and process restarts)."""
    global _current_idle_episode_notified, _last_mismatch_episode_notified
    global _mismatch_start_time, _mismatch_snoozed_until, _idle_snoozed_until
    global _block_reminders_notified, _block_snoozed_until, _block_skipped, _block_started
    global _missed_blocks_notified
    with _state_lock:
        _current_idle_episode_notified = False
        _last_mismatch_episode_notified = None
        _mismatch_start_time = None
        _mismatch_snoozed_until = 0.0
        _idle_snoozed_until = 0.0
        _block_reminders_notified.clear()
        _block_snoozed_until.clear()
        _block_skipped.clear()
        _block_started.clear()
        _missed_blocks_notified.clear()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def parse_db_datetime(val: Any) -> Optional[datetime]:
    """Parse a datetime from sqlite observations/recovery_gaps, ensuring timezone awareness (UTC default)."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(val))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def format_relative_datetime(dt: datetime, reference_dt: Optional[datetime] = None) -> str:
    """Format datetime with clear relative date context (Today, Yesterday, or full date in local timezone)."""
    try:
        local_dt = dt.astimezone() if dt.tzinfo else dt
    except Exception:
        local_dt = dt

    ref = reference_dt or now_utc()
    try:
        local_ref = ref.astimezone() if ref.tzinfo else ref
    except Exception:
        local_ref = ref

    ref_date = local_ref.date()
    activity_date = local_dt.date()
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    if not time_str:
        time_str = local_dt.strftime("%I:%M %p")

    day_diff = (ref_date - activity_date).days
    if day_diff == 0:
        return f"Today at {time_str}"
    elif day_diff == 1:
        return f"Yesterday at {time_str}"
    else:
        date_str = local_dt.strftime("%a, %b %d")
        return f"{date_str} at {time_str}"


def is_in_time_window(target_time: dt_time, start_str: str, end_str: str) -> bool:
    """Check if a time of day falls inside [start_str, end_str], handling overnight wrap-around."""
    try:
        sp = [int(p) for p in start_str.split(":")]
        ep = [int(p) for p in end_str.split(":")]
        start_t = dt_time(sp[0], sp[1])
        end_t = dt_time(ep[0], ep[1])
        if start_t <= end_t:
            return start_t <= target_time <= end_t
        else:
            return target_time >= start_t or target_time <= end_t
    except Exception:
        return False


def calculate_waking_gap_minutes(
    start_dt: datetime,
    end_dt: datetime,
    sleep_start_str: str = "23:00",
    sleep_end_str: str = "07:00",
) -> float:
    """
    Calculate the plausible waking duration (in minutes) within a gap interval.
    Subtracts time falling inside the configured overnight sleep period.
    """
    try:
        start_local = start_dt.astimezone() if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc).astimezone()
        end_local = end_dt.astimezone() if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc).astimezone()
    except Exception:
        start_local = start_dt
        end_local = end_dt

    total_secs = (end_local - start_local).total_seconds()
    if total_secs <= 0:
        return 0.0

    try:
        sp = [int(p) for p in sleep_start_str.split(":")]
        ep = [int(p) for p in sleep_end_str.split(":")]
        start_t = dt_time(sp[0], sp[1])
        end_t = dt_time(ep[0], ep[1])
    except Exception:
        return max(0.0, total_secs / 60.0)

    # Generate sleep windows covering the gap range
    sleep_secs = 0.0
    tz = start_local.tzinfo
    cur_date = start_local.date() - timedelta(days=1)
    max_date = end_local.date() + timedelta(days=1)

    while cur_date <= max_date:
        if start_t > end_t:
            w_start = datetime.combine(cur_date, start_t, tzinfo=tz)
            w_end = datetime.combine(cur_date + timedelta(days=1), end_t, tzinfo=tz)
        else:
            w_start = datetime.combine(cur_date, start_t, tzinfo=tz)
            w_end = datetime.combine(cur_date, end_t, tzinfo=tz)

        overlap_start = max(start_local, w_start)
        overlap_end = min(end_local, w_end)
        if overlap_end > overlap_start:
            sleep_secs += (overlap_end - overlap_start).total_seconds()

        cur_date += timedelta(days=1)

    waking_secs = max(0.0, total_secs - sleep_secs)
    return waking_secs / 60.0


def get_settings_from_db(db: sqlite3.Connection) -> Dict[str, Any]:
    """Load settings directly from active sqlite connection."""
    defaults = {
        "notifications_enabled": True,
        "windows_toasts_enabled": True,
        "notification_sound": "default",
        "idle_alert_threshold_minutes": 3,
        "mismatch_grace_minutes": 2,
        "distraction_cooldown_minutes": 15,
        "missed_recovery_threshold_minutes": 30,
        "missed_recovery_enabled": True,
        "time_block_reminders_enabled": True,
        "time_block_autostart_focus": False,
        "focus_mismatch_alerts_enabled": True,
        "idle_alerts_enabled": True,
        "missed_block_recovery_enabled": True,
        "default_snooze_minutes": 5,
        "notification_rate_limit_seconds": 45,
        "quiet_hours_enabled": False,
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "overnight_suppression_enabled": True,
        "overnight_sleep_start": "23:00",
        "overnight_sleep_end": "07:00",
    }
    try:
        rows = db.execute("SELECT key, value FROM app_settings").fetchall()
        result = dict(defaults)
        for r in rows:
            k, v = r["key"], r["value"]
            if k in (
                "notifications_enabled",
                "windows_toasts_enabled",
                "missed_recovery_enabled",
                "time_block_reminders_enabled",
                "time_block_autostart_focus",
                "focus_mismatch_alerts_enabled",
                "idle_alerts_enabled",
                "missed_block_recovery_enabled",
                "quiet_hours_enabled",
                "overnight_suppression_enabled",
            ):
                result[k] = str(v).lower() in ("true", "1", "yes")
            elif k in (
                "idle_alert_threshold_minutes",
                "mismatch_grace_minutes",
                "distraction_cooldown_minutes",
                "missed_recovery_threshold_minutes",
                "default_snooze_minutes",
                "notification_rate_limit_seconds",
            ):
                try:
                    result[k] = int(v)
                except ValueError:
                    pass
            else:
                result[k] = v
        return result
    except Exception:
        return defaults


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = db_path or DB_PATH
    conn = sqlite3.connect(str(target), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Snooze Controls
# ---------------------------------------------------------------------------

def snooze_idle_alerts(minutes: int = 5):
    """Snooze idle notifications for the specified duration."""
    global _idle_snoozed_until
    with _state_lock:
        _idle_snoozed_until = time.time() + (minutes * 60)


def snooze_mismatch_alerts(minutes: int = 15):
    """Snooze focus schedule-mismatch alerts for the specified duration."""
    global _mismatch_snoozed_until
    with _state_lock:
        _mismatch_snoozed_until = time.time() + (minutes * 60)


# ---------------------------------------------------------------------------
# Notification Persistence & Queries
# ---------------------------------------------------------------------------

def create_notification(
    db: sqlite3.Connection,
    notif_type: str,
    title: str,
    body: str,
    details: Optional[Dict[str, Any]] = None,
    status: str = "delivered",
) -> Dict[str, Any]:
    """Store a notification in the database."""
    ts = now_iso()
    details_str = json.dumps(details) if details else None
    try:
        cursor = db.execute(
            """
            INSERT INTO notifications (type, title, body, details, unread, dismissed, status, created_at)
            VALUES (?, ?, ?, ?, 1, 0, ?, ?)
            """,
            (notif_type, title, body, details_str, status, ts),
        )
    except sqlite3.OperationalError as e:
        if "no column named status" in str(e).lower():
            cursor = db.execute(
                """
                INSERT INTO notifications (type, title, body, details, unread, dismissed, created_at)
                VALUES (?, ?, ?, ?, 1, 0, ?)
                """,
                (notif_type, title, body, details_str, ts),
            )
        else:
            raise
    db.commit()
    notif_id = cursor.lastrowid
    return {
        "id": notif_id,
        "type": notif_type,
        "title": title,
        "body": body,
        "details": details,
        "unread": True,
        "dismissed": False,
        "status": status,
        "created_at": ts,
    }


def update_notification_status(db: sqlite3.Connection, notif_id: int, status: str) -> bool:
    """Update notification lifecycle status (e.g. 'acted_upon', 'snoozed', 'skipped', 'dismissed')."""
    try:
        db.execute(
            "UPDATE notifications SET status = ?, unread = 0 WHERE id = ?",
            (status, notif_id),
        )
        db.commit()
        return True
    except Exception:
        return False


def get_notifications(
    db: sqlite3.Connection,
    limit: int = 50,
    filter_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Return notifications list and unread count."""
    query = "SELECT * FROM notifications WHERE dismissed = 0"
    params: List[Any] = []

    if filter_type and filter_type != "all":
        if filter_type == "unread":
            query += " AND unread = 1"
        else:
            query += " AND type = ?"
            params.append(filter_type)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()

    items = []
    for r in rows:
        details_val = None
        if r["details"]:
            try:
                details_val = json.loads(r["details"])
            except Exception:
                details_val = None

        r_keys = r.keys()
        items.append({
            "id": r["id"],
            "type": r["type"],
            "title": r["title"],
            "body": r["body"],
            "details": details_val,
            "unread": bool(r["unread"]),
            "dismissed": bool(r["dismissed"]),
            "status": r["status"] if "status" in r_keys and r["status"] else "delivered",
            "created_at": r["created_at"],
        })

    unread_row = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE dismissed = 0 AND unread = 1"
    ).fetchone()
    unread_count = unread_row[0] if unread_row else 0

    return {
        "notifications": items,
        "unread_count": unread_count,
    }


def mark_notification_read(db: sqlite3.Connection, notification_id: int) -> bool:
    """Mark a notification as read."""
    cursor = db.execute(
        "UPDATE notifications SET unread = 0 WHERE id = ?",
        (notification_id,),
    )
    db.commit()
    return cursor.rowcount > 0


def mark_all_read(db: sqlite3.Connection) -> int:
    """Mark all notifications as read."""
    cursor = db.execute("UPDATE notifications SET unread = 0 WHERE unread = 1")
    db.commit()
    return cursor.rowcount


def dismiss_notification(db: sqlite3.Connection, notification_id: int) -> bool:
    """Dismiss a notification from view."""
    cursor = db.execute(
        "UPDATE notifications SET dismissed = 1, unread = 0 WHERE id = ?",
        (notification_id,),
    )
    db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Idle Evaluation
# ---------------------------------------------------------------------------

def evaluate_idle_condition(
    db: sqlite3.Connection,
    idle_seconds: float,
    is_tracking: bool,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check if user inactivity crossed the idle threshold.
    Alerts once per continuous idle episode and triggers Windows desktop toast.
    """
    global _current_idle_episode_notified, _idle_snoozed_until

    if not is_tracking:
        with _state_lock:
            _current_idle_episode_notified = False
        return None

    settings = get_settings_from_db(db)
    if not settings.get("notifications_enabled", True):
        return None
    if not settings.get("idle_alerts_enabled", True):
        return None

    threshold_mins = settings.get("idle_alert_threshold_minutes", 3)
    threshold_secs = threshold_mins * 60

    with _state_lock:
        if idle_seconds < 15.0:
            # User has resumed active input
            _current_idle_episode_notified = False
            return None

        if idle_seconds >= threshold_secs and not _current_idle_episode_notified:
            if time.time() < _idle_snoozed_until:
                return None

            _current_idle_episode_notified = True

            title = "Inactivity Detected"
            body = f"You've been away for {threshold_mins} minutes. Ready to resume tracking?"
            now_local = datetime.now()
            time_str = now_local.strftime("%I:%M %p").lstrip("0")
            idle_actions = [
                {
                    "content": "Resume Work",
                    "arguments": "timetracker://navigate?action=resume_work",
                    "icon": "btn_play.png",
                },
                {
                    "content": "Start Break",
                    "arguments": "timetracker://navigate?action=start_break",
                    "icon": "btn_cross.png",
                },
                {
                    "content": "Snooze 5 min",
                    "arguments": "timetracker://action?name=snooze_idle_5",
                    "icon": "btn_clock.png",
                },
            ]

            # 1. Post native Windows Toast
            send_windows_toast(
                title=title,
                message=body,
                timestamp_str=time_str,
                launch_url="timetracker://navigate?action=resume_work",
                actions=idle_actions,
                scenario="default",
                tag="idle_current",
                group="time_tracker",
                db_path=db_path,
            )

            # 2. Persist in Notification Center
            return create_notification(
                db,
                notif_type="idle",
                title=title,
                body=body,
                details={"idle_minutes": threshold_mins},
                status="delivered",
            )

    return None


# ---------------------------------------------------------------------------
# Smart Distraction & Schedule-Mismatch Evaluation
# ---------------------------------------------------------------------------

def _is_distraction_activity(db: sqlite3.Connection, app: str, title: str) -> bool:
    """Return True if an application or window title represents known distracting activity."""
    app_lower = (app or "").lower()
    title_lower = (title or "").lower()

    distraction_apps = {
        "spotify.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
        "discord.exe", "netflix.exe", "vlc.exe", "tiktok.exe",
    }
    if app_lower in distraction_apps:
        return True

    distraction_keywords = [
        "youtube", "netflix", "reddit", "twitter", "x.com", "instagram",
        "facebook", "twitch", "tiktok", "9gag", "steam",
    ]
    if any(k in app_lower or k in title_lower for k in distraction_keywords):
        return True

    # Check categorized type in category rules
    cat = match_category(db, app, title)
    if cat and cat.get("type") == "distraction":
        return True

    return False


def evaluate_schedule_mismatch(
    db: sqlite3.Connection,
    active_obs: Optional[Dict[str, Any]],
    is_tracking: bool,
    now_override: Optional[datetime] = None,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Compare current active activity with planned time blocks.
    Respects grace periods, ignores quick switches, and alerts once per episode.
    """
    global _mismatch_start_time, _last_mismatch_episode_notified, _mismatch_snoozed_until

    if not is_tracking or not active_obs:
        with _state_lock:
            _mismatch_start_time = None
        return None

    if active_obs.get("kind") == "idle":
        with _state_lock:
            _mismatch_start_time = None
        return None

    settings = get_settings_from_db(db)
    if not settings.get("notifications_enabled", True):
        return None
    if not settings.get("focus_mismatch_alerts_enabled", True):
        return None

    # Check active time block for current local time
    now_dt = now_override or datetime.now()
    try:
        now_local = now_dt.astimezone() if now_dt.tzinfo else now_dt
    except Exception:
        now_local = now_dt

    date_str = now_local.strftime("%Y-%m-%d")

    rows = db.execute(
        """
        SELECT tb.*, c.name as category_name, c.type as category_type
        FROM time_blocks tb
        LEFT JOIN categories c ON tb.category_id = c.id
        WHERE tb.date = ?
        ORDER BY tb.id DESC
        """,
        (date_str,),
    ).fetchall()

    current_block = None
    for r in rows:
        b = dict(r)
        try:
            b_start = _parse_time_block_datetime(b["date"], b["start_time"], now_local.tzinfo)
            b_end = _parse_time_block_datetime(b["date"], b["end_time"], now_local.tzinfo)
            if b_end <= b_start:
                b_end += timedelta(days=1)
            if b_start <= now_local <= b_end:
                current_block = b
                break
        except Exception:
            continue

    if not current_block:
        with _state_lock:
            _mismatch_start_time = None
            _last_mismatch_episode_notified = None
        return None
    app = active_obs.get("app", "Unknown")
    title = active_obs.get("title", "")

    # Check if current activity matches planned block
    cat = match_category(db, app, title)
    cat_id = cat["id"] if cat else None
    cat_type = cat["type"] if cat else None

    is_mismatch = False
    if current_block.get("category_id"):
        if cat_id != current_block["category_id"]:
            if _is_distraction_activity(db, app, title) or cat_type == "distraction":
                is_mismatch = True
    else:
        # Generic focus block: any confirmed distraction counts as mismatch
        if _is_distraction_activity(db, app, title) or cat_type == "distraction":
            is_mismatch = True

    if not is_mismatch:
        with _state_lock:
            _mismatch_start_time = None
            _last_mismatch_episode_notified = None
        return None

    # Mismatch detected: evaluate grace period
    grace_mins = settings.get("mismatch_grace_minutes", 2)
    grace_secs = max(30.0, grace_mins * 60.0)

    now_ts = time.time()
    with _state_lock:
        if _mismatch_start_time is None:
            _mismatch_start_time = now_ts
            return None

        elapsed = now_ts - _mismatch_start_time
        if elapsed < grace_secs:
            return None

        # Check snooze
        if now_ts < _mismatch_snoozed_until:
            return None

        episode_key = f"{current_block['id']}_{app}"
        if _last_mismatch_episode_notified == episode_key:
            return None

        _last_mismatch_episode_notified = episode_key

        block_title = current_block.get("title") or "Planned Task"
        notif_title = f"You may have drifted from {block_title}"
        notif_body = "Recent activity appears unrelated to your current task."

        details = {
            "block_id": current_block["id"],
            "block_title": block_title,
            "start_time": current_block["start_time"],
            "end_time": current_block["end_time"],
            "app": app,
        }

        now_local = datetime.now()
        time_str = now_local.strftime("%I:%M %p").lstrip("0")
        block_id = current_block.get("id", "")
        focus_actions = [
            {
                "content": "Return to Task",
                "arguments": f"timetracker://action?name=return_to_task&block_id={block_id}",
                "icon": "btn_play.png",
            },
            {
                "content": "Review Activity",
                "arguments": f"timetracker://navigate?action=review_activity&block_id={block_id}",
            },
            {
                "content": "Switch Task",
                "arguments": f"timetracker://navigate?action=switch_task&block_id={block_id}",
            },
            {
                "content": "Snooze 15 min",
                "arguments": "timetracker://action?name=snooze_mismatch_15",
                "icon": "btn_clock.png",
            },
        ]

        # 1. Post native Windows Toast with reminder scenario for visible desktop banner
        send_windows_toast(
            title=notif_title,
            message=notif_body,
            timestamp_str=time_str,
            launch_url=f"timetracker://navigate?action=return_to_task&block_id={block_id}",
            actions=focus_actions,
            scenario="reminder",
            tag=f"mismatch_{block_id}",
            group="time_tracker",
            db_path=db_path,
        )

        # 2. Persist in Notification Center
        return create_notification(
            db,
            notif_type="focus",
            title=notif_title,
            body=notif_body,
            details=details,
            status="delivered",
        )


# ---------------------------------------------------------------------------
# Scheduled Time-Block Start Reminders & Focus Session Integration
# ---------------------------------------------------------------------------

def _is_block_started(db: sqlite3.Connection, block_id: int) -> bool:
    """Check if focus session has already been started for a time block."""
    with _state_lock:
        if block_id in _block_started:
            return True
    try:
        row = db.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (f"block_focus_started_{block_id}",),
        ).fetchone()
        return bool(row and row["value"] in ("1", "true"))
    except Exception:
        return False


def _mark_block_started(db: sqlite3.Connection, block_id: int):
    """Mark a time block as started in in-memory state and persistent app_settings."""
    with _state_lock:
        _block_started.add(block_id)
        _block_reminders_notified.add(block_id)
    try:
        ts = now_iso()
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, '1', ?)
            ON CONFLICT(key) DO UPDATE SET value = '1', updated_at = excluded.updated_at
            """,
            (f"block_focus_started_{block_id}", ts),
        )
        db.commit()
    except Exception:
        pass


def _is_block_skipped(db: sqlite3.Connection, block_id: int) -> bool:
    """Check if user has chosen to skip reminder for this time block."""
    with _state_lock:
        if block_id in _block_skipped:
            return True
    try:
        row = db.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (f"block_skipped_{block_id}",),
        ).fetchone()
        return bool(row and row["value"] in ("1", "true"))
    except Exception:
        return False


def _get_block_snoozed_until(db: sqlite3.Connection, block_id: int) -> Optional[float]:
    """Return unix timestamp until which this time block reminder is snoozed, or None."""
    with _state_lock:
        if block_id in _block_snoozed_until:
            return _block_snoozed_until[block_id]
    try:
        row = db.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (f"block_snoozed_until_{block_id}",),
        ).fetchone()
        if row and row["value"]:
            val = float(row["value"])
            with _state_lock:
                _block_snoozed_until[block_id] = val
            return val
    except Exception:
        pass
    return None


def _mark_block_reminded(db: sqlite3.Connection, block_id: int):
    """Mark a time block as reminded or expired in memory and persistent storage."""
    with _state_lock:
        _block_reminders_notified.add(block_id)
    try:
        ts = now_iso()
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, '1', ?)
            ON CONFLICT(key) DO UPDATE SET value = '1', updated_at = excluded.updated_at
            """,
            (f"notif_block_reminded_{block_id}", ts),
        )
        db.commit()
    except Exception:
        pass


def _has_block_been_notified(db: sqlite3.Connection, block_id: int) -> bool:
    """Check if start reminder has already been dispatched for this time block."""
    with _state_lock:
        if block_id in _block_reminders_notified:
            return True
    try:
        row_sett = db.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (f"notif_block_reminded_{block_id}",),
        ).fetchone()
        if row_sett and str(row_sett["value"]).lower() in ("1", "true"):
            with _state_lock:
                _block_reminders_notified.add(block_id)
            return True
        row = db.execute(
            """
            SELECT id FROM notifications
            WHERE type = 'time_block' AND details LIKE ?
            LIMIT 1
            """,
            (f'%"block_id": {block_id}%',),
        ).fetchone()
        if row:
            with _state_lock:
                _block_reminders_notified.add(block_id)
            return True
    except Exception:
        pass
    return False


def _parse_time_block_datetime(date_str: str, time_str: str, tzinfo: Optional[timezone] = None) -> datetime:
    """Parse time block date and start/end string into timezone-aware datetime."""
    t_str = str(time_str).strip()
    if "T" in t_str:
        dt = datetime.fromisoformat(t_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tzinfo)
        return dt.astimezone(tzinfo)

    # Standard "HH:MM" or "HH:MM:SS"
    parts = [int(p) for p in t_str.split(":")[:2]]
    d_parts = [int(p) for p in date_str.split("-")[:3]]
    return datetime(d_parts[0], d_parts[1], d_parts[2], parts[0], parts[1], tzinfo=tzinfo)


def evaluate_time_block_reminders(
    db: sqlite3.Connection,
    is_tracking: bool = False,
    now_override: Optional[datetime] = None,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Evaluate planned time blocks against current local time.
    Dispatches native Windows desktop notification when a scheduled block is about to start or just started.
    Strictly prevents stale start notifications for expired or overdue blocks.
    Respects quiet hours, overnight sleep periods, and deduplication.
    """
    settings = get_settings_from_db(db)
    if not settings.get("notifications_enabled", True):
        return None
    if not settings.get("time_block_reminders_enabled", True):
        return None

    now_dt = now_override or now_utc()
    try:
        now_local = now_dt.astimezone() if now_dt.tzinfo else now_dt
    except Exception:
        now_local = now_dt

    today_str = now_local.strftime("%Y-%m-%d")
    now_ts = now_dt.timestamp()

    # Quiet hours check
    in_quiet_hours = False
    if settings.get("quiet_hours_enabled", False):
        qh_start = settings.get("quiet_hours_start", "22:00")
        qh_end = settings.get("quiet_hours_end", "07:00")
        if is_in_time_window(now_local.time(), qh_start, qh_end):
            in_quiet_hours = True

    # Overnight suppression check
    if settings.get("overnight_suppression_enabled", True):
        sleep_start = settings.get("overnight_sleep_start", "23:00")
        sleep_end = settings.get("overnight_sleep_end", "07:00")
        if is_in_time_window(now_local.time(), sleep_start, sleep_end):
            in_quiet_hours = True

    # Query today's scheduled time blocks
    rows = db.execute(
        """
        SELECT tb.*, c.name as category_name, c.color as category_color, c.type as category_type
        FROM time_blocks tb
        LEFT JOIN categories c ON tb.category_id = c.id
        WHERE tb.date = ?
        ORDER BY tb.start_time ASC
        """,
        (today_str,),
    ).fetchall()

    if not rows:
        return None

    for r in rows:
        b = dict(r)
        block_id = b["id"]
        block_title = (b.get("title") or "Focus Block").strip()

        try:
            b_start = _parse_time_block_datetime(b["date"], b["start_time"], now_local.tzinfo)
            b_end = _parse_time_block_datetime(b["date"], b["end_time"], now_local.tzinfo)
            if b_end <= b_start:
                b_end += timedelta(days=1)
        except Exception as e:
            logger.debug("Could not parse time block %s timestamps: %s", block_id, e)
            continue

        # 1. Block has already ended in the past (expired)
        # NEVER describe an expired block as starting now!
        if now_local >= b_end:
            _mark_block_reminded(db, block_id)
            continue

        # 2. Block has not reached notification window yet (starts at b_start - 5 minutes)
        time_until_start = (b_start - now_local).total_seconds()
        if time_until_start > 300:  # > 5 minutes before scheduled start
            continue

        # 3. Missed start times protection (e.g. system was sleeping or app was off during start time)
        # If block started > 10 minutes ago, do not fire overdue start notification
        delta_secs = (now_local - b_start).total_seconds()
        if delta_secs > 600:  # > 10 minutes past start
            _mark_block_reminded(db, block_id)
            continue

        # 4. Set the block as the current planned task in app_settings (without claiming work has begun)
        ts_iso = now_iso()
        try:
            db.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ('current_planned_task', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (block_title, ts_iso),
            )
            db.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ('current_planned_block_id', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (str(block_id), ts_iso),
            )
            db.commit()
        except Exception:
            pass

        # 5. Check if user already started the block
        if _is_block_started(db, block_id):
            _mark_block_reminded(db, block_id)
            continue

        # Check if currently tracking an active task that matches this block
        if is_tracking:
            try:
                import api.tracker_manager as tracker_mgr
                active_task = tracker_mgr.get_active_task()
                if active_task:
                    t_name = (active_task.get("user_task") or active_task.get("title") or "").strip().lower()
                    b_title_lower = block_title.lower()
                    if b_title_lower and (t_name == b_title_lower or (b_title_lower in t_name and len(b_title_lower) > 3)):
                        _mark_block_started(db, block_id)
                        _mark_block_reminded(db, block_id)
                        continue
            except Exception:
                pass

        # 6. Check if user chose to skip this block
        if _is_block_skipped(db, block_id):
            _mark_block_reminded(db, block_id)
            continue

        # 7. Check if reminder is snoozed
        snoozed_until = _get_block_snoozed_until(db, block_id)
        if snoozed_until is not None:
            if now_ts < snoozed_until:
                # Still within snooze window
                continue
            # Snooze expired: proceed to re-remind

        # 8. Auto-start focus session if optionally enabled by user preference
        if settings.get("time_block_autostart_focus", False):
            logger.info("Auto-starting focus session for time block: %s", block_title)
            res = start_focus_for_time_block(db, block_id)
            _mark_block_reminded(db, block_id)
            return {
                "block_id": block_id,
                "title": block_title,
                "auto_started": True,
                "result": res,
            }

        # 9. Check if already notified and not snoozed
        if _has_block_been_notified(db, block_id) and snoozed_until is None:
            continue

        # 10. Quiet hours suppression: keep planned task set, but suppress desktop toast
        if in_quiet_hours:
            logger.debug("Time block reminder toast suppressed during quiet hours: %s", block_title)
            _mark_block_reminded(db, block_id)
            continue

        # 11. Format time range and duration for toast
        start_fmt = b_start.strftime("%I:%M %p").lstrip("0")
        end_fmt = b_end.strftime("%I:%M %p").lstrip("0")
        time_range_str = f"{start_fmt} - {end_fmt}"

        dur_mins = int(round((b_end - b_start).total_seconds() / 60))
        dur_str = f"{dur_mins // 60}h {dur_mins % 60}m" if dur_mins >= 60 else f"{dur_mins} min"

        title = f"Time to start {block_title}"
        body = f"{time_range_str} · {dur_str} planned"

        actions = [
            {
                "content": "Start Focus",
                "arguments": f"timetracker://navigate?action=start_focus_block&block_id={block_id}",
                "icon": "btn_play.png",
            },
            {
                "content": "Snooze 5 min",
                "arguments": f"timetracker://action?name=snooze_block&block_id={block_id}&minutes=5",
                "icon": "btn_clock.png",
            },
            {
                "content": "Skip Block",
                "arguments": f"timetracker://action?name=skip_block&block_id={block_id}",
                "icon": "btn_cross.png",
            },
            {
                "content": "Open Planner",
                "arguments": f"timetracker://navigate?action=open_planner&block_id={block_id}",
            },
        ]

        now_local_str = now_local.strftime("%I:%M %p").lstrip("0")

        # 12. Dispatch native Windows toast with reminder scenario and tag grouping
        send_windows_toast(
            title=title,
            message=body,
            timestamp_str=now_local_str,
            launch_url=f"timetracker://navigate?action=open_planner&block_id={block_id}",
            actions=actions,
            scenario="reminder",
            tag=f"block_{block_id}",
            group="time_tracker",
            db_path=db_path,
        )

        _mark_block_reminded(db, block_id)
        if snoozed_until is not None:
            try:
                db.execute("DELETE FROM app_settings WHERE key = ?", (f"block_snoozed_until_{block_id}",))
                db.commit()
                with _state_lock:
                    _block_snoozed_until.pop(block_id, None)
            except Exception:
                pass

        # 13. Persist in Notification Center
        details = {
            "block_id": block_id,
            "block_title": block_title,
            "category_id": b.get("category_id"),
            "category_name": b.get("category_name"),
            "start_time": b["start_time"],
            "end_time": b["end_time"],
            "time_range": time_range_str,
            "duration_minutes": dur_mins,
        }
        notif = create_notification(
            db,
            notif_type="time_block",
            title=title,
            body=f"Scheduled for {time_range_str} ({dur_str}). Ready to begin your planned focus session?",
            details=details,
            status="delivered",
        )

        return {
            "block_id": block_id,
            "title": block_title,
            "time_range": time_range_str,
            "notification": notif,
        }

    return None


def start_focus_for_time_block(
    db: sqlite3.Connection,
    block_id: int,
) -> Dict[str, Any]:
    """
    Make the block the active task and start a linked Focus Session using existing tracking/session functionality.
    Does not fabricate historical observations or record fake work.
    """
    row = db.execute(
        """
        SELECT tb.*, c.name as category_name, c.type as category_type
        FROM time_blocks tb
        LEFT JOIN categories c ON tb.category_id = c.id
        WHERE tb.id = ?
        """,
        (block_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Time block with id {block_id} not found.")

    block = dict(row)
    block_title = (block.get("title") or "Focus Block").strip()
    cat_id = block.get("category_id")

    # 1. Start tracking if not active
    import api.tracker_manager as tracker_mgr
    if not tracker_mgr.is_tracking_active():
        try:
            tracker_mgr.start_tracking()
        except Exception as e:
            logger.warning("Could not start tracking process on Start Focus: %s", e)

    # 2. Assign active task name and category
    active_task = tracker_mgr.assign_active_task(task_name=block_title, category_id=cat_id)

    # 3. Mark block as started in state and persistent settings
    _mark_block_started(db, block_id)

    ts = now_iso()
    try:
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('current_planned_task', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (block_title, ts),
        )
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('current_focus_block_id', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (str(block_id), ts),
        )
        db.commit()
    except Exception:
        pass

    # 4. Remove active Windows toast banner immediately
    try:
        remove_windows_toast(tag=f"block_{block_id}", group="time_tracker")
    except Exception:
        pass

    # 5. Mark related time_block notification as read and acted_upon
    try:
        db.execute(
            """
            UPDATE notifications
            SET unread = 0, status = 'acted_upon'
            WHERE type = 'time_block' AND details LIKE ?
            """,
            (f'%"block_id": {block_id}%',),
        )
        db.commit()
    except Exception:
        pass

    return {
        "status": "started",
        "block_id": block_id,
        "title": block_title,
        "category_id": cat_id,
        "active_task": active_task,
    }


def snooze_time_block_reminder(
    db: sqlite3.Connection,
    block_id: int,
    minutes: int = 5,
) -> Dict[str, Any]:
    """
    Postpone the time-block start reminder without changing the scheduled block dates or times.
    """
    duration_mins = max(1, min(60, minutes))
    until_ts = time.time() + (duration_mins * 60)

    with _state_lock:
        _block_snoozed_until[block_id] = until_ts

    ts = now_iso()
    try:
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (f"block_snoozed_until_{block_id}", str(until_ts), ts),
        )
        # Remove active Windows toast banner immediately
        remove_windows_toast(tag=f"block_{block_id}", group="time_tracker")
        # Mark related notification as snoozed
        db.execute(
            """
            UPDATE notifications
            SET unread = 0, status = 'snoozed'
            WHERE type = 'time_block' AND details LIKE ?
            """,
            (f'%"block_id": {block_id}%',),
        )
        db.commit()
    except Exception:
        pass

    return {
        "status": "snoozed",
        "block_id": block_id,
        "minutes": duration_mins,
        "snoozed_until": until_ts,
    }


def skip_time_block(
    db: sqlite3.Connection,
    block_id: int,
) -> Dict[str, Any]:
    """
    Dismiss the reminder without deleting the block or recording fake work.
    """
    with _state_lock:
        _block_skipped.add(block_id)
        _block_reminders_notified.add(block_id)

    ts = now_iso()
    try:
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, '1', ?)
            ON CONFLICT(key) DO UPDATE SET value = '1', updated_at = excluded.updated_at
            """,
            (f"block_skipped_{block_id}", ts),
        )
        # Remove active Windows toast banner immediately
        remove_windows_toast(tag=f"block_{block_id}", group="time_tracker")
        # Dismiss related notification
        db.execute(
            """
            UPDATE notifications
            SET dismissed = 1, unread = 0, status = 'skipped'
            WHERE type = 'time_block' AND details LIKE ?
            """,
            (f'%"block_id": {block_id}%',),
        )
        db.commit()
    except Exception:
        pass

    return {
        "status": "skipped",
        "block_id": block_id,
    }


def reschedule_time_block(
    db: sqlite3.Connection,
    block_id: int,
    new_date: str,
    new_start_time: str,
    new_end_time: str,
) -> Dict[str, Any]:
    """
    Update a scheduled block to a new time window, reset reminder flags so it can notify at the new time,
    and remove any active Windows toast.
    """
    row = db.execute("SELECT * FROM time_blocks WHERE id = ?", (block_id,)).fetchone()
    if not row:
        raise ValueError(f"Time block {block_id} not found.")

    # Update block
    db.execute(
        """
        UPDATE time_blocks
        SET date = ?, start_time = ?, end_time = ?
        WHERE id = ?
        """,
        (new_date, new_start_time, new_end_time, block_id),
    )

    # Clear reminder and skipped flags so it can notify at new time
    with _state_lock:
        _block_reminders_notified.discard(block_id)
        _block_skipped.discard(block_id)
        _block_started.discard(block_id)
        _block_snoozed_until.pop(block_id, None)
        _missed_blocks_notified.discard(block_id)

    try:
        db.execute(
            """
            DELETE FROM app_settings
            WHERE key IN (?, ?, ?, ?, ?)
            """,
            (
                f"notif_block_reminded_{block_id}",
                f"block_skipped_{block_id}",
                f"block_focus_started_{block_id}",
                f"block_snoozed_until_{block_id}",
                f"missed_block_notified_{block_id}",
            ),
        )
        db.execute(
            """
            UPDATE notifications
            SET dismissed = 1, unread = 0, status = 'acted_upon'
            WHERE (type = 'time_block' OR type = 'missed_block') AND details LIKE ?
            """,
            (f'%"block_id": {block_id}%',),
        )
        db.commit()
    except Exception:
        pass

    try:
        remove_windows_toast(tag=f"block_{block_id}", group="time_tracker")
        remove_windows_toast(tag=f"missed_{block_id}", group="time_tracker")
    except Exception:
        pass

    return {
        "status": "rescheduled",
        "block_id": block_id,
        "date": new_date,
        "start_time": new_start_time,
        "end_time": new_end_time,
    }


def evaluate_missed_block_recovery(
    db: sqlite3.Connection,
    is_tracking: bool = False,
    now_override: Optional[datetime] = None,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check for scheduled blocks that ended recently without focus session or tracked work.
    Dispatches a single actionable missed-block recovery notification (not a start reminder).
    Suppressed during quiet hours, overnight sleep periods, and when disabled in settings.
    """
    global _missed_blocks_notified

    settings = get_settings_from_db(db)
    if not settings.get("notifications_enabled", True):
        return None
    if not settings.get("missed_block_recovery_enabled", True):
        return None

    now_dt = now_override or now_utc()
    try:
        now_local = now_dt.astimezone() if now_dt.tzinfo else now_dt
    except Exception:
        now_local = now_dt

    today_str = now_local.strftime("%Y-%m-%d")

    # Quiet hours check
    if settings.get("quiet_hours_enabled", False):
        qh_start = settings.get("quiet_hours_start", "22:00")
        qh_end = settings.get("quiet_hours_end", "07:00")
        if is_in_time_window(now_local.time(), qh_start, qh_end):
            return None

    # Overnight suppression check
    if settings.get("overnight_suppression_enabled", True):
        sleep_start = settings.get("overnight_sleep_start", "23:00")
        sleep_end = settings.get("overnight_sleep_end", "07:00")
        if is_in_time_window(now_local.time(), sleep_start, sleep_end):
            return None

    # Query today's scheduled time blocks
    rows = db.execute(
        """
        SELECT tb.*, c.name as category_name
        FROM time_blocks tb
        LEFT JOIN categories c ON tb.category_id = c.id
        WHERE tb.date = ?
        ORDER BY tb.end_time DESC
        """,
        (today_str,),
    ).fetchall()

    for r in rows:
        b = dict(r)
        block_id = b["id"]
        block_title = (b.get("title") or "Planned Task").strip()

        try:
            b_start = _parse_time_block_datetime(b["date"], b["start_time"], now_local.tzinfo)
            b_end = _parse_time_block_datetime(b["date"], b["end_time"], now_local.tzinfo)
            if b_end <= b_start:
                b_end += timedelta(days=1)
        except Exception:
            continue

        # Must have already ended in the past
        if now_local < b_end:
            continue

        # Must have ended recently: within the last 90 minutes
        ended_mins_ago = (now_local - b_end).total_seconds() / 60.0
        if ended_mins_ago > 90.0:
            continue

        # Must not have been started or explicitly skipped
        if _is_block_started(db, block_id) or _is_block_skipped(db, block_id):
            continue

        # Check if already notified for missed block
        with _state_lock:
            if block_id in _missed_blocks_notified:
                continue

        try:
            notified_row = db.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (f"missed_block_notified_{block_id}",),
            ).fetchone()
            if notified_row and str(notified_row["value"]).lower() in ("1", "true"):
                with _state_lock:
                    _missed_blocks_notified.add(block_id)
                continue
        except Exception:
            pass

        # Check if there was substantial matching tracked activity during the block interval
        try:
            matched_act = db.execute(
                """
                SELECT SUM(duration_seconds) as total_dur
                FROM observations
                WHERE datetime(start_time) >= datetime(?)
                  AND datetime(end_time) <= datetime(?)
                  AND kind = 'active'
                """,
                (b_start.isoformat(), b_end.isoformat()),
            ).fetchone()
            if matched_act and matched_act["total_dur"] and matched_act["total_dur"] >= 600:
                # User did at least 10 minutes of active work in that period, consider it met
                continue
        except Exception:
            pass

        # Mark as notified to ensure exactly 1 recovery prompt
        with _state_lock:
            _missed_blocks_notified.add(block_id)

        try:
            ts_iso = now_iso()
            db.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, '1', ?)
                ON CONFLICT(key) DO UPDATE SET value = '1', updated_at = excluded.updated_at
                """,
                (f"missed_block_notified_{block_id}", ts_iso),
            )
            db.commit()
        except Exception:
            pass

        start_fmt = b_start.strftime("%I:%M %p").lstrip("0")
        end_fmt = b_end.strftime("%I:%M %p").lstrip("0")
        time_range_str = f"{start_fmt} - {end_fmt}"

        title = f"Missed block: {block_title}"
        body = f"Scheduled for {time_range_str}. Would you like to reschedule or review your activity?"

        actions = [
            {
                "content": "Reschedule",
                "arguments": f"timetracker://navigate?action=reschedule_block&block_id={block_id}",
                "icon": "btn_clock.png",
            },
            {
                "content": "Review Activity",
                "arguments": f"timetracker://navigate?action=review_activity&block_id={block_id}",
            },
            {
                "content": "Dismiss",
                "arguments": f"timetracker://action?name=dismiss_missed_block&block_id={block_id}",
                "icon": "btn_cross.png",
            },
        ]

        now_local_str = now_local.strftime("%I:%M %p").lstrip("0")

        # Dispatch Windows toast with tag missed_{block_id}
        send_windows_toast(
            title=title,
            message=body,
            timestamp_str=now_local_str,
            launch_url=f"timetracker://navigate?action=open_planner&block_id={block_id}",
            actions=actions,
            scenario="reminder",
            tag=f"missed_{block_id}",
            group="time_tracker",
            db_path=db_path,
        )

        details = {
            "block_id": block_id,
            "block_title": block_title,
            "time_range": time_range_str,
            "category_name": b.get("category_name"),
            "ended_minutes_ago": int(round(ended_mins_ago)),
        }

        notif = create_notification(
            db,
            notif_type="missed_block",
            title=title,
            body=body,
            details=details,
            status="delivered",
        )

        return {
            "block_id": block_id,
            "title": block_title,
            "time_range": time_range_str,
            "notification": notif,
        }

    return None


def get_current_planned_block(
    db: sqlite3.Connection,
    now_override: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return the current scheduled block for local time, including focus session state.
    """
    now_dt = now_override or now_utc()
    try:
        now_local = now_dt.astimezone() if now_dt.tzinfo else now_dt
    except Exception:
        now_local = now_dt

    today_str = now_local.strftime("%Y-%m-%d")

    rows = db.execute(
        """
        SELECT tb.*, c.name as category_name, c.color as category_color, c.type as category_type
        FROM time_blocks tb
        LEFT JOIN categories c ON tb.category_id = c.id
        WHERE tb.date = ?
        ORDER BY tb.start_time ASC
        """,
        (today_str,),
    ).fetchall()

    for r in rows:
        b = dict(r)
        try:
            b_start = _parse_time_block_datetime(b["date"], b["start_time"], now_local.tzinfo)
            b_end = _parse_time_block_datetime(b["date"], b["end_time"], now_local.tzinfo)
            if b_end <= b_start:
                b_end += timedelta(days=1)
        except Exception:
            continue

        if b_start <= now_local <= b_end:
            b_id = b["id"]
            b["is_started"] = _is_block_started(db, b_id)
            b["is_skipped"] = _is_block_skipped(db, b_id)
            b["is_current"] = True
            return b

    return None


# ---------------------------------------------------------------------------
# Missed-Activity Recovery Engine
# ---------------------------------------------------------------------------

def detect_missed_activity_gap(
    db: sqlite3.Connection,
    db_path: Optional[Path] = None,
    now_override: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect if tracking resumption or launch follows a significant inactive gap.
    Creates a pending recovery gap entry and dispatches a recovery notification.
    Suppresses prompts for gaps falling in quiet hours or normal overnight sleep periods.
    """
    settings = get_settings_from_db(db)
    if not settings.get("notifications_enabled", True):
        return None
    if not settings.get("missed_recovery_enabled", True):
        return None

    threshold_mins = settings.get("missed_recovery_threshold_minutes", 30)
    threshold_secs = threshold_mins * 60

    now_dt = now_override or now_utc()
    try:
        now_local = now_dt.astimezone()
    except Exception:
        now_local = now_dt

    # 1. Quiet hours suppression check on current time
    if settings.get("quiet_hours_enabled", False):
        qh_start = settings.get("quiet_hours_start", "22:00")
        qh_end = settings.get("quiet_hours_end", "07:00")
        if is_in_time_window(now_local.time(), qh_start, qh_end):
            logger.debug("Missed-activity recovery suppressed during active quiet hours (%s-%s)", qh_start, qh_end)
            return None

    # 2. Overnight sleep suppression check on current time
    overnight_enabled = settings.get("overnight_suppression_enabled", True)
    sleep_start = settings.get("overnight_sleep_start", "23:00")
    sleep_end = settings.get("overnight_sleep_end", "07:00")
    if overnight_enabled and is_in_time_window(now_local.time(), sleep_start, sleep_end):
        logger.debug("Missed-activity recovery suppressed during overnight sleep window (%s-%s)", sleep_start, sleep_end)
        return None

    # 3. Check for active ongoing session
    ongoing = db.execute(
        """
        SELECT id, start_time FROM observations
        WHERE end_time IS NULL
        ORDER BY datetime(start_time) DESC LIMIT 1
        """
    ).fetchone()
    if ongoing:
        ongoing_start = parse_db_datetime(ongoing["start_time"])
        if ongoing_start and (now_dt - ongoing_start).total_seconds() < threshold_secs:
            return None

    # 4. Query true latest chronological closed observation
    last_obs = db.execute(
        """
        SELECT id, start_time, end_time, app, title
        FROM observations
        WHERE end_time IS NOT NULL
        ORDER BY datetime(COALESCE(end_time, start_time)) DESC LIMIT 1
        """
    ).fetchone()

    if not last_obs:
        return None

    last_end_dt = parse_db_datetime(last_obs["end_time"])
    if not last_end_dt:
        return None

    gap_secs = (now_dt - last_end_dt).total_seconds()
    if gap_secs < threshold_secs:
        return None

    # 5. Check if newer tracking observations exist after last_end_dt
    newer_obs = db.execute(
        """
        SELECT id FROM observations
        WHERE datetime(COALESCE(end_time, start_time)) > datetime(?)
        LIMIT 1
        """,
        (last_end_dt.isoformat(),),
    ).fetchone()
    if newer_obs:
        return None

    # 6. Evaluate plausible waking duration
    if overnight_enabled:
        waking_mins = calculate_waking_gap_minutes(last_end_dt, now_dt, sleep_start, sleep_end)
        if waking_mins < threshold_mins:
            logger.info(
                "Overnight gap (%d min total, %.1f min waking) suppressed as normal sleep period",
                int(gap_secs / 60),
                waking_mins,
            )
            return None

    gap_start_iso = last_end_dt.isoformat()
    gap_end_iso = now_dt.isoformat()

    # Check if this exact gap has already been recorded
    existing = db.execute(
        "SELECT id, status FROM recovery_gaps WHERE gap_start = ? AND gap_end = ?",
        (gap_start_iso, gap_end_iso),
    ).fetchone()

    if existing:
        return None

    # Check if any pending gap overlaps significantly
    overlapping = db.execute(
        "SELECT id FROM recovery_gaps WHERE status = 'pending' AND gap_start = ?",
        (gap_start_iso,),
    ).fetchone()

    if overlapping:
        return None

    cursor = db.execute(
        """
        INSERT INTO recovery_gaps (gap_start, gap_end, duration_seconds, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (gap_start_iso, gap_end_iso, gap_secs, now_iso()),
    )
    db.commit()
    gap_id = cursor.lastrowid

    # Format human-readable time with relative date context (local timezone)
    time_str = format_relative_datetime(last_end_dt, reference_dt=now_dt)
    gap_minutes = int(round(gap_secs / 60))

    title = "Welcome back: Recover Missed Activity"
    body = (
        f"Your last recorded activity ended at {time_str}. Tracking was inactive for {gap_minutes} minutes. "
        "Were you doing anything you'd like to add?"
    )

    details = {
        "gap_id": gap_id,
        "gap_start": gap_start_iso,
        "gap_end": gap_end_iso,
        "duration_minutes": gap_minutes,
        "last_app": last_obs["app"],
    }

    recovery_actions = [
        {
            "content": "Add Activity",
            "arguments": f"timetracker://navigate?action=add_activity&gap_id={gap_id}",
            "icon": "btn_play.png",
        },
        {
            "content": "Skip",
            "arguments": f"timetracker://action?name=skip_gap&gap_id={gap_id}",
            "icon": "btn_cross.png",
        },
        {
            "content": "Remind Later",
            "arguments": f"timetracker://action?name=snooze_gap&gap_id={gap_id}",
            "icon": "btn_clock.png",
        },
    ]

    now_local = datetime.now()
    toast_time_str = now_local.strftime("%I:%M %p").lstrip("0")

    # 1. Post native Windows Toast
    send_windows_toast(
        title=title,
        message=body,
        timestamp_str=toast_time_str,
        launch_url=f"timetracker://navigate?action=add_activity&gap_id={gap_id}",
        actions=recovery_actions,
        scenario="reminder",
        db_path=db_path,
    )

    # 2. Persist in Notification Center
    notif = create_notification(
        db,
        notif_type="recovery",
        title=title,
        body=body,
        details=details,
    )

    return {
        "gap_id": gap_id,
        "gap_start": gap_start_iso,
        "gap_end": gap_end_iso,
        "duration_seconds": gap_secs,
        "duration_minutes": gap_minutes,
        "notification": notif,
    }


def get_pending_recovery_gap(db: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """
    Return the most recent pending recovery gap for user action.
    Expires outdated gaps, gaps superseded by subsequent tracking,
    or overnight gaps when suppression is active.
    """
    row = db.execute(
        """
        SELECT * FROM recovery_gaps
        WHERE status = 'pending'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        return None

    gap = dict(row)
    gap_id = gap["id"]
    settings = get_settings_from_db(db)

    # If recovery is disabled, don't return
    if not settings.get("missed_recovery_enabled", True) or not settings.get("notifications_enabled", True):
        return None

    # Check current time against quiet hours
    now_dt = now_utc()
    try:
        now_local = now_dt.astimezone()
    except Exception:
        now_local = now_dt

    if settings.get("quiet_hours_enabled", False):
        qh_start = settings.get("quiet_hours_start", "22:00")
        qh_end = settings.get("quiet_hours_end", "07:00")
        if is_in_time_window(now_local.time(), qh_start, qh_end):
            return None

    # Check overnight suppression on current time
    overnight_enabled = settings.get("overnight_suppression_enabled", True)
    sleep_start = settings.get("overnight_sleep_start", "23:00")
    sleep_end = settings.get("overnight_sleep_end", "07:00")
    if overnight_enabled and is_in_time_window(now_local.time(), sleep_start, sleep_end):
        return None

    # Check waking duration of the gap
    gap_start_dt = parse_db_datetime(gap.get("gap_start"))
    gap_end_dt = parse_db_datetime(gap.get("gap_end"))
    if gap_start_dt and gap_end_dt and overnight_enabled:
        threshold_mins = settings.get("missed_recovery_threshold_minutes", 30)
        waking_mins = calculate_waking_gap_minutes(gap_start_dt, gap_end_dt, sleep_start, sleep_end)
        if waking_mins < threshold_mins:
            # Auto-expire normal sleep gap
            db.execute("UPDATE recovery_gaps SET status = 'skipped', reviewed_at = ? WHERE id = ?", (now_iso(), gap_id))
            db.commit()
            return None

    # Check if subsequent tracking has occurred well after gap_end
    latest_obs = db.execute(
        "SELECT MAX(datetime(COALESCE(end_time, start_time))) as max_ts FROM observations"
    ).fetchone()
    if latest_obs and latest_obs["max_ts"]:
        latest_dt = parse_db_datetime(latest_obs["max_ts"])
        if latest_dt and gap_end_dt and (latest_dt - gap_end_dt).total_seconds() > 3600:
            db.execute("UPDATE recovery_gaps SET status = 'skipped', reviewed_at = ? WHERE id = ?", (now_iso(), gap_id))
            db.commit()
            return None

    return gap


def resolve_recovery_gap(
    db: sqlite3.Connection,
    gap_id: int,
    action: str = "skip",
) -> bool:
    """Resolve a recovery gap with 'skip' or 'snooze'."""
    status = "skipped" if action == "skip" else "snoozed"
    ts = now_iso()
    cursor = db.execute(
        "UPDATE recovery_gaps SET status = ?, reviewed_at = ? WHERE id = ?",
        (status, ts, gap_id),
    )
    # Also mark related recovery notifications as read
    try:
        db.execute(
            """
            UPDATE notifications
            SET unread = 0
            WHERE type = 'recovery' AND details LIKE ?
            """,
            (f'%"gap_id": {gap_id}%',),
        )
    except Exception:
        pass

    db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Manual Activity Entry for Missing Interval
# ---------------------------------------------------------------------------

def record_manual_activity(
    db: sqlite3.Connection,
    task_name: str,
    start_time: str,
    end_time: str,
    category_id: Optional[int] = None,
    notes: Optional[str] = None,
    recovery_gap_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Record a manual activity entry for a missed interval.
    Validates timestamps, prevents double counting, never fabricates executable names,
    and never overwrites raw tracking observations.
    """
    clean_task = (task_name or "").strip()
    if not clean_task:
        raise ValueError("Task name cannot be empty.")

    try:
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)
    except Exception as e:
        raise ValueError(f"Invalid timestamp format: {e}")

    if end_dt <= start_dt:
        raise ValueError("End time must be after start time.")

    duration_secs = (end_dt - start_dt).total_seconds()
    if duration_secs <= 0 or duration_secs > 86400:
        raise ValueError(f"Invalid duration ({duration_secs:.0f}s). Must be between 1s and 24h.")

    title = clean_task
    if notes and notes.strip():
        title = f"{clean_task} — {notes.strip()}"

    # Insert into observations cleanly: kind='active', app='Manual Entry'
    cursor = db.execute(
        """
        INSERT INTO observations (kind, app, title, task, start_time, end_time, duration_seconds)
        VALUES ('active', 'Manual Entry', ?, ?, ?, ?, ?)
        """,
        (
            title,
            clean_task,
            start_dt.isoformat(),
            end_dt.isoformat(),
            duration_secs,
        ),
    )
    obs_id = cursor.lastrowid

    # Record in tasks table
    try:
        db.execute("INSERT OR IGNORE INTO tasks (name) VALUES (?)", (clean_task,))
    except Exception:
        pass

    # Record category override
    if category_id is not None:
        ts = now_iso()
        session_key = f"Manual Entry_{obs_id}"
        try:
            db.execute(
                """
                INSERT INTO session_categories (session_key, category_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET category_id = excluded.category_id, updated_at = excluded.updated_at
                """,
                (session_key, category_id, ts),
            )
        except Exception:
            pass

    # Resolve recovery gap if linked
    if recovery_gap_id:
        resolve_recovery_gap(db, recovery_gap_id, action="resolved_added")

    db.commit()

    return {
        "observation_id": obs_id,
        "task_name": clean_task,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "duration_seconds": duration_secs,
        "category_id": category_id,
        "app": "Manual Entry",
        "title": title,
    }
