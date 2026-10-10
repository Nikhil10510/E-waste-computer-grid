# Step 7 - physical Windows and LAN acceptance

Prepared 10 October 2026. Implementation is available in the Windows 0.6.2
release. Local five-worker evidence is a single-PC simulation with real frozen
EXEs and Docker computation. Do not mark the following gates passed until the
listed machines and operations are actually observed.

Local blocked-connection recovery, five frozen helpers and installer lifecycle
checks are recorded in [software completion](SOFTWARE_COMPLETION.md). These do
not replace physical Wi-Fi loss or separate-machine acceptance.

## Start with a clean worker laptop

1. Pull current source on the coordinator and obtain the trusted Setup EXE,
   matching checksum JSON and team-offline-v2 archive. Follow
   `WINDOWS_WORKER_RELEASE.md`. Do not distribute AppData or private tokens.
2. Keep PostgreSQL/API/dashboard on one coordinator. Check its actual Wi-Fi IPv4
   with `ipconfig`. Ensure the API is reachable from the worker:

   ```powershell
   Invoke-RestMethod http://COORDINATOR_IP:8080/api/health
   ```

   Replace `COORDINATOR_IP` with the current IP. An `ok` response confirms API
   reachability; same Wi-Fi alone does not overcome client isolation/firewall.
   For private LAN HTTP explicitly select the owner app's HTTP option. Public
   use needs the separately configured HTTPS deployment.
3. On a supported Windows amd64 machine without Python/source, install the
   worker. Docker Desktop/WSL and Linux containers remain prerequisites. Record
   Windows/Docker versions and the installer/archive hashes.
4. With no pairing, confirm the app does not create/claim job work. Import the
   archive, complete preflight and generate a code. An administrator invites it;
   the owner approves locally. Record the physical laptop name and public node
   ID, never its node secret or pairing private secret.
5. Upload ten known demo photos from the coordinator, chunk size 5. Require
   COMPLETED, two accepted tasks, zero failed tasks, ten exact predictions and
   exactly one accepted metric per task. Confirm task owners correspond to the
   separate laptop, and retain downloaded JSON and sanitized logs.

## Then test four or five physical laptops

1. Repeat installation/approval on every contributing machine, with its own
   independently created identity and owner-approved limits. No backend,
   dashboard or dataset installation is required on worker-only laptops.
2. Verify all intended workers are online. Pause them while preparing inputs,
   then upload enough independent images and small chunks to observe parallel
   activity. Use real images with unique submitted identities; record the exact
   input list. A task is a batch, not a laptop, so assignments need not be equal.
3. Resume and watch separate machines compute at overlapping times. Retain
   node-to-device mapping, per-task owner IDs and real container image IDs/CPU
   and RAM quotas. Dashboard Online cores is reported capacity, not live usage.
4. During a running task, close/stop only one test worker, or deliberately end
   its identified test process. Keep the coordinator and other workers alive.
   Verify remaining workers retry unfinished work and finish the same job.
   Default leases can take minutes to expire; do not promise instantaneous retry.
5. Check every input exactly once, one accepted metric per completed task,
   bounded retries and no leftovers belonging to stopped workers. Reopen the
   stopped laptop and validate the same saved identity and paused state.
6. Separately disconnect one worker's Wi-Fi, restore it, and check recovery
   without copying/clearing credentials. Do not change the coordinator's network
   while trying to isolate only a worker-side outage.

Do not claim speedup from the single-PC test. If benchmarking, compare identical
inputs/model/chunking and a declared timed interval on one versus several
physical devices. Warm/cold runtime preparation must be reported separately.
Energy remains ESTIMATED unless measured independently under a stated boundary.

## Owner, startup and install matrix

| Gate | Required observation | Current status |
| --- | --- | --- |
| Clean worker without Python/source | Installed app imports, pairs and finishes exact real-image job | Pending |
| Decline/expiry/revocation | No unauthorized job start; revoked identity cannot resume | Local protocol tests pass; physical run pending |
| Tray while running | Explicit hide/open works; Pause/Resume/Stop/Exit affects only owned work | Local GUI and helper tests pass; combined physical run pending |
| Startup off | Sign-in/reboot leaves app closed and no computing | Pending real sign-in |
| Startup on | Sign-in opens one app; no automatic computing; pause retained | Registry logic tested; real sign-in pending |
| Startup disabled again | Owned login entry absent; next sign-in does not launch | Pending real sign-in |
| Upgrade active/paused | Stop handshake, retry unfinished work, same identity/limits/pause | Local idle GUI upgrade passes; active-operation run pending |
| Uninstall during download/inference/upload | Owned activity stops; no false completion; unrelated containers survive | Local uninstall/worker cancellation pass separately; combined run pending |
| Another Windows account/device | Copied DPAPI state unreadable and preserved with guidance | Pending physical/account run |
| Missing/stopped/wrong Docker | Clear preflight failure and no enrollment or native fallback | Missing endpoint tested; other configurations pending |
| Bad archive/manifest, low disk | Fail visibly before job start; preserve state; repair documented | Archive/manifest unit tests pass; environmental failure run pending |
| LAN crash/outage recovery | Another physical worker accepts retry; exact inputs and metrics | Local five-worker crash test passes; LAN pending |

For damaged installs or incompatible releases, retain state and diagnostics.
Do not solve a setup fault by deleting credentials, broad process kills,
database resets, shared Docker pruning or copying another owner's identity.
Use controlled test accounts for install/reboot/fault tests.

## Evidence to retain

Create a new dated acceptance record with release/checksums, actual OS/Docker
versions, physical device inventory, coordinator URL without secrets, public
node IDs, source/build fingerprint, exact inputs, task ownership, retry counts,
downloaded output, accepted metric counts, cleanup and pass/fail/pending entries.
Sanitize screenshots and logs. Distinguish human-observed actions from automated
fixtures. Update the current ledger while retaining older checkpoint evidence.

## Prompt for the next teammate or AI

Read docs/WINDOWS_WORKER_RELEASE.md, this runbook and
output/onboarding/step6-acceptance.md before making changes. Steps 1-4 and Step 5
offline implementation exist; Step 6 Windows packaging/tray/startup/lifecycle
now has local evidence. Step 5's separate-laptop job and Step 7's clean-PC,
real-login and physical LAN gates remain pending. Start by verifying the actual
release and running these gates, not rewriting the scheduler or enrollment.
Preserve consent, DPAPI state, resource limits, pause, immutable workload IDs,
attempt fencing and exact results. Make fixes only for observed faults; report
remaining hardware/environment gates honestly. AWS publication and a waste
classification model are separate scope.
