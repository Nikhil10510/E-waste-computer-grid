import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import random
import signal
import threading
import time
import requests
from urllib.parse import urljoin
from api_client import APIClient, APIError
from config import Config
from task_executor import TaskExecutor, TaskCancelled
from log_safety import SafeFormatter
from launch import prepare_external_programs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@contextmanager
def worker_lock():
    """OS-owned lock is released even after a crash."""
    handle = (Config.DATA_DIR / "agent.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Another worker is already using DATA_DIR; give each worker a separate directory")
    try:
        yield
    finally:
        handle.close()


class WorkerAgent:
    def __init__(self):
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.active_task = None
        self.lease_deadline = 0.0
        self.api = APIClient()
        if os.environ.get('EWASTE_LOG_FILE'):
            handler = RotatingFileHandler(os.environ['EWASTE_LOG_FILE'], maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
            handler.setFormatter(SafeFormatter(lambda: (self.api.node_secret, Config.ENROLLMENT_TOKEN)))
            logging.getLogger().handlers = [handler]
        # Owner stop/crash applies during startup probes as well as real jobs.
        self.start_local_monitors()
        try:
            self.executor = TaskExecutor()
            self.executor.recover_containers()
            self.capabilities = self.executor.capabilities(self.cancel)
        except BaseException:
            self.shutdown()
            raise

    def shutdown(self, *_args):
        with self.lock:
            self.stop.set()
            self.cancel.set()

    def heartbeat_loop(self):
        while not self.stop.is_set():
            with self.lock:
                task = self.active_task
            try:
                reply = self.api.send_heartbeat(task)
                with self.lock:
                    if task is self.active_task and task:
                        if reply["action"] == "CANCEL_TASK":
                            self.cancel.set()
                        elif reply.get("lease_expires_at"):
                            self.confirm_lease(reply)
            except APIError as exc:
                logger.warning("Heartbeat failed: %s", exc)
                if exc.status in (401, 403):
                    self.shutdown()
                with self.lock:
                    if task is self.active_task and task and (exc.status in (401, 403) or self.lease_expired()):
                        self.cancel.set()
            self.stop.wait(self.api.heartbeat_interval)

    def local_stop_loop(self):
        # The desktop controller owns this request file. It never sends a token
        # or terminates unrelated processes to stop its worker.
        while not self.stop.is_set():
            if (Config.DATA_DIR / 'stop.request').exists():
                self.shutdown()
                return
            self.stop.wait(0.25)

    def lease_watchdog_loop(self):
        # Heartbeat HTTP can block for its read timeout. Stop owned execution
        # independently at the last confirmed deadline during a network outage.
        while not self.stop.wait(0.1):
            with self.lock:
                if getattr(self, 'active_task', None) and self.lease_expired():
                    self.cancel.set()

    def confirm_lease(self, message):
        self.lease_deadline = datetime.fromisoformat(message['lease_expires_at'].replace('Z', '+00:00')).timestamp()
        remaining = message.get('lease_remaining_ms')
        if isinstance(remaining, (int, float)) and not isinstance(remaining, bool) and 0 <= remaining <= 900000:
            seconds = max(0, remaining / 1000 - message.get('_request_elapsed_seconds', 0))
        else: seconds = max(0, self.lease_deadline - time.time())  # Older coordinator compatibility.
        self.lease_monotonic_deadline = time.monotonic() + seconds

    def lease_expired(self):
        deadline = getattr(self, 'lease_monotonic_deadline', None)
        return time.monotonic() >= deadline if deadline is not None else time.time() >= self.lease_deadline

    def report(self, task, raw, duration):
        result_key = None
        # Retry transient uploads and completion responses without re-running compute.
        while not self.stop.is_set():
            try:
                if result_key is None:
                    self.executor.check_cancel(self.cancel)
                    upload = self.api.get_upload_url(task)
                    upload_url = urljoin(Config.CONTROL_PLANE_URL + "/", upload["upload_url"])
                    response = requests.put(upload_url, data=raw, headers={"Content-Type": "application/json"}, timeout=(10, 30))
                    response.raise_for_status()
                    result_key = upload["result_key"]
                self.executor.check_cancel(self.cancel)
                return self.api.complete_task(task, duration, result_key)
            except (APIError, requests.RequestException) as exc:
                if isinstance(exc, APIError) and exc.status is not None and exc.status < 500 and exc.status != 429:
                    raise
                if self.lease_expired() or self.cancel.is_set():
                    raise TaskCancelled("Could not report results before lease expired") from exc
                logger.warning("Result delivery interrupted; retrying")
                self.stop.wait(2)
        raise TaskCancelled('Worker stopped before result delivery finished')

    def release_stopped_task(self, task):
        # Give queued work back promptly after a local stop. The server checks
        # the lease token, so a stale/revoked attempt cannot release another one.
        try:
            self.api.fail_task(task, 'Owner stopped the worker', retryable=True, attempts=1)
        except APIError:
            logger.warning('Stopped assignment could not be released; server lease recovery will handle it')

    def process_task(self, task):
        with self.lock:
            stopped = self.stop.is_set()
            if not stopped:
                self.cancel.clear()
                self.active_task = task
                self.confirm_lease(task)
        if stopped:
            self.release_stopped_task(task)
            return
        logger.info("Executing task %s, attempt %s", task["task_id"], task["retry_count"])
        try:
            raw, duration = self.executor.execute_task(task, self.cancel)
            self.report(task, raw, duration)
            logger.info("Task %s completed", task["task_id"])
        except TaskCancelled as exc:
            logger.warning("%s", exc)
            if self.stop.is_set(): self.release_stopped_task(task)
        except Exception as exc:
            logger.error("Task failed: %s", exc)
            try:
                self.api.fail_task(task, str(exc), retryable=not isinstance(exc, ValueError))
            except APIError:
                logger.warning("Failure report unavailable; server lease recovery will handle it")
        finally:
            with self.lock:
                self.active_task = None
            try:
                self.api.send_heartbeat()
            except APIError:
                pass

    def start(self, once=False):
        self.start_local_monitors()
        while not self.stop.is_set():
            try:
                self.api.register(self.capabilities)
                break
            except APIError as exc:
                logger.error("Registration failed: %s", exc)
                if once or exc.status in (401, 403):
                    self.shutdown()
                    raise
                self.stop.wait(5)
        if self.stop.is_set():
            return
        logger.info("Worker %s online (%s)", self.api.node_id, ", ".join(self.capabilities))
        heartbeat = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat.start()
        interval = Config.MIN_POLL_INTERVAL
        try:
            while not self.stop.is_set():
                try:
                    task = self.api.request_task()
                    if self.stop.is_set():
                        if task: self.release_stopped_task(task)
                        break
                    if task:
                        self.process_task(task)
                        interval = Config.MIN_POLL_INTERVAL
                        if once:
                            break
                    else:
                        if once:
                            break
                        self.stop.wait(max(0.1, interval + random.uniform(-0.5, 0.5)))
                        interval = min(interval * 2, Config.MAX_POLL_INTERVAL)
                except APIError as exc:
                    logger.warning("Polling failed: %s", exc)
                    if exc.status in (401, 403):
                        self.shutdown()
                        raise
                    if once:
                        raise
                    self.stop.wait(3)
        finally:
            self.stop.set()
            heartbeat.join(timeout=25)

    def start_local_monitors(self):
        if getattr(self, '_local_monitors_started', False): return
        self._local_monitors_started = True
        for loop in (self.local_stop_loop, self.owner_liveness_loop, self.lease_watchdog_loop):
            threading.Thread(target=loop, daemon=True).start()

    def owner_liveness_loop(self):
        """A crashed owner app must not leave an invisible computing agent."""
        pid, created = os.environ.get('EWASTE_OWNER_PID'), os.environ.get('EWASTE_OWNER_CREATED')
        if not pid or not created: return  # Independent development CLI.
        import psutil
        try:
            owner = psutil.Process(int(pid))
            if abs(owner.create_time() - float(created)) > 0.01:
                self.shutdown(); return
            while not self.stop.wait(0.5):
                if not owner.is_running() or abs(owner.create_time() - float(created)) > 0.01:
                    self.shutdown(); return
        except (psutil.Error, ValueError): self.shutdown()


def main():
    prepare_external_programs()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one assignment and exit")
    parser.add_argument("--preflight", action="store_true", help="Verify approved runtimes without enrollment; exit 1 if image inference is unavailable")
    args = parser.parse_args()
    Config.setup_dirs()
    if args.preflight:
        preflight_cancel = threading.Event()
        stop_path = os.getenv('EWASTE_PREFLIGHT_STOP_FILE')
        def watch_preflight_stop():
            while not preflight_cancel.wait(0.1):
                if stop_path and Path(stop_path).exists(): preflight_cancel.set()
        if stop_path: threading.Thread(target=watch_preflight_stop, daemon=True).start()
        try:
            executor = TaskExecutor()
            capabilities = executor.capabilities(preflight_cancel)
            print(json.dumps({"mode": Config.EXECUTION_MODE, "capabilities": capabilities,
                              "errors": executor.preflight_errors}, indent=2))
            ready = set(capabilities) == set(Config.RELEASE.images) if Config.RELEASE else 'image_inference' in capabilities
            return 0 if ready else 1
        except Exception as error:
            print(json.dumps({"mode": Config.EXECUTION_MODE, "error": str(error)}))
            return 1
    with worker_lock():
        agent = WorkerAgent()
        signal.signal(signal.SIGINT, agent.shutdown)
        signal.signal(signal.SIGTERM, agent.shutdown)
        agent.start(once=args.once)
    return 0


if __name__ == '__main__': sys.exit(main())
