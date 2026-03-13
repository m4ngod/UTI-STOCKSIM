"""LeaderboardService (Spec Task 11)

职责 (R4 AC1/2/3/4/5/6):
- get_leaderboard(window, limit, force_refresh): 构造时间窗口参数 / 排名 / rank_delta
- 排序稳定: 相同收益率(return_pct) 保持上一轮顺序 (避免 UI 抖动)
- rank_delta: 旧排名 - 新排名 (正数=上升, 负数=下降)
- 缓存: 窗口级别 TTL (默认 3s) + metrics 统计 cache_hit / miss
- 指标: leaderboard_get, leaderboard_cache_hit, leaderboard_cache_miss, leaderboard_build_ms
- 未来扩展: TODO 对接真实后端 RPC 获取统计; TODO 增加更多风险指标 (Sortino, Calmar)

实现策略:
- 纯内存 + 线程安全 RLock
- Synthetic 数据: 基于 agent 数量(默认30)生成 deterministic baseline + refresh jitter
- 稳定排序: 使用上一轮 index 作为次级排序 key
- rank_delta 计算: 第二次(含)以后刷新才有值; 新出现 agent rank_delta=None

Edge Cases:
- limit<=0 返回 []
- 未知 window 抛 AgentServiceError 风格统一 LeaderboardServiceError('INVALID_WINDOW')
- force_refresh=True 忽略 TTL
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import time
import random
import math
from threading import RLock

from observability.metrics import metrics
from app.core_dto.leaderboard import LeaderboardRowDTO

VALID_WINDOWS = {"1d", "7d", "30d", "90d", "ytd", "all"}

class LeaderboardServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

class LeaderboardService:
    def __init__(self, *, ttl_seconds: float = 3.0, agent_count: int = 30):
        self._ttl_ms = int(ttl_seconds * 1000)
        self._agent_count = agent_count
        self._cache: Dict[str, Tuple[int, List[LeaderboardRowDTO]]] = {}
        self._prev_ranks: Dict[str, Dict[str, int]] = {}
        self._prev_order: Dict[str, Dict[str, int]] = {}
        self._refresh_counter: Dict[str, int] = {w: 0 for w in VALID_WINDOWS}
        self._lock = RLock()

    # ------------- Public API -------------
    def get_leaderboard(self, window: str, limit: int = 50, *, force_refresh: bool = False) -> List[LeaderboardRowDTO]:
        """获取排行榜.
        window: 时间窗口 (1d/7d/30d/90d/ytd/all)
        limit: 返回前 N 条
        force_refresh: True 时无视 TTL 重建
        """
        if limit <= 0:
            return []
        if window not in VALID_WINDOWS:
            raise LeaderboardServiceError("INVALID_WINDOW", f"unsupported window: {window}")
        metrics.inc("leaderboard_get")
        now_ms = int(time.time() * 1000)
        with self._lock:
            ts_rows = self._cache.get(window)
            if (not force_refresh) and ts_rows and (now_ms - ts_rows[0] < self._ttl_ms):
                metrics.inc("leaderboard_cache_hit")
                # 返回缓存 (切片保证 limit)
                return ts_rows[1][:limit]
            metrics.inc("leaderboard_cache_miss")
            t0 = time.perf_counter()
            rows = self._build_rows(window)
            # 排序 & rank & rank_delta
            prev_ranks = self._prev_ranks.get(window, {})
            prev_order = self._prev_order.get(window, {})
            # 稳定排序: return_pct 降序, prev_index 升序, agent_id 升序
            rows.sort(key=lambda r: (-r.return_pct, prev_order.get(r.agent_id, math.inf), r.agent_id))
            new_prev_order: Dict[str, int] = {}
            new_prev_ranks: Dict[str, int] = {}
            for idx, row in enumerate(rows, start=1):
                old_rank = prev_ranks.get(row.agent_id)
                row.rank = idx  # type: ignore[assignment]
                if old_rank is not None:
                    row.rank_delta = old_rank - idx
                # 新出现 row.rank_delta 维持 None
                new_prev_ranks[row.agent_id] = idx
                new_prev_order[row.agent_id] = idx  # 顺序 index
            # 更新缓存&状态
            self._cache[window] = (now_ms, rows)
            self._prev_ranks[window] = new_prev_ranks
            self._prev_order[window] = new_prev_order
            elapsed_ms = (time.perf_counter() - t0) * 1000
            metrics.add_timing("leaderboard_build_ms", elapsed_ms)
            return rows[:limit]

    # ------------- Internal -------------
    def _build_rows(self, window: str) -> List[LeaderboardRowDTO]:
        # refresh 计数保证 jitter 变化
        c = self._refresh_counter[window]
        self._refresh_counter[window] += 1
        base_seed = hash((window, self._agent_count)) & 0xFFFF_FFFF
        rng = random.Random(base_seed + c)
        rows: List[LeaderboardRowDTO] = []
        # 基础收益率区间随 window 放大
        window_scale = {
            "1d": 0.02,
            "7d": 0.05,
            "30d": 0.15,
            "90d": 0.30,
            "ytd": 0.60,
            "all": 1.00,
        }[window]
        for i in range(self._agent_count):
            agent_id = f"agt-{i:03d}"
            ret = rng.uniform(-0.2, 1.0) * window_scale  # return_pct (0~scale with negatives)
            # annualized 粗略: return_pct * (365/天窗口估算)，防止除 0
            days = {
                "1d": 1,
                "7d": 7,
                "30d": 30,
                "90d": 90,
                "ytd": 200,
                "all": 365,
            }[window]
            annualized = ret * (365 / max(days, 1))
            # sharpe 简化: ret / (vol ~ random) 避免 0
            vol = rng.uniform(0.05, 0.30)
            sharpe = ret / vol if vol else None
            max_dd = abs(rng.uniform(0.01, 0.35))
            win_rate = rng.uniform(0.3, 0.9)
            equity = 100_000 * (1 + ret)
            rows.append(
                LeaderboardRowDTO(
                    agent_id=agent_id,
                    return_pct=ret,
                    annualized=annualized,
                    sharpe=sharpe,
                    max_drawdown=max_dd,
                    win_rate=win_rate,
                    equity=equity,
                    rank=1,  # placeholder, 会被重写
                )
            )
        return rows

__all__ = [
    "LeaderboardService",
    "LeaderboardServiceError",
    "VALID_WINDOWS",
]

