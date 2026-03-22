"""Streamlit dashboard: oracle /metrics polling and simulator parameter sidebar (config save in phase 6.2)."""

from __future__ import annotations

import os
from typing import Any, Optional

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

ORACLE_URL = os.getenv("ORACLE_URL", "http://127.0.0.1:8000").rstrip("/")
METRICS_TIMEOUT_SEC = 2.0
AUTO_REFRESH_MS = 5000

st.set_page_config(page_title="IoT Oracle Dashboard", layout="wide")


def _dash(v: Any) -> str:
    if v is None:
        return "—"
    return str(v)


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

with st.sidebar:
    st.header("Simulator parameters")
    st.caption("Values shown for the next phase (6.2); run the simulator separately with matching env.")
    n_devices = st.number_input("N_DEVICES", min_value=1, max_value=1000, value=5, step=1)
    interval_sec = st.number_input("INTERVAL_SEC", min_value=0.1, max_value=3600.0, value=1.0, step=0.1)
    burst_enabled = st.checkbox("BURST_ENABLED", value=False)
    burst_start_sec = st.number_input("BURST_START_SEC", min_value=0, max_value=86400, value=60, step=1)
    burst_duration_sec = st.number_input("BURST_DURATION_SEC", min_value=1, max_value=86400, value=20, step=1)
    burst_multiplier = st.number_input("BURST_MULTIPLIER", min_value=0.1, max_value=100.0, value=5.0, step=0.1)
    st.text_input("ORACLE_URL (read-only)", value=ORACLE_URL, disabled=True)
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
