# MaltaShop

MaltaShop is a demo storefront with a FastAPI order service and SQLite storage.

## Run locally

Install the order service dependencies, then run the API from the project root:

```bash
python -m pip install -r order_service/requirements.txt
python -m uvicorn order_service.app:app --reload
```

Open `http://127.0.0.1:8000/`. The demo storefront and order endpoints are served by the same app.

## Orders, saved details, and delivery

The checkout saves each order item (SKU and quantity), customer email, name, phone,
delivery address, city, postcode, payment preference, order status, and delivery
estimate in SQLite. Orders are stored on the server, not just in the shopper's
browser. To find an order, use its ID from the confirmation and choose **Track an
order**.

- The **My orders** page lists checkout orders using the checkout email and phone
  number, so customers do not need an order/tracking ID. It shows products,
  order status, and delivery estimate without exposing the delivery address.
- Customers can cancel a pending order up to 12 hours after it was placed. The
  server checks the deadline when the cancellation is requested; after the
  deadline, the cancellation is rejected.
- From **My orders**, customers can report a problem with a product or the
  delivery person. Product complaints must identify an item in that order.
  Complaints are saved in the SQLite database and linked to the order.
- Local run: `data/orders.db` in the project.
- Docker Compose: `/data/orders.db` on the persistent `orderdata` volume.
- PythonAnywhere: `~/maltashop/data/orders.db`.

The checkout and confirmation show an estimated **minimum of 2 and maximum of 5
working days** for delivery across Malta and Gozo. Weekends are excluded; this is
an estimate, not a guaranteed delivery date. The demo records a payment preference
but does not collect card details or process payments. Existing SQLite databases
are upgraded when the order service starts.

The demo's order lookup asks for both the customer's email and phone number.
Before using customer order lookup on a public production site, add a verified
sign-in or one-time-code flow rather than treating those details as strong
authentication.

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
