import json
import os
import threading
import time
import uuid
import requests
from config import Config
from hardware import get_hardware_specs
from resource_limits import validate_limits, memory_bytes


class APIError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class APIClient:
    def __init__(self):
        self.base_url = Config.CONTROL_PLANE_URL
        self.lock = threading.RLock()
        self.node_id = None
        self.node_secret = None
        self.registration_key = str(uuid.uuid4())
        self.heartbeat_interval = Config.HEARTBEAT_INTERVAL
        self.resource_limits = None
        self.paused = False
        if Config.CREDENTIALS_FILE.exists():
            try:
                data = json.loads(Config.CREDENTIALS_FILE.read_text())
                if data.get("control_plane_url", self.base_url) != self.base_url:
                    raise ValueError("Worker identity belongs to a different grid; use a separate state directory")
                self.node_id = data.get("node_id")
                self.node_secret = data.get("node_secret")
                self.registration_key = data.get("registration_key", self.registration_key)
                self.resource_limits = data.get('resource_limits')
                self.paused = data.get('paused', False)
            except (OSError, json.JSONDecodeError):
                pass
        self.save_credentials()

    def save_credentials(self):
        with self.lock:
            temp = Config.CREDENTIALS_FILE.with_suffix(".tmp")
            temp.write_text(json.dumps({
                "node_id": self.node_id, "node_secret": self.node_secret,
                "registration_key": self.registration_key,
                "control_plane_url": self.base_url,
                "resource_limits": self.resource_limits, "paused": self.paused,
            }))
            if os.name != "nt":
                temp.chmod(0o600)
            temp.replace(Config.CREDENTIALS_FILE)

    def clear_credentials(self):
        with self.lock:
            self.node_id = self.node_secret = None
            self.save_credentials()

    def request(self, method, path, payload=None, headers=None, enrollment=False, attempts=3):
        with self.lock:
            auth = {"Authorization": "Bearer " + (Config.ENROLLMENT_TOKEN if enrollment else self.node_secret or "")}
            if self.node_id and not enrollment:
                auth["x-node-id"] = self.node_id
        auth.update(headers or {})
        last_error = None
        for attempt in range(attempts):
            try:
                # Per-call sessions avoid sharing mutable requests.Session state with the heartbeat thread.
                response = requests.request(method, self.base_url + path, json=payload, headers=auth, timeout=(5, 20))
                if response.status_code == 204:
                    return None
                if response.ok:
                    return response.json()
                try:
                    message = response.json().get("error", response.reason)
                except ValueError:
                    message = response.reason
                last_error = APIError(message, response.status_code)
                if response.status_code < 500 and response.status_code != 429:
                    raise last_error
            except requests.RequestException as exc:
                last_error = APIError(str(exc))
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 4))
        raise last_error

    def register(self, capabilities):
        hardware = get_hardware_specs(capabilities)
        if self.node_id and self.node_secret:
            # Existing approval is authenticated with this device's credential.
            # No shared enrollment token is needed on restart.
            data = self.request("POST", "/nodes/session", hardware)
            if Config.REQUIRE_PAIRED_IDENTITY and data.get('enrollment_mode') != 'paired':
                raise APIError('Desktop worker requires an owner-approved identity', 403)
            self.apply_session(data)
            self.heartbeat_interval = min(Config.HEARTBEAT_INTERVAL, data["heartbeat_interval_seconds"])
            return
        if Config.REQUIRE_PAIRED_IDENTITY:
            raise APIError("Owner-approved identity missing; use the worker app to pair", 401)
        data = self.request("POST", "/nodes/register", {
            **hardware, "registration_key": self.registration_key,
        }, enrollment=True)
        with self.lock:
            self.node_id = data["node_id"]
            self.node_secret = data["node_secret"]
            self.heartbeat_interval = min(Config.HEARTBEAT_INTERVAL, data["heartbeat_interval_seconds"])
            self.apply_session(data)

    def apply_session(self, data):
        self.paused = data.get('paused', False)
        if data.get('resource_limits') is not None:
            self.resource_limits = validate_limits(data['resource_limits'])
            os.environ['WORKLOAD_CPUS'] = format(self.resource_limits['cpu'], 'g')
            os.environ['WORKLOAD_MEMORY_LIMIT'] = str(memory_bytes(self.resource_limits))
        self.save_credentials()

    def send_heartbeat(self, task=None):
        return self.request("POST", f"/nodes/{self.node_id}/heartbeat", {
            "state": "WORKING" if task else "IDLE",
            "active_task_id": task["task_id"] if task else None,
            "lease_token": task["lease_token"] if task else None,
        }, attempts=1)

    def request_task(self):
        return self.request("GET", "/tasks/request")

    def get_upload_url(self, task):
        return self.request("GET", f"/tasks/{task['task_id']}/upload-url",
                            headers={"x-lease-token": task["lease_token"]})

    def complete_task(self, task, execution_time_ms, result_key):
        return self.request("POST", f"/tasks/{task['task_id']}/complete", {
            "lease_token": task["lease_token"], "execution_time_ms": execution_time_ms,
            "result_key": result_key,
        })

    def fail_task(self, task, error, retryable=True):
        return self.request("POST", f"/tasks/{task['task_id']}/fail", {
            "lease_token": task["lease_token"], "error": str(error)[:2000] or "Execution failed",
            "retryable": retryable,
        })
