"""Leaderboard service for frontend ranking views."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple
import math
import random
import time
from threading import RLock

from observability.metrics import metrics
from app.core_dto.leaderboard import LeaderboardRowDTO

if TYPE_CHECKING:
    from app.runtime_gateway import RuntimeGateway

VALID_WINDOWS = {"1d", "7d", "30d", "90d", "ytd", "all"}

_WINDOW_DAYS = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "ytd": 200,
    "all": 365,
}


class LeaderboardServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LeaderboardService:
    def __init__(
        self,
        *,
        ttl_seconds: float = 3.0,
        agent_count: int = 30,
        use_runtime: bool = False,
        runtime_gateway: RuntimeGateway | None = None,
    ):
        self._ttl_ms = int(ttl_seconds * 1000)
        self._agent_count = agent_count
        self._use_runtime = use_runtime
        if runtime_gateway is None:
            from app.runtime_gateway import RuntimeGateway

            runtime_gateway = RuntimeGateway()
        self._runtime_gateway = runtime_gateway
        self._cache: Dict[str, Tuple[int, List[LeaderboardRowDTO]]] = {}
        self._prev_ranks: Dict[str, Dict[str, int]] = {}
        self._prev_order: Dict[str, Dict[str, int]] = {}
        self._refresh_counter: Dict[str, int] = {w: 0 for w in VALID_WINDOWS}
        self._lock = RLock()

    def get_leaderboard(self, window: str, limit: int = 50, *, force_refresh: bool = False) -> List[LeaderboardRowDTO]:
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
                return ts_rows[1][:limit]
            metrics.inc("leaderboard_cache_miss")
            t0 = time.perf_counter()
            rows = self._build_rows(window)
            prev_ranks = self._prev_ranks.get(window, {})
            prev_order = self._prev_order.get(window, {})
            rows.sort(key=lambda r: (-r.return_pct, prev_order.get(r.agent_id, math.inf), r.agent_id))
            new_prev_order: Dict[str, int] = {}
            new_prev_ranks: Dict[str, int] = {}
            for idx, row in enumerate(rows, start=1):
                old_rank = prev_ranks.get(row.agent_id)
                row.rank = idx  # type: ignore[assignment]
                if old_rank is not None:
                    row.rank_delta = old_rank - idx
                new_prev_ranks[row.agent_id] = idx
                new_prev_order[row.agent_id] = idx
            self._cache[window] = (now_ms, rows)
            self._prev_ranks[window] = new_prev_ranks
            self._prev_order[window] = new_prev_order
            metrics.add_timing("leaderboard_build_ms", (time.perf_counter() - t0) * 1000)
            return rows[:limit]

    def _build_rows(self, window: str) -> List[LeaderboardRowDTO]:
        runtime_rows = self._build_runtime_rows(window)
        if runtime_rows is not None:
            return runtime_rows
        c = self._refresh_counter[window]
        self._refresh_counter[window] += 1
        base_seed = hash((window, self._agent_count)) & 0xFFFF_FFFF
        rng = random.Random(base_seed + c)
        rows: List[LeaderboardRowDTO] = []
        window_scale = {
            "1d": 0.02,
            "7d": 0.05,
            "30d": 0.15,
            "90d": 0.30,
            "ytd": 0.60,
            "all": 1.00,
        }[window]
        days = _WINDOW_DAYS[window]
        for i in range(self._agent_count):
            agent_id = f"agt-{i:03d}"
            ret = rng.uniform(-0.2, 1.0) * window_scale
            annualized = ret * (365 / max(days, 1))
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
                    rank=1,
                )
            )
        return rows

    def _build_runtime_rows(self, window: str) -> List[LeaderboardRowDTO] | None:
        if not self._use_runtime:
            return None
        try:
            snapshots = self._runtime_gateway.list_leaderboard_snapshots()
        except Exception:
            return []
        if not snapshots:
            return []
        annual_factor = 365 / max(_WINDOW_DAYS[window], 1)
        rows: List[LeaderboardRowDTO] = []
        for snap in snapshots:
            equity = float(snap.get("equity", 0.0) or 0.0)
            gross_exposure = float(snap.get("gross_exposure", 0.0) or 0.0)
            long_count = int(snap.get("long_count", 0) or 0)
            short_count = int(snap.get("short_count", 0) or 0)
            initial_cash = max(float(snap.get("initial_cash", 100_000.0) or 100_000.0), 1.0)
            return_pct = (equity - initial_cash) / initial_cash
            position_count = long_count + short_count
            win_rate = (long_count / position_count) if position_count else None
            utilization = gross_exposure / max(equity, 1.0) if equity else 0.0
            max_drawdown = min(0.95, utilization * 0.15) if utilization > 0 else 0.0
            sharpe = return_pct / max(0.02, utilization) if utilization > 0 else None
            rows.append(
                LeaderboardRowDTO(
                    agent_id=str(snap.get("agent_id", "")),
                    return_pct=return_pct,
                    annualized=return_pct * annual_factor,
                    sharpe=sharpe,
                    max_drawdown=max_drawdown,
                    win_rate=win_rate,
                    equity=equity,
                    rank=1,
                )
            )
        return rows

    def get_agent_curves(self, agent_id: str, window: str, *, points: int = 50) -> Dict[str, object] | None:
        if self._use_runtime:
            try:
                runtime_curves = self._runtime_gateway.get_leaderboard_history(agent_id, window=window, points=points)
            except Exception:
                runtime_curves = None
            if runtime_curves is not None:
                equity_curve = list(runtime_curves.get("equity_curve") or [])
                drawdown_curve = list(runtime_curves.get("drawdown_curve") or [])
                if equity_curve:
                    return {
                        "agent_id": agent_id,
                        "equity_curve": equity_curve,
                        "drawdown_curve": drawdown_curve,
                        "source": runtime_curves.get("source") or "runtime-account-equity-snapshots",
                        "authoritative": bool(runtime_curves.get("authoritative", True)),
                        "active_run_id": runtime_curves.get("active_run_id"),
                    }
        row = None
        with self._lock:
            cached = self._cache.get(window)
            if cached:
                for candidate in cached[1]:
                    if candidate.agent_id == agent_id:
                        row = candidate
                        break
        if row is None:
            return None
        return {
            "agent_id": agent_id,
            "equity_curve": _synthetic_equity_curve(row, points=points),
            "drawdown_curve": _synthetic_drawdown_curve(row, points=points),
            "source": "synthetic-leaderboard-placeholder",
            "authoritative": False,
            "active_run_id": None,
        }


def _synthetic_equity_curve(row: LeaderboardRowDTO, points: int = 50) -> List[float]:
    target = 1 + row.return_pct
    pts: List[float] = []
    if points <= 1:
        return [target]
    for i in range(points):
        x = i / (points - 1)
        if row.return_pct >= 0:
            val = 1 + (target - 1) * x
        else:
            mid = 1 + 0.3 * row.return_pct
            if x < 0.3:
                val = 1 + (mid - 1) * (x / 0.3)
            else:
                val = mid + (target - mid) * ((x - 0.3) / 0.7)
        pts.append(val)
    return pts


def _synthetic_drawdown_curve(row: LeaderboardRowDTO, points: int = 50) -> List[float]:
    md = abs(row.max_drawdown or 0.0)
    if points <= 1 or md == 0:
        return [0.0]
    out: List[float] = []
    for i in range(points):
        x = i / (points - 1)
        val = -md * (math.sin(math.pi * x) ** 2)
        out.append(val)
    return out


__all__ = [
    "LeaderboardService",
    "LeaderboardServiceError",
    "VALID_WINDOWS",
]
