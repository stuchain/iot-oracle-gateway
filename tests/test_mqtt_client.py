"""Tests for oracle MQTT client: enqueue (payload_str, ingest_ts_ms)."""
import queue
from unittest.mock import MagicMock, patch

import pytest

from oracle.mqtt_client import (
    CONNECT_RETRY_SLEEP_SEC,
    RECONNECT_SLEEP_SEC,
    TELEMETRY_TOPIC,
    _connect_with_retry,
    _on_disconnect_factory,
    _reconnect_watch_loop,
    make_on_message_handler,
    start_mqtt_consumer,
)


def test_make_on_message_enqueues_decoded_string_and_timestamp():
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    handler = make_on_message_handler(q)
    fake_msg = MagicMock()
    fake_msg.payload = b'{"device_id":"dev-01","ts_ms":1}'

    with patch("oracle.mqtt_client.time.time", return_value=1.234):
        handler(None, None, fake_msg)

    payload_str, ingest_ts_ms = q.get_nowait()
    assert payload_str == '{"device_id":"dev-01","ts_ms":1}'
    assert ingest_ts_ms == 1234


@patch("oracle.mqtt_client.threading.Thread")
@patch("oracle.mqtt_client.mqtt.Client")
def test_start_mqtt_consumer_subscribes_and_on_message_enqueues(mock_client_cls, mock_thread_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_thread_cls.return_value = MagicMock()

    q: queue.Queue[tuple[str, int]] = queue.Queue()
    _, q_out, _ = start_mqtt_consumer(message_queue=q, host="test-host", port=9999)

    assert q_out is q
    mock_client_cls.assert_called_once()
    mock_client.connect.assert_called_once_with("test-host", 9999)
    mock_client.subscribe.assert_called_once_with(TELEMETRY_TOPIC)
    assert mock_thread_cls.call_count == 2
    assert mock_thread_cls.call_args_list[0][1]["name"] == "oracle-mqtt-loop"
    assert mock_thread_cls.call_args_list[1][1]["name"] == "oracle-mqtt-reconnect"
    assert mock_thread_cls.return_value.start.call_count == 2

    assert callable(mock_client.on_message)
    assert callable(mock_client.on_disconnect)

    fake_msg = MagicMock()
    fake_msg.payload = b'{"ok":true}'
    with patch("oracle.mqtt_client.time.time", return_value=42.0):
        mock_client.on_message(None, None, fake_msg)

    payload_str, ingest_ts_ms = q.get_nowait()
    assert payload_str == '{"ok":true}'
    assert ingest_ts_ms == 42000


def test_connect_with_retry_retries_until_success():
    client = MagicMock()
    client.connect.side_effect = [OSError("down"), OSError("still down"), None]

    with patch("oracle.mqtt_client.time.sleep") as sleep_mock:
        _connect_with_retry(client, "h", 1883)

    assert client.connect.call_count == 3
    sleep_mock.assert_called_with(CONNECT_RETRY_SLEEP_SEC)
    assert sleep_mock.call_count == 2


def test_on_disconnect_logs_warning_only_for_nonzero_rc():
    cb = _on_disconnect_factory()
    with patch("oracle.mqtt_client.LOG.warning") as warn:
        cb(MagicMock(), None, 0)
        warn.assert_not_called()
        cb(MagicMock(), None, 1)
        warn.assert_called_once()


def test_reconnect_watch_loop_calls_reconnect_when_disconnected():
    client = MagicMock()
    client.is_connected.side_effect = [False, RuntimeError("stop-loop")]

    def _raise_after_second_sleep(_):
        if client.is_connected.call_count >= 1:
            raise RuntimeError("stop-loop")

    with patch("oracle.mqtt_client.time.sleep", side_effect=_raise_after_second_sleep):
        with pytest.raises(RuntimeError, match="stop-loop"):
            _reconnect_watch_loop(client, "h", 1883)

    client.reconnect.assert_called_once()


def test_reconnect_watch_loop_does_not_reconnect_when_connected():
    client = MagicMock()
    client.is_connected.return_value = True

    with patch("oracle.mqtt_client.time.sleep", side_effect=RuntimeError("stop-loop")):
        with pytest.raises(RuntimeError, match="stop-loop"):
            _reconnect_watch_loop(client, "h", 1883)

    client.reconnect.assert_not_called()


def test_reconnect_watch_loop_handles_reconnect_exception_and_continues():
    client = MagicMock()
    client.is_connected.side_effect = [False, False, RuntimeError("stop-loop")]
    client.reconnect.side_effect = [Exception("boom"), None]

    sleep_calls = {"n": 0}

    def _sleep(_seconds):
        sleep_calls["n"] += 1
        # Let loop run enough for two reconnect attempts, then stop.
        if sleep_calls["n"] >= 3:
            raise RuntimeError("stop-loop")

    with patch("oracle.mqtt_client.time.sleep", side_effect=_sleep), patch(
        "oracle.mqtt_client.LOG.warning"
    ) as warn:
        with pytest.raises(RuntimeError, match="stop-loop"):
            _reconnect_watch_loop(client, "h", 1883)

    assert client.reconnect.call_count == 2
    # Includes "not connected" warnings and one reconnect failure warning.
    assert warn.call_count >= 3


def test_make_on_message_invalid_utf8_does_not_enqueue_and_logs_warning():
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    handler = make_on_message_handler(q)
    fake_msg = MagicMock()
    fake_msg.payload = b"\xff\xfe\xfa"

    with patch("oracle.mqtt_client.LOG.warning") as warn:
        handler(None, None, fake_msg)

    warn.assert_called_once()
    assert q.empty()


def test_make_on_message_none_payload_does_not_enqueue_and_logs_warning():
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    handler = make_on_message_handler(q)
    fake_msg = MagicMock()
    fake_msg.payload = None

    with patch("oracle.mqtt_client.LOG.warning") as warn:
        handler(None, None, fake_msg)

    warn.assert_called_once()
    assert q.empty()


def test_make_on_message_non_bytes_payload_does_not_enqueue_and_logs_warning():
    q: queue.Queue[tuple[str, int]] = queue.Queue()
    handler = make_on_message_handler(q)
    fake_msg = MagicMock()
    fake_msg.payload = {"not": "bytes"}

    with patch("oracle.mqtt_client.LOG.warning") as warn:
        handler(None, None, fake_msg)

    warn.assert_called_once()
    assert q.empty()


def test_make_on_message_queue_full_drops_and_logs_warning():
    q: queue.Queue[tuple[str, int]] = queue.Queue(maxsize=1)
    q.put(("already", 1))
    handler = make_on_message_handler(q)
    fake_msg = MagicMock()
    fake_msg.payload = b'{"ok":true}'

    with patch("oracle.mqtt_client.LOG.warning") as warn, patch(
        "oracle.mqtt_client.time.time", return_value=55.0
    ):
        handler(None, None, fake_msg)

    warn.assert_called_once()
    # Existing item remains; new one should be dropped.
    payload_str, ingest_ts_ms = q.get_nowait()
    assert payload_str == "already"
    assert ingest_ts_ms == 1
