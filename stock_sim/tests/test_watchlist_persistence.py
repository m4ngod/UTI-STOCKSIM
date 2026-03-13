import json
import time
from pathlib import Path
from typing import List

from app.panels.market.panel import MarketPanel
from app.services.watchlist_store import WatchlistStore
from app.core_dto.snapshot import SnapshotDTO

# ---- Stubs ----
class _StubController:
    def __init__(self):
        self._snapshots = {}
    def list_snapshots(self, page: int, page_size: int, symbol_filter, sort_by: str):  # noqa: D401
        items = list(self._snapshots.values())
        return {"items": items, "total": len(items), "page": 1}
    def get_snapshot(self, symbol: str):
        return self._snapshots.get(symbol)

class _StubService:
    def ensure_symbol(self, symbol: str):  # noqa: D401
        pass
    def request_detail(self, symbol: str, timeframe, ensure_loaded: bool = True):  # noqa: D401
        return {"series": None, "is_stale": False}

# ---- Tests ----

def test_watchlist_persistence_restore(tmp_path: Path):
    writes: List[List[str]] = []
    store_path = tmp_path / "watchlist.json"
    store = WatchlistStore(str(store_path), debounce_seconds=0.05, on_write=lambda syms: writes.append(syms))
    panel = MarketPanel(_StubController(), _StubService(), watchlist_store=store)
    panel.add_symbol("AAA")
    panel.add_symbol("BBB")  # 第二次快速添加应仍只最终一次写
    # 等待去抖
    time.sleep(0.12)
    assert len(writes) == 1  # 去抖成功 (无写放大)
    with open(store_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data["symbols"] == ["AAA", "BBB"]

    # 重启 (新实例加载)
    store2 = WatchlistStore(str(store_path), debounce_seconds=0.05)
    panel2 = MarketPanel(_StubController(), _StubService(), watchlist_store=store2)
    view = panel2.get_view()
    assert view["watchlist"]["symbols"] == ["AAA", "BBB"]

    # 移除并立即 flush
    panel2.remove_symbol("AAA")
    store2.flush_now()
    with open(store_path, 'r', encoding='utf-8') as f:
        data2 = json.load(f)
    assert data2["symbols"] == ["BBB"]


def test_watchlist_flush_now(tmp_path: Path):
    store_path = tmp_path / "watchlist.json"
    store = WatchlistStore(str(store_path), debounce_seconds=10.0)  # 很长, 不等待定时器
    panel = MarketPanel(_StubController(), _StubService(), watchlist_store=store)
    panel.add_symbol("X1")
    # 未 flush 前文件不存在
    assert not store_path.exists()
    store.flush_now()
    assert store_path.exists()
    with open(store_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data["symbols"] == ["X1"]

