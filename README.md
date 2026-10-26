# Time Tracker AI 2.0

> **Intelligent, Privacy-First Productivity & Automated Activity Tracking Desktop App for Windows**

Time Tracker AI 2.0 is an intelligent, automated time and focus tracking platform built for Windows. It provides real-time window observation, semantic activity classification, structured time blocks, AI coaching insights, intelligent Windows toast notifications, and a standalone desktop user interface powered by PyWebView and React.

---

## Key Features

- **Automated Window & Browser Tracking**: Passively monitors active application windows and browser tabs with zero manual clock-in friction.
- **Dedicated Desktop App Chrome**: Frameless, sleek desktop window with custom window controls (minimize, maximize/restore, drag, close) adhering to the native Windows work area.
- **Focus Sessions & Time Blocks**: Plan, execute, duplicate, and analyze structured deep work time blocks with automatic start and schedule-mismatch recovery alerts.
- **Smart Windows Toast Notifications**: Context-sensitive reminders with native actionable buttons, intelligent deduplication, quiet hours, and 1-click snooze/action routing directly into the native app.
- **Missed-Activity Recovery**: Automatically detects idle gaps (e.g., away from computer or offline meetings) and prompts the user to categorize or skip when returning.
- **Daily AI Coach & Semantic Clustering**: Summarizes productivity trends, longest focus streaks, interruptors, and daily goal achievements.
- **Privacy First & Local Storage**: All activity logs, screenshots, and metrics remain strictly stored in local SQLite (`tracker.db`).

---

## Architecture Overview

```
Time Tracker AI 2.0
├── desktop_app.py           # PyWebView standalone Windows desktop application entrypoint
├── package_windows_app.py   # Automated packaging pipeline (Vite build + PyInstaller)
├── build_installer.py       # Inno Setup Windows installer compiler
├── installer.iss            # Inno Setup compilation script
├── TimeTrackerAI.spec       # PyInstaller bundle specification
├── main.py                  # Core background tracking daemon
├── widget.py                # Floating desktop mini-widget
├── api/                     # FastAPI backend architecture
│   ├── server.py            # REST API endpoints & lifecycle handlers
│   ├── tracker_manager.py   # Tracker subprocess controller
│   ├── notification_engine.py # Smart notification supervisor & rate limiter
│   ├── windows_notifier.py  # Native Windows PowerShell toast dispatcher
│   ├── ai_coach_engine.py   # AI insights & daily summary generation
│   ├── clustering.py        # Semantic activity clustering engine
│   ├── activity_intelligence.py # Category classification & window title analysis
│   ├── autostart.py         # Windows startup registry integration
│   ├── categories.py        # Category CRUD & custom keyword rules
│   ├── goals.py             # Daily work & focus goal progress
│   └── migrations.py        # SQLite schema migrations
├── assets/                  # Brand assets, icons, audio chimes, widget skins
├── web/                     # Modern React + TypeScript + Vite frontend
│   ├── src/                 # Dashboard views, components, and hooks
│   └── dist/                # Production build output bundled into desktop app
└── tests/ (test_*.py)       # Comprehensive test suite (360+ tests)
```

---

## Getting Started

### Prerequisites

- **OS**: Windows 10 or Windows 11 (64-bit)
- **Python**: 3.10 or 3.11
- **Node.js**: 18+ and npm
- **Inno Setup 6** (optional, for installer creation)

### Setup & Development

1. **Clone the repository**:
   ```bash
   git clone https://github.com/pan103769/time-tracker_ai-2.0.git
   cd time-tracker_ai-2.0
   ```

2. **Set up Python Virtual Environment**:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Install Frontend Dependencies**:
   ```bash
   cd web
   npm install
   cd ..
   ```

4. **Run in Development Mode**:
   ```bash
   # Terminal 1: Start backend server
   python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --reload

   # Terminal 2: Start Vite frontend
   npm --prefix web run dev

   # Terminal 3 (Optional): Launch desktop wrapper connected to Vite dev server
   python desktop_app.py --dev
   ```

---

## Desktop Packaging & Installer Build

### 1. Build Standalone Portable Executable
Run the reproducible packaging pipeline:
```bash
python package_windows_app.py
```
This compiles the Vite frontend into `web/dist/`, invokes PyInstaller with `TimeTrackerAI.spec`, and outputs the standalone application to `dist/TimeTrackerAI/TimeTrackerAI.exe`.

### 2. Build Single-File Windows Installer
Compile the setup wizard via Inno Setup:
```bash
python build_installer.py
```
This generates the full installer wizard at `dist_installer/TimeTrackerAI_Setup_v2.0.0.exe`.

---

## Running Tests

Run the full automated test suite (360+ tests):
```bash
python -m unittest discover -s . -p "test_*.py"
```

Verify frontend build:
```bash
npm --prefix web run build
```

---

## License

MIT License. Designed and engineered for high-performance productivity tracking.
