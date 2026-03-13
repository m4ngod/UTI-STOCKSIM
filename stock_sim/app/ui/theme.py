"""ThemeManager (R6,R21)

轻量主题管理：基于 QSS 主题文件 (QSS/<theme>.qss)。
- apply_theme(theme_name): 尝试读取 QSS 并应用到 QApplication 实例 (若存在)。
- register_post_apply(callback): 主题应用后回调（可用于刷新自定义绘制控件）。

设计要求：
- 不抛异常；IO / 文件缺失静默失败并记录 metrics (可选)。
- 操作需 <50ms (文件很小，一次性读取)。
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable, List

try:  # 允许 headless
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore

from observability.metrics import metrics

_QSS_DIR = Path("QSS")

class ThemeManager:
    def __init__(self):
        self._current: str | None = None
        self._callbacks: List[Callable[[str], None]] = []

    @property
    def current(self) -> str | None:
        return self._current

    def register_post_apply(self, fn: Callable[[str], None]):
        self._callbacks.append(fn)

    def apply_theme(self, theme: str):  # noqa: D401
        self._current = theme
        if QApplication is None:
            return
        app = QApplication.instance()
        if app is None:
            return
        qss_path = _QSS_DIR / f"{theme}.qss"
        css = ""
        if qss_path.is_file():
            try:
                css = qss_path.read_text(encoding="utf-8")
            except Exception:  # pragma: no cover
                metrics.inc("theme_read_fail")
                css = ""
        else:
            metrics.inc("theme_missing")
        try:
            app.setStyleSheet(css)
        except Exception:  # pragma: no cover
            metrics.inc("theme_apply_error")
        for cb in list(self._callbacks):
            try:
                cb(theme)
            except Exception:  # pragma: no cover
                metrics.inc("theme_callback_error")

__all__ = ["ThemeManager"]

