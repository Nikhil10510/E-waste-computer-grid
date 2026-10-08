# Worker agent

Owner: Vaibhav. The host agent enrolls, maintains leases, downloads assigned
inputs, executes approved workloads, uploads JSON and reports completion.
Each old laptop needs this agent and a supported runtime installed once; nobody
needs to manually process individual photos on it.

## Prepare from the repository root

Use a fresh Python environment; virtual environments copied from another machine
are not portable. This checkout was verified with Python 3.12 on Windows. Native
inference dependencies support this documented version; Python 3.8 is not the
supported setup for the pinned inference runtime.

```powershell
py -3.12 -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r worker\requirements.txt -r workloads\ai-inference\requirements.txt
.\.venv-local\Scripts\python.exe workloads\ai-inference\download_model.py
Copy-Item worker\.env.example worker\.env
```

Set `CONTROL_PLANE_URL` to the API reachable from this laptop and set
`ENROLLMENT_TOKEN` to the backend's matching value. The example token is for
local development; choose a private token for shared deployment. A different
laptop must use the server's LAN address, not `localhost`.

## Docker execution (default)

Install/start Docker Engine/Desktop, prepare model artifacts first, then build:

```powershell
docker build -t ewaste/dummy-workload:v1 workloads/dummy-workload
docker build -t ewaste/ai-workload:v1 workloads/ai-inference
.\.venv-local\Scripts\python.exe worker\agent.py --preflight
.\.venv-local\Scripts\python.exe worker\agent.py
```

Rebuild old inference images to include the artifact manifest and current script.
Preflight executes one tiny probe through the same Docker settings used for real
tasks: no network, read-only root, bounded CPU/RAM and restricted permissions.
Model and labels must be baked into the image; there is no runtime model download.
Image presence alone is not a readiness check. Tags are the current allowlist;
immutable release digests and distribution to physical teammates remain release work.

## Native execution (local development)

```powershell
$env:EXECUTION_MODE = 'native'
.\.venv-local\Scripts\python.exe worker\agent.py --preflight
.\.venv-local\Scripts\python.exe worker\agent.py
```

Native mode launches only the two repository scripts with the same Python
interpreter as the agent. It has no Docker isolation and is intended for trusted
local development. `--preflight` needs no API credentials and does not enroll;
it prints mode, verified capabilities and errors. Exit 0 means image inference
passed; exit 1 means it is unavailable. Startup also probes capabilities before
registration. If inference fails but dummy passes, the normal agent advertises
only dummy; if nothing passes, it stops. Fix the reported error before a real demo.
Default probe timeout is 30 seconds; `PREFLIGHT_TIMEOUT` can be set for slow devices.

Agent state is in `worker/.worker_data`, temporary attempts in `.task_exec`.
Never copy credentials between workers. On one machine, assign each agent
different `DATA_DIR` and `TEMP_EXEC_DIR`; `--once` processes at most one assignment
for controlled integration tests. Stop with Ctrl+C.

## Verify

```powershell
.\.venv-local\Scripts\python.exe -m unittest discover -s worker\tests -v
```

If Docker connection fails, check its daemon and host permissions. If artifact
preflight fails, verify checksums/labels, dependencies, timeout and rebuild the
image. If registration fails, check URL, enrollment token and network access.
Passing preflight proves local execution; it does not prove browser submission,
LAN reachability, S3 access or a multi-device fleet.
## Approval onboarding status

Pairing, owner approval, credential-based reconnect and revocation are available
in the backend. A source-based desktop preview is available through
`python worker/desktop.py --api-url https://your-grid.example/api` from repo root.
For a trusted local HTTP demo add `--allow-http`. It needs Tkinter and prepared
Docker images. Full interactive acceptance, installer and protected storage are
pending. See
[WORKER_ONBOARDING.md](../docs/WORKER_ONBOARDING.md).
An agent with saved credentials now authenticates using `/nodes/session`;
upgrade the backend before deploying this agent. Authentication denial stops
the agent and requires owner attention; it never silently re-enrolls.

