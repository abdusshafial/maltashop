import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest


def make_client(order_module, email="shopper@example.com", role="customer"):
    client = TestClient(order_module.app)
    if role == "customer":
        response = client.post(
            "/auth/register",
            json={"email": email, "full_name": "Ari Borg", "password": "test-password-123"},
        )
        assert response.status_code == 201
    else:
        with order_module.connect() as db:
            db.execute(
                "INSERT INTO users (id,email,full_name,password_hash,role,is_active,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    f"{role}-{email}", email, "Shop Staff",
                    order_module.hash_password("test-password-123"), role, 1,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        response = client.post(
            "/auth/login",
            json={"email": email, "password": "test-password-123"},
        )
        assert response.status_code == 200
    return client


def test_order_creation_and_idempotency(order_module):
    client = make_client(order_module)
    headers = {"Idempotency-Key": "test-100", "X-Correlation-ID": "corr-100"}
    payload = {"sku": "HEADPHONES-01", "quantity": 2}

    response = client.post("/orders", json=payload, headers=headers)
    assert response.status_code == 202
    assert response.json()["correlation_id"] == "corr-100"
    assert response.json()["duplicate"] is False
    assert client.get("/orders/test-100").status_code == 200
    assert client.post("/orders", json=payload, headers=headers).json()["duplicate"] is True
    assert client.post(
        "/orders", json={**payload, "quantity": 3}, headers=headers
    ).status_code == 409
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1


def test_invalid_order(order_module):
    client = make_client(order_module)
    response = client.post(
        "/orders", json={"sku": "HEADPHONES-01", "quantity": 0}
    )
    assert response.status_code == 422


def test_batch_order_creation_is_atomic_and_idempotent(order_module):
    client = make_client(order_module)
    headers = {"Idempotency-Key": "cart-100", "X-Correlation-ID": "corr-cart-100"}
    payload = {
        "items": [
            {"sku": "HEADPHONES-01", "quantity": 1},
            {"sku": "SPEAKER-01", "quantity": 2},
        ],
    }

    response = client.post("/orders/batch", json=payload, headers=headers)
    assert response.status_code == 202
    assert len(response.json()["orders"]) == 2
    assert all(not order["duplicate"] for order in response.json()["orders"])
    assert response.json()["correlation_id"] == "corr-cart-100"

    reordered_payload = {**payload, "items": list(reversed(payload["items"]))}
    retry = client.post("/orders/batch", json=reordered_payload, headers=headers)
    assert retry.status_code == 202
    assert all(order["duplicate"] for order in retry.json()["orders"])
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
        event = order_module.json.loads(
            db.execute("SELECT payload FROM outbox").fetchone()[0]
        )
        assert event["type"] == "OrderPlaced"
        assert event["recipient_email"] == "shopper@example.com"
        assert len(event["items"]) == 2

    changed_payload = {
        "items": [
            {"sku": "HEADPHONES-01", "quantity": 3},
            {"sku": "SPEAKER-01", "quantity": 1},
        ],
    }
    conflict = client.post("/orders/batch", json=changed_payload, headers=headers)
    assert conflict.status_code == 409
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 2


def test_batch_retry_with_added_item_is_rejected_atomically(order_module):
    client = make_client(order_module)
    headers = {"Idempotency-Key": "cart-added-item"}
    original = {
        "items": [{"sku": "HEADPHONES-01", "quantity": 1}],
    }
    assert client.post("/orders/batch", json=original, headers=headers).status_code == 202

    changed = {
        **original,
        "items": [*original["items"], {"sku": "SPEAKER-01", "quantity": 1}],
    }
    response = client.post("/orders/batch", json=changed, headers=headers)

    assert response.status_code == 409
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1


def test_batch_rejects_duplicate_skus(order_module):
    response = make_client(order_module).post(
        "/orders/batch",
        json={
            "items": [
                {"sku": "HEADPHONES-01", "quantity": 1},
                {"sku": "HEADPHONES-01", "quantity": 2},
            ],
        },
    )

    assert response.status_code == 422


def test_checkout_saves_customer_details_and_delivery_estimate(order_module):
    client = make_client(order_module)
    response = client.post(
        "/orders/batch",
        headers={"Idempotency-Key": "complete-checkout"},
        json={
            "full_name": "Ari Borg",
            "phone": "+356 1234 5678",
            "address": "12 Example Street",
            "city": "Valletta",
            "postal_code": "VLT 1000",
            "payment_method": "cash",
            "items": [{"sku": "HEADPHONES-01", "quantity": 1}],
        },
    )

    assert response.status_code == 202
    order_id = response.json()["orders"][0]["order_id"]
    assert response.json()["orders"][0]["delivery_min_days"] == 2
    assert response.json()["orders"][0]["delivery_max_days"] == 5

    tracked_order = client.get(f"/orders/{order_id}").json()
    assert tracked_order["earliest_delivery"]
    assert tracked_order["latest_delivery"] >= tracked_order["earliest_delivery"]
    assert tracked_order["payment_method"] == "cash"

    with order_module.connect() as db:
        saved = db.execute(
            "SELECT customer_id,full_name,phone,address,city,postal_code,payment_method,sku,quantity,delivery_min_days,delivery_max_days "
            "FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()
    assert saved == (
        "shopper@example.com",
        "Ari Borg",
        "+356 1234 5678",
        "12 Example Street",
        "Valletta",
        "VLT 1000",
        "cash",
        "HEADPHONES-01",
        1,
        2,
        5,
    )


def test_checkout_rejects_incomplete_delivery_details(order_module):
    response = make_client(order_module).post(
        "/orders/batch",
        json={
            "full_name": "Ari Borg",
            "items": [{"sku": "HEADPHONES-01", "quantity": 1}],
        },
    )

    assert response.status_code == 422


def test_existing_database_is_migrated_without_losing_orders(order_module, tmp_path):
    database_path = tmp_path / "legacy-orders.db"
    with sqlite3.connect(database_path) as db:
        db.execute(
            "CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, "
            "sku TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, "
            "correlation_id TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE outbox (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "published INTEGER NOT NULL DEFAULT 0)"
        )
        db.execute(
            "CREATE TABLE batch_requests (idempotency_key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO orders VALUES ('old-order','old-customer','OLD-SKU',1,'PENDING','old-correlation')"
        )

    order_module.DB = str(database_path)
    order_module.initialize()

    with order_module.connect() as db:
        migrated_order = db.execute(
            "SELECT customer_id,sku,quantity,delivery_min_days,delivery_max_days FROM orders WHERE id='old-order'"
        ).fetchone()
    assert migrated_order == ("old-customer", "OLD-SKU", 1, 2, 5)

def test_existing_user_role_constraint_is_migrated(order_module, tmp_path):
    database_path = tmp_path / "old-users.db"
    with sqlite3.connect(database_path) as db:
        db.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,full_name TEXT NOT NULL,"
            "password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN "
            "('customer','admin','product_management_officer')),is_active INTEGER NOT NULL DEFAULT 1,"
            "created_at TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
            (
                "existing-user", "existing@example.test", "Existing User",
                "legacy-hash", "customer", 1, datetime.now(timezone.utc).isoformat(),
            ),
        )

    order_module.DB = str(database_path)
    order_module.initialize()
    with order_module.connect() as db:
        assert db.execute("SELECT id,role FROM users").fetchone() == ("existing-user", "customer")
        db.execute(
            "INSERT INTO users (id,email,full_name,password_hash,role,is_active,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("new-staff", "delivery@example.test", "Delivery", "hash", "order_fulfillment_officer", 1, "now"),
        )


def create_checkout_order(client, idempotency_key, email="shopper@example.com", phone="+356 1234 5678"):
    return client.post(
        "/orders/batch",
        headers={"Idempotency-Key": idempotency_key},
        json={
            "full_name": "Ari Borg",
            "phone": phone,
            "address": "12 Example Street",
            "city": "Valletta",
            "postal_code": "VLT 1000",
            "items": [
                {"sku": "HEADPHONES-01", "quantity": 1},
                {"sku": "SPEAKER-01", "quantity": 2},
            ],
        },
    )


def test_customer_can_list_orders_with_auto_assigned_tracking_ids(order_module):
    client = make_client(order_module)
    created = create_checkout_order(client, "my-orders-checkout")
    assert created.status_code == 202

    response = client.post(
        "/orders/my",
        json={"email": " SHOPPER@example.com ", "phone": "00356 1234-5678"},
    )

    assert response.status_code == 200
    result = response.json()["orders"]
    assert len(result) == 1
    assert result[0]["status"] == "PENDING"
    assert result[0]["can_cancel"] is True
    assert len(result[0]["items"]) == 2
    assert {item["sku"] for item in result[0]["items"]} == {
        "HEADPHONES-01",
        "SPEAKER-01",
    }
    expected_ids = {
        order["order_id"] for order in created.json()["orders"]
    }
    assert {item["order_id"] for item in result[0]["items"]} == expected_ids
    tracking_ids = {
        item["delivery_tracking_id"] for item in result[0]["items"]
    }
    assert len(tracking_ids) == 2
    assert all(tracking_id.startswith("MT-") for tracking_id in tracking_ids)
    tracked = client.get(f"/orders/{next(iter(tracking_ids))}")
    assert tracked.status_code == 200
    assert tracked.json()["delivery_tracking_id"] in tracking_ids


def test_product_reviews_require_a_delivered_purchase_and_allow_one_review(order_module):
    customer = make_client(order_module)
    placed = create_checkout_order(customer, "review-checkout")
    assert placed.status_code == 202
    assert customer.get("/products/HEADPHONES-01/review-eligibility").json() == {
        "eligible": False, "delivered": False, "review": None
    }
    assert customer.post(
        "/products/HEADPHONES-01/reviews",
        json={"rating": 5, "comment": "Lovely sound"},
    ).status_code == 403

    fulfillment = make_client(
        order_module, email="delivery@example.com", role="order_fulfillment_officer"
    )
    correlation_id = placed.json()["correlation_id"]
    assert fulfillment.patch(
        f"/staff/fulfillment/orders/{correlation_id}", json={"status": "RECEIVED"}
    ).status_code == 200
    assert fulfillment.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={
            "status": "DISPATCHED",
            "facility": "Valletta Delivery Facility",
            "tracking_reference": "MT-REVIEW-123",
        },
    ).status_code == 200
    assert fulfillment.patch(
        f"/staff/fulfillment/orders/{correlation_id}", json={"status": "DELIVERED"}
    ).status_code == 200

    eligible = customer.get("/products/HEADPHONES-01/review-eligibility")
    assert eligible.json() == {"eligible": True, "delivered": True, "review": None}
    review = customer.post(
        "/products/HEADPHONES-01/reviews",
        json={"rating": 5, "comment": "  Lovely sound and very comfortable  "},
    )
    assert review.status_code == 201
    assert review.json()["comment"] == "Lovely sound and very comfortable"
    assert customer.post(
        "/products/HEADPHONES-01/reviews",
        json={"rating": 4, "comment": "A second review"},
    ).status_code == 409

    public_reviews = customer.get("/products/HEADPHONES-01/reviews")
    assert public_reviews.json()["review_count"] == 1
    assert public_reviews.json()["average_rating"] == 5
    assert public_reviews.json()["reviews"][0]["reviewer"] == "Verified customer"
    products = customer.get("/products").json()["products"]
    headphones = next(product for product in products if product["sku"] == "HEADPHONES-01")
    assert headphones["average_rating"] == 5
    assert headphones["review_count"] == 1


def test_product_reviews_are_private_to_customer_purchase_and_account(order_module):
    customer = make_client(order_module)
    assert customer.get("/products/HEADPHONES-01/review-eligibility").status_code == 200
    assert customer.get("/products/SPEAKER-01/review-eligibility").json()["delivered"] is False
    assert make_client(order_module, email="other@example.com").post(
        "/products/HEADPHONES-01/reviews",
        json={"rating": 5, "comment": "Not my purchase"},
    ).status_code == 403
    assert customer.post(
        "/products/HEADPHONES-01/reviews", json={"rating": 6, "comment": "Too many stars"}
    ).status_code == 422

def test_customer_can_submit_product_and_delivery_complaints(order_module):
    client = make_client(order_module)
    create_checkout_order(client, "complaint-checkout")
    orders = client.post(
        "/orders/my",
        json={"email": "shopper@example.com", "phone": "12345678"},
    ).json()["orders"]
    order = orders[0]
    credentials = {
        "email": "shopper@example.com",
        "phone": "+356 1234 5678",
        "correlation_id": order["correlation_id"],
    }

    product_complaint = client.post(
        "/orders/complaints",
        json={
            **credentials,
            "complaint_type": "product",
            "product_sku": "HEADPHONES-01",
            "message": "The headphones arrived damaged.",
        },
    )
    assert product_complaint.status_code == 201
    assert product_complaint.json()["status"] == "RECEIVED"

    delivery_complaint = client.post(
        "/orders/complaints",
        json={
            **credentials,
            "complaint_type": "delivery",
            "message": "The delivery person left the parcel outside.",
        },
    )
    assert delivery_complaint.status_code == 201

    with order_module.connect() as db:
        complaints = db.execute(
            "SELECT complaint_type,product_sku,message FROM complaints ORDER BY created_at,id"
        ).fetchall()
    assert {row[0] for row in complaints} == {"product", "delivery"}
    assert ("product", "HEADPHONES-01", "The headphones arrived damaged.") in complaints
    assert ("delivery", None, "The delivery person left the parcel outside.") in complaints


def test_complaint_requires_valid_order_credentials_and_order_item(order_module):
    client = make_client(order_module)
    create_checkout_order(client, "complaint-validation-checkout")
    correlation_id = client.post(
        "/orders/my",
        json={"email": "shopper@example.com", "phone": "12345678"},
    ).json()["orders"][0]["correlation_id"]
    payload = {
        "email": "shopper@example.com",
        "phone": "87654321",
        "correlation_id": correlation_id,
        "complaint_type": "product",
        "product_sku": "NOT-IN-ORDER",
        "message": "This product has an issue.",
    }
    assert client.post("/orders/complaints", json=payload).status_code == 422

    payload["phone"] = "12345678"
    assert client.post("/orders/complaints", json=payload).status_code == 422

    payload["product_sku"] = "HEADPHONES-01"
    payload["message"] = "          "
    assert client.post("/orders/complaints", json=payload).status_code == 422


def test_customers_can_only_see_and_manage_their_own_orders(order_module):
    client = make_client(order_module)
    created = create_checkout_order(client, "private-order")
    other_customer = make_client(order_module, email="other@example.com")
    other_orders = other_customer.post("/orders/my", json={})
    assert other_orders.status_code == 200
    assert other_orders.json()["orders"] == []
    assert other_customer.get(f"/orders/{created.json()['orders'][0]['order_id']}").status_code == 404
    cancel_wrong_user = other_customer.post(
        "/orders/my/cancel",
        json={"correlation_id": created.json()["correlation_id"]},
    )
    assert cancel_wrong_user.status_code == 404
    with order_module.connect() as db:
        assert db.execute(
            "SELECT count(*) FROM orders WHERE status='PENDING'"
        ).fetchone()[0] == 2


def test_order_cancellation_deadline_is_exactly_twelve_hours(order_module):
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    created = (now - timedelta(hours=12)).isoformat()

    deadline, can_cancel_at_deadline = order_module.cancellation_details(created, now)
    _, can_cancel_after_deadline = order_module.cancellation_details(
        created, now + timedelta(microseconds=1)
    )

    assert deadline == now.isoformat()
    assert can_cancel_at_deadline is True
    assert can_cancel_after_deadline is False


def test_customer_can_cancel_order_within_twelve_hours(order_module):
    client = make_client(order_module)
    created = create_checkout_order(client, "cancel-in-time")
    correlation_id = created.json()["correlation_id"]
    cancellation = {
        "email": "shopper@example.com",
        "phone": "+356 1234 5678",
        "correlation_id": correlation_id,
    }

    response = client.post("/orders/my/cancel", json=cancellation)

    assert response.status_code == 200
    assert response.json() == {"status": "CANCELLED", "already_cancelled": False}
    with order_module.connect() as db:
        events = [
            order_module.json.loads(row[0])
            for row in db.execute("SELECT payload FROM outbox ORDER BY rowid")
        ]
    cancellation_events = [event for event in events if event["type"] == "OrderCancelled"]
    assert len(cancellation_events) == 1
    assert cancellation_events[0]["recipient_email"] == "shopper@example.com"
    assert cancellation_events[0]["correlation_id"] == correlation_id
    assert client.post("/orders/my/cancel", json=cancellation).json() == {
        "status": "CANCELLED",
        "already_cancelled": True,
    }
    orders = client.post(
        "/orders/my",
        json={"email": "shopper@example.com", "phone": "+356 1234 5678"},
    ).json()["orders"]
    assert orders[0]["status"] == "CANCELLED"
    assert orders[0]["can_cancel"] is False
    with order_module.connect() as db:
        assert db.execute(
            "SELECT count(*) FROM orders WHERE correlation_id=? AND status='CANCELLED'",
            (correlation_id,),
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT stock FROM products WHERE sku='HEADPHONES-01'"
        ).fetchone()[0] == 25


def test_customer_cannot_cancel_order_after_twelve_hours(order_module):
    client = make_client(order_module)
    created = create_checkout_order(client, "cancel-too-late")
    correlation_id = created.json()["correlation_id"]
    with order_module.connect() as db:
        db.execute(
            "UPDATE orders SET created_at=? WHERE correlation_id=?",
            ("2026-01-01T00:00:00+00:00", correlation_id),
        )

    response = client.post(
        "/orders/my/cancel",
        json={
            "email": "shopper@example.com",
            "phone": "+356 1234 5678",
            "correlation_id": correlation_id,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "The 12-hour cancellation period has expired"
    with order_module.connect() as db:
        assert db.execute(
            "SELECT count(*) FROM orders WHERE correlation_id=? AND status='PENDING'",
            (correlation_id,),
        ).fetchone()[0] == 2


def test_order_lookup_returns_404_for_unknown_order(order_module):
    response = make_client(order_module).get("/orders/missing")
    assert response.status_code == 404


def test_publisher_sends_and_marks_pending_events(order_module, monkeypatch):
    client = make_client(order_module)
    response = client.post(
        "/orders",
        json={"sku": "HEADPHONES-01", "quantity": 2},
        headers={"Idempotency-Key": "published-order", "X-Correlation-ID": "corr-1"},
    )
    assert response.status_code == 202
    with order_module.connect() as db:
        for event_type in ("OrderAccepted", "OrderCancelled"):
            event_id = f"event-{event_type}"
            db.execute(
                "INSERT INTO outbox (event_id,payload,published) VALUES (?,?,0)",
                (
                    event_id,
                    order_module.json.dumps({
                        "event_id": event_id,
                        "type": event_type,
                        "order_id": "published-order",
                        "correlation_id": "corr-1",
                    }),
                ),
            )
        db.execute(
            "INSERT INTO outbox (event_id,payload,published) VALUES (?,?,0)",
            (
                "event-password-reset",
                order_module.json.dumps({
                    "event_id": "event-password-reset",
                    "type": "PasswordReset",
                    "recipient_email": "customer@example.com",
                    "reset_url": "https://shop.example.com/#reset-token=token",
                    "expires_at": "2026-11-10T09:30:00+00:00",
                }),
            ),
        )

    class FakeChannel:
        def __init__(self):
            self.published = []
            self.exchanges = []
            self.queues = []
            self.bindings = []

        def exchange_declare(self, **kwargs):
            self.exchanges.append(kwargs)

        def queue_declare(self, **kwargs):
            self.queues.append(kwargs)

        def queue_bind(self, **kwargs):
            self.bindings.append(kwargs)

        def basic_publish(self, **kwargs):
            self.published.append(kwargs)

    class FakeConnection:
        def __init__(self):
            self.fake_channel = FakeChannel()
            self.closed = False

        def channel(self):
            return self.fake_channel

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(
        order_module.pika,
        "BlockingConnection",
        Mock(return_value=connection),
    )

    order_module.publish_pending()

    assert connection.closed
    assert len(connection.fake_channel.published) == 4
    published = connection.fake_channel.published[0]
    assert {
        "exchange": "malta.dead",
        "exchange_type": "direct",
        "durable": True,
    } in connection.fake_channel.exchanges
    assert {
        "queue": "notification.order_placed",
        "durable": True,
        "arguments": {
            "x-dead-letter-exchange": "malta.dead",
            "x-dead-letter-routing-key": "notification.order_placed.dead",
        },
    } in connection.fake_channel.queues
    assert {
        "queue": "notification.order_placed.dead",
        "durable": True,
    } in connection.fake_channel.queues
    assert published["routing_key"] == "order.placed"
    assert {
        event["type"]: message["routing_key"]
        for message in connection.fake_channel.published
        for event in [order_module.json.loads(message["body"])]
    } == {
        "OrderPlaced": "order.placed",
        "OrderAccepted": "order.accepted",
        "OrderCancelled": "order.cancelled",
        "PasswordReset": "password.reset",
    }
    assert published["properties"].delivery_mode == 2
    assert published["properties"].content_type == "application/json"
    event = order_module.json.loads(published["body"])
    assert event["type"] == "OrderPlaced"
    assert event["order_id"] == "published-order"
    with order_module.connect() as db:
        assert db.execute("SELECT published FROM outbox").fetchone()[0] == 1

    order_module.publish_pending()
    assert len(connection.fake_channel.published) == 4


def test_storefront_is_served(order_module):
    response = TestClient(order_module.app).get("/")
    assert response.status_code == 200
    assert "MaltaShop" in response.text


def test_authentication_requires_login_and_sets_secure_session_cookie(order_module):
    anonymous = TestClient(order_module.app)
    assert anonymous.get("/auth/me").status_code == 401
    assert anonymous.post("/orders/my", json={}).status_code == 401
    assert anonymous.post(
        "/orders", json={"sku": "HEADPHONES-01", "quantity": 1}
    ).status_code == 401

    registered = anonymous.post(
        "/auth/register",
        json={
            "email": "new-customer@example.com",
            "full_name": "New Customer",
            "password": "test-password-123",
        },
    )
    assert registered.status_code == 201
    assert registered.json()["role"] == "customer"
    assert "httponly" in registered.headers["set-cookie"].lower()
    assert anonymous.get("/auth/me").json()["email"] == "new-customer@example.com"
    assert anonymous.post(
        "/auth/register",
        json={
            "email": "NEW-CUSTOMER@example.com",
            "full_name": "Duplicate",
            "password": "test-password-123",
        },
    ).status_code == 409

    login = TestClient(order_module.app)
    assert login.post(
        "/auth/login",
        json={"email": "new-customer@example.com", "password": "wrong-password"},
    ).status_code == 401
    assert login.post(
        "/auth/login",
        json={"email": "NEW-CUSTOMER@example.com", "password": "test-password-123"},
    ).status_code == 200
    assert login.post("/auth/logout").status_code == 200
    assert login.get("/auth/me").status_code == 401


def test_password_reset_changes_password_and_revokes_sessions(order_module):
    account = TestClient(order_module.app)
    assert account.post(
        "/auth/register",
        json={
            "email": "reset-customer@example.com",
            "full_name": "Reset Customer",
            "password": "original-password-123",
        },
    ).status_code == 201
    old_session = account.cookies.get(order_module.SESSION_COOKIE)

    anonymous = TestClient(order_module.app)
    known_response = anonymous.post(
        "/auth/password-reset/request",
        json={"email": "RESET-CUSTOMER@example.com"},
    )
    unknown_response = anonymous.post(
        "/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )
    assert known_response.status_code == unknown_response.status_code == 200
    assert known_response.json() == unknown_response.json()

    with order_module.connect() as db:
        reset_event = order_module.json.loads(
            db.execute(
                "SELECT payload FROM outbox WHERE published=0 ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0]
        )
        token = reset_event["reset_url"].split("#reset-token=", 1)[1]
        token_hash = order_module.hashlib.sha256(token.encode()).hexdigest()
        assert db.execute(
            "SELECT 1 FROM password_reset_tokens WHERE token_hash=?", (token_hash,)
        ).fetchone()

    changed = anonymous.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "new-password-123"},
    )
    assert changed.status_code == 200
    assert changed.json()["message"] == "Your password has been updated. Please log in."
    assert account.get("/auth/me").status_code == 401
    assert anonymous.post(
        "/auth/login",
        json={"email": "reset-customer@example.com", "password": "original-password-123"},
    ).status_code == 401
    assert anonymous.post(
        "/auth/login",
        json={"email": "reset-customer@example.com", "password": "new-password-123"},
    ).status_code == 200
    assert anonymous.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "another-password-123"},
    ).status_code == 400
    assert old_session


def test_staff_roles_can_request_password_reset(order_module):
    for role in (
        "admin",
        "product_management_officer",
        "inventory_manager",
        "order_fulfillment_officer",
        "finance_officer",
    ):
        client = make_client(
            order_module,
            email=f"{role.replace('_', '-')}@example.com",
            role=role,
        )
        response = client.post(
            "/auth/password-reset/request",
            json={"email": f"{role.replace('_', '-')}@example.com"},
        )
        assert response.status_code == 200


def test_password_reset_rejects_expired_token(order_module):
    client = make_client(order_module)
    client.post(
        "/auth/password-reset/request",
        json={"email": "shopper@example.com"},
    )
    with order_module.connect() as db:
        payload = order_module.json.loads(
            db.execute(
                "SELECT payload FROM outbox WHERE published=0 ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0]
        )
        token = payload["reset_url"].split("#reset-token=", 1)[1]
        token_hash = order_module.hashlib.sha256(token.encode()).hexdigest()
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.execute(
            "UPDATE password_reset_tokens SET expires_at=? WHERE token_hash=?",
            (expired_at, token_hash),
        )

    response = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "new-password-123"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "This reset link is invalid or has expired."


def test_initial_admin_bootstrap_requires_valid_credentials(order_module, monkeypatch):
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", " owner@example.com ")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "configured-admin-password")
    monkeypatch.setenv("INITIAL_ADMIN_NAME", "Configured Owner")
    order_module.initialize()

    client = TestClient(order_module.app)
    login = client.post(
        "/auth/login",
        json={"email": "OWNER@example.com", "password": "configured-admin-password"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "admin"
    assert login.json()["full_name"] == "Configured Owner"

    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "short")
    with pytest.raises(ValueError, match="10 to 256 characters"):
        order_module.initialize()


def test_demo_accounts_are_only_created_when_enabled(order_module, monkeypatch):
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0

    monkeypatch.setenv("DEMO_ACCOUNTS", "true")
    order_module.initialize()
    accounts = {
        "demo-customer@maltashop.test": ("Demo-Customer-2026!", "customer"),
        "demo-officer@maltashop.test": ("Demo-Officer-2026!", "product_management_officer"),
        "demo-inventory@maltashop.test": ("Demo-Inventory-2026!", "inventory_manager"),
        "demo-fulfillment@maltashop.test": ("Demo-Fulfillment-2026!", "order_fulfillment_officer"),
        "demo-finance@maltashop.test": ("Demo-Finance-2026!", "finance_officer"),
        "demo-admin@maltashop.test": ("Demo-Admin-2026!", "admin"),
    }
    for email, (password, role) in accounts.items():
        client = TestClient(order_module.app)
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        assert login.json()["role"] == role

    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 6


def test_stock_decrement_and_failed_batch_rollback(order_module):
    client = make_client(order_module)
    with order_module.connect() as db:
        db.execute("UPDATE products SET stock=0 WHERE sku='SPEAKER-01'")

    failed = client.post(
        "/orders/batch",
        headers={"Idempotency-Key": "atomic-stock-failure"},
        json={
            "items": [
                {"sku": "HEADPHONES-01", "quantity": 2},
                {"sku": "SPEAKER-01", "quantity": 1},
            ]
        },
    )
    assert failed.status_code == 409
    with order_module.connect() as db:
        assert db.execute(
            "SELECT stock FROM products WHERE sku='HEADPHONES-01'"
        ).fetchone()[0] == 25
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM batch_requests").fetchone()[0] == 0

    successful = client.post(
        "/orders/batch",
        headers={"Idempotency-Key": "stock-decrement"},
        json={"items": [{"sku": "HEADPHONES-01", "quantity": 3}]},
    )
    assert successful.status_code == 202
    with order_module.connect() as db:
        row = db.execute(
            "SELECT stock FROM products WHERE sku='HEADPHONES-01'"
        ).fetchone()
        price_snapshot = db.execute(
            "SELECT unit_price_cents FROM orders WHERE sku='HEADPHONES-01'"
        ).fetchone()[0]
    assert row[0] == 22
    assert price_snapshot > 0


def test_role_permissions_and_product_management(order_module):
    customer = make_client(order_module)
    officer = make_client(
        order_module, email="officer@example.com", role="product_management_officer"
    )
    inventory_manager = make_client(
        order_module, email="inventory@example.com", role="inventory_manager"
    )
    admin = make_client(order_module, email="admin@example.com", role="admin")

    assert customer.get("/admin/products").status_code == 403
    assert officer.get("/admin/products").status_code == 200
    assert inventory_manager.get("/admin/products").status_code == 200
    assert officer.get("/admin/users").status_code == 403
    assert officer.get("/admin/orders").status_code == 403
    assert inventory_manager.post(
        "/admin/products",
        json={
            "sku": "INVENTORY-CANNOT-CREATE",
            "name": "Unauthorized product",
            "category": "Accessories",
            "price": 12,
            "image": "https://example.com/product.jpg",
        },
    ).status_code == 403
    assert admin.get("/admin/users").status_code == 200
    assert admin.get("/admin/orders").status_code == 200

    created = officer.post(
        "/admin/products",
        json={
            "sku": "OFFICER-CREATED-1",
            "name": "Officer product",
            "category": "Accessories",
            "price": 12.34,
            "image": "https://example.com/product.jpg",
        },
    )
    assert created.status_code == 201
    assert created.json()["stock"] == 0
    assert officer.patch(
        "/admin/products/OFFICER-CREATED-1",
        json={"stock": 4},
    ).status_code == 403
    assert inventory_manager.patch(
        "/admin/products/OFFICER-CREATED-1",
        json={"price": 15.5},
    ).status_code == 403
    changed_stock = inventory_manager.patch(
        "/admin/products/OFFICER-CREATED-1",
        json={"stock": 4},
    )
    assert changed_stock.status_code == 200
    assert changed_stock.json()["stock"] == 4
    changed = officer.patch(
        "/admin/products/OFFICER-CREATED-1",
        json={"price": 15.5},
    )
    assert changed.status_code == 200
    assert changed.json()["price"] == 15.5
    assert changed.json()["stock"] == 4
    assert officer.post(
        "/admin/users",
        json={
            "email": "managed@example.com",
            "full_name": "Managed User",
            "password": "managed-password-123",
            "role": "customer",
        },
    ).status_code == 403
    managed_user = admin.post(
        "/admin/users",
        json={
            "email": "managed@example.com",
            "full_name": "Managed User",
            "password": "managed-password-123",
            "role": "customer",
        },
    )
    assert managed_user.status_code == 201
    assert managed_user.json()["role"] == "customer"
    managed_id = managed_user.json()["id"]
    managed_client = TestClient(order_module.app)
    assert managed_client.post(
        "/auth/login",
        json={"email": "managed@example.com", "password": "managed-password-123"},
    ).status_code == 200
    self_admin = next(
        user for user in admin.get("/admin/users").json()["users"]
        if user["email"] == "admin@example.com"
    )
    assert admin.patch(
        f"/admin/users/{self_admin['id']}",
        json={"role": "admin", "is_active": False},
    ).status_code == 409
    disabled = admin.patch(
        f"/admin/users/{managed_id}",
        json={"role": "customer", "is_active": False},
    )
    assert disabled.status_code == 200
    assert managed_client.get("/auth/me").status_code == 401


def test_admin_can_assign_each_staff_role(order_module):
    admin = make_client(order_module, email="root@example.com", role="admin")
    roles = (
        "product_management_officer",
        "inventory_manager",
        "order_fulfillment_officer",
        "finance_officer",
    )
    for role in roles:
        created = admin.post(
            "/admin/users",
            json={
                "email": f"{role}@example.test",
                "full_name": role.replace("_", " ").title(),
                "password": "staff-account-password",
                "role": role,
            },
        )
        assert created.status_code == 201
        assert created.json()["role"] == role
        staff_client = TestClient(order_module.app)
        login = staff_client.post(
            "/auth/login",
            json={
                "email": f"{role}@example.test",
                "password": "staff-account-password",
            },
        )
        assert login.status_code == 200
        assert login.json()["role"] == role


def test_fulfillment_lifecycle_and_customer_tracking(order_module):
    customer = make_client(order_module)
    dispatcher = make_client(
        order_module, email="delivery@example.com", role="order_fulfillment_officer"
    )
    finance = make_client(order_module, email="finance@example.com", role="finance_officer")
    placed = create_checkout_order(customer, "delivery-lifecycle")
    correlation_id = placed.json()["correlation_id"]
    order_id = placed.json()["orders"][0]["order_id"]

    assert customer.get("/staff/fulfillment/orders").status_code == 403
    assert finance.get("/staff/fulfillment/orders").status_code == 403
    assert dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={"status": "DISPATCHED", "facility": "Valletta", "tracking_reference": "MT-100"},
    ).status_code == 409
    accepted = dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={"status": "RECEIVED"},
    )
    assert accepted.status_code == 200
    with order_module.connect() as db:
        events = [
            order_module.json.loads(row[0])
            for row in db.execute("SELECT payload FROM outbox ORDER BY rowid")
        ]
    accepted_events = [event for event in events if event["type"] == "OrderAccepted"]
    assert len(accepted_events) == 1
    assert accepted_events[0]["recipient_email"] == "shopper@example.com"
    assert accepted_events[0]["correlation_id"] == correlation_id
    my_order_before_dispatch = customer.post("/orders/my", json={}).json()["orders"][0]
    expected_order_ids = {
        item["order_id"] for item in my_order_before_dispatch["items"]
    }
    order_item = next(
        item for item in my_order_before_dispatch["items"]
        if item["order_id"] == order_id
    )
    auto_tracking_id = order_item["delivery_tracking_id"]
    assert auto_tracking_id.startswith("MT-")
    assert customer.get(f"/orders/{auto_tracking_id}").json()["order_id"] == order_id
    assert dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={"status": "DISPATCHED"},
    ).status_code == 422
    dispatched = dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={
            "status": "DISPATCHED",
            "facility": "Valletta Delivery Facility",
            "tracking_reference": "MT-TRACK-123",
        },
    )
    assert dispatched.status_code == 200
    tracking = customer.get(f"/orders/{order_id}")
    assert tracking.status_code == 200
    assert tracking.json()["status"] == "DISPATCHED"
    assert tracking.json()["delivery_facility"] == "Valletta Delivery Facility"
    assert tracking.json()["delivery_tracking_id"] == "MT-TRACK-123"
    assert customer.get("/orders/MT-TRACK-123").json()["order_id"] in expected_order_ids
    assert dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={"status": "DELIVERED"},
    ).json()["status"] == "DELIVERED"
    my_order = customer.post("/orders/my", json={}).json()["orders"][0]
    assert my_order["status"] == "DELIVERED"
    assert my_order["delivery_facility"] == "Valletta Delivery Facility"
    assert my_order["delivery_tracking_id"] == "MT-TRACK-123"
    assert my_order["items"][0]["delivery_tracking_id"] == "MT-TRACK-123"


def test_live_delivery_gps_is_opt_in_private_and_expires(order_module):
    customer = make_client(order_module)
    dispatcher = make_client(
        order_module, email="gps-delivery@example.com", role="order_fulfillment_officer"
    )
    other_dispatcher = make_client(
        order_module, email="gps-backup@example.com", role="order_fulfillment_officer"
    )
    other_customer = make_client(order_module, email="different-shopper@example.com")
    placed = create_checkout_order(customer, "gps-sharing")
    correlation_id = placed.json()["correlation_id"]
    order_id = placed.json()["orders"][0]["order_id"]
    location_url = f"/staff/fulfillment/orders/{correlation_id}/location"
    location = {"latitude": 35.8992, "longitude": 14.5141, "accuracy": 12.5}

    assert customer.put(location_url, json=location).status_code == 403
    assert dispatcher.put(location_url, json=location).status_code == 409
    assert customer.get(f"/orders/{order_id}").json()["live_location"] is None
    assert other_customer.get(f"/orders/{order_id}").status_code == 404

    assert dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={"status": "RECEIVED"},
    ).status_code == 200
    assert dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={
            "status": "DISPATCHED",
            "facility": "Valletta Delivery Facility",
            "tracking_reference": "MT-GPS-123",
        },
    ).status_code == 200
    assert dispatcher.put(
        location_url,
        json={**location, "latitude": 91},
    ).status_code == 422
    assert dispatcher.put(location_url, json=location).status_code == 200

    live = customer.get(f"/orders/{order_id}").json()["live_location"]
    assert live["status"] == "live"
    assert live["latitude"] == location["latitude"]
    assert live["longitude"] == location["longitude"]
    my_order = customer.post("/orders/my", json={}).json()["orders"][0]
    assert my_order["live_location"]["status"] == "live"
    assert other_dispatcher.put(location_url, json=location).status_code == 409
    assert other_dispatcher.delete(location_url).status_code == 403

    with order_module.connect() as db:
        db.execute(
            "UPDATE delivery_locations SET updated_at=? WHERE correlation_id=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(), correlation_id),
        )
    stale = customer.get(f"/orders/{order_id}").json()["live_location"]
    assert stale == {"status": "stale", "updated_at": stale["updated_at"]}
    assert other_dispatcher.put(location_url, json=location).status_code == 200
    assert dispatcher.delete(location_url).status_code == 403
    assert other_dispatcher.delete(location_url).json()["status"] == "stopped"
    assert customer.get(f"/orders/{order_id}").json()["live_location"] is None

    assert dispatcher.put(location_url, json=location).status_code == 200
    delivered = dispatcher.patch(
        f"/staff/fulfillment/orders/{correlation_id}",
        json={"status": "DELIVERED"},
    )
    assert delivered.status_code == 200
    assert customer.get(f"/orders/{order_id}").json()["live_location"] is None
    with order_module.connect() as db:
        assert db.execute(
            "SELECT count(*) FROM delivery_locations WHERE correlation_id=?",
            (correlation_id,),
        ).fetchone()[0] == 0


def test_finance_can_reconcile_payments_and_refunds(order_module):
    customer = make_client(order_module)
    finance = make_client(order_module, email="finance@example.com", role="finance_officer")
    dispatcher = make_client(
        order_module, email="delivery@example.com", role="order_fulfillment_officer"
    )
    placed = create_checkout_order(customer, "finance-reconciliation")
    first_order = placed.json()["orders"][0]
    correlation_id = placed.json()["correlation_id"]

    assert customer.get("/staff/finance/summary").status_code == 403
    assert dispatcher.get("/staff/finance/summary").status_code == 403
    initial = finance.get("/staff/finance/summary")
    assert initial.status_code == 200
    assert initial.json()["summary"]["outstanding"] > 0
    assert finance.patch(
        f"/staff/finance/orders/{first_order['order_id']}/payment",
        json={"payment_status": "PAID"},
    ).status_code == 200
    paid = finance.get("/staff/finance/summary").json()
    assert paid["summary"]["recorded_revenue"] > 0

    assert customer.post(
        "/orders/my/cancel", json={"correlation_id": correlation_id}
    ).status_code == 200
    assert finance.patch(
        f"/staff/finance/orders/{first_order['order_id']}/payment",
        json={"payment_status": "REFUNDED"},
    ).status_code == 200
    refunded = finance.get("/staff/finance/summary").json()
    assert refunded["summary"]["refunded"] == first_order["quantity"] * 64

    assert finance.patch(
        f"/staff/finance/orders/{first_order['order_id']}/payment",
        json={"payment_status": "PAID"},
    ).status_code == 409


def test_legacy_orders_remain_admin_only(order_module):
    customer = make_client(order_module)
    admin = make_client(order_module, email="admin@example.com", role="admin")
    with order_module.connect() as db:
        db.execute(
            "INSERT INTO orders (id,customer_id,sku,quantity,status,correlation_id) "
            "VALUES ('legacy-order','legacy-customer','OLD-SKU',1,'PENDING','legacy-correlation')"
        )

    assert customer.post("/orders/my", json={}).json()["orders"] == []
    assert customer.get("/orders/legacy-order").status_code == 404
    all_orders = admin.get("/admin/orders")
    assert all_orders.status_code == 200
    assert any(order["order_id"] == "legacy-order" for order in all_orders.json()["orders"])
    assert admin.get("/orders/legacy-order").status_code == 200
