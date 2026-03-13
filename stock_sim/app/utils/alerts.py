"""告警与通知去抖 (Spec Task 19)

目标:
- 资金/回撤/心跳 阈值监控 (R6 AC6, R3 AC7)
- 60s 去抖: 同一告警类型在窗口内只触发一次 (Spec Done: 时间窗口内多次触发仅一次通知)
- 支持外部注入阈值 (与 SettingsState.alert_thresholds 对齐: drawdown_pct, heartbeat_ms, 可扩展)
- 触发后发事件: topic = 'alert.triggered'
- metrics:
  * metrics.inc('alert_triggered') 总计
  * metrics.inc(f'alert.{type}') 分类型计数
  * metrics.inc('alert_suppressed') 去抑次数

使用方式:
manager = AlertManager(thresholds={'drawdown_pct':0.1,'heartbeat_ms':10000})
manager.check_drawdown(current_equity, peak_equity)
manager.check_heartbeat(last_heartbeat_ts=time.time())

线程安全: 使用 RLock.
"""
from __future__ import annotations
import time
from threading import RLock
from typing import Dict, Optional, Any
from stock_sim.observability.metrics import metrics
from stock_sim.infra.event_bus import event_bus

__all__ = ["AlertManager"]

class AlertManager:
    def __init__(self, *, thresholds: Optional[Dict[str, Any]] = None, debounce_seconds: int = 60):
        self._lock = RLock()
        self._thresholds: Dict[str, Any] = thresholds.copy() if thresholds else {}
        self._debounce_seconds = debounce_seconds
        self._last_trigger: Dict[str, float] = {}

    # ---------------- Thresholds -----------------
    def update_thresholds(self, **kwargs):
        with self._lock:
            self._thresholds.update(kwargs)

    def get_threshold(self, key: str, default: Any = None):
        with self._lock:
            return self._thresholds.get(key, default)

    # ---------------- Core -----------------------
    def _should_fire(self, kind: str) -> bool:
        now = time.time()
        last = self._last_trigger.get(kind, 0)
        if now - last >= self._debounce_seconds:
            self._last_trigger[kind] = now
            return True
        metrics.inc("alert_suppressed", 1)
        return False

    def _emit(self, kind: str, message: str, data: Dict[str, Any]):
        payload = {
            'type': kind,
            'message': message,
            'data': data,
            'ts': time.time(),
        }
        event_bus.publish('alert.triggered', payload)
        metrics.inc('alert_triggered', 1)
        metrics.inc(f'alert.{kind}', 1)

    # ---------------- Public Checks --------------
    def check_drawdown(self, current_equity: float, peak_equity: float):
        if peak_equity <= 0:
            return False
        thr = self.get_threshold('drawdown_pct')
        if thr is None:
            return False
        drawdown = (peak_equity - current_equity) / peak_equity
        if drawdown >= thr:
            kind = 'drawdown'
            if self._should_fire(kind):
                self._emit(kind, f'Drawdown {drawdown:.2%} >= {thr:.2%}', {
                    'drawdown': drawdown,
                    'threshold': thr,
                    'current_equity': current_equity,
                    'peak_equity': peak_equity,
                })
                return True
        return False

    def check_heartbeat(self, last_heartbeat_ts: float):
        thr_ms = self.get_threshold('heartbeat_ms')
        if thr_ms is None:
            return False
        delta_ms = (time.time() - last_heartbeat_ts) * 1000
        if delta_ms >= thr_ms:
            kind = 'heartbeat_timeout'
            if self._should_fire(kind):
                self._emit(kind, f'Heartbeat silent {int(delta_ms)}ms >= {thr_ms}ms', {
                    'delta_ms': delta_ms,
                    'threshold_ms': thr_ms,
                })
                return True
        return False

    def check_balance(self, balance: float):
        # 可选: 若存在 min_balance 阈值
        thr = self.get_threshold('min_balance')
        if thr is None:
            return False
        if balance < thr:
            kind = 'low_balance'
            if self._should_fire(kind):
                self._emit(kind, f'Balance {balance} < {thr}', {
                    'balance': balance,
                    'threshold': thr,
                })
                return True
        return False

    # 统一入口: 便于批量检查
    def evaluate(self, *, current_equity: Optional[float] = None, peak_equity: Optional[float] = None,
                 last_heartbeat_ts: Optional[float] = None, balance: Optional[float] = None):
        if current_equity is not None and peak_equity is not None:
            self.check_drawdown(current_equity, peak_equity)
        if last_heartbeat_ts is not None:
            self.check_heartbeat(last_heartbeat_ts)
        if balance is not None:
            self.check_balance(balance)

