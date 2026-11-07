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
