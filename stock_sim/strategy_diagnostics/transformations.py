"""Versioned Scenario Transformation Catalog contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import TYPE_CHECKING, Iterable, Literal, Mapping, Protocol

if TYPE_CHECKING:
    from .market_paths import (
        FiveMinuteBar,
        InstrumentState,
        ScenarioDataWorldInput,
        SessionPriceLimitReference,
    )


ParameterValueType = Literal["decimal", "enum"]


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
class AppliedTransformation:
    transformation_id: str
    family: str
    catalog_version: str
    implementation_version: str
    parameters: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "transformation_id": self.transformation_id,
            "family": self.family,
            "catalog_version": self.catalog_version,
            "implementation_version": self.implementation_version,
            "parameters": dict(self.parameters),
        }


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
            except (InvalidOperation, ValueError):
                issues.append(
                    TransformationCatalogIssue(
                        path=path,
                        rule="transformation.parameter-type",
                        message=f"Parameter {name!r} must be a decimal value.",
                        correction="Provide a decimal string or number.",
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
        if entry.transformation_id == "trend-regime.v1":
            transformed = _apply_trend_regime(transformed, request.parameters)
        else:  # pragma: no cover - catalog registration and implementation stay atomic
            raise ValueError(
                f"No implementation exists for {entry.transformation_id!r}"
            )
        applied.append(
            AppliedTransformation(
                transformation_id=entry.transformation_id,
                family=entry.family,
                catalog_version=catalog.catalog_version,
                implementation_version=entry.implementation_version,
                parameters=_canonical_parameters(entry, request.parameters),
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
        else:
            canonical.append((name, str(value)))
    return tuple(canonical)


def _apply_trend_regime(
    world: ScenarioDataWorldInput,
    parameters: Mapping[str, object],
) -> ScenarioDataWorldInput:
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
        transformed_bars.extend(
            replace(
                bar,
                open=bar.open * factor,
                high=bar.high * factor,
                low=bar.low * factor,
                close=bar.close * factor,
                amount=bar.amount * factor,
            )
            for bar in bars
        )
    return replace(
        world,
        bars=tuple(
            sorted(
                transformed_bars,
                key=lambda item: (item.end_time, item.instrument),
            )
        ),
    )


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
    states = tuple(world.instrument_states)
    safe_factors: list[Decimal] = []
    for bar in bars:
        state = _state_at(states, bar.instrument, bar.end_time)
        reference = _price_limit_reference_at(
            world.price_limit_references,
            bar.instrument,
            bar.end_time,
        )
        if reference.is_st is not state.is_st:
            raise ValueError(
                "Point-in-time price-limit rule and Instrument State disagree "
                f"for {bar.instrument!r}"
            )
        if reference.limit_fraction is None:
            continue
        safe_factors.append(
            _daily_price_limit_bound(
                reference.previous_close,
                reference.limit_fraction,
                bullish=bullish,
            )
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
    "apply_registered_transformations",
    "create_initial_transformation_catalog",
]
