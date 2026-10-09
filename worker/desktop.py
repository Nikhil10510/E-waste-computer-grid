"""Owner desktop with protected state and background runtime/network checks."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from api_client import APIError
from desktop_runtime import DesktopRuntime
from hardware import get_hardware_specs
from pairing_client import PairingClient, normalize_api_url, state_directory
from resource_limits import validate_limits
from state_store import load_state, save_state, WINDOWS
from log_safety import safe_text


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
        self.preferences = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'EWasteGrid' / 'desktop-settings.json'
        preference_error = None
        if not api_url and directory is None and self.preferences.exists():
            try:
                previous = load_state(self.preferences)
                api_url, allow_http = previous['api_url'], previous['allow_http']
            except Exception as error: preference_error = safe_text(error)
        api_url = api_url or 'http://localhost:8080/api'
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
        self.disconnecting = False
        self.starting = False
        self.stop_after_start = False
        self.threads = []
        root.title('E-Waste Grid Worker')
        root.geometry('740x650'); root.minsize(520, 440)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        if 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('TFrame', background='#f5f8fa')
        style.configure('TLabel', background='#f5f8fa', foreground='#243746', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 21, 'bold'), foreground='#123448')
        style.configure('TButton', font=('Segoe UI', 10), padding=(12, 7))
        header = ttk.Frame(root, padding=(18, 10)); header.pack(fill='x')
        ttk.Label(header, text='Contribute this laptop', style='Title.TLabel').pack(anchor='w')
        self.connection = tk.StringVar(value='Not connected')
        ttk.Label(header, textvariable=self.connection).pack(anchor='w')
        footer = ttk.Frame(root, padding=(18, 8)); footer.pack(side='bottom', fill='x')
        self.status = tk.StringVar(value='Choose your grid and limits, then prepare a connection.')
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=680)
        self.status_label.pack(fill='x', pady=(0, 8))
        row = ttk.Frame(footer); row.pack(fill='x')
        for column in range(2): row.columnconfigure(column, weight=1)
        self.start_button = ttk.Button(row, text='Start worker', command=self.start, state='disabled')
        self.start_button.grid(row=0, column=0, sticky='ew', padx=(0, 4), pady=2)
        self.stop_button = ttk.Button(row, text='Stop worker', command=self.stop, state='disabled')
        self.stop_button.grid(row=0, column=1, sticky='ew', padx=(4, 0), pady=2)
        self.pause_button = ttk.Button(row, text='Pause worker', command=self.toggle_pause, state='disabled')
        self.pause_button.grid(row=1, column=0, sticky='ew', padx=(0, 4), pady=2)
        self.disconnect_button = ttk.Button(row, text='Disconnect / change grid', command=self.reset_connection)
        self.disconnect_button.grid(row=1, column=1, sticky='ew', padx=(4, 0), pady=2)
        notebook = ttk.Notebook(root); notebook.pack(fill='both', expand=True, padx=18)
        setup = ttk.Frame(notebook); notebook.add(setup, text='Connection')
        diagnostics = ttk.Frame(notebook, padding=10); notebook.add(diagnostics, text='Diagnostics')
        ttk.Button(diagnostics, text='Refresh diagnostics', command=self.refresh_diagnostics).pack(anchor='w', pady=(0, 8))
        self.log_view = ScrolledText(diagnostics, height=12, wrap='word', font=('Consolas', 10), state='disabled')
        self.log_view.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(setup, highlightthickness=0, background='#f5f8fa')
        scrollbar = ttk.Scrollbar(setup, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y'); self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        panel = ttk.Frame(self.canvas, padding=12)
        panel_id = self.canvas.create_window(0, 0, window=panel, anchor='nw')
        panel.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(panel_id, width=event.width))
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
        memory_row = ttk.Frame(panel); memory_row.pack(fill='x', pady=(0, 10))
        ttk.Label(memory_row, text='RAM limit (GiB)').pack(side='left')
        self.memory_input = ttk.Spinbox(memory_row, from_=0.25, to=hardware['ram_gb'], increment=0.25, width=7, textvariable=self.memory_value)
        self.memory_input.pack(side='left', padx=8)
        self.prepare_button = ttk.Button(panel, text='Prepare connection', command=self.prepare); self.prepare_button.pack(anchor='w')
        ttk.Separator(panel).pack(fill='x', pady=17)
        self.code = tk.StringVar(value='No pairing code yet')
        ttk.Label(panel, text='Share only this code with the grid administrator:').pack(anchor='w')
        self.code_entry = ttk.Entry(panel, textvariable=self.code, state='readonly', font=('Consolas', 19))
        self.code_entry.pack(fill='x', pady=(6, 8))
        ttk.Button(panel, text='Copy pairing code', command=self.copy_code).pack(anchor='w')
        connection_row = ttk.Frame(panel); connection_row.pack(fill='x', pady=(8, 0))
        self.retry_button = ttk.Button(connection_row, text='Check invitation again', command=self.poll, state='disabled'); self.retry_button.pack(side='left')
        self.policy = tk.StringVar(value='Choose limits before pairing. Docker enforces the workload ceilings.')
        ttk.Label(panel, textvariable=self.policy, wraplength=660).pack(anchor='w', pady=(12, 0))
        ttk.Label(panel, text='Approved workloads: image classification and pipeline demo.\nWorkload limits exclude Docker/WSL overhead. Source/Python still required.', wraplength=460).pack(anchor='w', pady=(6, 0))
        ttk.Label(panel, text='Saved state: Windows account protection (DPAPI).' if WINDOWS else 'Saved state: owner-only files; Windows encryption is unavailable.', wraplength=460).pack(anchor='w', pady=(6, 0))
        root.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(350, root.winfo_width() - 40)) if event.widget is root else None)
        self.restore_settings(api_url, allow_http)
        if preference_error: self.status.set(preference_error)
        root.after(100, self.drain_events)

    def restore_settings(self, api_url, allow_http):
        try:
            url = normalize_api_url(api_url, allow_http)
            directory = Path(self.directory_override) if self.directory_override else state_directory(url)
            path = directory / 'settings.json'
            if not path.exists(): return
            saved = load_state(path)
            if saved.get('api_url') != url: raise ValueError('Saved settings belong to another grid')
            limits = validate_limits(saved['resource_limits'])
            self.name.set(saved['name']); self.allow_http.set(saved['allow_http'])
            self.cpu_value.set(format(limits['cpu'], 'g')); self.memory_value.set(format(limits['memory_gb'], 'g'))
        except Exception as error: self.status.set(safe_text(error))

    def background(self, name, work):
        if self.busy or self.closing: return
        self.busy = True
        self.prepare_button.configure(state='disabled')
        self.retry_button.configure(state='disabled')
        self.pause_button.configure(state='disabled')
        for button in self.popup_buttons: button.configure(state='disabled')
        events = self.events
        def run():
            try: events.put((name, work(), None))
            except Exception as error: events.put((name, None, error))
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread); thread.start()

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
            save_state(directory / 'settings.json', {'api_url': url, 'name': name,
                'allow_http': self.allow_http.get(), 'resource_limits': limits})
            if self.directory_override is None:
                save_state(self.preferences, {'api_url': url, 'allow_http': self.allow_http.get()})
            self.address.configure(state='disabled'); self.http_box.configure(state='disabled'); self.name_entry.configure(state='disabled')
            self.cpu_input.configure(state='disabled'); self.memory_input.configure(state='disabled')
            self.status.set('Checking Docker and the approved workload runtimes...')
            self.approved = False
            self.connection.set('Checking runtime and grid')
            client, runtime = self.client, self.runtime
            def prepare_connection():
                identity = client.saved_identity()
                saved_policy = identity.get('resource_limits') if identity else client.session.get('resource_limits') if client.session else limits
                saved_policy = saved_policy or {'cpu': min(2, hardware['cpu_cores']), 'memory_gb': min(2, hardware['ram_gb'])}
                runtime.limits = validate_limits({'cpu': min(saved_policy['cpu'], hardware['cpu_cores']),
                    'memory_gb': min(saved_policy['memory_gb'], hardware['ram_gb'])})
                capabilities = runtime.preflight()
                if identity: return ('identity', identity)
                if client.session: return ('session', client.session)
                reported = get_hardware_specs(capabilities); reported['name'] = name
                return ('session', client.begin(reported, runtime.limits))
            self.background('prepare', prepare_connection)
        except Exception as error: self.status.set(safe_text(error))

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
        elif self.client and self.approved and not self.busy:
            self.background('session', self.client.saved_identity)

    def refresh_diagnostics(self):
        if self.runtime and not self.busy:
            runtime = self.runtime
            secrets = self.private_values()
            self.background('diagnostics', lambda: runtime.diagnostics(secrets))

    def private_values(self):
        if self.client and self.client.session:
            return (self.client.session.get('pairing_secret'), self.client.session.get('pairing_code'))
        return ()

    def reset_connection(self):
        if self.busy or self.closing:
            self.status.set('Wait for the current operation before changing grids. Stop remains available.')
            return
        if self.runtime and self.runtime.running():
            self.disconnecting = True; self.stop(); return
        if self.poll_timer: self.root.after_cancel(self.poll_timer); self.poll_timer = None
        self.hide_invitation()
        if self.lock_context: self.lock_context.__exit__(None, None, None); self.lock_context = None
        self.client = self.runtime = None; self.approved = False
        self.disconnecting = False; self.paused = False
        self.connection.set('Not connected')
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
        self.popup.geometry('560x400'); self.popup.minsize(560, 360)
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
        client = self.client
        self.background('approve' if approve else 'decline', lambda: client.decide(approve))

    def start(self):
        if not self.approved or self.closing or self.busy: return
        try:
            self.starting = True; self.stop_after_start = False
            self.background('start', self.runtime.start)
            self.start_button.configure(state='disabled'); self.stop_button.configure(state='normal')
            self.pause_button.configure(state='normal')
            self.status.set('Launching the worker process...')
        except Exception as error: self.status.set(str(error))

    def stop(self):
        if self.starting:
            self.stop_after_start = True
            self.status.set('Stop requested. Waiting for the worker launch to finish...')
        if self.runtime and self.runtime.running():
            self.stopping = True; self.runtime.request_stop()
            self.stop_button.configure(state='disabled'); self.start_button.configure(state='disabled')
            self.status.set('Stopping the worker safely. Waiting for any active network request to finish...')

    def toggle_pause(self):
        if not self.approved or self.busy or self.closing: return
        self.status.set('Updating participation with the grid...')
        client, paused = self.client, not self.paused
        self.background('participation', lambda: client.set_paused(paused))

    def display_policy(self):
        limits = self.runtime.limits
        self.cpu_value.set(format(limits['cpu'], 'g')); self.memory_value.set(format(limits['memory_gb'], 'g'))
        self.policy.set(f"Workload ceilings: {limits['cpu']:g} CPU equivalents / {limits['memory_gb']:g} GiB RAM.\nSaved approval keeps these limits when this app restarts.")

    def close(self):
        self.closing = True
        self.hide_invitation()
        if self.runtime and self.runtime.running(): self.stop()
        elif self.busy: self.status.set('Closing safely. Waiting for the current runtime check or network request...')
        elif self.threads: self.status.set('Closing safely. Waiting for background operations...')
        else: self.finish_close()

    def finish_close(self):
        if self.lock_context: self.lock_context.__exit__(None, None, None); self.lock_context = None
        self.root.destroy()

    def drain_events(self):
        self.threads = [thread for thread in self.threads if thread.is_alive()]
        if self.closing:
            try:
                while True:
                    self.events.get_nowait(); self.busy = False
            except queue.Empty: pass
            if self.runtime and self.runtime.running() and not self.stopping: self.stop()
            if self.busy or self.threads or (self.runtime and self.runtime.running()): self.root.after(200, self.drain_events)
            else: self.finish_close()
            return
        try:
            while True:
                name, result, error = self.events.get_nowait()
                self.busy = False
                for button in self.popup_buttons: button.configure(state='normal')
                if error:
                    if name == 'start':
                        self.starting = False
                        self.start_button.configure(state='normal' if self.approved else 'disabled')
                        self.stop_button.configure(state='disabled')
                    self.status.set(safe_text(error, self.private_values())); self.poll_delay = min(30000, self.poll_delay * 2)
                    self.connection.set('Grid unavailable — retrying' if isinstance(error, APIError) and error.status not in (401, 403, 410) else 'Connection needs attention')
                    if isinstance(error, APIError) and error.status in (401, 403, 410):
                        self.hide_invitation(); self.approved = False; self.start_button.configure(state='disabled')
                        if self.runtime and self.runtime.running(): self.stop()
                    if isinstance(error, APIError) and error.status == 410 and self.client and self.client.session:
                        # Expired private sessions cannot recover. Stop polling
                        # them and allow the owner to request a fresh code.
                        self.client.session_file.unlink(missing_ok=True)
                        self.client.session = None
                        self.code.set('Code expired')
                        self.status.set('No worker was started. Click Prepare connection for a new code.')
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
                        self.connection.set('Approved — paused' if self.paused else 'Approved — worker stopped')
                    else:
                        self.code.set(data['pairing_code'])
                        self.status.set('Share the code with your grid administrator. No computing starts before approval.')
                        self.retry_button.configure(state='normal')
                        self.schedule_poll(100)
                        self.connection.set('Waiting for administrator invitation')
                elif name == 'poll':
                    state = result['state']; self.poll_delay = 3000
                    if state == 'INVITED':
                        self.connection.set('Waiting for your approval')
                        self.status.set('Invitation received. Approve or decline it in the invitation window.')
                        self.show_invitation(result)
                    elif state == 'APPROVED':
                        # Recover an owner-approved decision whose HTTP response
                        # or credential-file write was interrupted.
                        client = self.client
                        self.background('approve', lambda: client.decide(True))
                    elif state in ('EXPIRED', 'DECLINED'):
                        self.hide_invitation(); self.client.session_file.unlink(missing_ok=True); self.client.session = None
                        self.code.set('Code expired' if state == 'EXPIRED' else 'Invitation declined')
                        self.status.set('No worker was started. Click Prepare connection for a new code.')
                        self.prepare_button.configure(state='normal')
                elif name == 'approve':
                    self.hide_invitation(); self.approved = True; self.code.set('Approved')
                    self.start()
                elif name == 'start':
                    self.starting = False
                    if self.stop_after_start: self.stop()
                    else:
                        self.status.set('Worker process running in paused mode. Resume when ready.' if self.paused else 'Worker process running. View task progress in the grid dashboard.')
                    self.connection.set('Approved — stopping' if self.stop_after_start else 'Approved — paused' if self.paused else 'Approved — worker process running')
                elif name == 'decline':
                    self.hide_invitation(); self.code.set('Invitation declined')
                    self.status.set('Invitation declined. No worker was started.')
                    self.prepare_button.configure(state='normal')
                elif name == 'participation':
                    self.paused = result['paused']
                    self.pause_button.configure(text='Resume worker' if self.paused else 'Pause worker')
                    self.status.set('Paused: current work may finish; no new tasks will be assigned.' if self.paused else 'Resumed. The worker will check for tasks shortly.' if self.runtime.running() else 'Resumed. Click Start worker to participate.')
                    self.connection.set('Approved — paused' if self.paused else 'Approved — ready')
                elif name == 'session':
                    recovered = self.connection.get() == 'Grid unavailable — retrying'
                    self.paused = result.get('paused', False)
                    self.pause_button.configure(text='Resume worker' if self.paused else 'Pause worker')
                    self.poll_delay = 3000
                    self.connection.set('Grid: ' + result.get('status', 'approved') + (' / paused' if self.paused else '') + (' / process stopped' if not self.runtime.running() else ''))
                    if recovered: self.status.set('Grid connection restored. Saved approval and participation settings are retained.')
                elif name == 'diagnostics':
                    self.log_view.configure(state='normal'); self.log_view.delete('1.0', 'end')
                    self.log_view.insert('end', result); self.log_view.configure(state='disabled')
                self.pause_button.configure(state='normal' if self.approved else 'disabled')
                if self.client and self.client.session:
                    self.schedule_poll(self.poll_delay)
                elif self.approved and not self.busy: self.schedule_poll(max(5000, self.poll_delay))
        except queue.Empty: pass
        if self.runtime and self.runtime.process and not self.runtime.running():
            self.runtime.process = None
            self.stop_button.configure(state='disabled'); self.start_button.configure(state='normal' if self.approved else 'disabled')
            self.status.set('Worker stopped.' if self.stopping else f'Worker exited. Inspect {self.runtime.log_file} for details.')
            self.stopping = False
            self.connection.set('Approved — worker stopped' if self.approved else 'Connection needs attention')
            if self.disconnecting: self.reset_connection()
        self.root.after(150, self.drain_events)


def main():
    parser = argparse.ArgumentParser(description='Owner approval window for the source-based grid worker')
    parser.add_argument('--api-url', default=None, help='Grid address; otherwise restore the last selected grid')
    parser.add_argument('--allow-http', action='store_true', help='Allow trusted local demo HTTP')
    parser.add_argument('--state-directory', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    WorkerWindow(root, args.api_url, args.allow_http, args.state_directory)
    root.mainloop()


if __name__ == '__main__': main()
