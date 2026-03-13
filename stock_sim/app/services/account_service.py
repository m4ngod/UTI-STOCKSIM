"""AccountService (Spec Task 9)

目标 (对应 R1 AC1/2/3):
- 拉取账户/持仓 (switch / 初次加载) -> AC3 支持账户切换 <300ms (服务层提供快速同步接口)
- 提供一致性校验: 若 5s 内无 ACCOUNT_UPDATED 事件, 外部调用 check_consistency() 拉取后端最新并对比净值差异; 差异 >0.5% (默认阈值) 记录告警/指标 (AC2)
- 事件驱动刷新 (<200ms) 主要由 EventBridge + Controller 完成 (AC1), 服务仅提供拉取函数

实现要点:
1. 可注入 fetcher 后端函数, 默认使用 _synthetic_fetcher 生成确定性数据, 便于测试 (无 IO)
2. diff 计算: |remote.equity - local.equity| / max(remote.equity, 1.0)
3. 阈值 diff > diff_threshold -> metrics.inc("account_consistency_violation") 并返回 exceeded=True
4. 统一返回 AccountDTO, 不在此层做分页; 面板分页由 Controller/Panel 层处理
5. 账户切换: load_account(account_id) 即可; 若已有缓存可直接返回 (简单缓存 last_account)

未来扩展 (TODO):
- TODO: 对接真实后端 RPC/REST 客户端
- TODO: 增量持仓 diff 提供 (position level changes)
- TODO: 账户多币种支持 (扩展 equity/cash 字段结构)

"""
from __future__ import annotations
from typing import Callable, Tuple, Optional, List
import time
import math
import threading

from observability.metrics import metrics
from app.core_dto.account import AccountDTO, PositionDTO

# ---------------- Fetcher 协议 ----------------
Fetcher = Callable[[str], AccountDTO]

class AccountService:
    """账户数据拉取与一致性校验服务.

    公共方法:
    - load_account(account_id) -> AccountDTO: 切换/初次加载
    - check_consistency(local: AccountDTO) -> (remote, diff_ratio, exceeded)
    - get_cached() -> Optional[AccountDTO]
    """
    def __init__(self, *, fetcher: Optional[Fetcher] = None, diff_threshold: float = 0.005):
        self._fetcher: Fetcher = fetcher or _synthetic_fetcher
        self._diff_threshold = diff_threshold
        self._last_account: Optional[AccountDTO] = None
        self._lock = threading.RLock()

    # ---------------- Public API ----------------
    def load_account(self, account_id: str) -> AccountDTO:
        start = time.perf_counter()
        acc = self._fetcher(account_id)
        with self._lock:
            self._last_account = acc
        dur_ms = (time.perf_counter() - start) * 1000
        metrics.add_timing("account_load_ms", dur_ms)
        return acc

    def get_cached(self) -> Optional[AccountDTO]:
        with self._lock:
            return self._last_account

    def check_consistency(self, local: AccountDTO) -> Tuple[AccountDTO, float, bool]:
        """拉取最新远端账户并与本地快照对比净值差异.
        返回: (remote_account, diff_ratio, exceeded)
        diff_ratio = abs(remote.equity-local.equity)/max(remote.equity,1)
        exceeded 为 True 表示超过阈值 (记录 metrics & 供上层触发告警)
        """
        remote = self._fetcher(local.account_id)
        diff_ratio = abs(remote.equity - local.equity) / max(remote.equity, 1.0)
        exceeded = diff_ratio > self._diff_threshold
        if exceeded:
            metrics.inc("account_consistency_violation")
        metrics.add_timing("account_consistency_diff", diff_ratio * 100)  # 记录为百分比值
        with self._lock:
            # 始终更新缓存为最新远端 (避免后续重复大差异警告)
            self._last_account = remote
        return remote, diff_ratio, exceeded

# ---------------- Synthetic Fetcher (Deterministic, No IO) ----------------

def _synthetic_fetcher(account_id: str) -> AccountDTO:
    """生成确定性伪账户数据.

    逻辑:
    - hash(account_id) 生成基数
    - 3~5 个持仓, 数量 & 价格伪随机
    - equity = cash + sum( position.qty * (avg_price * 波动因子) ) + unrealized_pnl
    - utilization = min( (equity-cash)/max(equity,1), 1 ) 近似
    该函数仅用于前端阶段未接后端时的测试/占位.
    """
    h = abs(hash(account_id)) % 10_000
    base_cash = 100_000 + (h % 5_000)
    # 生成持仓数量
    rng_seed = h or 1
    symbols = [f"SYM{(rng_seed + i) % 97:02d}" for i in range(1, (rng_seed % 3) + 4)]  # 3~5 个
    positions: List[PositionDTO] = []
    total_mv = 0.0
    unreal_total = 0.0
    for i, sym in enumerate(symbols):
        qty = (rng_seed % (50 + i * 10) + 10) * 10
        avg_price = 10 + ((rng_seed // (i + 1)) % 500) / 10.0
        borrowed = (i % 2) * (qty // 5)
        # 简单波动: sin + cos 基于 i/h
        factor = 1 + math.sin((h % 360) / 57.0 + i) * 0.01 + math.cos(i) * 0.005
        market_price = avg_price * factor
        unreal = (market_price - avg_price) * qty
        unreal_total += unreal
        total_mv += market_price * qty
        positions.append(PositionDTO(
            symbol=sym,
            quantity=qty,
            frozen_qty=0,
            avg_price=avg_price,
            borrowed_qty=borrowed,
            pnl_unreal=unreal,
        ))
    equity = base_cash + unreal_total + total_mv * 0.0  # 不重复加市值, 仅添加浮动盈亏到现金形成 equity 近似
    # 若需要更真实, 可定义 equity = base_cash + total_mv 但需同步 pnl 逻辑
    utilization = min(max((equity - base_cash) / max(equity, 1.0), 0.0), 1.0)
    snapshot_id = f"acc-{account_id}-{int(time.time()*1000)}"
    sim_day = time.strftime("%Y-%m-%d")
    return AccountDTO(
        account_id=account_id,
        cash=base_cash,
        frozen_cash=0.0,
        positions=positions,
        realized_pnl=0.0,
        unrealized_pnl=unreal_total,
        equity=equity,
        utilization=utilization,
        snapshot_id=snapshot_id,
        sim_day=sim_day,
    )

__all__ = [
    "AccountService",
    "_synthetic_fetcher",
]

