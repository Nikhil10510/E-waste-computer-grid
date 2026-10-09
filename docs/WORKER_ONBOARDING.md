# Worker onboarding implementation

## Current checkpoint - 10 October 2026

Steps 1-4 passed their local acceptance gates. Step 5 offline distribution is
implemented and has local import/pinned-Docker job evidence. The user reports
real preflight passed on the separate Windows laptop; its approved job ownership
and downloaded results are the remaining final check. See
[offline runtime setup and boundaries](OFFLINE_RUNTIME.md) and
`output/onboarding/step5-verification.json`. Earlier sections retain their dated
checkpoint claims. Installer/startup and physical recovery remain Steps 6-7.

## Step 1 — pairing and approval backend

Implemented locally: expiring pairing sessions, authenticated invitations,
owner decisions, private worker credentials, reconnect and revocation.
The dashboard invitation form and source-based Windows approval window now
exist. Step 2 Windows interaction acceptance passed locally; the installer and
separate-device acceptance are pending.
See step 2 below for the exact verified scope.

### Protocol

1. The app chooses an API address and verifies its runtime locally. Production
   uses a trusted HTTPS address; an arbitrary display name is not proof of identity.
2. `POST /api/pairing` sends the same hardware fields as script registration,
   excluding `registration_key`. It needs no global enrollment token.
3. The server returns `pairing_id`, an eight-character case-sensitive
   `pairing_code`, a private `pairing_secret`, `expires_at`, `grid_name`,
   `worker_name`, and state `WAITING`. The session lasts ten minutes by default.
4. The app shows only the code. Keep the private credential inside the app.
   Do not place it in URLs, notifications or logs.
5. An administrator sends `POST /api/pairing/invite` with
   `{"pairing_code":"..."}` and the existing admin bearer token.
   The state becomes `INVITED`; this does **not** create a worker.
6. The app polls `GET /api/pairing/:id` using its private pairing bearer token.
   Poll every few seconds, with backoff on errors and HTTP 429. The eventual
   interface displays the invitation and allows approve/decline.
7. The app sends `POST /api/pairing/:id/decision`, with the same private token
   and `{"decision":"approve"}` or `{"decision":"decline"}`.
8. Approval creates one `Node`, initially `OFFLINE`, and returns `node_id`,
   `node_secret`, `enrollment_mode` and `heartbeat_interval_seconds`.
   Save the identity **before** starting the agent. The enrollment mode is
   `paired`. Decline creates no node.
9. The existing agent uses the node identity for its session, heartbeats and
   task requests. Normal restart does not require the shared enrollment token.

State transitions: `WAITING -> INVITED -> APPROVED | DECLINED`. An expired
session reports `EXPIRED` and cannot accept a decision. An approval before an
invitation returns 409. Duplicate decisions are idempotent only when the decision
matches the already accepted outcome. Concurrent approvals and lost-response
retries return the same worker/credential; they never create another worker.
Recovery is available only until session expiry and never after node revocation.
Polling never returns the code, pairing secret, or worker secret.

Codes carry 48 bits of randomness; private pairing and new worker credentials
carry 256 bits. The database stores hashes of codes and pairing credentials.
Approved pairing records are retained as consent evidence. Other sessions are
removed by the existing sweep once expiry is more than 24 hours old.

### Reconnect and revoke

`GET /api/nodes/session` validates the existing worker credential.
`POST /api/nodes/session` also refreshes hardware and preflight capabilities.
Both use bearer `node_secret` and `x-node-id`; neither returns the secret.

`POST /api/nodes/:node_id/revoke` accepts the admin token, or that node's own
worker credentials. It is idempotent. Revocation blocks session, heartbeat,
assignment and result acceptance. The worker stops on 401/403 instead of
discarding its identity and silently enrolling again. Already executing work
stops when the agent observes the denial, rather than instantly at the server's
update. Unfinished assignments recover through the existing lease timeout/retry.
An already issued signed storage URL retains its own expiry, but cannot be used
to accept a completed result after revocation.

Dashboard output preserves `REVOKED` even after stale heartbeats and excludes
revoked devices from online capacity. It exposes no credentials or pairing codes.

New credential files include `control_plane_url`, preventing accidental reuse
of an identity with another server. Existing legacy files without that field
are accepted for compatibility and bound when saved; their prior origin cannot
be established retroactively. Secure Windows credential storage is still pending.

### Configuration and rollout

- `GRID_NAME`: configured display name, default `E-Waste Compute Grid`.
- `PAIRING_TTL_MS`: positive duration, default `600000`.
- `ALLOW_LEGACY_ENROLLMENT`: development defaults to true, production to false.
  The local Compose stack and examples explicitly keep it true so existing
  development launch scripts remain usable. Set it false for approval-only
  admission. A holder of the legacy enrollment token can otherwise register
  a fresh identity without pairing; revoking an old registration key does not
  invalidate the global token. Never distribute that token in the future app.

Upgrade the backend/schema **before** deploying the new agent, which uses
`/nodes/session` for saved identities. The old backend has no such route.

For the local Compose prototype, rebuilding the backend runs its existing
`prisma db push` startup against the updated schema. These changes add the
pairing table and two node columns, retaining existing records.

For a managed deployment, take the normal database backup, review
`control-plane/prisma/changes/20261009_pairing.sql`, and run that additive SQL
once against the pre-pairing schema before starting the new backend. Do not run
it again after `db push` has created the same fields. The upgrade is tested on
an isolated schema with an existing worker. This repository still has no Prisma
migration baseline; the SQL file does not pretend to create one. Establish
baseline/migration history before claiming a production release.

Pairing limits per source IP per minute: 10 creates, 30 invitation attempts,
30 decisions, 120 polls; responses include `Retry-After`. The limiter bounds
its in-memory map and removes expired buckets. It does not trust forwarded IP
headers. Multi-instance/proxy deployments require shared gateway limits and
correct proxy configuration; the in-process limiter alone is not a fleet-wide
security guarantee. Pairing is for the existing controlled team grid, not an
unrestricted public volunteer service or a new multi-tenant account system.

### Verification

Backend integration covers no work before approval, wrong secrets, authenticated
invitation, concurrent duplicate approval, decline/expiry, secret-safe polling
and dashboard, reconnect, revocation, legacy compatibility, lease recovery and
the additive database upgrade. Existing real Python/image integration is retained.
Worker tests cover saved identity reuse, grid binding and no re-enrollment after
revocation. Backend build and frontend build/lint are also checked.

Step 1 verification on 2026-10-09: **27 backend tests passed with zero skips**
(20 real PostgreSQL/HTTP integration cases and seven unit cases), **16 worker
tests passed**, frontend build and lint passed. Test schemas are separate from
the local demo database's public schema. The additive SQL upgrade retains a
seeded pre-existing worker. Windows sandbox restrictions required running the
Prisma/DB and worker child-process checks outside the sandbox.

The existing local `ewaste-phase2` backend and dashboard were rebuilt. The API
and dashboard proxy health checks pass, the protected pairing route responds,
and the existing demo retains one node, one job, two tasks and two metrics.
No AWS deployment was changed. See
[step 1 verification record](../output/onboarding/step1-verification.json).

## Next steps

2. Completed locally: interactive approval/decline, expiry, Docker computation,
   stop and full desktop restart with a saved identity. See the step 2 record.
3. Resource-policy acceptance completed locally with real HTTP/Docker checks:
   custom CPU/RAM ceilings, pause/drain, restart, admission and active stop/retry.
   Its custom-limit approval click was subsequently verified in Step 4.
4. Completed locally: responsive desktop, connection state, diagnostics,
   settings persistence, protected Windows identity/session storage and scoped
   stop/disconnect. See the Step 4 evidence below.
5. Distribute verified workload images and automate checks/download/preflight.
   Docker/WSL remains a supported-device prerequisite for this execution path.
6. Package the app/runtime into a Windows installer; add optional login startup,
   tray controls and clean uninstall. Test on a machine without Python/source.
7. Verify the full flow on a separate physical laptop, including decline,
   expiry, reboot, resource limits, pause, revocation and network interruptions.

The remaining steps are not verified by step 1's API tests. They are separate
acceptance gates before describing onboarding as one-click or production-ready.

## Step 2 — source-based invitation and desktop preview (complete locally)

Implemented:

- Dashboard code-entry form with case-sensitive validation, duplicate-click
  protection, API error reporting and explicit waiting-for-owner messaging.
- `worker/pairing_client.py`: private session persistence, atomic identity save,
  decline, lost-response/write recovery and credential-based reconnect. HTTPS
  by default; explicit trusted-LAN HTTP option. Credential-bearing requests
  reject redirects.
- `worker/desktop.py`: Tkinter window with background preflight/polling,
  code display/copy, approval dialog, start/stop and grid switching. No computing
  is started by merely preparing a code or receiving an invitation.
- `worker/desktop_runtime.py`: uses the existing Docker worker with saved limits,
  defaulting to two CPU equivalents and 2 GiB per workload. It does not pass shared admin
  or enrollment tokens to the worker. The worker refuses script identities
  when `REQUIRE_PAIRED_IDENTITY=true`.
- Graceful local stop request checked by the agent. The controller waits for
  shutdown instead of killing unrelated processes or containers. An outstanding
  network request may delay exit. Custom limits and pause/drain acceptance is
  recorded separately under Step 3 below.

From repository root on the current API machine:

```powershell
.\.venv\Scripts\python.exe worker\desktop.py --api-url http://127.0.0.1:18080/api --allow-http
```

On another laptop replace localhost with the current API host address. Python
3.12 with Tkinter, current source, Docker and the two existing workload images
are still prerequisites. No installer, tray icon, autostart or automatic image
download exists yet. App state defaults to a per-grid folder under
`%LOCALAPPDATA%\EWasteGrid`; `--state-directory` overrides it for development.
Private session/identity files now use Windows account protection; see Step 4.

Verified on 2026-10-09: **31 backend tests, zero skips; 33 worker tests;
32 workload tests; frontend build/lint**.
Real Python clients approve/decline through HTTP and persist credentials. An
approved real agent computes with an intentionally invalid global enrollment
token in an isolated test schema. Unit checks cover lost responses, failed
credential writes, redirects, desktop identity enforcement and scoped stop.

The local dashboard invitation form was previously observed submitting a code
successfully. This continuation used real authenticated HTTP invitations and
the actual Windows desktop controls. Preparing/inviting created zero nodes and
no worker process before owner approval. The dialog displayed the grid/API
address and resource ceilings. Approve and start created one paired identity.
Ten tracked photos completed in two Docker tasks with exact input coverage and
zero failures. Stop worker reported a clean stop with no workload containers
remaining. After closing and reopening the entire app, Prepare connection showed
Already approved. A second job stayed queued until Start worker was pressed,
then completed under the same node ID, without another pairing session/node.

Decline created no identity, node or worker. Expiry was exercised by advancing
only a fresh session's expiry in the isolated test schema; the app cleared it,
showed Code expired, and could generate a fresh code. The HTTP 410 decision-race
path is also covered by a Tkinter callback regression test. It previously kept
polling an expired private session; the fix clears that session and enables
Prepare connection. Frontend lint is scoped to application source/config so it
does not scan installed dependency code.

This verifies **Step 2 locally**, not onboarding on a separate physical laptop,
model classification accuracy, an installer, or the full Step 3 resource-policy
matrix. No AWS deployment was changed. Results and sanitized task ownership are
linked from [the acceptance record](../output/onboarding/step2-acceptance.md) and
[the verification ledger](../output/onboarding/step2-verification.json).

## Step 3 — participation and resource policy (verified locally)

The existing policy is now checked with real Docker containers, kernel cgroups
and the authenticated owner API. The test worker approved 0.5 CPU equivalents
and 0.75 GiB RAM. Docker enforced a 50,000/100,000 CPU quota, 805,306,368 memory
bytes and zero swap. Its paused process could not claim new work; pause during
execution drained only the active task. Pause and limits survived agent restart.
Resume finished the remaining work. A job requiring 1 GiB remained queued on
the 0.75 GiB worker despite its larger physical RAM.

Two gaps were fixed: Docker now caps combined memory/swap at the RAM ceiling;
owner stop explicitly returns a cancelled assignment using its lease token,
rather than leaving it assigned until expiry. This also handles a task response
arriving during shutdown. The release gets one HTTP attempt; failed delivery
falls back to server lease recovery. Revoked/stale leases cannot release a new
attempt. A stop/retry uses the existing retry budget, so repeated interruptions
can eventually produce a failed task.

### Using the controls

1. Open the source desktop against your running API, choose a laptop name and
   CPU/RAM ceilings, then click Prepare connection. Use the same API address on
   restart; state is stored separately per grid. For normal image jobs keep at
   least the default 2 GiB ceiling, which their default admission requirement uses.
2. Share only the code. After the administrator invites it, inspect the grid
   address and displayed ceilings and approve locally. Merely receiving an
   invitation starts no computation. Limits are fixed by this approval; changing
   them requires fresh owner approval, not a server-side increase.
3. Pause worker blocks new assignments while current work finishes. The API may
   show DRAINING before PAUSED. Resume worker allows polling to claim work again.
4. Stop worker cancels local execution and removes only this worker's containers.
   The interrupted task can retry on an eligible worker. Stop is asynchronous;
   outstanding network/Docker operations may delay it. After a stopped process,
   click Start worker explicitly. Starting while saved pause is true stays paused.

CPU is a quota in logical CPU equivalents, not a dedicated core reservation or
a percentage of the whole PC. RAM is a ceiling per workload container. These
ceilings do not include the Python agent or Docker/WSL overhead and do not pool
memory across laptops. One task runs at a time per worker. Native development
mode does not enforce Docker resource ceilings. The current admission contract
checks capabilities and required RAM, not live CPU utilization or a CPU minimum.

Verified on 2026-10-09: **33 backend tests, zero skips; 37 worker tests**. Backend
coverage includes simultaneous task polls versus pause/revoke, frozen consent,
lease fencing and duplicate result accounting. Worker coverage includes real Tk
callbacks with mocked HTTP/compute, resource validation and stop races. Live
Docker acceptance processed 300 synthetic inputs in three accepted tasks with
exact coverage and zero failures, including a cancelled/retried attempt. Another
test container remained running through all stops/restarts.

Custom values and preflight were observed in the desktop, but Windows capture
failed before its custom-limit approval click could be verified. That decision
and the live pause/resume matrix used the real HTTP owner client. This does not
claim a new full manual UI run, physical-laptop/reboot acceptance or waste-model
accuracy. This historical Step 3 record predates the Step 4 UI/storage checks
below. Steps 5–7 remain open. No schema/API
contract or AWS deployment changed in this continuation.

See [Step 3 acceptance](../output/onboarding/step3-acceptance.md),
[verification ledger](../output/onboarding/step3-verification.json) and
[live Docker evidence](../output/onboarding/step3-docker-verification.json).

## Step 4 — desktop reliability and protected state (complete locally)

The window now has a scrolling Connection tab and a Diagnostics tab. Start,
Stop, Pause/Resume and Disconnect stay outside the scrolling area. The default
window fits the tested Windows display at 150% scaling; a Tk test also verifies
that the controls remain visible at the minimum 520 × 440 logical size.
Preflight, HTTP polling, worker launch and log reads run in background threads.
The interface reports connection failures, retries the existing identity, and
shows recovery without obtaining a new identity. Authentication denial stops
participation and requires owner attention.

Windows encrypts the complete credentials, private pairing session and settings
records with current-user DPAPI. Existing plain JSON migrates atomically when
read successfully. Encryption/decryption failures, damaged envelopes and oversized
state stop the operation without replacing the identity or enrolling a fresh
worker. File locks and atomic updates preserve fields when the desktop and
agent save concurrently. POSIX uses mode 0600 files, not Windows encryption.
DPAPI uses the Windows account's protection, rather than a key stored beside
the credentials. Its account binding is described by
[Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).
It does not protect against malicious software already running as that user.
Migration does not remove historical plaintext from backups or disk history.

### Open and use the desktop

From repository root, using the existing Python environment:

```powershell
.\.venv-local\Scripts\python.exe worker\desktop.py --api-url http://SERVER_IP:8080/api --allow-http
```

Replace SERVER_IP with your coordinator's current LAN address. Use its configured
port; 18082 was only this acceptance fixture. For HTTPS omit `--allow-http`.
Python with Tkinter and the prepared Docker images are still prerequisites.

1. Enter the trusted API address, laptop name and desired CPU/RAM ceilings.
   Prepare connection checks the runtime and generates a code, or verifies a
   saved approved identity. Share only the pairing code with the administrator.
2. Inspect the invitation and approve locally. No worker starts before approval.
   Normal image submissions require the default 2 GiB RAM admission requirement;
   the 0.75 GiB acceptance jobs below explicitly requested 0.75 GiB.
3. Pause blocks new tasks while current work finishes. Stop cancels local work;
   an outstanding HTTP/Docker operation may take time to return. A Stop request
   made while launch is pending is applied once the process exists.
4. Disconnect / change grid stops the owned process before unlocking the address.
   It retains the saved identity and does not revoke it or erase results.
   Reconnect to the same grid and explicitly Start worker. A saved pause still
   requires Resume. Closing the app waits for background work and the owned agent.
5. Open Diagnostics and click Refresh diagnostics for bounded preflight and task
   log tails. Private tokens, bearer values and URL queries are redacted. The
   desktop agent log rotates at 1 MiB with two backups. This is local diagnosis,
   not a remote telemetry service; review logs before sharing.

Default state is per grid under `%LOCALAPPDATA%\EWasteGrid`. The last selected
grid is restored when starting without `--api-url`; name, HTTP consent and limits
are restored for that grid. An explicit `--state-directory` isolates development
fixtures and does not write global desktop preferences. Keep state on its original
Windows account and computer; do not copy it to other workers. For unreadable
state, preserve the files and investigate the account/backup rather than deleting
them to force enrollment. Each physical laptop needs its own approval.

### Verification and boundary

On 2026-10-09: **61 worker tests passed; 33 backend tests passed with zero skips**,
including actual PostgreSQL/HTTP and Windows encryption/subprocess checks.
Automated regressions cover network loss/recovery, revoked identity, delayed
preflight/launch, failed launch, shutdown during download/upload, atomic migration,
tampering, failed writes, concurrent state updates and log redaction. Docker
execution cancellation and retry retain the Step 3 live evidence.

Actual Windows UI acceptance approved 0.5 CPU / 0.75 GiB, then paused, resumed,
displayed diagnostics, closed, reopened and reconnected with the same identity.
Two real ten-photo jobs each completed two Docker tasks with exact filename
coverage and zero failures. Both stayed queued while paused, including after
restart/Start. Disconnect stopped the owned agent and retained encrypted identity.
This closes the prior manual custom-limit approval gap.

The existing CLI source ZIP allowlist now includes the new protected-state,
logging and resource-limit modules; its integrity/hash check passed. This is a
source handoff compatibility fix, not Step 5 image distribution or Step 6 packaging.
There is no installer, service, tray or autostart yet. Other Windows accounts,
physical reboot, separate laptops and LAN/network fault acceptance remain Step 7
checks. No backend API/schema, workload/model or AWS deployment changed here.

See [Step 4 acceptance](../output/onboarding/step4-acceptance.md) and
[verification ledger](../output/onboarding/step4-verification.json).
