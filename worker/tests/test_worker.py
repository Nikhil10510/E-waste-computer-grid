import json
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
from api_client import APIClient, APIError
from agent import WorkerAgent
from task_executor import TaskExecutor, TaskCancelled


class WorkerTests(unittest.TestCase):
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
        agent.api = MagicMock(); agent.executor = MagicMock()
        agent.executor.execute_task.side_effect = ValueError('Bad input')
        agent.process_task({'task_id': 'task', 'lease_token': 'attempt', 'retry_count': 0, 'lease_expires_at': '2099-01-01T00:00:00Z'})
        self.assertIsNone(agent.active_task)
        self.assertFalse(agent.api.fail_task.call_args.kwargs['retryable'])


if __name__ == '__main__':
    unittest.main()
