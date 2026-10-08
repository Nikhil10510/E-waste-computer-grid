import base64
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tempfile
from threading import Event
import requests
from urllib.parse import urljoin
from config import Config, ROOT

logger = logging.getLogger(__name__)


class TaskCancelled(RuntimeError):
    pass


class TaskExecutor:
    def __init__(self):
        self.docker_client = None
        if Config.EXECUTION_MODE == "docker":
            import docker
            self.docker_client = docker.from_env(timeout=15)
            self.docker_client.ping()

    def capabilities(self):
        capabilities = []
        self.preflight_errors = {}
        for kind in Config.IMAGES:
            try:
                if self.docker_client:
                    self.docker_client.images.get(Config.IMAGES[kind])
                self.verify_workload(kind)
                capabilities.append(kind)
            except Exception as error:
                self.preflight_errors[kind] = str(error)
                logger.warning("Workload %s not advertised: preflight failed: %s", kind, error)
        if not capabilities:
            raise RuntimeError("No approved workload passed runtime preflight")
        return capabilities

    def verify_workload(self, kind):
        # This tiny synthetic probe checks runtime health, not classification accuracy.
        with tempfile.TemporaryDirectory(prefix="preflight-", dir=Config.TEMP_EXEC_DIR) as temp:
            inputs, outputs = Path(temp) / "input", Path(temp) / "output"
            inputs.mkdir(); outputs.mkdir()
            name = "probe.txt" if kind == "dummy" else "probe.png"
            if kind == "dummy":
                (inputs / name).write_text("runtime probe", encoding="utf-8")
            else:
                (inputs / name).write_bytes(base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGNg+M/wn4GB8T8DCAAAG/kC/0A9Dx0AAAAASUVORK5CYII="))
            self.run_workload(kind, inputs, outputs, Event(), "preflight-" + os.urandom(8).hex(), preflight=True)
            result = json.loads((outputs / "result.json").read_text(encoding="utf-8"))
            predictions = result.get("predictions", [])
            if (result.get("status") != "SUCCESS" or result.get("itemsProcessed") != 1
                    or result.get("itemsFailed") != 0 or result.get("errors") != []
                    or len(predictions) != 1 or predictions[0].get("image") != name):
                raise ValueError("Runtime probe did not produce its one expected result")

    @staticmethod
    def check_cancel(cancel):
        if cancel.is_set():
            raise TaskCancelled("Task stopped because its lease was lost or worker is shutting down")

    def stage_inputs(self, task, input_dir, cancel):
        items = task["payload"].get("items", [])
        if not items:
            raise ValueError("Task has no inputs")
        seen = set()
        for item in items:
            self.check_cancel(cancel)
            name = item.get("name", "")
            if not re.fullmatch(r"[a-zA-Z0-9._-]+", name) or name in (".", "..") or name in seen:
                raise ValueError("Unsafe or duplicate input filename")
            seen.add(name)
            target = input_dir / name
            if task["payload"]["workload_type"] == "dummy":
                target.write_text(item.get("content", ""), encoding="utf-8")
                continue
            url = urljoin(Config.CONTROL_PLANE_URL + "/", item.get("download_url", ""))
            if not url.startswith(("http://", "https://")):
                raise ValueError("Input is missing a download URL")
            # Expiring URLs are used only by the host agent. Never log their credentials.
            with requests.get(url, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                if int(response.headers.get("Content-Length", "0")) > Config.MAX_DOWNLOAD_BYTES:
                    raise ValueError("Input exceeds size limit")
                size = 0
                with target.open("wb") as out:
                    for chunk in response.iter_content(65536):
                        self.check_cancel(cancel)
                        size += len(chunk)
                        if size > Config.MAX_DOWNLOAD_BYTES:
                            raise ValueError("Input exceeds size limit")
                        out.write(chunk)

    def run_workload(self, kind, input_dir, output_dir, cancel, attempt, preflight=False):
        if kind not in Config.IMAGES:
            raise ValueError("Unsupported workload")
        started = time.monotonic()
        timeout = min(Config.WORKLOAD_TIMEOUT, Config.PREFLIGHT_TIMEOUT) if preflight else Config.WORKLOAD_TIMEOUT
        if self.docker_client:
            container = self.docker_client.containers.run(
                Config.IMAGES[kind], detach=True,
                environment={"PREFLIGHT": "1" if preflight else "0"},
                name=f"ewaste-{attempt}",
                labels={"ewaste.worker": str(Config.DATA_DIR), "ewaste.attempt": attempt},
                volumes={str(input_dir): {"bind": "/data/input", "mode": "ro"},
                         str(output_dir): {"bind": "/data/output", "mode": "rw"}},
                network_disabled=True, read_only=True, cap_drop=["ALL"],
                security_opt=["no-new-privileges"], pids_limit=128,
                mem_limit=os.getenv("WORKLOAD_MEMORY_LIMIT", "2g"),
                nano_cpus=int(float(os.getenv("WORKLOAD_CPUS", "2")) * 1_000_000_000),
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                user=f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None,
            )
            try:
                while True:
                    self.check_cancel(cancel)
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("Workload exceeded execution timeout")
                    container.reload()
                    if container.status in ("exited", "dead"):
                        if container.attrs["State"]["ExitCode"] != 0:
                            logs = container.logs(tail=20).decode("utf-8", errors="replace")
                            raise RuntimeError("Container failed: " + logs[-1500:])
                        break
                    cancel.wait(0.2)
            finally:
                container.remove(force=True)
        else:
            # Explicit development mode, limited to two repository-owned scripts.
            script = ROOT / "workloads" / ("dummy-workload/run_dummy.py" if kind == "dummy" else "ai-inference/run_inference.py")
            env = os.environ.copy()
            env.update(INPUT_DIR=str(input_dir), OUTPUT_DIR=str(output_dir), PYTHONUTF8="1", PREFLIGHT="1" if preflight else "0",
                       MODEL_PATH=str(ROOT / "workloads/ai-inference/models/mobilenetv2-12.onnx"),
                       LABELS_PATH=str(ROOT / "workloads/ai-inference/models/imagenet_labels.json"),
                       ARTIFACT_MANIFEST=str(ROOT / "workloads/ai-inference/models/artifact-manifest.json"))
            with (output_dir / "execution.log").open("wb") as log:
                process = subprocess.Popen([sys.executable, str(script)], env=env, stdout=log, stderr=log)
                try:
                    while process.poll() is None:
                        self.check_cancel(cancel)
                        if time.monotonic() - started > timeout:
                            raise TimeoutError("Workload exceeded execution timeout")
                        cancel.wait(0.1)
                    if process.returncode:
                        raise RuntimeError("Workload failed: " + (output_dir / "execution.log").read_text(errors="replace")[-1500:])
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
        return int((time.monotonic() - started) * 1000)

    def recover_containers(self):
        if self.docker_client:
            # Only containers started by this exact worker identity are cleaned up.
            for container in self.docker_client.containers.list(all=True, filters={"label": "ewaste.worker=" + str(Config.DATA_DIR)}):
                container.remove(force=True)

    def execute_task(self, task, cancel):
        task_id, token = task["task_id"], task["lease_token"]
        if not re.fullmatch(r"[a-f0-9-]{36}", task_id) or not re.fullmatch(r"[a-f0-9-]{36}", token):
            raise ValueError("Invalid task identity")
        task_dir = Config.TEMP_EXEC_DIR / f"{task_id}-{token}"
        input_dir, output_dir = task_dir / "input", task_dir / "output"
        # Retries must never reuse previous inputs/results.
        if task_dir.exists():
            shutil.rmtree(task_dir)
        input_dir.mkdir(parents=True)
        output_dir.mkdir()
        try:
            self.stage_inputs(task, input_dir, cancel)
            duration = self.run_workload(task["payload"]["workload_type"], input_dir, output_dir, cancel, token)
            self.check_cancel(cancel)
            result_path = output_dir / "result.json"
            if result_path.stat().st_size > Config.MAX_RESULT_BYTES:
                raise ValueError("Workload result exceeds size limit")
            raw = result_path.read_bytes()
            result = json.loads(raw)
            if result.get("itemsProcessed", 0) < 1:
                raise ValueError("Workload produced no successful results")
            return raw, duration
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)
