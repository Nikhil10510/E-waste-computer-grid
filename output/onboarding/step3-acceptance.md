# Step 3 local resource-policy acceptance — 2026-10-09

Resource-policy acceptance passed on the development Windows machine with real
HTTP/PostgreSQL and Docker execution. Manual custom-limit approval interaction,
protected settings/credentials, packaging and separate-device release checks
remain open. This is not an installer or physical multi-laptop acceptance run.

## Environment

- Source based on `672a8698bc7e4404c2d1545c50760dafbfcf455d`, preserving Step 2
  changes and adding the fixes below.
- Isolated API `http://127.0.0.1:18081/api`, PostgreSQL 18 on port 55433 and schema
  `ewaste_acceptance_step3_20261009`; legacy enrollment disabled.
- Python 3.12 from the repository `.venv`, Docker 29.6.1 with cgroup v2 and the
  prepared repository workload images. Private fixture/config/log files remain
  ignored under `.test-data/step3-acceptance`.
- One paired node: `8d724529-3bcc-46a0-ac53-6fb284f090b5`.
- Policy: 0.5 CPU equivalents and 0.75 GiB RAM, below physical capacity.

The desktop's custom values and successful runtime preflight were observed.
Windows Computer Use then failed to capture the approval window with
`foreground window did not report a process id`. No further UI inputs were
sent. Approval used the real owner HTTP client; live pause/resume checks used
that client and the actual desktop runtime/agent. Tk callback tests separately
exercise approve, decline, pause and resume with mocked network/compute. The
Step 2 manual UI run with default limits remains separate evidence.

## Verified behavior

| Check | Evidence |
| --- | --- |
| Owner consent bounds | Backend and worker reject invalid/over-hardware limits; approved limits cannot be increased by a session refresh or approval retry. |
| Kernel CPU ceiling | `cpu.max = 50000 100000`, equivalent to 0.5 CPU; Docker `NanoCpus = 500000000`. |
| Kernel RAM/swap ceiling | `memory.max = 805306368`; `memory.swap.max = 0`; combined memory/swap configured to 805306368 bytes. |
| Isolation | Docker configuration retained disabled network and read-only root. |
| Paused start | Real worker started and heartbeated but received HTTP 204, launched no task and contributed zero available cores. |
| Pause while running | Server reported DRAINING; existing lease could replay; only current task completed, then PAUSED/204 blocked the next. |
| Restart while paused | New agent process reused the identity and persisted policy, remained paused and accepted no task. |
| Resume | Finished the remaining task with exact 200-input coverage, no errors and two accepted tasks. |
| Active stop | Cancelled the owned workload, removed its container and returned its assignment promptly; observed stop took 0.469 seconds. |
| Stop then paused restart | No task/result accepted while paused; old assignment did not replay. |
| Retry | Resume assigned a new lease with retry count 1; all 100 inputs accepted once in one completed task. |
| Effective RAM admission | A 1 GiB requirement stayed QUEUED on this 0.75 GiB worker throughout. |
| Scoped cleanup | A separate test container remained running through stop/restart and was removed only by the test harness afterwards. |
| Pause/revoke races | Real HTTP/DB integration runs simultaneous task polls against pause/revoke; at most one active lease, no subsequent admission while paused/revoked, and no accepted output after revocation. |
| Accepted result accounting | Three completed tasks and three database metrics; no metric for the cancelled attempt. Exact input identities verified in downloaded results. |

The live resource-policy jobs use synthetic `dummy` inputs so each active task
lasts long enough to observe pause and cancellation. They do not assess image
classification. Image execution and corrupt-input coverage also pass in the
backend suite; Step 2 records the separate live Docker photo jobs.

## Changes made

- `worker/task_executor.py`: set Docker's combined memory/swap limit equal to
  the chosen RAM ceiling. Previously the default swap allowance could exceed it.
- `worker/agent.py`: return stopped assignments using the existing failure
  endpoint and lease token. Cover both active cancellation and an assignment
  response arriving after stop; do not start that late computation.
- `worker/api_client.py`: allow the shutdown release to use one bounded HTTP
  attempt instead of retrying shutdown delivery repeatedly.
- Worker regressions cover stop races, lost-lease fencing, failed release and
  Docker memory/swap settings. Tk test teardown collects destroyed callback
  cycles on the main thread, avoiding intermittent Tcl destruction in a worker
  thread during later tests.
- Backend regressions cover concurrent polls versus pause/revoke. Their paired
  node policy is seeded independently of pairing creation tests, preserving the
  real per-IP pairing rate limit.
- `scripts/verify_resource_policy.py`: scoped live acceptance runner, requiring
  a fresh local test grid and an approved identity; records sanitized evidence.
- Current onboarding docs/ledger updated. No new public API/schema contract,
  scheduler replacement, workload/model or AWS deployment was introduced.

## Checks and artifacts

- Backend build and tests: **33 passed, zero skipped**, including 26 real
  PostgreSQL/HTTP integration cases and seven unit cases.
- Worker tests: **37 passed**. Callback tests mock HTTP/compute; the acceptance
  runner supplements them with real Docker and owner HTTP requests.
- [Live Docker report](step3-docker-verification.json).
- [Drain/resume downloaded result](step3-docker-verification-drain-results.json).
- [Stop/retry downloaded result](step3-docker-verification-retry-results.json).
- [Sanitized database task ownership](step3-task-ownership.json).
- [Step 3 verification ledger](step3-verification.json).

An initial Docker pipe timeout occurred before any job was created; retry after
checking daemon health succeeded. The first resource inspection incorrectly
expected Docker `HostConfig.NetworkMode` to equal `none`; with the SDK's
`network_disabled=True`, the relevant field is `Config.NetworkDisabled`. The
inspection was corrected and only this fixture's jobs were cleared before the
successful run. Failed-run records remain in the ignored private test directory.
Prisma generation required stopping the tracked test API to release its Windows
DLL lock. These failed attempts are not included as passing checks.

Frontend/workload source did not change in Step 3, so their prior passing
build/lint and workload-unit records were not repeated. Backend integration did
rerun real inference and exact-photo accounting after the worker changes.

## Repeat locally

For normal use, follow the source desktop setup in
[WORKER_ONBOARDING.md](../../docs/WORKER_ONBOARDING.md): choose limits before
pairing, approve locally, submit work, then exercise Pause/Resume/Stop/Start.
Use at least the default 2 GiB for normal image jobs; lower ceilings can leave
those jobs queued when they fail the admission requirement.

The automated acceptance runner additionally needs a **fresh dedicated local
grid**, one approved node with fractional CPU and RAM below 2 GiB, no previous
jobs and a closed desktop/agent. Its private config contains `api_url`, `schema`
(prefix `ewaste_acceptance_step3_`) and `admin_token`. Configure the test backend
with a 10-second lease, 120-second attempt deadline and 500 ms sweep interval;
prepare both workload images. Do not reuse a shared/demo schema or commit that
config. Run from repository root:

```powershell
.\.venv\Scripts\python.exe scripts\verify_resource_policy.py `
  --private-config .test-data\step3-acceptance\private.json `
  --state-directory .test-data\step3-acceptance\owner `
  --report output\onboarding\step3-docker-verification.json
```

The retained schema already has evidence jobs, so a direct rerun will reject it.
Use a new isolated fixture rather than deleting existing demo work. The runner
starts/stops its worker and its sentinel; it does not manage the API/database.
For automated regressions:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s worker\tests -v
$env:TEST_DATABASE_URL = 'postgresql://ewaste@127.0.0.1:55433/postgres'
$env:TEST_PYTHON = "$PWD\.venv\Scripts\python.exe"
Push-Location control-plane
npm test
Pop-Location
```

Adapt DB credentials/port to the local setup. Backend tests create and remove
their own schema. Stop source APIs using this Prisma client before `npm test`
on Windows so generation can replace its DLL.

## Boundaries and cleanup

Ceilings apply to each workload container, excluding Python/Docker/WSL overhead.
CPU quota is not dedicated-core reservation; RAM is not pooled across laptops.
Native development mode has no Docker resource enforcement. Stop may wait for
outstanding I/O; failed release recovers through lease expiry. Repeated stops
consume the existing retry budget. The admission contract uses supported
workloads and required RAM, not live utilization or a CPU minimum.

The acceptance desktop/agent/API were stopped and owned workload/sentinel
containers removed. Shared Docker/PostgreSQL and test evidence were retained.
No AWS service or teammate's physical laptop was changed. Manual custom-limit
approval, protected Windows credentials, interface polish, image distribution,
installer, startup/reboot and separate physical-device acceptance remain open.
