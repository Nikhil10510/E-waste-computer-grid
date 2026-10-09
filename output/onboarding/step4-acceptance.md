# Step 4 acceptance — desktop reliability and protected state

Verified locally on 2026-10-09 in `C:/Users/BIT/Desktop/E-waste`. Base commit:
`672a8698bc7e4404c2d1545c50760dafbfcf455d`, with existing Steps 2–3 changes retained.
Step 4 is complete for the source desktop on this development machine.

## What changed

| Area | Implementation and purpose |
| --- | --- |
| Windows state | `worker/state_store.py` encrypts credentials, private pairing sessions and settings using current-user DPAPI, with atomic replacement and file locks. Existing JSON migrates on a successful read. Damaged, oversized or undecryptable files are preserved and rejected. |
| Shared clients | `api_client.py`, `pairing_client.py` and `desktop_runtime.py` share protected state, retain unknown fields and bind identity to the selected grid. Credential HTTP requests refuse redirects. |
| Desktop | `desktop.py` adds Connection/Diagnostics tabs, scrolling content and persistent controls. Preflight, requests, process launch and log reads run in background threads. Settings and selected grid persist; retry retains the approved identity. |
| Shutdown | Pending launch honors Stop; close waits for background operations and the owned process. Disconnect stops the process before allowing a different grid and retains identity. Launch failure allows retry without another approval. |
| Diagnostics | `log_safety.py` redacts known tokens, bearer values, secret fields and URL queries. Desktop-agent logs rotate at 1 MiB with two backups; diagnostics reads at most 16 KB from each of three logs. Preflight errors expose the actual runtime issue. |
| Source handoff | `Create-WorkerBundle.py` now includes required state, logging and resource-policy modules; its ZIP integrity/hash checks passed. This preserves the existing CLI source handoff. |

The API/schema, scheduler and inference model are unchanged by Step 4. No new
Python package is needed for DPAPI. Windows state is protected by the current
user's Windows credentials, with no adjacent plaintext encryption key.
[Microsoft documents DPAPI account binding](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).
POSIX still uses owner-only files (0600), rather than this Windows encryption.
Encryption does not protect against code running as the same user, and migration
does not erase historical copies/backups.

## Automated verification

- **61 worker tests passed**, including actual Windows encryption, plaintext
  migration, failed encryption/atomic replacement, tampering, malformed/oversized
  state, concurrent updates and a second process reading/updating protected state.
- Tk callbacks exercised delayed preflight, connection failure/recovery, revocation,
  settings restore, small-window controls, disconnect, launch failure and Stop
  while launch is pending. HTTP/process behavior is mocked in these callback tests.
- Worker regressions stop during image download and result upload, clean partial
  input, avoid completion and release the fenced assignment. Existing tests cover
  execution cancellation, stale lease, late task response and failed release.
- **33 backend tests passed, zero skips**: 26 actual PostgreSQL/HTTP integrations
  and seven unit checks. Backend build passed. A real paired Python agent reads
  protected credentials and computes without a shared enrollment token.
- Existing CLI bundle rebuilt: 25 source files; integrity and per-file hashes
  checked. This proves source packaging compatibility, not installer acceptance.
- Frontend/workload suites were not repeated: their source did not change here;
  Step 2 records retain the prior checks.

Commands used from repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s worker\tests -v
$env:TEST_DATABASE_URL = 'postgresql://ewaste@127.0.0.1:55433/postgres'
$env:TEST_PYTHON = "$PWD\.venv\Scripts\python.exe"
Push-Location control-plane
npm test
Pop-Location
.\.venv\Scripts\python.exe scripts\Create-WorkerBundle.py
```

## Real Windows desktop / Docker acceptance

Isolated coordinator: `http://127.0.0.1:18082/api`, PostgreSQL schema
`ewaste_acceptance_step4_20261009`, private fixture `.test-data/step4-acceptance`.
Windows Python 3.12, Docker Engine 29.6.1; prepared workload images. Private
tokens and encrypted state stay in the ignored fixture, outside public evidence.

1. Opened the actual source desktop. The saved laptop name and 0.5 CPU / 0.75 GiB
   limits appeared. Connection content scrolled; all four controls were visible
   at the tested 150% display scale.
2. Prepared the connection through the UI; actual Docker preflight passed.
   Administrator invitation used authenticated local HTTP. Preparation/invitation
   created zero nodes and started no computation.
3. Inspected the real invitation showing the grid/API and custom ceilings.
   Activated **Approve and start** through the actual window. One paired node
   was created and encrypted credentials were saved. This closes the Step 3
   manual custom-limit approval gap.
4. Used Pause in the desktop; submitted ten genuine photos in two five-image
   tasks via the local API. The job stayed QUEUED with zero accepted tasks.
   Used Resume; both Docker tasks completed. Downloaded results passed exact
   filename/chunk accounting, class/confidence contract and zero-error checks.
5. Opened Diagnostics and refreshed the view. It displayed preflight capability
   checks and agent task-completion logs without private credentials.
6. Paused and closed the entire app, then relaunched the same state directory.
   Name/limits restored. Prepare displayed Already approved and Resume worker.
   A second photo job stayed queued before Start and also after Start while paused.
   Resume completed its two Docker tasks under the same node ID, without a second
   node or approved pairing.
7. Used Disconnect / change grid. The agent stopped before the UI unlocked its
   fields and showed Not connected; protected credentials remained. Closed the
   app. Agent/desktop locks were released and no owned containers remained.

Final SQL accounting: **one node, one approved pairing, two jobs, four completed
tasks and four accepted metrics**, all owned by node
`294eb397-092b-4374-95fc-dac425001072`. Each job accounted for all ten submitted
photos, exactly once. These acceptance jobs explicitly requested 0.75 GiB;
normal dashboard image jobs retain their default 2 GiB admission requirement.

The final connection-label/recovery text adjustment was verified by Tk tests;
the live window had loaded the preceding source during the second job. Core
execution/storage/control behavior was identical.

## Evidence and cleanup

- [Verification ledger](step4-verification.json)
- [Task ownership and accepted metrics](step4-task-ownership.json)
- [Job 1 results](step4-desktop-job1-results.json), [coverage check](step4-desktop-job1-check.json)
- [Job 2 results](step4-desktop-job2-results.json), [coverage check](step4-desktop-job2-check.json)

Stopped only the acceptance desktop/agent and the tracked test API on port 18082.
Shared Docker/PostgreSQL and the isolated test evidence were retained. Historical
Step 2/3 records and unrelated local changes were preserved.

## Remaining boundary

Next is **Step 5: verified workload-image distribution**. Step 6 installer,
tray/login startup and uninstall are still pending, followed by Step 7 separate
physical-device/reboot/LAN failure acceptance. This run did not test a different
Windows account/machine or a live network partition. Those are distinct from
the actual same-account subprocess/app-restart checks and mocked network-failure
tests above. This is not a three-laptop demo, clean-machine installer, measured
energy-saving result, classifier-accuracy evaluation or AWS deployment.

Usage and recovery details: [worker onboarding guide](../../docs/WORKER_ONBOARDING.md).
