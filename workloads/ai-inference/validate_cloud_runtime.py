"""
E-Waste Compute Grid — Cloud-Connected Worker AI Runtime Validator
Owner: Nikhil Kumar (Workloads & Compute Lead)
Consumer: Vaibhav & Kushagra (Cloud Pipeline Verification)

Validates the complete cloud-connected AI inference lifecycle:
1. Input Data Fetch: Simulates receiving an S3 dataset chunk (or presigned download URL).
2. Model Verification: Ensures the ONNX model is verified and cached locally.
3. Execution: Runs MobileNetV2 batch inference using task_runner.
4. Energy Calculation: Computes task energy footprint and cloud savings.
5. Result Upload: Validates output package ready for S3 upload.
6. Timing Breakdown: Measures download latency, inference compute, and packaging overhead.
"""

import os
import sys
import json
import time
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any

# Ensure standard output UTF-8 support
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    from s3_model_manager import ModelArtifactManager
except ImportError:
    # If run from project root
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "s3_model_manager",
        Path(__file__).resolve().parent / "s3_model_manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ModelArtifactManager = mod.ModelArtifactManager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from workloads.task_runner import execute_task



def run_cloud_connected_simulation(
    task_id: str = "cloud-sim-task-001",
    sample_data_source: Path = None,
    device_type: str = "desktop_standard"
) -> Dict[str, Any]:
    """
    Simulates the exact end-to-end cloud task execution cycle performed by a Worker Agent.
    """
    timeline = {}
    total_start = time.perf_counter()

    # Step 1: Model check / verification
    t0 = time.perf_counter()
    mgr = ModelArtifactManager()
    model_status = mgr.ensure_model_available()
    timeline["modelCheckMs"] = int((time.perf_counter() - t0) * 1000)

    # Step 2: Prepare isolated task directories (simulating S3 chunk download)
    t0 = time.perf_counter()
    temp_dir = tempfile.mkdtemp(prefix="cloud_worker_task_")
    task_input = Path(temp_dir) / "input"
    task_output = Path(temp_dir) / "output"
    task_input.mkdir(parents=True)
    task_output.mkdir(parents=True)

    # Copy sample images into task input (simulating S3 download)
    source_dir = sample_data_source or (BASE_DIR / "workloads" / "test-data" / "sample")
    for img in source_dir.glob("*.*"):
        if img.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            shutil.copy2(img, task_input / img.name)
    timeline["inputStagingMs"] = int((time.perf_counter() - t0) * 1000)

    # Step 3: Execute AI Task via Task Runner
    t0 = time.perf_counter()
    completion_payload = execute_task(
        task_id=task_id,
        workload_type="IMAGE_CLASSIFICATION",
        input_dir=str(task_input),
        output_dir=str(task_output),
        device_type=device_type
    )
    timeline["workloadExecutionMs"] = int((time.perf_counter() - t0) * 1000)

    # Step 4: Validate Result Package
    result_file = task_output / "result.json"
    result_valid = result_file.exists() and result_file.stat().st_size > 100
    timeline["resultValidationMs"] = int((time.perf_counter() - t0) * 1000)

    total_duration_ms = int((time.perf_counter() - total_start) * 1000)

    # Clean up temporary staging directory
    shutil.rmtree(temp_dir, ignore_errors=True)

    validation_report = {
        "status": "SUCCESS" if result_valid and completion_payload["status"] == "COMPLETED" else "FAILED",
        "taskId": task_id,
        "deviceType": device_type,
        "itemsProcessed": completion_payload.get("itemsProcessed", 0),
        "totalWallClockMs": total_duration_ms,
        "timingBreakdown": timeline,
        "energy": completion_payload.get("energy", {}),
        "modelVerification": {
            "status": model_status.get("status"),
            "sha256": model_status.get("sha256")[:16] + "..."
        }
    }

    return validation_report


if __name__ == "__main__":
    print("[CLOUD_VALIDATOR] Running Cloud-Connected Worker AI Runtime Validation...")
    report = run_cloud_connected_simulation()
    print("[CLOUD_VALIDATOR] Validation Complete! Report:")
    print(json.dumps(report, indent=2))
