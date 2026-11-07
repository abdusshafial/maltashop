import time, logging
from app import publish_pending
logging.basicConfig(level=logging.INFO)
while True:
    try: publish_pending()
    except Exception as exc: logging.warning('Outbox retry scheduled: %s',exc)
    time.sleep(2)
