"""AgentCreationModal

目的:
- 提供带校验的批量创建对话框逻辑 (可选 GUI, 这里主实现逻辑层 + 轻量 UI 占位)
- 支持 strategies 列表 (仅对 MultiStrategyRetail 有意义)
- 校验数值区间与类型: count ∈ [1, MAX_COUNT]; agent_type ∈ BATCH_ALLOWED_TYPES
- 校验策略: 对 MultiStrategyRetail 必须提供至少 1 条非空策略字符串
- 调用 AgentsPanel.start_batch_create 以获得进度 (逐个创建)
- get_view 返回当前输入 / 错误 / 进度

视图结构:
{
  'input': {
      'agent_type': str | None,
      'count': int | None,
      'name_prefix': str | None,
      'strategies': list[str] | None,
  },
  'error': str | None,              # 校验或业务错误码
  'submitted': bool,                # 是否已触发批量
  'progress': batch_dict | None,    # 对应 agents_panel.get_view()['batch']
}

错误码约定:
- INVALID_COUNT: count <=0
- COUNT_TOO_LARGE: count > MAX_COUNT
- AGENT_BATCH_UNSUPPORTED: 类型不允许 (沿用服务层/控制器语义)
- EMPTY_STRATEGIES: MultiStrategyRetail 缺少策略
- UNKNOWN: 未分类异常

成功标准:
- submit 返回 True -> AgentsPanel.batch 开始; 轮询 refresh_progress 查看进度直至 in_progress=False
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any

from app.services.agent_service import BATCH_ALLOWED_TYPES
from app.panels.agents.panel import AgentsPanel

MAX_COUNT = 500

__all__ = ["AgentCreationModal", "MAX_COUNT"]

class AgentCreationModal:
    def __init__(self, agents_panel: AgentsPanel):
        self._panel = agents_panel
        self._agent_type: Optional[str] = None
        self._count: Optional[int] = None
        self._name_prefix: Optional[str] = None
        self._strategies: Optional[List[str]] = None
        self._initial_cash: Optional[float] = None  # 新增
        self._error: Optional[str] = None
        self._submitted: bool = False
        self._progress_cache: Optional[Dict[str, Any]] = None

    # -------- Public API --------
    def open(self):  # 重置输入
        self._agent_type = None
        self._count = None
        self._name_prefix = None
        self._strategies = None
        self._initial_cash = None
        self._error = None
        self._submitted = False
        self._progress_cache = None

    def submit(self, *, agent_type: str, count: int, name_prefix: str = "agent", strategies: Optional[List[str]] = None, initial_cash: Optional[float] = None) -> bool:
        # 更新输入
        self._agent_type = agent_type
        self._count = count
        self._name_prefix = name_prefix
        self._strategies = list(strategies) if strategies else (None if strategies is None else [])
        self._initial_cash = float(initial_cash) if (initial_cash is not None) else None
        self._error = None
        self._submitted = False
        self._progress_cache = None
        # 校验
        if count <= 0:
            self._error = 'INVALID_COUNT'
            return False
        if count > MAX_COUNT:
            self._error = 'COUNT_TOO_LARGE'
            return False
        if agent_type not in BATCH_ALLOWED_TYPES:
            self._error = 'AGENT_BATCH_UNSUPPORTED'
            return False
        if agent_type == 'MultiStrategyRetail':
            if not strategies or not any(s.strip() for s in strategies):
                self._error = 'EMPTY_STRATEGIES'
                return False
            # 过滤空白项, 去重
            clean = []
            seen = set()
            for s in strategies:
                s2 = s.strip()
                if not s2:
                    continue
                if s2 in seen:
                    continue
                seen.add(s2)
                clean.append(s2)
            self._strategies = clean
            if not clean:
                self._error = 'EMPTY_STRATEGIES'
                return False
            # MSR 允许自定义初始资金（可选，默认 100000）
            if initial_cash is not None and self._initial_cash is not None and self._initial_cash < 0:
                self._error = 'INVALID_INITIAL_CASH'
                return False
        try:
            ok = self._panel.start_batch_create(count=count, agent_type=agent_type, name_prefix=name_prefix, strategies=self._strategies, initial_cash=self._initial_cash)
            if not ok:
                # 已有批量在执行
                self._error = 'BATCH_IN_PROGRESS'
                return False
            self._submitted = True
            # 初始进度缓存
            self.refresh_progress()
            return True
        except Exception as e:  # noqa: BLE001
            # 适配 service/控制器抛出的 AgentServiceError 已被吞掉；这里统一 UNKNOWN
            self._error = getattr(e, 'code', 'UNKNOWN') or 'UNKNOWN'
            return False

    def refresh_progress(self):  # 拉取最新 batch 视图
        try:
            v = self._panel.get_view()
            self._progress_cache = v.get('batch')
        except Exception:
            pass

    def get_view(self) -> Dict[str, Any]:
        return {
            'input': {
                'agent_type': self._agent_type,
                'count': self._count,
                'name_prefix': self._name_prefix,
                'strategies': list(self._strategies) if self._strategies else (None if self._strategies is None else []),
                'initial_cash': self._initial_cash,
            },
            'error': self._error,
            'submitted': self._submitted,
            'progress': self._progress_cache,
        }
