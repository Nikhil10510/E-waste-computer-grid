import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(Path(__file__).with_name(".env"))


class Config:
    CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "http://localhost:8080/api").rstrip("/")
    ENROLLMENT_TOKEN = os.getenv("ENROLLMENT_TOKEN", "local-enrollment-change-me")
    DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "worker" / ".worker_data"))).resolve()
    CREDENTIALS_FILE = DATA_DIR / "credentials.json"
    TEMP_EXEC_DIR = Path(os.getenv("TEMP_EXEC_DIR", str(ROOT / "worker" / ".task_exec"))).resolve()
    EXECUTION_MODE = os.getenv("EXECUTION_MODE", "docker")
    REQUIRE_PAIRED_IDENTITY = os.getenv("REQUIRE_PAIRED_IDENTITY", "false") == "true"
    HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "15"))
    MIN_POLL_INTERVAL = float(os.getenv("MIN_POLL_INTERVAL", "2"))
    MAX_POLL_INTERVAL = float(os.getenv("MAX_POLL_INTERVAL", "30"))
    WORKLOAD_TIMEOUT = float(os.getenv("WORKLOAD_TIMEOUT", "600"))
    PREFLIGHT_TIMEOUT = float(os.getenv("PREFLIGHT_TIMEOUT", "30"))
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    MAX_RESULT_BYTES = 5 * 1024 * 1024
    IMAGES = {
        "dummy": os.getenv("DUMMY_IMAGE", "ewaste/dummy-workload:v1"),
        "image_inference": os.getenv("INFERENCE_IMAGE", "ewaste/ai-workload:v1"),
    }

    @classmethod
    def setup_dirs(cls):
        if cls.EXECUTION_MODE not in ("docker", "native"):
            raise ValueError("EXECUTION_MODE must be docker or native")
        if min(cls.HEARTBEAT_INTERVAL, cls.MIN_POLL_INTERVAL, cls.MAX_POLL_INTERVAL, cls.WORKLOAD_TIMEOUT, cls.PREFLIGHT_TIMEOUT) <= 0:
            raise ValueError("Worker intervals and timeout must be positive")
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.TEMP_EXEC_DIR.mkdir(parents=True, exist_ok=True)
