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


def test_send_anchor_rejects_non_32_byte_hash(tmp_path):
    abi_file = tmp_path / "abi.json"
    abi_file.write_text(json.dumps({"abi": MINIMAL_ANCHOR_ABI}), encoding="utf-8")
    out = send_anchor("http://127.0.0.1:8545", "0x" + "a" * 40, str(abi_file), b"\x01", 1, 2, 3)
    assert out.success is False
    assert "32 bytes" in (out.error or "")


def test_send_anchor_returns_not_connected_error(monkeypatch, tmp_path):
    monkeypatch.setattr("oracle.anchor_contract.load_contract_abi", lambda p: MINIMAL_ANCHOR_ABI)
    abi_file = tmp_path / "abi.json"
    abi_file.write_text(json.dumps({"abi": MINIMAL_ANCHOR_ABI}), encoding="utf-8")
    with patch("oracle.anchor_contract.Web3") as W3:
        w3 = W3.return_value
        w3.is_connected.return_value = False
        out = send_anchor(
            "http://127.0.0.1:8545", "0x" + "a" * 40, str(abi_file), b"\x02" * 32, 1, 2, 3
        )
    assert out.success is False
    assert out.error == "not connected to RPC"


def test_send_anchor_returns_no_accounts_error(monkeypatch, tmp_path):
    monkeypatch.setattr("oracle.anchor_contract.load_contract_abi", lambda p: MINIMAL_ANCHOR_ABI)
    abi_file = tmp_path / "abi.json"
    abi_file.write_text(json.dumps({"abi": MINIMAL_ANCHOR_ABI}), encoding="utf-8")
    with patch("oracle.anchor_contract.Web3") as W3:
        w3 = W3.return_value
        w3.is_connected.return_value = True
        w3.eth.accounts = []
        out = send_anchor(
            "http://127.0.0.1:8545", "0x" + "a" * 40, str(abi_file), b"\x02" * 32, 1, 2, 3
        )
    assert out.success is False
    assert out.error == "no accounts on node"


def test_send_anchor_returns_contract_exception_text(monkeypatch, tmp_path):
    monkeypatch.setattr("oracle.anchor_contract.load_contract_abi", lambda p: MINIMAL_ANCHOR_ABI)
    abi_file = tmp_path / "abi.json"
    abi_file.write_text(json.dumps({"abi": MINIMAL_ANCHOR_ABI}), encoding="utf-8")
    with patch("oracle.anchor_contract.Web3") as W3:
        w3 = W3.return_value
        w3.is_connected.return_value = True
        w3.eth.accounts = ["0x" + "a" * 40]
        w3.eth.contract.side_effect = RuntimeError("bad contract")
        out = send_anchor(
            "http://127.0.0.1:8545", "0x" + "a" * 40, str(abi_file), b"\x02" * 32, 1, 2, 3
        )
    assert out.success is False
    assert out.error == "anchor_transaction_failed"


def test_send_anchor_in_debug_mode_returns_raw_exception(monkeypatch, tmp_path):
    monkeypatch.setattr("oracle.anchor_contract.DEBUG", True)
    monkeypatch.setattr("oracle.anchor_contract.load_contract_abi", lambda p: MINIMAL_ANCHOR_ABI)
    abi_file = tmp_path / "abi.json"
    abi_file.write_text(json.dumps({"abi": MINIMAL_ANCHOR_ABI}), encoding="utf-8")
    with patch("oracle.anchor_contract.Web3") as W3:
        w3 = W3.return_value
        w3.is_connected.return_value = True
        w3.eth.accounts = ["0x" + "a" * 40]
        w3.eth.contract.side_effect = RuntimeError("bad contract debug detail")
        out = send_anchor(
            "http://127.0.0.1:8545", "0x" + "a" * 40, str(abi_file), b"\x02" * 32, 1, 2, 3
        )
    assert out.success is False
    assert "bad contract debug detail" in (out.error or "")


def test_anchor_tick_skip_continues_when_anchoring_log_write_fails(tmp_path):
    runner = MagicMock()
    state = _oracle_state(tmp_path, runner)

    def _fail_log(*_args, **_kwargs):
        raise OSError("disk full")

    state._append_anchoring_log = _fail_log  # type: ignore[method-assign]
    state.anchor_tick()
    runner.assert_not_called()
    assert state.last_anchor_info["skipped"] is True


def test_anchor_tick_success_continues_when_anchoring_log_write_fails(tmp_path):
    def runner(_bh: bytes, _sm: int, _em: int, _c: int) -> AnchorResult:
        return AnchorResult(tx_hash="0xok", success=True, block_number=1)

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

    def _fail_log(*_args, **_kwargs):
        raise OSError("permission denied")

    state._append_anchoring_log = _fail_log  # type: ignore[method-assign]
    state.anchor_tick()
    assert state.last_anchor_info["success"] is True
    assert state.last_anchor_info["tx_hash"] == "0xok"
    assert state._pending_anchor == []


def test_anchor_tick_repeated_failures_then_recovery_drains_accumulated_pending(tmp_path):
    calls = {"n": 0}

    def runner(_bh: bytes, _sm: int, _em: int, _c: int) -> AnchorResult:
        calls["n"] += 1
        if calls["n"] <= 3:
            return AnchorResult(tx_hash=None, success=False, error="rpc timeout")
        return AnchorResult(tx_hash="0xrecover", success=True, block_number=42)

    state = _oracle_state(tmp_path, runner)
    # Three windows queued for anchoring.
    for i in range(3):
        state._pending_anchor.append(
            WindowSummary(
                window_start_ms=i * 5000,
                window_end_ms=(i + 1) * 5000,
                msg_count=1,
                msgs_per_sec=0.2,
                avg_latency_ms=1.0,
                z_score=0.0,
                is_anomaly=False,
            )
        )

    state.anchor_tick()
    assert state.last_anchor_info["success"] is False
    assert len(state._pending_anchor) == 3
    state.anchor_tick()
    assert state.last_anchor_info["success"] is False
    assert len(state._pending_anchor) == 3
    state.anchor_tick()
    assert state.last_anchor_info["success"] is False
    assert len(state._pending_anchor) == 3
    state.anchor_tick()
    assert state.last_anchor_info["success"] is True
    assert state.last_anchor_info["tx_hash"] == "0xrecover"
    assert state._pending_anchor == []


def test_anchor_tick_success_removes_only_snapshot_when_new_rows_arrive_during_send(tmp_path):
    state_holder = {}

    def runner(_bh: bytes, _sm: int, _em: int, _c: int) -> AnchorResult:
        # Simulate new finalized window arriving while tx is in flight.
        st = state_holder["state"]
        st._pending_anchor.append(
            WindowSummary(
                window_start_ms=15000,
                window_end_ms=20000,
                msg_count=1,
                msgs_per_sec=0.2,
                avg_latency_ms=1.0,
                z_score=0.0,
                is_anomaly=False,
            )
        )
        return AnchorResult(tx_hash="0xsnap", success=True, block_number=9)

    state = _oracle_state(tmp_path, runner)
    state_holder["state"] = state
    # Initial snapshot size is 2.
    state._pending_anchor.append(
        WindowSummary(
            window_start_ms=0,
            window_end_ms=5000,
            msg_count=1,
            msgs_per_sec=0.2,
            avg_latency_ms=1.0,
            z_score=0.0,
            is_anomaly=False,
        )
    )
    state._pending_anchor.append(
        WindowSummary(
            window_start_ms=5000,
            window_end_ms=10000,
            msg_count=1,
            msgs_per_sec=0.2,
            avg_latency_ms=1.0,
            z_score=0.0,
            is_anomaly=False,
        )
    )

    state.anchor_tick()
    assert state.last_anchor_info["success"] is True
    # The two snapshot rows are removed; the one appended mid-send remains pending.
    assert len(state._pending_anchor) == 1
    assert state._pending_anchor[0].window_start_ms == 15000
