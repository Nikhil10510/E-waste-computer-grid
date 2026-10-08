"""
E-Waste Compute Grid — Task Runner Helper Module
Owner: Nikhil Kumar (Workloads & Compute)
Consumer: Vaibhav (Worker Agent Daemon)

This module provides a unified execution interface for the Worker Agent.
When the Worker Agent receives a task from the Control Plane, it calls:
    result_payload = execute_task(task_id, workload_type, input_dir, output_dir, device_type)

The Task Runner:
1. Determines execution mode (Docker container if available, otherwise native Python).
2. Spawns the appropriate workload (AI inference or Dummy mock).
3. Measures wall-clock execution time accurately.
4. Reads and validates the output result.json.
5. Computes energy consumption & green cloud savings using energy_calculator.py.
6. Formats the entire response into the exact POST /tasks/complete schema
   defined in docs/api_contracts.md (§4).
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

# Ensure standard output UTF-8 support
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Import energy calculator
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
try:
    from workloads.energy.energy_calculator import estimate_energy, calculate_cloud_savings
except ImportError:
    # Fallback if imported from another cwd
    from energy.energy_calculator import estimate_energy, calculate_cloud_savings


def check_docker_available() -> bool:
    """Check if Docker daemon is accessible."""
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return res.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False


def execute_task(
    task_id: str,
    workload_type: str = "IMAGE_CLASSIFICATION",
    input_dir: str = "",
    output_dir: str = "",
    device_type: str = "desktop_standard",
    is_measured_energy: bool = False,
    measured_watts: float = None,
    prefer_docker: bool = False
) -> dict:
    """
    Execute a compute task and return the completion payload for POST /tasks/complete.

    Args:
        task_id: Unique task identifier (UUID string).
        workload_type: "IMAGE_CLASSIFICATION" or "DUMMY".
        input_dir: Absolute path to directory containing input files/images.
        output_dir: Absolute path to directory where result.json should be written.
        device_type: Classified device type (e.g. "laptop_standard", "desktop_old").
        is_measured_energy: True if power is measured via smart plug / hardware meter.
        measured_watts: Measured wattage if is_measured_energy is True.
        prefer_docker: Try Docker if available, otherwise fallback to native Python.

    Returns:
        dict: Payload matching POST /tasks/complete contract.
    """
    aliases = {"IMAGE_CLASSIFICATION": "IMAGE_CLASSIFICATION", "IMAGE_INFERENCE": "IMAGE_CLASSIFICATION", "DUMMY": "DUMMY"}
    if workload_type.upper() not in aliases:
        raise ValueError("Unknown workload type")
    workload_type = aliases[workload_type.upper()]
    input_path = Path(input_dir).resolve()
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    
    result_json_path = output_path / "result.json"
    if result_json_path.exists():
        result_json_path.unlink()  # Remove stale results

    has_docker = prefer_docker and check_docker_available()
    workloads_root = Path(__file__).resolve().parent

    start_wall_time = time.perf_counter()
    exit_code = 0
    stderr_output = ""

    # Set up environment variables for the child process
    env = os.environ.copy()
    env["INPUT_DIR"] = str(input_path)
    env["OUTPUT_DIR"] = str(output_path)
    env["PYTHONUTF8"] = "1"

    if workload_type.upper() == "IMAGE_CLASSIFICATION":
        model_path = workloads_root / "ai-inference" / "models" / "mobilenetv2-12.onnx"
        labels_path = workloads_root / "ai-inference" / "models" / "imagenet_labels.json"
        script_path = workloads_root / "ai-inference" / "run_inference.py"

        env["MODEL_PATH"] = str(model_path)
        env["LABELS_PATH"] = str(labels_path)

        if has_docker:
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{input_path}:/data/input:ro",
                "-v", f"{output_path}:/data/output",
                "ewaste/ai-workload:v1"
            ]
        else:
            cmd = [sys.executable, str(script_path)]

    else:  # Default to DUMMY workload
        script_path = workloads_root / "dummy-workload" / "run_dummy.py"
        if has_docker:
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{input_path}:/data/input:ro",
                "-v", f"{output_path}:/data/output",
                "ewaste/dummy-workload:v1"
            ]
        else:
            cmd = [sys.executable, str(script_path)]

    # Execute workload process
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300
        )
        exit_code = proc.returncode
        stderr_output = proc.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stderr_output = "Task execution timed out after 300 seconds."
    except Exception as e:
        exit_code = -1
        stderr_output = str(e)

    duration_ms = int((time.perf_counter() - start_wall_time) * 1000)

    # If execution failed or result.json was not generated
    if exit_code != 0 or not result_json_path.exists():
        return {
            "taskId": task_id,
            "status": "FAILED",
            "executionTimeMs": duration_ms,
            "error": {
                "code": "EXECUTION_ERROR" if exit_code != -1 else "TIMEOUT",
                "message": stderr_output.strip() or f"Process exited with code {exit_code}",
                "retryable": True
            }
        }

    # Load result.json produced by the workload
    try:
        with open(result_json_path, "r", encoding="utf-8") as f:
            workload_result = json.load(f)
        if not isinstance(workload_result, dict) or workload_result.get("itemsProcessed", 0) <= 0:
            raise ValueError("Workload produced no successful items")
    except (OSError, ValueError) as error:
        return {"taskId": task_id, "status": "FAILED", "executionTimeMs": duration_ms,
                "error": {"code": "INVALID_RESULT", "message": str(error), "retryable": False}}

    # Compute Energy Metrics
    energy_data = estimate_energy(
        device_type=device_type,
        execution_time_ms=duration_ms,
        is_measured=is_measured_energy,
        measured_watts=measured_watts
    )

    savings_data = calculate_cloud_savings(
        total_energy_wh=energy_data["energyWh"],
        total_execution_time_ms=duration_ms
    )

    # Assemble completion payload strictly compliant with docs/api_contracts.md §4
    completion_payload = {
        "taskId": task_id,
        "status": "COMPLETED",
        "executionTimeMs": duration_ms,
        "itemsProcessed": workload_result.get("itemsProcessed", 0),
        "itemsFailed": workload_result.get("itemsFailed", 0),
        "result": workload_result,
        "energy": {
            "energyWh": energy_data["energyWh"],
            "powerWatts": energy_data["powerWatts"],
            "metricType": energy_data["metricType"],
            "cloudBaselineWh": savings_data["cloudEnergyWh"],
            "energySavedWh": savings_data["energySavedWh"],
            "co2SavedGrams": savings_data["co2SavedGrams"]
        }
    }

    return completion_payload


if __name__ == "__main__":
    print("[TASK_RUNNER] Running self-test...")
    test_input = BASE_DIR / "workloads" / "test-data" / "sample"
    test_output = BASE_DIR / "workloads" / "test-data" / "test_runner_output"
    
    sample_payload = execute_task(
        task_id="test-task-001",
        workload_type="IMAGE_CLASSIFICATION",
        input_dir=str(test_input),
        output_dir=str(test_output),
        device_type="desktop_standard"
    )
    print("[TASK_RUNNER] Self-test complete! Payload summary:")
    print(json.dumps({
        "taskId": sample_payload.get("taskId"),
        "status": sample_payload.get("status"),
        "executionTimeMs": sample_payload.get("executionTimeMs"),
        "itemsProcessed": sample_payload.get("itemsProcessed"),
        "energy": sample_payload.get("energy")
    }, indent=2))
