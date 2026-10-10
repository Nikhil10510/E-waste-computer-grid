"""Local real install/upgrade/uninstall with private app state and owned paths.

Refuses to run if this account already has an installed app or its shortcuts.
Does not enable actual login startup or reboot, and preserves owner AppData.
"""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import winreg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from app_lifecycle import running
from state_store import save_state, load_state

KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\EWasteGridWorker'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY):
            raise RuntimeError('An owner installation exists. Use a separate test account.')
    except FileNotFoundError: pass
    shortcuts = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/E-Waste Grid Worker'
    if shortcuts.exists(): raise RuntimeError('Existing owner shortcuts must not be touched.')
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        try:
            winreg.QueryValueEx(key, 'EWasteGridWorker')
            raise RuntimeError('Existing owner login entry must not be touched.')
        except FileNotFoundError: pass
    directory = (ROOT / '.test-data' / ('installer_' + uuid.uuid4().hex)).resolve()
    directory.relative_to(ROOT / '.test-data')
    directory.mkdir(parents=True)
    install = directory / 'App With Spaces'
    local = directory / 'Private AppData'
    control = local / 'EWasteGrid/app'
    state = local / 'EWasteGrid/test-grid'
    env = os.environ.copy(); env['LOCALAPPDATA'] = str(local)
    app = None
    report = {'date': datetime.now(timezone.utc).isoformat(), 'status': 'RUNNING', 'checks': {},
        'installer_sha256': hashlib.sha256(args.installer.read_bytes()).hexdigest(),
        'scope': 'Real same-account Windows installer, upgrade and uninstall; private app state; no clean PC/reboot/another-account claim'}
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], creationflags=subprocess.CREATE_NO_WINDOW)
    def install_with(path):
        # NSIS /D= consumes the remainder and must be the final unquoted option.
        command = subprocess.list2cmdline([str(path.resolve()), '/S']) + ' /D=' + str(install)
        result = subprocess.run(command, env=env, timeout=120)
        if result.returncode: raise RuntimeError(f'Installer failed with code {result.returncode}')
    def launch():
        process = subprocess.Popen([str(install / 'EWasteWorker.exe'), '--api-url', 'https://installer-test.invalid/api',
            '--state-directory', str(state)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while not running(control):
            if process.poll() is not None or time.monotonic() > deadline: raise RuntimeError('Installed GUI did not open')
            time.sleep(0.1)
        return process
    def uninstall():
        # _?= runs synchronously from this verified fixture installation.
        exe = install / 'Uninstall.exe'
        if not exe.exists(): return
        if (install / '.ewaste-install-id').read_text() != 'EWasteGridWorker':
            raise RuntimeError('Refusing unverified install cleanup')
        command = subprocess.list2cmdline([str(exe), '/S']) + ' _?=' + str(install)
        result = subprocess.run(command, env=env, timeout=120)
        if result.returncode: raise RuntimeError(f'Uninstaller failed with code {result.returncode}')
        # Direct _?= mode cannot remove its own executable while it is running.
        # After its owned process exits, remove just that known test artifact.
        if exe.exists() and not (install / '.ewaste-install-id').exists():
            exe.unlink()
            if not any(install.iterdir()): install.rmdir()
    try:
        install_with(args.previous)
        report['checks']['previous_real_release_installed_in_path_with_spaces'] = True
        identity = {'node_id': str(uuid.uuid4()), 'node_secret': uuid.uuid4().hex + uuid.uuid4().hex,
            'control_plane_url': 'https://installer-test.invalid/api', 'enrollment_mode': 'paired',
            'resource_limits': {'cpu': 0.5, 'memory_gb': 1.0}, 'paused': True}
        save_state(state / 'credentials.json', identity)
        protected_bytes = (state / 'credentials.json').read_bytes()
        app = launch()
        install_with(args.installer)
        app.wait(timeout=10)
        assert not running(control)
        assert (state / 'credentials.json').read_bytes() == protected_bytes and load_state(state / 'credentials.json') == identity
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            report['installed_version'] = winreg.QueryValueEx(key, 'DisplayVersion')[0]
            assert Path(winreg.QueryValueEx(key, 'InstallLocation')[0]) == install
        assert (install / 'EWasteAgent.exe').is_file() and (install / '_internal/releases/current.json').is_file()
        report['checks']['upgrade_gracefully_closes_existing_gui'] = True
        report['checks']['upgrade_preserves_dpapi_identity_limits_and_pause_byte_for_byte'] = True
        smoke = directory / 'installed-gui-smoke.json'
        process = subprocess.run([str(install / 'EWasteWorker.exe'), '--smoke-test', '--report', str(smoke)],
            env=env, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode == 0 and json.loads(smoke.read_text())['status'] == 'PASSED'
        report['gui_sha256'] = hashlib.sha256((install/'EWasteWorker.exe').read_bytes()).hexdigest()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.with_name(args.report.stem + '-gui-smoke.json').write_text(smoke.read_text(), encoding='utf-8')
        report['checks']['installed_frozen_gui_and_tray_smoke'] = True
        app = launch()
        uninstall()
        app.wait(timeout=10)
        assert not running(control) and not (install / 'EWasteWorker.exe').exists()
        assert not (install / 'EWasteAgent.exe').exists() and not (install / '_internal').exists()
        assert not shortcuts.exists()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY): raise AssertionError('Uninstall key remains')
        except FileNotFoundError: pass
        assert load_state(state / 'credentials.json') == identity
        report['checks']['uninstall_closes_gui_and_removes_owned_files_shortcuts_registry'] = True
        report['checks']['uninstall_retains_protected_user_state'] = True
        assert unrelated.poll() is None
        report['checks']['unrelated_owned_test_process_survives_install_upgrade_uninstall'] = True
        report['status'] = 'PASSED'
    finally:
        if app and app.poll() is None:
            subprocess.run([str(install / 'EWasteWorker.exe'), '--shutdown'], env=env, timeout=70)
            app.wait(timeout=10)
        if (install / 'Uninstall.exe').exists(): uninstall()
        if unrelated.poll() is None: unrelated.terminate(); unrelated.wait(timeout=10)
        if report['status'] != 'PASSED': report['status'] = 'FAILED'
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(args.report)}))


if __name__ == '__main__': main()
