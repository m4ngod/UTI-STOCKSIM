"""Deterministic baseline Reference Market Path materialization contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterable, Mapping, Protocol

from .historical_segments import HistoricalMarketSegment


_PRICE_TOLERANCE = Decimal("0.000001")
_EXPANDER_VERSION = "within-bar-expander-v1"


def _canonical_hash(payload: object) -> str:
    encoded = _json_dumps(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_dumps(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _adjustment_payload(state: "InstrumentState") -> dict[str, str | None]:
    factor = state.adjustment_factor
    return {
        "factor": _decimal_text(factor) if factor is not None else None,
        "provenance": state.adjustment_provenance,
    }


@dataclass(frozen=True, slots=True)
class FiveMinuteBar:
    """One normalized, canonical-unadjusted source bar."""

    instrument: str
    end_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("instrument must not be empty")
        if self.end_time.tzinfo is not None:
            raise ValueError("Simulation Time must be timezone-naive market-local time")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("source OHLC prices must be positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("source high violates OHLC constraints")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("source low violates OHLC constraints")
        if self.volume < 0 or self.amount < 0:
            raise ValueError("source volume and amount must be nonnegative")

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "end_time": self.end_time.isoformat(),
            "open": _decimal_text(self.open),
            "high": _decimal_text(self.high),
            "low": _decimal_text(self.low),
            "close": _decimal_text(self.close),
            "volume": self.volume,
            "amount": _decimal_text(self.amount),
        }


@dataclass(frozen=True, slots=True)
class InstrumentState:
    """Point-in-time Eligible Universe and reference-data state."""

    instrument: str
    effective_at: datetime
    eligible: bool
    trading_status: str
    is_st: bool
    industry: str
    adjustment_factor: Decimal | None
    adjustment_provenance: str

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("instrument must not be empty")
        if self.effective_at.tzinfo is not None:
            raise ValueError("Simulation Time must be timezone-naive market-local time")
        if self.trading_status not in {"trading", "suspended"}:
            raise ValueError("trading_status must be trading or suspended")
        if not self.industry.strip():
            raise ValueError("industry must not be empty")
        if self.adjustment_factor is not None and self.adjustment_factor <= 0:
            raise ValueError("adjustment_factor must be positive when present")
        if not self.adjustment_provenance.strip():
            raise ValueError("adjustment_provenance must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "effective_at": self.effective_at.isoformat(),
            "eligible": self.eligible,
            "trading_status": self.trading_status,
            "is_st": self.is_st,
            "industry": self.industry,
            "adjustment_factor": (
                _decimal_text(self.adjustment_factor)
                if self.adjustment_factor is not None
                else None
            ),
            "adjustment_provenance": self.adjustment_provenance,
        }


@dataclass(frozen=True, slots=True)
class ScenarioDataWorldInput:
    """Admitted point-in-time inputs used by baseline materialization."""

    segment_id: str
    segment_content_hash: str
    source_snapshot_id: str
    bars: tuple[FiveMinuteBar, ...]
    instrument_states: tuple[InstrumentState, ...]

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError("Scenario Data World input requires five-minute bars")
        if not self.instrument_states:
            raise ValueError("Scenario Data World input requires instrument states")


class HistoricalMarketDataSource(Protocol):
    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput: ...


class InMemoryHistoricalMarketDataSource:
    """Deterministic historical-data boundary fixture."""

    def __init__(self, worlds: Iterable[ScenarioDataWorldInput]) -> None:
        self._worlds = {world.segment_id: world for world in worlds}

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        try:
            return self._worlds[segment.segment_id]
        except KeyError as exc:
            raise ValueError("No materialization input exists for this segment") from exc


@dataclass(frozen=True, slots=True)
class MarketPathNode:
    instrument: str
    simulation_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    reconstructed: bool
    features: tuple[tuple[str, Decimal], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "simulation_time": self.simulation_time.isoformat(),
            "open": _decimal_text(self.open),
            "high": _decimal_text(self.high),
            "low": _decimal_text(self.low),
            "close": _decimal_text(self.close),
            "volume": self.volume,
            "amount": _decimal_text(self.amount),
            "reconstructed": self.reconstructed,
            "features": {name: _decimal_text(value) for name, value in self.features},
        }


@dataclass(frozen=True, slots=True)
class MaterializedMarketPath:
    artifact_hash: str
    segment_id: str
    segment_content_hash: str
    source_snapshot_id: str
    seed: int
    expander_version: str
    source_resolution: str
    runtime_resolution: str
    reconstructed: bool
    numeric_tolerance: str
    nodes: tuple[MarketPathNode, ...]
    instrument_states: tuple[InstrumentState, ...]

    def to_preview_dict(self) -> dict[str, object]:
        return {
            "artifact_hash": self.artifact_hash,
            "segment_id": self.segment_id,
            "source_snapshot_id": self.source_snapshot_id,
            "seed": self.seed,
            "expander_version": self.expander_version,
            "source_resolution": self.source_resolution,
            "runtime_resolution": self.runtime_resolution,
            "reconstructed": self.reconstructed,
            "numeric_tolerance": self.numeric_tolerance,
            "node_count": len(self.nodes),
            "instrument_count": len(
                {state.instrument for state in self.instrument_states if state.eligible}
            ),
            "start_time": self.nodes[0].simulation_time.isoformat(),
            "end_time": self.nodes[-1].simulation_time.isoformat(),
            "first_node": self.nodes[0].to_dict(),
            "last_node": self.nodes[-1].to_dict(),
        }


class MarketPathArtifactStore(Protocol):
    def put(self, path: MaterializedMarketPath) -> MaterializedMarketPath: ...

    def get(self, artifact_hash: str) -> MaterializedMarketPath: ...


class InMemoryMarketPathArtifactStore:
    def __init__(self) -> None:
        self._paths: dict[str, MaterializedMarketPath] = {}

    def put(self, path: MaterializedMarketPath) -> MaterializedMarketPath:
        existing = self._paths.get(path.artifact_hash)
        if existing is not None and existing != path:
            raise ValueError("immutable Materialized Market Path identity collision")
        self._paths[path.artifact_hash] = path
        return self._paths[path.artifact_hash]

    def get(self, artifact_hash: str) -> MaterializedMarketPath:
        try:
            return self._paths[artifact_hash]
        except KeyError as exc:
            raise KeyError("unknown Materialized Market Path artifact") from exc


class ParquetMarketPathArtifactStore:
    """Content-addressed local Parquet adapter hidden behind the store port."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @classmethod
    def from_environment(cls) -> "ParquetMarketPathArtifactStore":
        configured = os.environ.get("STOCK_SIM_DIAGNOSTICS_ARTIFACT_ROOT", "").strip()
        if configured:
            root = Path(configured)
        else:
            local_data = Path(
                os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
            )
            root = local_data / "UTI-STOCKSIM" / "diagnostics" / "market_paths"
        return cls(root)

    def put(self, path: MaterializedMarketPath) -> MaterializedMarketPath:
        if _canonical_hash(_materialized_content(path)) != path.artifact_hash:
            raise ValueError("Materialized Market Path content hash is invalid")
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._artifact_directory(path.artifact_hash)
        if destination.is_dir():
            existing = self.get(path.artifact_hash)
            if existing != path:
                raise ValueError("immutable Materialized Market Path identity collision")
            return existing
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self._root))
        try:
            self._write_parquet(path, staging)
            (staging / "manifest.json").write_text(
                _json_dumps(_manifest_payload(path)),
                encoding="utf-8",
            )
            staging.replace(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return self.get(path.artifact_hash)

    def get(self, artifact_hash: str) -> MaterializedMarketPath:
        artifact_directory = self._artifact_directory(artifact_hash)
        try:
            manifest = json.loads(
                (artifact_directory / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise KeyError("unknown Materialized Market Path artifact") from exc
        nodes, states = self._read_parquet(artifact_directory)
        path = MaterializedMarketPath(
            artifact_hash=str(manifest["artifact_hash"]),
            segment_id=str(manifest["segment_id"]),
            segment_content_hash=str(manifest["segment_content_hash"]),
            source_snapshot_id=str(manifest["source_snapshot_id"]),
            seed=int(manifest["seed"]),
            expander_version=str(manifest["expander_version"]),
            source_resolution=str(manifest["source_resolution"]),
            runtime_resolution=str(manifest["runtime_resolution"]),
            reconstructed=bool(manifest["reconstructed"]),
            numeric_tolerance=str(manifest["numeric_tolerance"]),
            nodes=nodes,
            instrument_states=states,
        )
        if path.artifact_hash != artifact_hash:
            raise ValueError("artifact manifest identity does not match its address")
        if _canonical_hash(_materialized_content(path)) != artifact_hash:
            raise ValueError("stored Materialized Market Path failed hash verification")
        return path

    def _artifact_directory(self, artifact_hash: str) -> Path:
        if len(artifact_hash) != 64 or any(
            character not in "0123456789abcdef" for character in artifact_hash
        ):
            raise ValueError("artifact_hash must be lowercase SHA-256")
        return self._root / artifact_hash

    @staticmethod
    def _write_parquet(path: MaterializedMarketPath, directory: Path) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB is required for Materialized Market Path storage"
            ) from exc
        nodes_path = directory / "nodes.parquet"
        states_path = directory / "instrument_states.parquet"
        with duckdb.connect(":memory:") as connection:
            connection.execute(
                "CREATE TABLE nodes (instrument VARCHAR, simulation_time VARCHAR, "
                "open VARCHAR, high VARCHAR, low VARCHAR, close VARCHAR, "
                "volume BIGINT, amount VARCHAR, reconstructed BOOLEAN, "
                "features_json VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        node.instrument,
                        node.simulation_time.isoformat(),
                        str(node.open),
                        str(node.high),
                        str(node.low),
                        str(node.close),
                        node.volume,
                        str(node.amount),
                        node.reconstructed,
                        _json_dumps({name: str(value) for name, value in node.features}),
                    )
                    for node in path.nodes
                ],
            )
            connection.execute(
                "CREATE TABLE instrument_states (instrument VARCHAR, "
                "effective_at VARCHAR, eligible BOOLEAN, trading_status VARCHAR, "
                "is_st BOOLEAN, industry VARCHAR, adjustment_factor VARCHAR, "
                "adjustment_provenance VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO instrument_states VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        state.instrument,
                        state.effective_at.isoformat(),
                        state.eligible,
                        state.trading_status,
                        state.is_st,
                        state.industry,
                        (
                            str(state.adjustment_factor)
                            if state.adjustment_factor is not None
                            else None
                        ),
                        state.adjustment_provenance,
                    )
                    for state in path.instrument_states
                ],
            )
            connection.execute(
                f"COPY nodes TO {_duckdb_string(nodes_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            connection.execute(
                f"COPY instrument_states TO {_duckdb_string(states_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )

    @staticmethod
    def _read_parquet(
        directory: Path,
    ) -> tuple[tuple[MarketPathNode, ...], tuple[InstrumentState, ...]]:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB is required for Materialized Market Path storage"
            ) from exc
        with duckdb.connect(":memory:") as connection:
            node_rows = connection.execute(
                "SELECT instrument, simulation_time, open, high, low, close, "
                "volume, amount, reconstructed, features_json FROM read_parquet("
                f"{_duckdb_string(directory / 'nodes.parquet')}) "
                "ORDER BY simulation_time, instrument"
            ).fetchall()
            state_rows = connection.execute(
                "SELECT instrument, effective_at, eligible, trading_status, is_st, "
                "industry, adjustment_factor, adjustment_provenance "
                f"FROM read_parquet({_duckdb_string(directory / 'instrument_states.parquet')}) "
                "ORDER BY effective_at, instrument"
            ).fetchall()
        nodes = tuple(
            MarketPathNode(
                instrument=str(row[0]),
                simulation_time=datetime.fromisoformat(str(row[1])),
                open=Decimal(str(row[2])),
                high=Decimal(str(row[3])),
                low=Decimal(str(row[4])),
                close=Decimal(str(row[5])),
                volume=int(row[6]),
                amount=Decimal(str(row[7])),
                reconstructed=bool(row[8]),
                features=tuple(
                    (str(name), Decimal(str(value)))
                    for name, value in json.loads(str(row[9])).items()
                ),
            )
            for row in node_rows
        )
        states = tuple(
            InstrumentState(
                instrument=str(row[0]),
                effective_at=datetime.fromisoformat(str(row[1])),
                eligible=bool(row[2]),
                trading_status=str(row[3]),
                is_st=bool(row[4]),
                industry=str(row[5]),
                adjustment_factor=(
                    Decimal(str(row[6])) if row[6] is not None else None
                ),
                adjustment_provenance=str(row[7]),
            )
            for row in state_rows
        )
        return nodes, states


class FutureDataAccessError(ValueError):
    """Raised when a caller asks beyond the Scenario Market View cursor."""


@dataclass(frozen=True, slots=True)
class ScenarioMarketSnapshot:
    simulation_time: datetime
    eligible_universe: tuple[str, ...]
    states: tuple[InstrumentState, ...]
    latest_nodes: tuple[MarketPathNode, ...]

    def to_dict(self) -> dict[str, object]:
        state_by_instrument = {state.instrument: state for state in self.states}
        node_by_instrument = {node.instrument: node for node in self.latest_nodes}
        return {
            "simulation_time": self.simulation_time.isoformat(),
            "eligible_universe": list(self.eligible_universe),
            "trading_status": {
                instrument: {
                    "status": state_by_instrument[instrument].trading_status,
                    "is_st": state_by_instrument[instrument].is_st,
                }
                for instrument in self.eligible_universe
            },
            "industries": {
                instrument: state_by_instrument[instrument].industry
                for instrument in self.eligible_universe
            },
            "adjustments": {
                instrument: _adjustment_payload(state_by_instrument[instrument])
                for instrument in self.eligible_universe
            },
            "features": {
                instrument: {
                    name: _decimal_text(value)
                    for name, value in node_by_instrument[instrument].features
                }
                for instrument in self.eligible_universe
                if instrument in node_by_instrument
            },
            "latest_nodes": {
                instrument: node_by_instrument[instrument].to_dict()
                for instrument in self.eligible_universe
                if instrument in node_by_instrument
            },
        }


class ScenarioMarketView:
    """Read one immutable Reference Market Path through Simulation Time."""

    def __init__(
        self,
        path: MaterializedMarketPath,
        *,
        initial_cursor: datetime,
    ) -> None:
        if initial_cursor.tzinfo is not None:
            raise ValueError("Simulation Time cursor must be timezone-naive")
        earliest_state = min(
            state.effective_at for state in path.instrument_states
        )
        if initial_cursor < earliest_state or initial_cursor > path.nodes[-1].simulation_time:
            raise ValueError("initial cursor lies outside the materialized market path")
        self._path = path
        self._cursor = initial_cursor

    @property
    def artifact_hash(self) -> str:
        return self._path.artifact_hash

    @property
    def simulation_time(self) -> datetime:
        return self._cursor

    def advance_to(self, simulation_time: datetime) -> None:
        if simulation_time < self._cursor:
            raise ValueError("Simulation Time cursor cannot move backwards")
        if simulation_time > self._path.nodes[-1].simulation_time:
            raise ValueError("Simulation Time cursor cannot move beyond the path")
        self._cursor = simulation_time

    def history(self, instrument: str) -> tuple[MarketPathNode, ...]:
        return tuple(
            node
            for node in self._path.nodes
            if node.instrument == instrument
            and node.simulation_time <= self._cursor
        )

    def node_at(
        self,
        instrument: str,
        simulation_time: datetime,
    ) -> MarketPathNode | None:
        if simulation_time > self._cursor:
            raise FutureDataAccessError(
                "Requested market data is later than the current Simulation Time cursor"
            )
        return next(
            (
                node
                for node in self._path.nodes
                if node.instrument == instrument
                and node.simulation_time == simulation_time
            ),
            None,
        )

    def snapshot(self) -> ScenarioMarketSnapshot:
        state_by_instrument: dict[str, InstrumentState] = {}
        for state in self._path.instrument_states:
            if state.effective_at <= self._cursor:
                state_by_instrument[state.instrument] = state
        eligible_universe = tuple(
            sorted(
                instrument
                for instrument, state in state_by_instrument.items()
                if state.eligible
            )
        )
        latest_by_instrument: dict[str, MarketPathNode] = {}
        for node in self._path.nodes:
            if (
                node.simulation_time <= self._cursor
                and node.instrument in eligible_universe
            ):
                latest_by_instrument[node.instrument] = node
        return ScenarioMarketSnapshot(
            simulation_time=self._cursor,
            eligible_universe=eligible_universe,
            states=tuple(state_by_instrument[item] for item in eligible_universe),
            latest_nodes=tuple(
                latest_by_instrument[item]
                for item in eligible_universe
                if item in latest_by_instrument
            ),
        )


def _expand_bar(bar: FiveMinuteBar, seed: int) -> tuple[MarketPathNode, ...]:
    digest = hashlib.sha256(
        f"{_EXPANDER_VERSION}|{seed}|{bar.instrument}|{bar.end_time.isoformat()}".encode(
            "utf-8"
        )
    ).digest()
    earlier_index = 2 + digest[1] % 2
    later_index = 6 + digest[2] % 2
    high_index, low_index = (
        (earlier_index, later_index)
        if digest[0] % 2 == 0
        else (later_index, earlier_index)
    )
    closes = [bar.open] * 10
    closes[high_index] = bar.high
    closes[low_index] = bar.low
    closes[-1] = bar.close

    base_volume, remainder = divmod(bar.volume, 10)
    volume_parts = [base_volume] * 10
    offset = digest[3] % 10
    for index in range(remainder):
        volume_parts[(offset + index * 3) % 10] += 1
    base_amount = bar.amount / Decimal(10)
    amount_parts = [base_amount] * 9
    amount_parts.append(bar.amount - sum(amount_parts, Decimal("0")))

    nodes: list[MarketPathNode] = []
    previous = bar.open
    interval_start = bar.end_time - timedelta(minutes=5)
    for index, close in enumerate(closes):
        nodes.append(
            MarketPathNode(
                instrument=bar.instrument,
                simulation_time=interval_start + timedelta(seconds=30 * (index + 1)),
                open=previous,
                high=max(previous, close),
                low=min(previous, close),
                close=close,
                volume=volume_parts[index],
                amount=amount_parts[index],
                reconstructed=True,
            )
        )
        previous = close
    return tuple(nodes)


def _is_a_share_five_minute_bar_end(value: datetime) -> bool:
    minute_of_day = value.hour * 60 + value.minute
    in_session = (
        9 * 60 + 35 <= minute_of_day <= 11 * 60 + 30
        or 13 * 60 + 5 <= minute_of_day <= 15 * 60
    )
    return value.second == 0 and value.microsecond == 0 and minute_of_day % 5 == 0 and in_session


def _with_causal_features(
    nodes: tuple[MarketPathNode, ...],
) -> tuple[MarketPathNode, ...]:
    previous_by_instrument: dict[str, Decimal] = {}
    session_open: dict[tuple[str, object], Decimal] = {}
    enriched: list[MarketPathNode] = []
    for node in nodes:
        previous = previous_by_instrument.get(node.instrument, node.open)
        session_key = (node.instrument, node.simulation_time.date())
        opening = session_open.setdefault(session_key, node.open)
        features = (
            ("return_30s", node.close / previous - Decimal(1)),
            ("session_return", node.close / opening - Decimal(1)),
        )
        enriched.append(replace(node, features=features))
        previous_by_instrument[node.instrument] = node.close
    return tuple(enriched)


def _validate_reaggregation(
    source_bars: tuple[FiveMinuteBar, ...],
    nodes: tuple[MarketPathNode, ...],
) -> None:
    nodes_by_bar: dict[tuple[str, datetime], list[MarketPathNode]] = {}
    for node in nodes:
        bar_end = node.simulation_time + timedelta(
            seconds=(300 - (node.simulation_time.minute * 60 + node.simulation_time.second) % 300)
            % 300
        )
        nodes_by_bar.setdefault((node.instrument, bar_end), []).append(node)
    for source in source_bars:
        expanded = sorted(
            nodes_by_bar.get((source.instrument, source.end_time), ()),
            key=lambda item: item.simulation_time,
        )
        if len(expanded) != 10:
            raise ValueError("a five-minute source bar did not produce ten 30-second nodes")
        actual_prices = (
            expanded[0].open,
            max(node.high for node in expanded),
            min(node.low for node in expanded),
            expanded[-1].close,
        )
        expected_prices = (source.open, source.high, source.low, source.close)
        if any(
            abs(actual - expected) > _PRICE_TOLERANCE
            for actual, expected in zip(actual_prices, expected_prices, strict=True)
        ):
            raise ValueError("reconstructed nodes violate the declared OHLC tolerance")
        if sum(node.volume for node in expanded) != source.volume:
            raise ValueError("reconstructed nodes do not preserve source volume")
        if sum((node.amount for node in expanded), Decimal("0")) != source.amount:
            raise ValueError("reconstructed nodes do not preserve source amount")


def _materialized_content(path: MaterializedMarketPath) -> Mapping[str, object]:
    return {
        "segment_id": path.segment_id,
        "segment_content_hash": path.segment_content_hash,
        "source_snapshot_id": path.source_snapshot_id,
        "seed": path.seed,
        "expander_version": path.expander_version,
        "source_resolution": path.source_resolution,
        "runtime_resolution": path.runtime_resolution,
        "reconstructed": path.reconstructed,
        "numeric_tolerance": path.numeric_tolerance,
        "nodes": [node.to_dict() for node in path.nodes],
        "instrument_states": [
            state.to_dict()
            for state in path.instrument_states
        ],
    }


def _manifest_payload(path: MaterializedMarketPath) -> Mapping[str, object]:
    return {
        "artifact_hash": path.artifact_hash,
        "segment_id": path.segment_id,
        "segment_content_hash": path.segment_content_hash,
        "source_snapshot_id": path.source_snapshot_id,
        "seed": path.seed,
        "expander_version": path.expander_version,
        "source_resolution": path.source_resolution,
        "runtime_resolution": path.runtime_resolution,
        "reconstructed": path.reconstructed,
        "numeric_tolerance": path.numeric_tolerance,
        "node_count": len(path.nodes),
        "instrument_state_count": len(path.instrument_states),
    }


def _duckdb_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


class ScenarioMaterializer:
    """Materialize admitted segments into immutable baseline market paths."""

    def __init__(
        self,
        source: HistoricalMarketDataSource,
        artifact_store: MarketPathArtifactStore,
    ) -> None:
        self._source = source
        self._artifact_store = artifact_store

    def materialize_baseline(
        self,
        segment: HistoricalMarketSegment,
        *,
        seed: int,
    ) -> MaterializedMarketPath:
        world = self._source.load_scenario_data_world(segment)
        if (
            world.segment_id != segment.segment_id
            or world.segment_content_hash != segment.content_hash
            or world.source_snapshot_id != segment.source_snapshot_id
        ):
            raise ValueError(
                "materialization input identity does not match the admitted segment"
            )
        if any(not _is_a_share_five_minute_bar_end(bar.end_time) for bar in world.bars):
            raise ValueError(
                "materialization input contains a bar outside the A-share session grid"
            )
        bar_keys = tuple((bar.instrument, bar.end_time) for bar in world.bars)
        if len(bar_keys) != len(set(bar_keys)):
            raise ValueError("materialization input contains duplicate five-minute bars")
        expanded_by_bar = tuple(
            node
            for bar in sorted(
                world.bars,
                key=lambda item: (item.end_time, item.instrument),
            )
            for node in _expand_bar(bar, seed)
        )
        expanded = tuple(
            sorted(
                expanded_by_bar,
                key=lambda item: (item.simulation_time, item.instrument),
            )
        )
        nodes = _with_causal_features(expanded)
        _validate_reaggregation(world.bars, nodes)
        path = MaterializedMarketPath(
            artifact_hash="",
            segment_id=world.segment_id,
            segment_content_hash=world.segment_content_hash,
            source_snapshot_id=world.source_snapshot_id,
            seed=seed,
            expander_version=_EXPANDER_VERSION,
            source_resolution="5m",
            runtime_resolution="30s",
            reconstructed=True,
            numeric_tolerance=str(_PRICE_TOLERANCE),
            nodes=nodes,
            instrument_states=tuple(
                sorted(
                    world.instrument_states,
                    key=lambda item: (item.effective_at, item.instrument),
                )
            ),
        )
        path = replace(path, artifact_hash=_canonical_hash(_materialized_content(path)))
        return self._artifact_store.put(path)

    def get(self, artifact_hash: str) -> MaterializedMarketPath:
        return self._artifact_store.get(artifact_hash)


__all__ = [
    "FiveMinuteBar",
    "FutureDataAccessError",
    "HistoricalMarketDataSource",
    "InMemoryHistoricalMarketDataSource",
    "InMemoryMarketPathArtifactStore",
    "InstrumentState",
    "MarketPathArtifactStore",
    "MarketPathNode",
    "MaterializedMarketPath",
    "ParquetMarketPathArtifactStore",
    "ScenarioDataWorldInput",
    "ScenarioMarketSnapshot",
    "ScenarioMarketView",
    "ScenarioMaterializer",
]
