"""Unit tests for anchoring (mocked Web3 / injectable runner)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from oracle.anchor_contract import AnchorResult, send_anchor
from oracle.service import OracleState, create_app
from oracle.windows import WindowSummary


MINIMAL_ANCHOR_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "batchHash", "type": "bytes32"},
            {"internalType": "uint256", "name": "startMs", "type": "uint256"},
            {"internalType": "uint256", "name": "endMs", "type": "uint256"},
            {"internalType": "uint256", "name": "count", "type": "uint256"},
        ],
        "name": "anchor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def test_send_anchor_invokes_contract_with_expected_args(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "oracle.anchor_contract.load_contract_abi", lambda p: MINIMAL_ANCHOR_ABI
    )
    batch_hash = b"\x02" * 32
    addr = "0x" + "a" * 40

    with patch("oracle.anchor_contract.Web3") as W3:
        w3 = W3.return_value
        w3.is_connected.return_value = True
        w3.eth.accounts = [addr]
        w3.to_hex = MagicMock(return_value="0xdeadbeef")

        mock_fn = MagicMock()
        mock_fn.transact.return_value = b"\x01" * 32
        contract = MagicMock()
        contract.functions.anchor.return_value = mock_fn
        w3.eth.contract.return_value = contract
        w3.eth.wait_for_transaction_receipt.return_value = {"blockNumber": 7}

        abi_file = tmp_path / "abi.json"
        abi_file.write_text(json.dumps({"abi": MINIMAL_ANCHOR_ABI}), encoding="utf-8")

        r = send_anchor(
            "http://127.0.0.1:8545",
            addr,
            str(abi_file),
            batch_hash,
            100,
            200,
            3,
        )

    assert r.success is True
    assert r.tx_hash == "0xdeadbeef"
    assert r.block_number == 7
    contract.functions.anchor.assert_called_once_with(batch_hash, 100, 200, 3)
    mock_fn.transact.assert_called_once_with({"from": addr})


def _oracle_state(tmp_path, anchor_send):
    return OracleState(
        window_sec=5,
        secret=b"s",
        csv_path=str(tmp_path / "w.csv"),
        ewma_alpha=0.2,
        ewma_z_threshold=3.0,
        ewma_epsilon=1e-6,
        anchoring_log_path=str(tmp_path / "anchor.csv"),
        anchor_send=anchor_send,
    )


def test_anchor_tick_empty_does_not_call_runner(tmp_path):
    runner = MagicMock()
    state = _oracle_state(tmp_path, runner)
    state.anchor_tick()
    runner.assert_not_called()
    assert state.last_anchor_info["skipped"] is True


def test_anchor_tick_calls_runner_with_batch_args(tmp_path):
    calls = []

    def runner(bh: bytes, sm: int, em: int, c: int) -> AnchorResult:
        calls.append((bh, sm, em, c))
        return AnchorResult(tx_hash="0xabc", success=True, block_number=1)

    state = _oracle_state(tmp_path, runner)
    s = WindowSummary(
        window_start_ms=0,
        window_end_ms=5000,
        msg_count=1,
        msgs_per_sec=0.2,
        avg_latency_ms=1.0,
        z_score=0.0,
        is_anomaly=False,
    )
    state._pending_anchor.append(s)
    state.anchor_tick()
    assert len(calls) == 1
    bh, sm, em, c = calls[0]
    assert len(bh) == 32
    assert sm == 0 and em == 5000 and c == 1
    assert state.last_anchor_info["success"] is True
    assert state.last_anchor_info["skipped"] is False
    assert state._pending_anchor == []


def test_create_app_with_anchor_runner(tmp_path):
    recorded = []

    def runner(bh: bytes, sm: int, em: int, c: int) -> AnchorResult:
        recorded.append((bh, sm, em, c))
        return AnchorResult(tx_hash="0x1", success=True, block_number=1)

    q = __import__("queue").Queue()
    app = create_app(
        start_mqtt=False,
        message_queue=q,
        csv_path=str(tmp_path / "telemetry_windows.csv"),
        anchoring_log_path=str(tmp_path / "anchoring_log.csv"),
        hmac_secret="x",
        contract_address="",
        anchor_runner=runner,
        anchor_interval_sec=3600.0,
    )
    state = app.state.oracle_state
    s = WindowSummary(
        window_start_ms=0,
        window_end_ms=5000,
        msg_count=1,
        msgs_per_sec=0.2,
        avg_latency_ms=1.0,
        z_score=0.0,
        is_anomaly=False,
    )
    state._pending_anchor.append(s)
    state.anchor_tick()
    assert len(recorded) == 1
