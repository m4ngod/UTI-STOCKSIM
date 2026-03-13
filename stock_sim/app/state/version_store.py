"""VersionStore (Spec Task 15)

职责 (R8 AC2/3/4/5/6):
- 为每个 agent_id 维护参数版本链列表 (顺序递增的 version int)。
- 支持新增版本 add_version(agent_id, diff_json, author)
- 支持基于历史版本回滚 create_rollback(agent_id, target_version, author) -> 生成新版本 (version = last+1, rollback_of=target_version)
- JSON 持久化: 初始化时尝试加载; 每次更新后原子写回 (临时文件 + rename)。
- 线程安全 (RLock)。
- 提供 list_versions(agent_id, limit=None, reverse=False) 与 get_latest_version(agent_id)。

设计要点:
- 存储结构: {agent_id: [ {version, created_at, author, diff_json, rollback_of}, ...] }
- version 从 1 开始 (人类可读, 与回滚“生成 v+1”描述符吻合)。
- rollback_of: 指向被回滚的目标版本 (而非上一个)。
- diff_json 为任意 dict (不做 schema 校验, 上层控制器负责校验)。

错误:
- VersionStoreError(code, message)
  - AGENT_NOT_FOUND (访问不存在 agent 版本时)
  - VERSION_NOT_FOUND (回滚目标不存在)

指标 (轻量): version_add, version_rollback, version_persist_ms

后续扩展:
- 增加最大版本保留数/压缩策略
- 增量 diff 合并 / 存档大 diff
"""
from __future__ import annotations
import json
import os
import time
from typing import Dict, List, Optional, Any, Iterable
from threading import RLock
from dataclasses import dataclass

from app.core_dto.versioning import AgentVersionDTO
from observability.metrics import metrics

class VersionStoreError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class _AgentChain:
    versions: List[AgentVersionDTO]

class VersionStore:
    def __init__(self, path: str = "version_store.json"):
        self._path = path
        self._lock = RLock()
        self._data: Dict[str, _AgentChain] = {}
        self._load_if_exists()

    # --------------- Persistence ----------------
    def _load_if_exists(self):
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for agent_id, arr in raw.items():
                chain = []
                for item in arr:
                    # 容错: 忽略缺失字段条目
                    try:
                        chain.append(AgentVersionDTO(**item))
                    except Exception:
                        continue
                if chain:
                    self._data[agent_id] = _AgentChain(chain)
        except Exception:
            # 读取失败忽略 (可考虑记录指标)
            pass

    def _persist(self):
        t0 = time.perf_counter()
        tmp_path = self._path + ".tmp"
        serializable: Dict[str, List[Dict[str, Any]]] = {}
        for agent_id, chain in self._data.items():
            serializable[agent_id] = [v.dict() for v in chain.versions]
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False)
        os.replace(tmp_path, self._path)
        metrics.add_timing('version_persist_ms', (time.perf_counter()-t0)*1000)

    # --------------- Helpers ----------------
    def _next_version(self, agent_id: str) -> int:
        chain = self._data.get(agent_id)
        if not chain or not chain.versions:
            return 1
        return chain.versions[-1].version + 1

    def _get_chain(self, agent_id: str) -> _AgentChain:
        ch = self._data.get(agent_id)
        if ch is None:
            raise VersionStoreError('AGENT_NOT_FOUND', f'agent {agent_id} has no versions')
        return ch

    # --------------- Public API ----------------
    def add_version(self, agent_id: str, diff_json: Dict[str, Any], author: str, *, rollback_of: Optional[int] = None) -> AgentVersionDTO:
        with self._lock:
            ver = self._next_version(agent_id)
            dto = AgentVersionDTO(
                version=ver,
                created_at=int(time.time()*1000),
                author=author,
                diff_json=dict(diff_json),
                rollback_of=rollback_of,
            )
            chain = self._data.setdefault(agent_id, _AgentChain([]))
            chain.versions.append(dto)
            self._persist()
            metrics.inc('version_add')
            if rollback_of is not None:
                metrics.inc('version_rollback')
            return dto

    def create_rollback(self, agent_id: str, target_version: int, author: str) -> AgentVersionDTO:
        with self._lock:
            chain = self._get_chain(agent_id)
            target = None
            for v in chain.versions:
                if v.version == target_version:
                    target = v
                    break
            if target is None:
                raise VersionStoreError('VERSION_NOT_FOUND', f'target version {target_version} not found for agent {agent_id}')
            # 复用 target diff_json 作为回滚基础 (真实场景可存完整快照)
            return self.add_version(agent_id, diff_json=target.diff_json, author=author, rollback_of=target_version)

    def list_versions(self, agent_id: str, *, limit: Optional[int] = None, reverse: bool = False) -> List[AgentVersionDTO]:
        with self._lock:
            chain = self._get_chain(agent_id)
            arr = list(chain.versions)
            if reverse:
                arr = list(reversed(arr))
            if limit is not None:
                return arr[:limit]
            return arr

    def get_latest_version(self, agent_id: str) -> AgentVersionDTO:
        with self._lock:
            chain = self._get_chain(agent_id)
            return chain.versions[-1]

    def exists(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._data and bool(self._data[agent_id].versions)

__all__ = [
    'VersionStore', 'VersionStoreError'
]

