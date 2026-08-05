"""Internal Qt Adapter and host for the centralized QML Journey Workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import count
from math import ceil
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from typing import Protocol, cast
from uuid import uuid4

from PySide6.QtCore import (
    Property,
    QObject,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget

from app.features import (
    ApproveDiagnosticTaskConfiguration,
    ApprovedScenarioRecipeId,
    ApprovedScenarioRecipeVersionId,
    CampaignNodeTarget,
    CancelDiagnosticTarget,
    CancelDiagnosticTask,
    CandidateEvidence,
    CreateDiagnosticTask,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCampaignNodeHandoff,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticSetupSelectionContext,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    DiagnosticTaskId,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandResult,
    DiagnosticTasksContext,
    DiagnosticTasksFeature,
    DiagnosticTasksViewState,
    DiagnosticTaskTarget,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsSelection,
    EvidenceAndFindingsSubscription,
    EvidenceAndFindingsViewState,
    EvidenceCoverage,
    EvidenceDimension,
    FormalDiagnosticCampaignTarget,
    MarketScenarioId,
    PauseDiagnosticTarget,
    PauseDiagnosticTask,
    ResumeDiagnosticTarget,
    ResumeDiagnosticTask,
    RetryFailedCampaignNode,
    ReviseDiagnosticTaskConfiguration,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringSelection,
    RunMonitoringViewState,
    ScenarioLabContext,
    ScenarioLabFeature,
    ScenarioLabFocusTarget,
    ScenarioLabViewState,
    ScenarioDiagnosticSelection,
    StartFormalDiagnosticCampaign,
    StrategyLibraryContext,
    StrategyLibraryFeature,
    StrategyLibraryFocusTarget,
    StrategySelectionBookmark,
    StrategyUnderTestId,
    Subscription,
    ValidateDiagnosticTaskConfiguration,
    compose_diagnostic_setup_selection_context,
)
from app.features.strategy_library import (
    CompareStrategies,
    SelectFormalStrategySet,
    StrategyComparisonDisposition,
    StrategyLibraryAvailabilityFilter,
    StrategyLibraryViewState,
    StrategySelectionContext,
    StrategySelectionDisposition,
)
from app.features.strategy_library_application import StrategyLibraryEntry
from app.features.scenario_lab_application import (
    ApprovedScenarioRecipeVersionProjection,
    ApproveScenarioRecipeCommand,
    ComposeFormalScenarioSetCommand,
    CreateAiAssistedScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftCommand,
    HistoricalSegmentEntry,
    MaterializeApprovedScenarioRecipeCommand,
    MarketScenarioEntry,
    FormalScenarioSetProjection,
    ReferenceMarketPathEntry,
    RequestedExecutionAssumptionsProjection,
    ResolveScenarioExecutionAssumptionsCommand,
    ReviseScenarioRecipeDraftCommand,
    ScenarioLabActorId,
    ScenarioLabCommandContentIdentity,
    ScenarioLabCommandDisposition,
    ScenarioLabCommandId,
    ScenarioLabCommandMetadata,
    ScenarioLabIdempotencyIdentity,
    ScenarioLabTaskHandle,
    ScenarioLabUnavailabilityReason,
    ScenarioExecutionAssumptionTarget,
    ScenarioExecutionResolutionProjection,
    ScenarioSelectionContextProjection,
    ScenarioMaterializationAttemptId,
    ScenarioRecipeAuthoringMode,
    ScenarioRecipeDataPolicy,
    ScenarioRecipeDraftPayload,
    ScenarioRecipeDraftProjection,
    ScenarioRecipeParameterInput,
    ScenarioRecipeParameterKind,
    ScenarioRecipeTransformationInput,
    ScenarioRecipeValidationProjection,
    SelectFormalScenarioSetCommand,
    TransformationCatalogEntryProjection,
    TransformationParameterProjection,
    ValidateScenarioRecipeDraftCommand,
    RetryScenarioMaterializationCommand,
    canonical_scenario_lab_command_content_identity,
)
from app.features.diagnostic_setup import (
    ApproveDiagnosticTaskConfigurationFromSetup,
    CreateDiagnosticTaskFromSetup,
    DiagnosticSetupSelectionCoordinator,
    ReviseDiagnosticTaskConfigurationFromSetup,
    StartFormalDiagnosticCampaignFromSetup,
    ValidateDiagnosticTaskConfigurationFromSetup,
)
from app.features.run_monitoring import SourceGenerationId, TaskHandleId, TaskPhase
from app.journey_recovery import (
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
)


from .accessibility import (
    AccessibilityPreferences,
    AccessibilitySettingsQtAdapter,
    detect_accessibility_preferences,
)
from .evidence_chart import (
    EvidenceChartFrameGate,
    EvidenceChartFrameGateResult,
    EvidenceChartPresentation,
    EvidenceChartRenderFrame,
    EvidenceChartSamplingPolicy,
    EvidenceChartViewport,
    advance_evidence_chart_presentation_revision,
    build_evidence_chart_presentation,
)

_QML_ROOT = Path(__file__).resolve().parent / "qml"
_MOUNT_GENERATIONS = count(1)
_MOUNT_GENERATION_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class ViewMountGenerationId:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 1:
            raise ValueError("View mount generation must be positive")


def _next_mount_generation() -> ViewMountGenerationId:
    with _MOUNT_GENERATION_LOCK:
        return ViewMountGenerationId(next(_MOUNT_GENERATIONS))


class StrategyLibraryQtAdapter(QObject):
    """Qt-only projection of the typed Strategy Library Feature Interface."""

    stateChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: StrategyLibraryFeature,
        *,
        context: StrategyLibraryContext | None = None,
        bookmark_sink: Callable[[StrategySelectionBookmark], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or StrategyLibraryContext()
        self._state = feature.snapshot(self._context)
        self._comparison_entries: tuple[StrategyLibraryEntry, ...] = ()
        self._comparison_source: tuple[str, int] | None = None
        self._bookmark_sink = bookmark_sink
        self._command_message = (
            "Compare the backend-declared formal set before selecting it."
        )
        self._mount_generation = _next_mount_generation()
        self._route_active = True
        self._closed = False
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: StrategyLibraryViewState) -> None:
        if not self._closed and self._route_active:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: StrategyLibraryViewState,
    ) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        incoming_source = (
            "" if state.source_revision is None else state.source_revision.value,
            state.source.generation.value,
        )
        if (
            self._comparison_source is not None
            and (
                self._comparison_source != incoming_source
                or state.freshness.value != "fresh"
            )
        ):
            self._comparison_entries = ()
            self._comparison_source = None
        self._state = state
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return self._state.presentation.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return self._state.freshness.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceRevision(self) -> str:  # noqa: N802
        return (
            "Unavailable"
            if self._state.source_revision is None
            else self._state.source_revision.value
        )

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def sourceGeneration(self) -> int:  # noqa: N802
        return self._state.source.generation.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def focusRestorationId(self) -> str:  # noqa: N802
        focus = self._state.focus_restoration_id
        return "" if focus is None else focus.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def focusRestorationTarget(self) -> str:  # noqa: N802
        bookmark = self._context.selection_bookmark
        return (
            StrategyLibraryFocusTarget.SEARCH.value
            if bookmark is None
            else bookmark.focus_target.value
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def searchText(self) -> str:  # noqa: N802
        return self._context.search_text

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def availabilityFilter(self) -> str:  # noqa: N802
        return self._context.availability_filter.value

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def entryCount(self) -> int:  # noqa: N802
        return len(self._state.entries)

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def entries(self) -> list[dict[str, object]]:
        return [
            _strategy_library_entry_payload(item) for item in self._state.entries
        ]

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def comparisonCount(self) -> int:  # noqa: N802
        return len(self._comparison_entries)

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def comparisonEntries(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _strategy_library_entry_payload(item)
            for item in self._comparison_entries
        ]

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCompare(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_compare

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canSelectFormalSet(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_select_formal_strategy_set

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def selectionStatus(self) -> str:  # noqa: N802
        return self._state.selection_status.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def selectionMessage(self) -> str:  # noqa: N802
        return self._state.selection_message

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def selectionContextId(self) -> str:  # noqa: N802
        selection = self._state.selection
        return "" if selection is None else selection.context_identity

    def current_formal_strategy_ids(self) -> tuple[StrategyUnderTestId, ...]:
        selection = self.current_formal_strategy_selection()
        if selection is None:
            return ()
        return tuple(item.strategy_id for item in selection.selections)

    def current_formal_strategy_selection(self) -> StrategySelectionContext | None:
        selection = self._state.selection
        if (
            self._state.selection_status.value != "current"
            or selection is None
            or self._state.freshness.value != "fresh"
            or self._state.presentation.value not in {"ready", "partial"}
            or self._state.source_revision is None
            or self._state.error is not None
        ):
            return None
        return selection

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def commandMessage(self) -> str:  # noqa: N802
        return self._command_message

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusMessage(self) -> str:  # noqa: N802
        if self._state.error is not None:
            return self._state.error.message
        messages = {
            "loading": "Reading the authoritative Strategy inventory.",
            "empty": "No formal Strategies Under Test are available.",
            "ready": "Authoritative formal Strategy inventory is ready.",
            "partial": (
                "Some formal Strategies remain visible with blocking reasons."
            ),
            "stale": "Retaining the last reliable Strategy inventory.",
            "disconnected": (
                "Disconnected; retained Strategy data may be stale."
            ),
            "failed": "The authoritative Strategy inventory could not be read.",
        }
        return messages[self._state.presentation.value]

    @Slot()
    def refresh(self) -> None:
        if self._closed:
            return
        state = self._feature.snapshot(self._context)
        self._accept_state(self._mount_generation.value, state)

    @Slot()
    def compareFormalSet(self) -> None:  # noqa: N802
        if self._closed or not self.canCompare:
            return
        entries = self._formal_entries()
        source_revision = self._state.source_revision
        if source_revision is None:
            return
        result = self._feature.compare_strategies(
            CompareStrategies(
                strategy_ids=tuple(item.strategy_id for item in entries),
                expected_source_revision=source_revision,
                expected_source_generation=self._state.source.generation,
            )
        )
        self._comparison_entries = (
            result.entries
            if result.disposition is StrategyComparisonDisposition.AVAILABLE
            else ()
        )
        self._comparison_source = (
            source_revision.value,
            self._state.source.generation.value,
        )
        self._command_message = result.message
        self.stateChanged.emit()

    @Slot()
    def selectFormalSet(self) -> None:  # noqa: N802
        if self._closed or not self.canSelectFormalSet:
            return
        entries = self._formal_entries()
        source_revision = self._state.source_revision
        if source_revision is None or any(
            item.guardrail_profile is None for item in entries
        ):
            return
        result = self._feature.select_formal_strategy_set(
            SelectFormalStrategySet(
                strategy_ids=tuple(item.strategy_id for item in entries),
                guardrail_profile_ids=tuple(
                    item.guardrail_profile.profile_id for item in entries
                    if item.guardrail_profile is not None
                ),
                expected_source_revision=source_revision,
                expected_source_generation=self._state.source.generation,
                originating_view_revision=self._state.revision,
            )
        )
        self._command_message = result.message
        if (
            result.disposition is StrategySelectionDisposition.SELECTED
            and result.selection is not None
        ):
            bookmark = StrategySelectionBookmark(
                selections=result.selection.selections,
                source_generation=result.selection.source_generation,
                focus_target=StrategyLibraryFocusTarget.SELECT_FORMAL_SET,
                focus_strategy_id=self._context.focus_strategy_id,
            )
            next_context = StrategyLibraryContext(
                search_text=self._context.search_text,
                availability_filter=self._context.availability_filter,
                required_capabilities=self._context.required_capabilities,
                focus_strategy_id=self._context.focus_strategy_id,
                selection_bookmark=bookmark,
            )
            if self._bookmark_sink is not None:
                self._bookmark_sink(bookmark)
            self._replace_context(next_context)
            return
        self.stateChanged.emit()

    def _formal_entries(self) -> tuple[StrategyLibraryEntry, ...]:
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return ()
        return tuple(
            item
            for item in inventory.entries
            if item.required_for_v1_formal_campaign
        )

    @Slot(str)
    def setSearchText(self, value: str) -> None:  # noqa: N802
        normalized = " ".join(value.split())
        if normalized == self._context.search_text:
            return
        self._replace_context(
            StrategyLibraryContext(
                search_text=normalized,
                availability_filter=self._context.availability_filter,
                required_capabilities=self._context.required_capabilities,
                focus_strategy_id=self._context.focus_strategy_id,
                selection_bookmark=self._context.selection_bookmark,
            )
        )

    @Slot(str)
    def setAvailabilityFilter(self, value: str) -> None:  # noqa: N802
        try:
            availability = StrategyLibraryAvailabilityFilter(value)
        except ValueError:
            return
        if availability is self._context.availability_filter:
            return
        self._replace_context(
            StrategyLibraryContext(
                search_text=self._context.search_text,
                availability_filter=availability,
                required_capabilities=self._context.required_capabilities,
                focus_strategy_id=self._context.focus_strategy_id,
                selection_bookmark=self._context.selection_bookmark,
            )
        )

    @Slot(str)
    def setFocusStrategy(self, value: str) -> None:  # noqa: N802
        if self._closed:
            return
        strategy_id = StrategyUnderTestId(value)
        inventory = self._state.last_reliable_inventory
        if inventory is None or all(
            item.strategy_id != strategy_id for item in inventory.entries
        ):
            return
        bookmark = self._context.selection_bookmark
        if self._state.selection is not None:
            bookmark = StrategySelectionBookmark(
                selections=self._state.selection.selections,
                source_generation=self._state.selection.source_generation,
                focus_target=StrategyLibraryFocusTarget.STRATEGY_DETAILS,
                focus_strategy_id=strategy_id,
            )
            if self._bookmark_sink is not None:
                self._bookmark_sink(bookmark)
        self._replace_context(
            StrategyLibraryContext(
                search_text=self._context.search_text,
                availability_filter=self._context.availability_filter,
                required_capabilities=self._context.required_capabilities,
                focus_strategy_id=strategy_id,
                selection_bookmark=bookmark,
            )
        )

    def _replace_context(self, context: StrategyLibraryContext) -> None:
        if self._closed:
            return
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        self._mount_generation = _next_mount_generation()
        self._context = context
        self._state = self._feature.snapshot(context)
        current_source = (
            ""
            if self._state.source_revision is None
            else self._state.source_revision.value,
            self._state.source.generation.value,
        )
        if (
            self._comparison_source is not None
            and (
                self._comparison_source != current_source
                or self._state.freshness.value != "fresh"
            )
        ):
            self._comparison_entries = ()
            self._comparison_source = None
        self._subscription = (
            self._feature.subscribe(context, self._queue_state)
            if self._route_active
            else None
        )
        self.stateChanged.emit()

    def set_route_active(self, active: bool) -> None:
        if self._closed or active is self._route_active:
            return
        self._route_active = active
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        if active:
            self._state = self._feature.snapshot(self._context)
            self._subscription = self._feature.subscribe(
                self._context,
                self._queue_state,
            )
            self.stateChanged.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._route_active = False
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()


def _strategy_library_entry_payload(entry: object) -> dict[str, object]:
    strategy = cast(StrategyLibraryEntry, entry)
    guardrail_profile = strategy.guardrail_profile
    return {
        "strategyId": strategy.strategy_id.value,
        "strategyVersion": strategy.strategy_version,
        "displayName": strategy.display.display_name,
        "summary": strategy.display.summary,
        "availability": strategy.availability.value,
        "availabilityLabel": strategy.availability.value.replace("_", " ").title(),
        "formalCampaignEligible": strategy.formal_campaign_eligible,
        "sourceModule": strategy.source.module,
        "sourcePath": strategy.source.source_relative_path,
        "sourceHash": strategy.source.content_sha256,
        "lineage": list(strategy.source.lineage),
        "surfaceVersion": strategy.compatibility.surface_version,
        "manifestHash": strategy.compatibility.content_hash,
        "capabilities": list(strategy.compatibility.declared_capabilities),
        "lifecycleCallbacks": list(
            strategy.compatibility.lifecycle_callbacks
        ),
        "scheduledCallbacks": list(
            strategy.compatibility.scheduled_callbacks
        ),
        "schedulingCalls": list(strategy.compatibility.scheduling_calls),
        "contextFields": list(strategy.compatibility.context_fields),
        "portfolioFields": list(strategy.compatibility.portfolio_fields),
        "marketDataCalls": list(strategy.compatibility.market_data_calls),
        "historyUnits": list(strategy.compatibility.history_units),
        "configurationCalls": list(
            strategy.compatibility.configuration_calls
        ),
        "tradingCalls": list(strategy.compatibility.trading_calls),
        "loggingCalls": list(strategy.compatibility.logging_calls),
        "candidateDataPolicy": strategy.candidate_data_policy,
        "guardrailProfileId": (
            "" if guardrail_profile is None else guardrail_profile.profile_id.value
        ),
        "guardrailProfileVersion": (
            ""
            if guardrail_profile is None
            else guardrail_profile.profile_version
        ),
        "guardrailThresholds": [
            {
                "metric": item.metric_name,
                "operator": item.operator,
                "value": item.value,
            }
            for item in (
                ()
                if guardrail_profile is None
                else guardrail_profile.thresholds
            )
        ],
        "dependencies": [
            {
                "kind": item.kind.value,
                "identity": item.identity,
                "version": item.version,
                "contentHash": item.content_hash,
                "available": item.available,
                "compatible": item.compatible,
            }
            for item in strategy.dependencies
        ],
        "reasons": [
            {
                "code": item.code.value,
                "summary": item.summary,
                "guidance": item.corrective_guidance,
            }
            for item in strategy.availability_reasons
        ],
    }


class ScenarioLabQtAdapter(QObject):
    """Qt-only projection of the typed Scenario Lab Feature Interface."""

    stateChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: ScenarioLabFeature,
        *,
        context: ScenarioLabContext | None = None,
        formal_strategy_selection_provider: (
            Callable[[], tuple[StrategyUnderTestId, ...]] | None
        ) = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or ScenarioLabContext()
        self._state = feature.snapshot(self._context)
        self._selected_draft_id: str | None = None
        self._selected_recipe_version_id: str | None = None
        self._formal_strategy_selection_provider = (
            formal_strategy_selection_provider or (lambda: ())
        )
        self._command_message = (
            "Create an exact manual Recipe Draft from an admitted segment. "
            "Optional AI assistance is unavailable unless a configured provider "
            "produces an audited typed Draft."
        )
        self._mount_generation = _next_mount_generation()
        self._route_active = True
        self._closed = False
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: ScenarioLabViewState) -> None:
        if not self._closed and self._route_active:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(self, mount_generation: int, state: ScenarioLabViewState) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        self._state = state
        if self._selected_draft_id is not None and not any(
            item.draft_id.value == self._selected_draft_id
            for item in state.recipe_drafts
        ):
            self._selected_draft_id = None
        if self._selected_recipe_version_id is not None and not any(
            item.recipe_version_id.value == self._selected_recipe_version_id
            for item in state.approved_recipe_versions
        ):
            self._selected_recipe_version_id = None
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return self._state.presentation.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return self._state.freshness.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceRevision(self) -> str:  # noqa: N802
        return (
            "Unavailable"
            if self._state.source_revision is None
            else self._state.source_revision.value
        )

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def sourceGeneration(self) -> int:  # noqa: N802
        return self._state.source.generation.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def searchText(self) -> str:  # noqa: N802
        return self._context.search_text

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableMarkets(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted({item.market for item in inventory.historical_segments})

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableLayers(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted({item.layer.value for item in inventory.market_scenarios})

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableSources(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted(
            {item.source_snapshot_id.value for item in inventory.historical_segments}
        )

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableRecipeVersions(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted(
            {item.recipe_version_id.value for item in inventory.market_scenarios}
        )

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableTransformationFamilies(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted(
            {item.family for item in inventory.transformation_catalog.entries}
        )

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableCompatibilities(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted(
            {
                *(item.compatibility.value for item in inventory.reference_paths),
                *(item.compatibility.value for item in inventory.market_scenarios),
            }
        )

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def availableReproducibilities(self) -> list[str]:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return []
        return sorted(
            {
                *(item.reproducibility.value for item in inventory.reference_paths),
                *(item.reproducibility.value for item in inventory.market_scenarios),
            }
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def marketFilter(self) -> str:  # noqa: N802
        return "" if not self._context.markets else self._context.markets[0]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def layerFilter(self) -> str:  # noqa: N802
        return "" if not self._context.layers else self._context.layers[0]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceFilter(self) -> str:  # noqa: N802
        return "" if not self._context.sources else self._context.sources[0]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def recipeVersionFilter(self) -> str:  # noqa: N802
        return (
            ""
            if not self._context.recipe_versions
            else self._context.recipe_versions[0]
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def transformationFamilyFilter(self) -> str:  # noqa: N802
        return (
            ""
            if not self._context.transformation_families
            else self._context.transformation_families[0]
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def compatibilityFilter(self) -> str:  # noqa: N802
        return (
            ""
            if not self._context.compatibilities
            else self._context.compatibilities[0]
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reproducibilityFilter(self) -> str:  # noqa: N802
        return (
            ""
            if not self._context.reproducibilities
            else self._context.reproducibilities[0]
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reconstructionFilter(self) -> str:  # noqa: N802
        if self._context.reconstructed is None:
            return "all"
        return "reconstructed" if self._context.reconstructed else "recorded"

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def historicalSegmentCount(self) -> int:  # noqa: N802
        return len(self._state.historical_segments)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def referencePathCount(self) -> int:  # noqa: N802
        return len(self._state.reference_paths)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarioCount(self) -> int:  # noqa: N802
        return len(self._state.market_scenarios)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def recipeDraftCount(self) -> int:  # noqa: N802
        return len(self._state.recipe_drafts)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def recipeValidationCount(self) -> int:  # noqa: N802
        return len(self._state.recipe_validations)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def approvedRecipeVersionCount(self) -> int:  # noqa: N802
        return len(self._state.approved_recipe_versions)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def taskHandleCount(self) -> int:  # noqa: N802
        return len(self._state.task_handles)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def scenarioSetCount(self) -> int:  # noqa: N802
        return len(self._state.scenario_sets)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def executionResolutionCount(self) -> int:  # noqa: N802
        return len(self._state.execution_resolutions)

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def selectionContextCount(self) -> int:  # noqa: N802
        return len(self._state.selection_contexts)

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def scenarioSets(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _formal_scenario_set_payload(item)
            for item in self._state.scenario_sets
        ]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def executionResolutions(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _scenario_execution_resolution_payload(item)
            for item in self._state.execution_resolutions
        ]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def selectionContexts(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _scenario_selection_context_payload(item)
            for item in self._state.selection_contexts
        ]

    def current_diagnostic_selection(self) -> ScenarioDiagnosticSelection | None:
        if (
            self._state.freshness.value != "fresh"
            or self._state.presentation.value not in {"ready", "partial"}
            or self._state.error is not None
        ):
            return None
        contexts = tuple(
            item
            for item in self._state.selection_contexts
            if item.status.value == "current" and item.formal_handoff_eligible
        )
        if not contexts:
            return None
        context = max(contexts, key=lambda item: item.selection_revision)
        scenario_set = next(
            (
                item
                for item in self._state.scenario_sets
                if item.scenario_set_id == context.scenario_set_id
                and item.projection_revision
                == context.scenario_set_projection_revision
            ),
            None,
        )
        resolution = next(
            (
                item
                for item in self._state.execution_resolutions
                if item.resolution_id == context.execution_resolution_id
                and item.projection_revision
                == context.execution_resolution_projection_revision
            ),
            None,
        )
        scenarios_by_id = {
            item.scenario_id: item for item in self._state.market_scenarios
        }
        scenarios = tuple(
            scenarios_by_id[identity]
            for identity in context.case_ids
            if identity in scenarios_by_id
        )
        if (
            scenario_set is None
            or resolution is None
            or len(scenarios) != len(context.case_ids)
        ):
            return None
        return ScenarioDiagnosticSelection(
            context=context,
            scenario_set=scenario_set,
            market_scenarios=scenarios,
            execution_resolution=resolution,
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canComposeScenarioSet(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_compose_scenario_set

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResolveExecutionAssumptions(self) -> bool:  # noqa: N802
        return (
            self._state.capabilities.can_resolve_execution_assumptions
            and len(self._formal_strategy_selection_provider()) == 2
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canSelectFormalScenarioSet(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_select_formal_scenario_set

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def scenarioCommandMessage(self) -> str:  # noqa: N802
        return self._command_message

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCreateRecipeDraft(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_create_recipe_draft

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCreateAiAssistedRecipeDraft(self) -> bool:  # noqa: N802
        return (
            self._state.capabilities.can_create_ai_assisted_recipe_draft
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def aiAuthoringStatus(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None:
            return "AI Recipe authoring capability is awaiting authoritative state."
        capabilities = inventory.authoring_capabilities
        if not capabilities.ai_authoring_available:
            return "Audited AI Recipe authoring is unavailable: no provider is configured."
        return (
            "Audited AI Recipe authoring is configured through "
            f"{capabilities.ai_provider} / {capabilities.ai_model}. "
            "Its typed Draft remains untrusted until exact validation and approval."
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canReviseRecipeDraft(self) -> bool:  # noqa: N802
        return (
            self._state.capabilities.can_revise_recipe_draft
            and self._selected_draft() is not None
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canValidateRecipeDraft(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_validate_recipe_draft

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canApproveRecipe(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_approve_recipe

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canMaterializeApprovedRecipe(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_materialize_reference_path

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canRetryMaterialization(self) -> bool:  # noqa: N802
        return self._state.capabilities.can_retry_materialization

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def historicalSegments(self) -> list[dict[str, object]]:  # noqa: N802
        return [_historical_segment_payload(item) for item in self._state.historical_segments]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def referencePaths(self) -> list[dict[str, object]]:  # noqa: N802
        return [_reference_path_payload(item) for item in self._state.reference_paths]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarios(self) -> list[dict[str, object]]:  # noqa: N802
        return [_market_scenario_payload(item) for item in self._state.market_scenarios]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def recipeDrafts(self) -> list[dict[str, object]]:  # noqa: N802
        return [_recipe_draft_payload(item) for item in self._state.recipe_drafts]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def recipeValidations(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _recipe_validation_payload(item)
            for item in self._state.recipe_validations
        ]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def approvedRecipeVersions(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _approved_recipe_version_payload(item)
            for item in self._state.approved_recipe_versions
        ]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def taskHandles(self) -> list[dict[str, object]]:  # noqa: N802
        return [
            _scenario_lab_task_handle_payload(item)
            for item in self._state.task_handles
        ]

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def transformations(self) -> list[dict[str, object]]:
        catalog = self._state.transformation_catalog
        if catalog is None:
            return []
        return [_transformation_payload(item) for item in catalog.entries]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def catalogVersion(self) -> str:  # noqa: N802
        catalog = self._state.transformation_catalog
        return "Unavailable" if catalog is None else catalog.catalog_version

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def focusRestorationIdentity(self) -> str:  # noqa: N802
        return self._state.focus_restoration_identity or ""

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusMessage(self) -> str:  # noqa: N802
        if self._state.error is not None:
            return self._state.error.message
        return {
            "loading": "Reading admitted data, Reference Paths, and Market Scenarios.",
            "empty": "No admitted Scenario Lab inventory is available.",
            "ready": "Authoritative Scenario Lab inventory is ready.",
            "partial": "Some immutable Scenario Lab facts failed closed.",
            "stale": "Retaining the last reliable Scenario Lab inventory.",
            "disconnected": "Disconnected; retained Scenario Lab data may be stale.",
            "failed": "The authoritative Scenario Lab inventory could not be read.",
        }[self._state.presentation.value]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def recipeCapabilityMessage(self) -> str:  # noqa: N802
        return self._command_message

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def selectedRecipeDraftId(self) -> str:  # noqa: N802
        return self._selected_draft_id or ""

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def selectedRecipeVersionId(self) -> str:  # noqa: N802
        return self._selected_recipe_version_id or ""

    @Slot(
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        int,
        int,
        int,
        bool,
        str,
    )
    def createRecipeDraft(  # noqa: N802
        self,
        name: str,
        segment_id: str,
        transformation_id: str,
        commission_bps: str,
        slippage_bps: str,
        max_fill_fraction: str,
        transformation_parameter_hint: str,
        latency_nodes: int,
        decision_cadence_minutes: int,
        materialization_seed: int,
        allow_partial_fills: bool,
        market_rule_profile_version: str,
    ) -> None:
        try:
            payload = self._build_recipe_payload(
                name=name,
                segment_id=segment_id,
                transformation_id=transformation_id,
                transformation_parameter_hint=transformation_parameter_hint,
                commission_bps=commission_bps,
                slippage_bps=slippage_bps,
                max_fill_fraction=max_fill_fraction,
                latency_nodes=latency_nodes,
                decision_cadence_minutes=decision_cadence_minutes,
                materialization_seed=materialization_seed,
                allow_partial_fills=allow_partial_fills,
                market_rule_profile_version=market_rule_profile_version,
            )
            metadata = self._authoring_metadata("create-recipe-draft")
            command = CreateScenarioRecipeDraftCommand(
                metadata=metadata,
                payload=payload,
                author_id=ScenarioLabActorId("journey-workspace-operator"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.create_recipe_draft(command)
            if result.draft is not None:
                self._selected_draft_id = result.draft.draft_id.value
                self._selected_recipe_version_id = None
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Recipe Draft input rejected: {exc}"
            self.stateChanged.emit()

    @Slot(str)
    def createAiAssistedRecipeDraft(self, intent: str) -> None:  # noqa: N802
        if not self.canCreateAiAssistedRecipeDraft:
            self._command_message = (
                "AI Recipe authoring unavailable: no audited provider is configured."
            )
            self.stateChanged.emit()
            return
        try:
            metadata = self._authoring_metadata("create-ai-recipe-draft")
            command = CreateAiAssistedScenarioRecipeDraftCommand(
                metadata=metadata,
                intent=intent,
                author_id=ScenarioLabActorId("journey-workspace-operator"),
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.author_recipe_with_ai(command)
            if result.draft is not None:
                self._selected_draft_id = result.draft.draft_id.value
                self._selected_recipe_version_id = None
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"AI Recipe intent rejected: {exc}"
            self.stateChanged.emit()

    @Slot(
        str,
        str,
        str,
        str,
        str,
        str,
        int,
        int,
        int,
        bool,
        str,
    )
    def reviseSelectedRecipeDraft(  # noqa: N802
        self,
        name: str,
        transformation_id: str,
        commission_bps: str,
        slippage_bps: str,
        max_fill_fraction: str,
        transformation_parameter_hint: str,
        latency_nodes: int,
        decision_cadence_minutes: int,
        materialization_seed: int,
        allow_partial_fills: bool,
        market_rule_profile_version: str,
    ) -> None:
        predecessor = self._selected_draft()
        if predecessor is None:
            self._command_message = "Select an authoritative Recipe Draft revision first."
            self.stateChanged.emit()
            return
        try:
            payload = self._build_recipe_payload(
                name=name,
                segment_id=predecessor.payload.historical_segment_id.value,
                transformation_id=transformation_id,
                transformation_parameter_hint=transformation_parameter_hint,
                commission_bps=commission_bps,
                slippage_bps=slippage_bps,
                max_fill_fraction=max_fill_fraction,
                latency_nodes=latency_nodes,
                decision_cadence_minutes=decision_cadence_minutes,
                materialization_seed=materialization_seed,
                allow_partial_fills=allow_partial_fills,
                market_rule_profile_version=market_rule_profile_version,
            )
            metadata = self._authoring_metadata("revise-recipe-draft")
            command = ReviseScenarioRecipeDraftCommand(
                metadata=metadata,
                predecessor_draft_id=predecessor.draft_id,
                expected_draft_revision=predecessor.revision,
                payload=payload,
                author_id=ScenarioLabActorId("journey-workspace-operator"),
                based_on_recipe_version_id=(
                    predecessor.based_on_recipe_version_id
                    if self._selected_recipe_version_id is None
                    else ApprovedScenarioRecipeVersionId(
                        self._selected_recipe_version_id
                    )
                ),
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.revise_recipe_draft(command)
            if result.draft is not None:
                self._selected_draft_id = result.draft.draft_id.value
                self._selected_recipe_version_id = None
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Recipe Draft revision rejected: {exc}"
            self.stateChanged.emit()

    @Slot(str)
    def selectRecipeDraft(self, draft_id: str) -> None:  # noqa: N802
        if not any(item.draft_id.value == draft_id for item in self._state.recipe_drafts):
            return
        self._selected_draft_id = draft_id
        self._selected_recipe_version_id = None
        self.stateChanged.emit()

    @Slot(str)
    def selectApprovedRecipeVersion(self, version_id: str) -> None:  # noqa: N802
        version = next(
            (
                item
                for item in self._state.approved_recipe_versions
                if item.recipe_version_id.value == version_id
            ),
            None,
        )
        if version is None:
            return
        self._selected_recipe_version_id = version_id
        self._selected_draft_id = version.approval.draft_id.value
        self.stateChanged.emit()

    @Slot(str)
    def validateRecipeDraft(self, draft_id: str) -> None:  # noqa: N802
        draft = next(
            (
                item
                for item in self._state.recipe_drafts
                if item.draft_id.value == draft_id
            ),
            None,
        )
        if draft is None:
            self._command_message = "The selected Recipe Draft is unavailable."
            self.stateChanged.emit()
            return
        metadata = self._authoring_metadata("validate-recipe-draft")
        command = ValidateScenarioRecipeDraftCommand(
            metadata=metadata,
            draft_id=draft.draft_id,
            expected_draft_revision=draft.revision,
            expected_payload_hash=draft.payload_hash,
        )
        command = replace(
            command,
            metadata=replace(
                metadata,
                canonical_content_identity=(
                    canonical_scenario_lab_command_content_identity(command)
                ),
            ),
        )
        result = self._feature.validate_recipe_draft(command)
        self._finish_recipe_command(
            result.receipt.disposition,
            result.receipt.message,
        )

    @Slot(str)
    def approveRecipeValidation(self, validation_id: str) -> None:  # noqa: N802
        validation = next(
            (
                item
                for item in self._state.recipe_validations
                if item.validation_id.value == validation_id
            ),
            None,
        )
        if validation is None or not validation.is_valid:
            self._command_message = (
                "Approval requires one exact successful Recipe validation."
            )
            self.stateChanged.emit()
            return
        draft = next(
            (
                item
                for item in self._state.recipe_drafts
                if item.draft_id == validation.draft_id
                and item.revision == validation.draft_revision
                and item.payload_hash == validation.payload_hash
            ),
            None,
        )
        if draft is None:
            self._command_message = (
                "The exact validated Recipe Draft revision is unavailable."
            )
            self.stateChanged.emit()
            return
        metadata = self._authoring_metadata("approve-recipe")
        command = ApproveScenarioRecipeCommand(
            metadata=metadata,
            draft_id=draft.draft_id,
            expected_draft_revision=draft.revision,
            expected_payload_hash=draft.payload_hash,
            validation_id=validation.validation_id,
            actor_id=ScenarioLabActorId("journey-workspace-operator"),
        )
        command = replace(
            command,
            metadata=replace(
                metadata,
                canonical_content_identity=(
                    canonical_scenario_lab_command_content_identity(command)
                ),
            ),
        )
        result = self._feature.approve_recipe(command)
        if result.approved_version is not None:
            self._selected_recipe_version_id = (
                result.approved_version.recipe_version_id.value
            )
            self._selected_draft_id = (
                result.approved_version.approval.draft_id.value
            )
        self._finish_recipe_command(
            result.receipt.disposition,
            result.receipt.message,
        )

    @Slot(str)
    def materializeApprovedRecipeVersion(self, version_id: str) -> None:  # noqa: N802
        version = next(
            (
                item
                for item in self._state.approved_recipe_versions
                if item.recipe_version_id.value == version_id
            ),
            None,
        )
        if version is None or not version.can_materialize:
            self._command_message = (
                "Materialization requires one exact current compatible "
                "Approved Scenario Recipe Version."
            )
            self.stateChanged.emit()
            return
        try:
            metadata = self._authoring_metadata("materialize-reference-path")
            command = MaterializeApprovedScenarioRecipeCommand(
                metadata=metadata,
                recipe_version_id=version.recipe_version_id,
                expected_recipe_content_hash=version.content_hash,
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.materialize_reference_path(command)
            self._selected_recipe_version_id = version.recipe_version_id.value
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Materialization rejected: {exc}"
            self.stateChanged.emit()

    @Slot(str, str)
    def retryMaterialization(  # noqa: N802
        self,
        attempt_id: str,
        task_handle_id: str,
    ) -> None:
        predecessor = next(
            (
                item
                for item in self._state.task_handles
                if item.attempt_identity.value == attempt_id
                and item.identity.value == task_handle_id
            ),
            None,
        )
        if (
            predecessor is None
            or predecessor.phase is not TaskPhase.FAILED
            or not predecessor.retryable
        ):
            self._command_message = (
                "Retry requires one exact retryable failed materialization attempt."
            )
            self.stateChanged.emit()
            return
        try:
            metadata = self._authoring_metadata("retry-materialization")
            command = RetryScenarioMaterializationCommand(
                metadata=metadata,
                predecessor_attempt_id=ScenarioMaterializationAttemptId(
                    attempt_id
                ),
                predecessor_task_handle_id=TaskHandleId(task_handle_id),
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.retry_materialization(command)
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Materialization retry rejected: {exc}"
            self.stateChanged.emit()

    @Slot()
    def composeVisibleScenarioSet(self) -> None:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not self.canComposeScenarioSet:
            return
        baseline = next(
            (
                item
                for item in inventory.market_scenarios
                if item.layer.value == "baseline"
            ),
            None,
        )
        if baseline is None:
            self._command_message = (
                "Composition requires one authoritative untransformed baseline."
            )
            self.stateChanged.emit()
            return
        try:
            metadata = self._authoring_metadata("compose-scenario-set")
            command = ComposeFormalScenarioSetCommand(
                metadata=metadata,
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(
                    item.scenario_id
                    for item in self._state.market_scenarios
                    if item.layer.value == "isolated_sensitivity"
                ),
                compound_case_ids=tuple(
                    item.scenario_id
                    for item in self._state.market_scenarios
                    if item.layer.value == "compound"
                ),
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.compose_scenario_set(command)
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Scenario Set composition rejected: {exc}"
            self.stateChanged.emit()

    @Slot()
    def resolveLatestScenarioSet(self) -> None:  # noqa: N802
        if not self.canResolveExecutionAssumptions:
            self._command_message = (
                "Resolve assumptions after selecting the exact formal Strategy set."
            )
            self.stateChanged.emit()
            return
        scenario_set = next(
            (
                item
                for item in reversed(self._state.scenario_sets)
                if item.formal_handoff_eligible
            ),
            None,
        )
        if scenario_set is None:
            self._command_message = (
                "Resolve assumptions requires a complete Formal Scenario Set."
            )
            self.stateChanged.emit()
            return
        baseline = next(
            (
                item
                for item in self._state.market_scenarios
                if item.scenario_id == scenario_set.baseline_case_id
            ),
            None,
        )
        path = next(
            (
                item
                for item in self._state.reference_paths
                if baseline is not None and item.path_id == baseline.path_id
            ),
            None,
        )
        if path is None:
            self._command_message = (
                "The baseline Reference Market Path is unavailable."
            )
            self.stateChanged.emit()
            return
        try:
            metadata = self._authoring_metadata(
                "resolve-execution-assumptions"
            )
            command = ResolveScenarioExecutionAssumptionsCommand(
                metadata=metadata,
                scenario_set_id=scenario_set.scenario_set_id,
                targets=tuple(
                    ScenarioExecutionAssumptionTarget(
                        strategy_id=strategy_id,
                        campaign_case_id=case_id,
                        decision_time=path.start_time,
                    )
                    for strategy_id in self._formal_strategy_selection_provider()
                    for case_id in scenario_set.case_ids
                ),
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.resolve_execution_assumptions(command)
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Execution resolution rejected: {exc}"
            self.stateChanged.emit()

    @Slot()
    def selectLatestFormalScenarioSet(self) -> None:  # noqa: N802
        if not self.canSelectFormalScenarioSet:
            return
        scenario_set = next(
            (
                item
                for item in reversed(self._state.scenario_sets)
                if item.formal_handoff_eligible
            ),
            None,
        )
        resolution = next(
            (
                item
                for item in reversed(self._state.execution_resolutions)
                if scenario_set is not None
                and item.scenario_set_id == scenario_set.scenario_set_id
                and item.formal_handoff_eligible
            ),
            None,
        )
        if scenario_set is None or resolution is None:
            return
        try:
            metadata = self._authoring_metadata("select-formal-scenario-set")
            command = SelectFormalScenarioSetCommand(
                metadata=metadata,
                scenario_set_id=scenario_set.scenario_set_id,
                case_ids=scenario_set.case_ids,
                originating_view_revision=self._state.revision,
                execution_resolution_id=resolution.resolution_id,
            )
            command = replace(
                command,
                metadata=replace(
                    metadata,
                    canonical_content_identity=(
                        canonical_scenario_lab_command_content_identity(command)
                    ),
                ),
            )
            result = self._feature.select_formal_scenario_set(command)
            self._finish_recipe_command(
                result.receipt.disposition,
                result.receipt.message,
            )
        except (TypeError, ValueError) as exc:
            self._command_message = f"Formal Scenario selection rejected: {exc}"
            self.stateChanged.emit()

    @Slot(str)
    def setSearchText(self, value: str) -> None:  # noqa: N802
        normalized = " ".join(value.split())
        if normalized == self._context.search_text:
            return
        self._replace_context(replace(self._context, search_text=normalized))

    @Slot(str)
    def setMarketFilter(self, value: str) -> None:  # noqa: N802
        markets = () if not value else (value,)
        if markets != self._context.markets:
            self._replace_context(replace(self._context, markets=markets))

    @Slot(str)
    def setLayerFilter(self, value: str) -> None:  # noqa: N802
        layers = () if not value else (value,)
        if layers != self._context.layers:
            self._replace_context(replace(self._context, layers=layers))

    @Slot(str)
    def setSourceFilter(self, value: str) -> None:  # noqa: N802
        sources = () if not value else (value,)
        if sources != self._context.sources:
            self._replace_context(replace(self._context, sources=sources))

    @Slot(str)
    def setRecipeVersionFilter(self, value: str) -> None:  # noqa: N802
        recipe_versions = () if not value else (value,)
        if recipe_versions != self._context.recipe_versions:
            self._replace_context(
                replace(self._context, recipe_versions=recipe_versions)
            )

    @Slot(str)
    def setTransformationFamilyFilter(self, value: str) -> None:  # noqa: N802
        transformation_families = () if not value else (value,)
        if transformation_families != self._context.transformation_families:
            self._replace_context(
                replace(
                    self._context,
                    transformation_families=transformation_families,
                )
            )

    @Slot(str)
    def setCompatibilityFilter(self, value: str) -> None:  # noqa: N802
        compatibilities = () if not value else (value,)
        if compatibilities != self._context.compatibilities:
            self._replace_context(
                replace(self._context, compatibilities=compatibilities)
            )

    @Slot(str)
    def setReproducibilityFilter(self, value: str) -> None:  # noqa: N802
        reproducibilities = () if not value else (value,)
        if reproducibilities != self._context.reproducibilities:
            self._replace_context(
                replace(self._context, reproducibilities=reproducibilities)
            )

    @Slot(str)
    def setReconstructionFilter(self, value: str) -> None:  # noqa: N802
        reconstructed = {
            "all": None,
            "reconstructed": True,
            "recorded": False,
        }.get(value)
        if value not in {"all", "reconstructed", "recorded"}:
            return
        if reconstructed is not self._context.reconstructed:
            self._replace_context(
                replace(self._context, reconstructed=reconstructed)
            )

    @Slot(str)
    def setFocusIdentity(self, value: str) -> None:  # noqa: N802
        if not value:
            return
        target = ScenarioLabFocusTarget.HISTORICAL_SEGMENT
        if any(item.path_id.value == value for item in self._state.reference_paths):
            target = ScenarioLabFocusTarget.REFERENCE_PATH
        elif any(item.scenario_id.value == value for item in self._state.market_scenarios):
            target = ScenarioLabFocusTarget.MARKET_SCENARIO
        self._replace_context(
            replace(self._context, focus_target=target, focus_identity=value)
        )

    def _selected_draft(self) -> ScenarioRecipeDraftProjection | None:
        return next(
            (
                item
                for item in self._state.recipe_drafts
                if item.draft_id.value == self._selected_draft_id
            ),
            None,
        )

    def _authoring_metadata(self, operation: str) -> ScenarioLabCommandMetadata:
        if self._state.source_revision is None:
            raise ValueError("Scenario Lab source revision is unavailable")
        identity = uuid4().hex
        return ScenarioLabCommandMetadata(
            command_id=ScenarioLabCommandId(f"{operation}-{identity}"),
            idempotency_identity=ScenarioLabIdempotencyIdentity(
                f"{operation}-idempotency-{identity}"
            ),
            canonical_content_identity=ScenarioLabCommandContentIdentity(
                "pending-canonical-content"
            ),
            expected_source_revision=self._state.source_revision,
            expected_source_generation=SourceGenerationId(
                self._state.source.generation.value
            ),
        )

    def _build_recipe_payload(
        self,
        *,
        name: str,
        segment_id: str,
        transformation_id: str,
        transformation_parameter_hint: str,
        commission_bps: str,
        slippage_bps: str,
        max_fill_fraction: str,
        latency_nodes: int,
        decision_cadence_minutes: int,
        materialization_seed: int,
        allow_partial_fills: bool,
        market_rule_profile_version: str,
    ) -> ScenarioRecipeDraftPayload:
        segment = next(
            (
                item
                for item in self._state.historical_segments
                if item.segment_id.value == segment_id
            ),
            None,
        )
        if segment is None:
            raise ValueError("Select an admitted Historical Market Segment")
        Decimal(commission_bps)
        Decimal(slippage_bps)
        Decimal(max_fill_fraction)
        transformations: tuple[ScenarioRecipeTransformationInput, ...] = ()
        if transformation_id:
            catalog = self._state.transformation_catalog
            definition = (
                None
                if catalog is None
                else next(
                    (
                        item
                        for item in catalog.entries
                        if item.transformation_id == transformation_id
                    ),
                    None,
                )
            )
            if definition is None:
                raise ValueError("Select a registered transformation identity")
            parameters = tuple(
                self._recipe_parameter_input(
                    parameter,
                    transformation_parameter_hint if index == 0 else "",
                )
                for index, parameter in enumerate(definition.parameters)
            )
            transformations = (
                ScenarioRecipeTransformationInput(
                    transformation_id=definition.transformation_id,
                    parameters=parameters,
                ),
            )
        return ScenarioRecipeDraftPayload(
            name=name,
            historical_segment_id=segment.segment_id,
            transformations=transformations,
            requested_execution_assumptions=(
                RequestedExecutionAssumptionsProjection(
                    commission_bps=commission_bps,
                    slippage_bps=slippage_bps,
                    max_fill_fraction=max_fill_fraction,
                    latency_nodes=latency_nodes,
                    allow_partial_fills=allow_partial_fills,
                )
            ),
            decision_cadence_minutes=decision_cadence_minutes,
            materialization_seed=materialization_seed,
            data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
            market_rule_profile_version=market_rule_profile_version,
        )

    @staticmethod
    def _recipe_parameter_input(
        definition: object,
        hint: str,
    ) -> ScenarioRecipeParameterInput:
        parameter = cast(TransformationParameterProjection, definition)
        raw = hint.strip()
        if not raw:
            raw = (
                parameter.choices[0]
                if parameter.choices
                else parameter.minimum
                if parameter.minimum is not None
                else "1"
            )
        if parameter.value_type == "decimal":
            kind = ScenarioRecipeParameterKind.DECIMAL
            value: bool | int | Decimal | str = Decimal(raw)
        elif parameter.value_type == "integer":
            kind = ScenarioRecipeParameterKind.INTEGER
            value = int(raw)
        elif parameter.value_type == "boolean":
            kind = ScenarioRecipeParameterKind.BOOLEAN
            normalized = raw.casefold()
            if normalized not in {"true", "false"}:
                raise ValueError(f"{parameter.name} must be true or false")
            value = normalized == "true"
        else:
            kind = ScenarioRecipeParameterKind.CHOICE
            value = raw
        return ScenarioRecipeParameterInput(
            name=parameter.name,
            kind=kind,
            value=value,
        )

    def _finish_recipe_command(
        self,
        disposition: ScenarioLabCommandDisposition,
        message: str,
    ) -> None:
        self._command_message = f"{disposition.value}: {message}"
        state = self._feature.snapshot(self._context)
        if state.revision > self._state.revision:
            self._state = state
        self.stateChanged.emit()

    @Slot()
    def refresh(self) -> None:
        if self._closed:
            return
        state = self._feature.snapshot(self._context)
        self._accept_state(self._mount_generation.value, state)

    def _replace_context(self, context: ScenarioLabContext) -> None:
        if self._closed:
            return
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        self._mount_generation = _next_mount_generation()
        self._context = context
        self._state = self._feature.snapshot(context)
        self._subscription = (
            self._feature.subscribe(context, self._queue_state)
            if self._route_active
            else None
        )
        self.stateChanged.emit()

    def recovery_context(self) -> ScenarioLabContext:
        """Return immutable presentation focus for the workspace bookmark."""

        return self._context

    def set_route_active(self, active: bool) -> None:
        if self._closed or active is self._route_active:
            return
        self._route_active = active
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        if active:
            self._state = self._feature.snapshot(self._context)
            self._subscription = self._feature.subscribe(
                self._context,
                self._queue_state,
            )
            self.stateChanged.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._route_active = False
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()


def _scenario_lab_reason_payload(
    item: ScenarioLabUnavailabilityReason,
) -> dict[str, object]:
    return {
        "code": item.code.value,
        "summary": item.summary,
        "correctiveGuidance": item.corrective_guidance,
    }


def _historical_segment_payload(item: HistoricalSegmentEntry) -> dict[str, object]:
    return {
        "segmentId": item.segment_id.value,
        "contentHash": item.content_hash,
        "sourceSnapshotId": item.source_snapshot_id.value,
        "sourceSnapshotContentHash": item.source_snapshot_content_hash,
        "label": item.label,
        "market": item.market,
        "startDate": item.start_date.isoformat(),
        "endDate": item.end_date.isoformat(),
        "provider": item.provenance.provider,
        "dataset": item.provenance.dataset,
        "sourceVersion": item.provenance.version,
        "eligibleInstrumentCount": item.eligible_instrument_count,
        "tradingDayCount": item.trading_day_count,
        "barCount": item.bar_count,
        "admissionState": item.admission_state.value,
        "qualityState": item.quality_state.value,
        "recommendationTags": list(item.recommendation_tags),
        "unavailabilityReasons": [
            _scenario_lab_reason_payload(reason)
            for reason in item.unavailability_reasons
        ],
    }


def _reference_path_payload(item: ReferenceMarketPathEntry) -> dict[str, object]:
    preview = item.preview
    return {
        "pathId": item.path_id.value,
        "segmentId": item.segment_id.value,
        "segmentContentHash": item.segment_content_hash,
        "sourceSnapshotId": item.source_snapshot_id.value,
        "seed": item.seed,
        "expanderVersion": item.expander_version,
        "sourceResolution": item.source_resolution,
        "runtimeResolution": item.runtime_resolution,
        "reconstructed": item.reconstructed,
        "reconstructionNotice": item.reconstruction_notice,
        "numericTolerance": item.numeric_tolerance,
        "normalizationProvenance": item.normalization_provenance,
        "marketRuleProfileVersion": item.market_rule_profile_version,
        "transformationCatalogVersion": item.transformation_catalog_version,
        "startTime": item.start_time.isoformat(),
        "endTime": item.end_time.isoformat(),
        "integrity": item.integrity.value,
        "compatibility": item.compatibility.value,
        "reproducibility": item.reproducibility.value,
        "appliedTransformations": [
            {
                "transformationId": transformation.transformation_id,
                "family": transformation.family,
                "catalogVersion": transformation.catalog_version,
                "implementationVersion": (
                    transformation.implementation_version
                ),
                "parameters": [
                    {"name": name, "value": value}
                    for name, value in transformation.parameters
                ],
            }
            for transformation in item.transformations
        ],
        "previewNodeCount": 0 if preview is None else len(preview.nodes),
        "boundedNodeLimit": 0 if preview is None else preview.bounded_node_limit,
        "previewAtTime": "" if preview is None else preview.at_time.isoformat(),
        "eligibleUniverse": (
            [] if preview is None else list(preview.eligible_universe)
        ),
        "previewNodes": (
            []
            if preview is None
            else [
                {
                    "instrument": node.instrument,
                    "simulationTime": node.simulation_time.isoformat(),
                    "open": node.open,
                    "high": node.high,
                    "low": node.low,
                    "close": node.close,
                    "volume": node.volume,
                    "amount": node.amount,
                    "reconstructed": node.reconstructed,
                }
                for node in preview.nodes
            ]
        ),
        "unavailabilityReasons": [
            _scenario_lab_reason_payload(reason)
            for reason in item.unavailability_reasons
        ],
    }


def _market_scenario_payload(item: MarketScenarioEntry) -> dict[str, object]:
    return {
        "scenarioId": item.scenario_id.value,
        "layer": item.layer.value,
        "comparisonRole": item.comparison_role.value,
        "baselineScenarioId": (
            "" if item.baseline_scenario_id is None else item.baseline_scenario_id.value
        ),
        "recipeVersionId": item.recipe_version_id.value,
        "recipeContentHash": item.recipe_content_hash,
        "pathId": item.path_id.value,
        "segmentId": item.segment_id.value,
        "segmentContentHash": item.segment_content_hash,
        "sourceSnapshotId": item.source_snapshot_id.value,
        "seed": item.seed,
        "transformationCatalogVersion": item.transformation_catalog_version,
        "marketRuleProfileVersion": item.market_rule_profile_version,
        "decisionCadenceMinutes": item.decision_cadence_minutes,
        "transformations": [
            {
                "transformationId": transformation.transformation_id,
                "family": transformation.family,
                "implementationVersion": (
                    transformation.implementation_version
                ),
                "parameters": [
                    {"name": name, "value": value}
                    for name, value in transformation.parameters
                ],
            }
            for transformation in item.transformations
        ],
        "requestedExecutionAssumptions": {
            "commissionBps": (
                item.requested_execution_assumptions.commission_bps
            ),
            "slippageBps": item.requested_execution_assumptions.slippage_bps,
            "maxFillFraction": (
                item.requested_execution_assumptions.max_fill_fraction
            ),
            "latencyNodes": item.requested_execution_assumptions.latency_nodes,
            "allowPartialFills": (
                item.requested_execution_assumptions.allow_partial_fills
            ),
        },
        "compatibility": item.compatibility.value,
        "reproducibility": item.reproducibility.value,
        "executionResolution": item.execution_resolution.value,
        "unavailabilityReasons": [
            _scenario_lab_reason_payload(reason)
            for reason in item.unavailability_reasons
        ],
    }


def _formal_scenario_set_payload(
    item: FormalScenarioSetProjection,
) -> dict[str, object]:
    return {
        "scenarioSetId": item.scenario_set_id.value,
        "eligibility": item.eligibility.value,
        "baselineCaseId": item.baseline_case_id.value,
        "isolatedCaseIds": [value.value for value in item.isolated_case_ids],
        "compoundCaseIds": [value.value for value in item.compound_case_ids],
        "caseIds": [value.value for value in item.case_ids],
        "comparisonRelationships": [
            {
                "kind": value.kind,
                "subjectCaseId": value.subject_case_id.value,
                "controlCaseIds": [
                    identity.value for identity in value.control_case_ids
                ],
            }
            for value in item.comparison_relationships
        ],
        "missingRequirements": list(item.missing_requirements),
        "formalHandoffEligible": item.formal_handoff_eligible,
    }


def _scenario_execution_resolution_payload(
    item: ScenarioExecutionResolutionProjection,
) -> dict[str, object]:
    return {
        "resolutionId": item.resolution_id.value,
        "scenarioSetId": item.scenario_set_id.value,
        "formalHandoffEligible": item.formal_handoff_eligible,
        "targets": [
            {
                "strategyId": value.strategy_id.value,
                "strategyVersion": value.strategy_version,
                "compatibilityManifestHash": (
                    value.compatibility_manifest_hash
                ),
                "guardrailProfileId": value.guardrail_profile_id,
                "guardrailProfileVersion": value.guardrail_profile_version,
                "campaignCaseId": value.campaign_case_id.value,
                "state": value.state.value,
                "decisionTime": (
                    ""
                    if value.decision_time is None
                    else value.decision_time.isoformat()
                ),
                "afterDecisionTime": (
                    ""
                    if value.after_decision_time is None
                    else value.after_decision_time.isoformat()
                ),
                "activationTime": (
                    ""
                    if value.activation_time is None
                    else value.activation_time.isoformat()
                ),
                "decisionCadenceMinutes": value.decision_cadence_minutes,
                "decisionGrid": value.decision_grid,
                "activationPolicy": value.activation_policy,
                "executionPolicyVersion": value.execution_policy_version,
                "conditions": [
                    {
                        "name": condition.name,
                        "requestedValue": condition.requested_value,
                        "effectiveValue": condition.effective_value,
                        "overrideReason": condition.override_reason or "",
                    }
                    for condition in value.conditions
                ],
                "unavailabilityReasons": list(value.unavailability_reasons),
            }
            for value in item.targets
        ],
    }


def _scenario_selection_context_payload(
    item: ScenarioSelectionContextProjection,
) -> dict[str, object]:
    return {
        "selectionContextId": item.selection_context_id.value,
        "scenarioSetId": item.scenario_set_id.value,
        "scenarioSetProjectionRevision": (
            item.scenario_set_projection_revision
        ),
        "caseIds": [value.value for value in item.case_ids],
        "executionResolutionId": item.execution_resolution_id.value,
        "executionResolutionProjectionRevision": (
            item.execution_resolution_projection_revision
        ),
        "status": item.status.value,
        "selectionRevision": item.selection_revision,
        "originatingViewRevision": item.originating_view_revision,
        "sourceRevision": item.source_revision.value,
        "sourceGeneration": item.source_generation.value,
        "formalHandoffEligible": item.formal_handoff_eligible,
        "exactRecipeBindings": [
            value.recipe_version_id.value
            + " / "
            + value.recipe_content_hash
            for value in item.case_bindings
        ],
        "exactPathBindings": [
            value.reference_path_id.value
            + " / "
            + value.reference_path_content_hash
            for value in item.case_bindings
        ],
        "exactStrategyBindings": [
            value.strategy_id.value
            + "@"
            + value.strategy_version
            + " / manifest "
            + value.compatibility_manifest_hash
            + " / Guardrail "
            + value.guardrail_profile_id
            + "@"
            + value.guardrail_profile_version
            + " / execution "
            + value.execution_policy_version
            for value in item.strategy_bindings
        ],
        "caseBindings": [
            {
                "caseId": value.campaign_case_id.value,
                "segmentId": value.segment_id.value,
                "segmentContentHash": value.segment_content_hash,
                "sourceSnapshotId": value.source_snapshot_id.value,
                "seed": value.seed,
                "transformationCatalogVersion": (
                    value.transformation_catalog_version
                ),
                "marketRuleProfileVersion": (
                    value.market_rule_profile_version
                ),
                "transformations": [
                    transformation.transformation_id
                    + "@"
                    + transformation.implementation_version
                    for transformation in value.transformations
                ],
            }
            for value in item.case_bindings
        ],
    }


def _transformation_payload(item: TransformationCatalogEntryProjection) -> dict[str, object]:
    return {
        "transformationId": item.transformation_id,
        "label": item.transformation_id,
        "family": item.family,
        "implementationVersion": item.implementation_version,
        "parameters": [
            {
                "name": parameter.name,
                "valueType": parameter.value_type,
                "required": parameter.required,
                "minimum": parameter.minimum or "",
                "maximum": parameter.maximum or "",
                "choices": list(parameter.choices),
            }
            for parameter in item.parameters
        ],
        "compatibilityRules": list(item.compatibility_rules),
        "causalityConstraints": list(item.causality_constraints),
    }


def _recipe_draft_payload(item: ScenarioRecipeDraftProjection) -> dict[str, object]:
    requested = item.payload.requested_execution_assumptions
    return {
        "draftId": item.draft_id.value,
        "recipeId": item.recipe_id,
        "revision": item.revision,
        "name": item.payload.name,
        "historicalSegmentId": item.payload.historical_segment_id.value,
        "payloadHash": item.payload_hash,
        "authorId": item.author_id.value,
        "createdAt": item.created_at.isoformat(),
        "predecessorDraftId": (
            ""
            if item.predecessor_draft_id is None
            else item.predecessor_draft_id.value
        ),
        "basedOnRecipeVersionId": (
            ""
            if item.based_on_recipe_version_id is None
            else item.based_on_recipe_version_id.value
        ),
        "authoringMode": item.authoring_mode.value,
        "assistantAttemptId": item.assistant_attempt_id or "",
        "decisionCadenceMinutes": item.payload.decision_cadence_minutes,
        "materializationSeed": item.payload.materialization_seed,
        "dataPolicy": item.payload.data_policy.value,
        "marketRuleProfileVersion": item.payload.market_rule_profile_version,
        "transformations": [
            {
                "transformationId": transformation.transformation_id,
                "implementationVersion": "draft-selection",
                "parameters": [
                    {
                        "name": parameter.name,
                        "kind": parameter.kind.value,
                        "value": str(parameter.value),
                    }
                    for parameter in transformation.parameters
                ],
            }
            for transformation in item.payload.transformations
        ],
        "requestedExecutionAssumptions": {
            "commissionBps": requested.commission_bps,
            "slippageBps": requested.slippage_bps,
            "maxFillFraction": requested.max_fill_fraction,
            "latencyNodes": requested.latency_nodes,
            "allowPartialFills": requested.allow_partial_fills,
        },
    }


def _recipe_validation_payload(
    item: ScenarioRecipeValidationProjection,
) -> dict[str, object]:
    dependencies = item.dependencies
    return {
        "validationId": item.validation_id.value,
        "draftId": item.draft_id.value,
        "draftRevision": item.draft_revision,
        "payloadHash": item.payload_hash,
        "valid": item.is_valid,
        "recipeContentHash": item.recipe_content_hash or "",
        "validatedAt": item.validated_at.isoformat(),
        "findings": [
            {
                "path": ".".join(finding.path),
                "ruleCode": finding.rule_code,
                "severity": finding.severity.value,
                "explanation": finding.explanation,
                "correction": finding.correction,
                "retryable": finding.retryable,
                "differentInputRequired": finding.different_input_required,
            }
            for finding in item.findings
        ],
        "dependencies": {
            "historicalSegmentId": dependencies.historical_segment_id.value,
            "historicalSegmentContentHash": (
                dependencies.historical_segment_content_hash
            ),
            "sourceSnapshotId": dependencies.source_snapshot_id.value,
            "sourceSnapshotContentHash": (
                dependencies.source_snapshot_content_hash
            ),
            "recipeSchemaIdentity": dependencies.recipe_schema_identity,
            "recipeSchemaHash": dependencies.recipe_schema_hash,
            "transformationCatalogVersion": (
                dependencies.transformation_catalog_version
            ),
            "transformationCatalogHash": (
                dependencies.transformation_catalog_hash
            ),
            "transformationImplementations": list(
                dependencies.transformation_implementation_identities
            ),
            "dataPolicy": dependencies.data_policy.value,
            "causalityRules": list(dependencies.causality_rule_identities),
            "marketRuleProfileVersion": (
                dependencies.market_rule_profile_version
            ),
            "marketRuleProfileHash": dependencies.market_rule_profile_hash,
            "compatibilityObservations": [
                {
                    "subject": observation.subject,
                    "state": observation.state.value,
                    "explanation": observation.explanation,
                }
                for observation in dependencies.compatibility_observations
            ],
        },
    }


def _approved_recipe_version_payload(
    item: ApprovedScenarioRecipeVersionProjection,
) -> dict[str, object]:
    approval = item.approval
    dependencies = approval.dependencies
    return {
        "recipeVersionId": item.recipe_version_id.value,
        "recipeId": item.recipe_id,
        "versionNumber": item.version_number,
        "contentHash": item.content_hash,
        "name": item.payload.name,
        "authorId": item.author_id.value,
        "basedOnRecipeVersionId": (
            ""
            if item.based_on_recipe_version_id is None
            else item.based_on_recipe_version_id.value
        ),
        "authorityState": item.authority_state.value,
        "authorityReasons": [
            _scenario_lab_reason_payload(reason)
            for reason in item.authority_reasons
        ],
        "canMaterialize": item.can_materialize,
        "approvalId": approval.approval_id.value,
        "draftId": approval.draft_id.value,
        "draftRevision": approval.draft_revision or "",
        "payloadHash": approval.payload_hash,
        "validationId": (
            "" if approval.validation_id is None else approval.validation_id.value
        ),
        "dependencyBindingAvailable": dependencies is not None,
        "recipeContentHash": approval.recipe_content_hash,
        "actorId": approval.actor_id.value,
        "approvedAt": approval.approved_at.isoformat(),
        "historicalSegmentId": (
            ""
            if dependencies is None
            else dependencies.historical_segment_id.value
        ),
        "historicalSegmentContentHash": (
            ""
            if dependencies is None
            else dependencies.historical_segment_content_hash
        ),
        "sourceSnapshotId": (
            "" if dependencies is None else dependencies.source_snapshot_id.value
        ),
        "sourceSnapshotContentHash": (
            "" if dependencies is None else dependencies.source_snapshot_content_hash
        ),
        "recipeSchemaIdentity": (
            "" if dependencies is None else dependencies.recipe_schema_identity
        ),
        "recipeSchemaHash": (
            "" if dependencies is None else dependencies.recipe_schema_hash
        ),
        "transformationCatalogVersion": (
            "" if dependencies is None else dependencies.transformation_catalog_version
        ),
        "transformationCatalogHash": (
            "" if dependencies is None else dependencies.transformation_catalog_hash
        ),
        "transformationImplementations": list(
            ()
            if dependencies is None
            else dependencies.transformation_implementation_identities
        ),
        "dataPolicy": (
            "" if dependencies is None else dependencies.data_policy.value
        ),
        "causalityRules": list(
            () if dependencies is None else dependencies.causality_rule_identities
        ),
        "marketRuleProfileVersion": (
            "" if dependencies is None else dependencies.market_rule_profile_version
        ),
        "marketRuleProfileHash": (
            "" if dependencies is None else dependencies.market_rule_profile_hash
        ),
        "compatibilityObservations": [
            {
                "subject": observation.subject,
                "state": observation.state.value,
                "explanation": observation.explanation,
            }
            for observation in (
                ()
                if dependencies is None
                else dependencies.compatibility_observations
            )
        ],
        "materializationSeed": item.payload.materialization_seed,
        "transformations": [
            {
                "transformationId": transformation.transformation_id,
                "parameters": [
                    {
                        "name": parameter.name,
                        "kind": parameter.kind.value,
                        "value": str(parameter.value),
                    }
                    for parameter in transformation.parameters
                ],
            }
            for transformation in item.payload.transformations
        ],
    }


def _scenario_lab_task_handle_payload(
    item: ScenarioLabTaskHandle,
) -> dict[str, object]:
    return {
        "taskHandleId": item.identity.value,
        "attemptId": item.attempt_identity.value,
        "operation": item.operation.value,
        "targetKind": item.target_identity.kind.value,
        "targetIdentity": item.target_identity.value,
        "phase": item.phase.value,
        "progress": item.progress,
        "progressPercent": round(item.progress * 100),
        "resultKind": (
            "" if item.result_identity is None else item.result_identity.kind.value
        ),
        "resultIdentity": (
            "" if item.result_identity is None else item.result_identity.value
        ),
        "errorCode": "" if item.error is None else item.error.code.value,
        "errorMessage": "" if item.error is None else item.error.message,
        "errorRetryable": False if item.error is None else item.error.retryable,
        "cancelable": item.cancelable,
        "retryable": item.retryable,
        "terminal": item.terminal,
        "predecessorTaskHandleId": (
            ""
            if item.predecessor_task_handle_id is None
            else item.predecessor_task_handle_id.value
        ),
    }


class DiagnosticTasksQtAdapter(QObject):
    """Qt-only projection of the typed Diagnostic Tasks Feature Interface."""

    stateChanged = Signal()
    announcementChanged = Signal()
    deliveryRequested = Signal(int, object)
    campaignContextReady = Signal(object)
    campaignHandoffReady = Signal(object)
    evidenceHandoffReady = Signal(object)

    def __init__(
        self,
        feature: DiagnosticTasksFeature,
        *,
        context: DiagnosticTasksContext | None = None,
        setup_selection_provider: (
            Callable[[], DiagnosticSetupSelectionContext | None] | None
        ) = None,
        setup_selection_refresh: Callable[[], None] | None = None,
        setup_selection_coordinator: (
            DiagnosticSetupSelectionCoordinator | None
        ) = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or DiagnosticTasksContext.workspace()
        self._setup_selection_provider = setup_selection_provider
        self._setup_selection_refresh = setup_selection_refresh
        self._setup_selection_coordinator = setup_selection_coordinator
        self._refreshing_setup_selection = False
        if setup_selection_provider is not None:
            self._observe_current_setup_selection()
        self._state = feature.snapshot(self._context)
        self._setup_sources_diagnostic_generation = (
            None
            if setup_selection_provider is None
            else self._state.source.generation.value
        )
        self._mount_generation = _next_mount_generation()
        self._route_active = True
        self._campaign_navigation_pending = False
        self._last_emitted_monitoring_selection: tuple[str, str] | None = None
        self._last_emitted_evidence_selection: (
            tuple[str, str, str, str, str, str] | None
        ) = None
        self._create_status = (
            "Create is ready when all displayed authoritative inputs are ready."
        )
        self._command_status = (
            "Correction, validation, and exact-revision approval are ready "
            "when their typed capabilities are available."
        )
        self._last_accessibility_announcement_key = (
            self._accessibility_announcement_key()
        )
        self._closed = False
        self.stateChanged.connect(
            self._emit_accessibility_announcement_if_changed
        )
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: DiagnosticTasksViewState) -> None:
        if not self._closed and self._route_active:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: DiagnosticTasksViewState,
    ) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        self._refresh_setup_selection_sources(
            diagnostic_generation=state.source.generation.value,
            force=state.freshness.value != "fresh",
        )
        self._state = state
        self.stateChanged.emit()
        self._emit_monitoring_handoff_if_ready()
        self._emit_evidence_handoff_if_ready()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        error = self._state.error
        details = (
            f"{self.freshness} · {self.presentationState} · "
            f"{self._state.completeness.value}"
        )
        return (
            details
            if error is None
            else (
                f"{details} · structured error {error.code}: "
                f"{error.message} · retryable "
                f"{str(error.retryable).lower()}"
            )
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def stateTitle(self) -> str:  # noqa: N802
        presentation_state = str(self._state.presentation.value)
        return {
            "loading": "Loading authoritative inputs",
            "empty": "No authoritative inputs are registered",
            "ready": "Authoritative inputs are ready",
            "degraded": "Showing last reliable authoritative inputs",
            "failed": "Authoritative input read failed",
            "input_unavailable": "Required authoritative inputs are unavailable",
        }[presentation_state]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceText(self) -> str:  # noqa: N802
        return (
            f"{self._state.source.identity} · "
            f"g{self._state.source.generation.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def strategyCatalogText(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.strategies:
            return "No authoritative Strategy Under Test is available."
        return "\n".join(
            (
                f"{item.strategy_id.value}@{item.strategy_version} · "
                f"{'required fixed input' if item.required else 'optional input'} · "
                f"compatibility {item.compatibility_surface_version} "
                f"{item.compatibility_manifest_hash} · "
                f"module {item.strategy_module} · "
                f"guardrail {item.guardrail_profile_id.value}@"
                f"{item.guardrail_profile_version} · thresholds "
                + ", ".join(
                    f"{threshold.metric_name} {threshold.operator} {threshold.value}"
                    for threshold in item.guardrail_thresholds
                )
            )
            for item in inventory.strategies
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def recipeCatalogText(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.approved_recipes:
            return "No approved Scenario Recipe version is available."
        return "\n".join(
            (
                f"{item.recipe_id} · {item.recipe_version_id.value} · "
                f"{item.content_hash} · schema {item.schema_version} · "
                f"catalog {item.transformation_catalog_version}"
            )
            for item in inventory.approved_recipes
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarioCatalogText(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.market_scenarios:
            return "No materialized Market Scenario is available."
        return "\n".join(
            (
                f"{item.market_scenario_id.value} · {item.layer.value} · "
                f"case {item.campaign_case_id.value} · "
                f"source {item.historical_segment_id.value} "
                f"{item.historical_segment_content_hash} · "
                f"snapshot {item.source_snapshot_id.value} · "
                f"seed {item.materialization_seed} · "
                f"materializer {item.materialization_provenance.expander_version} "
                f"{item.materialization_provenance.source_resolution}->"
                f"{item.materialization_provenance.runtime_resolution} · "
                f"numeric tolerance "
                f"{item.materialization_provenance.numeric_tolerance} · "
                f"normalization "
                f"{item.materialization_provenance.normalization_provenance} · "
                f"reconstructed "
                f"{str(item.materialization_provenance.reconstructed).lower()} · "
                f"transformations {item.transformation_catalog_version}/"
                + (
                    ", ".join(
                        f"{transformation.transformation_id} "
                        f"[{transformation.family}]@"
                        f"{transformation.implementation_version} "
                        + (
                            "("
                            + ", ".join(
                                f"{parameter.name}={parameter.value}"
                                for parameter in transformation.parameters
                            )
                            + ")"
                            if transformation.parameters
                            else "(no parameters)"
                        )
                        for transformation in item.applied_transformations
                    )
                    or "baseline (no applied transformations)"
                )
                + " · "
                f"market rules {item.market_rule_profile_version} · "
                f"comparison {item.comparison_requirement} · "
                "execution policy "
                + ", ".join(
                    f"{value.name}={value.value}@{value.version} "
                    f"from {value.source}"
                    for value in item.execution_policy_values
                )
            )
            for item in inventory.market_scenarios
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reproductionManifestStatus(self) -> str:  # noqa: N802
        return str(self._state.reproduction_manifest_availability.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def blockingReasonsText(self) -> str:  # noqa: N802
        if not self._state.blocking_reasons:
            return "No blocking reason."
        return "\n".join(
            f"{reason.code.value}: {reason.message}"
            for reason in self._state.blocking_reasons
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCreate(self) -> bool:  # noqa: N802
        return bool(
            self._state.capabilities.can_create
            and (
                self._setup_selection_provider is None
                or self._current_setup_selection() is not None
            )
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canRevise(self) -> bool:  # noqa: N802
        return bool(
            self._state.capabilities.can_revise
            and (
                self._setup_selection_provider is None
                or self._current_setup_selection() is not None
            )
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def setupSelectionReady(self) -> bool:  # noqa: N802
        return self._current_setup_selection() is not None

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def setupSelectionText(self) -> str:  # noqa: N802
        setup = self._current_setup_selection()
        if setup is None:
            return (
                "Select one current formal Strategy set and one current "
                "formal Scenario Set before Diagnostic Task handoff."
            )
        scenario = setup.scenario_selection.context
        strategy = setup.strategy_selection
        return (
            f"Setup {setup.context_identity} · Strategy selection "
            f"{strategy.context_identity} · Strategy source "
            f"{strategy.source_revision.value} / view "
            f"r{strategy.originating_view_revision} / generation "
            f"g{strategy.source_generation.value} · Scenario selection "
            f"{scenario.selection_context_id.value} / set "
            f"{scenario.scenario_set_id.value}@"
            f"r{scenario.scenario_set_projection_revision} / resolution "
            f"{scenario.execution_resolution_id.value}@"
            f"r{scenario.execution_resolution_projection_revision} / "
            f"selection r{scenario.selection_revision} / view "
            f"r{scenario.originating_view_revision} / source "
            f"{scenario.source_revision.value} / generation "
            f"g{scenario.source_generation.value} · configuration "
            f"{setup.configuration.content_identity.value}"
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canValidate(self) -> bool:  # noqa: N802
        return bool(
            self._state.capabilities.can_validate
            and self._current_setup_matches_task()
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canApprove(self) -> bool:  # noqa: N802
        return bool(
            self._state.capabilities.can_approve
            and self._current_setup_matches_task()
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canStartCampaign(self) -> bool:  # noqa: N802
        return bool(
            self._state.capabilities.can_start_campaign
            and self._current_setup_matches_task()
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPauseTask(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_pause)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResumeTask(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_resume)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancelTask(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_cancel)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPauseCampaign(self) -> bool:  # noqa: N802
        task = self._state.task
        return bool(
            task is not None
            and task.handoff.campaign_id is not None
            and task.handoff.campaign_lifecycle
            is DiagnosticTaskLifecycle.RUNNING
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResumeCampaign(self) -> bool:  # noqa: N802
        task = self._state.task
        return bool(
            task is not None
            and task.handoff.campaign_id is not None
            and task.handoff.campaign_lifecycle
            is DiagnosticTaskLifecycle.PAUSED
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancelCampaign(self) -> bool:  # noqa: N802
        task = self._state.task
        return bool(
            task is not None
            and task.handoff.campaign_id is not None
            and task.handoff.campaign_lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.RESUMING,
            }
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPauseCampaignNode(self) -> bool:  # noqa: N802
        task = self._state.task
        node = self._actionable_campaign_node()
        return bool(
            task is not None
            and task.lifecycle is DiagnosticTaskLifecycle.RUNNING
            and node is not None
            and node.lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
            }
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResumeCampaignNode(self) -> bool:  # noqa: N802
        task = self._state.task
        node = self._actionable_campaign_node()
        return bool(
            task is not None
            and task.lifecycle is DiagnosticTaskLifecycle.RUNNING
            and node is not None
            and node.lifecycle is DiagnosticTaskLifecycle.PAUSED
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancelCampaignNode(self) -> bool:  # noqa: N802
        node = self._actionable_campaign_node()
        return bool(
            node is not None
            and node.lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.RESUMING,
            }
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canRetryFailedCampaignNode(self) -> bool:  # noqa: N802
        return bool(
            self._state.capabilities.can_retry_failed_node
            and self._retryable_campaign_node() is not None
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def taskStatusText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None:
            return "No durable Diagnostic Task has been created."
        return (
            f"{task.task_id.value} · r{task.revision} · "
            f"{task.lifecycle.value} · configuration "
            f"{task.configuration.content_identity.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def taskHandleText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None or not task.task_handles:
            return "No persistent TaskHandle is available."
        return "\n".join(
            (
                f"{handle.identity.value} · {handle.phase.value} · "
                f"{handle.progress:.0%} · "
                f"{handle.result or 'pending'} · "
                f"cancelable {str(handle.cancelable).lower()}"
            )
            for handle in task.task_handles
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def createStatusText(self) -> str:  # noqa: N802
        return self._create_status

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def validationStatusText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None:
            return "No Diagnostic Task revision is available for validation."
        validation = task.validation
        if validation.validation_id is None:
            return f"Task r{task.revision} has not been validated."
        findings = (
            "no findings"
            if not validation.findings
            else "; ".join(
                f"{item.severity.value} {item.code.value}: "
                f"{item.safe_explanation}"
                for item in validation.findings
            )
        )
        return (
            f"{validation.state.value} · validation "
            f"{validation.validation_id.value}@"
            f"{validation.validation_revision} · task "
            f"r{validation.validated_revision} · {findings}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def approvalStatusText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None or task.approval is None:
            return "No exact-revision approval is active."
        approval = task.approval
        return (
            f"{approval.approval_id.value} · task "
            f"r{approval.approved_revision} · validation "
            f"{approval.validation_id.value}@"
            f"{approval.validation_revision} · actor "
            f"{approval.actor_identity.value} · "
            f"{approval.approved_at.isoformat()}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignHandoffText(self) -> str:  # noqa: N802
        context = self.monitoring_context()
        if context is None or context.selection is None:
            return "No Formal Diagnostic Campaign has been handed off."
        selection = context.selection
        return (
            f"Campaign {selection.campaign_id.value} · "
            f"Run {selection.run_id.value if selection.run_id is not None else 'pending'}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def evidenceHandoffText(self) -> str:
        task = self._state.task
        if task is None or task.handoff.campaign_id is None:
            return "No Evidence and Findings handoff is available."
        handoff = task.handoff
        run_lines = tuple(
            (
                f"Campaign Case {node.selected_campaign_case_id.value}; "
                f"Market Scenario {node.market_scenario_id.value}; "
                f"attempt {attempt.attempt_id.value}; "
                f"Run {run.run_id.value}; "
                f"Strategy Under Test {run.strategy_id.value}; "
                "Reproduction Manifest "
                f"{run.reproduction_manifest_id.value if run.reproduction_manifest_id is not None else 'not yet available'}"
            )
            for node in handoff.campaign_nodes
            for attempt in node.attempts
            if attempt.attempt_id == node.active_attempt_id
            for run in attempt.runs
        )
        return " · ".join(
            (
                (
                    f"Evidence Package "
                    f"{handoff.evidence_package_id.value if handoff.evidence_package_id is not None else 'not yet available'}"
                ),
                (
                    f"Top Reproduction Manifest "
                    f"{handoff.reproduction_manifest_id.value if handoff.reproduction_manifest_id is not None else 'not yet available'}"
                ),
                *run_lines,
            )
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignLifecycleText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None or task.handoff.campaign_id is None:
            return "No Formal Diagnostic Campaign lifecycle is available."
        lifecycle = task.handoff.campaign_lifecycle
        revision = task.handoff.campaign_revision
        return (
            f"{task.handoff.campaign_id.value} · "
            f"r{revision if revision is not None else 'unknown'} · "
            f"{lifecycle.value if lifecycle is not None else 'unknown'}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignNodeLifecycleText(self) -> str:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None:
            return "No actionable Campaign node is available."
        return (
            f"{node.campaign_node_id.value} · r{node.revision} · "
            f"{node.lifecycle.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def failedNodeRetryText(self) -> str:  # noqa: N802
        node = self._retry_history_campaign_node()
        if node is None:
            return "No failed Campaign attempt history is available."
        attempts = "; ".join(
            (
                f"attempt {attempt.attempt_number} "
                f"{attempt.attempt_id.value} · {attempt.lifecycle.value} · "
                "predecessor "
                f"{attempt.predecessor_attempt_id.value if attempt.predecessor_attempt_id is not None else 'none'} · "
                "TaskHandle "
                f"{attempt.task_handle_id.value if attempt.task_handle_id is not None else 'none'} · "
                "failure "
                f"{attempt.failure.code + ': ' + attempt.failure.message if attempt.failure is not None else 'none'}"
            )
            for attempt in node.attempts
        )
        return (
            f"Node {node.campaign_node_id.value} · r{node.revision} · "
            f"{attempts}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def commandStatusText(self) -> str:  # noqa: N802
        return self._command_status

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def capabilitiesText(self) -> str:
        capabilities = (
            ("create", self.canCreate),
            ("correct", self.canRevise),
            ("validate", self.canValidate),
            ("approve", self.canApprove),
            ("start Campaign", self.canStartCampaign),
            (
                "pause",
                self.canPauseTask
                or self.canPauseCampaign
                or self.canPauseCampaignNode,
            ),
            (
                "resume",
                self.canResumeTask
                or self.canResumeCampaign
                or self.canResumeCampaignNode,
            ),
            (
                "cancel diagnostic target",
                self.canCancelTask
                or self.canCancelCampaign
                or self.canCancelCampaignNode,
            ),
            ("retry failed node", self.canRetryFailedCampaignNode),
        )
        return "Capabilities · " + " · ".join(
            f"{name} {'available' if available else 'unavailable'}"
            for name, available in capabilities
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def accessibilitySummaryText(self) -> str:
        error = self._state.error
        manifest_id = self._state.reproduction_manifest_id
        return ". ".join(
            (
                (
                    f"Diagnostic Tasks {self.presentationState}; "
                    f"freshness {self.freshness}; "
                    f"view revision {self.revisionText}; "
                    f"source {self.sourceText}"
                ),
                cast(str, self.taskStatusText),
                f"Validation {self.validationStatusText}",
                f"Approval {self.approvalStatusText}",
                f"TaskHandle {self.taskHandleText}",
                cast(str, self.campaignHandoffText),
                cast(str, self.evidenceHandoffText),
                cast(str, self.campaignLifecycleText),
                cast(str, self.campaignNodeLifecycleText),
                (
                    "Reproduction Manifest "
                    f"{self.reproductionManifestStatus} · "
                    f"{manifest_id.value if manifest_id is not None else 'no identity'}"
                ),
                cast(str, self.capabilitiesText),
                (
                    "No structured error."
                    if error is None
                    else (
                        f"Structured error {error.code}: {error.message}; "
                        f"retryable {str(error.retryable).lower()}."
                    )
                ),
            )
        )

    @Property(str, notify=announcementChanged)  # type: ignore[arg-type]
    def accessibilityAnnouncementText(self) -> str:
        return self._build_accessibility_announcement_text()

    def _build_accessibility_announcement_text(self) -> str:
        task = self._state.task
        error = self._state.error
        lifecycle = (
            "No Diagnostic Task"
            if task is None
            else f"Diagnostic Task {task.lifecycle.value}"
        )
        validation = (
            "validation unavailable"
            if task is None
            else f"validation {task.validation.state.value}"
        )
        approval = (
            "approval unavailable"
            if task is None or task.approval is None
            else (
                "approval bound to exact task revision "
                f"r{task.approval.approved_revision}"
            )
        )
        latest_handle = (
            None
            if task is None or not task.task_handles
            else task.task_handles[-1]
        )
        handle = (
            "no TaskHandle"
            if latest_handle is None
            else (
                f"TaskHandle {latest_handle.identity.value} "
                f"{latest_handle.phase.value} "
                f"{latest_handle.progress:.0%}"
            )
        )
        evidence = (
            "Evidence "
            + cast(str, self.reproductionManifestStatus).replace("_", " ")
        )
        error_text = (
            ""
            if error is None
            else f"; structured error {error.code}: {error.message}"
        )
        return (
            f"Diagnostic Tasks update; freshness {self.freshness}; "
            f"{lifecycle}; {validation}; {approval}; {handle}; "
            f"{evidence}; {self.commandStatusText}{error_text}"
        )

    def _accessibility_announcement_key(self) -> tuple[object, ...]:
        task = self._state.task
        error = self._state.error
        latest_handle = (
            None
            if task is None or not task.task_handles
            else task.task_handles[-1]
        )
        validation = None if task is None else task.validation
        approval = None if task is None else task.approval
        handoff = None if task is None else task.handoff
        node_states = (
            ()
            if handoff is None
            else tuple(
                (
                    node.campaign_node_id.value,
                    node.lifecycle.value,
                    (
                        None
                        if node.active_attempt_id is None
                        else node.active_attempt_id.value
                    ),
                    tuple(
                        (
                            attempt.attempt_id.value,
                            attempt.lifecycle.value,
                        )
                        for attempt in node.attempts
                        if attempt.attempt_id == node.active_attempt_id
                    ),
                )
                for node in handoff.campaign_nodes
            )
        )
        return (
            self._state.freshness.value,
            self._state.presentation.value,
            None if task is None else task.task_id.value,
            None if task is None else task.lifecycle.value,
            None if validation is None else validation.state.value,
            (
                None
                if validation is None or validation.validation_id is None
                else validation.validation_id.value
            ),
            None if approval is None else approval.approved_revision,
            (
                None
                if latest_handle is None
                else latest_handle.identity.value
            ),
            None if latest_handle is None else latest_handle.phase.value,
            None if latest_handle is None else latest_handle.result,
            (
                None
                if handoff is None or handoff.campaign_lifecycle is None
                else handoff.campaign_lifecycle.value
            ),
            node_states,
            self._state.reproduction_manifest_availability.value,
            None if error is None else error.code,
            self._create_status,
            self._command_status,
        )

    @Slot()
    def _emit_accessibility_announcement_if_changed(self) -> None:
        key = self._accessibility_announcement_key()
        if key == self._last_accessibility_announcement_key:
            return
        self._last_accessibility_announcement_key = key
        self.announcementChanged.emit()

    @Slot()
    def createTask(self) -> None:  # noqa: N802
        setup = self._current_setup_selection()
        configuration = self._configuration_from_inventory(
            include_all_cases=False
        )
        if configuration is None or not self.canCreate:
            self._create_status = (
                "Diagnostic Task creation requires all authoritative inputs."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        command_id = DiagnosticCommandId(
            f"create-diagnostic-task-{command_identity}"
        )
        idempotency_key = DiagnosticCommandIdempotencyKey(
            f"diagnostic-task-create-{command_identity}"
        )
        command = (
            CreateDiagnosticTask(
                command_id=command_id,
                idempotency_key=idempotency_key,
                configuration=configuration,
            )
            if setup is None
            else CreateDiagnosticTaskFromSetup(
                command_id=command_id,
                idempotency_key=idempotency_key,
                configuration=configuration,
                setup_selection=setup,
            )
        )
        result = self._feature.create_diagnostic_task(command)
        self._create_status = self._command_result_text(result)
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def reviseTask(self) -> None:  # noqa: N802
        task = self._state.task
        setup = self._current_setup_selection()
        configuration = self._configuration_from_inventory(
            include_all_cases=True
        )
        if task is None or configuration is None or not self.canRevise:
            self._command_status = (
                "Configuration correction is unavailable for this task state."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        command_id = DiagnosticCommandId(
            f"revise-diagnostic-task-{command_identity}"
        )
        idempotency_key = DiagnosticCommandIdempotencyKey(
            f"diagnostic-task-revise-{command_identity}"
        )
        command = (
            ReviseDiagnosticTaskConfiguration(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                configuration=configuration,
            )
            if setup is None
            else ReviseDiagnosticTaskConfigurationFromSetup(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                configuration=configuration,
                setup_selection=setup,
            )
        )
        result = self._feature.revise_configuration(command)
        self._command_status = self._command_result_text(result)
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def validateTask(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canValidate:
            self._command_status = (
                "Validation is unavailable for this task state."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        setup = self._current_setup_selection()
        command_id = DiagnosticCommandId(
            f"validate-diagnostic-task-{command_identity}"
        )
        idempotency_key = DiagnosticCommandIdempotencyKey(
            f"diagnostic-task-validate-{command_identity}"
        )
        result = self._feature.validate_configuration(
            ValidateDiagnosticTaskConfiguration(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
            )
            if setup is None
            else ValidateDiagnosticTaskConfigurationFromSetup(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                setup_selection=setup,
            )
        )
        self._command_status = self._command_result_text(result)
        self.refresh()
        self.stateChanged.emit()

    @Slot(str)
    def approveTask(self, actor_identity: str) -> None:  # noqa: N802
        task = self._state.task
        actor = actor_identity.strip()
        if task is None or not self.canApprove or not actor:
            self._command_status = (
                "Approval requires a valid exact revision and an actor identity."
            )
            self.stateChanged.emit()
            return
        validation = task.validation
        if (
            validation.validation_id is None
            or validation.validation_revision is None
            or validation.validated_revision is None
            or validation.configuration_content_identity is None
        ):
            self._command_status = (
                "Approval requires a valid exact revision."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        setup = self._current_setup_selection()
        command_id = DiagnosticCommandId(
            f"approve-diagnostic-task-{command_identity}"
        )
        idempotency_key = DiagnosticCommandIdempotencyKey(
            f"diagnostic-task-approve-{command_identity}"
        )
        result = self._feature.approve_configuration(
            ApproveDiagnosticTaskConfiguration(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                validation_id=validation.validation_id,
                validation_revision=validation.validation_revision,
                validated_revision=validation.validated_revision,
                configuration_content_id=(
                    validation.configuration_content_identity
                ),
                actor_id=DiagnosticActorId(actor),
            )
            if setup is None
            else ApproveDiagnosticTaskConfigurationFromSetup(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                validation_id=validation.validation_id,
                validation_revision=validation.validation_revision,
                validated_revision=validation.validated_revision,
                configuration_content_id=(
                    validation.configuration_content_identity
                ),
                actor_id=DiagnosticActorId(actor),
                setup_selection=setup,
            )
        )
        self._command_status = self._command_result_text(result)
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def startCampaign(self) -> None:  # noqa: N802
        task = self._state.task
        approval = None if task is None else task.approval
        if (
            task is None
            or approval is None
            or not self.canStartCampaign
            or approval.approved_revision != task.revision
        ):
            self._command_status = (
                "Campaign start requires the exact approved task revision."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        setup = self._current_setup_selection()
        command_id = DiagnosticCommandId(
            f"start-diagnostic-campaign-{command_identity}"
        )
        idempotency_key = DiagnosticCommandIdempotencyKey(
            f"diagnostic-campaign-start-{command_identity}"
        )
        result = self._feature.start_formal_diagnostic_campaign(
            StartFormalDiagnosticCampaign(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                approved_revision=approval.approved_revision,
            )
            if setup is None
            else StartFormalDiagnosticCampaignFromSetup(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task.task_id,
                expected_revision=task.revision,
                approved_revision=approval.approved_revision,
                setup_selection=setup,
            )
        )
        self._command_status = self._command_result_text(result)
        if result.rejection_reason is None:
            self._campaign_navigation_pending = True
        self.refresh()
        self.stateChanged.emit()
        self._emit_monitoring_handoff_if_ready()

    @Slot()
    def pauseDiagnosticTaskTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canPauseTask:
            self._lifecycle_unavailable("Task pause")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.pause_diagnostic_target(
                PauseDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"pause-diagnostic-task-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-task-pause-{command_identity}"
                    ),
                    target=DiagnosticTaskTarget(task.task_id),
                    expected_revision=task.revision,
                )
            )
        )

    @Slot()
    def resumeDiagnosticTaskTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canResumeTask:
            self._lifecycle_unavailable("Task resume")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.resume_diagnostic_target(
                ResumeDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"resume-diagnostic-task-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-task-resume-{command_identity}"
                    ),
                    target=DiagnosticTaskTarget(task.task_id),
                    expected_revision=task.revision,
                )
            )
        )

    @Slot()
    def cancelDiagnosticTaskTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canCancelTask:
            self._lifecycle_unavailable("Task cancel")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.cancel_diagnostic_target(
                CancelDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"cancel-diagnostic-task-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-task-cancel-{command_identity}"
                    ),
                    target=DiagnosticTaskTarget(task.task_id),
                    expected_revision=task.revision,
                )
            )
        )

    @Slot()
    def pauseFormalDiagnosticCampaignTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if (
            task is None
            or task.handoff.campaign_id is None
            or task.handoff.campaign_revision is None
            or not self.canPauseCampaign
        ):
            self._lifecycle_unavailable("Campaign pause")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.pause_diagnostic_target(
                PauseDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"pause-diagnostic-campaign-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-campaign-pause-{command_identity}"
                    ),
                    target=FormalDiagnosticCampaignTarget(
                        task.handoff.campaign_id
                    ),
                    expected_revision=task.handoff.campaign_revision,
                )
            )
        )

    @Slot()
    def resumeFormalDiagnosticCampaignTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if (
            task is None
            or task.handoff.campaign_id is None
            or task.handoff.campaign_revision is None
            or not self.canResumeCampaign
        ):
            self._lifecycle_unavailable("Campaign resume")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.resume_diagnostic_target(
                ResumeDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"resume-diagnostic-campaign-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-campaign-resume-{command_identity}"
                    ),
                    target=FormalDiagnosticCampaignTarget(
                        task.handoff.campaign_id
                    ),
                    expected_revision=task.handoff.campaign_revision,
                )
            )
        )

    @Slot()
    def cancelFormalDiagnosticCampaignTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if (
            task is None
            or task.handoff.campaign_id is None
            or task.handoff.campaign_revision is None
            or not self.canCancelCampaign
        ):
            self._lifecycle_unavailable("Campaign cancel")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.cancel_diagnostic_target(
                CancelDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"cancel-diagnostic-campaign-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-campaign-cancel-{command_identity}"
                    ),
                    target=FormalDiagnosticCampaignTarget(
                        task.handoff.campaign_id
                    ),
                    expected_revision=task.handoff.campaign_revision,
                )
            )
        )

    @Slot()
    def pauseCampaignNodeTarget(self) -> None:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None or not self.canPauseCampaignNode:
            self._lifecycle_unavailable("Campaign node pause")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.pause_diagnostic_target(
                PauseDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"pause-campaign-node-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"campaign-node-pause-{command_identity}"
                    ),
                    target=CampaignNodeTarget(node.campaign_node_id),
                    expected_revision=node.revision,
                )
            )
        )

    @Slot()
    def resumeCampaignNodeTarget(self) -> None:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None or not self.canResumeCampaignNode:
            self._lifecycle_unavailable("Campaign node resume")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.resume_diagnostic_target(
                ResumeDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"resume-campaign-node-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"campaign-node-resume-{command_identity}"
                    ),
                    target=CampaignNodeTarget(node.campaign_node_id),
                    expected_revision=node.revision,
                )
            )
        )

    @Slot()
    def cancelCampaignNodeTarget(self) -> None:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None or not self.canCancelCampaignNode:
            self._lifecycle_unavailable("Campaign node cancel")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.cancel_diagnostic_target(
                CancelDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"cancel-campaign-node-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"campaign-node-cancel-{command_identity}"
                    ),
                    target=CampaignNodeTarget(node.campaign_node_id),
                    expected_revision=node.revision,
                )
            )
        )

    @Slot()
    def retryFailedCampaignNode(self) -> None:  # noqa: N802
        task = self._state.task
        node = self._retryable_campaign_node()
        attempt = (
            None
            if node is None or node.active_attempt_id is None
            else next(
                (
                    candidate
                    for candidate in node.attempts
                    if candidate.attempt_id == node.active_attempt_id
                ),
                None,
            )
        )
        if (
            task is None
            or node is None
            or attempt is None
            or not self.canRetryFailedCampaignNode
        ):
            self._lifecycle_unavailable("Failed Campaign node retry")
            return
        command_identity = uuid4().hex
        result = self._feature.retry_failed_campaign_node(
            RetryFailedCampaignNode(
                command_id=DiagnosticCommandId(
                    f"retry-failed-campaign-node-{command_identity}"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    f"failed-campaign-node-retry-{command_identity}"
                ),
                task_id=task.task_id,
                campaign_node_id=node.campaign_node_id,
                failed_attempt_id=attempt.attempt_id,
                expected_revision=node.revision,
            )
        )
        self._command_status = self._command_result_text(result)
        if result.rejection_reason is None:
            self._campaign_navigation_pending = True
        self.refresh()
        self.stateChanged.emit()
        self._emit_monitoring_handoff_if_ready()

    def _complete_lifecycle_command(
        self,
        result: DiagnosticTasksCommandResult,
    ) -> None:
        self._command_status = self._command_result_text(result)
        self.refresh()
        self.stateChanged.emit()

    @staticmethod
    def _command_result_text(
        result: DiagnosticTasksCommandResult,
    ) -> str:
        reason = result.rejection_reason
        if reason is None:
            return result.message
        current_revision = (
            ""
            if result.current_revision is None
            else (
                " Authoritative current revision "
                f"r{result.current_revision}."
            )
        )
        return (
            f"{result.message} Rejection "
            f"{reason.value.replace('_', ' ')}."
            f"{current_revision}"
        )

    def _lifecycle_unavailable(self, operation: str) -> None:
        self._command_status = (
            f"{operation} is unavailable for the authoritative lifecycle."
        )
        self.stateChanged.emit()

    def _actionable_campaign_node(
        self,
    ) -> DiagnosticCampaignNodeHandoff | None:
        task = self._state.task
        if task is None:
            return None
        terminal = {
            DiagnosticTaskLifecycle.CANCELED,
            DiagnosticTaskLifecycle.COMPLETED,
            DiagnosticTaskLifecycle.FAILED,
        }
        return next(
            (
                node
                for node in task.handoff.campaign_nodes
                if node.lifecycle not in terminal
            ),
            next(iter(task.handoff.campaign_nodes), None),
        )

    def _retryable_campaign_node(
        self,
    ) -> DiagnosticCampaignNodeHandoff | None:
        task = self._state.task
        if task is None:
            return None
        return next(
            (
                node
                for node in task.handoff.campaign_nodes
                if node.lifecycle is DiagnosticTaskLifecycle.FAILED
                and node.active_attempt_id is not None
                and bool(node.attempts)
                and node.attempts[-1].attempt_id == node.active_attempt_id
                and node.attempts[-1].lifecycle
                is DiagnosticTaskLifecycle.FAILED
            ),
            None,
        )

    def _retry_history_campaign_node(
        self,
    ) -> DiagnosticCampaignNodeHandoff | None:
        retryable = self._retryable_campaign_node()
        if retryable is not None:
            return retryable
        task = self._state.task
        if task is None:
            return None
        return next(
            (
                node
                for node in task.handoff.campaign_nodes
                if len(node.attempts) > 1
                or any(attempt.failure is not None for attempt in node.attempts)
            ),
            None,
        )

    def monitoring_context(self) -> RunMonitoringContext | None:
        task = self._state.task
        if task is None:
            return None
        handoff = task.handoff
        if handoff.campaign_id is None:
            return None
        authoritative_manifest_id = handoff.reproduction_manifest_id
        for node in handoff.campaign_nodes:
            active_attempt = next(
                (
                    attempt
                    for attempt in node.attempts
                    if attempt.attempt_id == node.active_attempt_id
                ),
                None,
            )
            if active_attempt is not None:
                for run in active_attempt.runs:
                    if (
                        authoritative_manifest_id is not None
                        and run.reproduction_manifest_id
                        != authoritative_manifest_id
                    ):
                        continue
                    return RunMonitoringContext.for_run(
                        RunMonitoringSelection(
                            campaign_id=handoff.campaign_id,
                            run_id=run.run_id,
                        )
                    )
        return None

    def recovery_task_id(self) -> DiagnosticTaskId | None:
        """Return only the selected durable task identity, never its config."""

        task = self._state.task
        return self._context.task_id if task is None else task.task_id

    def evidence_context(self) -> EvidenceAndFindingsContext | None:
        task = self._state.task
        if task is None or not task.handoff.ready_for_evidence_and_findings:
            return None
        handoff = task.handoff
        if handoff.campaign_id is None:
            return None
        authoritative_manifest_id = handoff.reproduction_manifest_id
        if authoritative_manifest_id is None:
            return None
        selected_cases = {
            item.campaign_case_id: item
            for item in handoff.selected_cases
        }
        for node in handoff.campaign_nodes:
            selected_case = selected_cases.get(node.selected_campaign_case_id)
            if selected_case is None or node.active_attempt_id is None:
                continue
            active_attempt = next(
                (
                    item
                    for item in node.attempts
                    if item.attempt_id == node.active_attempt_id
                ),
                None,
            )
            if active_attempt is None:
                continue
            for run in active_attempt.runs:
                if (
                    run.reproduction_manifest_id
                    != authoritative_manifest_id
                ):
                    continue
                return EvidenceAndFindingsContext.for_selection(
                    EvidenceAndFindingsSelection(
                        campaign_id=handoff.campaign_id,
                        run_id=run.run_id,
                        strategy_id=run.strategy_id,
                        market_scenario_id=MarketScenarioId(
                            node.campaign_case_id.value
                        ),
                        approved_recipe_id=ApprovedScenarioRecipeId(
                            selected_case.recipe_version_id.value
                        ),
                        reproduction_manifest_id=(
                            run.reproduction_manifest_id
                        ),
                    )
                )
        return None

    def _emit_monitoring_handoff_if_ready(self) -> None:
        context = self.monitoring_context()
        if context is None or context.selection is None:
            return
        selection = context.selection
        if selection.run_id is None:
            return
        identity = (selection.campaign_id.value, selection.run_id.value)
        if identity == self._last_emitted_monitoring_selection:
            return
        self._last_emitted_monitoring_selection = identity
        self.campaignContextReady.emit(context)
        if self._campaign_navigation_pending:
            self._campaign_navigation_pending = False
            self.campaignHandoffReady.emit(context)

    def _emit_evidence_handoff_if_ready(self) -> None:
        context = self.evidence_context()
        if context is None or context.selection is None:
            return
        selection = context.selection
        if (
            selection.strategy_id is None
            or selection.market_scenario_id is None
            or selection.approved_recipe_id is None
            or selection.reproduction_manifest_id is None
        ):
            return
        identity = (
            selection.campaign_id.value,
            selection.run_id.value,
            selection.strategy_id.value,
            selection.market_scenario_id.value,
            selection.approved_recipe_id.value,
            selection.reproduction_manifest_id.value,
        )
        if identity == self._last_emitted_evidence_selection:
            return
        self._last_emitted_evidence_selection = identity
        self.evidenceHandoffReady.emit(context)

    def _configuration_from_inventory(
        self,
        *,
        include_all_cases: bool,
    ) -> DiagnosticTaskConfiguration | None:
        if self._setup_selection_provider is not None:
            setup = self._current_setup_selection()
            return None if setup is None else setup.configuration
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.market_scenarios:
            return None
        recipe_by_id = {
            item.recipe_version_id: item
            for item in inventory.approved_recipes
        }
        baseline_case_id = next(
            (
                item.campaign_case_id
                for item in inventory.market_scenarios
                if item.layer is DiagnosticCampaignLayer.BASELINE
            ),
            None,
        )
        if baseline_case_id is None:
            return None
        selected_scenarios = tuple(
            item
            for item in inventory.market_scenarios
            if include_all_cases
            or item.layer is DiagnosticCampaignLayer.BASELINE
        )
        return DiagnosticTaskConfiguration.create(
            strategy_selections=tuple(
                DiagnosticStrategySelection(
                    strategy_id=item.strategy_id,
                    strategy_version=item.strategy_version,
                    compatibility_manifest_hash=(
                        item.compatibility_manifest_hash
                    ),
                    guardrail_profile_id=item.guardrail_profile_id,
                    guardrail_profile_version=item.guardrail_profile_version,
                )
                for item in inventory.strategies
            ),
            campaign_case_selections=tuple(
                DiagnosticCampaignCaseSelection(
                    layer=item.layer,
                    recipe_version_id=item.recipe_version_id,
                    recipe_content_hash=recipe_by_id[
                        item.recipe_version_id
                    ].content_hash,
                    market_scenario_id=item.market_scenario_id,
                    campaign_case_id=item.campaign_case_id,
                    comparison_role=(
                        DiagnosticComparisonRole.CONTROL
                        if item.layer is DiagnosticCampaignLayer.BASELINE
                        else DiagnosticComparisonRole.COMPARE_TO_BASELINE
                    ),
                    baseline_campaign_case_id=(
                        None
                        if item.layer is DiagnosticCampaignLayer.BASELINE
                        else baseline_case_id
                    ),
                    execution_policy_values=item.execution_policy_values,
                )
                for item in selected_scenarios
            ),
        )

    def _current_setup_selection(self) -> DiagnosticSetupSelectionContext | None:
        provider = self._setup_selection_provider
        if provider is None:
            return None
        try:
            return provider()
        except (KeyError, TypeError, ValueError):
            return None

    def _observe_current_setup_selection(self) -> None:
        coordinator = self._setup_selection_coordinator
        if coordinator is not None:
            coordinator.observe(self._current_setup_selection())

    def _refresh_setup_selection_sources(
        self,
        *,
        diagnostic_generation: int | None = None,
        force: bool = False,
    ) -> None:
        if self._refreshing_setup_selection:
            return
        if (
            not force
            and diagnostic_generation is not None
            and diagnostic_generation
            == self._setup_sources_diagnostic_generation
        ):
            return
        self._refreshing_setup_selection = True
        try:
            refresh = self._setup_selection_refresh
            if refresh is not None:
                refresh()
            self._observe_current_setup_selection()
            if diagnostic_generation is not None:
                self._setup_sources_diagnostic_generation = (
                    diagnostic_generation
                )
        finally:
            self._refreshing_setup_selection = False

    def _current_setup_matches_task(self) -> bool:
        if self._setup_selection_provider is None:
            return True
        setup = self._current_setup_selection()
        task = self._state.task
        if setup is None or task is None:
            return False
        binding_identity = task.setup_selection_context_identity
        if binding_identity is None or binding_identity == setup.context_identity:
            return True
        binding_generation = task.setup_strategy_source_generation
        binding_scenario = task.setup_scenario_selection_context_identity
        return bool(
            binding_generation is not None
            and setup.strategy_selection.source_generation.value
            > binding_generation
            and binding_scenario
            == setup.scenario_selection.context.selection_context_id.value
            and task.configuration.content_identity
            == setup.configuration.content_identity
        )

    def upstreamSelectionChanged(self) -> None:  # noqa: N802
        if self._closed or self._refreshing_setup_selection:
            return
        self._observe_current_setup_selection()
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def refresh(self) -> None:
        self._accept_state(
            self._mount_generation.value,
            self._feature.snapshot(self._context),
        )

    def set_route_active(self, active: bool) -> None:
        if self._closed or active is self._route_active:
            return
        self._route_active = active
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        if active:
            state = self._feature.snapshot(self._context)
            self._refresh_setup_selection_sources(
                diagnostic_generation=state.source.generation.value,
                force=state.freshness.value != "fresh",
            )
            self._state = state
            self._subscription = self._feature.subscribe(
                self._context,
                self._queue_state,
            )
            self.stateChanged.emit()
            self._emit_monitoring_handoff_if_ready()
            self._emit_evidence_handoff_if_ready()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._route_active = False
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


class RunMonitoringQtAdapter(QObject):
    """Qt-only projection of the external typed Run Monitoring Interface."""

    stateChanged = Signal()
    commandChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or RunMonitoringContext.no_selection()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._route_active = True
        self._closed = False
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: RunMonitoringViewState) -> None:
        if self._closed or not self._route_active:
            return
        self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: RunMonitoringViewState,
    ) -> None:
        if (
            self._closed
            or mount_generation != self._mount_generation.value
        ):
            return
        if state.context != self._context:
            return
        if state.revision <= self._state.revision:
            return
        self._state = state
        self.stateChanged.emit()

    def select_context(self, context: RunMonitoringContext) -> None:
        if self._closed:
            return
        if context == self._context:
            return
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        self._mount_generation = _next_mount_generation()
        self._context = context
        self._state = self._feature.snapshot(context)
        self._subscription = (
            self._feature.subscribe(context, self._queue_state)
            if self._route_active
            else None
        )
        self.stateChanged.emit()

    def set_route_active(self, active: bool) -> None:
        if self._closed or active is self._route_active:
            return
        self._route_active = active
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        if active:
            self._state = self._feature.snapshot(self._context)
            self._subscription = self._feature.subscribe(
                self._context,
                self._queue_state,
            )
            self.stateChanged.emit()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def phase(self) -> str:
        return str(self._state.phase.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def ageText(self) -> str:  # noqa: N802 - QML property convention
        return f"{self._state.age.total_seconds():.1f}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshnessThresholdText(self) -> str:  # noqa: N802
        return f"{self._state.freshness_threshold.total_seconds():.1f}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def completeness(self) -> str:
        return str(self._state.completeness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        details = (
            f"{self.freshness} · {self.phase} · {self.completeness}"
        )
        error = self._state.error
        if error is not None:
            return f"{details} · {error.code} · {error.message}"
        return details

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802 - QML property convention
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def observedAtText(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.observed_at.isoformat())

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceIdentity(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.source.identity)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceGenerationText(self) -> str:  # noqa: N802
        return f"g{self._state.source.generation.value}"

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def mountGeneration(self) -> int:  # noqa: N802
        return self._mount_generation.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def mountGenerationText(self) -> str:  # noqa: N802
        return f"m{self._mount_generation.value}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignIdentity(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        return "" if selection is None else selection.campaign_id.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def runIdentity(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        if selection is None or selection.run_id is None:
            return ""
        return str(selection.run_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def strategyIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.strategy_id is None:
            return "Unavailable"
        return str(data.strategy_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarioIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.market_scenario_id is None:
            return "Unavailable"
        return str(data.market_scenario_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def scenarioSetIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.scenario_set_id is None:
            return "Unavailable"
        return str(data.scenario_set_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reproductionManifestIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.reproduction_manifest_id is None:
            return "Unavailable"
        return str(data.reproduction_manifest_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def lifecycle(self) -> str:
        data = self._state.last_reliable_data
        return "" if data is None else data.lifecycle.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def terminalOutcome(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.terminal_outcome is None:
            return ""
        return str(data.terminal_outcome.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def currentNodeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return (
            f"{data.progress.current_node_id} · "
            f"{data.progress.current_node_label}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def progressText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return f"{data.progress.completed} / {data.progress.total}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def simulationTimeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return (
            f"Day {data.simulation_time.sim_day} · "
            f"{data.simulation_time.instant.isoformat()}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def wallTimeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        seconds = int(data.wall_time.elapsed.total_seconds())
        return f"{data.wall_time.observed_at.isoformat()} · elapsed {seconds}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def executionAssumptionsText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return "\n".join(
            (
                f"{item.name}: requested {item.requested_value}; "
                f"effective {item.effective_value}"
                + (
                    f"; override {item.override_reason}"
                    if item.override_reason
                    else ""
                )
            )
            for item in data.execution_assumptions
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def alertsText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return "\n".join(
            f"{item.severity.value.upper()} · {item.message}"
            for item in data.alerts
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def diagnosticContextText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        context = data.context
        return "\n".join(
            (
                f"Market · {', '.join(context.market) or 'none'}",
                f"Account · {', '.join(context.account) or 'none'}",
                f"Positions · {', '.join(context.positions) or 'none'}",
                f"Orders · {', '.join(context.orders) or 'none'}",
                f"Fills · {', '.join(context.fills) or 'none'}",
            )
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPause(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_pause
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResume(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_resume
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancel(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_cancel
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def activeTaskText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.active_task is None:
            return ""
        task = data.active_task
        details = [
            task.identity.value,
            task.phase.value,
            f"{round(task.progress * 100)}%",
            "cancelable" if task.cancelable else "not cancelable",
        ]
        if task.result:
            details.append(task.result)
        if task.error is not None:
            details.extend((task.error.code, task.error.message))
        return " · ".join(details)

    @Property(str, notify=commandChanged)  # type: ignore[arg-type]
    def commandMessage(self) -> str:  # noqa: N802
        return getattr(self, "_command_message", "")

    @Slot()
    def refresh(self) -> None:
        self._accept_state(
            self._mount_generation.value,
            self._feature.snapshot(self._context),
        )

    @Slot()
    def pauseDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.pause_diagnostic_task(
            PauseDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    @Slot()
    def resumeDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.resume_diagnostic_task(
            ResumeDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    @Slot()
    def cancelDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.cancel_diagnostic_task(
            CancelDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    def _set_command_message(self, message: str) -> None:
        if getattr(self, "_command_message", "") == message:
            return
        self._command_message = message
        self.commandChanged.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._route_active = False
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


class EvidenceAndFindingsQtAdapter(QObject):
    """Qt projection plus local-only research exploration state."""

    stateChanged = Signal()
    localStateChanged = Signal()
    chartPresentationChanged = Signal()
    chartSemanticsChanged = Signal()
    chartGeometryChanged = Signal()
    chartInteractionChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: EvidenceAndFindingsFeature,
        *,
        context: EvidenceAndFindingsContext | None = None,
        chart_clock: Callable[[], int] = monotonic_ns,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or EvidenceAndFindingsContext.no_selection()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._route_active = True
        self._closed = False
        self._selected_candidate = ""
        self._selected_finding = ""
        self._evidence_filter = "all"
        self._sort_order = "dimension"
        self._active_tab = "findings"
        self._viewport_intent = "overview"
        self._selected_point_source_index: int | None = None
        self._selected_overlay = ""
        self._selected_breakpoint = ""
        self._chart_clock = chart_clock
        self._chart_frame_gate = EvidenceChartFrameGate(
            max_frames_per_second=20
        )
        self._pending_chart_presentations: list[
            EvidenceChartPresentation
        ] = []
        self._chart_interaction_enabled = False
        self._chart_timer = QTimer(self)
        self._chart_timer.setSingleShot(True)
        self._chart_timer.timeout.connect(self.flush_chart_frames)
        self._repair_local_selection()
        self._chart_presentation = self._build_chart_presentation()
        self._chart_semantic_presentation = self._chart_presentation
        self._chart_frame_sequence = 1
        initial_gate = self._chart_frame_gate.offer(
            self._chart_presentation.frame,
            now_ns=self._chart_clock(),
        )
        if not initial_gate.committed:
            raise RuntimeError(
                "Initial Evidence chart presentation was not committed"
            )
        self._sync_chart_interaction_enabled()
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: EvidenceAndFindingsSubscription | None = (
            feature.subscribe(
                self._context,
                self._queue_state,
            )
        )

    def _queue_state(self, state: EvidenceAndFindingsViewState) -> None:
        if not self._closed and self._route_active:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: EvidenceAndFindingsViewState,
    ) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        previous_state = self._state
        self._state = state
        self._repair_local_selection()
        if (
            state.context == previous_state.context
            and state.source == previous_state.source
            and state.last_reliable_data is previous_state.last_reliable_data
        ):
            presentation = advance_evidence_chart_presentation_revision(
                self._chart_presentation,
                state,
            )
        else:
            presentation = self._build_chart_presentation()
        self._offer_chart_presentation(
            presentation,
            local=False,
        )
        self.stateChanged.emit()
        self.localStateChanged.emit()

    def select_context(self, context: EvidenceAndFindingsContext) -> None:
        if self._closed or context == self._context:
            return
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        self._mount_generation = _next_mount_generation()
        self._context = context
        self._state = self._feature.snapshot(context)
        self._selected_candidate = ""
        self._selected_finding = ""
        self._selected_point_source_index = None
        self._selected_overlay = ""
        self._selected_breakpoint = ""
        self._repair_local_selection()
        self._chart_timer.stop()
        self._pending_chart_presentations.clear()
        self._chart_frame_gate = EvidenceChartFrameGate(
            max_frames_per_second=20
        )
        self._chart_presentation = self._build_chart_presentation()
        self._chart_semantic_presentation = self._chart_presentation
        self._chart_frame_sequence += 1
        initial_gate = self._chart_frame_gate.offer(
            self._chart_presentation.frame,
            now_ns=self._chart_clock(),
        )
        if not initial_gate.committed:
            raise RuntimeError(
                "Selected Evidence chart presentation was not committed"
            )
        self._subscription = (
            self._feature.subscribe(context, self._queue_state)
            if self._route_active
            else None
        )
        self.stateChanged.emit()
        self.localStateChanged.emit()
        self.chartPresentationChanged.emit()
        self.chartSemanticsChanged.emit()
        self.chartGeometryChanged.emit()
        self._sync_chart_interaction_enabled()

    def set_route_active(self, active: bool) -> None:
        if self._closed or active is self._route_active:
            return
        self._route_active = active
        self._mount_generation = _next_mount_generation()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        self._chart_timer.stop()
        self._pending_chart_presentations.clear()
        if not active:
            return
        self._state = self._feature.snapshot(self._context)
        self._repair_local_selection()
        self._chart_frame_gate = EvidenceChartFrameGate(
            max_frames_per_second=20
        )
        self._chart_presentation = self._build_chart_presentation()
        self._chart_semantic_presentation = self._chart_presentation
        self._chart_frame_sequence += 1
        initial_gate = self._chart_frame_gate.offer(
            self._chart_presentation.frame,
            now_ns=self._chart_clock(),
        )
        if not initial_gate.committed:
            raise RuntimeError(
                "Reactivated Evidence chart presentation was not committed"
            )
        self._subscription = self._feature.subscribe(
            self._context,
            self._queue_state,
        )
        self.stateChanged.emit()
        self.localStateChanged.emit()
        self.chartPresentationChanged.emit()
        self.chartSemanticsChanged.emit()
        self.chartGeometryChanged.emit()
        self._sync_chart_interaction_enabled()

    def _repair_local_selection(self) -> None:
        data = self._state.last_reliable_data
        candidates = () if data is None else data.candidates
        candidate_ids = {item.identity.value for item in candidates}
        if self._selected_candidate not in candidate_ids:
            self._selected_candidate = (
                candidates[0].identity.value if candidates else ""
            )
        candidate = self._candidate()
        findings = () if candidate is None else candidate.findings
        finding_ids = {item.identity.value for item in findings}
        if self._selected_finding not in finding_ids:
            self._selected_finding = (
                findings[0].identity.value if findings else ""
            )
        chart = None if candidate is None else candidate.chart
        overlay_ids = (
            set() if chart is None else {item.identity for item in chart.overlays}
        )
        if self._selected_overlay not in overlay_ids:
            self._selected_overlay = (
                chart.overlays[0].identity
                if chart is not None and chart.overlays
                else ""
            )
        breakpoints = tuple(
            breakpoint
            for finding in findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        breakpoint_ids = {item.identity.value for item in breakpoints}
        if self._selected_breakpoint not in breakpoint_ids:
            self._selected_breakpoint = (
                breakpoints[0].identity.value if breakpoints else ""
            )
        if chart is None:
            self._selected_point_source_index = None

    def _candidate(self) -> CandidateEvidence | None:
        data = self._state.last_reliable_data
        if data is None:
            return None
        return next(
            (
                item
                for item in data.candidates
                if item.identity.value == self._selected_candidate
            ),
            None,
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def phase(self) -> str:
        return str(self._state.phase.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def completeness(self) -> str:
        return str(self._state.completeness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceText(self) -> str:  # noqa: N802
        return (
            f"{self._state.source.identity} · "
            f"g{self._state.source.generation.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        error = self._state.error
        details = (
            f"{self.freshness} · {self.phase} · {self.completeness}"
        )
        if error is not None:
            return f"{details} · {error.message}"
        return details

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def pinnedIdentitiesText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        selection = (
            data.selection
            if data is not None
            else self._state.context.selection
        )
        if selection is None:
            return "No Formal Diagnostic Campaign or Strategy Run selected."
        lines = [
                f"Campaign · {selection.campaign_id.value}",
                f"Run · {selection.run_id.value}",
                (
                    "Strategy Under Test · "
                    f"{_optional_identity(selection.strategy_id)}"
                ),
                (
                    "Market Scenario · "
                    f"{_optional_identity(selection.market_scenario_id)}"
                ),
                (
                    "Approved Scenario Recipe · "
                    f"{_optional_identity(selection.approved_recipe_id)}"
                ),
                (
                    "Reproduction Manifest · "
                    f"{_optional_identity(selection.reproduction_manifest_id)}"
                ),
        ]
        if data is not None:
            lines.append(
                "Diagnostic Evidence Package · "
                f"{data.evidence_package_id.value}"
            )
        return "\n".join(lines)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def hasReliableData(self) -> bool:  # noqa: N802
        return self._state.last_reliable_data is not None

    @Property("QVariantList", notify=localStateChanged)  # type: ignore[arg-type]
    def candidateIdentities(self) -> list[str]:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return []
        return [item.identity.value for item in data.candidates]

    @Property("QVariantList", notify=localStateChanged)  # type: ignore[arg-type]
    def findingIdentities(self) -> list[str]:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return []
        return [item.identity.value for item in candidate.findings]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def candidateSummaryText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return "No candidate evidence is available."
        return "  ·  ".join(
            f"{item.identity.value} — {item.label}" for item in data.candidates
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def curveCatalogText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        curves = (
            ()
            if data is None
            else tuple(
                curve
                for candidate in data.candidates
                for curve in candidate.curves
            )
        )
        if not curves:
            return (
                "No sealed sensitivity curves are available; typed textual "
                "evidence remains authoritative."
            )
        lines = []
        for curve in curves:
            axis = (
                (
                    f"{curve.axis.parameter_name} "
                    f"({curve.axis.value_type}, {curve.axis.order})"
                )
                if curve.axis is not None
                else "categorical"
            )
            points = ", ".join(
                (
                    f"case {point.case_id.value} / run {point.run_id.value} / "
                    f"metric {point.evidence_id.value} / manifest "
                    f"{point.reproduction_manifest_id.value} / artifact "
                    f"{point.run_artifact_hash} / parameters "
                    f"{', '.join(f'{name}={value}' for name, value in point.parameters)} "
                    f"/ value {point.value} {curve.unit}"
                )
                for point in curve.points
            )
            lines.append(

                    f"{curve.identity} · transformation "
                    f"{curve.transformation_family} / {curve.transformation_id} · "
                    f"strategy {curve.strategy_id.value}@{curve.strategy_version} · "
                    f"metric {curve.metric_name} / unit {curve.unit} · "
                    f"axis {axis} · {points}"

            )
        return "\n".join(lines)

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def selectedCandidateIdentity(self) -> str:  # noqa: N802
        return self._selected_candidate

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def selectedFindingIdentity(self) -> str:  # noqa: N802
        return self._selected_finding

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def evidenceFilter(self) -> str:  # noqa: N802
        return self._evidence_filter

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def sortOrder(self) -> str:  # noqa: N802
        return self._sort_order

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def activeTab(self) -> str:  # noqa: N802
        return self._active_tab

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def viewportIntent(self) -> str:  # noqa: N802
        return self._viewport_intent

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAcceptedRevision(self) -> int:  # noqa: N802
        return self._chart_presentation.frame.revision

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAcceptedRevisionText(self) -> str:  # noqa: N802
        return f"r{self.chartAcceptedRevision}"

    @Property(str, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartSourceIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.source_identity

    @Property(int, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartSourcePointCount(self) -> int:  # noqa: N802
        return self._chart_presentation.source_point_count

    @Property(int, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartVisiblePointCount(self) -> int:  # noqa: N802
        sample = self._chart_presentation.sample
        return 0 if sample is None else len(sample.points)

    @Property(int, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartOverlayCount(self) -> int:  # noqa: N802
        return len(self._chart_presentation.overlay_identities)

    @Property(str, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartSamplingPolicy(self) -> str:  # noqa: N802
        sample = self._chart_presentation.sample
        return (
            EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1.value
            if sample is None
            else sample.key.policy.value
        )

    @Property(str, notify=chartSemanticsChanged)  # type: ignore[arg-type]
    def chartNarrativeText(self) -> str:  # noqa: N802
        return self._chart_semantic_presentation.narrative_text

    @Property(str, notify=chartSemanticsChanged)  # type: ignore[arg-type]
    def chartTableText(self) -> str:  # noqa: N802
        return self._chart_semantic_presentation.table_text

    @Property(str, notify=chartSemanticsChanged)  # type: ignore[arg-type]
    def chartAccessibleText(self) -> str:  # noqa: N802
        return self._chart_semantic_presentation.accessible_text

    @Property("QVariantList", notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartOverlayIdentities(self) -> list[str]:  # noqa: N802
        return list(self._chart_presentation.overlay_identities)

    @Property("QVariantList", notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartOverlayModels(self) -> list[dict[str, object]]:  # noqa: N802
        frame = self._chart_presentation.frame
        return [
            {
                "identity": item.identity,
                "axis": item.axis.value,
                "position": item.normalized_coordinate,
                "selected": (
                    item.identity == frame.selected_overlay_identity
                ),
            }
            for item in frame.overlays
        ]

    @Property("QVariantList", notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartNormalizedPoints(self) -> list[QPointF]:  # noqa: N802
        sample = self._chart_presentation.sample
        if sample is None:
            return []
        return [
            QPointF(item.normalized_x, item.normalized_y)
            for item in sample.points
        ]

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartFrameSequence(self) -> int:  # noqa: N802
        return self._chart_frame_sequence

    @Property(bool, notify=chartInteractionChanged)  # type: ignore[arg-type]
    def chartInteractionEnabled(self) -> bool:  # noqa: N802
        return self._chart_interaction_enabled

    @Property("QVariantList", notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartBreakpointIdentities(self) -> list[str]:  # noqa: N802
        return list(self._chart_presentation.breakpoint_identities)

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartOverlayIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_overlay_identity

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartFindingIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_finding_identity

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartBreakpointIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_breakpoint_identity

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointIndex(self) -> int:  # noqa: N802
        selected = self._chart_presentation.selected_point_source_index
        return -1 if selected is None else selected

    @Property(float, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointX(self) -> float:  # noqa: N802
        selected = self._chart_presentation.frame.selected_point
        return -1.0 if selected is None else selected[0]

    @Property(float, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointY(self) -> float:  # noqa: N802
        selected = self._chart_presentation.frame.selected_point
        return -1.0 if selected is None else selected[1]

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def coverageText(self) -> str:  # noqa: N802
        return (
            "Baseline  ·  Isolated sensitivity  ·  Compound scenario  ·  "
            "Quick Experiment — exploratory only; does not satisfy formal coverage."
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def comparisonText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        data = self._state.last_reliable_data
        if data is None:
            return ""
        records = {
            item.identity: item
            for package_candidate in data.candidates
            for item in package_candidate.evidence
        }
        lines = [f"TYPED COMPARISONS · {candidate.identity.value}"]
        for comparison in candidate.comparisons:
            reference = records[comparison.reference_evidence_id]
            observed = records[comparison.observed_evidence_id]
            lines.extend(
                (
                    f"{comparison.identity.value} · {comparison.label}",
                    (
                        f"Reference {reference.identity.value} · "
                        f"{reference.value} {reference.unit} · "
                        f"Observed {observed.identity.value} · "
                        f"{observed.value} {observed.unit}"
                    ),
                )
            )
        return "\n".join(lines)

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def breakpointsText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        breakpoints = tuple(
            breakpoint
            for finding in candidate.findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        return "\n".join(
            (
                f"Sensitivity Breakpoint · {item.identity.value} · "
                f"{item.assumption_name} {item.threshold} · {item.outcome} · "
                f"evidence {', '.join(ref.value for ref in item.evidence_ids)}"
            )
            for item in breakpoints
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def assumptionsText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        return "\n".join(
            (
                f"{item.name} · requested {item.requested_value} · "
                f"effective {item.effective_value}"
                + (
                    f" · override {item.override_reason}"
                    if item.override_reason
                    else " · no override"
                )
            )
            for item in candidate.execution_assumptions
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def provenanceText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        provenance = candidate.provenance
        dependencies = ", ".join(
            f"{item.name} {item.version} {item.artifact_hash}"
            for item in provenance.dependencies
        )
        return "\n".join(
            (
                f"Artifact hashes · {', '.join(provenance.artifact_hashes)}",
                (
                    "Source runs · "
                    f"{', '.join(item.value for item in provenance.source_run_ids)}"
                ),
                f"Runner · {provenance.runner_version}",
                f"Build · {provenance.build_version}",
                f"Dependencies · {dependencies}",
            )
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def readOnlyContextText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        context = data.read_only_context
        orders = ", ".join(
            f"{item.identity} {item.status} ({item.diagnostic_note})"
            for item in context.orders
        )
        fills = ", ".join(
            (
                f"{item.identity} from {item.order_identity} · "
                f"{item.quantity} @ {item.price}"
            )
            for item in context.fills
        )
        return "\n".join(
            (
                "Orders and fills are read-only evidence traces.",
                f"Market · {', '.join(context.market)}",
                f"Account · {', '.join(context.account)}",
                f"Positions · {', '.join(context.positions)}",
                f"Orders · {orders}",
                f"Fills · {fills}",
            )
        )

    @Slot(str)
    def selectCandidate(self, identity: str) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or identity not in {
            item.identity.value for item in data.candidates
        }:
            return
        if identity == self._selected_candidate:
            return
        self._selected_candidate = identity
        self._selected_finding = ""
        self._repair_local_selection()
        self._publish_local_change()

    @Slot(str)
    def selectFinding(self, identity: str) -> None:  # noqa: N802
        candidate = self._candidate()
        if candidate is None or identity not in {
            item.identity.value for item in candidate.findings
        }:
            return
        if identity != self._selected_finding:
            self._selected_finding = identity
            self._publish_local_change()

    @Slot(float)
    def selectChartPointAtRatio(self, ratio: float) -> None:  # noqa: N802
        if not self._chart_interaction_enabled:
            return
        sample = self._chart_presentation.sample
        if sample is None or not sample.points:
            return
        bounded = max(0.0, min(float(ratio), 1.0))
        sample_index = round(bounded * (len(sample.points) - 1))
        source_index = sample.points[sample_index].source_index
        if source_index == self._selected_point_source_index:
            return
        self._selected_point_source_index = source_index
        self._publish_local_change()

    @Slot(int)
    def stepChartPoint(self, direction: int) -> None:  # noqa: N802
        if not self._chart_interaction_enabled:
            return
        sample = self._chart_presentation.sample
        if sample is None or not sample.points or direction == 0:
            return
        current_index = next(
            (
                index
                for index, point in enumerate(sample.points)
                if point.source_index == self._selected_point_source_index
            ),
            len(sample.points) - 1,
        )
        target_index = max(
            0,
            min(
                current_index + (1 if direction > 0 else -1),
                len(sample.points) - 1,
            ),
        )
        source_index = sample.points[target_index].source_index
        if source_index == self._selected_point_source_index:
            return
        self._selected_point_source_index = source_index
        self._publish_local_change()

    @Slot(str)
    def selectChartOverlay(self, identity: str) -> None:  # noqa: N802
        if (
            not self._chart_interaction_enabled
            or identity not in self._chart_presentation.overlay_identities
            or identity == self._selected_overlay
        ):
            return
        self._selected_overlay = identity
        self._publish_local_change()

    @Slot(str)
    def selectChartBreakpoint(self, identity: str) -> None:  # noqa: N802
        if (
            not self._chart_interaction_enabled
            or identity not in self._chart_presentation.breakpoint_identities
            or identity == self._selected_breakpoint
        ):
            return
        self._selected_breakpoint = identity
        self._publish_local_change()

    @Slot(str)
    def setEvidenceFilter(self, value: str) -> None:  # noqa: N802
        allowed = {"all"} | {item.value for item in EvidenceCoverage} | {
            item.value for item in EvidenceDimension
        }
        self._set_local("_evidence_filter", value, allowed)

    @Slot(str)
    def setSortOrder(self, value: str) -> None:  # noqa: N802
        self._set_local("_sort_order", value, {"dimension", "coverage"})

    @Slot(str)
    def setActiveTab(self, value: str) -> None:  # noqa: N802
        if (
            value
            not in {"findings", "assumptions", "provenance", "context"}
            or value == self._active_tab
        ):
            return
        self._active_tab = value
        self.localStateChanged.emit()

    @Slot(str)
    def setViewportIntent(self, value: str) -> None:  # noqa: N802
        self._set_local(
            "_viewport_intent",
            value,
            {"overview", "baseline", "sensitivity", "compound_stress"},
        )

    def _set_local(
        self,
        attribute: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if value not in allowed or getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self._publish_local_change()

    def _publish_local_change(self) -> None:
        self._offer_chart_presentation(
            self._build_chart_presentation(),
            local=True,
        )
        self.localStateChanged.emit()

    def _build_chart_presentation(self) -> EvidenceChartPresentation:
        return build_evidence_chart_presentation(
            self._state,
            self._candidate(),
            selected_finding_identity=self._selected_finding,
            viewport=_chart_viewport(self._viewport_intent),
            selected_point_source_index=self._selected_point_source_index,
            selected_overlay_identity=self._selected_overlay,
            selected_breakpoint_identity=self._selected_breakpoint,
            evidence_filter=self._evidence_filter,
            sort_order=self._sort_order,
        )

    def _offer_chart_presentation(
        self,
        presentation: EvidenceChartPresentation,
        *,
        local: bool,
    ) -> None:
        self._selected_point_source_index = (
            presentation.selected_point_source_index
        )
        self._selected_overlay = presentation.selected_overlay_identity
        self._selected_breakpoint = presentation.selected_breakpoint_identity
        self._pending_chart_presentations.append(presentation)
        now_ns = self._chart_clock()
        result = (
            self._chart_frame_gate.offer_local(
                presentation.frame,
                now_ns=now_ns,
            )
            if local
            else self._chart_frame_gate.offer_metadata(
                presentation.frame,
                now_ns=now_ns,
            )
            if (
                not self._pending_chart_presentations[:-1]
                and self._same_chart_paint_work(
                    self._chart_presentation,
                    presentation,
                )
            )
            else self._chart_frame_gate.offer(
                presentation.frame,
                now_ns=now_ns,
            )
        )
        if not result.accepted:
            self._pending_chart_presentations.pop()
        elif local:
            self._publish_chart_semantics(presentation)
        self._apply_chart_gate_result(result)

    def flush_chart_frames(self) -> None:
        self._apply_chart_gate_result(
            self._chart_frame_gate.flush(now_ns=self._chart_clock())
        )

    def _apply_chart_gate_result(
        self,
        result: EvidenceChartFrameGateResult,
    ) -> None:
        for frame in result.committed:
            presentation_index = self._matching_chart_presentation_index(
                frame
            )
            if presentation_index is None:
                continue
            presentation = self._pending_chart_presentations[
                presentation_index
            ]
            del self._pending_chart_presentations[: presentation_index + 1]
            previous = self._chart_presentation
            geometry_changed = (
                previous.source_identity != presentation.source_identity
                or previous.source_point_count
                != presentation.source_point_count
                or previous.frame.points != presentation.frame.points
                or previous.frame.overlays != presentation.frame.overlays
                or previous.selected_overlay_identity
                != presentation.selected_overlay_identity
            )
            self._chart_presentation = presentation
            self._publish_chart_semantics(presentation)
            self._chart_frame_sequence += 1
            if geometry_changed:
                self.chartGeometryChanged.emit()
            self.chartPresentationChanged.emit()
        due_in_ns = result.due_in_ns
        if due_in_ns is None:
            self._chart_timer.stop()
        else:
            self._chart_timer.start(max(1, ceil(due_in_ns / 1_000_000)))
        self._sync_chart_interaction_enabled()

    def _publish_chart_semantics(
        self,
        presentation: EvidenceChartPresentation,
    ) -> None:
        current = self._chart_semantic_presentation
        self._chart_semantic_presentation = presentation
        if (
            current.narrative_text == presentation.narrative_text
            and current.table_text == presentation.table_text
            and current.accessible_text == presentation.accessible_text
        ):
            return
        self.chartSemanticsChanged.emit()

    @staticmethod
    def _same_chart_paint_work(
        current: EvidenceChartPresentation,
        candidate: EvidenceChartPresentation,
    ) -> bool:
        return bool(
            current.source_identity == candidate.source_identity
            and current.source_point_count == candidate.source_point_count
            and current.frame.points == candidate.frame.points
            and current.frame.overlays == candidate.frame.overlays
            and current.frame.selected_point
            == candidate.frame.selected_point
            and current.frame.selected_overlay_identity
            == candidate.frame.selected_overlay_identity
            and current.frame.selected_finding_identity
            == candidate.frame.selected_finding_identity
            and current.frame.selected_breakpoint_identity
            == candidate.frame.selected_breakpoint_identity
        )

    def _sync_chart_interaction_enabled(self) -> None:
        sample = self._chart_presentation.sample
        enabled = bool(
            not self._pending_chart_presentations
            and sample is not None
            and sample.points
        )
        if enabled == self._chart_interaction_enabled:
            return
        self._chart_interaction_enabled = enabled
        self.chartInteractionChanged.emit()

    def _matching_chart_presentation_index(
        self,
        frame: EvidenceChartRenderFrame,
    ) -> int | None:
        for index in range(
            len(self._pending_chart_presentations) - 1,
            -1,
            -1,
        ):
            candidate = self._pending_chart_presentations[index].frame
            if (
                candidate.revision == frame.revision
                and candidate.points is frame.points
                and candidate.overlays is frame.overlays
                and candidate.selected_point
                == frame.selected_point
                and candidate.selected_overlay_identity
                == frame.selected_overlay_identity
                and candidate.selected_finding_identity
                == frame.selected_finding_identity
                and candidate.selected_breakpoint_identity
                == frame.selected_breakpoint_identity
            ):
                return index
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._route_active = False
        self._mount_generation = _next_mount_generation()
        self._chart_timer.stop()
        self._pending_chart_presentations.clear()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


def _title(value: EvidenceCoverage | EvidenceDimension) -> str:
    if value is EvidenceCoverage.QUICK_EXPERIMENT:
        return "Quick Experiment"
    return str(value.value).replace("_", " ").capitalize()


def _optional_identity(value: object | None) -> str:
    if value is None:
        return "Unavailable"
    return str(getattr(value, "value", "Unavailable"))


def _chart_viewport(intent: str) -> EvidenceChartViewport:
    viewports = {
        "overview": EvidenceChartViewport(0.0, 1.0),
        "baseline": EvidenceChartViewport(0.0, 0.25),
        "sensitivity": EvidenceChartViewport(0.25, 0.7),
        "compound_stress": EvidenceChartViewport(0.7, 1.0),
    }
    return viewports.get(intent, viewports["overview"])


class JourneyWorkspaceHost(QQuickWidget):
    """Exactly one route-level QML host mounted by the Widgets MainWindow."""

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
        strategy_library_feature: StrategyLibraryFeature | None = None,
        strategy_library_context: StrategyLibraryContext | None = None,
        strategy_library_bookmark_sink: (
            Callable[[StrategySelectionBookmark], None] | None
        ) = None,
        journey_workspace_bookmark: JourneyWorkspaceBookmark | None = None,
        journey_workspace_bookmark_sink: (
            Callable[[JourneyWorkspaceBookmark], None] | None
        ) = None,
        scenario_lab_feature: ScenarioLabFeature | None = None,
        scenario_lab_context: ScenarioLabContext | None = None,
        diagnostic_tasks_feature: DiagnosticTasksFeature | None = None,
        diagnostic_tasks_context: DiagnosticTasksContext | None = None,
        diagnostic_setup_selection_coordinator: (
            DiagnosticSetupSelectionCoordinator | None
        ) = None,
        evidence_feature: EvidenceAndFindingsFeature | None = None,
        evidence_context: EvidenceAndFindingsContext | None = None,
        accessibility_preferences: AccessibilityPreferences | None = None,
        parent: QWidget | None = None,
        initial_route: str = "diagnostic_tasks",
    ) -> None:
        super().__init__(parent)
        if initial_route not in {
            "strategy_library",
            "scenario_lab",
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        }:
            raise ValueError(
                f"Unsupported Journey Workspace route: {initial_route!r}"
            )
        initial_route_identity = JourneyWorkspaceRoute(initial_route)
        self._journey_workspace_bookmark = replace(
            journey_workspace_bookmark or JourneyWorkspaceBookmark(),
            last_route=initial_route_identity,
        )
        self._journey_workspace_bookmark_sink = (
            journey_workspace_bookmark_sink
        )
        self._active_route = initial_route_identity
        self.setObjectName("journeyWorkspaceHost")
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._workspace_closed = False
        self._accessibility_settings = AccessibilitySettingsQtAdapter(
            accessibility_preferences or detect_accessibility_preferences(),
            parent=self,
        )
        self.rootContext().setContextProperty(
            "accessibilitySettings",
            self._accessibility_settings,
        )
        self.rootContext().setContextProperty(
            "initialJourneyRoute",
            initial_route,
        )
        self._strategy_library = (
            StrategyLibraryQtAdapter(
                strategy_library_feature,
                context=strategy_library_context,
                bookmark_sink=strategy_library_bookmark_sink,
                parent=self,
            )
            if strategy_library_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "strategyLibrary",
            self._strategy_library,
        )
        self._scenario_lab = (
            ScenarioLabQtAdapter(
                scenario_lab_feature,
                context=scenario_lab_context,
                formal_strategy_selection_provider=(
                    (lambda: ())
                    if self._strategy_library is None
                    else self._strategy_library.current_formal_strategy_ids
                ),
                parent=self,
            )
            if scenario_lab_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "scenarioLab",
            self._scenario_lab,
        )
        if self._strategy_library is not None:
            self._strategy_library.refresh()
        if self._scenario_lab is not None:
            self._scenario_lab.refresh()
        if self._strategy_library is not None and self._scenario_lab is not None:
            self._strategy_library.stateChanged.connect(
                self._scenario_lab.stateChanged
            )
        if self._scenario_lab is not None:
            self._scenario_lab.stateChanged.connect(
                self._persist_journey_workspace_bookmark
            )
        self._diagnostic_tasks = (
            DiagnosticTasksQtAdapter(
                diagnostic_tasks_feature,
                context=diagnostic_tasks_context,
                setup_selection_provider=(
                    self._current_diagnostic_setup_selection
                    if self._strategy_library is not None
                    and self._scenario_lab is not None
                    else None
                ),
                setup_selection_refresh=(
                    self._refresh_diagnostic_setup_sources
                    if self._strategy_library is not None
                    and self._scenario_lab is not None
                    else None
                ),
                setup_selection_coordinator=(
                    diagnostic_setup_selection_coordinator
                ),
                parent=self,
            )
            if diagnostic_tasks_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "diagnosticTasks",
            self._diagnostic_tasks,
        )
        if self._diagnostic_tasks is not None:
            if self._strategy_library is not None:
                self._strategy_library.stateChanged.connect(
                    self._diagnostic_tasks.upstreamSelectionChanged
                )
            if self._scenario_lab is not None:
                self._scenario_lab.stateChanged.connect(
                    self._diagnostic_tasks.upstreamSelectionChanged
                )
        self._run_monitoring = RunMonitoringQtAdapter(
            feature,
            context=context,
            parent=self,
        )
        if self._diagnostic_tasks is not None:
            self._diagnostic_tasks.campaignContextReady.connect(
                self._select_run_monitoring_handoff
            )
            self._diagnostic_tasks.campaignHandoffReady.connect(
                self._open_run_monitoring_handoff
            )
            self._diagnostic_tasks.stateChanged.connect(
                self._persist_journey_workspace_bookmark
            )
        self.rootContext().setContextProperty(
            "runMonitoring",
            self._run_monitoring,
        )
        self._evidence_and_findings = (
            EvidenceAndFindingsQtAdapter(
                evidence_feature,
                context=evidence_context,
                parent=self,
            )
            if evidence_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "evidenceAndFindings",
            self._evidence_and_findings,
        )
        if (
            self._diagnostic_tasks is not None
            and self._evidence_and_findings is not None
        ):
            self._diagnostic_tasks.evidenceHandoffReady.connect(
                self._open_evidence_and_findings_handoff
            )
        self.setSource(QUrl.fromLocalFile(str(_QML_ROOT / "JourneyWorkspace.qml")))
        if self.status() == QQuickWidget.Status.Error:
            details = "; ".join(error.toString() for error in self.errors())
            raise RuntimeError(f"Failed to load Journey Workspace QML: {details}")
        root = self.rootObject()
        if root is not None:
            root.activeRouteChanged.connect(self._active_route_changed)
            self._active_route_changed()
        if self._diagnostic_tasks is not None:
            if (
                initial_route_identity
                is not JourneyWorkspaceRoute.DIAGNOSTIC_TASKS
            ):
                self._diagnostic_tasks.refresh()
            monitoring_context = self._diagnostic_tasks.monitoring_context()
            if monitoring_context is not None:
                self._run_monitoring.select_context(monitoring_context)
            evidence_context = self._diagnostic_tasks.evidence_context()
            if evidence_context is not None:
                if self._evidence_and_findings is not None:
                    self._evidence_and_findings.select_context(evidence_context)

    @Slot()
    def _active_route_changed(self) -> None:
        root = self.rootObject()
        if self._workspace_closed or root is None:
            return
        try:
            route = JourneyWorkspaceRoute(str(root.property("activeRoute")))
        except ValueError:
            return
        self._apply_route_activation(route)
        if route is self._active_route:
            return
        self._active_route = route
        self._persist_journey_workspace_bookmark()

    @Slot()
    def _persist_journey_workspace_bookmark(self) -> None:
        sink = self._journey_workspace_bookmark_sink
        if self._workspace_closed or sink is None:
            return
        scenario_context = (
            None
            if self._scenario_lab is None
            else self._scenario_lab.recovery_context()
        )
        task_id = self._journey_workspace_bookmark.diagnostic_task_id
        if self._diagnostic_tasks is not None:
            recovered_task_id = self._diagnostic_tasks.recovery_task_id()
            if recovered_task_id is not None:
                task_id = recovered_task_id
        candidate = JourneyWorkspaceBookmark(
            last_route=self._active_route,
            diagnostic_task_id=task_id,
            scenario_focus_target=(
                self._journey_workspace_bookmark.scenario_focus_target
                if scenario_context is None
                else scenario_context.focus_target
            ),
            scenario_focus_identity=(
                self._journey_workspace_bookmark.scenario_focus_identity
                if scenario_context is None
                else scenario_context.focus_identity
            ),
        )
        if candidate == self._journey_workspace_bookmark:
            return
        self._journey_workspace_bookmark = candidate
        sink(candidate)

    def _current_diagnostic_setup_selection(
        self,
    ) -> DiagnosticSetupSelectionContext | None:
        if self._strategy_library is None or self._scenario_lab is None:
            return None
        strategy = self._strategy_library.current_formal_strategy_selection()
        scenario = self._scenario_lab.current_diagnostic_selection()
        if strategy is None or scenario is None:
            return None
        try:
            return compose_diagnostic_setup_selection_context(strategy, scenario)
        except (KeyError, TypeError, ValueError):
            return None

    def _refresh_diagnostic_setup_sources(self) -> None:
        if self._strategy_library is not None:
            self._strategy_library.refresh()
        if self._scenario_lab is not None:
            self._scenario_lab.refresh()

    def _apply_route_activation(
        self,
        route: JourneyWorkspaceRoute,
    ) -> None:
        if self._strategy_library is not None:
            self._strategy_library.set_route_active(
                route is JourneyWorkspaceRoute.STRATEGY_LIBRARY
            )
        if self._scenario_lab is not None:
            self._scenario_lab.set_route_active(
                route is JourneyWorkspaceRoute.SCENARIO_LAB
            )
        if self._diagnostic_tasks is not None:
            self._diagnostic_tasks.set_route_active(
                route is JourneyWorkspaceRoute.DIAGNOSTIC_TASKS
            )
        self._run_monitoring.set_route_active(
            route is JourneyWorkspaceRoute.RUN_MONITORING
        )
        if self._evidence_and_findings is not None:
            self._evidence_and_findings.set_route_active(
                route is JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
            )

    @Slot(object)
    def _select_run_monitoring_handoff(
        self,
        context: RunMonitoringContext,
    ) -> None:
        if self._workspace_closed or not isinstance(context, RunMonitoringContext):
            return
        self._run_monitoring.select_context(context)

    @Slot(object)
    def _open_run_monitoring_handoff(
        self,
        context: RunMonitoringContext,
    ) -> None:
        if self._workspace_closed or not isinstance(context, RunMonitoringContext):
            return
        self._select_run_monitoring_handoff(context)
        root = self.rootObject()
        if root is not None:
            root.setProperty("activeRoute", "run_monitoring")

    @Slot(object)
    def _open_evidence_and_findings_handoff(
        self,
        context: EvidenceAndFindingsContext,
    ) -> None:
        if (
            self._workspace_closed
            or self._evidence_and_findings is None
            or not isinstance(context, EvidenceAndFindingsContext)
        ):
            return
        self._evidence_and_findings.select_context(context)

    def close_adapter(self, *, unload_qml: bool = True) -> None:
        if self._workspace_closed:
            return
        self._workspace_closed = True
        root = self.rootObject()
        if root is not None:
            try:
                root.activeRouteChanged.disconnect(self._active_route_changed)
            except (RuntimeError, TypeError):
                pass
        if self._strategy_library is not None:
            self._strategy_library.close()
        if self._scenario_lab is not None:
            self._scenario_lab.close()
        if self._diagnostic_tasks is not None:
            self._diagnostic_tasks.close()
        self._run_monitoring.close()
        if self._evidence_and_findings is not None:
            self._evidence_and_findings.close()
        if unload_qml:
            self.setSource(QUrl())


__all__ = [
    "DiagnosticTasksQtAdapter",
    "EvidenceAndFindingsQtAdapter",
    "JourneyWorkspaceHost",
    "RunMonitoringQtAdapter",
    "ScenarioLabQtAdapter",
    "StrategyLibraryQtAdapter",
]
