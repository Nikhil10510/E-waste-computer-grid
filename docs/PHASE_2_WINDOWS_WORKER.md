# Phase 2: separate Windows laptop

Use the latest source on the contributing laptop. Recreate its Python environment
there; do not copy credentials/environments from the API host. Keep both computers
on the same reachable private network and keep the API host awake.

## Current isolated rehearsal server

This development session uses project `ewaste-phase2`, API port **18080**, dashboard
port **15173**, and PostgreSQL host port **55435**. These differ deliberately from
the default stack so existing application data is preserved.

The server's observed private address is **10.100.212.200**. It can change when
Wi-Fi changes, and reachability from another machine has not yet been verified.
No simulated workers start automatically. Demo enrollment token is
`local-phase2-enrollment`; dashboard admin token is `local-phase2-admin`. These are
isolated development values, not production credentials.

## On the separate laptop

From its current project/source-bundle root, with Docker Desktop running in Linux
container mode:

```powershell
Invoke-RestMethod http://10.100.212.200:18080/api/health -TimeoutSec 10
```

Expected `status: ok`. If it fails, fix network connectivity before starting the
agent. Check both PCs are on a mutually reachable network; campus/guest Wi-Fi may
isolate clients. Any needed firewall rule should allow only the API port on the
private network, reviewed by the owner. Scripts do not change firewall settings.

Prepare a fresh environment if needed:

```powershell
py -3.12 -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r worker\requirements.txt -r workloads\ai-inference\requirements.txt
.\.venv-local\Scripts\python.exe workloads\ai-inference\download_model.py
docker build -t ewaste/dummy-workload:v1 workloads/dummy-workload
docker build -t ewaste/ai-workload:v1 workloads/ai-inference
$env:ENROLLMENT_TOKEN = 'local-phase2-enrollment'
.\scripts\Start-Worker.ps1 -ControlPlaneUrl http://10.100.212.200:18080/api -WorkerName 'Retired Windows laptop'
```

If the Windows Python launcher is absent, substitute your installed Python 3.12
executable path for `py -3.12`; do not substitute a copied environment. Existing
healthy local environments can be reused. Keep the agent terminal open.

If using existing source without the new launcher, set all the equivalents:

```powershell
$env:CONTROL_PLANE_URL = 'http://10.100.212.200:18080/api'
$env:ENROLLMENT_TOKEN = 'local-phase2-enrollment'
$env:EXECUTION_MODE = 'docker'
$env:WORKER_NAME = 'Retired Windows laptop'
.\.venv-local\Scripts\python.exe worker\agent.py --preflight
.\.venv-local\Scripts\python.exe worker\agent.py
```

Use this fallback only after updating Phase 1 worker/workload scripts and artifact
manifests. Preflight must advertise `image_inference` without errors.

## On the API host / dashboard

The local rehearsal worker must be stopped first, so it cannot claim the physical
test job. Verify the distinct retired-laptop node appears online in the browser.
At `http://localhost:15173`, submit the ten genuine demo photos in alphabetical
order with chunk size 5 and name `Phase 2 physical Windows laptop`.

Retain these observations:

1. Node name/ID and Windows/Docker startup on the separate laptop.
2. Browser job ID, two tasks, successful progress and terminal state.
3. Two executing/completed task IDs in that laptop's logs, matching DB ownership.
4. Actual browser download, verified with `verify_job_results.py` on the API host.
5. Reload still shows the same job and results; no duplicate metrics/job creation.
6. Repeat once with a new job name to check teammate repeatability.

Do not include credentials or signed download URLs in evidence. A screenshot of
one local worker alone does not prove remote physical execution. Keep the gate
pending until the separate machine actually contributes and ownership is checked.

Stop the agent with Ctrl+C. Stop the isolated server with:

```powershell
docker compose --project-name ewaste-phase2 --env-file infra/.env.phase2 -f infra/docker-compose.yml down
```

That preserves its named DB/object volumes. The ignored `infra/.env.phase2` is
local session configuration; teammates can reproduce it from `infra/.env.example`
using the ports/tokens described above, without overwriting an existing env file.
