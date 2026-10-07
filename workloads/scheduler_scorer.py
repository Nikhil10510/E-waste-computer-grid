"""
E-Waste Compute Grid — Intelligent & Energy-Aware Worker Scoring Engine
Owner: Nikhil Kumar (Workloads, Compute & Energy Lead)
Consumers: Kushagra (Scheduler Owner), Chinmay (Dashboard Visualization)

Provides the multi-factor scoring function used by the Scheduler to intelligently
rank candidate worker nodes for task assignment, and produces human-readable
rationale logs for the Dashboard and Judges.

Formula:
  Score = (W_perf * S_perf) + (W_avail * S_avail) + (W_energy * S_energy) - Penalty_thermal

Where:
  - S_perf: Normalized benchmark score (0.0 to 1.0)
  - S_avail: Current resource availability (1 - CPU load fraction, 0.0 to 1.0)
  - S_energy: Energy efficiency score (throughput per Watt, normalized 0.0 to 1.0)
  - Penalty_thermal: Thermal penalty if temperature exceeds threshold (throttling risk)
"""

import sys
from typing import Dict, Any, List, Tuple
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from workloads.energy.energy_calculator import POWER_LOOKUP_TABLE_WATTS, estimate_energy
except ImportError:
    from energy.energy_calculator import POWER_LOOKUP_TABLE_WATTS, estimate_energy

# Default weights (tuneable by Scheduler)
DEFAULT_WEIGHTS = {
    "perf": 0.40,      # Prioritize capable workers
    "avail": 0.30,     # Prioritize idle/unloaded workers
    "energy": 0.30,    # Prioritize low-energy / high-efficiency workers
}

# Empirical baseline throughput in images/sec for reference device classes
DEVICE_THROUGHPUT_MAP = {
    "desktop_standard":   40.0,
    "desktop_high_power": 45.0,
    "desktop_old":        15.0,
    "laptop_standard":    25.0,
    "laptop_low_power":   15.0,
    "raspberry_pi_4":      8.0,
    "raspberry_pi_3":      3.0,
    "unknown":            10.0
}


def estimate_task_duration_and_energy(
    device_type: str,
    performance_score: float,
    item_count: int = 10,
    is_measured: bool = False,
    measured_watts: float = None
) -> Dict[str, Any]:
    """
    Calculate estimated duration (ms) and energy (Wh) for a task on a specific device.

    Returns:
        dict: estimatedTimeMs, estimatedEnergyWh, metricType, powerWatts
    """
    # Estimate throughput (images/sec) scaled by worker performance score
    base_tps = DEVICE_THROUGHPUT_MAP.get(device_type, 10.0)
    # Blend base table with individual worker score (normalized 0.1 - 1.0)
    scaled_score = max(0.1, min(1.0, performance_score or 0.5))
    effective_tps = max(1.0, base_tps * (scaled_score / 0.8))  # normalized around 0.8 base

    estimated_seconds = item_count / effective_tps
    estimated_ms = int(estimated_seconds * 1000)

    energy_res = estimate_energy(
        device_type=device_type,
        execution_time_ms=estimated_ms,
        is_measured=is_measured,
        measured_watts=measured_watts
    )

    return {
        "estimatedTimeMs": estimated_ms,
        "estimatedEnergyWh": energy_res["energyWh"],
        "powerWatts": energy_res["powerWatts"],
        "metricType": energy_res["metricType"],  # Strictly labeled MEASURED or ESTIMATED
        "estimatedThroughputFps": round(effective_tps, 2)
    }


def compute_worker_score(
    worker: Dict[str, Any],
    task_requirements: Dict[str, Any] = None,
    weights: Dict[str, float] = None
) -> Tuple[float, str, Dict[str, float]]:
    """
    Compute a composite score (0.0 to 1.0) and human-readable selection rationale.

    Args:
        worker: Node dictionary containing capabilities, performanceScore, cpuUsage, etc.
        task_requirements: Dict with requiredCapabilities, minPerformanceScore, etc.
        weights: Custom weights for perf, avail, energy.

    Returns:
        (total_score, rationale_string, component_breakdown)
    """
    w = weights or DEFAULT_WEIGHTS
    task_req = task_requirements or {}

    # 1. Hard Filter: Capabilities check
    required_caps = set(task_req.get("requiredCapabilities", []))
    worker_caps = set(worker.get("capabilities", []))
    if not required_caps.issubset(worker_caps):
        missing = sorted(list(required_caps - worker_caps))
        return 0.0, f"Incompatible: Missing capabilities {missing}", {}

    min_perf = task_req.get("minPerformanceScore", 0.0)
    perf_score = float(worker.get("performanceScore", worker.get("benchmark", {}).get("performanceScore", 0.5)))
    if perf_score < min_perf:
        return 0.0, f"Incompatible: Performance score {perf_score:.2f} below required {min_perf:.2f}", {}

    # 2. Performance component (S_perf: 0.0 - 1.0)
    s_perf = max(0.0, min(1.0, perf_score))

    # 3. Availability component (S_avail: 0.0 - 1.0)
    # Based on current CPU usage fraction (0.0 = completely idle -> S_avail = 1.0)
    cpu_usage = float(worker.get("cpuUsagePercent", 20.0)) / 100.0
    s_avail = max(0.0, min(1.0, 1.0 - cpu_usage))

    # 4. Energy Efficiency component (S_energy: 0.0 - 1.0)
    # Efficiency is images/sec per Watt consumed.
    device_type = worker.get("deviceType", "unknown")
    power_watts = POWER_LOOKUP_TABLE_WATTS.get(device_type, 45.0)
    base_tps = DEVICE_THROUGHPUT_MAP.get(device_type, 10.0)
    efficiency_fps_per_watt = (base_tps * s_perf) / max(1.0, power_watts)
    
    # Max theoretical efficiency is Raspberry Pi ~ 8 FPS / 6.5W ≈ 1.23 FPS/W
    # Desktop ~ 40 FPS / 130W ≈ 0.31 FPS/W
    # Normalize efficiency to 0.0 - 1.0 range
    s_energy = max(0.0, min(1.0, efficiency_fps_per_watt / 1.5))

    # 5. Thermal penalty (Throttling avoidance)
    temp_c = worker.get("temperatureCelsius")
    penalty_thermal = 0.0
    thermal_note = ""
    if temp_c is not None:
        if temp_c >= 80.0:
            penalty_thermal = 0.30
            thermal_note = f", thermal warning ({temp_c}°C)"
        elif temp_c >= 70.0:
            penalty_thermal = 0.10
            thermal_note = f", warm ({temp_c}°C)"

    # Composite Score
    total_score = (
        (w["perf"] * s_perf) +
        (w["avail"] * s_avail) +
        (w["energy"] * s_energy) -
        penalty_thermal
    )
    total_score = max(0.0, min(1.0, round(total_score, 4)))

    breakdown = {
        "s_perf": round(s_perf, 3),
        "s_avail": round(s_avail, 3),
        "s_energy": round(s_energy, 3),
        "penalty_thermal": round(penalty_thermal, 3),
        "total_score": total_score
    }

    # Human-readable rationale
    node_id = worker.get("nodeId") or worker.get("hostname", "node")
    rationale = (
        f"Selected {node_id} (Score: {total_score:.3f}): "
        f"Perf {s_perf:.2f}, Avail {s_avail:.2f} ({int((1-cpu_usage)*100)}% idle), "
        f"Energy Eff {s_energy:.2f} ({device_type} ~{power_watts:.0f}W)"
        f"{thermal_note}"
    )

    return total_score, rationale, breakdown


def rank_workers_for_task(
    workers: List[Dict[str, Any]],
    task_requirements: Dict[str, Any] = None,
    weights: Dict[str, float] = None
) -> List[Dict[str, Any]]:
    """
    Rank all active workers for an incoming task from best to worst.

    Returns:
        List of candidate dictionaries sorted by score descending, with selection rationale.
    """
    ranked = []
    for w in workers:
        score, rationale, breakdown = compute_worker_score(w, task_requirements, weights)
        if score > 0.0:  # Compatible
            ranked.append({
                "nodeId": w.get("nodeId") or w.get("hostname"),
                "score": score,
                "rationale": rationale,
                "breakdown": breakdown,
                "worker": w
            })

    # Sort descending by score
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


if __name__ == "__main__":
    import json

    print("[SCHEDULER_SCORER] Running self-test with sample nodes...")

    # Sample worker pool
    candidates = [
        {
            "nodeId": "worker-rpi4-01",
            "hostname": "pi-cluster-node1",
            "deviceType": "raspberry_pi_4",
            "performanceScore": 0.25,
            "cpuUsagePercent": 10.0,
            "capabilities": ["onnx_cpu", "python3", "ram_ge_2gb"],
            "temperatureCelsius": 48.0
        },
        {
            "nodeId": "worker-laptop-02",
            "hostname": "old-dell-laptop",
            "deviceType": "laptop_standard",
            "performanceScore": 0.65,
            "cpuUsagePercent": 85.0,  # Busy!
            "capabilities": ["onnx_cpu", "python3", "ram_ge_2gb", "ram_ge_4gb"],
            "temperatureCelsius": 74.0  # Warm!
        },
        {
            "nodeId": "worker-desktop-03",
            "hostname": "DESKTOP-MI5QIC8",
            "deviceType": "desktop_standard",
            "performanceScore": 1.00,
            "cpuUsagePercent": 15.0,  # Idle
            "capabilities": ["onnx_cpu", "python3", "ram_ge_2gb", "ram_ge_4gb", "cpu_ge_4cores"],
            "temperatureCelsius": 42.0
        }
    ]

    task_req = {
        "requiredCapabilities": ["onnx_cpu", "python3"],
        "minPerformanceScore": 0.20
    }

    results = rank_workers_for_task(candidates, task_req)
    for idx, r in enumerate(results, 1):
        print(f"\nRank {idx}: {r['nodeId']} (Score: {r['score']})")
        print(f"  Rationale: {r['rationale']}")
        print(f"  Breakdown: {r['breakdown']}")
