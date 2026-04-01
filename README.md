# IoT Oracle Gateway

## Description

This repository is a **single-machine** reference stack for coursework and demos: simulated IoT devices publish **JSON telemetry** over **MQTT**; the **oracle** subscribes, checks **HMAC** signatures, groups messages into **fixed-length time windows** (by ingest time), and computes **throughput**, **latency**, and **EWMA-based z-scores** for simple anomaly flagging. Results are **appended to CSV** (`telemetry_windows` under `DATA_DIR`) and exposed as **JSON** via **`GET /metrics`** on port **8000**.

Optionally, the oracle can **batch window hashes** and submit them to a **`TelemetryAnchor`** Solidity contract on a **local** Ethereum-compatible node (Hardhat/Ganache on **8545**). A **Streamlit** app on **8501** polls `/metrics`, plots historical windows from the CSV (including archived runs when rotation is enabled), and can drive the simulator from the sidebar.

The stack is intentionally small: **one** oracle process (threaded MQTT + optional anchor loop), **no** container requirement, **no** cloud broker in the defaults. For diagrams, data paths, threading, and module map, see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Requirements

- Python 3.10+
- Node.js / npm (Hardhat in `contracts/`)
- Mosquitto (or other broker) on **1883**
- JSON-RPC on **8545** (Ganache or `npx hardhat node`)

## Install

```bash
pip install -r requirements.txt
```

For contracts: `cd contracts && npm ci` (or `npm install`).

## Run (Windows)

From repo root: **`run.bat`** → runs `scripts/start_stack.ps1` (deps, Hardhat compile/deploy, oracle with `CONTRACT_ADDRESS`, Mosquitto, dashboard; opens `http://127.0.0.1:8501`). Ports **8545**, **1883**, **8000**, **8501**.

If ports are stuck: **`stop.bat`** or `powershell -File scripts/stop_stack.ps1` (optionally `-Force`). That kills whatever listens on those ports.

## Run (manual)

From repo root. Use the **same `HMAC_SECRET`** for simulator and oracle.

1. `mosquitto -c mosquitto/mosquitto.conf`
2. Local chain on `http://127.0.0.1:8545` (e.g. `npx hardhat node` or Ganache)
3. **Anchoring (optional):** `cd contracts && npx hardhat compile && npx hardhat run scripts/deploy.js --network localhost` → set **`CONTRACT_ADDRESS`** to the deployed address
4. `python -m oracle.service`
5. `python -m simulator.iot_simulator --config config/sim_config.json` (or set env vars; see `simulator/`)
6. `streamlit run dashboard/app.py`

**HMAC:** The oracle refuses the default secret unless you set a real **`HMAC_SECRET`** or **`ALLOW_INSECURE_DEFAULT_SECRET=true`** (local dev only).

**Dashboard:** Sidebar **Telemetry session** picks the active or archived CSV; **Past sessions** opens `data/telemetry_archive/`. **`TELEMETRY_ROTATE_ON_START`** (default `false`) rotates the active CSV on each oracle start; **`run.bat`** sets it for the oracle. See table below.

## Tests

```bash
python -m pytest
```

## Environment (minimal)

| Variable | Notes |
|----------|--------|
| `HMAC_SECRET` | Must match simulator; required in any real use |
| `CONTRACT_ADDRESS` | Set after deploy for anchoring; empty disables txs |
| `GANACHE_URL` | Default `http://127.0.0.1:8545` |
| `ORACLE_URL` | Dashboard → oracle (default `http://127.0.0.1:8000`) |
| `TELEMETRY_ROTATE_ON_START` | `true`: archive non-empty `telemetry_windows.csv` on oracle start |
| `DATA_DIR` | Default `data` — CSVs under here |

Full defaults: [`oracle/config.py`](oracle/config.py).

## CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) — Python tests + Hardhat compile/test/deploy check.
