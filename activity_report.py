import base64
import hashlib

import json

import os

import re

import sqlite3

import sys

import urllib.error

import urllib.request

from collections import defaultdict

from datetime import date, datetime, time, timedelta

from pathlib import Path

from urllib.parse import urlparse, urlunparse

DB_PATH = Path(os.environ.get("TIME_TRACKER_DB_PATH", Path(__file__).resolve().parent / "tracker.db"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")

AI_MODEL = os.getenv("TRACKER_AI_MODEL", "gemma4:cloud")

AI_TIMEOUT_SECONDS = int(os.getenv("TRACKER_AI_TIMEOUT_SECONDS", "90"))
VISION_MODEL = os.getenv("TRACKER_VISION_MODEL", "gemma3:4b")

CLASSIFIER_VERSION = "freeform-activity-v4-local-vision"

# Per-report memo: same context is classified at most once per run.
_RUN_CONTEXT_CACHE = {}

def format_duration(seconds):

    seconds = max(0, int(seconds))

    hours, remainder = divmod(seconds, 3600)

    minutes, seconds = divmod(remainder, 60)

    if hours:

        return f"{hours}h {minutes}m"

    if minutes:

        return f"{minutes}m {seconds}s"

    return f"{seconds}s"

def parse_timestamp(value, fallback=None):

    if value is None or value == "":

        return fallback

    try:

        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        return parsed.astimezone()

    except (ValueError, TypeError, OverflowError):

        try:

            return datetime.fromtimestamp(float(value)).astimezone()

        except (ValueError, TypeError, OSError, OverflowError):

            return fallback

def clean_url(url):

    if not url or not str(url).strip():

        return ""

    try:

        raw = str(url).strip()

        parsed = urlparse(raw if "://" in raw else "https://" + raw)

        if not parsed.netloc:

            return ""

        return urlunparse(

            (parsed.scheme, parsed.netloc, parsed.path, "", "", "")

        )

    except ValueError:

        return ""

def extract_json(text):
    """Parse JSON returned with or without Markdown code fences."""
    text = (text or "").strip()
    text = re.sub(r"\A```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*\Z", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError(f"No JSON object found in model response: {text[:300]!r}")

def cache_key(app, title, url):

    value = "\n".join(

        (

            CLASSIFIER_VERSION,

            AI_MODEL,

            app or "",

            title or "",

            clean_url(url),

        )

    )

    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()

def ensure_ai_cache(db):

    # Preserve the existing cache table and its historical rows.

    db.execute(

        """

        CREATE TABLE IF NOT EXISTS activity_ai_context (

            context_key TEXT PRIMARY KEY,

            app TEXT NOT NULL,

            title TEXT NOT NULL,

            url TEXT NOT NULL,

            category TEXT NOT NULL DEFAULT '',

            activity TEXT NOT NULL,

            reason TEXT NOT NULL DEFAULT '',

            confidence REAL NOT NULL DEFAULT 0,

            created_at TEXT NOT NULL,

            work_mode TEXT NOT NULL DEFAULT ''

        )

        """

    )

    db.commit()

def get_cached_context(db, app, title, url):

    columns = {

        row["name"]

        for row in db.execute(

            "PRAGMA table_info(activity_ai_context)"

        )

    }

    if not {

        "context_key",

        "activity",

        "reason",

        "confidence",

    }.issubset(columns):

        return None

    row = db.execute(

        """

        SELECT activity, reason, confidence

        FROM activity_ai_context

        WHERE context_key = ?

        """,

        (cache_key(app, title, url),),

    ).fetchone()

    if not row:

        return None

    return {

        "activity": row["activity"],

        "reason": row["reason"],

        "confidence": float(row["confidence"] or 0),

        "source": "cache",

    }

def save_context(db, app, title, url, result):

    columns = {

        row["name"]

        for row in db.execute(

            "PRAGMA table_info(activity_ai_context)"

        )

    }

    required = {

        "context_key",

        "app",

        "title",

        "url",

        "activity",

        "reason",

        "confidence",

        "created_at",

    }

    if not required.issubset(columns):

        return

    values = {

        "context_key": cache_key(app, title, url),

        "app": app or "",

        "title": title or "",

        "url": clean_url(url),

        "activity": result["activity"],

        "reason": result["reason"],

        "confidence": result["confidence"],

        "created_at": datetime.now().astimezone().isoformat(

            timespec="seconds"

        ),

    }

    # Legacy columns remain for database compatibility, but are unused.

    if "category" in columns:

        values["category"] = ""

    if "work_mode" in columns:

        values["work_mode"] = ""

    names = list(values)

    quoted_names = ", ".join(f'"{name}"' for name in names)

    placeholders = ", ".join("?" for _ in names)

    db.execute(

        f"""

        INSERT OR REPLACE INTO activity_ai_context

        ({quoted_names})

        VALUES ({placeholders})

        """,

        [values[name] for name in names],

    )

    db.commit()

def ask_ai(app, title, url="", nearby_context=""):

    safe_url = clean_url(url)

    prompt = f"""

Infer the likely computer activity using only the metadata below.

Return one JSON object with exactly these fields:

{{

  "activity": "Concise natural-language activity description",

  "reason": "Brief explanation of the evidence and uncertainty",

  "confidence": 0.0

}}

Rules:

- Generate a free-form activity description. Do not use fixed categories.

- Do not assign work modes.

- Be specific only when the evidence supports it.

- Never invent actions, code changes, page contents, or intentions.

- If the evidence is insufficient, explicitly state the uncertainty.

- Confidence must be a number between 0 and 1.

- Return JSON only, without Markdown fences.

Application: {app}

Window or page title: {title}

Sanitized URL: {safe_url or "Unavailable"}

Nearby window titles: {nearby_context or "Unavailable"}

"""

    payload = {

        "model": AI_MODEL,

        "stream": False,

        "format": "json",

        "messages": [

            {"role": "user", "content": prompt}

        ],

        "options": {"temperature": 0.1},

    }

    request = urllib.request.Request(

        f"{OLLAMA_URL}/api/chat",

        data=json.dumps(payload).encode("utf-8"),

        headers={"Content-Type": "application/json"},

        method="POST",

    )

    with urllib.request.urlopen(

        request, timeout=AI_TIMEOUT_SECONDS

    ) as response:

        outer = json.loads(response.read().decode("utf-8"))

    content = outer.get("message", {}).get("content", "")

    if not content.strip():

        raise ValueError(

            f"Ollama returned an empty message: {outer!r}"

        )

    parsed = extract_json(content)

    activity = parsed.get("activity")

    if not isinstance(activity, str) or not activity.strip():

        raise ValueError(

            "Model response has no usable activity description."

        )

    try:

        confidence = float(parsed.get("confidence", 0))

    except (TypeError, ValueError):

        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    return {

        "activity": activity.strip()[:200],

        "reason": str(parsed.get("reason", "")).strip()[:400],

        "confidence": confidence,

        "source": "AI",

    }

def classify_activity(
    db, app, title, url="", nearby_context="", refresh=False
):
    """Classify a context once per report run and persist successful results."""
    key = cache_key(app, title, url)

    # --refresh-ai deliberately bypasses both persistent and in-memory caches.
    if not refresh:
        if key in _RUN_CONTEXT_CACHE:
            return dict(_RUN_CONTEXT_CACHE[key])
        cached = get_cached_context(db, app, title, url)
        if cached:
            _RUN_CONTEXT_CACHE[key] = dict(cached)
            return dict(cached)

    try:
        result = ask_ai(app, title, url, nearby_context)
        save_context(db, app, title, url, result)
        _RUN_CONTEXT_CACHE[key] = dict(result)
        return result
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        # Do not memoize failures: a later attempt may succeed.
        return {
            "activity": "Uncertain — activity could not be classified",
            "reason": f"{type(error).__name__}: {error}",
            "confidence": 0.0,
            "source": "fallback",
        }

def load_browser_visits(db, day_start, day_end, now):

    tables = {

        row["name"]

        for row in db.execute(

            "SELECT name FROM sqlite_master WHERE type='table'"

        )

    }

    if "browser_visits" not in tables:

        return []

    columns = {

        row["name"]

        for row in db.execute(

            "PRAGMA table_info(browser_visits)"

        )

    }

    if not {"start_time", "end_time", "url"}.issubset(columns):

        return []

    selected = [

        column

        for column in ("start_time", "end_time", "url", "title")

        if column in columns

    ]

    rows = db.execute(

        "SELECT "

        + ", ".join(f'"{column}"' for column in selected)

        + ' FROM browser_visits ORDER BY "start_time"'

    ).fetchall()

    visits = []

    for row in rows:

        start = parse_timestamp(row["start_time"])

        end = parse_timestamp(row["end_time"], now)

        if (

            start is None

            or end is None

            or end <= start

            or end <= day_start

            or start >= day_end

        ):

            continue

        visits.append(

            {

                "start": max(start, day_start),

                "end": min(end, day_end),

                "url": row["url"] or "",

                "title": (

                    row["title"] or ""

                    if "title" in row.keys()

                    else ""

                ),

            }

        )

    return visits

def is_browser_app(app):

    return any(

        token in (app or "").lower()

        for token in (

            "chrome",

            "msedge",

            "firefox",

            "brave",

            "opera",

            "browser",

        )

    )

def describe_unknown_screenshot(db, observation_id):
    """Use local Gemma vision on a screenshot captured for this observation."""
    if observation_id is None:
        return None
    tables = {
        row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "activity_screenshots" not in tables:
        return None
    columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(activity_screenshots)"
        )
    }
    if not {"observation_id", "path", "description"}.issubset(columns):
        return None
    row = db.execute(
        "SELECT path, description FROM activity_screenshots WHERE observation_id=?",
        (observation_id,),
    ).fetchone()
    if not row:
        return None
    if row["description"] and row["description"].strip():
        return row["description"].strip()
    image_path = Path(row["path"])
    if not image_path.is_file():
        return None
    try:
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": VISION_MODEL,
            "stream": False,
            "messages": [{
                "role": "user",
                "content": (
                    "Describe the visible computer activity in this screenshot in one or two "
                    "sentences. Identify the app and visible task only when supported by evidence. "
                    "Do not infer intent or repeat sensitive personal information. If unclear, say so."
                ),
                "images": [encoded_image],
            }],
            "options": {"temperature": 0.1},
        }
        request = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SECONDS) as response:
            outer = json.loads(response.read().decode("utf-8"))
        description = str(outer.get("message", {}).get("content", "")).strip()
        if not description:
            return None
        description = description[:500]
        with db:
            db.execute(
                "UPDATE activity_screenshots SET description=? WHERE observation_id=?",
                (description, observation_id),
            )
        return description
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"  [vision] Local screenshot analysis skipped: {type(error).__name__}: {error}")
        return None


def use_visual_fallback(db, observation_id, result):
    """Only invoke local vision when metadata classification is uncertain."""
    activity = str(result.get("activity", "")).lower()
    uncertain = (
        float(result.get("confidence", 0) or 0) < 0.45
        or "uncertain" in activity
        or "could not be classified" in activity
        or "insufficient evidence" in activity
    )
    if not uncertain:
        return result
    description = describe_unknown_screenshot(db, observation_id)
    if not description:
        return result
    result = dict(result)
    result["activity"] = f"Visual context: {description}"
    result["reason"] = (str(result.get("reason", "")).strip() + " Local screenshot analyzed by " + VISION_MODEL).strip()[:400]
    result["source"] = "vision" if result.get("source") != "cache" else "vision-cache"
    return result


def classify_segments(

    db, app, title, start, end, visits, nearby, refresh=False

):

    if not is_browser_app(app):

        result = classify_activity(

            db,

            app,

            title,

            nearby_context=nearby,

            refresh=refresh,

        )

        return [

            {"seconds": (end - start).total_seconds(), **result}

        ]

    overlapping = []

    boundaries = {start, end}

    for visit in visits:

        left = max(start, visit["start"])

        right = min(end, visit["end"])

        if left < right:

            boundaries.update((left, right))

            overlapping.append(visit)

    points = sorted(boundaries)

    segments = []

    for left, right in zip(points, points[1:]):

        if right <= left:

            continue

        url = ""

        page_title = title

        for visit in overlapping:

            if visit["start"] <= left and visit["end"] >= right:

                url = visit["url"]

                page_title = visit["title"] or title

                break

        result = classify_activity(

            db, app, page_title, url, nearby, refresh

        )

        segments.append(

            {

                "seconds": (right - left).total_seconds(),

                "url": clean_url(url),

                **result,

            }

        )

    return segments

def main():

    _RUN_CONTEXT_CACHE.clear()

    args = [

        argument

        for argument in sys.argv[1:]

        if argument != "--refresh-ai"

    ]

    refresh = "--refresh-ai" in sys.argv[1:]

    if len(args) > 1:

        print(

            "Usage: python activity_report.py "

            "[YYYY-MM-DD] [--refresh-ai]"

        )

        return 1

    try:

        selected_date = (

            date.fromisoformat(args[0]) if args else date.today()

        )

    except ValueError:

        print("Invalid date. Use YYYY-MM-DD.")

        return 1

    if not DB_PATH.exists():

        print(f"Database not found: {DB_PATH}")

        return 1

    day_start = datetime.combine(

        selected_date, time.min

    ).astimezone()

    day_end = datetime.combine(

        selected_date + timedelta(days=1), time.min

    ).astimezone()

    now = datetime.now().astimezone()

    app_totals = defaultdict(float)

    window_totals = defaultdict(float)

    activity_totals = defaultdict(float)

    source_counts = defaultdict(int)

    active_seconds = 0.0

    idle_seconds = 0.0

    observations_found = False

    browser_segments = 0

    with sqlite3.connect(DB_PATH, timeout=10) as db:

        db.row_factory = sqlite3.Row

        tables = {

            row["name"]

            for row in db.execute(

                "SELECT name FROM sqlite_master WHERE type='table'"

            )

        }

        if "observations" not in tables:

            print(

                "No observations table found. "

                "Database left unchanged."

            )

            return 1

        ensure_ai_cache(db)

        visits = load_browser_visits(

            db, day_start, day_end, now

        )

        rows = db.execute(

            """

            SELECT kind, app, title, start_time, end_time

            FROM observations

            ORDER BY start_time

            """

        ).fetchall()

        for index, row in enumerate(rows):

            start = parse_timestamp(row["start_time"])

            end = parse_timestamp(row["end_time"], now)

            if (

                start is None

                or end is None

                or start >= day_end

                or end <= day_start

            ):

                continue

            start = max(start, day_start)

            end = min(end, day_end)

            seconds = max(0, (end - start).total_seconds())

            if seconds <= 0:

                continue

            observations_found = True

            if row["kind"] == "idle":

                idle_seconds += seconds

                continue

            app = row["app"] or "Unknown application"

            title = row["title"] or "Untitled window"

            active_seconds += seconds

            app_totals[app] += seconds

            window_totals[(app, title)] += seconds

            nearby = []

            for neighbor_index in (index - 1, index + 1):

                if 0 <= neighbor_index < len(rows):

                    neighbor = rows[neighbor_index]

                    if neighbor["kind"] != "idle":

                        nearby.append(

                            f'{neighbor["app"] or "Unknown app"}: '

                            f'{neighbor["title"] or "Untitled window"}'

                        )

            segments = classify_segments(

                db,

                app,

                title,

                start,

                end,

                visits,

                " | ".join(nearby)[:500],

                refresh,

            )

            for segment in segments:

                activity_totals[segment["activity"]] += segment["seconds"]

                source_counts[segment["source"]] += 1

                if segment.get("url"):

                    browser_segments += 1

    print(

        f"\nACTIVITY REPORT — {selected_date}\n"

        + "=" * 64

    )

    if not observations_found:

        print("No activity records found for this date.")

        return 0

    print("\nTIME SUMMARY")

    print(f"Observed active time : {format_duration(active_seconds)}")

    print(f"Observed idle time   : {format_duration(idle_seconds)}")

    print(

        f"Total recorded time  : "

        f"{format_duration(active_seconds + idle_seconds)}"

    )

    print("\nACTIVITIES — AI-GENERATED DESCRIPTIONS")

    for activity, seconds in sorted(

        activity_totals.items(),

        key=lambda item: item[1],

        reverse=True,

    ):

        print(f"{format_duration(seconds):>12} | {activity}")

    print("\nTIME BY APPLICATION")

    for app, seconds in sorted(

        app_totals.items(),

        key=lambda item: item[1],

        reverse=True,

    ):

        print(f"{format_duration(seconds):>12} | {app}")

    print("\nWINDOW DETAILS")

    for (app, title), seconds in sorted(

        window_totals.items(),

        key=lambda item: item[1],

        reverse=True,

    ):

        print(

            f"{format_duration(seconds):>12} | "

            f"{app} — {title}"

        )

    print("\nCLASSIFICATION NOTES")

    print(f"AI model                 : {AI_MODEL}")

    print(f"Browser segments         : {browser_segments}")

    print(f"AI classifications       : {source_counts['AI']}")

    print(f"Cached classifications   : {source_counts['cache']}")

    print(f"Fallback classifications : {source_counts['fallback']}")

    print(f"Classifier version       : {CLASSIFIER_VERSION}")

    print("- Existing observations and browser visits are preserved.")

    print("- URLs have query parameters and fragments removed.")

    print(f"Local vision model       : {VISION_MODEL}")
    print("- Screenshots are analyzed locally only; they are not sent to the cloud model.")
    print("- Screenshots are captured only for generic/unknown window metadata.")
    print("- Browser page contents and typed characters are not collected by this feature.")

    if refresh:

        print("- Cached classifications were bypassed.")

    return 0

if __name__ == "__main__":

    raise SystemExit(main())