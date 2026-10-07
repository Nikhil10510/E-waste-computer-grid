"""
Download MobileNetV2 ONNX model from the ONNX Model Zoo.
Run this script during Docker image build or locally to cache the model.

Usage:
    python download_model.py
    python download_model.py --output ./models/
"""

import os
import sys
import hashlib
import urllib.request

# Ensure standard output can handle Unicode characters on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# MobileNetV2 from ONNX Model Zoo
MODEL_URL = "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx"
MODEL_FILENAME = "mobilenetv2-12.onnx"

# Expected SHA256 for integrity verification
EXPECTED_SHA256 = "c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5"


# ImageNet labels (1000 classes)
LABELS_URL = "https://raw.githubusercontent.com/pytorch/hub/master/imagenet_classes.txt"
LABELS_FILENAME = "imagenet_labels.json"


def download_file(url: str, output_path: str, description: str = "file"):
    """Download a file with progress indication."""
    print(f"[INFO] Downloading {description}...")
    print(f"[INFO] URL: {url}")
    print(f"[INFO] Output: {output_path}")
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        urllib.request.urlretrieve(url, output_path)
        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[INFO] ✅ Downloaded {description} ({file_size_mb:.1f} MB)")
    except Exception as e:
        print(f"[ERROR] Failed to download {description}: {e}")
        sys.exit(1)


def verify_checksum(file_path: str, expected_hash: str) -> bool:
    """Verify SHA256 checksum of downloaded file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual_hash = sha256.hexdigest()
    
    if actual_hash != expected_hash:
        print(f"[WARN] Checksum mismatch!")
        print(f"[WARN]   Expected: {expected_hash}")
        print(f"[WARN]   Actual:   {actual_hash}")
        return False
    
    print(f"[INFO] ✅ Checksum verified: {actual_hash[:16]}...")
    return True


def download_labels(output_dir: str):
    """Download ImageNet class labels and convert to JSON format."""
    import json
    
    labels_path = os.path.join(output_dir, LABELS_FILENAME)
    
    if os.path.exists(labels_path):
        print(f"[INFO] Labels already exist: {labels_path}")
        return
    
    print("[INFO] Downloading ImageNet class labels...")
    
    try:
        response = urllib.request.urlopen(LABELS_URL)
        labels_text = response.read().decode("utf-8")
        labels_list = [line.strip() for line in labels_text.strip().split("\n")]
        
        # Save as JSON dict: {0: "tench", 1: "goldfish", ...}
        labels_dict = {i: label for i, label in enumerate(labels_list)}
        
        with open(labels_path, "w") as f:
            json.dump(labels_dict, f, indent=2)
        
        print(f"[INFO] ✅ Saved {len(labels_dict)} class labels to {labels_path}")
    except Exception as e:
        print(f"[WARN] Failed to download labels: {e}")
        print("[WARN] Inference will still work, but predictions won't have human-readable names.")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Download MobileNetV2 ONNX model")
    parser.add_argument(
        "--output", "-o",
        default="./models",
        help="Output directory for model files (default: ./models)"
    )
    args = parser.parse_args()
    
    output_dir = os.path.abspath(args.output)
    model_path = os.path.join(output_dir, MODEL_FILENAME)
    
    # Download model
    if os.path.exists(model_path):
        print(f"[INFO] Model already exists: {model_path}")
    else:
        download_file(MODEL_URL, model_path, "MobileNetV2 ONNX model")
    
    # Verify checksum (if available)
    if EXPECTED_SHA256:
        if not verify_checksum(model_path, EXPECTED_SHA256):
            raise RuntimeError("Model checksum mismatch; replace this artifact before inference")
    else:
        # Print hash for future reference
        sha256 = hashlib.sha256()
        with open(model_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        print(f"[INFO] Model SHA256: {sha256.hexdigest()}")
        print("[INFO] (Set EXPECTED_SHA256 in this script to enable verification)")
    
    # Download labels
    download_labels(output_dir)
    
    print(f"\n[INFO] ✅ All model files ready in {output_dir}/")
    print(f"[INFO]   Model:  {MODEL_FILENAME}")
    print(f"[INFO]   Labels: {LABELS_FILENAME}")


if __name__ == "__main__":
    main()
