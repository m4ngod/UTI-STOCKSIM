"""LeaderboardController (Spec Task 22)

职责 (R4,R10):
- 封装 LeaderboardService 刷新/缓存逻辑统一入口
- 提供 refresh(window, limit, force_refresh=False) 获取排行榜 (含 rank_delta)
- 提供 export(window, fmt, path=None) 调用 ExportService 导出当前窗口排行榜
- 支持 windows() 列出可选时间窗口 (供 UI 下拉)

设计 & 线程安全:
- 读写加 RLock, 缓存最近一次窗口数据 (用于 export 若未 refresh 会自动 refresh)
- Export 复用 service 生成的数据 (保持 rank/rank_delta 一致)

扩展 TODO:
- TODO: 对接真实后端 RPC 获取排行榜
- TODO: 导出附带更多风险指标 (Sortino, Calmar)
- TODO: Kafka/Streaming push 增量刷新

Future Hooks (Task50):
- TODO: Kafka 推送排行榜增量 (LEADERBOARD_DELTA -> kafka topic leaderboard.delta)
- TODO: RL 绩效联动 (接入 RL stats 追加列 reward_mean)
- TODO: 订阅型推送 (WebSocket) 降低轮询
- TODO: 导出支持 Parquet/Feather 格式
"""
from __future__ import annotations
from typing import List, Dict, Optional
from threading import RLock

from app.services.leaderboard_service import LeaderboardService, LeaderboardServiceError, VALID_WINDOWS
from app.core_dto.leaderboard import LeaderboardRowDTO
from app.services.export_service import ExportService, ExportServiceError
from observability.metrics import metrics

__all__ = ["LeaderboardController"]

class LeaderboardController:
    def __init__(self, service: LeaderboardService, export_service: Optional[ExportService] = None):
        self._service = service
        self._export = export_service or ExportService()
        self._lock = RLock()
        self._cache: Dict[str, List[LeaderboardRowDTO]] = {}  # window -> rows (最新)

    # ---------------- Public API ----------------
    def refresh(self, window: str, *, limit: int = 50, force_refresh: bool = False) -> List[LeaderboardRowDTO]:  # R4 AC1/2/3/4/5/6
        rows = self._service.get_leaderboard(window, limit, force_refresh=force_refresh)
        with self._lock:
            # 存完整 rows (service 已按 limit 切片) —— 直接存返回值即可
            self._cache[window] = rows
        return rows

    def windows(self) -> List[str]:  # 供 UI 构建下拉
        return sorted(list(VALID_WINDOWS))

    def export(self, window: str, fmt: str, *, limit: int = 50, file_path: str | None = None, force_refresh: bool = False) -> str:  # R10 AC1/2/3/4
        # 确保有数据
        with self._lock:
            rows = self._cache.get(window)
        if rows is None or force_refresh:
            rows = self.refresh(window, limit=limit, force_refresh=force_refresh)
        # 组装 meta
        meta = {"window": window, "rows": len(rows)}
        try:
            # ExportService 会自动赋 snapshot_id
            path = self._export.export(fmt, rows, meta, file_path=file_path)
            metrics.inc("leaderboard_controller_export_success")
            return path
        except ExportServiceError:
            metrics.inc("leaderboard_controller_export_failure")
            raise

    def get_cached(self, window: str) -> Optional[List[LeaderboardRowDTO]]:
        with self._lock:
            return self._cache.get(window)
