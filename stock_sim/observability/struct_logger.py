# file: observability/struct_logger.py
# python
import atexit
import json, os, queue, threading, time
from datetime import datetime
from threading import RLock
from stock_sim.settings import settings


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


class StructLogger:
    def __init__(self, path: str | None = None):
        self.path = path or settings.JSON_LOG_PATH
        dir_name = os.path.dirname(self.path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        self._lock = RLock()
        self._async_enabled = _env_bool("STOCKSIM_STRUCT_LOG_ASYNC", True)
        self._queue: queue.Queue[str] | None = None
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._file = None
        if self._async_enabled:
            max_queue = max(1, _env_int("STOCKSIM_STRUCT_LOG_MAX_QUEUE", 10000))
            self._queue = queue.Queue(maxsize=max_queue)
            self._thread = threading.Thread(
                target=self._writer_loop,
                name="StructLoggerWriter",
                daemon=True,
            )
            self._thread.start()
            atexit.register(self.close)

    def log(self, category: str, **fields):
        record = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds"),
            "cat": category,
            **fields
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        q = self._queue
        if self._async_enabled and q is not None and not self._stop_evt.is_set():
            try:
                q.put_nowait(line)
            except queue.Full:
                pass
            return
        self._write_line_sync(line)

    def flush(self, timeout: float = 1.0) -> None:
        q = self._queue
        if q is not None:
            if timeout is None:
                q.join()
            else:
                stop_at = time.monotonic() + max(0.0, float(timeout))
                while getattr(q, "unfinished_tasks", 0) and time.monotonic() < stop_at:
                    time.sleep(0.01)
        with self._lock:
            try:
                if self._file is not None:
                    self._file.flush()
            except Exception:
                pass

    def close(self) -> None:
        if not self._async_enabled:
            return
        self._stop_evt.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self.flush(timeout=0.5)

    def _write_line_sync(self, line: str) -> None:
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _writer_loop(self) -> None:
        q = self._queue
        if q is None:
            return
        while not self._stop_evt.is_set() or not q.empty():
            try:
                line = q.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    if self._file is None:
                        self._file = open(self.path, "a", encoding="utf-8", buffering=1)
                    self._file.write(line + "\n")
            except Exception:
                pass
            finally:
                try:
                    q.task_done()
                except Exception:
                    pass
        with self._lock:
            try:
                if self._file is not None:
                    self._file.flush()
                    self._file.close()
            except Exception:
                pass
            self._file = None

logger = StructLogger()
