"""Load env via python-dotenv; expose module-level constants with defaults."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_CONFIG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CONFIG_DIR.parent
_DEFAULT_CONTRACT_ABI = (
    _REPO_ROOT
    / "contracts"
    / "artifacts"
    / "contracts"
    / "TelemetryAnchor.sol"
    / "TelemetryAnchor.json"
)

# Helpers: parse env with fallback to default (invalid int/float -> use default)
def _int(key: str, default: int) -> int:
    try:
        val = os.getenv(key)
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def _float(key: str, default: float) -> float:
    try:
        val = os.getenv(key)
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

# MQTT
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = _int("MQTT_PORT", 1883)

# Windowing & anomaly detection
WINDOW_SEC = _int("WINDOW_SEC", 5)
EWMA_ALPHA = _float("EWMA_ALPHA", 0.2)
Z_THRESHOLD = _float("Z_THRESHOLD", 3.0)

# Anchoring
ANCHOR_INTERVAL_SEC = _int("ANCHOR_INTERVAL_SEC", 60)
GANACHE_URL = os.getenv("GANACHE_URL", "http://127.0.0.1:8545")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "").strip()
CONTRACT_ABI_PATH = os.getenv("CONTRACT_ABI_PATH", str(_DEFAULT_CONTRACT_ABI))

# Secrets (default for dev; set in .env for real use)
HMAC_SECRET = os.getenv("HMAC_SECRET", "change-me-in-production")

# Data paths (default: repo-root "data/" and files under it)
DATA_DIR = os.getenv("DATA_DIR", "data")
WINDOWS_CSV_PATH = os.path.join(DATA_DIR, "telemetry_windows.csv")
ANCHOR_LOG_PATH = os.path.join(DATA_DIR, "anchor_log.txt")
ANCHORING_LOG_PATH = os.path.join(DATA_DIR, "anchoring_log.csv")
