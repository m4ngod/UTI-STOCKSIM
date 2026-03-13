# file: observability/struct_logger.py
# python
import json, time, os
from datetime import datetime
from threading import RLock
from stock_sim.settings import settings

class StructLogger:
    def __init__(self, path: str | None = None):
        self.path = path or settings.JSON_LOG_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = RLock()

    def log(self, category: str, **fields):
        record = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds"),
            "cat": category,
            **fields
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

logger = StructLogger()