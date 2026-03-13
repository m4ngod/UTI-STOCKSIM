"""LayoutPersistence (Spec Task 16)

负责面板布局 JSON 持久化 (R6/R11 支撑):
- 保存: save(layout: dict)
- 部分更新: update(patch: dict) -> 合并并保存
- 读取: get() 返回当前内存布局 (深拷贝)
- 原子写: tmp + rename
- 提供缺省结构: {"panels": {}} 便于后续扩展 (dock pos / size / visible / order)

不执行复杂验证, 由上层 UI 控制器保证格式。
"""
from __future__ import annotations
import json
import os
from threading import RLock
from typing import Dict, Any
import copy

class LayoutPersistence:
    def __init__(self, path: str = "layout.json"):
        self._path = path
        self._lock = RLock()
        self._layout: Dict[str, Any] = {"panels": {}}
        self._load()

    # -------------- Public API --------------
    def get(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._layout)

    def save(self, layout: Dict[str, Any]):
        with self._lock:
            self._layout = copy.deepcopy(layout)
            self._persist()

    def update(self, patch: Dict[str, Any]):
        with self._lock:
            self._merge(self._layout, patch)
            self._persist()
        return self.get()

    # -------------- Internal ----------------
    def _merge(self, base: Dict[str, Any], patch: Dict[str, Any]):
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                self._merge(base[k], v)  # type: ignore[index]
            else:
                base[k] = v

    def _load(self):
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._merge(self._layout, raw)
        except Exception:
            pass

    def _persist(self):
        tmp = self._path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._layout, f, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            pass

__all__ = ["LayoutPersistence"]

