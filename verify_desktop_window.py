"""
verify_desktop_window.py — Automated verification script that launches PyWebView window,
inspects the rendered React DOM and API connectivity via evaluate_js, and closes cleanly.
"""

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import webview
import desktop_app


def on_window_ready(window):
    """Callback executed right after the PyWebView window is created and displayed."""
    print("[verify] Desktop window created and active.", flush=True)

    # Wait 2 seconds for React to mount and hydrate
    time.sleep(2.5)

    try:
        doc_title = window.evaluate_js("document.title")
        print(f"[verify] Document title: {doc_title}", flush=True)

        has_root = window.evaluate_js("Boolean(document.getElementById('root'))")
        print(f"[verify] Root element mounted: {has_root}", flush=True)

        root_children = window.evaluate_js("document.getElementById('root').children.length")
        print(f"[verify] Root children rendered: {root_children}", flush=True)

        # Check API connectivity through the window's WebView2 context
        api_health = window.evaluate_js(
            "fetch('/api/health').then(r => r.json()).then(d => d.status).catch(e => e.toString())"
        )
        print(f"[verify] Window API health response: {api_health}", flush=True)

        # Check tracker status through window
        tracker_status = window.evaluate_js(
            "fetch('/api/tracker/status').then(r => r.json()).then(d => d.status_text).catch(e => e.toString())"
        )
        print(f"[verify] Window Tracker status: {tracker_status}", flush=True)

    except Exception as e:
        print(f"[verify] Error evaluating JS: {e}", file=sys.stderr, flush=True)

    finally:
        print("[verify] Closing verification window...", flush=True)
        time.sleep(1.0)
        window.destroy()


def run_verification():
    desktop_app.setup_environment()
    port = 8000

    # Ensure backend is healthy
    if not desktop_app.is_backend_healthy(port):
        print(f"[verify] Starting embedded backend on port {port}...", flush=True)
        desktop_app.start_embedded_backend(port)
        if not desktop_app.wait_for_backend(port, 10.0):
            print(f"[verify] Backend failed to start on port {port}.", file=sys.stderr)
            sys.exit(1)

    icon_path = _ROOT / "assets" / "time_tracker_ai.ico"
    icon_arg = str(icon_path) if icon_path.exists() else None

    window = webview.create_window(
        title="Time Tracker AI — Verification Test",
        url=f"http://127.0.0.1:{port}/",
        width=1200,
        height=800,
        background_color="#0F1420",
    )

    print("[verify] Launching PyWebView...", flush=True)
    webview.start(on_window_ready, window, icon=icon_arg, private_mode=False)
    print("[verify] PyWebView closed cleanly. All checks complete.", flush=True)


if __name__ == "__main__":
    run_verification()

