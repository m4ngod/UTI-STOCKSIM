"""RollbackService (Spec Task 12 Part 2 / Task 39 增量)

职责 (R5 AC3/4/6):
- 管理前端可回滚检查点 (仅内存): create_checkpoint(label)
- rollback(checkpoint_id): 恢复 clock.sim_day & 内部标记 current_checkpoint
- 一致性校验 (Task 39 扩展):
  * 校验 sim_day 相等 (原有)
  * 若提供 AccountService: 校验 equity 相对差异 < equity_tolerance_ratio (默认 0.0001 即 0.01%)
    - 记录 checkpoint.baseline_equity
    - 失败 -> RollbackServiceError("CONSISTENCY_FAIL")
  * 若提供 AccountService: 计算 positions hash (symbol,qty,avg_price 排序) 与当前对比 (差异仅记日志 TODO, 现同样视为一致性失败)
  * 若提供 AgentService: 计算 agents hash (agent_id,type,params_version 排序) 与 checkpoint 对比 (差异视为一致性失败)
- 若校验失败, 抛出 RollbackServiceError("CONSISTENCY_FAIL") 并不修改最终状态 (恢复 before)
- 提供 list_checkpoints()

指标:
- rollback_checkpoint_create
- rollback_attempt / rollback_success / rollback_failure
- rollback_consistency_violation

未来扩展 TODO:
- TODO: 记录账户/持仓/智能体版本, 校验 equity/positions hash (已部分实现基础哈希)
- TODO: 永久存储至本地磁盘 (JSON)
- TODO: 对 positions / agents 差异分类 (轻微/严重)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from threading import RLock
import time
import uuid
import hashlib
import json

from observability.metrics import metrics
from app.services.clock_service import ClockService, ClockServiceError
from app.services.account_service import AccountService
from app.services.agent_service import AgentService

class RollbackServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class _Checkpoint:
    id: str
    label: str
    sim_day: str
    created_ms: int
    baseline_equity: Optional[float] = None
    positions_hash: Optional[str] = None
    agents_hash: Optional[str] = None

class RollbackService:
    def __init__(self, clock: ClockService, *, account_service: AccountService | None = None,
                 agent_service: AgentService | None = None, equity_tolerance_ratio: float = 0.0001):
        self._clock = clock
        self._lock = RLock()
        self._checkpoints: Dict[str, _Checkpoint] = {}
        self._order: List[str] = []  # 维护插入顺序
        self._current_id: str | None = None
        self._account = account_service
        self._agents = agent_service
        self._equity_tol = equity_tolerance_ratio

    def create_checkpoint(self, label: str) -> str:
        state = self._clock.get_state()
        cp_id = uuid.uuid4().hex[:12]
        # 采集基线数据
        baseline_equity: Optional[float] = None
        positions_hash: Optional[str] = None
        agents_hash: Optional[str] = None
        if self._account:
            acc = self._account.get_cached()
            if acc:
                baseline_equity = acc.equity
                positions_hash = self._hash_positions(acc.positions)
        if self._agents:
            agents = self._agents.list_agents()
            if agents:
                agents_hash = self._hash_agents(agents)
        cp = _Checkpoint(
            id=cp_id,
            label=label,
            sim_day=state.sim_day,
            created_ms=int(time.time()*1000),
            baseline_equity=baseline_equity,
            positions_hash=positions_hash,
            agents_hash=agents_hash,
        )
        with self._lock:
            self._checkpoints[cp_id] = cp
            self._order.append(cp_id)
            self._current_id = cp_id
        metrics.inc("rollback_checkpoint_create")
        return cp_id

    def list_checkpoints(self) -> List[dict]:
        with self._lock:
            return [self._cp_to_dict(self._checkpoints[i]) for i in self._order]

    def rollback(self, checkpoint_id: str, *, simulate_inconsistent: bool = False):
        metrics.inc("rollback_attempt")
        with self._lock:
            cp = self._checkpoints.get(checkpoint_id)
            if not cp:
                metrics.inc("rollback_failure")
                raise RollbackServiceError("NOT_FOUND", f"checkpoint {checkpoint_id} not found")
            before = self._clock.get_state()
            try:
                if simulate_inconsistent:
                    metrics.inc("rollback_consistency_violation")
                    raise RollbackServiceError("CONSISTENCY_FAIL", "simulated inconsistency")
                # 应用 sim_day
                self._clock.start(cp.sim_day)
                # 一致性校验 (账户 & 代理)
                self._validate_consistency(cp)
                self._current_id = cp.id
                metrics.inc("rollback_success")
            except RollbackServiceError:
                # 恢复原状态
                self._restore_clock(before)
                metrics.inc("rollback_failure")
                raise

    # -------------- Internal helpers --------------
    def _restore_clock(self, before_state):
        try:
            if before_state.status == "RUNNING":
                self._clock.start(before_state.sim_day)
            elif before_state.status == "PAUSED":
                self._clock.start(before_state.sim_day)
                self._clock.pause()
            else:
                self._clock.stop()
        except ClockServiceError:
            pass

    def _hash_positions(self, positions) -> str:
        arr = [
            {
                "symbol": p.symbol,
                "qty": p.quantity,
                "avg": p.avg_price,
            } for p in positions
        ]
        arr_sorted = sorted(arr, key=lambda x: (x["symbol"], x["qty"], x["avg"]))
        return hashlib.md5(json.dumps(arr_sorted, sort_keys=True).encode()).hexdigest()

    def _hash_agents(self, agents) -> str:
        arr = [
            {
                "id": a.agent_id,
                "type": a.type,
                "pv": a.params_version,
            } for a in agents
        ]
        arr_sorted = sorted(arr, key=lambda x: (x["id"], x["type"], x["pv"]))
        return hashlib.md5(json.dumps(arr_sorted, sort_keys=True).encode()).hexdigest()

    def _validate_consistency(self, cp: _Checkpoint):
        # Account equity & positions hash
        if self._account:
            acc = self._account.get_cached()
            if cp.baseline_equity is not None and acc is not None:
                diff_ratio = abs(acc.equity - cp.baseline_equity) / max(cp.baseline_equity, 1.0)
                if diff_ratio >= self._equity_tol:
                    metrics.inc("rollback_consistency_violation")
                    raise RollbackServiceError("CONSISTENCY_FAIL", f"equity diff {diff_ratio:.6f} >= {self._equity_tol}")
            if cp.positions_hash and acc is not None:
                cur_hash = self._hash_positions(acc.positions)
                if cur_hash != cp.positions_hash:
                    metrics.inc("rollback_consistency_violation")
                    raise RollbackServiceError("CONSISTENCY_FAIL", "positions hash mismatch")
        # Agents hash
        if self._agents:
            agents = self._agents.list_agents()
            if cp.agents_hash and agents:
                cur_agents_hash = self._hash_agents(agents)
                if cur_agents_hash != cp.agents_hash:
                    metrics.inc("rollback_consistency_violation")
                    raise RollbackServiceError("CONSISTENCY_FAIL", "agents hash mismatch")

    def current_checkpoint(self) -> str | None:
        with self._lock:
            return self._current_id

    def _cp_to_dict(self, cp: _Checkpoint) -> dict:
        return {
            "id": cp.id,
            "label": cp.label,
            "sim_day": cp.sim_day,
            "created_ms": cp.created_ms,
            "is_current": cp.id == self._current_id,
        }

__all__ = ["RollbackService", "RollbackServiceError"]
