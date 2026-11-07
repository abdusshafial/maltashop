import os
import sys
from pathlib import Path

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

application = ASGIMiddleware(app)
