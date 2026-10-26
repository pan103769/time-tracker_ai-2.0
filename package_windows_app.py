"""
package_windows_app.py — Reproducible Windows Packaging Script for Time Tracker AI 2.

Builds the frontend production distribution and bundles the standalone Windows executable
using PyInstaller into dist/TimeTrackerAI/TimeTrackerAI.exe.
"""

from __future__ import annotations

import os
import shutil
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


def build_frontend():
    """Build Vite frontend production distribution."""
    print("--- 1. Building Frontend Production Distribution ---", flush=True)
    web_dir = _ROOT / "web"
    cmd = ["npm", "run", "build"]
    shell = sys.platform == "win32"
    res = subprocess.run(cmd, cwd=str(web_dir), shell=shell)
    if res.returncode != 0:
        raise RuntimeError("Frontend production build failed. Please fix Vite/TypeScript errors first.")

    dist_index = web_dir / "dist" / "index.html"
    if not dist_index.exists():
        raise RuntimeError(f"Expected build artifact {dist_index} does not exist.")
    print("✓ Frontend built successfully into web/dist/\n", flush=True)


def run_pyinstaller():
    """Run PyInstaller with TimeTrackerAI.spec."""
    print("--- 2. Packaging Application with PyInstaller ---", flush=True)
    venv_pyinstaller = _ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
    pyinstaller_cmd = str(venv_pyinstaller) if venv_pyinstaller.exists() else "pyinstaller"

    spec_file = _ROOT / "TimeTrackerAI.spec"
    if not spec_file.exists():
        raise RuntimeError(f"Spec file {spec_file} not found.")

    cmd = [pyinstaller_cmd, "--clean", "--noconfirm", str(spec_file)]
    res = subprocess.run(cmd, cwd=str(_ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}.")

    out_exe = _ROOT / "dist" / "TimeTrackerAI" / "TimeTrackerAI.exe"
    if not out_exe.exists():
        raise RuntimeError(f"Expected packaged executable {out_exe} was not produced.")
    print(f"✓ Standalone executable generated at: {out_exe}\n", flush=True)
    return out_exe


def verify_packaged_output(out_exe: Path):
    """Safety and integrity checks on the packaged output directory."""
    print("--- 3. Verifying Packaged Distribution Integrity ---", flush=True)
    dist_dir = out_exe.parent

    # Check executable size
    size_mb = out_exe.stat().st_size / (1024 * 1024)
    print(f"Executable binary size: {size_mb:.2f} MB")

    # Check required asset directories
    bundled_web = dist_dir / "_internal" / "web" / "dist"
    if not bundled_web.exists():
        bundled_web = dist_dir / "web" / "dist"
    if not (bundled_web / "index.html").exists():
        print(f"WARNING: web/dist/index.html was not found in expected bundled path ({bundled_web})")
    else:
        print(f"✓ Bundled web frontend verified at: {bundled_web}")

    bundled_assets = dist_dir / "_internal" / "assets"
    if not bundled_assets.exists():
        bundled_assets = dist_dir / "assets"
    if not (bundled_assets / "time_tracker_ai.ico").exists():
        print(f"WARNING: time_tracker_ai.ico was not found in expected bundled assets ({bundled_assets})")
    else:
        print(f"✓ Bundled brand assets verified at: {bundled_assets}")

    # Safety: ensure no development database or credentials leaked into dist
    forbidden_files = ["tracker.db", ".env", "id_rsa"]
    for root, _, files in os.walk(dist_dir):
        for f in files:
            if f in forbidden_files:
                raise RuntimeError(f"SECURITY HAZARD: Found {f} inside packaged distribution {root}! Bundling personal databases or credentials is strictly prohibited.")

    print("✓ Security check passed: No development databases or credentials bundled.")
    print("\n--- Build Complete Successfully! ---")
    print(f"You can launch the packaged app at: {out_exe}")


def main():
    try:
        build_frontend()
        exe_path = run_pyinstaller()
        verify_packaged_output(exe_path)
    except Exception as e:
        print(f"\n[Packaging Error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
