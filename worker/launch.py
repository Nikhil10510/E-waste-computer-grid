"""Trusted source/frozen helper selection, independent of working directory."""
from pathlib import Path
import os
import sys


def desktop_command(*arguments):
    if getattr(sys, 'frozen', False): return [sys.executable, *arguments]
    return [sys.executable, str(Path(__file__).with_name('desktop.py').resolve()), *arguments]


def agent_command(*arguments):
    if getattr(sys, 'frozen', False):
        helper = Path(sys.executable).resolve().with_name('EWasteAgent.exe')
        if not helper.is_file():
            raise RuntimeError('Bundled worker helper is missing. Repair the installation; no worker was started.')
        return [str(helper), *arguments]
    return [sys.executable, str(Path(__file__).with_name('agent.py').resolve()), *arguments]


def prepare_external_programs():
    """The GUI/helper need their Python DLLs; Docker needs the system search path.

    Call after importing native Python dependencies on Windows. Both bundle
    executables have their own bootloader and establish their own DLL paths.
    """
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
