from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def valid_event():
    return {
        "type": "OrderPlaced",
        "event_id": "evt-1",
        "order_id": "order-1",
        "correlation_id": "corr-1",
    }


def test_event_consumed_once(notification_module):
    notification_module.initialize()
    event = valid_event()

    assert notification_module.apply_event(event) is True
    assert notification_module.apply_event(event) is False
    with notification_module.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM received_events").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"type": "Unknown"}, "Unsupported event"),
        (
            {
                "type": "OrderPlaced",
                "event_id": "evt-1",
                "order_id": "order-1",
            },
            "Missing correlation_id",
        ),
        ([], "Event must be a JSON object"),
        ({**valid_event(), "event_id": "  "}, "Missing event_id"),
    ],
)
def test_invalid_event_is_rejected_without_writing(
    notification_module, event, message
):
    notification_module.initialize()

    with pytest.raises(ValueError, match=message):
        notification_module.apply_event(event)

    with notification_module.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM received_events").fetchone()[0] == 0


def test_queue_setup_routes_failed_messages_to_durable_dead_letter_queue(
    notification_module,
):
    channel = Mock()

    notification_module.configure_queues(channel)

    channel.exchange_declare.assert_any_call(
        exchange="malta.events", exchange_type="topic", durable=True
    )
    channel.exchange_declare.assert_any_call(
        exchange="malta.dead", exchange_type="direct", durable=True
    )
    channel.queue_declare.assert_any_call(
        queue="notification.order_placed.dead", durable=True
    )
    channel.queue_declare.assert_any_call(
        queue="notification.order_placed",
        durable=True,
        arguments={
            "x-dead-letter-exchange": "malta.dead",
            "x-dead-letter-routing-key": "notification.order_placed.dead",
        },
    )
    channel.queue_bind.assert_any_call(
        exchange="malta.dead",
        queue="notification.order_placed.dead",
        routing_key="notification.order_placed.dead",
    )


def test_message_callback_acknowledges_processed_and_duplicate_events(
    notification_module,
):
    notification_module.initialize()
    channel = Mock()
    method = SimpleNamespace(delivery_tag=7)
    body = notification_module.json.dumps(valid_event()).encode()

    notification_module.on_message(channel, method, None, body)
    notification_module.on_message(channel, method, None, body)

    assert channel.basic_ack.call_count == 2
    channel.basic_ack.assert_called_with(delivery_tag=7)
    channel.basic_nack.assert_not_called()
    with notification_module.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM received_events").fetchone()[0] == 1


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"type":"Unsupported"}'])
def test_message_callback_dead_letters_invalid_events(
    notification_module, body
):
    notification_module.initialize()
    channel = Mock()

    notification_module.on_message(channel, SimpleNamespace(delivery_tag=8), None, body)

    channel.basic_nack.assert_called_once_with(delivery_tag=8, requeue=False)
    channel.basic_ack.assert_not_called()
    with notification_module.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM received_events").fetchone()[0] == 0


def test_message_callback_does_not_nack_again_when_ack_fails(notification_module):
    notification_module.initialize()
    channel = Mock()
    channel.basic_ack.side_effect = OSError("broker channel closed")
    body = notification_module.json.dumps(valid_event()).encode()

    with pytest.raises(OSError, match="broker channel closed"):
        notification_module.on_message(
            channel, SimpleNamespace(delivery_tag=9), None, body
        )

    channel.basic_nack.assert_not_called()


def test_message_callback_nacks_storage_failures_for_dead_lettering(
    notification_module, monkeypatch
):
    channel = Mock()
    monkeypatch.setattr(
        notification_module,
        "apply_event",
        Mock(side_effect=OSError("database unavailable")),
    )
    body = notification_module.json.dumps(valid_event()).encode()

    notification_module.on_message(
        channel, SimpleNamespace(delivery_tag=10), None, body
    )

    channel.basic_nack.assert_called_once_with(delivery_tag=10, requeue=False)
    channel.basic_ack.assert_not_called()


def test_run_closes_connection_after_consumer_failure(
    notification_module, monkeypatch
):
    class StopRetry(Exception):
        pass

    channel = Mock()
    channel.start_consuming.side_effect = OSError("connection interrupted")

    class FakeConnection:
        is_open = True

        def __init__(self):
            self.closed = False

        def channel(self):
            return channel

        def close(self):
            self.closed = True
            self.is_open = False

    connection = FakeConnection()
    monkeypatch.setattr(
        notification_module.pika,
        "BlockingConnection",
        Mock(return_value=connection),
    )
    monkeypatch.setattr(
        notification_module.time,
        "sleep",
        Mock(side_effect=StopRetry),
    )

    with pytest.raises(StopRetry):
        notification_module.run()

    assert connection.closed
