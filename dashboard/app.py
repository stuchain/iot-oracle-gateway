"""Streamlit dashboard: oracle /metrics polling, simulator config, and CSV window charts.

Telemetry CSV (default ``data/telemetry_windows.csv``) is re-read on every Streamlit rerun,
including the periodic auto-refresh and the "Refresh metrics now" button—no separate cache,
so new oracle rows appear after the next rerun.
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from oracle.config import DEBUG, TELEMETRY_ARCHIVE_SUBDIR, redact_path, redact_url, sanitize_exception

LOG = logging.getLogger(__name__)

ORACLE_URL = os.getenv("ORACLE_URL", "http://127.0.0.1:8000").rstrip("/")
METRICS_TIMEOUT_SEC = 2.0
AUTO_REFRESH_MS = 5000
Z_THRESHOLD = float(os.getenv("Z_THRESHOLD", "3.0"))

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SIM_CONFIG = _REPO_ROOT / "config" / "sim_config.json"
SIM_CONFIG_PATH = Path(os.getenv("SIM_CONFIG_PATH", str(_DEFAULT_SIM_CONFIG)))

st.set_page_config(page_title="IoT Oracle Dashboard", layout="wide")

if "sim_proc" not in st.session_state:
    st.session_state.sim_proc = None

st.markdown(
    """
    <style>
      :root {
        --card-bg: rgba(30, 41, 59, 0.35);
        --card-border: rgba(148, 163, 184, 0.25);
        --muted: #9ca3af;
        --ok: #22c55e;
        --warn: #f59e0b;
        --radius-sm: 8px;
        --radius-md: 10px;
        --radius-lg: 12px;
        --space-1: 0.14rem;
        --space-2: 0.26rem;
        --space-3: 0.42rem;
        --space-4: 0.62rem;
      }
      .block-container {
        padding-top: 0.62rem;
        padding-bottom: 0.3rem;
      }
      h2, h3, h4 {
        margin-top: 0.16rem !important;
        margin-bottom: 0.24rem !important;
      }
      /* Main title: room for descenders (y, g, p) — tight line-height + overflow clips glyphs */
      h1 {
        margin-top: 0.16rem !important;
        margin-bottom: 0.28rem !important;
        line-height: 1.42 !important;
        padding-bottom: 0.12em !important;
      }
      [data-testid="stHeading"] {
        overflow: visible !important;
      }
      p { margin-bottom: 0.16rem !important; }
      .section-card {
        background: var(--card-bg);
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: var(--radius-lg);
        padding: var(--space-2) var(--space-3);
        margin: var(--space-1) 0 var(--space-2) 0;
      }
      .metric-group-title {
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.01em;
        color: #cbd5e1;
        margin: 0 0 var(--space-2) 0;
      }
      .group-card {
        background: rgba(15, 23, 42, 0.24);
        border: 1px solid rgba(148, 163, 184, 0.42);
        border-radius: var(--radius-md);
        padding: var(--space-3) var(--space-4);
        margin: 0.06rem 0 0.16rem 0;
      }
      .summary-grid [data-testid="stColumn"] {
        padding-right: 0.8rem;
      }
      .summary-grid [data-testid="stColumn"]:last-child {
        padding-right: 0;
      }
      .metric-card {
        border: 1px solid rgba(148, 163, 184, 0.32);
        border-radius: var(--radius-md);
        background: rgba(15, 23, 42, 0.28);
        padding: var(--space-2) var(--space-3);
        margin-bottom: 0.48rem;
      }
      .metric-card:last-child { margin-bottom: 0.12rem; }
      .metric-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.32rem;
        margin-bottom: 0.1rem;
      }
      .metric-label {
        font-size: 0.71rem;
        color: #cbd5e1;
        line-height: 1.15;
      }
      .metric-value {
        font-size: 0.94rem;
        color: #f8fafc;
        line-height: 1.18;
        font-weight: 650;
        word-break: break-all;
        overflow-wrap: anywhere;
      }
      .help-details {
        position: relative;
        margin: 0;
        line-height: 1;
      }
      .help-summary {
        list-style: none;
        cursor: pointer;
        width: 1rem;
        height: 1rem;
        border-radius: 999px;
        border: 1px solid rgba(148, 163, 184, 0.5);
        color: #cbd5e1;
        font-size: 0.72rem;
        display: flex;
        align-items: center;
        justify-content: center;
        user-select: none;
      }
      .help-summary::-webkit-details-marker { display: none; }
      .help-details[open] .help-summary {
        border-color: rgba(147, 197, 253, 0.65);
        color: #93c5fd;
      }
      .help-popover {
        position: absolute;
        right: 0;
        top: 1.15rem;
        z-index: 999;
        width: 18rem;
        max-width: min(18rem, 60vw);
        background: rgba(15, 23, 42, 0.98);
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: var(--radius-sm);
        padding: 0.4rem 0.5rem;
        font-size: 0.75rem;
        line-height: 1.22rem;
        color: #e2e8f0;
        text-align: left;
        box-shadow: 0 8px 20px rgba(2, 6, 23, 0.5);
      }
      .status-chip {
        display: inline-block;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
        padding: 0.18rem 0.6rem;
        border: 1px solid rgba(148, 163, 184, 0.35);
      }
      .status-ok { color: var(--ok); }
      .status-warn { color: var(--warn); }
      .small-muted { color: var(--muted); font-size: 0.85rem; }
      div[data-testid="stMetric"] {
        border: 1px solid var(--card-border);
        border-radius: 10px;
        padding: 0.2rem 0.35rem;
        background: rgba(15, 23, 42, 0.28);
      }
      div[data-testid="stMetricValue"] { font-size: 0.96rem !important; }
      div[data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
      section[data-testid="stSidebar"] {
        padding-top: 0.35rem !important;
      }
      section[data-testid="stSidebar"] > div {
        padding-top: 0.15rem !important;
        padding-bottom: 0.25rem !important;
      }
      section[data-testid="stSidebar"] h1,
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3 {
        font-size: 0.95rem !important;
        margin-top: 0 !important;
        margin-bottom: 0.12rem !important;
        line-height: 1.2 !important;
      }
      section[data-testid="stSidebar"] [data-testid="stCaption"] {
        margin-top: 0 !important;
        margin-bottom: 0.2rem !important;
        font-size: 0.72rem !important;
      }
      section[data-testid="stSidebar"] .stNumberInput,
      section[data-testid="stSidebar"] .stCheckbox,
      section[data-testid="stSidebar"] .stTextInput,
      section[data-testid="stSidebar"] .stSelectbox {
        margin-bottom: 0.02rem !important;
      }
      section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
        font-size: 0.76rem;
      }
      section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
        margin-bottom: 0.06rem !important;
        font-size: 0.78rem !important;
      }
      section[data-testid="stSidebar"] [data-testid="stNumberInput"] > div,
      section[data-testid="stSidebar"] [data-testid="stTextInput"] > div,
      section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div {
        margin-bottom: 0.06rem !important;
      }
      .sidebar-section-gap {
        margin-top: 0.18rem;
        margin-bottom: 0.08rem;
      }
      section[data-testid="stSidebar"] [data-testid="stButton"] button {
        width: 100% !important;
        box-sizing: border-box !important;
        min-height: 2.05rem !important;
        border-radius: 8px !important;
        font-size: 0.8rem !important;
        font-weight: 550 !important;
        letter-spacing: 0.02em !important;
        padding: 0.35rem 0.5rem !important;
        transition: background 0.15s ease, border-color 0.15s ease, opacity 0.15s ease !important;
      }
      /* Secondary / outline: unified “ghost” panel buttons */
      section[data-testid="stSidebar"] [data-testid="stButton"] button[kind="secondary"] {
        background: rgba(30, 41, 59, 0.72) !important;
        border: 1px solid rgba(148, 163, 184, 0.38) !important;
        color: #e2e8f0 !important;
      }
      section[data-testid="stSidebar"] [data-testid="stButton"] button[kind="secondary"]:hover:not(:disabled) {
        background: rgba(51, 65, 85, 0.85) !important;
        border-color: rgba(186, 230, 253, 0.35) !important;
        color: #f8fafc !important;
      }
      /* Primary: Start simulator */
      section[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(180deg, #15803d 0%, #166534 100%) !important;
        border: 1px solid rgba(74, 222, 128, 0.45) !important;
        color: #f0fdf4 !important;
        box-shadow: 0 1px 0 rgba(255, 255, 255, 0.06) inset !important;
      }
      section[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"]:hover:not(:disabled) {
        filter: brightness(1.06) !important;
        border-color: rgba(134, 239, 172, 0.55) !important;
      }
      section[data-testid="stSidebar"] [data-testid="stButton"] button:disabled {
        opacity: 0.4 !important;
        cursor: not-allowed !important;
      }
      section[data-testid="stSidebar"] div[data-testid="stButton"] {
        margin-bottom: 0.1rem;
      }
      section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button {
        width: 100% !important;
        box-sizing: border-box !important;
        min-height: 2.05rem !important;
        border-radius: 8px !important;
        font-size: 0.8rem !important;
        font-weight: 550 !important;
        letter-spacing: 0.02em !important;
        padding: 0.35rem 0.5rem !important;
      }
      section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button[kind="primary"] {
        background: linear-gradient(180deg, #15803d 0%, #166534 100%) !important;
        border: 1px solid rgba(74, 222, 128, 0.45) !important;
        color: #f0fdf4 !important;
        box-shadow: 0 1px 0 rgba(255, 255, 255, 0.06) inset !important;
      }
      section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button[kind="primary"]:hover:not(:disabled) {
        filter: brightness(1.06) !important;
      }
      section[data-testid="stSidebar"] [data-testid="stDownloadButton"] {
        margin-bottom: 0.1rem;
      }
      section[data-testid="stSidebar"] .sidebar-run-line {
        margin: 0.08rem 0 0.18rem 0 !important;
        line-height: 1.35 !important;
      }
      /* Equal-width columns in sidebar so paired buttons align */
      section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        gap: 0.4rem !important;
        align-items: stretch !important;
      }
      section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        flex: 1 1 0% !important;
        min-width: 0 !important;
      }
      .sidebar-btn-row-gap {
        height: 0.4rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def _popen_simulator(cmd: list[str]) -> subprocess.Popen:
    kwargs: dict = {"cwd": str(_REPO_ROOT)}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen(cmd, **kwargs)


def _simulator_running() -> bool:
    proc = st.session_state.sim_proc
    if proc is None:
        return False
    if proc.poll() is not None:
        st.session_state.sim_proc = None
        return False
    return True


def _dash(v: Any) -> str:
    if v is None:
        return "—"
    return str(v)


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes")


def _metric_card(label: str, value: Any, help_text: str, key: str) -> str:
    """Render a compact metric card with custom inline help popover."""
    val = _dash(value)
    return (
        "<div class='metric-card'>"
        "<div class='metric-head'>"
        f"<div class='metric-label'>{label}</div>"
        "<details class='help-details'>"
        f"<summary class='help-summary' id='help-{key}' aria-label='Show help'>?</summary>"
        f"<div class='help-popover'>{help_text}</div>"
        "</details>"
        "</div>"
        f"<div class='metric-value'>{val}</div>"
        "</div>"
    )


def load_sim_config() -> dict[str, Any]:
    if not SIM_CONFIG_PATH.exists():
        return {}
    try:
        with open(SIM_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        LOG.warning("Could not load %s: %s", SIM_CONFIG_PATH, e)
        return {}


def save_sim_config(payload: dict[str, Any]) -> None:
    SIM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SIM_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch_metrics() -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Return (json dict, error message). Error is None on success."""
    url = f"{ORACLE_URL}/metrics"
    try:
        r = requests.get(url, timeout=METRICS_TIMEOUT_SEC)
        if r.status_code != 200:
            if DEBUG:
                return None, f"HTTP {r.status_code} from {url}"
            return None, f"Oracle metrics request failed (HTTP {r.status_code})."
        return r.json(), None
    except requests.RequestException as e:
        if DEBUG:
            return None, f"Cannot reach oracle at {url}: {e}"
        return None, "Cannot reach oracle endpoint. Check service and network."


def telemetry_csv_path() -> Path:
    """Default matches oracle ``DATA_DIR`` / ``telemetry_windows.csv``."""
    override = os.getenv("TELEMETRY_CSV_PATH")
    if override:
        return Path(override)
    data_dir = os.getenv("DATA_DIR", "data")
    return _REPO_ROOT / data_dir / "telemetry_windows.csv"


def telemetry_archive_dir() -> Path:
    """Directory where rotated telemetry CSVs are stored (matches oracle)."""
    data_dir = os.getenv("DATA_DIR", "data")
    return _REPO_ROOT / data_dir / TELEMETRY_ARCHIVE_SUBDIR


def list_telemetry_session_files() -> list[tuple[str, Path]]:
    """Return (label, path): active ``telemetry_windows.csv`` first, then archived sessions newest first."""
    current = telemetry_csv_path()
    entries: list[tuple[str, Path]] = [("Current (active)", current)]
    arch = telemetry_archive_dir()
    if arch.is_dir():
        archived = sorted(
            arch.glob("telemetry_windows_*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in archived:
            entries.append((p.name, p))
    return entries


def open_past_sessions_folder() -> Optional[str]:
    """Create the telemetry archive directory if needed and open it in the OS file manager."""
    arch = telemetry_archive_dir()
    try:
        arch.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        LOG.warning("Could not create telemetry archive dir: %s", e)
        return str(e)
    p = arch.resolve()
    try:
        if sys.platform == "win32":
            subprocess.Popen(f'explorer "{p}"', shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return None
    except Exception as e:
        LOG.warning("Could not open past sessions folder: %s", e)
        return str(e)


def anchoring_log_csv_path() -> Path:
    """Default matches oracle ``ANCHORING_LOG_PATH`` / ``DATA_DIR`` / ``anchoring_log.csv``."""
    override = os.getenv("ANCHORING_LOG_PATH")
    if override:
        return Path(override)
    data_dir = os.getenv("DATA_DIR", "data")
    return _REPO_ROOT / data_dir / "anchoring_log.csv"


def anchor_log_txt_path() -> Path:
    """Legacy text anchor log under ``DATA_DIR``."""
    data_dir = os.getenv("DATA_DIR", "data")
    override = os.getenv("ANCHOR_LOG_PATH")
    if override:
        return Path(override)
    return _REPO_ROOT / data_dir / "anchor_log.txt"


def deployment_localhost_json_path() -> Path:
    return _REPO_ROOT / "contracts" / "deployments" / "localhost.json"


def build_results_export_zip(
    metrics: Optional[dict[str, Any]],
    *,
    sim_config_path: Optional[Path] = None,
    telemetry_csv_path_override: Optional[Path] = None,
    anchoring_log_path_override: Optional[Path] = None,
    deployment_json_override: Optional[Path] = None,
    anchor_txt_override: Optional[Path] = None,
) -> tuple[bytes, str]:
    """Bundle live metrics (including hashes), config, and CSV artifacts into a zip for download."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"iot-oracle-export-{ts}.zip"
    buf = io.BytesIO()
    sim_p = sim_config_path if sim_config_path is not None else SIM_CONFIG_PATH
    tel_p = telemetry_csv_path_override if telemetry_csv_path_override is not None else telemetry_csv_path()
    anch_p = anchoring_log_path_override if anchoring_log_path_override is not None else anchoring_log_csv_path()
    deploy_p = deployment_json_override if deployment_json_override is not None else deployment_localhost_json_path()
    anchor_txt_p = anchor_txt_override if anchor_txt_override is not None else anchor_log_txt_path()

    summary: dict[str, Any] = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "oracle_url": ORACLE_URL,
        "z_threshold": Z_THRESHOLD,
        "files_included": [],
        "paths": {
            "sim_config": str(sim_p.resolve()),
            "telemetry_windows_csv": str(tel_p.resolve()),
            "anchoring_log_csv": str(anch_p.resolve()),
            "anchor_log_txt": str(anchor_txt_p.resolve()),
            "deployment_localhost_json": str(deploy_p.resolve()),
        },
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "metrics.json",
            json.dumps(
                metrics if metrics is not None else {"error": "metrics unavailable"},
                indent=2,
                default=str,
            ),
        )
        summary["files_included"].append("metrics.json")

        if sim_p.is_file():
            zf.writestr("sim_config.json", sim_p.read_text(encoding="utf-8"))
            summary["files_included"].append("sim_config.json")

        if tel_p.is_file():
            zf.writestr("telemetry_windows.csv", tel_p.read_text(encoding="utf-8"))
            summary["files_included"].append("telemetry_windows.csv")

        if anch_p.is_file():
            zf.writestr("anchoring_log.csv", anch_p.read_text(encoding="utf-8"))
            summary["files_included"].append("anchoring_log.csv")

        if anchor_txt_p.is_file():
            zf.writestr("anchor_log.txt", anchor_txt_p.read_text(encoding="utf-8"))
            summary["files_included"].append("anchor_log.txt")

        if deploy_p.is_file():
            zf.writestr("deployment_localhost.json", deploy_p.read_text(encoding="utf-8"))
            summary["files_included"].append("deployment_localhost.json")

        zf.writestr("export_manifest.json", json.dumps(summary, indent=2, default=str))

    buf.seek(0)
    return buf.getvalue(), filename


def load_telemetry_csv(path: Optional[Path] = None) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """Load window CSV; return (df, error_message). Error set if unreadable or missing columns."""
    path = telemetry_csv_path() if path is None else path
    if not path.is_file():
        if DEBUG:
            return (
                None,
                f"CSV not found: `{path}` (set TELEMETRY_CSV_PATH or run the oracle to create it).",
            )
        return None, "Telemetry CSV not found. Run the oracle or set TELEMETRY_CSV_PATH."
    try:
        df = pd.read_csv(path)
    except Exception as e:
        LOG.warning("Failed to read telemetry CSV %s: %s", path, e)
        if DEBUG:
            return None, f"Could not read CSV: {e}"
        return None, f"Could not read CSV: {sanitize_exception(e, fallback='read_failed')}"
    if df.empty:
        return df, None
    required = {"window_end_ms", "msgs_per_sec", "z_score"}
    missing = required - set(df.columns)
    if missing:
        return None, f"CSV missing columns {sorted(missing)}; expected at least {sorted(required)}."
    return df, None


st.title("IoT Oracle Gateway")
st.caption("Live metrics from the oracle `/metrics` endpoint.")

st_autorefresh(interval=AUTO_REFRESH_MS, key="metrics_autorefresh")

cfg = load_sim_config()
data, err = fetch_metrics()

tel_entries = list_telemetry_session_files()
tel_path_strs = [str(p.resolve()) for _, p in tel_entries]
if tel_path_strs and "dash_telemetry_csv" not in st.session_state:
    st.session_state.dash_telemetry_csv = tel_path_strs[0]


def _telemetry_label_for(path_str: str) -> str:
    for lbl, p in tel_entries:
        try:
            if str(p.resolve()) == path_str:
                return lbl
        except OSError:
            if str(p) == path_str:
                return lbl
    return redact_path(path_str) if not DEBUG else path_str


with st.sidebar:
    st.header("Simulator")
    st.caption("Save config, then start.")
    nd_col, int_col = st.columns(2)
    with nd_col:
        n_devices = st.number_input(
            "N_DEVICES",
            min_value=1,
            max_value=1000,
            value=int(cfg.get("N_DEVICES", 5)),
            step=1,
        )
    with int_col:
        interval_sec = st.number_input(
            "INTERVAL_SEC",
            min_value=0.1,
            max_value=3600.0,
            value=float(cfg.get("INTERVAL_SEC", 1.0)),
            step=0.1,
        )
    burst_enabled = st.checkbox(
        "BURST_ENABLED",
        value=_as_bool(cfg.get("BURST_ENABLED", False)),
    )
    burst_cols = st.columns(2)
    with burst_cols[0]:
        burst_start_sec = st.number_input(
            "Burst start (s)",
            min_value=0,
            max_value=86400,
            value=int(cfg.get("BURST_START_SEC", 60)),
            step=1,
        )
    with burst_cols[1]:
        burst_duration_sec = st.number_input(
            "Burst duration (s)",
            min_value=1,
            max_value=86400,
            value=int(cfg.get("BURST_DURATION_SEC", 20)),
            step=1,
        )
    bm_col, rt_col = st.columns(2)
    with bm_col:
        burst_multiplier = st.number_input(
            "Burst mult",
            min_value=0.1,
            max_value=100.0,
            value=float(cfg.get("BURST_MULTIPLIER", 5.0)),
            step=0.1,
        )
    with rt_col:
        max_runtime_sec = st.number_input(
            "Max runtime (s)",
            min_value=0.0,
            max_value=86400.0,
            value=0.0,
            step=1.0,
            key="dash_max_runtime_sec",
            help="0 = run until Stop. Passed as --max-runtime-sec when starting the simulator.",
        )
    st.markdown("<div class='sidebar-section-gap'></div>", unsafe_allow_html=True)
    op_col, cfg_col = st.columns(2)
    with op_col:
        st.text_input(
            "Oracle",
            value=ORACLE_URL if DEBUG else f"...{redact_url(ORACLE_URL)}",
            disabled=True,
        )
    with cfg_col:
        st.text_input(
            "Config",
            value=str(SIM_CONFIG_PATH) if DEBUG else redact_path(str(SIM_CONFIG_PATH)),
            disabled=True,
        )

    if st.button("Save config", type="primary", use_container_width=True, key="dash_save_config"):
        payload = {
            "N_DEVICES": int(n_devices),
            "INTERVAL_SEC": float(interval_sec),
            "BURST_ENABLED": bool(burst_enabled),
            "BURST_START_SEC": int(burst_start_sec),
            "BURST_DURATION_SEC": int(burst_duration_sec),
            "BURST_MULTIPLIER": float(burst_multiplier),
        }
        try:
            save_sim_config(payload)
            if DEBUG:
                st.success(f"Saved to `{SIM_CONFIG_PATH}`")
            else:
                st.success(f"Saved `{redact_path(str(SIM_CONFIG_PATH))}`")
        except OSError as e:
            LOG.exception("Failed to write sim config")
            if DEBUG:
                st.warning(f"Could not write config file: {e}")
            else:
                st.warning("Could not write config file.")

    st.markdown("<div class='sidebar-section-gap'></div>", unsafe_allow_html=True)
    running = _simulator_running()
    chip = (
        "<span class='status-chip status-ok'>Running</span>"
        if running
        else "<span class='status-chip status-warn'>Stopped</span>"
    )
    st.markdown(
        f"<p class='sidebar-run-line'><strong>Simulator run</strong> &nbsp; {chip}</p>",
        unsafe_allow_html=True,
    )

    start_col, stop_col = st.columns(2, gap="small")
    with start_col:
        if st.button(
            "Start simulator",
            type="primary",
            disabled=running,
            use_container_width=True,
            key="dash_start_sim",
        ):
            if _simulator_running():
                st.warning("Simulator is already running. Stop it first or use the other console.")
            elif not SIM_CONFIG_PATH.is_file():
                if DEBUG:
                    st.warning(f"Save config first (missing `{SIM_CONFIG_PATH}`).")
                else:
                    st.warning("Save config first (simulator config file missing).")
            else:
                cmd = [
                    sys.executable,
                    "-m",
                    "simulator.iot_simulator",
                    "--config",
                    str(SIM_CONFIG_PATH),
                ]
                if max_runtime_sec > 0:
                    cmd.extend(["--max-runtime-sec", str(max_runtime_sec)])
                try:
                    st.session_state.sim_proc = _popen_simulator(cmd)
                    st.success("Simulator started.")
                    st.rerun()
                except OSError as e:
                    LOG.exception("Failed to start simulator")
                    if DEBUG:
                        st.error(f"Could not start simulator: {e}")
                    else:
                        st.error("Could not start simulator.")
    with stop_col:
        if st.button(
            "Stop simulator",
            disabled=not running,
            use_container_width=True,
            key="dash_stop_sim",
        ):
            proc = st.session_state.sim_proc
            if proc is None or proc.poll() is not None:
                st.session_state.sim_proc = None
                st.info("Simulator was not running.")
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                st.session_state.sim_proc = None
                st.success("Simulator stopped.")
                st.rerun()

    st.markdown("<div class='sidebar-btn-row-gap'></div>", unsafe_allow_html=True)
    ref_col, past_col = st.columns(2, gap="small")
    with ref_col:
        if st.button("Refresh", use_container_width=True, key="dash_refresh_metrics"):
            st.rerun()
    with past_col:
        if st.button(
            "Past sessions",
            use_container_width=True,
            key="dash_open_past_sessions",
            help="Open the telemetry archive folder on disk (rotated session CSVs).",
        ):
            err = open_past_sessions_folder()
            if err:
                st.warning(f"Could not open folder: {err}")
            else:
                st.toast("Opened past sessions folder", icon="📂")

    if tel_path_strs:
        cur = st.session_state.get("dash_telemetry_csv", tel_path_strs[0])
        if cur not in tel_path_strs:
            cur = tel_path_strs[0]
            st.session_state.dash_telemetry_csv = cur
        t_idx = tel_path_strs.index(cur)
        selected_telemetry_str = st.selectbox(
            "Telemetry session",
            tel_path_strs,
            index=t_idx,
            format_func=_telemetry_label_for,
            key="dash_telemetry_session_select",
            help="History chart and export use this file. Pick archived runs after rotation.",
        )
        st.session_state.dash_telemetry_csv = selected_telemetry_str

    try:
        tel_for_export = (
            Path(st.session_state.dash_telemetry_csv)
            if tel_path_strs and st.session_state.get("dash_telemetry_csv")
            else None
        )
        export_zip_bytes, export_zip_name = build_results_export_zip(
            data,
            telemetry_csv_path_override=tel_for_export,
        )
    except Exception as ex:
        LOG.exception("Failed to build export zip")
        err_buf = io.BytesIO()
        with zipfile.ZipFile(err_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("EXPORT_ERROR.txt", str(ex))
        err_buf.seek(0)
        export_zip_bytes, export_zip_name = err_buf.getvalue(), "iot-oracle-export-error.zip"

    st.download_button(
        label="Export results",
        data=export_zip_bytes,
        file_name=export_zip_name,
        mime="application/zip",
        type="primary",
        use_container_width=True,
        key="dash_export_results",
        help="Download a zip: live /metrics (hashes), sim_config.json, telemetry_windows.csv, anchoring_log.csv, deployment record, and export_manifest.json.",
    )

if err:
    st.warning(err)
    st.info("Start the oracle with: `python -m oracle.service` (or your usual command).")

if data is None:
    c1 = c2 = c3 = c4 = lat = zv = anom = "—"
    anchor = {}
else:
    c1 = _dash(data.get("verified_count"))
    c2 = _dash(data.get("rejected_count"))
    c3 = _dash(data.get("msgs_per_sec"))
    c4 = _dash(data.get("msg_count"))
    zv = _dash(data.get("z_score"))
    lat = _dash(data.get("avg_latency_ms"))
    anom = _dash(data.get("is_anomaly"))
    anchor = data.get("last_anchor_info") or {}

if data is None:
    a_batch = a_tx = a_success = a_skipped = a_error = a_block = "—"
else:
    a_batch = anchor.get("batch_hash") or "—"
    a_tx = anchor.get("tx_hash") or "—"
    a_success = _dash(anchor.get("success"))
    a_skipped = _dash(anchor.get("skipped"))
    a_error = _dash(anchor.get("error"))
    a_block = _dash(anchor.get("block_number"))

st.markdown("<div class='summary-grid'>", unsafe_allow_html=True)
cat_traffic, cat_anomaly, cat_anchoring = st.columns(3)

with cat_traffic:
    st.markdown("<div class='group-card'>", unsafe_allow_html=True)
    st.markdown("<div class='metric-group-title'>Traffic Metrics</div>", unsafe_allow_html=True)
    t1, t2 = st.columns(2)
    with t1:
        st.markdown(
            _metric_card(
                "Verified Messages",
                c1,
                "Total telemetry messages that passed HMAC and schema verification.",
                "verified",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _metric_card(
                "Messages Per Second",
                c3,
                "Throughput in the latest finalized telemetry window.",
                "mps",
            ),
            unsafe_allow_html=True,
        )
    with t2:
        st.markdown(
            _metric_card(
                "Rejected Messages",
                c2,
                "Total telemetry messages rejected due to invalid JSON, HMAC, or schema checks.",
                "rejected",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _metric_card(
                "Window Message Count",
                c4,
                "Number of telemetry messages in the latest finalized window.",
                "window_count",
            ),
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

with cat_anomaly:
    st.markdown("<div class='group-card'>", unsafe_allow_html=True)
    st.markdown("<div class='metric-group-title'>Latency and Anomaly</div>", unsafe_allow_html=True)
    a1, a2 = st.columns(2)
    with a1:
        st.markdown(
            _metric_card(
                "Average Latency (ms)",
                lat,
                "Mean ingest latency in milliseconds for messages in the latest finalized window.",
                "latency",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _metric_card(
                "Anomaly Flag (0/1)",
                anom,
                "1 means anomaly detected in the latest window; 0 means normal behavior.",
                "anomaly_flag",
            ),
            unsafe_allow_html=True,
        )
    with a2:
        st.markdown(
            _metric_card(
                "Z-Score",
                zv,
                "EWMA z-score for latest throughput; larger absolute values indicate stronger deviation from baseline.",
                "z_score",
            ),
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

with cat_anchoring:
    st.markdown("<div class='group-card'>", unsafe_allow_html=True)
    st.markdown("<div class='metric-group-title'>Anchoring Status</div>", unsafe_allow_html=True)
    an1, an2, an3 = st.columns(3)
    with an1:
        st.markdown(
            _metric_card(
                "Anchor Success",
                a_success,
                "Whether the latest anchoring attempt succeeded.",
                "anchor_success",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _metric_card(
                "Skipped Anchor",
                a_skipped,
                "True when anchoring tick was skipped because there were no pending windows.",
                "anchor_skipped",
            ),
            unsafe_allow_html=True,
        )
    with an2:
        st.markdown(
            _metric_card(
                "Batch Hash",
                a_batch,
                "Hash of the telemetry batch submitted for blockchain anchoring.",
                "batch_hash",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _metric_card(
                "Transaction Hash",
                a_tx,
                "Blockchain transaction hash for the latest anchoring attempt.",
                "tx_hash",
            ),
            unsafe_allow_html=True,
        )
    with an3:
        st.markdown(
            _metric_card(
                "Block Number",
                a_block,
                "Block number containing the latest successful anchoring transaction.",
                "block_number",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _metric_card(
                "Anchor Error",
                a_error if a_error and a_error != "None" else "—",
                "Error from the latest anchoring attempt, if any.",
                "anchor_error",
            ),
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

st.subheader("Window history (telemetry_windows.csv)")
selected_csv = Path(
    st.session_state.get("dash_telemetry_csv", str(telemetry_csv_path().resolve()))
)
st.caption(
    f"Selected: `"
    f"{selected_csv if DEBUG else redact_path(str(selected_csv))}"
    f"`. Reloads on every rerun (auto-refresh ~{AUTO_REFRESH_MS // 1000}s). "
    f"Anomaly threshold Z_THRESHOLD={Z_THRESHOLD} (env, match oracle)."
)

df_csv, csv_err = load_telemetry_csv(selected_csv)
if csv_err:
    st.warning(csv_err)
elif df_csv is None:
    st.info("No CSV data.")
elif df_csv.empty:
    st.info("CSV has no data rows yet.")
else:
    tdf = df_csv.copy()
    tdf["t"] = pd.to_datetime(tdf["window_end_ms"], unit="ms", utc=True)
    st.markdown("**Throughput (msgs/s) over time**")
    st.line_chart(tdf.set_index("t")[["msgs_per_sec"]], height=245)
    st.markdown("**Z-score over time** (second series = threshold)")
    zplot = tdf.set_index("t")[["z_score"]].copy()
    zplot["threshold"] = Z_THRESHOLD
    st.line_chart(zplot, height=245)
