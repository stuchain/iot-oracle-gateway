"""Tests for oracle HMAC verification.

These follow the Phase 3 intent:
- Valid payload from simulator helper verifies successfully.
- Tampering any field without updating HMAC fails verification.
"""

import json

from simulator.hmac_utils import compute_hmac

from oracle.verify import verify_payload


def test_verify_payload_accepts_valid_hmac():
    secret = b"test-secret"
    base = {
        "device_id": "dev-01",
        "ts_ms": 1000,
        "temp_c": 22.5,
        "humidity_pct": 60.0,
        "power_w": 50.0,
    }
    full = {**base, "hmac": compute_hmac(base, secret)}
    payload_json = json.dumps(full)

    parsed, valid = verify_payload(payload_json, secret)
    assert valid is True
    assert parsed is not None
    assert parsed["device_id"] == "dev-01"
    assert parsed["ts_ms"] == 1000
    assert parsed["hmac"] == full["hmac"]


def test_verify_payload_rejects_tampered_field_keeps_hmac():
    secret = b"test-secret"
    base = {
        "device_id": "dev-01",
        "ts_ms": 1000,
        "temp_c": 22.5,
        "humidity_pct": 60.0,
        "power_w": 50.0,
    }
    full = {**base, "hmac": compute_hmac(base, secret)}

    tampered = {**full, "temp_c": 23.0}  # HMAC is no longer valid for this payload.
    payload_json = json.dumps(tampered)

    parsed, valid = verify_payload(payload_json, secret)
    assert valid is False
    assert parsed is None

