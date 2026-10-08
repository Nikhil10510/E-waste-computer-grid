import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

MODULE_PATH = Path(__file__).resolve().parents[1] / "test-data/setup_sample_data.py"
spec = importlib.util.spec_from_file_location("setup_sample_data", MODULE_PATH)
dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dataset)


class DemoDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        image = Image.new("RGB", (8, 8), "red")
        image.putpixel((0, 0), (0, 0, 255))  # Synthetic fixture, not semantic evaluation.
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.raw = buffer.getvalue()
        self.manifest = self.root / "manifest.json"
        self.write_manifest(hashlib.sha256(self.raw).hexdigest())
        self.output = self.root / "photos"

    def write_manifest(self, checksum, filename="photo.png"):
        self.manifest.write_text(json.dumps({"images": [{"filename": filename,
            "source_url": "https://example.test/photo.png", "sha256": checksum}]}))

    def test_verified_download_is_cached_without_repeating_network(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(args)
            return io.BytesIO(self.raw)
        dataset.prepare_dataset(self.manifest, self.output, opener=opener)
        dataset.prepare_dataset(self.manifest, self.output, verify_only=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((self.output / "photo.png").read_bytes(), self.raw)

    def test_network_failure_creates_no_placeholder(self):
        def fail(*args, **kwargs):
            raise OSError("Network unavailable")
        with self.assertRaisesRegex(RuntimeError, "No fallback"):
            dataset.prepare_dataset(self.manifest, self.output, opener=fail)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_corrupt_cache_is_replaced_only_after_verified_download(self):
        self.output.mkdir()
        target = self.output / "photo.png"
        target.write_bytes(b"old placeholder")
        with self.assertRaises(RuntimeError):
            dataset.prepare_dataset(self.manifest, self.output, opener=lambda *a, **k: io.BytesIO(b"bad download"))
        self.assertEqual(target.read_bytes(), b"old placeholder")
        self.assertEqual(list(self.output.glob("*.tmp")), [])
        dataset.prepare_dataset(self.manifest, self.output, opener=lambda *a, **k: io.BytesIO(self.raw))
        self.assertEqual(target.read_bytes(), self.raw)

    def test_matching_checksum_cannot_accept_non_image_or_uniform_placeholder(self):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
        for raw in [b"not an image", buffer.getvalue()]:
            self.write_manifest(hashlib.sha256(raw).hexdigest())
            with self.assertRaises(RuntimeError):
                dataset.prepare_dataset(self.manifest, self.output, opener=lambda *a, **k: io.BytesIO(raw))
            self.assertFalse((self.output / "photo.png").exists())

    def test_verify_only_is_offline_and_manifest_paths_are_safe(self):
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            dataset.prepare_dataset(self.manifest, self.output, verify_only=True)
        self.write_manifest("0" * 64, "../escape.png")
        with self.assertRaises(ValueError):
            dataset.prepare_dataset(self.manifest, self.output)


if __name__ == "__main__":
    unittest.main()
