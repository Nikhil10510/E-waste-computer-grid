"""Source-based desktop runner with saved resource ceilings and scoped shutdown."""
import json
import os
from pathlib import Path
import subprocess
import sys
from resource_limits import validate_limits, memory_bytes
from state_store import load_state
from log_safety import safe_text

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
    env['EWASTE_LOG_FILE'] = str(Path(directory) / 'agent.log')
    return env


class DesktopRuntime:
    def __init__(self, api_url, directory, name, limits=None):
        self.api_url, self.directory, self.name = api_url, Path(directory), name
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.log_file = self.directory / 'worker.log'
        self.agent_log_file = self.directory / 'agent.log'
        self.preflight_log_file = self.directory / 'preflight.log'
        self.stop_file = self.directory / 'stop.request'
        self.limits = validate_limits(limits or {'cpu': 2, 'memory_gb': 2})

    def preflight(self):
        completed = subprocess.run([sys.executable, str(AGENT_PATH), '--preflight'],
            env=worker_environment(self.api_url, self.directory, self.name, self.limits),
            capture_output=True, text=True, timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        diagnostic = safe_text(completed.stdout + '\n' + completed.stderr)[-16000:]
        self.preflight_log_file.write_text(diagnostic, encoding='utf-8')
        try: data = json.loads(completed.stdout)
        except ValueError: raise RuntimeError('Runtime check returned an invalid response. See Diagnostics.') from None
        if completed.returncode:
            detail = data.get('error') or '; '.join(f'{k}: {v}' for k, v in data.get('errors', {}).items())
            raise RuntimeError('Runtime check failed: ' + safe_text(detail or 'Start Docker with Linux containers and prepare the approved images.')[:700])
        if data.get('mode') != 'docker' or 'image_inference' not in data.get('capabilities', []):
            raise RuntimeError('Image inference did not pass the Docker runtime check')
        return data['capabilities']

    def start(self):
        if self.process and self.process.poll() is None: return
        credentials = self.directory / 'credentials.json'
        saved = load_state(credentials)
        if saved.get('control_plane_url') != self.api_url or not saved.get('node_secret'):
            raise ValueError('An approved identity for this grid must be saved before starting')
        self.stop_file.unlink(missing_ok=True)
        if self.log_file.exists() and self.log_file.stat().st_size > 1024 * 1024:
            self.log_file.replace(self.log_file.with_suffix('.log.1'))
        with self.log_file.open('ab') as stream:
            self.process = subprocess.Popen([sys.executable, str(AGENT_PATH)],
                env=worker_environment(self.api_url, self.directory, self.name, self.limits), stdout=stream, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def request_stop(self):
        if self.process and self.process.poll() is None:
            self.stop_file.write_text('stop', encoding='ascii')

    def running(self):
        return self.process is not None and self.process.poll() is None

    def diagnostics(self, secrets=()):
        credentials = self.directory / 'credentials.json'
        if credentials.exists():
            secrets = (*secrets, load_state(credentials).get('node_secret'))
        sections = []
        for path in (self.preflight_log_file, self.log_file, self.agent_log_file):
            if path.exists():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 16000))
                    tail = stream.read(16000).decode('utf-8', errors='replace')
                sections.append(path.name + '\n' + safe_text(tail, secrets))
        return '\n\n'.join(sections) or 'No diagnostics yet. Prepare a connection to check the runtime.'
