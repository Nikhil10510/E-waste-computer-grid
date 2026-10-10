# Worker agent

Owner: Vaibhav. The host agent enrolls, maintains leases, downloads assigned
inputs, executes approved workloads, uploads JSON and reports completion.
Each old laptop needs this agent and a supported runtime installed once; nobody
needs to manually process individual photos on it.

Windows worker-only laptops can now use the bundled 0.6.2 installer without
Python/source. Docker Desktop/WSL and the matching offline archive are still
required. See [packaged app usage](../docs/WINDOWS_WORKER_RELEASE.md). Source
commands below remain useful for development; packaged enrollment uses owner
approval, not the development enrollment token.

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

## Verified offline runtime distribution

The owner desktop now uses the trusted `releases/current.json` and immutable
image IDs. Click **Import offline workloads** to verify/load the team's
`images.tar` and run real preflight before pairing. No worker starts merely
because images were prepared. Python/Docker remain prerequisites; no installer
or autostart is added. See [offline setup](../docs/OFFLINE_RUNTIME.md).

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
Docker images. Step 2 interaction acceptance passed locally: approve, decline,
expiry, real Docker computation, stop and full app restart with the same identity.
Step 4 adds Windows DPAPI-protected identity/session/settings files, a scrolling
connection form, persistent Stop/Disconnect controls and redacted diagnostics.
Legacy state migrates atomically; unreadable state is preserved for recovery.
Keep worker state on its original Windows account and laptop. Settings and saved
pause survive app restart; Start does not override Pause. Disconnect stops the
agent and retains its identity. Installer and separate-device acceptance remain pending. See
[WORKER_ONBOARDING.md](../docs/WORKER_ONBOARDING.md).
Step 3 policy acceptance passed locally: owner ceilings are enforced by Docker,
including zero additional swap; pause drains current work and blocks the next;
restart preserves pause; active stop releases its lease for retry. Network
failure falls back to lease expiry. Repeated stops consume the normal retry
budget. Limits cover the workload, not Python/Docker/WSL overhead. Normal image
jobs require the default 2 GiB; a lower approved ceiling can leave them queued.
See [Step 3 evidence](../output/onboarding/step3-acceptance.md) for test scope and
its historical test scope. The custom-limit approval click and full desktop
restart were subsequently verified in [Step 4 acceptance](../output/onboarding/step4-acceptance.md).
An agent with saved credentials now authenticates using `/nodes/session`;
upgrade the backend before deploying this agent. Authentication denial stops
the agent and requires owner attention; it never silently re-enrolls.

