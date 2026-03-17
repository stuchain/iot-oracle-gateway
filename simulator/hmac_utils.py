"""Canonical JSON and HMAC-SHA256 for telemetry payloads (matches oracle)."""
import hashlib
import hmac as hmac_lib
import json


def canonical_dumps(payload_without_hmac: dict) -> bytes:
    """Serialize dict to canonical JSON bytes (sort_keys, no spaces).

    Must match oracle so HMAC verification is identical. Empty dict returns b'{}'.
    """
    return json.dumps(payload_without_hmac, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_hmac(payload: dict, secret: bytes) -> str:
    """Compute HMAC-SHA256 over canonical JSON of payload (excluding 'hmac' key), return hex.

    If payload already has 'hmac', it is excluded before canonicalization.
    """
    data = {k: v for k, v in payload.items() if k != "hmac"}
    msg = canonical_dumps(data)
    return hmac_lib.new(secret, msg, digestmod=hashlib.sha256).hexdigest()
