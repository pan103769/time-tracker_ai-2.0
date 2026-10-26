
from pathlib import Path
import re
import shutil
from datetime import datetime

TARGET = Path("main.py")

if not TARGET.exists():
    raise SystemExit("ERROR: Run this from your project directory.")

source = TARGET.read_text(encoding="utf-8")
backup = TARGET.with_name(
    f"main.py.backup_{datetime.now():%Y%m%d_%H%M%S}"
)


def replace_function(text, name, replacement):
    pattern = (
        rf"(?ms)^def {re.escape(name)}\(.*?"
        rf"(?=^def |^if __name__ == [\"\']__main__[\"\']|\Z)"
    )
    match = re.search(pattern, text)

    if not match:
        raise SystemExit(
            f"ERROR: Could not find {name}(). No changes made."
        )

    return (
        text[:match.start()]
        + replacement.rstrip()
        + "\n\n"
        + text[match.end():]
    )


needs_visual = '''def needs_visual_context(app, title):
    """Return True when foreground metadata is generic."""
    app_text = (app or "").strip().lower()
    title_text = (title or "").strip().lower()

    return (
        app_text in {"", "unknown", "unknown.exe"}
        or title_text in UNKNOWN_TITLES
        or title_text.startswith("untitled -")
    )
'''


worker = '''def screenshot_worker(stop_event):
    """Analyze queued screenshots and verify database writes."""
    db = sqlite3.connect(DB_PATH, timeout=15)

    try:
        while True:
            try:
                item = screenshot_queue.get(timeout=0.5)
            except queue.Empty:
                if stop_event.is_set():
                    break
                continue

            if item is None:
                screenshot_queue.task_done()
                if screenshot_queue.empty():
                    break
                continue

            observation_id, captured_at, app, title, image_bytes = item

            try:
                print(
                    f"[vision] Analyzing observation {observation_id} "
                    f"with {VISION_MODEL}..."
                )

                description = analyze_screenshot(
                    image_bytes, app, title
                )

                with db:
                    db.execute(
                        """
                        INSERT INTO activity_screenshots
                            (observation_id, path, captured_at, description)
                        VALUES (?, '', ?, ?)
                        ON CONFLICT(observation_id) DO UPDATE SET
                            path = '',
                            captured_at = excluded.captured_at,
                            description = excluded.description
                        """,
                        (
                            observation_id,
                            timestamp(captured_at),
                            description,
                        ),
                    )

                saved = db.execute(
                    """
                    SELECT description
                    FROM activity_screenshots
                    WHERE observation_id = ?
                    """,
                    (observation_id,),
                ).fetchone()

                if saved and saved[0]:
                    print(
                        f"[vision] SAVED observation {observation_id}: "
                        f"{saved[0]}"
                    )
                else:
                    print(
                        f"[vision] ERROR: save verification failed "
                        f"for observation {observation_id}"
                    )

            except Exception as error:
                print(
                    f"[vision] FAILED observation {observation_id}: "
                    f"{type(error).__name__}: {error}"
                )

            finally:
                image_bytes = None
                screenshot_queue.task_done()

    finally:
        db.close()
'''


capture = '''def queue_unknown_screenshot(
    observation_id, app, title, captured_at
):
    """Capture only when metadata is generic; never save image files."""
    if not SCREENSHOTS_ENABLED:
        print("[vision] SKIP: screenshots disabled.")
        return

    if ImageGrab is None:
        print("[vision] SKIP: Pillow ImageGrab unavailable.")
        return

    if not needs_visual_context(app, title):
        print(
            f"[vision] SKIP: identifiable window: "
            f"{app!r} | {title!r}"
        )
        return

    if is_sensitive_app(app, title):
        print(
            f"[vision] SKIP: sensitive window: {app!r} | {title!r}"
        )
        return

    image_bytes = None

    try:
        image_bytes = capture_screenshot_bytes()

        if not image_bytes:
            print("[vision] FAILED: screenshot capture returned no image.")
            return

        item = (
            observation_id,
            captured_at,
            app,
            title,
            image_bytes,
        )

        try:
            screenshot_queue.put_nowait(item)
        except queue.Full:
            print("[vision] FAILED: queue full; screenshot discarded.")
            return

        image_bytes = None  # Queue now owns the image bytes.

        print(
            f"[vision] QUEUED observation {observation_id}: "
            f"{app!r} | {title!r}"
        )

    except Exception as error:
        print(
            f"[vision] CAPTURE FAILED: "
            f"{type(error).__name__}: {error}"
        )
'''


for name in (
    "needs_visual_context",
    "screenshot_worker",
    "queue_unknown_screenshot",
):
    if not re.search(rf"(?m)^def {name}\(", source):
        raise SystemExit(
            f"ERROR: {name}() not found. No changes made."
        )

updated = source

updated = replace_function(
    updated, "needs_visual_context", needs_visual
)
updated = replace_function(
    updated, "screenshot_worker", worker
)
updated = replace_function(
    updated, "queue_unknown_screenshot", capture
)

old_shutdown = '''        stop_event.set()

        try:
            screenshot_queue.put_nowait(None)
        except queue.Full:
            pass
'''

new_shutdown = '''        # Allow queued screenshots to finish before stopping the worker.
        try:
            screenshot_queue.put(None, timeout=2)
        except queue.Full:
            print("[vision] WARNING: queue full during shutdown.")

        if "vision_thread" in locals():
            if vision_thread.is_alive():
                vision_thread.join(timeout=100)

        stop_event.set()

        if "vision_thread" in locals() and vision_thread.is_alive():
            print(
                "[vision] WARNING: worker still running; "
                "the model request may be waiting."
            )
'''

if old_shutdown not in updated:
    raise SystemExit(
        "ERROR: shutdown block did not match. No changes made."
    )

updated = updated.replace(old_shutdown, new_shutdown, 1)

# Compile before touching main.py.
compile(updated, str(TARGET), "exec")

shutil.copy2(TARGET, backup)
TARGET.write_text(updated, encoding="utf-8", newline="")

print("Vision pipeline patch applied.")
print(f"Backup: {backup}")
print("Database was not modified.")
