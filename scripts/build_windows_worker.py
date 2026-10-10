"""Build an unsigned per-user Windows package using a portable NSIS compiler."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from product import VERSION


def checksum(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nsis', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/installers')
    args = parser.parse_args()
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('Build on Windows amd64 with Python 3.12')
    if sys.version_info[:2] != (3, 12): raise RuntimeError('Use Python 3.12 for this release')
    nsis = args.nsis.resolve()
    if not nsis.is_file(): raise ValueError('Supply the portable makensis.exe path')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    work = ROOT / '.build/windows'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(work / 'dist'), '--workpath', str(work / 'work'),
        str(ROOT / 'packaging/windows/worker.spec')], cwd=ROOT, check=True)
    bundle = work / 'dist/EWasteGridWorker'
    inventory = []
    notice_dir = bundle / 'third_party_notices'; notice_dir.mkdir(exist_ok=True)
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        inventory.append({'name': name, 'version': distribution.version,
            'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License', ''),
            'homepage': distribution.metadata.get('Home-page', '')})
        for relative in distribution.files or []:
            if ('license' in str(relative).lower() or Path(relative).name.lower().startswith(('copying', 'notice'))):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    target = notice_dir / name / str(relative).replace('..', '_').replace(':', '_')
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file(): shutil.copyfile(python_license, notice_dir / 'PYTHON_LICENSE.txt')
    (bundle / 'THIRD_PARTY_INVENTORY.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    compiler_version = subprocess.check_output([str(nsis), '/VERSION'], text=True).strip()
    inputs = [p for folder in ('worker', 'packaging/windows') for p in (ROOT/folder).rglob('*')
        if p.is_file() and (p.suffix in ('.py', '.spec', '.nsi', '.txt') or p == ROOT/'worker/releases/current.json')
        and not any(part.startswith('.') or part in ('__pycache__', 'tests') for part in p.relative_to(ROOT).parts)]
    inputs += [Path(__file__), ROOT/'scripts/Build-WindowsWorker.ps1']
    source_hashes = {p.relative_to(ROOT).as_posix(): checksum(p) for p in sorted(inputs)}
    (bundle / 'SOURCE_INPUT_HASHES.json').write_text(json.dumps(source_hashes, indent=2), encoding='utf-8')
    build = {'version': VERSION, 'built_at_utc': datetime.now(timezone.utc).isoformat(),
        'platform': platform.platform(), 'python': platform.python_version(), 'nsis': compiler_version,
        'pyinstaller': metadata.version('PyInstaller'), 'unsigned_development_release': True,
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_has_changes': bool(subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT, text=True)),
        'source_input_sha256': hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest(),
        'release_manifest_sha256': checksum(ROOT / 'worker/releases/current.json')}
    (bundle / 'BUILD_METADATA.json').write_text(json.dumps(build, indent=2), encoding='utf-8')
    installer = output / f'EWasteGridWorker-{VERSION}-Windows-amd64-Setup.exe'
    subprocess.run([str(nsis), f'/DAPP_VERSION={VERSION}', f'/DBUNDLE_DIR={bundle}',
        f'/DOUTPUT_FILE={installer}', str(ROOT / 'packaging/windows/worker.nsi')], check=True)
    portable = output / f'EWasteGridWorker-{VERSION}-Windows-amd64-Portable.zip'
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file(): archive.write(path, Path(bundle.name) / path.relative_to(bundle))
    artifacts = {path.name: {'bytes': path.stat().st_size, 'sha256': checksum(path)} for path in (installer, portable)}
    (output / 'release-checksums.json').write_text(json.dumps({'build': build, 'artifacts': artifacts}, indent=2), encoding='utf-8')
    print(json.dumps({'installer': str(installer), 'portable': str(portable), 'build': build}, indent=2))


if __name__ == '__main__': main()
