# IoT Oracle Gateway

## Overview

This project is an end-to-end **IoT telemetry pipeline** for coursework and demos: simulated devices publish signed JSON over **MQTT**; an **oracle** gateway subscribes, verifies **HMAC**, aggregates traffic into fixed **time windows**, and runs **EWMA + z-score** anomaly detection. Window metrics are written to **CSV** and exposed via **`GET /metrics`**. Optional **on-chain anchoring** batches window hashes to a **`TelemetryAnchor`** Solidity contract on a **local** chain (Ganache/Hardhat). A **Streamlit dashboard** can plot throughput and z-scores and save simulator parameters. The stack is intentionally **single-machine** and easy to run without containers. For a concise data-flow description, see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Prerequisites

- **Python** 3.10+
- **Node.js** and **npm** (Hardhat, Ganache CLI)
- **Ganache** (CLI or GUI) for local Ethereum on port **8545**
- **Mosquitto** (or another MQTT broker) on port **1883** by default

## How to run (ordered)

Run from the **repository root** unless noted. Use the **same `HMAC_SECRET`** for the simulator and oracle.

1. **Start Mosquitto** with the project config: `mosquitto -c mosquitto/mosquitto.conf` (see [Running Mosquitto](#running-mosquitto)).
2. **Start Ganache** on `http://127.0.0.1:8545` (e.g. `npx ganache --port 8545`).
3. **Deploy the contract** (optional if you only want MQTT → oracle → CSV without anchoring): from `contracts/`, `npm install`, `npx hardhat compile`, `npx hardhat run scripts/deploy.js --network localhost`. Copy the printed address into **`CONTRACT_ADDRESS`** (or `oracle/contract.json` if you use that workflow).
4. **Start the oracle:** `python -m oracle.service` — HTTP **`/metrics`** defaults to **port 8000** (see [Deploying TelemetryAnchor](#deploying-telemetryanchor-local-ganache) for env).
5. **Start the simulator:** e.g. `python -m simulator.iot_simulator`, or with dashboard-saved config `python -m simulator.iot_simulator --config config/sim_config.json` (see [Simulator](#simulator) and [Using the dashboard](#using-the-dashboard)).
6. **Optional — dashboard:** `streamlit run dashboard/app.py` (reads **`/metrics`** and **`data/telemetry_windows.csv`**).

**Reproducible experiments (Phase 7):** with services up, you can run **`scripts/run_experiment_baseline.sh`** or **`scripts/run_experiment_burst.sh`** (bash/Git Bash), or **`scripts/run_experiment_baseline.ps1`** / **`scripts/run_experiment_burst.ps1`** on Windows, then **`python scripts/plot_results.py`** to generate plots under **`plots/`**.

## Configuration reference

Values load from the environment (and **`.env`** via `python-dotenv` in the oracle). Defaults below match [`oracle/config.py`](oracle/config.py) unless stated.

| Variable | Default / notes |
|----------|-----------------|
| **Oracle — MQTT** | |
| `MQTT_HOST` | `localhost` |
| `MQTT_PORT` | `1883` |
| **Oracle — windows & anomaly** | |
| `WINDOW_SEC` | `5` — window length in seconds |
| `EWMA_ALPHA` | `0.2` — EWMA smoothing |
| `Z_THRESHOLD` | `3.0` — z-score above ⇒ `is_anomaly` |
| **Oracle — HMAC** | |
| `HMAC_SECRET` | `change-me-in-production` — **must match** the simulator |
| **Oracle — anchoring** | |
| `GANACHE_URL` | `http://127.0.0.1:8545` — JSON-RPC for Web3 |
| `CONTRACT_ADDRESS` | empty — if unset, anchoring txs are disabled |
| `CONTRACT_ABI_PATH` | path to compiled `TelemetryAnchor.json` under `contracts/artifacts/...` |
| `ANCHOR_INTERVAL_SEC` | `60` — seconds between anchoring attempts |
| **Oracle — data paths** | |
| `DATA_DIR` | `data` — repo-root relative; window CSV is `telemetry_windows.csv` inside it (`WINDOWS_CSV_PATH` in code) |
| `ANCHORING_LOG_PATH` | `${DATA_DIR}/anchoring_log.csv` |
| **Simulator** | |
| `N_DEVICES`, `INTERVAL_SEC` | device count and publish interval |
| `BURST_ENABLED`, `BURST_START_SEC`, `BURST_DURATION_SEC`, `BURST_MULTIPLIER` | optional burst window (see [Simulator](#simulator)) |
| **Dashboard** | |
| `ORACLE_URL` | `http://127.0.0.1:8000` — oracle base URL |
| `Z_THRESHOLD` | `3.0` — for chart threshold line (should match oracle) |
| `TELEMETRY_CSV_PATH` | overrides CSV path for charts; else `DATA_DIR` + `telemetry_windows.csv` |
| `SIM_CONFIG_PATH` | `config/sim_config.json` — where the UI saves simulator JSON |

The oracle HTTP **bind** in code is **`0.0.0.0:8000`** (not overridden by env in `main()`).

## Limitations

- **Single process** oracle (threaded MQTT consumer + optional anchor loop); no horizontal scaling.
- **MQTT** is assumed **trusted on the LAN** — there is no TLS/auth broker configuration in the defaults.
- **HMAC** proves **integrity** of telemetry fields the oracle checks; it does **not** encrypt payloads or hide them on the wire.
- **Chain** setup is **local development** (Ganache/Hardhat); not a production network deployment.
- **Anchoring** requires a funded account on the local chain; failures are logged to **`anchoring_log.csv`** without halting ingest.

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

### Anchoring evidence for the report

After runs with on-chain anchoring enabled, the oracle appends one row per anchoring attempt to **`data/anchoring_log.csv`** (override with **`ANCHORING_LOG_PATH`** or **`DATA_DIR`**). Columns include **`timestamp_iso`**, **`batch_hash`**, **`tx_hash`**, **`success`** (`1`/`0`), **`skipped`**, **`start_ms`**, **`end_ms`**, **`count`** (window range covered by the batch), and **`error`**. Failed sends are still logged with **`success=0`** and an empty **`tx_hash`** when no hash was returned.

**For the report,** copy one or two **`tx_hash`** values from `anchoring_log.csv` and optionally show a short receipt or event snippet. To inspect on a local node (Ganache / Hardhat):

- **Ganache GUI:** open the **Transactions** tab and find the tx by hash.
- **JSON-RPC:** `eth_getTransactionReceipt` with your RPC URL (e.g. `curl` to `http://127.0.0.1:8545`) and decode **`logs`** for the **`Anchored`** event (see `TelemetryAnchor.sol`: `Anchored(batchHash, startMs, endMs, count, submitter)`).
- **Hardhat console** (from **`contracts/`**): `npx hardhat console --network localhost`, then use `ethers` to `getTransactionReceipt(txHash)` and parse logs with the contract ABI, or call view helpers on the contract if you add them.

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
