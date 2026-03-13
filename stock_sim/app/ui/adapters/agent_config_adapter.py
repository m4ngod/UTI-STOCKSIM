"""AgentConfigPanelAdapter

功能:
- 绑定 AgentConfigPanel, 提供脚本输入与版本提交封装
- 提供 add_version(diff, author, script_code) 封装: 先做大小校验(>200KB 拒绝), 再调用逻辑层 panel.add_version
- 暴露 get_state() 返回 panel.get_view() 及最近一次提交状态
- 展示 violations / error (沿用 panel.script 字段)；若本地大小校验失败 -> last_submit_error='SCRIPT_TOO_LARGE'
- 超大脚本时发送通知 warning (code='script.too_large') （若 notification_center 可用）

结构: get_state 返回
{
  'panel': <panel.get_view() 原样>,
  'last_submit_ok': bool|None,
  'last_submit_error': str|None,
  'staged_script_size': int|None,
}

注意:
- 不在此重复脚本 AST 校验 (由面板/validator 完成)
- headless 环境下无 GUI 控件; 未来可扩展真实 QTextEdit 绑定
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from app.panels.agent_config.panel import AgentConfigPanel

# 可选通知中心
try:  # pragma: no cover
    from app.panels.shared.notifications import notification_center as _notification_center
except Exception:  # pragma: no cover
    _notification_center = None

MAX_SCRIPT_BYTES = 200 * 1024  # 200KB

__all__ = ["AgentConfigPanelAdapter", "MAX_SCRIPT_BYTES"]

class AgentConfigPanelAdapter:
    def __init__(self, panel: AgentConfigPanel):
        self._panel = panel
        self._last_submit_ok: Optional[bool] = None
        self._last_submit_error: Optional[str] = None
        self._staged_script_size: Optional[int] = None

    # ---------- Core Ops ----------
    def add_version(self, diff: Dict[str, Any], *, author: str, script_code: Optional[str] = None) -> bool:
        self._last_submit_ok = None
        self._last_submit_error = None
        if script_code is not None:
            self._staged_script_size = len(script_code.encode('utf-8'))
            if self._staged_script_size > MAX_SCRIPT_BYTES:
                self._last_submit_ok = False
                self._last_submit_error = 'SCRIPT_TOO_LARGE'
                try:  # 通知
                    if _notification_center is not None:
                        _notification_center.publish_warning('script.too_large', f'script > {MAX_SCRIPT_BYTES} bytes rejected')
                except Exception:  # pragma: no cover
                    pass
                return False
        else:
            self._staged_script_size = None
        ok = self._panel.add_version(diff, author=author, script_code=script_code)
        self._last_submit_ok = ok
        if not ok:
            # 读取 panel 中的错误 (script.last_error)
            view = self._panel.get_view()
            script_state = view.get('script', {}) if isinstance(view, dict) else {}
            err = script_state.get('last_error')
            if err:
                self._last_submit_error = err
        return ok

    def rollback(self, target_version: int, *, author: str) -> bool:
        ok = self._panel.rollback(target_version, author=author)
        # rollback 不涉及脚本错误, 简单更新状态
        self._last_submit_ok = ok
        self._last_submit_error = None if ok else 'ROLLBACK_FAIL'
        return ok

    def refresh(self):  # 与其他 adapters 一致的刷新接口
        # 仅调用 panel.refresh (更新版本缓存). 不改变提交状态
        try:
            self._panel.refresh()
        except Exception:  # pragma: no cover
            pass

    # ---------- View ----------
    def get_state(self) -> Dict[str, Any]:
        return {
            'panel': self._panel.get_view(),
            'last_submit_ok': self._last_submit_ok,
            'last_submit_error': self._last_submit_error,
            'staged_script_size': self._staged_script_size,
        }

