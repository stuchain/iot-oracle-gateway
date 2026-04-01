"""Tests for oracle.config environment parsing fallback behavior."""

from __future__ import annotations

import importlib
import os

import oracle.config as config


def _reload_config():
    return importlib.reload(config)


def test_config_invalid_int_float_envs_fall_back(monkeypatch):
    monkeypatch.setenv("MQTT_PORT", "bad-int")
    monkeypatch.setenv("WINDOW_SEC", "not-an-int")
    monkeypatch.setenv("EWMA_ALPHA", "not-a-float")
    monkeypatch.setenv("Z_THRESHOLD", "not-a-float")
    cfg = _reload_config()
    assert cfg.MQTT_PORT == 1883
    assert cfg.WINDOW_SEC == 5
    assert cfg.EWMA_ALPHA == 0.2
    assert cfg.Z_THRESHOLD == 3.0


def test_config_valid_envs_override_defaults(monkeypatch):
    monkeypatch.setenv("MQTT_PORT", "2883")
    monkeypatch.setenv("WINDOW_SEC", "10")
    monkeypatch.setenv("EWMA_ALPHA", "0.4")
    monkeypatch.setenv("Z_THRESHOLD", "2.2")
    monkeypatch.setenv("HMAC_SECRET", "custom-secret")
    cfg = _reload_config()
    assert cfg.MQTT_PORT == 2883
    assert cfg.WINDOW_SEC == 10
    assert cfg.EWMA_ALPHA == 0.4
    assert cfg.Z_THRESHOLD == 2.2
    assert cfg.HMAC_SECRET == "custom-secret"


def test_config_contract_address_strip_and_data_paths(monkeypatch):
    monkeypatch.setenv("CONTRACT_ADDRESS", " 0xabc ")
    monkeypatch.setenv("DATA_DIR", "my_data")
    cfg = _reload_config()
    assert cfg.CONTRACT_ADDRESS == "0xabc"
    assert cfg.WINDOWS_CSV_PATH.replace("\\", "/").endswith("my_data/telemetry_windows.csv")
    assert cfg.ANCHORING_LOG_PATH.replace("\\", "/").endswith("my_data/anchoring_log.csv")


def teardown_module():
    # Keep process env stable for subsequent tests in this session.
    for key in (
        "MQTT_PORT",
        "WINDOW_SEC",
        "EWMA_ALPHA",
        "Z_THRESHOLD",
        "HMAC_SECRET",
        "CONTRACT_ADDRESS",
        "DATA_DIR",
        "TELEMETRY_ROTATE_ON_START",
        "TELEMETRY_ARCHIVE_SUBDIR",
    ):
        os.environ.pop(key, None)
    _reload_config()
