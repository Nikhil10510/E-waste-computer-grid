"""Exercise actual Tk callbacks with mocked network/compute, not an owner's live consent."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import WorkerWindow


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
        self.until(lambda: self.spawn.called)
        saved = json.loads((Path(self.temp.name) / 'credentials.json').read_text())
        self.assertEqual(saved['node_id'], self.node_id)
        self.window.stop_button.invoke()
        self.assertTrue((Path(self.temp.name) / 'stop.request').exists())
        self.process.poll.return_value = 0
        self.until(lambda: self.window.runtime.process is None)
        self.process.poll.return_value = None
        self.window.start_button.invoke()
        self.assertEqual(self.spawn.call_count, 2)
        self.assertEqual(json.loads((Path(self.temp.name) / 'credentials.json').read_text())['node_id'], self.node_id)

    def test_decline_button_never_starts_a_worker(self):
        self.prepare(); self.invite(); self.window.popup_buttons[1].invoke()
        self.until(lambda: self.window.client.session is None and not self.window.busy)
        self.spawn.assert_not_called()
        self.assertFalse((Path(self.temp.name) / 'credentials.json').exists())

    def test_pause_and_resume_callbacks_persist_state_without_restarting_compute(self):
        self.prepare(); self.invite(); self.window.popup_buttons[0].invoke()
        self.until(lambda: self.spawn.called)
        self.window.pause_button.invoke()
        self.until(lambda: self.window.paused and not self.window.busy)
        self.assertTrue(json.loads((Path(self.temp.name) / 'credentials.json').read_text())['paused'])
        self.window.pause_button.invoke()
        self.until(lambda: not self.window.paused and not self.window.busy)
        self.assertFalse(json.loads((Path(self.temp.name) / 'credentials.json').read_text())['paused'])
        self.assertEqual(self.spawn.call_count, 1)


if __name__ == '__main__': unittest.main()
