"""Windows tray callbacks publish actions; only Tk's thread touches the UI."""
import os
import threading


class TrayControl:
    def __init__(self, events):
        self.events, self.icon = events, None
        self.thread = None
        self.snapshot = {'start': False, 'stop': False, 'pause': False, 'paused': False, 'status': 'Ready'}

    def start(self):
        if os.name != 'nt': raise RuntimeError('System tray is supported on Windows in this release.')
        if self.thread and self.thread.is_alive():
            self.events.put(('tray-ready', None, None)); return
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new('RGBA', (64, 64), '#123448')
        draw = ImageDraw.Draw(image)
        for x, y in ((10, 12), (36, 12), (23, 37)):
            draw.rounded_rectangle((x, y, x + 18, y + 16), radius=3, fill='#13b896')
        def action(name):
            return lambda icon, item: self.events.put(('tray-action', name, None))
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self.snapshot['status'], None, enabled=False),
            pystray.MenuItem('Open window', action('open'), default=True),
            pystray.MenuItem('Start worker', action('start'), enabled=lambda item: self.snapshot['start']),
            pystray.MenuItem('Stop worker', action('stop'), enabled=lambda item: self.snapshot['stop']),
            pystray.MenuItem(lambda item: 'Resume worker' if self.snapshot['paused'] else 'Pause worker',
                            action('pause'), enabled=lambda item: self.snapshot['pause']),
            pystray.MenuItem('Exit and stop worker', action('exit')))
        self.icon = pystray.Icon('EWasteGridWorker', image, 'E-Waste Grid Worker', menu)
        icon, events = self.icon, self.events
        def setup(icon):
            icon.visible = True
            events.put(('tray-ready', None, None))
        def run():
            try: icon.run(setup=setup)
            except Exception as error: events.put(('tray-failed', None, error))
        self.thread = threading.Thread(target=run, name='ewaste-tray', daemon=True)
        self.thread.start()

    def update(self, snapshot):
        changed = snapshot != self.snapshot
        self.snapshot = snapshot.copy()
        if changed and self.icon and self.icon.visible: self.icon.update_menu()

    def stop(self):
        if self.icon: self.icon.stop()
        if self.thread: self.thread.join(timeout=2)
        self.icon = None
