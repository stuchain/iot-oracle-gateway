"""Tests for simulator HMAC: determinism, tampering, and edge cases."""
from simulator.hmac_utils import canonical_dumps, compute_hmac

SECRET = b"test-secret"


def test_same_payload_different_key_order_yields_same_hmac():
    """Same logical payload with different key order yields same HMAC."""
    d1 = {"device_id": "dev-01", "ts_ms": 1000, "temp_c": 22.5, "humidity_pct": 60.0, "power_w": 50.0}
    d2 = {"power_w": 50.0, "humidity_pct": 60.0, "temp_c": 22.5, "ts_ms": 1000, "device_id": "dev-01"}
    assert compute_hmac(d1, SECRET) == compute_hmac(d2, SECRET)


def test_changing_one_field_yields_different_hmac():
    """Changing one field (e.g. temp_c) yields different HMAC."""
    payload = {"device_id": "dev-01", "ts_ms": 1000, "temp_c": 22.5, "humidity_pct": 60.0, "power_w": 50.0}
    tampered = {**payload, "temp_c": 23.0}
    assert compute_hmac(payload, SECRET) != compute_hmac(tampered, SECRET)


def test_payload_with_hmac_key_excludes_hmac_from_signed_bytes():
    """Payload already has 'hmac' key: exclude it before canonicalization."""
    data = {"device_id": "dev-01", "ts_ms": 1000, "temp_c": 22.5, "humidity_pct": 60.0, "power_w": 50.0}
    with_hmac = {**data, "hmac": "old-hex-value"}
    assert compute_hmac(with_hmac, SECRET) == compute_hmac(data, SECRET)


def test_canonical_dumps_empty_dict_returns_empty_json_bytes():
    """Empty dict: canonical_dumps returns b'{}'."""
    assert canonical_dumps({}) == b"{}"


def test_compute_hmac_returns_hex_string_64_chars():
    """compute_hmac returns a hex-only string of length 64 (SHA-256)."""
    payload = {"device_id": "dev-01", "ts_ms": 1000, "temp_c": 22.5, "humidity_pct": 60.0, "power_w": 50.0}
    result = compute_hmac(payload, SECRET)
    assert isinstance(result, str)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)
