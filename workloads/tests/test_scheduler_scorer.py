"""
E-Waste Compute Grid — Phase 5 Energy-Aware Scheduler Unit Tests
Owner: Nikhil Kumar (Workloads & Compute)
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from workloads.scheduler_scorer import (
    compute_worker_score,
    rank_workers_for_task,
    estimate_task_duration_and_energy
)



class TestSchedulerScorer(unittest.TestCase):

    def test_01_filter_missing_capabilities(self):
        worker = {
            "nodeId": "node-no-onnx",
            "capabilities": ["python3"],
            "performanceScore": 0.8
        }
        score, rationale, _ = compute_worker_score(
            worker,
            task_requirements={"requiredCapabilities": ["onnx_cpu", "python3"]}
        )
        self.assertEqual(score, 0.0)
        self.assertIn("Missing capabilities", rationale)

    def test_02_filter_insufficient_performance(self):
        worker = {
            "nodeId": "node-weak",
            "capabilities": ["onnx_cpu"],
            "performanceScore": 0.15
        }
        score, rationale, _ = compute_worker_score(
            worker,
            task_requirements={"requiredCapabilities": ["onnx_cpu"], "minPerformanceScore": 0.30}
        )
        self.assertEqual(score, 0.0)
        self.assertIn("below required", rationale)

    def test_03_thermal_throttling_penalty(self):
        cool_worker = {
            "nodeId": "cool-node",
            "deviceType": "desktop_standard",
            "capabilities": ["onnx_cpu"],
            "performanceScore": 0.8,
            "cpuUsagePercent": 20.0,
            "temperatureCelsius": 45.0
        }
        hot_worker = {
            "nodeId": "hot-node",
            "deviceType": "desktop_standard",
            "capabilities": ["onnx_cpu"],
            "performanceScore": 0.8,
            "cpuUsagePercent": 20.0,
            "temperatureCelsius": 82.0  # Throttling risk
        }

        score_cool, _, b_cool = compute_worker_score(cool_worker, {"requiredCapabilities": ["onnx_cpu"]})
        score_hot, _, b_hot = compute_worker_score(hot_worker, {"requiredCapabilities": ["onnx_cpu"]})

        self.assertGreater(score_cool, score_hot)
        self.assertEqual(b_hot["penalty_thermal"], 0.3)

    def test_04_energy_metric_labels(self):
        res = estimate_task_duration_and_energy("desktop_standard", performance_score=1.0, item_count=20)
        self.assertIn("estimatedEnergyWh", res)
        self.assertIn("metricType", res)
        self.assertEqual(res["metricType"], "ESTIMATED")

    def test_05_ranking_order(self):
        workers = [
            {"nodeId": "busy", "deviceType": "laptop_standard", "performanceScore": 0.5, "cpuUsagePercent": 95.0, "capabilities": ["onnx_cpu"]},
            {"nodeId": "idle", "deviceType": "laptop_standard", "performanceScore": 0.5, "cpuUsagePercent": 5.0, "capabilities": ["onnx_cpu"]}
        ]
        ranked = rank_workers_for_task(workers, {"requiredCapabilities": ["onnx_cpu"]})
        self.assertEqual(ranked[0]["nodeId"], "idle")
        self.assertEqual(ranked[1]["nodeId"], "busy")


if __name__ == "__main__":
    unittest.main()
