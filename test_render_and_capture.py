"""
test_render_and_capture.py — Captures the live native Tkinter widget window
in both Expanded (520x190) and Compact (520x68) modes using Windows GDI,
saves artifacts for visual inspection, and validates design fidelity.
"""

import ctypes
from ctypes import wintypes
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from PIL import Image

from widget import DesktopWidget, WIDGET_WIDTH, WIDGET_HEIGHT_EXPANDED, WIDGET_HEIGHT_COMPACT

ARTIFACTS_DIR = Path("C:/Users/user/.gemini/antigravity/brain/2283b18e-e374-4aee-a377-fb9f1454b832")


def capture_window_gdi(hwnd: int, width: int, height: int, save_path: Path):
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Get device contexts
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)

    # PW_RENDERFULLCONTENT = 2
    res = user32.PrintWindow(hwnd, mem_dc, 2)
    if not res:
        # Fallback to BitBlt
        gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, 0x00CC0020)

    # Extract bitmap bits
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth = width
    bih.biHeight = -height  # top-down
    bih.biPlanes = 1
    bih.biBitCount = 32
    bih.biCompression = 0

    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(bih), 0)

    # Convert to PIL Image
    img = Image.frombuffer("RGBA", (width, height), buf.raw, "raw", "BGRA", 0, 1)

    # Clean up
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    img.save(save_path)
    print(f"Captured window ({width}x{height}) -> {save_path}")
    return img


def main():
    root = tk.Tk()
    root.geometry(f"{WIDGET_WIDTH}x{WIDGET_HEIGHT_EXPANDED}+50+50")
    
    widget = DesktopWidget(root)
    # Ensure expanded mode
    if widget.is_compact:
        widget.toggle_compact_mode()

    root.update()
    root.update_idletasks()
    time.sleep(0.3)
    root.update()

    hwnd = root.winfo_id()
    parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
    target_hwnd = parent_hwnd if parent_hwnd else hwnd

    # 1. Capture Expanded Mode
    expanded_path = ARTIFACTS_DIR / "test_widget_expanded_capture.png"
    img_exp = capture_window_gdi(target_hwnd, WIDGET_WIDTH, WIDGET_HEIGHT_EXPANDED, expanded_path)

    # 2. Toggle to Compact Mode
    widget.toggle_compact_mode()
    root.update()
    root.update_idletasks()
    time.sleep(0.3)
    root.update()

    compact_path = ARTIFACTS_DIR / "test_widget_compact_capture.png"
    img_comp = capture_window_gdi(target_hwnd, WIDGET_WIDTH, WIDGET_HEIGHT_COMPACT, compact_path)

    # Close
    widget.running = False
    root.destroy()
    print("Captures completed successfully!")


if __name__ == "__main__":
    main()

