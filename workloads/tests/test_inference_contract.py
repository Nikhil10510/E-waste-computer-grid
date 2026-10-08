import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('inference', Path(__file__).resolve().parents[1] / 'ai-inference/run_inference.py')
inference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inference)


class InferenceContractTests(unittest.TestCase):
    def test_labels_require_complete_nonempty_class_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'labels.json'
            for labels in [[], {'0': 'cat'}, {str(i): '' for i in range(1000)}, 42]:
                path.write_text(json.dumps(labels))
                with self.assertRaises(ValueError):
                    inference.load_labels(str(path))
            path.write_text(json.dumps([f'class_{i}' for i in range(1000)]))
            self.assertEqual(len(inference.load_labels(str(path))), 1000)

    def test_artifact_preflight_rejects_changed_model_or_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model, labels, manifest = root/'model.onnx', root/'labels.json', root/'artifact-manifest.json'
            model.write_bytes(b'test-model'); labels.write_bytes(b'test-labels\n')
            manifest.write_text(json.dumps({'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
                                           'labels_sha256': hashlib.sha256(labels.read_bytes()).hexdigest()}))
            with patch.object(inference, 'MODEL_PATH', str(model)), patch.object(inference, 'LABELS_PATH', str(labels)), patch.object(inference, 'ARTIFACT_MANIFEST', str(manifest)):
                inference.verify_artifacts()
                labels.write_bytes(b'test-labels\r\n')
                inference.verify_artifacts()
                labels.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    inference.verify_artifacts()


if __name__ == '__main__':
    unittest.main()
