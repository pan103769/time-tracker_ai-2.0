"""
api/windows_notifier.py — Native Windows toast notification dispatcher for Time Tracker AI 2.

Dispatches real Windows 10/11 desktop toast notification banners via WinRT API using
the registered Time Tracker AI application identity (AUMID: TimeTrackerAI.App).

Features:
- Windows Start Menu shortcut & Registry AUMID registration for branded title & icon.
- Explicit ShowBanner=1 and Enabled=1 in Windows Notification Settings registry.
- Supported Toast Generic XML templates with scenario="reminder" to ensure visual banners
  are prioritized, stay visible, and break through quiet modes when appropriate.
- Process lifespan stabilization (Start-Sleep -Milliseconds 2500) so the Windows notification
  platform does not drop or orphan the banner due to premature process teardown.
- App logo override with custom Time Tracker AI brand icon.
- Sound preferences: default Windows chime, silent, or custom bundled chime.
- Asynchronous dispatch via ThreadPoolExecutor with zero blocking on tracking threads.
- Comprehensive diagnostic inspection (AUMID, Registry, SHQueryUserNotificationState,
  Action Center history, ToastNotifier Setting).
- Quiet hours enforcement and non-blocking failure tolerance.
"""

from __future__ import annotations

import base64
import html
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("windows_notifier")
_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _ROOT / "tracker.db"
ASSETS_DIR = _ROOT / "assets"
ICO_PATH = ASSETS_DIR / "time_tracker_ai.ico"
PNG_PATH = ASSETS_DIR / "time_tracker_ai.png"
CHIME_PATH = ASSETS_DIR / "chime.wav"
BTN_PLAY_PATH = ASSETS_DIR / "btn_play.png"
BTN_CROSS_PATH = ASSETS_DIR / "btn_cross.png"
BTN_CLOCK_PATH = ASSETS_DIR / "btn_clock.png"

AUMID = "TimeTrackerAI.App"
APP_NAME = "Time Tracker AI"

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="win_toast")
_registered: bool = False
_reg_lock = threading.Lock()

# Thread-safe diagnostics tracker
_diag_lock = threading.Lock()
_diagnostics_state: Dict[str, Any] = {
    "last_attempt_time": None,
    "last_submission_result": None,
    "last_delivery_error": None,
    "last_title": None,
    "last_scenario": None,
    "total_dispatched": 0,
    "total_failed": 0,
}


# ---------------------------------------------------------------------------
# Asset Generation & Identity Registration
# ---------------------------------------------------------------------------

def _ensure_icon_assets():
    """Ensure high-resolution icon, button icons, and gentle chime assets exist in assets directory."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    if not PNG_PATH.exists() or not ICO_PATH.exists():
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # Squircle dark midnight navy background
            draw.rounded_rectangle([8, 8, 247, 247], radius=54, fill=(15, 20, 32, 255), outline=(0, 240, 255, 230), width=6)
            # Inner purple gradient accent
            draw.rounded_rectangle([14, 14, 241, 241], radius=48, outline=(128, 101, 255, 180), width=3)
            # Productivity lightning / clock core in purple
            bolt = [(140, 32), (75, 135), (125, 135), (105, 224), (185, 115), (135, 115), (165, 32)]
            draw.polygon(bolt, fill=(128, 101, 255, 255))
            # Inner cyan core
            core = [(140, 48), (88, 133), (127, 133), (114, 200), (172, 118), (134, 118), (158, 48)]
            draw.polygon(core, fill=(0, 240, 255, 255))

            img.save(str(PNG_PATH), format="PNG")
            img.save(str(ICO_PATH), format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
        except Exception as e:
            logger.debug("Could not generate brand icon assets: %s", e)

    # Action button icons for toast
    if not BTN_PLAY_PATH.exists() or not BTN_CROSS_PATH.exists() or not BTN_CLOCK_PATH.exists():
        try:
            from PIL import Image, ImageDraw
            # 1. Play Button (Cyan triangle)
            im_play = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
            d_play = ImageDraw.Draw(im_play)
            triangle = [(56, 36), (156, 96), (56, 156)]
            d_play.polygon(triangle, fill=(0, 240, 255, 255))
            im_play = im_play.resize((48, 48), Image.Resampling.LANCZOS)
            im_play.save(str(BTN_PLAY_PATH), "PNG")

            # 2. Cross Button (White X)
            im_cross = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
            d_cross = ImageDraw.Draw(im_cross)
            w = 20
            d_cross.line([(48, 48), (144, 144)], fill=(240, 244, 250, 255), width=w)
            d_cross.line([(48, 144), (144, 48)], fill=(240, 244, 250, 255), width=w)
            for pt in [(48, 48), (144, 144), (48, 144), (144, 48)]:
                d_cross.ellipse([pt[0]-w//2, pt[1]-w//2, pt[0]+w//2, pt[1]+w//2], fill=(240, 244, 250, 255))
            im_cross = im_cross.resize((48, 48), Image.Resampling.LANCZOS)
            im_cross.save(str(BTN_CROSS_PATH), "PNG")

            # 3. Clock Button (White clock)
            im_clock = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
            d_clock = ImageDraw.Draw(im_clock)
            cw = 18
            d_clock.ellipse([28, 28, 164, 164], outline=(240, 244, 250, 255), width=cw)
            d_clock.line([(96, 96), (96, 52)], fill=(240, 244, 250, 255), width=cw)
            d_clock.line([(96, 96), (134, 96)], fill=(240, 244, 250, 255), width=cw)
            for pt in [(96, 96), (96, 52), (134, 96)]:
                d_clock.ellipse([pt[0]-cw//2, pt[1]-cw//2, pt[0]+cw//2, pt[1]+cw//2], fill=(240, 244, 250, 255))
            im_clock = im_clock.resize((48, 48), Image.Resampling.LANCZOS)
            im_clock.save(str(BTN_CLOCK_PATH), "PNG")
        except Exception as e:
            logger.debug("Could not generate button icons: %s", e)

    # Gentle, soothing, calm chime (soft acoustic bell harmonic arpeggio)
    if not CHIME_PATH.exists():
        try:
            import math
            import struct
            import wave
            sample_rate = 44100
            duration = 0.85
            num_samples = int(sample_rate * duration)
            frames = bytearray()
            for i in range(num_samples):
                t = i / sample_rate
                def env(onset: float, decay_rate: float) -> float:
                    if t < onset:
                        return 0.0
                    dt = t - onset
                    att = 0.5 * (1.0 - math.cos(math.pi * min(1.0, dt / 0.035)))
                    dec = math.exp(-decay_rate * dt)
                    return att * dec

                e1 = env(0.0, 3.8)
                n1 = (math.sin(2 * math.pi * 329.63 * t) + 0.18 * math.sin(2 * math.pi * 659.25 * t)) * e1 * 0.13
                e2 = env(0.07, 4.0)
                n2 = (math.sin(2 * math.pi * 493.88 * max(0.0, t - 0.07)) + 0.15 * math.sin(2 * math.pi * 987.77 * max(0.0, t - 0.07))) * e2 * 0.11
                e3 = env(0.14, 4.5)
                n3 = (math.sin(2 * math.pi * 659.25 * max(0.0, t - 0.14)) + 0.10 * math.sin(2 * math.pi * 1318.5 * max(0.0, t - 0.14))) * e3 * 0.07

                total = n1 + n2 + n3
                if t > 0.75:
                    fade = 0.5 * (1.0 + math.cos(math.pi * (t - 0.75) / 0.10))
                    total *= fade

                val = max(-32767, min(32767, int(total * 32767.0)))
                frames.extend(struct.pack("<h", val))

            with wave.open(str(CHIME_PATH), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(frames)
        except Exception as e:
            logger.debug("Could not generate bundled chime: %s", e)


def register_windows_app_identity() -> bool:
    """
    Register Time Tracker AI AUMID in Windows Registry and Start Menu Programs folder.
    Configures:
    1. HKCU\\Software\\Classes\\AppUserModelId\\TimeTrackerAI.App
    2. HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings\\TimeTrackerAI.App
       with ShowBanner=1, Enabled=1, ShowInActionCenter=1.
    3. Start Menu Shortcut with real pythonw.exe target and System.AppUserModel.ID property.
    """
    global _registered
    if sys.platform != "win32":
        return False

    with _reg_lock:
        if _registered:
            return True

        _ensure_icon_assets()

        try:
            import winreg

            # 1. Register in HKCU Classes\AppUserModelId
            key_path = f"Software\\Classes\\AppUserModelId\\{AUMID}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
                if ICO_PATH.exists():
                    winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(ICO_PATH.resolve()))
                winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ, "FF0F1420")

            # 2. Register Windows Notification Settings (Force ShowBanner=1 and Enabled=1)
            notif_key_path = f"Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings\\{AUMID}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, notif_key_path) as nkey:
                winreg.SetValueEx(nkey, "ShowBanner", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(nkey, "Enabled", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(nkey, "ShowInActionCenter", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(nkey, "Sound", 0, winreg.REG_DWORD, 1)

            # 3. Register Start Menu Shortcut with System.AppUserModel.ID
            import pythoncom
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
            from win32com.propsys import propsys, pscon
            from win32com.shell import shell, shellcon
            import win32com.client

            programs_folder = shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0)
            shortcut_path = os.path.join(programs_folder, f"{APP_NAME}.lnk")

            wscript = win32com.client.Dispatch("WScript.Shell")
            shortcut = wscript.CreateShortCut(shortcut_path)

            venv_pythonw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
            exe_target = str(venv_pythonw.resolve()) if venv_pythonw.exists() else sys.executable
            main_script = str((_ROOT / "main.py").resolve())

            shortcut.TargetPath = exe_target
            shortcut.Arguments = f'"{main_script}"'
            shortcut.WorkingDirectory = str(_ROOT.resolve())
            if ICO_PATH.exists():
                shortcut.IconLocation = f"{ICO_PATH.resolve()},0"
            shortcut.Description = f"{APP_NAME} Productivity Engine"
            shortcut.Save()

            # Set System.AppUserModel.ID on the shortcut
            store = propsys.SHGetPropertyStoreFromParsingName(shortcut_path, None, 2, propsys.IID_IPropertyStore)
            propval = propsys.PROPVARIANTType(AUMID, pythoncom.VT_LPWSTR)
            store.SetValue(pscon.PKEY_AppUserModel_ID, propval)
            store.Commit()

            # 4. Register Custom URI Protocol (timetracker://)
            protocol_key = r"Software\Classes\timetracker"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, protocol_key) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Time Tracker AI Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, protocol_key + r"\DefaultIcon") as icon_key:
                if ICO_PATH.exists():
                    winreg.SetValueEx(icon_key, "", 0, winreg.REG_SZ, f'"{ICO_PATH.resolve()}",0')

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, protocol_key + r"\shell\open\command") as cmd_key:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}" "%1"'
                else:
                    desktop_script = (_ROOT / "desktop_app.py").resolve()
                    cmd = f'"{exe_target}" "{desktop_script}" "%1"'
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)

            _registered = True
            logger.info("Registered Windows AUMID '%s' and protocol 'timetracker://'", AUMID)
            return True
        except Exception as e:
            logger.debug("Notice: Windows identity registration deferred: %s", e)
            return False


# ---------------------------------------------------------------------------
# Notification Preferences & Quiet Hours
# ---------------------------------------------------------------------------

def _is_in_quiet_hours(
    start_or_settings: Any,
    end_str: Optional[str] = None,
    now_time: Optional[time] = None,
) -> bool:
    """Check if current local time is within quiet hours (e.g. 22:00 to 07:00)."""
    try:
        if isinstance(start_or_settings, dict):
            if not start_or_settings.get("quiet_hours_enabled", True):
                return False
            start_str = start_or_settings.get("quiet_hours_start", "22:00")
            end_str = start_or_settings.get("quiet_hours_end", "07:00")
        else:
            start_str = str(start_or_settings)
            if end_str is None:
                end_str = "07:00"

        if now_time is None:
            now_time = datetime.now().time()
        start_parts = [int(p) for p in start_str.split(":")]
        end_parts = [int(p) for p in end_str.split(":")]
        start_t = dt_time(start_parts[0], start_parts[1])
        end_t = dt_time(end_parts[0], end_parts[1])

        if start_t <= end_t:
            return start_t <= now_time <= end_t
        else:
            return now_time >= start_t or now_time <= end_t
    except Exception:
        return False


def get_notification_settings(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load notification preferences from app_settings table."""
    target_db = db_path or DB_PATH
    defaults = {
        "user_name": "pant",
        "notifications_enabled": True,
        "windows_toasts_enabled": True,
        "notification_sound": "default",  # "default" | "silent" | "custom"
        "idle_alert_threshold_minutes": 3,
        "mismatch_grace_minutes": 2,
        "distraction_cooldown_minutes": 15,
        "missed_recovery_threshold_minutes": 30,
        "missed_recovery_enabled": True,
        "time_block_reminders_enabled": True,
        "time_block_autostart_focus": False,
        "quiet_hours_enabled": False,
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "overnight_suppression_enabled": True,
        "overnight_sleep_start": "23:00",
        "overnight_sleep_end": "07:00",
    }
    if not target_db.exists():
        return defaults

    try:
        conn = sqlite3.connect(str(target_db), timeout=3)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        conn.close()

        result = dict(defaults)
        for r in rows:
            k, v = r["key"], r["value"]
            if k in (
                "notifications_enabled",
                "windows_toasts_enabled",
                "missed_recovery_enabled",
                "time_block_reminders_enabled",
                "time_block_autostart_focus",
                "quiet_hours_enabled",
                "overnight_suppression_enabled",
            ):
                result[k] = v.lower() in ("true", "1", "yes")
            elif k in (
                "idle_alert_threshold_minutes",
                "mismatch_grace_minutes",
                "distraction_cooldown_minutes",
                "missed_recovery_threshold_minutes",
            ):
                try:
                    result[k] = int(v)
                except ValueError:
                    pass
            else:
                result[k] = v
        return result
    except Exception as e:
        logger.debug("Failed to read settings from db: %s", e)
        return defaults


# ---------------------------------------------------------------------------
# Native Toast Dispatching
# ---------------------------------------------------------------------------

def _play_custom_chime():
    """Play custom bundled chime sound via Windows multimedia."""
    try:
        import winsound
        if CHIME_PATH.exists():
            winsound.PlaySound(str(CHIME_PATH), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception as e:
        logger.debug("Could not play custom chime: %s", e)


def to_protocol_uri(raw_url_or_action: Optional[str]) -> str:
    """
    Ensure every notification launch URL and action argument uses the custom
    'timetracker://' protocol so Windows Shell activates Time Tracker AI directly
    without launching Google Chrome or Microsoft Edge.
    """
    if not raw_url_or_action:
        return "timetracker://navigate?action=overview"
    s = str(raw_url_or_action).strip()
    if s.lower().startswith("timetracker://"):
        return s
    if s.lower().startswith("timetracker:"):
        return "timetracker://" + s[len("timetracker:"):].lstrip("/")
    # Convert legacy http://localhost:... URLs
    if "://" in s:
        import urllib.parse
        parsed = urllib.parse.urlsplit(s)
        query = parsed.query
        if query:
            return f"timetracker://navigate?{query}"
        path = parsed.path.strip("/")
        return f"timetracker://navigate?action={path or 'overview'}"
    if s.startswith("?"):
        return f"timetracker://navigate{s}"
    if "=" in s:
        return f"timetracker://navigate?{s}"
    return f"timetracker://navigate?action={s}"


def build_toast_xml(
    title: str,
    message: str,
    timestamp_str: Optional[str] = None,
    attribution: Optional[str] = None,
    launch_url: str = "timetracker://navigate?action=overview",
    action_text: Optional[str] = None,
    actions: Optional[List[Dict[str, str]]] = None,
    sound_mode: str = "default",
    scenario: str = "reminder",
) -> str:
    """
    Constructs a well-formed Windows Toast Generic XML payload.
    Supports scenario='reminder' to ensure desktop toast banners are pre-expanded,
    persistent, and given elevated delivery priority.
    """
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    safe_url = html.escape(launch_url)

    if timestamp_str is None:
        now_local = datetime.now()
        ts_text = now_local.strftime("%I:%M %p").lstrip("0")
    else:
        ts_text = timestamp_str
    safe_timestamp = html.escape(ts_text) if ts_text else ""

    icon_tag = ""
    if PNG_PATH.exists():
        png_uri = PNG_PATH.resolve().as_uri()
        icon_tag = f'<image placement="appLogoOverride" hint-crop="circle" src="{png_uri}" />'

    if sound_mode == "silent":
        audio_tag = '<audio silent="true" />'
    elif sound_mode in ("custom", "gentle"):
        audio_tag = '<audio silent="true" />'
        _play_custom_chime()
    else:
        audio_tag = '<audio src="ms-winsoundevent:Notification.Default" />'

    actions_xml = ""
    if actions and len(actions) > 0:
        action_elements = []
        for act in actions:
            act_content = html.escape(act.get("content", ""))
            act_args = html.escape(act.get("arguments", launch_url))
            icon_attr = ""
            icon_name = act.get("icon")
            if icon_name and (ASSETS_DIR / icon_name).exists():
                icon_uri = (ASSETS_DIR / icon_name).resolve().as_uri()
                icon_attr = f'imageUri="{icon_uri}"'
            action_elements.append(
                f'<action content="{act_content}" arguments="{act_args}" {icon_attr} activationType="protocol" />'
            )
        actions_inner = "\n            ".join(action_elements)
        actions_xml = f"<actions>\n            {actions_inner}\n        </actions>"
    elif action_text and launch_url:
        safe_action = html.escape(action_text)
        actions_xml = f'<actions><action content="{safe_action}" arguments="{safe_url}" activationType="protocol" /></actions>'

    if timestamp_str and attribution:
        meta_line = f"{timestamp_str} · {attribution}"
        timestamp_tag = f'<text>{html.escape(meta_line)}</text>'
    elif timestamp_str:
        timestamp_tag = f'<text>{safe_timestamp}</text>'
    else:
        timestamp_tag = ""

    attrib_tag = f'<text placement="attribution">{html.escape(attribution)}</text>' if attribution else ""

    # Clean valid root toast tag with scenario support
    scenario_attr = f'scenario="{scenario}"' if scenario else ""

    xml_text = f"""<toast launch="{safe_url}" {scenario_attr}>
    <visual>
        <binding template="ToastGeneric">
            {icon_tag}
            <text>{safe_title}</text>
            <text>{safe_message}</text>
            {timestamp_tag}
            {attrib_tag}
        </binding>
    </visual>
    {audio_tag}
    {actions_xml}
</toast>"""
    return xml_text


def _dispatch_powershell_toast(
    title: str,
    message: str,
    timestamp_str: Optional[str] = None,
    attribution: Optional[str] = None,
    launch_url: str = "http://localhost:5173",
    action_text: Optional[str] = None,
    actions: Optional[List[Dict[str, str]]] = None,
    sound_mode: str = "default",
    scenario: str = "reminder",
    tag: Optional[str] = None,
    group: str = "time_tracker",
) -> Dict[str, Any]:
    """
    Execute PowerShell WinRT script to display toast notification banner.
    Stabilizes process lifespan with Start-Sleep -Milliseconds 2500 so Windows Shell
    has ample time to bind and display the visual banner without dropping it.
    """
    attempt_time = datetime.now().isoformat()
    if sys.platform != "win32":
        with _diag_lock:
            _diagnostics_state["last_attempt_time"] = attempt_time
            _diagnostics_state["last_submission_result"] = "unsupported_platform"
            _diagnostics_state["last_delivery_error"] = "Non-Windows platform"
        return {"success": False, "error": "Non-Windows platform"}

    register_windows_app_identity()
    xml_text = build_toast_xml(
        title=title,
        message=message,
        timestamp_str=timestamp_str,
        attribution=attribution,
        launch_url=launch_url,
        action_text=action_text,
        actions=actions,
        sound_mode=sound_mode,
        scenario=scenario,
    )

    tag_assignment = ""
    if tag:
        safe_tag = tag.replace("'", "")
        safe_group = group.replace("'", "")
        tag_assignment = f"""
$toast.Tag = '{safe_tag}'
$toast.Group = '{safe_group}'
"""

    ps_code = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlCommands, ContentType = WindowsRuntime] | Out-Null

$xmlText = @'
{xml_text}
'@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($xmlText)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.Priority = [Windows.UI.Notifications.ToastNotificationPriority]::High
$toast.ExpirationTime = [DateTimeOffset]::Now.AddMinutes(15)
{tag_assignment}

$submissionStatus = "submitted"
$notifierSetting = "Unknown"

try {{
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}')
    $notifierSetting = [string]$notifier.Setting
    $notifier.Show($toast)
}} catch {{
    try {{
        $fallback = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe')
        $notifierSetting = [string]$fallback.Setting
        $fallback.Show($toast)
        $submissionStatus = "fallback_powershell"
    }} catch {{
        $submissionStatus = "failed"
        Write-Error $_.Exception.Message
        exit 1
    }}
}}

Write-Output "STATUS:$submissionStatus|SETTING:$notifierSetting"

# Process Lifespan Stabilization:
Start-Sleep -Milliseconds 2500
"""

    encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
    creationflags = 0x08000000  # CREATE_NO_WINDOW

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        is_success = proc.returncode == 0

        notifier_setting = "Enabled"
        submission_status = "submitted"
        for line in stdout.splitlines():
            if line.startswith("STATUS:"):
                parts = line.split("|")
                submission_status = parts[0].replace("STATUS:", "").strip()
                if len(parts) > 1:
                    notifier_setting = parts[1].replace("SETTING:", "").strip()

        with _diag_lock:
            _diagnostics_state["last_attempt_time"] = attempt_time
            _diagnostics_state["last_title"] = title
            _diagnostics_state["last_scenario"] = scenario
            if is_success:
                _diagnostics_state["last_submission_result"] = submission_status
                _diagnostics_state["last_delivery_error"] = None
                _diagnostics_state["total_dispatched"] += 1
            else:
                _diagnostics_state["last_submission_result"] = "failed"
                _diagnostics_state["last_delivery_error"] = stderr or f"Process exited with code {proc.returncode}"
                _diagnostics_state["total_failed"] += 1

        return {
            "success": is_success,
            "status": submission_status,
            "notifier_setting": notifier_setting,
            "error": stderr if not is_success else None,
        }
    except Exception as e:
        logger.error("Failed to invoke PowerShell WinRT toast: %s", e)
        with _diag_lock:
            _diagnostics_state["last_attempt_time"] = attempt_time
            _diagnostics_state["last_submission_result"] = "failed"
            _diagnostics_state["last_delivery_error"] = str(e)
            _diagnostics_state["total_failed"] += 1
        return {"success": False, "status": "exception", "error": str(e)}


_last_toast_dispatch_time: float = 0.0
_toast_throttle_lock = threading.Lock()
MIN_TOAST_INTERVAL_SECONDS: float = 20.0  # Avoid bursts of routine toasts within 20s


def remove_windows_toast(tag: str, group: str = "time_tracker") -> bool:
    """
    Remove an active or pending notification banner from the screen and Windows Action Center.
    Uses native Windows.UI.Notifications.ToastNotificationManager.History.Remove.
    """
    if sys.platform != "win32" or not tag:
        return False
    safe_tag = tag.replace("'", "")
    safe_group = group.replace("'", "")
    ps_code = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
try {{
    [Windows.UI.Notifications.ToastNotificationManager]::History.Remove('{safe_tag}', '{safe_group}', '{AUMID}')
}} catch {{
    try {{
        [Windows.UI.Notifications.ToastNotificationManager]::History.Remove('{safe_tag}')
    }} catch {{
        exit 0
    }}
}}
"""
    encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
    creationflags = 0x08000000
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=5,
            creationflags=creationflags,
        )
        return True
    except Exception:
        return False


def reset_rate_limit_state():
    """Reset rate-limiting timestamp for testing and clean test isolation."""
    global _last_toast_dispatch_time
    with _toast_throttle_lock:
        _last_toast_dispatch_time = 0.0


def send_windows_toast(
    title: str,
    message: str,
    timestamp_str: Optional[str] = None,
    attribution: Optional[str] = None,
    launch_url: str = "http://localhost:5173",
    action_text: Optional[str] = None,
    actions: Optional[List[Dict[str, str]]] = None,
    sound_mode: Optional[str] = None,
    scenario: str = "reminder",
    force: bool = False,
    tag: Optional[str] = None,
    group: str = "time_tracker",
    db_path: Optional[Path] = None,
) -> bool:
    """
    Queue and send a native Windows desktop notification asynchronously.
    Enforces quiet hours, user preferences, sound mode, rate limiting, and branded app identity.
    Uses scenario='reminder' by default for elevated display persistence and banner reliability.
    """
    if sys.platform != "win32":
        return False

    settings = get_notification_settings(db_path)
    if not force:
        if not settings.get("notifications_enabled", True):
            return False
        if not settings.get("windows_toasts_enabled", True):
            return False
        if settings.get("quiet_hours_enabled", False):
            start = settings.get("quiet_hours_start", "22:00")
            end = settings.get("quiet_hours_end", "07:00")
            if _is_in_quiet_hours(start, end):
                return False

    # Rate limiting: throttle routine alerts to prevent bursts of desktop toasts
    global _last_toast_dispatch_time
    now_ts = time.time()
    with _toast_throttle_lock:
        if not force and (now_ts - _last_toast_dispatch_time < MIN_TOAST_INTERVAL_SECONDS):
            logger.info("Desktop toast rate-limited: only %0.1fs since previous notification", now_ts - _last_toast_dispatch_time)
            return False
        _last_toast_dispatch_time = now_ts

    effective_sound = sound_mode or settings.get("notification_sound", "default")
    protocol_launch_url = to_protocol_uri(launch_url)
    protocol_actions = None
    if actions:
        protocol_actions = []
        for act in actions:
            act_copy = dict(act)
            raw_args = act_copy.get("arguments", protocol_launch_url)
            act_copy["arguments"] = to_protocol_uri(raw_args)
            protocol_actions.append(act_copy)

    def _worker():
        try:
            _dispatch_powershell_toast(
                title=title,
                message=message,
                timestamp_str=timestamp_str,
                attribution=attribution,
                launch_url=protocol_launch_url,
                action_text=action_text,
                actions=protocol_actions,
                sound_mode=effective_sound,
                scenario=scenario,
                tag=tag,
                group=group,
            )
        except Exception as e:
            logger.error("Background toast error: %s", e)

    _executor.submit(_worker)
    return True


def dispatch_test_toast(
    title: str = "[TEST] Desktop Notification Test",
    message: str = "Time Tracker AI desktop notification system is working properly.",
    scenario: str = "reminder",
    actions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Synchronously triggers an explicitly marked test toast and returns structured delivery diagnostics.
    Never uses real productivity schedules or misleading tasks.
    """
    if actions is None:
        actions = [
            {
                "content": "Open App",
                "arguments": "timetracker://navigate?action=overview",
            },
            {
                "content": "Dismiss Test",
                "arguments": "timetracker://action?name=dismiss",
            },
        ]

    with _diag_lock:
        _diagnostics_state["last_attempt_time"] = datetime.now().isoformat()
    res = _dispatch_powershell_toast(
        title=title,
        message=message,
        launch_url="timetracker://navigate?action=overview",
        actions=actions,
        tag="test_notification",
        group="time_tracker",
        scenario=scenario,
    )
    with _diag_lock:
        if res.get("success"):
            _diagnostics_state["last_submission_result"] = "submitted"
        else:
            _diagnostics_state["last_submission_result"] = "failed"
            _diagnostics_state["last_delivery_error"] = res.get("error")
    return res


# ---------------------------------------------------------------------------
# Diagnostics & System State Inspection
# ---------------------------------------------------------------------------

def get_windows_notification_diagnostics(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Inspects full Windows notification pipeline health:
    - Settings toggles
    - Registry AUMID & ShowBanner keys
    - Start Menu shortcut presence & target
    - Windows NotificationSetting enum (Enabled / DisabledForApplication)
    - SHQueryUserNotificationState (Detects Focus Assist, DND, or Fullscreen)
    - Action Center unread items count
    - Actionable troubleshooting advice
    """
    settings = get_notification_settings(db_path)
    is_win32 = sys.platform == "win32"

    diag_data: Dict[str, Any] = {
        "platform": sys.platform,
        "is_windows": is_win32,
        "notifications_enabled": settings.get("notifications_enabled", True),
        "windows_toasts_enabled": settings.get("windows_toasts_enabled", True),
        "aumid": AUMID,
        "aumid_registered": False,
        "show_banner_registry": False,
        "shortcut_installed": False,
        "shortcut_target": None,
        "notifier_setting": "Unknown",
        "user_notification_state": "Unknown",
        "action_center_count": 0,
        "troubleshooting_hints": [],
    }

    with _diag_lock:
        diag_data["last_attempt_time"] = _diagnostics_state["last_attempt_time"]
        diag_data["last_submission_result"] = _diagnostics_state["last_submission_result"]
        diag_data["last_delivery_error"] = _diagnostics_state["last_delivery_error"]
        diag_data["total_dispatched"] = _diagnostics_state["total_dispatched"]
        diag_data["total_failed"] = _diagnostics_state["total_failed"]

    if not is_win32:
        diag_data["troubleshooting_hints"].append("Native desktop toast banners require Windows 10 or 11.")
        return diag_data

    # 1. Check Registry AUMID & Settings
    try:
        import winreg
        classes_key = f"Software\\Classes\\AppUserModelId\\{AUMID}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, classes_key) as k:
            diag_data["aumid_registered"] = True
    except Exception:
        diag_data["aumid_registered"] = False

    try:
        import winreg
        notif_key = f"Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings\\{AUMID}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, notif_key) as k:
            val, _ = winreg.QueryValueEx(k, "ShowBanner")
            diag_data["show_banner_registry"] = val == 1
    except Exception:
        diag_data["show_banner_registry"] = False

    # 2. Check Start Menu Shortcut
    try:
        from win32com.shell import shell, shellcon
        import win32com.client
        programs_folder = shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0)
        lnk_path = os.path.join(programs_folder, f"{APP_NAME}.lnk")
        if os.path.exists(lnk_path):
            diag_data["shortcut_installed"] = True
            wscript = win32com.client.Dispatch("WScript.Shell")
            sc = wscript.CreateShortCut(lnk_path)
            diag_data["shortcut_target"] = f"{sc.TargetPath} {sc.Arguments}".strip()
    except Exception as e:
        logger.debug("Failed checking shortcut: %s", e)

    # 3. Query WinRT Notifier Setting & User Notification State via quick PowerShell
    ps_inspect = f"""
$setting = "Unknown"
try {{
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $n = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}')
    $setting = [string]$n.Setting
}} catch {{}}

$qunsState = "Unknown"
try {{
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Quns {{
    [DllImport("shell32.dll")]
    public static extern int SHQueryUserNotificationState(out int pquns);
}}
"@
    $s = 0
    [Quns]::SHQueryUserNotificationState([ref]$s) | Out-Null
    switch ($s) {{
        1 {{ $qunsState = "QUNS_NOT_PRESENT" }}
        2 {{ $qunsState = "QUNS_BUSY" }}
        3 {{ $qunsState = "QUNS_RUNNING_D3D_FULL_SCREEN" }}
        4 {{ $qunsState = "QUNS_PRESENTATION_MODE" }}
        5 {{ $qunsState = "QUNS_ACCEPTS_NOTIFICATIONS" }}
        6 {{ $qunsState = "QUNS_QUIET_TIME" }}
        7 {{ $qunsState = "QUNS_APP" }}
        Default {{ $qunsState = "STATE_$s" }}
    }}
}} catch {{}}

$histCount = 0
try {{
    $h = [Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory('{AUMID}')
    $histCount = $h.Count
}} catch {{}}

Write-Output "SETTING:$setting|QUNS:$qunsState|HIST:$histCount"
"""
    try:
        enc = base64.b64encode(ps_inspect.encode("utf-16le")).decode("ascii")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=0x08000000,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                if "SETTING:" in line and "QUNS:" in line:
                    parts = line.split("|")
                    diag_data["notifier_setting"] = parts[0].replace("SETTING:", "").strip()
                    diag_data["user_notification_state"] = parts[1].replace("QUNS:", "").strip()
                    try:
                        diag_data["action_center_count"] = int(parts[2].replace("HIST:", "").strip())
                    except ValueError:
                        pass
    except Exception as e:
        logger.debug("Failed querying WinRT notifier setting: %s", e)

    # 4. Actionable Troubleshooting Guidance
    hints = []
    if not diag_data["notifications_enabled"]:
        hints.append("Application notifications are currently disabled in Settings.")
    if not diag_data["windows_toasts_enabled"]:
        hints.append("Windows desktop toast banners are disabled in Settings.")

    if diag_data["notifier_setting"] == "DisabledForApplication":
        hints.append(
            "Windows has blocked notifications for Time Tracker AI. Go to Windows Settings → System → Notifications, find 'Time Tracker AI', and toggle it On."
        )
    elif diag_data["notifier_setting"] == "DisabledForUser":
        hints.append("Windows notifications are globally disabled for your Windows account.")

    if diag_data["user_notification_state"] == "QUNS_QUIET_TIME":
        hints.append(
            "Windows Focus Assist / Do Not Disturb is active. Visual banners are routed directly to Action Center. Alarms and Reminders will still display pre-expanded."
        )
    elif diag_data["user_notification_state"] in ("QUNS_BUSY", "QUNS_RUNNING_D3D_FULL_SCREEN"):
        hints.append(
            "A full-screen application or presentation is active. Windows suppresses non-critical toast banners to prevent disruption."
        )

    if not diag_data["show_banner_registry"]:
        hints.append("Registry ShowBanner setting was not found; running setup registration will configure it.")

    if not hints:
        hints.append("Windows notification platform is ready. Desktop toast banners and action buttons are active.")

    diag_data["troubleshooting_hints"] = hints
    return diag_data
