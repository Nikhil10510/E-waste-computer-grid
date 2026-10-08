# Worker onboarding implementation

## Step 1 — pairing and approval backend

Implemented locally: expiring pairing sessions, authenticated invitations,
owner decisions, private worker credentials, reconnect and revocation.
The dashboard invitation form and source-based Windows approval window now
exist. The installer and complete Windows interaction acceptance are pending.
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

2. Finish interactive approval/stop/restart acceptance for the source-based
   pairing client, invitation form and desktop window. See the step 2 record.
3. Add configurable, validated Docker CPU/RAM limits, local resource consent,
   pause/drain and stop semantics, with server-side admission state.
4. Build the Windows desktop interface, responsive background polling, runtime
   checks, readable logs, and protected identity/settings storage.
5. Distribute verified workload images and automate checks/download/preflight.
   Docker/WSL remains a supported-device prerequisite for this execution path.
6. Package the app/runtime into a Windows installer; add optional login startup,
   tray controls and clean uninstall. Test on a machine without Python/source.
7. Verify the full flow on a separate physical laptop, including decline,
   expiry, reboot, resource limits, pause, revocation and network interruptions.

These pending steps are not verified by step 1's API tests. They are separate
acceptance gates before describing onboarding as one-click or production-ready.

## Step 2 — source-based invitation and desktop preview

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
- `worker/desktop_runtime.py`: uses the existing Docker worker with fixed limits
  of two CPU equivalents and 2 GiB per workload. It does not pass shared admin
  or enrollment tokens to the worker. The worker refuses script identities
  when `REQUIRE_PAIRED_IDENTITY=true`.
- Graceful local stop request checked by the agent. The controller waits for
  shutdown instead of killing unrelated processes or containers. An outstanding
  network request may delay exit; pause/drain and custom limits are not added.

From repository root on the current API machine:

```powershell
.\.venv-local\Scripts\python.exe worker\desktop.py --api-url http://localhost:18080/api --allow-http
```

On another laptop replace localhost with the current API host address. Python
3.12 with Tkinter, current source, Docker and the two existing workload images
are still prerequisites. No installer, tray icon, autostart or automatic image
download exists yet. App state defaults to a per-grid folder under
`%LOCALAPPDATA%\EWasteGrid`; `--state-directory` overrides it for development.
Private session/identity files still need the protected-storage milestone.

Verified: **29 backend tests, zero skips; 24 worker tests; frontend build/lint**.
Real Python clients approve/decline through HTTP and persist credentials. An
approved real agent computes with an intentionally invalid global enrollment
token in an isolated test schema. Unit checks cover lost responses, failed
credential writes, redirects, desktop identity enforcement and scoped stop.

The Windows main window was visually inspected; its Docker preflight generated
a code. The local dashboard showed a successful invitation to that code.
Computer Use was stopped with Escape before the delivered approval popup was
visually checked. Native button approval, worker stop/restart and separate-device
acceptance are **not verified**. Continue those checks next; do not mark all of
step 2 complete based on API tests alone. The local dashboard image was rebuilt;
AWS was not updated. See `output/onboarding/step2-verification.json`.
