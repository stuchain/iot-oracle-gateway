"""HMAC verification and parsing for oracle.

The simulator computes HMAC-SHA256 over canonical JSON bytes of the telemetry
payload *excluding* the `hmac` field. This module verifies the same scheme.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
from typing import Any, Optional

from oracle.json_utils import canonical_dumps


def verify_payload(payload: str | dict[str, Any], secret: bytes) -> tuple[Optional[dict[str, Any]], bool]:
    """Verify an incoming telemetry payload string/dict against its HMAC.

    Args:
        payload: Raw JSON string or an already-parsed dict containing an `hmac` hex string.
        secret: HMAC secret bytes.

    Returns:
        (parsed_dict, valid)
        - parsed_dict is None when parsing or verification fails.
        - valid is True only when computed HMAC matches payload['hmac'].
    """

    if isinstance(payload, str):
        try:
            parsed: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError:
            return None, False
    elif isinstance(payload, dict):
        parsed = payload
    else:
        return None, False

    hmac_value = parsed.get("hmac")
    if not isinstance(hmac_value, str) or not hmac_value:
        return None, False

    # Canonicalize everything except 'hmac', matching simulator behavior.
    payload_without_hmac = {k: v for k, v in parsed.items() if k != "hmac"}
    msg = canonical_dumps(payload_without_hmac)
    expected = hmac_lib.new(secret, msg, digestmod=hashlib.sha256).hexdigest()

    if not hmac_lib.compare_digest(expected, hmac_value):
        return None, False

    # Ensure the parsed payload has the fields the rest of the pipeline expects.
    if not isinstance(parsed.get("device_id"), str) or not parsed["device_id"]:
        return None, False
    if not isinstance(parsed.get("ts_ms"), int):
        return None, False

    for k in ("temp_c", "humidity_pct", "power_w"):
        v = parsed.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None, False

    return parsed, True

