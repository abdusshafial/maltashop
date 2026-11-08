"""MaltaShop demo Order API with transactional outbox, independent SQLite DB."""
import json, logging, os, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
import pika
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = os.getenv('ORDER_DB', str(PROJECT_ROOT / 'data' / 'orders.db'))
RABBIT = os.getenv('RABBITMQ_HOST', 'rabbitmq')
MIN_DELIVERY_DAYS = 2
MAX_DELIVERY_DAYS = 5
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
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, min_length=5, max_length=30)
    address: str | None = Field(default=None, min_length=5, max_length=250)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    postal_code: str | None = Field(default=None, min_length=2, max_length=20)
    payment_method: str = Field(default='cash', pattern='^(card|paypal|cash)$')

    @model_validator(mode='after')
    def require_complete_delivery_details(self):
        details = (self.full_name, self.phone, self.address, self.city, self.postal_code)
        if any(value is not None for value in details) and not all(details):
            raise ValueError('Provide your name, phone, street address, city, and postal code')
        return self

class MyOrdersIn(BaseModel):
    email: str = Field(min_length=3, max_length=100)
    phone: str = Field(min_length=5, max_length=30)

class CancelOrderIn(MyOrdersIn):
    correlation_id: str = Field(min_length=1, max_length=100)

class OrderComplaintIn(MyOrdersIn):
    correlation_id: str = Field(min_length=1, max_length=100)
    complaint_type: str = Field(pattern='^(product|delivery)$')
    product_sku: str | None = Field(default=None, min_length=1, max_length=80)
    message: str = Field(min_length=10, max_length=2000)

    @model_validator(mode='after')
    def require_product_for_product_complaint(self):
        if self.complaint_type == 'product' and not self.product_sku:
            raise ValueError('Choose the product you are complaining about')
        if self.complaint_type == 'delivery' and self.product_sku:
            raise ValueError('A product must not be selected for a delivery complaint')
        self.message = self.message.strip()
        if len(self.message) < 10:
            raise ValueError('Describe your complaint in at least 10 characters')
        return self

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
        db.execute(
            'CREATE TABLE IF NOT EXISTS complaints ('
            'id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, complaint_type TEXT NOT NULL, '
            'product_sku TEXT, message TEXT NOT NULL, created_at TEXT NOT NULL)'
        )
        columns = {row[1] for row in db.execute('PRAGMA table_info(orders)')}
        new_columns = {
            'full_name': "TEXT NOT NULL DEFAULT ''",
            'phone': "TEXT NOT NULL DEFAULT ''",
            'address': "TEXT NOT NULL DEFAULT ''",
            'city': "TEXT NOT NULL DEFAULT ''",
            'postal_code': "TEXT NOT NULL DEFAULT ''",
            'payment_method': "TEXT NOT NULL DEFAULT 'cash'",
            'created_at': "TEXT NOT NULL DEFAULT ''",
            'delivery_min_days': f'INTEGER NOT NULL DEFAULT {MIN_DELIVERY_DAYS}',
            'delivery_max_days': f'INTEGER NOT NULL DEFAULT {MAX_DELIVERY_DAYS}',
        }
        for column, definition in new_columns.items():
            if column not in columns:
                db.execute(f'ALTER TABLE orders ADD COLUMN {column} {definition}')

initialize()

def add_business_days(start: datetime, business_days: int) -> str:
    delivery_date = start.date()
    days_added = 0
    while days_added < business_days:
        delivery_date += timedelta(days=1)
        if delivery_date.weekday() < 5:
            days_added += 1
    return delivery_date.isoformat()

def delivery_dates(created_at: str) -> tuple[str | None, str | None]:
    if not created_at:
        return None, None
    created = datetime.fromisoformat(created_at)
    return (
        add_business_days(created, MIN_DELIVERY_DAYS),
        add_business_days(created, MAX_DELIVERY_DAYS),
    )

def normalized_phone(phone: str) -> str:
    digits = ''.join(character for character in phone if character.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('356') and len(digits) == 11:
        return digits[3:]
    return digits

def parse_order_time(created_at: str) -> datetime | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc)

def cancellation_details(created_at: str, now: datetime | None = None) -> tuple[str | None, bool]:
    created = parse_order_time(created_at)
    if created is None:
        return None, False
    deadline = created + timedelta(hours=12)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return deadline.isoformat(), current_time.astimezone(timezone.utc) <= deadline

@app.get('/health')
def health():
    return {'status':'ok','service':'orders'}

@app.post('/orders', status_code=202)
def create_order(body: OrderIn, x_correlation_id: str | None = Header(None), idempotency_key: str | None = Header(None)):
    cid = x_correlation_id or str(uuid.uuid4())
    oid = idempotency_key or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {'event_id':str(uuid.uuid4()), 'type':'OrderPlaced', 'order_id':oid, 'customer_id':body.customer_id, 'sku':body.sku, 'quantity':body.quantity, 'correlation_id':cid, 'occurred_at':created_at}
    with connect() as db:
        existing = db.execute('SELECT id,correlation_id,status,customer_id,sku,quantity FROM orders WHERE id=?',(oid,)).fetchone()
        if existing:
            if (existing[3],existing[4],existing[5]) != (body.customer_id,body.sku,body.quantity):
                raise HTTPException(409,'Idempotency key already used with different payload')
            return {'order_id':oid,'status':existing[2],'correlation_id':existing[1], 'duplicate':True}
        db.execute(
            'INSERT INTO orders (id,customer_id,sku,quantity,status,correlation_id,created_at,delivery_min_days,delivery_max_days) VALUES (?,?,?,?,?,?,?,?,?)',
            (oid,body.customer_id,body.sku,body.quantity,'PENDING',cid,created_at,MIN_DELIVERY_DAYS,MAX_DELIVERY_DAYS)
        )
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
        'full_name': body.full_name,
        'phone': body.phone,
        'address': body.address,
        'city': body.city,
        'postal_code': body.postal_code,
        'payment_method': body.payment_method,
        'items': sorted(
            [{'sku': item.sku, 'quantity': item.quantity} for item in body.items],
            key=lambda item: item['sku']
        )
    }, sort_keys=True, separators=(',', ':'))
    orders = []
    created_at = datetime.now(timezone.utc).isoformat()
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
                'SELECT id,correlation_id,status,customer_id,sku,quantity,created_at FROM orders WHERE id=?',
                (oid,)
            ).fetchone()
            if existing:
                if (existing[3], existing[4], existing[5]) != (body.customer_id, item.sku, item.quantity):
                    raise HTTPException(409, 'Idempotency key already used with different payload')
                earliest_delivery, latest_delivery = delivery_dates(existing[6])
                orders.append({
                    'order_id': oid, 'sku': item.sku, 'quantity': item.quantity,
                    'status': existing[2], 'duplicate': True,
                    'delivery_min_days': MIN_DELIVERY_DAYS,
                    'delivery_max_days': MAX_DELIVERY_DAYS,
                    'earliest_delivery': earliest_delivery, 'latest_delivery': latest_delivery
                })
                continue

            event_id = str(uuid.uuid4())
            payload = {
                'event_id': event_id, 'type': 'OrderPlaced', 'order_id': oid,
                'customer_id': body.customer_id, 'sku': item.sku, 'quantity': item.quantity,
                'correlation_id': cid, 'occurred_at': created_at
            }
            db.execute(
                'INSERT INTO orders (id,customer_id,sku,quantity,status,correlation_id,full_name,phone,address,city,postal_code,payment_method,created_at,delivery_min_days,delivery_max_days) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    oid, body.customer_id, item.sku, item.quantity, 'PENDING', cid,
                    body.full_name or '', body.phone or '', body.address or '',
                    body.city or '', body.postal_code or '', body.payment_method,
                    created_at, MIN_DELIVERY_DAYS, MAX_DELIVERY_DAYS
                )
            )
            db.execute('INSERT INTO outbox VALUES (?,?,0)', (event_id, json.dumps(payload)))
            earliest_delivery, latest_delivery = delivery_dates(created_at)
            orders.append({
                'order_id': oid, 'sku': item.sku, 'quantity': item.quantity,
                'status': 'PENDING', 'duplicate': False,
                'delivery_min_days': MIN_DELIVERY_DAYS,
                'delivery_max_days': MAX_DELIVERY_DAYS,
                'earliest_delivery': earliest_delivery, 'latest_delivery': latest_delivery
            })

    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'order_batch_created',
        'order_ids': [order['order_id'] for order in orders], 'correlation_id': cid
    }))
    return {'orders': orders, 'correlation_id': cid}

@app.post('/orders/my')
def list_my_orders(body: MyOrdersIn):
    email = body.email.strip().casefold()
    phone = normalized_phone(body.phone)
    if len(phone) < 5:
        raise HTTPException(422, 'Enter a valid phone number')

    with connect() as db:
        rows = db.execute(
            'SELECT id,sku,quantity,status,correlation_id,created_at,delivery_min_days,delivery_max_days,phone '
            'FROM orders WHERE lower(trim(customer_id))=? ORDER BY created_at DESC,id',
            (email,)
        ).fetchall()

    matching_rows = [row for row in rows if normalized_phone(row[8]) == phone]
    grouped = {}
    for row in matching_rows:
        order = grouped.get(row[4])
        deadline, within_window = cancellation_details(row[5])
        if order is None:
            order = {
                'correlation_id': row[4],
                'status': row[3],
                'created_at': row[5] or None,
                'cancellation_deadline': deadline,
                'can_cancel': row[3] == 'PENDING' and within_window,
                'delivery_min_days': row[6],
                'delivery_max_days': row[7],
                'items': [],
            }
            grouped[row[4]] = order
        order['items'].append({
            'sku': row[1],
            'quantity': row[2],
        })
        if row[3] != order['status']:
            order['status'] = 'PENDING'
        if row[3] != 'PENDING':
            order['can_cancel'] = False

    return {'orders': list(grouped.values())}

@app.post('/orders/my/cancel')
def cancel_my_order(body: CancelOrderIn):
    email = body.email.strip().casefold()
    phone = normalized_phone(body.phone)
    if len(phone) < 5:
        raise HTTPException(422, 'Enter a valid phone number')

    with connect() as db:
        rows = db.execute(
            'SELECT id,status,created_at,phone FROM orders '
            'WHERE correlation_id=? AND lower(trim(customer_id))=?',
            (body.correlation_id, email)
        ).fetchall()
        if not rows or any(normalized_phone(row[3]) != phone for row in rows):
            raise HTTPException(404, 'Order not found')
        if all(row[1] == 'CANCELLED' for row in rows):
            return {'status': 'CANCELLED', 'already_cancelled': True}
        if any(row[1] != 'PENDING' for row in rows):
            raise HTTPException(409, 'This order can no longer be cancelled')
        if any(not cancellation_details(row[2])[1] for row in rows):
            raise HTTPException(409, 'The 12-hour cancellation period has expired')

        order_ids = [row[0] for row in rows]
        placeholders = ','.join('?' for _ in order_ids)
        db.execute(
            f"UPDATE orders SET status='CANCELLED' WHERE id IN ({placeholders}) AND status='PENDING'",
            order_ids
        )
        updated_count = db.execute(
            f"SELECT count(*) FROM orders WHERE id IN ({placeholders}) AND status='CANCELLED'",
            order_ids
        ).fetchone()[0]
        if updated_count != len(order_ids):
            raise HTTPException(409, 'This order can no longer be cancelled')

    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'order_cancelled',
        'order_ids': order_ids, 'correlation_id': body.correlation_id
    }))
    return {'status': 'CANCELLED', 'already_cancelled': False}

@app.post('/orders/complaints', status_code=201)
def create_order_complaint(body: OrderComplaintIn):
    email = body.email.strip().casefold()
    phone = normalized_phone(body.phone)
    if len(phone) < 5:
        raise HTTPException(422, 'Enter a valid phone number')

    with connect() as db:
        rows = db.execute(
            'SELECT sku,phone FROM orders '
            'WHERE correlation_id=? AND lower(trim(customer_id))=?',
            (body.correlation_id, email)
        ).fetchall()
        if not rows or any(normalized_phone(row[1]) != phone for row in rows):
            raise HTTPException(404, 'Order not found')
        if body.complaint_type == 'product' and body.product_sku not in {row[0] for row in rows}:
            raise HTTPException(422, 'The selected product is not part of this order')

        complaint_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        db.execute(
            'INSERT INTO complaints (id,correlation_id,complaint_type,product_sku,message,created_at) '
            'VALUES (?,?,?,?,?,?)',
            (complaint_id, body.correlation_id, body.complaint_type, body.product_sku, body.message.strip(), created_at)
        )

    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'order_complaint_created',
        'complaint_id': complaint_id, 'correlation_id': body.correlation_id,
        'complaint_type': body.complaint_type
    }))
    return {'complaint_id': complaint_id, 'status': 'RECEIVED', 'created_at': created_at}

@app.get('/orders/{order_id}')
def get_order(order_id: str):
    with connect() as db:
        row = db.execute(
            'SELECT id,customer_id,sku,quantity,status,correlation_id,created_at,delivery_min_days,delivery_max_days,payment_method FROM orders WHERE id=?',
            (order_id,)
        ).fetchone()
    if not row: raise HTTPException(404,'Not found')
    earliest_delivery, latest_delivery = delivery_dates(row[6])
    return {
        'order_id': row[0],
        'customer_id': row[1],
        'sku': row[2],
        'quantity': row[3],
        'status': row[4],
        'correlation_id': row[5],
        'created_at': row[6] or None,
        'delivery_min_days': row[7],
        'delivery_max_days': row[8],
        'earliest_delivery': earliest_delivery,
        'latest_delivery': latest_delivery,
        'payment_method': row[9],
    }

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
