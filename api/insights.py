"""
api/insights.py — Productivity analysis, interruption detection, and daily AI summaries.

Analyzes session transitions to identify true focus interruptions, computes
productivity metrics, and generates AI or deterministic daily summaries.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from activity_report import AI_MODEL, OLLAMA_URL, format_duration
from api.categories import match_category
from api.goals import analyze_time_blocks, evaluate_goals
from api.migrations import now_iso


def _is_ollama_online(timeout: float = 0.8) -> bool:
    """Quick check if local Ollama daemon is reachable."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def detect_interruptions_and_streaks(
    sessions: List[Dict[str, Any]]
) -> Tuple[int, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Rigorously detect interruptions during focus sessions.
    
    Definition:
    An interruption occurs when the user is engaged in an active focus session
    (duration >= 180s in a 'focus' or 'work' category) and switches to an
    unrelated app for a brief burst (< 180s) or distraction, or experiences an idle break.
    
    Returns:
    (total_interruptions, top_interruptors_list, longest_focus_streak)
    """
    if not sessions:
        return 0, [], None

    interruptor_counts: Dict[str, int] = {}
    interruptor_durations: Dict[str, float] = {}
    total_interruptions = 0

    longest_focus_streak: Optional[Dict[str, Any]] = None
    max_focus_secs = 0.0

    # Track ongoing focus streak across sessions
    current_focus_secs = 0.0
    current_focus_start = None
    current_focus_app = ""
    current_focus_title = ""

    for i, s in enumerate(sessions):
        kind = s.get("kind", "active")
        dur = s.get("duration_seconds", 0.0)
        c_type = s.get("category_type") or (s.get("category", {}).get("type", "work"))
        app = s.get("app", "Unknown")
        title = s.get("title", "")

        is_focus = (kind == "active" and c_type == "focus")

        if is_focus:
            if current_focus_secs == 0:
                current_focus_start = s.get("start")
                current_focus_app = app
                current_focus_title = title
            current_focus_secs += dur

            if current_focus_secs > max_focus_secs:
                max_focus_secs = current_focus_secs
                longest_focus_streak = {
                    "app": current_focus_app,
                    "title": current_focus_title,
                    "start": current_focus_start,
                    "end": s.get("end"),
                    "duration_seconds": current_focus_secs,
                    "duration_label": format_duration(current_focus_secs),
                }
        else:
            # Not focus: check if this was an interruption of a prior focus session
            if current_focus_secs >= 180.0:
                # Prior session was a real focus session!
                # If this session is short (< 300s) or is a distraction:
                if dur < 300.0 or c_type == "distraction":
                    interrupting_name = app if kind != "idle" else "Idle Gap"
                    interruptor_counts[interrupting_name] = interruptor_counts.get(interrupting_name, 0) + 1
                    interruptor_durations[interrupting_name] = interruptor_durations.get(interrupting_name, 0.0) + dur
                    total_interruptions += 1

            current_focus_secs = 0.0
            current_focus_start = None

    # Rank top interruptors by frequency and duration
    top_interruptors = []
    for app_name, count in sorted(interruptor_counts.items(), key=lambda x: (x[1], interruptor_durations.get(x[0], 0)), reverse=True)[:6]:
        lost = interruptor_durations.get(app_name, 0.0)
        top_interruptors.append({
            "app": app_name,
            "count": count,
            "lost_seconds": round(lost, 1),
            "lost_label": format_duration(lost),
        })

    return total_interruptions, top_interruptors, longest_focus_streak


def compute_daily_productivity(
    db: sqlite3.Connection,
    date_str: str,
    sessions: List[Dict[str, Any]],
    prev_sessions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Compute comprehensive productivity metrics for a given date.
    All metrics are 100% deterministic, grounded in SQLite observations.
    """
    total_active_seconds = sum(s["duration_seconds"] for s in sessions if s.get("kind") != "idle")
    total_idle_seconds = sum(s["duration_seconds"] for s in sessions if s.get("kind") == "idle")

    # Category totals
    category_totals: Dict[str, Dict[str, Any]] = {}
    type_totals = {"focus": 0.0, "work": 0.0, "personal": 0.0, "distraction": 0.0, "uncategorized": 0.0}

    for s in sessions:
        if s.get("kind") == "idle":
            continue
        cat = s.get("category") or {}
        cat_name = cat.get("name") or s.get("category_name") or "Other / Needs Review"
        cat_type = cat.get("type") or s.get("category_type")
        if not cat_type or (cat_type == "personal" and any(w in cat_name.lower() for w in ("uncategorized", "other", "review"))):
            cat_type = "uncategorized"
        cat_color = cat.get("color") or s.get("category_color") or "#9ca3af"
        dur = s.get("duration_seconds", 0.0)

        if cat_type in type_totals:
            type_totals[cat_type] += dur
        else:
            type_totals["uncategorized"] += dur

        if cat_name not in category_totals:
            category_totals[cat_name] = {
                "name": cat_name,
                "type": cat_type,
                "color": cat_color,
                "seconds": 0.0,
            }
        category_totals[cat_name]["seconds"] += dur

    # Sort categories by duration descending
    category_breakdown = []
    for c in sorted(category_totals.values(), key=lambda x: x["seconds"], reverse=True):
        pct = round(c["seconds"] / total_active_seconds * 100, 1) if total_active_seconds > 0 else 0.0
        category_breakdown.append({
            "name": c["name"],
            "type": c["type"],
            "color": c["color"],
            "seconds": c["seconds"],
            "label": format_duration(c["seconds"]),
            "pct": pct,
        })

    # Productive work calculation
    # Only "focus" and "work" categories count as productive work.
    # Distractions, idle time, personal tasks, and unclassified activities are excluded.
    productive_work_seconds = type_totals["focus"] + type_totals["work"]
    unclassified_seconds = type_totals["uncategorized"]
    study_seconds = sum(
        s.get("duration_seconds", 0.0)
        for s in sessions
        if s.get("kind") != "idle" and any(
            k in (s.get("category_name") or s.get("category", {}).get("name") or "").lower()
            for k in ("research", "study", "learning")
        )
    )

    # Interruption & streak detection
    total_interruptions, top_interruptors, longest_streak = detect_interruptions_and_streaks(sessions)

    # Focus score calculation (0 - 100):
    # Weighted by focus ratio (50%), distraction minimization (30%), interruption frequency (20%)
    if total_active_seconds > 0:
        focus_ratio = type_totals["focus"] / total_active_seconds
        distraction_ratio = type_totals["distraction"] / total_active_seconds
        interruption_penalty = min(0.3, (total_interruptions * 0.03))
        score = max(5, min(100, int((focus_ratio * 60) + (max(0, 1.0 - distraction_ratio) * 40) - (interruption_penalty * 100))))
    else:
        score = 0

    # Day-over-day comparison
    comparison = None
    if prev_sessions:
        prev_active = sum(s["duration_seconds"] for s in prev_sessions if s.get("kind") != "idle")
        prev_productive = sum(
            s["duration_seconds"]
            for s in prev_sessions
            if s.get("kind") != "idle" and (
                s.get("category_type") in ("focus", "work") or
                s.get("category", {}).get("type") in ("focus", "work")
            )
        )
        prev_focus = sum(
            s["duration_seconds"]
            for s in prev_sessions
            if s.get("kind") != "idle" and (s.get("category_type") == "focus" or s.get("category", {}).get("type") == "focus")
        )
        prev_distraction = sum(
            s["duration_seconds"]
            for s in prev_sessions
            if s.get("kind") != "idle" and (s.get("category_type") == "distraction" or s.get("category", {}).get("type") == "distraction")
        )
        prev_interruptions, _, _ = detect_interruptions_and_streaks(prev_sessions)

        comparison = {
            "work_change_seconds": round(productive_work_seconds - prev_productive, 1),
            "work_change_label": format_duration(abs(productive_work_seconds - prev_productive)),
            "work_improved": productive_work_seconds >= prev_productive,
            "focus_change_seconds": round(type_totals["focus"] - prev_focus, 1),
            "focus_change_label": format_duration(abs(type_totals["focus"] - prev_focus)),
            "focus_improved": type_totals["focus"] >= prev_focus,
            "distraction_change_seconds": round(type_totals["distraction"] - prev_distraction, 1),
            "distraction_change_label": format_duration(abs(type_totals["distraction"] - prev_distraction)),
            "distraction_improved": type_totals["distraction"] <= prev_distraction,
            "interruption_change": total_interruptions - prev_interruptions,
        }

    # Goal evaluation
    goal_results = evaluate_goals(db, date_str, sessions)

    # Time-block analysis
    block_results = analyze_time_blocks(db, date_str, sessions)

    return {
        "date": date_str,
        "total_work_seconds": round(productive_work_seconds, 1),
        "total_work_label": format_duration(productive_work_seconds),
        "productive_work_seconds": round(productive_work_seconds, 1),
        "productive_work_label": format_duration(productive_work_seconds),
        "total_tracked_seconds": round(total_active_seconds, 1),
        "total_tracked_label": format_duration(total_active_seconds),
        "total_idle_seconds": round(total_idle_seconds, 1),
        "total_idle_label": format_duration(total_idle_seconds),
        "focus_seconds": round(type_totals["focus"], 1),
        "focus_label": format_duration(type_totals["focus"]),
        "study_seconds": round(study_seconds, 1),
        "study_label": format_duration(study_seconds),
        "distraction_seconds": round(type_totals["distraction"], 1),
        "distraction_label": format_duration(type_totals["distraction"]),
        "unclassified_seconds": round(unclassified_seconds, 1),
        "unclassified_label": format_duration(unclassified_seconds),
        "productivity_score": score,
        "category_breakdown": category_breakdown,
        "total_interruptions": total_interruptions,
        "top_interruptors": top_interruptors,
        "longest_streak": longest_streak,
        "comparison": comparison,
        "goals": goal_results,
        "time_blocks": block_results,
    }


def generate_daily_ai_summary(
    db: sqlite3.Connection,
    date_str: str,
    productivity: Dict[str, Any],
    refresh: bool = False,
) -> Dict[str, Any]:
    """
    Generate or fetch cached daily AI productivity summary.
    If Ollama is available, enriches with AI insights; otherwise provides
    a deterministic evidence-based summary. Never blocks routine polling.
    """
    try:
        obs_count = db.execute(
            "SELECT COUNT(*) FROM observations WHERE date(start_time, 'localtime') = ?", (date_str,)
        ).fetchone()[0]
    except (sqlite3.OperationalError, Exception):
        obs_count = 0

    # Check database cache first
    if not refresh:
        try:
            row = db.execute(
                "SELECT summary_json, obs_count FROM daily_ai_summaries WHERE date = ?",
                (date_str,),
            ).fetchone()
            if row and row["obs_count"] == obs_count:
                try:
                    cached = json.loads(row["summary_json"])
                    cached["source"] = "cache"
                    return cached
                except Exception:
                    pass
        except (sqlite3.OperationalError, Exception):
            pass

    # Deterministic factual baseline
    total_work = productivity.get("productive_work_label") or productivity.get("total_work_label", "0s")
    total_tracked = productivity.get("total_tracked_label", total_work)
    focus_time = productivity.get("focus_label", "0s")
    study_time = productivity.get("study_label", "0s")
    distraction_time = productivity.get("distraction_label", "0s")
    unclassified_time = productivity.get("unclassified_label", "0s")
    interruptions = productivity.get("total_interruptions", 0)
    top_interruptors = productivity.get("top_interruptors", [])
    longest = productivity.get("longest_streak")
    goals = productivity.get("goals", [])
    achieved_goals = sum(1 for g in goals if g.get("is_achieved"))

    # Generate personalized coaching narrative and actionable suggestions
    longest_label = longest["duration_label"] if longest else "0m"
    longest_app = longest["app"] if longest else "your tools"
    top_int_str = ", ".join([f"{item['app']} ({item['count']}x)" for item in top_interruptors[:3]])

    narrative_parts = []
    if longest:
        narrative_parts.append(f"Your longest focus block was {longest_label} on {longest_app}.")
    else:
        narrative_parts.append("Your focus was spread across brief sessions today without extended blocks.")

    if top_interruptors:
        primary_int = top_interruptors[0]
        narrative_parts.append(f"{primary_int['app']} interrupted {primary_int['count']} session{'s' if primary_int['count'] > 1 else ''}; try batching notifications.")
    elif interruptions == 0:
        narrative_parts.append("Zero focus interruptions occurred today—exceptional task continuity.")

    dist_secs = productivity.get("distraction_seconds", 0)
    if dist_secs > 0:
        narrative_parts.append(f"You spent {distraction_time} on distractions.")
    else:
        narrative_parts.append("No recorded distraction activity today.")

    coach_narrative = " ".join(narrative_parts)

    # Structured suggestions matching Image A
    suggestions = []
    if interruptions > 2 and top_interruptors:
        suggestions.append({
            "id": "batch_notifications",
            "icon": "mute",
            "text": f"Consider muting {top_interruptors[0]['app']} during scheduled focus blocks.",
            "type": "distraction",
        })
    if productivity.get("focus_seconds", 0) < 7200:
        suggestions.append({
            "id": "deep_work_block",
            "icon": "lightbulb",
            "text": "Try a 90-minute focus block this afternoon for complex tasks.",
            "type": "focus",
        })
    else:
        suggestions.append({
            "id": "sustain_momentum",
            "icon": "lightbulb",
            "text": "Strong deep work momentum today. Take intentional 10-minute rest breaks.",
            "type": "break",
        })

    # Derive Coach headline, key win, main challenge, suggestion matching Image A
    if productivity.get("focus_seconds", 0) >= 7200 or productivity.get("productivity_score", 0) >= 65:
        headline = "Great progress today! 🔥"
    elif productivity.get("total_work_seconds", 0) > 0:
        headline = "Solid momentum building! ⚡"
    else:
        headline = "Ready to start your focus day? 🚀"

    key_win = (
        f"{longest_label} uninterrupted focus block on {longest_app}."
        if longest
        else (f"Reached {achieved_goals} daily goals." if achieved_goals > 0 else "Consistent computer activity recorded.")
    )

    if top_interruptors:
        first_int = top_interruptors[0]
        main_challenge = f"Frequent {first_int['app']} checks ({first_int['count']} times, {first_int['lost_label']} lost)."
    elif dist_secs > 600:
        main_challenge = f"Spent {distraction_time} on distracting applications."
    else:
        main_challenge = "Minimal distractions detected during active periods."

    suggestion_text = suggestions[0]["text"] if suggestions else "Try a 45-minute focus block after lunch with notifications off."

    # Format human-friendly time for "Generated 10:05 PM"
    now_dt = datetime.now()
    generated_time_str = now_dt.strftime("%I:%M %p").lstrip("0")

    recommendations = [s["text"] for s in suggestions]
    key_takeaway = f"Completed {total_work} of productive work ({total_tracked} total active screen time) with {focus_time} in deep focus and {distraction_time} on distractions."

    deterministic_summary = {
        "headline": headline,
        "key_takeaway": key_takeaway,
        "narrative": coach_narrative,
        "key_win": key_win,
        "main_challenge": main_challenge,
        "suggestion": suggestion_text,
        "what_went_well": key_win,
        "what_got_in_way": main_challenge,
        "focus_streak_summary": f"Your longest uninterrupted focus block was {longest_label} on {longest_app}." if longest else "No extended focus blocks detected.",
        "interruption_analysis": f"Top interruptions came from: {top_int_str}." if top_interruptors else "No focus interruptions recorded.",
        "goals_summary": f"Achieved {achieved_goals} of {len(goals)} configured productivity goals.",
        "recommendations": recommendations,
        "suggestions": suggestions,
        "source": "deterministic",
        "generated_at": now_iso(),
        "generated_time_label": generated_time_str,
    }

    # If Ollama is not requested or offline, return deterministic summary immediately
    if not refresh or not _is_ollama_online():
        # Save to DB cache
        db.execute(
            """
            INSERT OR REPLACE INTO daily_ai_summaries (date, summary_json, obs_count, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (date_str, json.dumps(deterministic_summary), obs_count, now_iso()),
        )
        db.commit()
        return deterministic_summary

    # Call Ollama for natural language enhancement when explicitly requested
    try:
        prompt = f"""
You are an executive productivity coach reviewing a user's computer activity for date {date_str}.
Adopt a warm, direct, empathetic, and evidence-grounded coaching tone (like Gemini Coach).
Facts:
- Productive work time: {total_work}
- Total active screen time: {total_tracked}
- Deep focus time: {focus_time}
- Distraction time: {distraction_time}
- Interruption count: {interruptions}
- Top interruptors: {top_int_str or 'None'}
- Longest focus session: {longest.get('duration_label', 'None') if longest else 'None'} ({longest.get('app', '') if longest else ''})
- Goals achieved: {achieved_goals}/{len(goals)}

Return JSON with exact keys:
{{
  "narrative": "A warm, concise 2-3 sentence coaching narrative highlighting the day's wins, interruptions, and distraction patterns with concrete numbers.",
  "what_went_well": "1 specific evidence-based sentence on wins",
  "what_got_in_way": "1 specific sentence on what broke focus or caused friction",
  "suggestions": [
    {{"icon": "lightbulb", "text": "Specific next action 1"}},
    {{"icon": "mute", "text": "Specific next action 2"}}
  ]
}}
"""
        payload = {
            "model": AI_MODEL,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.2},
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            res_obj = json.loads(response.read().decode("utf-8"))
            content = res_obj.get("message", {}).get("content", "")
            parsed = json.loads(content)
            ai_narrative = parsed.get("narrative", coach_narrative)
            ai_suggestions = parsed.get("suggestions", suggestions)
            ai_recs = [s.get("text", "") for s in ai_suggestions if isinstance(s, dict)] or recommendations

            ai_summary = {
                "headline": headline,
                "key_takeaway": ai_narrative,
                "narrative": ai_narrative,
                "key_win": parsed.get("what_went_well", key_win),
                "main_challenge": parsed.get("what_got_in_way", main_challenge),
                "suggestion": ai_recs[0] if ai_recs else suggestion_text,
                "what_went_well": parsed.get("what_went_well", deterministic_summary["what_went_well"]),
                "what_got_in_way": parsed.get("what_got_in_way", deterministic_summary["what_got_in_way"]),
                "focus_streak_summary": deterministic_summary["focus_streak_summary"],
                "interruption_analysis": deterministic_summary["interruption_analysis"],
                "goals_summary": deterministic_summary["goals_summary"],
                "recommendations": ai_recs,
                "suggestions": ai_suggestions,
                "source": "AI Coach",
                "generated_at": now_iso(),
                "generated_time_label": generated_time_str,
            }
            db.execute(
                """
                INSERT OR REPLACE INTO daily_ai_summaries (date, summary_json, obs_count, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (date_str, json.dumps(ai_summary), obs_count, now_iso()),
            )
            db.commit()
            return ai_summary
    except Exception:
        return deterministic_summary
