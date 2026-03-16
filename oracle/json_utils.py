"""Canonical JSON serialization for deterministic HMAC(serialize(payload))."""
import json


def canonical_dumps(obj: dict) -> bytes:
    """Serialize dict to canonical JSON bytes (sort_keys, no spaces)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
