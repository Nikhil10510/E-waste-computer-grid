import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_release import OfflineRelease, PreparationCancelled, run_command, docker_cli_environment
from desktop_runtime import worker_environment, DesktopRuntime
from task_executor import TaskExecutor
from config import Config
from docker.errors import ImageNotFound, DockerException


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.archive = self.directory / 'images.tar'; self.archive.write_bytes(b'reviewed archive')
        self.data = {'schema_version': 1, 'result_version': 1, 'release': 'test-v1', 'platform': 'linux/amd64',
            'archive': {'bytes': self.archive.stat().st_size, 'sha256': hashlib.sha256(self.archive.read_bytes()).hexdigest()},
            'images': {'dummy': {'image_id': 'sha256:' + 'a' * 64}, 'image_inference':
                {'image_id': 'sha256:' + 'b' * 64, 'model_sha256': 'c' * 64, 'labels_sha256': 'd' * 64}}}
        self.manifest = self.directory / 'release.json'
        self.release = self.write_release()
        self.client = MagicMock()
        self.client.info.return_value = {'OSType': 'linux', 'Architecture': 'x86_64'}
        self.imported = False
        def get(image_id):
            if not self.imported: raise ImageNotFound('missing')
            return MagicMock(attrs={'Id': image_id, 'Os': 'linux', 'Architecture': 'amd64'})
        self.client.images.get.side_effect = get
        self.docker = patch('docker.from_env', return_value=self.client); self.docker.start()

    def tearDown(self):
        self.docker.stop(); self.temp.cleanup()

    def write_release(self):
        self.manifest.write_text(json.dumps(self.data))
        return OfflineRelease(self.manifest)

    def test_unapproved_workloads_mutable_images_and_platforms_rejected(self):
        original = copy.deepcopy(self.data)
        for mutate in [lambda d: d['images'].update(arbitrary={'image_id': 'sha256:' + 'f' * 64}),
                lambda d: d['images']['dummy'].update(image_id='ewaste/dummy:v1'),
                lambda d: d.update(platform='linux/arm64'), lambda d: d.update(result_version=2)]:
            self.data = copy.deepcopy(original); mutate(self.data)
            with self.assertRaises(ValueError): self.write_release()

    def test_checksum_failure_never_calls_docker_load_and_cleans_snapshot(self):
        self.archive.write_bytes(b'corrupt! archive')
        with patch('runtime_release.run_command') as command:
            with self.assertRaisesRegex(ValueError, 'checksum'): self.release.prepare(self.directory, self.archive)
            command.assert_not_called()
        self.assertFalse(list(self.directory.glob('runtime-import-*')))

    def test_verified_snapshot_not_original_is_imported_then_ids_verified(self):
        observed = []
        def load(command, *args, **kwargs):
            path = Path(command[-1]); observed.append(path)
            self.assertNotEqual(path, self.archive)
            self.assertEqual(path.read_bytes(), b'reviewed archive')
            self.archive.write_bytes(b'changed by another process')
            self.imported = True
        with patch('runtime_release.run_command', side_effect=load):
            self.assertEqual(self.release.prepare(self.directory, self.archive), self.release.images)
        self.assertFalse(observed[0].exists())

    def test_valid_cache_skips_transfer_without_archive(self):
        self.imported = True
        with patch('runtime_release.run_command') as command:
            self.release.prepare(self.directory)
            command.assert_not_called()

    def test_missing_images_report_import_requirement(self):
        with self.assertRaisesRegex(RuntimeError, 'Import'): self.release.prepare(self.directory)

    def test_import_that_lacks_approved_ids_is_not_ready(self):
        with patch('runtime_release.run_command'):
            with self.assertRaisesRegex(RuntimeError, 'all approved'): self.release.prepare(self.directory, self.archive)

    def test_wrong_cached_platform_is_rejected(self):
        self.client.images.get.side_effect = None
        self.client.images.get.return_value.attrs = {'Id': self.release.images['dummy'], 'Os': 'linux', 'Architecture': 'arm64'}
        with self.assertRaises(ValueError): self.release.prepare(self.directory)

    def test_wrong_engine_mode_and_architecture_are_actionable(self):
        for info in [{'OSType': 'windows', 'Architecture': 'amd64'}, {'OSType': 'linux', 'Architecture': 'aarch64'}]:
            self.client.info.return_value = info
            with self.assertRaisesRegex(RuntimeError, 'Linux amd64'): self.release.prepare(self.directory)

    def test_docker_stopped_is_actionable_and_never_imports(self):
        self.client.info.side_effect = DockerException('daemon unavailable')
        with patch('runtime_release.run_command') as command:
            with self.assertRaisesRegex(RuntimeError, 'Start Docker Desktop'): self.release.prepare(self.directory)
            command.assert_not_called()

    def test_low_disk_space_and_wrong_size_fail_before_import(self):
        with patch('runtime_release.shutil.disk_usage', return_value=MagicMock(free=1)):
            with self.assertRaisesRegex(RuntimeError, 'disk'): self.release.prepare(self.directory, self.archive)
        self.archive.write_bytes(b'too short')
        with self.assertRaisesRegex(ValueError, 'size'): self.release.prepare(self.directory, self.archive)

    def test_cancel_during_hash_does_not_load_or_leave_temporary_files(self):
        cancel = threading.Event()
        with patch('runtime_release.run_command') as command:
            with self.assertRaises(PreparationCancelled):
                self.release.prepare(self.directory, self.archive, cancel, lambda message: cancel.set())
            command.assert_not_called()
        self.assertFalse(list(self.directory.glob('runtime-import-*')))

    def test_cancel_import_stops_only_its_cli_and_retries_cleanly(self):
        cancel = threading.Event()
        process = MagicMock(); process.poll.return_value = None
        def progress(message): cancel.set()
        with patch('runtime_release.subprocess.Popen', return_value=process):
            with self.assertRaises(PreparationCancelled): run_command(['docker', 'image', 'load'], cancel, progress)
        process.terminate.assert_called_once()
        self.assertEqual(process.wait.call_args.kwargs['timeout'], 5)

    def test_preflight_cancellation_requests_cooperative_cleanup_before_termination(self):
        cancel = threading.Event()
        process = MagicMock(); process.poll.return_value = None
        stop = MagicMock()
        def progress(message): cancel.set()
        def cooperative(): stop(); process.poll.return_value = 0
        with patch('runtime_release.subprocess.Popen', return_value=process):
            with self.assertRaises(PreparationCancelled):
                run_command(['python', 'agent.py', '--preflight'], cancel, progress, request_stop=cooperative)
        stop.assert_called_once(); process.terminate.assert_not_called()

    def test_pinned_identity_reaches_preflight_agent_and_execution(self):
        with patch.dict('os.environ', {'DUMMY_IMAGE': 'untrusted:latest', 'WORKLOAD_RELEASE_MANIFEST': 'untrusted.json'}):
            env = worker_environment('https://grid.example/api', self.directory, 'Laptop', release=self.release)
        self.assertEqual(env['DUMMY_IMAGE'], self.release.images['dummy'])
        self.assertEqual(env['WORKLOAD_RELEASE_SHA256'], self.release.fingerprint)
        executor = TaskExecutor.__new__(TaskExecutor); executor.docker_client = self.client
        self.imported = True
        container = self.client.containers.run.return_value
        container.status = 'exited'; container.attrs = {'State': {'ExitCode': 0}}
        with patch.object(Config, 'RELEASE', self.release), patch.object(Config, 'IMAGES', self.release.images):
            executor.run_workload('dummy', self.directory, self.directory, threading.Event(), 'attempt')
        self.assertEqual(self.client.containers.run.call_args.args[0], self.release.images['dummy'])

    def test_preflight_failure_does_not_mark_runtime_ready(self):
        runtime = DesktopRuntime('https://grid.example/api', self.directory, 'Laptop')
        runtime.release = self.release
        with patch.object(self.release, 'prepare'), patch.object(runtime, 'preflight', side_effect=RuntimeError('bad model')):
            with self.assertRaisesRegex(RuntimeError, 'bad model'):
                runtime.prepare_images(self.archive, threading.Event(), lambda message: None)


    def test_missing_release_never_falls_back_to_mutable_desktop_images(self):
        with patch('desktop_runtime.DEFAULT_MANIFEST', self.directory / 'missing.json'):
            with self.assertRaisesRegex(RuntimeError, 'No reviewed runtime release'):
                DesktopRuntime('https://grid.example/api', self.directory, 'Laptop')

    def test_schema_boolean_and_nonobject_manifest_are_rejected(self):
        self.data['schema_version'] = True
        with self.assertRaises(ValueError): self.write_release()
        self.manifest.write_text('[]')
        with self.assertRaises(ValueError): OfflineRelease(self.manifest)

    def test_invalid_manifest_field_types_and_oversize_fail_clearly(self):
        original = copy.deepcopy(self.data)
        for mutate in [lambda d: d.update(release=1), lambda d: d.update(archive=[]),
                lambda d: d['images']['dummy'].update(image_id=1),
                lambda d: d['images']['image_inference'].update(model_sha256=[]),
                lambda d: d['archive'].update(sha256=1)]:
            self.data = copy.deepcopy(original); mutate(self.data)
            with self.assertRaises(ValueError): self.write_release()
        self.manifest.write_bytes(b'a' * 65537)
        with self.assertRaisesRegex(ValueError, 'too large'): OfflineRelease(self.manifest)

    def test_failed_cooperative_stop_file_still_terminates_owned_child(self):
        cancel = threading.Event()
        process = MagicMock(); process.poll.return_value = None
        with patch('runtime_release.subprocess.Popen', return_value=process):
            with self.assertRaises(PreparationCancelled):
                run_command(['python', 'agent.py'], cancel, lambda message: cancel.set(),
                    request_stop=MagicMock(side_effect=OSError('disk full')))
        process.terminate.assert_called_once()

    def test_saved_cli_context_cannot_redirect_archive_to_another_engine(self):
        with patch.dict('os.environ', {'DOCKER_CONTEXT': 'unrelated-remote', 'DOCKER_HOST': 'tcp://local.test:2375'}):
            env = docker_cli_environment()
        self.assertNotIn('DOCKER_CONTEXT', env)
        self.assertEqual(env['DOCKER_HOST'], 'tcp://local.test:2375')


if __name__ == '__main__': unittest.main()
