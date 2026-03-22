"""Streamlit dashboard: oracle /metrics polling and simulator config (config/sim_config.json)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

LOG = logging.getLogger(__name__)

ORACLE_URL = os.getenv("ORACLE_URL", "http://127.0.0.1:8000").rstrip("/")
METRICS_TIMEOUT_SEC = 2.0
AUTO_REFRESH_MS = 5000

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SIM_CONFIG = _REPO_ROOT / "config" / "sim_config.json"
SIM_CONFIG_PATH = Path(os.getenv("SIM_CONFIG_PATH", str(_DEFAULT_SIM_CONFIG)))

st.set_page_config(page_title="IoT Oracle Dashboard", layout="wide")


def _dash(v: Any) -> str:
    if v is None:
        return "—"
    return str(v)


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes")


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
            return None, f"HTTP {r.status_code} from {url}"
        return r.json(), None
    except requests.RequestException as e:
        return None, f"Cannot reach oracle at {url}: {e}"


st.title("IoT Oracle Gateway")
st.caption("Live metrics from the oracle `/metrics` endpoint. Start the oracle on port 8000 (default).")

st_autorefresh(interval=AUTO_REFRESH_MS, key="metrics_autorefresh")

cfg = load_sim_config()

with st.sidebar:
    st.header("Simulator parameters")
    st.caption(
        "Save writes **`config/sim_config.json`** (repo root). Run the simulator in another terminal; "
        "this app does not start or stop it."
    )
    n_devices = st.number_input(
        "N_DEVICES",
        min_value=1,
        max_value=1000,
        value=int(cfg.get("N_DEVICES", 5)),
        step=1,
    )
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
    burst_start_sec = st.number_input(
        "BURST_START_SEC",
        min_value=0,
        max_value=86400,
        value=int(cfg.get("BURST_START_SEC", 60)),
        step=1,
    )
    burst_duration_sec = st.number_input(
        "BURST_DURATION_SEC",
        min_value=1,
        max_value=86400,
        value=int(cfg.get("BURST_DURATION_SEC", 20)),
        step=1,
    )
    burst_multiplier = st.number_input(
        "BURST_MULTIPLIER",
        min_value=0.1,
        max_value=100.0,
        value=float(cfg.get("BURST_MULTIPLIER", 5.0)),
        step=0.1,
    )
    st.text_input("ORACLE_URL (read-only)", value=ORACLE_URL, disabled=True)
    st.text_input("Config file path (read-only)", value=str(SIM_CONFIG_PATH), disabled=True)

    if st.button("Save config", type="primary"):
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
            st.success(f"Saved to `{SIM_CONFIG_PATH}`")
        except OSError as e:
            LOG.exception("Failed to write sim config")
            st.warning(f"Could not write config file: {e}")

    if st.button("Refresh metrics now"):
        st.rerun()

data, err = fetch_metrics()

if err:
    st.warning(err)
    st.info("Start the oracle with: `python -m oracle.service` (or your usual command).")

col1, col2, col3, col4 = st.columns(4)
if data is None:
    c1 = c2 = c3 = c4 = "—"
    zv = lat = "—"
    anom = "—"
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

with col1:
    st.metric("Verified messages", c1)
with col2:
    st.metric("Rejected messages", c2)
with col3:
    st.metric("Msgs/s (latest window)", c3)
with col4:
    st.metric("Msg count (window)", c4)

st.subheader("Latency and anomaly")
lat_col, z_col, anom_col = st.columns(3)
with lat_col:
    st.metric("Avg latency (ms)", lat)
with z_col:
    st.metric("Z-score", zv)
with anom_col:
    st.metric("Is anomaly (0/1)", anom)

st.subheader("Anchoring")
if data is None:
    st.write("**batch_hash:** —")
    st.write("**tx_hash:** —")
    st.write("**success:** —")
    st.write("**skipped:** —")
    st.write("**error:** —")
else:
    st.write(f"**batch_hash:** `{anchor.get('batch_hash')}`" if anchor.get("batch_hash") else "**batch_hash:** —")
    st.write(f"**tx_hash:** `{anchor.get('tx_hash')}`" if anchor.get("tx_hash") else "**tx_hash:** —")
    st.write(f"**success:** {_dash(anchor.get('success'))}")
    st.write(f"**skipped:** {_dash(anchor.get('skipped'))}")
    st.write(f"**error:** {_dash(anchor.get('error'))}")
    if anchor.get("block_number") is not None:
        st.write(f"**block_number:** {_dash(anchor.get('block_number'))}")
