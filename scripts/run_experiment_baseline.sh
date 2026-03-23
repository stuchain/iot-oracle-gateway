#!/usr/bin/env bash
set -euo pipefail

# Phase 7.1 baseline experiment runner (human-assisted).
# Expected behavior:
# - Stable msgs_per_sec (roughly N_DEVICES / INTERVAL_SEC)
# - Low z_score values
# - is_anomaly mostly 0
#
# Prerequisites (start these in separate terminals):
# 1) Mosquitto: mosquitto -c mosquitto/mosquitto.conf
# 2) Ganache:   npx ganache --port 8545
# 3) Deploy contract if needed:
#      cd contracts && npm install && npx hardhat compile
#      npx hardhat run scripts/deploy.js --network localhost
# 4) Oracle:    python3 -m oracle.service
# 5) Optional dashboard: streamlit run dashboard/app.py
#
# This script starts only the simulator for the baseline run.

RUN_SECONDS="${1:-180}"  # default 3 minutes

echo "Starting BASELINE experiment (Phase 7.1)"
echo "Params: N_DEVICES=8 INTERVAL_SEC=1 BURST_ENABLED=false"
echo "Duration: ${RUN_SECONDS}s"
echo
echo "If prerequisites are not running yet, stop now (Ctrl+C) and start them first."
sleep 2

if command -v timeout >/dev/null 2>&1; then
  N_DEVICES=8 \
  INTERVAL_SEC=1 \
  BURST_ENABLED=false \
  timeout "${RUN_SECONDS}" python3 -m simulator.iot_simulator || true
elif command -v gtimeout >/dev/null 2>&1; then
  N_DEVICES=8 \
  INTERVAL_SEC=1 \
  BURST_ENABLED=false \
  gtimeout "${RUN_SECONDS}" python3 -m simulator.iot_simulator || true
else
  echo "No timeout tool found (timeout/gtimeout). Running until Ctrl+C."
  N_DEVICES=8 \
  INTERVAL_SEC=1 \
  BURST_ENABLED=false \
  python3 -m simulator.iot_simulator
fi

echo
echo "Baseline run ended. Check:"
echo "- data/telemetry_windows.csv (msgs_per_sec stability, low z_score)"
echo "- GET /metrics from oracle for latest window + anomaly fields"
