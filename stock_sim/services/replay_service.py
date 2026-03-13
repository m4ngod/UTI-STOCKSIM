from __future__ import annotations
"""最小回放服务 (platform-hardening Task4/Task15 需求的简化版本)

功能:
- load_events(start_ts=None, end_ts=None, limit=None) -> list[dict]
- replay(apply_fn, start_ts=None, end_ts=None, limit=None) -> int  (将事件 payload 传给回调)

当前仅用于测试: 只读取 event_log 表, 不做幂等/排序修正以外的复杂逻辑。
"""
import json
from typing import Callable, Iterable, List, Dict, Any, Optional

try:  # 优先包内导入
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
except Exception:  # 源码根目录运行
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore

class ReplayService:
    def load_events(self, start_ts: int | None = None, end_ts: int | None = None, limit: int | None = None) -> List[Dict[str, Any]]:
        s = SessionLocal()
        try:
            q = s.query(EventLog)
            if start_ts is not None:
                q = q.filter(EventLog.ts_ms >= start_ts)
            if end_ts is not None:
                q = q.filter(EventLog.ts_ms <= end_ts)
            q = q.order_by(EventLog.ts_ms.asc(), EventLog.id.asc())
            if limit is not None:
                q = q.limit(limit)
            rows = q.all()
            out: List[Dict[str, Any]] = []
            for r in rows:
                try:
                    payload = json.loads(r.payload) if r.payload else {}
                except Exception:
                    payload = {"_raw": r.payload}
                out.append({
                    'id': r.id,
                    'ts_ms': r.ts_ms,
                    'type': r.type,
                    'symbol': r.symbol,
                    'payload': payload
                })
            return out
        finally:
            s.close()

    def replay(self, apply_fn: Callable[[Dict[str, Any]], None], start_ts: int | None = None,
               end_ts: int | None = None, limit: int | None = None) -> int:
        events = self.load_events(start_ts=start_ts, end_ts=end_ts, limit=limit)
        for ev in events:
            try:
                apply_fn(ev)
            except Exception:  # 测试环境忽略
                pass
        return len(events)

replay_service = ReplayService()

__all__ = ["ReplayService", "replay_service"]
