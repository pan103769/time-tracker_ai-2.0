"""
api/categories.py — Category and rule management and classification engine.

Handles custom categories, rule matching with precedence, manual overrides,
context-aware browser/document content disambiguation, and honest uncertainty fallbacks.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from api.migrations import now_iso


# ---------------------------------------------------------------------------
# Constants & Match Patterns
# ---------------------------------------------------------------------------

BROWSER_PROCESSES = {
    "chrome.exe", "msedge.exe", "opera.exe", "firefox.exe", "brave.exe",
    "chromium.exe", "vivaldi.exe", "browser.exe", "safari.exe"
}

BROWSER_SUFFIX_RE = re.compile(
    r"\s*-\s*(Google Chrome|Microsoft[\u200b\s]*Edge|Mozilla Firefox|Opera|Brave|Chromium|Vivaldi)\s*$",
    re.IGNORECASE,
)

PROFILE_SUFFIX_RE = re.compile(
    r"\s*-\s*(School|Work|Personal|Default Profile|Profile \d+)\s*$",
    re.IGNORECASE,
)

SITE_TO_DOMAIN: dict[str, str] = {
    "youtube": "youtube.com",
    "chess.com": "chess.com",
    "chess": "chess.com",
    "chatgpt": "chatgpt.com",
    "openai": "openai.com",
    "github": "github.com",
    "gitlab": "gitlab.com",
    "gemini": "gemini.google.com",
    "google gemini": "gemini.google.com",
    "claude": "claude.ai",
    "anthropic": "claude.ai",
    "netflix": "netflix.com",
    "spotify": "spotify.com",
    "reddit": "reddit.com",
    "twitter": "x.com",
    " / x": "x.com",
    " - x": "x.com",
    "home / x": "x.com",
    "stackoverflow": "stackoverflow.com",
    "stack overflow": "stackoverflow.com",
    "leetcode": "leetcode.com",
    "hackerrank": "hackerrank.com",
    "notion": "notion.so",
    "trello": "trello.com",
    "linear": "linear.app",
    "jira": "jira.atlassian.com",
    "figma": "figma.com",
    "twitch": "twitch.tv",
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "whatsapp": "web.whatsapp.com",
    "discord": "discord.com",
    "slack": "slack.com",
    "gmail": "mail.google.com",
    "google mail": "mail.google.com",
    "google meet": "meet.google.com",
    "zoom": "zoom.us",
    "pinterest": "pinterest.com",
    "pin on ": "pinterest.com",
    "monkeytype": "monkeytype.com",
    "wikipedia": "wikipedia.org",
    "medium": "medium.com",
    "arxiv": "arxiv.org",
    "wikipedia": "wikipedia.org",
    "coursera": "coursera.org",
    "udemy": "udemy.com",
    "dev community": "dev.to",
    "dev.to": "dev.to",
    "pinterest": "pinterest.com",
    "amazon": "amazon.com",
    "google search": "google.com",
    "time tracker ai": "timetracker.local",
}

# Technical, programming, and learning topic keywords for YouTube disambiguation
YOUTUBE_TECH_KEYWORDS = (
    "python", "javascript", "react", "rust", "c++", "golang", "java", "dsa", "leetcode",
    "fastapi", "django", "flask", "docker", "kubernetes", "sql", "database", "sqlite",
    "git", "github", "keynote", "conference", "lecture", "deep dive", "crash course",
    "open weight", "ai model", "machine learning", "neural network", "transformer",
    "data structure", "algorithms", "system design", "operating system", "software engineer",
    "tech talk", "talk", "seminar", "backend", "frontend", "full stack", "full-stack",
    "web development", "coding", "programming", "code review", "debugging", "compiler",
    "linux", "terminal", "powershell", "api development", "tutorial |", "tutorial -"
)

# Common entertainment/vlog keywords for YouTube disambiguation
YOUTUBE_ENTERTAINMENT_KEYWORDS = (
    "vlog", "gaming", "stream", "live stream", "gameplay", "valorant", "minecraft",
    "roblox", "gta", "funny", "comedy", "prank", "music", "song", "remix", "official video",
    "trailer", "teaser", "movie", "episode", "roast", "reacts", "reaction", "standup",
    "stand-up", "food", "eating", "burger", "street food", "wedding", "shaadi", "crush",
    "shorts", "unhinged", "pc gaming", "samosa", "garba", "navratri", "tour", "house tour"
)

# Coding project topic keywords for ChatGPT / AI disambiguation
AI_CODING_KEYWORDS = (
    "project", "coding", "code", "bug", "error", "function", "api", "refactor",
    "git", "python", "react", "typescript", "backend", "frontend", "time tracker",
    "time tracking", "database", "sql", "algorithm", "vibe coding", "harness",
    "full-stack", "daemon", "fastapi", "endpoint", "architecture", "component",
    "tailwind", "css", "html"
)

# Academic, science, and technical learning topics for AI disambiguation
AI_STUDY_KEYWORDS = (
    "dns", "virtualization", "operating system", "sjf", "analysis", "explanation",
    "philosophy", "history", "science", "theory", "resolution", "protocol", "physics",
    "math", "calculus", "linear algebra", "discrete math", "network", "tcp/ip"
)


# ---------------------------------------------------------------------------
# Metadata Extraction Helpers
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Extract clean domain/hostname from a URL string."""
    if not url:
        return ""
    try:
        clean = url.strip()
        if not (clean.startswith("http://") or clean.startswith("https://")):
            clean = "https://" + clean
        parsed = urlparse(clean)
        netloc = (parsed.netloc or "").lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def clean_browser_title(title: str) -> str:
    """Strip browser suffixes and operating system / profile tags from window title."""
    t = (title or "").replace("\u200b", "").replace("\ufeff", "").strip()
    # Strip browser suffix first
    t = re.sub(
        r"\s*[-—|•]\s*(?:Google\s+Chrome|Microsoft\s*Edge|Mozilla\s+Firefox|Opera(?:\s+GX)?|Brave(?:\s+Browser)?|Chromium|Vivaldi)(?:\s+beta|\s+dev)?\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Strip profile suffix
    t = re.sub(
        r"\s*[-—|•]\s*(?:Profile\s+\d+|School|Work|Personal|Default(?:\s+Profile)?|Guest)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Strip page count suffix e.g. 'and 4 more pages'
    t = re.sub(r"\s*and\s+\d+\s+more\s+page(?:s)?\s*$", "", t, flags=re.IGNORECASE).strip()
    # Strip profile suffix if it appeared before page count
    t = re.sub(
        r"\s*[-—|•]\s*(?:Profile\s+\d+|School|Work|Personal|Default(?:\s+Profile)?|Guest)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Strip tab counter notification prefix e.g. (5)
    t = re.sub(r"^\(\d+\)\s*", "", t).strip()
    return t.strip(" -—|•")


def extract_domain_and_site(app: str, title: str, url: str = "") -> dict:
    """
    Extract domain, site name, and document markers from browser metadata,
    window titles, and URLs.
    """
    clean_t = clean_browser_title(title)
    t_lower = clean_t.lower()
    app_lower = (app or "").lower().strip()
    is_browser = app_lower in BROWSER_PROCESSES or "chrome" in app_lower or "edge" in app_lower or "opera" in app_lower or "browser" in app_lower

    domain = _extract_domain(url)
    site = ""
    is_doc = bool(re.search(r"\.(pdf|epub|docx?|pptx?|xlsx?)\b", t_lower))

    # If domain not yet known and this is a browser or web document, search window title
    if not domain and (is_browser or is_doc):
        # 1. Multi-level domain in window title (e.g. "docs.python.org", "chess.com", "github.com")
        m = re.search(r"\b((?:[a-z0-9\-]+\.)+(?:com|org|io|ai|app|net|edu|gov|so|tv|me|dev|co|in))\b", t_lower)
        if m:
            domain = m.group(1)

        # 2. Known site name mapped to domain
        if not domain:
            for site_key, mapped_dom in SITE_TO_DOMAIN.items():
                if site_key in t_lower:
                    domain = mapped_dom
                    site = site_key
                    break

    return {
        "clean_title": clean_t,
        "domain": domain,
        "site": site,
        "is_browser": is_browser,
        "is_document": is_doc,
    }


# ---------------------------------------------------------------------------
# Categories & Rules CRUD
# ---------------------------------------------------------------------------

def get_all_categories(db: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Return all categories sorted by type and name."""
    rows = db.execute(
        "SELECT id, name, color, type, created_at FROM categories ORDER BY type, name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_rules(db: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Return all category rules joined with category info."""
    rows = db.execute(
        """
        SELECT r.id, r.category_id, r.match_type, r.pattern, r.priority, r.created_at,
               c.name as category_name, c.color as category_color, c.type as category_type
        FROM category_rules r
        JOIN categories c ON r.category_id = c.id
        ORDER BY r.priority DESC, r.id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def create_category(db: sqlite3.Connection, name: str, color: str, c_type: str) -> Dict[str, Any]:
    """Create a new custom category."""
    name_clean = name.strip()
    color_clean = color.strip() or "#8b5cf6"
    valid_types = {"focus", "work", "personal", "distraction"}
    c_type_clean = c_type.strip().lower() if c_type.strip().lower() in valid_types else "work"

    ts = now_iso()
    cursor = db.execute(
        "INSERT INTO categories (name, color, type, created_at) VALUES (?, ?, ?, ?)",
        (name_clean, color_clean, c_type_clean, ts),
    )
    db.commit()
    return {
        "id": cursor.lastrowid,
        "name": name_clean,
        "color": color_clean,
        "type": c_type_clean,
        "created_at": ts,
    }


def update_category(
    db: sqlite3.Connection, cat_id: int, name: str, color: str, c_type: str
) -> Optional[Dict[str, Any]]:
    """Update an existing category."""
    name_clean = name.strip()
    color_clean = color.strip()
    valid_types = {"focus", "work", "personal", "distraction"}
    c_type_clean = c_type.strip().lower() if c_type.strip().lower() in valid_types else "work"

    db.execute(
        "UPDATE categories SET name = ?, color = ?, type = ? WHERE id = ?",
        (name_clean, color_clean, c_type_clean, cat_id),
    )
    db.commit()
    row = db.execute("SELECT id, name, color, type, created_at FROM categories WHERE id = ?", (cat_id,)).fetchone()
    return dict(row) if row else None


def delete_category(db: sqlite3.Connection, cat_id: int) -> bool:
    """Delete a category and its associated rules."""
    cursor = db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    db.commit()
    return cursor.rowcount > 0


def create_rule(
    db: sqlite3.Connection, category_id: int, match_type: str, pattern: str, priority: int = 40
) -> Dict[str, Any]:
    """Create a new matching rule. Defaults to priority 40 so user rules take precedence."""
    valid_types = {"domain", "url", "app", "title_contains"}
    m_type = match_type.strip().lower() if match_type.strip().lower() in valid_types else "app"
    pat = pattern.strip().lower()
    ts = now_iso()

    cursor = db.execute(
        """
        INSERT INTO category_rules (category_id, match_type, pattern, priority, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (category_id, m_type, pat, priority, ts),
    )
    db.commit()

    row = db.execute(
        """
        SELECT r.id, r.category_id, r.match_type, r.pattern, r.priority, r.created_at,
               c.name as category_name, c.color as category_color, c.type as category_type
        FROM category_rules r
        JOIN categories c ON r.category_id = c.id
        WHERE r.id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def delete_rule(db: sqlite3.Connection, rule_id: int) -> bool:
    """Delete a rule."""
    cursor = db.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    db.commit()
    return cursor.rowcount > 0


def set_session_category_override(db: sqlite3.Connection, session_key: str, category_id: int) -> bool:
    """Persist a manual user override for a specific session."""
    ts = now_iso()
    db.execute(
        """
        INSERT OR REPLACE INTO session_categories (session_key, category_id, updated_at)
        VALUES (?, ?, ?)
        """,
        (session_key, category_id, ts),
    )
    db.commit()
    return True


def remove_session_category_override(db: sqlite3.Connection, session_key: str) -> bool:
    """Remove manual user override for a session."""
    cursor = db.execute("DELETE FROM session_categories WHERE session_key = ?", (session_key,))
    db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Core Classification Engine
# ---------------------------------------------------------------------------

def match_category(
    db: Optional[sqlite3.Connection],
    app: str,
    title: str,
    url: str = "",
    session_key: Optional[str] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
    categories_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    manual_overrides: Optional[Dict[str, int]] = None,
    task: Optional[str] = None,
    obs_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Evaluate category for an activity with strict, verifiable precedence:
    1. Explicit manual session override (session_categories)
    2. Explicitly configured user classification rules (high-priority user rules)
    3. Explicit user-assigned task or activity (observations.task or active task)
    4. Website domain & browser URL (with context-aware content disambiguation)
    5. Browser window title / document pattern
    6. Application identity & executable
    7. Existing deterministic classification rules
    8. Honest uncertain fallback ('Other / Needs Review' with inspectable uncertainty)
    """
    if categories_by_id is None and db is not None:
        cat_rows = db.execute("SELECT id, name, color, type FROM categories").fetchall()
        categories_by_id = {r["id"]: dict(r) for r in cat_rows}
    elif categories_by_id is None:
        categories_by_id = {
            1: {"id": 1, "name": "Coding & Development", "color": "#8b5cf6", "type": "focus"},
            2: {"id": 2, "name": "Research & Learning", "color": "#06b6d4", "type": "focus"},
            3: {"id": 3, "name": "Communication & Meetings", "color": "#3b82f6", "type": "work"},
            4: {"id": 4, "name": "Planning & Management", "color": "#10b981", "type": "work"},
            5: {"id": 5, "name": "Entertainment & Media", "color": "#ef4444", "type": "distraction"},
            6: {"id": 6, "name": "Social & Browsing", "color": "#f59e0b", "type": "distraction"},
            7: {"id": 7, "name": "Utilities & System", "color": "#6b7280", "type": "work"},
            8: {"id": 8, "name": "Other / Needs Review", "color": "#9ca3af", "type": "uncategorized"},
        }

    # Identify uncertain fallback category (honest fallback, never personal)
    uncategorized = None
    for c in categories_by_id.values():
        if "uncategorized" in c["name"].lower() or "other" in c["name"].lower() or "review" in c["name"].lower():
            uncategorized = dict(c)
            break
    if not uncategorized and categories_by_id:
        uncategorized = dict(list(categories_by_id.values())[0])
    elif not uncategorized:
        uncategorized = {"id": 8, "name": "Other / Needs Review", "color": "#9ca3af", "type": "uncategorized"}

    if uncategorized.get("type") == "personal":
        uncategorized["type"] = "uncategorized"

    # 1. Manual session override (check session_key, app_obsId, or obsId)
    target_cat_id = None
    if manual_overrides is not None:
        if session_key and session_key in manual_overrides:
            target_cat_id = manual_overrides[session_key]
        elif obs_ids:
            for oid in obs_ids:
                if f"{app}_{oid}" in manual_overrides:
                    target_cat_id = manual_overrides[f"{app}_{oid}"]
                    break
                if f"obs_{oid}" in manual_overrides:
                    target_cat_id = manual_overrides[f"obs_{oid}"]
                    break
    elif db is not None:
        keys_to_check = []
        if session_key:
            keys_to_check.append(session_key)
        if obs_ids:
            for oid in obs_ids:
                keys_to_check.append(f"{app}_{oid}")
                keys_to_check.append(f"obs_{oid}")

        if keys_to_check:
            placeholders = ",".join("?" for _ in keys_to_check)
            row = db.execute(
                f"SELECT category_id FROM session_categories WHERE session_key IN ({placeholders}) LIMIT 1",
                tuple(keys_to_check),
            ).fetchone()
            if row:
                target_cat_id = row["category_id"]

    if target_cat_id and target_cat_id in categories_by_id:
        matched = dict(categories_by_id[target_cat_id])
        matched["source"] = "manual"
        matched["confidence"] = 1.0
        matched["is_uncertain"] = False
        return matched

    # Load rules if not provided
    if rules is None and db is not None:
        rules = get_all_rules(db)
    elif rules is None:
        rules = []

    # Extract metadata and domains
    meta = extract_domain_and_site(app, title, url)
    domain_clean = meta["domain"].lower().strip()
    clean_title = meta["clean_title"]
    title_lower = clean_title.lower()
    app_lower = (app or "").strip().lower()
    url_clean = (url or "").strip().lower()
    is_doc = meta["is_document"]
    is_browser = meta["is_browser"]

    # 2. User Explicit High-Priority Rules (priority >= 40)
    for r in rules:
        if r.get("priority", 10) >= 40:
            m_type = r["match_type"]
            pat = r["pattern"].lower()
            if m_type == "url" and pat and pat in url_clean:
                cid = r["category_id"]
                if cid in categories_by_id:
                    res = dict(categories_by_id[cid])
                    res["source"] = "rule"
                    res["domain"] = domain_clean
                    res["matched_rule"] = f"url:{r['pattern']}"
                    res["confidence"] = 0.95
                    res["is_uncertain"] = False
                    return res
            elif m_type == "domain" and pat and domain_clean:
                if pat == domain_clean or domain_clean.endswith("." + pat):
                    cid = r["category_id"]
                    if cid in categories_by_id:
                        res = dict(categories_by_id[cid])
                        res["source"] = "rule"
                        res["domain"] = domain_clean
                        res["matched_rule"] = f"domain:{r['pattern']}"
                        res["confidence"] = 0.95
                        res["is_uncertain"] = False
                        return res
            elif m_type == "title_contains" and pat and pat in title_lower:
                cid = r["category_id"]
                if cid in categories_by_id:
                    res = dict(categories_by_id[cid])
                    res["source"] = "rule"
                    res["domain"] = domain_clean
                    res["matched_rule"] = f"title:{r['pattern']}"
                    res["confidence"] = 0.95
                    res["is_uncertain"] = False
                    return res
            elif m_type == "app" and pat:
                if pat == app_lower or (pat.replace(".exe", "") == app_lower.replace(".exe", "")):
                    cid = r["category_id"]
                    if cid in categories_by_id:
                        res = dict(categories_by_id[cid])
                        res["source"] = "rule"
                        res["domain"] = domain_clean
                        res["matched_rule"] = f"app:{r['pattern']}"
                        res["confidence"] = 0.95
                        res["is_uncertain"] = False
                        return res

    # 3. Explicit User-Assigned Task or Activity
    if task:
        task_clean = task.strip().lower()

        # Check if the current context is an obvious distraction site (e.g. YouTube entertainment, Netflix, Gaming)
        is_clear_distraction = (
            domain_clean in ("netflix.com", "chess.com", "lichess.org", "pinterest.com", "x.com", "twitter.com", "reddit.com", "instagram.com", "tiktok.com", "twitch.tv")
            or (
                (domain_clean == "youtube.com" or "youtube" in title_lower)
                and not any(kw in title_lower for kw in YOUTUBE_TECH_KEYWORDS)
            )
            or any(s in title_lower for s in ("netflix", "prime video", "disney+", "hulu", "twitch.tv"))
        )

        # Direct category name match
        for cid, c in categories_by_id.items():
            if c["name"].lower() == task_clean:
                # Do not let a work/focus task override clear distraction leakage
                if is_clear_distraction and c.get("type") in ("focus", "work"):
                    break
                res = dict(c)
                res["source"] = "task"
                res["domain"] = domain_clean
                res["confidence"] = 1.0
                res["is_uncertain"] = False
                return res

        # Semantic task intent matching (only applies if not a clear distraction)
        if not is_clear_distraction:
            if any(w in task_clean for w in ("study", "learn", "dsa", "course", "read", "lecture", "research", "exam")):
                for c in categories_by_id.values():
                    if "research" in c["name"].lower() or "learning" in c["name"].lower():
                        res = dict(c)
                        res["source"] = "task"
                        res["domain"] = domain_clean
                        res["confidence"] = 0.95
                        res["is_uncertain"] = False
                        return res

            if any(w in task_clean for w in ("code", "dev", "bug", "project", "work", "refactor", "api", "review")):
                for c in categories_by_id.values():
                    if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                        res = dict(c)
                        res["source"] = "task"
                        res["domain"] = domain_clean
                        res["confidence"] = 0.95
                        res["is_uncertain"] = False
                        return res

    # Idle fallback
    if app_lower == "idle":
        for c in categories_by_id.values():
            if "system" in c["name"].lower() or "utilities" in c["name"].lower():
                res = dict(c)
                res["source"] = "system"
                res["confidence"] = 1.0
                res["is_uncertain"] = False
                return res
        return dict(uncategorized)

    # 4. Website Domain & URL with Context-Aware Content Disambiguation
    # YouTube (Educational vs Entertainment)
    if domain_clean == "youtube.com" or "youtube" in title_lower:
        if any(kw in title_lower for kw in YOUTUBE_TECH_KEYWORDS):
            for c in categories_by_id.values():
                if "research" in c["name"].lower() or "learning" in c["name"].lower():
                    res = dict(c)
                    res["source"] = "content"
                    res["domain"] = domain_clean or "youtube.com"
                    res["matched_rule"] = "youtube.com (technical / educational)"
                    res["confidence"] = 0.88
                    res["is_uncertain"] = False
                    return res
        elif any(kw in title_lower for kw in YOUTUBE_ENTERTAINMENT_KEYWORDS):
            for c in categories_by_id.values():
                if "entertainment" in c["name"].lower():
                    res = dict(c)
                    res["source"] = "content"
                    res["domain"] = domain_clean or "youtube.com"
                    res["matched_rule"] = "youtube.com (entertainment / media)"
                    res["confidence"] = 0.90
                    res["is_uncertain"] = False
                    return res
        # Standard fallback for youtube
        for c in categories_by_id.values():
            if "entertainment" in c["name"].lower():
                res = dict(c)
                res["source"] = "rule"
                res["domain"] = domain_clean or "youtube.com"
                res["matched_rule"] = "domain:youtube.com"
                res["confidence"] = 0.85
                res["is_uncertain"] = False
                return res

    # Netflix (Streaming Entertainment)
    if domain_clean == "netflix.com" or "netflix" in title_lower:
        for c in categories_by_id.values():
            if "entertainment" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = "netflix.com"
                res["matched_rule"] = "site:netflix"
                res["confidence"] = 0.95
                res["is_uncertain"] = False
                return res

    # Chess.com & Lichess (Gaming / Entertainment)
    if domain_clean in ("chess.com", "lichess.org") or "chess.com" in title_lower or ("chess" in title_lower and any(w in title_lower for w in ("play", "tactics", "stockfish", "game"))):
        for c in categories_by_id.values():
            if "entertainment" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = domain_clean or "chess.com"
                res["matched_rule"] = "site:chess"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Social Media: Pinterest, X / Twitter, Reddit, Instagram, Threads
    if domain_clean in ("pinterest.com", "x.com", "twitter.com", "reddit.com", "instagram.com") or any(
        s in title_lower for s in ("pinterest", "pin on ", "home / x", " / x", "reddit", "twitter")
    ):
        for c in categories_by_id.values():
            if "social" in c["name"].lower() or "browsing" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = domain_clean or "social"
                res["matched_rule"] = "site:social_media"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Localhost development
    if domain_clean in ("localhost", "127.0.0.1") or any(loc in title_lower for loc in ("localhost", "127.0.0.1", ":5173", ":8000", ":3000")):
        for c in categories_by_id.values():
            if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                res = dict(c)
                res["source"] = "content"
                res["domain"] = "localhost"
                res["matched_rule"] = "content:localhost_development"
                res["confidence"] = 0.95
                res["is_uncertain"] = False
                return res

    # AI platforms and conversation topics
    is_ai_platform = domain_clean in ("chatgpt.com", "gemini.google.com", "claude.ai") or any(k in title_lower for k in ("chatgpt", "gemini", "claude"))
    if is_ai_platform:
        if any(kw in title_lower for kw in AI_CODING_KEYWORDS):
            for c in categories_by_id.values():
                if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                    res = dict(c)
                    res["source"] = "content"
                    res["domain"] = domain_clean or "chatgpt.com"
                    res["matched_rule"] = f"{domain_clean or 'ai'} (coding)"
                    res["confidence"] = 0.88
                    res["is_uncertain"] = False
                    return res
        if any(kw in title_lower for kw in ("planning", "schedule", "roadmap", "sprint", "milestone", "architecture")):
            for c in categories_by_id.values():
                if "plan" in c["name"].lower() or "manage" in c["name"].lower():
                    res = dict(c)
                    res["source"] = "content"
                    res["domain"] = domain_clean or "chatgpt.com"
                    res["matched_rule"] = f"{domain_clean or 'ai'} (planning)"
                    res["confidence"] = 0.88
                    res["is_uncertain"] = False
                    return res
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "learning" in c["name"].lower():
                res = dict(c)
                res["source"] = "rule"
                res["domain"] = domain_clean or "chatgpt.com"
                res["matched_rule"] = f"domain:{domain_clean or 'ai'}"
                res["confidence"] = 0.85
                res["is_uncertain"] = False
                return res

    # Document & PDF reading (Note: browser profile names like '- School -' are NOT educational content)
    if is_doc:
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "learning" in c["name"].lower():
                res = dict(c)
                res["source"] = "document"
                res["domain"] = domain_clean or "document"
                res["matched_rule"] = "document:pdf_reading"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Technical documentation and reference (docs.*, documentation)
    if "documentation" in title_lower or (domain_clean and domain_clean.startswith("docs.")):
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "learning" in c["name"].lower():
                res = dict(c)
                res["source"] = "rule"
                res["domain"] = domain_clean
                res["matched_rule"] = "domain:documentation"
                res["confidence"] = 0.88
                res["is_uncertain"] = False
                return res

    # Technical learning, Computer Science & Academic study topics
    if any(kw in title_lower for kw in AI_STUDY_KEYWORDS) or any(w in title_lower for w in ("book summary", "philosophy", "niti", "wisdom", "history", "reading", "lecture", "tutorial", "exam", "course")):
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "learning" in c["name"].lower():
                res = dict(c)
                res["source"] = "content"
                res["domain"] = domain_clean
                res["matched_rule"] = "content:academic_study"
                res["confidence"] = 0.88
                res["is_uncertain"] = False
                return res

    # Technical coding, software projects, and developer repository patterns
    if any(kw in title_lower for kw in AI_CODING_KEYWORDS) or ("/" in title_lower and any(w in title_lower for w in ("time_tracker", "github", "repo", "master", "branch", "commit", "pull"))):
        for c in categories_by_id.values():
            if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                res = dict(c)
                res["source"] = "content"
                res["domain"] = domain_clean
                res["matched_rule"] = "content:software_development"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Pinterest & Social Media
    if title_lower.startswith("pin on ") or "pinterest" in title_lower:
        for c in categories_by_id.values():
            if "social" in c["name"].lower() or "browsing" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = domain_clean or "pinterest.com"
                res["matched_rule"] = "site:pinterest"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Google Search Queries
    if " - google search" in title_lower or title_lower.endswith("google search"):
        if any(w in title_lower for w in ("code", "api", "python", "bug", "vibe", "app", "dev", "harness", "fastapi", "react", "typescript", "git")):
            for c in categories_by_id.values():
                if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                    res = dict(c)
                    res["source"] = "search"
                    res["domain"] = "google.com"
                    res["matched_rule"] = "search:technical_query"
                    res["confidence"] = 0.88
                    res["is_uncertain"] = False
                    return res
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "learning" in c["name"].lower():
                res = dict(c)
                res["source"] = "search"
                res["domain"] = "google.com"
                res["matched_rule"] = "search:research_query"
                res["confidence"] = 0.85
                res["is_uncertain"] = False
                return res

    # Typing skill practice / training
    if "monkeytype" in title_lower:
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "utilities" in c["name"].lower():
                res = dict(c)
                res["source"] = "app"
                res["domain"] = "monkeytype.com"
                res["matched_rule"] = "site:monkeytype"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Chess and online gaming
    if domain_clean in ("chess.com", "lichess.org") or "chess" in title_lower:
        for c in categories_by_id.values():
            if "gaming" in c["name"].lower() or "entertainment" in c["name"].lower():
                res = dict(c)
                res["source"] = "rule"
                res["domain"] = domain_clean or "chess.com"
                res["matched_rule"] = f"domain:{domain_clean or 'chess.com'}"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Communication & Messaging domains
    if domain_clean in ("web.whatsapp.com", "whatsapp.com", "discord.com", "slack.com") or "whatsapp" in title_lower:
        for c in categories_by_id.values():
            if "communication" in c["name"].lower() or "meetings" in c["name"].lower():
                res = dict(c)
                res["source"] = "rule"
                res["domain"] = domain_clean or "web.whatsapp.com"
                res["matched_rule"] = f"domain:{domain_clean or 'whatsapp'}"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Local Time Tracker AI Dashboard (only when actually browser/dashboard, not VS Code)
    if (domain_clean == "timetracker.local" or "time tracker ai — dashboard" in title_lower) and app_lower not in ("code.exe", "cursor.exe", "devenv.exe", "pycharm64.exe"):
        for c in categories_by_id.values():
            if "planning" in c["name"].lower() or "utilities" in c["name"].lower():
                res = dict(c)
                res["source"] = "app_dashboard"
                res["domain"] = domain_clean
                res["matched_rule"] = "Time Tracker AI Dashboard"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # Priority passes:
    # Pass A: URL matches (highest specificity)
    if url_clean:
        for r in rules:
            if r["match_type"] == "url" and r["pattern"] and r["pattern"] in url_clean:
                cid = r["category_id"]
                if cid in categories_by_id:
                    res = dict(categories_by_id[cid])
                    res["source"] = "rule"
                    res["domain"] = domain_clean
                    res["matched_rule"] = f"url:{r['pattern']}"
                    res["confidence"] = 0.90
                    res["is_uncertain"] = False
                    return res

    # Pass B: Domain matches
    if domain_clean:
        for r in rules:
            if r["match_type"] == "domain" and r["pattern"]:
                pat = r["pattern"].lower()
                if pat == domain_clean or domain_clean.endswith("." + pat):
                    cid = r["category_id"]
                    if cid in categories_by_id:
                        res = dict(categories_by_id[cid])
                        res["source"] = "rule"
                        res["domain"] = domain_clean
                        res["matched_rule"] = f"domain:{r['pattern']}"
                        res["confidence"] = 0.88
                        res["is_uncertain"] = False
                        return res

    # 5. Window title / Pattern matching (Pass C)
    for r in rules:
        if r["match_type"] == "title_contains" and r["pattern"] and r["pattern"] in title_lower:
            cid = r["category_id"]
            if cid in categories_by_id:
                res = dict(categories_by_id[cid])
                res["source"] = "rule"
                res["domain"] = domain_clean
                res["matched_rule"] = f"title:{r['pattern']}"
                res["confidence"] = 0.85
                res["is_uncertain"] = False
                return res

    # Contextual title heuristics
    if "api code review" in title_lower or "fastapi" in title_lower or "code review" in title_lower or "vibe coding" in title_lower or "time tracking project" in title_lower:
        for c in categories_by_id.values():
            if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                res = dict(c)
                res["source"] = "title"
                res["domain"] = domain_clean
                res["matched_rule"] = "title:coding_context"
                res["confidence"] = 0.92
                res["is_uncertain"] = False
                return res

    if "offline brainstorming" in title_lower or "architecture diagrams" in title_lower:
        for c in categories_by_id.values():
            if "planning" in c["name"].lower():
                res = dict(c)
                res["source"] = "title"
                res["domain"] = domain_clean
                res["matched_rule"] = "title:planning_context"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    if "dev community" in title_lower or "hacktoberfest" in title_lower:
        for c in categories_by_id.values():
            if "coding" in c["name"].lower() or "research" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = domain_clean or "dev.to"
                res["matched_rule"] = "site:dev_community"
                res["confidence"] = 0.88
                res["is_uncertain"] = False
                return res

    if "documentation" in title_lower or "rize documentation" in title_lower or "python documentation" in title_lower:
        for c in categories_by_id.values():
            if "research" in c["name"].lower() or "learning" in c["name"].lower():
                res = dict(c)
                res["source"] = "title"
                res["domain"] = domain_clean
                res["matched_rule"] = "title:documentation"
                res["confidence"] = 0.88
                res["is_uncertain"] = False
                return res

    if "pinterest" in title_lower:
        for c in categories_by_id.values():
            if "social" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = domain_clean or "pinterest.com"
                res["matched_rule"] = "site:pinterest"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    if "let'sporn" in title_lower or "usersporn" in title_lower or "porn" in title_lower:
        for c in categories_by_id.values():
            if "entertainment" in c["name"].lower():
                res = dict(c)
                res["source"] = "site"
                res["domain"] = domain_clean
                res["matched_rule"] = "site:entertainment"
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    # 6. Pass D: App matches
    for r in rules:
        if r["match_type"] == "app" and r["pattern"]:
            pat = r["pattern"].lower()
            if pat == app_lower or (pat.replace(".exe", "") == app_lower.replace(".exe", "")):
                cid = r["category_id"]
                if cid in categories_by_id:
                    res = dict(categories_by_id[cid])
                    res["source"] = "rule"
                    res["domain"] = domain_clean
                    res["matched_rule"] = f"app:{r['pattern']}"
                    res["confidence"] = 0.85
                    res["is_uncertain"] = False
                    return res

    # Specific desktop application classes
    if app_lower in ("code.exe", "cursor.exe", "devenv.exe", "pycharm64.exe", "pycharm.exe", "sublime_text.exe"):
        for c in categories_by_id.values():
            if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                res = dict(c)
                res["source"] = "app"
                res["domain"] = domain_clean
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    if app_lower in ("fpsaimtrainer-win64-shipping.exe", "steam.exe", "steamwebhelper.exe"):
        for c in categories_by_id.values():
            if "gaming" in c["name"].lower() or "entertainment" in c["name"].lower():
                res = dict(c)
                res["source"] = "app"
                res["domain"] = domain_clean
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    if app_lower in ("slack.exe", "teams.exe", "discord.exe", "whatsapp.exe", "whatsapp.root.exe", "outlook.exe", "telegram.exe"):
        for c in categories_by_id.values():
            if "communication" in c["name"].lower() or "meetings" in c["name"].lower():
                res = dict(c)
                res["source"] = "app"
                res["domain"] = domain_clean
                res["confidence"] = 0.90
                res["is_uncertain"] = False
                return res

    if app_lower in ("snippingtool.exe", "explorer.exe", "cmd.exe", "powershell.exe", "windowsterminal.exe", "wt.exe", "taskmgr.exe", "applicationframehost.exe", "shellhost.exe", "shellexperiencehost.exe"):
        for c in categories_by_id.values():
            if "utilities" in c["name"].lower() or "system" in c["name"].lower():
                res = dict(c)
                res["source"] = "app"
                res["domain"] = domain_clean
                res["confidence"] = 0.85
                res["is_uncertain"] = False
                return res

    if app_lower in ("pythonw.exe", "python.exe"):
        for c in categories_by_id.values():
            if "coding" in c["name"].lower() or "develop" in c["name"].lower():
                res = dict(c)
                res["source"] = "app"
                res["domain"] = domain_clean
                res["confidence"] = 0.80
                res["is_uncertain"] = False
                return res

    # 8. Honest Uncertain Fallback
    res = dict(uncategorized)
    res["source"] = "uncertain"
    res["domain"] = domain_clean
    res["confidence"] = 0.30
    res["is_uncertain"] = True
    if res.get("type") in ("personal", "work", None):
        res["type"] = "uncategorized"
    return res
