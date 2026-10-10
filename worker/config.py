import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if not getattr(sys, 'frozen', False): load_dotenv(Path(__file__).with_name(".env"))

STATE_ROOT = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'EWasteGrid' / 'helper'


class Config:
    CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "http://localhost:8080/api").rstrip("/")
    ENROLLMENT_TOKEN = os.getenv("ENROLLMENT_TOKEN", "local-enrollment-change-me")
    DATA_DIR = Path(os.getenv("DATA_DIR", str(STATE_ROOT if getattr(sys, 'frozen', False) else ROOT / "worker" / ".worker_data"))).resolve()
    CREDENTIALS_FILE = DATA_DIR / "credentials.json"
    TEMP_EXEC_DIR = Path(os.getenv("TEMP_EXEC_DIR", str(STATE_ROOT / 'tasks' if getattr(sys, 'frozen', False) else ROOT / "worker" / ".task_exec"))).resolve()
    EXECUTION_MODE = os.getenv("EXECUTION_MODE", "docker")
    REQUIRE_PAIRED_IDENTITY = bool(getattr(sys, 'frozen', False)) or os.getenv("REQUIRE_PAIRED_IDENTITY", "false") == "true"
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
    RELEASE = None
    if os.getenv('WORKLOAD_RELEASE_MANIFEST'):
        from runtime_release import OfflineRelease
        RELEASE = OfflineRelease(os.environ['WORKLOAD_RELEASE_MANIFEST'])
        if RELEASE.fingerprint != os.getenv('WORKLOAD_RELEASE_SHA256'):
            raise ValueError('Runtime release changed after selection; prepare it again')
        IMAGES = RELEASE.images.copy()

    @classmethod
    def setup_dirs(cls):
        if getattr(sys, 'frozen', False) and (cls.EXECUTION_MODE != 'docker' or cls.RELEASE is None):
            raise ValueError('Start this packaged helper through the owner app with a verified Docker release.')
        if cls.EXECUTION_MODE not in ("docker", "native"):
            raise ValueError("EXECUTION_MODE must be docker or native")
        if min(cls.HEARTBEAT_INTERVAL, cls.MIN_POLL_INTERVAL, cls.MAX_POLL_INTERVAL, cls.WORKLOAD_TIMEOUT, cls.PREFLIGHT_TIMEOUT) <= 0:
            raise ValueError("Worker intervals and timeout must be positive")
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.TEMP_EXEC_DIR.mkdir(parents=True, exist_ok=True)
