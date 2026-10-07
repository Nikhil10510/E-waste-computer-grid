"""
E-Waste Compute Grid — Energy Calculator
Owner: Nikhil Kumar

Calculates energy consumption for task execution based on device type
and execution time. Supports both MEASURED and ESTIMATED modes.

See docs/energy_specification.md for the full specification.
"""

import sys
import math

# Ensure standard output can handle Unicode characters on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# Hardware baseline wattage table (Active wattage under 70-100% CPU load)
# Source: CPU TDP ratings + peripheral overhead estimates
POWER_LOOKUP_TABLE_WATTS = {
    "raspberry_pi_4":     6.5,
    "raspberry_pi_3":     5.0,
    "laptop_low_power":   25.0,
    "laptop_standard":    45.0,
    "desktop_old":        95.0,
    "desktop_standard":   130.0,
    "desktop_high_power": 180.0,
    "unknown":            35.0,   # Conservative fallback
}

# Cloud baseline for savings comparison
# AWS g4dn.xlarge (T4 GPU) ≈ 200W total system power
CLOUD_BASELINE_WATTS = 200.0

# Global average grid carbon intensity: 0.42 kg CO₂/kWh
# Source: IEA (International Energy Agency)
CARBON_INTENSITY_KG_PER_KWH = 0.42


def estimate_energy(
    device_type: str,
    execution_time_ms: int,
    is_measured: bool = False,
    measured_watts: float = None
) -> dict:
    """
    Calculate energy consumed during a task execution.
    
    Args:
        device_type: Key from POWER_LOOKUP_TABLE_WATTS
        execution_time_ms: Wall-clock execution time in milliseconds
        is_measured: True if measured_watts comes from a real power meter
        measured_watts: Actual measured power draw (only used if is_measured=True)
    
    Returns:
        Energy metrics dict matching the API contract schema
    """
    if not math.isfinite(execution_time_ms) or execution_time_ms < 0:
        raise ValueError("Execution time must be finite and nonnegative")
    if is_measured and (measured_watts is None or not math.isfinite(measured_watts) or measured_watts <= 0):
        raise ValueError("Measured power must be finite and positive")
    # Determine power draw
    if is_measured and measured_watts is not None and measured_watts > 0:
        power_watts = measured_watts
        metric_type = "MEASURED"
    else:
        power_watts = POWER_LOOKUP_TABLE_WATTS.get(device_type, POWER_LOOKUP_TABLE_WATTS["unknown"])
        metric_type = "ESTIMATED"
    
    # Core formula: Energy (Wh) = Power (W) × Time (hours)
    hours = execution_time_ms / (1000.0 * 3600.0)
    energy_wh = power_watts * hours
    
    return {
        "energyWh": round(energy_wh, 6),
        "powerWatts": round(power_watts, 1),
        "metricType": metric_type,
        "deviceType": device_type,
        "executionTimeMs": execution_time_ms
    }


def calculate_cloud_savings(total_energy_wh: float, total_execution_time_ms: int) -> dict:
    """
    Calculate energy and CO₂ savings compared to running on cloud GPU instances.
    
    This is used by the dashboard for the "environmental impact" visualization.
    
    Args:
        total_energy_wh: Sum of energy from all completed tasks (Wh)
        total_execution_time_ms: Sum of execution times from all completed tasks (ms)
    
    Returns:
        Savings metrics dict
    """
    # Hypothetical equal-runtime comparison; not a measured same-work benchmark.
    if not math.isfinite(total_energy_wh) or total_energy_wh < 0 or not math.isfinite(total_execution_time_ms) or total_execution_time_ms < 0:
        raise ValueError("Energy and execution time must be finite and nonnegative")
    cloud_hours = total_execution_time_ms / (1000.0 * 3600.0)
    cloud_energy_wh = CLOUD_BASELINE_WATTS * cloud_hours
    
    # Energy saved
    energy_saved_wh = max(0, cloud_energy_wh - total_energy_wh)
    
    # CO₂ saved (grams)
    co2_saved_grams = energy_saved_wh * CARBON_INTENSITY_KG_PER_KWH
    
    # Hardware life extended (hours)
    hardware_life_hours = total_execution_time_ms / (1000.0 * 3600.0)
    
    return {
        "cloudBaselineWatts": CLOUD_BASELINE_WATTS,
        "comparisonAssumption": "Hypothetical 200 W system running for the same duration; not measured savings",
        "cloudEnergyWh": round(cloud_energy_wh, 4),
        "actualEnergyWh": round(total_energy_wh, 4),
        "energySavedWh": round(energy_saved_wh, 4),
        "co2SavedGrams": round(co2_saved_grams, 2),
        "hardwareLifeExtendedHours": round(hardware_life_hours, 4),
        "savingsPercent": round(
            (energy_saved_wh / cloud_energy_wh * 100) if cloud_energy_wh > 0 else 0,
            1
        )
    }


def get_power_for_device(device_type: str) -> float:
    """Get the baseline power draw for a device type."""
    return POWER_LOOKUP_TABLE_WATTS.get(device_type, POWER_LOOKUP_TABLE_WATTS["unknown"])


def list_device_types() -> dict:
    """Return the full lookup table (useful for debugging/display)."""
    return dict(POWER_LOOKUP_TABLE_WATTS)


# --- CLI usage for testing ---

if __name__ == "__main__":
    import json
    
    print("E-Waste Energy Calculator")
    print("=" * 40)
    
    # Example: laptop running a 2.5 second task
    result = estimate_energy(
        device_type="laptop_standard",
        execution_time_ms=2500,
        is_measured=False
    )
    print(f"\nExample - Laptop (estimated):")
    print(json.dumps(result, indent=2))
    
    # Example: measured power on a desktop
    result_measured = estimate_energy(
        device_type="desktop_old",
        execution_time_ms=5000,
        is_measured=True,
        measured_watts=87.3
    )
    print(f"\nExample - Desktop (measured):")
    print(json.dumps(result_measured, indent=2))
    
    # Example: cloud savings for a batch of 10 tasks
    savings = calculate_cloud_savings(
        total_energy_wh=0.35,  # Total across all tasks
        total_execution_time_ms=25000  # Total execution time
    )
    print(f"\nCloud Savings:")
    print(json.dumps(savings, indent=2))
    
    # Print the full lookup table
    print(f"\nPower Lookup Table:")
    for device, watts in POWER_LOOKUP_TABLE_WATTS.items():
        print(f"  {device:25s} → {watts:6.1f}W")
