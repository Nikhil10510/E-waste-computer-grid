"""Windows approval UI around the existing worker; run from source for step 2."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from api_client import APIError
from desktop_runtime import DesktopRuntime
from hardware import get_hardware_specs
from pairing_client import PairingClient, normalize_api_url, state_directory
from resource_limits import validate_limits


@contextmanager
def desktop_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / 'desktop.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            if not handle.read(1): handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('Another worker app already uses this grid. Close it before opening another.')
    try: yield
    finally: handle.close()


class WorkerWindow:
    def __init__(self, root, api_url='', allow_http=False, directory=None):
        self.root, self.directory_override = root, directory
        self.events = queue.Queue()
        self.client = self.runtime = None
        self.lock_context = None
        self.busy, self.closing, self.approved, self.stopping = False, False, False, False
        self.poll_delay = 3000
        self.poll_timer = None
        self.popup = None
        self.popup_buttons = []
        self.paused = False
        root.title('E-Waste Grid Worker')
        root.geometry('740x760'); root.minsize(720, 740)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        if 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('TFrame', background='#f5f8fa')
        style.configure('TLabel', background='#f5f8fa', foreground='#243746', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 21, 'bold'), foreground='#123448')
        style.configure('TButton', font=('Segoe UI', 10), padding=(12, 7))
        panel = ttk.Frame(root, padding=26); panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='Contribute this laptop', style='Title.TLabel').pack(anchor='w')
        ttk.Label(panel, text='Approve a grid invitation before any computing starts.').pack(anchor='w', pady=(5, 20))
        ttk.Label(panel, text='Grid API address').pack(anchor='w')
        self.url = tk.StringVar(value=api_url)
        self.address = ttk.Entry(panel, textvariable=self.url, font=('Segoe UI', 11)); self.address.pack(fill='x', pady=(4, 8))
        self.allow_http = tk.BooleanVar(value=allow_http)
        self.http_box = ttk.Checkbutton(panel, text='Allow HTTP for a trusted local demo network', variable=self.allow_http)
        self.http_box.pack(anchor='w')
        ttk.Label(panel, text='Laptop name').pack(anchor='w', pady=(12, 0))
        self.name = tk.StringVar(value=os.environ.get('COMPUTERNAME', 'Retired laptop'))
        self.name_entry = ttk.Entry(panel, textvariable=self.name); self.name_entry.pack(fill='x', pady=(4, 10))
        hardware = get_hardware_specs(['dummy'])
        self.cpu_value = tk.StringVar(value=format(min(2, hardware['cpu_cores']), 'g'))
        self.memory_value = tk.StringVar(value=format(min(2, hardware['ram_gb']), 'g'))
        limits_row = ttk.Frame(panel); limits_row.pack(fill='x', pady=(0, 10))
        ttk.Label(limits_row, text='CPU limit').pack(side='left')
        self.cpu_input = ttk.Spinbox(limits_row, from_=0.25, to=min(64, hardware['cpu_cores']), increment=0.25, width=7, textvariable=self.cpu_value)
        self.cpu_input.pack(side='left', padx=(8, 22))
        ttk.Label(limits_row, text='RAM limit (GiB)').pack(side='left')
        self.memory_input = ttk.Spinbox(limits_row, from_=0.25, to=hardware['ram_gb'], increment=0.25, width=7, textvariable=self.memory_value)
        self.memory_input.pack(side='left', padx=8)
        self.prepare_button = ttk.Button(panel, text='Prepare connection', command=self.prepare); self.prepare_button.pack(anchor='w')
        ttk.Separator(panel).pack(fill='x', pady=17)
        self.code = tk.StringVar(value='No pairing code yet')
        ttk.Label(panel, text='Share only this code with the grid administrator:').pack(anchor='w')
        self.code_entry = ttk.Entry(panel, textvariable=self.code, state='readonly', font=('Consolas', 19))
        self.code_entry.pack(fill='x', pady=(6, 8))
        ttk.Button(panel, text='Copy pairing code', command=self.copy_code).pack(anchor='w')
        self.status = tk.StringVar(value='Enter your grid address. Docker and approved images must be available.')
        ttk.Label(panel, textvariable=self.status, wraplength=660).pack(anchor='w', pady=(16, 10))
        row = ttk.Frame(panel); row.pack(fill='x')
        self.start_button = ttk.Button(row, text='Start worker', command=self.start, state='disabled'); self.start_button.pack(side='left')
        self.stop_button = ttk.Button(row, text='Stop worker', command=self.stop, state='disabled'); self.stop_button.pack(side='left', padx=8)
        self.pause_button = ttk.Button(row, text='Pause worker', command=self.toggle_pause, state='disabled'); self.pause_button.pack(side='left')
        connection_row = ttk.Frame(panel); connection_row.pack(fill='x', pady=(8, 0))
        self.retry_button = ttk.Button(connection_row, text='Check invitation again', command=self.poll, state='disabled'); self.retry_button.pack(side='left')
        ttk.Button(connection_row, text='Change grid', command=self.reset_connection).pack(side='left', padx=8)
        self.policy = tk.StringVar(value='Choose limits before pairing. Docker enforces the workload ceilings.')
        ttk.Label(panel, textvariable=self.policy, wraplength=660).pack(anchor='w', pady=(12, 0))
        ttk.Label(panel, text='Approved workloads: image classification and pipeline demo.\nSource preview: installer and protected storage are still pending.', wraplength=660).pack(anchor='w', pady=(6, 0))
        root.after(100, self.drain_events)

    def background(self, name, work):
        if self.busy or self.closing: return
        self.busy = True
        self.prepare_button.configure(state='disabled')
        self.retry_button.configure(state='disabled')
        self.pause_button.configure(state='disabled')
        for button in self.popup_buttons: button.configure(state='disabled')
        def run():
            try: self.events.put((name, work(), None))
            except Exception as error: self.events.put((name, None, error))
        threading.Thread(target=run, daemon=True).start()

    def prepare(self):
        if self.busy or self.closing: return
        try:
            url = normalize_api_url(self.url.get(), self.allow_http.get())
            name = self.name.get().strip()
            if not name or len(name) > 200: raise ValueError('Enter a laptop name of 1-200 characters')
            hardware = get_hardware_specs(['dummy'])
            limits = validate_limits({'cpu': float(self.cpu_value.get()), 'memory_gb': float(self.memory_value.get())}, hardware['cpu_cores'], hardware['ram_gb'])
            directory = Path(self.directory_override) if self.directory_override else state_directory(url)
            if self.lock_context is None:
                self.lock_context = desktop_lock(directory)
                try: self.lock_context.__enter__()
                except Exception: self.lock_context = None; raise
            self.client = PairingClient(url, directory, self.allow_http.get())
            self.runtime = DesktopRuntime(url, directory, name, limits)
            self.address.configure(state='disabled'); self.http_box.configure(state='disabled'); self.name_entry.configure(state='disabled')
            self.cpu_input.configure(state='disabled'); self.memory_input.configure(state='disabled')
            self.status.set('Checking Docker and the approved workload runtimes...')
            self.approved = False
            def prepare_connection():
                identity = self.client.saved_identity()
                saved_policy = identity.get('resource_limits') if identity else self.client.session.get('resource_limits') if self.client.session else limits
                saved_policy = saved_policy or {'cpu': min(2, hardware['cpu_cores']), 'memory_gb': min(2, hardware['ram_gb'])}
                self.runtime.limits = validate_limits({'cpu': min(saved_policy['cpu'], hardware['cpu_cores']),
                    'memory_gb': min(saved_policy['memory_gb'], hardware['ram_gb'])})
                capabilities = self.runtime.preflight()
                if identity: return ('identity', identity)
                if self.client.session: return ('session', self.client.session)
                reported = get_hardware_specs(capabilities); reported['name'] = name
                return ('session', self.client.begin(reported, self.runtime.limits))
            self.background('prepare', prepare_connection)
        except Exception as error: self.status.set(str(error))

    def copy_code(self):
        if self.client and self.client.session:
            self.root.clipboard_clear(); self.root.clipboard_append(self.client.session['pairing_code'])

    def schedule_poll(self, delay):
        if self.poll_timer: self.root.after_cancel(self.poll_timer)
        self.poll_timer = self.root.after(delay, self.poll)

    def poll(self):
        if self.poll_timer: self.root.after_cancel(self.poll_timer); self.poll_timer = None
        if self.client and self.client.session and not self.busy:
            self.background('poll', self.client.poll)

    def reset_connection(self):
        if self.busy or self.closing or (self.runtime and self.runtime.running()):
            self.status.set('Finish the current operation and stop the worker before changing grids.')
            return
        if self.poll_timer: self.root.after_cancel(self.poll_timer); self.poll_timer = None
        self.hide_invitation()
        if self.lock_context: self.lock_context.__exit__(None, None, None); self.lock_context = None
        self.client = self.runtime = None; self.approved = False
        self.code.set('No pairing code yet')
        self.address.configure(state='normal'); self.http_box.configure(state='normal'); self.name_entry.configure(state='normal')
        self.cpu_input.configure(state='normal'); self.memory_input.configure(state='normal')
        self.prepare_button.configure(state='normal'); self.start_button.configure(state='disabled'); self.stop_button.configure(state='disabled'); self.retry_button.configure(state='disabled')
        self.pause_button.configure(state='disabled')
        self.status.set('Enter the trusted API address for the grid you want to join.')

    def show_invitation(self, data):
        if self.popup is not None: return
        self.popup = tk.Toplevel(self.root)
        self.popup.title('Approve grid invitation')
        self.popup.geometry('560x320'); self.popup.minsize(560, 320)
        self.popup.transient(self.root); self.popup.grab_set()
        self.popup.protocol('WM_DELETE_WINDOW', lambda: self.decide(False))
        body = ttk.Frame(self.popup, padding=24); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Join this compute grid?', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(body, text=f"{data['grid_name']}\n{self.client.api_url}", wraplength=500).pack(anchor='w', pady=12)
        limits = self.runtime.limits
        ttk.Label(body, text=f"Approval starts approved computing workloads on this laptop.\nEach workload is capped at {limits['cpu']:g} CPU equivalents and {limits['memory_gb']:g} GiB RAM.\nYou can pause or stop the worker at any time.", wraplength=500).pack(anchor='w', pady=(0, 16))
        row = ttk.Frame(body); row.pack(anchor='w')
        approve = ttk.Button(row, text='Approve and start', command=lambda: self.decide(True)); approve.pack(side='left')
        decline = ttk.Button(row, text='Decline', command=lambda: self.decide(False)); decline.pack(side='left', padx=10)
        self.popup_buttons = [approve, decline]

    def hide_invitation(self):
        if self.popup is not None:
            self.popup.destroy(); self.popup = None; self.popup_buttons = []

    def decide(self, approve):
        self.status.set('Saving owner decision with the grid...')
        self.background('approve' if approve else 'decline', lambda: self.client.decide(approve))

    def start(self):
        if not self.approved or self.closing or self.busy: return
        try:
            self.runtime.start()
            self.start_button.configure(state='disabled'); self.stop_button.configure(state='normal')
            self.pause_button.configure(state='normal')
            self.status.set('Worker process running in paused mode. Resume when ready.' if self.paused else 'Worker process running. View task progress in the grid dashboard.')
        except Exception as error: self.status.set(str(error))

    def stop(self):
        if self.runtime and self.runtime.running():
            self.stopping = True; self.runtime.request_stop()
            self.stop_button.configure(state='disabled'); self.start_button.configure(state='disabled')
            self.status.set('Stopping the worker safely. Waiting for any active network request to finish...')

    def toggle_pause(self):
        if not self.approved or self.busy or self.closing: return
        self.status.set('Updating participation with the grid...')
        self.background('participation', lambda: self.client.set_paused(not self.paused))

    def display_policy(self):
        limits = self.runtime.limits
        self.cpu_value.set(format(limits['cpu'], 'g')); self.memory_value.set(format(limits['memory_gb'], 'g'))
        self.policy.set(f"Workload ceilings: {limits['cpu']:g} CPU equivalents / {limits['memory_gb']:g} GiB RAM.\nSaved approval keeps these limits when this app restarts.")

    def close(self):
        self.closing = True
        self.hide_invitation()
        if self.runtime and self.runtime.running(): self.stop()
        elif self.busy: self.status.set('Closing safely. Waiting for the current runtime check or network request...')
        else: self.finish_close()

    def finish_close(self):
        if self.lock_context: self.lock_context.__exit__(None, None, None); self.lock_context = None
        self.root.destroy()

    def drain_events(self):
        if self.closing:
            try:
                while True:
                    self.events.get_nowait(); self.busy = False
            except queue.Empty: pass
            if self.busy or (self.runtime and self.runtime.running()): self.root.after(200, self.drain_events)
            else: self.finish_close()
            return
        try:
            while True:
                name, result, error = self.events.get_nowait()
                self.busy = False
                for button in self.popup_buttons: button.configure(state='normal')
                if error:
                    self.status.set(str(error)); self.poll_delay = min(30000, self.poll_delay * 2)
                    if isinstance(error, APIError) and error.status in (401, 403, 410):
                        self.hide_invitation(); self.approved = False; self.start_button.configure(state='disabled')
                    if self.client and self.client.session: self.retry_button.configure(state='normal')
                    else: self.prepare_button.configure(state='normal')
                elif name == 'prepare':
                    kind, data = result
                    self.display_policy()
                    if kind == 'identity':
                        self.approved = True; self.start_button.configure(state='normal')
                        self.paused = data.get('paused', False)
                        self.pause_button.configure(text='Resume worker' if self.paused else 'Pause worker', state='normal')
                        self.code.set('Already approved')
                        self.status.set('This laptop has a saved approved identity. Click Start worker to participate.')
                    else:
                        self.code.set(data['pairing_code'])
                        self.status.set('Share the code with your grid administrator. No computing starts before approval.')
                        self.retry_button.configure(state='normal')
                        self.schedule_poll(100)
                elif name == 'poll':
                    state = result['state']; self.poll_delay = 3000
                    if state == 'INVITED':
                        self.status.set('Invitation received. Approve or decline it in the invitation window.')
                        self.show_invitation(result)
                    elif state == 'APPROVED':
                        # Recover an owner-approved decision whose HTTP response
                        # or credential-file write was interrupted.
                        self.background('approve', lambda: self.client.decide(True))
                    elif state in ('EXPIRED', 'DECLINED'):
                        self.hide_invitation(); self.client.session_file.unlink(missing_ok=True); self.client.session = None
                        self.code.set('Code expired' if state == 'EXPIRED' else 'Invitation declined')
                        self.status.set('No worker was started. Click Prepare connection for a new code.')
                        self.prepare_button.configure(state='normal')
                elif name == 'approve':
                    self.hide_invitation(); self.approved = True; self.code.set('Approved')
                    self.start()
                elif name == 'decline':
                    self.hide_invitation(); self.code.set('Invitation declined')
                    self.status.set('Invitation declined. No worker was started.')
                    self.prepare_button.configure(state='normal')
                elif name == 'participation':
                    self.paused = result['paused']
                    self.pause_button.configure(text='Resume worker' if self.paused else 'Pause worker')
                    self.status.set('Paused: current work may finish; no new tasks will be assigned.' if self.paused else 'Resumed. The worker will check for tasks shortly.' if self.runtime.running() else 'Resumed. Click Start worker to participate.')
                self.pause_button.configure(state='normal' if self.approved else 'disabled')
                if self.client and self.client.session:
                    self.schedule_poll(self.poll_delay)
        except queue.Empty: pass
        if self.runtime and self.runtime.process and not self.runtime.running():
            self.runtime.process = None
            self.stop_button.configure(state='disabled'); self.start_button.configure(state='normal' if self.approved else 'disabled')
            self.status.set('Worker stopped.' if self.stopping else f'Worker exited. Inspect {self.runtime.log_file} for details.')
            self.stopping = False
        self.root.after(150, self.drain_events)


def main():
    parser = argparse.ArgumentParser(description='Owner approval window for the source-based grid worker')
    parser.add_argument('--api-url', default='http://localhost:8080/api')
    parser.add_argument('--allow-http', action='store_true', help='Allow trusted local demo HTTP')
    parser.add_argument('--state-directory', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    WorkerWindow(root, args.api_url, args.allow_http, args.state_directory)
    root.mainloop()


if __name__ == '__main__': main()
