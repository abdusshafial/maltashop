"""MaltaShop notification worker for order email updates."""
import html
import json
import logging
import os
import smtplib
import sqlite3
import time
from contextlib import contextmanager
from email.message import EmailMessage
from ssl import create_default_context

import pika

DB = os.getenv('NOTIFICATION_DB', '/data/notifications.db')
HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '').strip()
SMTP_PASSWORD = ''.join(os.getenv('SMTP_PASSWORD', '').split())
SMTP_FROM = os.getenv('SMTP_FROM', '').strip() or SMTP_USER
EVENT_ROUTING_KEYS = {
    'OrderPlaced': 'order.placed',
    'OrderAccepted': 'order.accepted',
    'OrderCancelled': 'order.cancelled',
}
EVENT_SUBJECTS = {
    'OrderPlaced': 'Your MaltaShop order is confirmed',
    'OrderAccepted': 'Your MaltaShop order has been accepted',
    'OrderCancelled': 'Your MaltaShop order has been cancelled',
}
logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('notifications')


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=10)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def email_is_configured():
    return email_configuration_error() is None


def email_configuration_error():
    if not SMTP_USER or not SMTP_PASSWORD or not SMTP_FROM:
        return 'Set SMTP_USER and SMTP_PASSWORD (SMTP_FROM defaults to SMTP_USER)'
    if SMTP_HOST.casefold() == 'smtp.gmail.com' and len(SMTP_PASSWORD) != 16:
        return 'Gmail SMTP_PASSWORD must be a 16-character Google App Password'
    return None


def validate_event(event):
    if not isinstance(event, dict):
        raise ValueError('Event must be a JSON object')
    if event.get('type') not in EVENT_SUBJECTS:
        raise ValueError('Unsupported event')
    for key in ('event_id', 'correlation_id'):
        value = event.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Missing ' + key)
    order_ids = event.get('order_ids') or [event.get('order_id')]
    if not order_ids or any(not isinstance(value, str) or not value.strip() for value in order_ids):
        raise ValueError('Missing order_id')
    recipient = event.get('recipient_email') or event.get('customer_id')
    if not isinstance(recipient, str) or not recipient.strip():
        raise ValueError('Missing recipient_email')
    items = event.get('items')
    if items is not None and (
        not isinstance(items, list)
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get('name') or item.get('sku'), str)
            or not isinstance(item.get('quantity'), int)
            for item in items
        )
    ):
        raise ValueError('Invalid items')
    return recipient, order_ids, items or []


def send_email(event, recipient, order_ids, items):
    if not email_is_configured():
        raise RuntimeError('SMTP is not configured; set SMTP_USER and SMTP_PASSWORD')

    customer_name = event.get('customer_name') or 'MaltaShop customer'
    greeting = f"Hello {customer_name},"
    item_lines = [
        f"- {item.get('name') or item.get('sku')} × {item['quantity']}"
        for item in items
    ]
    order_line = ', '.join(order_ids)
    status_text = {
        'OrderPlaced': 'Your order has been confirmed and is now being prepared.',
        'OrderAccepted': 'Your order has been accepted and is being prepared for dispatch.',
        'OrderCancelled': 'Your order has been cancelled.',
    }[event['type']]
    text = '\n'.join([
        greeting,
        '',
        status_text,
        f'Order ID: {order_line}',
        *(item_lines or []),
        '',
        'Thank you for shopping with MaltaShop.',
    ])
    safe_name = html.escape(customer_name)
    safe_status = html.escape(status_text)
    safe_order = html.escape(order_line)
    html_items = ''.join(
        f"<li>{html.escape(str(item.get('name') or item.get('sku')))} × {item['quantity']}</li>"
        for item in items
    )
    message = EmailMessage()
    message['Subject'] = EVENT_SUBJECTS[event['type']]
    message['From'] = SMTP_FROM
    message['To'] = recipient
    message.set_content(text)
    message.add_alternative(
        f'<html><body><p>Hello {safe_name},</p><p>{safe_status}</p>'
        f'<p><strong>Order ID:</strong> {safe_order}</p><ul>{html_items}</ul>'
        '<p>Thank you for shopping with MaltaShop.</p></body></html>',
        subtype='html',
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls(context=create_default_context())
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)
    log.info(json.dumps({
        'level': 'INFO',
        'service': 'notifications',
        'event': 'order_email_sent',
        'type': event['type'],
        'order_ids': order_ids,
        'correlation_id': event['correlation_id'],
    }))


def initialize():
    os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)
    with connect() as db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS received_events ('
            'event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, '
            'correlation_id TEXT NOT NULL, processed_at TEXT DEFAULT CURRENT_TIMESTAMP)'
        )


def apply_event(event):
    recipient, order_ids, items = validate_event(event)
    with connect() as db:
        if db.execute(
            'SELECT 1 FROM received_events WHERE event_id=?',
            (event['event_id'],),
        ).fetchone():
            inserted = False
        else:
            send_email(event, recipient, order_ids, items)
            db.execute(
                'INSERT INTO received_events(event_id,order_id,correlation_id) VALUES (?,?,?)',
                (event['event_id'], order_ids[0], event['correlation_id']),
            )
            inserted = True
    log.info(json.dumps({
        'level': 'INFO',
        'service': 'notifications',
        'event': 'order_event_consumed' if inserted else 'duplicate_ignored',
        'order_id': order_ids[0],
        'correlation_id': event['correlation_id'],
    }))
    return inserted


def configure_queues(channel):
    channel.exchange_declare(exchange='malta.events', exchange_type='topic', durable=True)
    channel.exchange_declare(exchange='malta.dead', exchange_type='direct', durable=True)
    channel.queue_declare(queue='notification.order_placed.dead', durable=True)
    channel.queue_bind(
        exchange='malta.dead',
        queue='notification.order_placed.dead',
        routing_key='notification.order_placed.dead',
    )
    channel.queue_declare(
        queue='notification.order_placed',
        durable=True,
        arguments={
            'x-dead-letter-exchange': 'malta.dead',
            'x-dead-letter-routing-key': 'notification.order_placed.dead',
        },
    )
    for routing_key in EVENT_ROUTING_KEYS.values():
        channel.queue_bind(
            exchange='malta.events',
            queue='notification.order_placed',
            routing_key=routing_key,
        )


def on_message(channel, method, properties, body):
    try:
        apply_event(json.loads(body))
    except Exception:
        log.exception(
            'Event handling failed; message_id=%s',
            getattr(properties, 'message_id', None),
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    else:
        channel.basic_ack(delivery_tag=method.delivery_tag)


def run():
    initialize()
    while True:
        if not email_is_configured():
            log.error('Email queue is waiting for SMTP setup: %s', email_configuration_error())
            time.sleep(30)
            continue
        conn = None
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(host=HOST, heartbeat=30))
            channel = conn.channel()
            configure_queues(channel)
            channel.basic_qos(prefetch_count=10)
            channel.basic_consume(queue='notification.order_placed', on_message_callback=on_message)
            log.info(json.dumps({'level': 'INFO', 'service': 'notifications', 'event': 'consumer_ready'}))
            channel.start_consuming()
        except Exception as exc:
            log.warning('Broker unavailable; retrying: %s', exc)
        finally:
            if conn is not None and conn.is_open:
                try:
                    conn.close()
                except Exception:
                    log.exception('Failed to close RabbitMQ connection')
        time.sleep(3)


if __name__ == '__main__':
    run()
