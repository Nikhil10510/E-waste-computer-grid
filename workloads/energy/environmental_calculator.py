"""
E-Waste Compute Grid — Comprehensive Environmental Impact Calculator
Owner: Nikhil Kumar (Workloads & Energy Lead)
Consumers: Chinmay (Dashboard Visuals), Kushagra (Job Reporting)

Computes the holistic environmental impact of executing distributed workloads on retired hardware:
1. Operational Carbon (Scope 2): Power draw * grid carbon intensity.
2. Embodied Carbon Amortization (Scope 3): Avoided new hardware manufacturing emissions.
3. E-Waste Diversion: Physical kilograms of electronic waste kept in active service.
4. Tangible Equivalencies: Trees planted equivalent, smartphone charges equivalent.
"""

from typing import Dict, Any

# Global standard emission & hardware factors (Sources: IEA, EPA, Dell/Apple LCA reports)
GRID_CARBON_INTENSITY_KG_PER_KWH = {
    "global_average": 0.42,  # IEA global grid average
    "us_average":     0.37,  # US EPA eGRID
    "india_average":  0.71,  # India CEA national grid (coal-weighted)
    "europe_average": 0.23,  # EEA EU-27 average
    "clean_green":    0.05   # Hydro / Solar / Wind predominant
}

# Average embodied carbon in device manufacturing (kg CO2e)
DEVICE_EMBODIED_CARBON_KG = {
    "desktop_standard":   320.0,
    "desktop_high_power": 450.0,
    "desktop_old":        280.0,
    "laptop_standard":    220.0,
    "laptop_low_power":   180.0,
    "raspberry_pi_4":      15.0,
    "raspberry_pi_3":      12.0,
    "cloud_server_gpu":   950.0  # Proportionate share of 1U/2U GPU server lifecycle
}

# Device physical weight for landfill diversion calculations (kg)
DEVICE_WEIGHT_KG = {
    "desktop_standard":   8.5,
    "desktop_high_power": 11.0,
    "desktop_old":        9.2,
    "laptop_standard":    2.2,
    "laptop_low_power":   1.5,
    "raspberry_pi_4":     0.15,
    "raspberry_pi_3":     0.12,
    "unknown":            4.0
}

# Typical hardware lifespan in hours (3 years @ 8 hrs/day ≈ 8,760 hours)
LIFESPAN_HOURS = 8760.0

# 1 mature tree absorbs ~21.77 kg CO2 per year (~0.0596 kg/day or 59.6 grams/day)
TREE_ABSORPTION_KG_PER_YEAR = 21.77

# 1 typical smartphone full charge consumes ~12 Wh
SMARTPHONE_CHARGE_WH = 12.0


def compute_environmental_impact(
    total_energy_wh: float,
    cloud_baseline_energy_wh: float,
    total_execution_time_ms: int,
    active_devices: list = None,
    grid_region: str = "global_average"
) -> Dict[str, Any]:
    """
    Calculate comprehensive environmental metrics comparing e-waste execution to cloud.

    Args:
        total_energy_wh: Total actual watt-hours consumed across all tasks.
        cloud_baseline_energy_wh: Baseline watt-hours if executed on AWS GPU instance.
        total_execution_time_ms: Cumulative wall-clock run time across tasks.
        active_devices: List of device_type strings utilized in the job.
        grid_region: Key for grid carbon intensity.

    Returns:
        dict: Full environmental statistics breakdown.
    """
    carbon_intensity = GRID_CARBON_INTENSITY_KG_PER_KWH.get(
        grid_region,
        GRID_CARBON_INTENSITY_KG_PER_KWH["global_average"]
    )

    # 1. Operational Energy & Carbon (Scope 2)
    actual_kwh = total_energy_wh / 1000.0
    cloud_kwh = cloud_baseline_energy_wh / 1000.0
    energy_saved_wh = max(0.0, cloud_baseline_energy_wh - total_energy_wh)
    energy_saved_kwh = energy_saved_wh / 1000.0

    actual_co2_kg = actual_kwh * carbon_intensity
    cloud_co2_kg = cloud_kwh * carbon_intensity
    co2_saved_kg = max(0.0, cloud_co2_kg - actual_co2_kg)
    co2_saved_grams = round(co2_saved_kg * 1000.0, 3)

    energy_savings_pct = (
        round((energy_saved_wh / cloud_baseline_energy_wh) * 100, 1)
        if cloud_baseline_energy_wh > 0
        else 0.0
    )

    # 2. Hardware Life Extension & Embodied Carbon (Scope 3)
    compute_hours = (total_execution_time_ms / 1000.0) / 3600.0
    devices = active_devices or ["desktop_standard"]
    
    # Average embodied carbon across the active machines
    avg_embodied_kg = sum(
        DEVICE_EMBODIED_CARBON_KG.get(d, 250.0) for d in devices
    ) / len(devices)

    # Embodied carbon amortized per compute hour
    embodied_co2_amortized_per_hour = avg_embodied_kg / LIFESPAN_HOURS
    embodied_co2_extended_grams = round(
        (embodied_co2_amortized_per_hour * compute_hours) * 1000.0, 3
    )

    # 3. E-Waste Landfill Mass in Active Service (kg)
    total_ewaste_diverted_kg = round(
        sum(DEVICE_WEIGHT_KG.get(d, 4.0) for d in devices), 2
    )

    # 4. Tangible Equivalencies
    smartphone_charges_saved = round(energy_saved_wh / SMARTPHONE_CHARGE_WH, 1)
    tree_days_equivalent = round((co2_saved_kg / (TREE_ABSORPTION_KG_PER_YEAR / 365.25)), 2)

    return {
        "operational": {
            "actualEnergyWh": round(total_energy_wh, 4),
            "cloudBaselineEnergyWh": round(cloud_baseline_energy_wh, 4),
            "energySavedWh": round(energy_saved_wh, 4),
            "energySavingsPercent": energy_savings_pct,
            "actualCo2Grams": round(actual_co2_kg * 1000.0, 3),
            "cloudCo2Grams": round(cloud_co2_kg * 1000.0, 3),
            "co2SavedGrams": co2_saved_grams,
            "gridRegion": grid_region,
            "carbonIntensityKgPerKwh": carbon_intensity
        },
        "hardwareLifeExtension": {
            "computeHoursDelivered": round(compute_hours, 5),
            "embodiedCarbonAmortizedGrams": embodied_co2_extended_grams,
            "totalEwasteMassActiveKg": total_ewaste_diverted_kg,
            "activeDeviceCount": len(devices)
        },
        "equivalencies": {
            "smartphoneChargesSaved": smartphone_charges_saved,
            "treeDaysEquivalent": tree_days_equivalent,
            "cleanAirHeadline": (
                f"Saved {co2_saved_grams:.1f}g CO2e and kept {total_ewaste_diverted_kg}kg "
                f"of computer hardware in active service."
            )
        }
    }


if __name__ == "__main__":
    import json

    # Example: 10,000 images processed across 3 mixed retired machines
    res = compute_environmental_impact(
        total_energy_wh=18.5,
        cloud_baseline_energy_wh=36.0,
        total_execution_time_ms=648_000,  # ~10.8 minutes
        active_devices=["desktop_standard", "laptop_standard", "raspberry_pi_4"],
        grid_region="global_average"
    )

    print("[ENVIRONMENTAL_CALCULATOR] Example Batch Run Impact:")
    print(json.dumps(res, indent=2))
