import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'worker'))
from config import Config
from state_store import load_state
from api_client import APIClient, APIError
from agent import WorkerAgent
from task_executor import TaskExecutor, TaskCancelled


class WorkerTests(unittest.TestCase):
    def test_watchdog_cancels_expired_lease_without_waiting_for_heartbeat_network(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.active_task = {'task_id': 'owned'}
        agent.lease_deadline = time.time() + 600
        agent.lease_monotonic_deadline = time.monotonic() + 0.05
        watchdog = threading.Thread(target=agent.lease_watchdog_loop)
        watchdog.start()
        try: self.assertTrue(agent.cancel.wait(0.6))
        finally: agent.stop.set(); watchdog.join(1)
        self.assertFalse(watchdog.is_alive())

    def test_confirmed_relative_lease_uses_monotonic_time_and_accounts_for_request_delay(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        with patch('agent.time.monotonic', return_value=100), patch('agent.time.time', return_value=999999999999):
            agent.confirm_lease({'lease_expires_at': '2026-10-10T00:00:00Z', 'lease_remaining_ms': 5000, '_request_elapsed_seconds': 2})
            self.assertEqual(agent.lease_monotonic_deadline, 103)
            self.assertFalse(agent.lease_expired())
        with patch('agent.time.monotonic', return_value=104), patch('agent.time.time', return_value=0):
            self.assertTrue(agent.lease_expired())

    def test_restart_authenticates_saved_identity_without_shared_enrollment(self):
        client = APIClient.__new__(APIClient)
        client.node_id, client.node_secret = 'approved-node', 'private-secret'
        with patch.object(client, 'request', return_value={'heartbeat_interval_seconds': 10}) as request, patch.object(client, 'save_credentials'):
            client.register(['dummy'])
        self.assertEqual(request.call_args.args[:2], ('POST', '/nodes/session'))
        self.assertNotIn('enrollment', request.call_args.kwargs)

    def test_saved_identity_cannot_be_sent_to_a_different_grid(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Config, 'CREDENTIALS_FILE', Path(temp) / 'credentials.json'):
            Config.CREDENTIALS_FILE.write_text(json.dumps({'control_plane_url': 'https://other.example/api',
                'node_id': 'private-node', 'node_secret': 'private-secret'}))
            with self.assertRaisesRegex(ValueError, 'different grid'):
                APIClient()
            self.assertEqual(load_state(Config.CREDENTIALS_FILE)['node_secret'], 'private-secret')

    def test_revoked_worker_stops_instead_of_re_enrolling(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.lock = threading.RLock()
        agent.api = MagicMock()
        agent.capabilities = ['dummy']
        agent.heartbeat_loop = MagicMock()
        agent.api.request_task.side_effect = APIError('Access revoked', 403)
        with self.assertRaises(APIError):
            agent.start()
        agent.api.register.assert_called_once()
        agent.api.clear_credentials.assert_not_called()
        self.assertTrue(agent.stop.is_set())

    def test_revoked_worker_fails_startup_without_retry_loop(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.lock = threading.RLock()
        agent.api = MagicMock()
        agent.capabilities = ['dummy']
        agent.api.register.side_effect = APIError('Approval required', 403)
        with self.assertRaises(APIError):
            agent.start()
        agent.api.register.assert_called_once()

    def test_startup_recovers_old_owned_containers_before_runtime_probe(self):
        order = []
        with patch('agent.APIClient'), patch('agent.TaskExecutor') as factory:
            factory.return_value.recover_containers.side_effect = lambda: order.append('recover')
            factory.return_value.capabilities.side_effect = lambda cancel: order.append('preflight') or ['dummy']
            agent = WorkerAgent()
            agent.shutdown()
        self.assertEqual(order, ['recover', 'preflight'])
        self.assertEqual(agent.capabilities, ['dummy'])

    def test_owner_stop_during_initial_runtime_probe_cancels_before_enrollment(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Config, 'DATA_DIR', Path(temp)), patch('agent.APIClient') as client, patch('agent.TaskExecutor') as factory:
            def preflight(cancel):
                (Path(temp) / 'stop.request').write_text('stop')
                self.assertTrue(cancel.wait(1))
                raise TaskCancelled('Owner stopped startup')
            factory.return_value.capabilities.side_effect = preflight
            with self.assertRaises(TaskCancelled): WorkerAgent()
            client.return_value.register.assert_not_called()

    def test_capabilities_only_advertise_runtimes_that_execute_successfully(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        executor.docker_client = None
        with patch.object(executor, 'verify_workload', side_effect=[None, RuntimeError('Broken ONNX runtime')]) as probe:
            self.assertEqual(executor.capabilities(), ['dummy'])
            self.assertEqual(probe.call_count, 2)
            self.assertIn('Broken ONNX', executor.preflight_errors['image_inference'])

    def test_worker_with_no_usable_runtime_fails_instead_of_enrolling(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        executor.docker_client = None
        with patch.object(executor, 'verify_workload', side_effect=RuntimeError('Bad runtime')):
            with self.assertRaisesRegex(RuntimeError, 'No approved workload'):
                executor.capabilities()

    def test_docker_image_presence_does_not_replace_execution_probe(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        executor.docker_client = MagicMock()
        with patch.object(executor, 'verify_workload', side_effect=[None, RuntimeError('Container cannot execute')]) as probe:
            self.assertEqual(executor.capabilities(), ['dummy'])
            self.assertEqual(executor.docker_client.images.get.call_count, 2)
            self.assertEqual(probe.call_count, 2)

    def test_docker_enforces_owner_memory_without_additional_swap(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        executor.docker_client = MagicMock()
        container = executor.docker_client.containers.run.return_value
        container.status = 'exited'
        container.attrs = {'State': {'ExitCode': 0}}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                {'WORKLOAD_CPUS': '0.5', 'WORKLOAD_MEMORY_LIMIT': '805306368'}):
            executor.run_workload('dummy', Path(temp), Path(temp), threading.Event(), 'attempt')
        options = executor.docker_client.containers.run.call_args.kwargs
        self.assertEqual(options['nano_cpus'], 500000000)
        self.assertEqual(options['mem_limit'], '805306368')
        self.assertEqual(options['memswap_limit'], options['mem_limit'])
        self.assertTrue(options['network_disabled'])
        self.assertTrue(options['read_only'])
        container.remove.assert_called_once_with(force=True)

    def test_preflight_rejects_success_for_wrong_input_and_cleans_temporary_files(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        executor.docker_client = None
        with tempfile.TemporaryDirectory() as temp, patch.object(Config, 'TEMP_EXEC_DIR', Path(temp)):
            def fake_run(kind, inputs, outputs, *args, **kwargs):
                self.assertTrue(kwargs['preflight'])
                (outputs / 'result.json').write_text(json.dumps({'status': 'SUCCESS', 'itemsProcessed': 1,
                    'itemsFailed': 0, 'errors': [], 'predictions': [{'image': 'wrong.txt'}]}))
            with patch.object(executor, 'run_workload', side_effect=fake_run):
                with self.assertRaises(ValueError):
                    executor.verify_workload('dummy')
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_api_sends_bearer_secret_and_node_id(self):
        client = APIClient.__new__(APIClient)
        client.base_url = 'http://example.test/api'
        client.lock = threading.RLock()
        client.node_id, client.node_secret = 'node', 'secret'
        response = MagicMock(ok=True, status_code=200)
        response.json.return_value = {'ok': True}
        with patch('api_client.requests.request', return_value=response) as request:
            client.request_task()
            headers = request.call_args.kwargs['headers']
            self.assertEqual(headers['Authorization'], 'Bearer secret')
            self.assertEqual(headers['x-node-id'], 'node')

    def test_unauthorized_api_is_not_silently_treated_as_empty_queue(self):
        client = APIClient.__new__(APIClient)
        client.base_url = 'http://example.test/api'
        client.lock = threading.RLock()
        client.node_id, client.node_secret = 'node', 'secret'
        response = MagicMock(ok=False, status_code=401)
        response.json.return_value = {'error': 'Unauthorized'}
        with patch('api_client.requests.request', return_value=response):
            with self.assertRaises(APIError) as error:
                client.request_task()
        self.assertEqual(error.exception.status, 401)

    def test_input_path_traversal_and_duplicate_names_rejected(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        with tempfile.TemporaryDirectory() as temp:
            for names in [['../escape'], ['a.txt', 'a.txt']]:
                task = {'payload': {'workload_type': 'dummy', 'items': [{'name': n, 'content': 'a'} for n in names]}}
                with self.assertRaises(ValueError):
                    executor.stage_inputs(task, Path(temp), threading.Event())
            self.assertFalse((Path(temp).parent / 'escape').exists())

    def test_cancelled_input_staging_stops_immediately(self):
        cancel = threading.Event(); cancel.set()
        executor = TaskExecutor.__new__(TaskExecutor)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(TaskCancelled):
                executor.stage_inputs({'payload': {'items': [{'name': 'one'}]}}, Path(temp), cancel)

    def test_native_workload_timeout_kills_child(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        executor.docker_client = None
        with tempfile.TemporaryDirectory() as temp:
            inputs, outputs = Path(temp) / 'inputs', Path(temp) / 'outputs'
            inputs.mkdir(); outputs.mkdir()
            for n in range(20):
                (inputs / f'{n}.txt').write_text('demo')
            started = time.monotonic()
            with patch.object(Config, 'WORKLOAD_TIMEOUT', 0.05):
                with self.assertRaises(TimeoutError):
                    executor.run_workload('dummy', inputs, outputs, threading.Event(), 'test')
            self.assertLess(time.monotonic() - started, 3)

    def test_completion_retries_without_uploading_result_again(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.stop = MagicMock(); agent.stop.is_set.return_value = False
        agent.cancel = threading.Event()
        agent.executor = MagicMock()
        agent.api = MagicMock()
        agent.api.get_upload_url.return_value = {'upload_url': '/api/storage?test', 'result_key': 'output'}
        agent.api.complete_task.side_effect = [APIError('Connection lost'), {'status': 'TASK_COMPLETED'}]
        agent.lease_deadline = time.time() + 60
        with patch('agent.requests.put') as upload:
            result = agent.report({}, b'{}', 1000)
            self.assertEqual(result['status'], 'TASK_COMPLETED')
            self.assertEqual(upload.call_count, 1)
            self.assertEqual(agent.api.complete_task.call_count, 2)

    def test_execution_failure_clears_active_state(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.cancel = threading.Event()
        agent.stop = threading.Event()
        agent.api = MagicMock(); agent.executor = MagicMock()
        agent.executor.execute_task.side_effect = ValueError('Bad input')
        agent.process_task({'task_id': 'task', 'lease_token': 'attempt', 'retry_count': 0, 'lease_expires_at': '2099-01-01T00:00:00Z'})
        self.assertIsNone(agent.active_task)
        self.assertFalse(agent.api.fail_task.call_args.kwargs['retryable'])

    def test_stop_during_assignment_response_does_not_start_compute(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.api = MagicMock(); agent.capabilities = ['dummy']; agent.heartbeat_loop = MagicMock()
        agent.process_task = MagicMock()
        def arriving_assignment():
            agent.shutdown()
            return {'task_id': 'assigned-while-stopping'}
        agent.api.request_task.side_effect = arriving_assignment
        agent.start()
        agent.process_task.assert_not_called()
        agent.api.fail_task.assert_called_once_with({'task_id': 'assigned-while-stopping'},
            'Owner stopped the worker', retryable=True, attempts=1)
        self.assertTrue(agent.cancel.is_set())

    def test_stopped_agent_never_clears_cancellation_to_begin_a_task(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.api = MagicMock(); agent.executor = MagicMock(); agent.shutdown()
        agent.process_task({'task_id': 'late-task'})
        agent.executor.execute_task.assert_not_called()
        self.assertTrue(agent.cancel.is_set())

    def test_owner_stop_releases_cancelled_task_without_reporting_a_result(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.api = MagicMock(); agent.executor = MagicMock()
        task = {'task_id': 'task', 'lease_token': 'attempt', 'retry_count': 0,
                'lease_expires_at': '2099-01-01T00:00:00Z'}
        def cancel_running(*args):
            agent.shutdown()
            raise TaskCancelled('Owner stop')
        agent.executor.execute_task.side_effect = cancel_running
        agent.process_task(task)
        agent.api.fail_task.assert_called_once_with(task, 'Owner stopped the worker', retryable=True, attempts=1)
        agent.api.complete_task.assert_not_called()
        self.assertIsNone(agent.active_task)

    def test_stop_during_image_download_removes_partial_inputs_and_releases_lease(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.api = MagicMock(); agent.executor = TaskExecutor.__new__(TaskExecutor)
        task = {'task_id': '11111111-1111-4111-8111-111111111111', 'lease_token': '22222222-2222-4222-8222-222222222222',
                'retry_count': 0, 'lease_expires_at': '2099-01-01T00:00:00Z',
                'payload': {'workload_type': 'image_inference', 'items': [{'name': 'photo.png', 'download_url': 'http://localhost/input'}]}}
        response = MagicMock(); response.__enter__.return_value = response; response.headers = {}
        def download(*args):
            yield b'partial image'
            agent.shutdown()
            yield b'more bytes'
        response.iter_content.side_effect = download
        with tempfile.TemporaryDirectory() as temp, patch.object(Config, 'TEMP_EXEC_DIR', Path(temp)), patch('task_executor.requests.get', return_value=response):
            agent.process_task(task)
            self.assertEqual(list(Path(temp).iterdir()), [])
        agent.api.fail_task.assert_called_once_with(task, 'Owner stopped the worker', retryable=True, attempts=1)
        agent.api.complete_task.assert_not_called()

    def test_stop_during_result_upload_prevents_completion_and_releases_lease(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.api = MagicMock(); agent.executor = TaskExecutor.__new__(TaskExecutor)
        agent.executor.execute_task = MagicMock(return_value=(b'{}', 1))
        agent.api.get_upload_url.return_value = {'upload_url': 'http://localhost/output', 'result_key': 'output'}
        task = {'task_id': 'task', 'lease_token': 'lease', 'retry_count': 0, 'lease_expires_at': '2099-01-01T00:00:00Z'}
        def uploaded(*args, **kwargs):
            agent.shutdown()
            return MagicMock()
        with patch('agent.requests.put', side_effect=uploaded): agent.process_task(task)
        agent.api.complete_task.assert_not_called()
        agent.api.fail_task.assert_called_once_with(task, 'Owner stopped the worker', retryable=True, attempts=1)

    def test_lost_lease_cancellation_does_not_release_a_foreign_attempt(self):
        agent = WorkerAgent.__new__(WorkerAgent)
        agent.lock = threading.RLock(); agent.stop, agent.cancel = threading.Event(), threading.Event()
        agent.api = MagicMock(); agent.executor = MagicMock()
        agent.executor.execute_task.side_effect = TaskCancelled('Lease lost')
        agent.process_task({'task_id': 'task', 'lease_token': 'attempt', 'retry_count': 0,
                            'lease_expires_at': '2099-01-01T00:00:00Z'})
        agent.api.fail_task.assert_not_called()

    def test_unavailable_release_leaves_recovery_to_the_server(self):
        agent = WorkerAgent.__new__(WorkerAgent); agent.api = MagicMock()
        agent.api.fail_task.side_effect = APIError('Network unavailable')
        agent.release_stopped_task({'task_id': 'task', 'lease_token': 'attempt'})
        agent.api.fail_task.assert_called_once()


if __name__ == '__main__':
    unittest.main()
