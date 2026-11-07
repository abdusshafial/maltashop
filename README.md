# MaltaShop

MaltaShop is a demo storefront with a FastAPI order service and SQLite storage.

## Run locally

Install the order service dependencies, then run the API from the project root:

```bash
python -m pip install -r order_service/requirements.txt
python -m uvicorn order_service.app:app --reload
```

Open `http://127.0.0.1:8000/`. The demo storefront and order endpoints are served by the same app.

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
