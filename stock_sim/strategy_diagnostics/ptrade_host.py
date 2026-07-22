"""Versioned PTrade compatibility surface and isolated reference-strategy hosts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Callable, Final, Literal, Mapping, Protocol, Sequence, cast

from .execution_conditions import ResolvedExecutionConditions
from .market_paths import InstrumentState, MarketPathNode, ScenarioMarketSnapshot


PTRADE_SURFACE_VERSION: Final = "ptrade_surface.v1"
PTRADE_IN_PROCESS_HOST_VERSION: Final = "ptrade-in-process-host.v1"
PTRADE_SUBPROCESS_HOST_VERSION: Final = "ptrade-subprocess-host.v1"
PTRADE_SUBPROCESS_PROTOCOL_VERSION: Final = "ptrade-subprocess-json.v1"
REFERENCE_PTRADE_STRATEGY_ID: Final = "anchored-ranked-candidate-reference"
REFERENCE_PTRADE_STRATEGY_VERSION: Final = (
    "anchored-ranked-candidate-reference.v1"
)

ConfigurationCall = Literal["set_slippage", "set_commission"]
LogLevel = Literal["info", "warning", "error"]
PTradeHostEvent = Literal["initialize", "decision", "handle_data"]


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class PTradeCompatibilityError(RuntimeError):
    """An explicit failure for a call outside one compatibility version."""

    def __init__(
        self,
        call: str,
        *,
        detail: str | None = None,
        surface_version: str = PTRADE_SURFACE_VERSION,
    ) -> None:
        self.call = call
        self.surface_version = surface_version
        message = (
            f"{surface_version} does not support or accept call {call!r}"
            + (f": {detail}" if detail else "")
        )
        super().__init__(message)


class PTradeHostProcessError(RuntimeError):
    """A subprocess failed without mutating the parent Strategy Run process."""


@dataclass(frozen=True, slots=True)
class PTradeCompatibilityManifest:
    surface_version: str
    strategy_id: str
    strategy_version: str
    strategy_module: str
    lifecycle_callbacks: tuple[str, ...]
    scheduled_callbacks: tuple[str, ...]
    scheduling_calls: tuple[str, ...]
    context_fields: tuple[str, ...]
    portfolio_fields: tuple[str, ...]
    market_data_calls: tuple[str, ...]
    configuration_calls: tuple[str, ...]
    trading_calls: tuple[str, ...]
    logging_calls: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.surface_version != PTRADE_SURFACE_VERSION:
            raise ValueError("unsupported PTrade Compatibility Surface version")
        if (
            not self.strategy_id.strip()
            or not self.strategy_version.strip()
            or not self.strategy_module.strip()
        ):
            raise ValueError("PTrade strategy identity must not be empty")
        if len(self.supported_calls) != len(set(self.supported_calls)):
            raise ValueError("PTrade compatibility calls must be unique")

    @property
    def supported_calls(self) -> tuple[str, ...]:
        return (
            self.scheduling_calls
            + self.market_data_calls
            + self.configuration_calls
            + self.trading_calls
            + self.logging_calls
        )

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict())

    def require_call(self, call: str) -> None:
        if call not in self.supported_calls:
            raise PTradeCompatibilityError(call)

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_version": self.surface_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_module": self.strategy_module,
            "lifecycle_callbacks": list(self.lifecycle_callbacks),
            "scheduled_callbacks": list(self.scheduled_callbacks),
            "scheduling_calls": list(self.scheduling_calls),
            "context_fields": list(self.context_fields),
            "portfolio_fields": list(self.portfolio_fields),
            "market_data_calls": list(self.market_data_calls),
            "configuration_calls": list(self.configuration_calls),
            "trading_calls": list(self.trading_calls),
            "logging_calls": list(self.logging_calls),
        }


REFERENCE_PTRADE_COMPATIBILITY_MANIFEST: Final = PTradeCompatibilityManifest(
    surface_version=PTRADE_SURFACE_VERSION,
    strategy_id=REFERENCE_PTRADE_STRATEGY_ID,
    strategy_version=REFERENCE_PTRADE_STRATEGY_VERSION,
    strategy_module="strategy_diagnostics.reference_ptrade_strategy",
    lifecycle_callbacks=("initialize", "handle_data"),
    scheduled_callbacks=("rebalance",),
    scheduling_calls=("run_daily",),
    context_fields=(
        "current_dt",
        "portfolio",
        "state",
        "eligible_universe",
        "decision_cadence_minutes",
        "order_shares",
    ),
    portfolio_fields=("available_cash", "total_value", "positions"),
    market_data_calls=("set_universe", "get_history", "get_current_data"),
    configuration_calls=("set_slippage", "set_commission"),
    trading_calls=("order",),
    logging_calls=("log.info", "log.warning", "log.error"),
)


@dataclass(frozen=True, slots=True)
class PTradePositionSnapshot:
    instrument: str
    amount: int
    closeable_amount: int
    average_cost: Decimal
    market_price: Decimal
    market_value: Decimal

    def __getattr__(self, name: str) -> object:
        raise PTradeCompatibilityError(f"position.{name}")

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("PTrade position instrument must not be empty")
        if self.amount < 0 or not 0 <= self.closeable_amount <= self.amount:
            raise ValueError("PTrade position share quantities are invalid")
        if min(self.average_cost, self.market_price, self.market_value) < 0:
            raise ValueError("PTrade position money values must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "amount": self.amount,
            "closeable_amount": self.closeable_amount,
            "average_cost": _decimal_text(self.average_cost),
            "market_price": _decimal_text(self.market_price),
            "market_value": _decimal_text(self.market_value),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradePositionSnapshot":
        return cls(
            instrument=str(payload["instrument"]),
            amount=int(str(payload["amount"])),
            closeable_amount=int(str(payload["closeable_amount"])),
            average_cost=Decimal(str(payload["average_cost"])),
            market_price=Decimal(str(payload["market_price"])),
            market_value=Decimal(str(payload["market_value"])),
        )


@dataclass(frozen=True, slots=True)
class PTradePortfolioSnapshot:
    available_cash: Decimal
    total_value: Decimal
    positions: tuple[PTradePositionSnapshot, ...]

    def __getattr__(self, name: str) -> object:
        raise PTradeCompatibilityError(f"portfolio.{name}")

    def __post_init__(self) -> None:
        if self.available_cash < 0 or self.total_value < 0:
            raise ValueError("PTrade portfolio values must not be negative")
        instruments = [item.instrument for item in self.positions]
        if len(instruments) != len(set(instruments)):
            raise ValueError("PTrade portfolio positions must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "available_cash": _decimal_text(self.available_cash),
            "total_value": _decimal_text(self.total_value),
            "positions": [item.to_dict() for item in self.positions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradePortfolioSnapshot":
        positions = cast(Sequence[Mapping[str, object]], payload["positions"])
        return cls(
            available_cash=Decimal(str(payload["available_cash"])),
            total_value=Decimal(str(payload["total_value"])),
            positions=tuple(PTradePositionSnapshot.from_dict(item) for item in positions),
        )


@dataclass(slots=True)
class PTradeContext:
    """Mutable strategy context with immutable point-in-time portfolio facts."""

    current_dt: datetime
    portfolio: PTradePortfolioSnapshot
    state: dict[str, str]
    eligible_universe: tuple[str, ...]
    decision_cadence_minutes: int
    order_shares: int

    def __getattr__(self, name: str) -> object:
        raise PTradeCompatibilityError(f"context.{name}")


@dataclass(frozen=True, slots=True)
class PTradeConfigurationRequest:
    call: ConfigurationCall
    value: Decimal

    def to_dict(self) -> dict[str, object]:
        return {"call": self.call, "value": _decimal_text(self.value)}

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "PTradeConfigurationRequest":
        call = str(payload["call"])
        if call not in ("set_slippage", "set_commission"):
            raise PTradeCompatibilityError(call)
        return cls(call=cast(ConfigurationCall, call), value=Decimal(str(payload["value"])))


@dataclass(frozen=True, slots=True)
class PTradeOrderRequest:
    instrument: str
    amount: int

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("PTrade order instrument must not be empty")
        if self.amount == 0:
            raise ValueError("PTrade signed-share order amount must not be zero")

    def to_dict(self) -> dict[str, object]:
        return {"instrument": self.instrument, "amount": self.amount}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeOrderRequest":
        return cls(
            instrument=str(payload["instrument"]),
            amount=int(str(payload["amount"])),
        )


@dataclass(frozen=True, slots=True)
class PTradeLogRecord:
    level: LogLevel
    message: str

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("PTrade log message must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {"level": self.level, "message": self.message}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeLogRecord":
        level = str(payload["level"])
        if level not in ("info", "warning", "error"):
            raise ValueError("unsupported PTrade log level")
        return cls(level=cast(LogLevel, level), message=str(payload["message"]))


@dataclass(frozen=True, slots=True)
class PTradeRuntimeState:
    initialized: bool
    universe: tuple[str, ...]
    scheduled_callbacks: tuple[tuple[str, int], ...]
    strategy_state: tuple[tuple[str, str], ...]

    @classmethod
    def empty(cls) -> "PTradeRuntimeState":
        return cls(
            initialized=False,
            universe=(),
            scheduled_callbacks=(),
            strategy_state=(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "initialized": self.initialized,
            "universe": list(self.universe),
            "scheduled_callbacks": [
                {"callback": callback, "cadence_minutes": cadence}
                for callback, cadence in self.scheduled_callbacks
            ],
            "strategy_state": dict(self.strategy_state),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeRuntimeState":
        schedules = cast(
            Sequence[Mapping[str, object]],
            payload.get("scheduled_callbacks", ()),
        )
        state = cast(Mapping[str, object], payload.get("strategy_state", {}))
        return cls(
            initialized=bool(payload.get("initialized", False)),
            universe=tuple(str(item) for item in cast(Sequence[object], payload.get("universe", ()))),
            scheduled_callbacks=tuple(
                (str(item["callback"]), int(str(item["cadence_minutes"])))
                for item in schedules
            ),
            strategy_state=tuple(sorted((str(name), str(value)) for name, value in state.items())),
        )


@dataclass(frozen=True, slots=True)
class PTradeHostInvocation:
    run_id: str
    strategy_id: str
    strategy_version: str
    compatibility_manifest_hash: str
    materialization_hash: str
    simulation_time: datetime
    decision_cadence_minutes: int
    order_shares: int
    random_seed: int
    market_snapshot: ScenarioMarketSnapshot
    market_history: tuple[MarketPathNode, ...]
    portfolio: PTradePortfolioSnapshot
    event: PTradeHostEvent = "decision"
    runtime_state: PTradeRuntimeState | None = None

    def __post_init__(self) -> None:
        if self.simulation_time.tzinfo is not None:
            raise ValueError("PTrade Simulation Time must be timezone-naive")
        if self.market_snapshot.simulation_time != self.simulation_time:
            raise ValueError("PTrade snapshot time must match invocation time")
        if self.decision_cadence_minutes not in (30, 60):
            raise ValueError("PTrade decision cadence must be 30 or 60 minutes")
        if self.order_shares <= 0:
            raise ValueError("PTrade reference order_shares must be positive")
        if self.event not in ("initialize", "decision", "handle_data"):
            raise ValueError("unsupported PTrade host event")
        if len(self.compatibility_manifest_hash) != 64:
            raise ValueError("PTrade compatibility manifest hash must be SHA-256")
        eligible = set(self.market_snapshot.eligible_universe)
        if any(node.simulation_time > self.simulation_time for node in self.market_history):
            raise ValueError("PTrade market history contains future data")
        if any(node.instrument not in eligible for node in self.market_history):
            raise ValueError("PTrade market history contains an ineligible instrument")

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "compatibility_manifest_hash": self.compatibility_manifest_hash,
            "materialization_hash": self.materialization_hash,
            "simulation_time": self.simulation_time.isoformat(),
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "order_shares": self.order_shares,
            "random_seed": self.random_seed,
            "market_snapshot": {
                "simulation_time": self.market_snapshot.simulation_time.isoformat(),
                "eligible_universe": list(self.market_snapshot.eligible_universe),
                "states": [item.to_dict() for item in self.market_snapshot.states],
                "latest_nodes": [item.to_dict() for item in self.market_snapshot.latest_nodes],
            },
            "market_history": [item.to_dict() for item in self.market_history],
            "portfolio": self.portfolio.to_dict(),
            "event": self.event,
            "runtime_state": (
                self.runtime_state.to_dict() if self.runtime_state is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeHostInvocation":
        snapshot_payload = cast(Mapping[str, object], payload["market_snapshot"])
        states = cast(Sequence[Mapping[str, object]], snapshot_payload["states"])
        latest_nodes = cast(
            Sequence[Mapping[str, object]],
            snapshot_payload["latest_nodes"],
        )
        history = cast(Sequence[Mapping[str, object]], payload["market_history"])
        runtime_payload = payload.get("runtime_state")
        return cls(
            run_id=str(payload["run_id"]),
            strategy_id=str(payload["strategy_id"]),
            strategy_version=str(payload["strategy_version"]),
            compatibility_manifest_hash=str(payload["compatibility_manifest_hash"]),
            materialization_hash=str(payload["materialization_hash"]),
            simulation_time=datetime.fromisoformat(str(payload["simulation_time"])),
            decision_cadence_minutes=int(str(payload["decision_cadence_minutes"])),
            order_shares=int(str(payload["order_shares"])),
            random_seed=int(str(payload["random_seed"])),
            market_snapshot=ScenarioMarketSnapshot(
                simulation_time=datetime.fromisoformat(
                    str(snapshot_payload["simulation_time"])
                ),
                eligible_universe=tuple(
                    str(item)
                    for item in cast(
                        Sequence[object],
                        snapshot_payload["eligible_universe"],
                    )
                ),
                states=tuple(_instrument_state_from_dict(item) for item in states),
                latest_nodes=tuple(_market_node_from_dict(item) for item in latest_nodes),
            ),
            market_history=tuple(_market_node_from_dict(item) for item in history),
            portfolio=PTradePortfolioSnapshot.from_dict(
                cast(Mapping[str, object], payload["portfolio"])
            ),
            event=cast(PTradeHostEvent, str(payload.get("event", "decision"))),
            runtime_state=(
                PTradeRuntimeState.from_dict(
                    cast(Mapping[str, object], runtime_payload)
                )
                if isinstance(runtime_payload, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class PTradeHostResult:
    surface_version: str
    manifest_hash: str
    host_adapter_version: str
    lifecycle_events: tuple[str, ...]
    scheduled_callbacks: tuple[tuple[str, int], ...]
    configuration_requests: tuple[PTradeConfigurationRequest, ...]
    order_requests: tuple[PTradeOrderRequest, ...]
    market_data_calls: tuple[str, ...]
    log_records: tuple[PTradeLogRecord, ...]
    runtime_state: PTradeRuntimeState
    process_id: int
    worker_global_counter: int
    random_probe: str

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_version": self.surface_version,
            "manifest_hash": self.manifest_hash,
            "host_adapter_version": self.host_adapter_version,
            "lifecycle_events": list(self.lifecycle_events),
            "scheduled_callbacks": [
                {"callback": callback, "cadence_minutes": cadence}
                for callback, cadence in self.scheduled_callbacks
            ],
            "configuration_requests": [
                item.to_dict() for item in self.configuration_requests
            ],
            "order_requests": [item.to_dict() for item in self.order_requests],
            "market_data_calls": list(self.market_data_calls),
            "log_records": [item.to_dict() for item in self.log_records],
            "runtime_state": self.runtime_state.to_dict(),
            "process_id": self.process_id,
            "worker_global_counter": self.worker_global_counter,
            "random_probe": self.random_probe,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeHostResult":
        _validate_host_result_payload(payload)
        schedules = cast(
            Sequence[Mapping[str, object]],
            payload["scheduled_callbacks"],
        )
        configurations = cast(
            Sequence[Mapping[str, object]],
            payload["configuration_requests"],
        )
        orders = cast(Sequence[Mapping[str, object]], payload["order_requests"])
        logs = cast(Sequence[Mapping[str, object]], payload["log_records"])
        return cls(
            surface_version=str(payload["surface_version"]),
            manifest_hash=str(payload["manifest_hash"]),
            host_adapter_version=str(payload["host_adapter_version"]),
            lifecycle_events=tuple(
                str(item)
                for item in cast(Sequence[object], payload["lifecycle_events"])
            ),
            scheduled_callbacks=tuple(
                (str(item["callback"]), int(str(item["cadence_minutes"])))
                for item in schedules
            ),
            configuration_requests=tuple(
                PTradeConfigurationRequest.from_dict(item) for item in configurations
            ),
            order_requests=tuple(PTradeOrderRequest.from_dict(item) for item in orders),
            market_data_calls=tuple(
                str(item)
                for item in cast(Sequence[object], payload["market_data_calls"])
            ),
            log_records=tuple(PTradeLogRecord.from_dict(item) for item in logs),
            runtime_state=PTradeRuntimeState.from_dict(
                cast(Mapping[str, object], payload["runtime_state"])
            ),
            process_id=int(str(payload["process_id"])),
            worker_global_counter=int(str(payload["worker_global_counter"])),
            random_probe=str(payload["random_probe"]),
        )


def _validate_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} has unexpected or missing fields")


def _require_json_array(
    payload: Mapping[str, object],
    field: str,
    *,
    label: str,
) -> list[object]:
    value = payload[field]
    if not isinstance(value, list):
        raise ValueError(f"{label}.{field} must be a JSON array")
    return value


def _require_json_object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _validate_schedule_payload(value: object, *, label: str) -> None:
    schedule = _require_json_object(value, label=label)
    _validate_exact_keys(
        schedule,
        {"callback", "cadence_minutes"},
        label=label,
    )
    if not isinstance(schedule["callback"], str) or type(
        schedule["cadence_minutes"]
    ) is not int:
        raise ValueError(f"{label} has invalid field types")


def _validate_runtime_state_payload(value: object) -> None:
    runtime = _require_json_object(value, label="PTrade runtime state")
    _validate_exact_keys(
        runtime,
        {"initialized", "universe", "scheduled_callbacks", "strategy_state"},
        label="PTrade runtime state",
    )
    if type(runtime["initialized"]) is not bool:
        raise ValueError("PTrade runtime state.initialized must be boolean")
    universe = _require_json_array(
        runtime,
        "universe",
        label="PTrade runtime state",
    )
    if any(not isinstance(item, str) for item in universe):
        raise ValueError("PTrade runtime state.universe must contain strings")
    schedules = _require_json_array(
        runtime,
        "scheduled_callbacks",
        label="PTrade runtime state",
    )
    for index, item in enumerate(schedules):
        _validate_schedule_payload(
            item,
            label=f"PTrade runtime state.scheduled_callbacks[{index}]",
        )
    strategy_state = _require_json_object(
        runtime["strategy_state"],
        label="PTrade runtime state.strategy_state",
    )
    if any(
        not isinstance(name, str) or not isinstance(state_value, str)
        for name, state_value in strategy_state.items()
    ):
        raise ValueError("PTrade runtime state.strategy_state must map strings")


def _validate_host_result_payload(payload: Mapping[str, object]) -> None:
    _validate_exact_keys(
        payload,
        {
            "surface_version",
            "manifest_hash",
            "host_adapter_version",
            "lifecycle_events",
            "scheduled_callbacks",
            "configuration_requests",
            "order_requests",
            "market_data_calls",
            "log_records",
            "runtime_state",
            "process_id",
            "worker_global_counter",
            "random_probe",
        },
        label="PTrade host result",
    )
    for field in (
        "surface_version",
        "manifest_hash",
        "host_adapter_version",
        "random_probe",
    ):
        if not isinstance(payload[field], str):
            raise ValueError(f"PTrade host result.{field} must be a string")
    for field in ("process_id", "worker_global_counter"):
        if type(payload[field]) is not int:
            raise ValueError(f"PTrade host result.{field} must be an integer")
    for field in ("lifecycle_events", "market_data_calls"):
        values = _require_json_array(payload, field, label="PTrade host result")
        if any(not isinstance(item, str) for item in values):
            raise ValueError(f"PTrade host result.{field} must contain strings")
    schedules = _require_json_array(
        payload,
        "scheduled_callbacks",
        label="PTrade host result",
    )
    for index, item in enumerate(schedules):
        _validate_schedule_payload(
            item,
            label=f"PTrade host result.scheduled_callbacks[{index}]",
        )
    configurations = _require_json_array(
        payload,
        "configuration_requests",
        label="PTrade host result",
    )
    for index, item in enumerate(configurations):
        configuration = _require_json_object(
            item,
            label=f"PTrade host result.configuration_requests[{index}]",
        )
        _validate_exact_keys(
            configuration,
            {"call", "value"},
            label=f"PTrade host result.configuration_requests[{index}]",
        )
        if not isinstance(configuration["call"], str) or not isinstance(
            configuration["value"], str
        ):
            raise ValueError("PTrade configuration request fields must be strings")
    orders = _require_json_array(
        payload,
        "order_requests",
        label="PTrade host result",
    )
    for index, item in enumerate(orders):
        order = _require_json_object(
            item,
            label=f"PTrade host result.order_requests[{index}]",
        )
        _validate_exact_keys(
            order,
            {"instrument", "amount"},
            label=f"PTrade host result.order_requests[{index}]",
        )
        if not isinstance(order["instrument"], str) or type(order["amount"]) is not int:
            raise ValueError("PTrade order request fields have invalid types")
    logs = _require_json_array(payload, "log_records", label="PTrade host result")
    for index, item in enumerate(logs):
        record = _require_json_object(
            item,
            label=f"PTrade host result.log_records[{index}]",
        )
        _validate_exact_keys(
            record,
            {"level", "message"},
            label=f"PTrade host result.log_records[{index}]",
        )
        if not isinstance(record["level"], str) or not isinstance(
            record["message"], str
        ):
            raise ValueError("PTrade log record fields must be strings")
    _validate_runtime_state_payload(payload["runtime_state"])


@dataclass(frozen=True, slots=True)
class PTradeAuditOrderRequest:
    decision_time: datetime
    instrument: str
    amount: int

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_time": self.decision_time.isoformat(),
            "instrument": self.instrument,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeAuditOrderRequest":
        return cls(
            decision_time=datetime.fromisoformat(str(payload["decision_time"])),
            instrument=str(payload["instrument"]),
            amount=int(str(payload["amount"])),
        )


@dataclass(frozen=True, slots=True)
class PTradeRunAudit:
    surface_version: str
    manifest_hash: str
    execution_resolution: ResolvedExecutionConditions
    host_adapter_versions: tuple[str, ...] = ()
    lifecycle_events: tuple[str, ...] = ()
    configuration_requests: tuple[PTradeConfigurationRequest, ...] = ()
    order_requests: tuple[PTradeAuditOrderRequest, ...] = ()
    market_data_calls: tuple[str, ...] = ()
    log_records: tuple[PTradeLogRecord, ...] = ()

    def append(
        self,
        result: PTradeHostResult,
        *,
        decision_time: datetime,
    ) -> "PTradeRunAudit":
        if (
            result.surface_version != self.surface_version
            or result.manifest_hash != self.manifest_hash
        ):
            raise ValueError("PTrade host result does not match the pinned surface")
        if self.host_adapter_versions != (result.host_adapter_version,):
            raise ValueError(
                "PTrade host result does not match the pinned adapter version"
            )
        return PTradeRunAudit(
            surface_version=self.surface_version,
            manifest_hash=self.manifest_hash,
            execution_resolution=self.execution_resolution,
            host_adapter_versions=self.host_adapter_versions,
            lifecycle_events=self.lifecycle_events + result.lifecycle_events,
            configuration_requests=(
                self.configuration_requests + result.configuration_requests
            ),
            order_requests=self.order_requests
            + tuple(
                PTradeAuditOrderRequest(
                    decision_time=decision_time,
                    instrument=item.instrument,
                    amount=item.amount,
                )
                for item in result.order_requests
            ),
            market_data_calls=self.market_data_calls + result.market_data_calls,
            log_records=self.log_records + result.log_records,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_version": self.surface_version,
            "manifest_hash": self.manifest_hash,
            "host_adapter_versions": list(self.host_adapter_versions),
            "lifecycle_events": list(self.lifecycle_events),
            "configuration_requests": [
                item.to_dict() for item in self.configuration_requests
            ],
            "execution_resolution": self.execution_resolution.to_dict(),
            "order_requests": [item.to_dict() for item in self.order_requests],
            "market_data_calls": list(self.market_data_calls),
            "log_records": [item.to_dict() for item in self.log_records],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PTradeRunAudit":
        configurations = cast(
            Sequence[Mapping[str, object]],
            payload.get("configuration_requests", ()),
        )
        orders = cast(
            Sequence[Mapping[str, object]],
            payload.get("order_requests", ()),
        )
        logs = cast(Sequence[Mapping[str, object]], payload.get("log_records", ()))
        return cls(
            surface_version=str(payload["surface_version"]),
            manifest_hash=str(payload["manifest_hash"]),
            execution_resolution=ResolvedExecutionConditions.from_dict(
                cast(Mapping[str, object], payload["execution_resolution"])
            ),
            host_adapter_versions=tuple(
                str(item)
                for item in cast(
                    Sequence[object],
                    payload.get("host_adapter_versions", ()),
                )
            ),
            lifecycle_events=tuple(
                str(item)
                for item in cast(
                    Sequence[object],
                    payload.get("lifecycle_events", ()),
                )
            ),
            configuration_requests=tuple(
                PTradeConfigurationRequest.from_dict(item) for item in configurations
            ),
            order_requests=tuple(PTradeAuditOrderRequest.from_dict(item) for item in orders),
            market_data_calls=tuple(
                str(item)
                for item in cast(
                    Sequence[object],
                    payload.get("market_data_calls", ()),
                )
            ),
            log_records=tuple(PTradeLogRecord.from_dict(item) for item in logs),
        )


class PTradeStrategyHost(Protocol):
    @property
    def adapter_version(self) -> str: ...

    def invoke(self, invocation: PTradeHostInvocation) -> PTradeHostResult: ...


class PTradeWorkerTransport(Protocol):
    def exchange(
        self,
        request_text: str,
        *,
        python_executable: str,
        timeout_seconds: float,
    ) -> str: ...


class InProcessPTradeStrategyHost:
    """Deterministic contract-test adapter; production uses the subprocess host."""

    @property
    def adapter_version(self) -> str:
        return PTRADE_IN_PROCESS_HOST_VERSION

    def invoke(self, invocation: PTradeHostInvocation) -> PTradeHostResult:
        return _execute_reference_invocation(
            invocation,
            host_adapter_version=PTRADE_IN_PROCESS_HOST_VERSION,
        )


class SubprocessPTradeStrategyHost:
    """Run one callback invocation in a fresh subprocess with a JSON protocol."""

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        timeout_seconds: float = 30,
        transport: PTradeWorkerTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("PTrade subprocess timeout must be positive")
        self._python_executable = python_executable or sys.executable
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _IsolatedSubprocessPTradeWorkerTransport()

    @property
    def adapter_version(self) -> str:
        return PTRADE_SUBPROCESS_HOST_VERSION

    def invoke(self, invocation: PTradeHostInvocation) -> PTradeHostResult:
        request = {
            "protocol_version": PTRADE_SUBPROCESS_PROTOCOL_VERSION,
            "invocation": invocation.to_dict(),
        }
        response_text = self._transport.exchange(
            _canonical_json(request),
            python_executable=self._python_executable,
            timeout_seconds=self._timeout_seconds,
        )
        return _decode_subprocess_response(response_text)


class _IsolatedSubprocessPTradeWorkerTransport:
    def exchange(
        self,
        request_text: str,
        *,
        python_executable: str,
        timeout_seconds: float,
    ) -> str:
        package_root = str(Path(__file__).resolve().parent.parent)
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            package_root
            if not existing_python_path
            else os.pathsep.join((package_root, existing_python_path))
        )
        try:
            with tempfile.TemporaryDirectory(
                prefix="uti-ptrade-host-"
            ) as working_directory:
                completed = subprocess.run(
                    [
                        python_executable,
                        "-m",
                        "strategy_diagnostics.ptrade_host_worker",
                    ],
                    input=request_text,
                    cwd=working_directory,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=timeout_seconds,
                )
        except subprocess.TimeoutExpired as error:
            raise PTradeHostProcessError(
                "PTrade subprocess exceeded its isolated execution timeout"
            ) from error
        except OSError as error:
            raise PTradeHostProcessError(
                "PTrade subprocess could not be started in isolation"
            ) from error
        if completed.returncode != 0:
            raise PTradeHostProcessError(
                "PTrade subprocess failed in isolation with exit code "
                f"{completed.returncode}: {completed.stderr.strip()}"
            )
        return completed.stdout


def _decode_subprocess_response(response_text: str) -> PTradeHostResult:
    try:
        raw_envelope = json.loads(response_text)
    except (json.JSONDecodeError, TypeError) as error:
        raise PTradeHostProcessError(
            "PTrade subprocess returned an invalid JSON envelope"
        ) from error
    if not isinstance(raw_envelope, dict):
        raise PTradeHostProcessError(
            "PTrade subprocess response envelope must be a JSON object"
        )
    envelope = cast(dict[str, object], raw_envelope)
    if envelope.get("protocol_version") != PTRADE_SUBPROCESS_PROTOCOL_VERSION:
        raise PTradeHostProcessError(
            "PTrade subprocess response protocol version does not match"
        )
    ok = envelope.get("ok")
    if type(ok) is not bool:
        raise PTradeHostProcessError(
            "PTrade subprocess response 'ok' field must be boolean"
        )
    if ok is False:
        error_type = envelope.get("error_type")
        message = envelope.get("message")
        if not isinstance(error_type, str) or not isinstance(message, str):
            raise PTradeHostProcessError(
                "PTrade subprocess error envelope is missing typed fields"
            )
        if error_type == "PTradeCompatibilityError":
            call = envelope.get("call")
            surface_version = envelope.get("surface_version")
            if not isinstance(call, str) or not isinstance(surface_version, str):
                raise PTradeHostProcessError(
                    "PTrade compatibility error envelope is incomplete"
                )
            raise PTradeCompatibilityError(
                call,
                detail=message,
                surface_version=surface_version,
            )
        raise PTradeHostProcessError(f"{error_type}: {message}")
    result_payload = envelope.get("result")
    if not isinstance(result_payload, dict):
        raise PTradeHostProcessError(
            "PTrade subprocess success envelope is missing a result object"
        )
    try:
        result = PTradeHostResult.from_dict(
            cast(dict[str, object], result_payload)
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PTradeHostProcessError(
            "PTrade subprocess result does not match the host contract"
        ) from error
    expected_identity = (
        PTRADE_SURFACE_VERSION,
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.content_hash,
        PTRADE_SUBPROCESS_HOST_VERSION,
    )
    actual_identity = (
        result.surface_version,
        result.manifest_hash,
        result.host_adapter_version,
    )
    if actual_identity != expected_identity:
        raise PTradeHostProcessError(
            "PTrade subprocess result identity does not match the registered host"
        )
    return result


class _PTradeRuntime:
    def __init__(
        self,
        invocation: PTradeHostInvocation,
        state: PTradeRuntimeState,
    ) -> None:
        self.invocation = invocation
        self.universe = list(invocation.market_snapshot.eligible_universe)
        self.schedules = list(state.scheduled_callbacks)
        self.strategy_state = dict(state.strategy_state)
        self.lifecycle_events: list[str] = []
        self.configuration_requests: list[PTradeConfigurationRequest] = []
        self.order_requests: list[PTradeOrderRequest] = []
        self.market_data_calls: list[str] = []
        self.log_records: list[PTradeLogRecord] = []
        self.initialized = state.initialized

    @property
    def context(self) -> PTradeContext:
        return PTradeContext(
            current_dt=self.invocation.simulation_time,
            portfolio=self.invocation.portfolio,
            state=self.strategy_state,
            eligible_universe=self.invocation.market_snapshot.eligible_universe,
            decision_cadence_minutes=self.invocation.decision_cadence_minutes,
            order_shares=self.invocation.order_shares,
        )

    def run_daily(
        self,
        callback: Callable[[PTradeContext], None],
        *,
        cadence_minutes: int,
    ) -> None:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("run_daily")
        callback_name = getattr(callback, "__name__", "")
        if callback_name not in (
            REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.scheduled_callbacks
        ):
            raise PTradeCompatibilityError(f"run_daily:{callback_name or '<anonymous>'}")
        if cadence_minutes != self.invocation.decision_cadence_minutes:
            raise PTradeCompatibilityError(
                "run_daily",
                detail="scheduled cadence differs from the pinned Strategy Run cadence",
            )
        schedule = (callback_name, cadence_minutes)
        if schedule not in self.schedules:
            self.schedules.append(schedule)

    def set_universe(self, instruments: Sequence[str]) -> None:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("set_universe")
        normalized = tuple(dict.fromkeys(str(item) for item in instruments))
        eligible = self.invocation.market_snapshot.eligible_universe
        if set(normalized) != set(eligible):
            raise PTradeCompatibilityError(
                "set_universe",
                detail="the requested universe must equal the active Eligible Universe",
            )
        self.universe = list(normalized)

    def set_slippage(self, value: Decimal) -> None:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("set_slippage")
        self.configuration_requests.append(
            PTradeConfigurationRequest(call="set_slippage", value=value)
        )

    def set_commission(self, value: Decimal) -> None:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("set_commission")
        self.configuration_requests.append(
            PTradeConfigurationRequest(call="set_commission", value=value)
        )

    def get_history(
        self,
        *,
        count: int,
        unit: str,
        fields: tuple[str, ...],
    ) -> dict[str, tuple[dict[str, object], ...]]:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("get_history")
        if count <= 0 or unit != "30s":
            raise PTradeCompatibilityError(
                "get_history",
                detail="ptrade_surface.v1 reference strategy accepts positive 30s reads",
            )
        allowed_fields = {"open", "high", "low", "close", "volume", "amount"}
        if not fields or any(field not in allowed_fields for field in fields):
            raise PTradeCompatibilityError(
                "get_history",
                detail="an unsupported point-in-time history field was requested",
            )
        self.market_data_calls.append(
            f"get_history:{unit}:{count}:{','.join(fields)}"
        )
        result: dict[str, tuple[dict[str, object], ...]] = {}
        for instrument in self.universe:
            nodes = [
                node
                for node in self.invocation.market_history
                if node.instrument == instrument
                and node.simulation_time <= self.invocation.simulation_time
            ][-count:]
            result[instrument] = tuple(
                {
                    "simulation_time": node.simulation_time,
                    **{field: getattr(node, field) for field in fields},
                }
                for node in nodes
            )
        return result

    def get_current_data(self) -> dict[str, MarketPathNode]:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("get_current_data")
        self.market_data_calls.append("get_current_data")
        visible = {
            node.instrument: node
            for node in self.invocation.market_snapshot.latest_nodes
            if node.instrument in set(self.universe)
        }
        if set(visible) != set(self.universe):
            raise PTradeCompatibilityError(
                "get_current_data",
                detail="current data is incomplete for the active strategy universe",
            )
        return visible

    def order(self, instrument: str, amount: int) -> None:
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call("order")
        if instrument not in self.universe:
            raise PTradeCompatibilityError(
                "order",
                detail="orders must target the active scenario Eligible Universe",
            )
        self.order_requests.append(
            PTradeOrderRequest(instrument=instrument, amount=amount)
        )

    def log(self, level: LogLevel, message: str) -> None:
        call = f"log.{level}"
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.require_call(call)
        self.log_records.append(PTradeLogRecord(level=level, message=message))

    def snapshot_state(self) -> PTradeRuntimeState:
        return PTradeRuntimeState(
            initialized=self.initialized,
            universe=tuple(self.universe),
            scheduled_callbacks=tuple(self.schedules),
            strategy_state=tuple(sorted(self.strategy_state.items())),
        )


class _PTradeLogFacade:
    def __init__(self, runtime: _PTradeRuntime) -> None:
        self._runtime = runtime

    def info(self, message: str) -> None:
        self._runtime.log("info", message)

    def warning(self, message: str) -> None:
        self._runtime.log("warning", message)

    def error(self, message: str) -> None:
        self._runtime.log("error", message)

    def __getattr__(self, name: str) -> object:
        raise PTradeCompatibilityError(f"log.{name}")


def _load_reference_strategy_module() -> ModuleType:
    manifest = REFERENCE_PTRADE_COMPATIBILITY_MANIFEST
    specification = importlib.util.find_spec(manifest.strategy_module)
    if specification is None or specification.loader is None:
        raise PTradeCompatibilityError(
            f"strategy_module:{manifest.strategy_module}",
            detail="registered strategy module cannot be loaded",
        )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _inject_ptrade_surface(module: ModuleType, runtime: _PTradeRuntime) -> None:
    setattr(module, "set_universe", runtime.set_universe)
    setattr(module, "set_slippage", runtime.set_slippage)
    setattr(module, "set_commission", runtime.set_commission)
    setattr(module, "run_daily", runtime.run_daily)
    setattr(module, "get_history", runtime.get_history)
    setattr(module, "get_current_data", runtime.get_current_data)
    setattr(module, "order", runtime.order)
    setattr(module, "log", _PTradeLogFacade(runtime))


def _require_strategy_callback(
    module: ModuleType,
    callback_name: str,
) -> Callable[..., object]:
    callback = getattr(module, callback_name, None)
    if not callable(callback):
        raise PTradeCompatibilityError(
            f"callback:{callback_name}",
            detail="registered strategy callback is missing or not callable",
        )
    return cast(Callable[..., object], callback)


def _invoke_strategy_callback(
    callback: Callable[..., object],
    *args: object,
) -> None:
    try:
        callback(*args)
    except NameError as error:
        missing_name = error.name or "unknown_global"
        raise PTradeCompatibilityError(
            missing_name,
            detail="strategy referenced a global outside the injected surface",
        ) from error


def _execute_reference_invocation(
    invocation: PTradeHostInvocation,
    *,
    host_adapter_version: str,
) -> PTradeHostResult:
    manifest = REFERENCE_PTRADE_COMPATIBILITY_MANIFEST
    if invocation.compatibility_manifest_hash != manifest.content_hash:
        raise PTradeCompatibilityError(
            "compatibility_manifest",
            detail="manifest hash differs from the registered reference strategy",
        )
    if (invocation.strategy_id, invocation.strategy_version) != (
        manifest.strategy_id,
        manifest.strategy_version,
    ):
        raise PTradeCompatibilityError(
            f"strategy:{invocation.strategy_id}@{invocation.strategy_version}"
        )
    runtime = _PTradeRuntime(
        invocation,
        invocation.runtime_state or PTradeRuntimeState.empty(),
    )
    module = _load_reference_strategy_module()
    _inject_ptrade_surface(module, runtime)
    context = runtime.context
    if invocation.event == "initialize" and runtime.initialized:
        raise PTradeCompatibilityError(
            "initialize",
            detail="strategy initialization may only run once",
        )
    if not runtime.initialized:
        runtime.lifecycle_events.append("initialize")
        _invoke_strategy_callback(
            _require_strategy_callback(module, "initialize"),
            context,
        )
        runtime.initialized = True
    if invocation.event == "decision":
        for callback_name, cadence_minutes in tuple(runtime.schedules):
            if cadence_minutes != invocation.decision_cadence_minutes:
                continue
            runtime.lifecycle_events.append(f"scheduled:{callback_name}")
            _invoke_strategy_callback(
                _require_strategy_callback(module, callback_name),
                context,
            )
    elif invocation.event == "handle_data":
        runtime.lifecycle_events.append("handle_data")
        _invoke_strategy_callback(
            _require_strategy_callback(module, "handle_data"),
            context,
            runtime.get_current_data(),
        )
    worker_global_counter = int(getattr(module, "strategy_global_counter", 0))
    return PTradeHostResult(
        surface_version=manifest.surface_version,
        manifest_hash=manifest.content_hash,
        host_adapter_version=host_adapter_version,
        lifecycle_events=tuple(runtime.lifecycle_events),
        scheduled_callbacks=tuple(runtime.schedules),
        configuration_requests=tuple(runtime.configuration_requests),
        order_requests=tuple(runtime.order_requests),
        market_data_calls=tuple(runtime.market_data_calls),
        log_records=tuple(runtime.log_records),
        runtime_state=runtime.snapshot_state(),
        process_id=os.getpid(),
        worker_global_counter=worker_global_counter,
        random_probe=format(random.Random(invocation.random_seed).random(), ".17g"),
    )


def subprocess_worker_response(request_text: str) -> str:
    """Execute one trusted JSON request for ``ptrade_host_worker``."""

    try:
        request = cast(Mapping[str, object], json.loads(request_text))
        if request.get("protocol_version") != PTRADE_SUBPROCESS_PROTOCOL_VERSION:
            raise PTradeCompatibilityError(
                "subprocess_protocol",
                detail="unsupported subprocess protocol version",
            )
        invocation = PTradeHostInvocation.from_dict(
            cast(Mapping[str, object], request["invocation"])
        )
        result = _execute_reference_invocation(
            invocation,
            host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
        )
        return _canonical_json(
            {
                "protocol_version": PTRADE_SUBPROCESS_PROTOCOL_VERSION,
                "ok": True,
                "result": result.to_dict(),
            }
        )
    except PTradeCompatibilityError as error:
        return _canonical_json(
            {
                "protocol_version": PTRADE_SUBPROCESS_PROTOCOL_VERSION,
                "ok": False,
                "error_type": type(error).__name__,
                "message": str(error),
                "call": error.call,
                "surface_version": error.surface_version,
            }
        )
    except Exception as error:
        return _canonical_json(
            {
                "protocol_version": PTRADE_SUBPROCESS_PROTOCOL_VERSION,
                "ok": False,
                "error_type": type(error).__name__,
                "message": str(error),
            }
        )


def _market_node_from_dict(payload: Mapping[str, object]) -> MarketPathNode:
    features = cast(Mapping[str, object], payload.get("features", {}))
    return MarketPathNode(
        instrument=str(payload["instrument"]),
        simulation_time=datetime.fromisoformat(str(payload["simulation_time"])),
        open=Decimal(str(payload["open"])),
        high=Decimal(str(payload["high"])),
        low=Decimal(str(payload["low"])),
        close=Decimal(str(payload["close"])),
        volume=int(str(payload["volume"])),
        amount=Decimal(str(payload["amount"])),
        reconstructed=bool(payload["reconstructed"]),
        features=tuple(
            sorted((str(name), Decimal(str(value))) for name, value in features.items())
        ),
    )


def _instrument_state_from_dict(payload: Mapping[str, object]) -> InstrumentState:
    raw_factor = payload.get("decision_adjustment_factor")
    return InstrumentState(
        instrument=str(payload["instrument"]),
        effective_at=datetime.fromisoformat(str(payload["effective_at"])),
        eligible=bool(payload["eligible"]),
        trading_status=str(payload["trading_status"]),
        is_st=bool(payload["is_st"]),
        industry=str(payload["industry"]),
        decision_adjustment_factor=(
            Decimal(str(raw_factor)) if raw_factor is not None else None
        ),
        decision_adjustment_provenance=str(
            payload["decision_adjustment_provenance"]
        ),
    )


__all__ = [
    "InProcessPTradeStrategyHost",
    "PTRADE_IN_PROCESS_HOST_VERSION",
    "PTRADE_SUBPROCESS_HOST_VERSION",
    "PTRADE_SURFACE_VERSION",
    "PTradeAuditOrderRequest",
    "PTradeCompatibilityError",
    "PTradeCompatibilityManifest",
    "PTradeConfigurationRequest",
    "PTradeContext",
    "PTradeHostInvocation",
    "PTradeHostEvent",
    "PTradeHostProcessError",
    "PTradeHostResult",
    "PTradeLogRecord",
    "PTradeOrderRequest",
    "PTradePortfolioSnapshot",
    "PTradePositionSnapshot",
    "PTradeRunAudit",
    "PTradeRuntimeState",
    "PTradeStrategyHost",
    "PTradeWorkerTransport",
    "REFERENCE_PTRADE_COMPATIBILITY_MANIFEST",
    "REFERENCE_PTRADE_STRATEGY_ID",
    "REFERENCE_PTRADE_STRATEGY_VERSION",
    "SubprocessPTradeStrategyHost",
]
