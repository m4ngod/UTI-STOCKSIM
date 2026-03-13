"""I18nManager (R6,R21)

职责:
- 维护已注册控件及其翻译 key 映射
- 提供 register(widget, key, attr='setText') 将 t(key) 结果应用到 widget.attr
- refresh(): 遍历所有注册项重新应用翻译

设计要求:
- 不依赖具体面板实现, 仅假设控件有指定方法
- 失败静默并记录 metrics.i18n_apply_error
- 调用成本低 (O(n) 注册控件数量)
"""
from __future__ import annotations
from typing import Any, List, Dict
from observability.metrics import metrics
from app.i18n.loader import t

class I18nManager:
    def __init__(self):
        self._items: List[Dict[str, Any]] = []  # [{'w':widget,'key':key,'attr':attr}]

    def register(self, widget: Any, key: str, attr: str = 'setText'):
        self._items.append({'w': widget, 'key': key, 'attr': attr})
        # 初次注册立即应用一次
        self._apply_single(widget, key, attr)

    def refresh(self):  # 语言切换后调用
        for it in list(self._items):
            self._apply_single(it['w'], it['key'], it['attr'])

    def _apply_single(self, widget: Any, key: str, attr: str):
        try:
            text = t(key)
            fn = getattr(widget, attr, None)
            if callable(fn):
                fn(text)
        except Exception:  # pragma: no cover
            metrics.inc('i18n_apply_error')

__all__ = ["I18nManager"]

