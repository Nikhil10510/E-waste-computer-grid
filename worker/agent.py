import argparse
import json
import sys
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
        self.executor.recover_containers()
        self.capabilities = self.executor.capabilities()

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
                            self.lease_deadline = datetime.fromisoformat(reply["lease_expires_at"].replace("Z", "+00:00")).timestamp()
            except APIError as exc:
                logger.warning("Heartbeat failed: %s", exc)
                if exc.status in (401, 403):
                    self.shutdown()
                with self.lock:
                    if task is self.active_task and task and (exc.status in (401, 403) or time.time() >= self.lease_deadline):
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
                if time.time() >= self.lease_deadline or self.cancel.is_set():
                    raise TaskCancelled("Could not report results before lease expired") from exc
                logger.warning("Result delivery interrupted; retrying")
                self.stop.wait(2)
        raise TaskCancelled('Worker stopped before result delivery finished')

    def process_task(self, task):
        with self.lock:
            if self.stop.is_set(): return
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
        threading.Thread(target=self.local_stop_loop, daemon=True).start()
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
                    if self.stop.is_set(): break
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one assignment and exit")
    parser.add_argument("--preflight", action="store_true", help="Verify approved runtimes without enrollment; exit 1 if image inference is unavailable")
    args = parser.parse_args()
    Config.setup_dirs()
    if args.preflight:
        try:
            executor = TaskExecutor()
            capabilities = executor.capabilities()
            print(json.dumps({"mode": Config.EXECUTION_MODE, "capabilities": capabilities,
                              "errors": executor.preflight_errors}, indent=2))
            sys.exit(0 if "image_inference" in capabilities else 1)
        except Exception as error:
            print(json.dumps({"mode": Config.EXECUTION_MODE, "error": str(error)}))
            sys.exit(1)
    with worker_lock():
        agent = WorkerAgent()
        signal.signal(signal.SIGINT, agent.shutdown)
        signal.signal(signal.SIGTERM, agent.shutdown)
        agent.start(once=args.once)
