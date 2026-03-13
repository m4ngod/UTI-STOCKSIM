"""WatchlistStore

持久化自选股列表到 JSON 文件, 带防写放大去抖(debounce)。
- set_symbols() 只调度一次延迟写; 期间多次更新合并为一次
- flush_now() 立即写入 (测试/关闭时调用)
- 线程安全 RLock
- on_write 回调: 测试计数
结构: {"symbols": ["AAA", "BBB"]}
"""
from __future__ import annotations
from typing import List, Optional, Callable
import json
import os
import threading
import time
from threading import RLock

class WatchlistStore:
    def __init__(self, path: str, debounce_seconds: float = 0.5, on_write: Optional[Callable[[List[str]], None]] = None):
        self._path = path
        self._debounce = debounce_seconds
        self._lock = RLock()
        self._symbols: List[str] = []
        self._timer: Optional[threading.Timer] = None
        self._pending = False
        self._last_write_ts = 0.0
        self._on_write = on_write

    # ---------- Load / Access ----------
    def load(self) -> List[str]:
        with self._lock:
            try:
                if os.path.exists(self._path):
                    with open(self._path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        syms = data.get("symbols", [])
                        if isinstance(syms, list):
                            self._symbols = [str(s) for s in syms]
            except Exception:  # pragma: no cover
                pass
            return list(self._symbols)

    def get_symbols(self) -> List[str]:
        with self._lock:
            return list(self._symbols)

    # ---------- Update ----------
    def set_symbols(self, symbols: List[str]):
        with self._lock:
            self._symbols = list(symbols)
            self._pending = True
            if self._timer and self._timer.is_alive():
                return
            self._timer = threading.Timer(self._debounce, self._debounced_flush)
            self._timer.daemon = True
            self._timer.start()

    def _debounced_flush(self):  # 定时器线程调用
        with self._lock:
            if not self._pending:
                return
            self._write_no_lock()

    def flush_now(self):
        with self._lock:
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
            if self._pending:
                self._write_no_lock()

    def _write_no_lock(self):
        try:
            os.makedirs(os.path.dirname(self._path) or '.', exist_ok=True)
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"symbols": self._symbols}, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:  # pragma: no cover
            return
        self._pending = False
        self._last_write_ts = time.time()
        if self._on_write:
            try:
                self._on_write(list(self._symbols))
            except Exception:  # pragma: no cover
                pass

__all__ = ["WatchlistStore"]
