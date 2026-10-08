"""
E-Waste Compute Grid — Job Result Aggregator
Owner: Nikhil Kumar (Workloads & Compute)
Consumer: Kushagra (Control Plane / Scheduler)

Combines multiple completed Task results into a single consolidated Job Result.
Used when all tasks of a Job reach 'COMPLETED' status.

Input: List of task completion payloads (or list of task result.json dicts)
Output: Consolidated Job Result dictionary with aggregated inference metrics,
        energy metrics, and cloud savings totals.
"""

from typing import List, Dict, Any


def aggregate_job_results(task_results: List[Dict[str, Any]], job_id: str = "") -> Dict[str, Any]:
    """
    Aggregate multiple task results into a comprehensive Job completion summary.
    Includes fault-tolerance: deduplicates re-executed tasks and isolates partial/failed outputs.

    Args:
        task_results: List of completed task payloads (from POST /tasks/complete)
                      or list of result.json dictionaries.
        job_id: Identifier of the parent job.

    Returns:
        dict: Consolidated Job summary.
    """
    # Deduplicate by taskId (prevents double-counting if a task was requeued after timeout)
    deduped_tasks = {}
    for idx, task in enumerate(task_results):
        if not isinstance(task, dict):
            continue
        tid = task.get("taskId") or f"unidentified_task_{idx}"
        if tid in deduped_tasks:
            # Prefer COMPLETED over FAILED or partial
            if deduped_tasks[tid].get("status") != "COMPLETED" and task.get("status") == "COMPLETED":
                deduped_tasks[tid] = task
        else:
            deduped_tasks[tid] = task

    effective_tasks = list(deduped_tasks.values())
    total_tasks = len(effective_tasks)
    failed_tasks = sum(t.get("status") == "FAILED" for t in effective_tasks)
    total_items_processed = 0
    total_items_failed = 0
    total_execution_time_ms = 0
    total_energy_wh = 0.0
    total_cloud_baseline_wh = 0.0
    total_energy_saved_wh = 0.0
    total_co2_saved_grams = 0.0

    all_predictions = []
    all_errors = []
    confidences = []
    seen_images = set()

    for task in effective_tasks:
        # Check if task is full task payload or inner result
        res = task.get("result", task)
        if not isinstance(res, dict):
            res = {}
        energy = task.get("energy", {})
        if not isinstance(energy, dict):
            energy = {}

        total_items_processed += res.get("itemsProcessed", 0)
        total_items_failed += res.get("itemsFailed", 0)
        total_execution_time_ms += task.get("executionTimeMs", res.get("executionTimeMs", 0))

        # Accumulate energy metrics safely
        total_energy_wh += float(energy.get("energyWh", 0.0) or 0.0)
        total_cloud_baseline_wh += float(energy.get("cloudBaselineWh", 0.0) or 0.0)
        total_energy_saved_wh += float(energy.get("energySavedWh", 0.0) or 0.0)
        total_co2_saved_grams += float(energy.get("co2SavedGrams", 0.0) or 0.0)

        # Collect predictions with image deduplication
        preds = res.get("predictions", [])
        if isinstance(preds, list):
            for p in preds:
                if isinstance(p, dict):
                    img_name = p.get("image")
                    if img_name and img_name in seen_images:
                        continue  # Skip duplicate image prediction from retried tasks
                    if img_name:
                        seen_images.add(img_name)
                    all_predictions.append(p)
                    conf = p.get("confidence")
                    if isinstance(conf, (int, float)):
                        confidences.append(float(conf))

        # Collect errors
        errs = res.get("errors", [])
        if isinstance(errs, list):
            all_errors.extend(errs)
        if task.get("status") == "FAILED" and "error" in task:
            all_errors.append(task["error"])

    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    overall_savings_pct = (
        round((total_energy_saved_wh / total_cloud_baseline_wh) * 100, 1)
        if total_cloud_baseline_wh > 0
        else 0.0
    )

    aggregated_summary = {
        "jobId": job_id,
        "status": ("FAILED" if failed_tasks == total_tasks and total_tasks else
                   "PARTIAL_SUCCESS" if total_items_failed or failed_tasks else "COMPLETED"),
        "failedTasks": failed_tasks,
        "totalTasks": total_tasks,
        "totalItemsProcessed": total_items_processed,
        "totalItemsFailed": total_items_failed,
        "totalExecutionTimeMs": total_execution_time_ms,
        "summary": {
            "totalPredictions": len(all_predictions),
            "averageConfidence": avg_confidence,
            "errorCount": len(all_errors),
        },
        "environmentalImpact": {
            "totalEnergyConsumedWh": round(total_energy_wh, 4),
            "cloudBaselineEnergyWh": round(total_cloud_baseline_wh, 4),
            "totalEnergySavedWh": round(total_energy_saved_wh, 4),
            "totalCo2SavedGrams": round(total_co2_saved_grams, 3),
            "savingsPercent": overall_savings_pct
        },
        "predictions": all_predictions,
        "errors": all_errors
    }

    return aggregated_summary


if __name__ == "__main__":
    import json

    # Self-test with mock tasks
    mock_tasks = [
        {
            "taskId": "task-001",
            "executionTimeMs": 500,
            "result": {
                "itemsProcessed": 5,
                "itemsFailed": 0,
                "predictions": [{"image": f"img_{i}.jpg", "confidence": 0.85} for i in range(5)],
                "errors": []
            },
            "energy": {
                "energyWh": 0.015,
                "cloudBaselineWh": 0.025,
                "energySavedWh": 0.010,
                "co2SavedGrams": 0.004
            }
        },
        {
            "taskId": "task-002",
            "executionTimeMs": 600,
            "result": {
                "itemsProcessed": 5,
                "itemsFailed": 0,
                "predictions": [{"image": f"img_{i+5}.jpg", "confidence": 0.90} for i in range(5)],
                "errors": []
            },
            "energy": {
                "energyWh": 0.018,
                "cloudBaselineWh": 0.030,
                "energySavedWh": 0.012,
                "co2SavedGrams": 0.005
            }
        }
    ]

    job_result = aggregate_job_results(mock_tasks, job_id="job-abc-123")
    print("[AGGREGATOR] Self-test complete:")
    print(json.dumps(job_result, indent=2))
