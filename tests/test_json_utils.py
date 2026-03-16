"""Tests for canonical_dumps: deterministic JSON bytes for HMAC."""
import json
import pytest

from oracle.json_utils import canonical_dumps


def test_same_logical_dict_different_order_produces_identical_bytes():
    """Two dicts with same key-value pairs in different order produce identical bytes."""
    d1 = {"a": 1, "b": 2, "c": 3}
    d2 = {"c": 3, "a": 1, "b": 2}
    assert canonical_dumps(d1) == canonical_dumps(d2)


def test_result_is_bytes_and_decodes_to_valid_json():
    """Assert result is bytes and decoding gives valid JSON."""
    obj = {"x": "hello", "y": 42}
    result = canonical_dumps(obj)
    assert isinstance(result, bytes)
    decoded = json.loads(result.decode("utf-8"))
    assert decoded == obj


def test_nested_dict_is_stable():
    """Nested dict is serialized deterministically (stable output)."""
    d1 = {"outer": {"inner_b": 2, "inner_a": 1}}
    d2 = {"outer": {"inner_a": 1, "inner_b": 2}}
    assert canonical_dumps(d1) == canonical_dumps(d2)
    # Also verify it's valid JSON
    raw = canonical_dumps(d1).decode("utf-8")
    assert json.loads(raw) == {"outer": {"inner_a": 1, "inner_b": 2}}
