"""AccountPanel (Spec Task 24)

职责 (R1):
- 展示账户资金/权益/利用率/盈亏摘要
- 展示持仓分页 + 过滤 (symbol 子串匹配, 不区分大小写)
- 阈值高亮: 基于 SettingsStore.alert_thresholds['drawdown_pct'] (作为盈亏幅度阈值)
  若 |pnl_unreal| / max(position.avg_price * quantity, 1) >= drawdown_pct -> highlight=True
- 切换账户调用 AccountController.load_account(account_id) 并缓存当前 account_id
- 保证切换完成后渲染数据 (get_view) 在 300ms 以内 (服务层 + 控制器已是快速操作)

设计:
- 纯逻辑 (UI 框架无关) 返回结构化 dict 供上层 UI 渲染
- 线程安全: 简单 RLock; 读取 view 时不阻断 set 操作太久
- 订阅 SettingsStore 阈值更新 (动态高亮)

返回结构 get_view():
{
  'account': { 'account_id','cash','equity','utilization','realized_pnl','unrealized_pnl','snapshot_id','sim_day' },
  'positions': { 'total','page','page_size','items': [ {symbol, qty, avg_price, pnl_unreal, ratio, highlight} ] },
  'filter': symbol_filter or None,
}

未来扩展 TODO:
- TODO: 增加列排序 (盈亏/数量/符号)
- TODO: 增加持仓增量更新合并 (事件驱动)
- TODO: 增加多账户对比视图
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from threading import RLock
import time

from app.controllers.account_controller import AccountController
from app.state.settings_store import SettingsStore
from app.core_dto.account import AccountDTO, PositionDTO
# 新增: 通知中心 (可选)
try:  # pragma: no cover
    from app.panels.shared.notifications import notification_center as _shared_notification_center
except Exception:  # pragma: no cover
    _shared_notification_center = None

__all__ = ["AccountPanel"]

class AccountPanel:
    def __init__(self, controller: AccountController, settings_store: Optional[SettingsStore] = None):
        self._ctl = controller
        self._store = settings_store
        self._lock = RLock()
        self._account_id: Optional[str] = None
        self._symbol_filter: Optional[str] = None
        self._page: int = 1
        self._page_size: int = 20
        self._drawdown_threshold: float = 0.10  # 默认 10%
        if self._store is not None:
            # 初始化阈值
            try:
                self._drawdown_threshold = float(self._store.get_state().alert_thresholds.get('drawdown_pct', 0.10))
            except Exception:
                pass
            self._store.on_alert_thresholds(self._on_thresholds)
        # 新增: 已通知高亮 symbol 集合 (会话级去重)
        self._highlight_notified: set[str] = set()

    # ---------------- Public API ----------------
    def switch_account(self, account_id: str):  # 切换账户 (R1 AC1)
        start = time.perf_counter()
        acc = self._ctl.load_account(account_id)
        elapsed_ms = (time.perf_counter() - start) * 1000
        with self._lock:
            self._account_id = account_id
            # 切换账户后重置已通知集合
            self._highlight_notified.clear()
        # 简单断言性能 (超出仅记录, 不抛异常)
        if elapsed_ms > 300:  # 目标: <300ms
            try:
                from observability.metrics import metrics
                metrics.inc("account_panel_switch_slow")
            except Exception:  # pragma: no cover
                pass
        return acc

    def set_filter(self, symbol_substring: Optional[str]):
        with self._lock:
            self._symbol_filter = symbol_substring.lower() if symbol_substring else None

    def set_page(self, page: int, page_size: int):
        with self._lock:
            if page >= 1:
                self._page = page
            if page_size > 0:
                self._page_size = page_size

    def refresh(self):  # 手动刷新 (重新拉取同账户)
        with self._lock:
            aid = self._account_id
        if aid:
            self._ctl.load_account(aid)

    def get_view(self) -> Dict[str, Any]:  # R1 AC2/3: 分页 + 过滤
        with self._lock:
            page = self._page
            page_size = self._page_size
            filt = self._symbol_filter
        acc = self._ctl.get_account()
        if not acc:
            return {
                'account': None,
                'positions': {'total': 0, 'page': page, 'page_size': page_size, 'items': []},
                'filter': filt,
            }
        # 过滤 + 分页
        items: List[PositionDTO] = acc.positions
        if filt:
            items = [p for p in items if filt in p.symbol.lower()]
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start:start+page_size] if start < total else []
        enriched = [self._enrich_position(p) for p in page_items]
        return {
            'account': self._account_summary(acc),
            'positions': {
                'total': total,
                'page': page,
                'page_size': page_size,
                'items': enriched,
            },
            'filter': filt,
        }

    # ---------------- Internal ----------------
    def _account_summary(self, acc: AccountDTO) -> Dict[str, Any]:
        return {
            'account_id': acc.account_id,
            'cash': acc.cash,
            'equity': acc.equity,
            'utilization': acc.utilization,
            'realized_pnl': acc.realized_pnl,
            'unrealized_pnl': acc.unrealized_pnl,
            'snapshot_id': acc.snapshot_id,
            'sim_day': acc.sim_day,
        }

    def _enrich_position(self, p: PositionDTO) -> Dict[str, Any]:
        mv_base = max(p.avg_price * p.quantity, 1.0)
        pnl = p.pnl_unreal or 0.0
        ratio = pnl / mv_base
        highlight = abs(ratio) >= self._drawdown_threshold
        if highlight:
            # O(1) 集合判断, 去重
            sym = p.symbol
            if sym not in self._highlight_notified:
                self._highlight_notified.add(sym)
                try:  # pragma: no cover
                    if _shared_notification_center is not None:
                        _shared_notification_center.publish(
                            'alert',
                            'position.highlight',
                            f'持仓 {sym} 触发盈亏阈值 (ratio={ratio:.2%})',
                            data={'symbol': sym, 'ratio': ratio},
                        )
                except Exception:
                    pass
        return {
            'symbol': p.symbol,
            'quantity': p.quantity,
            'avg_price': p.avg_price,
            'borrowed_qty': p.borrowed_qty,
            'pnl_unreal': p.pnl_unreal,
            'pnl_ratio': ratio,
            'highlight': highlight,
        }

    def _on_thresholds(self, kind: str, value, full):  # noqa: ANN001
        try:
            th = value.get('drawdown_pct') if isinstance(value, dict) else None
            if th is not None:
                self._drawdown_threshold = float(th)
        except Exception:
            pass
