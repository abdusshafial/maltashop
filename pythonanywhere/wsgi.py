import os
import sys
import threading
from pathlib import Path
from typing import Callable, Iterable

PROJECT_ROOT = Path(
    os.environ.get("MALTASHOP_ROOT", Path(__file__).resolve().parent.parent)
)
if not (PROJECT_ROOT / "order_service" / "app.py").is_file():
    PROJECT_ROOT = Path.home() / "maltashop"
if not (PROJECT_ROOT / "order_service" / "app.py").is_file():
    raise RuntimeError(f"MaltaShop project files not found in {PROJECT_ROOT}")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ORDER_DB", str(PROJECT_ROOT / "data" / "orders.db"))
os.environ.setdefault("NOTIFICATION_DB", str(PROJECT_ROOT / "data" / "notifications.db"))
os.environ.setdefault("RABBITMQ_HOST", "localhost")

from a2wsgi import ASGIMiddleware
from order_service.app import app

_asgi_application = None
_asgi_application_lock = threading.Lock()


def application(environ: dict, start_response: Callable) -> Iterable[bytes]:
    global _asgi_application
    if _asgi_application is None:
        with _asgi_application_lock:
            if _asgi_application is None:
                _asgi_application = ASGIMiddleware(app)
    return _asgi_application(environ, start_response)
