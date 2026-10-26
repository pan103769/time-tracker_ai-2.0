# -*- mode: python ; coding: utf-8 -*-
"""
TimeTrackerAI.spec — PyInstaller build specification for Time Tracker AI 2 desktop app.
Packages FastAPI backend, PyWebView GUI, tracking engine, and React frontend into a standalone Windows app.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT = Path.cwd()

datas = [
    (str(ROOT / 'web' / 'dist'), 'web/dist'),
    (str(ROOT / 'assets'), 'assets'),
    (str(ROOT / 'widget_config.json'), '.'),
]

# Collect pywebview and pythonnet data files if present
datas += collect_data_files('webview')

hiddenimports = [
    # Uvicorn & ASGI
    'uvicorn',
    'uvicorn.config',
    'uvicorn.main',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    # FastAPI & Starlette
    'fastapi',
    'fastapi.staticfiles',
    'fastapi.responses',
    'fastapi.middleware.cors',
    'starlette',
    'starlette.staticfiles',
    'starlette.responses',
    'starlette.routing',
    'pydantic',
    # PyWebView & Pythonnet
    'webview',
    'webview.platforms',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'pythonnet',
    'clr_loader',
    'cffi',
    '_cffi_backend',
    # Database & System APIs
    'sqlite3',
    'psutil',
    'PIL',
    'PIL.ImageGrab',
    'win32gui',
    'win32con',
    'win32process',
    'win32api',
    # Application modules
    'activity_report',
    'ai_timeline',
    'browser_tracker',
    'main',
    'widget',
    'desktop_app',
]

# Collect all api submodules dynamically
hiddenimports += collect_submodules('api')

a = Analysis(
    ['desktop_app.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy',
        'IPython',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TimeTrackerAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'assets' / 'time_tracker_ai.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TimeTrackerAI',
)

