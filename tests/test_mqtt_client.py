"""Tests for oracle MQTT client: enqueue (payload_str, ingest_ts_ms)."""
import queue
from unittest.mock import MagicMock, patch

from oracle.mqtt_client import TELEMETRY_TOPIC, make_on_message_handler, start_mqtt_consumer


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
