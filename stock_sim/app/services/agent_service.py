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
import os
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional

from app.core_dto.agent import AgentMetaDTO
from infra.event_bus import event_bus
from observability.metrics import metrics

from .log_stream_service import LogStreamService

if TYPE_CHECKING:
    from app.runtime_gateway import RuntimeGateway

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

try:
    from app.services.runtime_model_agent import RuntimeModelAgent
    from app.services.model_registry_service import ModelRegistryService
except Exception:  # pragma: no cover
    RuntimeModelAgent = None  # type: ignore
    ModelRegistryService = None  # type: ignore


ActionType = Literal["start", "pause", "stop"]
BATCH_ALLOWED_TYPES = {"Retail", "MultiStrategyRetail"}
DEFAULT_MODEL_INITIAL_CASH = 50_000_000.0


def _publish_account_created(payload: dict[str, Any]) -> None:
    try:
        from app.event_bridge import publish_account_created
    except ImportError:
        return
    publish_account_created(payload)


def _publish_agent_status_changed(payload: dict[str, Any]) -> None:
    try:
        from app.event_bridge import publish_agent_status_changed
    except ImportError:
        return
    publish_agent_status_changed(payload)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


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
        model_agent_factory: Optional[Callable[..., Any]] = None,
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
        runtime_gateway_injected = runtime_gateway is not None
        if runtime_gateway is None:
            from app.runtime_gateway import RuntimeGateway

            runtime_gateway = RuntimeGateway()
        self._runtime_gateway = runtime_gateway
        self._sync_runtime_bindings_enabled = runtime_gateway_injected
        self._retail_agent_factory = retail_agent_factory or self._default_retail_agent_factory
        self._model_agent_factory = model_agent_factory or self._default_model_agent_factory
        self._uses_default_account_bootstrapper = account_bootstrapper is None
        self._account_bootstrapper = account_bootstrapper or self._bootstrap_runtime_account
        self._model_counter = 0
        self._last_state_persist_ms: Dict[str, int] = {}
        self._heartbeat_persist_interval_ms = max(
            1_000,
            _env_int("STOCKSIM_AGENT_HEARTBEAT_PERSIST_INTERVAL_MS", 15_000),
        )
        self._last_runtime_sync_ts = 0.0
        self._runtime_sync_min_interval_s = 0.75

    def list_agents(self) -> List[AgentMetaDTO]:
        self._sync_from_runtime_bindings()
        with self._lock:
            return list(self._agents.values())

    def get(self, agent_id: str) -> Optional[AgentMetaDTO]:
        self._sync_from_runtime_bindings(force=True)
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

    def apply_model_inheritance(
        self,
        agent_id: str,
        *,
        child_model_id: str,
        parent_model_id: str,
        parent_checkpoint_id: str | None,
        generation: int,
        mutation: dict[str, Any] | None = None,
        inheritance_mode: str = "full_clone_mutation",
        episode_id: str | None = None,
    ) -> AgentMetaDTO:
        self._sync_from_runtime_bindings()
        child_model_id = str(child_model_id or "").strip()
        if not child_model_id:
            raise AgentServiceError("INVALID_MODEL_ID", "child_model_id is required")
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
            if str(getattr(agent, "type", "") or "") != "Model":
                raise AgentServiceError("AGENT_TYPE_UNSUPPORTED", f"agent is not a Model: {agent_id}")
            agent.model_id = child_model_id
            if episode_id is not None:
                agent.episode_id = str(episode_id)
            agent.params_version = int(getattr(agent, "params_version", 0) or 0) + 1
            agent.last_action = "inheritance"
            self._agents[agent_id] = agent
            self._runtime_agents.pop(agent_id, None)
        self._persist_runtime_agent_meta(
            agent_id,
            type="Model",
            model_id=child_model_id,
            parent_model_id=parent_model_id,
            parent_checkpoint_id=parent_checkpoint_id,
            generation=int(generation),
            mutation=mutation or {},
            inheritance_mode=inheritance_mode,
            episode_id=episode_id,
            params_version=agent.params_version,
            last_action="inheritance",
        )
        self._log.append(agent_id, f"Inherited model={child_model_id} from checkpoint={parent_checkpoint_id}")
        return agent

    def bind_model_episode(
        self,
        agent_id: str,
        *,
        episode_id: str | None,
        model_id: str | None = None,
        mode: str | None = None,
    ) -> AgentMetaDTO:
        self._sync_from_runtime_bindings()
        stale_runtime_agent = None
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
            if str(getattr(agent, "type", "") or "") != "Model":
                raise AgentServiceError("AGENT_TYPE_UNSUPPORTED", f"agent is not a Model: {agent_id}")
            if model_id is not None and str(model_id).strip():
                agent.model_id = str(model_id)
            if mode is not None and str(mode).strip():
                agent.mode = str(mode)
            agent.episode_id = str(episode_id) if episode_id is not None else None
            self._agents[agent_id] = agent
            stale_runtime_agent = self._runtime_agents.pop(agent_id, None)
        if stale_runtime_agent is not None:
            self._call_runtime_lifecycle(stale_runtime_agent, "stop", emit_state=False)
        self._persist_runtime_agent_meta(
            agent_id,
            type="Model",
            model_id=agent.model_id,
            mode=agent.mode,
            episode_id=agent.episode_id,
        )
        self._log.append(agent_id, f"Bound model episode={agent.episode_id}")
        return agent

    def complete_model_episode(self, agent_ids: List[str], *, episode_id: str | None = None) -> Dict[str, Any]:
        normalized_ids: List[str] = []
        seen: set[str] = set()
        for raw_id in agent_ids or []:
            agent_id = str(raw_id or "").strip()
            if agent_id and agent_id not in seen:
                normalized_ids.append(agent_id)
                seen.add(agent_id)
        if not normalized_ids:
            return {"success_ids": [], "failed": []}

        self._sync_from_runtime_bindings(force=True)
        success: List[str] = []
        failed: List[Dict[str, str]] = []
        meta_updates: Dict[str, Dict[str, Any]] = {}

        for agent_id in normalized_ids:
            with self._lock:
                agent = self._agents.get(agent_id)
                runtime_agent = self._runtime_agents.get(agent_id)
            if agent is None:
                failed.append({"agent_id": agent_id, "error": "AGENT_NOT_FOUND"})
                continue
            if str(getattr(agent, "type", "") or "") != "Model":
                failed.append({"agent_id": agent_id, "error": "AGENT_TYPE_UNSUPPORTED"})
                continue
            try:
                complete = getattr(runtime_agent, "complete_episode", None)
                if callable(complete):
                    try:
                        complete(episode_id=episode_id)
                    except TypeError:
                        complete()
                with self._lock:
                    current = self._agents.get(agent_id)
                    if current is not None:
                        current.episode_id = None
                        self._agents[agent_id] = current
                meta_updates[agent_id] = {"episode_id": None}
                self._log.append(agent_id, f"Completed model episode={episode_id or '-'}")
                success.append(agent_id)
            except Exception as exc:
                failed.append({"agent_id": agent_id, "error": str(exc)})
        self._persist_runtime_agent_meta_bulk(meta_updates)
        return {"success_ids": success, "failed": failed}

    def control(self, agent_id: str, action: ActionType) -> AgentMetaDTO:
        self._sync_from_runtime_bindings(force=True)
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
        runtime_agent = self._ensure_runtime_agent(agent_id, agent=agent)
        now = int(time.time() * 1000)
        if action == "start":
            run_id = self._active_runtime_run_id()
            if run_id:
                self._persist_runtime_agent_meta(agent_id, run_id=run_id)
            if runtime_agent is not None:
                self._call_runtime_lifecycle(runtime_agent, "start", emit_state=False)
            with self._lock:
                current = self._agents.get(agent_id)
            heartbeat_ms = (
                current.last_heartbeat
                if current and current.status == "RUNNING" and current.last_heartbeat is not None
                else now
            )
            self._apply_runtime_state(
                agent_id,
                status="RUNNING",
                heartbeat_ms=heartbeat_ms,
                start_time_ms=(current.start_time if current and current.start_time is not None else now),
                emit_event=True,
            )
        elif action == "pause":
            if runtime_agent is not None:
                self._call_runtime_lifecycle(runtime_agent, "pause", emit_state=False)
            with self._lock:
                current = self._agents.get(agent_id)
            heartbeat_ms = (
                current.last_heartbeat
                if current and current.status == "PAUSED" and current.last_heartbeat is not None
                else now
            )
            self._apply_runtime_state(
                agent_id,
                status="PAUSED",
                heartbeat_ms=heartbeat_ms,
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

    def control_many(self, agent_ids: List[str], action: ActionType) -> Dict[str, Any]:
        """Apply one lifecycle action to many agents with a single binding sync.

        The UI can select dozens of rows. Calling ``control`` in a loop is much
        more expensive than the action itself because each call rehydrates all
        persisted bindings. This method keeps the single-agent semantics but
        amortizes the sync and avoids duplicate RUNNING/PAUSED persistence when
        runtime agents already emit their state through callbacks.
        """
        normalized_ids: List[str] = []
        seen: set[str] = set()
        for raw_id in agent_ids or []:
            agent_id = str(raw_id or "").strip()
            if agent_id and agent_id not in seen:
                normalized_ids.append(agent_id)
                seen.add(agent_id)
        if not normalized_ids:
            return {"success_ids": [], "failed": [], "action": action}
        if action not in {"start", "pause", "stop"}:
            raise AgentServiceError("INVALID_ACTION", str(action))

        self._sync_from_runtime_bindings(force=True)
        now = int(time.time() * 1000)
        run_id = self._active_runtime_run_id() if action == "start" else None
        success: List[str] = []
        failed: List[Dict[str, str]] = []
        meta_updates: Dict[str, Dict[str, Any]] = {}

        for agent_id in normalized_ids:
            with self._lock:
                agent = self._agents.get(agent_id)
            if agent is None:
                failed.append({"agent_id": agent_id, "error": "AGENT_NOT_FOUND"})
                continue
            try:
                runtime_agent = self._ensure_runtime_agent(agent_id, agent=agent)
                if action == "start":
                    if runtime_agent is not None:
                        self._call_runtime_lifecycle(runtime_agent, "start", emit_state=False)
                    start_time_ms = agent.start_time if agent.start_time is not None else now
                    self._apply_runtime_state(
                        agent_id,
                        status="RUNNING",
                        heartbeat_ms=now,
                        start_time_ms=start_time_ms,
                        emit_event=True,
                        persist=False,
                    )
                    meta_updates[agent_id] = {
                        "run_id": run_id,
                        "status": "RUNNING",
                        "last_heartbeat": now,
                        "start_time": start_time_ms,
                    }
                elif action == "pause":
                    if runtime_agent is not None:
                        self._call_runtime_lifecycle(runtime_agent, "pause", emit_state=False)
                    self._apply_runtime_state(
                        agent_id,
                        status="PAUSED",
                        heartbeat_ms=now,
                        emit_event=True,
                        persist=False,
                    )
                    meta_updates[agent_id] = {"status": "PAUSED", "last_heartbeat": now}
                else:
                    if runtime_agent is not None:
                        self._stop_runtime_agent_async(agent_id, runtime_agent)
                    self._apply_runtime_state(
                        agent_id,
                        status="STOPPED",
                        heartbeat_ms=None,
                        emit_event=True,
                        persist=False,
                    )
                    meta_updates[agent_id] = {"status": "STOPPED", "last_heartbeat": None}
                metrics.inc(f"agent_control_action_{action}")
                self._log.append(agent_id, f"Control action={action}")
                success.append(agent_id)
            except Exception as exc:
                failed.append({"agent_id": agent_id, "error": str(exc)})
        self._persist_runtime_agent_meta_bulk(meta_updates)
        return {"success_ids": success, "failed": failed, "action": action}

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

        if self._uses_default_account_bootstrapper:
            self._bootstrap_runtime_accounts_bulk(created, initial_cash)
        else:
            for account_id in pending_account_bootstrap:
                try:
                    self._account_bootstrapper(account_id, initial_cash)
                except Exception:
                    pass
        for account_id in pending_account_bootstrap:
            try:
                _publish_account_created(
                    {
                        "account_id": account_id,
                        "initial_cash": initial_cash,
                    }
                )
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

    def create_model_agent(
        self,
        *,
        agent_id: str | None = None,
        model_id: str = "hold_model_v1",
        name: str | None = None,
        mode: str = "inference",
        initial_cash: float = DEFAULT_MODEL_INITIAL_CASH,
        episode_id: str | None = None,
    ) -> AgentMetaDTO:
        model_id = str(model_id or "hold_model_v1").strip() or "hold_model_v1"
        mode = str(mode or "inference").strip() or "inference"
        with self._lock:
            if agent_id is None:
                self._model_counter += 1
                agent_id = f"MODEL{self._model_counter:04d}"
            agent_id = str(agent_id).strip()
            if not agent_id:
                raise AgentServiceError("INVALID_AGENT_ID", "agent_id is required")
            if agent_id in self._agents:
                raise AgentServiceError("AGENT_ALREADY_EXISTS", f"agent already exists: {agent_id}")
            meta = _synthetic_factory(
                agent_id=agent_id,
                name=name or agent_id,
                a_type="Model",
                model_id=model_id,
                mode=mode,
                episode_id=episode_id,
            )
            self._agents[agent_id] = meta
        try:
            self._account_bootstrapper(agent_id, float(initial_cash))
            _publish_account_created(
                {
                    "account_id": agent_id,
                    "initial_cash": float(initial_cash),
                }
            )
        except Exception:
            pass
        self._persist_runtime_agent_meta(
            agent_id,
            type="Model",
            name=name or agent_id,
            model_id=model_id,
            mode=mode,
            episode_id=episode_id,
            params_version=0,
        )
        self._log.generate_initial(agent_id)
        return meta

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
        if resolved is None:
            return None
        agent_type = str(getattr(resolved, "type", "") or "")
        if agent_type == "Model":
            try:
                runtime_agent = self._model_agent_factory(
                    agent_id=agent_id,
                    model_id=str(getattr(resolved, "model_id", None) or "hold_model_v1"),
                    mode=str(getattr(resolved, "mode", None) or "inference"),
                    episode_id=getattr(resolved, "episode_id", None),
                    runtime_gateway=self._runtime_gateway,
                    state_callback=self._on_runtime_state,
                    metrics_callback=self._on_model_metrics,
                )
            except Exception:
                runtime_agent = None
            if runtime_agent is not None:
                with self._lock:
                    self._runtime_agents[agent_id] = runtime_agent
            return runtime_agent
        if agent_type != "Retail":
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

    def _default_model_agent_factory(
        self,
        *,
        agent_id: str,
        model_id: str,
        mode: str,
        episode_id: str | None = None,
        runtime_gateway: RuntimeGateway,
        state_callback: Callable[..., None] | None = None,
        metrics_callback: Callable[[str, Dict[str, Any]], None] | None = None,
    ) -> Any:
        if RuntimeModelAgent is None:
            return None
        registry = ModelRegistryService() if ModelRegistryService is not None else None
        return RuntimeModelAgent(
            agent_id=agent_id,
            model_id=model_id,
            mode=mode,
            episode_id=episode_id,
            runtime_gateway=runtime_gateway,
            state_callback=state_callback or self._on_runtime_state,
            metrics_callback=metrics_callback or self._on_model_metrics,
            registry=registry,
        )

    @staticmethod
    def _call_runtime_lifecycle(runtime_agent: Any, method_name: str, *, emit_state: bool) -> None:
        method = getattr(runtime_agent, method_name, None)
        if not callable(method):
            return
        try:
            method(emit_state=emit_state)
        except TypeError:
            method()

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

    def _bootstrap_runtime_accounts_bulk(self, agents: List[AgentMetaDTO], initial_cash: float) -> None:
        if not agents:
            return
        try:
            from stock_sim.persistence.models_imports import SessionLocal
            from stock_sim.persistence.models_account import Account
            from stock_sim.persistence.models_agent_binding import AgentBinding
            from stock_sim.persistence import models_init
        except Exception:  # pragma: no cover
            try:
                from persistence.models_imports import SessionLocal  # type: ignore
                from persistence.models_account import Account  # type: ignore
                from persistence.models_agent_binding import AgentBinding  # type: ignore
                from persistence import models_init  # type: ignore
            except Exception:
                for meta in agents:
                    try:
                        self._bootstrap_runtime_account(meta.agent_id, initial_cash)
                    except Exception:
                        pass
                return

        try:
            ensure = getattr(models_init, "ensure_models", None)
            ensure() if callable(ensure) else models_init.init_models()
            run_id = self._runtime_gateway.ensure_desktop_run()
            session = SessionLocal()
        except Exception:
            for meta in agents:
                try:
                    self._bootstrap_runtime_account(meta.agent_id, initial_cash)
                except Exception:
                    pass
            return
        try:
            import json

            agent_ids = [meta.agent_id for meta in agents]
            existing_accounts = {
                row[0]
                for row in session.query(Account.id).filter(Account.id.in_(agent_ids)).all()
            }
            existing_bindings = {
                row.agent_name: row
                for row in session.query(AgentBinding).filter(AgentBinding.agent_name.in_(agent_ids)).all()
            }
            for meta in agents:
                if meta.agent_id not in existing_accounts:
                    session.add(Account(id=meta.agent_id, cash=float(initial_cash)))
                binding_meta = {
                    "name": meta.name or meta.agent_id,
                    "initial_cash": float(initial_cash),
                    "strategy": getattr(meta, "strategy", None),
                    "type": meta.type,
                    "status": "STOPPED",
                    "params_version": int(getattr(meta, "params_version", 0) or 0),
                    "start_time": None,
                    "last_heartbeat": None,
                    "run_id": run_id,
                }
                row = existing_bindings.get(meta.agent_id)
                if row is None:
                    session.add(
                        AgentBinding(
                            agent_name=meta.agent_id,
                            agent_type=str(meta.type or "GENERIC").upper(),
                            account_id=meta.agent_id,
                            run_id=run_id,
                            meta=json.dumps(binding_meta, ensure_ascii=False),
                        )
                    )
                else:
                    row.agent_type = str(meta.type or "GENERIC").upper()
                    row.account_id = meta.agent_id
                    row.run_id = run_id
                    row.meta = json.dumps(binding_meta, ensure_ascii=False)
                    row.touch()
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            for meta in agents:
                try:
                    self._bootstrap_runtime_account(meta.agent_id, initial_cash)
                except Exception:
                    pass
        finally:
            try:
                session.close()
            except Exception:
                pass
        try:
            self._runtime_gateway.allocate_pending_ipo_distributions_if_running()
        except Exception:
            pass

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

    def _sync_from_runtime_bindings(self, *, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and (now - self._last_runtime_sync_ts) < self._runtime_sync_min_interval_s:
                return
            self._last_runtime_sync_ts = now
        rows = self._runtime_binding_rows()
        if not rows:
            return
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
                model_id = meta.get("model_id")
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
                        model_id=(str(model_id) if model_id is not None and str(model_id).strip() else None),
                        mode=(str(meta.get("mode")) if meta.get("mode") is not None and str(meta.get("mode")).strip() else None),
                        episode_id=(str(meta.get("episode_id")) if meta.get("episode_id") is not None and str(meta.get("episode_id")).strip() else None),
                        last_reward=self._maybe_float(meta.get("last_reward")),
                        equity=self._maybe_float(meta.get("equity")),
                        pnl=self._maybe_float(meta.get("pnl")),
                        last_action=(str(meta.get("last_action")) if meta.get("last_action") is not None and str(meta.get("last_action")).strip() else None),
                    )
                    if agent_type == "Retail":
                        self._remember_retail_name(agent_id)
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
                if model_id is not None and str(model_id).strip():
                    current.model_id = str(model_id)
                if "episode_id" in meta:
                    raw_episode_id = meta.get("episode_id")
                    current.episode_id = (
                        str(raw_episode_id)
                        if raw_episode_id is not None and str(raw_episode_id).strip()
                        else None
                    )
                for attr in ("mode", "last_action"):
                    value = meta.get(attr)
                    if value is not None and str(value).strip():
                        setattr(current, attr, str(value))
                for attr in ("last_reward", "equity", "pnl"):
                    value = self._maybe_float(meta.get(attr))
                    if value is not None:
                        setattr(current, attr, value)
                if meta.get("params_version") is not None:
                    try:
                        current.params_version = int(meta.get("params_version") or 0)
                    except Exception:
                        pass
                self._agents[agent_id] = current
                if agent_type == "Retail":
                    self._remember_retail_name(agent_id)

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
        persist: bool = True,
    ) -> None:
        payload: Dict[str, Any] | None = None
        persist_state = False
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            previous_status = agent.status
            if status is not None:
                agent.status = status  # type: ignore[assignment]
            if start_time_ms is not None and agent.start_time is None:
                agent.start_time = start_time_ms
            if heartbeat_ms is not None:
                agent.last_heartbeat = heartbeat_ms
            self._agents[agent_id] = agent
            now_ms = heartbeat_ms or int(time.time() * 1000)
            last_persist_ms = self._last_state_persist_ms.get(agent_id, 0)
            persist_state = (
                emit_event
                or heartbeat_ms is None
                or (status is not None and status != previous_status)
                or (now_ms - last_persist_ms) >= self._heartbeat_persist_interval_ms
            )
            if persist_state:
                self._last_state_persist_ms[agent_id] = now_ms
            if emit_event:
                payload = {
                    "agent_id": agent.agent_id,
                    "status": agent.status,
                    "last_heartbeat": agent.last_heartbeat,
                    "start_time": agent.start_time,
                }
        if payload is not None:
            try:
                _publish_agent_status_changed(payload)
            except Exception:
                pass
        if persist and persist_state:
            self._persist_runtime_agent_meta(
                agent_id,
                status=status,
                start_time=start_time_ms,
                last_heartbeat=heartbeat_ms,
            )

    def _on_model_metrics(self, agent_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            if payload.get("model_id") is not None:
                agent.model_id = str(payload.get("model_id"))
            if payload.get("mode") is not None:
                agent.mode = str(payload.get("mode"))
            if "episode_id" in payload:
                raw_episode_id = payload.get("episode_id")
                agent.episode_id = str(raw_episode_id) if raw_episode_id is not None else None
            if payload.get("last_action") is not None:
                agent.last_action = str(payload.get("last_action"))
            if payload.get("last_reward") is not None:
                agent.last_reward = self._maybe_float(payload.get("last_reward"))
            if payload.get("equity") is not None:
                agent.equity = self._maybe_float(payload.get("equity"))
            if payload.get("pnl") is not None:
                agent.pnl = self._maybe_float(payload.get("pnl"))
            self._agents[agent_id] = agent
        self._persist_runtime_agent_meta(
            agent_id,
            model_id=payload.get("model_id"),
            mode=payload.get("mode"),
            episode_id=payload.get("episode_id"),
            last_action=payload.get("last_action"),
            last_reward=payload.get("last_reward"),
            equity=payload.get("equity"),
            pnl=payload.get("pnl"),
        )

    def _persist_runtime_agent_meta(self, agent_id: str, **updates: Any) -> None:
        updater = getattr(self._runtime_gateway, "update_agent_binding_meta", None)
        if not callable(updater):
            return
        try:
            updater(agent_id, **updates)
        except Exception:
            pass

    def _persist_runtime_agent_meta_bulk(self, updates_by_agent: Dict[str, Dict[str, Any]]) -> None:
        if not updates_by_agent:
            return
        try:
            from stock_sim.persistence.models_imports import SessionLocal
            from stock_sim.persistence.models_agent_binding import AgentBinding
        except Exception:  # pragma: no cover
            try:
                from persistence.models_imports import SessionLocal  # type: ignore
                from persistence.models_agent_binding import AgentBinding  # type: ignore
            except Exception:
                for agent_id, updates in updates_by_agent.items():
                    self._persist_runtime_agent_meta(agent_id, **updates)
                return
        try:
            import json

            session = SessionLocal()
        except Exception:
            for agent_id, updates in updates_by_agent.items():
                self._persist_runtime_agent_meta(agent_id, **updates)
            return
        try:
            rows = (
                session.query(AgentBinding)
                .filter(AgentBinding.agent_name.in_(list(updates_by_agent.keys())))
                .all()
            )
            for row in rows:
                agent_id = str(row.agent_name)
                updates = updates_by_agent.get(agent_id) or {}
                try:
                    merged = json.loads(row.meta) if row.meta else {}
                    if not isinstance(merged, dict):
                        merged = {}
                except Exception:
                    merged = {}
                for key, value in updates.items():
                    if value is None and key not in {"start_time", "last_heartbeat", "episode_id"}:
                        continue
                    merged[key] = value
                run_id = str(merged.get("run_id") or "").strip()
                if run_id:
                    row.run_id = run_id
                row.meta = json.dumps(merged, ensure_ascii=False)
                row.touch()
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            for agent_id, updates in updates_by_agent.items():
                self._persist_runtime_agent_meta(agent_id, **updates)
        finally:
            try:
                session.close()
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
    def _maybe_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _normalize_status(value: object, *, fallback: str = "STOPPED") -> str:
        raw = str(value or "").strip().upper()
        if raw in {"RUNNING", "PAUSED", "STOPPED", "INACTIVE"}:
            return raw
        return fallback

    def _remember_retail_name(self, agent_id: str) -> None:
        text = str(agent_id or "").strip().lower()
        if not text:
            return
        idx = len(text)
        while idx > 0 and text[idx - 1].isdigit():
            idx -= 1
        if idx == len(text):
            return
        prefix = text[:idx].strip()
        suffix = text[idx:].strip()
        if not prefix or not suffix:
            return
        try:
            value = int(suffix)
        except Exception:
            return
        self._retail_counters[prefix] = max(self._retail_counters.get(prefix, 0), value)


def _synthetic_factory(
    *,
    agent_id: str,
    name: str,
    a_type: str,
    strategy: str | None = None,
    model_id: str | None = None,
    mode: str | None = None,
    episode_id: str | None = None,
) -> AgentMetaDTO:
    return AgentMetaDTO(
        agent_id=agent_id,
        name=name,
        type=a_type,
        status="STOPPED",
        start_time=None,
        last_heartbeat=None,
        params_version=0,
        strategy=strategy,
        model_id=model_id,
        mode=mode,
        episode_id=episode_id,
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
    if upper == "MODEL":
        return "Model"
    return raw


__all__ = [
    "AgentService",
    "AgentServiceError",
    "BatchCreateConfig",
    "BATCH_ALLOWED_TYPES",
]
