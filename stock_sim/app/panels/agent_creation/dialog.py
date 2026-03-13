"""AgentCreationDialog (Spec Task 30)

职责:
- 提供批量创建 (仅允许 Retail / MultiStrategyRetail) 的一次性提交逻辑
- 利用 AgentCreationController.batch_create
- 暴露最近一次提交结果 (success_ids/failed) 与错误码 (AGENT_BATCH_UNSUPPORTED 等)
- 新增: R2-UI 进度与取消 (UI 非阻塞):
  - set_batch_params(count, initial_cash, strategy, seed, name_prefix)
  - start_batch(agent_type) 后台线程执行 controller.batch_create
  - cancel(): 提出取消请求 (当前阶段仅 UI 层标记; T5 将在控制器层实现真正取消/进度流)

与 AgentsPanel 区别:
- AgentsPanel 支持进度/逐个创建线程; Dialog 这里是一次性提交 (模拟表单确认)

get_view() 结构:
{
  'last_result': {'success_ids': [...], 'failed': [...] } | None,
  'last_error': str | None,
  'submitted': int,
  'agent_type': str | None,
  'progress': {
      'mode': 'indeterminate' | 'determinate',
      'current': int | None,
      'total': int | None,
      'started_ts': float | None,
      'completed_ts': float | None,
      'cancel_requested': bool,
      'running': bool,
  },
  'params': {
      'count': int,
      'initial_cash': float,
      'strategy': str | None,
      'seed': int | None,
      'name_prefix': str,
  },
  'errors': { field: code },
}
"""
from __future__ import annotations
from threading import RLock, Thread
from typing import Any, Dict, Optional
import time

from app.controllers.agent_creation_controller import AgentCreationController
from app.services.agent_service import AgentServiceError

try:  # metrics 可选
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **kw):
            pass
    metrics = _Dummy()

__all__ = ["AgentCreationDialog", "register_agent_creation_dialog"]

class AgentCreationDialog:
    def __init__(self, controller: AgentCreationController):
        self._ctl = controller
        self._lock = RLock()
        self._last_result: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None
        self._submitted: int = 0
        self._agent_type: Optional[str] = None
        # ---- R2: 批量参数/进度/取消 ----
        self._params = {
            'count': 1,
            'initial_cash': 100_000.0,
            'strategy': None,
            'seed': None,
            'name_prefix': 'agent',
        }
        self._progress = {
            'mode': 'indeterminate',  # 当前阶段无真实进度, 采用不定进度
            'current': 0,
            'total': 0,
            'started_ts': 0.0,
            'completed_ts': 0.0,
            'cancel_requested': False,
            'running': False,
        }
        self._errors: Dict[str, str] = {}
        self._worker: Optional[Thread] = None

    # ---------------- 旧的一次性提交 API (保留兼容) ----------------
    def submit(self, *, agent_type: str, count: int, name_prefix: str = "agent") -> bool:
        with self._lock:
            self._last_result = None
            self._last_error = None
            self._submitted = count
            self._agent_type = agent_type
        try:
            res = self._ctl.batch_create(agent_type=agent_type, count=count, name_prefix=name_prefix)
            with self._lock:
                self._last_result = res
            metrics.inc('agent_creation_dialog_submit')
            return True
        except AgentServiceError as e:
            with self._lock:
                self._last_error = e.code
            metrics.inc('agent_creation_dialog_error')
            return False
        except Exception:  # noqa: BLE001
            with self._lock:
                self._last_error = 'UNKNOWN'
            metrics.inc('agent_creation_dialog_error')
            return False

    # ---------------- R2: 参数设置/进度/取消 ----------------
    def set_batch_params(self, *, count: Optional[int] = None, initial_cash: Optional[float] = None,
                         strategy: Optional[str] = None, seed: Optional[int] = None,
                         name_prefix: Optional[str] = None):
        with self._lock:
            # 更新
            if count is not None:
                self._params['count'] = count
            if initial_cash is not None:
                self._params['initial_cash'] = float(initial_cash)
            if strategy is not None:
                self._params['strategy'] = strategy
            if seed is not None:
                self._params['seed'] = seed
            if name_prefix is not None:
                self._params['name_prefix'] = name_prefix.strip() or 'agent'
            # 校验
            self._errors.clear()
            c = self._params['count']
            if not isinstance(c, int) or c < 1 or c > 1000:
                self._errors['count'] = 'ERR_COUNT_RANGE'  # 1..1000
            if not self._params['name_prefix']:
                self._errors['name_prefix'] = 'ERR_NAME_PREFIX_EMPTY'
            # 其它字段保留为 UI 展示, 暂不在控制器层使用 (T5 实现)

    def start_batch(self, *, agent_type: str) -> bool:
        with self._lock:
            # 若有错误或正在运行或已请求取消, 则拒绝启动
            if self._errors:
                self._last_error = 'ERR_PARAMS_INVALID'
                return False
            if self._progress['running']:
                self._last_error = 'ERR_ALREADY_RUNNING'
                return False
            if self._progress['cancel_requested']:
                self._last_error = 'ERR_CANCELED'
                return False
            self._agent_type = agent_type
            self._submitted = int(self._params['count'])
            # 重置进度
            self._progress.update({
                'mode': 'indeterminate',
                'current': None,
                'total': None,
                'started_ts': time.time(),
                'completed_ts': None,
                'cancel_requested': False,
                'running': True,
            })
            self._last_result = None
            self._last_error = None
            # 启动后台线程
            t = Thread(target=self._run_batch_worker, name="AgentBatchCreateWorker", daemon=True)
            self._worker = t
            metrics.inc('agent_creation_dialog_start')
        t.start()
        return True

    def cancel(self):  # 仅 UI 标记; 控制器层取消由 T5 实现
        with self._lock:
            if not self._progress['running']:
                self._progress['cancel_requested'] = True
                self._last_error = 'ERR_CANCELED'
                return
            self._progress['cancel_requested'] = True
            metrics.inc('agent_creation_dialog_cancel')

    # ---------------- 内部: 后台线程 ----------------
    def _run_batch_worker(self):
        try:
            with self._lock:
                agent_type = self._agent_type or 'Retail'
                count = int(self._params['count'])
                name_prefix = self._params['name_prefix']
                cancel_now = self._progress['cancel_requested']
            if cancel_now:
                with self._lock:
                    self._last_error = 'ERR_CANCELED'
                    self._progress['running'] = False
                    self._progress['completed_ts'] = time.time()
                return
            # 调用控制器 (一次性)
            res = self._ctl.batch_create(agent_type=agent_type, count=count, name_prefix=name_prefix)
            with self._lock:
                self._last_result = res
                self._progress['running'] = False
                self._progress['completed_ts'] = time.time()
            metrics.inc('agent_creation_dialog_complete')
        except AgentServiceError as e:
            with self._lock:
                self._last_error = e.code
                self._progress['running'] = False
                self._progress['completed_ts'] = time.time()
            metrics.inc('agent_creation_dialog_error')
        except Exception:  # noqa: BLE001
            with self._lock:
                self._last_error = 'UNKNOWN'
                self._progress['running'] = False
                self._progress['completed_ts'] = time.time()
            metrics.inc('agent_creation_dialog_error')

    # ---------------- 视图 ----------------
    def get_view(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'last_result': self._last_result,
                'last_error': self._last_error,
                'submitted': self._submitted,
                'agent_type': self._agent_type,
                'progress': {
                    'mode': self._progress['mode'],
                    'current': self._progress['current'],
                    'total': self._progress['total'],
                    'started_ts': self._progress['started_ts'],
                    'completed_ts': self._progress['completed_ts'],
                    'cancel_requested': self._progress['cancel_requested'],
                    'running': self._progress['running'],
                },
                'params': dict(self._params),
                'errors': dict(self._errors),
            }

# 注册辅助 (可选): 将对话框作为一个面板名 "agent_creation" 注册 (惰性实例化)
from app.panels import replace_panel  # noqa: E402

def register_agent_creation_dialog(controller: AgentCreationController):
    replace_panel('agent_creation', lambda: AgentCreationDialog(controller), title='AgentCreation')
