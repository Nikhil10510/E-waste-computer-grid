#!/usr/bin/env bash
# ===================================================
# E-Waste Compute Grid — Teammate Benchmark Runner
# Owner: Nikhil Kumar
# ===================================================
set -e

echo "[E-WASTE] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.8+."
    exit 1
fi

echo "[E-WASTE] Ensuring required packages are installed (numpy, psutil)..."
python3 -m pip install numpy psutil --quiet

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[E-WASTE] Running Hardware Detection and Matrix Benchmark..."
python3 "${SCRIPT_DIR}/hardware_benchmark.py" --verbose

echo ""
echo "[E-WASTE] Done! Please share the Score, GFLOPS, and Device Type printed above with Nikhil."
