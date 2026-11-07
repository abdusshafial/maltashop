"""MaltaShop demo Order API with transactional outbox, independent SQLite DB."""
import json, logging, os, sqlite3, uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import pika
from pathlib import Path

DB = os.getenv('ORDER_DB', '/data/orders.db')
RABBIT = os.getenv('RABBITMQ_HOST', 'rabbitmq')
logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('orders')
app = FastAPI(title='MaltaShop Order Service', version='1.0')

class OrderIn(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0, le=100)

class OrderLine(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0, le=100)

class OrderBatchIn(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    items: list[OrderLine] = Field(min_length=1, max_length=20)

@contextmanager
def connect():
    conn = sqlite3.connect(DB, timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()

def initialize():
    os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, sku TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, correlation_id TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS batch_requests (idempotency_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')

initialize()

@app.get('/health')
def health():
    return {'status':'ok','service':'orders'}

@app.post('/orders', status_code=202)
def create_order(body: OrderIn, x_correlation_id: str | None = Header(None), idempotency_key: str | None = Header(None)):
    cid = x_correlation_id or str(uuid.uuid4())
    oid = idempotency_key or str(uuid.uuid4())
    payload = {'event_id':str(uuid.uuid4()), 'type':'OrderPlaced', 'order_id':oid, 'customer_id':body.customer_id, 'sku':body.sku, 'quantity':body.quantity, 'correlation_id':cid, 'occurred_at':datetime.now(timezone.utc).isoformat()}
    with connect() as db:
        existing = db.execute('SELECT id,correlation_id,status,customer_id,sku,quantity FROM orders WHERE id=?',(oid,)).fetchone()
        if existing:
            if (existing[3],existing[4],existing[5]) != (body.customer_id,body.sku,body.quantity):
                raise HTTPException(409,'Idempotency key already used with different payload')
            return {'order_id':oid,'status':existing[2],'correlation_id':existing[1], 'duplicate':True}
        db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?)',(oid,body.customer_id,body.sku,body.quantity,'PENDING',cid))
        db.execute('INSERT INTO outbox VALUES (?,?,0)',(payload['event_id'],json.dumps(payload)))
    log.info(json.dumps({'level':'INFO','service':'orders','event':'order_created','order_id':oid,'correlation_id':cid}))
    return {'order_id':oid,'status':'PENDING','correlation_id':cid,'duplicate':False}

@app.post('/orders/batch', status_code=202)
def create_order_batch(body: OrderBatchIn, x_correlation_id: str | None = Header(None), idempotency_key: str | None = Header(None)):
    if len({item.sku for item in body.items}) != len(body.items):
        raise HTTPException(422, 'Each SKU can appear only once in an order')

    batch_id = idempotency_key or str(uuid.uuid4())
    cid = x_correlation_id or str(uuid.uuid4())
    request_payload = json.dumps({
        'customer_id': body.customer_id,
        'items': sorted(
            [{'sku': item.sku, 'quantity': item.quantity} for item in body.items],
            key=lambda item: item['sku']
        )
    }, sort_keys=True, separators=(',', ':'))
    orders = []
    with connect() as db:
        existing_request = db.execute(
            'SELECT payload FROM batch_requests WHERE idempotency_key=?',
            (batch_id,)
        ).fetchone()
        if existing_request and existing_request[0] != request_payload:
            raise HTTPException(409, 'Idempotency key already used with different payload')
        if not existing_request:
            db.execute(
                'INSERT INTO batch_requests VALUES (?,?)',
                (batch_id, request_payload)
            )

        for item in body.items:
            oid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'maltashop:{batch_id}:{item.sku}'))
            existing = db.execute(
                'SELECT id,correlation_id,status,customer_id,sku,quantity FROM orders WHERE id=?',
                (oid,)
            ).fetchone()
            if existing:
                if (existing[3], existing[4], existing[5]) != (body.customer_id, item.sku, item.quantity):
                    raise HTTPException(409, 'Idempotency key already used with different payload')
                orders.append({
                    'order_id': oid, 'sku': item.sku, 'quantity': item.quantity,
                    'status': existing[2], 'duplicate': True
                })
                continue

            event_id = str(uuid.uuid4())
            payload = {
                'event_id': event_id, 'type': 'OrderPlaced', 'order_id': oid,
                'customer_id': body.customer_id, 'sku': item.sku, 'quantity': item.quantity,
                'correlation_id': cid, 'occurred_at': datetime.now(timezone.utc).isoformat()
            }
            db.execute(
                'INSERT INTO orders VALUES (?,?,?,?,?,?)',
                (oid, body.customer_id, item.sku, item.quantity, 'PENDING', cid)
            )
            db.execute('INSERT INTO outbox VALUES (?,?,0)', (event_id, json.dumps(payload)))
            orders.append({
                'order_id': oid, 'sku': item.sku, 'quantity': item.quantity,
                'status': 'PENDING', 'duplicate': False
            })

    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'order_batch_created',
        'order_ids': [order['order_id'] for order in orders], 'correlation_id': cid
    }))
    return {'orders': orders, 'correlation_id': cid}

@app.get('/orders/{order_id}')
def get_order(order_id: str):
    with connect() as db:
        row = db.execute('SELECT id,customer_id,sku,quantity,status,correlation_id FROM orders WHERE id=?',(order_id,)).fetchone()
    if not row: raise HTTPException(404,'Not found')
    return dict(zip(['order_id','customer_id','sku','quantity','status','correlation_id'],row))

@app.get('/')
def storefront():
    return FileResponse(Path(__file__).parent / 'static' / 'index.html')

app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')

def publish_pending():
    """At-least-once: crash after publish can duplicate; consumers deduplicate."""
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT, heartbeat=30))
    try:
        channel = connection.channel()
        channel.exchange_declare(exchange='malta.events',exchange_type='topic',durable=True)
        channel.exchange_declare(exchange='malta.dead',exchange_type='direct',durable=True)
        channel.queue_declare(queue='notification.order_placed.dead',durable=True)
        channel.queue_bind(exchange='malta.dead',queue='notification.order_placed.dead',routing_key='notification.order_placed.dead')
        channel.queue_declare(
            queue='notification.order_placed',
            durable=True,
            arguments={
                'x-dead-letter-exchange':'malta.dead',
                'x-dead-letter-routing-key':'notification.order_placed.dead'
            }
        )
        channel.queue_bind(exchange='malta.events',queue='notification.order_placed',routing_key='order.placed')
        with connect() as db:
            rows=db.execute('SELECT event_id,payload FROM outbox WHERE published=0 ORDER BY rowid LIMIT 50').fetchall()
        for eid,payload in rows:
            channel.basic_publish(exchange='malta.events',routing_key='order.placed',body=payload,properties=pika.BasicProperties(delivery_mode=2,message_id=eid,content_type='application/json'),mandatory=False)
            with connect() as db:
                db.execute('UPDATE outbox SET published=1 WHERE event_id=?',(eid,))
            event=json.loads(payload)
            log.info(json.dumps({'level':'INFO','service':'orders','event':'order_event_published','event_id':eid,'correlation_id':event['correlation_id']}))
    finally: connection.close()
