"""Telemetry payload schema for simulator and oracle.

Payload shape: device_id, ts_ms, temp_c, humidity_pct, power_w. The field
'hmac' is not part of the signing payload; it is added after computing
HMAC-SHA256 over the canonical JSON bytes of the dict without 'hmac'.
"""
from typing import TypedDict


class TelemetryPayload(TypedDict, total=True):
    """Telemetry fields used for building and signing (no hmac)."""

    device_id: str
    ts_ms: int
    temp_c: float
    humidity_pct: float
    power_w: float


class TelemetryPayloadWithHmac(TypedDict, total=True):
    """Full payload as published: TelemetryPayload plus hmac (hex string)."""

    device_id: str
    ts_ms: int
    temp_c: float
    humidity_pct: float
    power_w: float
    hmac: str
