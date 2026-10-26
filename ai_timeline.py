"""
ai_timeline.py — AI-powered, editable activity timeline.

Reads observations already collected by main.py and browser_tracker.py,
groups them into human-readable sessions, and adds AI-generated descriptions.
User corrections are stored in timeline_edits and survive restarts.

Usage:
    python ai_timeline.py                       # Today's timeline
    python ai_timeline.py 2026-10-20            # Specific date
    python ai_timeline.py --edit 3              # Edit session #3 interactively
    python ai_timeline.py --edit 3 2026-10-20   # Edit on a specific date
    python ai_timeline.py --refresh-ai          # Bypass AI description cache
    python ai_timeline.py --no-idle             # Hide idle periods
"""

import hashlib
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Reconfigure Windows console encoding so emojis and unicode page titles
# print cleanly without charmap encoding errors.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Reuse existing configuration and helpers from activity_report
# ---------------------------------------------------------------------------
from activity_report import (
    AI_MODEL,
    AI_TIMEOUT_SECONDS,
    DB_PATH,
    OLLAMA_URL,
    _RUN_CONTEXT_CACHE,
    clean_url,
    describe_unknown_screenshot,
    extract_json,
    format_duration,
    is_browser_app,
    load_browser_visits,
    parse_timestamp,
    use_visual_fallback,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMELINE_CLASSIFIER_VERSION = "timeline-activity-v2"

# Gap between two consecutive same-activity observations that forces a new session.
SESSION_GAP_SECONDS: int = 120

# Observations shorter than this are noise and are discarded.
MIN_SESSION_SECONDS: float = 2.0

# AI confidence below this marks a session as uncertain.
UNCERTAIN_CONFIDENCE: float = 0.45

_SEP = "-" * 90

BROWSER_SUFFIXES = (
    " - Google Chrome",
    " - Microsoft Edge",
    " - Chromium",
    " - Mozilla Firefox",
    " - Opera",
    " - Brave",
)

UNKNOWN_TITLES = {
    "", "unknown", "untitled window", "new tab", "about:blank", "google chrome",
    "microsoft edge", "opera", "firefox"
}

SENSITIVE_APP_TOKENS = (
    # Password managers & vaults
    "keepass", "1password", "bitwarden", "lastpass", "dashlane",
    "enpass", "nordpass", "roboform", "passbolt", "authenticator",
    "password", "vault", "credential",
    # Private / Incognito browsing
    "incognito", "inprivate", "private browsing", "private window",
    # Authentication & Accounts
    "login", "log in", "sign in", "signin", "sign-in", "sign up", "signup",
    "auth", "sso", "2fa", "mfa", "two-factor", "verification code",
    "reset password", "change password", "enter credentials", "oauth",
    # Banking & Financial & Payments
    "bank", "banking", "wallet", "paypal", "stripe checkout", "checkout",
    "credit card", "billing", "chase", "wells fargo", "citi", "bank of america",
    "crypto", "binance", "coinbase", "metamask",
    # Private messaging
    "signal", "telegram", "whatsapp", "discord", "viber", "wire",
    # Medical & Health records
    "mychart", "patient portal", "medical record", "health record",
)


# ---------------------------------------------------------------------------
# Database helpers — timeline_edits table
# ---------------------------------------------------------------------------


def ensure_timeline_edits(db: sqlite3.Connection) -> None:
    """Create timeline_edits if it does not exist. Safe on any existing database."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS timeline_edits (
            id          INTEGER PRIMARY KEY,
            session_key TEXT    NOT NULL UNIQUE,
            description TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
        """
    )
    db.commit()


def get_user_edit(db: sqlite3.Connection, session_key: str) -> str | None:
    """Return the user-supplied description for this session, or None."""
    row = db.execute(
        "SELECT description FROM timeline_edits WHERE session_key = ?",
        (session_key,),
    ).fetchone()
    return row["description"] if row else None


def save_user_edit(
    db: sqlite3.Connection, session_key: str, description: str
) -> None:
    """Persist a user description. Overwrites any previous edit."""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO timeline_edits (session_key, description, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(session_key) DO UPDATE SET
            description = excluded.description,
            updated_at  = excluded.updated_at
        """,
        (session_key, description.strip(), now, now),
    )
    db.commit()


def delete_user_edit(db: sqlite3.Connection, session_key: str) -> bool:
    """Remove a user correction so the AI description is used again.
    Returns True if a row was deleted, False if none existed."""
    cursor = db.execute(
        "DELETE FROM timeline_edits WHERE session_key = ?", (session_key,)
    )
    db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Session key
# ---------------------------------------------------------------------------


def make_session_key(kind: str, app: str, first_obs_id: int) -> str:
    """
    Stable 16-character identifier for a session.

    Keyed on (kind, app, first_observation_id) so user edits survive
    re-runs as long as the underlying observations are unchanged.
    Observation IDs are database PKs and never reused.
    """
    value = f"{kind}\n{app}\n{first_obs_id}"
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Title cleaning and topic extraction helpers
# ---------------------------------------------------------------------------


def clean_window_title(title: str, app: str = "") -> str:
    """Strip browser/IDE suffixes, dirty indicators, and normalize whitespace."""
    t = (title or "").strip()
    if t.startswith("● "):  # VS Code dirty file indicator
        t = t[2:].strip()
    for suffix in BROWSER_SUFFIXES:
        if t.endswith(suffix):
            t = t[:-len(suffix)].strip()
            break
    if t.endswith(" - Visual Studio Code"):
        t = t[:-len(" - Visual Studio Code")].strip()
    return t


def is_sensitive_window(app: str, title: str, url: str = "") -> bool:
    """Check if app, window title, or URL matches sensitive application tokens."""
    combined = f"{app or ''} {title or ''} {url or ''}".lower()
    return any(token in combined for token in SENSITIVE_APP_TOKENS)


def _extract_vscode_info(title: str) -> dict:
    """Extract filename, project name, and language from a VS Code title."""
    clean = clean_window_title(title)
    parts = clean.split(" - ")
    filename = parts[0].strip() if parts else ""
    project = parts[1].strip() if len(parts) > 1 else ""

    is_welcome = clean.lower() == "welcome" or filename.lower() == "welcome"
    ext = Path(filename).suffix.lower() if filename else ""

    return {
        "filename": filename,
        "project": project,
        "extension": ext,
        "is_welcome": is_welcome,
        "clean_title": clean,
    }


def _extract_browser_info(title: str, url: str) -> dict:
    """Analyze browser title and URL to detect domain, platform, and topics."""
    clean = clean_window_title(title)
    clean_lower = clean.lower()
    url_lower = (url or "").lower()

    # 1. ChatGPT
    is_chatgpt = (
        "chatgpt.com" in url_lower
        or "chat.openai.com" in url_lower
        or "chatgpt" in clean_lower
    )
    chatgpt_topic = ""
    if is_chatgpt:
        topic_cand = re.sub(r"(?i)\bchatgpt\b", "", clean).strip(" -|:—\t\r\n")
        # Remove trailing emojis/stars
        topic_cand = re.sub(r"[\s🌟⭐✨]+$", "", topic_cand).strip()
        if topic_cand and topic_cand.lower() not in UNKNOWN_TITLES and topic_cand.lower() != "new chat":
            chatgpt_topic = topic_cand

    # 2. Google Gemini
    is_gemini = "gemini.google.com" in url_lower or "google gemini" in clean_lower
    gemini_topic = ""
    if is_gemini:
        cand = re.sub(r"(?i)\bgoogle gemini\b", "", clean).strip(" -|:—\t\r\n")
        if cand and cand.lower() not in UNKNOWN_TITLES:
            gemini_topic = cand

    # 3. Documentation
    is_docs = (
        "docs.python.org" in url_lower
        or "python.org/doc" in url_lower
        or "sqlite.org" in url_lower
        or "developer.mozilla.org" in url_lower
        or "stackoverflow.com" in url_lower
        or "github.com" in url_lower
        or "python documentation" in clean_lower
        or "documentation" in clean_lower
    )
    docs_subject = ""
    if is_docs:
        if "sqlite" in url_lower or "sqlite" in clean_lower:
            docs_subject = "SQLite"
        elif "docs.python.org" in url_lower or "python documentation" in clean_lower:
            docs_subject = "Python"
        elif "github.com" in url_lower or "github" in clean_lower:
            docs_subject = "GitHub"
        elif "stackoverflow.com" in url_lower or "stack overflow" in clean_lower:
            docs_subject = "Stack Overflow"
        else:
            docs_subject = "documentation"

    # 4. YouTube
    is_youtube = "youtube.com" in url_lower or "youtube" in clean_lower
    video_topic = ""
    if is_youtube:
        cand = re.sub(r"(?i)\b-?\s*youtube\b", "", clean).strip(" -|:—\t\r\n")
        if cand and cand.lower() not in UNKNOWN_TITLES:
            video_topic = cand

    # 5. Hacktoberfest
    is_hacktoberfest = "hacktoberfest" in clean_lower or "hacktoberfest" in url_lower
    hacktoberfest_page = ""
    if is_hacktoberfest:
        if "activities" in clean_lower:
            hacktoberfest_page = "activities page"
        elif "schedule" in clean_lower:
            hacktoberfest_page = "schedule"
        elif "my hacktoberfest" in clean_lower:
            hacktoberfest_page = "dashboard"
        else:
            hacktoberfest_page = "site"

    # 6. Google Search
    is_search = "google.com/search" in url_lower or "google search" in clean_lower
    search_query = ""
    if is_search:
        query_cand = re.sub(r"(?i)\b-?\s*google search\b", "", clean).strip(" -|:—\t\r\n")
        if query_cand:
            search_query = query_cand

    is_generic = clean_lower in UNKNOWN_TITLES or clean_lower == ""

    return {
        "clean_title": clean,
        "is_chatgpt": is_chatgpt,
        "chatgpt_topic": chatgpt_topic,
        "is_gemini": is_gemini,
        "gemini_topic": gemini_topic,
        "is_docs": is_docs,
        "docs_subject": docs_subject,
        "is_youtube": is_youtube,
        "video_topic": video_topic,
        "is_hacktoberfest": is_hacktoberfest,
        "hacktoberfest_page": hacktoberfest_page,
        "is_search": is_search,
        "search_query": search_query,
        "is_generic": is_generic,
    }


# ---------------------------------------------------------------------------
# Activity Fingerprinting for Meaningful Session Grouping
# ---------------------------------------------------------------------------


def get_activity_fingerprint(obs: dict, visits: list[dict] | None = None) -> tuple:
    """
    Generate an activity fingerprint tuple so that adjacent observations
    are merged only when they represent the same meaningful activity.

    - Distinct browser activities (ChatGPT vs. Hacktoberfest vs. Docs) produce distinct fingerprints.
    - Consecutive pages within the same website/task (e.g. Hacktoberfest) produce identical fingerprints.
    - Coding within the same IDE project produces identical fingerprints.
    - Idle produces a dedicated idle fingerprint.
    """
    if obs["kind"] == "idle":
        return ("idle",)

    app = (obs.get("app") or "Unknown").strip().lower()
    title = obs.get("title") or ""

    # Code editors
    if app in ("code.exe", "devenv.exe", "pycharm64.exe", "sublime_text.exe", "cursor.exe"):
        vs = _extract_vscode_info(title)
        # Use project name if available, else app name
        proj = vs["project"].lower() if vs["project"] else ""
        return ("code", app, proj)

    # Browsers
    if is_browser_app(app):
        # Check URL from visits if available
        matched_url = ""
        if visits:
            best_v = find_matching_browser_visit({"start": obs["start"], "end": obs["end"], "titles": {title}}, visits)
            if best_v:
                matched_url = best_v.get("url") or ""

        info = _extract_browser_info(title, matched_url)
        if info["is_chatgpt"]:
            # Same ChatGPT topic or general ChatGPT
            return ("browser", "chatgpt", info["chatgpt_topic"].lower() if info["chatgpt_topic"] else "")
        if info["is_gemini"]:
            return ("browser", "gemini", info["gemini_topic"].lower() if info["gemini_topic"] else "")
        if info["is_hacktoberfest"]:
            return ("browser", "hacktoberfest", "")
        if info["is_docs"]:
            return ("browser", "docs", info["docs_subject"].lower())
        if info["is_youtube"]:
            return ("browser", "youtube", info["video_topic"].lower() if info["video_topic"] else "")
        if info["is_search"]:
            return ("browser", "search", info["search_query"].lower())
        if info["is_generic"]:
            return ("browser", "generic", app)

        # General web page: extract main domain or topic keyword
        clean = info["clean_title"].lower()
        parts = [p.strip() for p in re.split(r"[|\-—]", clean) if p.strip()]
        topic_key = parts[-1] if len(parts) > 1 else (parts[0] if parts else "")
        return ("browser", "web", topic_key)

    # Desktop apps
    return ("app", app)


# ---------------------------------------------------------------------------
# Observation loading
# ---------------------------------------------------------------------------


def load_observations(
    db: sqlite3.Connection,
    day_start: datetime,
    day_end: datetime,
) -> list[dict]:
    """
    Load observations that overlap the requested day, clipped to its boundaries.
    Only rows with a positive clipped duration are returned.
    Handles UTC vs local timezone differences and midnight boundaries strictly.
    """
    # Ensure day_start and day_end are timezone-aware
    if day_start.tzinfo is None:
        day_start = day_start.astimezone()
    if day_end.tzinfo is None:
        day_end = day_end.astimezone()

    from datetime import timezone as dt_tz
    day_start_utc = day_start.astimezone(dt_tz.utc).isoformat()
    day_end_utc   = day_end.astimezone(dt_tz.utc).isoformat()
    day_start_loc = day_start.isoformat()
    day_end_loc   = day_end.isoformat()

    # Check if task column exists in observations table
    cols = {r[1] for r in db.execute("PRAGMA table_info(observations)").fetchall()}
    has_task = "task" in cols
    select_cols = "id, kind, app, title, start_time, end_time, duration_seconds" + (", task" if has_task else "")

    # Query matching either UTC-formatted timestamps or local-formatted timestamps in DB
    rows = db.execute(
        f"""
        SELECT {select_cols}
        FROM observations
        WHERE (
            (start_time < ? AND (end_time IS NULL OR end_time > ?))
            OR
            (start_time < ? AND (end_time IS NULL OR end_time > ?))
        )
        ORDER BY start_time, id
        """,
        (day_end_utc, day_start_utc, day_end_loc, day_start_loc),
    ).fetchall()

    now: datetime = datetime.now().astimezone()
    result: list[dict] = []

    for row in rows:
        start = parse_timestamp(row["start_time"])
        end   = parse_timestamp(row["end_time"], now)

        if start is None or end is None:
            continue

        # Strict boundary exclusion: does observation actually overlap [day_start, day_end)?
        if end <= day_start or start >= day_end:
            continue

        # Clip to the day's boundaries so we never count time outside the day.
        clipped_start = max(start, day_start)
        clipped_end   = min(end,   day_end)
        secs  = max(0.0, (clipped_end - clipped_start).total_seconds())

        if secs <= 0:
            continue

        is_ongoing = (row["end_time"] is None)
        if not is_ongoing and secs < MIN_SESSION_SECONDS:
            continue

        result.append(
            {
                "id":               row["id"],
                "kind":             row["kind"] or "active",
                "app":              row["app"]   or "Unknown",
                "title":            row["title"] or "Untitled window",
                "start":            clipped_start,
                "end":              clipped_end,
                "duration_seconds": secs,
                "is_ongoing":       is_ongoing,
                "task":             row["task"] if has_task and "task" in row.keys() else None,
            }
        )

    # Deduplicate exact identical intervals to avoid inflating totals
    deduped_result: list[dict] = []
    seen_intervals: set = set()
    for item in result:
        inv_key = (item["app"], item["title"], item["start"].isoformat(), item["end"].isoformat())
        if inv_key in seen_intervals:
            continue
        seen_intervals.add(inv_key)
        deduped_result.append(item)

    # If Manual Entry exists, it is authoritative over Idle periods that overlap it
    manual_intervals = [
        (m["start"], m["end"]) for m in deduped_result if m["app"] == "Manual Entry"
    ]
    if manual_intervals:
        final_result = []
        for item in deduped_result:
            if item["kind"] == "idle":
                # Check if this idle interval is subsumed by a manual entry
                is_subsumed = any(
                    m_start <= item["start"] and item["end"] <= m_end
                    for m_start, m_end in manual_intervals
                )
                if is_subsumed:
                    continue
            final_result.append(item)
        return final_result

    return deduped_result


# ---------------------------------------------------------------------------
# Session grouping
# ---------------------------------------------------------------------------


def _new_session(obs: dict) -> dict:
    return {
        "kind":             obs["kind"],
        "app":              obs["app"],
        "title":            obs["title"],
        "start":            obs["start"],
        "end":              obs["end"],
        "duration_seconds": obs["duration_seconds"],
        "titles":           {obs["title"]},
        "observation_ids":  [obs["id"]],
        "ai_description":   None,
        "user_description": None,
        "confidence":       None,
        "is_uncertain":     False,
        "source":           None,
        "url":              None,
        "domain":           None,
        "task":             obs.get("task"),
        "session_key":      None,
        "is_ongoing":       bool(obs.get("is_ongoing", False)),
    }


def group_into_sessions(
    observations: list[dict],
    visits: list[dict] | None = None,
) -> list[dict]:
    """
    Merge consecutive observations only when they represent the same meaningful activity.

    Grouping rules:
    - Same kind (active vs. idle).
    - Consecutive idle periods merge together.
    - Active observations merge only when their activity fingerprints match
      (e.g., same coding workspace, same web task/domain).
    - Preserves distinct explicit user-assigned tasks (no merging across different tasks).
    - Gap between observations must not exceed SESSION_GAP_SECONDS.
    - Duration is always the sum of constituent durations (no gap double-counting).
    """
    if not observations:
        return []

    sessions: list[dict] = []
    current: dict | None = None

    for obs in observations:
        if current is not None:
            same_kind = obs["kind"] == current["kind"]
            gap = (obs["start"] - current["end"]).total_seconds()
            within_gap = gap <= SESSION_GAP_SECONDS

            if not same_kind or not within_gap:
                merge = False
            elif obs["kind"] == "idle":
                merge = True
            else:
                task_curr = (current.get("task") or "").strip()
                task_obs = (obs.get("task") or "").strip()
                if task_curr and task_obs and task_curr != task_obs:
                    merge = False
                else:
                    fp_curr = get_activity_fingerprint(current, visits)
                    fp_obs = get_activity_fingerprint(obs, visits)
                    merge = (fp_curr == fp_obs)
        else:
            merge = False

        if merge:
            if obs["end"] > current["end"]:
                if obs["start"] < current["end"]:
                    # Overlapping interval: add only the non-overlapping extension
                    overlap_sec = max(0.0, (obs["end"] - current["end"]).total_seconds())
                    current["duration_seconds"] += overlap_sec
                else:
                    current["duration_seconds"] += obs["duration_seconds"]
                current["end"] = obs["end"]
            current["title"]             = obs["title"]
            current["titles"].add(obs["title"])
            current["observation_ids"].append(obs["id"])
            if not current.get("task") and obs.get("task"):
                current["task"] = obs["task"]
            if obs.get("is_ongoing"):
                current["is_ongoing"] = True
        else:
            if current is not None:
                sessions.append(current)
            current = _new_session(obs)

    if current is not None:
        sessions.append(current)

    # Assign stable session keys using the first observation ID in each group.
    for s in sessions:
        s["session_key"] = make_session_key(
            s["kind"], s["app"], s["observation_ids"][0]
        )

    return sessions


# ---------------------------------------------------------------------------
# Browser visit matching & Stored Vision Integration
# ---------------------------------------------------------------------------


def find_matching_browser_visit(
    session: dict, visits: list[dict]
) -> dict | None:
    """
    Match browser_visits records to a timeline session using both
    time overlap and window/page title similarity.
    """
    if not visits:
        return None

    best_visit = None
    best_score = 0.0

    session_titles = {clean_window_title(t).lower() for t in session.get("titles", {session.get("title", "")})}

    for v in visits:
        overlap_start = max(session["start"], v["start"])
        overlap_end   = min(session["end"],   v["end"])
        overlap = max(0.0, (overlap_end - overlap_start).total_seconds())

        v_title_clean = clean_window_title(v.get("title", "")).lower()
        title_match = v_title_clean in session_titles if v_title_clean else False

        # Score combining time overlap and exact title matching
        score = overlap + (60.0 if title_match else 0.0)

        if score > best_score:
            best_score = score
            best_visit = v

    return best_visit if best_score > 0 else None


def _best_url_for_session(session: dict, visits: list[dict]) -> str:
    """Return the URL of the best matching browser visit for this session."""
    v = find_matching_browser_visit(session, visits)
    return v["url"] if v else ""


def _stored_vision_description(db: sqlite3.Connection, session: dict) -> str | None:
    """Return a vision description stored during tracking for any obs in this session."""
    for obs_id in session["observation_ids"]:
        try:
            row = db.execute(
                "SELECT description FROM activity_screenshots "
                "WHERE observation_id = ? AND description != ''",
                (obs_id,),
            ).fetchone()
            if row and row["description"] and row["description"].strip():
                return row["description"].strip()
        except sqlite3.OperationalError:
            pass
    return None


# ---------------------------------------------------------------------------
# Evidence-based Activity Description Inference
# ---------------------------------------------------------------------------


def infer_evidence_description(
    session: dict, stored_vision: str | None = None
) -> tuple[str, float, str, bool]:
    """
    Infer a concise, specific, evidence-grounded activity description.

    Returns:
        (description, confidence, source, is_uncertain)
    """
    # 1. Idle
    if session["kind"] == "idle":
        return ("Idle — no input detected.", 1.0, "system", False)

    app = session.get("app") or "Unknown"
    app_lower = app.lower()
    title = session.get("title") or ""
    url = session.get("url") or ""

    # 2. Sensitive apps safeguard
    if is_sensitive_window(app, title, url):
        clean_app = app.replace(".exe", "").capitalize()
        return (f"Using {clean_app} (sensitive application)", 1.0, "privacy", False)

    # 3. If stored vision description exists and window title or metadata is generic, use visual context
    if stored_vision:
        title_lower = title.strip().lower()
        clean_vision = stored_vision.strip()
        is_generic = (
            title_lower in UNKNOWN_TITLES
            or app_lower in ("explorer.exe", "unknown", "unknown.exe", "applicationframehost.exe", "notepad.exe")
            or title_lower.startswith("untitled")
            or title_lower == app_lower.replace(".exe", "")
        )
        if is_generic:
            return (f"Visual context: {clean_vision}", 0.90, "vision", False)

    # 4. VS Code / Code Editors
    if app_lower in ("code.exe", "devenv.exe", "pycharm64.exe", "sublime_text.exe", "cursor.exe"):
        vs = _extract_vscode_info(title)
        fn = vs["filename"]
        proj = vs["project"]

        if vs["is_welcome"]:
            return ("Viewing Welcome page in VS Code", 0.95, "evidence", False)

        if fn:
            if fn.lower() == "ai_timeline.py":
                return ("Editing the AI timeline implementation in Python", 0.95, "evidence", False)
            if fn.lower() == "browser_tracker.py":
                return ("Editing the browser tracker implementation in Python", 0.95, "evidence", False)
            if fn.lower() == "main.py":
                target = f" ({proj})" if proj else ""
                return (f"Editing main.py in Python{target}", 0.95, "evidence", False)
            if fn.lower().startswith("test_"):
                return (f"Editing unit tests in Python ({fn})", 0.95, "evidence", False)
            if vs["extension"] == ".py":
                target = f" ({proj})" if proj else ""
                return (f"Editing {fn} in Python{target}", 0.92, "evidence", False)

            # Other file types
            target = f" in {proj}" if proj else ""
            return (f"Editing {fn}{target} in VS Code", 0.90, "evidence", False)

        if vs["clean_title"] and vs["clean_title"].lower() != "visual studio code":
            return (f"Working in VS Code on {vs['clean_title']}", 0.85, "evidence", False)

        return ("Working in VS Code — active file unspecified", 0.65, "evidence", False)

    # 5. Browsers
    if is_browser_app(app_lower):
        b_info = _extract_browser_info(title, url)

        # 5a. ChatGPT
        if b_info["is_chatgpt"]:
            topic = b_info["chatgpt_topic"]
            if topic:
                # Format naturally: "Working in ChatGPT on the time-tracking project"
                topic_clean = topic.strip()
                if "time tracking" in topic_clean.lower() or "time tracker" in topic_clean.lower():
                    return ("Working in ChatGPT on the time-tracking project", 0.95, "evidence", False)
                if topic_clean.lower().startswith("discuss"):
                    return (f"{topic_clean} in ChatGPT", 0.92, "evidence", False)
                return (f"Working in ChatGPT on {topic_clean}", 0.92, "evidence", False)
            return ("Working in ChatGPT — conversation topic unspecified", 0.80, "evidence", False)

        # 5b. Google Gemini
        if b_info["is_gemini"]:
            topic = b_info["gemini_topic"]
            if topic:
                return (f"Working in Google Gemini on '{topic}'", 0.90, "evidence", False)
            return ("Working in Google Gemini", 0.85, "evidence", False)

        # 5c. Documentation
        if b_info["is_docs"]:
            subj = b_info["docs_subject"]
            if subj == "SQLite":
                return ("Reading Python documentation about SQLite", 0.95, "evidence", False)
            if subj == "Python":
                return ("Reading Python documentation", 0.92, "evidence", False)
            if subj == "GitHub":
                return ("Browsing GitHub repository", 0.90, "evidence", False)
            if subj == "Stack Overflow":
                return ("Researching developer discussions on Stack Overflow", 0.90, "evidence", False)
            return ("Reading technical documentation in Chrome", 0.85, "evidence", False)

        # 5d. Hacktoberfest
        if b_info["is_hacktoberfest"]:
            page = b_info["hacktoberfest_page"]
            if page == "activities page":
                return ("Reading the Hacktoberfest 2026 activities page", 0.95, "evidence", False)
            if page == "schedule":
                return ("Checking the Hacktoberfest 2026 October schedule", 0.92, "evidence", False)
            if page == "dashboard":
                return ("Viewing My Hacktoberfest 2026 dashboard", 0.92, "evidence", False)
            return ("Browsing Hacktoberfest 2026 in Chrome", 0.90, "evidence", False)

        # 5e. YouTube
        if b_info["is_youtube"]:
            v = b_info["video_topic"]
            if v:
                return (f"Watching or listening to '{v}' on YouTube", 0.90, "evidence", False)
            return ("Browsing YouTube", 0.85, "evidence", False)

        # 5f. Google Search
        if b_info["is_search"]:
            q = b_info["search_query"]
            if q:
                return (f"Searching Google for '{q}'", 0.90, "evidence", False)
            return ("Searching Google", 0.80, "evidence", False)

        # 5g. Generic browser window
        if b_info["is_generic"]:
            b_name = "Chrome" if "chrome" in app_lower else ("Edge" if "edge" in app_lower else "browser")
            return (f"Browsing in {b_name} — specific activity unclear", 0.35, "evidence", True)

        # 5h. Specific web page
        clean_t = b_info["clean_title"]
        if clean_t:
            b_name = "Chrome" if "chrome" in app_lower else ("Edge" if "edge" in app_lower else "browser")
            return (f"Reading '{clean_t}' in {b_name}", 0.82, "evidence", False)

    # 6. Windows desktop utilities
    if app_lower == "snippingtool.exe":
        return ("Taking screenshot or clipping using Snipping Tool", 0.90, "evidence", False)

    if app_lower == "explorer.exe":
        clean_t = clean_window_title(title)
        if clean_t and clean_t.lower() not in UNKNOWN_TITLES:
            return (f"Browsing files in {clean_t} using Windows Explorer", 0.80, "evidence", False)
        return ("Using Windows Explorer — specific folder unclear", 0.35, "evidence", True)

    if app_lower in ("cmd.exe", "powershell.exe", "windowsterminal.exe", "wt.exe"):
        return ("Running command-line tools in Terminal", 0.80, "evidence", False)

    # 7. Generic fallback
    clean_t = clean_window_title(title)
    if clean_t and clean_t.lower() not in UNKNOWN_TITLES:
        return (f"Using {app}: {clean_t}", 0.60, "evidence", False)

    return (f"Using {app} — specific activity unclear", 0.25, "evidence", True)


# ---------------------------------------------------------------------------
# Ollama AI Integration with Local Caching
# ---------------------------------------------------------------------------


_OLLAMA_ONLINE: bool | None = None


def is_ollama_available() -> bool:
    """Check once if the local Ollama service is reachable to avoid repeated connection timeouts."""
    global _OLLAMA_ONLINE
    if _OLLAMA_ONLINE is not None:
        return _OLLAMA_ONLINE
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            _OLLAMA_ONLINE = (resp.status == 200)
    except Exception:
        _OLLAMA_ONLINE = False
    return _OLLAMA_ONLINE


def _timeline_cache_key(app: str, title: str, url: str) -> str:
    value = "\n".join((TIMELINE_CLASSIFIER_VERSION, AI_MODEL, app or "", title or "", clean_url(url)))
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def ask_timeline_ai(
    app: str, title: str, url: str = "", nearby_context: str = ""
) -> dict:
    """Call Ollama with timeline-specific instructions and rules."""
    safe_url = clean_url(url)
    clean_t = clean_window_title(title, app)

    prompt = f"""
Infer the specific computer activity from this foreground window metadata.

Examples of desired detail:
- VS Code: "Editing the AI timeline implementation in Python"
- Chrome: "Reading the Hacktoberfest 2026 activities page"
- ChatGPT: "Working in ChatGPT on the time-tracking project"
- Documentation: "Reading Python documentation about SQLite"
- Insufficient evidence: "Browsing in Chrome — specific activity unclear"

Rules:
- Distinguish ChatGPT activity from coding in VS Code.
- When the window or URL indicates ChatGPT, identify the topic from page title when supported.
- Never invent code changes, typed prompts, or unseen actions.
- Do not guess hidden activity or assume browser activity is coding time tracker unless supported by browser evidence.
- If evidence is generic or insufficient, explicitly mark uncertainty and set confidence below 0.40.
- Return one JSON object only:
{{
  "activity": "Concise natural-language description",
  "reason": "Brief explanation",
  "confidence": 0.0
}}

Application: {app}
Window title: {clean_t or "Untitled"}
Sanitized URL: {safe_url or "Unavailable"}
"""

    payload = {
        "model": AI_MODEL,
        "stream": False,
        "format": "json",
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.1},
    }

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SECONDS) as response:
        outer = json.loads(response.read().decode("utf-8"))

    content = outer.get("message", {}).get("content", "")
    if not content.strip():
        raise ValueError("Ollama returned an empty response")

    parsed = extract_json(content)
    act = (parsed.get("activity") or "").strip()
    if not act:
        raise ValueError("Model response has no activity description")

    conf = float(parsed.get("confidence", 0.0) or 0.0)
    conf = max(0.0, min(1.0, conf))

    return {
        "activity": act[:200],
        "reason": str(parsed.get("reason", "")).strip()[:400],
        "confidence": conf,
        "source": "AI",
    }


def classify_timeline_activity(
    db: sqlite3.Connection,
    app: str,
    title: str,
    url: str = "",
    nearby_context: str = "",
    refresh: bool = False,
    allow_network: bool = True,
) -> dict:
    """Classify with cache support in activity_ai_context table."""
    key = _timeline_cache_key(app, title, url)

    if not refresh:
        if key in _RUN_CONTEXT_CACHE:
            return dict(_RUN_CONTEXT_CACHE[key])

        # Check activity_ai_context table
        try:
            row = db.execute(
                "SELECT activity, reason, confidence FROM activity_ai_context WHERE context_key = ?",
                (key,),
            ).fetchone()
            if row:
                cached = {
                    "activity": row["activity"],
                    "reason": row["reason"],
                    "confidence": float(row["confidence"] or 0),
                    "source": "cache",
                }
                _RUN_CONTEXT_CACHE[key] = cached
                return cached
        except sqlite3.OperationalError:
            pass

    if not allow_network:
        return {
            "activity": "",
            "reason": "Live AI disabled; using cached or evidence fallback",
            "confidence": 0.0,
            "source": "fallback",
        }

    # Check if Ollama is online before attempting HTTP call
    if not is_ollama_available():
        return {
            "activity": "",
            "reason": "Ollama service offline",
            "confidence": 0.0,
            "source": "fallback",
        }

    # Ask AI
    try:
        res = ask_timeline_ai(app, title, url, nearby_context)

        # Save to database cache
        now_ts = datetime.now().astimezone().isoformat(timespec="seconds")
        db.execute(
            """
            INSERT OR REPLACE INTO activity_ai_context
                (context_key, app, title, url, activity, reason, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (key, app or "", title or "", clean_url(url), res["activity"], res["reason"], res["confidence"], now_ts),
        )
        db.commit()
        _RUN_CONTEXT_CACHE[key] = dict(res)
        return res
    except Exception as err:
        # Fallback to rule-based evidence description
        return {
            "activity": "",
            "reason": f"AI unavailable: {err}",
            "confidence": 0.0,
            "source": "fallback",
        }


def classify_activity(
    db: sqlite3.Connection,
    app: str,
    title: str,
    url: str = "",
    nearby_context: str = "",
    refresh: bool = False,
    allow_network: bool = True,
) -> dict:
    """Classify activity using Ollama with caching in activity_ai_context."""
    return classify_timeline_activity(db, app, title, url, nearby_context, refresh, allow_network=allow_network)


# ---------------------------------------------------------------------------
# Session Enrichment
# ---------------------------------------------------------------------------


def enrich_session(
    db: sqlite3.Connection,
    session: dict,
    visits: list[dict],
    all_sessions: list[dict],
    index: int,
    refresh: bool = False,
    allow_network: bool = True,
) -> None:
    """
    Populate ai_description, confidence, is_uncertain, and source on *session*
    in-place by combining evidence rules, browser visits, stored vision descriptions,
    and Ollama AI models.
    """
    # 1. Idle session
    if session["kind"] == "idle":
        session["ai_description"] = "Idle — no input detected."
        session["confidence"]     = 1.0
        session["is_uncertain"]   = False
        session["source"]         = "system"
        return

    app = session["app"]
    title = session["title"]

    # 2. Match browser visit (URL and specific page title)
    url = ""
    if is_browser_app(app):
        matched_v = find_matching_browser_visit(session, visits)
        if matched_v:
            url = matched_v.get("url") or ""
            # If observation title was generic but visit has a real title, use it
            if clean_window_title(title).lower() in UNKNOWN_TITLES and matched_v.get("title"):
                title = matched_v["title"]
                session["title"] = title
        elif db is not None:
            # Fallback to historical visits by title when browser_tracker wasn't running concurrently
            try:
                for t_cand in session.get("titles", {title}):
                    if t_cand and clean_window_title(t_cand).lower() not in UNKNOWN_TITLES:
                        row = db.execute(
                            "SELECT url FROM browser_visits WHERE title = ? AND url != '' AND url != 'https://' ORDER BY id DESC LIMIT 1",
                            (t_cand,),
                        ).fetchone()
                        if row and row["url"]:
                            url = row["url"]
                            break
            except sqlite3.OperationalError:
                pass
    session["url"] = clean_url(url)
    try:
        from api.categories import extract_domain_and_site
        dom_meta = extract_domain_and_site(app, title, session["url"])
        session["domain"] = dom_meta.get("domain") or None
    except Exception:
        pass

    # 3. Check for stored vision description from live tracking
    stored_vision = _stored_vision_description(db, session)

    # 4. Generate deterministic evidence-grounded description
    ev_desc, ev_conf, ev_src, ev_unc = infer_evidence_description(session, stored_vision)

    # 5. If evidence is high confidence (e.g. >= 0.85) and not uncertain, prefer evidence description
    if ev_conf >= 0.85 and not refresh and not ev_unc:
        session["ai_description"] = ev_desc
        session["confidence"]     = ev_conf
        session["source"]         = ev_src
        session["is_uncertain"]   = False
        return

    # 6. When AI is requested or evidence has lower confidence, call classifier
    first_obs_id = session["observation_ids"][0] if session.get("observation_ids") else None
    ai_result = classify_activity(db, app, title, url, "", refresh=refresh, allow_network=allow_network)
    ai_result = use_visual_fallback(db, first_obs_id, ai_result)

    act = (ai_result.get("activity") or "").strip()
    conf = float(ai_result.get("confidence", 0) or 0)
    is_unc = (
        conf < UNCERTAIN_CONFIDENCE
        or "uncertain" in act.lower()
        or "could not be classified" in act.lower()
        or "insufficient evidence" in act.lower()
    )

    if not is_unc and act:
        session["ai_description"] = act
        session["confidence"]     = conf
        session["source"]         = ai_result.get("source", "AI")
        session["is_uncertain"]   = False
    elif stored_vision:
        session["ai_description"] = f"Visual context: {stored_vision}"
        session["confidence"]     = 0.85
        session["source"]         = "vision"
        session["is_uncertain"]   = False
    else:
        # Fall back to evidence description or AI result
        session["ai_description"] = act or ev_desc
        session["confidence"]     = conf if act else ev_conf
        session["source"]         = ai_result.get("source", ev_src)
        session["is_uncertain"]   = is_unc if act else ev_unc


def enrich_all_sessions(
    db: sqlite3.Connection,
    sessions: list[dict],
    visits: list[dict],
    refresh: bool = False,
    verbose: bool = True,
    allow_network: bool = True,
) -> None:
    """Enrich every session; prints progress and handles Ctrl+C gracefully."""
    active_count = sum(1 for s in sessions if s["kind"] != "idle")
    if not active_count:
        return

    if verbose:
        print(
            f"Analyzing and classifying {active_count} session(s) "
            f"(cached results reused)... Press Ctrl+C to skip."
        )

    try:
        for i, s in enumerate(sessions):
            enrich_session(db, s, visits, sessions, i, refresh=refresh, allow_network=allow_network)
    except KeyboardInterrupt:
        if verbose:
            print("[info] Classification interrupted — showing partial results.")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

_UNCERTAIN_TAG = " [?]"
_EDITED_TAG    = " [edited]"


def print_timeline(
    sessions: list[dict],
    date_str: str,
    *,
    show_idle: bool = True,
) -> None:
    """Render the timeline to stdout."""
    print(f"\nAI ACTIVITY TIMELINE  {date_str}")
    print(_SEP)
    print(f"  {'#':>3}  {'Start':>8}  {'End':>8}  {'Duration':>10}  App")
    print(_SEP)

    active_total = 0.0
    idle_total   = 0.0
    displayed    = 0

    for s in sessions:
        if s["kind"] == "idle" and not show_idle:
            idle_total += s["duration_seconds"]
            continue

        num       = s.get("_display_number", "?")
        start_str = s["start"].astimezone().strftime("%H:%M:%S")
        end_str   = s["end"].astimezone().strftime("%H:%M:%S")
        dur_str   = format_duration(s["duration_seconds"])
        app_str   = (s["app"] or "Unknown")[:28]

        print()
        print(f"  {num:>3}  {start_str:>8}  {end_str:>8}  {dur_str:>10}  {app_str}")

        desc = (
            s.get("user_description")
            or s.get("ai_description")
            or "No description available."
        )
        tag = ""
        if s.get("user_description"):
            tag = _EDITED_TAG
        elif s.get("is_uncertain"):
            tag = _UNCERTAIN_TAG

        _print_wrapped(f"  -> {desc}{tag}", indent="      ", width=76)

        if s.get("url"):
            print(f"     URL: {s['url'][:78]}")

        if s["kind"] == "idle":
            idle_total += s["duration_seconds"]
        else:
            active_total += s["duration_seconds"]
        displayed += 1

    print()
    print(_SEP)
    print(
        f"  Active : {format_duration(active_total)}"
        f"   Idle : {format_duration(idle_total)}"
        f"   Sessions shown : {displayed}"
    )
    print()
    print(f"  [?] = uncertain description   [edited] = user-corrected")
    print(f"  To edit: python ai_timeline.py --edit <number> [YYYY-MM-DD]")
    print()


def _print_wrapped(text: str, indent: str, width: int) -> None:
    """Print text with simple word-wrap, applying *indent* from the second line."""
    words  = text.split()
    line   = ""
    first  = True
    for word in words:
        if len(line) + len(word) + 1 > width and line:
            print(line.rstrip())
            line  = indent
            first = False
        line += word + " "
    if line.strip():
        print(line.rstrip())


# ---------------------------------------------------------------------------
# Interactive edit
# ---------------------------------------------------------------------------


def prompt_edit(
    db: sqlite3.Connection,
    sessions: list[dict],
    number: int,
) -> int:
    """Interactively edit a session description by its displayed number."""
    target = next(
        (s for s in sessions if s.get("_display_number") == number), None
    )
    if target is None:
        if 1 <= number <= len(sessions):
            target = sessions[number - 1]
    if target is None:
        print(
            f"Session #{number} not found. "
            "Run without --edit to see the numbered list."
        )
        return 1

    start_s = target["start"].astimezone().strftime("%H:%M:%S")
    end_s   = target["end"].astimezone().strftime("%H:%M:%S")
    print(
        f"\nSession #{number}  {start_s} - {end_s}"
        f"  [{target['app']}]"
    )
    ai_desc   = target.get("ai_description") or "No AI description."
    user_desc = target.get("user_description")
    print(f"  Inferred description : {ai_desc}")
    if user_desc:
        print(f"  Current edit         : {user_desc}")

    print(
        "\nEnter a new description"
        " (blank = keep current, 'clear' = restore inferred description):"
    )
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nEdit cancelled.")
        return 0

    if not raw:
        print("No change made.")
        return 0

    if raw.lower() == "clear":
        if delete_user_edit(db, target["session_key"]):
            print("User edit removed. Inferred description will be shown.")
        else:
            print("No user edit existed for this session.")
        return 0

    save_user_edit(db, target["session_key"], raw)
    print(f"Saved: {raw}")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class _Args:
    selected_date: date | None = None
    edit:          int | None  = None
    refresh_ai:    bool        = False
    show_idle:     bool        = True


def _parse_args(argv: list[str]) -> "_Args | None":
    args       = _Args()
    positional = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--refresh-ai":
            args.refresh_ai = True
        elif arg == "--no-idle":
            args.show_idle = False
        elif arg == "--edit":
            if i + 1 >= len(argv):
                print("--edit requires a session number, e.g.: --edit 3")
                return None
            i += 1
            try:
                args.edit = int(argv[i])
            except ValueError:
                print(f"Invalid session number: {argv[i]!r}")
                return None
        elif arg.startswith("--edit="):
            try:
                args.edit = int(arg.split("=", 1)[1])
            except ValueError:
                print(f"Invalid session number in {arg!r}")
                return None
        elif arg.startswith("-"):
            print(f"Unknown flag: {arg!r}")
            print(
                "Usage: python ai_timeline.py [YYYY-MM-DD] "
                "[--edit N] [--refresh-ai] [--no-idle]"
            )
            return None
        else:
            positional.append(arg)
        i += 1

    if len(positional) > 1:
        print(
            "Usage: python ai_timeline.py [YYYY-MM-DD] "
            "[--edit N] [--refresh-ai] [--no-idle]"
        )
        return None

    if positional:
        try:
            args.selected_date = date.fromisoformat(positional[0])
        except ValueError:
            print(f"Invalid date: {positional[0]!r}. Use YYYY-MM-DD.")
            return None

    return args


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)
    if args is None:
        return 1

    _RUN_CONTEXT_CACHE.clear()

    selected_date = args.selected_date or date.today()
    day_start = datetime.combine(selected_date, time.min).astimezone()
    day_end   = day_start + timedelta(days=1)

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Start main.py first to begin tracking.")
        return 1

    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        ensure_timeline_edits(db)

        observations = load_observations(db, day_start, day_end)
        if not observations:
            print(f"No activity recorded for {selected_date}.")
            return 0

        visits = load_browser_visits(
            db, day_start, day_end, datetime.now().astimezone()
        )
        sessions = group_into_sessions(observations, visits)

        enrich_all_sessions(
            db, sessions, visits, refresh=args.refresh_ai, verbose=True
        )

        # Overlay user edits on top of AI descriptions.
        for s in sessions:
            s["user_description"] = get_user_edit(db, s["session_key"])

        # Assign display numbers (idle may be hidden, so number only shown sessions).
        num = 1
        for s in sessions:
            if not (s["kind"] == "idle" and not args.show_idle):
                s["_display_number"] = num
                num += 1
            else:
                s["_display_number"] = None

        if args.edit is not None:
            return prompt_edit(db, sessions, args.edit)

        print_timeline(sessions, str(selected_date), show_idle=args.show_idle)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
