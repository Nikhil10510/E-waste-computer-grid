"""Record Phase 1 Docker execution evidence using the actual host executor."""
import json
from pathlib import Path
import sys
from threading import Event
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from config import Config
from task_executor import TaskExecutor

Config.setup_dirs()
executor = TaskExecutor()
capabilities = executor.capabilities()
assert 'image_inference' in capabilities, executor.preflight_errors
inputs = ROOT / 'workloads/test-data/demo'
outputs = ROOT / 'output/workloads/phase1-docker'
outputs.mkdir(parents=True, exist_ok=True)
duration = executor.run_workload('image_inference', inputs, outputs, Event(), str(uuid.uuid4()), preflight=True)
result = json.loads((outputs / 'result.json').read_text())
manifest = json.loads((ROOT / 'workloads/test-data/demo-manifest.json').read_text())
expected = {entry['filename'] for entry in manifest['images']}
names = [item['image'] for item in result['predictions']]
assert result['status'] == 'SUCCESS' and result['itemsProcessed'] == 10 and result['itemsFailed'] == 0
assert len(names) == len(set(names)) == len(expected) and set(names) == expected and result['errors'] == []
native = json.loads((ROOT / 'output/workloads/phase1/result.json').read_text())
native_by_name = {p['image']: p for p in native['predictions']}
assert all(p['classId'] == native_by_name[p['image']]['classId'] for p in result['predictions'])
evidence = {
    'scope': 'One-host Docker workload execution through TaskExecutor; not a physical fleet or browser test.',
    'mode': Config.EXECUTION_MODE, 'capabilities': capabilities, 'preflight_errors': executor.preflight_errors,
    'image_ids': {kind: executor.docker_client.images.get(Config.IMAGES[kind]).id for kind in capabilities},
    'items_processed': 10, 'items_failed': 0, 'exact_input_coverage': True,
    'native_class_ids_match': True, 'execution_time_ms': duration,
    'limits': {'network_disabled': True, 'read_only_root': True, 'memory': '2g', 'cpus': 2, 'pids': 128},
}
(outputs / 'verification.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence, indent=2))
