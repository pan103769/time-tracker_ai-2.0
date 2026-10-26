
import psutil
from pywinauto import Desktop

print("Searching for Chrome windows...\n")

found = False

for window in Desktop(backend="uia").windows():
    try:
        title = window.window_text()
        if not title:
            continue

        process = psutil.Process(window.process_id()).name()

        if process.lower() != "chrome.exe":
            continue

        found = True
        print(f"\nChrome window: {title}")
        print("-" * 60)

        for control in window.descendants():
            try:
                info = control.element_info
                name = (info.name or "").strip()
                control_type = info.control_type or ""

                if name or control_type in ("Edit", "ComboBox"):
                    try:
                        value = control.get_value()
                    except Exception:
                        value = ""

                    print(
                        f"type={control_type!r} "
                        f"name={name!r} "
                        f"value={str(value)[:150]!r}"
                    )
            except Exception:
                pass

    except Exception:
        continue

if not found:
    print("No Chrome windows found. Make sure Chrome is open.")

print("\nInspection complete.")
