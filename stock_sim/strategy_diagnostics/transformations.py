"""Versioned Scenario Transformation Catalog contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import TYPE_CHECKING, Callable, Iterable, Literal, Mapping, Protocol

if TYPE_CHECKING:
    from .market_paths import (
        FiveMinuteBar,
        InstrumentState,
        ScenarioDataWorldInput,
        SessionPriceLimitReference,
    )


ParameterValueType = Literal["decimal", "enum", "integer"]
TransformationPhase = Literal["gap", "shock", "persistence", "recovery"]


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


class TransformationRequest(Protocol):
    @property
    def transformation_id(self) -> str: ...

    @property
    def parameters(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class TransformationParameterDefinition:
    name: str
    value_type: ParameterValueType
    required: bool
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    choices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        view: dict[str, object] = {
            "name": self.name,
            "value_type": self.value_type,
            "required": self.required,
        }
        if self.choices:
            view["choices"] = list(self.choices)
        if self.minimum is not None:
            view["minimum"] = _decimal_text(self.minimum)
        if self.maximum is not None:
            view["maximum"] = _decimal_text(self.maximum)
        return view


@dataclass(frozen=True, slots=True)
class TransformationCatalogEntry:
    transformation_id: str
    family: str
    implementation_version: str
    parameters: tuple[TransformationParameterDefinition, ...]
    compatibility_rules: tuple[str, ...]
    causality_constraints: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "transformation_id": self.transformation_id,
            "family": self.family,
            "implementation_version": self.implementation_version,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "compatibility_rules": list(self.compatibility_rules),
            "causality_constraints": list(self.causality_constraints),
        }


@dataclass(frozen=True, slots=True)
class TransformationCatalogIssue:
    path: str
    rule: str
    message: str
    correction: str


@dataclass(frozen=True, slots=True)
class TransformationPhaseMarker:
    phase: TransformationPhase
    start_source_bar_end_time: datetime
    end_source_bar_end_time: datetime
    source_time_count: int

    def __post_init__(self) -> None:
        if (
            self.start_source_bar_end_time.tzinfo is not None
            or self.end_source_bar_end_time.tzinfo is not None
        ):
            raise ValueError("Transformation phase times must be market-local")
        if self.end_source_bar_end_time < self.start_source_bar_end_time:
            raise ValueError("Transformation phase end cannot precede its start")
        if self.source_time_count <= 0:
            raise ValueError("Transformation phases require source times")

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "start_source_bar_end_time": (
                self.start_source_bar_end_time.isoformat()
            ),
            "end_source_bar_end_time": self.end_source_bar_end_time.isoformat(),
            "source_time_count": self.source_time_count,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> TransformationPhaseMarker:
        phase = payload.get("phase")
        if phase not in ("gap", "shock", "persistence", "recovery"):
            raise ValueError("Stored transformation phase is invalid")
        try:
            start_time = datetime.fromisoformat(
                str(payload["start_source_bar_end_time"])
            )
            end_time = datetime.fromisoformat(
                str(payload["end_source_bar_end_time"])
            )
            source_time_count = int(str(payload["source_time_count"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Stored transformation phase marker is invalid") from exc
        return cls(
            phase=phase,
            start_source_bar_end_time=start_time,
            end_source_bar_end_time=end_time,
            source_time_count=source_time_count,
        )


@dataclass(frozen=True, slots=True)
class AppliedTransformation:
    transformation_id: str
    family: str
    catalog_version: str
    implementation_version: str
    parameters: tuple[tuple[str, str], ...]
    phase_markers: tuple[TransformationPhaseMarker, ...] = ()
    statistics: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        view: dict[str, object] = {
            "transformation_id": self.transformation_id,
            "family": self.family,
            "catalog_version": self.catalog_version,
            "implementation_version": self.implementation_version,
            "parameters": dict(self.parameters),
        }
        if self.phase_markers:
            view["phase_markers"] = [
                marker.to_dict() for marker in self.phase_markers
            ]
        if self.statistics:
            view["statistics"] = dict(self.statistics)
        return view


@dataclass(frozen=True, slots=True)
class _TransformationApplication:
    world: ScenarioDataWorldInput
    phase_markers: tuple[TransformationPhaseMarker, ...] = ()
    statistics: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _ShockRecoveryPlan:
    direction: str
    displacement_by_time: tuple[tuple[datetime, Decimal], ...]
    phase_windows: tuple[
        tuple[TransformationPhase, tuple[datetime, ...]], ...
    ]
    peak_displacement: Decimal


class ScenarioTransformationCatalog:
    """Immutable registry of reviewed deterministic transformations."""

    def __init__(
        self,
        *,
        catalog_version: str,
        entries: Iterable[TransformationCatalogEntry],
    ) -> None:
        ordered = tuple(entries)
        by_id = {entry.transformation_id: entry for entry in ordered}
        if len(by_id) != len(ordered):
            raise ValueError("Transformation Catalog identifiers must be unique")
        self._catalog_version = catalog_version
        self._entries = tuple(sorted(ordered, key=lambda item: item.transformation_id))
        self._by_id = by_id

    @property
    def catalog_version(self) -> str:
        return self._catalog_version

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_version": self.catalog_version,
            "transformations": [entry.to_dict() for entry in self._entries],
        }

    def get_entry(self, transformation_id: str) -> TransformationCatalogEntry:
        try:
            return self._by_id[transformation_id]
        except KeyError as exc:
            raise ValueError(
                f"Transformation {transformation_id!r} is not registered"
            ) from exc

    def validate_requests(
        self,
        requests: Iterable[TransformationRequest],
        *,
        market_rule_profile: str,
        data_policy: str,
    ) -> tuple[TransformationCatalogIssue, ...]:
        issues: list[TransformationCatalogIssue] = []
        seen_families: set[str] = set()
        for index, request in enumerate(requests):
            base_path = f"transformations.{index}"
            entry = self._by_id.get(request.transformation_id)
            if entry is None:
                issues.append(
                    TransformationCatalogIssue(
                        path=f"{base_path}.transformation_id",
                        rule="transformation.not-registered",
                        message=(
                            f"Transformation {request.transformation_id!r} is not registered."
                        ),
                        correction=(
                            "Remove it or choose a registered Transformation Catalog entry."
                        ),
                    )
                )
                continue
            if "a-share-cash-equity.v1" in entry.compatibility_rules and (
                market_rule_profile != "a-share-cash-equity.v1"
            ):
                issues.append(
                    TransformationCatalogIssue(
                        path="market_rule_profile",
                        rule="transformation.incompatible-market-profile",
                        message="The transformation is incompatible with the market profile.",
                        correction="Use market_rule_profile='a-share-cash-equity.v1'.",
                    )
                )
            if "point-in-time-inputs-only" in entry.causality_constraints and (
                data_policy != "point-in-time"
            ):
                issues.append(
                    TransformationCatalogIssue(
                        path="data_policy",
                        rule="causality.point-in-time-required",
                        message="The transformation requires point-in-time inputs.",
                        correction="Use data_policy='point-in-time'.",
                    )
                )
            if (
                "one-transform-per-family" in entry.compatibility_rules
                and entry.family in seen_families
            ):
                issues.append(
                    TransformationCatalogIssue(
                        path=f"{base_path}.transformation_id",
                        rule="transformation.incompatible-combination",
                        message=f"Transformation family {entry.family!r} is already present.",
                        correction="Keep only one transformation from this family.",
                    )
                )
            seen_families.add(entry.family)
            issues.extend(self._validate_parameters(base_path, entry, request.parameters))
        return tuple(issues)

    @staticmethod
    def _validate_parameters(
        base_path: str,
        entry: TransformationCatalogEntry,
        values: Mapping[str, object],
    ) -> tuple[TransformationCatalogIssue, ...]:
        issues: list[TransformationCatalogIssue] = []
        definitions = {parameter.name: parameter for parameter in entry.parameters}
        for name in sorted(set(values) - set(definitions)):
            forbidden_issue = _forbidden_parameter_issue(base_path, name)
            if forbidden_issue is not None:
                issues.append(forbidden_issue)
                continue
            issues.append(
                TransformationCatalogIssue(
                    path=f"{base_path}.parameters.{name}",
                    rule="transformation.parameter-unknown",
                    message=f"Parameter {name!r} is not declared by the catalog entry.",
                    correction="Remove the unsupported parameter.",
                )
            )
        for name, definition in definitions.items():
            path = f"{base_path}.parameters.{name}"
            if name not in values:
                if definition.required:
                    issues.append(
                        TransformationCatalogIssue(
                            path=path,
                            rule="transformation.parameter-required",
                            message=f"Parameter {name!r} is required.",
                            correction="Provide the parameter using the published type and bounds.",
                        )
                    )
                continue
            value = values[name]
            if definition.value_type == "enum":
                if not isinstance(value, str) or value not in definition.choices:
                    issues.append(
                        TransformationCatalogIssue(
                            path=path,
                            rule="transformation.parameter-type",
                            message=f"Parameter {name!r} must be one of {definition.choices!r}.",
                            correction="Choose one of the published values.",
                        )
                    )
                continue
            try:
                if isinstance(value, bool):
                    raise InvalidOperation
                decimal_value = Decimal(str(value))
                if not decimal_value.is_finite():
                    raise InvalidOperation
                if (
                    definition.value_type == "integer"
                    and decimal_value != decimal_value.to_integral_value()
                ):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                expected_type = (
                    "an integer value"
                    if definition.value_type == "integer"
                    else "a decimal value"
                )
                correction = (
                    "Provide an integer string or number."
                    if definition.value_type == "integer"
                    else "Provide a decimal string or number."
                )
                issues.append(
                    TransformationCatalogIssue(
                        path=path,
                        rule="transformation.parameter-type",
                        message=f"Parameter {name!r} must be {expected_type}.",
                        correction=correction,
                    )
                )
                continue
            if (
                definition.minimum is not None
                and decimal_value < definition.minimum
            ) or (
                definition.maximum is not None
                and decimal_value > definition.maximum
            ):
                issues.append(
                    TransformationCatalogIssue(
                        path=path,
                        rule="transformation.parameter-bounds",
                        message=f"Parameter {name!r} is outside the published bounds.",
                        correction=(
                            f"Choose a value from {_decimal_text(definition.minimum or Decimal(0))} "
                            f"through {_decimal_text(definition.maximum or Decimal(0))}."
                        ),
                    )
                )
        return tuple(issues)


def _forbidden_parameter_issue(
    base_path: str,
    name: str,
) -> TransformationCatalogIssue | None:
    normalized = name.lower().replace("-", "_")
    path = f"{base_path}.parameters.{name}"
    if any(token in normalized for token in ("python", "code", "script", "executable")):
        return TransformationCatalogIssue(
            path=path,
            rule="transformation.executable-code-forbidden",
            message="Scenario Recipes cannot contain executable transformation code.",
            correction="Choose a reviewed registered transformation and declared parameters.",
        )
    if any(token in normalized for token in ("expression", "formula", "expr")):
        return TransformationCatalogIssue(
            path=path,
            rule="transformation.expression-forbidden",
            message="Scenario Recipes cannot contain arbitrary expressions or formulas.",
            correction="Use only parameters declared by the Transformation Catalog.",
        )
    if "final" in normalized and any(
        token in normalized for token in ("price", "close", "ohlc", "market_data")
    ):
        return TransformationCatalogIssue(
            path=path,
            rule="transformation.final-price-edit-forbidden",
            message="Scenario Recipes cannot edit final market prices directly.",
            correction="Describe the condition through a registered transformation.",
        )
    if any(token in normalized for token in ("path", "file", "directory", "folder")):
        return TransformationCatalogIssue(
            path=path,
            rule="transformation.path-forbidden",
            message="Scenario Recipes cannot contain filesystem paths.",
            correction="Select admitted data and catalog capabilities by durable identity.",
        )
    return None


def apply_registered_transformations(
    world: ScenarioDataWorldInput,
    requests: Iterable[TransformationRequest],
    *,
    catalog: ScenarioTransformationCatalog,
    market_rule_profile: str = "a-share-cash-equity.v1",
    data_policy: str = "point-in-time",
) -> tuple[ScenarioDataWorldInput, tuple[AppliedTransformation, ...]]:
    ordered_requests = tuple(requests)
    issues = catalog.validate_requests(
        ordered_requests,
        market_rule_profile=market_rule_profile,
        data_policy=data_policy,
    )
    if issues:
        raise ValueError(
            "Invalid Scenario Transformation request: "
            + "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        )
    transformed = world
    applied: list[AppliedTransformation] = []
    for request in ordered_requests:
        entry = catalog.get_entry(request.transformation_id)
        implementation = _TRANSFORMATION_IMPLEMENTATIONS.get(
            entry.transformation_id
        )
        if implementation is None:  # pragma: no cover - registration stays atomic
            raise ValueError(
                f"No implementation exists for {entry.transformation_id!r}"
            )
        outcome = implementation(transformed, request.parameters)
        transformed = outcome.world
        applied.append(
            AppliedTransformation(
                transformation_id=entry.transformation_id,
                family=entry.family,
                catalog_version=catalog.catalog_version,
                implementation_version=entry.implementation_version,
                parameters=_canonical_parameters(entry, request.parameters),
                phase_markers=outcome.phase_markers,
                statistics=outcome.statistics,
            )
        )
    return transformed, tuple(applied)


def _canonical_parameters(
    entry: TransformationCatalogEntry,
    values: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    definitions = {parameter.name: parameter for parameter in entry.parameters}
    canonical: list[tuple[str, str]] = []
    for name in sorted(values):
        definition = definitions[name]
        value = values[name]
        if definition.value_type == "decimal":
            canonical.append((name, _decimal_text(Decimal(str(value)))))
        elif definition.value_type == "integer":
            canonical.append((name, str(int(Decimal(str(value))))))
        else:
            canonical.append((name, str(value)))
    return tuple(canonical)


def _apply_trend_regime(
    world: ScenarioDataWorldInput,
    parameters: Mapping[str, object],
) -> _TransformationApplication:
    direction = str(parameters["direction"])
    strength = Decimal(str(parameters["strength"]))
    sign = Decimal("1") if direction == "bullish" else Decimal("-1")
    maximum_session_shift = Decimal("0.04")
    bars_by_time: dict[datetime, list[FiveMinuteBar]] = {}
    for bar in world.bars:
        bars_by_time.setdefault(bar.end_time, []).append(bar)

    transformed_bars: list[FiveMinuteBar] = []
    for end_time in sorted(bars_by_time):
        bars = bars_by_time[end_time]
        desired_factor = Decimal("1") + (
            sign * strength * maximum_session_shift * _session_progress(end_time)
        )
        factor = _price_limit_safe_factor(
            desired_factor,
            bars,
            world,
            bullish=direction == "bullish",
        )
        transformed_bars.extend(_scale_bar(bar, factor) for bar in bars)
    return _TransformationApplication(
        world=replace(
            world,
            bars=tuple(
                sorted(
                    transformed_bars,
                    key=lambda item: (item.end_time, item.instrument),
                )
            ),
        )
    )


def _apply_volatility_scaling(
    world: ScenarioDataWorldInput,
    parameters: Mapping[str, object],
) -> _TransformationApplication:
    multiplier = Decimal(str(parameters["multiplier"]))
    transformed_bars: list[FiveMinuteBar] = []
    for bar in sorted(
        world.bars,
        key=lambda item: (item.end_time, item.instrument),
    ):
        reference, lower_bound, upper_bound = _validated_bar_price_limit_bounds(
            world,
            bar,
        )

        def scale(price: Decimal) -> Decimal:
            scaled = reference.previous_close + multiplier * (
                price - reference.previous_close
            )
            if lower_bound is not None:
                scaled = max(lower_bound, scaled)
            if upper_bound is not None:
                scaled = min(upper_bound, scaled)
            if scaled <= 0:
                raise ValueError(
                    "Volatility scaling produced a nonpositive market price"
                )
            return scaled

        transformed_open = scale(bar.open)
        transformed_high = scale(bar.high)
        transformed_low = scale(bar.low)
        transformed_close = scale(bar.close)
        transformed_bars.append(
            replace(
                bar,
                open=transformed_open,
                high=transformed_high,
                low=transformed_low,
                close=transformed_close,
                amount=bar.amount * transformed_close / bar.close,
            )
        )
    return _TransformationApplication(
        world=replace(world, bars=tuple(transformed_bars))
    )


def _apply_shock_recovery(
    world: ScenarioDataWorldInput,
    parameters: Mapping[str, object],
) -> _TransformationApplication:
    bars_by_time: dict[datetime, list[FiveMinuteBar]] = {}
    for bar in world.bars:
        bars_by_time.setdefault(bar.end_time, []).append(bar)
    source_times = tuple(sorted(bars_by_time))
    plan = _build_shock_recovery_plan(parameters, source_times)
    transformed_bars, effective_displacements = _apply_shock_recovery_plan(
        world,
        bars_by_time,
        plan,
    )
    return _TransformationApplication(
        world=replace(world, bars=transformed_bars),
        phase_markers=_shock_recovery_phase_markers(plan),
        statistics=_shock_recovery_statistics(
            world,
            bars_by_time,
            effective_displacements,
            requested_peak_displacement=plan.peak_displacement,
        ),
    )


def _build_shock_recovery_plan(
    parameters: Mapping[str, object],
    source_times: tuple[datetime, ...],
) -> _ShockRecoveryPlan:
    direction = str(parameters["direction"])
    gap_fraction = Decimal(str(parameters["gap_fraction"]))
    shock_fraction = Decimal(str(parameters["shock_fraction"]))
    shock_duration = int(Decimal(str(parameters["shock_duration_bars"])))
    persistence_duration = int(
        Decimal(str(parameters["persistence_duration_bars"]))
    )
    recovery_duration = int(Decimal(str(parameters["recovery_duration_bars"])))
    required_source_times = (
        1 + shock_duration + persistence_duration + recovery_duration
    )
    if len(source_times) < required_source_times:
        raise ValueError(
            "Shock/recovery phase composition requires at least "
            f"{required_source_times} distinct source bar times"
        )

    phase_windows: list[tuple[TransformationPhase, tuple[datetime, ...]]] = []
    displacement_by_time = dict.fromkeys(source_times, Decimal("0"))
    cursor = 0

    gap_times = source_times[cursor : cursor + 1]
    phase_windows.append(("gap", gap_times))
    displacement_by_time[gap_times[0]] = gap_fraction
    cursor += 1

    shock_times = source_times[cursor : cursor + shock_duration]
    phase_windows.append(("shock", shock_times))
    for step, end_time in enumerate(shock_times, start=1):
        displacement_by_time[end_time] = gap_fraction + (
            shock_fraction * Decimal(step) / Decimal(shock_duration)
        )
    cursor += shock_duration

    peak_displacement = gap_fraction + shock_fraction
    if persistence_duration:
        persistence_times = source_times[cursor : cursor + persistence_duration]
        phase_windows.append(("persistence", persistence_times))
        for end_time in persistence_times:
            displacement_by_time[end_time] = peak_displacement
        cursor += persistence_duration

    recovery_times = source_times[cursor : cursor + recovery_duration]
    phase_windows.append(("recovery", recovery_times))
    for step, end_time in enumerate(recovery_times, start=1):
        displacement_by_time[end_time] = peak_displacement * (
            Decimal("1") - Decimal(step) / Decimal(recovery_duration)
        )

    return _ShockRecoveryPlan(
        direction=direction,
        displacement_by_time=tuple(
            (end_time, displacement_by_time[end_time])
            for end_time in source_times
        ),
        phase_windows=tuple(phase_windows),
        peak_displacement=peak_displacement,
    )


def _apply_shock_recovery_plan(
    world: ScenarioDataWorldInput,
    bars_by_time: Mapping[datetime, list[FiveMinuteBar]],
    plan: _ShockRecoveryPlan,
) -> tuple[tuple[FiveMinuteBar, ...], tuple[tuple[datetime, Decimal], ...]]:
    sign = Decimal("1") if plan.direction == "bullish" else Decimal("-1")

    transformed_bars: list[FiveMinuteBar] = []
    effective_displacements: list[tuple[datetime, Decimal]] = []
    for end_time, displacement in plan.displacement_by_time:
        bars = bars_by_time[end_time]
        desired_factor = Decimal("1") + sign * displacement
        effective_factor = _price_limit_safe_factor(
            desired_factor,
            bars,
            world,
            bullish=plan.direction == "bullish",
        )
        effective_displacements.append(
            (end_time, abs(effective_factor - Decimal("1")))
        )
        transformed_bars.extend(
            _scale_bar(bar, effective_factor) for bar in bars
        )
    return (
        tuple(
            sorted(
                transformed_bars,
                key=lambda item: (item.end_time, item.instrument),
            )
        ),
        tuple(effective_displacements),
    )


def _shock_recovery_phase_markers(
    plan: _ShockRecoveryPlan,
) -> tuple[TransformationPhaseMarker, ...]:
    return tuple(
        TransformationPhaseMarker(
            phase=phase,
            start_source_bar_end_time=times[0],
            end_source_bar_end_time=times[-1],
            source_time_count=len(times),
        )
        for phase, times in plan.phase_windows
    )


def _shock_recovery_statistics(
    world: ScenarioDataWorldInput,
    bars_by_time: Mapping[datetime, list[FiveMinuteBar]],
    effective_displacements: tuple[tuple[datetime, Decimal], ...],
    *,
    requested_peak_displacement: Decimal,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "affected_source_bar_count": str(
                    sum(
                        len(bars_by_time[end_time])
                        for end_time, displacement in effective_displacements
                        if displacement != 0
                    )
                ),
                "effective_peak_displacement_fraction": _decimal_text(
                    max(
                        displacement
                        for _, displacement in effective_displacements
                    )
                ),
                "requested_peak_displacement_fraction": _decimal_text(
                    requested_peak_displacement
                ),
                "source_bar_count": str(len(world.bars)),
                "source_time_count": str(len(effective_displacements)),
            }.items()
        )
    )


def _scale_bar(bar: FiveMinuteBar, factor: Decimal) -> FiveMinuteBar:
    return replace(
        bar,
        open=bar.open * factor,
        high=bar.high * factor,
        low=bar.low * factor,
        close=bar.close * factor,
        amount=bar.amount * factor,
    )


_TRANSFORMATION_IMPLEMENTATIONS: Mapping[
    str,
    Callable[
        ["ScenarioDataWorldInput", Mapping[str, object]],
        _TransformationApplication,
    ],
] = {
    "shock-recovery.v1": _apply_shock_recovery,
    "trend-regime.v1": _apply_trend_regime,
    "volatility-scaling.v1": _apply_volatility_scaling,
}


def _session_progress(end_time: datetime) -> Decimal:
    minute = end_time.hour * 60 + end_time.minute
    if minute <= 11 * 60 + 30:
        elapsed = minute - (9 * 60 + 30)
    else:
        elapsed = 120 + minute - 13 * 60
    bounded = min(240, max(0, elapsed))
    return Decimal(bounded) / Decimal(240)


def _price_limit_safe_factor(
    desired_factor: Decimal,
    bars: Iterable[FiveMinuteBar],
    world: ScenarioDataWorldInput,
    *,
    bullish: bool,
) -> Decimal:
    safe_factors: list[Decimal] = []
    for bar in bars:
        reference, lower_bound, upper_bound = _validated_bar_price_limit_bounds(
            world,
            bar,
        )
        if reference.limit_fraction is None:
            continue
        if lower_bound is None or upper_bound is None:  # pragma: no cover
            raise AssertionError("bounded price-limit reference requires bounds")
        safe_factors.append(
            (upper_bound if bullish else lower_bound)
            / (bar.high if bullish else bar.low)
        )
    if not safe_factors:
        return desired_factor
    if bullish:
        if min(safe_factors) < Decimal("1"):
            raise ValueError(
                "Admitted source data already exceeds its point-in-time upper price limit"
            )
        return max(Decimal("1"), min(desired_factor, *safe_factors))
    if max(safe_factors) > Decimal("1"):
        raise ValueError(
            "Admitted source data already exceeds its point-in-time lower price limit"
        )
    return min(Decimal("1"), max(desired_factor, *safe_factors))


def _price_limit_reference_at(
    references: Iterable[SessionPriceLimitReference],
    instrument: str,
    at_time: datetime,
) -> SessionPriceLimitReference:
    candidates = tuple(
        reference
        for reference in references
        if reference.instrument == instrument
        and reference.session_date == at_time.date()
        and reference.effective_at <= at_time
    )
    if not candidates:
        raise ValueError(
            f"No point-in-time previous-close reference exists for {instrument!r} "
            f"on {at_time.date().isoformat()}"
        )
    return max(candidates, key=lambda reference: reference.effective_at)


def _validated_price_limit_reference_at(
    world: ScenarioDataWorldInput,
    instrument: str,
    at_time: datetime,
) -> SessionPriceLimitReference:
    state = _state_at(
        world.instrument_states,
        instrument,
        at_time,
    )
    reference = _price_limit_reference_at(
        world.price_limit_references,
        instrument,
        at_time,
    )
    if reference.is_st is not state.is_st:
        raise ValueError(
            "Point-in-time price-limit rule and Instrument State disagree "
            f"for {instrument!r}"
        )
    return reference


def _validated_bar_price_limit_bounds(
    world: ScenarioDataWorldInput,
    bar: FiveMinuteBar,
) -> tuple[
    SessionPriceLimitReference,
    Decimal | None,
    Decimal | None,
]:
    reference = _validated_price_limit_reference_at(
        world,
        bar.instrument,
        bar.end_time,
    )
    if reference.limit_fraction is None:
        return reference, None, None
    lower_bound = _daily_price_limit_bound(
        reference.previous_close,
        reference.limit_fraction,
        bullish=False,
    )
    upper_bound = _daily_price_limit_bound(
        reference.previous_close,
        reference.limit_fraction,
        bullish=True,
    )
    if bar.low < lower_bound or bar.high > upper_bound:
        raise ValueError(
            "Admitted source data already exceeds its point-in-time price limits"
        )
    return reference, lower_bound, upper_bound


def _daily_price_limit_bound(
    previous_close: Decimal,
    limit: Decimal,
    *,
    bullish: bool,
) -> Decimal:
    direction = Decimal("1") if bullish else Decimal("-1")
    return (previous_close * (Decimal("1") + direction * limit)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _state_at(
    states: Iterable[InstrumentState],
    instrument: str,
    at_time: datetime,
) -> InstrumentState:
    candidates = tuple(
        state
        for state in states
        if state.instrument == instrument
        and state.effective_at <= at_time
    )
    if not candidates:
        raise ValueError(
            f"No point-in-time Instrument State exists for {instrument!r}"
        )
    return max(candidates, key=lambda state: state.effective_at)


def create_initial_transformation_catalog() -> ScenarioTransformationCatalog:
    return ScenarioTransformationCatalog(
        catalog_version="scenario-transformation-catalog.v1",
        entries=(
            TransformationCatalogEntry(
                transformation_id="shock-recovery.v1",
                family="shock-recovery",
                implementation_version="shock-recovery.v1",
                parameters=(
                    TransformationParameterDefinition(
                        name="direction",
                        value_type="enum",
                        required=True,
                        choices=("bearish", "bullish"),
                    ),
                    TransformationParameterDefinition(
                        name="gap_fraction",
                        value_type="decimal",
                        required=True,
                        minimum=Decimal("0"),
                        maximum=Decimal("0.1"),
                    ),
                    TransformationParameterDefinition(
                        name="shock_fraction",
                        value_type="decimal",
                        required=True,
                        minimum=Decimal("0.01"),
                        maximum=Decimal("0.2"),
                    ),
                    TransformationParameterDefinition(
                        name="shock_duration_bars",
                        value_type="integer",
                        required=True,
                        minimum=Decimal("1"),
                        maximum=Decimal("12"),
                    ),
                    TransformationParameterDefinition(
                        name="persistence_duration_bars",
                        value_type="integer",
                        required=True,
                        minimum=Decimal("0"),
                        maximum=Decimal("24"),
                    ),
                    TransformationParameterDefinition(
                        name="recovery_duration_bars",
                        value_type="integer",
                        required=True,
                        minimum=Decimal("1"),
                        maximum=Decimal("24"),
                    ),
                ),
                compatibility_rules=(
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                    "ordered-gap-shock-persistence-recovery",
                ),
                causality_constraints=(
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ),
            ),
            TransformationCatalogEntry(
                transformation_id="volatility-scaling.v1",
                family="volatility",
                implementation_version="volatility-scaling.v1",
                parameters=(
                    TransformationParameterDefinition(
                        name="multiplier",
                        value_type="decimal",
                        required=True,
                        minimum=Decimal("0.5"),
                        maximum=Decimal("2"),
                    ),
                ),
                compatibility_rules=(
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                ),
                causality_constraints=(
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ),
            ),
            TransformationCatalogEntry(
                transformation_id="trend-regime.v1",
                family="trend-regime",
                implementation_version="trend-regime.v1",
                parameters=(
                    TransformationParameterDefinition(
                        name="direction",
                        value_type="enum",
                        required=True,
                        choices=("bearish", "bullish"),
                    ),
                    TransformationParameterDefinition(
                        name="strength",
                        value_type="decimal",
                        required=True,
                        minimum=Decimal("0"),
                        maximum=Decimal("1"),
                    ),
                ),
                compatibility_rules=(
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                ),
                causality_constraints=(
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ),
            ),
        ),
    )


__all__ = [
    "AppliedTransformation",
    "ScenarioTransformationCatalog",
    "TransformationCatalogEntry",
    "TransformationCatalogIssue",
    "TransformationParameterDefinition",
    "TransformationPhaseMarker",
    "apply_registered_transformations",
    "create_initial_transformation_catalog",
]
