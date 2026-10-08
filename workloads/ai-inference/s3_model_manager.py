"""
E-Waste Compute Grid — S3 Model Artifact Manager
Owner: Nikhil Kumar (Workloads & Compute Lead)
Consumer: Vaibhav (Worker Agent Cloud Connectivity)

Manages AI model artifacts in controlled cloud storage (AWS S3) and local worker caching:
1. Downloads MobileNetV2 ONNX FP32 & ImageNet labels from S3 (or presigned URLs).
2. Verifies cryptographic SHA-256 integrity to ensure untampered models.
3. Implements local caching: only downloads if model is missing or hash mismatch.
4. Zero AWS credentials required on worker nodes when using Pre-signed S3 URLs.
"""

import os
import sys
import hashlib
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure standard output UTF-8 support
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_MODEL_DIR = Path(__file__).resolve().parent / "models"
LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Frozen artifact metadata
MODEL_FILENAME = "mobilenetv2-12.onnx"
LABELS_FILENAME = "imagenet_labels.json"
EXPECTED_MODEL_SHA256 = "c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5"

DEFAULT_S3_BUCKET = os.getenv("S3_MODELS_BUCKET", "ewaste-grid-models")
DEFAULT_S3_KEY = f"models/v1/{MODEL_FILENAME}"


def compute_file_sha256(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


class ModelArtifactManager:
    """
    Manages downloading, caching, and verifying AI model artifacts.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir or LOCAL_MODEL_DIR).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.cache_dir / MODEL_FILENAME
        self.labels_path = self.cache_dir / LABELS_FILENAME

    def is_model_cached_and_valid(self) -> bool:
        """Check if model exists locally and passes SHA256 integrity verification."""
        if not self.model_path.exists() or self.model_path.stat().st_size < 1000:
            return False
        
        actual_hash = compute_file_sha256(self.model_path)
        return actual_hash == EXPECTED_MODEL_SHA256

    def ensure_model_available(
        self,
        presigned_url: Optional[str] = None,
        s3_client: Any = None,
        bucket: str = DEFAULT_S3_BUCKET,
        key: str = DEFAULT_S3_KEY
    ) -> Dict[str, Any]:
        """
        Ensure model is available locally.
        If already cached and verified, returns immediately with zero network overhead.
        Otherwise downloads from presigned URL, boto3 S3 client, or official backup zoo.
        """
        if self.is_model_cached_and_valid():
            return {
                "status": "CACHED",
                "modelPath": str(self.model_path),
                "labelsPath": str(self.labels_path),
                "sha256": EXPECTED_MODEL_SHA256,
                "downloaded": False
            }

        print(f"[MODEL_MANAGER] Model not in cache or hash mismatch. Downloading...")
        download_success = False

        # Method 1: Pre-signed URL (Recommended for secure, credential-less workers)
        if presigned_url:
            print(f"[MODEL_MANAGER] Fetching via Pre-signed URL...")
            try:
                urllib.request.urlretrieve(presigned_url, str(self.model_path))
                download_success = True
            except Exception as e:
                print(f"[MODEL_MANAGER] ⚠ Presigned download failed: {e}")

        # Method 2: Boto3 S3 Client (If worker has direct AWS role / credentials)
        if not download_success and s3_client:
            print(f"[MODEL_MANAGER] Fetching via Boto3 s3://{bucket}/{key}...")
            try:
                s3_client.download_file(bucket, key, str(self.model_path))
                download_success = True
            except Exception as e:
                print(f"[MODEL_MANAGER] ⚠ S3 direct download failed: {e}")

        # Method 3: Backup Model Zoo URL fallback
        if not download_success:
            print(f"[MODEL_MANAGER] Fetching via official Model Zoo fallback...")
            fallback_url = "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx"
            try:
                urllib.request.urlretrieve(fallback_url, str(self.model_path))
                download_success = True
            except Exception as e:
                raise RuntimeError(f"All model download channels failed: {e}")

        # Verify integrity
        actual_hash = compute_file_sha256(self.model_path)
        if actual_hash != EXPECTED_MODEL_SHA256:
            self.model_path.unlink(missing_ok=True)
            raise ValueError(
                f"Model integrity verification failed! Expected {EXPECTED_MODEL_SHA256}, got {actual_hash}"
            )

        print(f"[MODEL_MANAGER] ✅ Model verified successfully (SHA256: {actual_hash[:16]}...)")
        return {
            "status": "DOWNLOADED_AND_VERIFIED",
            "modelPath": str(self.model_path),
            "labelsPath": str(self.labels_path),
            "sha256": actual_hash,
            "downloaded": True
        }


if __name__ == "__main__":
    import json
    mgr = ModelArtifactManager()
    status = mgr.ensure_model_available()
    print("[MODEL_MANAGER] Status:")
    print(json.dumps(status, indent=2))
