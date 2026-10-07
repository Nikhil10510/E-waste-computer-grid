import os
import platform
import psutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.energy.energy_calculator import POWER_LOOKUP_TABLE_WATTS
from workloads.benchmark.hardware_benchmark import classify_device_type


def get_hardware_specs(capabilities=None):
    cores = psutil.cpu_count(logical=True) or 1
    ram = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    device = classify_device_type({
        "architecture": platform.machine(),
        "ramGb": ram,
        "cpuCoresPhysical": psutil.cpu_count(logical=False) or cores,
    })
    return {
        "name": os.getenv("WORKER_NAME", platform.node()),
        "os": platform.system().lower(),
        "cpu_cores": cores,
        "ram_gb": ram,
        "capabilities": capabilities or ["dummy"],
        "baseline_power_w": POWER_LOOKUP_TABLE_WATTS.get(device, 35.0),
    }


def estimate_baseline_power(specs):
    return specs.get("baseline_power_w", 35.0)
