#!/usr/bin/env bash
set -euo pipefail

# Phase 7.1 burst experiment runner (human-assisted).
# Expected behavior:
# - msgs_per_sec rises during burst window
# - z_score rises during burst
# - is_anomaly becomes 1 in at least one window
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
# This script starts only the simulator for the burst run.

RUN_SECONDS="${1:-180}"  # default 3 minutes

echo "Starting BURST experiment (Phase 7.1)"
echo "Params:"
echo "  N_DEVICES=8 INTERVAL_SEC=1"
echo "  BURST_ENABLED=true BURST_START_SEC=60 BURST_DURATION_SEC=20 BURST_MULTIPLIER=5"
echo "Duration: ${RUN_SECONDS}s"
echo
echo "If prerequisites are not running yet, stop now (Ctrl+C) and start them first."
sleep 2

if command -v timeout >/dev/null 2>&1; then
  N_DEVICES=8 \
  INTERVAL_SEC=1 \
  BURST_ENABLED=true \
  BURST_START_SEC=60 \
  BURST_DURATION_SEC=20 \
  BURST_MULTIPLIER=5 \
  timeout "${RUN_SECONDS}" python3 -m simulator.iot_simulator || true
elif command -v gtimeout >/dev/null 2>&1; then
  N_DEVICES=8 \
  INTERVAL_SEC=1 \
  BURST_ENABLED=true \
  BURST_START_SEC=60 \
  BURST_DURATION_SEC=20 \
  BURST_MULTIPLIER=5 \
  gtimeout "${RUN_SECONDS}" python3 -m simulator.iot_simulator || true
else
  echo "No timeout tool found (timeout/gtimeout). Running until Ctrl+C."
  N_DEVICES=8 \
  INTERVAL_SEC=1 \
  BURST_ENABLED=true \
  BURST_START_SEC=60 \
  BURST_DURATION_SEC=20 \
  BURST_MULTIPLIER=5 \
  python3 -m simulator.iot_simulator
fi

echo
echo "Burst run ended. Check:"
echo "- data/telemetry_windows.csv (spike in msgs_per_sec, z_score rise, is_anomaly=1)"
echo "- GET /metrics from oracle for latest anomaly status"
