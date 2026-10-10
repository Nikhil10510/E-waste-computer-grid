"""Exercise actual Tk callbacks with mocked network/compute, not an owner's live consent."""
import json
import gc
from pathlib import Path
import sys
import tempfile
import time
import threading
import tkinter as tk
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import WorkerWindow
from api_client import APIError
from state_store import load_state


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk(); self.root.withdraw()
        self.window = WorkerWindow(self.root, 'https://grid.example/api', False, Path(self.temp.name))
        self.node_id, self.pairing_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.paused = False
        self.policy = {'cpu': 1.0, 'memory_gb': 2.0}
        self.process = MagicMock(); self.process.poll.return_value = None
        self.requests = patch('pairing_client.requests.request', side_effect=self.request).start()
        self.preflight = patch('desktop_runtime.DesktopRuntime.preflight', return_value=['dummy', 'image_inference']).start()
        self.spawn = patch('desktop_runtime.subprocess.Popen', return_value=self.process).start()
        self.window.cpu_value.set('1'); self.window.memory_value.set('2')

    def request(self, method, url, **kwargs):
        if url.endswith('/pairing'):
            data = {'pairing_id': self.pairing_id, 'pairing_code': 'Ab1_-Z9q', 'pairing_secret': 's' * 43,
                'state': 'WAITING', 'grid_name': 'Test grid', 'worker_name': 'Test laptop'}
        elif url.endswith('/decision'):
            if kwargs['json']['decision'] == 'decline': data = {'state': 'DECLINED'}
            else:
                self.assertEqual(kwargs['json']['resource_limits'], self.policy)
                data = {'state': 'APPROVED', 'node_id': self.node_id, 'node_secret': 'n' * 43,
                    'resource_limits': self.policy, 'paused': False}
        elif url.endswith('/participation'):
            self.paused = kwargs['json']['paused']
            data = {'paused': self.paused, 'resource_limits': self.policy}
        else: data = {'state': 'WAITING'}
        response = MagicMock(status_code=200); response.json.return_value = data
        return response

    def until(self, condition):
        deadline = time.monotonic() + 4
        while not condition():
            self.root.update()
            if time.monotonic() >= deadline: self.fail(self.window.status.get())
            time.sleep(0.01)

    def tearDown(self):
        self.process.poll.return_value = 0
        self.until(lambda: not self.window.busy)
        for timer in self.root.tk.call('after', 'info'): self.root.after_cancel(timer)
        self.window.hide_invitation()
        if self.window.lock_context: self.window.lock_context.__exit__(None, None, None)
        self.root.destroy()
        patch.stopall()
        # Destroyed Tk widgets contain callback cycles. Collect them here on
        # their owning thread, before the next test starts a background worker.
        self.window = self.root = None
        gc.collect()
        self.temp.cleanup()

    def prepare(self):
        self.window.prepare_button.invoke()
        self.until(lambda: self.window.client is not None and self.window.client.session is not None and not self.window.busy)

    def invite(self):
        self.window.events.put(('poll', {'state': 'INVITED', 'grid_name': 'Test grid'}, None))
        self.until(lambda: self.window.popup is not None)

    def test_approval_button_saves_identity_before_launch_and_stop_restart_reuses_it(self):
        self.prepare(); self.invite()
        self.spawn.assert_not_called()
        self.assertFalse((Path(self.temp.name) / 'credentials.json').exists())
        self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called and not self.window.busy)
        saved = load_state(Path(self.temp.name) / 'credentials.json')
        self.assertEqual(saved['node_id'], self.node_id)
        self.window.stop_button.invoke()
        self.assertTrue((Path(self.temp.name) / 'stop.request').exists())
        self.process.poll.return_value = 0
        self.until(lambda: self.window.runtime.process is None)
        self.process.poll.return_value = None
        self.window.start_button.invoke()
        self.until(lambda: self.spawn.call_count == 2 and not self.window.busy)
        self.assertEqual(load_state(Path(self.temp.name) / 'credentials.json')['node_id'], self.node_id)

    def test_decline_button_never_starts_a_worker(self):
        self.prepare(); self.invite(); self.window.popup_buttons[1].invoke()
        self.until(lambda: self.window.client.session is None and not self.window.busy)
        self.spawn.assert_not_called()
        self.assertFalse((Path(self.temp.name) / 'credentials.json').exists())

    def test_import_progress_does_not_finish_background_work_or_enroll(self):
        entered, release = threading.Event(), threading.Event()
        def prepare(runtime, archive, cancel, progress):
            progress('Verifying offline archive: 50%'); entered.set()
            release.wait(3)
            return ['dummy', 'image_inference']
        with patch('desktop_runtime.DesktopRuntime.prepare_images', prepare):
            self.window.import_runtime('reviewed.tar')
            self.until(entered.is_set)
            self.until(lambda: self.window.status.get() == 'Verifying offline archive: 50%')
            self.assertTrue(self.window.busy)
            self.assertIsNone(self.window.client)
            self.spawn.assert_not_called()
            release.set(); self.until(lambda: not self.window.busy)
        self.assertIn('passed real preflight', self.window.status.get())

    def test_close_cancels_background_import_without_starting_compute(self):
        entered = threading.Event()
        def prepare(runtime, archive, cancel, progress):
            entered.set(); cancel.wait(3)
            from runtime_release import PreparationCancelled
            raise PreparationCancelled('cancelled')
        with patch('desktop_runtime.DesktopRuntime.prepare_images', prepare):
            self.window.import_runtime('reviewed.tar'); self.until(entered.is_set)
            self.window.finish_close = MagicMock()
            self.window.close()
            self.until(lambda: self.window.finish_close.called)
        self.assertTrue(self.window.preparation_cancel.is_set())
        self.spawn.assert_not_called(); self.assertIsNone(self.window.client)

    def test_cancelled_archive_picker_does_not_lock_the_wrong_grid(self):
        with patch('desktop.filedialog.askopenfilename', return_value=''):
            self.window.import_runtime()
        self.assertIsNone(self.window.lock_context)
        self.assertIsNone(self.window.runtime)
        self.assertFalse(self.window.busy)
        self.assertEqual(str(self.window.address['state']), 'normal')

    def test_expired_session_can_prepare_a_new_code_without_starting_compute(self):
        self.prepare(); self.invite()
        self.window.events.put(('poll', None, APIError('Pairing session expired', 410)))
        self.until(lambda: self.window.client.session is None and self.window.popup is None)
        self.assertFalse((Path(self.temp.name) / 'pairing.json').exists())
        self.assertEqual(str(self.window.prepare_button['state']), 'normal')
        self.spawn.assert_not_called()
        self.prepare()
        self.assertIsNotNone(self.window.client.session)
        self.spawn.assert_not_called()

    def test_pause_and_resume_callbacks_persist_state_without_restarting_compute(self):
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called and not self.window.busy)
        self.window.pause_button.invoke()
        self.until(lambda: self.window.paused and not self.window.busy)
        self.assertTrue(load_state(Path(self.temp.name) / 'credentials.json')['paused'])
        self.window.pause_button.invoke()
        self.until(lambda: not self.window.paused and not self.window.busy)
        self.assertFalse(load_state(Path(self.temp.name) / 'credentials.json')['paused'])
        self.assertEqual(self.spawn.call_count, 1)

    def test_slow_preflight_keeps_ui_responsive_and_close_waits_without_compute(self):
        waiting = threading.Event(); release = threading.Event()
        def slow():
            waiting.set(); release.wait(3); return ['dummy', 'image_inference']
        self.preflight.side_effect = slow
        self.window.prepare()
        self.until(waiting.is_set)
        tick = []
        self.root.after(10, lambda: tick.append(True))
        self.until(lambda: bool(tick))
        self.assertTrue(self.window.busy)
        self.window.finish_close = MagicMock()
        self.window.close(); self.root.update()
        self.window.finish_close.assert_not_called()
        release.set()
        self.until(lambda: self.window.finish_close.called)
        self.spawn.assert_not_called()

    def test_settings_restore_name_and_custom_limits_without_network_or_compute(self):
        self.window.name.set('Retired laptop'); self.window.cpu_value.set('0.5'); self.window.memory_value.set('0.75')
        self.prepare()
        self.window.name.set('changed'); self.window.cpu_value.set('2'); self.window.memory_value.set('2')
        self.requests.reset_mock()
        self.window.restore_settings('https://grid.example/api', False)
        self.assertEqual(self.window.name.get(), 'Retired laptop')
        self.assertEqual(self.window.cpu_value.get(), '0.5')
        self.assertEqual(self.window.memory_value.get(), '0.75')
        self.requests.assert_not_called(); self.spawn.assert_not_called()

    def test_connection_loss_does_not_discard_identity_or_grant_approval(self):
        self.prepare()
        self.window.events.put(('poll', None, APIError('Connection lost')))
        self.until(lambda: 'unavailable' in self.window.connection.get())
        self.assertIsNotNone(self.window.client.session)
        self.assertFalse(self.window.approved)
        self.spawn.assert_not_called()

    def test_revoke_notification_stops_owned_process_and_disables_restart(self):
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called and not self.window.busy)
        self.window.events.put(('session', None, APIError('Worker revoked', 403)))
        self.until(lambda: not self.window.approved)
        self.assertTrue((Path(self.temp.name)/'stop.request').exists())
        self.assertEqual(str(self.window.start_button['state']), 'disabled')

    def test_recovered_session_clears_network_error_and_displays_saved_pause(self):
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called and not self.window.busy)
        self.window.events.put(('session', None, APIError('Connection lost')))
        self.until(lambda: 'unavailable' in self.window.connection.get())
        self.window.events.put(('session', {'status':'OFFLINE', 'paused':True}, None))
        self.until(lambda: self.window.paused)
        self.assertIn('paused', self.window.connection.get())
        self.assertIn('restored', self.window.status.get())
        self.assertEqual(self.window.poll_delay, 3000)

    def test_disconnect_waits_for_stop_and_retains_approved_identity(self):
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called and not self.window.busy)
        self.window.reset_connection()
        self.assertTrue(self.window.disconnecting)
        self.assertIsNotNone(self.window.client)
        self.process.poll.return_value = 0
        self.until(lambda: self.window.client is None)
        self.assertTrue((Path(self.temp.name)/'credentials.json').exists())
        self.assertEqual(self.window.connection.get(), 'Not connected')

    def test_controls_stay_visible_at_small_window_size(self):
        self.root.deiconify(); self.root.geometry('520x440'); self.root.update()
        for button in (self.window.start_button,self.window.stop_button,self.window.pause_button,self.window.disconnect_button):
            self.assertTrue(button.winfo_ismapped())
            bottom = button.winfo_rooty() - self.root.winfo_rooty() + button.winfo_height()
            self.assertLessEqual(bottom, self.root.winfo_height())

    def test_stop_during_background_launch_is_applied_after_process_exists(self):
        waiting = threading.Event(); release = threading.Event()
        def slow_spawn(*args, **kwargs):
            waiting.set(); release.wait(3); return self.process
        self.spawn.side_effect = slow_spawn
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(waiting.is_set)
        self.window.stop_button.invoke()
        self.assertTrue(self.window.stop_after_start)
        release.set()
        self.until(lambda: (Path(self.temp.name)/'stop.request').exists())
        self.assertTrue(self.window.stopping)

    def test_failed_launch_leaves_saved_approval_and_allows_retry(self):
        self.spawn.side_effect = OSError('Unable to launch worker')
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called and not self.window.busy)
        self.assertFalse(self.window.starting)
        self.assertTrue(self.window.approved)
        self.assertEqual(str(self.window.start_button['state']), 'normal')
        self.assertEqual(str(self.window.stop_button['state']), 'disabled')
        self.assertEqual(load_state(Path(self.temp.name)/'credentials.json')['node_id'], self.node_id)

    def test_tray_actions_do_not_complete_inflight_preparation(self):
        self.window.busy = True
        self.window.events.put(('tray-action', 'open', None))
        self.root.update()
        self.window.drain_events()
        self.assertTrue(self.window.busy)
        self.window.busy = False

    def test_tray_failure_keeps_window_usable_without_starting_compute(self):
        with patch.object(self.window.tray, 'start', side_effect=RuntimeError('Tray unavailable')):
            self.window.minimize_to_tray()
        self.assertFalse(self.window.minimizing)
        self.assertEqual(self.root.state(), 'normal')
        self.spawn.assert_not_called()

    def test_window_hides_only_after_tray_ready_and_open_restores_it(self):
        with patch.object(self.window.tray, 'start'):
            self.window.minimize_to_tray()
            self.assertTrue(self.window.minimizing)
            self.window.events.put(('tray-ready', None, None))
            self.window.drain_events()
            self.assertEqual(self.root.state(), 'withdrawn')
            self.window.events.put(('tray-action', 'open', None))
            self.window.drain_events()
            self.assertEqual(self.root.state(), 'normal')

    def test_failed_startup_registration_reflects_actual_state(self):
        self.window.startup_enabled.set(True)
        with patch('windows_startup.set_enabled', side_effect=OSError('Registry denied')), patch('windows_startup.is_enabled', return_value=False):
            self.window.change_startup()
        self.assertFalse(self.window.startup_enabled.get())
        self.assertIn('Registry denied', self.window.status.get())
        self.spawn.assert_not_called()


if __name__ == '__main__': unittest.main()
