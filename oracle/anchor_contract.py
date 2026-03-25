"""Web3 client for TelemetryAnchor.anchor on Ganache / local chain."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from web3 import Web3

LOG = logging.getLogger(__name__)


@dataclass
class AnchorResult:
    """Outcome of a single anchor transaction attempt."""

    tx_hash: Optional[str]
    success: bool
    block_number: Optional[int] = None
    error: Optional[str] = None


def load_contract_abi(abi_path: str) -> list[dict[str, Any]]:
    with open(abi_path, encoding="utf-8") as f:
        artifact = json.load(f)
    return artifact["abi"]


def send_anchor(
    ganache_url: str,
    contract_address: str,
    abi_path: str,
    batch_hash: bytes,
    start_ms: int,
    end_ms: int,
    count: int,
) -> AnchorResult:
    """Send anchor(batchHash, startMs, endMs, count) using the first Ganache account."""
    if len(batch_hash) != 32:
        return AnchorResult(None, False, error="batch_hash must be 32 bytes")
    try:
        abi = load_contract_abi(abi_path)
        w3 = Web3(Web3.HTTPProvider(ganache_url))
        if not w3.is_connected():
            return AnchorResult(None, False, error="not connected to RPC")
        accounts = w3.eth.accounts
        if not accounts:
            return AnchorResult(None, False, error="no accounts on node")
        from_addr = accounts[0]
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_address), abi=abi
        )
        tx_hash = contract.functions.anchor(
            batch_hash, start_ms, end_ms, count
        ).transact({"from": from_addr})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        bn = receipt.get("blockNumber")
        block_number = int(bn) if bn is not None else None
        return AnchorResult(
            tx_hash=w3.to_hex(tx_hash),
            success=True,
            block_number=block_number,
            error=None,
        )
    except Exception as e:
        LOG.warning("anchor transaction failed: %s", e)
        return AnchorResult(None, False, error=str(e))
