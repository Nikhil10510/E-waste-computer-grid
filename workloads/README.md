# Workloads
Owner: Nikhil

This directory contains the actual tasks that get distributed to the workers.

## Responsibilities:
- Dockerfiles for the batch processing applications
- Python AI inference scripts (e.g., ONNX, PyTorch)
- Test datasets and benchmarking scripts

## Directory Structure
```
workloads/
├── README.md                  # This file
├── ai-inference/              # Production AI workload container
│   ├── Dockerfile             # CPU-optimized Python image (~250MB)
│   ├── requirements.txt       # onnxruntime, pillow, numpy
│   ├── run_inference.py       # Main inference entrypoint
│   ├── download_model.py      # Script to download MobileNetV2 ONNX model
│   └── models/                # Pre-baked model files
│       ├── mobilenetv2-12.onnx
│       └── imagenet_labels.json
├── dummy-workload/            # Lightweight mock for testing pipeline
│   ├── Dockerfile
│   └── run_dummy.py
├── benchmark/                 # Hardware benchmarking scripts
│   └── hardware_benchmark.py
├── energy/                    # Energy calculation utilities
│   └── energy_calculator.py
└── test-data/                 # Sample images for testing
    └── sample/
        ├── cat.jpg
        ├── dog.jpg
        └── car.jpg
```

## Phase 0 Status: ✅ COMPLETE
- [x] Model selected: MobileNetV2 (ONNX, FP32, CPU) — see docs/model_selection.md
- [x] API contracts frozen — see docs/api_contracts.md
- [x] Energy formula frozen — see docs/energy_specification.md
- [x] Capability flags defined — see docs/capability_flags.md
- [x] Container I/O convention defined (read /data/input, write /data/output)
- [x] Task chunking strategy: fixed_size, 100 files per chunk

## Phase Status:
- [x] **Phase 0:** Architecture, API contracts, database schema, energy spec frozen
- [x] **Phase 1:** Hardware benchmark script, teammate one-click runners, machine baselines (`docs/hardware_baselines.md`)
- [x] **Phase 2:** Deterministic dummy workload, task runner (`task_runner.py`), result aggregator (`result_aggregator.py`), integration guide (`docs/phase2_workload_guide.md`)
- [x] **Phase 3:** MobileNetV2 FP32 model downloaded, verified AI inference pipeline (40.5 img/s CPU), energy calculator
- [x] **Phase 4:** Fault tolerance, retry idempotency, atomic writes, automated test suite (`workloads/tests/test_fault_tolerance.py`), spec (`docs/fault_tolerance_specification.md`)
- [x] **Phase 5:** Energy-aware scheduling & scoring (`workloads/scheduler_scorer.py`), test suite (`workloads/tests/test_scheduler_scorer.py`), spec (`docs/intelligent_scheduling_specification.md`)
- [x] **Phase 6:** Hardware energy measurement & environmental story (`workloads/energy/power_meter.py`, `workloads/energy/environmental_calculator.py`), test suite (`workloads/tests/test_energy_and_environmental.py`), methodology (`docs/energy_and_environmental_methodology.md`)
- [x] **Phase 7:** AWS cloud integration & model artifact hosting (`workloads/ai-inference/s3_model_manager.py`, `workloads/ai-inference/validate_cloud_runtime.py`), spec (`docs/aws_integration_guide.md`)
- [ ] **Phase 8:** Final end-to-end integration demo & pitch presentation





