"""Prepare checksum-pinned model and labels before building a workload image."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "models/artifact-manifest.json"
MODEL_URL = "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx"
LABELS_URL = "https://raw.githubusercontent.com/pytorch/hub/master/imagenet_classes.txt"


def verify(raw, expected_hash, labels=False):
    normalized = raw.replace(b"\r\n", b"\n") if labels else raw
    if hashlib.sha256(normalized).hexdigest() != expected_hash:
        raise ValueError("Artifact checksum mismatch; replace the changed file before inference")
    if labels:
        mapping = json.loads(raw)
        if not isinstance(mapping, dict) or set(mapping) != {str(i) for i in range(1000)}:
            raise ValueError("Expected the complete 1000-class label mapping")
        if any(not isinstance(label, str) or not label.strip() for label in mapping.values()):
            raise ValueError("Label names must be nonempty strings")


def prepare_artifact(path, expected_hash, url, labels=False):
    if path.exists():
        verify(path.read_bytes(), expected_hash, labels)
        print(f"Verified cached {path.name}")
        return
    # Never leave a partial artifact or manufacture labels on download failure.
    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError("Artifact exceeds download limit")
    if labels:
        names = raw.decode("utf-8").strip().splitlines()
        raw = json.dumps({i: name.strip() for i, name in enumerate(names)}, indent=2).encode("utf-8")
    verify(raw, expected_hash, labels)
    temporary = path.with_suffix(path.suffix + ".download")
    try:
        temporary.write_bytes(raw)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Downloaded and verified {path.name}")


def prepare(output):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    prepare_artifact(output / manifest["model_filename"], manifest["model_sha256"], MODEL_URL)
    prepare_artifact(output / manifest["labels_filename"], manifest["labels_sha256"], LABELS_URL, labels=True)
    destination = output / MANIFEST.name
    if destination.resolve() != MANIFEST.resolve():
        destination.write_bytes(MANIFEST.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o", type=Path, default=BASE / "models")
    args = parser.parse_args()
    try:
        prepare(args.output)
    except Exception as error:
        print(f"Setup failed: {error}. No fallback artifact was created.")
        return 1
    print(f"Model and labels ready in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
