# MaltaShop

MaltaShop is a demo storefront with a FastAPI order service and SQLite storage.

## Run locally

Install the order service dependencies, then run the API from the project root:

```bash
python -m pip install -r order_service/requirements.txt
$env:SESSION_COOKIE_SECURE = "false"
python -m uvicorn order_service.app:app --reload
```

Open `http://127.0.0.1:8000/`. The demo storefront and order endpoints are served by the same app.
The cookie setting above is for local HTTP only; use `SESSION_COOKIE_SECURE=true`
when serving over HTTPS.

## Order email notifications

The Docker Compose notification worker can send three transactional emails to
the signed-in customer's account email: order confirmed at checkout, order
accepted by fulfillment staff, and order cancelled. To enable Gmail delivery:

1. Copy `.env.example` to `.env`.
2. Set `SMTP_USER` to the sending Gmail address and `SMTP_FROM` to that address
   (or leave `SMTP_FROM` empty).
3. Create a Google App Password after enabling 2-Step Verification, then put
   the full 16-character app password in `SMTP_PASSWORD` (spaces are okay).
   Do not use your normal Google password or commit `.env`.
4. Start or rebuild the services with `docker compose up --build -d`.

The worker uses Gmail SMTP over TLS on port 587 by default. Without SMTP
credentials it leaves email events queued and logs that setup is required;
the standalone local Uvicorn command above does not run RabbitMQ or the email
worker. The worker starts processing queued emails after valid credentials are
configured. Check delivery attempts with
`docker compose logs notification-worker --tail 60`.

## Accounts, roles, inventory, and orders

Customers create an account with their name, email, and password and must be
logged in to place an order. Passwords are stored as salted PBKDF2 hashes; login
uses an opaque, expiring, HTTP-only, SameSite=Strict cookie. Set
`SESSION_COOKIE_SECURE=true` when serving the site over HTTPS. Docker Compose
defaults this setting to `false` for its local HTTP-only port; override it for
any public HTTPS deployment.

- Configure the first administrator using `INITIAL_ADMIN_EMAIL`,
  `INITIAL_ADMIN_PASSWORD` (at least 10 characters), and optionally
  `INITIAL_ADMIN_NAME`. No default administrator password is created. For
  Docker Compose, put these values in an untracked local `.env` file. For
  a local run, set them in the shell before starting Uvicorn. For PythonAnywhere,
  set them in the WSGI configuration before importing the app.
- Optional local/demo accounts can be created by setting `DEMO_ACCOUNTS=true`
  before startup (or in the local Compose `.env`). Demo users are inserted only
  if their accounts do not already exist:

  | Role | Email (username) | Password |
  | --- | --- | --- |
  | Customer | `demo-customer@maltashop.test` | `Demo-Customer-2026!` |
  | Product management officer | `demo-officer@maltashop.test` | `Demo-Officer-2026!` |
  | Inventory manager | `demo-inventory@maltashop.test` | `Demo-Inventory-2026!` |
  | Order fulfillment officer | `demo-fulfillment@maltashop.test` | `Demo-Fulfillment-2026!` |
  | Finance officer | `demo-finance@maltashop.test` | `Demo-Finance-2026!` |
  | Administrator | `demo-admin@maltashop.test` | `Demo-Admin-2026!` |

  These public demo credentials are for local/test use only. Never enable
  `DEMO_ACCOUNTS` on a public or production deployment; use private
  `INITIAL_ADMIN_*` credentials instead.
- **Admin** can manage users and roles, view all orders, and perform any
  product, inventory, fulfillment, and finance action.
- **Product management officer** creates products and manages catalog categories,
  prices, and availability. New products start with zero stock.
- **Inventory manager** can view products and change stock quantities only;
  they cannot edit prices or product details.
- **Order fulfillment officer** accepts new orders, records the delivery
  (`PENDING` → `RECEIVED`), records the delivery facility and tracking reference
  when dispatching (`RECEIVED` → `DISPATCHED`), and confirms successful delivery
  (`DISPATCHED` → `DELIVERED`). Customers can see the progress and tracking
  details on their own orders. After dispatch, staff can explicitly start GPS
  sharing from a phone or other location-enabled device; the browser asks for
  permission, and the customer's signed-in account can see the live position.
  GPS sharing requires HTTPS (localhost is also a secure browser context).
  Staff can stop sharing at any time; stale coordinates are hidden after two
  minutes without an update and location data is deleted when delivery is
  confirmed.
- Transactional emails are sent for order confirmation, fulfillment acceptance,
  and customer cancellation. The order and its email event are saved together;
  notifications are delivered by the RabbitMQ worker.
- **Finance officer** reviews order totals and a reconciliation summary, then
  records externally confirmed payments and refunds for cancelled, paid orders.
  The demo does not collect or process money.
- Staff accounts have separate permissions enforced by the API, not only hidden
  interface controls. The admin can create, disable, and change every role.
- Checkout and inventory decrement happen in one SQLite write transaction.
  Concurrent orders cannot oversell stock; cancelled orders within the 12-hour
  window return their quantities to inventory.
- **My orders** and order tracking use the signed-in account. Customers only
  see their own account-linked orders. Orders from before account login was
  added have no account owner and remain admin-only.
- Customers can cancel a pending order within 12 hours after a confirmation
  prompt. They can also submit product complaints (selecting an item from the
  order) or delivery-person complaints; complaint records are stored in SQLite.
- Local run: `data/orders.db` in the project.
- Docker Compose: `/data/orders.db` on the persistent `orderdata` volume.
- PythonAnywhere: `~/maltashop/data/orders.db`.

The initial product inventory is loaded from `order_service/catalog_seed.json`
once. Subsequent product prices, categories, active status, and quantities are
stored in SQLite and are not overwritten on restart.

The checkout and confirmation show an estimated **minimum of 2 and maximum of 5
working days** for delivery across Malta and Gozo. Weekends are excluded; this is
an estimate, not a guaranteed delivery date. The demo records a payment preference
but does not collect card details or process payments. Existing SQLite databases
are upgraded when the order service starts.

## Publish from GitHub to PythonAnywhere

### 1. Push the project to GitHub

Create an empty GitHub repository, then from the project root:

```bash
git init
git add .
git status
```

Check that `.env`, databases, and virtual environments are not listed. Then commit and push:

```bash
git commit -m "Prepare MaltaShop for deployment"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

### 2. Clone and install on PythonAnywhere

In a PythonAnywhere Bash console, replace `YOUR_USERNAME` with your PythonAnywhere username:

```bash
cd ~
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY.git maltashop
cd ~/maltashop
mkvirtualenv --python=/usr/local/bin/python3.11 maltashop-venv
workon maltashop-venv
pip install -r pythonanywhere/requirements.txt
```

For a private GitHub repository, configure GitHub access on PythonAnywhere before cloning.

### 3. Configure the PythonAnywhere web app

In the PythonAnywhere **Web** tab:

1. Create a **Manual configuration** web app using Python 3.11.
2. Set the virtualenv to `/home/YOUR_USERNAME/.virtualenvs/maltashop-venv`.
3. Open the WSGI configuration file and replace its contents with the contents of `pythonanywhere/wsgi.py`. The file locates the project under `~/maltashop` when copied into PythonAnywhere's WSGI configuration.
4. Reload the web app.

The WSGI file bridges PythonAnywhere's WSGI interface to the FastAPI ASGI app and initializes its event loop lazily inside the uWSGI worker. Static files are served by FastAPI at `/static`; no separate static mapping is required.

### Demo order processing

The storefront and order API work without RabbitMQ. Without a configured RabbitMQ service and background publisher/consumer, orders are stored and can be looked up, but notification events remain queued in the SQLite outbox and are not processed. The demo does not collect payment details.
