# Two entry points sharing one read-only dependency directory.
from pathlib import Path
root = Path(SPECPATH).resolve().parents[1]
worker = root / 'worker'
assets = [(str(worker / 'releases/current.json'), 'releases'),
          (str(root / 'packaging/windows/NOTICE.txt'), '.')]
gui = Analysis([str(root / 'packaging/windows/desktop_entry.py')], pathex=[str(worker)],
    datas=assets, hiddenimports=['pystray._win32'], excludes=['onnxruntime', 'numpy', 'pytest', 'reportlab'])
agent = Analysis([str(root / 'packaging/windows/agent_entry.py')], pathex=[str(worker)],
    datas=assets, excludes=['tkinter', 'pystray', 'onnxruntime', 'numpy', 'pytest', 'reportlab'])
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True,
    name='EWasteWorker', console=False, uac_admin=False)
agent_exe = EXE(PYZ(agent.pure), agent.scripts, [], exclude_binaries=True,
    name='EWasteAgent', console=True, uac_admin=False)
bundle = COLLECT(gui_exe, agent_exe, gui.binaries, agent.binaries, gui.datas, agent.datas,
    strip=False, upx=False, name='EWasteGridWorker')
