"""One optional HKCU login entry. Opening the app never auto-starts computation."""
import os
from pathlib import Path
import subprocess
import sys
from product import APP_ID

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def supported():
    return os.name == 'nt' and bool(getattr(sys, 'frozen', False))


def startup_command():
    if not supported(): raise RuntimeError('Login startup is available in the packaged Windows app.')
    return subprocess.list2cmdline([str(Path(sys.executable).resolve()), '--login-startup'])


def read_entry():
    if os.name != 'nt': return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, kind = winreg.QueryValueEx(key, APP_ID)
            if kind != winreg.REG_SZ: raise RuntimeError('Login startup entry has an unexpected format.')
            return value
    except FileNotFoundError: return None


def is_enabled():
    return supported() and read_entry() == startup_command()


def set_enabled(enabled):
    if not isinstance(enabled, bool): raise ValueError('Startup choice must be boolean')
    command = startup_command()
    current = read_entry()
    if current is not None and current != command:
        raise RuntimeError('Another install owns this startup entry. Disable startup in that install before moving the app.')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        if enabled: winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, command)
        elif current is not None: winreg.DeleteValue(key, APP_ID)
    if is_enabled() != enabled: raise RuntimeError('Windows did not apply the login startup setting.')
