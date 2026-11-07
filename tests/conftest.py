from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def order_module(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDER_DB", str(tmp_path / "orders.db"))
    return load_module("order_app", ROOT / "order_service" / "app.py")


@pytest.fixture
def notification_module(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFICATION_DB", str(tmp_path / "notifications.db"))
    return load_module("notification_consumer", ROOT / "notification_service" / "consumer.py")
