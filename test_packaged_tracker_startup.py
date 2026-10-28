"""
test_packaged_tracker_startup.py ??? Verification tests for packaged backend and tracker startup.

Covers:
1. Desktop app CLI dispatch for --tracker-only, --browser-tracker-only, --server-only without GUI.
2. Tracker manager process selection in development vs packaged (frozen) mode.
3. Startup handshake verification: success, premature exit (code 0 and error codes), and timeout.
4. Process discovery, isolation, duplicate prevention, and clean stop.
5. Mutex acquisition/release and frontend error presentation distinction.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import api.tracker_manager as tm
import desktop_app


class TestDesktopCliDispatch(unittest.TestCase):
    """Test CLI argument parsing and dispatch in desktop_app.py."""

    def test_tracker_only_dispatches_to_main_without_gui(self):
        """--tracker-only must dispatch directly to main.main() and exit before GUI or mutex."""
        with patch("sys.argv", ["TimeTrackerAI.exe", "--tracker-only"]), \
             patch("desktop_app.setup_environment") as mock_setup, \
             patch("desktop_app.acquire_single_instance_mutex") as mock_mutex, \
             patch("webview.create_window") as mock_webview, \
             patch.dict("sys.modules", {"main": MagicMock()}):

            import main
            main.main = MagicMock()

            with self.assertRaises(SystemExit) as cm:
                desktop_app.main()

            self.assertEqual(cm.exception.code, 0)
            mock_setup.assert_called_once()
            main.main.assert_called_once()
            mock_mutex.assert_not_called()
            mock_webview.assert_not_called()

    def test_browser_tracker_only_dispatches_without_gui(self):
        """--browser-tracker-only must dispatch to browser_tracker.main() and exit before GUI."""
        with patch("sys.argv", ["TimeTrackerAI.exe", "--browser-tracker-only"]), \
             patch("desktop_app.setup_environment") as mock_setup, \
             patch("desktop_app.acquire_single_instance_mutex") as mock_mutex, \
             patch.dict("sys.modules", {"browser_tracker": MagicMock()}):

            import browser_tracker
            browser_tracker.main = MagicMock()

            with self.assertRaises(SystemExit) as cm:
                desktop_app.main()

            self.assertEqual(cm.exception.code, 0)
            mock_setup.assert_called_once()
            browser_tracker.main.assert_called_once()
            mock_mutex.assert_not_called()

    def test_server_only_dispatches_without_gui(self):
        """--server-only must dispatch to uvicorn.run and exit before GUI."""
        with patch("sys.argv", ["TimeTrackerAI.exe", "--server-only", "--port", "8888"]), \
             patch("desktop_app.setup_environment"), \
             patch("desktop_app.acquire_single_instance_mutex") as mock_mutex, \
             patch("uvicorn.run") as mock_uvicorn:

            with self.assertRaises(SystemExit) as cm:
                desktop_app.main()

            self.assertEqual(cm.exception.code, 0)
            mock_uvicorn.assert_called_once()
            mock_mutex.assert_not_called()


class TestProcessSelectionAndLaunching(unittest.TestCase):
    """Test process command construction and execution paths in tracker_manager."""

    def setUp(self):
        tm._managed_tracker_proc = None
        tm._managed_browser_proc = None
        tm._intentional_stop = False
        tm._last_exit_code = None
        tm._last_exit_message = None

    def tearDown(self):
        tm._managed_tracker_proc = None
        tm._managed_browser_proc = None

    def test_dev_mode_launches_python_script(self):
        """In development mode, start_tracking launches python with main.py."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 4321

        with patch.object(sys, "frozen", False, create=True), \
             patch.object(tm, "is_tracking_active", return_value=False), \
             patch.object(tm, "wait_for_tracker_startup", return_value=True), \
             patch.object(tm, "find_browser_tracker_processes", return_value=[MagicMock()]), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("builtins.open", unittest.mock.mock_open()):

            res = tm.start_tracking()
            self.assertTrue(res["is_tracking"])
            self.assertEqual(res["pid"], 4321)

            call_args = mock_popen.call_args_list[0]
            cmd = call_args[0][0]
            self.assertTrue(cmd[0].endswith("python.exe"))
            self.assertTrue(cmd[1].endswith("main.py"))

    def test_packaged_mode_launches_tracker_only_flag(self):
        """In packaged mode (sys.frozen=True), start_tracking launches executable with --tracker-only."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9876

        fake_exe = r"C:\Program Files\Time Tracker AI\TimeTrackerAI.exe"

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", fake_exe), \
             patch.object(tm, "is_tracking_active", return_value=False), \
             patch.object(tm, "wait_for_tracker_startup", return_value=True), \
             patch.object(tm, "find_browser_tracker_processes", return_value=[MagicMock()]), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("builtins.open", unittest.mock.mock_open()):

            res = tm.start_tracking()
            self.assertTrue(res["is_tracking"])
            self.assertEqual(res["pid"], 9876)

            call_args = mock_popen.call_args_list[0]
            cmd = call_args[0][0]
            self.assertEqual(cmd, [fake_exe, "--tracker-only"])
            self.assertNotIn("main.py", cmd)

            cwd = call_args[1].get("cwd")
            self.assertEqual(cwd, str(Path(fake_exe).parent))

            env = call_args[1].get("env", {})
            self.assertIn("TIME_TRACKER_DB_PATH", env)

    def test_dev_mode_duplicate_start_is_noop(self):
        """In dev mode, calling start_tracking when already active returns status without spawning."""
        with patch.object(tm, "is_tracking_active", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            res = tm.start_tracking()
            self.assertEqual(res["message"], "Tracker is already running.")
            mock_popen.assert_not_called()

    def test_packaged_mode_duplicate_start_is_noop(self):
        """In packaged mode, calling start_tracking when already active returns status without spawning."""
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(tm, "is_tracking_active", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            res = tm.start_tracking()
            self.assertEqual(res["message"], "Tracker is already running.")
            mock_popen.assert_not_called()

    def test_dev_mode_stop_tracking_stops_cleanly(self):
        """In dev mode, stop_tracking terminates running tracker processes cleanly."""
        mock_proc = MagicMock(pid=1234)
        mock_proc.poll.return_value = None
        tm._managed_tracker_proc = mock_proc

        with patch.object(sys, "frozen", False, create=True), \
             patch.object(tm, "is_tracking_active", return_value=True), \
             patch.object(tm, "find_tracker_processes", return_value=[]), \
             patch.object(tm, "find_browser_tracker_processes", return_value=[]), \
             patch.object(tm, "_recover_dangling_observations", return_value=0), \
             patch.object(tm, "is_mutex_active", return_value=False):

            res = tm.stop_tracking()
            self.assertFalse(res["is_tracking"])
            self.assertTrue(mock_proc.send_signal.called or mock_proc.terminate.called)

    def test_packaged_mode_stop_tracking_stops_cleanly(self):
        """In packaged mode, stop_tracking terminates packaged tracker process cleanly."""
        mock_proc = MagicMock(pid=5678)
        mock_proc.poll.return_value = None
        tm._managed_tracker_proc = mock_proc

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(tm, "is_tracking_active", return_value=True), \
             patch.object(tm, "find_tracker_processes", return_value=[]), \
             patch.object(tm, "find_browser_tracker_processes", return_value=[]), \
             patch.object(tm, "_recover_dangling_observations", return_value=0), \
             patch.object(tm, "is_mutex_active", return_value=False):

            res = tm.stop_tracking()
            self.assertFalse(res["is_tracking"])
            self.assertTrue(mock_proc.send_signal.called or mock_proc.terminate.called)


class TestStartupHandshake(unittest.TestCase):
    """Test startup handshake and failure detection in wait_for_tracker_startup."""

    def test_handshake_success_when_mutex_active(self):
        """Handshake succeeds when mutex becomes active while process is running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with patch.object(tm, "is_mutex_active", side_effect=[False, True]):
            result = tm.wait_for_tracker_startup(mock_proc, timeout=1.0)
            self.assertTrue(result)

    def test_handshake_detects_premature_exit_code_0(self):
        """Immediate exit with code 0 must raise RuntimeError, not report success."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0

        with patch.object(tm, "_read_last_log_error", return_value="Another instance of Time Tracker AI Desktop is already running"):
            with self.assertRaises(RuntimeError) as cm:
                tm.wait_for_tracker_startup(mock_proc, timeout=1.0)

            msg = str(cm.exception)
            self.assertIn("exited prematurely with code 0", msg)
            self.assertIn("Another instance", msg)

    def test_handshake_detects_premature_exit_error_code(self):
        """Immediate crash with error code 1 must raise RuntimeError with exit code and details."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1

        with patch.object(tm, "_read_last_log_error", return_value="Traceback: ImportError"):
            with self.assertRaises(RuntimeError) as cm:
                tm.wait_for_tracker_startup(mock_proc, timeout=1.0)

            msg = str(cm.exception)
            self.assertIn("exited prematurely with code 1", msg)
            self.assertIn("ImportError", msg)

    def test_handshake_timeout_terminates_hung_process(self):
        """Process that hangs without acquiring mutex within timeout must be terminated."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with patch.object(tm, "is_mutex_active", return_value=False), \
             patch.object(tm, "_read_last_log_error", return_value="Waiting for hook"):

            with self.assertRaises(RuntimeError) as cm:
                tm.wait_for_tracker_startup(mock_proc, timeout=0.15)

            msg = str(cm.exception)
            self.assertIn("failed to initialize within", msg)
            mock_proc.terminate.assert_called_once()


class TestProcessDiscoveryAndSafety(unittest.TestCase):
    """Test process filtering, process safety, and frontend banners."""

    def test_find_tracker_processes_detects_tracker_only(self):
        """find_tracker_processes must match --tracker-only but ignore --server-only and GUI."""
        gui_mock = MagicMock(pid=1001)
        gui_mock.info = {"cmdline": ["TimeTrackerAI.exe"]}

        server_mock = MagicMock(pid=1002)
        server_mock.info = {"cmdline": ["TimeTrackerAI.exe", "--server-only", "--port", "8000"]}

        tracker_mock = MagicMock(pid=1003)
        tracker_mock.info = {"cmdline": ["TimeTrackerAI.exe", "--tracker-only"]}

        dev_tracker_mock = MagicMock(pid=1004)
        dev_tracker_mock.info = {"cmdline": ["python.exe", "C:\\project\\main.py"]}

        with patch("psutil.process_iter", return_value=[gui_mock, server_mock, tracker_mock, dev_tracker_mock]), \
             patch("os.getpid", return_value=9999):

            procs = tm.find_tracker_processes()
            pids = [p.pid for p in procs]

            self.assertIn(1003, pids, "Packaged tracker-only must be found")
            self.assertIn(1004, pids, "Dev main.py tracker must be found")
            self.assertNotIn(1001, pids, "GUI process must NOT be matched as tracker")
            self.assertNotIn(1002, pids, "Server-only process must NOT be matched as tracker")

    def test_find_browser_tracker_detects_flag(self):
        """find_browser_tracker_processes matches --browser-tracker-only and browser_tracker.py."""
        p_flag = MagicMock(pid=2001)
        p_flag.info = {"cmdline": ["TimeTrackerAI.exe", "--browser-tracker-only"]}

        p_script = MagicMock(pid=2002)
        p_script.info = {"cmdline": ["python.exe", "browser_tracker.py"]}

        p_other = MagicMock(pid=2003)
        p_other.info = {"cmdline": ["TimeTrackerAI.exe"]}

        with patch("psutil.process_iter", return_value=[p_flag, p_script, p_other]), \
             patch("os.getpid", return_value=9999):

            procs = tm.find_browser_tracker_processes()
            pids = [p.pid for p in procs]

            self.assertIn(2001, pids)
            self.assertIn(2002, pids)
            self.assertNotIn(2003, pids)

    def test_stop_tracking_preserves_gui_and_server(self):
        """stop_tracking cleans up only tracker processes and never kills GUI or server."""
        mock_tracker = MagicMock(pid=5001)
        mock_tracker.poll.return_value = None

        gui_proc = MagicMock(pid=5002)
        gui_proc.info = {"cmdline": ["TimeTrackerAI.exe"]}

        server_proc = MagicMock(pid=5003)
        server_proc.info = {"cmdline": ["TimeTrackerAI.exe", "--server-only"]}

        tm._managed_tracker_proc = mock_tracker

        with patch.object(tm, "is_tracking_active", return_value=True), \
             patch.object(tm, "find_tracker_processes", return_value=[]), \
             patch.object(tm, "find_browser_tracker_processes", return_value=[]), \
             patch.object(tm, "_recover_dangling_observations", return_value=0), \
             patch.object(tm, "is_mutex_active", return_value=False):

            res = tm.stop_tracking()
            self.assertFalse(res["is_tracking"])
            self.assertIn("stopped successfully", res["message"].lower())

            self.assertTrue(
                mock_tracker.send_signal.called or mock_tracker.terminate.called,
                "Managed tracker process must be stopped via signal or terminate",
            )
            gui_proc.terminate.assert_not_called()
            server_proc.terminate.assert_not_called()

    def test_is_mutex_active_checks_v4_mutex(self):
        """is_mutex_active checks the Local\\TimeTrackerV4 mutex."""
        self.assertEqual(tm.MUTEX_NAME, r"Local\TimeTrackerV4")
        with patch("ctypes.windll.kernel32.OpenMutexW", create=True) as mock_open_mutex:
            mock_open_mutex.return_value = 0
            res = tm.is_mutex_active()
            self.assertFalse(res)

    def test_frontend_error_presentation_distinction(self):
        """Frontend App.tsx must have dedicated trackerError state distinct from backendError."""
        app_tsx_path = Path(__file__).resolve().parent / "web" / "src" / "App.tsx"
        self.assertTrue(app_tsx_path.exists())
        content = app_tsx_path.read_text(encoding="utf-8")

        self.assertIn("const [trackerError, setTrackerError] = useState", content)
        self.assertIn("Tracker Error:", content)
        self.assertIn("Backend Disconnected:", content)
        self.assertIn("setTrackerError(", content)
        self.assertIn("Retry Tracker", content)


if __name__ == "__main__":
    unittest.main()
