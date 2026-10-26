"""
api/ai_coach_engine.py
----------------------
Grounded AI Coach Chat Engine for Time Tracker AI 2.

Features:
1. Answers grounded 100% in actual SQLite observations, Time Blocks, and Goals.
2. 5 Prominent Quick-Question button handlers:
   - Study & Focus Time (separates study from coding and general work)
   - Distraction Analysis (exact distraction time, sources, comparisons, tips)
   - Where Did My Time Go (ranked breakdown with specific activities)
   - Performance Comparison (today vs yesterday, equivalent metrics)
   - What Should I Do Next (schedule, active focus, goals, next task)
3. Natural Language Query Parser (YouTube time, interruptions, goals, timeline)
4. Contextual memory across follow-ups in the active conversation
5. Interactive quick actions for timeline navigation and inspection
6. Ollama LLM integration when available, with deterministic fallback when offline
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import ai_timeline as tl
from activity_report import DB_PATH, format_duration
import api.activity_intelligence as activity_intel
import api.categories as categories_engine
import api.goals as goals_engine
import api.insights as insights_engine
import api.tracker_manager as tracker_manager

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
AI_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


def _is_ollama_available(timeout: float = 0.6) -> bool:
    """Check if local Ollama daemon is reachable."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _load_day_data(db: sqlite3.Connection, date_str: str) -> Dict[str, Any]:
    """
    Load canonical sessions, categories, goals, and blocks for a single day.
    Guarantees zero double-counting.
    """
    try:
        selected = date.fromisoformat(date_str)
    except ValueError:
        selected = date.today()

    day_start = datetime.combine(selected, datetime.min.time()).astimezone()
    day_end = day_start + timedelta(days=1)

    obs = tl.load_observations(db, day_start, day_end)
    visits = tl.load_browser_visits(db, day_start, day_end, datetime.now().astimezone())
    sessions = tl.group_into_sessions(obs, visits)

    # Preload categories & rules
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
        s["context_label"] = act["context_label"]
        s["is_browser"] = act["is_browser"]
        s["is_uncertain"] = act["is_uncertain"]

    # Canonical Metrics
    total_active_seconds = sum(s.get("duration_seconds", 0.0) for s in sessions if s.get("kind") != "idle")
    total_idle_seconds = sum(s.get("duration_seconds", 0.0) for s in sessions if s.get("kind") == "idle")

    type_totals = {"focus": 0.0, "work": 0.0, "personal": 0.0, "distraction": 0.0, "uncategorized": 0.0}
    category_totals: Dict[str, Dict[str, Any]] = {}

    study_sessions = []
    coding_sessions = []
    distraction_sessions = []

    for s in sessions:
        if s.get("kind") == "idle":
            continue
        c_name = s.get("category_name") or "Uncategorized"
        c_type = s.get("category_type") or "uncategorized"
        c_color = s.get("category_color") or "#8065FF"
        dur = s.get("duration_seconds", 0.0)

        if c_type in type_totals:
            type_totals[c_type] += dur
        else:
            type_totals["uncategorized"] += dur

        if c_name not in category_totals:
            category_totals[c_name] = {"name": c_name, "type": c_type, "color": c_color, "seconds": 0.0}
        category_totals[c_name]["seconds"] += dur

        # Specific task classification
        c_name_lower = c_name.lower()
        title_lower = (s.get("title") or "").lower()
        act_lower = (s.get("activity_name") or "").lower()
        app_lower = (s.get("app") or "").lower()

        is_study = (
            "research" in c_name_lower
            or "learn" in c_name_lower
            or "study" in c_name_lower
            or "moodle" in title_lower
            or "reading" in act_lower
            or any(w in title_lower for w in ("lecture", "tutorial", "course", "documentation", "wikipedia", "textbook"))
        )
        if is_study:
            study_sessions.append(s)

        is_coding = (
            "coding" in c_name_lower
            or "development" in c_name_lower
            or app_lower in ("code.exe", "devenv.exe", "pycharm64.exe")
            or "github" in title_lower
            or ("chatgpt" in act_lower and any(w in title_lower for w in ("project", "code", "debug", "api", "endpoint", "tracker")))
        )
        if is_coding:
            coding_sessions.append(s)

        if c_type == "distraction" or "entertainment" in c_name_lower or "social" in c_name_lower:
            distraction_sessions.append(s)

    study_seconds = sum(s.get("duration_seconds", 0.0) for s in study_sessions)
    coding_seconds = sum(s.get("duration_seconds", 0.0) for s in coding_sessions)
    productive_work_seconds = type_totals["focus"] + type_totals["work"]
    deep_focus_seconds = type_totals["focus"]
    distraction_seconds = type_totals["distraction"]

    # Interruption & streak detection
    interruptions, top_interruptors, longest_streak = insights_engine.detect_interruptions_and_streaks(sessions)

    # Hierarchical app breakdown
    app_breakdown = activity_intel.aggregate_hierarchical_usage(sessions, total_active_seconds)

    # Goals and Time Blocks
    goal_results = goals_engine.evaluate_goals(db, date_str, sessions)
    block_results = goals_engine.analyze_time_blocks(db, date_str, sessions)
    scheduled_blocks = goals_engine.get_time_blocks(db, date_str)

    return {
        "date_str": date_str,
        "sessions": sessions,
        "total_active_seconds": total_active_seconds,
        "total_active_label": format_duration(total_active_seconds),
        "total_idle_seconds": total_idle_seconds,
        "total_idle_label": format_duration(total_idle_seconds),
        "productive_work_seconds": productive_work_seconds,
        "productive_work_label": format_duration(productive_work_seconds),
        "deep_focus_seconds": deep_focus_seconds,
        "deep_focus_label": format_duration(deep_focus_seconds),
        "study_seconds": study_seconds,
        "study_label": format_duration(study_seconds),
        "coding_seconds": coding_seconds,
        "coding_label": format_duration(coding_seconds),
        "distraction_seconds": distraction_seconds,
        "distraction_label": format_duration(distraction_seconds),
        "unclassified_seconds": type_totals.get("uncategorized", 0.0),
        "unclassified_label": format_duration(type_totals.get("uncategorized", 0.0)),
        "type_totals": type_totals,
        "category_totals": category_totals,
        "interruptions": interruptions,
        "top_interruptors": top_interruptors,
        "longest_streak": longest_streak,
        "app_breakdown": app_breakdown,
        "study_sessions": study_sessions,
        "coding_sessions": coding_sessions,
        "distraction_sessions": distraction_sessions,
        "goals": goal_results,
        "time_blocks": block_results,
        "scheduled_blocks": scheduled_blocks,
    }


# ---------------------------------------------------------------------------
# Specialized Handlers for the 5 Suggested Questions
# ---------------------------------------------------------------------------

def answer_study_and_focus(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Button 1: How much did I study and focus today?"""
    date_str = data["date_str"]
    total_tracked = data["total_active_label"]
    study_time = data["study_label"]
    study_secs = data["study_seconds"]
    coding_time = data["coding_label"]
    coding_secs = data["coding_seconds"]
    deep_focus = data["deep_focus_label"]
    productive_work = data["productive_work_label"]
    longest = data["longest_streak"]

    focus_pct = round((data["deep_focus_seconds"] / max(1.0, data["total_active_seconds"])) * 100, 1)

    # Top specific study / academic items
    study_items = []
    seen = set()
    for s in data["study_sessions"]:
        name = s.get("activity_name") or s.get("title")
        if name and name not in seen:
            seen.add(name)
            study_items.append((name, s.get("duration_label", "0s")))

    lines = [
        f"### 📚 Study & Focus Summary for {date_str}",
        "",
        f"Out of **{total_tracked}** total tracked screen time today, here is the breakdown of your focused and learning activities:",
        "",
        f"- **Dedicated Study & Research:** `{study_time}`",
        f"- **Coding & Project Work:** `{coding_time}`",
        f"- **Deep Focus Time:** `{deep_focus}` ({focus_pct}% focus ratio)",
        f"- **Total Productive Work:** `{productive_work}`",
        "",
        "#### Understanding Your Time Breakdown",
        (
            f"You logged **{study_time}** in active study, tutorials, and research material. "
            f"Your remaining productive time (**{coding_time}**) was devoted to hands-on programming and system implementation."
            if study_secs > 0 else
            "No dedicated academic or research sessions were recorded today. Your productive hours were focused entirely on **hands-on coding and software development**."
        ),
    ]

    if longest:
        lines.append(f"- Longest uninterrupted focus streak: **{longest['duration_label']}** on `{longest['app']}`.")

    if study_items:
        lines.append("")
        lines.append("#### Observed Learning & Research Activities:")
        for name, dur in study_items[:4]:
            lines.append(f"- **{name}** (`{dur}`)")

    quick_actions = [
        {"label": "View Timeline", "action": "navigate_timeline", "param": date_str},
        {"label": "Explore Analytics", "action": "navigate_tab", "param": "insights"},
    ]

    evidence = {
        "study_seconds": study_secs,
        "coding_seconds": coding_secs,
        "deep_focus_seconds": data["deep_focus_seconds"],
        "productive_work_seconds": data["productive_work_seconds"],
        "total_active_seconds": data["total_active_seconds"],
    }

    return "\n".join(lines), quick_actions, evidence


def answer_distractions(data: Dict[str, Any], prev_data: Optional[Dict[str, Any]] = None) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Button 2: How much time did I waste on distractions?"""
    date_str = data["date_str"]
    dist_secs = data["distraction_seconds"]
    dist_label = data["distraction_label"]
    total_active = data["total_active_seconds"]
    total_tracked = data["total_active_label"]
    interruptions = data["interruptions"]
    top_interruptors = data["top_interruptors"]

    dist_pct = round((dist_secs / max(1.0, total_active)) * 100, 1)

    # Aggregate distraction apps and websites
    dist_by_name: Dict[str, float] = {}
    for s in data["distraction_sessions"]:
        name = s.get("activity_name") or s.get("title") or s.get("app")
        dist_by_name[name] = dist_by_name.get(name, 0.0) + s.get("duration_seconds", 0.0)

    top_dist = sorted(dist_by_name.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = [
        f"### 🎯 Distraction Analysis for {date_str}",
        "",
        f"You logged **{dist_label}** on non-work and entertainment activities today (**{dist_pct}%** of your {total_tracked} tracked screen time).",
        "",
    ]

    if dist_secs > 0:
        lines.append("#### Primary Distraction Sources:")
        for name, sec in top_dist:
            share = round((sec / dist_secs) * 100, 1)
            lines.append(f"- **{name}**: `{format_duration(sec)}` ({share}% of distractions)")
        lines.append("")
    else:
        lines.append("🎉 **Zero distracting websites or entertainment sessions recorded today.** Outstanding discipline!")
        lines.append("")

    if prev_data:
        prev_dist = prev_data["distraction_seconds"]
        diff = dist_secs - prev_dist
        if prev_dist > 0:
            pct_change = round((abs(diff) / prev_dist) * 100, 1)
            if diff < 0:
                lines.append(f"📈 **Improvement:** Distractions decreased by **{format_duration(abs(diff))}** ({pct_change}%) compared to yesterday ({prev_data['distraction_label']}).")
            elif diff > 0:
                lines.append(f"⚠️ Distractions increased by **{format_duration(diff)}** (+{pct_change}%) compared to yesterday ({prev_data['distraction_label']}).")
            else:
                lines.append(f"Distraction time was identical to yesterday ({prev_data['distraction_label']}).")
        lines.append("")

    lines.append("#### Recommended Flow Optimizations:")
    if top_interruptors:
        first = top_interruptors[0]
        lines.append(f"1. **Mute or batch notifications from {first['app']}**: It caused {first['count']} context switches ({first['lost_label']} lost).")
    if dist_pct > 20:
        lines.append("2. **Designate deliberate break windows**: Rather than checking media between tasks, schedule an uninterrupted 15-minute break.")
    else:
        lines.append("2. **Protect sustained focus momentum**: Your distraction ratio remains well within healthy boundaries.")

    quick_actions = [
        {"label": "Inspect Interruptors", "action": "navigate_tab", "param": "insights"},
        {"label": "View Timeline", "action": "navigate_timeline", "param": date_str},
    ]

    evidence = {
        "distraction_seconds": dist_secs,
        "distraction_pct": dist_pct,
        "total_active_seconds": total_active,
        "interruptions": interruptions,
    }

    return "\n".join(lines), quick_actions, evidence


def answer_time_breakdown(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Button 3: Where did my time go today?"""
    date_str = data["date_str"]
    total_active = data["total_active_label"]
    productive = data["productive_work_label"]
    distraction = data["distraction_label"]
    idle = data["total_idle_label"]
    unclassified = data["unclassified_label"]
    app_breakdown = data["app_breakdown"]

    lines = [
        f"### ⏱️ Where Your Time Went on {date_str}",
        "",
        f"Total observed computer activity was **{total_active}** (plus **{idle}** in away-from-keyboard idle gaps):",
        "",
        f"- **Productive Work:** `{productive}` ({round((data['productive_work_seconds'] / max(1.0, data['total_active_seconds'])) * 100, 1)}%)",
        f"- **Distractions & Media:** `{distraction}` ({round((data['distraction_seconds'] / max(1.0, data['total_active_seconds'])) * 100, 1)}%)",
        f"- **Uncertain / Needs Review:** `{unclassified}`",
        "",
        "#### Ranked Applications & Tools (With Specific Attribution):",
    ]

    for item in app_breakdown[:6]:
        app_name = item["app"]
        act_name = item["activity_name"]
        dur = item["duration_label"]
        pct = item["pct"]
        cat = item["category"]

        if item.get("is_browser") and item.get("children"):
            lines.append(f"- **{app_name}**: `{dur}` ({pct}%) — *{len(item['children'])} active websites*")
            for c in item["children"][:3]:
                lines.append(f"  - `{c['duration_label']}` • **{c['activity_name']}** ({c['category']})")
        else:
            lines.append(f"- **{app_name}**: `{dur}` ({pct}%) • *{act_name}* (`{cat}`)")

    quick_actions = [
        {"label": "Explore Analytics & Reports", "action": "navigate_tab", "param": "insights"},
        {"label": "Timeline View", "action": "navigate_timeline", "param": date_str},
    ]

    evidence = {
        "total_active_seconds": data["total_active_seconds"],
        "productive_work_seconds": data["productive_work_seconds"],
        "distraction_seconds": data["distraction_seconds"],
        "top_apps_count": len(app_breakdown),
    }

    return "\n".join(lines), quick_actions, evidence


def answer_performance_comparison(data: Dict[str, Any], prev_data: Optional[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Button 4: Am I improving compared with yesterday?"""
    date_str = data["date_str"]

    if not prev_data:
        return (
            f"### 📈 Performance Comparison for {date_str}\n\n"
            "Yesterday had no recorded tracking observations to compare against. "
            f"Today you completed **{data['productive_work_label']}** of productive work with **{data['deep_focus_label']}** in deep focus.",
            [{"label": "View History", "action": "navigate_tab", "param": "insights"}],
            {},
        )

    prev_date = prev_data["date_str"]
    work_diff = data["productive_work_seconds"] - prev_data["productive_work_seconds"]
    focus_diff = data["deep_focus_seconds"] - prev_data["deep_focus_seconds"]
    dist_diff = data["distraction_seconds"] - prev_data["distraction_seconds"]

    def fmt_diff(diff: float, higher_is_better: bool = True) -> str:
        sign = "+" if diff > 0 else "-"
        lbl = format_duration(abs(diff))
        status = "▲ Better" if (diff >= 0 if higher_is_better else diff <= 0) else "▼ Lower"
        return f"{sign}{lbl} ({status})"

    lines = [
        f"### 📈 Performance Comparison: {date_str} vs {prev_date}",
        "",
        "| Metric | Today | Yesterday | Difference |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Productive Work** | `{data['productive_work_label']}` | `{prev_data['productive_work_label']}` | {fmt_diff(work_diff, True)} |",
        f"| **Deep Focus** | `{data['deep_focus_label']}` | `{prev_data['deep_focus_label']}` | {fmt_diff(focus_diff, True)} |",
        f"| **Distractions** | `{data['distraction_label']}` | `{prev_data['distraction_label']}` | {fmt_diff(dist_diff, False)} |",
        f"| **Tracked Time** | `{data['total_active_label']}` | `{prev_data['total_active_label']}` | {format_duration(abs(data['total_active_seconds'] - prev_data['total_active_seconds']))} |",
        "",
        "#### Coaching Verdict:",
    ]

    if work_diff >= 1800 and dist_diff <= 300:
        lines.append("🚀 **Clear Improvement:** You increased productive work output significantly while keeping distractions contained.")
    elif focus_diff >= 1200:
        lines.append("🔥 **Quality Improvement:** You sustained deeper focus intervals with higher cognitive stamina.")
    elif dist_diff > 1800:
        lines.append("⚠️ **Distraction Creep:** Distraction time increased notably. Look into whether afternoon fatigue led to tab switching.")
    else:
        lines.append("⚖️ **Balanced Consistency:** Your work volume and focus discipline remained steady and reliable.")

    quick_actions = [
        {"label": "Open Analytics Comparison", "action": "navigate_tab", "param": "insights"},
    ]

    evidence = {
        "work_diff_seconds": work_diff,
        "focus_diff_seconds": focus_diff,
        "dist_diff_seconds": dist_diff,
    }

    return "\n".join(lines), quick_actions, evidence


def answer_what_next(db: sqlite3.Connection, data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Button 5: What should I focus on next?"""
    now_dt = datetime.now()
    now_time = now_dt.strftime("%H:%M")
    date_str = data["date_str"]

    is_tracking = tracker_manager.is_tracking_active()
    active_task = tracker_manager.get_active_task()

    # Current scheduled Time Block
    blocks = data["scheduled_blocks"]
    current_block = None
    upcoming_block = None

    for b in blocks:
        st = b.get("start_time", "00:00")
        et = b.get("end_time", "23:59")
        if st <= now_time <= et:
            current_block = b
        elif st > now_time and (upcoming_block is None or st < upcoming_block.get("start_time", "23:59")):
            upcoming_block = b

    # Goals evaluation
    goals = data["goals"]
    work_goal = next((g for g in goals if "work" in g.get("metric", "").lower() or "focus" in g.get("metric", "").lower()), None)

    lines = [
        "### 🚀 Action Recommendation",
        "",
    ]

    quick_actions = []

    # Priority 1: Ongoing active focus session in progress
    if active_task and active_task.get("user_task"):
        task_name = active_task["user_task"]
        lines.append(f"You have an active task in progress: **{task_name}**.")
        lines.append(f"Current duration: `{active_task.get('duration_label', 'Active')}`.")
        lines.append("👉 **Recommendation:** Protect your current momentum. Finish your current work milestone before switching tasks.")
        quick_actions.append({"label": "View Current Task", "action": "navigate_tab", "param": "overview"})

    # Priority 2: Scheduled Time Block right now
    elif current_block:
        title = current_block["title"]
        lines.append(f"Your schedule has a planned block right now (**{current_block['start_time']} – {current_block['end_time']}**):")
        lines.append(f"👉 **Focus on:** **{title}**")
        lines.append("Initiate a 25-minute Pomodoro focus run to align your activity with your daily planner.")
        quick_actions.append({"label": "Open Time Blocks", "action": "navigate_tab", "param": "timeblocks"})

    # Priority 3: Upcoming Time Block within the next hour
    elif upcoming_block:
        title = upcoming_block["title"]
        lines.append(f"Your next scheduled block begins at **{upcoming_block['start_time']}**: **{title}**.")
        lines.append("👉 **Recommendation:** Prepare reference materials, close distracting tabs, and begin on time.")
        quick_actions.append({"label": "Prepare Time Block", "action": "navigate_tab", "param": "timeblocks"})

    # Priority 4: Goal progress check
    elif work_goal and not work_goal.get("is_achieved"):
        target_label = work_goal.get("target_label", "target")
        curr_label = work_goal.get("actual_label") or work_goal.get("current_label", "0s")
        pct = work_goal.get("progress_pct", 0)
        lines.append(f"Your daily work goal is currently at **{curr_label} / {target_label}** ({pct}% complete).")
        lines.append("👉 **Recommendation:** Launch an uninterrupted 45-minute deep work session on your primary project to hit your daily goal.")
        quick_actions.append({"label": "Open Goals", "action": "navigate_tab", "param": "goals"})

    # Priority 5: Fallback general guidance
    else:
        lines.append(f"You have logged **{data['productive_work_label']}** of productive work today.")
        lines.append("👉 **Recommendation:** Take a 10-minute mental rest walk, or schedule your key focus priorities for tomorrow in Time Blocks.")
        quick_actions.append({"label": "Plan Tomorrow", "action": "navigate_tab", "param": "timeblocks"})

    evidence = {
        "is_tracking": is_tracking,
        "has_current_block": bool(current_block),
        "has_upcoming_block": bool(upcoming_block),
    }

    return "\n".join(lines), quick_actions, evidence


# ---------------------------------------------------------------------------
# Natural Language Chat Query Orchestrator
# ---------------------------------------------------------------------------

def process_ai_coach_message(
    db: sqlite3.Connection,
    message: str,
    selected_date: str,
    history: Optional[List[Dict[str, Any]]] = None,
    preset_action: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for AI Coach Chatbot.
    Dispatches to deterministic ground-truth engines and optionally polishes via Ollama.
    """
    msg_clean = (message or "").strip().lower()
    hist = history or []

    # 1. Resolve Target Date & Scope
    target_date = selected_date
    if "yesterday" in msg_clean:
        y = date.fromisoformat(selected_date) - timedelta(days=1)
        target_date = y.isoformat()
    elif "today" in msg_clean:
        target_date = date.today().isoformat()
    elif hist:
        # Check last assistant message for date_scope context if present
        for h in reversed(hist):
            if h.get("date_scope"):
                target_date = h["date_scope"]
                break

    # Load canonical day data
    day_data = _load_day_data(db, target_date)

    # Load yesterday's data for comparisons
    prev_d = date.fromisoformat(target_date) - timedelta(days=1)
    prev_data = _load_day_data(db, prev_d.isoformat())

    # 2. Check 5 Quick Button Presets
    if preset_action == "study_focus" or any(p in msg_clean for p in ("study and focus", "study time", "how much did i study", "focus today", "learning time")):
        resp_text, actions, evidence = answer_study_and_focus(day_data)
        return {
            "response": resp_text,
            "grounded": True,
            "sources": ["Observations", "Categories", "Research & Learning"],
            "quick_actions": actions,
            "date_scope": target_date,
            "meta": evidence,
        }

    if preset_action == "distractions" or any(p in msg_clean for p in ("waste", "wasted", "distraction", "distractions", "entertainment time", "lost time")):
        resp_text, actions, evidence = answer_distractions(day_data, prev_data)
        return {
            "response": resp_text,
            "grounded": True,
            "sources": ["Observations", "Entertainment & Media", "Interruptors"],
            "quick_actions": actions,
            "date_scope": target_date,
            "meta": evidence,
        }

    if preset_action == "time_breakdown" or any(p in msg_clean for p in ("where did my time go", "where did time go", "time breakdown", "breakdown today", "app breakdown", "applications used")):
        resp_text, actions, evidence = answer_time_breakdown(day_data)
        return {
            "response": resp_text,
            "grounded": True,
            "sources": ["Observations", "App Attribution", "Hierarchical Usage"],
            "quick_actions": actions,
            "date_scope": target_date,
            "meta": evidence,
        }

    if preset_action == "performance_comparison" or any(p in msg_clean for p in ("improving", "comparison", "compared with yesterday", "compare yesterday", "vs yesterday", "better than yesterday")):
        resp_text, actions, evidence = answer_performance_comparison(day_data, prev_data)
        return {
            "response": resp_text,
            "grounded": True,
            "sources": ["Daily Productivity", "Historical Comparison"],
            "quick_actions": actions,
            "date_scope": target_date,
            "meta": evidence,
        }

    if preset_action == "what_next" or any(p in msg_clean for p in ("what should i focus on next", "what should i do next", "what next", "next task", "recommend a task", "what to do")):
        resp_text, actions, evidence = answer_what_next(db, day_data)
        return {
            "response": resp_text,
            "grounded": True,
            "sources": ["Active Tracker", "Time Blocks", "Goals"],
            "quick_actions": actions,
            "date_scope": target_date,
            "meta": evidence,
        }

    # 3. Natural Language Queries: YouTube specific inquiry (Entertainment vs Learning)
    if "youtube" in msg_clean:
        yt_sessions = [
            s for s in day_data["sessions"]
            if "youtube" in ((s.get("app") or "") + (s.get("title") or "") + (s.get("url") or "")).lower()
        ]
        yt_secs = sum(s.get("duration_seconds", 0.0) for s in yt_sessions)
        yt_label = format_duration(yt_secs)

        yt_ent = [s for s in yt_sessions if "entertainment" in (s.get("category_name") or "").lower()]
        yt_edu = [s for s in yt_sessions if any(w in (s.get("category_name") or "").lower() for w in ("research", "learning", "coding"))]
        yt_other = [s for s in yt_sessions if s not in yt_ent and s not in yt_edu]

        yt_ent_sec = sum(s.get("duration_seconds", 0.0) for s in yt_ent)
        yt_edu_sec = sum(s.get("duration_seconds", 0.0) for s in yt_edu)

        lines = [
            f"### 📺 YouTube Activity Breakdown on {target_date}",
            "",
            f"Total observed YouTube screen time was **{yt_label}** across {len(yt_sessions)} intervals:",
            "",
            f"- **Entertainment & Gaming:** `{format_duration(yt_ent_sec)}` ({round(yt_ent_sec / max(1.0, yt_secs) * 100, 1)}%)",
            f"- **Research & Learning:** `{format_duration(yt_edu_sec)}` ({round(yt_edu_sec / max(1.0, yt_secs) * 100, 1)}%)",
            "",
        ]
        if yt_edu:
            lines.append("#### 🎓 Learning & Technical Content Observed:")
            edu_items = {}
            for s in yt_edu:
                name = s.get("activity_name") or s.get("title")
                edu_items[name] = edu_items.get(name, 0.0) + s.get("duration_seconds", 0.0)
            for name, sec in sorted(edu_items.items(), key=lambda x: x[1], reverse=True)[:3]:
                lines.append(f"- **{name}**: `{format_duration(sec)}`")
            lines.append("")

        if yt_ent:
            lines.append("#### 🎮 Entertainment, Streams & Shorts Observed:")
            ent_items = {}
            for s in yt_ent:
                name = s.get("activity_name") or s.get("title")
                ent_items[name] = ent_items.get(name, 0.0) + s.get("duration_seconds", 0.0)
            for name, sec in sorted(ent_items.items(), key=lambda x: x[1], reverse=True)[:4]:
                lines.append(f"- **{name}**: `{format_duration(sec)}`")

        if not yt_sessions:
            lines = [f"### 📺 YouTube Activity on {target_date}", "", "Zero YouTube activity observed on this date."]

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["YouTube Activity", "Category Breakdown"],
            "quick_actions": [{"label": "View Timeline", "action": "navigate_timeline", "param": target_date}],
            "date_scope": target_date,
            "meta": {"youtube_seconds": yt_secs, "entertainment_seconds": yt_ent_sec, "learning_seconds": yt_edu_sec},
        }

    # 4. Natural Language Queries: Netflix inquiry
    if "netflix" in msg_clean:
        nf_sessions = [
            s for s in day_data["sessions"]
            if "netflix" in ((s.get("app") or "") + (s.get("title") or "") + (s.get("url") or "")).lower()
        ]
        nf_secs = sum(s.get("duration_seconds", 0.0) for s in nf_sessions)
        lines = [
            f"### 🎬 Netflix Usage on {target_date}",
            "",
            f"You spent **{format_duration(nf_secs)}** streaming on Netflix across {len(nf_sessions)} session intervals.",
            "",
            f"- **Classification:** `Entertainment & Media` (Distraction)",
            f"- **Share of Distractions:** {round((nf_secs / max(1.0, day_data['distraction_seconds'])) * 100, 1)}% of total distraction time.",
        ]
        if nf_sessions:
            lines.append("")
            lines.append("👉 **Coaching Tip:** Schedule Netflix watching for designated evening downtime after daily goals are met.")

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Netflix Tracking", "Distraction Analysis"],
            "quick_actions": [{"label": "View Timeline", "action": "navigate_timeline", "param": target_date}],
            "date_scope": target_date,
            "meta": {"netflix_seconds": nf_secs},
        }

    # 5. Natural Language Queries: ChatGPT inquiry (Coding vs Research vs General)
    if "chatgpt" in msg_clean or "chat gpt" in msg_clean:
        cg_sessions = [
            s for s in day_data["sessions"]
            if any(k in ((s.get("app") or "") + (s.get("title") or "") + (s.get("url") or "")).lower() for k in ("chatgpt", "openai"))
        ]
        cg_secs = sum(s.get("duration_seconds", 0.0) for s in cg_sessions)
        cg_code = [s for s in cg_sessions if "coding" in (s.get("category_name") or "").lower()]
        cg_res = [s for s in cg_sessions if any(w in (s.get("category_name") or "").lower() for w in ("research", "learning"))]
        cg_other = [s for s in cg_sessions if s not in cg_code and s not in cg_res]

        code_sec = sum(s.get("duration_seconds", 0.0) for s in cg_code)
        res_sec = sum(s.get("duration_seconds", 0.0) for s in cg_res)

        lines = [
            f"### 🤖 ChatGPT Activity Breakdown on {target_date}",
            "",
            f"Total time spent using ChatGPT was **{format_duration(cg_secs)}**:",
            "",
            f"- **Coding & Debugging:** `{format_duration(code_sec)}` ({round((code_sec / max(1.0, cg_secs)) * 100, 1)}%)",
            f"- **Technical Research:** `{format_duration(res_sec)}` ({round((res_sec / max(1.0, cg_secs)) * 100, 1)}%)",
            "",
        ]
        cg_items = {}
        for s in cg_sessions:
            name = s.get("activity_name") or s.get("title")
            cg_items[name] = cg_items.get(name, 0.0) + s.get("duration_seconds", 0.0)
        if cg_items:
            lines.append("#### Specific Topics & Projects Observed:")
            for name, sec in sorted(cg_items.items(), key=lambda x: x[1], reverse=True)[:4]:
                lines.append(f"- **{name}**: `{format_duration(sec)}`")

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["ChatGPT Attribution", "AI Disambiguation"],
            "quick_actions": [{"label": "View Timeline", "action": "navigate_timeline", "param": target_date}],
            "date_scope": target_date,
            "meta": {"chatgpt_seconds": cg_secs, "coding_seconds": code_sec, "research_seconds": res_sec},
        }

    # 6. Natural Language Queries: Coding vs Researching
    if ("coding" in msg_clean and "research" in msg_clean) or "coding vs" in msg_clean or "code vs study" in msg_clean:
        code_time = day_data["coding_label"]
        code_secs = day_data["coding_seconds"]
        study_time = day_data["study_label"]
        study_secs = day_data["study_seconds"]
        ratio = round((code_secs / max(1.0, study_secs)), 2)

        lines = [
            f"### 💻 Coding vs. Research & Learning on {target_date}",
            "",
            f"| Activity Type | Duration | Share of Productive Time |",
            f"| :--- | :--- | :--- |",
            f"| **Coding & Development** | `{code_time}` | {round((code_secs / max(1.0, day_data['productive_work_seconds'])) * 100, 1)}% |",
            f"| **Research & Learning** | `{study_time}` | {round((study_secs / max(1.0, day_data['productive_work_seconds'])) * 100, 1)}% |",
            "",
            f"👉 **Ratio:** You spent **{ratio}x** as much time coding as researching.",
        ]
        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Coding Sessions", "Research Sessions"],
            "quick_actions": [{"label": "View Analytics", "action": "navigate_tab", "param": "insights"}],
            "date_scope": target_date,
            "meta": {"coding_seconds": code_secs, "study_seconds": study_secs},
        }

    # 7. Natural Language Queries: Uncertain / Needs Review Inquiry
    if "uncertain" in msg_clean or "needs review" in msg_clean or "unclassified" in msg_clean:
        unc_sessions = [
            s for s in day_data["sessions"]
            if s.get("kind") != "idle" and (
                s.get("is_uncertain") or (s.get("category_type") == "uncategorized") or "needs review" in (s.get("category_name") or "").lower()
            )
        ]
        unc_secs = sum(s.get("duration_seconds", 0.0) for s in unc_sessions)
        lines = [
            f"### 🔍 Uncertain & Unclassified Time on {target_date}",
            "",
            f"Total time marked as **Needs Review** is **{format_duration(unc_secs)}** ({round((unc_secs / max(1.0, day_data['total_active_seconds'])) * 100, 1)}% of tracked screen time).",
            "",
        ]
        if unc_sessions:
            lines.append("#### Items Requiring Classification Review:")
            unc_map = {}
            for s in unc_sessions:
                name = s.get("activity_name") or s.get("title")
                unc_map[name] = unc_map.get(name, 0.0) + s.get("duration_seconds", 0.0)
            for name, sec in sorted(unc_map.items(), key=lambda x: x[1], reverse=True)[:5]:
                lines.append(f"- **{name}**: `{format_duration(sec)}`")
            lines.append("")
            lines.append("👉 **Resolution:** You can reclassify these activities directly in Detailed Activity Records or create custom category rules in Settings.")
        else:
            lines.append("Zero uncertain activity! All tracked intervals have verified category attributions.")

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Uncertain Activity Audit"],
            "quick_actions": [{"label": "Open Detailed Records", "action": "navigate_tab", "param": "insights"}],
            "date_scope": target_date,
            "meta": {"uncertain_seconds": unc_secs},
        }

    # 8. Natural Language Queries: Top Websites Inquiry
    if "website" in msg_clean or "websites" in msg_clean or "sites" in msg_clean:
        app_breakdown = day_data["app_breakdown"]
        web_items = [item for item in app_breakdown if item.get("is_browser") or item.get("site_name")]
        lines = [
            f"### 🌐 Top Websites & Web Activities for {target_date}",
            "",
        ]
        if web_items:
            for item in web_items[:6]:
                name = item["app"]
                dur = item["duration_label"]
                pct = item["pct"]
                cat = item["category"]
                lines.append(f"- **{name}** (`{cat}`): `{dur}` ({pct}% of active time)")
        else:
            lines.append("No web browsing activity recorded today.")

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Website Attribution Engine"],
            "quick_actions": [{"label": "Analytics & Reports", "action": "navigate_tab", "param": "insights"}],
            "date_scope": target_date,
            "meta": {"web_items_count": len(web_items)},
        }

    # 4. Natural Language Queries: Interruptions inquiry
    if "interrupt" in msg_clean or "switch" in msg_clean or "interrupted" in msg_clean:
        interruptors = day_data["top_interruptors"]
        total_int = day_data["interruptions"]
        lines = [
            f"### ⚡ Focus Interruption Report for {target_date}",
            "",
            f"A total of **{total_int}** context-switch interruptions occurred during your focus runs today.",
            "",
        ]
        if interruptors:
            lines.append("#### Ranked Interruption Sources:")
            for item in interruptors:
                lines.append(f"- **{item['app']}**: `{item['lost_label']}` lost across {item['count']} switch events")
            lines.append("")
            lines.append(f"👉 **Coaching Tip:** Try setting `{interruptors[0]['app']}` to Do-Not-Disturb during deep focus.")
        else:
            lines.append("No focus interruptions were logged today! Excellent continuity.")

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Interruption Detection", "Focus Continuity"],
            "quick_actions": [{"label": "View Analytics", "action": "navigate_tab", "param": "insights"}],
            "date_scope": target_date,
            "meta": {"total_interruptions": total_int},
        }

    # 5. Natural Language Queries: Goals inquiry
    if "goal" in msg_clean or "goals" in msg_clean or "targets" in msg_clean:
        goals = day_data["goals"]
        lines = [
            f"### 🎯 Goal Progress for {target_date}",
            "",
        ]
        if goals:
            achieved = sum(1 for g in goals if g.get("is_achieved"))
            lines.append(f"You have achieved **{achieved} of {len(goals)}** configured goals today:")
            lines.append("")
            for g in goals:
                icon = "✅" if g.get("is_achieved") else "⏳"
                curr_lbl = g.get('actual_label') or g.get('current_label') or '0s'
                lines.append(f"- {icon} **{g.get('title')}**: `{curr_lbl}` / `{g.get('target_label')}` ({g.get('progress_pct', 0)}%)")
        else:
            lines.append("No active productivity goals configured yet.")
            lines.append("👉 Click below to create your daily work time or focus goals.")

        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Goals Engine"],
            "quick_actions": [{"label": "Manage Goals", "action": "navigate_tab", "param": "goals"}],
            "date_scope": target_date,
            "meta": {"goals_count": len(goals)},
        }

    # 6. Natural Language Queries: Daily Review inquiry
    if "review" in msg_clean or "summary" in msg_clean or "how did i do" in msg_clean:
        longest = day_data["longest_streak"]
        top_int = day_data["top_interruptors"]
        lines = [
            f"### 🌟 Daily Executive Review for {target_date}",
            "",
            f"- **Productive Work Accomplished:** `{day_data['productive_work_label']}` (out of `{day_data['total_active_label']}` active screen time).",
            f"- **Deep Focus:** `{day_data['deep_focus_label']}`.",
            f"- **Distraction Loss:** `{day_data['distraction_label']}`.",
            "",
            "#### 🏆 What Went Well:",
            (
                f"- Longest focus run reached **{longest['duration_label']}** uninterrupted on `{longest['app']}`."
                if longest else
                f"- Successfully logged {day_data['productive_work_label']} of active development."
            ),
            "",
            "#### ⚠️ What Stood In The Way:",
            (
                f"- Top context switch interruptions: {top_int[0]['app']} ({top_int[0]['lost_label']} lost)."
                if top_int else
                "Minimal focus interruptions detected today."
            ),
            "",
            "#### 🎯 Actionable Improvement for Tomorrow:",
            "Schedule a designated 90-minute morning deep work block before opening communication or media apps.",
        ]
        return {
            "response": "\n".join(lines),
            "grounded": True,
            "sources": ["Comprehensive Daily Synthesis"],
            "quick_actions": [
                {"label": "View Timeline", "action": "navigate_timeline", "param": target_date},
                {"label": "Analytics & Reports", "action": "navigate_tab", "param": "insights"},
            ],
            "date_scope": target_date,
            "meta": {},
        }

    # 7. General Conversational Fallback (Ollama if available, else Grounded Overview)
    if _is_ollama_available():
        try:
            summary_facts = f"""
Facts for {target_date}:
- Productive Work Time: {day_data['productive_work_label']}
- Deep Focus Time: {day_data['deep_focus_label']}
- Study Time: {day_data['study_label']}
- Coding Time: {day_data['coding_label']}
- Distraction Time: {day_data['distraction_label']}
- Total Tracked Time: {day_data['total_active_label']}
- Focus Interruptions: {day_data['interruptions']}
- Longest Streak: {day_data['longest_streak']['duration_label'] if day_data['longest_streak'] else 'None'}
"""
            prompt = f"""You are Time Tracker AI's intelligent productivity coach.
Answer the user's question directly, concisely, and empathetically using ONLY the verified facts below.
Do not invent facts or numbers.

{summary_facts}

User Question: {message}
"""
            payload = {
                "model": AI_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.2},
            }
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_obj = json.loads(response.read().decode("utf-8"))
                llm_text = res_obj.get("message", {}).get("content", "").strip()
                if llm_text:
                    return {
                        "response": llm_text,
                        "grounded": True,
                        "sources": ["Ollama LLM", "Verified Tracked Observations"],
                        "quick_actions": [{"label": "View Timeline", "action": "navigate_timeline", "param": target_date}],
                        "date_scope": target_date,
                        "meta": {},
                    }
        except Exception:
            pass

    # Deterministic Conversational Fallback
    fallback_lines = [
        f"### 🤖 AI Coach Insight for {target_date}",
        "",
        f"Regarding *\"{message}\"*: Today you logged **{day_data['productive_work_label']}** of productive work out of **{day_data['total_active_label']}** total computer time.",
        "",
        f"- **Deep Focus:** `{day_data['deep_focus_label']}`",
        f"- **Study & Learning:** `{day_data['study_label']}`",
        f"- **Distraction Time:** `{day_data['distraction_label']}`",
        f"- **Interruptions:** `{day_data['interruptions']} events`",
        "",
        "You can click any of the 5 quick questions above for specialized deep-dive breakdowns.",
    ]

    return {
        "response": "\n".join(fallback_lines),
        "grounded": True,
        "sources": ["Grounded Activity Engine"],
        "quick_actions": [
            {"label": "View Timeline", "action": "navigate_timeline", "param": target_date},
            {"label": "Analytics & Reports", "action": "navigate_tab", "param": "insights"},
        ],
        "date_scope": target_date,
        "meta": {},
    }
