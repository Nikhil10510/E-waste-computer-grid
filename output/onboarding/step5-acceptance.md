# Step 5 - offline distribution acceptance

Checkpoint: 10 October 2026. Base commit: `a14f604`; new changes are local.
Steps 1-4 retain their earlier local acceptance. This step implements the user's
chosen offline distribution route rather than selecting/publishing a registry.

## Result and actual evidence

- Exported two approved Linux/amd64 images by immutable image ID into
  `output/runtime/team-offline-v1/images.tar`, with a versioned trusted manifest,
  fixed archive checksum/size and pinned model/label hashes.
- Release creation compared the baked artifact contract with reviewed source and
  ran genuine restricted preflight before export. No enrollment was involved.
- Final isolated fixture imported the real verified archive via Docker, exercised
  a cache hit without an archive and ran pinned preflight plus a genuine image job.
  It simulated owner approval on a test node; it did not operate a live popup.
- Ten pinned photographs completed in two tasks: exact filename coverage, ten
  predictions, zero failures and two accepted metrics under one paired node.
- Observed **job attempt** containers used the expected inference image ID, one
  CPU equivalent, 2 GiB RAM, no extra swap, read-only root and no container network.
  The JSON distinguishes those snapshots from preflight probes.
- Stopped only the fixture's agent/API; the generated isolated test schema was
  dropped and no owned containers remained. Shared demo data was preserved.

See `step5-docker-verification.json` for actual job/task IDs, image IDs, observed
container policy, accepted counts and cleanup. `step5-job-results.json` is the
downloaded aggregate used for exact-coverage verification. This is one-host
automation, not model-accuracy, measured-energy, fleet or AWS evidence.

## Automated validation

- **84 worker tests passed, zero skips**, including Windows DPAPI/identity
  regressions, hidden Tk callbacks, cancellation, manifest/type/version bounds,
  corrupted/changed/undersized archives, engine/platform mismatch, missing/cache
  behavior, import failure, host disk checks and pinned task execution.
- **33 backend tests passed, zero skips**: 26 actual PostgreSQL/HTTP integration
  cases plus seven unit checks, including paired Python subprocesses. Backend
  build passed. Test schemas were isolated from the development public schema.
- **32 workload tests passed.** Frontend source was unchanged; build/lint was not
  repeated for this worker-only feature.
- Initial sandbox runs failed on temporary file/DPAPI permissions. Authorized
  unsandboxed reruns passed; those failures were not treated as successful tests.

Commands: worker/workload `python -m unittest discover`; backend `npm test` with
local `TEST_DATABASE_URL` and actual `TEST_PYTHON`; `Build-OfflineRuntime.py`,
`verify_offline_runtime.py` and `Create-DesktopWorkerBundle.py` from repository root.
Private environment values, pairing/node secrets and copied state are excluded.

## Separate-machine report and remaining gate

The user said a separate Windows laptop was available and reported:
**Approved images passed real preflight** after the offline-bundle instructions.
Record this as **user-reported**, not independently observed. Its exact OS/Docker
versions and whether its image store was initially empty have not been supplied.
The report used the first source preview; the final handoff has the same approved
image release with added fail-closed/cancellation checks.

Pending: owner prepares/invites/approves on that laptop, then it owns a ten-photo
job (chunk five), shows WORKING, and returns exact ten predictions/zero errors.
Record worker/job IDs, versions and sanitized downloaded coverage evidence. This
is the final distribution check; Step 7's broader physical fault matrix remains.
Do not infer that the final gate passed merely from the local automated test.

## Practical limits

Python/Tkinter and Docker/WSL remain prerequisites; the source ZIP is not an
installer and adds no service/tray/autostart. No public registry, signature service
or automatic update infrastructure was created. A trusted source manifest is the
trust anchor; hashing a malicious archive with a malicious manifest is insufficient.
Import cancellation can leave content in Docker after its CLI stops; no rollback
or global prune is claimed. Host disk headroom is an estimate, not WSL-store free
space. Runtime preparation performs tiny probes but never starts a job agent or
enrolls a node. Supported release is Linux/amd64; other hardware requires testing.

The large archive is ignored by Git and must be transferred separately. The source
and current manifest still need a reviewed commit/push for teammates using Git.
Use `docs/OFFLINE_RUNTIME.md` for receiving-laptop and maintainer procedures.
