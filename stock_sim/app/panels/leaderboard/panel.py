"""LeaderboardPanel (Spec Task 27)

职责 (R4,R10):
- 选择时间窗口(window) 获取排行榜列表 (调用 LeaderboardController.refresh)
- 支持再次刷新以获得 rank_delta 变化
- 行选择: 生成收益曲线 & 回撤曲线占位 (无真实历史 -> 依据 return_pct & max_drawdown 合成)
- 导出当前窗口排行榜 (调用 LeaderboardController.export)
- 排序: 基于当前缓存 rows 在面板层二次排序 (return_pct / sharpe / equity / rank)

视图结构 get_view():
{
  'window': str,
  'windows': [...可选窗口...],
  'sort_by': str,
  'rows': [ {agent_id, rank, rank_delta, return_pct, sharpe, max_drawdown, win_rate, equity} ],
  'selected': {
      'agent_id': str,
      'equity_curve': [float],
      'drawdown_curve': [float],
  } | None,
  'last_refresh_ts': epoch_ms,
}

曲线合成策略(占位):
- equity_curve: N=50, 线性递增到 (1+return_pct), 若 return_pct<0 则先小幅上升再下降。
- drawdown_curve: 使用 max_drawdown 绝对值构造一个平滑下探后回升到 0 的曲线。

扩展 TODO:
- TODO: 接入真实历史收益序列
- TODO: 支持前端增量 push 排名变化
- TODO: 指标更多列配置化
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from threading import RLock
import time
import math

from app.controllers.leaderboard_controller import LeaderboardController
from app.core_dto.leaderboard import LeaderboardRowDTO

__all__ = ["LeaderboardPanel"]

_VALID_SORT = {"rank", "return_pct", "sharpe", "equity"}
_DEFAULT_WINDOW = "1d"

class LeaderboardPanel:
    def __init__(self, controller: LeaderboardController, *, default_window: str = _DEFAULT_WINDOW, limit: int = 50):
        self._ctl = controller
        self._lock = RLock()
        self._window = default_window
        self._limit = limit
        self._sort_by = "rank"
        self._rows_cache: List[LeaderboardRowDTO] = []
        self._selected_agent: Optional[str] = None
        self._last_refresh_ts: int = 0
        # 初次加载
        self.refresh(force=True)

    # ------------- Public API -------------
    def set_window(self, window: str):  # R4 AC2
        if window not in self._ctl.windows():
            raise ValueError(f"unsupported window: {window}")
        with self._lock:
            if self._window != window:
                self._window = window
                self._selected_agent = None
        self.refresh(force=True)

    def set_sort(self, sort_by: str):
        if sort_by in _VALID_SORT:
            with self._lock:
                self._sort_by = sort_by

    def refresh(self, force: bool = False):  # R4 AC1/4
        rows = self._ctl.refresh(self._window, limit=self._limit, force_refresh=force)
        with self._lock:
            self._rows_cache = rows
            self._last_refresh_ts = int(time.time()*1000)
        # 若没有选中则默认选排名第一 (如存在)
        if not self._selected_agent and rows:
            self._selected_agent = rows[0].agent_id

    def select(self, agent_id: str):  # 行选择
        with self._lock:
            self._selected_agent = agent_id

    def export(self, fmt: str = "csv") -> str:  # R10 AC1/2/3
        path = self._ctl.export(self._window, fmt, limit=self._limit)
        return path

    def get_view(self) -> Dict[str, Any]:  # R4 AC3/5/6
        with self._lock:
            window = self._window
            sort_by = self._sort_by
            rows = list(self._rows_cache)
            selected_id = self._selected_agent
            last_ts = self._last_refresh_ts
        # 排序 (复制)
        def sort_key(r: LeaderboardRowDTO):
            if sort_by == "return_pct":
                return (-r.return_pct, r.rank)
            if sort_by == "sharpe":
                return (-(r.sharpe or -9999), r.rank)
            if sort_by == "equity":
                return (-(r.equity or 0), r.rank)
            return (r.rank,)
        rows_sorted = sorted(rows, key=sort_key)
        view_rows: List[Dict[str, Any]] = [self._row_view(r) for r in rows_sorted]
        selected_block = None
        if selected_id:
            r = next((x for x in rows if x.agent_id == selected_id), None)
            if r:
                selected_block = {
                    'agent_id': r.agent_id,
                    'equity_curve': self._equity_curve(r),
                    'drawdown_curve': self._drawdown_curve(r),
                }
        return {
            'window': window,
            'windows': self._ctl.windows(),
            'sort_by': sort_by,
            'rows': view_rows,
            'selected': selected_block,
            'last_refresh_ts': last_ts,
        }

    # ------------- Helpers -------------
    @staticmethod
    def _row_view(r: LeaderboardRowDTO) -> Dict[str, Any]:
        return {
            'agent_id': r.agent_id,
            'rank': r.rank,
            'rank_delta': r.rank_delta,
            'return_pct': r.return_pct,
            'sharpe': r.sharpe,
            'max_drawdown': r.max_drawdown,
            'win_rate': r.win_rate,
            'equity': r.equity,
        }

    @staticmethod
    def _equity_curve(r: LeaderboardRowDTO, points: int = 50) -> List[float]:
        target = 1 + r.return_pct
        pts: List[float] = []
        if points <= 1:
            return [target]
        for i in range(points):
            x = i / (points - 1)
            if r.return_pct >= 0:
                val = 1 + (target - 1) * x  # 线性增长
            else:
                # 先小幅上升到 1 + 0.3*return_pct 然后下降到 target
                mid = 1 + 0.3 * r.return_pct
                if x < 0.3:
                    val = 1 + (mid - 1) * (x / 0.3)
                else:
                    val = mid + (target - mid) * ((x - 0.3)/(0.7))
            pts.append(val)
        return pts

    @staticmethod
    def _drawdown_curve(r: LeaderboardRowDTO, points: int = 50) -> List[float]:
        # 使用最大回撤构造一个平滑下探曲线 (负值表示回撤)
        md = abs(r.max_drawdown or 0.0)
        if points <= 1 or md == 0:
            return [0.0]
        out: List[float] = []
        for i in range(points):
            x = i / (points - 1)
            # 使用一个 sin^2 形状下探再回升: -md * sin(pi*x)^2
            val = -md * (math.sin(math.pi * x) ** 2)
            out.append(val)
        return out


