"""AgentService (Spec Task 10)

Responsibilities:
- list_agents(): return agent meta visible to the desktop app
- control(agent_id, action): start / pause / stop agent execution
- batch_create_retail(config): create Retail / MultiStrategyRetail populations
- tail_logs / page_logs: expose log snippets for the selected agent

Implementation notes:
- Retail agents are now backed by a small runtime executor that submits real
  orders through TradingService.
- MultiStrategyRetail remains app-layer metadata-first for now.
- Thread safety: RLock
- Errors: AgentServiceError(code, message)
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Dict, List, Literal, Optional

from app.core_dto.agent import AgentMetaDTO
from app.event_bridge import publish_account_created, publish_agent_status_changed
from infra.event_bus import event_bus
from observability.metrics import metrics
from app.runtime_gateway import RuntimeGateway

from .log_stream_service import LogStreamService

try:
    from agents.retail_strategy import allocate_retail_strategies
except Exception:  # pragma: no cover
    def allocate_retail_strategies(count: int, preferred=None, *, seed=None, mode: str = "normal"):  # type: ignore
        preferred = [s for s in (preferred or []) if s]
        if preferred:
            return [preferred[i % len(preferred)] for i in range(count)]
        return ["mean_revert" for _ in range(count)]

try:
    from app.services.runtime_retail_agent import RuntimeRetailAgent
except Exception:  # pragma: no cover
    RuntimeRetailAgent = None  # type: ignore


ActionType = Literal["start", "pause", "stop"]
BATCH_ALLOWED_TYPES = {"Retail", "MultiStrategyRetail"}


class AgentServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class BatchCreateConfig:
    count: int
    agent_type: str
    name_prefix: str = "agent"
    initial_cash: float = 100_000.0
    strategies: Optional[List[str]] = None


class AgentService:
    def __init__(
        self,
        *,
        log_stream: Optional[LogStreamService] = None,
        retail_agent_factory: Optional[Callable[..., Any]] = None,
        account_bootstrapper: Optional[Callable[[str, float], None]] = None,
        runtime_gateway: RuntimeGateway | None = None,
    ):
        self._agents: Dict[str, AgentMetaDTO] = {}
        self._lock = threading.RLock()
        self._log = log_stream or LogStreamService()
        self._msr_counter = 0
        self._retail_counters: Dict[str, int] = {}
        self._runtime_agents: Dict[str, Any] = {}
        self._runtime_stop_threads: Dict[str, threading.Thread] = {}
        self._runtime_gateway = runtime_gateway or RuntimeGateway()
        self._sync_runtime_bindings_enabled = runtime_gateway is not None
        self._retail_agent_factory = retail_agent_factory or self._default_retail_agent_factory
        self._account_bootstrapper = account_bootstrapper or self._bootstrap_runtime_account

    def list_agents(self) -> List[AgentMetaDTO]:
        self._sync_from_runtime_bindings()
        with self._lock:
            return list(self._agents.values())

    def get(self, agent_id: str) -> Optional[AgentMetaDTO]:
        self._sync_from_runtime_bindings()
        with self._lock:
            return self._agents.get(agent_id)

    def update_params_version(self, agent_id: str, new_version: int) -> AgentMetaDTO:
        self._sync_from_runtime_bindings()
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
            agent.params_version = new_version  # type: ignore[assignment]
            self._agents[agent_id] = agent
        self._persist_runtime_agent_meta(agent_id, params_version=int(new_version))
        with self._lock:
            return agent

    def control(self, agent_id: str, action: ActionType) -> AgentMetaDTO:
        self._sync_from_runtime_bindings()
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
        runtime_agent = self._ensure_runtime_agent(agent_id, agent=agent)
        now = int(time.time() * 1000)
        if action == "start":
            if runtime_agent is not None:
                runtime_agent.start()
            with self._lock:
                current = self._agents.get(agent_id)
            self._apply_runtime_state(
                agent_id,
                status="RUNNING",
                heartbeat_ms=(current.last_heartbeat if current and current.last_heartbeat is not None else now),
                start_time_ms=(current.start_time if current and current.start_time is not None else now),
                emit_event=True,
            )
        elif action == "pause":
            if runtime_agent is not None:
                runtime_agent.pause()
            with self._lock:
                current = self._agents.get(agent_id)
            self._apply_runtime_state(
                agent_id,
                status="PAUSED",
                heartbeat_ms=(current.last_heartbeat if current and current.last_heartbeat is not None else now),
                emit_event=True,
            )
        elif action == "stop":
            if runtime_agent is not None:
                self._stop_runtime_agent_async(agent_id, runtime_agent)
            self._apply_runtime_state(agent_id, status="STOPPED", heartbeat_ms=None, emit_event=True)
        else:
            raise AgentServiceError("INVALID_ACTION", action)
        metrics.inc(f"agent_control_action_{action}")
        self._log.append(agent_id, f"Control action={action}")
        with self._lock:
            return self._agents[agent_id]

    def batch_create_retail(self, cfg: BatchCreateConfig) -> Dict[str, Any]:
        if cfg.count <= 0:
            return {"success_ids": [], "failed": ["INVALID_COUNT"]}
        if cfg.agent_type not in BATCH_ALLOWED_TYPES:
            metrics.inc("agent_batch_unsupported")
            raise AgentServiceError("AGENT_BATCH_UNSUPPORTED", f"type {cfg.agent_type} not allowed for batch")

        success: List[str] = []
        failed: List[str] = []
        created: List[AgentMetaDTO] = []
        pending_account_bootstrap: List[str] = []
        now = int(time.time() * 1000)
        strategies = getattr(cfg, "strategies", None)
        initial_cash = float(getattr(cfg, "initial_cash", 100_000.0) or 100_000.0)
        assigned_strategies = allocate_retail_strategies(
            cfg.count,
            strategies,
            seed=now,
            mode="post_ipo_cold_start" if cfg.agent_type == "Retail" else "normal",
        )

        with self._lock:
            for i in range(cfg.count):
                try:
                    strategy_name = assigned_strategies[i] if i < len(assigned_strategies) else None
                    if cfg.agent_type == "MultiStrategyRetail":
                        self._msr_counter += 1
                        agent_id = f"MSR{self._msr_counter:04d}"
                        agent_name = agent_id
                    else:
                        retail_name = self._next_retail_name(strategy_name or "retail")
                        agent_id = retail_name
                        agent_name = retail_name
                    if agent_id in self._agents:
                        failed.append(agent_id)
                        metrics.inc("agent_create_fail")
                        continue
                    meta = _synthetic_factory(
                        agent_id=agent_id,
                        name=agent_name,
                        a_type=cfg.agent_type,
                        strategy=strategy_name,
                    )
                    self._agents[agent_id] = meta
                    success.append(agent_id)
                    created.append(meta)
                    pending_account_bootstrap.append(agent_id)
                    metrics.inc("agent_create_success")
                    if cfg.agent_type == "Retail":
                        runtime_agent = self._retail_agent_factory(
                            agent_id=agent_id,
                            strategy=strategy_name or "noise",
                            initial_cash=initial_cash,
                            state_callback=self._on_runtime_state,
                        )
                        if runtime_agent is not None:
                            self._runtime_agents[agent_id] = runtime_agent
                except Exception:
                    failed.append(f"{cfg.agent_type}-{i}")
                    metrics.inc("agent_create_fail")

        for account_id in pending_account_bootstrap:
            try:
                self._account_bootstrapper(account_id, initial_cash)
            except Exception:
                pass
            try:
                publish_account_created({"account_id": account_id, "initial_cash": initial_cash})
            except Exception:
                pass

        for meta in created:
            self._log.generate_initial(meta.agent_id)

        payload = {
            "success_ids": list(success),
            "failed": list(failed),
            "type": cfg.agent_type,
            "count": cfg.count,
            "initial_cash": initial_cash,
            "strategies": assigned_strategies,
        }
        try:
            event_bus.publish("agent.batch.create.progress", payload)
            event_bus.publish("agent.batch.create.completed", payload)
        except Exception:
            pass
        return {"success_ids": success, "failed": failed, "strategies": assigned_strategies}

    def tail_logs(self, agent_id: str, n: int = 100) -> List[str]:
        return self._log.tail(agent_id, n)

    def page_logs(self, agent_id: str, page: int, page_size: int) -> List[str]:
        return self._log.page(agent_id, page, page_size)

    def _next_retail_name(self, strategy: str) -> str:
        key = (strategy or "retail").strip().lower() or "retail"
        next_index = self._retail_counters.get(key, 0) + 1
        self._retail_counters[key] = next_index
        return f"{key}{next_index:03d}"

    def _default_retail_agent_factory(
        self,
        *,
        agent_id: str,
        strategy: str,
        initial_cash: float,
        state_callback: Callable[..., None] | None = None,
    ) -> Any:
        if RuntimeRetailAgent is None:
            return None
        return RuntimeRetailAgent(
            agent_id=agent_id,
            strategy=strategy,
            state_callback=state_callback or self._on_runtime_state,
            runtime_gateway=self._runtime_gateway,
        )

    def _ensure_runtime_agent(self, agent_id: str, *, agent: AgentMetaDTO | None = None) -> Any:
        with self._lock:
            existing = self._runtime_agents.get(agent_id)
            if existing is not None:
                return existing
            resolved = agent or self._agents.get(agent_id)
        if resolved is None or str(getattr(resolved, "type", "") or "") != "Retail":
            return None
        strategy = str(getattr(resolved, "strategy", None) or "noise")
        try:
            runtime_agent = self._retail_agent_factory(
                agent_id=agent_id,
                strategy=strategy,
                initial_cash=100_000.0,
                state_callback=self._on_runtime_state,
            )
        except Exception:
            runtime_agent = None
        if runtime_agent is not None:
            with self._lock:
                self._runtime_agents[agent_id] = runtime_agent
        return runtime_agent

    def _stop_runtime_agent_async(self, agent_id: str, runtime_agent: Any) -> None:
        with self._lock:
            existing = self._runtime_stop_threads.get(agent_id)
            if existing is not None and existing.is_alive():
                return

        def _worker() -> None:
            try:
                runtime_agent.stop()
            except Exception:
                pass
            finally:
                with self._lock:
                    current = self._runtime_stop_threads.get(agent_id)
                    if current is threading.current_thread():
                        self._runtime_stop_threads.pop(agent_id, None)

        worker = threading.Thread(
            target=_worker,
            name=f"AgentStop-{agent_id}",
            daemon=True,
        )
        with self._lock:
            self._runtime_stop_threads[agent_id] = worker
        worker.start()

    def _bootstrap_runtime_account(self, account_id: str, initial_cash: float) -> None:
        meta = self.get(account_id)
        self._runtime_gateway.bootstrap_agent_account(
            account_id=account_id,
            initial_cash=initial_cash,
            agent_type=(str(getattr(meta, "type", "")) if meta is not None else None),
            strategy=(str(getattr(meta, "strategy", "")) if meta is not None and getattr(meta, "strategy", None) is not None else None),
        )
        self._runtime_gateway.allocate_pending_ipo_distributions_if_running()

    def _runtime_binding_rows(self) -> List[Dict[str, Any]]:
        if not self._sync_runtime_bindings_enabled:
            return []
        try:
            rows = self._runtime_gateway.list_agent_bindings(include_all_runs=True)
        except TypeError:
            try:
                rows = self._runtime_gateway.list_agent_bindings()
            except Exception:
                return []
        except Exception:
            return []
        return list(rows or [])

    def _active_runtime_run_id(self) -> str | None:
        getter = getattr(self._runtime_gateway, "get_current_run_id", None)
        if not callable(getter):
            return None
        try:
            value = str(getter() or "").strip()
        except Exception:
            return None
        return value or None

    def _sync_from_runtime_bindings(self) -> None:
        rows = self._runtime_binding_rows()
        if not rows:
            return
        retail_ids_to_hydrate: List[str] = []
        active_run_id = self._active_runtime_run_id()
        with self._lock:
            for row in rows:
                agent_id = str(row.get("agent_name") or row.get("account_id") or "").strip()
                if not agent_id:
                    continue
                meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
                row_run_id = str(row.get("run_id") or meta.get("run_id") or "").strip() or None
                restored_from_previous_run = active_run_id is not None and row_run_id is not None and row_run_id != active_run_id
                status_value = "STOPPED" if restored_from_previous_run else meta.get("status")
                heartbeat_value = None if restored_from_previous_run else meta.get("last_heartbeat")
                start_time_value = None if restored_from_previous_run else meta.get("start_time")
                agent_type = _normalize_agent_type(row.get("agent_type") or meta.get("type") or "GENERIC")
                strategy = meta.get("strategy")
                current = self._agents.get(agent_id)
                if current is None:
                    self._agents[agent_id] = AgentMetaDTO(
                        agent_id=agent_id,
                        name=str(meta.get("name") or agent_id),
                        type=agent_type,
                        status=self._normalize_status(status_value),
                        start_time=self._maybe_int(start_time_value),
                        last_heartbeat=self._maybe_int(heartbeat_value),
                        params_version=int(meta.get("params_version") or 0),
                        strategy=(str(strategy) if strategy is not None and str(strategy).strip() else None),
                    )
                    if agent_type == "Retail":
                        retail_ids_to_hydrate.append(agent_id)
                    continue
                current.name = str(meta.get("name") or current.name or agent_id)
                current.type = agent_type
                current.status = self._normalize_status(status_value, fallback=current.status)  # type: ignore[assignment]
                if restored_from_previous_run or "start_time" in meta:
                    current.start_time = self._maybe_int(start_time_value)
                if restored_from_previous_run or "last_heartbeat" in meta:
                    current.last_heartbeat = self._maybe_int(heartbeat_value)
                if strategy is not None and str(strategy).strip():
                    current.strategy = str(strategy)
                if meta.get("params_version") is not None:
                    try:
                        current.params_version = int(meta.get("params_version") or 0)
                    except Exception:
                        pass
                self._agents[agent_id] = current
                if agent_type == "Retail":
                    retail_ids_to_hydrate.append(agent_id)
        for agent_id in retail_ids_to_hydrate:
            self._ensure_runtime_agent(agent_id)

    def _on_runtime_state(
        self,
        agent_id: str,
        status: str,
        heartbeat_ms: int | None,
        start_time_ms: int | None,
    ) -> None:
        self._apply_runtime_state(
            agent_id,
            status=status,
            heartbeat_ms=heartbeat_ms,
            start_time_ms=start_time_ms,
            emit_event=(heartbeat_ms is None),
        )

    def _apply_runtime_state(
        self,
        agent_id: str,
        *,
        status: str | None = None,
        heartbeat_ms: int | None = None,
        start_time_ms: int | None = None,
        emit_event: bool = False,
    ) -> None:
        payload: Dict[str, Any] | None = None
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            if status is not None:
                agent.status = status  # type: ignore[assignment]
            if start_time_ms is not None and agent.start_time is None:
                agent.start_time = start_time_ms
            if heartbeat_ms is not None:
                agent.last_heartbeat = heartbeat_ms
            self._agents[agent_id] = agent
            if emit_event:
                payload = {
                    "agent_id": agent.agent_id,
                    "status": agent.status,
                    "last_heartbeat": agent.last_heartbeat,
                    "start_time": agent.start_time,
                }
        if payload is not None:
            try:
                publish_agent_status_changed(payload)
            except Exception:
                pass
        self._persist_runtime_agent_meta(
            agent_id,
            status=status,
            start_time=start_time_ms,
            last_heartbeat=heartbeat_ms,
        )

    def _persist_runtime_agent_meta(self, agent_id: str, **updates: Any) -> None:
        updater = getattr(self._runtime_gateway, "update_agent_binding_meta", None)
        if not callable(updater):
            return
        try:
            updater(agent_id, **updates)
        except Exception:
            pass

    @staticmethod
    def _maybe_int(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _normalize_status(value: object, *, fallback: str = "STOPPED") -> str:
        raw = str(value or "").strip().upper()
        if raw in {"RUNNING", "PAUSED", "STOPPED", "INACTIVE"}:
            return raw
        return fallback


def _synthetic_factory(*, agent_id: str, name: str, a_type: str, strategy: str | None = None) -> AgentMetaDTO:
    return AgentMetaDTO(
        agent_id=agent_id,
        name=name,
        type=a_type,
        status="STOPPED",
        start_time=None,
        last_heartbeat=None,
        params_version=0,
        strategy=strategy,
    )


def _normalize_agent_type(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "GENERIC"
    upper = raw.upper()
    if upper == "RETAIL":
        return "Retail"
    if upper == "MULTISTRATEGYRETAIL":
        return "MultiStrategyRetail"
    return raw


__all__ = [
    "AgentService",
    "AgentServiceError",
    "BatchCreateConfig",
    "BATCH_ALLOWED_TYPES",
]
