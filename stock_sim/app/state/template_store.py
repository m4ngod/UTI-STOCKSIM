"""TemplateStore

职责:
- 策略参数模板持久化 (JSON) + 原子写 (tmp + rename)
- 模板唯一 (name)
- add_template(name, diff_json, author)
- list_templates() / get(name)

应用场景:
- AgentConfigController.apply_template -> 读取模板 diff_json 生成新的参数版本

错误代码:
- TEMPLATE_EXISTS
- TEMPLATE_NOT_FOUND

结构:
{"templates": [ {name, created_at, author, diff_json}, ... ]}
"""
from __future__ import annotations
import json, os, time
from dataclasses import dataclass
from threading import RLock
from typing import Dict, List, Any, Optional

__all__ = ["TemplateStore", "TemplateStoreError", "TemplateDTO"]

class TemplateStoreError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class TemplateDTO:
    name: str
    created_at: int
    author: str
    diff_json: Dict[str, Any]

class TemplateStore:
    def __init__(self, path: str = "strategy_templates.json"):
        self._path = path
        self._lock = RLock()
        self._data: Dict[str, TemplateDTO] = {}
        self._load_if_exists()

    # ---------- Persistence ----------
    def _load_if_exists(self):
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            arr = raw.get('templates', []) if isinstance(raw, dict) else []
            for item in arr:
                try:
                    dto = TemplateDTO(
                        name=item['name'],
                        created_at=int(item['created_at']),
                        author=item.get('author', ''),
                        diff_json=dict(item.get('diff_json', {})),
                    )
                    self._data[dto.name] = dto
                except Exception:
                    continue
        except Exception:
            pass

    def _persist(self):
        tmp = self._path + '.tmp'
        serial = {"templates": [v.__dict__ for v in self._data.values()]}
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False)
        os.replace(tmp, self._path)

    # ---------- Public API ----------
    def add_template(self, name: str, diff_json: Dict[str, Any], author: str) -> TemplateDTO:
        if not name:
            raise TemplateStoreError("INVALID_NAME", "name empty")
        with self._lock:
            if name in self._data:
                raise TemplateStoreError("TEMPLATE_EXISTS", f"template exists: {name}")
            dto = TemplateDTO(name=name, created_at=int(time.time()*1000), author=author, diff_json=dict(diff_json))
            self._data[name] = dto
            self._persist()
            return dto

    def get(self, name: str) -> TemplateDTO:
        with self._lock:
            dto = self._data.get(name)
            if dto is None:
                raise TemplateStoreError("TEMPLATE_NOT_FOUND", name)
            return dto

    def list_templates(self) -> List[TemplateDTO]:
        with self._lock:
            return list(self._data.values())

