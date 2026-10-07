import argparse
from contextlib import contextmanager
from datetime import datetime
import logging
import os
import random
import signal
import threading
import time
import requests
from urllib.parse import urljoin
from api_client import APIClient, APIError
from config import Config
from task_executor import TaskExecutor, TaskCancelled

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
        self.executor = TaskExecutor()
        self.capabilities = self.executor.capabilities()
        self.executor.recover_containers()

    def shutdown(self, *_args):
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
                            self.lease_deadline = datetime.fromisoformat(reply["lease_expires_at"].replace("Z", "+00:00")).timestamp()
            except APIError as exc:
                logger.warning("Heartbeat failed: %s", exc)
                with self.lock:
                    if task is self.active_task and task and (exc.status in (401, 403) or time.time() >= self.lease_deadline):
                        self.cancel.set()
            self.stop.wait(self.api.heartbeat_interval)

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
                return self.api.complete_task(task, duration, result_key)
            except (APIError, requests.RequestException) as exc:
                if isinstance(exc, APIError) and exc.status is not None and exc.status < 500 and exc.status != 429:
                    raise
                if time.time() >= self.lease_deadline or self.cancel.is_set():
                    raise TaskCancelled("Could not report results before lease expired") from exc
                logger.warning("Result delivery interrupted; retrying")
                self.stop.wait(2)

    def process_task(self, task):
        with self.lock:
            self.cancel.clear()
            self.active_task = task
            self.lease_deadline = datetime.fromisoformat(task["lease_expires_at"].replace("Z", "+00:00")).timestamp()
        logger.info("Executing task %s, attempt %s", task["task_id"], task["retry_count"])
        try:
            raw, duration = self.executor.execute_task(task, self.cancel)
            self.report(task, raw, duration)
            logger.info("Task %s completed", task["task_id"])
        except TaskCancelled as exc:
            logger.warning("%s", exc)
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
        while not self.stop.is_set():
            try:
                self.api.register(self.capabilities)
                break
            except APIError as exc:
                logger.error("Registration failed: %s", exc)
                if once:
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
                        self.api.clear_credentials()
                        try:
                            self.api.register(self.capabilities)
                        except APIError as registration_error:
                            logger.warning("Re-enrollment failed: %s", registration_error)
                    if once:
                        raise
                    self.stop.wait(3)
        finally:
            self.stop.set()
            heartbeat.join(timeout=25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one assignment and exit")
    args = parser.parse_args()
    Config.setup_dirs()
    with worker_lock():
        agent = WorkerAgent()
        signal.signal(signal.SIGINT, agent.shutdown)
        signal.signal(signal.SIGTERM, agent.shutdown)
        agent.start(once=args.once)
