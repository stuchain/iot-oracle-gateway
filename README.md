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

Run instructions for each component will be added in later phases.
