"""
E-Waste Compute Grid — Dummy Workload
A lightweight mock workload for testing the pipeline end-to-end
without needing ONNX Runtime or a real model.

This unblocks Kushagra (control-plane) and Vaibhav (worker agent)
immediately — they can test task assignment, execution, and completion
while Nikhil builds the real AI workload.
"""

import os
import sys
import json
import time
import random
import hashlib

# Ensure standard output can handle Unicode characters on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


INPUT_DIR = os.getenv("INPUT_DIR", "/data/input")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/output")

# Simulated processing delay per file (seconds)
PROCESSING_DELAY_PER_FILE = float(os.getenv("PROCESSING_DELAY", "0.1"))


def main():
    start_time = time.perf_counter()
    
    print("[DUMMY] Starting dummy workload...")
    print(f"[DUMMY] Input:  {INPUT_DIR}")
    print(f"[DUMMY] Output: {OUTPUT_DIR}")
    print(f"[DUMMY] Delay per file: {PROCESSING_DELAY_PER_FILE}s")
    
    # Discover input files
    if os.path.isdir(INPUT_DIR):
        input_files = sorted(f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f)))
    else:
        raise FileNotFoundError("Input directory not found")
    if not input_files:
        raise ValueError("Input directory contains no files")
    
    print(f"[DUMMY] Found {len(input_files)} files")
    
    # Simulate processing each file
    predictions = []
    for i, filename in enumerate(input_files):
        # Simulate processing time
        time.sleep(PROCESSING_DELAY_PER_FILE)
        
        # Generate deterministic mock prediction based on filename hash
        file_hash = hashlib.md5(filename.encode()).hexdigest()
        class_id = int(file_hash[:4], 16) % 1000
        confidence = round(0.5 + (int(file_hash[4:8], 16) % 5000) / 10000, 4)
        
        predictions.append({
            "image": filename,
            "classId": class_id,
            "className": f"dummy_class_{class_id}",
            "confidence": confidence
        })
        
        if (i + 1) % 5 == 0:
            print(f"[DUMMY] Processed {i + 1}/{len(input_files)}...")
    
    total_time_ms = int((time.perf_counter() - start_time) * 1000)
    
    # Write result (same schema as real inference output)
    result = {
        "status": "SUCCESS",
        "itemsProcessed": len(predictions),
        "itemsFailed": 0,
        "executionTimeMs": total_time_ms,
        "predictions": predictions,
        "errors": [],
        "summary": {
            "totalImages": len(input_files),
            "successfulInferences": len(predictions),
            "failedInferences": 0,
            "averageConfidence": round(
                sum(p["confidence"] for p in predictions) / len(predictions), 4
            ) if predictions else 0,
            "imagesPerSecond": round(
                len(predictions) / (total_time_ms / 1000), 2
            ) if total_time_ms > 0 else 0
        },
        "_meta": {
            "workloadType": "DUMMY",
            "note": "This is a mock result for pipeline testing"
        }
    }
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "result.json")
    tmp_path = os.path.join(OUTPUT_DIR, "result.json.tmp")
    
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp_path, output_path)
    
    print(f"[DUMMY] ✅ Done! {len(predictions)} items in {total_time_ms}ms")
    print(f"[DUMMY] Output: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[DUMMY] [FATAL] {e}")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, "result.json")
        tmp_path = os.path.join(OUTPUT_DIR, "result.json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "FATAL_ERROR",
                    "error": str(e),
                    "itemsProcessed": 0,
                    "predictions": []
                }, f, indent=2)
            os.replace(tmp_path, output_path)
        except Exception:
            pass
        sys.exit(1)

