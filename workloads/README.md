# Approved workloads

Owner: Nikhil, with Vaibhav owning host/container execution. The active path is
`worker/task_executor.py` running one allowlisted script/container per assigned
batch. It reads `/data/input` and writes `/data/output/result.json` in Docker;
native development uses equivalent environment paths.

| Workload | Purpose | Output |
| --- | --- | --- |
| `dummy` | Deterministic pipeline and recovery testing | Synthetic class/score per text item |
| `image_inference` | Real CPU MobileNetV2 classification | ImageNet class ID/name/confidence per decoded image |

Real classifier setup, model integrity and data provenance are documented in
`ai-inference/models/README.md` and `test-data/README.md`. The implemented result
contract is `docs/api_contracts.md`; accepted results must account for every
assigned image exactly once. All-input failures report task failure, while mixed
results may complete with explicit item errors and a partial-success job.

Run the real-photo evaluator and test suite from the repository root:

```powershell
.\.venv-local\Scripts\python.exe workloads\test-data\evaluate_demo.py
.\.venv-local\Scripts\python.exe -m unittest discover -s workloads\tests -v
```

Other benchmark, scoring, energy and S3 helper modules exist in this directory.
Their existence and unit tests do not mean those features drive the live scheduler
or have been measured/deployed. The live queue uses PostgreSQL claim order and
capability/RAM eligibility; live energy is estimated, not power-meter measurement.
Use `docs/MASTER_PROJECT_PLAN.md` and `docs/PHASE_1_STATUS.md` for current evidence
and remaining development phases rather than the old module-phase checklists.
