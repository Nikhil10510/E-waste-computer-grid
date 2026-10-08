# Phase 1 implementation and handoff

Date: 8 October 2026. Scope: the master plan's **genuine workload and trustworthy
contract** phase. This record covers the work of all four teammates in this
checkout. Phase 2's browser-to-physical-worker demo is a separate acceptance gate.

## Work completed, in dependency order

| Order / teammate | Implemented work | Why it matters |
| --- | --- | --- |
| 1. Kushagra — backend/contracts | Validate result counts, status, class fields and exact assigned identities across predictions/errors; update real API contract; test rejected output leaves task/job/metrics untouched | Ten output rows cannot substitute for the ten correct inputs |
| 2. Nikhil — workloads/data | Ten genuine photos with pinned provenance/checksums and five label expectations; fail visibly without synthetic download fallbacks; mandatory 1000-class labels; verified model/labels; real-photo evaluator | Useful classification needs genuine pixels and the correct class mapping |
| 3. Vaibhav — worker/runtime | Execute each approved workload during capability preflight; inference probe validates pinned artifacts and actual ONNX execution; standalone preflight command; fresh environment setup | Installed packages or an image tag do not prove the workload can run |
| 4. Chinmay — frontend | Default to real classification; label dummy mode synthetic; validate selection before uploads; explain queued jobs with no compatible worker | Users can distinguish infrastructure testing from real inference |

Architecture is still PostgreSQL + HTTP pull, existing lease/retry/idempotency
behavior, host agent and approved workloads. No schema migration or new queue
was needed. Existing clients already emit the now-required result fields;
external/custom workers with incomplete result artifacts must follow the updated
contract. Endpoint names and request bodies remain unchanged.

## Verification record

**Phase 1 implementation and local verification passed.** No test below was
skipped. This does not close Phase 2 or prove a physical fleet.

| Check | Result / scope |
| --- | --- |
| Backend build and tests | 18 passed, including 13 real PostgreSQL/HTTP integration tests; isolated PostgreSQL 15 database and per-run schema |
| Worker tests | 12 passed in fresh `.venv-local`, including recovery-before-preflight startup ordering |
| Workload tests | 27 passed, including download failures, corrupt/solid inputs, label integrity and line-ending portability |
| Frontend | TypeScript/Vite production build and Oxlint passed |
| Native runtime preflight | Both dummy and image inference passed; no preflight errors |
| Genuine-photo local evaluation | 10 processed, 0 failed, exact ten identities |
| Real two-agent integration | Ten photos split into two tasks through two native agents on this host; two accepted metrics, exact prefixed identities |
| Docker builds and execution | Both approved images built; both startup probes passed; ten photos processed through actual TaskExecutor limits with no network and read-only root |
| Docker/native comparison | All ten class IDs matched; exact input coverage in both runs |

Total: **57 passing tests**. The separate three-test artifact setup run used the
bundled Python runtime initially; those same tests also passed in the full fresh
environment suite and are counted once in the 57. Verification host was Windows
with Docker Desktop Linux containers; native Python 3.12.14, ONNX Runtime 1.17.1,
NumPy 1.26.4 and Pillow 10.4.0. The inference container uses Python 3.10.

The first dependency install failed because one download did not match its
published hash. Retrying downloaded the package successfully with integrity
checks still enabled. Native ONNX Runtime emits a Windows-version warning on
this host, despite passing execution; target-device compatibility still needs
the actual preflight on each teammate's machine.

Evidence artifacts:

- `output/workloads/phase1/result.json`: actual native classifier output.
- `output/workloads/phase1/evaluation.json`: predictions versus the stated label rubric.
- `output/workloads/phase1/python-environment.txt`: installed Python package versions.
- `output/workloads/phase1-docker/result.json`: actual container classifier output.
- `output/workloads/phase1-docker/verification.json`: image IDs, limits, preflight and comparison results.
- `tmp/phase1-photos.png`: visually inspected contact sheet of the genuine inputs.

The accepted label rubric matched **2 of 5** eligible images (cat and coffee).
Brick, blurred clock and rocket labels did not match; five other images have no
scored label expectation. Do not report this as general model accuracy. The
photos intentionally remain genuine and the mismatches visible. Before a
classification-quality claim, define a suitable labeled evaluation set and
measure preprocessing/model quality separately from distributed execution.

Local image IDs for reproducibility (built tags remain mutable):

```text
ewaste/dummy-workload:v1 sha256:d121e1d4507b428d4493bba24123c5005f979c545b2b1e754de5887f0f9ec075
ewaste/ai-workload:v1    sha256:7b36126880e510bdbd0117b3ab784cb4a41e3267df29f91877ff02b5c28217f7
```

The test server and per-test schemas were cleaned up; the disposable database
container was removed after verification. Existing application data/config was
not overwritten. Approved workload images and `.venv-local` remain for continued
development. No actual browser, physical fleet, AWS or S3 test was executed here.

## Reproduce the workload checks

Run commands from the repository root with a supported Python 3.12 installation:

```powershell
py -3.12 -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r worker\requirements.txt -r workloads\ai-inference\requirements.txt
.\.venv-local\Scripts\python.exe workloads\ai-inference\download_model.py
.\.venv-local\Scripts\python.exe workloads\test-data\setup_sample_data.py
.\.venv-local\Scripts\python.exe workloads\test-data\setup_sample_data.py --verify-only
$env:EXECUTION_MODE = 'native'
.\.venv-local\Scripts\python.exe worker\agent.py --preflight
.\.venv-local\Scripts\python.exe workloads\test-data\evaluate_demo.py
.\.venv-local\Scripts\python.exe -m unittest discover -s worker\tests -v
.\.venv-local\Scripts\python.exe -m unittest discover -s workloads\tests -v
```

Use `.venv-local`, not the copied `.venv` directory. Native mode is trusted local
development, not the physical-worker isolation target. Worker setup and Docker
build/preflight commands are in `worker/README.md`; Docker must be running.

The real-photo evaluator writes `output/workloads/phase1/result.json` and
`evaluation.json`. One class/name/confidence per image is expected. A wrong class
is a model-quality issue; missing/duplicated/unassigned output is a protocol bug.
Label matches on these five curated expectations are a sanity check, not general
accuracy. No energy savings or distributed speedup is established by this run.

For backend integration tests, first install backend dependencies with `npm ci`
in `control-plane`. Use a disposable PostgreSQL database you own, never a durable
production database. The suite creates and drops its own random schema. Set
`TEST_DATABASE_URL` and an absolute `TEST_PYTHON` path to the fresh environment,
then run `npm test` in `control-plane`. Without `TEST_DATABASE_URL`, integration
tests are skipped. The genuine-photo test also requires prepared `demo/` images
and the model/labels; the expected result is two completed tasks, ten exact image
identities and two accepted metrics through two native agents on one host.

Frontend checks run in `frontend`: `npm run build` and `npm run lint`.

## What remains before the next milestone

1. Recover/use the canonical Git repository; this local checkout has no Git
   metadata, so changes here have not been committed or pushed.
2. Prepare a physical retired laptop with Docker and the approved workload
   images. Use a unique worker identity and an API URL reachable over the LAN.
3. Start backend and dashboard with matching tokens and storage/API addresses.
   Do not overwrite an existing database/environment file just to copy examples.
4. In the browser, upload the ten genuine photos with chunk size 5. Retain the
   job ID, sanitized worker logs and downloaded result. Confirm two tasks and
   ten accounted inputs. Repeat from the written setup.
5. Capture actual browser and physical-device evidence before closing Phase 2.
   Three-device distribution, abrupt worker-kill recovery, measured energy,
   durable release migrations and real AWS/S3 deployment remain later gates.

The old workload README's blanket phase-completion claims have been replaced.
Helpers for scoring, measurement and cloud access still exist, but this phase
does not establish that they run in the live system. The original audit and
master plan are historical snapshots; this file records the implementation delta.

## Key references

- `docs/api_contracts.md`: actual API and exact result acceptance rules.
- `worker/README.md`: fresh environment, preflight, Docker/native modes.
- `workloads/test-data/README.md`: data source, verification and evaluator.
- `frontend/README.md`: dashboard setup and Phase 2 manual scenario.
- `docs/MASTER_PROJECT_PLAN.md`: later phases and release gates.
