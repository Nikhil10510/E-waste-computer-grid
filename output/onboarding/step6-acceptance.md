# Step 6 local acceptance - 10 October 2026

Implementation: Windows amd64 release 0.6.1, PyInstaller 6.22.3, NSIS 3.13,
Python 3.12.6, Windows 11 build 26300, team-offline-v2 Linux amd64 images.
Base commit: bd9271b521403a2981bb7244b06a0fb71573812f plus current local changes.
Exact compiled inputs and artifact hashes are in the release metadata/checksums;
this implementation task has not committed or pushed these changes.

## Implemented and locally verified

| Check | Result and evidence |
| --- | --- |
| Frozen owner app and helper | Both real EXEs built with shared dependencies, Tk/Tcl, manifest and license inventory |
| Real installed GUI/tray | Widgets, real tray hide/open, duplicate launch, isolated startup toggle and Exit pass: step6-gui-smoke.json |
| Per-user install lifecycle | Install from previous development build, upgrade while its GUI runs, new installed GUI smoke and uninstall while GUI runs pass: step6-installer-lifecycle.json |
| State preservation | Encrypted identity/limits/pause retained byte-for-byte on upgrade and readable after uninstall; unrelated fixture process survives |
| Real packaged computation | Ten pinned real photos, two accepted tasks, exact input accounting, zero errors and two metrics: step6-packaged-job.json |
| Consent enforcement | No fixture worker launched before simulated approval; packaged helper rejects missing approval even with environment override; native fallback refused |
| Resource/participation | Actual immutable images, 0.5 CPU/1 GiB test quotas, no extra swap, read-only/no-network containers; pause blocks new tasks and survives helper restart |
| Scoped cleanup | No owned containers remain after Stop; a real unrelated test container survives; only fixture-owned artifacts are cleaned |
| Five-worker recovery | Five frozen helpers on ONE PC, 60 image inputs/30 tasks, concurrent execution, deliberate helper crash, lease retry, exact results and one accepted metric per task: step7-local-five-worker.json |
| Regression | 97 worker tests, 33 configured backend tests (zero skips) and 32 workload tests pass |
| Portable compiler | Official NSIS archive/compiler hashes verified; no global compiler installation |

Approvals in the packaged-helper fixture are simulated in an isolated loopback
HTTP/PostgreSQL schema. This is not human consent or a separate laptop. Docker
computation is real. The installer fixture exercises real Windows install/UI
operations with private test state. Registry startup toggles use an isolated
test key; actual login startup remains untouched.

An upgrade test exposed delayed Windows DLL release after the old GUI lock was
released. The app now verifies owner executable/PID/start time and waits for full
process exit; the installer has a bounded dependency-directory release retry
for older versions and refuses failed stop/write operations. No blanket process
kill, Docker prune, owner-state deletion or database reset was introduced.

The v1 archive was unavailable here. A new verified v2 archive was built from
available workload images, with the same pinned model/labels and new immutable
image/archive identities. Historical v1 evidence is retained, not rewritten.

## Reproduce local checks

Run from the repository root using a working development Python environment:

```powershell
$compiler = .\scripts\Get-NsisCompiler.ps1
.\scripts\Build-WindowsWorker.ps1 -NsisCompiler $compiler -Python python
.\.venv\Scripts\python.exe -m unittest discover -s worker/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s workloads/tests -v
```

For isolated real helper acceptance, set `TEST_DATABASE_URL` privately to a
dedicated localhost test database with schema-create privileges. The fixture
creates and drops only its generated schema. Start Docker with the v2 images
already imported and ensure backend dependencies/build and ten demo photos exist:

```powershell
.\.venv\Scripts\python.exe scripts\verify_packaged_workers.py `
  --helper .build\windows\dist\EWasteGridWorker\EWasteAgent.exe `
  --workers 1 --report output\onboarding\step6-packaged-job.json
.\.venv\Scripts\python.exe scripts\verify_packaged_workers.py `
  --helper .build\windows\dist\EWasteGridWorker\EWasteAgent.exe `
  --workers 5 --report output\onboarding\step7-local-five-worker.json
```

The fleet fixture accelerates lease/offline/heartbeat timers only in its own
server/helper processes; production defaults are unchanged. It kills only one
Popen-owned disposable helper and removes only its owned sentinel container.

`scripts/verify_windows_installer.py` accepts `--installer`, `--previous` and
`--report`. It refuses an existing owner installation/shortcuts/startup entry,
uses a generated dedicated workspace install path/private AppData and performs
real same-user registry/shortcut changes. Use a controlled test account. The
previous 0.6.0 installer in `.build` is a local development fixture, not a
published historical release or a supported rollback promise.

## Still pending

- Step 5 final separate-laptop job ownership/result record.
- Clean Windows laptop without system Python/source and another account/device.
- Real sign-in/reboot with startup off/on/off and saved pause.
- Physical 4-5 laptop LAN computation, worker/network failure and recovery.
- Combined active installer operations during download/inference/upload and
  environmental failure checks (low disk, wrong container mode, damaged install).
- Remote execution of the newly added Windows CI package job.

These are acceptance gates, not evidence already obtained. The detailed next
procedure is docs/STEP7_PHYSICAL_ACCEPTANCE.md. Public signing/distribution, AWS
deployment and a trained waste-category model remain separate product work.
Current output is ImageNet classification and estimated energy; no measured
savings, physical fleet performance or 100% reliability claim is made.
