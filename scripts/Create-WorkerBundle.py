"""Create a worker-only source handoff without environments or credentials."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'worker/agent.py', 'worker/api_client.py', 'worker/config.py', 'worker/hardware.py',
    'worker/state_store.py', 'worker/log_safety.py', 'worker/resource_limits.py',
    'worker/product.py', 'worker/launch.py',
    'worker/runtime_release.py', 'worker/releases/current.json',
    'worker/task_executor.py', 'worker/requirements.txt', 'worker/README.md', 'worker/.env.example',
    'scripts/Start-Worker.ps1', 'docs/PHASE_2_WINDOWS_WORKER.md',
    'workloads/energy/energy_calculator.py', 'workloads/benchmark/hardware_benchmark.py',
    'workloads/dummy-workload/run_dummy.py', 'workloads/dummy-workload/Dockerfile',
    'workloads/ai-inference/run_inference.py', 'workloads/ai-inference/download_model.py',
    'workloads/ai-inference/requirements.txt', 'workloads/ai-inference/Dockerfile',
    'workloads/ai-inference/models/README.md', 'workloads/ai-inference/models/artifact-manifest.json',
    'workloads/ai-inference/models/mobilenetv2-12.onnx', 'workloads/ai-inference/models/imagenet_labels.json',
]


def main():
    output = ROOT / 'output/handoff'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'E_Waste_Phase_2_Windows_Worker.zip'
    hashes = {}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in FILES:
            raw = (ROOT / relative).read_bytes()
            hashes[relative] = hashlib.sha256(raw).hexdigest()
            bundle.writestr(relative, raw)
        bundle.writestr('README.md',
            '# Windows worker handoff\n\n'
            'This contains the approved worker source and pinned model, not the API/dashboard or Git history. '
            'Extract into a new directory. Install/create a fresh Python 3.12 .venv-local there; '
            'never copy the API host credentials/environment. Follow docs/PHASE_2_WINDOWS_WORKER.md. '
            'Start Docker Desktop in Linux mode, build the two approved workload images, and use the current '
            'server URL/enrollment token. Setup instructions are for a private development demo.\n')
        bundle.writestr('SOURCE_MANIFEST.json', json.dumps(hashes, indent=2) + '\n')
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Archive failed integrity verification')
        for name, expected in hashes.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError(f'Bundled source changed: {name}')
        if any(name.endswith('credentials.json') or '/.venv' in name or name.endswith('/.env') for name in bundle.namelist()):
            raise ValueError('Private state must not be bundled')
    report = {'archive': archive.name, 'source_files': len(hashes), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'scope': 'Worker-only source handoff; excludes credentials, environments and Git history.'}
    (output / 'worker-bundle-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
