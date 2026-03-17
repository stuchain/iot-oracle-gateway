# IoT Oracle Gateway

IoT telemetry pipeline: a simulator publishes telemetry over MQTT; the oracle ingests it, aggregates in windows, runs anomaly detection (e.g. EWMA + z-score), and anchors hashes on-chain; a dashboard shows metrics. Built to stay simple and easy to run bare-metal (containerization can come later).

## Prerequisites

- **Python** 3.10+
- **Node.js** and **npm**
- **Ganache** (CLI or GUI) for local Ethereum
- **Mosquitto** for MQTT

## Components

- **simulator/** – IoT producer script(s)
- **oracle/** – Gateway service (MQTT ingest, windowing, anomaly detection, anchoring)
- **contracts/** – Hardhat project and Solidity anchor contract (placeholder only; real contract and deploy script in Phase 5)
- **dashboard/** – Streamlit app for metrics

### Simulator

Run the telemetry simulator (requires Mosquitto or another MQTT broker):

```bash
python -m simulator.iot_simulator
```

Config via env or CLI: `N_DEVICES`, `INTERVAL_SEC`, `MQTT_HOST`, `MQTT_PORT`, `HMAC_SECRET`. Subscribe to telemetry with:

```bash
mosquitto_sub -t 'iot/devices/+/telemetry'
```

**Burst scenario:** To trigger a higher message rate during a time window (e.g. for anomaly evaluation), run for ~2 minutes with burst at 60s for 20s:

```bash
BURST_ENABLED=1 BURST_START_SEC=60 BURST_DURATION_SEC=20 BURST_MULTIPLIER=5 python -m simulator.iot_simulator
```

Message rate increases during the burst (60–80s); you can observe it via `mosquitto_sub` or oracle metrics.

Run instructions for the other components will be added in later phases.
