"""Build a source desktop handoff; this is not an installer or Python runtime."""
import hashlib
import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [f'worker/{name}' for name in ['agent.py', 'api_client.py', 'config.py', 'desktop.py',
    'desktop_runtime.py', 'hardware.py', 'log_safety.py', 'pairing_client.py', 'requirements.txt',
    'resource_limits.py', 'runtime_release.py', 'state_store.py', 'task_executor.py', 'releases/current.json']]
FILES += [f'worker/{name}' for name in ['product.py', 'launch.py', 'app_lifecycle.py', 'windows_startup.py', 'tray_control.py', 'package_checks.py']]
README = '''E-Waste Grid - Step 6 source desktop preview

This bundle contains reviewed source and the trusted offline release manifest.
It contains no private settings, credentials, virtual environment, coordinator,
installer or automatic startup. Python 3.12 with Tkinter remains a prerequisite.
Docker Desktop must be running in Linux-container mode on a supported amd64 PC.
Do not build workload images on this laptop: copy the separate images.tar file.

Extract this ZIP into a new directory. In PowerShell in that directory, run:
  py -3.12 -m venv .venv
  .\\.venv\\Scripts\\python.exe -m pip install -r worker\\requirements.txt
  .\\.venv\\Scripts\\python.exe worker\\desktop.py
Dependency setup may need the internet once. The image import itself is offline.

In the app:
1. Enter the coordinator's API URL. localhost points to THIS laptop; use the
   coordinator's actual LAN IP and port. Select trusted-demo HTTP only for LAN.
2. Choose owner-approved CPU/RAM ceilings. Normal image jobs need 2 GiB RAM.
3. Click Import offline workloads and select the team's images.tar.
4. Wait for archive verification, import and real Docker preflight. Cancellation
   never starts a worker; Docker may retain content already imported.
5. Click Prepare connection; share only the pairing code with the grid admin.
6. Inspect and approve the invitation on this laptop to start computing.
7. Pause/Resume/Stop remain owner controls. Closing waits for owned work to stop.

Keep the trusted current.json from this reviewed source bundle. Replacing the
archive AND manifest removes the trust check; checksums alone are not publisher
authentication. Use the checksum supplied by the team through a trusted channel.
Check SHA-256 with Get-FileHash before opening a replacement source ZIP.

Record OS/Docker version, import result, node ID and a ten-photo job with two
accepted tasks and exact downloaded results. Never share pairing/node secrets,
protected per-user state, admin tokens or full unreviewed logs. Installer/reboot
and multi-device fault testing remain physical acceptance milestones. A separate
Step 6 frozen installer is now available; this ZIP is the Python source preview,
not that installer or the full development repository. No cloud deployment here.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/handoff/E_Waste_Desktop_Worker_Step6_Source.zip')
    output = parser.parse_args().output
    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = {}
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            raw = (ROOT / name).read_bytes()
            bundle.writestr(name, raw)
            inventory[name] = hashlib.sha256(raw).hexdigest()
        bundle.writestr('READ_ME_FIRST.txt', README)
        bundle.writestr('source-checksums.json', json.dumps(inventory, indent=2))
    with zipfile.ZipFile(output) as bundle:
        assert bundle.testzip() is None
        for name, checksum in inventory.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == checksum
        assert len(bundle.namelist()) == len(FILES) + 2
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(checksum + '\n', encoding='ascii')
    print(json.dumps({'bundle': str(output), 'files': len(FILES), 'sha256': checksum, 'installer': False}))


if __name__ == '__main__': main()
