import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import agent_command
from app_lifecycle import instance_lock, AppAlreadyRunning, running, request, shutdown_app
import windows_startup
from agent import WorkerAgent


class PackagingTests(unittest.TestCase):
    def test_frozen_helper_is_resolved_beside_executable_not_from_cwd(self):
        with tempfile.TemporaryDirectory(prefix='worker path ') as temp:
            folder = Path(temp); helper = folder / 'EWasteAgent.exe'; helper.write_bytes(b'fixture')
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(folder/'EWasteWorker.exe')):
                self.assertEqual(agent_command('--preflight'), [str(helper), '--preflight'])
                helper.unlink()
                with self.assertRaisesRegex(RuntimeError, 'helper is missing'): agent_command()

    def test_source_command_preserves_existing_agent_cli(self):
        with patch.object(sys, 'frozen', False, create=True):
            command = agent_command('--once')
            self.assertEqual(command[0], sys.executable)
            self.assertTrue(Path(command[1]).is_file())
            self.assertEqual(command[2], '--once')

    def test_instance_requests_wait_for_release_without_killing_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with instance_lock(directory):
                self.assertTrue(running(directory))
                with self.assertRaises(AppAlreadyRunning):
                    with instance_lock(directory): pass
                self.assertTrue(request(directory, 'show'))
                self.assertTrue((directory/'show.request').exists())
                self.assertFalse(shutdown_app(directory, timeout=0.02))
            self.assertFalse(running(directory))
            self.assertTrue(shutdown_app(directory, timeout=0.01))

    def test_shutdown_waits_for_verified_process_exit_after_lock_release(self):
        with tempfile.TemporaryDirectory() as temp:
            code = """import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app_lifecycle import instance_lock
d=Path(sys.argv[2])
with instance_lock(d, record_owner=True):
    print('READY',flush=True)
    while not (d/'shutdown.request').exists(): time.sleep(0.01)
time.sleep(0.35)
"""
            child = subprocess.Popen([sys.executable, '-c', code, str(Path(__file__).resolve().parents[1]), temp], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'READY')
                started = time.monotonic()
                self.assertTrue(shutdown_app(Path(temp), timeout=5))
                self.assertGreaterEqual(time.monotonic()-started, 0.25)
                # Windows venv has a redirector parent; the verified owner exits
                # first, then that launcher finishes returning its exit status.
                self.assertEqual(child.wait(timeout=2), 0)
            finally:
                if child.poll() is None: child.terminate(); child.wait(timeout=5)
                child.stdout.close()

    def test_shutdown_refuses_unverified_owner_without_sending_request(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with instance_lock(directory):
                (directory/'owner.json').write_text('{invalid')
                self.assertFalse(shutdown_app(directory, timeout=0.01))
                self.assertFalse((directory/'shutdown.request').exists())

    def test_owner_pid_reuse_cancels_instead_of_trusting_unrelated_process(self):
        agent = WorkerAgent.__new__(WorkerAgent); agent.stop = threading.Event(); agent.cancel = threading.Event()
        agent.lock = threading.RLock()
        with patch.dict(os.environ, {'EWASTE_OWNER_PID': '1234', 'EWASTE_OWNER_CREATED': '100'}), patch('psutil.Process') as process:
            process.return_value.create_time.return_value = 200
            agent.owner_liveness_loop()
        self.assertTrue(agent.stop.is_set()); self.assertTrue(agent.cancel.is_set())

    def test_owner_exit_cancels_owned_agent_without_killing_other_processes(self):
        agent = WorkerAgent.__new__(WorkerAgent); agent.stop = threading.Event(); agent.cancel = threading.Event()
        agent.lock = threading.RLock()
        with patch.dict(os.environ, {'EWASTE_OWNER_PID': '1234', 'EWASTE_OWNER_CREATED': '100'}), patch('psutil.Process') as process:
            process.return_value.create_time.return_value = 100
            process.return_value.is_running.return_value = False
            agent.owner_liveness_loop()
            process.return_value.kill.assert_not_called()
        self.assertTrue(agent.stop.is_set()); self.assertTrue(agent.cancel.is_set())

    @unittest.skipUnless(os.name == 'nt', 'Windows registry contract')
    def test_startup_uses_quoted_installed_path_and_refuses_foreign_entry(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', r'C:\App With Spaces\EWasteWorker.exe'):
            self.assertEqual(windows_startup.startup_command(), '"C:\\App With Spaces\\EWasteWorker.exe" --login-startup')
            with patch('windows_startup.read_entry', return_value='foreign-command'):
                with self.assertRaisesRegex(RuntimeError, 'Another install'): windows_startup.set_enabled(False)

    @unittest.skipUnless(os.name == 'nt', 'Windows registry isolated acceptance')
    def test_startup_enable_disable_readback_in_isolated_hkcu_key(self):
        import uuid
        import winreg
        key = r'Software\EWasteGridTest_' + uuid.uuid4().hex
        try:
            with patch.object(sys, 'frozen', True, create=True), patch.object(windows_startup, 'KEY', key):
                self.assertFalse(windows_startup.is_enabled())
                windows_startup.set_enabled(True)
                self.assertTrue(windows_startup.is_enabled())
                self.assertIn('--login-startup', windows_startup.read_entry())
                windows_startup.set_enabled(False)
                self.assertFalse(windows_startup.is_enabled())
        finally:
            try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except FileNotFoundError: pass
