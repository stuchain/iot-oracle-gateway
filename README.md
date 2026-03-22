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
- **contracts/** – Hardhat project and `TelemetryAnchor` Solidity contract; deploy with Ganache on port 8545 (see “Deploying TelemetryAnchor” below)
- **dashboard/** – Streamlit UI for oracle metrics and simulator parameters. With the oracle listening on port **8000** (default), run: `streamlit run dashboard/app.py`. Set **`ORACLE_URL`** if the API is elsewhere.

### Using the dashboard

The dashboard **does not** start or stop the simulator (or Mosquitto); it only reads oracle metrics and can write simulator settings to disk.

1. Start **Mosquitto** (see [Running Mosquitto](#running-mosquitto)).
2. Start the **oracle** in one terminal: `python -m oracle.service` (or your usual command; default HTTP **8000**).
3. Start the **dashboard** in another terminal: `streamlit run dashboard/app.py`.
4. In the sidebar, set **N_DEVICES**, **INTERVAL_SEC**, and optional burst fields, then click **Save config**. This creates or updates **`config/sim_config.json`** at the repo root (override with env **`SIM_CONFIG_PATH`** if needed).
5. Start the **simulator** in a **third** terminal from the repo root (after saving):

   ```bash
   python -m simulator.iot_simulator --config config/sim_config.json
   ```

   The simulator reads that JSON; you can still use env vars or CLI flags for other options (e.g. `MQTT_HOST`, `HMAC_SECRET`). Without `--config`, the simulator uses environment defaults only.

6. **Charts** (throughput and z-score over time) read **`data/telemetry_windows.csv`** on every Streamlit rerun (including auto-refresh). Override with **`TELEMETRY_CSV_PATH`** or **`DATA_DIR`** if needed; **`Z_THRESHOLD`** in the environment should match the oracle for the threshold line.

### Deploying TelemetryAnchor (local Ganache)

The oracle (later phases) sends batch hashes to the `TelemetryAnchor` contract on a local chain. **Ganache must be listening on port 8545** before you deploy; if it is not running, Hardhat will fail to connect (e.g. connection refused).

1. **Start Ganache** on **http://127.0.0.1:8545** (default port **8545**):
   - **CLI:** `npx ganache --port 8545` (or `ganache-cli -p 8545` if you use the legacy package name)
   - **GUI:** Ganache, create a workspace with **8545** as the server port
2. **In another terminal**, from the project root:

   ```bash
   cd contracts
   npm install
   npx hardhat compile
   npx hardhat run scripts/deploy.js --network localhost
   ```

3. The script prints the deployed address and writes **`contracts/deployments/localhost.json`** (ignored by git) with `contractAddress`, `rpcUrl`, and `chainId`.  
4. **For the oracle**, point the deployed address (and later the ABI) at your config or env. For example, set **`CONTRACT_ADDRESS`** to the printed address, or keep a local **`oracle/contract.json`** (see Phase 5 anchoring docs) when that file is wired.

**Hardhat network:** `localhost` in [`contracts/hardhat.config.js`](contracts/hardhat.config.js) uses `http://127.0.0.1:8545`, matching Ganache’s default host/port.

**CI (automated deploy check):** On push and pull requests, [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `npm ci`, `hardhat compile`, `hardhat test`, then starts **`npx hardhat node`** in the background (same host/port as above), runs `scripts/deploy.js --network localhost`, and asserts `contracts/deployments/localhost.json` contains a valid `contractAddress`. That replaces the manual “chain running + deploy succeeds” check for regressions; use Ganache or Hardhat node locally when developing.

### Simulator

Run the telemetry simulator (requires Mosquitto or another MQTT broker):

```bash
python -m simulator.iot_simulator
```

Config via env or CLI: `N_DEVICES`, `INTERVAL_SEC`, `MQTT_HOST`, `MQTT_PORT`, `HMAC_SECRET`. To use parameters saved from the dashboard, pass **`--config config/sim_config.json`** (see [Using the dashboard](#using-the-dashboard)). Subscribe to telemetry with (see also "Running Mosquitto" above):

```bash
mosquitto_sub -h localhost -p 1883 -t 'iot/devices/+/telemetry' -v
```

**Burst scenario:** To trigger a higher message rate during a time window (e.g. for anomaly evaluation), run for ~2 minutes with burst at 60s for 20s:

```bash
BURST_ENABLED=1 BURST_START_SEC=60 BURST_DURATION_SEC=20 BURST_MULTIPLIER=5 python -m simulator.iot_simulator
```

Message rate increases during the burst (60–80s); you can observe it via `mosquitto_sub` or oracle metrics.

Run instructions for the other components will be added in later phases.
