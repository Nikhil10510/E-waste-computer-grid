"""Fetch the pinned real-photo demo set. Never create synthetic fallbacks."""

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent
MANIFEST_PATH = BASE / "demo-manifest.json"
DEMO_DIR = BASE / "demo"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def load_manifest(path=MANIFEST_PATH):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = manifest.get("images", [])
    if not entries:
        raise ValueError("Dataset manifest has no images")
    names = set()
    for entry in entries:
        name = entry.get("filename", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+\.(png|jpg|jpeg)", name) or name in names:
            raise ValueError("Unsafe or duplicate dataset filename")
        names.add(name)
        if not re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", "")):
            raise ValueError(f"Missing pinned checksum for {name}")
        if not entry.get("source_url", "").startswith("https://"):
            raise ValueError(f"Dataset source must use HTTPS: {name}")
    return manifest


def validate_image(path, expected_hash):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError("Image is empty or exceeds the download limit")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Image checksum does not match the pinned source")
    with Image.open(path) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Image dimensions exceed the demo limit")
        image.verify()
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        if all(low == high for low, high in rgb.getextrema()):
            raise ValueError("Solid-color placeholder is not a demonstration photograph")
        return {"width": image.width, "height": image.height}


def prepare_dataset(manifest_path=MANIFEST_PATH, output_dir=DEMO_DIR,
                    verify_only=False, opener=urllib.request.urlopen):
    manifest = load_manifest(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    verified = []
    for entry in manifest["images"]:
        target = output_dir / entry["filename"]
        try:
            dimensions = validate_image(target, entry["sha256"])
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            if verify_only:
                raise RuntimeError(f"Dataset is not ready: {target.name}: {error}") from error
            temporary = None
            try:
                request = urllib.request.Request(entry["source_url"], headers={"User-Agent": "E-Waste-Compute-Grid/1"})
                with opener(request, timeout=30) as response:
                    raw = response.read(MAX_IMAGE_BYTES + 1)
                if not 0 < len(raw) <= MAX_IMAGE_BYTES:
                    raise ValueError("Download is empty or exceeds size limit")
                with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".download-", suffix=".tmp", delete=False) as out:
                    temporary = Path(out.name)
                    out.write(raw)
                dimensions = validate_image(temporary, entry["sha256"])
                temporary.replace(target)
            except Exception as download_error:
                raise RuntimeError(f"Dataset download failed for {target.name}: {download_error}. No fallback image was created.") from download_error
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        verified.append({**entry, **dimensions})
        print(f"[DATA] Verified {target.name}")
    print(f"[DATA] Ready: {len(verified)} verified real-photo inputs in {output_dir}")
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEMO_DIR)
    parser.add_argument("--verify-only", action="store_true", help="Verify cached files without network access")
    args = parser.parse_args()
    try:
        prepare_dataset(output_dir=args.output, verify_only=args.verify_only)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[DATA] ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
