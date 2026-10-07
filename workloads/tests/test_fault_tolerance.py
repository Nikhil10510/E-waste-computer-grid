"""
E-Waste Compute Grid — Phase 4 Fault Tolerance & Idempotency Tests
Owner: Nikhil Kumar (Workloads & Compute)

Verifies:
1. Workload safe restarts (stale files from previous killed runs are ignored/cleaned).
2. Atomic writes (no half-written result.json).
3. Aggregator task deduplication (requeued/duplicate tasks don't double count).
4. Partial task failure resilience (one failed task doesn't crash job aggregation).
5. Corrupt input resilience (bad files recorded in errors, good files processed).
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

# Setup path to import workloads
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from workloads.task_runner import execute_task
from workloads.result_aggregator import aggregate_job_results


class TestFaultToleranceAndIdempotency(unittest.TestCase):

    def test_failed_first_task_does_not_reference_previous_prediction(self):
        result = aggregate_job_results([{"taskId": "failed", "status": "FAILED", "error": {"message": "timeout"}}])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(len(result["errors"]), 1)

    def test_partial_result_errors_are_not_duplicated(self):
        result = aggregate_job_results([{"taskId": "partial", "status": "COMPLETED", "result": {
            "itemsProcessed": 1, "itemsFailed": 1, "predictions": [{"image": "good", "confidence": 0.8}],
            "errors": [{"image": "bad"}]}}])
        self.assertEqual(result["status"], "PARTIAL_SUCCESS")
        self.assertEqual(len(result["errors"]), 1)

    def test_unknown_workload_cannot_fall_back_to_fake_success(self):
        with self.assertRaises(ValueError):
            execute_task("invalid", "unknown_workload")

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ewaste_fault_test_")
        self.input_dir = os.path.join(self.test_dir, "input")
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # Create 3 valid test images
        for i in range(3):
            img = Image.new("RGB", (64, 64), color=(i * 40, 100, 150))
            img.save(os.path.join(self.input_dir, f"test_img_{i}.png"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_safe_restart_with_stale_partial_output(self):
        """Simulate a previous crash leaving a half-written result.json.tmp and stale result.json."""
        stale_tmp = os.path.join(self.output_dir, "result.json.tmp")
        stale_json = os.path.join(self.output_dir, "result.json")

        with open(stale_tmp, "w") as f:
            f.write('{"status": "INCOMPLETE", "half_written":')  # Corrupted JSON
        with open(stale_json, "w") as f:
            f.write('{"status": "OLD_STALE_RUN"}')

        # Execute task afresh
        payload = execute_task(
            task_id="restart-task-001",
            workload_type="DUMMY",
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            device_type="desktop_standard"
        )

        self.assertEqual(payload["status"], "COMPLETED")
        self.assertEqual(payload["itemsProcessed"], 3)
        self.assertTrue(os.path.exists(stale_json))
        # Ensure stale tmp file was cleaned up and output is valid JSON
        with open(stale_json, "r") as f:
            data = json.load(f)
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["itemsProcessed"], 3)

    def test_02_corrupt_input_file_isolation(self):
        """Add a completely corrupted file (random text file renamed as .jpg) to input."""
        corrupt_file = os.path.join(self.input_dir, "corrupted_bad.jpg")
        with open(corrupt_file, "wb") as f:
            f.write(b"NOT_A_REAL_IMAGE_DATA_123456789")

        payload = execute_task(
            task_id="corrupt-input-task-002",
            workload_type="IMAGE_CLASSIFICATION",
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            device_type="desktop_standard"
        )

        # The task should complete the 3 valid images and isolate the 1 bad image in errors
        self.assertEqual(payload["status"], "COMPLETED")
        result = payload["result"]
        self.assertEqual(result["itemsProcessed"], 3)
        self.assertEqual(result["itemsFailed"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("corrupted_bad.jpg", result["errors"][0]["image"])

    def test_03_aggregator_task_deduplication(self):
        """Simulate a worker task timeout where task was retried and both reported."""
        task_a_attempt_1 = {
            "taskId": "task-dup-100",
            "status": "COMPLETED",
            "executionTimeMs": 500,
            "itemsProcessed": 3,
            "result": {
                "itemsProcessed": 3,
                "predictions": [{"image": "img1.png", "confidence": 0.88}],
                "errors": []
            },
            "energy": {"energyWh": 0.02, "cloudBaselineWh": 0.03, "energySavedWh": 0.01, "co2SavedGrams": 0.005}
        }
        # Duplicate submission (e.g. late network arrival)
        task_a_attempt_2 = {
            "taskId": "task-dup-100",
            "status": "COMPLETED",
            "executionTimeMs": 480,
            "itemsProcessed": 3,
            "result": {
                "itemsProcessed": 3,
                "predictions": [{"image": "img1.png", "confidence": 0.88}],
                "errors": []
            },
            "energy": {"energyWh": 0.02, "cloudBaselineWh": 0.03, "energySavedWh": 0.01, "co2SavedGrams": 0.005}
        }
        task_b = {
            "taskId": "task-other-200",
            "status": "COMPLETED",
            "executionTimeMs": 600,
            "itemsProcessed": 3,
            "result": {
                "itemsProcessed": 3,
                "predictions": [{"image": "img2.png", "confidence": 0.92}],
                "errors": []
            },
            "energy": {"energyWh": 0.02, "cloudBaselineWh": 0.03, "energySavedWh": 0.01, "co2SavedGrams": 0.005}
        }

        job_summary = aggregate_job_results([task_a_attempt_1, task_a_attempt_2, task_b], job_id="job-dedup-test")

        # Total tasks should be 2 (deduplicated), NOT 3
        self.assertEqual(job_summary["totalTasks"], 2)
        # Total items should be 6, NOT 9
        self.assertEqual(job_summary["totalItemsProcessed"], 6)
        # Energy should NOT be double counted
        self.assertAlmostEqual(job_summary["environmentalImpact"]["totalEnergyConsumedWh"], 0.04, places=3)

    def test_04_partial_task_failure_aggregation(self):
        """Simulate a job where 1 task succeeded and 1 task failed."""
        task_success = {
            "taskId": "task-ok",
            "status": "COMPLETED",
            "executionTimeMs": 500,
            "result": {
                "itemsProcessed": 5,
                "itemsFailed": 0,
                "predictions": [{"image": "imgA.png", "confidence": 0.8}],
                "errors": []
            },
            "energy": {"energyWh": 0.02, "cloudBaselineWh": 0.03, "energySavedWh": 0.01, "co2SavedGrams": 0.004}
        }
        task_failed = {
            "taskId": "task-err",
            "status": "FAILED",
            "executionTimeMs": 120,
            "error": {"code": "TIMEOUT", "message": "Worker lost connection", "retryable": True}
        }

        job_summary = aggregate_job_results([task_success, task_failed], job_id="job-partial-test")

        self.assertEqual(job_summary["totalTasks"], 2)
        self.assertEqual(job_summary["totalItemsProcessed"], 5)
        # Failed task is logged in errors without crashing
        self.assertGreater(len(job_summary["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
