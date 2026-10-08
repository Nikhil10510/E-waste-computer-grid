"""
E-Waste Compute Grid — Phase 6 Energy & Environmental Test Suite
Owner: Nikhil Kumar (Workloads & Energy Lead)
"""

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from workloads.energy.power_meter import PowerMeter, measure_workload_energy
from workloads.energy.environmental_calculator import compute_environmental_impact


class TestEnergyAndEnvironmental(unittest.TestCase):

    def test_short_interval_includes_start_and_end_energy(self):
        meter = PowerMeter(device_type="laptop_standard", sample_interval_sec=0.1)
        meter.start()
        time.sleep(0.01)
        profile = meter.stop()
        self.assertGreater(profile["energyWh"], 0)
        expected = 45 * profile["executionTimeMs"] / 3_600_000
        self.assertAlmostEqual(profile["energyWh"], expected, delta=0.00003)

    def test_01_power_meter_integration_and_metric_type(self):
        """Verify numerical trapezoidal integration and metricType labeling."""
        with PowerMeter(device_type="laptop_standard") as meter:
            time.sleep(0.1)
        profile = meter.stop()

        self.assertIn("energyWh", profile)
        self.assertGreater(profile["energyWh"], 0.0)
        self.assertEqual(profile["metricType"], "ESTIMATED")
        self.assertEqual(profile["deviceType"], "laptop_standard")
        self.assertEqual(profile["averageWatts"], 45.0)

    def test_02_measured_power_override(self):
        """Simulate an external hardware wattmeter callback returning 52.5W."""
        mock_wattmeter = lambda: 52.5

        with PowerMeter(device_type="laptop_standard", external_meter_func=mock_wattmeter) as meter:
            time.sleep(0.1)
        profile = meter.stop()

        self.assertEqual(profile["metricType"], "MEASURED")
        self.assertEqual(profile["sensorSource"], "external_wattmeter")
        self.assertEqual(profile["averageWatts"], 52.5)

    def test_03_convenience_measure_workload_energy(self):
        """Verify wrapper function measures execution of a callable."""
        dummy_fn = lambda: sum(i * i for i in range(10_000))
        result, profile = measure_workload_energy(dummy_fn, device_type="desktop_standard")

        self.assertIsInstance(result, int)
        self.assertIn("energyWh", profile)
        self.assertIn("cloudSavings", profile)

    def test_04_environmental_impact_calculation(self):
        """Verify operational CO2, embodied carbon, and e-waste mass calculations."""
        res = compute_environmental_impact(
            total_energy_wh=10.0,
            cloud_baseline_energy_wh=25.0,
            total_execution_time_ms=360_000,  # 0.1 hours
            active_devices=["desktop_standard", "laptop_standard"],
            grid_region="global_average"
        )

        op = res["operational"]
        self.assertEqual(op["energySavedWh"], 15.0)
        self.assertEqual(op["energySavingsPercent"], 60.0)
        self.assertAlmostEqual(op["co2SavedGrams"], 15.0 * 0.42 / 1000.0 * 1000.0, places=3)

        life = res["hardwareLifeExtension"]
        self.assertEqual(life["activeDeviceCount"], 2)
        self.assertAlmostEqual(life["totalEwasteMassActiveKg"], 8.5 + 2.2, places=1)


if __name__ == "__main__":
    unittest.main()
