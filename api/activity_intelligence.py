"""
api/activity_intelligence.py
-----------------------------
Browser Intelligence & Task-Level Activity Attribution Engine.

Identifies actual websites, tools, documents, projects, and specific tasks
from active window titles, URLs, browser visits, and application metadata.

Rules of Attribution:
1. User explicit edits / manual overrides are strictly respected.
2. User explicit classification rules have high priority.
3. Actual window context (URL, domain, document, page title) is parsed deterministically.
4. Active planned tasks (Time Blocks) provide context without inventing fake work.
5. Honest fallback ("Browser Activity — Needs Review") when evidence is insufficient.
6. Zero double counting: Parent browser rows are presentation summaries only.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit


# ---------------------------------------------------------------------------
# Constants & Browser Identifiers
# ---------------------------------------------------------------------------

BROWSER_PROCESSES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "opera.exe": "Opera",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave Browser",
    "browser.exe": "Browser",
}

BROWSER_SUFFIX_RE = re.compile(
    r"\s*[-—|•]\s*(?:Google\s+Chrome|Microsoft\s+Edge|Opera(?:\s+GX)?|Mozilla\s+Firefox|Brave(?:\s+Browser)?|Chromium)(?:\s+beta|\s+dev)?\s*$",
    re.IGNORECASE,
)

PROFILE_SUFFIX_RE = re.compile(
    r"\s*[-—|•]\s*(?:Profile\s+\d+|School|Work|Personal|Default|Guest)(?:\s+and\s+\d+\s+more\s+page(?:s)?)?\s*$",
    re.IGNORECASE,
)

PAGE_COUNT_SUFFIX_RE = re.compile(
    r"\s*and\s+\d+\s+more\s+page(?:s)?\s*$",
    re.IGNORECASE,
)

GENERIC_TITLES = {
    "",
    "new tab",
    "new tab and 1 more page",
    "untitled",
    "untitled window",
    "not found",
    "page not found",
    "working...",
    "redirecting",
    "sign in to your account",
    "login",
    "log in",
    "blank page",
    "about:blank",
}

APP_FRIENDLY_NAMES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "opera.exe": "Opera",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "code.exe": "VS Code",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "sublime_text.exe": "Sublime Text",
    "cursor.exe": "Cursor",
    "spotify.exe": "Spotify",
    "explorer.exe": "File Explorer",
    "powershell.exe": "PowerShell",
    "cmd.exe": "Command Prompt",
    "windowsterminal.exe": "Windows Terminal",
    "snippingtool.exe": "Snipping Tool",
    "notion.exe": "Notion",
    "whatsapp.root.exe": "WhatsApp",
    "whatsapp.exe": "WhatsApp",
    "telegram.exe": "Telegram",
    "discord.exe": "Discord",
    "python.exe": "Python",
    "pythonw.exe": "Python Background",
    "idle": "Idle",
}


# ---------------------------------------------------------------------------
# Cleaning & Title Extraction Helpers
# ---------------------------------------------------------------------------

def clean_browser_window_title(title: str) -> str:
    """Strip browser and profile suffixes to extract foreground page/tab title."""
    if not title:
        return ""
    t = title.replace("\u200b", "").replace("\ufeff", "").strip()
    # Strip browser suffix first
    t = re.sub(
        r"\s*[-—|•]\s*(?:Google\s+Chrome|Microsoft\s*Edge|Opera(?:\s+GX)?|Mozilla\s+Firefox|Brave(?:\s+Browser)?|Chromium)(?:\s+beta|\s+dev)?\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Strip profile suffix (e.g. '- School', '- Profile 1')
    t = re.sub(
        r"\s*[-—|•]\s*(?:Profile\s+\d+|School|Work|Personal|Default(?:\s+Profile)?|Guest)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Strip page count suffix (e.g. 'and 4 more pages')
    t = re.sub(r"\s*and\s+\d+\s+more\s+page(?:s)?\s*$", "", t, flags=re.IGNORECASE).strip()
    # Strip profile suffix again in case it appeared before page count
    t = re.sub(
        r"\s*[-—|•]\s*(?:Profile\s+\d+|School|Work|Personal|Default(?:\s+Profile)?|Guest)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Strip leading tab notification count e.g. (5)
    t = re.sub(r"^\(\d+\)\s*", "", t).strip()
    return t.strip(" -—|•")


def extract_domain_from_url(url: str) -> str:
    """Extract clean domain (e.g. 'youtube.com', 'chatgpt.com') from a URL."""
    if not url:
        return ""
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        netloc = urlsplit(u).netloc.lower()
        # Remove port if present
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        # Remove www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def clean_project_name(name: str) -> str:
    """Clean IDE project/folder name."""
    if not name:
        return ""
    # Strip special icons
    return re.sub(r"[\s🌟⭐✨]+$", "", name).strip()


# ---------------------------------------------------------------------------
# Specific Activity Attribution
# ---------------------------------------------------------------------------

def derive_specific_activity(
    app: str,
    title: str,
    url: str = "",
    task: Optional[str] = None,
    category_name: Optional[str] = None,
    user_description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Derives specific activity name, site/tool, document, and context label
    following strict precedence rules without inventing fake facts.
    """
    app_raw = (app or "Unknown").strip()
    app_lower = app_raw.lower()
    app_clean = APP_FRIENDLY_NAMES.get(app_lower, app_raw.replace(".exe", ""))
    is_browser = (
        app_lower in BROWSER_PROCESSES
        or "chrome" in app_lower
        or "edge" in app_lower
        or "opera" in app_lower
        or "firefox" in app_lower
        or "brave" in app_lower
        or "browser" in app_lower
    )

    clean_t = clean_browser_window_title(title) if is_browser else (title or "").strip()
    t_lower = clean_t.lower()
    domain = extract_domain_from_url(url)
    clean_cat = category_name or "Uncategorized"

    # Precedence 1: User explicitly edited session description
    if user_description and user_description.strip():
        user_desc = user_description.strip()
        return {
            "activity_name": user_desc,
            "specific_task": user_desc,
            "site_name": domain or app_clean,
            "document_name": None,
            "app_display_name": app_clean,
            "context_label": f"{app_clean} · {domain or app_clean} · {clean_cat}",
            "is_browser": is_browser,
            "is_uncertain": False,
        }

    # Precedence 2: Browser Activity Intelligence
    if is_browser:
        # Check for PDF or document opened in browser
        doc_m = re.search(r"([a-zA-Z0-9_\-\.\s\(\)]+\.(?:pdf|epub|docx?|pptx?|xlsx?))\b", clean_t, re.IGNORECASE)
        if doc_m:
            doc_file = doc_m.group(1).strip()
            # Clean trailing download markers e.g. _Worldfreebooks.com_ (1)
            doc_name_clean = re.sub(r"\s*_\w+\.\w+_\s*", "", doc_file)
            return {
                "activity_name": f"Reading — {doc_name_clean}",
                "specific_task": f"Reading Document ({doc_name_clean})",
                "site_name": "Document Viewer",
                "document_name": doc_file,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · {doc_name_clean} · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 1. YouTube
        if "youtube.com" in domain or "youtube" in t_lower:
            cand = re.sub(r"(?i)\s*[-—|•]\s*youtube\b", "", clean_t).strip(" -—|•")
            cand = re.sub(r"[\s🌟⭐✨]+$", "", cand).strip()
            if not cand or cand.lower() in GENERIC_TITLES or cand.lower() == "youtube":
                cand = "Video Streaming"
            else:
                # Truncate overly long YouTube video titles neatly
                if len(cand) > 60:
                    cand = cand[:57].rstrip() + "…"

            # Context task
            is_edu = any(w in t_lower for w in ("tutorial", "course", "lecture", "learn", "dsa", "coding", "python", "algorithm", "guide", "class", "study"))
            task_label = "Educational Video" if is_edu else "Entertainment / Media"
            return {
                "activity_name": f"YouTube — {cand}",
                "specific_task": task_label,
                "site_name": "YouTube",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · YouTube · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 2. Netflix
        if "netflix.com" in domain or "netflix" in t_lower:
            cand = re.sub(r"(?i)\s*[-—|•]\s*netflix\b", "", clean_t).strip(" -—|•")
            if not cand or cand.lower() in GENERIC_TITLES or cand.lower() == "netflix":
                cand = "Streaming Entertainment"
            return {
                "activity_name": f"Netflix — {cand}",
                "specific_task": f"Streaming Video & Movies ({cand})",
                "site_name": "Netflix",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Netflix · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 3. ChatGPT
        if "chatgpt.com" in domain or "openai.com" in domain or "chatgpt" in t_lower or "openai" in t_lower:
            cand = re.sub(r"(?i)\bchatgpt\b", "", clean_t).strip(" -—|•\t\r\n")
            cand = re.sub(r"[\s🌟⭐✨]+$", "", cand).strip()
            if not cand or cand.lower() in GENERIC_TITLES or cand.lower() == "new chat":
                cand = task if task else "AI Conversation"

            is_code = any(w in t_lower for w in ("project", "code", "coding", "bug", "error", "api", "python", "react", "fastapi", "git", "debug"))
            is_res = any(w in t_lower for w in ("dns", "theory", "research", "concept", "history", "explain", "learn", "study"))
            task_type = "Coding & Debugging" if is_code else ("Technical Research" if is_res else "AI Conversation")

            return {
                "activity_name": f"ChatGPT — {cand}",
                "specific_task": f"ChatGPT ({task_type}: {cand})",
                "site_name": "ChatGPT",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · ChatGPT · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 4. Google Gemini
        if "gemini.google.com" in domain or "google gemini" in t_lower or "gemini" in t_lower:
            cand = re.sub(r"(?i)\b(?:google\s+)?gemini\b", "", clean_t).strip(" -—|•\t\r\n")
            cand = re.sub(r"[\s🌟⭐✨]+$", "", cand).strip()
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = task if task else "Technical Assistance"
            return {
                "activity_name": f"Google Gemini — {cand}",
                "specific_task": f"Gemini ({cand})",
                "site_name": "Google Gemini",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Google Gemini · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 5. Claude
        if "claude.ai" in domain or "claude" in t_lower:
            cand = re.sub(r"(?i)\bclaude\b", "", clean_t).strip(" -—|•\t\r\n")
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = "AI Assistance"
            return {
                "activity_name": f"Claude — {cand}",
                "specific_task": f"Claude ({cand})",
                "site_name": "Claude",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Claude · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 6. GitHub / GitLab
        if "github.com" in domain or "github" in t_lower or re.search(r"\b[\w\-]+/[\w\-]+", t_lower) or "gitlab.com" in domain:
            cand = re.sub(r"(?i)\s*[-—|•]\s*github\b", "", clean_t).strip(" -—|•")
            if not cand or cand.lower() in GENERIC_TITLES or cand.lower() == "github":
                cand = "Repository Exploration"
            return {
                "activity_name": f"GitHub — {cand}",
                "specific_task": "Repository Development",
                "site_name": "GitHub",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · GitHub · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 7. Localhost / Local Web Apps
        if any(loc in domain or loc in t_lower for loc in ("localhost", "127.0.0.1", ":5173", ":8000", ":3000")):
            cand = re.sub(r"(?i)\s*[-—|•]\s*dashboard\b", "", clean_t).strip(" -—|•")
            if not cand:
                cand = "Time Tracker AI — Dashboard"
            return {
                "activity_name": f"Localhost — {cand}",
                "specific_task": f"Local Development ({cand})",
                "site_name": "Localhost",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Localhost · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 8. Google Search
        if "google.com" in domain and ("search" in url or "google search" in t_lower) or "google search" in t_lower:
            cand = re.sub(r"(?i)\s*[-—|•]\s*google\s+search\b", "", clean_t).strip(" -—|•")
            cand = re.sub(r"[\s🌟⭐✨]+$", "", cand).strip()
            if not cand or cand.lower() in GENERIC_TITLES or cand.lower() == "google":
                cand = "Technical Research"
            return {
                "activity_name": f"Google Search — {cand}",
                "specific_task": f"Search: {cand}",
                "site_name": "Google Search",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Google Search · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 9. Chess.com / Lichess
        if "chess.com" in domain or "chess.com" in t_lower or ("chess" in t_lower and any(w in t_lower for w in ("play", "tactics", "stockfish", "game"))):
            cand = re.sub(r"(?i)\s*[-—|•]\s*chess\.com\b", "", clean_t).strip(" -—|•")
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = "Online Chess"
            return {
                "activity_name": f"Chess.com — {cand}",
                "specific_task": "Chess Gameplay / Analysis",
                "site_name": "Chess.com",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Chess.com · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 10. Pinterest
        if "pinterest.com" in domain or "pinterest" in t_lower or "pin on " in t_lower:
            cand = re.sub(r"(?i)\s*[-—|•]\s*pinterest\b", "", clean_t).strip(" -—|•")
            cand = re.sub(r"^\(\d+\)\s*", "", cand).strip()
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = "Visual Discovery"
            return {
                "activity_name": f"Pinterest — {cand}",
                "specific_task": f"Social Browsing & Discovery ({cand})",
                "site_name": "Pinterest",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Pinterest · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 11. X (Twitter)
        if "x.com" in domain or "twitter.com" in domain or "home / x" in t_lower or " / x" in t_lower or " - x" in t_lower or "twitter" in t_lower:
            return {
                "activity_name": "X (Twitter) — Home Feed",
                "specific_task": "Social Media Feed & Browsing",
                "site_name": "X (Twitter)",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · X (Twitter) · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 12. LinkedIn
        if "linkedin.com" in domain or "linkedin" in t_lower:
            cand = re.sub(r"(?i)\s*[-—|•]\s*linkedin\b", "", clean_t).strip(" -—|•")
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = "Professional Feed"
            return {
                "activity_name": f"LinkedIn — {cand}",
                "specific_task": f"Professional Networking ({cand})",
                "site_name": "LinkedIn",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · LinkedIn · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 13. Moodle / Academic Portal
        if "cet.iitp.ac.in" in domain or "moodle" in t_lower or "iitp.ac.in" in domain:
            cand = re.sub(r"(?i)\s*[-—|•]\s*moodle\b", "", clean_t).strip(" -—|•")
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = "IIT Patna CET Moodle"
            return {
                "activity_name": f"Moodle — {cand}",
                "specific_task": "Course Work & Academic Portal",
                "site_name": "Moodle",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Moodle · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 14. Wikipedia
        if "wikipedia.org" in domain or "wikipedia" in t_lower:
            cand = re.sub(r"(?i)\s*[-—|•]\s*wikipedia\b", "", clean_t).strip(" -—|•")
            if not cand or cand.lower() in GENERIC_TITLES:
                cand = "Reference Articles"
            return {
                "activity_name": f"Wikipedia — {cand}",
                "specific_task": f"Reading: {cand}",
                "site_name": "Wikipedia",
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Wikipedia · {clean_cat}",
                "is_browser": True,
                "is_uncertain": False,
            }

        # 9. Generic Domain or Clean Page Title
        # Extract potential domain from title if not in URL
        if not domain:
            dom_m = re.search(r"\b((?:[a-z0-9\-]+\.)+(?:com|org|io|ai|app|net|edu|gov|so|tv|me|dev|co|in))\b", t_lower)
            if dom_m:
                domain = dom_m.group(1)

        # Honest check if title is empty or generic
        if t_lower in GENERIC_TITLES:
            if domain:
                site_disp = domain.capitalize()
                return {
                    "activity_name": f"{site_disp} — Web Browsing",
                    "specific_task": f"Browsing {domain}",
                    "site_name": domain,
                    "document_name": None,
                    "app_display_name": app_clean,
                    "context_label": f"{app_clean} · {domain} · {clean_cat}",
                    "is_browser": True,
                    "is_uncertain": False,
                }
            return {
                "activity_name": "Browser Activity — Needs Review",
                "specific_task": "Unclassified Web Activity",
                "site_name": app_clean,
                "document_name": None,
                "app_display_name": app_clean,
                "context_label": f"{app_clean} · Needs Review · {clean_cat}",
                "is_browser": True,
                "is_uncertain": True,
            }

        # If meaningful title exists
        site_name = domain.capitalize() if domain else "Web"
        cand_title = clean_t
        if len(cand_title) > 55:
            cand_title = cand_title[:52].rstrip() + "…"

        return {
            "activity_name": f"{site_name} — {cand_title}" if domain else cand_title,
            "specific_task": clean_t,
            "site_name": domain or app_clean,
            "document_name": None,
            "app_display_name": app_clean,
            "context_label": f"{app_clean} · {domain or 'Web'} · {clean_cat}",
            "is_browser": True,
            "is_uncertain": False,
        }

    # Precedence 3: Desktop Applications
    # 1. VS Code / Code Editors
    if app_lower in ("code.exe", "cursor.exe", "devenv.exe", "pycharm64.exe", "sublime_text.exe"):
        # e.g. "server.py - time tracker ai 2 - Visual Studio Code"
        parts = [p.strip() for p in clean_t.split(" - ") if p.strip()]
        # Remove editor name
        parts = [p for p in parts if not any(ed in p.lower() for ed in ("visual studio code", "cursor", "sublime text", "pycharm"))]
        file_part = parts[0] if parts else ""
        proj_part = parts[1] if len(parts) > 1 else ""
        if not proj_part and file_part and not file_part.endswith((".py", ".ts", ".tsx", ".js", ".html", ".css", ".json")):
            proj_part = file_part
            file_part = ""

        proj_clean = clean_project_name(proj_part) or (task if task else "Workspace")
        activity_title = f"{app_clean} — {proj_clean}"
        if file_part:
            activity_title += f" ({file_part})"

        return {
            "activity_name": activity_title,
            "specific_task": f"Development: {proj_clean}",
            "site_name": app_clean,
            "document_name": file_part or None,
            "app_display_name": app_clean,
            "context_label": f"{app_clean} · {proj_clean} · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 2. Spotify
    if app_lower == "spotify.exe":
        cand = clean_t.replace("Spotify.exe", "").replace("Spotify", "").strip(" -—|•")
        track_name = cand if cand and cand.lower() not in GENERIC_TITLES else "Music Playback"
        return {
            "activity_name": f"Spotify — {track_name}",
            "specific_task": "Music & Audio Streaming",
            "site_name": "Spotify",
            "document_name": None,
            "app_display_name": "Spotify",
            "context_label": f"Spotify · Music Streaming · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 3. File Explorer
    if app_lower == "explorer.exe":
        folder = clean_t.strip(" -—|•") or "Directory Navigation"
        return {
            "activity_name": f"File Explorer — {folder}",
            "specific_task": f"Browsing Files ({folder})",
            "site_name": "File Explorer",
            "document_name": None,
            "app_display_name": "File Explorer",
            "context_label": f"File Explorer · {folder} · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 4. Notion
    if app_lower == "notion.exe":
        page = clean_t.replace("Notion", "").strip(" -—|•") or "Workspace & Notes"
        return {
            "activity_name": f"Notion — {page}",
            "specific_task": f"Planning: {page}",
            "site_name": "Notion",
            "document_name": None,
            "app_display_name": "Notion",
            "context_label": f"Notion · {page} · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 5. Terminal / PowerShell / CLI
    if app_lower in ("powershell.exe", "cmd.exe", "windowsterminal.exe"):
        term_title = clean_t or "Command Line"
        return {
            "activity_name": f"Terminal — {term_title}",
            "specific_task": "Command Line Operations",
            "site_name": app_clean,
            "document_name": None,
            "app_display_name": app_clean,
            "context_label": f"{app_clean} · Command Line · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 6. Communication (WhatsApp, Discord, Telegram)
    if "whatsapp" in app_lower or "discord" in app_lower or "telegram" in app_lower:
        comm_title = clean_t or "Chat & Messaging"
        return {
            "activity_name": f"{app_clean} — {comm_title}",
            "specific_task": "Communication & Messaging",
            "site_name": app_clean,
            "document_name": None,
            "app_display_name": app_clean,
            "context_label": f"{app_clean} · Communication · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 7. Snipping Tool
    if "snippingtool" in app_lower:
        return {
            "activity_name": "Snipping Tool — Screen Capture",
            "specific_task": "Screen Capture & Annotation",
            "site_name": "Snipping Tool",
            "document_name": None,
            "app_display_name": "Snipping Tool",
            "context_label": f"Snipping Tool · System Tool · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 8. Idle
    if app_lower == "idle" or (title and title.lower() == "idle"):
        return {
            "activity_name": "Idle — Away from Keyboard",
            "specific_task": "Inactive / Away Break",
            "site_name": "System",
            "document_name": None,
            "app_display_name": "Idle",
            "context_label": "System · Idle · Inactive",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 9. Fallback Desktop Activity
    if clean_t and clean_t.lower() not in GENERIC_TITLES:
        short_title = clean_t[:50] + ("…" if len(clean_t) > 50 else "")
        return {
            "activity_name": f"{app_clean} — {short_title}",
            "specific_task": clean_t,
            "site_name": app_clean,
            "document_name": None,
            "app_display_name": app_clean,
            "context_label": f"{app_clean} · {clean_cat}",
            "is_browser": False,
            "is_uncertain": False,
        }

    # 10. Honest Unknown Fallback
    return {
        "activity_name": f"{app_clean} — Needs Review",
        "specific_task": "Unclassified Application Activity",
        "site_name": app_clean,
        "document_name": None,
        "app_display_name": app_clean,
        "context_label": f"{app_clean} · Needs Review · {clean_cat}",
        "is_browser": False,
        "is_uncertain": True,
    }


# ---------------------------------------------------------------------------
# Hierarchical Website & Activity Usage Aggregation (Zero Double-Counting)
# ---------------------------------------------------------------------------

def aggregate_hierarchical_usage(
    sessions: List[Dict[str, Any]],
    total_active_seconds: float,
) -> List[Dict[str, Any]]:
    """
    Builds website-level and activity-first time attribution hierarchy:
    - Level 1: Primary rows represent (Website / Tool, Category) pairs
      (e.g. YouTube - Entertainment & Media, YouTube - Research & Learning, Netflix, ChatGPT, VS Code).
    - Level 2: Specific activity details (individual video titles, documents, conversation tasks).
    - CRITICAL ACCOUNTING RULES:
      Parent row duration = sum(child.duration).
      Every interval contributes at most once.
      Sum of Level 1 durations == total_active_seconds. Zero double counting.
    """
    total_sec = max(1.0, total_active_seconds)

    # Level 1 Bucket: (site_name, category_name)
    primary_groups: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for s in sessions:
        if s.get("kind") == "idle":
            continue

        act = s.get("activity_meta") or derive_specific_activity(
            app=s.get("app", ""),
            title=s.get("title", ""),
            url=s.get("url", ""),
            task=s.get("task"),
            category_name=s.get("category_name"),
            user_description=s.get("user_description"),
        )

        site_name = act.get("site_name") or "Other Activity"
        cat_name = s.get("category_name") or "Other / Needs Review"
        cat_color = s.get("category_color") or "#9ca3af"
        cat_type = s.get("category_type") or "uncategorized"
        dur = s.get("duration_seconds", 0.0)

        app_raw = s.get("app", "")
        app_lower = app_raw.lower()
        is_browser = act.get("is_browser", False)
        browser_app = APP_FRIENDLY_NAMES.get(app_lower, app_raw.replace(".exe", "")) if is_browser else None

        group_key = (site_name, cat_name)
        if group_key not in primary_groups:
            primary_groups[group_key] = {
                "site_name": site_name,
                "category": cat_name,
                "category_color": cat_color,
                "category_type": cat_type,
                "duration_seconds": 0.0,
                "switches": 0,
                "is_browser": is_browser,
                "browser_name": browser_app,
                "child_sessions": {},
            }

        g = primary_groups[group_key]
        g["duration_seconds"] += dur
        g["switches"] += 1
        if is_browser and not g["browser_name"]:
            g["browser_name"] = browser_app

        # Level 2 Child: Group by specific activity / title
        act_title = act.get("activity_name") or s.get("title") or site_name
        child_key = f"{act_title}::{act.get('specific_task', '')}"
        if child_key not in g["child_sessions"]:
            g["child_sessions"][child_key] = {
                "id": f"{site_name}_{len(g['child_sessions'])}",
                "site_name": site_name,
                "activity_name": act_title,
                "specific_task": act.get("specific_task") or act_title,
                "category": cat_name,
                "category_color": cat_color,
                "category_type": cat_type,
                "duration_seconds": 0.0,
                "switches": 0,
                "is_uncertain": act.get("is_uncertain", False),
                "is_browser": is_browser,
                "browser_name": browser_app,
                "app": site_name,
            }
        g["child_sessions"][child_key]["duration_seconds"] += dur
        g["child_sessions"][child_key]["switches"] += 1

    result_rows = []
    for (site_name, cat_name), g in primary_groups.items():
        dur = g["duration_seconds"]
        pct = round((dur / total_sec) * 100, 1)

        # Sort children descending by duration
        children = []
        for c in sorted(g["child_sessions"].values(), key=lambda x: x["duration_seconds"], reverse=True):
            c_pct = round((c["duration_seconds"] / total_sec) * 100, 1)
            c_hours = int(c["duration_seconds"] // 3600)
            c_mins = int((c["duration_seconds"] % 3600) // 60)
            c_secs = int(c["duration_seconds"] % 60)
            c_lbl = f"{c_hours}h {c_mins}m" if c_hours > 0 else (f"{c_mins}m {c_secs}s" if c_mins > 0 else f"{c_secs}s")
            c["duration_label"] = c_lbl
            c["pct"] = c_pct
            children.append(c)

        # Format parent duration label
        hours = int(dur // 3600)
        mins = int((dur % 3600) // 60)
        secs = int(dur % 60)
        dur_lbl = f"{hours}h {mins}m" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")

        # Determine summary task context
        if len(children) == 1:
            task_context = children[0]["specific_task"]
        else:
            if site_name == "YouTube" and "entertainment" in cat_name.lower():
                task_context = f"Gaming streams, shorts & video playback ({len(children)} items)"
            elif site_name == "YouTube" and ("research" in cat_name.lower() or "learning" in cat_name.lower()):
                task_context = f"Technical talks, tutorials & lectures ({len(children)} lectures)"
            elif site_name == "ChatGPT" and "coding" in cat_name.lower():
                task_context = f"Development & debugging conversations ({len(children)} topics)"
            elif site_name == "ChatGPT" and "research" in cat_name.lower():
                task_context = f"Technical research & conceptual exploration ({len(children)} topics)"
            elif site_name == "Document Viewer":
                task_context = f"Reading PDF & study documents ({len(children)} documents)"
            elif site_name == "Chess.com":
                task_context = f"Online chess gameplay & tactics analysis ({len(children)} matches)"
            elif site_name == "Pinterest":
                task_context = f"Visual discovery & moodboard browsing ({len(children)} pins)"
            elif "Needs Review" in site_name:
                task_context = f"Unclassified browser activity ({len(children)} tabs, needs review)"
            else:
                task_context = f"Activity across {len(children)} distinct tasks/pages"

        all_uncertain = all(c["is_uncertain"] for c in children) if children else False

        result_rows.append({
            "id": f"site_{site_name}_{cat_name}".replace(" ", "_").replace("/", "_").replace("&", "_").lower(),
            "app": site_name,
            "activity_name": f"{site_name} — {cat_name}" if len(children) > 1 else children[0]["activity_name"],
            "specific_task": task_context,
            "site_name": site_name,
            "category": cat_name,
            "category_color": g["category_color"],
            "category_type": g["category_type"],
            "duration_seconds": dur,
            "duration_label": dur_lbl,
            "pct": pct,
            "switches": g["switches"],
            "is_browser": g["is_browser"],
            "browser_name": g["browser_name"],
            "is_uncertain": all_uncertain,
            "children": children,
        })

    # Sort descending by duration
    return sorted(result_rows, key=lambda x: x["duration_seconds"], reverse=True)


def aggregate_browser_containers(
    sessions: List[Dict[str, Any]],
    total_active_seconds: float,
) -> List[Dict[str, Any]]:
    """
    Computes optional explanatory browser diagnostics containers:
    - Neutral summary label 'Mixed Browser Activity' (does not steal or inherit child categories).
    - Breaks down each browser into its constituent website activities.
    - Preserves desktop application containers (VS Code, Spotify, etc.).
    - Strict zero double counting.
    """
    total_sec = max(1.0, total_active_seconds)

    # Bucket sessions by process/app
    app_buckets: Dict[str, List[Dict[str, Any]]] = {}
    for s in sessions:
        if s.get("kind") == "idle":
            continue
        app_name = s.get("app", "Unknown")
        app_buckets.setdefault(app_name, []).append(s)

    containers = []
    for app_name, app_sessions in app_buckets.items():
        app_dur = sum(s.get("duration_seconds", 0.0) for s in app_sessions)
        app_switches = len(app_sessions)
        app_pct = round((app_dur / total_sec) * 100, 1)

        app_lower = app_name.lower()
        is_browser = (
            app_lower in BROWSER_PROCESSES
            or "chrome" in app_lower
            or "edge" in app_lower
            or "opera" in app_lower
            or "firefox" in app_lower
            or "brave" in app_lower
        )
        app_friendly = APP_FRIENDLY_NAMES.get(app_lower, app_name.replace(".exe", ""))

        # Format duration label
        hours = int(app_dur // 3600)
        mins = int((app_dur % 3600) // 60)
        secs = int(app_dur % 60)
        dur_lbl = f"{hours}h {mins}m" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")

        if is_browser:
            # Group browser child sessions into website-level items
            site_groups = aggregate_hierarchical_usage(app_sessions, total_active_seconds)
            containers.append({
                "id": f"browser_{app_name}",
                "app": app_friendly,
                "activity_name": f"{app_friendly} (Mixed Browser Activity)",
                "specific_task": f"Multi-tab browsing across {len(site_groups)} distinct website activities",
                "category": "Mixed Browser Activity",
                "category_color": "#16D5E2",
                "category_type": "work",
                "duration_seconds": app_dur,
                "duration_label": dur_lbl,
                "pct": app_pct,
                "switches": app_switches,
                "is_browser": True,
                "browser_name": app_friendly,
                "is_uncertain": False,
                "children": site_groups,
            })
        else:
            first_s = app_sessions[0]
            act = first_s.get("activity_meta") or derive_specific_activity(
                app=app_name,
                title=first_s.get("title", ""),
                url="",
                task=first_s.get("task"),
                category_name=first_s.get("category_name"),
            )
            cat_name = first_s.get("category_name") or "Uncategorized"
            cat_color = first_s.get("category_color") or "#8065FF"
            cat_type = first_s.get("category_type") or "work"

            containers.append({
                "id": f"app_{app_name}",
                "app": app_friendly,
                "activity_name": act["activity_name"],
                "specific_task": act["specific_task"],
                "category": cat_name,
                "category_color": cat_color,
                "category_type": cat_type,
                "duration_seconds": app_dur,
                "duration_label": dur_lbl,
                "pct": app_pct,
                "switches": app_switches,
                "is_browser": False,
                "browser_name": None,
                "is_uncertain": act["is_uncertain"],
                "children": [],
            })

    return sorted(containers, key=lambda x: x["duration_seconds"], reverse=True)
