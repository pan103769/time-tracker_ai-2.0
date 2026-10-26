"""
api/clustering.py - Deterministic Semantic Activity Clustering and Visual Debounce Engine.

Provides presentation-layer clustering for timeline views:
1. Excursion Debounce: If user switches away from a dominant app and returns to it,
   and the intervening excursion lasts STRICTLY LESS than 60 seconds, it is visually
   absorbed into the dominant continuous block, recording an interruption.
   Excursions >= 60 seconds are NOT absorbed.
2. Semantic Activity Clustering: Adjacent rapid switches (< 180s each) are grouped into
   semantically coherent clusters based on category, specific task context, titles,
   and application domain.
3. Semantic Boundaries: When activity materially transitions (e.g. from coding to entertainment,
   or from research to social browsing), a cluster boundary is enforced. Unrelated
   entertainment (YouTube shorts, gaming clips) is NEVER merged into Coding & Debugging.
4. Strict Duration & Data Preservation: Underlying observations in tracker.db are NEVER
   merged, modified, or overwritten. Original timestamps and non-overlapping durations
   remain 100% intact. Sum of child durations reconciles exactly with cluster duration.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ChildSegment:
    app: str
    title: str
    start: str
    end: str
    duration_seconds: int
    category_name: Optional[str] = None
    category_color: Optional[str] = None
    category_type: Optional[str] = None
    is_interruption: bool = False


@dataclass
class TimelineCluster:
    cluster_id: str
    label: str
    cluster_type: str  # 'single', 'absorbed', 'mixed', 'category'
    dominant_app: str
    dominant_category: Optional[str]
    category_color: str
    category_type: str
    start: str
    end: str
    duration_seconds: int
    interruption_count: int
    child_segments: List[ChildSegment] = field(default_factory=list)
    app_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    is_idle: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def parse_iso(iso_str: str) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        return datetime.fromisoformat(iso_str)
    except Exception:
        try:
            return datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None


def calculate_app_breakdown(segments: List[ChildSegment]) -> List[Dict[str, Any]]:
    totals: Dict[str, int] = {}
    for s in segments:
        app_name = s.app or "Unknown"
        totals[app_name] = totals.get(app_name, 0) + max(0, s.duration_seconds)

    total_sec = sum(totals.values()) or 1
    items = []
    for app, sec in sorted(totals.items(), key=lambda x: x[1], reverse=True):
        items.append({
            "app": app,
            "seconds": sec,
            "pct": round((sec / total_sec) * 100, 1),
            "label": f"{sec // 60}m {sec % 60}s" if sec >= 60 else f"{sec}s",
        })
    return items


def get_session_semantic_domain(session: Dict[str, Any] | ChildSegment) -> str:
    """
    Categorizes an observation or child segment into its core semantic activity domain:
    'coding', 'entertainment', 'research', 'communication', 'planning', 'social', 'system_overlay', 'other'
    """
    if isinstance(session, dict):
        app = (session.get("app") or "").strip().lower()
        title = (session.get("title") or "").strip().lower()
        cat_name = (session.get("category_name") or "").strip().lower()
        cat_type = (session.get("category_type") or "").strip().lower()
        url = (session.get("url") or "").strip().lower()
    else:
        app = (session.app or "").strip().lower()
        title = (session.title or "").strip().lower()
        cat_name = (session.category_name or "").strip().lower()
        cat_type = (session.category_type or "").strip().lower()
        url = ""

    # 1. System Overlays & Windows desktop shell utilities
    system_apps = {
        "explorer.exe",
        "shellexperiencehost.exe",
        "searchapp.exe",
        "taskmgr.exe",
        "systemsettings.exe",
        "lockapp.exe",
        "applicationframehost.exe",
    }
    if app in system_apps or "notification center" in title or "quick settings" in title:
        return "system_overlay"
    if "utilities & system" in cat_name or cat_name == "system":
        return "system_overlay"

    # 2. Entertainment, Media & Gaming
    media_apps = {"spotify.exe", "vlc.exe", "steam.exe", "netflix.exe"}
    gaming_keywords = (
        "valorant",
        "cyberpunk",
        "csgo",
        "minecraft",
        "standoff",
        "roblox",
        "chess.com",
        "steam",
        "gameplay",
        "fps",
        "clutch",
        "ace",
        "twitch",
        "gaming",
    )
    entertainment_media_keywords = (
        "youtube",
        "netflix",
        "spotify",
        "twitch",
        "vimeo",
        "prime video",
        "disney",
        "hotstar",
        "crunchyroll",
        "#shorts",
        "#gaming",
        "trailer",
        "episode",
        "music",
        "lofi",
        "video",
    )

    if app in media_apps or any(gk in app for gk in ("valorant", "steam", "epicgames")):
        return "entertainment"
    if "entertainment" in cat_name or "gaming" in cat_name or (cat_type == "distraction" and not ("social" in cat_name or "browse" in cat_name)):
        # Check if actually social browsing
        if any(sk in title or sk in url or sk in app for sk in ("twitter", "x.com", "reddit", "instagram", "facebook", "linkedin")):
            return "social"
        return "entertainment"
    if any(emk in title for emk in entertainment_media_keywords) or any(emk in url for emk in entertainment_media_keywords):
        return "entertainment"
    if any(gk in title for gk in gaming_keywords) or any(gk in url for gk in gaming_keywords):
        return "entertainment"

    # 3. Coding & Software Development
    coding_apps = {
        "code.exe",
        "cursor.exe",
        "pycharm64.exe",
        "pycharm.exe",
        "idea64.exe",
        "idea.exe",
        "devenv.exe",
        "sublime_text.exe",
        "nvim.exe",
    }
    terminal_apps = {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "windowsterminal.exe",
        "bash.exe",
        "git-bash.exe",
    }
    if app in coding_apps or "cursor" in app or "pycharm" in app or "visual studio" in app:
        return "coding"
    if "code" in cat_name or "develop" in cat_name or "programming" in cat_name:
        return "coding"
    if app in terminal_apps or "terminal" in app or "powershell" in app or app in ("python.exe", "node.exe", "cargo.exe"):
        return "coding"
    if any(dk in title or dk in url for dk in ("github.com", "gitlab.com", "localhost", "127.0.0.1", "fastapi", "vue", "react", "vite")):
        return "coding"

    # 4. Technical Research & Documentation
    research_keywords = (
        "docs",
        "documentation",
        "stackoverflow",
        "github",
        "api reference",
        "api",
        "mdn",
        "tutorial",
        "guide",
        "manual",
        "arxiv",
        "paper",
        "cheat sheet",
        "pypi",
        "npm",
    )
    if "research" in cat_name or "learn" in cat_name or "study" in cat_name or "education" in cat_name:
        return "research"
    if any(rk in title for rk in research_keywords) or any(rk in url for rk in research_keywords):
        return "research"

    # 5. Team Communication & Meetings
    comm_apps = {
        "slack.exe",
        "discord.exe",
        "teams.exe",
        "whatsapp.exe",
        "whatsapp.root.exe",
        "telegram.exe",
        "zoom.exe",
        "outlook.exe",
        "thunderbird.exe",
    }
    if app in comm_apps or any(ca in app for ca in ("slack", "discord", "teams", "whatsapp", "telegram")):
        return "communication"
    if "communi" in cat_name or "meeting" in cat_name or "chat" in cat_name or "messaging" in cat_name:
        return "communication"

    # 6. Planning & Organization
    plan_apps = {"notion.exe", "obsidian.exe", "excel.exe", "winword.exe", "onenote.exe"}
    if app in plan_apps or any(pa in app for pa in ("notion", "obsidian", "trello", "jira")):
        return "planning"
    if "plan" in cat_name or "organi" in cat_name or "manage" in cat_name:
        return "planning"

    # 7. Social & Web Browsing
    if "social" in cat_name or any(sk in title or sk in url for sk in ("twitter", "x.com", "reddit", "instagram", "facebook", "linkedin")):
        return "social"

    return "other"


def get_domain_purpose(dom: str) -> str:
    """
    Returns 'work', 'distraction', or 'neutral'.
    """
    if dom in ("coding", "research", "communication", "planning", "work"):
        return "work"
    if dom in ("entertainment", "social", "distraction"):
        return "distraction"
    return "neutral"


def are_domains_compatible(dom1: str, dom2: str) -> bool:
    """
    Determines whether two activity domains can naturally coalesce into a unified cluster.
    - Same domain is always compatible.
    - System overlays (explorer, notification center) are neutral bridges.
    - Productive work domains (coding, research, communication, planning) are compatible for work task switching.
    - Distraction domains (entertainment, social) coalesce within media browsing.
    - Work and Distraction are strictly INCOMPATIBLE and enforce a hard semantic boundary.
    """
    if dom1 == dom2:
        return True
    if dom1 == "system_overlay" or dom2 == "system_overlay":
        return True
    p1 = get_domain_purpose(dom1)
    p2 = get_domain_purpose(dom2)
    if p1 != p2 and p1 != "neutral" and p2 != "neutral":
        return False
    if p1 == "work" and p2 == "work":
        return True
    if p1 == "distraction" and p2 == "distraction":
        return True
    return True


def is_browser_app(app: str) -> bool:
    app_lower = (app or "").lower()
    return any(b in app_lower for b in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"))


def infer_cluster_metadata(segments: List[ChildSegment]) -> tuple[str, str, str, str]:
    """
    Dynamically name clusters from recorded signals (task, category, titles, exe, chronological sequence).
    Uses strict non-overlapping duration weighting across child segments.
    Returns (label, dominant_category, category_color, category_type).
    """
    if not segments:
        return ("Mixed Activity", "Task Switching", "#8065FF", "work")

    num_switches = len(segments)
    total_dur = sum(max(0, s.duration_seconds) for s in segments) or 1

    # Accumulate durations by category and by semantic domain
    cat_durations: Dict[str, int] = {}
    cat_colors: Dict[str, str] = {}
    cat_types: Dict[str, str] = {}
    dom_durations: Dict[str, int] = {}

    for s in segments:
        cat = s.category_name or "Other / Needs Review"
        dur = max(0, s.duration_seconds)
        cat_durations[cat] = cat_durations.get(cat, 0) + dur
        if s.category_color:
            cat_colors[cat] = s.category_color
        if s.category_type:
            cat_types[cat] = s.category_type

        dom = get_session_semantic_domain(s)
        dom_durations[dom] = dom_durations.get(dom, 0) + dur

    sorted_cats = sorted(cat_durations.items(), key=lambda x: x[1], reverse=True)
    dominant_cat, dominant_cat_dur = sorted_cats[0]
    dominant_cat_pct = dominant_cat_dur / total_dur

    sorted_doms = sorted(dom_durations.items(), key=lambda x: x[1], reverse=True)
    dominant_dom, dominant_dom_dur = sorted_doms[0]

    # If top domain is neutral system overlay, look at second domain
    if dominant_dom == "system_overlay" and len(sorted_doms) > 1:
        dominant_dom, dominant_dom_dur = sorted_doms[1]

    all_titles = [s.title for s in segments if s.title]
    coding_apps = {"code.exe", "cursor.exe", "pycharm64.exe", "pycharm.exe", "idea64.exe", "idea.exe", "devenv.exe", "sublime_text.exe", "nvim.exe"}
    terminal_apps = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "bash.exe", "git-bash.exe"}

    # If rapid switches span 3 or more unrelated domains (e.g. Dev + Chat + General Browser), treat as Mixed Activity
    dev_count = sum(1 for s in segments if get_session_semantic_domain(s) == "coding")
    comm_count = sum(1 for s in segments if get_session_semantic_domain(s) == "communication")
    media_count = sum(1 for s in segments if get_session_semantic_domain(s) == "entertainment")
    browser_other_count = sum(1 for s in segments if is_browser_app(s.app) and get_session_semantic_domain(s) not in ("coding", "research", "entertainment"))
    distinct_domains = sum(1 for cnt in (dev_count, comm_count, media_count, browser_other_count) if cnt > 0)
    if distinct_domains >= 3:
        return (f"Mixed Activity ({num_switches} switches)", "Task Switching", "#8065FF", "work")

    # -------------------------------------------------------------------------
    # Case 1: Dominant Domain is ENTERTAINMENT (or dominant_cat is Entertainment & Media)
    # -------------------------------------------------------------------------
    if dominant_dom == "entertainment" or "entertainment" in dominant_cat.lower() or "gaming" in dominant_cat.lower():
        dyn_cat = "Entertainment & Media"
        dyn_color = cat_colors.get(dominant_cat) or "#FA5275"
        dyn_type = "distraction"

        gaming_kw = ("valorant", "gaming", "game", "standoff", "cyberpunk", "chess", "steam", "fps", "clutch", "ace", "bgmi", "r6", "fortnite")
        has_gaming = any(any(gk in t.lower() for gk in gaming_kw) for t in all_titles)
        has_shorts = any("#shorts" in t.lower() or "shorts" in t.lower() for t in all_titles)
        has_music = any(mk in t.lower() for t in all_titles for mk in ("music", "lofi", "spotify", "soundtrack", "song"))

        if has_gaming and has_shorts:
            label = f"Entertainment — YouTube Gaming Shorts ({num_switches} switches)"
        elif has_gaming:
            label = f"Gaming & Entertainment ({num_switches} switches)"
        elif any("youtube" in s.title.lower() or "video" in s.title.lower() or "movie" in s.title.lower() or s.app.lower() == "vlc.exe" for s in segments if s.title):
            label = f"Video & Media Watching ({num_switches} switches)"
        elif has_music:
            label = f"Music & Audio Listening ({num_switches} switches)"
        else:
            label = f"Video & Media Watching ({num_switches} switches)"

        return (label, dyn_cat, dyn_color, dyn_type)

    # -------------------------------------------------------------------------
    # Case 2: Dominant Domain is CODING (or dominant_cat is Coding & Development)
    # -------------------------------------------------------------------------
    if dominant_dom == "coding" or "code" in dominant_cat.lower() or "develop" in dominant_cat.lower():
        dyn_cat = "Coding & Development"
        dyn_color = cat_colors.get(dominant_cat) or "#35D68A"
        dyn_type = "focus"

        coding_titles = [s.title.lower() for s in segments if (s.app.lower() in coding_apps or s.app.lower() in terminal_apps or s.app.lower() in ("python.exe", "node.exe"))]
        is_debug = any(any(kw in t for kw in ("test", "pytest", "debug", "run", "build", "pdb", "unittest", "npm run", "cargo test")) for t in coding_titles)
        has_terminal = any(s.app.lower() in terminal_apps for s in segments)

        project_name = None
        for s in segments:
            if s.app.lower() in coding_apps and s.title:
                m = re.search(r"-\s*([^-]+?)\s*-\s*Visual Studio", s.title, re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip()
                    if candidate and candidate.lower() not in ("visual studio code", "visual studio"):
                        project_name = candidate
                        break

        if project_name:
            if is_debug or has_terminal:
                label = f"Coding & Debugging — {project_name}"
            else:
                label = f"Project Development — {project_name}"
        elif is_debug or has_terminal:
            label = f"Coding & Debugging ({num_switches} switches)"
        else:
            label = f"Software Development ({num_switches} switches)"

        return (label, dyn_cat, dyn_color, dyn_type)

    # -------------------------------------------------------------------------
    # Case 3: Dominant Domain is RESEARCH (or dominant_cat is Research & Learning)
    # -------------------------------------------------------------------------
    if dominant_dom == "research" or "research" in dominant_cat.lower() or "learn" in dominant_cat.lower():
        dyn_cat = "Research & Learning"
        dyn_color = cat_colors.get(dominant_cat) or "#38BDF8"
        dyn_type = "focus"

        subject = None
        for s in segments:
            t_lower = s.title.lower()
            if "documentation" in t_lower or "docs" in t_lower or "stackoverflow" in t_lower:
                clean_t = s.title.split(" - ")[0].split(" | ")[0].strip()
                if clean_t and len(clean_t) <= 40:
                    subject = clean_t
                    break

        if subject:
            label = f"Technical Research & Documentation — {subject}"
        else:
            label = f"Technical Research & Documentation ({num_switches} switches)"

        return (label, dyn_cat, dyn_color, dyn_type)

    # -------------------------------------------------------------------------
    # Case 4: Dominant Domain is COMMUNICATION (or dominant_cat is Communication & Meetings)
    # -------------------------------------------------------------------------
    if dominant_dom == "communication" or "communi" in dominant_cat.lower() or "meet" in dominant_cat.lower():
        dyn_cat = "Communication & Meetings"
        dyn_color = cat_colors.get(dominant_cat) or "#818CF8"
        dyn_type = "work"
        label = f"Team Communication & Messaging ({num_switches} switches)"
        return (label, dyn_cat, dyn_color, dyn_type)

    # -------------------------------------------------------------------------
    # Case 5: Dominant Domain is PLANNING (or dominant_cat is Planning & Organization)
    # -------------------------------------------------------------------------
    if dominant_dom == "planning" or "plan" in dominant_cat.lower() or "organi" in dominant_cat.lower():
        dyn_cat = "Planning & Organization"
        dyn_color = cat_colors.get(dominant_cat) or "#F59E0B"
        dyn_type = "work"
        label = f"Planning & Documentation ({num_switches} switches)"
        return (label, dyn_cat, dyn_color, dyn_type)

    # -------------------------------------------------------------------------
    # Case 6: Dominant Domain is SOCIAL (or dominant_cat is Social & Browsing)
    # -------------------------------------------------------------------------
    if dominant_dom == "social" or "social" in dominant_cat.lower():
        dyn_cat = "Social & Browsing"
        dyn_color = cat_colors.get(dominant_cat) or "#EC4899"
        dyn_type = "distraction"
        label = f"Social & Web Browsing ({num_switches} switches)"
        return (label, dyn_cat, dyn_color, dyn_type)

    # -------------------------------------------------------------------------
    # Case 7: Truly Mixed Activity / Task Switching (No dominant domain >= 50%)
    # -------------------------------------------------------------------------
    if dominant_cat_pct >= 0.50 and dominant_cat not in ("Other / Needs Review", "Unknown", "Other"):
        return (
            f"Mixed Activity — {dominant_cat} ({num_switches} switches)",
            dominant_cat,
            cat_colors.get(dominant_cat, "#8065FF"),
            cat_types.get(dominant_cat, "work"),
        )

    return (f"Mixed Activity ({num_switches} switches)", "Task Switching", "#8065FF", "work")


def cluster_timeline_sessions(
    sessions: List[Dict[str, Any]],
    debounce_threshold_seconds: int = 60,
    mixed_threshold_seconds: int = 180,
    group_by_category: bool = False,
) -> List[TimelineCluster]:
    """
    Deterministically transforms a sequence of raw canonical sessions into presentation clusters.

    Rules:
    - Never modifies input sessions or database records.
    - Idle sessions (kind == 'idle') or gaps >= 30s never absorb or get absorbed.
    - Excursion < debounce_threshold_seconds returning to same dominant app & context is absorbed.
    - Excursion >= debounce_threshold_seconds is NOT absorbed.
    - Rapid switches (< mixed_threshold_seconds) coalesce into intelligent activity clusters.
    - Semantic boundaries split clusters when the activity context materially changes (e.g. coding to entertainment).
    - Entertainment (YouTube, gaming) is NEVER merged into Coding & Debugging clusters.
    """
    if not sessions:
        return []

    # Sort deterministically by start time
    valid_sessions = [s for s in sessions if s.get("start") and s.get("end")]
    if not valid_sessions:
        return []

    clusters: List[TimelineCluster] = []
    i = 0
    n = len(valid_sessions)

    while i < n:
        curr = valid_sessions[i]
        curr_app = curr.get("app") or "Unknown"
        curr_kind = curr.get("kind", "active")
        curr_cat_name = curr.get("category_name") or "Other"
        curr_cat_color = curr.get("category_color") or "#8065FF"
        curr_cat_type = curr.get("category_type") or "work"
        curr_duration = int(curr.get("duration_seconds", 0))

        # Check if idle
        if curr_kind == "idle":
            seg = ChildSegment(
                app=curr_app,
                title=curr.get("title", "Idle"),
                start=curr["start"],
                end=curr["end"],
                duration_seconds=curr_duration,
                category_name="Idle",
                category_color="#5A6679",
                category_type="break",
                is_interruption=False,
            )
            cluster = TimelineCluster(
                cluster_id=f"idle_{i}",
                label="Idle / Away",
                cluster_type="single",
                dominant_app="Idle",
                dominant_category="Idle",
                category_color="#5A6679",
                category_type="break",
                start=curr["start"],
                end=curr["end"],
                duration_seconds=curr_duration,
                interruption_count=0,
                child_segments=[seg],
                app_breakdown=[{"app": "Idle", "seconds": curr_duration, "pct": 100.0, "label": f"{curr_duration}s"}],
                is_idle=True,
            )
            clusters.append(cluster)
            i += 1
            continue

        # Check Excursion Debounce (Rule 1):
        # A -> B -> A where B < debounce_threshold_seconds (strictly < 60s)
        # Returns to same app AND compatible context, active kind, no large gaps (< 10s).
        absorbed = False
        if i + 2 < n:
            mid = valid_sessions[i + 1]
            third = valid_sessions[i + 2]
            mid_app = mid.get("app") or "Unknown"
            third_app = third.get("app") or "Unknown"
            mid_dur = int(mid.get("duration_seconds", 0))
            mid_kind = mid.get("kind", "active")
            third_kind = third.get("kind", "active")

            t_curr_end = parse_iso(curr["end"])
            t_mid_start = parse_iso(mid["start"])
            t_mid_end = parse_iso(mid["end"])
            t_third_start = parse_iso(third["start"])

            gap1 = (t_mid_start - t_curr_end).total_seconds() if t_curr_end and t_mid_start else 0
            gap2 = (t_third_start - t_mid_end).total_seconds() if t_mid_end and t_third_start else 0

            # For browser apps (chrome, edge), verify they return to the same activity domain/category
            same_context = True
            if is_browser_app(curr_app):
                curr_dom = get_session_semantic_domain(curr)
                third_dom = get_session_semantic_domain(third)
                same_context = are_domains_compatible(curr_dom, third_dom)

            if (
                third_app.lower() == curr_app.lower()
                and mid_app.lower() != curr_app.lower()
                and mid_dur < debounce_threshold_seconds
                and mid_kind != "idle"
                and third_kind != "idle"
                and gap1 < 10
                and gap2 < 10
                and same_context
            ):
                seg1 = ChildSegment(
                    app=curr_app,
                    title=curr.get("title", ""),
                    start=curr["start"],
                    end=curr["end"],
                    duration_seconds=curr_duration,
                    category_name=curr_cat_name,
                    category_color=curr_cat_color,
                    category_type=curr_cat_type,
                    is_interruption=False,
                )
                seg2 = ChildSegment(
                    app=mid_app,
                    title=mid.get("title", ""),
                    start=mid["start"],
                    end=mid["end"],
                    duration_seconds=mid_dur,
                    category_name=mid.get("category_name"),
                    category_color=mid.get("category_color"),
                    category_type=mid.get("category_type"),
                    is_interruption=True,
                )
                seg3 = ChildSegment(
                    app=third_app,
                    title=third.get("title", ""),
                    start=third["start"],
                    end=third["end"],
                    duration_seconds=int(third.get("duration_seconds", 0)),
                    category_name=third.get("category_name") or curr_cat_name,
                    category_color=third.get("category_color") or curr_cat_color,
                    category_type=third.get("category_type") or curr_cat_type,
                    is_interruption=False,
                )
                total_dur = curr_duration + mid_dur + seg3.duration_seconds
                segments = [seg1, seg2, seg3]
                cluster = TimelineCluster(
                    cluster_id=f"cluster_{i}",
                    label=curr_app.replace(".exe", ""),
                    cluster_type="absorbed",
                    dominant_app=curr_app,
                    dominant_category=curr_cat_name,
                    category_color=curr_cat_color,
                    category_type=curr_cat_type,
                    start=curr["start"],
                    end=third["end"],
                    duration_seconds=total_dur,
                    interruption_count=1,
                    child_segments=segments,
                    app_breakdown=calculate_app_breakdown(segments),
                    is_idle=False,
                )
                clusters.append(cluster)
                i += 3
                absorbed = True

        if absorbed:
            continue

        # Check Semantic Rapid Switching & Intelligent Activity Clustering:
        # Accumulates rapid switches (< mixed_threshold_seconds) while respecting semantic boundaries.
        j = i
        rapid_segments: List[ChildSegment] = []
        rapid_total_dur = 0
        cluster_domain = get_session_semantic_domain(curr)

        # If starting with a brief system overlay, attempt to anchor to following task
        if cluster_domain == "system_overlay" and i + 1 < n:
            next_dom = get_session_semantic_domain(valid_sessions[i + 1])
            if next_dom != "system_overlay":
                cluster_domain = next_dom

        while j < n:
            s_cand = valid_sessions[j]
            s_dur = int(s_cand.get("duration_seconds", 0))
            s_kind = s_cand.get("kind", "active")
            if s_kind == "idle":
                break

            # Check gap and midnight boundary
            if j > i:
                prev_end = parse_iso(valid_sessions[j - 1]["end"])
                cand_start = parse_iso(s_cand["start"])
                if prev_end and cand_start:
                    if prev_end.date() != cand_start.date() or (cand_start - prev_end).total_seconds() > 30:
                        break

                # Sustained session (>= 180s) terminates candidate accumulation
                if s_dur >= mixed_threshold_seconds:
                    break

                # Semantic Boundary Check:
                cand_dom = get_session_semantic_domain(s_cand)
                if not are_domains_compatible(cluster_domain, cand_dom):
                    # Check if this is merely a single transient excursion (< 60s) returning to cluster_domain
                    is_transient = (
                        s_dur < 60
                        and j + 1 < n
                        and are_domains_compatible(cluster_domain, get_session_semantic_domain(valid_sessions[j + 1]))
                        and valid_sessions[j + 1].get("kind") != "idle"
                    )
                    # Entertainment and social switches lasting >= 30s or not returning immediately enforce a hard boundary
                    if cand_dom in ("entertainment", "social") and (s_dur >= 30 or not is_transient):
                        break
                    if not is_transient:
                        break

            rapid_segments.append(
                ChildSegment(
                    app=s_cand.get("app") or "Unknown",
                    title=s_cand.get("title", ""),
                    start=s_cand["start"],
                    end=s_cand["end"],
                    duration_seconds=s_dur,
                    category_name=s_cand.get("category_name"),
                    category_color=s_cand.get("category_color"),
                    category_type=s_cand.get("category_type"),
                    is_interruption=(j > i and get_session_semantic_domain(s_cand) != cluster_domain and get_session_semantic_domain(s_cand) != "system_overlay"),
                )
            )
            rapid_total_dur += s_dur
            j += 1

        if len(rapid_segments) >= 3 and rapid_total_dur >= 60:
            breakdown = calculate_app_breakdown(rapid_segments)
            dominant = breakdown[0]["app"] if breakdown else "Mixed"
            dyn_label, dyn_cat, dyn_color, dyn_type = infer_cluster_metadata(rapid_segments)
            cluster = TimelineCluster(
                cluster_id=f"mixed_{i}",
                label=dyn_label,
                cluster_type="mixed",
                dominant_app=dominant,
                dominant_category=dyn_cat,
                category_color=dyn_color,
                category_type=dyn_type,
                start=rapid_segments[0].start,
                end=rapid_segments[-1].end,
                duration_seconds=rapid_total_dur,
                interruption_count=sum(1 for seg in rapid_segments if seg.is_interruption),
                child_segments=rapid_segments,
                app_breakdown=breakdown,
                is_idle=False,
            )
            clusters.append(cluster)
            i = j
            continue

        # Default: Single standalone session block
        seg = ChildSegment(
            app=curr_app,
            title=curr.get("title", ""),
            start=curr["start"],
            end=curr["end"],
            duration_seconds=curr_duration,
            category_name=curr_cat_name,
            category_color=curr_cat_color,
            category_type=curr_cat_type,
            is_interruption=False,
        )
        cluster = TimelineCluster(
            cluster_id=f"single_{i}",
            label=curr_app.replace(".exe", ""),
            cluster_type="single",
            dominant_app=curr_app,
            dominant_category=curr_cat_name,
            category_color=curr_cat_color,
            category_type=curr_cat_type,
            start=curr["start"],
            end=curr["end"],
            duration_seconds=curr_duration,
            interruption_count=0,
            child_segments=[seg],
            app_breakdown=[{
                "app": curr_app,
                "seconds": curr_duration,
                "pct": 100.0,
                "label": f"{curr_duration // 60}m {curr_duration % 60}s" if curr_duration >= 60 else f"{curr_duration}s",
            }],
            is_idle=False,
        )
        clusters.append(cluster)
        i += 1

    return clusters
