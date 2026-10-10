# E-Waste Compute Grid

Reuse authorized idle/retired laptops to process independent batches. A dashboard
uploads images; the API stores jobs/tasks in PostgreSQL; a host agent claims work
over HTTP and runs an approved CPU classifier in Docker. Accepted results are
validated against the exact input set and downloadable as JSON.

Real workload: MobileNetV2 ImageNet classification (one class/score per photo).
`dummy` is a synthetic pipeline test. Energy displayed today is estimated from
an assumed hardware baseline and accepted execution time. This is a controlled
team prototype; three physical devices, measured savings and AWS deployment are
separate verification milestones.

## Prerequisites and source

**Latest software checkpoint:** Windows worker 0.6.2, task/attempt history,
per-image results, job cancellation and safe database migrations are implemented.
Read [completion, upgrade and remaining work](docs/SOFTWARE_COMPLETION.md) before
resuming from an earlier PDF. Physical laptop acceptance is still pending.

**Windows owner app update (10 October 2026):** Step 6 packaging is implemented
and locally tested. Worker-only laptops can use the bundled EXE installer plus
the verified offline archive; they need Docker/WSL, but no system Python/source.
See [Windows release and usage](docs/WINDOWS_WORKER_RELEASE.md) and
[remaining physical acceptance](docs/STEP7_PHYSICAL_ACCEPTANCE.md). The source
commands below still apply to development/coordinator setup.

- Docker Desktop/Engine running with Linux containers and Docker Compose.
- Python 3.12 installed for the host worker/model setup. Create environments on
  each machine; do not copy `.venv` or `.venv-local` between laptops.
- Node 22.12+ or Node 24 if running backend/frontend outside Docker. Docker builds
  use Node 22 and `npm ci` against the existing package locks.
- A current source checkout from
  [the team's repository](https://github.com/dkush2024-dot/E-waste-computer-grid).
  Onboarding Steps 1-4, Step 5 offline implementation and Step 6 local packaging
  are included. Separate-device, real-login and physical fleet acceptance remain
  open; earlier PDF handoffs are historical snapshots.

PowerShell commands below run from the repository root. If `py -3.12` is not
configured, use the absolute path to an installed Python 3.12 executable instead.
Use a fresh virtual environment in your own checkout; a teammate's environment
paths and interpreter setup are not portable.

## Prepare worker/model/data once

On a fresh machine:

```powershell
py -3.12 -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r worker\requirements.txt -r workloads\ai-inference\requirements.txt
.\.venv-local\Scripts\python.exe workloads\ai-inference\download_model.py
.\.venv-local\Scripts\python.exe workloads\test-data\setup_sample_data.py
docker build -t ewaste/dummy-workload:v1 workloads/dummy-workload
docker build -t ewaste/ai-workload:v1 workloads/ai-inference
```

Skip environment creation if your local environment already runs correctly.
Setup validates cached model/labels/photos too; failures are explicit and do not
generate fallback data. Keep the pinned manifests with the source.

## Start API, database and dashboard

Create `infra/.env` from the example **only if it does not already exist**:

```powershell
if (-not (Test-Path infra\.env)) { Copy-Item infra\.env.example infra\.env }
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d --build
docker compose --env-file infra/.env -f infra/docker-compose.yml ps
Invoke-RestMethod http://localhost:8080/api/health
```

Default dashboard: `http://localhost:5173`; API: `http://localhost:8080/api`.
Connect in the dashboard with the `ADMIN_TOKEN` configured in `infra/.env`.
Example tokens are local development values. Do not print or commit actual
deployment credentials. Preserve an existing database's password/configuration.

Default services are **db, control-plane, frontend**. Worker agents run on the
contributing hosts. Container simulations are opt-in:

```powershell
docker compose --env-file infra/.env --profile simulation -f infra/docker-compose.yml up -d --build
```

Those two simulation containers are not two separate physical laptops.

## Connect a host worker

Secure pairing/approval is implemented at the API level. A source-based desktop
approval preview and dashboard invitation form exist. Step 2 approval, decline,
expiry, Docker computation, stop and saved-identity restart passed on the local
Windows machine. Step 3 custom resource ceilings, pause/drain, restart and
active stop/retry also passed local HTTP/Docker acceptance. Installer acceptance
passed locally; separate-laptop acceptance remains pending. See
[worker onboarding status and protocol](docs/WORKER_ONBOARDING.md).
Upgrade the backend before using the updated worker with a saved identity.
The script flow below remains enabled for local development.

Desktop preview (Python with Tkinter and running Linux/amd64 Docker required):

```powershell
.\.venv-local\Scripts\python.exe worker\desktop.py --api-url http://localhost:8080/api --allow-http
```

Use the configured API host/port on each laptop. The existing isolated local
demo uses port 18080 instead. This preview replaces repeated launch configuration
with a window, but still needs source/Python until the installer is built.
Step 4 adds protected Windows credentials/settings, persistent controls and
redacted diagnostics. Saved pause remains in effect after restart. Disconnect
stops the owned worker before changing grids and retains its identity. See
[Step 4 acceptance](output/onboarding/step4-acceptance.md) for local test scope.

Step 5 adds **Import offline workloads**: select the team's separately copied
`images.tar`, verify its checksum/image identities, then run real preflight.
The desktop executes the reviewed release's immutable image IDs, with no manual
workload build needed on a receiving laptop. Python/Docker remain prerequisites.
See [offline setup and current evidence](docs/OFFLINE_RUNTIME.md). The large
archive is ignored by Git; the source manifest and setup tools are included.

Use the matching enrollment token from your API's configuration:

```powershell
$env:ENROLLMENT_TOKEN = 'local-enrollment-change-me'
.\scripts\Start-Worker.ps1 -ControlPlaneUrl http://localhost:8080/api -WorkerName 'Local Docker worker'
```

The launcher checks API health, explicitly sets URL/runtime/state paths, verifies
actual Docker inference and then enrolls. Keep it running; Ctrl+C stops it.
Optional `-StateDirectory` gives each agent distinct credentials/task paths.
`-ExecutionMode native` is trusted local development without Docker isolation.

For a second laptop on the same LAN, set `API_BIND_ADDRESS=0.0.0.0` in the
server's `infra/.env` and recreate the API service. Use that server's private
IPv4 address in the worker URL; `localhost` on the second laptop points to itself.
Keep the DB binding at `127.0.0.1`; only the API needs LAN access. Verify
`Invoke-RestMethod http://SERVER_IP:8080/api/health` on the second laptop before
enrolling. If blocked, check network/client isolation and a narrowly scoped
private-network firewall rule with the machine's owner. No router/public exposure
or firewall change is made by these scripts.

## Run the acceptance demo

In the browser, select all ten files in `workloads/test-data/demo` in alphabetical
order, name the job and set items per task to 5. Expect two tasks, then a terminal
COMPLETED job, 100% progress and a Download results button. Verify the downloaded
file (replace the example path with yours):

```powershell
.\.venv-local\Scripts\python.exe workloads\test-data\verify_job_results.py C:\path\to\job.json --report output\phase2\verification.json
```

It checks counts, exact prefixed names, task chunk membership, prediction fields
and explicit estimated metrics. It does not judge label accuracy or prove which
physical machine executed the task; retain worker/DB evidence too. The initial
curated model sanity check matched 2 of 5 label expectations; see Phase 1 evidence.

## Testing and operating

```powershell
.\.venv-local\Scripts\python.exe -m unittest discover -s worker\tests -v
.\.venv-local\Scripts\python.exe -m unittest discover -s workloads\tests -v
```

Backend: `npm ci`, then `npm test` in `control-plane`. Set `TEST_DATABASE_URL` to
a disposable development database and `TEST_PYTHON` to an absolute fresh Python
environment path; otherwise integration tests are skipped. Tests use separate
random schemas. Frontend: `npm ci`, `npm run build`, `npm run lint` in `frontend`.

Compose host database port defaults to **55432**; inside containers it is
**db:5432**. Defaults are configurable through `infra/.env.example`. The backend
container synchronizes a development schema with `prisma db push`; reviewed
release migrations are still future work. Standalone backend config lives in
`control-plane/.env`, not the Compose env file. A dashboard Vite proxy uses
`API_PROXY_TARGET`; workers always need their own reachable API URL.

Inspect service logs with `docker compose --env-file infra/.env -f
infra/docker-compose.yml logs --tail 100`. Stop with the same command prefix
followed by `down`; named database/object volumes remain. Do not add `--volumes`
unless you deliberately intend to destroy that development state.

See [Phase 0/2 status](docs/PHASE_0_2_STATUS.md), [physical Windows setup](docs/PHASE_2_WINDOWS_WORKER.md),
[implemented API contract](docs/api_contracts.md), [Phase 1 evidence](docs/PHASE_1_STATUS.md)
and [master plan](docs/MASTER_PROJECT_PLAN.md).
