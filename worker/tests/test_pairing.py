import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import MagicMock, patch
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_client import APIClient, APIError
from state_store import load_state
from config import Config
from pairing_client import PairingClient, normalize_api_url
from desktop_runtime import DesktopRuntime, worker_environment
from agent import WorkerAgent
from resource_limits import validate_limits


def reply(data, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = data
    return response


class PairingTests(unittest.TestCase):
    def session(self):
        return dict(pairing_id=str(uuid.uuid4()), pairing_code='Ab1_-Z9q', pairing_secret='s' * 43, state='WAITING',
            expires_at='2030-01-01T00:00:00Z', grid_name='Test grid', worker_name='Owner laptop')

    def approved(self):
        return dict(state='APPROVED', node_id=str(uuid.uuid4()), node_secret='n' * 43, enrollment_mode='paired')

    def test_url_requires_trusted_transport_and_rejects_credential_urls(self):
        self.assertEqual(normalize_api_url('https://GRID.example/api/'), 'https://grid.example/api')
        self.assertEqual(normalize_api_url('http://localhost:18080/api', True), 'http://localhost:18080/api')
        for value in ['http://grid.example/api', 'https://user:secret@grid.example/api', 'https://grid.example/api?token=secret',
                      'https://grid.example/api#fragment', 'https://grid.example/other', 'https://grid.example:99999/api', 'file:///api']:
            with self.assertRaises(ValueError): normalize_api_url(value)

    def test_lost_approval_response_recovers_same_session_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            client = PairingClient('https://grid.example/api', temp)
            session, approved = self.session(), self.approved()
            with patch('pairing_client.requests.request', return_value=reply(session, 201)):
                client.begin({'capabilities': ['dummy']})
            with patch('pairing_client.requests.request', side_effect=requests.ConnectionError('lost response')):
                with self.assertRaises(APIError): client.decide(True)
            self.assertTrue(client.session_file.exists()); self.assertFalse(client.credentials_file.exists())
            recovered = PairingClient('https://grid.example/api', temp)
            with patch('pairing_client.requests.request', return_value=reply(approved)) as request:
                recovered.decide(True)
            self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer ' + session['pairing_secret'])
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            saved = load_state(recovered.credentials_file)
            self.assertEqual(saved['node_id'], approved['node_id'])
            self.assertEqual(saved['control_plane_url'], client.api_url)
            self.assertIsNone(recovered.session); self.assertFalse(recovered.session_file.exists())

    def test_failed_credential_write_retains_pairing_for_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            client = PairingClient('https://grid.example/api', temp)
            with patch('pairing_client.requests.request', return_value=reply(self.session(), 201)): client.begin({})
            approved = self.approved()
            with patch('pairing_client.requests.request', return_value=reply(approved)), patch('pairing_client.atomic_json', side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError): client.decide(True)
            self.assertTrue(client.session_file.exists()); self.assertIsNotNone(client.session)
            with patch('pairing_client.requests.request', return_value=reply(approved)): client.decide(True)
            self.assertEqual(load_state(client.credentials_file)['node_id'], approved['node_id'])

    def test_decline_never_writes_worker_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            client = PairingClient('https://grid.example/api', temp)
            with patch('pairing_client.requests.request', return_value=reply(self.session(), 201)): client.begin({})
            with patch('pairing_client.requests.request', return_value=reply({'state': 'DECLINED'})): client.decide(False)
            self.assertFalse(client.credentials_file.exists()); self.assertFalse(client.session_file.exists())

    def test_redirect_cannot_forward_private_session_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            client = PairingClient('https://grid.example/api', temp)
            with patch('pairing_client.requests.request', return_value=reply({}, 302)) as request:
                with self.assertRaises(APIError) as error: client.request('GET', '/pairing/test', secret='private')
            self.assertEqual(error.exception.status, 302)
            self.assertFalse(request.call_args.kwargs['allow_redirects'])

    def test_desktop_worker_rejects_script_identity_even_with_valid_secret(self):
        client = APIClient.__new__(APIClient); client.node_id, client.node_secret = 'node', 'secret'
        with patch.object(Config, 'REQUIRE_PAIRED_IDENTITY', True), patch.object(client, 'request', return_value={'enrollment_mode': 'legacy'}):
            with self.assertRaises(APIError): client.register(['dummy'])
        client.node_id = client.node_secret = None
        with patch.object(Config, 'REQUIRE_PAIRED_IDENTITY', True), patch.object(client, 'request') as request:
            with self.assertRaises(APIError): client.register(['dummy'])
            request.assert_not_called()

    def test_desktop_process_has_fixed_limits_and_no_shared_grid_tokens(self):
        with patch.dict('os.environ', {'ADMIN_TOKEN': 'admin', 'ENROLLMENT_TOKEN': 'enroll', 'WORKLOAD_CPUS': '99', 'EXECUTION_MODE': 'native'}):
            env = worker_environment('https://grid.example/api', Path('state'), 'Laptop')
        self.assertNotIn('ADMIN_TOKEN', env); self.assertNotIn('ENROLLMENT_TOKEN', env)
        self.assertEqual(env['WORKLOAD_CPUS'], '2'); self.assertEqual(env['WORKLOAD_MEMORY_LIMIT'], str(2 * 1024 ** 3))
        self.assertEqual(env['EXECUTION_MODE'], 'docker'); self.assertEqual(env['REQUIRE_PAIRED_IDENTITY'], 'true')

    def test_desktop_stop_request_cancels_only_its_agent_state(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Config, 'DATA_DIR', Path(temp)):
            runtime = DesktopRuntime('https://grid.example/api', temp, 'Laptop')
            runtime.process = MagicMock(); runtime.process.poll.return_value = None
            runtime.request_stop()
            agent = WorkerAgent.__new__(WorkerAgent); agent.stop, agent.cancel = threading.Event(), threading.Event(); agent.lock = threading.RLock()
            agent.local_stop_loop()
            self.assertTrue(agent.stop.is_set()); self.assertTrue(agent.cancel.is_set())
            runtime.process.terminate.assert_not_called(); runtime.process.kill.assert_not_called()

    def test_owner_limits_reject_invalid_and_over_capacity_values(self):
        for value in [None, {'cpu': True, 'memory_gb': 2}, {'cpu': float('nan'), 'memory_gb': 2},
                      {'cpu': 5, 'memory_gb': 2}, {'cpu': 1, 'memory_gb': 9}, {'cpu': 1, 'memory_gb': 0}]:
            with self.assertRaises(ValueError): validate_limits(value, cpu_max=4, memory_max=8)
        self.assertEqual(validate_limits({'cpu': 0.5, 'memory_gb': 0.75}), {'cpu': 0.5, 'memory_gb': 0.75})

    def test_selected_limits_survive_a_lost_approval_response(self):
        with tempfile.TemporaryDirectory() as temp:
            client = PairingClient('https://grid.example/api', temp)
            policy = {'cpu': 0.5, 'memory_gb': 1}
            with patch('pairing_client.requests.request', return_value=reply(self.session(), 201)):
                client.begin({'cpu_cores': 4, 'ram_gb': 8}, policy)
            recovered = PairingClient('https://grid.example/api', temp)
            with patch('pairing_client.requests.request', return_value=reply({**self.approved(), 'resource_limits': policy})) as request:
                recovered.decide(True)
            self.assertEqual(request.call_args.kwargs['json']['resource_limits'], policy)
            self.assertEqual(load_state(recovered.credentials_file)['resource_limits'], policy)

    def test_custom_limits_reach_the_docker_worker_environment(self):
        env = worker_environment('https://grid.example/api', Path('state'), 'Laptop', {'cpu': 0.5, 'memory_gb': 0.75})
        self.assertEqual(env['WORKLOAD_CPUS'], '0.5')
        self.assertEqual(env['WORKLOAD_MEMORY_LIMIT'], str(int(0.75 * 1024 ** 3)))


if __name__ == '__main__': unittest.main()
