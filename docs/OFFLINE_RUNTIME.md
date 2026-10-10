# Step 5 - verified offline workload distribution

Current update, 10 October 2026: the Windows 0.6.1 app bundles its host runtime;
Python/Tk is required only for the source preview below. Its trusted manifest
uses **team-offline-v2**. See [current release files and usage](WINDOWS_WORKER_RELEASE.md)
for the matching archive checksum/image IDs. The v1 values below describe the
historical initial release and must not be mixed with the new v2 app.

Implemented source preview on 10 October 2026. This route imports a team-built
Docker archive without building workloads on each contributing laptop. It does
not install Python/Docker or create the Step 6 Windows installer.

## Trust and supported runtime

The initial release targets **Linux amd64 Docker containers**, including Docker
Desktop on an amd64 Windows laptop. Docker/WSL must be installed and running.
Python 3.12 with Tkinter remains required for this source app. ARM, Windows
containers, obsolete CPUs and other OS combinations are not certified by this
release. Actual preflight catches unsupported inference instructions/runtime.

`worker/releases/current.json` is the trusted manifest from the reviewed source.
It fixes the release/result version, platform, image IDs, model/label hashes and
archive SHA-256/size. Docker image IDs are immutable configuration/layer content
digests; they are **not registry manifest digests**. The desktop sends these IDs
consistently into preflight, agent configuration and task execution.

Get the manifest/source ZIP through the team's trusted channel or reviewed Git
commit. An archive hash does not authenticate a publisher if an attacker also
replaces its manifest. Do not accept a manifest supplied by a job or download an
arbitrary workload. Registry publication, release signatures and trusted automatic
updates are not implemented by this offline route.

Initial artifacts:

- `output/runtime/team-offline-v1/images.tar`: 112,585,728 bytes (about 107 MiB).
- Archive SHA-256: `8f64f8996415c264aa7d144518b1338b4d67878d1be1119992f889fe85e0bdbf`.
- `output/handoff/E_Waste_Desktop_Worker_Step5_Source.zip`: allowlisted desktop
  source, requirements and trusted manifest; no credentials, copied environment,
  installer, coordinator, model source files or startup configuration.
- Its `.zip.sha256` companion identifies the exact generated source bundle.

The large archive is ignored by Git and is not pushed automatically. Copy it
separately, e.g. by USB. Offline refers to image distribution; dependency setup
may need the internet once and normal jobs still need access to the coordinator.

## Owner flow

1. Extract the source ZIP into a new folder; follow `READ_ME_FIRST.txt`. Create a
   fresh Python environment and install `worker/requirements.txt`. Never copy
   another laptop's virtual environment or protected credentials.
2. Start `worker/desktop.py`. Set the trusted coordinator address; `localhost`
   means this laptop. For a private LAN demo explicitly select HTTP; use HTTPS
   for deployment. Choose CPU/RAM ceilings before preparation/approval.
3. Click **Import offline workloads**, select `images.tar`, and wait for visible
   verification/import/preflight status. Use **Cancel preparation** to stop.
4. Once real preflight passes, click **Prepare connection**, share only its code,
   and approve the administrator's invitation locally. Preparation does not
   enroll a node or start a job worker; it executes tiny runtime probes only.
5. Submit the ten demo photos with chunk size five. Normal image jobs require
   2 GiB task admission; choose sufficient approved capacity rather than raising
   limits without consent. Check exact downloaded outputs and node/task ownership.

Preparation reuses valid cached image IDs. A cache hit does not read a selected
archive because nothing needs importing. Missing images require an archive.
Failure/retry retains per-grid identity, owner ceilings and saved pause; it does
not grant consent or silently substitute dummy/native execution. The desktop
fails if its trusted manifest is missing, instead of reverting to mutable tags.
The historical development CLI still supports explicit tag-based configuration.

## Verification, cancellation and disk behavior

Before import, check daemon Linux/amd64 mode and host disk headroom. Copy the
selected open archive into a temporary owned snapshot while hashing it; compare
the exact size and checksum before Docker reads that snapshot. This prevents a
changed original file being used after verification. Only then run `docker image
load`, verify each loaded image ID/platform and run existing restricted real
preflight under selected limits. Model/label artifacts remain baked into the
image; the release builder verifies their contract against the pinned source.

The host headroom check reserves two archive sizes plus 256 MiB. This is an
estimate, not a reading of free space inside a remote Docker/WSL image store.
Daemon disk-full errors are surfaced; the app does not prune unrelated content.

Cancellation during verification deletes only the owned snapshot. During import
it terminates only the spawned Docker CLI, not Docker itself or other containers.
Docker may finish importing already submitted data after client cancellation;
the app does not claim rollback or readiness. Retry verifies content again.
Preflight cancellation requests cooperative stop so owned containers can clean
up, with bounded subprocess shutdown as a fallback. No enrollment/agent starts
because an import was cancelled. Closing waits for background work to end.

## Maintainer: create a new reviewed offline release

Build and review the two workloads once on the release machine, with pinned
model/label artifacts. Then, from repository root:

```powershell
.\.venv-local\Scripts\python.exe scripts\Build-OfflineRuntime.py `
  --output output\runtime\team-offline-v2 --release team-offline-v2
```

The builder resolves the existing approved build tags, reads the baked artifact
contract from a newly created stopped container, runs real restricted preflight,
exports exact image IDs and hashes the archive. It removes only its own stopped
inspection container and refuses to overwrite an existing archive/manifest.
This creates local files, not a registry publication.

Review the generated `release.json`, image IDs/platform, model contract and
actual test results. Only then deliberately replace the source's
`worker/releases/current.json` and create a reviewed release commit/tag. Never
change a workload/model contract in place without considering server/worker
compatibility. Existing tasks continue with their process-selected release;
stop/reprepare before selecting an update. Changing the manifest after selection
is rejected by the child fingerprint check. Retain older artifacts for rollback.

Generate a new source handoff after finalizing source/manifest:

```powershell
.\.venv-local\Scripts\python.exe scripts\Create-DesktopWorkerBundle.py
```

## Evidence and completion boundary

Read `output/onboarding/step5-verification.json`, `step5-acceptance.md` and
`step5-docker-verification.json`. Unit import failures use mocks. The local
acceptance actually imports the archive, tests the cache, performs pinned Docker
preflight, and runs an isolated HTTP/PostgreSQL image job. Its owner decision is
an automated fixture, not a human popup. It leaves the shared demo data intact.

The user reported **Approved images passed real preflight** on a separate Windows
laptop. This is user-reported external-machine evidence, not direct observation
by this agent. Approved job ownership/results on that laptop and its exact
OS/Docker versions are the remaining final checks. No Step 6 installer, physical
reboot/multi-device fault matrix, cloud deployment or energy/accuracy claim follows
from this milestone.

To rerun the local fixture after building the backend, use a private LOCAL
development database environment file (never a production environment):

```powershell
.\.venv-local\Scripts\python.exe scripts\verify_offline_runtime.py `
  --development-env-file infra\.env.phase2 `
  --archive output\runtime\team-offline-v1\images.tar
```

That env file is machine-specific and ignored. The fixture uses a generated
`ewaste_test_step5_*` schema, a loopback ephemeral API and generated test tokens;
it drops only that schema after acceptance. Never share private fixture state.
