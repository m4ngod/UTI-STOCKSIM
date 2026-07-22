"""Anchored, node-driven Strategy Runs over immutable market paths."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Callable, Final, Literal, Protocol, cast

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from .market_paths import (
    MarketPathNode,
    MaterializedMarketPath,
    ScenarioMarketSnapshot,
    ScenarioMarketView,
)


STRATEGY_RUN_ENGINE_VERSION: Final = "anchored-strategy-run.v1"
BASELINE_EXECUTION_POLICY_VERSION: Final = "private-ledger-baseline.v1"
REFERENCE_STRATEGY_ID: Final = "anchored-ranked-candidate-reference"
REFERENCE_STRATEGY_VERSION: Final = "anchored-ranked-candidate-reference.v1"

StrategyRunStatus = Literal[
    "running",
    "paused",
    "completed",
    "cancelled",
    "failed",
]
OrderStatus = Literal["queued", "filled", "rejected"]


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class StrategyRunSpecification:
    """Immutable inputs pinned into one deterministic Strategy Run identity."""

    recipe_version_id: str
    recipe_content_hash: str
    materialization_hash: str
    source_snapshot_id: str
    materialization_seed: int
    transformation_catalog_version: str
    transformation_implementation_versions: tuple[str, ...]
    market_rule_profile_version: str
    execution_policy_version: str
    strategy_id: str
    strategy_version: str
    decision_cadence_minutes: int
    initial_cash: Decimal
    order_shares: int
    replica_id: str
    code_identity: str
    engine_version: str = STRATEGY_RUN_ENGINE_VERSION

    def __post_init__(self) -> None:
        if self.decision_cadence_minutes not in (30, 60):
            raise ValueError("decision cadence must be 30 or 60 Simulation Time minutes")
        if self.initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        if self.order_shares <= 0:
            raise ValueError("reference strategy order shares must be positive")
        required_text = (
            self.recipe_version_id,
            self.recipe_content_hash,
            self.materialization_hash,
            self.source_snapshot_id,
            self.transformation_catalog_version,
            self.market_rule_profile_version,
            self.execution_policy_version,
            self.strategy_id,
            self.strategy_version,
            self.replica_id,
            self.code_identity,
            self.engine_version,
        )
        if any(not value.strip() for value in required_text):
            raise ValueError("strategy run identity fields must be non-empty")

    @property
    def run_id(self) -> str:
        return f"strategy-run-{_canonical_hash(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_version_id": self.recipe_version_id,
            "recipe_content_hash": self.recipe_content_hash,
            "materialization_hash": self.materialization_hash,
            "source_snapshot_id": self.source_snapshot_id,
            "materialization_seed": self.materialization_seed,
            "transformation_catalog_version": self.transformation_catalog_version,
            "transformation_implementation_versions": list(
                self.transformation_implementation_versions
            ),
            "market_rule_profile_version": self.market_rule_profile_version,
            "execution_policy_version": self.execution_policy_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "initial_cash": _decimal_text(self.initial_cash),
            "order_shares": self.order_shares,
            "replica_id": self.replica_id,
            "code_identity": self.code_identity,
            "engine_version": self.engine_version,
        }


@dataclass(frozen=True, slots=True)
class StrategyOrder:
    order_id: str
    instrument: str
    shares: int
    decision_time: datetime
    activation_time: datetime
    status: OrderStatus
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "instrument": self.instrument,
            "shares": self.shares,
            "decision_time": self.decision_time.isoformat(),
            "activation_time": self.activation_time.isoformat(),
            "status": self.status,
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True, slots=True)
class PrivateFill:
    fill_id: str
    order_id: str
    instrument: str
    shares: int
    price: Decimal
    gross_value: Decimal
    simulation_time: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "instrument": self.instrument,
            "shares": self.shares,
            "price": _decimal_text(self.price),
            "gross_value": _decimal_text(self.gross_value),
            "simulation_time": self.simulation_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    instrument: str
    shares: int
    average_cost: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "shares": self.shares,
            "average_cost": _decimal_text(self.average_cost),
            "market_price": _decimal_text(self.market_price),
            "market_value": _decimal_text(self.market_value),
            "unrealized_pnl": _decimal_text(self.unrealized_pnl),
        }


@dataclass(frozen=True, slots=True)
class EquityPoint:
    simulation_time: datetime
    cash: Decimal
    positions_value: Decimal
    equity: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "simulation_time": self.simulation_time.isoformat(),
            "cash": _decimal_text(self.cash),
            "positions_value": _decimal_text(self.positions_value),
            "equity": _decimal_text(self.equity),
        }


@dataclass(frozen=True, slots=True)
class StrategyRunSnapshot:
    run_id: str
    status: StrategyRunStatus
    specification: StrategyRunSpecification
    current_simulation_time: datetime | None
    processed_node_count: int
    total_node_count: int
    decision_times: tuple[datetime, ...]
    orders: tuple[StrategyOrder, ...]
    fills: tuple[PrivateFill, ...]
    cash: Decimal
    positions: tuple[PortfolioPosition, ...]
    equity_curve: tuple[EquityPoint, ...]
    failure_code: str | None
    failure_message: str | None
    run_artifact_hash: str | None

    @property
    def materialization_hash(self) -> str:
        return self.specification.materialization_hash

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "specification": self.specification.to_dict(),
            "materialization_hash": self.materialization_hash,
            "current_simulation_time": (
                self.current_simulation_time.isoformat()
                if self.current_simulation_time is not None
                else None
            ),
            "processed_node_count": self.processed_node_count,
            "total_node_count": self.total_node_count,
            "decision_times": [item.isoformat() for item in self.decision_times],
            "orders": [item.to_dict() for item in self.orders],
            "fills": [item.to_dict() for item in self.fills],
            "portfolio": {
                "cash": _decimal_text(self.cash),
                "positions": [item.to_dict() for item in self.positions],
            },
            "equity_curve": [item.to_dict() for item in self.equity_curve],
            "failure": (
                {
                    "code": self.failure_code,
                    "message": self.failure_message,
                }
                if self.failure_code is not None
                else None
            ),
            "run_artifact_hash": self.run_artifact_hash,
        }


@dataclass(frozen=True, slots=True)
class _LedgerPosition:
    instrument: str
    shares: int
    total_cost: Decimal


@dataclass(frozen=True, slots=True)
class _StrategyRunState:
    specification: StrategyRunSpecification
    status: StrategyRunStatus
    next_node_index: int
    decision_times: tuple[datetime, ...]
    orders: tuple[StrategyOrder, ...]
    fills: tuple[PrivateFill, ...]
    cash: Decimal
    positions: tuple[_LedgerPosition, ...]
    equity_curve: tuple[EquityPoint, ...]
    current_simulation_time: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    run_artifact_hash: str | None = None


class StrategyRunRepository(Protocol):
    def add(self, state: _StrategyRunState) -> None: ...

    def get(self, run_id: str) -> _StrategyRunState: ...

    def save(self, state: _StrategyRunState) -> None: ...


class InMemoryStrategyRunRepository:
    def __init__(self) -> None:
        self._states: dict[str, _StrategyRunState] = {}

    def add(self, state: _StrategyRunState) -> None:
        run_id = state.specification.run_id
        if run_id in self._states:
            raise ValueError(f"Strategy Run {run_id!r} already exists")
        self._states[run_id] = state

    def get(self, run_id: str) -> _StrategyRunState:
        try:
            return self._states[run_id]
        except KeyError as error:
            raise KeyError(f"Unknown Strategy Run {run_id!r}") from error

    def save(self, state: _StrategyRunState) -> None:
        run_id = state.specification.run_id
        if run_id not in self._states:
            raise KeyError(f"Unknown Strategy Run {run_id!r}")
        self._states[run_id] = state


class SqlStrategyRunRepository:
    """Durable run-state and normalized private-fact repository."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, state: _StrategyRunState) -> None:
        run_id = state.specification.run_id
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT run_id FROM diagnostic_strategy_runs "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(f"Strategy Run {run_id!r} already exists")
            connection.execute(
                text(
                    "INSERT INTO diagnostic_strategy_runs ("
                    "run_id, status, materialization_hash, recipe_version_id, "
                    "strategy_id, strategy_version, decision_cadence_minutes, "
                    "current_simulation_time, next_node_index, state_json, "
                    "run_artifact_hash, failure_code, failure_message, updated_at_utc"
                    ") VALUES ("
                    ":run_id, :status, :materialization_hash, :recipe_version_id, "
                    ":strategy_id, :strategy_version, :decision_cadence_minutes, "
                    ":current_simulation_time, :next_node_index, :state_json, "
                    ":run_artifact_hash, :failure_code, :failure_message, "
                    ":updated_at_utc"
                    ")"
                ),
                _strategy_run_row(state),
            )
            _replace_normalized_run_facts(connection, state)

    def get(self, run_id: str) -> _StrategyRunState:
        with self._engine.connect() as connection:
            state_json = connection.execute(
                text(
                    "SELECT state_json FROM diagnostic_strategy_runs "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).scalar_one_or_none()
        if state_json is None:
            raise KeyError(f"Unknown Strategy Run {run_id!r}")
        payload = json.loads(str(state_json))
        if not isinstance(payload, dict):
            raise ValueError("Persisted Strategy Run state must be a JSON object")
        state = _strategy_run_state_from_dict(cast(dict[str, Any], payload))
        if state.specification.run_id != run_id:
            raise ValueError("Persisted Strategy Run identity does not match its row key")
        return state

    def save(self, state: _StrategyRunState) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE diagnostic_strategy_runs SET "
                    "status = :status, "
                    "materialization_hash = :materialization_hash, "
                    "recipe_version_id = :recipe_version_id, "
                    "strategy_id = :strategy_id, "
                    "strategy_version = :strategy_version, "
                    "decision_cadence_minutes = :decision_cadence_minutes, "
                    "current_simulation_time = :current_simulation_time, "
                    "next_node_index = :next_node_index, "
                    "state_json = :state_json, "
                    "run_artifact_hash = :run_artifact_hash, "
                    "failure_code = :failure_code, "
                    "failure_message = :failure_message, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE run_id = :run_id"
                ),
                _strategy_run_row(state),
            )
            if result.rowcount != 1:
                raise KeyError(
                    f"Unknown Strategy Run {state.specification.run_id!r}"
                )
            _replace_normalized_run_facts(connection, state)

class StrategyRunEngine:
    """Run one reference strategy without mutating its Reference Market Path."""

    def __init__(
        self,
        path_loader: Callable[[str], MaterializedMarketPath],
        repository: StrategyRunRepository | None = None,
    ) -> None:
        self._path_loader = path_loader
        self._repository = repository or InMemoryStrategyRunRepository()

    def replace_repository(self, repository: StrategyRunRepository) -> None:
        self._repository = repository

    def start(self, specification: StrategyRunSpecification) -> StrategyRunSnapshot:
        path = self._path_loader(specification.materialization_hash)
        self._validate_specification(specification, path)
        state = _StrategyRunState(
            specification=specification,
            status="running",
            next_node_index=0,
            decision_times=(),
            orders=(),
            fills=(),
            cash=specification.initial_cash,
            positions=(),
            equity_curve=(),
        )
        self._repository.add(state)
        return self._snapshot(state, path)

    def get(self, run_id: str) -> StrategyRunSnapshot:
        state = self._repository.get(run_id)
        path = self._path_loader(state.specification.materialization_hash)
        return self._snapshot(state, path)

    def advance(self, run_id: str, *, node_count: int = 1) -> StrategyRunSnapshot:
        if node_count <= 0:
            raise ValueError("node_count must be positive")
        state = self._repository.get(run_id)
        if state.status != "running":
            raise ValueError(
                f"Strategy Run must be running before it can advance; status={state.status}"
            )
        path = self._path_loader(state.specification.materialization_hash)
        try:
            simulation_times = _simulation_times(path)
            stop = min(state.next_node_index + node_count, len(simulation_times))
            for node_index in range(state.next_node_index, stop):
                state = self._process_node(
                    state,
                    path,
                    simulation_times,
                    node_index=node_index,
                )
            if state.next_node_index == len(simulation_times):
                state = replace(state, status="completed")
                state = replace(
                    state,
                    run_artifact_hash=_canonical_hash(_run_artifact_payload(state)),
                )
            self._repository.save(state)
        except Exception as error:
            failed = replace(
                state,
                status="failed",
                failure_code=type(error).__name__,
                failure_message=str(error),
                run_artifact_hash=None,
            )
            try:
                self._repository.save(failed)
            except Exception as persistence_error:
                raise RuntimeError(
                    "Strategy Run failed and its failure state could not be persisted"
                ) from persistence_error
            return self._snapshot(failed, path)
        return self._snapshot(state, path)

    def run_to_completion(
        self,
        run_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> StrategyRunSnapshot:
        if nodes_per_batch <= 0:
            raise ValueError("nodes_per_batch must be positive")
        snapshot = self.get(run_id)
        while snapshot.status == "running":
            snapshot = self.advance(run_id, node_count=nodes_per_batch)
        if snapshot.status == "failed":
            return snapshot
        if snapshot.status != "completed":
            raise ValueError(
                "Only a running Strategy Run can be completed; "
                f"status={snapshot.status}"
            )
        return snapshot

    def pause(self, run_id: str) -> StrategyRunSnapshot:
        state = self._repository.get(run_id)
        if state.status != "running":
            raise ValueError(
                f"Only a running Strategy Run can pause; status={state.status}"
            )
        state = replace(state, status="paused")
        self._repository.save(state)
        return self.get(run_id)

    def resume(self, run_id: str) -> StrategyRunSnapshot:
        state = self._repository.get(run_id)
        if state.status != "paused":
            raise ValueError(
                f"Only a paused Strategy Run can resume; status={state.status}"
            )
        state = replace(state, status="running")
        self._repository.save(state)
        return self.get(run_id)

    def cancel(self, run_id: str) -> StrategyRunSnapshot:
        state = self._repository.get(run_id)
        if state.status not in ("running", "paused"):
            raise ValueError(
                "Only a running or paused Strategy Run can be cancelled; "
                f"status={state.status}"
            )
        state = replace(state, status="cancelled")
        self._repository.save(state)
        return self.get(run_id)

    @staticmethod
    def _validate_specification(
        specification: StrategyRunSpecification,
        path: MaterializedMarketPath,
    ) -> None:
        if path.applied_transformations:
            raise ValueError("An anchored baseline Strategy Run requires an untransformed path")
        expected_path_identity = (
            path.artifact_hash,
            path.source_snapshot_id,
            path.seed,
            path.transformation_catalog_version,
            path.market_rule_profile_version,
        )
        if expected_path_identity != (
            specification.materialization_hash,
            specification.source_snapshot_id,
            specification.materialization_seed,
            specification.transformation_catalog_version,
            specification.market_rule_profile_version,
        ):
            raise ValueError("Strategy Run specification does not match the market path identity")
        if specification.transformation_implementation_versions:
            raise ValueError("A baseline Strategy Run cannot pin applied transformations")
        if specification.execution_policy_version != BASELINE_EXECUTION_POLICY_VERSION:
            raise ValueError("Unsupported baseline execution policy version")
        if (
            specification.strategy_id,
            specification.strategy_version,
        ) != (REFERENCE_STRATEGY_ID, REFERENCE_STRATEGY_VERSION):
            raise ValueError("Unsupported reference Strategy Under Test version")
        if specification.engine_version != STRATEGY_RUN_ENGINE_VERSION:
            raise ValueError("Unsupported Strategy Run Engine version")
        if path.runtime_resolution != "30s":
            raise ValueError("The anchored Strategy Run Engine requires a 30-second path")

    def _process_node(
        self,
        state: _StrategyRunState,
        path: MaterializedMarketPath,
        simulation_times: tuple[datetime, ...],
        *,
        node_index: int,
    ) -> _StrategyRunState:
        simulation_time = simulation_times[node_index]
        current_nodes = {
            node.instrument: node
            for node in path.nodes
            if node.simulation_time == simulation_time
        }
        state = self._activate_orders(state, current_nodes, simulation_time)
        view = ScenarioMarketView(path, initial_cursor=simulation_times[0])
        view.advance_to(simulation_time)
        market_snapshot = view.snapshot()
        if _is_decision_time(
            simulation_time,
            cadence_minutes=state.specification.decision_cadence_minutes,
        ):
            state = replace(
                state,
                decision_times=state.decision_times + (simulation_time,),
            )
            if node_index + 1 < len(simulation_times):
                state = self._queue_reference_decision(
                    state,
                    market_snapshot,
                    activation_time=simulation_times[node_index + 1],
                )
        state = self._mark_equity(state, market_snapshot, simulation_time)
        return replace(
            state,
            next_node_index=node_index + 1,
            current_simulation_time=simulation_time,
        )

    @staticmethod
    def _activate_orders(
        state: _StrategyRunState,
        current_nodes: dict[str, MarketPathNode],
        simulation_time: datetime,
    ) -> _StrategyRunState:
        orders = list(state.orders)
        fills = list(state.fills)
        cash = state.cash
        positions = {item.instrument: item for item in state.positions}
        for index, order in enumerate(orders):
            if order.status != "queued" or order.activation_time > simulation_time:
                continue
            node = current_nodes.get(order.instrument)
            if node is None:
                continue
            price = node.close
            gross_value = price * abs(order.shares)
            existing = positions.get(order.instrument)
            existing_shares = existing.shares if existing is not None else 0
            if order.shares > 0 and gross_value > cash:
                orders[index] = replace(
                    order,
                    status="rejected",
                    rejection_reason="baseline_insufficient_cash",
                )
                continue
            if order.shares < 0 and abs(order.shares) > existing_shares:
                orders[index] = replace(
                    order,
                    status="rejected",
                    rejection_reason="baseline_insufficient_position",
                )
                continue
            if order.shares > 0:
                cash -= gross_value
                prior_cost = existing.total_cost if existing is not None else Decimal("0")
                positions[order.instrument] = _LedgerPosition(
                    instrument=order.instrument,
                    shares=existing_shares + order.shares,
                    total_cost=prior_cost + gross_value,
                )
            else:
                cash += gross_value
                if existing is None:
                    raise RuntimeError("sell activation lost its private position")
                remaining_shares = existing.shares + order.shares
                if remaining_shares == 0:
                    del positions[order.instrument]
                else:
                    positions[order.instrument] = replace(
                        existing,
                        shares=remaining_shares,
                        total_cost=(
                            existing.total_cost
                            * Decimal(remaining_shares)
                            / Decimal(existing.shares)
                        ),
                    )
            orders[index] = replace(order, status="filled")
            fills.append(
                PrivateFill(
                    fill_id=f"{order.order_id}:fill",
                    order_id=order.order_id,
                    instrument=order.instrument,
                    shares=order.shares,
                    price=price,
                    gross_value=gross_value,
                    simulation_time=simulation_time,
                )
            )
        return replace(
            state,
            orders=tuple(orders),
            fills=tuple(fills),
            cash=cash,
            positions=tuple(sorted(positions.values(), key=lambda item: item.instrument)),
        )

    @staticmethod
    def _queue_reference_decision(
        state: _StrategyRunState,
        market_snapshot: ScenarioMarketSnapshot,
        *,
        activation_time: datetime,
    ) -> _StrategyRunState:
        if state.positions or state.orders:
            return state
        candidate = _top_ranked_candidate(market_snapshot)
        if candidate is None:
            return state
        current_node = next(
            node for node in market_snapshot.latest_nodes if node.instrument == candidate
        )
        requested_cost = current_node.close * state.specification.order_shares
        if requested_cost > state.cash:
            return state
        order = StrategyOrder(
            order_id=f"{state.specification.run_id}:order-0001",
            instrument=candidate,
            shares=state.specification.order_shares,
            decision_time=market_snapshot.simulation_time,
            activation_time=activation_time,
            status="queued",
        )
        return replace(state, orders=(order,))

    @staticmethod
    def _mark_equity(
        state: _StrategyRunState,
        market_snapshot: ScenarioMarketSnapshot,
        simulation_time: datetime,
    ) -> _StrategyRunState:
        price_by_instrument = {
            node.instrument: node.close for node in market_snapshot.latest_nodes
        }
        positions_value = sum(
            (
                price_by_instrument[position.instrument] * position.shares
                for position in state.positions
                if position.instrument in price_by_instrument
            ),
            Decimal("0"),
        )
        point = EquityPoint(
            simulation_time=simulation_time,
            cash=state.cash,
            positions_value=positions_value,
            equity=state.cash + positions_value,
        )
        return replace(state, equity_curve=state.equity_curve + (point,))

    @staticmethod
    def _snapshot(
        state: _StrategyRunState,
        path: MaterializedMarketPath,
    ) -> StrategyRunSnapshot:
        market_prices: dict[str, Decimal] = {}
        if state.current_simulation_time is not None:
            for node in path.nodes:
                if node.simulation_time <= state.current_simulation_time:
                    market_prices[node.instrument] = node.close
        positions = tuple(
            PortfolioPosition(
                instrument=position.instrument,
                shares=position.shares,
                average_cost=position.total_cost / Decimal(position.shares),
                market_price=market_prices.get(
                    position.instrument,
                    position.total_cost / Decimal(position.shares),
                ),
                market_value=(
                    market_prices.get(
                        position.instrument,
                        position.total_cost / Decimal(position.shares),
                    )
                    * position.shares
                ),
                unrealized_pnl=(
                    market_prices.get(
                        position.instrument,
                        position.total_cost / Decimal(position.shares),
                    )
                    * position.shares
                    - position.total_cost
                ),
            )
            for position in state.positions
        )
        return StrategyRunSnapshot(
            run_id=state.specification.run_id,
            status=state.status,
            specification=state.specification,
            current_simulation_time=state.current_simulation_time,
            processed_node_count=state.next_node_index,
            total_node_count=len(_simulation_times(path)),
            decision_times=state.decision_times,
            orders=state.orders,
            fills=state.fills,
            cash=state.cash,
            positions=positions,
            equity_curve=state.equity_curve,
            failure_code=state.failure_code,
            failure_message=state.failure_message,
            run_artifact_hash=state.run_artifact_hash,
        )


def _simulation_times(path: MaterializedMarketPath) -> tuple[datetime, ...]:
    return tuple(sorted({node.simulation_time for node in path.nodes}))


def _is_decision_time(simulation_time: datetime, *, cadence_minutes: int) -> bool:
    total_minutes = simulation_time.hour * 60 + simulation_time.minute
    return simulation_time.second == 0 and total_minutes % cadence_minutes == 0


def _top_ranked_candidate(snapshot: ScenarioMarketSnapshot) -> str | None:
    eligible = set(snapshot.eligible_universe)
    if not eligible:
        return None
    ranked: list[tuple[Decimal, str]] = []
    for node in snapshot.latest_nodes:
        if node.instrument not in eligible:
            continue
        features = dict(node.features)
        rank = features.get("candidate_rank")
        if rank is not None:
            ranked.append((rank, node.instrument))
    ranked_instruments = {instrument for _rank, instrument in ranked}
    if ranked_instruments != eligible:
        raise ValueError(
            "Reference strategy requires a candidate ranking for every eligible "
            "instrument at Decision Time"
        )
    ranks = [rank for rank, _instrument in ranked]
    if len(ranks) != len(set(ranks)):
        raise ValueError("Reference strategy candidate ranking contains duplicate ranks")
    return min(ranked)[1]


def _run_artifact_payload(state: _StrategyRunState) -> dict[str, object]:
    return {
        "run_id": state.specification.run_id,
        "status": state.status,
        "specification": state.specification.to_dict(),
        "current_simulation_time": (
            state.current_simulation_time.isoformat()
            if state.current_simulation_time is not None
            else None
        ),
        "processed_node_count": state.next_node_index,
        "decision_times": [item.isoformat() for item in state.decision_times],
        "orders": [item.to_dict() for item in state.orders],
        "fills": [item.to_dict() for item in state.fills],
        "cash": _decimal_text(state.cash),
        "positions": [
            {
                "instrument": item.instrument,
                "shares": item.shares,
                "total_cost": _decimal_text(item.total_cost),
            }
            for item in state.positions
        ],
        "equity_curve": [item.to_dict() for item in state.equity_curve],
        "failure_code": state.failure_code,
        "failure_message": state.failure_message,
    }


def _strategy_run_state_to_dict(state: _StrategyRunState) -> dict[str, object]:
    payload = _run_artifact_payload(state)
    payload["run_artifact_hash"] = state.run_artifact_hash
    return payload


def _strategy_run_state_from_dict(payload: dict[str, Any]) -> _StrategyRunState:
    specification_payload = cast(dict[str, Any], payload["specification"])
    specification = StrategyRunSpecification(
        recipe_version_id=str(specification_payload["recipe_version_id"]),
        recipe_content_hash=str(specification_payload["recipe_content_hash"]),
        materialization_hash=str(specification_payload["materialization_hash"]),
        source_snapshot_id=str(specification_payload["source_snapshot_id"]),
        materialization_seed=int(specification_payload["materialization_seed"]),
        transformation_catalog_version=str(
            specification_payload["transformation_catalog_version"]
        ),
        transformation_implementation_versions=tuple(
            str(item)
            for item in specification_payload[
                "transformation_implementation_versions"
            ]
        ),
        market_rule_profile_version=str(
            specification_payload["market_rule_profile_version"]
        ),
        execution_policy_version=str(
            specification_payload["execution_policy_version"]
        ),
        strategy_id=str(specification_payload["strategy_id"]),
        strategy_version=str(specification_payload["strategy_version"]),
        decision_cadence_minutes=int(
            specification_payload["decision_cadence_minutes"]
        ),
        initial_cash=Decimal(str(specification_payload["initial_cash"])),
        order_shares=int(specification_payload["order_shares"]),
        replica_id=str(specification_payload["replica_id"]),
        code_identity=str(specification_payload["code_identity"]),
        engine_version=str(specification_payload["engine_version"]),
    )
    orders = tuple(
        StrategyOrder(
            order_id=str(item["order_id"]),
            instrument=str(item["instrument"]),
            shares=int(item["shares"]),
            decision_time=datetime.fromisoformat(str(item["decision_time"])),
            activation_time=datetime.fromisoformat(str(item["activation_time"])),
            status=_parse_order_status(str(item["status"])),
            rejection_reason=(
                str(item["rejection_reason"])
                if item.get("rejection_reason") is not None
                else None
            ),
        )
        for item in cast(list[dict[str, Any]], payload["orders"])
    )
    fills = tuple(
        PrivateFill(
            fill_id=str(item["fill_id"]),
            order_id=str(item["order_id"]),
            instrument=str(item["instrument"]),
            shares=int(item["shares"]),
            price=Decimal(str(item["price"])),
            gross_value=Decimal(str(item["gross_value"])),
            simulation_time=datetime.fromisoformat(str(item["simulation_time"])),
        )
        for item in cast(list[dict[str, Any]], payload["fills"])
    )
    positions = tuple(
        _LedgerPosition(
            instrument=str(item["instrument"]),
            shares=int(item["shares"]),
            total_cost=Decimal(str(item["total_cost"])),
        )
        for item in cast(list[dict[str, Any]], payload["positions"])
    )
    equity_curve = tuple(
        EquityPoint(
            simulation_time=datetime.fromisoformat(str(item["simulation_time"])),
            cash=Decimal(str(item["cash"])),
            positions_value=Decimal(str(item["positions_value"])),
            equity=Decimal(str(item["equity"])),
        )
        for item in cast(list[dict[str, Any]], payload["equity_curve"])
    )
    current_simulation_time = payload.get("current_simulation_time")
    return _StrategyRunState(
        specification=specification,
        status=_parse_run_status(str(payload["status"])),
        next_node_index=int(payload["processed_node_count"]),
        decision_times=tuple(
            datetime.fromisoformat(str(item)) for item in payload["decision_times"]
        ),
        orders=orders,
        fills=fills,
        cash=Decimal(str(payload["cash"])),
        positions=positions,
        equity_curve=equity_curve,
        current_simulation_time=(
            datetime.fromisoformat(str(current_simulation_time))
            if current_simulation_time is not None
            else None
        ),
        failure_code=(
            str(payload["failure_code"])
            if payload.get("failure_code") is not None
            else None
        ),
        failure_message=(
            str(payload["failure_message"])
            if payload.get("failure_message") is not None
            else None
        ),
        run_artifact_hash=(
            str(payload["run_artifact_hash"])
            if payload.get("run_artifact_hash") is not None
            else None
        ),
    )


def _strategy_run_row(state: _StrategyRunState) -> dict[str, object]:
    specification = state.specification
    return {
        "run_id": specification.run_id,
        "status": state.status,
        "materialization_hash": specification.materialization_hash,
        "recipe_version_id": specification.recipe_version_id,
        "strategy_id": specification.strategy_id,
        "strategy_version": specification.strategy_version,
        "decision_cadence_minutes": specification.decision_cadence_minutes,
        "current_simulation_time": (
            state.current_simulation_time.isoformat()
            if state.current_simulation_time is not None
            else None
        ),
        "next_node_index": state.next_node_index,
        "state_json": json.dumps(
            _strategy_run_state_to_dict(state),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "run_artifact_hash": state.run_artifact_hash,
        "failure_code": state.failure_code,
        "failure_message": state.failure_message,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _parse_run_status(value: str) -> StrategyRunStatus:
    if value not in ("running", "paused", "completed", "cancelled", "failed"):
        raise ValueError(f"Persisted Strategy Run has invalid status {value!r}")
    return cast(StrategyRunStatus, value)


def _parse_order_status(value: str) -> OrderStatus:
    if value not in ("queued", "filled", "rejected"):
        raise ValueError(f"Persisted Strategy Order has invalid status {value!r}")
    return cast(OrderStatus, value)


def _replace_normalized_run_facts(
    connection: Connection,
    state: _StrategyRunState,
) -> None:
    run_id = state.specification.run_id
    for table in (
        "diagnostic_run_fills",
        "diagnostic_run_orders",
        "diagnostic_run_positions",
        "diagnostic_run_equity",
    ):
        connection.execute(
            text(f"DELETE FROM {table} WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    if state.orders:
        connection.execute(
            text(
                "INSERT INTO diagnostic_run_orders ("
                "order_id, run_id, instrument, shares, decision_time, "
                "activation_time, status, rejection_reason"
                ") VALUES ("
                ":order_id, :run_id, :instrument, :shares, :decision_time, "
                ":activation_time, :status, :rejection_reason"
                ")"
            ),
            [
                {
                    "order_id": item.order_id,
                    "run_id": run_id,
                    "instrument": item.instrument,
                    "shares": item.shares,
                    "decision_time": item.decision_time.isoformat(),
                    "activation_time": item.activation_time.isoformat(),
                    "status": item.status,
                    "rejection_reason": item.rejection_reason,
                }
                for item in state.orders
            ],
        )
    if state.fills:
        connection.execute(
            text(
                "INSERT INTO diagnostic_run_fills ("
                "fill_id, run_id, order_id, instrument, shares, price, "
                "gross_value, simulation_time"
                ") VALUES ("
                ":fill_id, :run_id, :order_id, :instrument, :shares, :price, "
                ":gross_value, :simulation_time"
                ")"
            ),
            [
                {
                    "fill_id": item.fill_id,
                    "run_id": run_id,
                    "order_id": item.order_id,
                    "instrument": item.instrument,
                    "shares": item.shares,
                    "price": _decimal_text(item.price),
                    "gross_value": _decimal_text(item.gross_value),
                    "simulation_time": item.simulation_time.isoformat(),
                }
                for item in state.fills
            ],
        )
    if state.positions:
        connection.execute(
            text(
                "INSERT INTO diagnostic_run_positions ("
                "run_id, instrument, shares, total_cost"
                ") VALUES (:run_id, :instrument, :shares, :total_cost)"
            ),
            [
                {
                    "run_id": run_id,
                    "instrument": item.instrument,
                    "shares": item.shares,
                    "total_cost": _decimal_text(item.total_cost),
                }
                for item in state.positions
            ],
        )
    if state.equity_curve:
        connection.execute(
            text(
                "INSERT INTO diagnostic_run_equity ("
                "run_id, simulation_time, cash, positions_value, equity"
                ") VALUES ("
                ":run_id, :simulation_time, :cash, :positions_value, :equity"
                ")"
            ),
            [
                {
                    "run_id": run_id,
                    "simulation_time": item.simulation_time.isoformat(),
                    "cash": _decimal_text(item.cash),
                    "positions_value": _decimal_text(item.positions_value),
                    "equity": _decimal_text(item.equity),
                }
                for item in state.equity_curve
            ],
        )


__all__ = [
    "BASELINE_EXECUTION_POLICY_VERSION",
    "EquityPoint",
    "InMemoryStrategyRunRepository",
    "PortfolioPosition",
    "PrivateFill",
    "REFERENCE_STRATEGY_ID",
    "REFERENCE_STRATEGY_VERSION",
    "STRATEGY_RUN_ENGINE_VERSION",
    "SqlStrategyRunRepository",
    "StrategyOrder",
    "StrategyRunEngine",
    "StrategyRunRepository",
    "StrategyRunSnapshot",
    "StrategyRunSpecification",
]
