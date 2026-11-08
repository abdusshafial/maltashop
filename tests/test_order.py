import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient


def test_order_creation_and_idempotency(order_module):
    client = TestClient(order_module.app)
    headers = {"Idempotency-Key": "test-100", "X-Correlation-ID": "corr-100"}
    payload = {"customer_id": "c1", "sku": "SKU-1", "quantity": 2}

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
    client = TestClient(order_module.app)
    response = client.post(
        "/orders", json={"customer_id": "c", "sku": "s", "quantity": 0}
    )
    assert response.status_code == 422


def test_batch_order_creation_is_atomic_and_idempotent(order_module):
    client = TestClient(order_module.app)
    headers = {"Idempotency-Key": "cart-100", "X-Correlation-ID": "corr-cart-100"}
    payload = {
        "customer_id": "shopper@example.com",
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
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 2

    changed_payload = {
        "customer_id": "shopper@example.com",
        "items": [
            {"sku": "HEADPHONES-01", "quantity": 3},
            {"sku": "NEW-ITEM", "quantity": 1},
        ],
    }
    conflict = client.post("/orders/batch", json=changed_payload, headers=headers)
    assert conflict.status_code == 409
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 2


def test_batch_retry_with_added_item_is_rejected_atomically(order_module):
    client = TestClient(order_module.app)
    headers = {"Idempotency-Key": "cart-added-item"}
    original = {
        "customer_id": "c1",
        "items": [{"sku": "SKU-1", "quantity": 1}],
    }
    assert client.post("/orders/batch", json=original, headers=headers).status_code == 202

    changed = {
        **original,
        "items": [*original["items"], {"sku": "SKU-2", "quantity": 1}],
    }
    response = client.post("/orders/batch", json=changed, headers=headers)

    assert response.status_code == 409
    with order_module.connect() as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1


def test_batch_rejects_duplicate_skus(order_module):
    response = TestClient(order_module.app).post(
        "/orders/batch",
        json={
            "customer_id": "c1",
            "items": [
                {"sku": "SKU-1", "quantity": 1},
                {"sku": "SKU-1", "quantity": 2},
            ],
        },
    )

    assert response.status_code == 422


def test_checkout_saves_customer_details_and_delivery_estimate(order_module):
    client = TestClient(order_module.app)
    response = client.post(
        "/orders/batch",
        headers={"Idempotency-Key": "complete-checkout"},
        json={
            "customer_id": "shopper@example.com",
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
    response = TestClient(order_module.app).post(
        "/orders/batch",
        json={
            "customer_id": "shopper@example.com",
            "full_name": "Ari Borg",
            "items": [{"sku": "SKU-1", "quantity": 1}],
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


def create_checkout_order(client, idempotency_key, email="shopper@example.com", phone="+356 1234 5678"):
    return client.post(
        "/orders/batch",
        headers={"Idempotency-Key": idempotency_key},
        json={
            "customer_id": email,
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


def test_customer_can_list_orders_without_tracking_id(order_module):
    client = TestClient(order_module.app)
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

def test_customer_can_submit_product_and_delivery_complaints(order_module):
    client = TestClient(order_module.app)
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
    client = TestClient(order_module.app)
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
    assert client.post("/orders/complaints", json=payload).status_code == 404

    payload["phone"] = "12345678"
    assert client.post("/orders/complaints", json=payload).status_code == 422

    payload["product_sku"] = "HEADPHONES-01"
    payload["message"] = "          "
    assert client.post("/orders/complaints", json=payload).status_code == 422


def test_customer_order_lookup_accepts_local_and_international_malta_phone(order_module):
    client = TestClient(order_module.app)
    create_checkout_order(client, "maltese-phone-format", phone="+356 9912-3456")

    for phone in ("9912 3456", "+356 9912 3456", "00356 9912 3456"):
        response = client.post(
            "/orders/my",
            json={"email": "shopper@example.com", "phone": phone},
        )
        assert response.status_code == 200
        assert len(response.json()["orders"]) == 1


def test_customer_order_lookup_requires_matching_email_and_phone(order_module):
    client = TestClient(order_module.app)
    created = create_checkout_order(client, "private-order")

    wrong_phone = client.post(
        "/orders/my",
        json={"email": "shopper@example.com", "phone": "+356 9999 9999"},
    )
    wrong_email = client.post(
        "/orders/my",
        json={"email": "other@example.com", "phone": "+356 1234 5678"},
    )

    assert wrong_phone.status_code == wrong_email.status_code == 200
    assert wrong_phone.json()["orders"] == []
    assert wrong_email.json()["orders"] == []
    cancel_wrong_phone = client.post(
        "/orders/my/cancel",
        json={
            "email": "shopper@example.com",
            "phone": "+356 9999 9999",
            "correlation_id": created.json()["correlation_id"],
        },
    )
    assert cancel_wrong_phone.status_code == 404
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
    client = TestClient(order_module.app)
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


def test_customer_cannot_cancel_order_after_twelve_hours(order_module):
    client = TestClient(order_module.app)
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
    response = TestClient(order_module.app).get("/orders/missing")
    assert response.status_code == 404


def test_publisher_sends_and_marks_pending_events(order_module, monkeypatch):
    client = TestClient(order_module.app)
    response = client.post(
        "/orders",
        json={"customer_id": "c1", "sku": "SKU-1", "quantity": 2},
        headers={"Idempotency-Key": "published-order", "X-Correlation-ID": "corr-1"},
    )
    assert response.status_code == 202

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
    assert len(connection.fake_channel.published) == 1
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
    assert published["properties"].delivery_mode == 2
    assert published["properties"].content_type == "application/json"
    event = order_module.json.loads(published["body"])
    assert event["type"] == "OrderPlaced"
    assert event["order_id"] == "published-order"
    with order_module.connect() as db:
        assert db.execute("SELECT published FROM outbox").fetchone()[0] == 1

    order_module.publish_pending()
    assert len(connection.fake_channel.published) == 1


def test_storefront_is_served(order_module):
    response = TestClient(order_module.app).get("/")
    assert response.status_code == 200
    assert "MaltaShop" in response.text
