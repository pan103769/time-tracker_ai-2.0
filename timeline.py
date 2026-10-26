"""
timeline.py — Activity timeline entry point.

By default, displays the rich AI activity timeline powered by ai_timeline.py.
Supports date selection (YYYY-MM-DD), interactive editing (--edit N),
refreshing AI classifications (--refresh-ai), and hiding idle time (--no-idle).

To view legacy raw observation records, pass --raw:
    python timeline.py --raw [YYYY-MM-DD]
"""

import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import ai_timeline

DB_PATH = Path(__file__).with_name("tracker.db")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def raw_timeline(selected_date: date) -> int:
    """Display legacy raw, unmerged observation records."""
    start_of_day = datetime.combine(selected_date, time.min).astimezone()
    start_of_next_day = start_of_day + timedelta(days=1)

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    db = sqlite3.connect(DB_PATH)
    try:
        rows = db.execute(
            """
            SELECT id, kind, app, title, start_time, end_time, duration_seconds
            FROM observations
            WHERE start_time < ?
              AND (end_time IS NULL OR end_time > ?)
            ORDER BY start_time, id
            """,
            (
                start_of_next_day.astimezone().isoformat(),
                start_of_day.astimezone().isoformat(),
            ),
        ).fetchall()
    finally:
        db.close()

    print(f"\nRAW OBSERVATION TIMELINE — {selected_date}\n")
    if not rows:
        print("No records found for this date.")
        return 0

    for row_id, kind, app, title, start_text, end_text, duration in rows:
        start = datetime.fromisoformat(start_text).astimezone()
        end = (
            datetime.fromisoformat(end_text).astimezone()
            if end_text
            else datetime.now().astimezone()
        )
        clipped_start = max(start, start_of_day)
        clipped_end = min(end, start_of_next_day)
        seconds = max(0, (clipped_end - clipped_start).total_seconds())

        print(
            f"{clipped_start:%H:%M:%S}  "
            f"{format_duration(seconds):>12}  "
            f"{kind.upper():6}  {app}"
        )
        if kind == "active" and title and title != app:
            print(f"{'':24}↳ {title[:100]}")

    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Check for --raw flag to display legacy raw observations
    if "--raw" in argv:
        args_without_raw = [a for a in argv if a != "--raw"]
        try:
            selected_date = (
                date.fromisoformat(args_without_raw[0])
                if args_without_raw
                else date.today()
            )
        except ValueError:
            print("Invalid date. Use YYYY-MM-DD.")
            return 1
        return raw_timeline(selected_date)

    # By default, reuse the AI timeline engine without duplicating any logic
    return ai_timeline.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
