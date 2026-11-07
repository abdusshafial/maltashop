"""MaltaShop Notification worker with an independent SQLite database."""
import json, logging, os, sqlite3, time
from contextlib import contextmanager
import pika
DB=os.getenv('NOTIFICATION_DB','/data/notifications.db')
HOST=os.getenv('RABBITMQ_HOST','rabbitmq')
logging.basicConfig(level=logging.INFO, format='%(message)s')
log=logging.getLogger('notifications')
@contextmanager
def connect():
    db=sqlite3.connect(DB, timeout=10)
    try:
        yield db;db.commit()
    except Exception:db.rollback();raise
    finally:db.close()
def initialize():
    os.makedirs(os.path.dirname(DB) or '.',exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS received_events (event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, correlation_id TEXT NOT NULL, processed_at TEXT DEFAULT CURRENT_TIMESTAMP)')

def apply_event(event):
    if not isinstance(event, dict):
        raise ValueError('Event must be a JSON object')
    if event.get('type')!='OrderPlaced': raise ValueError('Unsupported event')
    for k in ('event_id','order_id','correlation_id'):
        value=event.get(k)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Missing '+k)
    with connect() as db:
        before=db.total_changes
        db.execute('INSERT OR IGNORE INTO received_events(event_id,order_id,correlation_id) VALUES (?,?,?)',(event['event_id'],event['order_id'],event['correlation_id']))
        inserted=db.total_changes>before
    log.info(json.dumps({'level':'INFO','service':'notifications','event':'order_event_consumed' if inserted else 'duplicate_ignored','order_id':event['order_id'],'correlation_id':event['correlation_id']}))
    return inserted

def configure_queues(channel):
    channel.exchange_declare(exchange='malta.events',exchange_type='topic',durable=True)
    channel.exchange_declare(exchange='malta.dead',exchange_type='direct',durable=True)
    channel.queue_declare(queue='notification.order_placed.dead',durable=True)
    channel.queue_bind(
        exchange='malta.dead',
        queue='notification.order_placed.dead',
        routing_key='notification.order_placed.dead'
    )
    channel.queue_declare(
        queue='notification.order_placed',
        durable=True,
        arguments={
            'x-dead-letter-exchange':'malta.dead',
            'x-dead-letter-routing-key':'notification.order_placed.dead'
        }
    )
    channel.queue_bind(exchange='malta.events',queue='notification.order_placed',routing_key='order.placed')

def on_message(channel, method, properties, body):
    try:
        apply_event(json.loads(body))
    except Exception:
        log.exception(
            'Event handling failed; message_id=%s',
            getattr(properties, 'message_id', None)
        )
        channel.basic_nack(delivery_tag=method.delivery_tag,requeue=False)
    else:
        channel.basic_ack(delivery_tag=method.delivery_tag)

def run():
    initialize()
    while True:
        conn = None
        try:
            conn=pika.BlockingConnection(pika.ConnectionParameters(host=HOST,heartbeat=30))
            ch=conn.channel()
            configure_queues(ch)
            ch.basic_qos(prefetch_count=10)
            ch.basic_consume(queue='notification.order_placed',on_message_callback=on_message)
            log.info(json.dumps({'level':'INFO','service':'notifications','event':'consumer_ready'}))
            ch.start_consuming()
        except Exception as exc:
            log.warning('Broker unavailable; retrying: %s',exc)
        finally:
            if conn is not None and conn.is_open:
                try:
                    conn.close()
                except Exception:
                    log.exception('Failed to close RabbitMQ connection')
        time.sleep(3)
if __name__=='__main__':run()
