"""AgentsPanel (Spec Task 26)

职责 (R3):
- 列出智能体 (分页/可扩展)
- 批量创建(仅 Retail / MultiStrategyRetail) 并展示进度 (修订约束)
- 控制 start/pause/stop (委托 AgentController)
- 心跳超时高亮: 运行状态 RUNNING 且 last_heartbeat 距当前 > heartbeat_threshold_ms

设计:
- 纯逻辑, 与 UI 解耦
- 线程安全: RLock
- 批量创建使用后台线程模拟逐个创建以提供进度

视图 get_view() 返回:
{
  'agents': {
      'total': int,
      'items': [ {agent_id,name,type,status,start_time,last_heartbeat,params_version,heartbeat_stale} ]
  },
  'batch': {
      'in_progress': bool,
      'requested': int,
      'created': int,
      'failed': int,
      'type': str|None,
      'error': str|None,
  }
}
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from threading import RLock, Thread
import time

from app.controllers.agent_controller import AgentController
from app.services.agent_service import AgentService, BatchCreateConfig, AgentServiceError, BATCH_ALLOWED_TYPES
from app.core_dto.agent import AgentMetaDTO
# 新增: 通知中心 (可选)
try:  # pragma: no cover
    from app.panels.shared.notifications import notification_center as _shared_notification_center
except Exception:  # pragma: no cover
    _shared_notification_center = None

try:  # metrics 可选
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **kw):
            pass
        def add_timing(self, *a, **kw):
            pass
    metrics = _Dummy()

__all__ = ["AgentsPanel"]

class AgentsPanel:
    def __init__(self, controller: AgentController, service: AgentService, *, heartbeat_threshold_ms: int = 10_000):
        self._ctl = controller
        self._svc = service
        self._lock = RLock()
        self._heartbeat_ms = heartbeat_threshold_ms
        # 分页占位 (当前返回全部)
        self._batch_in_progress = False
        self._batch_requested = 0
        self._batch_created = 0
        self._batch_failed = 0
        self._batch_type: Optional[str] = None
        self._batch_error: Optional[str] = None
        self._batch_thread: Optional[Thread] = None
        # 新增: 已通知心跳超时集合
        self._stale_notified: set[str] = set()
        # 新增: 最近一次 strategies (仅记录，供调试/查看)
        self._batch_strategies: Optional[List[str]] = None
        # 可选：记录最近一次初始资金（仅调试/查看）
        self._batch_initial_cash: Optional[float] = None

    # -------------- 批量创建 --------------
    def start_batch_create(self, *, count: int, agent_type: str, name_prefix: str = "agent", strategies: Optional[List[str]] = None, initial_cash: Optional[float] = None) -> bool:
        with self._lock:
            if self._batch_in_progress:
                return False
            self._batch_in_progress = True
            self._batch_requested = count
            self._batch_created = 0
            self._batch_failed = 0
            self._batch_type = agent_type
            self._batch_error = None
            self._batch_strategies = list(strategies) if strategies else None
            self._batch_initial_cash = float(initial_cash) if initial_cash is not None else None
        t = Thread(target=self._run_batch, args=(count, agent_type, name_prefix, strategies, initial_cash), daemon=True)
        self._batch_thread = t
        t.start()
        return True

    def _run_batch(self, count: int, agent_type: str, name_prefix: str, strategies: Optional[List[str]], initial_cash: Optional[float]):  # noqa: D401
        start = time.perf_counter()
        try:
            # 逐个调用以展示进度
            for i in range(count):
                try:
                    cfg = BatchCreateConfig(count=1, agent_type=agent_type, name_prefix=name_prefix, strategies=strategies, initial_cash=(initial_cash if initial_cash is not None else 100_000.0))
                    self._svc.batch_create_retail(cfg)
                    with self._lock:
                        self._batch_created += 1
                except AgentServiceError as e:  # 捕获不允许类型错误
                    with self._lock:
                        self._batch_error = e.code
                        self._batch_failed += 1
                        # 不可用类型直接终止后续
                        break
                except Exception:  # 其他错误统计 failed
                    with self._lock:
                        self._batch_failed += 1
                # 模拟轻微延迟 (避免测试过快无法看到进度; 可选)
                time.sleep(0.005)
        finally:
            dur_ms = (time.perf_counter() - start) * 1000
            metrics.add_timing("agents_panel_batch_ms", dur_ms)
            with self._lock:
                self._batch_in_progress = False

    # -------------- 控制 --------------
    def control(self, agent_id: str, action: str) -> AgentMetaDTO:
        ag = self._ctl.control(agent_id, action)  # action 校验由 service 完成
        return ag

    # -------------- 视图 --------------
    def get_view(self) -> Dict[str, Any]:
        agents = self._ctl.list_agents()
        now_ms = int(time.time()*1000)
        items = [self._agent_view(a, now_ms) for a in agents]
        with self._lock:
            batch = {
                'in_progress': self._batch_in_progress,
                'requested': self._batch_requested,
                'created': self._batch_created,
                'failed': self._batch_failed,
                'type': self._batch_type,
                'error': self._batch_error,
                'strategies': list(self._batch_strategies) if self._batch_strategies else None,  # 新增
                'initial_cash': self._batch_initial_cash,
            }
        return {
            'agents': {
                'total': len(items),
                'items': items,
            },
            'batch': batch,
        }

    # -------------- 辅助 --------------
    def _agent_view(self, a: AgentMetaDTO, now_ms: int) -> Dict[str, Any]:
        lhb = a.last_heartbeat
        stale = False
        if a.status == 'RUNNING':
            if lhb is None:
                stale = True
            else:
                stale = (now_ms - lhb) > self._heartbeat_ms
        if stale:
            self._notify_stale_once(a.agent_id)
        return {
            'agent_id': a.agent_id,
            'name': a.name,
            'type': a.type,
            'status': a.status,
            'start_time': a.start_time,
            'last_heartbeat': a.last_heartbeat,
            'params_version': a.params_version,
            'heartbeat_stale': stale,
        }

    def _notify_stale_once(self, agent_id: str):  # 去重通知
        try:
            if _shared_notification_center is None:
                return
            # 简单 O(1) 去重; 不考虑恢复后再次触发 (需求: 首次过渡)
            if agent_id in self._stale_notified:
                return
            self._stale_notified.add(agent_id)
            _shared_notification_center.publish(
                'alert',
                'agent.heartbeat.stale',
                f'Agent {agent_id} heartbeat stale',
                data={'agent_id': agent_id},
            )
        except Exception:  # pragma: no cover
            pass

    # -------------- 配置 --------------
    def set_heartbeat_threshold(self, ms: int):
        if ms > 0:
            with self._lock:
                self._heartbeat_ms = ms

    def tail_logs(self, agent_id: str, n: int = 100):  # UI 适配器调用 (R18)
        try:
            return self._svc.tail_logs(agent_id, n)
        except Exception:
            return []
