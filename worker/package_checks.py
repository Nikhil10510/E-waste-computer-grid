"""Explicit local GUI smoke check. No pairing, jobs, startup entry or owner state.

    Registry writes use a fresh private test key, never the Windows login key.
    This verifies a real frozen Tk/tray process, not another physical laptop.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def gui_smoke(control, report):
    import tkinter as tk
    from desktop import WorkerWindow
    from launch import desktop_command
    import windows_startup
    checks = {}
    root = None
    try:
        with tempfile.TemporaryDirectory(prefix='ewaste-packaged-smoke-') as temp:
            root = tk.Tk(); root.withdraw()
            window = WorkerWindow(root, 'https://packaged-smoke.invalid/api', False, Path(temp), control)
            def until(condition, timeout=15):
                deadline = time.monotonic() + timeout
                while not condition():
                    root.update()
                    if time.monotonic() > deadline: raise TimeoutError('Packaged GUI smoke check timed out')
                    time.sleep(0.01)
            checks['tk_widgets_and_bundled_tcl'] = bool(window.start_button.winfo_exists())
            checks['no_approval_no_agent_no_identity'] = window.runtime is None and not (Path(temp)/'credentials.json').exists()
            window.tray_button.invoke()
            until(lambda: not window.minimizing)
            if not window.tray.icon or not window.tray.icon.visible:
                raise RuntimeError('Real Windows tray did not become visible')
            checks['real_tray_hides_window_after_ready'] = root.state() == 'withdrawn'
            duplicate = subprocess.Popen(desktop_command('--control-directory', str(control)),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if duplicate.wait(timeout=15) != 0: raise RuntimeError('Duplicate app launch failed')
            until(lambda: root.state() == 'normal')
            checks['duplicate_launch_restores_same_window'] = True
            if os.name == 'nt' and windows_startup.supported():
                import winreg
                previous = windows_startup.KEY
                key = r'Software\EWasteGridPackageTest_' + uuid.uuid4().hex
                try:
                    windows_startup.KEY = key
                    window.startup_enabled.set(False); window.startup_box.invoke()
                    if not windows_startup.is_enabled(): raise RuntimeError('Startup enable readback failed')
                    window.startup_box.invoke()
                    if windows_startup.is_enabled(): raise RuntimeError('Startup disable readback failed')
                    checks['startup_toggle_on_isolated_registry_key'] = True
                finally:
                    windows_startup.KEY = previous
                    try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                    except FileNotFoundError: pass
            window.events.put(('tray-action', 'exit', None))
            until(lambda: window.closing)
            checks['tray_exit_stops_icon_without_computing'] = window.tray.icon is None and window.runtime is None
            root = None
        if not all(checks.values()): raise RuntimeError('A packaged GUI smoke check failed')
        data = {'status': 'PASSED', 'checks': checks,
            'scope': 'Real local Tk/tray and duplicate process, isolated startup key; no physical laptop/reboot/owner approval claim'}
    except Exception as error:
        from log_safety import safe_text
        data = {'status': 'FAILED', 'checks': checks, 'error': safe_text(error)}
    finally:
        if root:
            try: window.tray.stop(); root.destroy()
            except tk.TclError: pass
    report = Path(report); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return 0 if data['status'] == 'PASSED' else 1
