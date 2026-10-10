# Software completion and team resumption checkpoint

10 October 2026. This document supersedes earlier implementation-pending PDF
snapshots. The core local hackathon software is implemented and tested. It does
not certify all machines, the entire long-term roadmap or a public deployment.

## What the project does now

The coordinator accepts photos, splits them into independent batches and stores
jobs in PostgreSQL. Consenting workers claim eligible batches over HTTP, download
their assigned inputs, run the approved Docker workload on their own CPU/RAM and
return validated JSON. Multiple workers can process separate batches concurrently.
RAM is local to each worker; the project does not combine laptops into shared RAM
or accelerate arbitrary applications. The dataset is uploaded on the coordinator;
worker-only laptops receive their assigned inputs automatically.

The real workload is MobileNetV2 ImageNet classification: one object label and
confidence per photo. Results can feed a downstream report or application. This
is not yet a wet-waste/plastic/e-waste classifier, object detector or image editor.
The pipeline demo returns synthetic results to exercise scheduling and transport.

## Newly completed software

- Windows 0.6.2 frozen GUI/helper, per-user installer and portable distribution;
  tray controls, explicit Start, opt-in login launch, owned shutdown, upgrade and
  uninstall. Docker Desktop/WSL remains a prerequisite. Windows DPAPI protects
  per-user identity/settings. Uninstall preserves that protected state.
- Reviewed offline v2 runtime manifest, immutable Docker image IDs, archive
  checksums and real preflight. Owner pairing/approval, limits, pause/drain and
  Stop controls remain enforced; packaged helpers require pairing and Docker.
- Paginated jobs, per-job input counts, timing, contributing workers and scoped
  energy estimates. Expand a job to see batches and an individual batch to see
  worker assignment attempts, retry reasons and per-image predictions/errors.
- Durable task-attempt history; accepted completion and metrics stay duplicate
  safe. Old jobs retain their results but cannot acquire invented historical
  attempt records or reliable start timestamps retroactively.
- Cancel unfinished jobs. Accepted results remain downloadable; queued/assigned
  work is fenced and unfinished inputs count as cancelled. Cancellation is
  idempotent and cannot resurrect completed work or accept late results.
- Independent monotonic lease watchdog stops expired owned computation even
  while a heartbeat HTTP socket is blocked. Relative lease time avoids reliance
  on matching PC clocks; network round-trip time is subtracted conservatively.
  Transfer/report calls remain bounded by their existing network timeouts.
- Safe SQL migration deployment with explicit baselining for supported old
  installations. Unexpected schema drift is refused without resetting data.
- Database readiness and process liveness endpoints, request IDs and sanitized
  operational errors. Dashboard stale-data feedback and cancellation of pending
  requests on disconnect/unmount prevent old responses repopulating a session.
- Windows build/artifact CI job, release metadata, dependency/license inventory
  and reproducible acceptance scripts. Remote CI has to pass independently.

## Upgrade and run after pulling

Preserve local environment files, data, owner state and credentials. Stop API and
workers before schema changes and back up the existing PostgreSQL database. On
Windows stop processes using Prisma before regenerating its client (a loaded DLL
can otherwise cause EPERM). Run from your own checkout, not someone else's .venv.

For a source-based coordinator whose database is already running:

```powershell
cd C:\path\to\E-waste\control-plane
npm ci
# Configure DATABASE_URL and the existing API settings in your local .env.
npm run db:deploy
npm run build
npm start
```

`db:deploy` supports a fresh database, the exact pre-migration baseline and the
exact current schema. It records the supported baseline, then applies additive
migrations. If drift is reported, retain the data and review the discrepancy;
do not use reset or --accept-data-loss. Baseline migration files are immutable.
Docker coordinator startup now runs this migration command too.

In a separate frontend terminal:

```powershell
cd C:\path\to\E-waste\frontend
$env:API_PROXY_TARGET="http://127.0.0.1:8080"
npm ci
npm run dev
```

Keep both terminals open. Check `/api/health` and `/api/ready` on your configured
API port. `/api/live` confirms only that the API process responds. Connect the
dashboard using the configured admin token; never share it with worker owners.
For Compose setup use the root README and preserve existing infra/.env values.

Worker-only laptops use the 0.6.2 Setup EXE and matching team-offline-v2 archive.
See WINDOWS_WORKER_RELEASE.md for checksums, build instructions and the owner
flow. Git excludes installers and the large offline archive: pulling source does
not download those binaries. Build them or obtain the trusted team/CI artifacts.
On a different laptop use the coordinator's current LAN IPv4 and port, not
localhost. Workers do not need the backend, Node, source checkout or dataset.

## Demonstrate and explain the result

1. Pair and approve workers, choose resource ceilings and explicitly Start them.
2. Upload photos, choose Image classification, give the job a name and set a
   small batch size. For 58 images and 2 items/task, there are 29 tasks.
3. Expand the job and batches. Show which worker attempted each batch and why
   retries happened. FIFO eligible claims need not split work equally.
4. Show each input's label/confidence or error, then download aggregated JSON.
   Batch completion can include individual failed images: inspect item counts.
5. Compare elapsed job time with cumulative accepted execution time. They are
   different: workers can overlap. Energy excludes retries/transfer/idle energy
   and is an estimate, not metered savings. Online CPU capacity is not utilization.
6. Cancel a separate unfinished test job to demonstrate retained accepted output
   and cancelled input counts. Stop an owned test worker to demonstrate recovery.

Presentation wording: "We reuse consenting idle computers for independent image
classification batches. Each laptop computes locally and sends predictions back;
the dashboard exposes worker ownership, retries and exact input coverage. The
grid can host a future validated waste classifier, but today's model recognizes
general ImageNet objects."

## Verification and evidence

- 100 worker tests, 32 workload tests and 41 backend tests (including three real
  migration cases) passed; frontend production build and lint passed.
- Real 0.6.2 installer upgraded 0.6.1 under private same-account test state,
  preserved protected identity/limits/pause, exercised installed GUI/tray and
  removed owned installation files. An unrelated test process survived.
- Five real frozen helper processes on one PC ran approved Docker image
  classification, exercised worker crash/reassignment and checked exact results,
  one accepted metric per completed task and owned-container cleanup.
- Two real frozen helpers tested blocked HTTP recovery with a five-second test
  lease: expired computation stopped in 4.640 seconds after simulated loss and
  the surviving worker accepted the 100-item synthetic batch exactly once.
- Browser verification exercised older-job pagination, attribution/retry history,
  per-image results/errors, cancellation, stale data and disconnect cleanup.
  That UI fixture uses synthetic predictions and is not classification evidence.

Current machine-readable reports are under output/onboarding/remaining-*.json.
Screenshots are remaining-dashboard.png and remaining-cancellation.png. Earlier
step6/step7 files are historical checkpoints; preserve their tested artifact
identities. No generated fixture borrowed real owner/admin credentials. Test
schemas are isolated and removed; existing application data was preserved.

## Remaining work requiring devices or separate decisions

1. Step 5/7 physical acceptance: approved job on a separate laptop, then four or
   five actual laptops, overlapping work, real Wi-Fi loss and recovery. Follow
   STEP7_PHYSICAL_ACCEPTANCE.md; one-PC helper tests do not replace LAN evidence.
2. Clean Windows without Python/source, another Windows account/device, real
   sign-in/reboot startup, and upgrade/uninstall during download, inference and
   reporting. Damaged install, low disk and unsupported runtime acceptance remain
   release gates. The installer is unsigned development distribution.
3. Waste classification: select/train/export a suitable model, define labels and
   preprocessing, pin its runtime, and evaluate a held-out labelled dataset before
   promising wet/plastic/e-waste predictions. Current inference alone does not
   implement that use case.
4. Public AWS hosting, HTTPS, real S3 integration/deployment acceptance, signing
   and production operations. No cloud deployment or spending was performed here.
   Keep this prototype on the controlled team network; legacy shared-token
   enrollment is a development flow and can be disabled for paired workers.
5. Physical speedup and energy measurement with identical inputs and stated
   boundaries; hardware provenance/consent evidence for the reuse claim. Later
   portfolio features and production security/scale work remain separate scope.

AI resumption: inspect this document, WINDOWS_WORKER_RELEASE.md and current Git
history first. Preserve local secrets/state and the input/output/lease contracts.
Do not mark a device gate complete using loopback tests; do not substitute this
ImageNet model for a trained waste model or claim estimated energy as savings.
