"""MaltaShop demo Order API with transactional outbox, independent SQLite DB."""
import hashlib, hmac, json, logging, os, re, secrets, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
import pika
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = os.getenv('ORDER_DB', str(PROJECT_ROOT / 'data' / 'orders.db'))
RABBIT = os.getenv('RABBITMQ_HOST', 'rabbitmq')
PUBLIC_APP_URL = os.getenv('PUBLIC_APP_URL', 'http://127.0.0.1:8000').rstrip('/')
MIN_DELIVERY_DAYS = 2
MAX_DELIVERY_DAYS = 5
LOCATION_STALE_AFTER = timedelta(minutes=2)
NOTIFICATION_ROUTING_KEYS = {
    'OrderPlaced': 'order.placed',
    'OrderAccepted': 'order.accepted',
    'OrderCancelled': 'order.cancelled',
    'PasswordReset': 'password.reset',
}
SESSION_COOKIE = 'maltashop_session'
SESSION_DAYS = 30
PASSWORD_RESET_MINUTES = 30
PASSWORD_RESET_REQUEST_COOLDOWN = timedelta(minutes=1)
PASSWORD_ITERATIONS = 310_000
PRODUCT_ROLES = ('admin', 'product_management_officer')
INVENTORY_ROLES = ('admin', 'inventory_manager')
STAFF_ROLES = (
    'admin', 'product_management_officer', 'inventory_manager',
    'order_fulfillment_officer', 'finance_officer',
)
logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('orders')
app = FastAPI(title='MaltaShop Order Service', version='1.0')

class OrderIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0, le=100)

class OrderLine(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0, le=100)

class OrderBatchIn(BaseModel):
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
    email: str = Field(default='', max_length=100)
    phone: str = Field(default='', max_length=30)

class CancelOrderIn(MyOrdersIn):
    correlation_id: str = Field(min_length=1, max_length=100)

class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=10, max_length=256)
    full_name: str = Field(min_length=1, max_length=100)

class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=256)

class PasswordResetRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=100)

class PasswordResetIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=10, max_length=256)

class AdminUserIn(RegisterIn):
    role: str = Field(pattern='^(customer|admin|product_management_officer|inventory_manager|order_fulfillment_officer|finance_officer)$')

class UserRoleIn(BaseModel):
    role: str = Field(pattern='^(customer|admin|product_management_officer|inventory_manager|order_fulfillment_officer|finance_officer)$')
    is_active: bool = True

class FulfillmentUpdateIn(BaseModel):
    status: str = Field(pattern='^(RECEIVED|DISPATCHED|DELIVERED)$')
    facility: str | None = Field(default=None, min_length=2, max_length=120)
    tracking_reference: str | None = Field(default=None, min_length=3, max_length=100)

    @model_validator(mode='after')
    def require_dispatch_details(self):
        if self.status == 'DISPATCHED' and (not self.facility or not self.tracking_reference):
            raise ValueError('Enter the delivery facility and tracking reference before dispatch')
        return self

class DeliveryLocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0, le=10000)

class PaymentUpdateIn(BaseModel):
    payment_status: str = Field(pattern='^(PAID|REFUNDED)$')

class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80, pattern='^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=60)
    price: float = Field(gt=0, le=100000)
    stock: int = Field(default=0, ge=0, le=1_000_000)
    tag: str = Field(default='NEW ARRIVAL', max_length=50)
    image: str = Field(min_length=1, max_length=1000)
    description: str = Field(default='', max_length=2000)
    active: bool = True

class ProductUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    price: float | None = Field(default=None, gt=0, le=100000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    tag: str | None = Field(default=None, max_length=50)
    image: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None

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

class ProductReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=3, max_length=1000)

    @model_validator(mode='after')
    def normalize_comment(self):
        self.comment = self.comment.strip()
        if len(self.comment) < 3:
            raise ValueError('Write at least 3 characters in your review')
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

def normalize_email(email: str) -> str:
    return email.strip().casefold()

def location_is_fresh(updated_at: str, now: datetime | None = None) -> bool:
    updated = datetime.fromisoformat(updated_at)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return current - updated <= LOCATION_STALE_AFTER

def delivery_location_response(row, now: datetime | None = None) -> dict | None:
    if not row:
        return None
    result = {
        'status': 'live' if location_is_fresh(row[3], now) else 'stale',
        'updated_at': row[3],
    }
    if result['status'] == 'live':
        result.update({
            'latitude': row[0],
            'longitude': row[1],
            'accuracy': row[2],
        })
    return result

def enqueue_order_notification(
    db: sqlite3.Connection,
    event_type: str,
    correlation_id: str,
    recipient_email: str,
    customer_name: str,
    items: list[dict],
    occurred_at: str,
) -> None:
    event_id = str(uuid.uuid4())
    order_ids = [item['order_id'] for item in items]
    payload = {
        'event_id': event_id,
        'type': event_type,
        'order_id': order_ids[0],
        'order_ids': order_ids,
        'recipient_email': recipient_email,
        'customer_name': customer_name,
        'items': [
            {
                'order_id': item['order_id'],
                'sku': item['sku'],
                'name': item['name'],
                'quantity': item['quantity'],
            }
            for item in items
        ],
        'correlation_id': correlation_id,
        'occurred_at': occurred_at,
    }
    db.execute(
        'INSERT INTO outbox (event_id,payload,published) VALUES (?,?,0)',
        (event_id, json.dumps(payload)),
    )

def hash_password(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), actual_salt, PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${actual_salt.hex()}${digest.hex()}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        candidate = hash_password(password, bytes.fromhex(salt_hex)).split('$')[3]
        return hmac.compare_digest(candidate, digest_hex) and int(iterations) == PASSWORD_ITERATIONS
    except (ValueError, TypeError):
        return False

def cookie_secure() -> bool:
    return os.getenv('SESSION_COOKIE_SECURE', 'true').strip().casefold() not in {'0', 'false', 'no'}

def require_same_origin(request: Request) -> None:
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc.casefold() != request.headers.get('host', '').casefold():
            raise HTTPException(403, 'Cross-origin requests are not allowed')

def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, 'Please log in to continue')
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        row = db.execute(
            'SELECT users.id,users.email,users.full_name,users.role,users.is_active '
            'FROM sessions JOIN users ON users.id=sessions.user_id '
            'WHERE sessions.token_hash=? AND sessions.expires_at>? ',
            (token_hash, now)
        ).fetchone()
    if not row or not row[4]:
        raise HTTPException(401, 'Your session has expired. Please log in again')
    return {'id': row[0], 'email': row[1], 'full_name': row[2], 'role': row[3]}

def require_roles(*roles: str):
    def role_dependency(user: dict = Depends(get_current_user)) -> dict:
        if user['role'] not in roles:
            raise HTTPException(403, 'You do not have permission to perform this action')
        return user
    return role_dependency

def create_session(db: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    created = datetime.now(timezone.utc)
    db.execute(
        'INSERT INTO sessions (token_hash,user_id,created_at,expires_at) VALUES (?,?,?,?)',
        (token_hash, user_id, created.isoformat(), (created + timedelta(days=SESSION_DAYS)).isoformat())
    )
    return token

def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True, secure=cookie_secure(), samesite='strict', path='/'
    )

def public_user(user: dict) -> dict:
    return {
        'id': user['id'], 'email': user['email'],
        'full_name': user['full_name'], 'role': user['role']
    }

def new_tracking_id() -> str:
    return f"MT-{uuid.uuid4().hex.upper()}"

def initialize():
    os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, sku TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, correlation_id TEXT NOT NULL)')
        db.execute(
            'CREATE TABLE IF NOT EXISTS delivery_locations ('
            'correlation_id TEXT PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL, '
            'accuracy REAL NOT NULL, updated_at TEXT NOT NULL, shared_by TEXT NOT NULL)'
        )
        db.execute('CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS batch_requests (idempotency_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute(
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
            "full_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL "
            "CHECK(role IN ('customer','admin','product_management_officer','inventory_manager',"
            "'order_fulfillment_officer','finance_officer')), "
            "is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)"
        )
        user_table_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()[0]
        if "'inventory_manager'" not in user_table_sql:
            db.execute(
                "CREATE TABLE users_migrated (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,"
                "full_name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL "
                "CHECK(role IN ('customer','admin','product_management_officer','inventory_manager',"
                "'order_fulfillment_officer','finance_officer')),is_active INTEGER NOT NULL DEFAULT 1,"
                "created_at TEXT NOT NULL)"
            )
            db.execute(
                'INSERT INTO users_migrated (id,email,full_name,password_hash,role,is_active,created_at) '
                'SELECT id,email,full_name,password_hash,role,is_active,created_at FROM users'
            )
            db.execute('DROP TABLE users')
            db.execute('ALTER TABLE users_migrated RENAME TO users')
        db.execute(
            'CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,'
            'created_at TEXT NOT NULL,expires_at TEXT NOT NULL)'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS password_reset_tokens ('
            'token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL)'
        )
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id)'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS password_reset_requests ('
            'email_hash TEXT PRIMARY KEY,requested_at TEXT NOT NULL)'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,'
            'price_cents INTEGER NOT NULL CHECK(price_cents>0),stock INTEGER NOT NULL CHECK(stock>=0),'
            'tag TEXT NOT NULL,image TEXT NOT NULL,description TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,'
            'updated_at TEXT NOT NULL)'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS complaints ('
            'id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, complaint_type TEXT NOT NULL, '
            'product_sku TEXT, message TEXT NOT NULL, created_at TEXT NOT NULL)'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS product_reviews ('
            'id TEXT PRIMARY KEY, user_id TEXT NOT NULL, product_sku TEXT NOT NULL, '
            'rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), comment TEXT NOT NULL, '
            'created_at TEXT NOT NULL, UNIQUE(user_id,product_sku))'
        )
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_product_reviews_sku_created '
            'ON product_reviews(product_sku,created_at DESC)'
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
            'user_id': 'TEXT',
            'product_name': "TEXT NOT NULL DEFAULT ''",
            'unit_price_cents': 'INTEGER NOT NULL DEFAULT 0',
            'product_category': "TEXT NOT NULL DEFAULT ''",
            'payment_status': "TEXT NOT NULL DEFAULT 'UNPAID'",
            'delivery_facility': "TEXT NOT NULL DEFAULT ''",
            'delivery_tracking_id': "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in new_columns.items():
            if column not in columns:
                db.execute(f'ALTER TABLE orders ADD COLUMN {column} {definition}')
        untracked_orders = db.execute(
            "SELECT id FROM orders WHERE delivery_tracking_id=''"
        ).fetchall()
        for (order_id,) in untracked_orders:
            db.execute(
                'UPDATE orders SET delivery_tracking_id=? WHERE id=?',
                (new_tracking_id(), order_id)
            )
        db.execute('CREATE INDEX IF NOT EXISTS idx_orders_user_created ON orders(user_id,created_at)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)')
        seed_path = Path(__file__).parent / 'catalog_seed.json'
        with seed_path.open(encoding='utf-8') as seed_file:
            seed_products = json.load(seed_file)
        now = datetime.now(timezone.utc).isoformat()
        db.executemany(
            'INSERT OR IGNORE INTO products (sku,name,category,price_cents,stock,tag,image,description,active,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            [
                (product['sku'], product['name'], product['category'], int(round(product['price'] * 100)),
                 product['stock'], product['tag'], product['image'], product['description'],
                 int(product['active']), now)
                for product in seed_products
            ]
        )
        admin_email = os.getenv('INITIAL_ADMIN_EMAIL', '').strip()
        admin_password = os.getenv('INITIAL_ADMIN_PASSWORD', '')
        if bool(admin_email) != bool(admin_password):
            raise ValueError('Set both INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD to bootstrap the admin')
        if admin_email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', normalize_email(admin_email)):
            raise ValueError('INITIAL_ADMIN_EMAIL must be a valid email address')
        if admin_password and not 10 <= len(admin_password) <= 256:
            raise ValueError('INITIAL_ADMIN_PASSWORD must contain 10 to 256 characters')
        if admin_email and not db.execute('SELECT 1 FROM users WHERE lower(email)=?', (normalize_email(admin_email),)).fetchone():
            db.execute(
                'INSERT INTO users (id,email,full_name,password_hash,role,is_active,created_at) VALUES (?,?,?,?,?,?,?)',
                (str(uuid.uuid4()), normalize_email(admin_email),
                 os.getenv('INITIAL_ADMIN_NAME', 'Shop Administrator').strip() or 'Shop Administrator',
                 hash_password(admin_password), 'admin', 1, now)
            )
        if os.getenv('DEMO_ACCOUNTS', '').strip().casefold() in {'1', 'true', 'yes'}:
            demo_users = (
                ('demo-customer@maltashop.test', 'Demo Customer', 'Demo-Customer-2026!', 'customer'),
                ('demo-officer@maltashop.test', 'Demo Product Officer', 'Demo-Officer-2026!', 'product_management_officer'),
                ('demo-inventory@maltashop.test', 'Demo Inventory Manager', 'Demo-Inventory-2026!', 'inventory_manager'),
                ('demo-fulfillment@maltashop.test', 'Demo Order Fulfillment', 'Demo-Fulfillment-2026!', 'order_fulfillment_officer'),
                ('demo-finance@maltashop.test', 'Demo Finance Officer', 'Demo-Finance-2026!', 'finance_officer'),
                ('demo-admin@maltashop.test', 'Demo Administrator', 'Demo-Admin-2026!', 'admin'),
            )
            db.executemany(
                'INSERT OR IGNORE INTO users (id,email,full_name,password_hash,role,is_active,created_at) '
                'VALUES (?,?,?,?,?,?,?)',
                [
                    (str(uuid.uuid4()), email, full_name, hash_password(password), role, 1, now)
                    for email, full_name, password, role in demo_users
                ]
            )

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

@app.post('/auth/register', status_code=201, dependencies=[Depends(require_same_origin)])
def register(body: RegisterIn, response: Response):
    email = normalize_email(body.email)
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise HTTPException(422, 'Enter a valid email address')
    user = {
        'id': str(uuid.uuid4()), 'email': email, 'full_name': body.full_name.strip(),
        'role': 'customer'
    }
    if not user['full_name']:
        raise HTTPException(422, 'Enter your name')
    with connect() as db:
        if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
            raise HTTPException(409, 'An account with that email already exists')
        db.execute(
            'INSERT INTO users (id,email,full_name,password_hash,role,is_active,created_at) VALUES (?,?,?,?,?,?,?)',
            (user['id'], email, user['full_name'], hash_password(body.password), 'customer', 1,
             datetime.now(timezone.utc).isoformat())
        )
        token = create_session(db, user['id'])
    set_session_cookie(response, token)
    return public_user(user)

@app.post('/auth/login', dependencies=[Depends(require_same_origin)])
def login(body: LoginIn, response: Response):
    email = normalize_email(body.email)
    with connect() as db:
        row = db.execute(
            'SELECT id,email,full_name,password_hash,role,is_active FROM users WHERE email=?',
            (email,)
        ).fetchone()
        if not row or not row[5] or not verify_password(body.password, row[3]):
            raise HTTPException(401, 'Email or password is incorrect')
        db.execute('DELETE FROM sessions WHERE expires_at<=?', (datetime.now(timezone.utc).isoformat(),))
        token = create_session(db, row[0])
    set_session_cookie(response, token)
    return public_user({'id': row[0], 'email': row[1], 'full_name': row[2], 'role': row[4]})

@app.post('/auth/password-reset/request', dependencies=[Depends(require_same_origin)])
def request_password_reset(body: PasswordResetRequestIn):
    email = normalize_email(body.email)
    email_hash = hashlib.sha256(email.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc)
    with connect() as db:
        previous = db.execute(
            'SELECT requested_at FROM password_reset_requests WHERE email_hash=?',
            (email_hash,)
        ).fetchone()
        if previous:
            previous_at = datetime.fromisoformat(previous[0])
            if now - previous_at < PASSWORD_RESET_REQUEST_COOLDOWN:
                return {'message': 'If an active account exists for that email, a password reset link will be sent.'}
        db.execute(
            'INSERT INTO password_reset_requests(email_hash,requested_at) VALUES (?,?) '
            'ON CONFLICT(email_hash) DO UPDATE SET requested_at=excluded.requested_at',
            (email_hash, now.isoformat())
        )
        user = db.execute(
            'SELECT id,email FROM users WHERE email=? AND is_active=1',
            (email,)
        ).fetchone()
        if user:
            reset_token = secrets.token_urlsafe(32)
            expires_at = (now + timedelta(minutes=PASSWORD_RESET_MINUTES)).isoformat()
            db.execute('DELETE FROM password_reset_tokens WHERE user_id=?', (user[0],))
            db.execute(
                'INSERT INTO password_reset_tokens(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)',
                (hashlib.sha256(reset_token.encode('utf-8')).hexdigest(), user[0], expires_at, now.isoformat())
            )
            event_id = str(uuid.uuid4())
            event = {
                'type': 'PasswordReset',
                'event_id': event_id,
                'recipient_email': user[1],
                'reset_url': f'{PUBLIC_APP_URL}/#reset-token={quote(reset_token, safe="")}',
                'expires_at': expires_at,
            }
            db.execute(
                'INSERT INTO outbox (event_id,payload,published) VALUES (?,?,0)',
                (event_id, json.dumps(event))
            )
    return {'message': 'If an active account exists for that email, a password reset link will be sent.'}

@app.post('/auth/password-reset/confirm', dependencies=[Depends(require_same_origin)])
def confirm_password_reset(body: PasswordResetIn):
    token_hash = hashlib.sha256(body.token.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc)
    with connect() as db:
        row = db.execute(
            'SELECT t.user_id,t.expires_at FROM password_reset_tokens t '
            'JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND u.is_active=1',
            (token_hash,)
        ).fetchone()
        if not row:
            raise HTTPException(400, 'This reset link is invalid or has expired.')
        if datetime.fromisoformat(row[1]) <= now:
            raise HTTPException(400, 'This reset link is invalid or has expired.')
        db.execute(
            'UPDATE users SET password_hash=? WHERE id=?',
            (hash_password(body.password), row[0])
        )
        db.execute('DELETE FROM password_reset_tokens WHERE user_id=?', (row[0],))
        db.execute('DELETE FROM sessions WHERE user_id=?', (row[0],))
    return {'message': 'Your password has been updated. Please log in.'}

@app.post('/auth/logout', dependencies=[Depends(require_same_origin)])
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash,))
    response.delete_cookie(SESSION_COOKIE, path='/', httponly=True, secure=cookie_secure(), samesite='strict')
    return {'status': 'logged_out'}

@app.get('/auth/me')
def current_user(user: dict = Depends(get_current_user)):
    return public_user(user)

def product_response(row: tuple) -> dict:
    return {
        'sku': row[0], 'name': row[1], 'category': row[2], 'price': row[3] / 100,
        'stock': row[4], 'tag': row[5], 'image': row[6], 'description': row[7],
        'active': bool(row[8])
    }

PRODUCT_SELECT = 'SELECT sku,name,category,price_cents,stock,tag,image,description,active FROM products'

@app.get('/products')
def list_products():
    with connect() as db:
        rows = db.execute(
            'SELECT p.sku,p.name,p.category,p.price_cents,p.stock,p.tag,p.image,p.description,p.active,'
            'COALESCE(AVG(r.rating),0),COUNT(r.id) '
            'FROM products p LEFT JOIN product_reviews r ON r.product_sku=p.sku '
            'WHERE p.active=1 GROUP BY p.sku ORDER BY p.name,p.sku'
        ).fetchall()
    return {'products': [
        {**product_response(row[:9]), 'average_rating': row[9], 'review_count': row[10]}
        for row in rows
    ]}

@app.get('/products/{sku}/reviews')
def list_product_reviews(sku: str):
    with connect() as db:
        rows = db.execute(
            'SELECT r.rating,r.comment,r.created_at,u.full_name '
            'FROM product_reviews r JOIN users u ON u.id=r.user_id '
            'WHERE r.product_sku=? ORDER BY r.created_at DESC,r.id DESC',
            (sku,)
        ).fetchall()
    reviews = [
        {'rating': row[0], 'comment': row[1], 'created_at': row[2], 'reviewer': 'Verified customer'}
        for row in rows
    ]
    return {
        'reviews': reviews,
        'review_count': len(reviews),
        'average_rating': round(sum(review['rating'] for review in reviews) / len(reviews), 1)
        if reviews else 0,
    }

@app.get('/products/{sku}/review-eligibility')
def product_review_eligibility(sku: str, user: dict = Depends(get_current_user)):
    if user['role'] != 'customer':
        raise HTTPException(403, 'Only customer accounts can leave product reviews')
    with connect() as db:
        purchased = db.execute(
            "SELECT 1 FROM orders WHERE user_id=? AND sku=? AND status='DELIVERED' LIMIT 1",
            (user['id'], sku)
        ).fetchone()
        review = db.execute(
            'SELECT rating,comment,created_at FROM product_reviews WHERE user_id=? AND product_sku=?',
            (user['id'], sku)
        ).fetchone()
    return {
        'eligible': bool(purchased) and review is None,
        'delivered': bool(purchased),
        'review': (
            {'rating': review[0], 'comment': review[1], 'created_at': review[2]}
            if review else None
        ),
    }

@app.post(
    '/products/{sku}/reviews',
    status_code=201,
    dependencies=[Depends(require_same_origin)],
)
def create_product_review(
    sku: str,
    body: ProductReviewIn,
    user: dict = Depends(get_current_user),
):
    if user['role'] != 'customer':
        raise HTTPException(403, 'Only customer accounts can leave product reviews')
    review_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with connect() as db:
            delivered_order = db.execute(
                "SELECT 1 FROM orders WHERE user_id=? AND sku=? AND status='DELIVERED' LIMIT 1",
                (user['id'], sku)
            ).fetchone()
            if not delivered_order:
                raise HTTPException(403, 'You can review a product after its order is delivered')
            db.execute(
                'INSERT INTO product_reviews (id,user_id,product_sku,rating,comment,created_at) '
                'VALUES (?,?,?,?,?,?)',
                (review_id, user['id'], sku, body.rating, body.comment, created_at)
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'You have already reviewed this product') from exc
    return {
        'id': review_id, 'rating': body.rating, 'comment': body.comment,
        'created_at': created_at, 'reviewer': 'Verified customer',
    }

@app.get('/admin/users')
def list_users(_admin: dict = Depends(require_roles('admin'))):
    with connect() as db:
        rows = db.execute(
            'SELECT id,email,full_name,role,is_active,created_at FROM users ORDER BY created_at,email'
        ).fetchall()
    return {'users': [
        {'id': row[0], 'email': row[1], 'full_name': row[2], 'role': row[3],
         'is_active': bool(row[4]), 'created_at': row[5]}
        for row in rows
    ]}

@app.post('/admin/users', status_code=201, dependencies=[Depends(require_same_origin)])
def create_managed_user(body: AdminUserIn, _admin: dict = Depends(require_roles('admin'))):
    email = normalize_email(body.email)
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise HTTPException(422, 'Enter a valid email address')
    user = {
        'id': str(uuid.uuid4()), 'email': email, 'full_name': body.full_name.strip(),
        'role': body.role
    }
    if not user['full_name']:
        raise HTTPException(422, 'Enter a name')
    try:
        with connect() as db:
            db.execute(
                'INSERT INTO users (id,email,full_name,password_hash,role,is_active,created_at) VALUES (?,?,?,?,?,?,?)',
                (user['id'], email, user['full_name'], hash_password(body.password), body.role, 1,
                 datetime.now(timezone.utc).isoformat())
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'An account with that email already exists') from exc
    return public_user(user)

@app.patch('/admin/users/{user_id}', dependencies=[Depends(require_same_origin)])
def update_managed_user(user_id: str, body: UserRoleIn, admin: dict = Depends(require_roles('admin'))):
    with connect() as db:
        target = db.execute('SELECT role,is_active FROM users WHERE id=?', (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, 'User not found')
        if user_id == admin['id'] and (body.role != 'admin' or not body.is_active):
            raise HTTPException(409, 'You cannot deactivate or demote your own administrator account')
        if target[0] == 'admin' and (body.role != 'admin' or not body.is_active):
            remaining = db.execute(
                "SELECT count(*) FROM users WHERE role='admin' AND is_active=1 AND id<>?",
                (user_id,)
            ).fetchone()[0]
            if not remaining:
                raise HTTPException(409, 'At least one active administrator must remain')
        db.execute('UPDATE users SET role=?,is_active=? WHERE id=?', (body.role, int(body.is_active), user_id))
        if not body.is_active:
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        row = db.execute(
            'SELECT id,email,full_name,role,is_active,created_at FROM users WHERE id=?', (user_id,)
        ).fetchone()
    return {'id': row[0], 'email': row[1], 'full_name': row[2], 'role': row[3],
            'is_active': bool(row[4]), 'created_at': row[5]}

@app.get('/admin/products')
def list_managed_products(_manager: dict = Depends(require_roles(*PRODUCT_ROLES, *INVENTORY_ROLES))):
    with connect() as db:
        rows = db.execute(PRODUCT_SELECT + ' ORDER BY category,name,sku').fetchall()
    return {'products': [product_response(row) for row in rows]}

@app.post('/admin/products', status_code=201, dependencies=[Depends(require_same_origin)])
def create_product(body: ProductIn, manager: dict = Depends(require_roles(*PRODUCT_ROLES))):
    if manager['role'] == 'product_management_officer' and body.stock != 0:
        raise HTTPException(403, 'New products must start with zero stock; an inventory manager can set the quantity')
    now = datetime.now(timezone.utc).isoformat()
    product = body.model_dump()
    try:
        with connect() as db:
            db.execute(
                'INSERT INTO products (sku,name,category,price_cents,stock,tag,image,description,active,updated_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (product['sku'], product['name'].strip(), product['category'].strip(),
                 int(round(product['price'] * 100)), product['stock'], product['tag'],
                 product['image'], product['description'], int(product['active']), now)
            )
            row = db.execute(PRODUCT_SELECT + ' WHERE sku=?', (product['sku'],)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'A product with that SKU already exists') from exc
    return product_response(row)

@app.patch('/admin/products/{sku}', dependencies=[Depends(require_same_origin)])
def update_product(
    sku: str,
    body: ProductUpdateIn,
    manager: dict = Depends(require_roles(*PRODUCT_ROLES, *INVENTORY_ROLES)),
):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, 'Provide at least one product field to update')
    if any(value is None for value in changes.values()):
        raise HTTPException(422, 'Product fields cannot be null')
    if manager['role'] == 'product_management_officer' and 'stock' in changes:
        raise HTTPException(403, 'Product officers cannot change stock; ask an inventory manager')
    if manager['role'] == 'inventory_manager' and set(changes) != {'stock'}:
        raise HTTPException(403, 'Inventory managers can only change stock quantities')
    columns = {
        'name': 'name', 'category': 'category', 'price': 'price_cents',
        'stock': 'stock', 'tag': 'tag', 'image': 'image', 'description': 'description',
        'active': 'active'
    }
    assignments = []
    values = []
    for field, value in changes.items():
        assignments.append(f'{columns[field]}=?')
        values.append(int(round(value * 100)) if field == 'price' else int(value) if field == 'active' else value)
    assignments.append('updated_at=?')
    values.extend([datetime.now(timezone.utc).isoformat(), sku])
    with connect() as db:
        updated = db.execute(
            f'UPDATE products SET {",".join(assignments)} WHERE sku=?', values
        ).rowcount
        if not updated:
            raise HTTPException(404, 'Product not found')
        row = db.execute(PRODUCT_SELECT + ' WHERE sku=?', (sku,)).fetchone()
    return product_response(row)

@app.get('/staff/fulfillment/orders')
def list_fulfillment_orders(_staff: dict = Depends(require_roles('admin', 'order_fulfillment_officer'))):
    with connect() as db:
        rows = db.execute(
            'SELECT id,customer_id,full_name,phone,address,city,postal_code,sku,product_name,quantity,'
            'status,correlation_id,created_at,delivery_facility,delivery_tracking_id '
            'FROM orders ORDER BY created_at,id'
        ).fetchall()
        location_ids = list(dict.fromkeys(row[11] for row in rows))
        location_rows = {}
        if location_ids:
            placeholders = ','.join('?' for _ in location_ids)
            location_rows = {
                row[0]: row[1:]
                for row in db.execute(
                    'SELECT correlation_id,latitude,longitude,accuracy,updated_at,shared_by '
                    f'FROM delivery_locations WHERE correlation_id IN ({placeholders})',
                    location_ids,
                ).fetchall()
            }
    grouped = {}
    for row in rows:
        if row[10] == 'CANCELLED':
            continue
        shipment = grouped.get(row[11])
        if shipment is None:
            shipment = {
                'correlation_id': row[11], 'customer_email': row[1], 'full_name': row[2],
                'phone': row[3], 'address': row[4], 'city': row[5], 'postal_code': row[6],
                'status': row[10], 'created_at': row[12], 'facility': row[13],
                'tracking_reference': row[14], 'items': [],
            }
            grouped[row[11]] = shipment
        shipment['items'].append({
            'sku': row[7], 'name': row[8] or row[7], 'quantity': row[9],
        })
    for correlation_id, shipment in grouped.items():
        location_row = location_rows.get(correlation_id)
        location = delivery_location_response(location_row)
        shipment['location_status'] = location['status'] if location else 'not_shared'
        shipment['location_updated_at'] = location['updated_at'] if location else None
        shipment['location_shared_by'] = location_row[4] if location_row else None
    return {'orders': list(grouped.values())}

@app.patch('/staff/fulfillment/orders/{correlation_id}', dependencies=[Depends(require_same_origin)])
def update_fulfillment(
    correlation_id: str,
    body: FulfillmentUpdateIn,
    staff: dict = Depends(require_roles('admin', 'order_fulfillment_officer')),
):
    previous_status = {'RECEIVED': 'PENDING', 'DISPATCHED': 'RECEIVED', 'DELIVERED': 'DISPATCHED'}[body.status]
    with connect() as db:
        rows = db.execute(
            'SELECT id,status,customer_id,full_name,sku,product_name,quantity '
            'FROM orders WHERE correlation_id=?',
            (correlation_id,),
        ).fetchall()
        if not rows:
            raise HTTPException(404, 'Order not found')
        if any(row[1] != previous_status for row in rows):
            raise HTTPException(409, f'Order must be {previous_status.lower()} before it can be {body.status.lower()}')
        order_ids = [row[0] for row in rows]
        placeholders = ','.join('?' for _ in order_ids)
        db.execute(
            f'UPDATE orders SET status=?,'
            'delivery_facility=CASE WHEN ?=? THEN ? ELSE delivery_facility END,'
            'delivery_tracking_id=CASE WHEN ?=? THEN ? ELSE delivery_tracking_id END '
            f'WHERE id IN ({placeholders}) AND status=?',
            (
                body.status,
                body.status, 'DISPATCHED', body.facility,
                body.status, 'DISPATCHED', body.tracking_reference,
                *order_ids, previous_status,
            ),
        )
        if body.status == 'RECEIVED':
            enqueue_order_notification(
                db,
                'OrderAccepted',
                correlation_id,
                rows[0][2],
                rows[0][3],
                [
                    {
                        'order_id': row[0],
                        'sku': row[4],
                        'name': row[5] or row[4],
                        'quantity': row[6],
                    }
                    for row in rows
                ],
                datetime.now(timezone.utc).isoformat(),
            )
        if body.status == 'DELIVERED':
            db.execute(
                'DELETE FROM delivery_locations WHERE correlation_id=?',
                (correlation_id,),
            )
    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'fulfillment_status_updated',
        'correlation_id': correlation_id, 'status': body.status, 'staff_id': staff['id'],
    }))
    return {'correlation_id': correlation_id, 'status': body.status}

@app.put(
    '/staff/fulfillment/orders/{correlation_id}/location',
    dependencies=[Depends(require_same_origin)],
)
def update_delivery_location(
    correlation_id: str,
    body: DeliveryLocationIn,
    staff: dict = Depends(require_roles('admin', 'order_fulfillment_officer')),
):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        rows = db.execute(
            'SELECT status FROM orders WHERE correlation_id=?',
            (correlation_id,),
        ).fetchall()
        if not rows:
            raise HTTPException(404, 'Order not found')
        if any(row[0] != 'DISPATCHED' for row in rows):
            raise HTTPException(409, 'Live GPS sharing is available only for dispatched orders')

        stale_before = (datetime.now(timezone.utc) - LOCATION_STALE_AFTER).isoformat()
        updated = db.execute(
            'INSERT INTO delivery_locations '
            '(correlation_id,latitude,longitude,accuracy,updated_at,shared_by) '
            'VALUES (?,?,?,?,?,?) '
            'ON CONFLICT(correlation_id) DO UPDATE SET latitude=excluded.latitude,'
            'longitude=excluded.longitude,accuracy=excluded.accuracy,'
            'updated_at=excluded.updated_at,shared_by=excluded.shared_by '
            'WHERE delivery_locations.shared_by=excluded.shared_by '
            'OR delivery_locations.updated_at<=?',
            (
                correlation_id, body.latitude, body.longitude, body.accuracy,
                now, staff['id'], stale_before,
            ),
        ).rowcount
        if not updated:
            raise HTTPException(409, 'Another staff member is currently sharing GPS for this order')
    return {'status': 'live', 'updated_at': now}

@app.delete(
    '/staff/fulfillment/orders/{correlation_id}/location',
    dependencies=[Depends(require_same_origin)],
)
def stop_delivery_location(
    correlation_id: str,
    staff: dict = Depends(require_roles('admin', 'order_fulfillment_officer')),
):
    with connect() as db:
        order = db.execute(
            'SELECT 1 FROM orders WHERE correlation_id=? LIMIT 1',
            (correlation_id,),
        ).fetchone()
        if not order:
            raise HTTPException(404, 'Order not found')
        current = db.execute(
            'SELECT shared_by FROM delivery_locations WHERE correlation_id=?',
            (correlation_id,),
        ).fetchone()
        if current and current[0] != staff['id']:
            raise HTTPException(403, 'Only the staff member sharing this GPS can stop it')
        db.execute(
            'DELETE FROM delivery_locations WHERE correlation_id=? AND shared_by=?',
            (correlation_id, staff['id']),
        )
    return {'status': 'stopped'}

@app.get('/staff/finance/summary')
def finance_summary(_finance: dict = Depends(require_roles('admin', 'finance_officer'))):
    with connect() as db:
        rows = db.execute(
            'SELECT id,customer_id,sku,product_name,quantity,unit_price_cents,status,payment_status,'
            'payment_method,created_at,correlation_id FROM orders ORDER BY created_at DESC,id'
        ).fetchall()
    orders = [{
        'order_id': row[0], 'customer_email': row[1], 'sku': row[2],
        'product_name': row[3] or row[2], 'quantity': row[4],
        'unit_price': row[5] / 100, 'total': row[4] * row[5] / 100,
        'status': row[6], 'payment_status': row[7], 'payment_method': row[8],
        'created_at': row[9], 'correlation_id': row[10],
    } for row in rows]
    return {
        'orders': orders,
        'summary': {
            'recorded_revenue': round(sum(order['total'] for order in orders if order['payment_status'] == 'PAID'), 2),
            'outstanding': round(sum(
                order['total'] for order in orders
                if order['payment_status'] == 'UNPAID' and order['status'] != 'CANCELLED'
            ), 2),
            'refunded': round(sum(order['total'] for order in orders if order['payment_status'] == 'REFUNDED'), 2),
        },
    }

@app.patch('/staff/finance/orders/{order_id}/payment', dependencies=[Depends(require_same_origin)])
def update_payment_status(
    order_id: str,
    body: PaymentUpdateIn,
    finance: dict = Depends(require_roles('admin', 'finance_officer')),
):
    with connect() as db:
        order = db.execute(
            'SELECT status,payment_status FROM orders WHERE id=?', (order_id,)
        ).fetchone()
        if not order:
            raise HTTPException(404, 'Order not found')
        status, payment_status = order
        if body.payment_status == 'PAID' and (payment_status != 'UNPAID' or status == 'CANCELLED'):
            raise HTTPException(409, 'Only unpaid, active orders can be recorded as paid')
        if body.payment_status == 'REFUNDED' and (payment_status != 'PAID' or status != 'CANCELLED'):
            raise HTTPException(409, 'Only paid, cancelled orders can be recorded as refunded')
        db.execute('UPDATE orders SET payment_status=? WHERE id=?', (body.payment_status, order_id))
    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'payment_status_updated',
        'order_id': order_id, 'payment_status': body.payment_status, 'staff_id': finance['id'],
    }))
    return {'order_id': order_id, 'payment_status': body.payment_status}

@app.get('/admin/orders')
def list_all_orders(_admin: dict = Depends(require_roles('admin'))):
    with connect() as db:
        rows = db.execute(
            'SELECT id,customer_id,user_id,sku,product_name,quantity,unit_price_cents,status,'
            'correlation_id,created_at,full_name,phone,address,city,postal_code,payment_method,'
            'payment_status,delivery_facility,delivery_tracking_id '
            'FROM orders ORDER BY created_at DESC,id'
        ).fetchall()
    return {'orders': [
        {'order_id': row[0], 'customer_email': row[1], 'user_id': row[2], 'sku': row[3],
         'product_name': row[4] or row[3], 'quantity': row[5], 'unit_price': row[6] / 100,
         'status': row[7], 'correlation_id': row[8], 'created_at': row[9],
         'full_name': row[10], 'phone': row[11], 'address': row[12], 'city': row[13],
         'postal_code': row[14], 'payment_method': row[15], 'payment_status': row[16],
         'delivery_facility': row[17], 'delivery_tracking_id': row[18]}
        for row in rows
    ]}

@app.post('/orders', status_code=202, dependencies=[Depends(require_same_origin)])
def create_order(body: OrderIn, user: dict = Depends(get_current_user),
                 x_correlation_id: str | None = Header(None), idempotency_key: str | None = Header(None)):
    cid = x_correlation_id or str(uuid.uuid4())
    oid = idempotency_key or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        'event_id': str(uuid.uuid4()), 'type': 'OrderPlaced', 'order_id': oid,
        'customer_id': user['email'], 'recipient_email': user['email'],
        'customer_name': user['full_name'],
        'items': [{'order_id': oid, 'sku': body.sku, 'name': body.sku, 'quantity': body.quantity}],
        'sku': body.sku, 'quantity': body.quantity,
        'correlation_id': cid, 'occurred_at': created_at,
    }
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id,correlation_id,status,customer_id,sku,quantity FROM orders WHERE id=?',(oid,)).fetchone()
        if existing:
            if (existing[3],existing[4],existing[5]) != (user['email'],body.sku,body.quantity):
                raise HTTPException(409,'Idempotency key already used with different payload')
            return {'order_id':oid,'status':existing[2],'correlation_id':existing[1], 'duplicate':True}
        product = db.execute(PRODUCT_SELECT + ' WHERE sku=? AND active=1', (body.sku,)).fetchone()
        if not product:
            raise HTTPException(404, 'Product not found')
        changed = db.execute(
            'UPDATE products SET stock=stock-? WHERE sku=? AND active=1 AND stock>=?',
            (body.quantity, body.sku, body.quantity)
        ).rowcount
        if not changed:
            raise HTTPException(409, 'There is not enough stock for this product')
        db.execute(
            'INSERT INTO orders (id,customer_id,user_id,sku,product_name,product_category,unit_price_cents,quantity,status,correlation_id,created_at,delivery_min_days,delivery_max_days,delivery_tracking_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (oid,user['email'],user['id'],body.sku,product[1],product[2],product[3],body.quantity,
             'PENDING',cid,created_at,MIN_DELIVERY_DAYS,MAX_DELIVERY_DAYS,new_tracking_id())
        )
        db.execute('INSERT INTO outbox VALUES (?,?,0)',(payload['event_id'],json.dumps(payload)))
    log.info(json.dumps({'level':'INFO','service':'orders','event':'order_created','order_id':oid,'correlation_id':cid}))
    return {'order_id':oid,'status':'PENDING','correlation_id':cid,'duplicate':False}

@app.post('/orders/batch', status_code=202, dependencies=[Depends(require_same_origin)])
def create_order_batch(body: OrderBatchIn, user: dict = Depends(get_current_user),
                       x_correlation_id: str | None = Header(None), idempotency_key: str | None = Header(None)):
    if len({item.sku for item in body.items}) != len(body.items):
        raise HTTPException(422, 'Each SKU can appear only once in an order')

    batch_id = idempotency_key or str(uuid.uuid4())
    cid = x_correlation_id or str(uuid.uuid4())
    request_payload = json.dumps({
        'user_id': user['id'],
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
        db.execute('BEGIN IMMEDIATE')
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

        product_rows = {}
        for item in body.items:
            row = db.execute(PRODUCT_SELECT + ' WHERE sku=? AND active=1', (item.sku,)).fetchone()
            if not row:
                raise HTTPException(404, f'Product {item.sku} is unavailable')
            product_rows[item.sku] = row

        pending_items = []
        for item in body.items:
            oid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'maltashop:{batch_id}:{item.sku}'))
            existing = db.execute(
                'SELECT id,correlation_id,status,customer_id,sku,quantity,created_at,user_id FROM orders WHERE id=?',
                (oid,)
            ).fetchone()
            if existing:
                if (existing[3], existing[4], existing[5], existing[7]) != (user['email'], item.sku, item.quantity, user['id']):
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
            product = product_rows[item.sku]
            if product[4] < item.quantity:
                raise HTTPException(409, f'Not enough stock for {product[1]}')
            pending_items.append((item, oid, product))

        for item, _oid, _product in pending_items:
            changed = db.execute(
                'UPDATE products SET stock=stock-? WHERE sku=? AND active=1 AND stock>=?',
                (item.quantity, item.sku, item.quantity)
            ).rowcount
            if not changed:
                raise HTTPException(409, f'Not enough stock for {item.sku}')

        for item, oid, product in pending_items:
            db.execute(
                'INSERT INTO orders (id,customer_id,user_id,sku,product_name,product_category,unit_price_cents,quantity,status,correlation_id,full_name,phone,address,city,postal_code,payment_method,created_at,delivery_min_days,delivery_max_days,delivery_tracking_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    oid, user['email'], user['id'], item.sku, product[1], product[2], product[3],
                    item.quantity, 'PENDING', cid,
                    body.full_name or '', body.phone or '', body.address or '',
                    body.city or '', body.postal_code or '', body.payment_method,
                    created_at, MIN_DELIVERY_DAYS, MAX_DELIVERY_DAYS, new_tracking_id()
                )
            )
            earliest_delivery, latest_delivery = delivery_dates(created_at)
            orders.append({
                'order_id': oid, 'sku': item.sku, 'quantity': item.quantity,
                'status': 'PENDING', 'duplicate': False,
                'delivery_min_days': MIN_DELIVERY_DAYS,
                'delivery_max_days': MAX_DELIVERY_DAYS,
                'earliest_delivery': earliest_delivery, 'latest_delivery': latest_delivery
            })
        if pending_items:
            enqueue_order_notification(
                db,
                'OrderPlaced',
                cid,
                user['email'],
                user['full_name'],
                [
                    {
                        'order_id': oid,
                        'sku': item.sku,
                        'name': product[1],
                        'quantity': item.quantity,
                    }
                    for item, oid, product in pending_items
                ],
                created_at,
            )

    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'order_batch_created',
        'order_ids': [order['order_id'] for order in orders], 'correlation_id': cid
    }))
    return {'orders': orders, 'correlation_id': cid}

@app.post('/orders/my', dependencies=[Depends(require_same_origin)])
def list_my_orders(_body: MyOrdersIn, user: dict = Depends(get_current_user)):
    with connect() as db:
        rows = db.execute(
            'SELECT id,sku,quantity,status,correlation_id,created_at,delivery_min_days,delivery_max_days,'
            'phone,product_name,delivery_facility,delivery_tracking_id '
            'FROM orders WHERE user_id=? ORDER BY created_at DESC,id',
            (user['id'],)
        ).fetchall()
        correlation_ids = list(dict.fromkeys(row[4] for row in rows))
        location_rows = {}
        if correlation_ids:
            placeholders = ','.join('?' for _ in correlation_ids)
            location_rows = {
                row[0]: row[1:]
                for row in db.execute(
                    'SELECT correlation_id,latitude,longitude,accuracy,updated_at '
                    f'FROM delivery_locations WHERE correlation_id IN ({placeholders})',
                    correlation_ids,
                ).fetchall()
            }

    grouped = {}
    for row in rows:
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
                'delivery_facility': row[10],
                'delivery_tracking_id': row[11],
                'live_location': delivery_location_response(location_rows.get(row[4])),
                'items': [],
            }
            grouped[row[4]] = order
        order['items'].append({
            'order_id': row[0],
            'delivery_tracking_id': row[11],
            'sku': row[1],
            'name': row[9] or row[1],
            'quantity': row[2],
        })
        if row[3] != order['status']:
            order['status'] = 'PENDING'
        if row[3] != 'PENDING':
            order['can_cancel'] = False

    return {'orders': list(grouped.values())}

@app.post('/orders/my/cancel', dependencies=[Depends(require_same_origin)])
def cancel_my_order(body: CancelOrderIn, user: dict = Depends(get_current_user)):
    with connect() as db:
        rows = db.execute(
            'SELECT id,status,created_at,sku,quantity,customer_id,full_name,product_name '
            'FROM orders '
            'WHERE correlation_id=? AND user_id=?',
            (body.correlation_id, user['id'])
        ).fetchall()
        if not rows:
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
        db.execute(
            'DELETE FROM delivery_locations WHERE correlation_id=?',
            (body.correlation_id,),
        )
        updated_count = db.execute(
            f"SELECT count(*) FROM orders WHERE id IN ({placeholders}) AND status='CANCELLED'",
            order_ids
        ).fetchone()[0]
        if updated_count != len(order_ids):
            raise HTTPException(409, 'This order can no longer be cancelled')
        for row in rows:
            db.execute('UPDATE products SET stock=stock+? WHERE sku=?', (row[4], row[3]))
        enqueue_order_notification(
            db,
            'OrderCancelled',
            body.correlation_id,
            rows[0][5],
            rows[0][6],
            [
                {
                    'order_id': row[0],
                    'sku': row[3],
                    'name': row[7] or row[3],
                    'quantity': row[4],
                }
                for row in rows
            ],
            datetime.now(timezone.utc).isoformat(),
        )

    log.info(json.dumps({
        'level': 'INFO', 'service': 'orders', 'event': 'order_cancelled',
        'order_ids': order_ids, 'correlation_id': body.correlation_id
    }))
    return {'status': 'CANCELLED', 'already_cancelled': False}

@app.post('/orders/complaints', status_code=201, dependencies=[Depends(require_same_origin)])
def create_order_complaint(body: OrderComplaintIn, user: dict = Depends(get_current_user)):
    with connect() as db:
        rows = db.execute(
            'SELECT sku FROM orders WHERE correlation_id=? AND user_id=?',
            (body.correlation_id, user['id'])
        ).fetchall()
        if not rows:
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
def get_order(order_id: str, user: dict = Depends(get_current_user)):
    query = (
        'SELECT id,customer_id,sku,quantity,status,correlation_id,created_at,delivery_min_days,'
        'delivery_max_days,payment_method,user_id,product_name,delivery_facility,delivery_tracking_id '
        'FROM orders WHERE (id=? OR delivery_tracking_id=?)'
    )
    parameters: tuple[str, ...] = (order_id, order_id)
    if user['role'] not in ('admin', 'order_fulfillment_officer', 'finance_officer'):
        query += ' AND user_id=?'
        parameters += (user['id'],)
    query += ' ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END LIMIT 1'
    parameters += (order_id,)
    with connect() as db:
        row = db.execute(query, parameters).fetchone()
        location_row = (
            db.execute(
                'SELECT latitude,longitude,accuracy,updated_at FROM delivery_locations '
                'WHERE correlation_id=?',
                (row[5],),
            ).fetchone()
            if row else None
        )
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
        'product_name': row[11] or row[2],
        'delivery_facility': row[12],
        'delivery_tracking_id': row[13],
        'live_location': delivery_location_response(location_row),
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
        channel.queue_bind(exchange='malta.events',queue='notification.order_placed',routing_key='order.accepted')
        channel.queue_bind(exchange='malta.events',queue='notification.order_placed',routing_key='order.cancelled')
        channel.queue_bind(exchange='malta.events',queue='notification.order_placed',routing_key='password.reset')
        with connect() as db:
            rows=db.execute('SELECT event_id,payload FROM outbox WHERE published=0 ORDER BY rowid LIMIT 50').fetchall()
        for eid,payload in rows:
            event=json.loads(payload)
            routing_key=NOTIFICATION_ROUTING_KEYS.get(event.get('type'))
            if not routing_key:
                raise ValueError(f"Unsupported notification event type: {event.get('type')}")
            channel.basic_publish(exchange='malta.events',routing_key=routing_key,body=payload,properties=pika.BasicProperties(delivery_mode=2,message_id=eid,content_type='application/json'),mandatory=False)
            with connect() as db:
                db.execute('UPDATE outbox SET published=1 WHERE event_id=?',(eid,))
            log.info(json.dumps({
                'level': 'INFO', 'service': 'orders', 'event': 'notification_event_published',
                'event_id': eid, 'correlation_id': event.get('correlation_id'),
                'type': event.get('type'),
            }))
    finally: connection.close()
