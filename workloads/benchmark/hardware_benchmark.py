"""
E-Waste Compute Grid — Hardware Benchmark Script
Owner: Nikhil Kumar

Runs at Worker Agent startup to classify the machine's processing
capability into a normalized score (0.0–1.0).

This score feeds into the Scheduler's scoring formula for intelligent
task assignment.

Usage:
    python hardware_benchmark.py
    python hardware_benchmark.py --iterations 10 --verbose
"""

import os
import sys
import json
import time
import platform

# Ensure standard output can handle Unicode box-drawing characters on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_hardware_info() -> dict:
    """Detect hardware specifications using psutil."""
    info = {
        "hostname": platform.node(),
        "os": platform.system().lower(),
        "architecture": platform.machine(),
        "pythonVersion": platform.python_version(),
        "cpuModel": platform.processor() or "unknown",
        "cpuCores": os.cpu_count() or 1,
        "cpuCoresPhysical": os.cpu_count() or 1,
    }
    
    if HAS_PSUTIL:
        info["cpuCoresPhysical"] = psutil.cpu_count(logical=False) or 1
        info["cpuCores"] = psutil.cpu_count(logical=True) or 1
        
        freq = psutil.cpu_freq()
        if freq:
            info["cpuFrequencyMhz"] = int(freq.max or freq.current)
        
        mem = psutil.virtual_memory()
        info["ramGb"] = round(mem.total / (1024 ** 3), 1)
        
        disk = psutil.disk_usage("/")
        info["diskFreeGb"] = round(disk.free / (1024 ** 3), 1)
    
    return info


def classify_device_type(hardware: dict) -> str:
    """
    Classify hardware into a device type for energy estimation.
    See docs/energy_specification.md for the full lookup table.
    """
    arch = hardware.get("architecture", "").lower()
    ram_gb = hardware.get("ramGb", 4)
    cores = hardware.get("cpuCoresPhysical", 2)
    
    if "arm" in arch or "aarch64" in arch:
        if ram_gb <= 4:
            return "raspberry_pi_4"
        else:
            return "laptop_low_power"
    elif cores <= 2 and ram_gb <= 4:
        return "laptop_low_power"
    elif cores <= 4 and ram_gb <= 8:
        return "laptop_standard"
    elif cores <= 4 and ram_gb <= 16:
        return "desktop_old"
    elif cores <= 8:
        return "desktop_standard"
    else:
        return "desktop_high_power"


def run_matrix_benchmark(iterations: int = 5, matrix_size: int = 1000) -> dict:
    """
    CPU benchmark using matrix multiplication.
    
    This measures raw floating-point throughput which correlates
    well with inference performance on CPU.
    """
    if not HAS_NUMPY:
        return run_fallback_benchmark(iterations)
    
    # Warm-up run (excluded from timing)
    a = np.random.rand(100, 100).astype(np.float32)
    b = np.random.rand(100, 100).astype(np.float32)
    _ = np.dot(a, b)
    
    # Timed runs
    times = []
    for i in range(iterations):
        a = np.random.rand(matrix_size, matrix_size).astype(np.float32)
        b = np.random.rand(matrix_size, matrix_size).astype(np.float32)
        
        start = time.perf_counter()
        _ = np.dot(a, b)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    
    # GFLOPS estimate: matrix multiply of NxN requires ~2*N^3 FLOPs
    gflops = (2 * matrix_size ** 3) / (avg_time * 1e9)
    
    # Normalize score: ~10 GFLOPS = score 1.0 (modern laptop)
    # Raspberry Pi 4 gets ~0.5 GFLOPS → score ~0.05
    # Old laptop gets ~3 GFLOPS → score ~0.3
    # Modern laptop gets ~10+ GFLOPS → score 1.0
    score = round(min(1.0, max(0.05, gflops / 10.0)), 2)
    
    return {
        "benchmarkType": f"matrix_multiply_{matrix_size}x{matrix_size}",
        "iterations": iterations,
        "avgTimeSeconds": round(avg_time, 4),
        "minTimeSeconds": round(min(times), 4),
        "maxTimeSeconds": round(max(times), 4),
        "estimatedGflops": round(gflops, 2),
        "performanceScore": score,
        "benchmarkDurationSeconds": round(sum(times), 3)
    }


def run_fallback_benchmark(iterations: int = 5) -> dict:
    """
    Fallback benchmark without numpy — uses pure Python math.
    Less accurate but works everywhere.
    """
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        # Simple compute: sum of squares
        total = sum(i * i for i in range(500000))
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    # Rough normalization: ~0.1s on modern laptop = score 1.0
    score = round(min(1.0, max(0.05, 0.1 / avg_time)), 2)
    
    return {
        "benchmarkType": "sum_of_squares_500k",
        "iterations": iterations,
        "avgTimeSeconds": round(avg_time, 4),
        "performanceScore": score,
        "benchmarkDurationSeconds": round(sum(times), 3),
        "note": "Fallback benchmark (numpy not available)"
    }


def detect_capabilities(hardware: dict) -> list:
    """
    Build capability flags list based on detected hardware.
    See docs/capability_flags.md for full specification.
    """
    caps = []
    
    # Python version
    if sys.version_info >= (3, 8):
        caps.append("python3")
    
    # Docker availability
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            caps.append("docker_available")
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    
    # ONNX Runtime availability (may be inside Docker only)
    try:
        import onnxruntime
        caps.append("onnx_cpu")
    except ImportError:
        # ONNX is inside the Docker container, not on the host
        # Mark as available if Docker is available (container has it)
        if "docker_available" in caps:
            caps.append("onnx_cpu")
    
    # RAM thresholds
    ram_gb = hardware.get("ramGb", 0)
    if ram_gb >= 2:
        caps.append("ram_ge_2gb")
    if ram_gb >= 4:
        caps.append("ram_ge_4gb")
    if ram_gb >= 8:
        caps.append("ram_ge_8gb")
    
    # CPU core thresholds
    cores = hardware.get("cpuCoresPhysical", 1)
    if cores >= 2:
        caps.append("cpu_ge_2cores")
    if cores >= 4:
        caps.append("cpu_ge_4cores")
    
    # Disk space
    disk_free = hardware.get("diskFreeGb", 0)
    if disk_free >= 5:
        caps.append("disk_ge_5gb")
    
    # Derived capabilities
    if "onnx_cpu" in caps and "ram_ge_2gb" in caps and "docker_available" in caps:
        caps.append("image_classification")
    if "docker_available" in caps:
        caps.append("batch_processing")
    
    return sorted(caps)


def run_full_benchmark(iterations: int = 5, verbose: bool = False) -> dict:
    """
    Run the complete hardware detection + benchmark suite.
    Returns the full payload for worker registration.
    """
    print("[BENCH] ═══════════════════════════════════════════")
    print("[BENCH]   E-Waste Compute Grid — Hardware Benchmark")
    print("[BENCH] ═══════════════════════════════════════════")
    
    # Step 1: Hardware detection
    print("[BENCH] Detecting hardware...")
    hardware = get_hardware_info()
    device_type = classify_device_type(hardware)
    
    print(f"[BENCH]   Hostname:    {hardware.get('hostname', 'unknown')}")
    print(f"[BENCH]   OS:          {hardware.get('os', 'unknown')}")
    print(f"[BENCH]   CPU:         {hardware.get('cpuModel', 'unknown')}")
    print(f"[BENCH]   Cores:       {hardware.get('cpuCoresPhysical', '?')} physical / {hardware.get('cpuCores', '?')} logical")
    print(f"[BENCH]   RAM:         {hardware.get('ramGb', '?')} GB")
    print(f"[BENCH]   Disk Free:   {hardware.get('diskFreeGb', '?')} GB")
    print(f"[BENCH]   Device Type: {device_type}")
    
    # Step 2: Run benchmark
    print(f"[BENCH] Running benchmark ({iterations} iterations)...")
    benchmark = run_matrix_benchmark(iterations)
    
    print(f"[BENCH]   Score:    {benchmark['performanceScore']}")
    print(f"[BENCH]   Avg Time: {benchmark['avgTimeSeconds']}s per iteration")
    if "estimatedGflops" in benchmark:
        print(f"[BENCH]   GFLOPS:  {benchmark['estimatedGflops']}")
    
    # Step 3: Detect capabilities
    print("[BENCH] Detecting capabilities...")
    capabilities = detect_capabilities(hardware)
    print(f"[BENCH]   Flags: {capabilities}")
    
    # Build registration payload
    result = {
        "hostname": hardware.get("hostname", "unknown"),
        "os": hardware.get("os", "unknown"),
        "architecture": hardware.get("architecture", "unknown"),
        "hardware": {
            "cpuModel": hardware.get("cpuModel", "unknown"),
            "cpuCores": hardware.get("cpuCoresPhysical", 1),
            "cpuFrequencyMhz": hardware.get("cpuFrequencyMhz", 0),
            "ramGb": hardware.get("ramGb", 0),
            "diskFreeGb": hardware.get("diskFreeGb", 0)
        },
        "capabilities": capabilities,
        "deviceType": device_type,
        "benchmark": benchmark
    }
    
    print("[BENCH] ═══════════════════════════════════════════")
    print(f"[BENCH] ✅ Benchmark complete! Score: {benchmark['performanceScore']}")
    print("[BENCH] ═══════════════════════════════════════════")
    
    if verbose:
        print("\n[BENCH] Full registration payload:")
        print(json.dumps(result, indent=2))
    
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="E-Waste Hardware Benchmark")
    parser.add_argument("--iterations", "-n", type=int, default=5,
                        help="Number of benchmark iterations (default: 5)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print full JSON payload")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Save result to JSON file")
    args = parser.parse_args()
    
    result = run_full_benchmark(iterations=args.iterations, verbose=args.verbose)
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[BENCH] Saved to {args.output}")
