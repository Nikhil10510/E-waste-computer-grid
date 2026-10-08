import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('model_setup', Path(__file__).resolve().parents[1] / 'ai-inference/download_model.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ModelSetupTests(unittest.TestCase):
    def test_existing_changed_artifact_is_not_advertised_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'model.onnx'
            path.write_bytes(b'changed')
            with patch.object(setup.urllib.request, 'urlopen') as download:
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    setup.prepare_artifact(path, hashlib.sha256(b'approved').hexdigest(), 'https://example.invalid/model')
                download.assert_not_called()
            self.assertEqual(path.read_bytes(), b'changed')

    def test_download_failure_leaves_no_fallback_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'labels.json'
            with patch.object(setup.urllib.request, 'urlopen', side_effect=OSError('offline')):
                with self.assertRaises(OSError):
                    setup.prepare_artifact(path, '0' * 64, 'https://example.invalid/labels', labels=True)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_label_hash_is_portable_but_mapping_is_mandatory(self):
        raw = json.dumps({i: f'class_{i}' for i in range(1000)}, indent=2).encode()
        checksum = hashlib.sha256(raw).hexdigest()
        setup.verify(raw.replace(b'\n', b'\r\n'), checksum, labels=True)
        incomplete = b'{"0":"cat"}'
        with self.assertRaisesRegex(ValueError, '1000-class'):
            setup.verify(incomplete, hashlib.sha256(incomplete).hexdigest(), labels=True)


if __name__ == '__main__':
    unittest.main()
