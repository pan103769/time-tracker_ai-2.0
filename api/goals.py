"""
api/goals.py — Goals evaluation and Time-Block analysis engine.

Manages configurable productivity goals (including inversion targets)
and compares planned time blocks against actual tracked activity.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from activity_report import format_duration
from api.categories import match_category
from api.migrations import now_iso


def get_goals(db: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Return all configured goals."""
    rows = db.execute(
        """
        SELECT g.id, g.title, g.metric, g.category_id, g.target_seconds,
               g.is_inversion, g.period, g.is_active, g.created_at,
               c.name as category_name, c.color as category_color
        FROM goals g
        LEFT JOIN categories c ON g.category_id = c.id
        ORDER BY g.id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def create_goal(
    db: sqlite3.Connection,
    title: str,
    metric: str,
    target_seconds: int,
    is_inversion: bool = False,
    category_id: Optional[int] = None,
    period: str = "daily",
) -> Dict[str, Any]:
    """Create a new goal."""
    ts = now_iso()
    cursor = db.execute(
        """
        INSERT INTO goals (title, metric, category_id, target_seconds, is_inversion, period, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (title.strip(), metric.strip(), category_id, target_seconds, 1 if is_inversion else 0, period, ts),
    )
    db.commit()
    row = db.execute(
        """
        SELECT g.*, c.name as category_name, c.color as category_color
        FROM goals g
        LEFT JOIN categories c ON g.category_id = c.id
        WHERE g.id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def update_goal(
    db: sqlite3.Connection,
    goal_id: int,
    title: str,
    target_seconds: int,
    is_inversion: bool = False,
    is_active: bool = True,
) -> Optional[Dict[str, Any]]:
    """Update goal settings."""
    db.execute(
        """
        UPDATE goals
        SET title = ?, target_seconds = ?, is_inversion = ?, is_active = ?
        WHERE id = ?
        """,
        (title.strip(), target_seconds, 1 if is_inversion else 0, 1 if is_active else 0, goal_id),
    )
    db.commit()
    row = db.execute(
        """
        SELECT g.*, c.name as category_name, c.color as category_color
        FROM goals g
        LEFT JOIN categories c ON g.category_id = c.id
        WHERE g.id = ?
        """,
        (goal_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_goal(db: sqlite3.Connection, goal_id: int) -> bool:
    """Delete a goal."""
    cursor = db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    db.commit()
    return cursor.rowcount > 0


def evaluate_goals(
    db: sqlite3.Connection,
    date_str: str,
    sessions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Calculate progress for all active goals on a given date.
    Correctly handles standard targets and inversion goals (e.g. max distraction).
    """
    active_goals = [g for g in get_goals(db) if g["is_active"]]

    # Precalculate metric totals from sessions
    # Productive work strictly includes "focus" and "work" categories, excluding distractions and personal
    total_tracked_seconds = sum(s["duration_seconds"] for s in sessions if s.get("kind") != "idle")
    productive_work_seconds = sum(
        s["duration_seconds"]
        for s in sessions
        if s.get("kind") != "idle" and (
            s.get("category_type") in ("focus", "work") or
            (s.get("category") or {}).get("type") in ("focus", "work")
        )
    )
    total_focus_seconds = sum(
        s["duration_seconds"]
        for s in sessions
        if s.get("kind") != "idle" and (s.get("category_type") == "focus" or (s.get("category") or {}).get("type") == "focus")
    )
    total_distraction_seconds = sum(
        s["duration_seconds"]
        for s in sessions
        if s.get("kind") != "idle" and (s.get("category_type") == "distraction" or (s.get("category") or {}).get("type") == "distraction")
    )

    category_seconds_map: Dict[int, float] = {}
    for s in sessions:
        if s.get("kind") == "idle":
            continue
        cid = s.get("category_id") or ((s.get("category") or {}).get("id"))
        if cid:
            category_seconds_map[cid] = category_seconds_map.get(cid, 0.0) + s["duration_seconds"]

    results = []
    for g in active_goals:
        metric = g["metric"]
        target = g["target_seconds"]
        is_inv = bool(g["is_inversion"])

        if metric == "work_time":
            actual = productive_work_seconds
        elif metric == "focus_time":
            actual = total_focus_seconds
        elif metric == "distraction_time":
            actual = total_distraction_seconds
        elif metric == "tracked_time":
            actual = total_tracked_seconds
        elif metric == "category_time" and g.get("category_id"):
            actual = category_seconds_map.get(g["category_id"], 0.0)
        else:
            actual = productive_work_seconds

        pct = round((actual / target * 100), 1) if target > 0 else 0.0

        if is_inv:
            # Inversion goal: target is maximum allowed.
            # Achieved if actual <= target.
            is_achieved = actual <= target
            remaining = max(0.0, target - actual)
            status_text = f"{format_duration(remaining)} remaining under limit" if is_achieved else f"{format_duration(actual - target)} over limit"
        else:
            # Standard goal: target is minimum desired.
            is_achieved = actual >= target
            remaining = max(0.0, target - actual)
            status_text = "Target reached!" if is_achieved else f"{format_duration(remaining)} to target"

        results.append({
            "id": g["id"],
            "title": g["title"],
            "metric": metric,
            "target_seconds": target,
            "target_label": format_duration(target),
            "actual_seconds": round(actual, 1),
            "actual_label": format_duration(actual),
            "is_inversion": is_inv,
            "progress_pct": min(pct, 100.0) if not is_inv else pct,
            "is_achieved": is_achieved,
            "status_text": status_text,
            "category_name": g.get("category_name"),
            "category_color": g.get("category_color"),
        })

    return results


# ---------------------------------------------------------------------------
# Time Blocks CRUD and Analysis
# ---------------------------------------------------------------------------


def _normalize_time_str(val: str) -> str:
    """Normalize time string or timestamp into standard HH:MM."""
    if not val:
        return "00:00"
    v = str(val).strip()
    if "T" in v:
        v = v.split("T")[-1]
    if " " in v:
        v = v.split(" ")[-1]
    parts = v.split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            return f"{h:02d}:{m:02d}"
        except ValueError:
            pass
    return v[:5]


def _format_time_range(st_str: str, et_str: str) -> str:
    """Format HH:MM range into user-friendly localized string e.g. '9:30 – 11:00 AM'."""
    try:
        sh, sm = [int(p) for p in _normalize_time_str(st_str).split(":")[:2]]
        eh, em = [int(p) for p in _normalize_time_str(et_str).split(":")[:2]]
        t_start = time(sh, sm)
        t_end = time(eh, em)

        # 12-hour format with AM/PM
        s_fmt = t_start.strftime("%I:%M %p").lstrip("0")
        e_fmt = t_end.strftime("%I:%M %p").lstrip("0")
        return f"{s_fmt} - {e_fmt}"
    except Exception:
        return f"{st_str} - {et_str}"


def get_time_blocks(db: sqlite3.Connection, date_str: str) -> List[Dict[str, Any]]:
    """Return all planned time blocks for a given date sorted chronologically."""
    rows = db.execute(
        """
        SELECT b.id, b.date, b.start_time, b.end_time, b.title, b.category_id, b.created_at,
               c.name as category_name, c.color as category_color, c.type as category_type
        FROM time_blocks b
        LEFT JOIN categories c ON b.category_id = c.id
        WHERE b.date = ?
        ORDER BY b.start_time ASC, b.id ASC
        """,
        (date_str,),
    ).fetchall()
    blocks = []
    for r in rows:
        b = dict(r)
        b["start_time"] = _normalize_time_str(b["start_time"])
        b["end_time"] = _normalize_time_str(b["end_time"])
        b["display_time_label"] = _format_time_range(b["start_time"], b["end_time"])
        blocks.append(b)
    return blocks


def create_time_block(
    db: sqlite3.Connection,
    block_date: str,
    start_time: str,
    end_time: str,
    title: str,
    category_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a new time block schedule commitment with normalized HH:MM times."""
    clean_st = _normalize_time_str(start_time)
    clean_et = _normalize_time_str(end_time)
    ts = now_iso()
    cursor = db.execute(
        """
        INSERT INTO time_blocks (date, start_time, end_time, title, category_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (block_date, clean_st, clean_et, title.strip(), category_id, ts),
    )
    db.commit()

    row = db.execute(
        """
        SELECT b.*, c.name as category_name, c.color as category_color, c.type as category_type
        FROM time_blocks b
        LEFT JOIN categories c ON b.category_id = c.id
        WHERE b.id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    res = dict(row)
    res["start_time"] = clean_st
    res["end_time"] = clean_et
    res["display_time_label"] = _format_time_range(clean_st, clean_et)
    return res


def update_time_block(
    db: sqlite3.Connection,
    block_id: int,
    block_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    title: Optional[str] = None,
    category_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Update an existing time block (reschedule or edit title/category)."""
    existing = db.execute("SELECT * FROM time_blocks WHERE id = ?", (block_id,)).fetchone()
    if not existing:
        return None

    ex_dict = dict(existing)
    new_date = block_date or ex_dict["date"]
    new_start = _normalize_time_str(start_time) if start_time else ex_dict["start_time"]
    new_end = _normalize_time_str(end_time) if end_time else ex_dict["end_time"]
    new_title = title.strip() if title is not None else ex_dict["title"]
    new_cat = category_id if category_id is not None else ex_dict.get("category_id")

    db.execute(
        """
        UPDATE time_blocks
        SET date = ?, start_time = ?, end_time = ?, title = ?, category_id = ?
        WHERE id = ?
        """,
        (new_date, new_start, new_end, new_title, new_cat, block_id),
    )
    db.commit()

    row = db.execute(
        """
        SELECT b.*, c.name as category_name, c.color as category_color, c.type as category_type
        FROM time_blocks b
        LEFT JOIN categories c ON b.category_id = c.id
        WHERE b.id = ?
        """,
        (block_id,),
    ).fetchone()
    if not row:
        return None
    res = dict(row)
    res["start_time"] = _normalize_time_str(res["start_time"])
    res["end_time"] = _normalize_time_str(res["end_time"])
    res["display_time_label"] = _format_time_range(res["start_time"], res["end_time"])
    return res


def duplicate_time_block(
    db: sqlite3.Connection,
    block_id: int,
    target_date: Optional[str] = None,
    time_offset_minutes: int = 0,
) -> Optional[Dict[str, Any]]:
    """Intentionally duplicate a time block commitment."""
    existing = db.execute("SELECT * FROM time_blocks WHERE id = ?", (block_id,)).fetchone()
    if not existing:
        return None
    b = dict(existing)
    d = target_date or b["date"]
    st = _normalize_time_str(b["start_time"])
    et = _normalize_time_str(b["end_time"])

    if time_offset_minutes != 0:
        try:
            sh, sm = [int(p) for p in st.split(":")]
            eh, em = [int(p) for p in et.split(":")]
            tot_s = (sh * 60 + sm + time_offset_minutes) % 1440
            tot_e = (eh * 60 + em + time_offset_minutes) % 1440
            st = f"{tot_s // 60:02d}:{tot_s % 60:02d}"
            et = f"{tot_e // 60:02d}:{tot_e % 60:02d}"
        except Exception:
            pass

    return create_time_block(db, d, st, et, b["title"], b.get("category_id"))


def check_time_block_overlaps(
    db: sqlite3.Connection,
    block_date: str,
    start_time: str,
    end_time: str,
    exclude_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Check if a proposed time block overlaps any existing blocks on that date."""
    blocks = get_time_blocks(db, block_date)
    st_norm = _normalize_time_str(start_time)
    et_norm = _normalize_time_str(end_time)

    overlaps = []
    for b in blocks:
        if exclude_id and b["id"] == exclude_id:
            continue
        b_st = _normalize_time_str(b["start_time"])
        b_et = _normalize_time_str(b["end_time"])

        # Check interval overlap: max(start1, start2) < min(end1, end2)
        if max(st_norm, b_st) < min(et_norm, b_et):
            overlaps.append(b)
    return overlaps


def delete_time_block(db: sqlite3.Connection, block_id: int) -> bool:
    """Delete a time block."""
    cursor = db.execute("DELETE FROM time_blocks WHERE id = ?", (block_id,))
    db.commit()
    return cursor.rowcount > 0


def analyze_time_blocks(
    db: sqlite3.Connection,
    date_str: str,
    sessions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compare planned schedule blocks against actual tracked activity.
    Identifies in-progress, upcoming, completed, partial, or missed blocks.
    Never double-counts time.
    """
    blocks = get_time_blocks(db, date_str)
    if not blocks:
        return []

    analysis = []

    # Determine timezone from sessions if available (defaults to local timezone)
    sample_tz = datetime.now().astimezone().tzinfo
    for s in sessions:
        try:
            st = s.get("start")
            if st:
                s_dt = datetime.fromisoformat(st)
                if s_dt.tzinfo:
                    sample_tz = s_dt.tzinfo
                    break
        except Exception:
            pass

    now_local = datetime.now().astimezone(sample_tz)
    today_str = now_local.strftime("%Y-%m-%d")

    # Check active focus task and settings
    current_focus_block_id = None
    try:
        r_bid = db.execute("SELECT value FROM app_settings WHERE key = 'current_focus_block_id'").fetchone()
        if r_bid and r_bid[0]:
            current_focus_block_id = int(r_bid[0])
    except Exception:
        pass

    for b in blocks:
        st_norm = _normalize_time_str(b["start_time"])
        et_norm = _normalize_time_str(b["end_time"])

        try:
            d_parts = [int(p) for p in b["date"].split("-")[:3]]
            sh, sm = [int(p) for p in st_norm.split(":")[:2]]
            eh, em = [int(p) for p in et_norm.split(":")[:2]]
            b_start_dt = datetime(d_parts[0], d_parts[1], d_parts[2], sh, sm, 0, tzinfo=sample_tz)
            b_end_dt = datetime(d_parts[0], d_parts[1], d_parts[2], eh, em, 0, tzinfo=sample_tz)
            if b_end_dt <= b_start_dt:
                b_end_dt += timedelta(days=1)
        except Exception:
            continue

        planned_duration = max(60.0, (b_end_dt - b_start_dt).total_seconds())

        matching_seconds = 0.0
        distraction_seconds = 0.0
        other_work_seconds = 0.0
        idle_seconds = 0.0
        interruptions = 0
        observed_apps = set()

        for s in sessions:
            try:
                s_start = datetime.fromisoformat(s["start"]).astimezone(sample_tz)
                s_end = datetime.fromisoformat(s["end"]).astimezone(sample_tz)
            except Exception:
                continue

            # Calculate overlap interval [overlap_start, overlap_end]
            overlap_start = max(b_start_dt, s_start)
            overlap_end = min(b_end_dt, s_end)
            overlap_secs = max(0.0, (overlap_end - overlap_start).total_seconds())

            if overlap_secs <= 0:
                continue

            kind = s.get("kind", "active")
            cat_id = s.get("category_id") or (s.get("category", {}).get("id"))
            cat_type = s.get("category_type") or (s.get("category", {}).get("type"))

            if kind == "idle":
                idle_seconds += overlap_secs
            else:
                observed_apps.add(s.get("app", "App"))
                # Check if session matches block criteria
                is_match = False
                if b.get("category_id") and cat_id == b["category_id"]:
                    is_match = True
                elif not b.get("category_id") and cat_type == "focus":
                    is_match = True
                elif b.get("title") and s.get("task") and b["title"].lower() in s["task"].lower():
                    is_match = True

                if is_match:
                    matching_seconds += overlap_secs
                elif cat_type == "distraction":
                    distraction_seconds += overlap_secs
                    interruptions += 1
                else:
                    other_work_seconds += overlap_secs

        match_pct = round((matching_seconds / planned_duration * 100), 1)

        # Dynamic Status Determination
        is_current = (b["date"] == today_str and b_start_dt <= now_local <= b_end_dt)
        is_active_focus = (current_focus_block_id == b["id"])

        if b["date"] == today_str:
            if is_current:
                status = "In Progress"
            elif now_local < b_start_dt:
                status = "Upcoming"
            else:
                # Past block
                if match_pct >= 70.0:
                    status = "Completed"
                elif match_pct >= 30.0:
                    status = "Partial"
                else:
                    status = "Missed"
        elif b["date"] > today_str:
            status = "Upcoming"
        else:
            # Historical date
            if match_pct >= 70.0:
                status = "Completed"
            elif match_pct >= 30.0:
                status = "Partial"
            else:
                status = "Missed"

        analysis.append({
            "block_id": b["id"],
            "title": b["title"],
            "date": b["date"],
            "start_time": st_norm,
            "end_time": et_norm,
            "display_time_label": _format_time_range(st_norm, et_norm),
            "planned_duration_seconds": planned_duration,
            "planned_label": format_duration(planned_duration),
            "matching_seconds": round(matching_seconds, 1),
            "matching_label": format_duration(matching_seconds),
            "distraction_seconds": round(distraction_seconds, 1),
            "distraction_label": format_duration(distraction_seconds),
            "idle_seconds": round(idle_seconds, 1),
            "match_pct": min(match_pct, 100.0),
            "status": status,
            "is_current": is_current,
            "is_active_focus": is_active_focus,
            "interruptions": interruptions,
            "category_name": b.get("category_name"),
            "category_color": b.get("category_color"),
            "category_type": b.get("category_type"),
            "observed_apps": list(observed_apps)[:5],
        })

    return analysis


def calculate_time_blocks_daily_summary(
    db: sqlite3.Connection,
    date_str: str,
    sessions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Computes four consistent, non-contradictory metrics for scheduled time blocks:
    1. Planned Time — Total non-overlapping scheduled duration for the day.
    2. Focus Time in Blocks — Actual qualifying matching focus/work duration inside scheduled windows.
    3. Plan Adherence — (Focus Time in Blocks / Planned Time) * 100%, strictly clamped to 100%.
    4. Distraction Time in Blocks — Time spent on distractions during scheduled blocks.
    """
    analysis = analyze_time_blocks(db, date_str, sessions)
    blocks = get_time_blocks(db, date_str)

    if not blocks:
        return {
            "date": date_str,
            "total_blocks": 0,
            "planned_seconds": 0.0,
            "planned_label": "0m",
            "focus_seconds": 0.0,
            "focus_label": "0m",
            "adherence_pct": 0.0,
            "distraction_seconds": 0.0,
            "distraction_label": "0m",
            "idle_seconds": 0.0,
            "idle_label": "0m",
            "in_progress_count": 0,
            "upcoming_count": 0,
            "completed_count": 0,
            "missed_count": 0,
            "skipped_count": 0,
        }

    sample_tz = datetime.now().astimezone().tzinfo
    for s in sessions:
        try:
            st = s.get("start")
            if st:
                s_dt = datetime.fromisoformat(st)
                if s_dt.tzinfo:
                    sample_tz = s_dt.tzinfo
                    break
        except Exception:
            pass

    # 1. Canonical Planned Time: Merge overlapping block intervals to prevent double-counting
    parsed_intervals: List[Tuple[datetime, datetime]] = []
    for b in blocks:
        try:
            st_clean = _normalize_time_str(b["start_time"])
            et_clean = _normalize_time_str(b["end_time"])
            d_parts = [int(p) for p in b["date"].split("-")[:3]]
            sh, sm = [int(p) for p in st_clean.split(":")[:2]]
            eh, em = [int(p) for p in et_clean.split(":")[:2]]
            b_s = datetime(d_parts[0], d_parts[1], d_parts[2], sh, sm, 0, tzinfo=sample_tz)
            b_e = datetime(d_parts[0], d_parts[1], d_parts[2], eh, em, 0, tzinfo=sample_tz)
            if b_e <= b_s:
                b_e += timedelta(days=1)
            parsed_intervals.append((b_s, b_e))
        except Exception:
            continue

    # Merge overlapping block intervals
    merged_intervals: List[Tuple[datetime, datetime]] = []
    for interval in sorted(parsed_intervals, key=lambda x: x[0]):
        if not merged_intervals:
            merged_intervals.append(interval)
        else:
            prev_s, prev_e = merged_intervals[-1]
            if interval[0] <= prev_e:
                merged_intervals[-1] = (prev_s, max(prev_e, interval[1]))
            else:
                merged_intervals.append(interval)

    planned_seconds = sum((end - start).total_seconds() for start, end in merged_intervals)

    # 2. Focus Time in Blocks: Sum of qualifying matching seconds across blocks
    focus_seconds = sum(item["matching_seconds"] for item in analysis)
    focus_seconds_for_adherence = min(planned_seconds, focus_seconds)

    # 3. Plan Adherence: Clearly defined formula
    if planned_seconds > 0:
        adherence_pct = round((focus_seconds_for_adherence / planned_seconds) * 100.0, 1)
    else:
        adherence_pct = 0.0

    # 4. Distraction Time in Blocks
    distraction_seconds = sum(item["distraction_seconds"] for item in analysis)
    idle_seconds = sum(item.get("idle_seconds", 0.0) for item in analysis)

    # Counts
    in_progress_count = sum(1 for item in analysis if item["status"] == "In Progress")
    upcoming_count = sum(1 for item in analysis if item["status"] == "Upcoming")
    completed_count = sum(1 for item in analysis if item["status"] == "Completed")
    missed_count = sum(1 for item in analysis if item["status"] == "Missed")
    skipped_count = sum(1 for item in analysis if item.get("status") == "Skipped")

    return {
        "date": date_str,
        "total_blocks": len(blocks),
        "planned_seconds": round(planned_seconds, 1),
        "planned_label": format_duration(planned_seconds),
        "focus_seconds": round(focus_seconds, 1),
        "focus_label": format_duration(focus_seconds),
        "adherence_pct": min(100.0, adherence_pct),
        "distraction_seconds": round(distraction_seconds, 1),
        "distraction_label": format_duration(distraction_seconds),
        "idle_seconds": round(idle_seconds, 1),
        "idle_label": format_duration(idle_seconds),
        "in_progress_count": in_progress_count,
        "upcoming_count": upcoming_count,
        "completed_count": completed_count,
        "missed_count": missed_count,
        "skipped_count": skipped_count,
    }
