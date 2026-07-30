"""Logic panel for training Arena control and observability."""
from __future__ import annotations

from threading import RLock
from typing import Any

from app.services.evidence_board_service import build_evidence_board
from app.services.arena_experiment_runner import ArenaExperimentConfig, ArenaExperimentRunner
from app.services.training_arena_service import ArenaModelSpec, TrainingArenaConfig, TrainingArenaService

__all__ = ["ArenaPanel"]

_DEFAULT_MODEL_IDS = ("hold_model_v1", "random_weight_v1")
_DEFAULT_SYMBOLS = ("001", "002")
_DEFAULT_EXPERIMENT_SYMBOLS = ("001", "002", "003")
_DEFAULT_MODEL_INITIAL_CASH = 50_000_000.0


class ArenaPanel:
    """Thin frontend-facing wrapper around TrainingArenaService.

    The panel owns UI selection state only. Episode creation, agent lifecycle,
    ranking, and persistence stay in the service layer.
    """

    def __init__(
        self,
        arena_service: TrainingArenaService,
        *,
        experiment_runner: ArenaExperimentRunner | None = None,
    ):
        self._service = arena_service
        self._experiment_runner = experiment_runner
        self._lock = RLock()
        self._selected_arena_id: str | None = None
        self._last_error: str | None = None
        self._last_experiment_report: dict[str, Any] | None = None
        self._experiment_running = False

    def create_arena(
        self,
        *,
        arena_id: str | None = None,
        model_specs: list[ArenaModelSpec | dict[str, Any]] | None = None,
        retail_count: int = 100,
        symbols: list[str] | None = None,
        generation: int = 0,
        episode_prefix: str = "episode",
        reward_profile: str = "relative_equity_risk_adjusted_v1",
    ) -> dict[str, Any]:
        try:
            specs = self._coerce_model_specs(model_specs)
            cfg = TrainingArenaConfig(
                arena_id=arena_id,
                model_specs=specs,
                retail_count=max(0, int(retail_count or 0)),
                symbols=list(symbols or _DEFAULT_SYMBOLS),
                generation=max(0, int(generation or 0)),
                episode_prefix=str(episode_prefix or "episode"),
                reward_profile=str(reward_profile or "relative_equity_risk_adjusted_v1"),
            )
            state = self._service.create_arena(cfg)
            with self._lock:
                self._selected_arena_id = state.get("arena_id")
                self._last_error = None
            return state
        except Exception as exc:
            self._set_error(exc)
            raise

    def select_arena(self, arena_id: str | None) -> None:
        with self._lock:
            self._selected_arena_id = arena_id or None
            self._last_error = None

    def start_arena(self, arena_id: str | None = None, *, episode_id: str | None = None) -> dict[str, Any]:
        arena_id = self._resolve_arena_id(arena_id)
        try:
            state = self._service.start_arena(arena_id, episode_id=episode_id)
            with self._lock:
                self._selected_arena_id = state.get("arena_id")
                self._last_error = None
            return state
        except Exception as exc:
            self._set_error(exc)
            raise

    def stop_arena(self, arena_id: str | None = None) -> dict[str, Any]:
        arena_id = self._resolve_arena_id(arena_id)
        try:
            state = self._service.stop_arena(arena_id)
            with self._lock:
                self._selected_arena_id = state.get("arena_id")
                self._last_error = None
            return state
        except Exception as exc:
            self._set_error(exc)
            raise

    def evaluate_arena(
        self,
        arena_id: str | None = None,
        *,
        complete_episode: bool = True,
    ) -> dict[str, Any]:
        arena_id = self._resolve_arena_id(arena_id)
        try:
            state = self._service.evaluate_arena(arena_id, complete_episode=complete_episode)
            with self._lock:
                self._selected_arena_id = state.get("arena_id")
                self._last_error = None
            return state
        except Exception as exc:
            self._set_error(exc)
            raise

    def run_experiment(
        self,
        *,
        arena_id: str | None = None,
        episode_id: str | None = None,
        duration_seconds: float = 30.0,
        retail_count: int = 100,
        symbols: list[str] | None = None,
        instrument_prices: list[float] | None = None,
        generation: int = 0,
        model_specs: list[ArenaModelSpec | dict[str, Any]] | None = None,
        run_pbt: bool = True,
        apply_inheritance: bool = False,
    ) -> dict[str, Any]:
        if self._experiment_runner is None:
            raise RuntimeError("arena experiment runner is not available")
        with self._lock:
            if self._experiment_running:
                raise RuntimeError("arena experiment is already running")
            self._experiment_running = True
            self._last_error = None
        try:
            experiment_symbols = list(symbols or _DEFAULT_EXPERIMENT_SYMBOLS)
            self._ensure_experiment_instruments(experiment_symbols, instrument_prices)
            cfg = ArenaExperimentConfig(
                arena_id=arena_id,
                episode_id=episode_id,
                generation=max(0, int(generation or 0)),
                symbols=experiment_symbols,
                retail_count=max(0, int(retail_count or 0)),
                model_specs=self._coerce_experiment_model_specs(model_specs),
                duration_seconds=max(0.0, float(duration_seconds or 0.0)),
                run_pbt=bool(run_pbt),
                apply_inheritance=bool(apply_inheritance),
            )
            report = self._experiment_runner.run(cfg)
            with self._lock:
                self._selected_arena_id = str(report.get("arena_id") or "") or self._selected_arena_id
                self._last_experiment_report = report
                self._last_error = None
            return report
        except Exception as exc:
            self._set_error(exc)
            raise
        finally:
            with self._lock:
                self._experiment_running = False

    def _ensure_experiment_instruments(
        self,
        symbols: list[str],
        prices: list[float] | None,
    ) -> None:
        if not prices or self._experiment_runner is None:
            return
        gateway = getattr(self._experiment_runner, "_runtime_gateway", None)
        creator = getattr(gateway, "create_instrument", None)
        restorer = getattr(gateway, "restore_runtime_instruments", None)
        if not callable(creator):
            return
        for idx, symbol in enumerate(symbols):
            try:
                price = float(prices[idx])
            except Exception:
                continue
            if price <= 0:
                continue
            try:
                creator(
                    symbol=str(symbol),
                    name=f"Arena Demo {symbol}",
                    price_step=0.01,
                    initial_price=price,
                    float_shares=100_000_000,
                    market_cap=price * 100_000_000,
                    total_shares=100_000_000,
                )
            except Exception:
                pass
        if callable(restorer):
            try:
                restorer()
            except Exception:
                pass

    def get_view(self) -> dict[str, Any]:
        with self._lock:
            selected_id = self._selected_arena_id
            last_error = self._last_error
            last_experiment_report = self._last_experiment_report
            experiment_running = self._experiment_running
        arenas = list(self._service.list_arenas())
        if selected_id is None and arenas:
            selected_id = arenas[-1].get("arena_id")
        selected = next((row for row in arenas if row.get("arena_id") == selected_id), None)
        rows = [self._arena_row(row) for row in arenas]
        leaderboard = self._leaderboard_rows(selected)
        controls = self._controls(selected)
        controls["can_run_experiment"] = self._experiment_runner is not None and not experiment_running
        return {
            "arena": {
                "selected": selected_id,
                "total": len(rows),
                "items": rows,
            },
            "selected": selected,
            "summary": (selected or {}).get("last_summary") if isinstance(selected, dict) else None,
            "leaderboard": leaderboard,
            "controls": controls,
            "experiment": self._experiment_view(
                last_experiment_report,
                running=experiment_running,
                available=self._experiment_runner is not None,
            ),
            "error": last_error,
        }

    def _resolve_arena_id(self, arena_id: str | None) -> str:
        if arena_id:
            return arena_id
        with self._lock:
            selected = self._selected_arena_id
        if selected:
            return selected
        arenas = self._service.list_arenas()
        if arenas:
            return str(arenas[-1]["arena_id"])
        raise ValueError("no arena selected")

    def _set_error(self, exc: Exception) -> None:
        with self._lock:
            self._last_error = str(exc)

    @staticmethod
    def _coerce_model_specs(
        model_specs: list[ArenaModelSpec | dict[str, Any]] | None,
    ) -> list[ArenaModelSpec]:
        if not model_specs:
            return [ArenaModelSpec(model_id=model_id) for model_id in _DEFAULT_MODEL_IDS]
        specs: list[ArenaModelSpec] = []
        for item in model_specs:
            if isinstance(item, ArenaModelSpec):
                specs.append(item)
                continue
            specs.append(
                ArenaModelSpec(
                    agent_id=item.get("agent_id"),
                    model_id=str(item.get("model_id") or "hold_model_v1"),
                    mode=str(item.get("mode") or "collect_only"),
                    initial_cash=float(item.get("initial_cash", _DEFAULT_MODEL_INITIAL_CASH) or _DEFAULT_MODEL_INITIAL_CASH),
                )
            )
        return specs

    @staticmethod
    def _coerce_experiment_model_specs(
        model_specs: list[ArenaModelSpec | dict[str, Any]] | None,
    ) -> list[ArenaModelSpec]:
        if not model_specs:
            return list(ArenaExperimentConfig().model_specs)
        return ArenaPanel._coerce_model_specs(model_specs)

    @staticmethod
    def _arena_row(row: dict[str, Any]) -> dict[str, Any]:
        model_ids = list(row.get("model_agent_ids") or [])
        retail_ids = list(row.get("retail_agent_ids") or [])
        symbols = list(row.get("symbols") or [])
        return {
            "arena_id": row.get("arena_id"),
            "status": row.get("status"),
            "episode_id": row.get("current_episode_id"),
            "generation": row.get("generation", 0),
            "model_count": len(model_ids),
            "retail_count": len(retail_ids),
            "symbols": symbols,
            "models": model_ids,
            "retail_agents": retail_ids,
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _leaderboard_rows(selected: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not selected:
            return []
        summary = selected.get("last_summary") or {}
        results = summary.get("results") if isinstance(summary, dict) else []
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(results or [], start=1):
            metrics = item.get("metrics") or item.get("metrics_json") or {}
            out.append(
                {
                    "rank": item.get("rank", idx),
                    "agent_id": item.get("agent_id"),
                    "model_id": item.get("model_id"),
                    "score": item.get("score"),
                    "equity_return": item.get("equity_return"),
                    "reward_total": item.get("reward_total"),
                    "submitted": int(metrics.get("submitted_order_count", 0) or 0),
                    "filled": int(metrics.get("filled_order_count", 0) or 0),
                    "rejected": int(metrics.get("rejected_order_count", 0) or 0),
                    "noop": int(metrics.get("noop_count", 0) or 0),
                    "rejected_reason": _format_rejected_reason(metrics),
                    "trade_count": item.get("trade_count"),
                    "max_drawdown": item.get("max_drawdown"),
                    "metrics": metrics,
                }
            )
        return out

    @staticmethod
    def _controls(selected: dict[str, Any] | None) -> dict[str, bool]:
        status = (selected or {}).get("status")
        has_selected = bool(selected)
        has_episode = bool((selected or {}).get("current_episode_id"))
        return {
            "can_create": True,
            "can_start": has_selected and status not in {"RUNNING", "EVALUATING"},
            "can_stop": has_selected and status == "RUNNING",
            "can_evaluate": has_selected and has_episode and status in {"RUNNING", "READY", "STOPPED"},
        }

    @staticmethod
    def _experiment_view(
        report: dict[str, Any] | None,
        *,
        running: bool,
        available: bool,
    ) -> dict[str, Any]:
        episode = (report or {}).get("episode") or {}
        pbt = (report or {}).get("pbt") or {}
        return {
            "available": bool(available),
            "running": bool(running),
            "report_path": (report or {}).get("report_path"),
            "arena_id": (report or {}).get("arena_id"),
            "episode_id": (report or {}).get("episode_id"),
            "transition_count": episode.get("transition_count", 0),
            "result_count": len(episode.get("results") or []),
            "pbt_checkpoint_count": len(pbt.get("checkpoints") or []),
            "pbt_lineage_count": len(pbt.get("lineage") or []),
            "top_results": list((episode.get("results") or [])[:5]),
            "evidence_board": build_evidence_board(_series_evidence_aggregate(report or {})),
        }


def _series_evidence_aggregate(report: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(report.get("series_evidence_aggregate"), dict):
        return report.get("series_evidence_aggregate")
    if isinstance(report.get("evidence_aggregate"), dict):
        return report.get("evidence_aggregate")
    aggregate = report.get("aggregate") if isinstance(report.get("aggregate"), dict) else {}
    if isinstance(aggregate.get("series_evidence"), dict):
        return aggregate.get("series_evidence")
    return None


def _format_rejected_reason(metrics: dict[str, Any]) -> str:
    explicit = str(metrics.get("rejected_reason_summary") or metrics.get("last_rejected_reason") or "").strip()
    if explicit:
        return explicit
    reasons = metrics.get("rejected_reasons")
    if not isinstance(reasons, dict) or not reasons:
        return ""
    ranked = sorted(
        ((str(reason), int(count or 0)) for reason, count in reasons.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return ", ".join(f"{reason} x{count}" for reason, count in ranked[:3] if count > 0)
