"""Same-user desktop instance guard and cooperative show/shutdown requests.

    Never kill processes. Shutdown waits for the locked owner's verified
    executable/PID/start time after owned helper/background work has stopped.
"""
from contextlib import contextmanager
import os
import json
from pathlib import Path
import sys
import time
import psutil


def control_directory():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'EWasteGrid' / 'app'


class AppAlreadyRunning(RuntimeError):
    pass


@contextmanager
def instance_lock(directory, record_owner=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / 'instance.lock').open('a+b')
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                if not handle.read(1): handle.write(b'0'); handle.flush()
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AppAlreadyRunning('The worker app is already open.') from None
        if record_owner:
            owner = {'pid': os.getpid(), 'created': psutil.Process().create_time(),
                'executable': str(Path(psutil.Process().exe()).resolve())}
            (directory / 'owner.json').write_text(json.dumps(owner), encoding='utf-8')
        yield
    finally: handle.close()


def running(directory):
    try:
        with instance_lock(directory): return False
    except AppAlreadyRunning: return True


def request(directory, action):
    if action not in ('show', 'shutdown'): raise ValueError('Unknown app action')
    directory = Path(directory)
    if not running(directory): return False
    (directory / (action + '.request')).write_text(action, encoding='ascii')
    return True


def shutdown_app(directory, timeout=60):
    directory = Path(directory)
    owner = None
    if running(directory) and (directory / 'owner.json').exists():
        try:
            saved = json.loads((directory / 'owner.json').read_text(encoding='utf-8'))
            if Path(saved['executable']).resolve() != Path(psutil.Process().exe()).resolve(): return False
            owner = psutil.Process(saved['pid'])
            if abs(owner.create_time() - saved['created']) > 0.01: return False
            if Path(owner.exe()).resolve() != Path(saved['executable']).resolve(): return False
        except psutil.NoSuchProcess: owner = None
        except (OSError, ValueError, KeyError, TypeError, psutil.Error): return False
    if not request(directory, 'shutdown'): return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not running(directory):
            if owner:
                try: owner.wait(timeout=max(0.01, deadline - time.monotonic()))
                except psutil.TimeoutExpired: return False
            return True
        time.sleep(0.1)
    return False
