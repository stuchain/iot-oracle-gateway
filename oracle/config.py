"""Load env via python-dotenv; expose module-level constants with defaults."""
import os
from pathlib import Path
from urllib.parse import urlparse

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


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")

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

# Privacy / diagnostics
DEBUG = _bool("DEBUG", False)
SAFE_ERRORS = _bool("SAFE_ERRORS", True)

# Secrets (default for dev only)
DEFAULT_HMAC_SECRET = "change-me-in-production"
HMAC_SECRET = os.getenv("HMAC_SECRET", DEFAULT_HMAC_SECRET)
ALLOW_INSECURE_DEFAULT_SECRET = _bool("ALLOW_INSECURE_DEFAULT_SECRET", False)

# Data paths (default: repo-root "data/" and files under it)
DATA_DIR = os.getenv("DATA_DIR", "data")
WINDOWS_CSV_PATH = os.path.join(DATA_DIR, "telemetry_windows.csv")
ANCHOR_LOG_PATH = os.path.join(DATA_DIR, "anchor_log.txt")
ANCHORING_LOG_PATH = os.path.join(DATA_DIR, "anchoring_log.csv")


def redact_path(path: str) -> str:
    """Return only basename to avoid exposing local filesystem details."""
    return os.path.basename(str(path)) or "<path>"


def redact_url(url: str) -> str:
    """Return a minimal endpoint label without host/user info."""
    try:
        parsed = urlparse(url)
        path = parsed.path or "/"
        return path
    except Exception:
        return "<endpoint>"


def sanitize_exception(
    exc: Exception,
    *,
    fallback: str = "operation_failed",
    debug: bool | None = None,
) -> str:
    """Hide exception internals unless debug explicitly enabled."""
    debug_mode = DEBUG if debug is None else bool(debug)
    if debug_mode:
        return str(exc)
    return fallback
