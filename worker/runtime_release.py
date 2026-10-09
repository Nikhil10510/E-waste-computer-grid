"""Trusted offline releases: verify content, import explicitly, execute image IDs.

The manifest is trusted through the reviewed checkout, not through the archive.
An image ID is a config/layer content digest, not a registry manifest digest.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from threading import Event

DEFAULT_MANIFEST = Path(__file__).with_name('releases') / 'current.json'
KINDS = {'dummy', 'image_inference'}
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')


class PreparationCancelled(RuntimeError):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise PreparationCancelled('Runtime preparation cancelled. No worker was started.')


def docker_cli_environment():
    """Use the SDK's endpoint, rather than an unrelated saved CLI context."""
    from docker.constants import DEFAULT_NPIPE, DEFAULT_UNIX_SOCKET
    env = os.environ.copy()
    env.pop('DOCKER_CONTEXT', None)
    env['DOCKER_HOST'] = env.get('DOCKER_HOST') or (DEFAULT_NPIPE if os.name == 'nt'
        else DEFAULT_UNIX_SOCKET.replace('http+unix://', 'unix://'))
    return env


def run_command(command, cancel, progress=lambda message: None, timeout=600, env=None, request_stop=None):
    """Bound output and stop only our CLI/subprocess; never stop the daemon."""
    check_cancel(cancel)
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except FileNotFoundError:
            raise RuntimeError('Docker CLI is missing. Install Docker Desktop with Linux containers.') from None
        started, tick = time.monotonic(), 0
        try:
            while process.poll() is None:
                check_cancel(cancel)
                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    raise TimeoutError('Runtime operation timed out. Check Docker and retry.')
                if elapsed >= tick:
                    progress(f'Import/preflight in progress ({int(elapsed)} seconds)...')
                    tick = elapsed + 1
                cancel.wait(0.1)
            check_cancel(cancel)
            output.seek(0, 2)
            length = output.tell()
            output.seek(max(0, length - 16000))
            result = output.read(16000).decode('utf-8', errors='replace')
            if process.returncode:
                raise RuntimeError('Runtime operation failed: ' + result[-1500:])
            return result
        finally:
            if process.poll() is None:
                if request_stop:
                    try:
                        request_stop()
                        process.wait(timeout=20)
                    except (OSError, subprocess.TimeoutExpired): pass
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


class OfflineRelease:
    def __init__(self, path=DEFAULT_MANIFEST):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise RuntimeError('No reviewed runtime release is configured. Ask the team for its release manifest.')
        if self.path.stat().st_size > 65536: raise ValueError('Release manifest is too large')
        raw = self.path.read_bytes()
        if len(raw) > 65536: raise ValueError('Release manifest is too large')
        self.manifest = json.loads(raw)
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        data = self.manifest
        if not isinstance(data, dict): raise ValueError('Release manifest must be an object')
        if (type(data.get('schema_version')) is not int or data.get('schema_version') != 1
                or type(data.get('result_version')) is not int or data.get('result_version') != 1
                or data.get('platform') != 'linux/amd64'
                or not isinstance(data.get('release'), str)
                or not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}', data['release'])):
            raise ValueError('Unsupported runtime release schema, result contract or platform')
        images = data.get('images')
        if not isinstance(images, dict) or set(images) != KINDS:
            raise ValueError('Release must include exactly the two approved workloads')
        for kind, image in images.items():
            if (not isinstance(image, dict) or not isinstance(image.get('image_id'), str)
                    or not DIGEST.fullmatch(image['image_id'])):
                raise ValueError('Release requires immutable image IDs')
        archive = data.get('archive', {})
        if not isinstance(archive, dict): raise ValueError('Invalid archive metadata')
        size = archive.get('bytes')
        if (not isinstance(archive.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', archive['sha256'])
                or isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 8 * 1024 ** 3):
            raise ValueError('Invalid archive checksum or size')
        for key in ('model_sha256', 'labels_sha256'):
            if (not isinstance(images['image_inference'].get(key), str)
                    or not re.fullmatch(r'[a-f0-9]{64}', images['image_inference'][key])):
                raise ValueError('Release is missing its pinned inference artifacts')
        self.images = {kind: image['image_id'] for kind, image in images.items()}

    def validate_image(self, kind, image):
        attrs = image.attrs
        if (attrs.get('Id') != self.images[kind] or attrs.get('Os') != 'linux'
                or attrs.get('Architecture') != 'amd64'):
            raise ValueError(f'{kind}: cached image does not match the approved identity/platform')

    def cached(self, client):
        from docker.errors import ImageNotFound
        missing = []
        for kind, image_id in self.images.items():
            try: self.validate_image(kind, client.images.get(image_id))
            except ImageNotFound: missing.append(kind)
        return missing

    def prepare(self, directory, archive=None, cancel=None, progress=lambda message: None, force_import=False):
        import docker
        cancel = cancel or Event()
        check_cancel(cancel)
        try:
            client = docker.from_env(timeout=15)
        except docker.errors.DockerException:
            raise RuntimeError('Docker is unavailable. Start Docker Desktop with Linux containers, then retry.') from None
        try:
            try: info = client.info()
            except docker.errors.DockerException:
                raise RuntimeError('Docker is unavailable. Start Docker Desktop with Linux containers, then retry.') from None
            arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(info.get('Architecture'), info.get('Architecture'))
            if info.get('OSType') != 'linux' or arch != 'amd64':
                raise RuntimeError('This release requires a Linux amd64 Docker engine. Windows containers/ARM are unsupported.')
            check_cancel(cancel)
            if not self.cached(client) and not force_import:
                progress('Approved release is cached. No archive import needed.')
                return self.images.copy()
            if archive is None:
                raise RuntimeError('Approved images are missing. Import the team offline image archive first.')
            directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
            expected = self.manifest['archive']
            if shutil.disk_usage(directory).free < expected['bytes'] * 2 + 256 * 1024 ** 2:
                raise RuntimeError('Insufficient host disk space for verified import. Docker/WSL also needs free disk space.')
            # Copy and hash the same open file into our owned snapshot. Docker
            # never reads an original archive that could change after hashing.
            with Path(archive).open('rb') as source, tempfile.TemporaryDirectory(prefix='runtime-import-', dir=directory) as temp:
                if os.fstat(source.fileno()).st_size != expected['bytes']:
                    raise ValueError('Archive size does not match the reviewed release')
                target = Path(temp) / 'images.tar'
                checksum, size, last_percent = hashlib.sha256(), 0, -1
                with target.open('wb') as output:
                    while True:
                        check_cancel(cancel)
                        block = source.read(1024 * 1024)
                        if not block: break
                        size += len(block)
                        if size > expected['bytes']: raise ValueError('Archive changed during verification')
                        output.write(block); checksum.update(block)
                        percent = int(size * 100 / expected['bytes'])
                        if percent != last_percent:
                            progress(f'Verifying offline archive: {percent}%')
                            last_percent = percent
                if size != expected['bytes'] or checksum.hexdigest() != expected['sha256']:
                    raise ValueError('Archive checksum mismatch. Obtain the reviewed team bundle; nothing was imported.')
                check_cancel(cancel)
                progress('Checksum verified. Importing approved workload images into Docker...')
                run_command(['docker', 'image', 'load', '--input', str(target)], cancel, progress, env=docker_cli_environment())
            check_cancel(cancel)
            if self.cached(client): raise RuntimeError('Import did not provide all approved images')
            progress('Image identities and platform verified. Real inference preflight is next.')
            return self.images.copy()
        finally:
            client.close()
