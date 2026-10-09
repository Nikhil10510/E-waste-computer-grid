import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state_store import load_state, save_state, update_state, StateError, WINDOWS
from api_client import APIClient
from config import Config


class StateTests(unittest.TestCase):
    def test_secret_roundtrip_and_no_plaintext_on_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credentials.json'
            data = {'node_secret': 'private-test-secret', 'name': 'Laptop café', 'paused': True}
            save_state(path, data)
            self.assertEqual(load_state(path), data)
            if WINDOWS:
                self.assertNotIn('private-test-secret', path.read_text())
                self.assertNotIn('Laptop', path.read_text())
                self.assertEqual(json.loads(path.read_text())['protection'], 'windows-dpapi-user')
            else: self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_legacy_migration_preserves_identity_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credentials.json'
            data = {'node_secret': 'old-private-secret', 'registration_key': 'stable', 'future_field': 'keep'}
            path.write_text(json.dumps(data))
            self.assertEqual(load_state(path), data)
            update_state(path, {'paused': True})
            self.assertEqual(load_state(path), {**data, 'paused': True})
            if WINDOWS: self.assertNotIn('old-private-secret', path.read_text())

    @unittest.skipUnless(WINDOWS, 'DPAPI is Windows-only')
    def test_encryption_failure_never_replaces_legacy_file_with_plaintext(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credentials.json'; original = '{"node_secret":"preserve"}'
            path.write_text(original)
            with patch('state_store._crypt', side_effect=StateError('Protection unavailable')):
                with self.assertRaises(StateError): load_state(path)
                with self.assertRaises(StateError): save_state(path, {'node_secret': 'new'})
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(Path(temp).glob('*.tmp')), [])

    def test_failed_atomic_replace_retains_previous_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credentials.json'; save_state(path, {'node_secret': 'keep'})
            original = path.read_bytes()
            with patch.object(Path, 'replace', side_effect=OSError('Disk write failed')):
                with self.assertRaises(OSError): save_state(path, {'node_secret': 'lost'})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(temp).glob('*.tmp')), [])

    @unittest.skipUnless(WINDOWS, 'DPAPI is Windows-only')
    def test_modified_encrypted_state_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credentials.json'; save_state(path, {'node_secret': 'private'})
            envelope = json.loads(path.read_text()); blob = bytearray(base64.b64decode(envelope['payload']))
            blob[len(blob)//2] ^= 128
            envelope['payload'] = base64.b64encode(blob).decode(); path.write_text(json.dumps(envelope))
            original = path.read_bytes()
            with self.assertRaises(StateError): load_state(path)
            self.assertEqual(path.read_bytes(), original)

    def test_unreadable_identity_stops_before_network_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Config, 'CREDENTIALS_FILE', Path(temp)/'credentials.json'):
            Config.CREDENTIALS_FILE.write_text('{broken')
            with patch('api_client.requests.request') as network:
                with self.assertRaises(StateError): APIClient()
            network.assert_not_called()
            self.assertEqual(Config.CREDENTIALS_FILE.read_text(), '{broken')

    def test_damaged_envelope_cannot_be_mistaken_for_legacy_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'credentials.json'
            path.write_text('{"format":"damaged","payload":"private"}')
            with self.assertRaises(StateError): load_state(path)
            self.assertIn('damaged', path.read_text())

    def test_oversized_state_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'credentials.json'; path.write_bytes(b' '*65537)
            with self.assertRaisesRegex(StateError, 'size limit'): load_state(path)

    def test_parallel_updates_do_not_lose_other_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'; save_state(path, {'identity': 'keep'})
            with ThreadPoolExecutor(max_workers=5) as workers:
                list(workers.map(lambda i: update_state(path, {str(i): i}), range(20)))
            self.assertEqual(load_state(path), {'identity': 'keep', **{str(i): i for i in range(20)}})

    def test_another_process_under_same_account_can_reconnect(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'credentials.json'; save_state(path, {'node_secret': 'test-only-secret'})
            code = "import sys; from state_store import load_state,update_state; p=sys.argv[1]; assert load_state(p)['node_secret']=='test-only-secret'; update_state(p,{'paused':True}); print('reconnected')"
            result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'reconnected')
            self.assertTrue(load_state(path)['paused'])


if __name__ == '__main__': unittest.main()
