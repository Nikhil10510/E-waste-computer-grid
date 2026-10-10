# Windows worker release 0.6.2

Checkpoint: 10 October 2026. Step 6 implementation and local acceptance are
complete. Step 5's separate-device job gate and Step 7's physical acceptance
remain pending. This is an unsigned team development release, not a certified
or publicly deployed product. Earlier PDFs describe the earlier checkpoint.

## What is ready

The per-user NSIS installer contains the owner window, bundled Python/Tk,
`EWasteWorker.exe`, `EWasteAgent.exe`, shared dependencies and a trusted runtime
manifest. A worker laptop does not need Python, Node, a source checkout, pip or
the dataset. Docker Desktop/WSL running Linux amd64 containers is still required.
The coordinator computer continues to run the API, PostgreSQL and dashboard.

Owner controls include offline import/preflight, pairing approval, Start/Stop,
Pause/Resume, diagnostics, explicit Minimize to tray, Open window and Exit.
Closing the window stops participation. Startup is off on fresh installation;
the opt-in **Open app when I sign in** opens the window and requires explicit
Start before jobs run. An administrator's invitation alone never grants consent.
Initial **Approve and start** explicitly grants consent and launches the worker.

The packaged helper requires a paired identity and a reviewed Docker release,
even if inherited environment settings request legacy enrollment or native
execution. CPU/RAM ceilings, pause, protected state and attempt fencing remain
the existing protocol. A crashed owner app causes its helper to cancel and stop.
There is one owner app per Windows account; independent CLI development workers
with separate state directories remain supported.

## Files to share with another laptop

Obtain these from the same trusted team release:

- `output/installers/EWasteGridWorker-0.6.2-Windows-amd64-Setup.exe`.
- `output/installers/release-checksums.json` to identify the actual build.
- `output/runtime/team-offline-v2/images.tar` for offline workload import.
- This guide and `docs/STEP7_PHYSICAL_ACCEPTANCE.md`.

The portable ZIP contains the same app without installer integration. Extract
the entire folder; both EXEs and `_internal` must stay together. Do not copy
someone else's AppData, credentials or virtual environment.

The current archive is **team-offline-v2**, 112,588,288 bytes, SHA-256
`c7a818ccb3788e22c5bdf216c56fdc763bbdb68ff3f431c4247625d4e89f13d7`.
The v1 archive was unavailable in this checkout, so v2 was built and preflighted
from local workload images; it preserves the pinned model/labels. Its immutable
image IDs are recorded in `worker/releases/current.json`, bundled into the app.
A v1 archive does not match the v2 app. Older evidence retains its v1 identity.
Git intentionally excludes installers and large runtime archives: teammates
pulling source need to build or obtain these artifacts separately.

Check transferred files before opening/importing them:

```powershell
Get-FileHash .\EWasteGridWorker-0.6.2-Windows-amd64-Setup.exe -Algorithm SHA256
Get-FileHash .\images.tar -Algorithm SHA256
```

Compare the installer with the team's checksum JSON and the archive with the
value above. Hashes identify artifacts; use a trusted channel to obtain them.

## Using the worker

1. Start Docker Desktop in Linux-container mode. Install the Setup EXE under
   the intended owner's normal Windows account. It installs per-user without
   an administrator requirement and does not enable login startup.
2. Open **E-Waste Grid Worker** from the Start menu. On this coordinator PC use
   `http://127.0.0.1:8080/api`. On another laptop use the coordinator's current
   LAN IP, e.g. `http://10.227.137.147:8080/api` only if that remains its IP.
   Select **Allow HTTP for a trusted local demo network** for LAN HTTP.
3. Choose a unique laptop name and owner-approved CPU/RAM limits. Normal
   dashboard image jobs require 2 GiB admission; choose at least 2 GiB for those
   tests. Docker/WSL overhead is additional to the per-workload ceiling.
4. Click **Import offline workloads**, select v2 `images.tar`, and wait for
   checksum verification, import and real Docker preflight. Cached exact images
   avoid a repeat import. Import/preflight can be cancelled and does not enroll
   a node or run submitted jobs.
5. Click **Prepare connection**, share only the pairing code, and let the grid
   administrator invite that code in the dashboard. Inspect the invitation
   locally, then click **Approve and start**, or Decline.
6. On the coordinator dashboard, upload ten demo photos, choose Image
   classification, set Items per task to 5, and submit. Two tasks should finish.
   Download results and verify every input appears exactly once.
7. Pause stops new assignments while current work drains. Stop cancels owned
   work; interrupted work can be retried. Minimize to tray explicitly keeps the
   app available. Tray Exit or closing the window stops its owned helper.
8. Reopening the app does not compute automatically. Prepare connection to
   validate the saved approval, then explicitly Start. Saved pause is retained.

The output is JSON predictions (class name, class ID, confidence and task ID),
not edited images. This model classifies ImageNet objects; it has not been
trained for wet waste, plastic or electronic-waste categories. The compute
grid could run a separately implemented, validated waste model later.

## Upgrade, uninstall and owned state

Install location: `%LOCALAPPDATA%\Programs\EWasteGridWorker`.
The installer owns this dedicated directory, its marker, Start menu shortcuts
and HKCU uninstall entry. It upgrades only a verified app-owned installation.
Upgrades/uninstall request cooperative shutdown and wait; they never kill
Python/Docker by name. The app verifies process identity and waits for full exit.
Old-version DLL release has a bounded retry before files are replaced.

State remains under `%LOCALAPPDATA%\EWasteGrid`: per-grid identity/settings/logs
and app control/preferences. Identity and private settings use same-account
Windows DPAPI. Same-account upgrades preserve identity, approved limits and
pause. Corrupt/unreadable state is preserved and reported; it does not trigger
silent re-enrollment. Copying state to another account/device is unsupported.

Uninstall through Windows Apps or the Start menu uninstaller. It removes owned
install files/shortcuts/registry and this install's optional login entry. It
retains protected user state and does not revoke the server identity, erase the
database, uninstall Docker or prune shared workload images. Use the grid's
explicit revoke action when access should be withdrawn. Keep another install's
startup entry untouched; disable it through that original install before moving
the app. Unsupported downgrades are not a tested rollback mechanism.

## Rebuilding from source

Build on Windows amd64 with Python 3.12. The compiler is portable and pinned;
`Get-NsisCompiler.ps1` verifies the official NSIS archive and compiler hashes.
Run from the repository root:

```powershell
$compiler = .\scripts\Get-NsisCompiler.ps1
.\scripts\Build-WindowsWorker.ps1 -NsisCompiler $compiler -Python python
```

If `python` is not the intended Python 3.12, supply its absolute executable
path. The script creates `.build/package-venv`, installs all pinned build
dependencies, freezes both EXEs and produces the installer, portable ZIP and
checksum JSON. `BUILD_METADATA.json`, `SOURCE_INPUT_HASHES.json`, dependency
inventory and collected license texts are included. The metadata records the
Git base, local modifications, exact build-input hashes, platform and toolchain.
The checksum JSON identifies the exact local build; rebuilds can have different
hashes. See the latest source checkpoint and evidence in SOFTWARE_COMPLETION.md.

The workflow now includes a Windows package build and downloadable CI artifact.
That newly added job has not run remotely yet; local success is not CI evidence.
Build-only CI also does not certify Docker/WSL or physical-laptop acceptance.

## Local evidence and remaining acceptance

See [current software evidence](SOFTWARE_COMPLETION.md) and
`output/onboarding/remaining-verification.json`. Earlier
`step6-acceptance.md` and `step6-verification.json` retain the 0.6.1 checkpoint.
The automated frozen-helper fixture uses generated loopback API/PostgreSQL
schemas and simulated approvals. It does not borrow owner credentials. A real
installed GUI/tray and upgrade/uninstall are tested separately. Five frozen
workers on one PC prove concurrent task execution and recovery behavior, not
five physical laptops, a speedup benchmark or electrical savings.

Remaining gates: clean Windows without Python/source, another account/device,
real login/reboot startup, approved multi-laptop jobs over LAN, network loss and
active installer operations during transfers/inference/reporting. Low-disk,
unsupported Docker/CPU, damaged-install repair and downgrade behavior also need
release acceptance. Public signing/distribution, AWS deployment and a custom
waste classifier are separate work, not features claimed by this release.

Tool behavior follows the official [PyInstaller runtime documentation](https://pyinstaller.org/en/stable/runtime-information.html),
[frozen subprocess guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)
and [NSIS manual](https://nsis.sourceforge.io/Docs/Chapter4.html).
