# Step 2 local acceptance — 2026-10-09

Step 2 is complete for the source-based desktop app on this Windows machine.
The remaining resource-policy matrix, protected storage, installer and separate
physical laptop acceptance are subsequent milestones.

## Environment and boundaries

- Current source based on `672a8698bc7e4404c2d1545c50760dafbfcf455d`, with
  the fixes described below.
- Local API `http://127.0.0.1:18080/api`; dashboard preview port `15173`.
- Separate PostgreSQL schema `ewaste_acceptance_step2_20261009` on port `55433`.
  Existing demo data was retained. Legacy enrollment was disabled for this run.
- Docker engine `29.6.1`, Linux workload images built from the repository:
  `ewaste/dummy-workload:v1` and `ewaste/ai-workload:v1`.
- Actual Tkinter UI controlled through Computer Use. Admin invitations in this
  continuation used the authenticated HTTP API; the dashboard invitation form
  had already been observed submitting successfully in the earlier Step 2 run.
- Private state/logs are in ignored `.test-data/step2-acceptance`. This record
  contains no admin tokens, private pairing secrets or worker credentials.

At the end of acceptance, the test desktop/worker and the tracked acceptance
API/preview processes were stopped. Shared Docker/PostgreSQL and all evidence
were retained. Start the API again before repeating the owner flow below.

## Observed acceptance

| Check | Observed outcome |
| --- | --- |
| Prepare connection | Docker preflight passed and displayed an eight-character code. |
| Before approval | Zero nodes, no worker log/process; invitation alone did not start computation. |
| Owner dialog | Grid name, local API address, approved workloads and 2 CPU / 2 GiB ceilings displayed. |
| Approve and start | Actual desktop button saved one paired identity and started its Docker agent. |
| Image computation | Ten repository demo photos, five per task: two completed tasks, zero failed items/tasks, ten predictions. |
| Stop worker | Desktop showed stopping then stopped; no workload containers remained. |
| Full app restart | Closed and relaunched app with the same state directory. Prepare showed Already approved. No new pairing was required. |
| Explicit restart | Second job remained QUEUED with zero completed tasks until the desktop Start worker button was activated. |
| Identity reuse | Second image job completed; database retained exactly one node. All four tasks belong to that same node. |
| Close while running | Closing the desktop stopped its idle agent and the desktop process exited. |
| Decline | Actual Decline button created no additional node, no saved identity and no worker log/process. |
| Expiry | Advanced only a fresh test session's UTC expiry in the isolated schema; real polling reported EXPIRED. Desktop cleared the session and showed Code expired. |
| Recovery | Prepare connection generated another fresh code after expiry, with no worker started. |

The expiry fixture accelerated the ten-minute wait; it did not alter production
TTL configuration or the existing demo database. The separate HTTP 410 race when
a decision arrives after expiry is covered by a Tkinter regression test using a
mocked HTTP error, not claimed as a live race observation.

## Results and ownership

Worker ID: `ca01326e-5efe-4d97-b0f4-24c773814bca`.

| Run | Job ID | Images | Tasks | Failed |
| --- | --- | ---: | ---: | ---: |
| After desktop approval | `fcdaf783-6a44-46d1-8ba8-f22e8569c773` | 10 | 2 | 0 |
| After full app restart | `073785df-de23-4dcc-87f5-400c01a7d7ca` | 10 | 2 | 0 |

- [First downloaded result](step2-desktop-job1-results.json) and
  [coverage check](step2-desktop-job1-check.json).
- [Restart downloaded result](step2-desktop-job2-results.json) and
  [coverage check](step2-desktop-job2-check.json).
- [Database task ownership](step2-desktop-task-ownership.json).
- [Verification ledger](step2-verification.json).

`workloads/test-data/verify_job_results.py` checked exact image identities,
expected task splitting, prediction structure, no errors and explicitly
estimated metrics for both downloads. This proves execution and accounting;
it does not establish visual classification accuracy or waste-category support.

## Fixes and automated checks

The expired-decision HTTP 410 path previously retained the unusable private
session and kept retrying it. The desktop now clears it, closes the invitation
and enables Prepare connection. A Tkinter callback test checks recovery without
spawning compute. Frontend lint now targets `src` and `vite.config.ts`, avoiding
installed dependency code. Onboarding docs now distinguish completed Step 2
from existing Step 3 features whose full acceptance is still pending.

The continuation's checks passed: 31 backend tests with zero skips, 33 worker
tests, 32 workload tests, frontend build and frontend lint. Backend tests use
real isolated PostgreSQL/HTTP integration; desktop callback tests mock HTTP and
child computation. The live UI/Docker runs above supplement those tests.

## Repeat the owner flow

1. Start the current backend and prepare both Docker workload images using the
   repository setup instructions. Use a separate test database/schema if testing
   with disposable identities.
2. From repository root, run the source desktop with your Python environment:
   `.\.venv\Scripts\python.exe worker\desktop.py --api-url http://127.0.0.1:18080/api --allow-http`.
   Match the actual API port; another laptop must use the API host's LAN address.
3. Choose limits, click Prepare connection and give only the displayed code to
   the grid administrator.
4. In the administrator dashboard, enter the code in the invitation form.
5. Inspect the owner dialog and choose Approve and start, or Decline.
6. Submit an image job in the dashboard; download and verify its results.
7. Click Stop worker. Close/reopen the app, click Prepare connection, then Start
   worker. It should recognize the saved identity without generating a new code.

Source/Python, Tkinter, Docker and prebuilt images are still required. A Windows
installer, protected credential store, reboot test and approval-based onboarding
on a second physical device are not delivered or verified by this milestone.
