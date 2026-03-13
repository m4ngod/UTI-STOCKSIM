"""AccountController (Spec Task 20)

职责 (R1):
- 封装 AccountService 账户加载接口
- 提供持仓分页/过滤能力 (面板使用)
- 简单缓存最近一次 AccountDTO
- 可扩展增量事件合并 (Phase1 直接全量替换)

分页 & 过滤:
get_positions(page=1, page_size=20, symbol_filter=None)
返回: { 'total': int, 'page': int, 'page_size': int, 'items': List[PositionDTO] }

指标: (Account 层当前无数值指标异步计算, 未来可扩扩展)

Future Hooks (Task50):
- TODO: RL stats 注入 (账户权益、保证金利用) 供 RL 面板聚合
- TODO: Kafka 事件外部化 (ACCOUNT_UPDATED -> Kafka Topic account.updates)
- TODO: 账户风险聚合指标 (max_drawdown_rolling, exposure_ratio) 缓存供导出
- TODO: dump_metrics() 集成按需附加 counters 到导出 JSON
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from threading import RLock

from app.core_dto.account import AccountDTO, PositionDTO
from app.services.account_service import AccountService
from observability.metrics import metrics

__all__ = ["AccountController"]

class AccountController:
    def __init__(self, service: AccountService):
        self._service = service
        self._lock = RLock()
        self._account: Optional[AccountDTO] = None
        self._last_account_id: Optional[str] = None

    # ---------------- Public API ----------------
    def load_account(self, account_id: str) -> AccountDTO:
        import time
        start = time.perf_counter()
        acc = self._service.load_account(account_id)
        with self._lock:
            self._account = acc
            self._last_account_id = account_id
        metrics.add_timing("account_controller_load_ms", (time.perf_counter() - start) * 1000)
        return acc

    def get_account(self) -> Optional[AccountDTO]:
        with self._lock:
            return self._account

    def get_positions(self, *, page: int = 1, page_size: int = 20, symbol_filter: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            acc = self._account
            if acc is None:
                return {"total": 0, "page": page, "page_size": page_size, "items": []}
            items: List[PositionDTO] = acc.positions
            if symbol_filter:
                sf = symbol_filter.lower()
                items = [p for p in items if sf in p.symbol.lower()]
            total = len(items)
            if page_size <= 0:
                page_size = 20
            start = (page - 1) * page_size
            if start >= total:
                paged: List[PositionDTO] = []
            else:
                end = start + page_size
                paged = items[start:end]
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": paged,
            }

    def refresh(self) -> Optional[AccountDTO]:
        with self._lock:
            acc_id = self._last_account_id
        if not acc_id:
            return None
        return self.load_account(acc_id)
