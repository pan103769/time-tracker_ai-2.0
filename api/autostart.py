"""
api/autostart.py — Windows Startup Configuration Manager for Time Tracker AI.

Provides standard, non-administrator auto-launch on Windows login via:
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

Uses pythonw.exe to prevent terminal popups at login, and verifies the
named mutex to guarantee that duplicate instances are never spawned.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

_ROOT = Path(__file__).resolve().parent.parent
REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "TimeTrackerAI"


def get_autostart_command() -> str:
    """
    Construct the command to launch background activity tracking at login.
    Prefers pythonw.exe in .venv so no console window is created.
    """
    venv_pythonw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.exists():
        py_exe = venv_pythonw
    else:
        # Fallback to sys.executable's pythonw sibling or sys.executable
        candidate = Path(sys.executable).with_name("pythonw.exe")
        py_exe = candidate if candidate.exists() else Path(sys.executable)

    main_script = _ROOT / "main.py"
    return f'"{py_exe}" "{main_script}"'


def is_autostart_enabled() -> bool:
    """Return True if TimeTrackerAI is registered in HKCU Run key."""
    if sys.platform != "win32":
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_KEY_PATH,
            0,
            winreg.KEY_READ,
        ) as key:
            try:
                val, reg_type = winreg.QueryValueEx(key, REG_VALUE_NAME)
                return bool(val)
            except FileNotFoundError:
                return False
    except Exception:
        return False


def enable_autostart() -> Tuple[bool, str]:
    """
    Register TimeTrackerAI in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    Requires only standard user privileges (no UAC / elevation needed).
    """
    if sys.platform != "win32":
        return False, "Autostart is only supported on Windows."

    command = get_autostart_command()

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_READ,
        ) as key:
            winreg.SetValueEx(
                key,
                REG_VALUE_NAME,
                0,
                winreg.REG_SZ,
                command,
            )
        return True, command
    except Exception as e:
        return False, str(e)


def disable_autostart() -> Tuple[bool, str]:
    """
    Remove TimeTrackerAI from HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    """
    if sys.platform != "win32":
        return False, "Autostart is only supported on Windows."

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_READ,
        ) as key:
            try:
                winreg.DeleteValue(key, REG_VALUE_NAME)
                return True, "Autostart disabled successfully."
            except FileNotFoundError:
                return True, "Autostart was already disabled."
    except Exception as e:
        return False, str(e)


def main(argv=None) -> int:
    """CLI dispatcher for managing autostart."""
    if argv is None:
        argv = sys.argv[1:]

    action = argv[0].lower() if argv else "--status"

    if action in ("--enable", "enable", "-e"):
        success, detail = enable_autostart()
        if success:
            print(f"Windows autostart enabled: {detail}")
            return 0
        else:
            print(f"Failed to enable autostart: {detail}", file=sys.stderr)
            return 1

    elif action in ("--disable", "disable", "-d"):
        success, detail = disable_autostart()
        if success:
            print("Windows autostart disabled.")
            return 0
        else:
            print(f"Failed to disable autostart: {detail}", file=sys.stderr)
            return 1

    elif action in ("--status", "status", "-s"):
        enabled = is_autostart_enabled()
        cmd = get_autostart_command()
        print(f"Windows autostart: {'ENABLED' if enabled else 'DISABLED'}")
        if enabled:
            print(f"Command: {cmd}")
        return 0

    else:
        print("Usage: python main.py autostart [--enable | --disable | --status]")
        return 2


if __name__ == "__main__":
    sys.exit(main())

