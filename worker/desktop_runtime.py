"""Source-based desktop runner; packaging and custom resource policy are later steps."""
import json
import os
from pathlib import Path
import subprocess
import sys
from resource_limits import validate_limits, memory_bytes

AGENT_PATH = Path(__file__).with_name('agent.py')


def worker_environment(api_url, directory, name, limits=None):
    limits = validate_limits(limits or {'cpu': 2, 'memory_gb': 2})
    env = os.environ.copy()
    for key in ('ADMIN_TOKEN', 'ENROLLMENT_TOKEN', 'STORAGE_SECRET', 'DATABASE_URL'):
        env.pop(key, None)
    env.update(CONTROL_PLANE_URL=api_url, DATA_DIR=str(directory), TEMP_EXEC_DIR=str(Path(directory) / 'tasks'),
        EXECUTION_MODE='docker', REQUIRE_PAIRED_IDENTITY='true', WORKER_NAME=name, PYTHONUTF8='1',
        WORKLOAD_CPUS=format(limits['cpu'], 'g'), WORKLOAD_MEMORY_LIMIT=str(memory_bytes(limits)),
        MAX_POLL_INTERVAL='5',
        DUMMY_IMAGE='ewaste/dummy-workload:v1', INFERENCE_IMAGE='ewaste/ai-workload:v1')
    return env


class DesktopRuntime:
    def __init__(self, api_url, directory, name, limits=None):
        self.api_url, self.directory, self.name = api_url, Path(directory), name
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.log_file = self.directory / 'worker.log'
        self.stop_file = self.directory / 'stop.request'
        self.limits = validate_limits(limits or {'cpu': 2, 'memory_gb': 2})

    def preflight(self):
        completed = subprocess.run([sys.executable, str(AGENT_PATH), '--preflight'],
            env=worker_environment(self.api_url, self.directory, self.name, self.limits),
            capture_output=True, text=True, timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if completed.returncode:
            raise RuntimeError('Runtime check failed. Start Docker with Linux containers and prepare the approved workload images. See worker/README.md.')
        data = json.loads(completed.stdout)
        if data.get('mode') != 'docker' or 'image_inference' not in data.get('capabilities', []):
            raise RuntimeError('Image inference did not pass the Docker runtime check')
        return data['capabilities']

    def start(self):
        if self.process and self.process.poll() is None: return
        credentials = self.directory / 'credentials.json'
        saved = json.loads(credentials.read_text(encoding='utf-8'))
        if saved.get('control_plane_url') != self.api_url or not saved.get('node_secret'):
            raise ValueError('An approved identity for this grid must be saved before starting')
        self.stop_file.unlink(missing_ok=True)
        with self.log_file.open('ab') as stream:
            self.process = subprocess.Popen([sys.executable, str(AGENT_PATH)],
                env=worker_environment(self.api_url, self.directory, self.name, self.limits), stdout=stream, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def request_stop(self):
        if self.process and self.process.poll() is None:
            self.stop_file.write_text('stop', encoding='ascii')

    def running(self):
        return self.process is not None and self.process.poll() is None
