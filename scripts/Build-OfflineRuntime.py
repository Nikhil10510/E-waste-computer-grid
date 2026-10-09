"""Export the reviewed team workloads locally; never publish to a registry."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from desktop_runtime import worker_environment
from runtime_release import OfflineRelease, run_command, docker_cli_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', default='team-offline-v1')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive, manifest = output / 'images.tar', output / 'release.json'
    if archive.exists() or manifest.exists(): raise ValueError('Use a new release directory; do not overwrite released artifacts')
    import docker
    client = docker.from_env(timeout=30)
    try:
        info = client.info()
        if info.get('OSType') != 'linux' or info.get('Architecture') not in ('x86_64', 'amd64'):
            raise ValueError('Initial release supports Linux amd64 only')
        images = {}
        for kind, tag in [('dummy', 'ewaste/dummy-workload:v1'), ('image_inference', 'ewaste/ai-workload:v1')]:
            image = client.images.get(tag)
            if image.attrs.get('Os') != 'linux' or image.attrs.get('Architecture') != 'amd64':
                raise ValueError('Wrong image platform: ' + kind)
            images[kind] = {'image_id': image.id}
        pinned = json.loads((ROOT / 'workloads/ai-inference/models/artifact-manifest.json').read_text())
        # Read the baked artifact contract without running the image or
        # mounting a host folder. Only this newly created container is removed.
        container = client.containers.create(images['image_inference']['image_id'])
        try:
            stream, _ = container.get_archive('/models/artifact-manifest.json')
            with tarfile.open(fileobj=io.BytesIO(b''.join(stream))) as data:
                member = next(member for member in data if member.isfile())
                baked = json.load(data.extractfile(member))
            if baked != pinned: raise ValueError('Baked inference artifact contract differs from reviewed source')
        finally: container.remove()
        images['image_inference'].update({key: pinned[key] for key in ('model_sha256', 'labels_sha256')})
        environment = worker_environment('http://localhost:8080/api', output / 'preflight', 'Release preflight')
        environment.update(DUMMY_IMAGE=images['dummy']['image_id'], INFERENCE_IMAGE=images['image_inference']['image_id'])
        # Release creation must prove runtime execution before exporting.
        result = subprocess.run([sys.executable, str(ROOT / 'worker/agent.py'), '--preflight'],
            env=environment, capture_output=True, text=True, timeout=90)
        if result.returncode: raise RuntimeError('Release preflight failed: ' + (result.stdout + result.stderr)[-2000:])
        probe = json.loads(result.stdout)
        if set(probe['capabilities']) != {'dummy', 'image_inference'}: raise ValueError('Both workloads must pass')
        run_command(['docker', 'image', 'save', '--output', str(archive),
            images['dummy']['image_id'], images['image_inference']['image_id']], Event(), print, env=docker_cli_environment())
        checksum = hashlib.sha256()
        with archive.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''): checksum.update(block)
        data = {'schema_version': 1, 'result_version': 1, 'release': args.release,
            'platform': 'linux/amd64', 'archive': {'filename': 'images.tar', 'bytes': archive.stat().st_size,
            'sha256': checksum.hexdigest()}, 'images': images}
        manifest.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        OfflineRelease(manifest)
        print(json.dumps({'manifest': str(manifest), 'archive': str(archive), 'images': images,
            'preflight': probe, 'docker_version': info.get('ServerVersion')}))
    finally: client.close()


if __name__ == '__main__': main()
