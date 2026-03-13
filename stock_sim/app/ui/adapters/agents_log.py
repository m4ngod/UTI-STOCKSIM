"""LogsViewer for AgentsPanel (R18 helper)

独立日志查看组件, 供 AgentsPanelAdapter 复用或单独调试。
- set_logs(lines: list[str]) -> 更新文本
- append(line: str) -> 追加一行

在 headless 模式下退化为存储字符串数组。
"""
from __future__ import annotations
from typing import List

try:
    from PySide6.QtWidgets import QTextEdit  # type: ignore
except Exception:  # pragma: no cover
    class QTextEdit:  # type: ignore
        def __init__(self): self._buf: List[str] = []
        def setReadOnly(self, *_): pass
        def setPlainText(self, t: str): self._buf = t.split('\n')
        def append(self, t: str): self._buf.append(t)

class LogsViewer(QTextEdit):  # type: ignore[misc]
    def __init__(self):  # noqa: D401
        super().__init__()  # type: ignore
        try:
            self.setReadOnly(True)  # type: ignore
        except Exception:  # pragma: no cover
            pass

    def set_logs(self, lines: List[str]):
        try:
            self.setPlainText('\n'.join(lines))  # type: ignore
        except Exception:  # pragma: no cover
            pass

    def append_line(self, line: str):
        try:
            self.append(line)  # type: ignore
        except Exception:  # pragma: no cover
            pass

__all__ = ["LogsViewer"]

