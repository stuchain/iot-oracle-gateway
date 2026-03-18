# IoT Oracle Gateway

IoT telemetry pipeline: a simulator publishes telemetry over MQTT; the oracle ingests it, aggregates in windows, runs anomaly detection (e.g. EWMA + z-score), and anchors hashes on-chain; a dashboard shows metrics. Built to stay simple and easy to run bare-metal (containerization can come later).

## Prerequisites

- **Python** 3.10+
- **Node.js** and **npm**
- **Ganache** (CLI or GUI) for local Ethereum
- **Mosquitto** for MQTT

## Running Mosquitto

Start the MQTT broker using the project config (default port **1883**; simulator and oracle use `localhost:1883` unless overridden):

```bash
mosquitto -c mosquitto/mosquitto.conf
```

To subscribe and verify telemetry (e.g. after starting the simulator):

```bash
mosquitto_sub -h localhost -p 1883 -t 'iot/devices/+/telemetry' -v
```

## Manual MQTT sanity test

To confirm the simulator publishes as expected and the broker delivers messages:

1. **Start Mosquitto:** `mosquitto -c mosquitto/mosquitto.conf`
2. **Start the simulator** (e.g. with 2 devices, 1s interval):  
   `N_DEVICES=2 INTERVAL_SEC=1 python -m simulator.iot_simulator`  
   (On Windows: `set N_DEVICES=2 && set INTERVAL_SEC=1 && python -m simulator.iot_simulator`)
3. **In another terminal**, run:  
   `mosquitto_sub -h localhost -p 1883 -t 'iot/devices/+/telemetry' -v`
4. **Expect** JSON messages with fields: `device_id`, `ts_ms`, `temp_c`, `humidity_pct`, `power_w`, `hmac`.

**Topic pattern (copy-paste):** `iot/devices/+/telemetry`  
**Example topics:** `iot/devices/dev-01/telemetry`, `iot/devices/dev-02/telemetry`, etc.

**Sample telemetry JSON (one line):**

```json
{"device_id":"dev-01","ts_ms":1710000000000,"temp_c":24.5,"humidity_pct":55.0,"power_w":42.0,"hmac":"a1b2c3..."}
```

This is documented steps only; no automated tests are added for this sanity check.

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

Config via env or CLI: `N_DEVICES`, `INTERVAL_SEC`, `MQTT_HOST`, `MQTT_PORT`, `HMAC_SECRET`. Subscribe to telemetry with (see also "Running Mosquitto" above):

```bash
mosquitto_sub -h localhost -p 1883 -t 'iot/devices/+/telemetry' -v
```

**Burst scenario:** To trigger a higher message rate during a time window (e.g. for anomaly evaluation), run for ~2 minutes with burst at 60s for 20s:

```bash
BURST_ENABLED=1 BURST_START_SEC=60 BURST_DURATION_SEC=20 BURST_MULTIPLIER=5 python -m simulator.iot_simulator
```

Message rate increases during the burst (60–80s); you can observe it via `mosquitto_sub` or oracle metrics.

Run instructions for the other components will be added in later phases.
