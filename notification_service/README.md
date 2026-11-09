# MaltaShop order-event prototype

Case-study demonstration for Unit 5 Service-Oriented Architecture and Microservices Fundamentals. Two independently deployable services: **Order API** (FastAPI) and **Notification Worker** (Python), with separate SQLite databases and RabbitMQ durable topic exchange. A separate outbox publisher runs from the Order image. It is a process, not a third business service.

## Run

Requires Docker Engine / Docker Desktop with Compose v2. From repository root:

```bash
cp .env.example .env       # Windows PowerShell: Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

When the services are healthy, open the storefront at **http://localhost:8000**. Browse and filter the sample collection, add several products to your bag, place a demo order, and look up its status from the confirmation screen or **Track an order** in the footer. The storefront is served by the Order API, and checkout submits the whole bag as one atomic, idempotent batch.

Checkout uses the signed-in customer's account email for order updates. Do not enter real personal information unless you have configured a trusted SMTP sender and understand this prototype's privacy limitations.

### Gmail email delivery

Copy `.env.example` to `.env`, set `SMTP_USER` to the sender's Gmail address,
and set `SMTP_PASSWORD` to a Google App Password (2-Step Verification must be
enabled). `SMTP_FROM` defaults to `SMTP_USER`; Gmail SMTP uses TLS on port 587.
Never use a regular Google account password or commit `.env`. With SMTP
credentials absent, the worker waits without consuming the durable email queue.
After setting credentials, restart the worker with `docker compose up -d
--build notification-worker`. Check `docker compose logs notification-worker`.

The worker sends one email per checkout and sends the acceptance or cancellation
update when those order changes are committed. SMTP delivery is asynchronous;
check the worker log for delivery or configuration errors.

PowerShell example:

```powershell
$headers = @{ 'X-Correlation-ID'='malta-demo-001'; 'Idempotency-Key'='demo-order-001' }
$body = @{ customer_id='customer-1'; sku='TV-42'; quantity=1 } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/orders -Method Post -ContentType 'application/json' -Headers $headers -Body $body
docker compose logs order-publisher notification-worker --tail 60
```

For Linux/macOS:

```bash
curl -i -X POST http://localhost:8000/orders -H 'Content-Type: application/json' -H 'X-Correlation-ID: malta-demo-001' -H 'Idempotency-Key: demo-order-001' -d '{"customer_id":"customer-1","sku":"TV-42","quantity":1}'
docker compose logs order-publisher notification-worker --tail 60
```

Order API: `http://localhost:8000/docs`, health: `/health`. RabbitMQ management UI: `http://localhost:15672` (use .env credentials). Shut down with `docker compose down` (preserves data). To erase volumes, use `docker compose down -v` **only if you intend to delete demo data**.

## Design and guarantees

- Each service writes only to its own database. Order API commits the order and an `OrderPlaced` message to its own SQLite database atomically.
- Publisher polls the outbox, sends persistent messages to RabbitMQ and marks them published. At-least-once publishing means duplicates are possible; Notification deduplicates by event ID.
- HTTP `202 PENDING` means **accepted for processing**, not paid or fulfilled.
- Storefront checkout creates all items in one transaction at `POST /orders/batch`; retrying with the same idempotency key does not create duplicates.
- Correlation ID is carried in HTTP, stored in the order and event, and logged in both processes.
- Example `Idempotency-Key` protects against duplicate order creation, with conflict on different payload.
- The notification queue and dead-letter queue are durable. Order confirmation, acceptance, and cancellation events are routed to the notification worker; invalid messages and processing failures go to `notification.order_placed.dead`.
- The consumer acknowledges a message only after its local SQLite transaction commits, and closes its RabbitMQ connection before retrying after a connection failure.

## Automated tests

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
```

## Scope / production gaps

This teaching prototype does **not** implement Payment or Inventory business services, payment processing, inventory reservation, authentication, customer PII handling, complete distributed saga, live AI recommendation or production Kubernetes. Section 6.1 of the report outlines those future interactions. Also missing: TLS/mTLS, production secrets, centralized telemetry, outbox publisher confirms, automated dead-letter replay/alerting, durable database backups, network policy, real load testing, CI deployment approval, and proven availability. SQLite shared between order-api and publisher is for local Compose use only; production should use managed PostgreSQL and coordinated outbox dispatch.

## Evidence collection

Run Docker Compose, issue the HTTP request above, and take actual screenshots of (1) HTTP response, (2) notification-worker logs showing `order_event_consumed`, (3) publisher/order logs with matching correlation ID. Push multiple meaningful commits to your own GitHub repository and capture an actual passing Actions run. No screenshots or remote build results are invented in this repository.

## Suggested commit progression

1. `docs: define order flow and architecture`
2. `feat: add order API and transactional outbox`
3. `feat: add RabbitMQ notification consumer`
4. `build: add Dockerfiles and Compose`
5. `test: add idempotency and event dedup tests`
6. `ci: add GitHub Actions pipeline`

Commit **as you work**; do not manufacture a history. The lecturer requires genuine incremental history.
