"""
build_installer.py — Compile installer.iss using Inno Setup Compiler (ISCC).
"""

import os
import subprocess
import sys
from pathlib import Path

# Fix Windows console encoding for UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parent


def find_iscc() -> Path | None:
    """Find ISCC.exe in system PATH or standard installation directories."""
    # Check PATH first
    path_iscc = shutil_which("iscc.exe") or shutil_which("iscc")
    if path_iscc:
        return Path(path_iscc)

    # Standard candidate locations on Windows
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def shutil_which(cmd: str):
    import shutil
    return shutil.which(cmd)


def compile_installer():
    print("--- Compiling Windows Installer with Inno Setup ---", flush=True)
    iss_file = _ROOT / "installer.iss"
    if not iss_file.exists():
        raise FileNotFoundError(f"Inno Setup script {iss_file} not found.")

    dist_exe = _ROOT / "dist" / "TimeTrackerAI" / "TimeTrackerAI.exe"
    if not dist_exe.exists():
        raise FileNotFoundError(f"Packaged executable {dist_exe} not found. Run package_windows_app.py first.")

    iscc = find_iscc()
    if not iscc:
        print(
            "NOTE: Inno Setup compiler (ISCC.exe) was not found in PATH or standard Program Files directories.\n"
            "The installer script 'installer.iss' is ready.\n"
            "To build the installer, install Inno Setup 6 (https://jrsoftware.org/isdl.php) and run: ISCC.exe installer.iss",
            file=sys.stderr,
        )
        return False

    print(f"Found Inno Setup Compiler: {iscc}", flush=True)
    out_dir = _ROOT / "dist_installer"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(iscc), str(iss_file)]
    res = subprocess.run(cmd, cwd=str(_ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"ISCC compilation failed with exit code {res.returncode}")

    installer_exe = out_dir / "TimeTrackerAI_Setup_v2.0.0.exe"
    if installer_exe.exists():
        size_mb = installer_exe.stat().st_size / (1024 * 1024)
        print(f"✓ Installer successfully compiled: {installer_exe} ({size_mb:.2f} MB)")
        return True
    return False


if __name__ == "__main__":
    success = compile_installer()
    sys.exit(0 if success else 1)
