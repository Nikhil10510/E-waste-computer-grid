"""Atomic local state; Windows DPAPI current-user protection, POSIX mode 0600.

Windows never falls back to plaintext. Legacy JSON migrates only after a
successful encrypted replacement. Unreadable state must not trigger enrollment.
"""
import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading
import time
import uuid

WINDOWS = os.name == 'nt'
_LOCK = threading.RLock()
_FORMAT = 'ewaste-protected-state'


class StateError(ValueError):
    pass


def _crypt(raw, decrypt=False):
    if not WINDOWS: raise StateError('Windows protected state requires the original Windows account')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    # UI_FORBIDDEN only: never LOCAL_MACHINE, which would allow other accounts.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise StateError('Cannot unlock/save protected state. Use the original Windows account; do not copy worker state between laptops.')
    try: return ctypes.string_at(output.data, output.size)
    finally: kernel.LocalFree(output.data)


@contextmanager
def _file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_name(path.name + '.lock').open('a+b') as handle:
        deadline = time.monotonic() + 5
        while True:
            try:
                if WINDOWS:
                    import msvcrt
                    handle.seek(0)
                    if not handle.read(1): handle.write(b'0'); handle.flush()
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    os.chmod(handle.name, 0o600)
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline: raise StateError('Saved state is busy. Wait for the other operation and retry.')
                time.sleep(0.05)
        try: yield
        finally:
            if WINDOWS:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle, fcntl.LOCK_UN)


def _read(path):
    try:
        if path.stat().st_size > 65536: raise StateError('Saved state exceeds its size limit. Keep this file for recovery.')
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict): raise ValueError('Expected state object')
        protected = data.get('format') == _FORMAT
        if not protected and any(key in data for key in ('format', 'protection', 'payload')):
            raise StateError('Unsupported or damaged protected-state envelope. Keep this file for recovery.')
        if protected:
            if data.get('version') != 1 or data.get('protection') != 'windows-dpapi-user':
                raise StateError('Unsupported protected-state version. Keep this file and use a compatible worker.')
            data = json.loads(_crypt(base64.b64decode(data['payload'], validate=True), True))
            if not isinstance(data, dict): raise ValueError('Expected state object')
        return data, protected
    except StateError: raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StateError('Saved state is unreadable. Keep it for recovery; no new worker was enrolled.') from error


def _write(path, value):
    if not isinstance(value, dict): raise StateError('State must be an object')
    raw = json.dumps(value, allow_nan=False).encode('utf-8')
    if WINDOWS:
        raw = json.dumps({'format': _FORMAT, 'version': 1, 'protection': 'windows-dpapi-user',
                          'payload': base64.b64encode(_crypt(raw)).decode('ascii')}).encode('utf-8')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            if not WINDOWS: os.chmod(temporary, 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)


def load_state(path, migrate=True):
    path = Path(path)
    with _file_lock(path):
        data, protected = _read(path)
        if migrate and WINDOWS and not protected: _write(path, data)
        elif not WINDOWS: os.chmod(path, 0o600)
        return data


def save_state(path, value):
    path = Path(path)
    with _file_lock(path): _write(path, value)


def update_state(path, changes):
    path = Path(path)
    with _file_lock(path):
        saved = _read(path)[0] if path.exists() else {}
        saved.update(changes)
        _write(path, saved)
        return saved
