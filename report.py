
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

DB_PATH = Path(__file__).with_name("tracker.db")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def main():
    try:
        selected_date = (
            date.fromisoformat(sys.argv[1])
            if len(sys.argv) > 1
            else date.today()
        )
    except ValueError:
        print("Invalid date. Use YYYY-MM-DD, e.g. 2026-10-14.")
        return

    if len(sys.argv) > 2:
        print("Usage: python report.py [YYYY-MM-DD]")
        return

    day_start = datetime.combine(
        selected_date, time.min
    ).astimezone()

    next_day_start = datetime.combine(
        selected_date + timedelta(days=1), time.min
    ).astimezone()

    totals = defaultdict(float)

    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute("""
            SELECT kind, app, start_time, end_time
            FROM observations
            WHERE start_time < ?
              AND (end_time IS NULL OR end_time > ?)
        """, (
            next_day_start.astimezone().isoformat(),
            day_start.astimezone().isoformat(),
        )).fetchall()

    for kind, app, start_text, end_text in rows:
        start = datetime.fromisoformat(start_text).astimezone()
        end = (
            datetime.fromisoformat(end_text).astimezone()
            if end_text
            else datetime.now().astimezone()
        )

        clipped_start = max(start, day_start)
        clipped_end = min(end, next_day_start)

        seconds = max(
            0.0, (clipped_end - clipped_start).total_seconds()
        )

        label = "Idle" if kind == "idle" else app
        totals[label] += seconds

    print(f"\nDAILY ACTIVITY SUMMARY — {selected_date}\n")

    if not totals:
        print("No records found for this date.")
        return

    print(f"{'Application':<25} {'Time spent':>12}")
    print("-" * 39)

    for app, seconds in sorted(
        totals.items(), key=lambda item: item[1], reverse=True
    ):
        print(f"{app[:25]:<25} {format_duration(seconds):>12}")

    active = sum(v for k, v in totals.items() if k != "Idle")
    idle = totals.get("Idle", 0.0)

    print("-" * 39)
    print(f"{'Total active':<25} {format_duration(active):>12}")
    print(f"{'Total idle':<25} {format_duration(idle):>12}")


if __name__ == "__main__":
    main()
