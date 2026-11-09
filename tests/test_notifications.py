from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def valid_event():
    return {
        "type": "OrderPlaced",
        "event_id": "evt-1",
        "order_id": "order-1",
        "recipient_email": "customer@example.com",
        "customer_name": "Ari Borg",
        "items": [{"order_id": "order-1", "sku": "HEADPHONES-01", "name": "Headphones", "quantity": 1}],
        "correlation_id": "corr-1",
    }


def test_event_consumed_once(notification_module, monkeypatch):
    notification_module.initialize()
    event = valid_event()
    send_email = Mock()
    monkeypatch.setattr(notification_module, "send_email", send_email)

    assert notification_module.apply_event(event) is True
    assert notification_module.apply_event(event) is False
    send_email.assert_called_once_with(
        event, "customer@example.com", ["order-1"], event["items"]
    )
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
                "recipient_email": "customer@example.com",
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
    for routing_key in ("order.placed", "order.accepted", "order.cancelled"):
        channel.queue_bind.assert_any_call(
            exchange="malta.events",
            queue="notification.order_placed",
            routing_key=routing_key,
        )
    channel.queue_bind.assert_any_call(
        exchange="malta.dead",
        queue="notification.order_placed.dead",
        routing_key="notification.order_placed.dead",
    )


def test_message_callback_acknowledges_processed_and_duplicate_events(
    notification_module, monkeypatch
):
    notification_module.initialize()
    channel = Mock()
    monkeypatch.setattr(notification_module, "send_email", Mock())
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


def test_message_callback_does_not_nack_again_when_ack_fails(
    notification_module, monkeypatch
):
    notification_module.initialize()
    channel = Mock()
    channel.basic_ack.side_effect = OSError("broker channel closed")
    monkeypatch.setattr(notification_module, "send_email", Mock())
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


@pytest.mark.parametrize(
    ("event_type", "subject"),
    [
        ("OrderPlaced", "Your MaltaShop order is confirmed"),
        ("OrderAccepted", "Your MaltaShop order has been accepted"),
        ("OrderCancelled", "Your MaltaShop order has been cancelled"),
    ],
)
def test_sends_gmail_smtp_status_email(
    notification_module, monkeypatch, event_type, subject
):
    notification_module.SMTP_USER = "shop@example.com"
    notification_module.SMTP_PASSWORD = "abcdefghijklmnop"
    notification_module.SMTP_FROM = "shop@example.com"
    server = Mock()
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)
    smtp = Mock(return_value=server)
    monkeypatch.setattr(notification_module.smtplib, "SMTP", smtp)
    event = {**valid_event(), "type": event_type}

    recipient, order_ids, items = notification_module.validate_event(event)
    notification_module.send_email(event, recipient, order_ids, items)

    smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=20)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("shop@example.com", "abcdefghijklmnop")
    message = server.send_message.call_args.args[0]
    assert message["To"] == "customer@example.com"
    assert message["Subject"] == subject
    assert "Ari Borg" in message.get_body(preferencelist=("plain",)).get_content()
    assert "order-1" in message.get_body(preferencelist=("plain",)).get_content()


def test_gmail_app_password_spaces_are_removed(notification_module, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    notification_module.SMTP_USER = "shop@example.com"
    notification_module.SMTP_FROM = "shop@example.com"
    notification_module.SMTP_PASSWORD = "".join(
        notification_module.os.getenv("SMTP_PASSWORD", "").split()
    )
    notification_module.SMTP_HOST = "smtp.gmail.com"

    assert notification_module.SMTP_PASSWORD == "abcdefghijklmnop"
    assert notification_module.email_is_configured() is True


def test_invalid_gmail_app_password_keeps_worker_paused(notification_module, monkeypatch):
    monkeypatch.setattr(notification_module, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(notification_module, "SMTP_USER", "shop@example.com")
    monkeypatch.setattr(notification_module, "SMTP_PASSWORD", "short-pass")
    monkeypatch.setattr(notification_module, "SMTP_FROM", "shop@example.com")

    assert notification_module.email_is_configured() is False
    assert "16-character" in notification_module.email_configuration_error()


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
    monkeypatch.setattr(notification_module, "SMTP_USER", "shop@example.com")
    monkeypatch.setattr(notification_module, "SMTP_PASSWORD", "abcdefghijklmnop")
    monkeypatch.setattr(notification_module, "SMTP_FROM", "shop@example.com")
    monkeypatch.setattr(
        notification_module.time,
        "sleep",
        Mock(side_effect=StopRetry),
    )

    with pytest.raises(StopRetry):
        notification_module.run()

    assert connection.closed
