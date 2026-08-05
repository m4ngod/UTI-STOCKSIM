"""Headless application boundary for the Strategy Diagnostics Laboratory."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import cast
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .baostock_source import BaoStockHistoricalSource
from .diagnostic_evidence import (
    DiagnosticEvidenceArtifactStore,
    DiagnosticEvidenceBuilder,
    DiagnosticEvidencePackage,
    DiagnosticExplanationBundle,
    DiagnosticFindingExplanationProvider,
    GuardrailThreshold,
    StrategyGuardrailProfile,
)
from .diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
    SqlDiagnosticEvidenceRepository,
)
from .diagnostic_tasks import (
    ApproveDiagnosticTaskConfigurationRequest,
    ChangeDiagnosticLifecycleRequest,
    CreateDiagnosticTaskRequest,
    DiagnosticCampaignAttemptHandoffSnapshot,
    DiagnosticCampaignNodeHandoffSnapshot,
    DiagnosticCampaignRunHandoffSnapshot,
    DiagnosticEvidenceHandoffState,
    DiagnosticLifecycleOperation,
    DiagnosticLifecycleTargetKind,
    DiagnosticSelectionDependencyBinding,
    DiagnosticTaskCampaignHandoffSnapshot,
    DiagnosticTaskCommandResult,
    DiagnosticTaskConfiguration,
    DiagnosticTaskCreationResult,
    DiagnosticTaskLifecycle,
    DiagnosticTaskService,
    DiagnosticTaskSnapshot,
    DiagnosticTaskValidationFinding,
    DiagnosticTaskValidationReferenceKind,
    DiagnosticTaskValidationSeverity,
    RetryFailedCampaignNodeRequest,
    ReviseDiagnosticTaskConfigurationRequest,
    SqlDiagnosticTaskRepository,
    StartFormalDiagnosticCampaignRequest,
    ValidateDiagnosticTaskConfigurationRequest,
)
from .execution_conditions import (
    RequestedExecutionAssumptions,
    ResolvedExecutionConditions,
    resolve_execution_conditions,
)
from .formal_scenario_sets import (
    FormalScenarioSetRecord,
    ScenarioExecutionResolutionRecord,
    ScenarioExecutionResolutionState,
    ScenarioExecutionTargetResolutionRecord,
    ScenarioSelectionCaseBindingRecord,
    ScenarioSelectionContextRecord,
    ScenarioSelectionContextStatus,
    ScenarioSelectionStrategyBindingRecord,
    compose_formal_scenario_set,
    create_scenario_selection_context,
    scenario_execution_resolution_identity,
)
from .formal_diagnostic_campaigns import (
    CampaignCaseSpecification,
    CampaignTransformation,
    DiagnosticCampaignCase,
    DiagnosticCampaignExecutionLayer,
    DiagnosticCampaignRunner,
    DiagnosticCampaignSnapshot,
    DiagnosticCampaignSpecification,
    DiagnosticCampaignStrategySelection,
    SqlDiagnosticCampaignRepository,
)
from .historical_segments import (
    HistoricalMarketSegment,
    HistoricalSegmentAdmissionService,
    HistoricalSegmentRecommendation,
    HistoricalSegmentSelection,
    HistoricalSource,
    SegmentAdmissionReport,
)
from .isolated_sensitivity_sets import (
    ISOLATED_SENSITIVITY_FAMILIES,
    IsolatedSensitivitySetRunner,
    IsolatedSensitivitySetSnapshot,
    IsolatedSensitivitySetSpecification,
    SensitivityCampaignCase,
    SensitivitySweepDefinition,
    SqlIsolatedSensitivitySetRepository,
)
from .market_paths import (
    HistoricalMarketDataSource,
    MarketPathArtifactStore,
    MaterializedMarketPath,
    ParquetMarketPathArtifactStore,
    ScenarioMarketView,
    ScenarioMaterializer,
)
from .persistence import (
    DIAGNOSTIC_SCHEMA_REVISION,
    DiagnosticMigrationReport,
    SqlHistoricalSegmentCatalog,
    SqlScenarioRecipeRepository,
    initialize_diagnostic_persistence,
)
from .ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    EmbeddedProductionPTradeStrategyHost,
    PTradeStrategyHost,
    ptrade_manifest_for,
)
from .recipes import (
    AIRecipeAssistant,
    AIRecipeAuditRecord,
    AIRecipeAuthoringResult,
    ApprovedScenarioRecipeVersion,
    RecipeValidationResult,
    RecipeWorkbench,
    ScenarioRecipeDraft,
    ScenarioRecipeV1,
)
from .reproduction import (
    DIAGNOSTIC_CODE_IDENTITY,
    ReproductionManifest,
    ReproductionReport,
    ReproductionService,
)
from .reproduction_storage import SqlReproductionRepository
from .scenario_lab_authoring import (
    ScenarioLabAuthoringMode,
    ScenarioLabAuthoringResult,
    ScenarioLabAuthoringService,
    ScenarioLabProjectionCommandResult,
    ScenarioMaterializationResult,
    ScenarioMaterializationScheduler,
    ScenarioMaterializationTaskRecord,
    ScenarioRecipeApprovalRecord,
    ScenarioRecipeDraftRevisionRecord,
    ScenarioRecipeValidationDependencyRecord,
    ScenarioRecipeValidationRecord,
    SqlScenarioLabAuthoringRepository,
    canonical_json,
)
from .strategy_campaigns import (
    BASELINE_CAMPAIGN_COMMISSION_BPS,
    BASELINE_CAMPAIGN_SLIPPAGE_BPS,
    BaselineCampaignRunner,
    BaselineCampaignSnapshot,
    BaselineCampaignSpecification,
)
from .strategy_runs import (
    BASELINE_EXECUTION_POLICY_VERSION,
    REFERENCE_STRATEGY_ID,
    REFERENCE_STRATEGY_VERSION,
    STRATEGY_RUN_ENGINE_VERSION,
    CompletedStrategyRunEvidence,
    SqlStrategyRunRepository,
    StrategyRunEngine,
    StrategyRunSnapshot,
    StrategyRunSpecification,
)
from .strategy_inventory import (
    FormalStrategySelectionCandidate,
    FormalStrategySetValidation,
    StrategyUnderTestInventoryEntry,
    StrategyUnderTestInventory,
    build_strategy_under_test_inventory,
    validate_formal_strategy_set,
)
from .transformations import create_initial_transformation_catalog
from .v1_acceptance import (
    V1AcceptanceFacts,
    V1AcceptanceGate,
    V1AcceptanceReport,
    V1AcceptanceSubject,
    V1CadenceProof,
    V1ProductSurfaceInventory,
)


@dataclass(frozen=True, slots=True)
class DiagnosticsApplicationState:
    """User-visible state returned by the diagnostic application boundary."""

    product: str
    workspace: str
    status: str
    message: str
    persistence_status: str
    persistence_revision: str | None
    supported_persistence_revision: str

    def to_dict(self) -> dict[str, object]:
        return {
            "product": self.product,
            "workspace": self.workspace,
            "status": self.status,
            "message": self.message,
            "persistence_status": self.persistence_status,
            "persistence_revision": self.persistence_revision,
            "supported_persistence_revision": self.supported_persistence_revision,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCaseInventory:
    """One authoritative read of existing paths and their valid Campaign Cases."""

    admitted_segments: tuple["ScenarioLabAdmittedSegment", ...]
    materialized_paths: tuple[MaterializedMarketPath, ...]
    available_cases: tuple[DiagnosticCampaignCase, ...]
    path_assessments: tuple["ScenarioLabPathAssessment", ...]
    case_assessments: tuple["ScenarioLabCampaignCaseAssessment", ...]


class ScenarioLabIntegrityAssessment(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"


class ScenarioLabCompatibilityAssessment(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    NOT_YET_RESOLVED = "not_yet_resolved"
    UNAVAILABLE = "unavailable"


class ScenarioLabReproducibilityAssessment(str, Enum):
    REPRODUCIBLE = "reproducible"
    NONREPRODUCIBLE = "nonreproducible"
    NOT_YET_RESOLVED = "not_yet_resolved"
    UNAVAILABLE = "unavailable"


class ScenarioLabAdmissionAssessment(str, Enum):
    ADMITTED = "admitted"
    MISSING = "missing"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"


class ScenarioLabQualityAssessment(str, Enum):
    PASSED = "passed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ScenarioLabInventoryReasonCode(str, Enum):
    SOURCE_INCOMPLETE = "scenario_lab_source_incomplete"
    PATH_INTEGRITY_FAILED = "reference_path_integrity_failed"
    PATH_RECIPE_INCOMPATIBLE = "reference_path_recipe_incompatible"
    PATH_PROVENANCE_INCOMPLETE = "reference_path_provenance_incomplete"
    NONBASELINE_WITHOUT_BASELINE = "nonbaseline_without_baseline"


@dataclass(frozen=True, slots=True)
class ScenarioLabInventoryReason:
    code: ScenarioLabInventoryReasonCode
    summary: str
    corrective_guidance: str


@dataclass(frozen=True, slots=True)
class ScenarioLabAdmittedSegment:
    segment: HistoricalMarketSegment
    source_snapshot_content_hash: str
    admission_state: ScenarioLabAdmissionAssessment
    quality_state: ScenarioLabQualityAssessment
    unavailability_reasons: tuple[ScenarioLabInventoryReason, ...]


@dataclass(frozen=True, slots=True)
class ScenarioLabPathAssessment:
    path_identity: str
    integrity: ScenarioLabIntegrityAssessment
    compatibility: ScenarioLabCompatibilityAssessment
    reproducibility: ScenarioLabReproducibilityAssessment
    reasons: tuple[ScenarioLabInventoryReason, ...]


@dataclass(frozen=True, slots=True)
class ScenarioLabCampaignCaseAssessment:
    campaign_case_identity: str
    compatibility: ScenarioLabCompatibilityAssessment
    reproducibility: ScenarioLabReproducibilityAssessment
    reasons: tuple[ScenarioLabInventoryReason, ...]


class DiagnosticsApplication:
    """Small product interface shared by headless and presentation adapters."""

    def __init__(
        self,
        historical_source: HistoricalSource | None = None,
        market_data_source: HistoricalMarketDataSource | None = None,
        artifact_store: MarketPathArtifactStore | None = None,
        recipe_assistant: AIRecipeAssistant | None = None,
        recipe_clock: Callable[[], datetime] | None = None,
        materialization_scheduler: ScenarioMaterializationScheduler | None = None,
        diagnostic_task_clock: Callable[[], datetime] | None = None,
        ptrade_host: PTradeStrategyHost | None = None,
        evidence_artifact_store: DiagnosticEvidenceArtifactStore | None = None,
        finding_explanation_provider: (
            DiagnosticFindingExplanationProvider | None
        ) = None,
    ) -> None:
        self._state: DiagnosticsApplicationState | None = None
        source = historical_source or BaoStockHistoricalSource()
        self._transformation_catalog = create_initial_transformation_catalog()
        self._historical_segments = HistoricalSegmentAdmissionService(
            source=source
        )
        candidate_market_source = market_data_source
        if candidate_market_source is None and callable(
            getattr(source, "load_scenario_data_world", None)
        ):
            candidate_market_source = cast(HistoricalMarketDataSource, source)
        self._scenario_materializer = (
            ScenarioMaterializer(
                source=candidate_market_source,
                artifact_store=(
                    artifact_store
                    or ParquetMarketPathArtifactStore.from_environment()
                ),
                transformation_catalog=self._transformation_catalog,
            )
            if candidate_market_source is not None
            else None
        )
        self._recipe_workbench = RecipeWorkbench(
            clock=recipe_clock,
            transformation_catalog=self._transformation_catalog,
        )
        self._scenario_lab_authoring = ScenarioLabAuthoringService(
            recipe_workbench=self._recipe_workbench,
            admitted_segments=self._historical_segments.list_segments,
            dependency_provider=self._scenario_recipe_validation_dependencies,
            materialize_reference_path=lambda version_id: (
                self.materialize_reference_path(version_id).artifact_hash
            ),
            materialization_scheduler=materialization_scheduler,
            clock=recipe_clock,
        )
        self._observed_diagnostic_setup_binding: (
            DiagnosticSelectionDependencyBinding | None
        ) = None
        self._diagnostic_setup_observation_initialized = False
        self._diagnostic_tasks = DiagnosticTaskService(
            clock=diagnostic_task_clock,
            configuration_validator=(
                self._is_authoritative_diagnostic_task_configuration
            ),
            configuration_validation=(
                self._validate_diagnostic_task_configuration
            ),
            validation_policy_provider=(
                self._diagnostic_task_validation_policy_identities
            ),
            dependency_binding_provider=(
                self._diagnostic_selection_dependency_binding
            ),
        )
        self._recipe_assistant = recipe_assistant
        self._strategy_runs = StrategyRunEngine(
            self._load_reference_path,
            ptrade_host=ptrade_host or EmbeddedProductionPTradeStrategyHost(),
        )
        self._isolated_sensitivity_sets = IsolatedSensitivitySetRunner(
            self._execute_isolated_sensitivity_case
        )
        self._diagnostic_campaigns = DiagnosticCampaignRunner(
            self._execute_diagnostic_campaign_case
        )
        self._evidence_artifact_store = (
            evidence_artifact_store
            or JsonDiagnosticEvidenceArtifactStore.from_environment()
        )
        self._diagnostic_evidence = DiagnosticEvidenceBuilder(
            self._diagnostic_campaigns.get,
            self._load_verified_reference_path,
            self._evidence_artifact_store,
        )
        self._reproduction = ReproductionService(
            run_loader=self._strategy_runs.get,
            recipe_hash_loader=lambda version_id: (
                self._recipe_workbench.get_version(version_id).content_hash
            ),
            path_loader=self._load_verified_reference_path,
            evidence_loader=self._diagnostic_evidence.get,
            source_snapshot_loader=(
                self._historical_segments.get_source_snapshot
            ),
            replay_run=self._strategy_runs.reproduce,
            code_identity=DIAGNOSTIC_CODE_IDENTITY,
        )
        self._finding_explanation_provider = finding_explanation_provider

    def start(self) -> DiagnosticsApplicationState:
        if self._state is None:
            self._state = DiagnosticsApplicationState(
                product="Strategy Diagnostics Laboratory",
                workspace="Diagnostics",
                status="ready",
                message="Diagnostics workspace is ready.",
                persistence_status="not_initialized",
                persistence_revision=None,
                supported_persistence_revision=DIAGNOSTIC_SCHEMA_REVISION,
            )
        return self._state

    def initialize_persistence(self, engine: Engine) -> DiagnosticMigrationReport:
        report = initialize_diagnostic_persistence(engine)
        self._historical_segments.replace_catalog(SqlHistoricalSegmentCatalog(engine))
        recipe_repository = SqlScenarioRecipeRepository(engine)
        self._recipe_workbench.replace_repository(recipe_repository)
        self._scenario_lab_authoring.replace_repository(
            SqlScenarioLabAuthoringRepository(
                engine,
                self._recipe_workbench,
            )
        )
        self._strategy_runs.replace_repository(SqlStrategyRunRepository(engine))
        self._isolated_sensitivity_sets.replace_repository(
            SqlIsolatedSensitivitySetRepository(engine)
        )
        self._diagnostic_campaigns.replace_repository(
            SqlDiagnosticCampaignRepository(engine)
        )
        self._diagnostic_tasks.replace_repository(
            SqlDiagnosticTaskRepository(engine)
        )
        self._diagnostic_evidence.replace_repository(
            SqlDiagnosticEvidenceRepository(
                engine,
                self._evidence_artifact_store,
            )
        )
        self._reproduction.replace_repository(
            SqlReproductionRepository(engine)
        )
        state = self.start()
        self._state = replace(
            state,
            persistence_status="ready",
            persistence_revision=report.current_revision,
        )
        for start_request in self._diagnostic_tasks.pending_start_requests():
            self.start_formal_diagnostic_task_campaign(start_request)
        for retry_request in self._diagnostic_tasks.pending_retry_requests():
            self.retry_failed_diagnostic_campaign_node(retry_request)
        for lifecycle_request in (
            self._diagnostic_tasks.pending_lifecycle_requests()
        ):
            self._change_diagnostic_lifecycle(lifecycle_request)
        return report

    def status(self) -> DiagnosticsApplicationState:
        if self._state is None:
            raise RuntimeError("Diagnostics application has not been started")
        return self._state

    def admit_historical_segment(
        self, selection: HistoricalSegmentSelection
    ) -> SegmentAdmissionReport:
        self.status()
        return self._historical_segments.admit(selection)

    def list_historical_segments(self) -> tuple[HistoricalMarketSegment, ...]:
        self.status()
        return cast(
            tuple[HistoricalMarketSegment, ...],
            self._historical_segments.list_segments(),
        )

    def list_approved_scenario_recipes(
        self,
    ) -> tuple[ApprovedScenarioRecipeVersion, ...]:
        """Enumerate immutable approved recipe versions for typed consumers."""

        self.status()
        return cast(
            tuple[ApprovedScenarioRecipeVersion, ...],
            self._recipe_workbench.list_approved_versions(),
        )

    def list_materialized_market_paths(
        self,
    ) -> tuple[MaterializedMarketPath, ...]:
        """Enumerate existing paths without materializing new diagnostic work."""

        self.status()
        if self._scenario_materializer is None:
            return ()
        return cast(
            tuple[MaterializedMarketPath, ...],
            self._scenario_materializer.list_materialized_paths(),
        )

    def list_available_diagnostic_campaign_cases(
        self,
    ) -> tuple[DiagnosticCampaignCase, ...]:
        """Enumerate valid existing recipe/path anchors without creating paths."""

        self.status()
        return self._diagnostic_campaign_cases_for_paths(
            self.list_materialized_market_paths()
        )

    def _active_formal_scenario_authority_cases(
        self,
        cases: tuple[DiagnosticCampaignCase, ...],
    ) -> tuple[DiagnosticCampaignCase, ...]:
        """Collapse immutable Recipe history to each lineage's active version."""

        latest_by_recipe: dict[str, ApprovedScenarioRecipeVersion] = {}
        for version in self._recipe_workbench.list_approved_versions():
            predecessor = latest_by_recipe.get(version.recipe_id)
            if (
                predecessor is None
                or version.version_number > predecessor.version_number
            ):
                latest_by_recipe[version.recipe_id] = version
        active_version_ids = {
            item.version_id for item in latest_by_recipe.values()
        }
        return tuple(
            item
            for item in cases
            if item.recipe_version_id in active_version_ids
        )

    def read_diagnostic_campaign_case_inventory(
        self,
    ) -> DiagnosticCampaignCaseInventory:
        """Read paths once and derive their valid Campaign Cases coherently."""

        self.status()
        admitted_segments = tuple(
            ScenarioLabAdmittedSegment(
                segment=segment,
                source_snapshot_content_hash=(
                    self._historical_segments.get_source_snapshot(
                        segment.source_snapshot_id
                    ).content_hash
                ),
                admission_state=ScenarioLabAdmissionAssessment.ADMITTED,
                quality_state=ScenarioLabQualityAssessment.PASSED,
                unavailability_reasons=(),
            )
            for segment in self._historical_segments.list_segments()
        )
        paths = self.list_materialized_market_paths()
        approved_versions = self._recipe_workbench.list_approved_versions()
        cases = self._diagnostic_campaign_cases_for_paths(paths)
        path_assessments = tuple(
            self._scenario_lab_path_assessment(
                path,
                available_cases=cases,
                has_approved_recipes=bool(approved_versions),
            )
            for path in paths
        )
        assessment_by_path = {
            item.path_identity: item for item in path_assessments
        }
        return DiagnosticCampaignCaseInventory(
            admitted_segments=admitted_segments,
            materialized_paths=paths,
            available_cases=cases,
            path_assessments=path_assessments,
            case_assessments=self._scenario_lab_case_assessments(
                cases,
                assessment_by_path=assessment_by_path,
            ),
        )

    def _scenario_lab_path_assessment(
        self,
        path: MaterializedMarketPath,
        *,
        available_cases: tuple[DiagnosticCampaignCase, ...],
        has_approved_recipes: bool,
    ) -> ScenarioLabPathAssessment:
        try:
            verified = self._load_verified_reference_path(path.artifact_hash)
        except (IndexError, KeyError, OSError, TypeError, UnicodeError, ValueError):
            return ScenarioLabPathAssessment(
                path_identity=path.artifact_hash,
                integrity=ScenarioLabIntegrityAssessment.FAILED,
                compatibility=ScenarioLabCompatibilityAssessment.UNAVAILABLE,
                reproducibility=ScenarioLabReproducibilityAssessment.UNAVAILABLE,
                reasons=(
                    ScenarioLabInventoryReason(
                        code=ScenarioLabInventoryReasonCode.PATH_INTEGRITY_FAILED,
                        summary=(
                            "The immutable Reference Market Path failed backend "
                            "integrity verification."
                        ),
                        corrective_guidance=(
                            "Re-materialize from an Approved Scenario Recipe and "
                            "verify the persisted artifact hash."
                        ),
                    ),
                ),
            )
        path_cases = tuple(
            case
            for case in available_cases
            if case.materialization_hash == path.artifact_hash
        )
        compatibility = (
            ScenarioLabCompatibilityAssessment.COMPATIBLE
            if path_cases
            else ScenarioLabCompatibilityAssessment.INCOMPATIBLE
            if has_approved_recipes
            else ScenarioLabCompatibilityAssessment.NOT_YET_RESOLVED
        )
        required_provenance = (
            verified.segment_id,
            verified.segment_content_hash,
            verified.source_snapshot_id,
            verified.expander_version,
            verified.source_resolution,
            verified.runtime_resolution,
            verified.numeric_tolerance,
            verified.normalization_provenance,
            verified.market_rule_profile_version,
            verified.transformation_catalog_version,
        )
        reproducible = bool(verified.nodes) and all(
            value.strip() for value in required_provenance
        )
        reasons: list[ScenarioLabInventoryReason] = []
        if compatibility is ScenarioLabCompatibilityAssessment.INCOMPATIBLE:
            reasons.append(
                ScenarioLabInventoryReason(
                    code=ScenarioLabInventoryReasonCode.PATH_RECIPE_INCOMPATIBLE,
                    summary="No Approved Scenario Recipe is compatible with this path.",
                    corrective_guidance=(
                        "Select or approve a Recipe whose exact segment, seed, "
                        "transformation, and market-rule bindings match this path."
                    ),
                )
            )
        elif compatibility is ScenarioLabCompatibilityAssessment.NOT_YET_RESOLVED:
            reasons.append(
                ScenarioLabInventoryReason(
                    code=ScenarioLabInventoryReasonCode.PATH_RECIPE_INCOMPATIBLE,
                    summary=(
                        "Compatibility is unresolved until an Approved Recipe exists."
                    ),
                    corrective_guidance=(
                        "Approve a Scenario Recipe before using this path in a "
                        "Formal Scenario Set."
                    ),
                )
            )
        if not reproducible:
            reasons.append(
                ScenarioLabInventoryReason(
                    code=ScenarioLabInventoryReasonCode.PATH_PROVENANCE_INCOMPLETE,
                    summary="Required deterministic path provenance is incomplete.",
                    corrective_guidance=(
                        "Restore the exact source snapshot, expander, resolution, "
                        "catalog, and market-rule provenance before reuse."
                    ),
                )
            )
        return ScenarioLabPathAssessment(
            path_identity=path.artifact_hash,
            integrity=ScenarioLabIntegrityAssessment.VERIFIED,
            compatibility=compatibility,
            reproducibility=(
                ScenarioLabReproducibilityAssessment.REPRODUCIBLE
                if reproducible
                else ScenarioLabReproducibilityAssessment.NONREPRODUCIBLE
            ),
            reasons=tuple(reasons),
        )

    @staticmethod
    def _scenario_lab_case_assessments(
        cases: tuple[DiagnosticCampaignCase, ...],
        *,
        assessment_by_path: Mapping[str, ScenarioLabPathAssessment],
    ) -> tuple[ScenarioLabCampaignCaseAssessment, ...]:
        baselines = {
            (
                case.historical_segment_id,
                case.historical_segment_content_hash,
                case.source_snapshot_id,
                case.materialization_seed,
            )
            for case in cases
            if case.layer == "baseline"
        }
        assessments: list[ScenarioLabCampaignCaseAssessment] = []
        for case in cases:
            path_assessment = assessment_by_path[case.materialization_hash]
            comparison_key = (
                case.historical_segment_id,
                case.historical_segment_content_hash,
                case.source_snapshot_id,
                case.materialization_seed,
            )
            comparison_valid = (
                case.layer == "baseline" or comparison_key in baselines
            )
            compatibility = (
                path_assessment.compatibility
                if comparison_valid
                else ScenarioLabCompatibilityAssessment.INCOMPATIBLE
            )
            reasons = list(path_assessment.reasons)
            if not comparison_valid:
                reasons.append(
                    ScenarioLabInventoryReason(
                        code=(
                            ScenarioLabInventoryReasonCode.NONBASELINE_WITHOUT_BASELINE
                        ),
                        summary=(
                            "The nonbaseline Campaign Case has no compatible baseline."
                        ),
                        corrective_guidance=(
                            "Materialize the exact baseline Recipe for the same "
                            "segment, source snapshot, and seed."
                        ),
                    )
                )
            assessments.append(
                ScenarioLabCampaignCaseAssessment(
                    campaign_case_identity=case.case_id,
                    compatibility=compatibility,
                    reproducibility=path_assessment.reproducibility,
                    reasons=tuple(reasons),
                )
            )
        return tuple(assessments)

    def _diagnostic_campaign_cases_for_paths(
        self,
        paths: Sequence[MaterializedMarketPath],
    ) -> tuple[DiagnosticCampaignCase, ...]:
        cases: list[DiagnosticCampaignCase] = []
        for approved in self._recipe_workbench.list_approved_versions():
            for path in paths:
                try:
                    cases.append(
                        self._diagnostic_campaign_case_from_existing_path(
                            approved,
                            path,
                        )
                    )
                except ValueError:
                    continue
        return tuple(sorted(cases, key=lambda item: item.case_id))

    def create_diagnostic_task(
        self,
        request: CreateDiagnosticTaskRequest,
    ) -> DiagnosticTaskCreationResult:
        """Create one durable task without validating or starting a Campaign."""

        self.status()
        binding = request.dependency_binding
        if binding is not None:
            self._observe_diagnostic_setup_dependency_binding(binding)
        return self._diagnostic_tasks.create(
            request,
            dependency_binding=binding,
        )

    def _observe_diagnostic_setup_dependency_binding(
        self,
        binding: DiagnosticSelectionDependencyBinding | None,
    ) -> None:
        """Record the current UI selection for authoritative reconciliation."""

        self._observed_diagnostic_setup_binding = binding
        self._diagnostic_setup_observation_initialized = True

    def get_diagnostic_task(
        self,
        task_id: str | None = None,
        *,
        dependency_binding: DiagnosticSelectionDependencyBinding | None = None,
        dependency_binding_observed: bool = False,
    ) -> DiagnosticTaskSnapshot | None:
        """Read a durable task by identity, or the latest workspace task."""

        self.status()
        if dependency_binding_observed:
            self._observe_diagnostic_setup_dependency_binding(
                dependency_binding
            )
        if task_id is None:
            return self._diagnostic_tasks.latest()
        return self._diagnostic_tasks.get(task_id)

    def revise_diagnostic_task_configuration(
        self,
        request: ReviseDiagnosticTaskConfigurationRequest,
    ) -> DiagnosticTaskCommandResult:
        """Correct one exact durable task revision without starting work."""

        self.status()
        binding = request.dependency_binding
        if binding is not None:
            self._observe_diagnostic_setup_dependency_binding(binding)
        return self._diagnostic_tasks.revise_configuration(
            request,
            dependency_binding=binding,
        )

    def validate_diagnostic_task_configuration(
        self,
        request: ValidateDiagnosticTaskConfigurationRequest,
    ) -> DiagnosticTaskCommandResult:
        """Validate one exact task revision against authoritative inputs."""

        self.status()
        if request.dependency_binding_observed:
            self._observe_diagnostic_setup_dependency_binding(
                request.dependency_binding
            )
        return self._diagnostic_tasks.validate_configuration(request)

    def approve_diagnostic_task_configuration(
        self,
        request: ApproveDiagnosticTaskConfigurationRequest,
    ) -> DiagnosticTaskCommandResult:
        """Approve only the exact current successfully validated revision."""

        self.status()
        if request.dependency_binding_observed:
            self._observe_diagnostic_setup_dependency_binding(
                request.dependency_binding
            )
        return self._diagnostic_tasks.approve_configuration(request)

    def start_formal_diagnostic_task_campaign(
        self,
        request: StartFormalDiagnosticCampaignRequest,
    ) -> DiagnosticTaskCommandResult:
        """Start the exact approved task as one real Formal Campaign."""

        self.status()
        if request.dependency_binding_observed:
            self._observe_diagnostic_setup_dependency_binding(
                request.dependency_binding
            )
        preflight = self._diagnostic_tasks.preflight_start(request)
        if isinstance(preflight, DiagnosticTaskCreationResult):
            if (
                preflight.disposition.value != "idempotent_replay"
                or preflight.affected_campaign_id is not None
            ):
                return preflight
            task = self._diagnostic_tasks.get(request.task_id)
            if task is None:
                return self._diagnostic_tasks.reject_start_unavailable(
                    request,
                    message="The accepted Diagnostic Task is unavailable.",
                    retryable=True,
                )
            accepted = preflight
        else:
            task = preflight
            accepted = None
        try:
            specification = self._formal_campaign_specification_for_task(
                task,
                request.approved_revision,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return self._diagnostic_tasks.reject_start_unavailable(
                request,
                message=(
                    "The exact approved Campaign Cases cannot form an "
                    "authoritative Formal Diagnostic Campaign."
                ),
            )
        if accepted is None:
            accepted = self._diagnostic_tasks.accept_start(request)
            if accepted.disposition.value not in {
                "asynchronous_acceptance",
                "idempotent_replay",
            }:
                return accepted
            if accepted.affected_campaign_id is not None:
                return accepted
        isolated = specification.isolated_sensitivity_set
        if isolated is None:
            return self._diagnostic_tasks.reject_start_unavailable(
                request,
                message=(
                    "A Formal Diagnostic Campaign requires its isolated "
                    "sensitivity layer."
                ),
            )
        handle = accepted.task_handle
        if handle is None:
            return self._diagnostic_tasks.reject_start_unavailable(
                request,
                message=(
                    "Accepted Campaign start requires a persistent TaskHandle."
                ),
                retryable=True,
            )
        continuation_claim_id = uuid4().hex
        try:
            claimed = self._diagnostic_tasks.claim_start_continuation(
                handle.task_handle_id,
                continuation_claim_id,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            claimed = False
        if not claimed:
            return replace(
                accepted,
                message=(
                    "Formal Diagnostic Campaign start accepted; another "
                    "authoritative continuation owns this TaskHandle."
                ),
                affected_campaign_id=specification.campaign_id,
            )
        try:
            self._isolated_sensitivity_sets.plan(isolated)
            campaign = self._diagnostic_campaigns.plan(specification)
            if not any(case.attempts for case in campaign.cases):
                campaign = self._diagnostic_campaigns.advance(
                    campaign.campaign_id,
                    max_cases=1,
                )
            handoff = self._diagnostic_task_campaign_handoff(
                task,
                campaign,
            )
            self._diagnostic_tasks.complete_start(
                handle.task_handle_id,
                continuation_claim_id,
                handoff,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            try:
                self._diagnostic_tasks.release_start_continuation(
                    handle.task_handle_id,
                    continuation_claim_id,
                )
            except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
                pass
            # The queued acceptance remains durable and safe to retry. Planning
            # identities are deterministic, so a lost response cannot create a
            # second Campaign.
            return replace(
                accepted,
                message=(
                    "Formal Diagnostic Campaign start accepted; authoritative "
                    "continuation remains queued."
                ),
                affected_campaign_id=specification.campaign_id,
            )
        return replace(
            accepted,
            affected_campaign_id=campaign.campaign_id,
        )

    def pause_diagnostic_target(
        self,
        request: ChangeDiagnosticLifecycleRequest,
    ) -> DiagnosticTaskCommandResult:
        """Pause one exact non-order Diagnostic Task lifecycle target."""

        if request.operation is not DiagnosticLifecycleOperation.PAUSE:
            raise ValueError("Pause requires an explicit pause operation")
        return self._change_diagnostic_lifecycle(request)

    def resume_diagnostic_target(
        self,
        request: ChangeDiagnosticLifecycleRequest,
    ) -> DiagnosticTaskCommandResult:
        """Resume one exact non-order Diagnostic Task lifecycle target."""

        if request.operation is not DiagnosticLifecycleOperation.RESUME:
            raise ValueError("Resume requires an explicit resume operation")
        return self._change_diagnostic_lifecycle(request)

    def cancel_diagnostic_target(
        self,
        request: ChangeDiagnosticLifecycleRequest,
    ) -> DiagnosticTaskCommandResult:
        """Cancel one exact non-order Diagnostic Task lifecycle target."""

        if request.operation is not DiagnosticLifecycleOperation.CANCEL:
            raise ValueError("Cancel requires an explicit cancel operation")
        return self._change_diagnostic_lifecycle(request)

    def retry_failed_diagnostic_campaign_node(
        self,
        request: RetryFailedCampaignNodeRequest,
    ) -> DiagnosticTaskCommandResult:
        """Retry one exact failed node as a durable new Campaign attempt."""

        self.status()
        accepted = self._diagnostic_tasks.retry_failed_campaign_node(request)
        if accepted.disposition.value not in {
            "asynchronous_acceptance",
            "idempotent_replay",
        }:
            return accepted
        handle = accepted.task_handle
        if handle is None:
            return accepted
        if handle.phase.value != "queued":
            return accepted
        task = self._diagnostic_tasks.get(request.task_id)
        if task is None or task.campaign_handoff is None:
            return replace(
                accepted,
                message=(
                    "Failed-node retry accepted; authoritative task reread "
                    "remains queued."
                ),
            )
        node = next(
            (
                candidate
                for candidate in task.campaign_handoff.campaign_nodes
                if candidate.campaign_node_id == request.campaign_node_id
            ),
            None,
        )
        attempt = (
            None
            if node is None
            else next(
                (
                    candidate
                    for candidate in node.attempts
                    if candidate.task_handle_id == handle.task_handle_id
                ),
                None,
            )
        )
        if node is None or attempt is None:
            return replace(
                accepted,
                message=(
                    "Failed-node retry accepted; persistent attempt binding "
                    "remains queued."
                ),
            )
        continuation_claim_id = uuid4().hex
        try:
            claimed = self._diagnostic_tasks.claim_start_continuation(
                handle.task_handle_id,
                continuation_claim_id,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            claimed = False
        if not claimed:
            return replace(
                accepted,
                message=(
                    "Failed-node retry accepted; another authoritative "
                    "continuation owns this TaskHandle."
                ),
            )
        try:
            campaign = self._diagnostic_campaigns.get(
                task.campaign_handoff.campaign_id
            )
            case = next(
                (
                    candidate
                    for candidate in campaign.cases
                    if candidate.case_id == node.campaign_case_id
                ),
                None,
            )
            if case is None:
                raise ValueError("Formal Diagnostic Campaign Case is unavailable")
            if len(case.attempts) == attempt.attempt_number - 1:
                campaign = self._diagnostic_campaigns.retry_case(
                    campaign.campaign_id,
                    case.case_id,
                )
            elif len(case.attempts) == attempt.attempt_number:
                if (
                    case.attempts[-1].attempt_number
                    != attempt.attempt_number
                ):
                    raise ValueError(
                        "Formal Diagnostic Campaign attempt history is not "
                        "contiguous"
                    )
            else:
                raise ValueError(
                    "Formal Diagnostic Campaign attempt history conflicts "
                    "with accepted retry"
                )
            handoff = self._diagnostic_task_campaign_handoff(task, campaign)
            self._diagnostic_tasks.complete_failed_node_retry(
                handle.task_handle_id,
                continuation_claim_id,
                handoff,
            )
            if campaign.status == "completed":
                self._seal_linked_diagnostic_task_evidence(campaign)
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            try:
                self._diagnostic_tasks.release_start_continuation(
                    handle.task_handle_id,
                    continuation_claim_id,
                )
            except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
                pass
            return replace(
                accepted,
                message=(
                    "Failed-node retry accepted; authoritative continuation "
                    "remains queued."
                ),
            )
        return accepted

    def _change_diagnostic_lifecycle(
        self,
        request: ChangeDiagnosticLifecycleRequest,
    ) -> DiagnosticTaskCommandResult:
        self.status()
        return self._diagnostic_tasks.change_lifecycle(request)

    def _formal_campaign_specification_for_task(
        self,
        task: DiagnosticTaskSnapshot,
        approved_revision: int,
    ) -> DiagnosticCampaignSpecification:
        baseline: DiagnosticCampaignCase | None = None
        isolated_by_family: dict[str, list[SensitivityCampaignCase]] = {
            family: [] for family in ISOLATED_SENSITIVITY_FAMILIES
        }
        compounds: list[DiagnosticCampaignCase] = []
        for selection in task.configuration.campaign_case_selections:
            anchor = (
                selection.recipe_version_id,
                selection.market_scenario_id,
            )
            selected_case = self.create_diagnostic_campaign_case(*anchor)
            if (
                selected_case.case_id != selection.campaign_case_id
                or selected_case.recipe_content_hash
                != selection.recipe_content_hash
            ):
                raise ValueError(
                    "Selected Campaign Case identity is no longer authoritative"
                )
            if selection.layer == "baseline":
                if baseline is not None:
                    raise ValueError(
                        "Formal Diagnostic Campaign requires one baseline"
                    )
                baseline = selected_case
            elif selection.layer == "isolated_sensitivity":
                isolated = self.create_isolated_sensitivity_case(*anchor)
                isolated_by_family[isolated.transformation_family].append(
                    isolated
                )
            elif selection.layer == "compound":
                compounds.append(selected_case)
            else:
                raise ValueError("Unsupported Diagnostic Campaign layer")
        isolated_specification = IsolatedSensitivitySetSpecification(
            sensitivity_set_replica_id=(
                f"{task.task_id}:revision-{approved_revision}:isolated"
            ),
            sweeps=tuple(
                SensitivitySweepDefinition(
                    transformation_family=family,
                    transformation_id=family_cases[0].transformation_id,
                    transformation_implementation_version=(
                        family_cases[0].transformation_implementation_version
                    ),
                    levels=tuple(family_cases),
                )
                for family in ISOLATED_SENSITIVITY_FAMILIES
                if (family_cases := isolated_by_family[family])
            ),
            initial_cash=Decimal("100000"),
            order_shares=1000,
        )
        specification = DiagnosticCampaignSpecification(
            campaign_replica_id=(
                f"{task.task_id}:revision-{approved_revision}:formal"
            ),
            baseline_case=baseline,
            isolated_sensitivity_set=isolated_specification,
            compound_cases=tuple(compounds),
            initial_cash=Decimal("100000"),
            order_shares=1000,
            approved_strategies=tuple(
                DiagnosticCampaignStrategySelection(
                    strategy_id=selection.strategy_id,
                    strategy_version=selection.strategy_version,
                    compatibility_manifest_hash=(
                        selection.compatibility_manifest_hash
                    ),
                    guardrail_profile_id=selection.guardrail_profile_id,
                    guardrail_profile_version=(
                        selection.guardrail_profile_version
                    ),
                )
                for selection in task.configuration.strategy_selections
            ),
        )
        specification = DiagnosticCampaignSpecification.from_dict(
            specification.to_dict()
        )
        if specification.campaign_type != "formal_diagnostic_campaign":
            raise ValueError("Approved task does not define a Formal Campaign")
        return specification

    @staticmethod
    def _diagnostic_task_campaign_handoff(
        task: DiagnosticTaskSnapshot,
        campaign: DiagnosticCampaignSnapshot,
    ) -> DiagnosticTaskCampaignHandoffSnapshot:
        selections = {
            (
                selection.recipe_version_id,
                selection.market_scenario_id,
            ): selection
            for selection in task.configuration.campaign_case_selections
        }
        manifest_by_run_id = (
            {}
            if task.campaign_handoff is None
            else {
                run.run_id: run.reproduction_manifest_id
                for node in task.campaign_handoff.campaign_nodes
                for attempt in node.attempts
                for run in attempt.runs
                if run.reproduction_manifest_id is not None
            }
        )
        nodes: list[DiagnosticCampaignNodeHandoffSnapshot] = []
        for case in campaign.cases:
            selection = selections.get(
                (
                    case.specification.recipe_version_id,
                    case.specification.materialization_hash,
                )
            )
            if selection is None:
                raise ValueError(
                    "Formal Campaign Case is not in the approved task"
                )
            attempts: list[DiagnosticCampaignAttemptHandoffSnapshot] = []
            for attempt in case.attempts:
                view = attempt.to_dict()
                member_values = view.get("members", ())
                if not isinstance(member_values, Sequence) or isinstance(
                    member_values,
                    (str, bytes),
                ):
                    raise ValueError("Campaign members must be an ordered list")
                run_handoffs = tuple(
                    DiagnosticCampaignRunHandoffSnapshot(
                        run_id=str(member["run_id"]),
                        strategy_id=str(member["strategy_id"]),
                        reproduction_manifest_id=manifest_by_run_id.get(
                            str(member["run_id"])
                        ),
                    )
                    for member in member_values
                    if isinstance(member, Mapping)
                    and isinstance(member.get("run_id"), str)
                    and isinstance(member.get("strategy_id"), str)
                )
                if len(run_handoffs) != len(member_values):
                    raise ValueError(
                        "Campaign member Run and Strategy identities are required"
                    )
                attempt_id = (
                    f"{campaign.campaign_id}:"
                    f"{selection.campaign_case_id}:"
                    f"attempt-{attempt.attempt_number}"
                )
                failure_code, failure_message = (
                    DiagnosticsApplication._campaign_attempt_failure(view)
                    if attempt.status == "incomplete"
                    else (None, None)
                )
                attempts.append(
                    DiagnosticCampaignAttemptHandoffSnapshot(
                        attempt_id=attempt_id,
                        runs=run_handoffs,
                        attempt_number=attempt.attempt_number,
                        lifecycle=(
                            DiagnosticTaskLifecycle.COMPLETED
                            if attempt.status == "completed"
                            else DiagnosticTaskLifecycle.FAILED
                        ),
                        predecessor_attempt_id=(
                            None if not attempts else attempts[-1].attempt_id
                        ),
                        failure_code=failure_code,
                        failure_message=failure_message,
                    )
                )
            nodes.append(
                DiagnosticCampaignNodeHandoffSnapshot(
                    campaign_node_id=(
                        f"{campaign.campaign_id}:"
                        f"{case.case_id}"
                    ),
                    campaign_case_id=case.case_id,
                    selected_campaign_case_id=(
                        selection.campaign_case_id
                    ),
                    market_scenario_id=selection.market_scenario_id,
                    attempts=tuple(attempts),
                    active_attempt_id=(
                        None
                        if not attempts
                        else attempts[-1].attempt_id
                    ),
                    lifecycle={
                        "planned": DiagnosticTaskLifecycle.QUEUED,
                        "completed": DiagnosticTaskLifecycle.COMPLETED,
                        "incomplete": DiagnosticTaskLifecycle.FAILED,
                    }[case.status],
                )
            )
        return DiagnosticTaskCampaignHandoffSnapshot(
            campaign_id=campaign.campaign_id,
            campaign_nodes=tuple(nodes),
            evidence_package_id=(
                None
                if task.campaign_handoff is None
                else task.campaign_handoff.evidence_package_id
            ),
            evidence_state=(
                DiagnosticEvidenceHandoffState.PENDING
                if task.campaign_handoff is None
                else task.campaign_handoff.evidence_state
            ),
            evidence_error_code=(
                None
                if task.campaign_handoff is None
                else task.campaign_handoff.evidence_error_code
            ),
            evidence_error_message=(
                None
                if task.campaign_handoff is None
                else task.campaign_handoff.evidence_error_message
            ),
            reproduction_manifest_id=(
                None
                if task.campaign_handoff is None
                else task.campaign_handoff.reproduction_manifest_id
            ),
        )

    @staticmethod
    def _campaign_attempt_failure(
        view: Mapping[str, object],
    ) -> tuple[str, str]:
        members = view.get("members", ())
        if isinstance(members, Sequence) and not isinstance(
            members,
            (str, bytes),
        ):
            for member in members:
                if not isinstance(member, Mapping):
                    continue
                if member.get("status") == "completed":
                    continue
                failure_value = member.get("failure", {})
                failure = (
                    failure_value
                    if isinstance(failure_value, Mapping)
                    else {}
                )
                return (
                    str(failure.get("code") or "IncompleteStrategyRun"),
                    str(
                        failure.get("message")
                        or "Strategy Run result is incomplete"
                    ),
                )
        failure_value = view.get("failure", {})
        failure = (
            failure_value if isinstance(failure_value, Mapping) else {}
        )
        return (
            str(failure.get("code") or "IncompleteCampaign"),
            str(failure.get("message") or "Campaign result is incomplete"),
        )

    def _validate_diagnostic_task_configuration(
        self,
        candidate: DiagnosticTaskConfiguration,
    ) -> tuple[DiagnosticTaskValidationFinding, ...]:
        findings: list[DiagnosticTaskValidationFinding] = []
        layers = tuple(
            item.layer for item in candidate.campaign_case_selections
        )
        for layer, code, explanation in (
            (
                "baseline",
                "campaign.layer.baseline_required",
                "Exactly one Baseline Campaign Case is required.",
            ),
            (
                "isolated_sensitivity",
                "campaign.layer.isolated_sensitivity_required",
                "At least one Isolated Sensitivity Campaign Case is required.",
            ),
            (
                "compound",
                "campaign.layer.compound_required",
                "At least one Compound Campaign Case is required.",
            ),
        ):
            count = layers.count(layer)
            invalid = count != 1 if layer == "baseline" else count < 1
            if invalid:
                findings.append(
                    DiagnosticTaskValidationFinding(
                        reference_kind=(
                            DiagnosticTaskValidationReferenceKind.CONFIGURATION
                        ),
                        reference_identity=candidate.content_identity,
                        severity=DiagnosticTaskValidationSeverity.ERROR,
                        code=code,
                        safe_explanation=explanation,
                        retryable=False,
                        requires_different_input=True,
                    )
                )
        findings.extend(
            self._diagnostic_task_authority_findings(candidate)
        )
        return tuple(findings)

    def _diagnostic_task_authority_findings(
        self,
        candidate: DiagnosticTaskConfiguration,
    ) -> tuple[DiagnosticTaskValidationFinding, ...]:
        findings: list[DiagnosticTaskValidationFinding] = []

        def add(
            reference_kind: DiagnosticTaskValidationReferenceKind,
            reference_identity: str,
            code: str,
            explanation: str,
        ) -> None:
            findings.append(
                DiagnosticTaskValidationFinding(
                    reference_kind=reference_kind,
                    reference_identity=reference_identity,
                    severity=DiagnosticTaskValidationSeverity.ERROR,
                    code=code,
                    safe_explanation=explanation,
                    retryable=False,
                    requires_different_input=True,
                )
            )

        if (
            candidate.content_identity
            != candidate.calculated_content_identity()
        ):
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "configuration.content_identity_mismatch",
                "The configuration content identity is not canonical.",
            )

        configuration = self.v1_diagnostic_configuration()
        manifests = {
            str(item["strategy_id"]): item
            for item in cast(
                list[Mapping[str, object]],
                configuration["supported_strategies"],
            )
        }
        profiles = {
            str(item["strategy_id"]): item
            for item in cast(
                list[Mapping[str, object]],
                configuration["supported_guardrail_profiles"],
            )
        }
        selected_strategy_ids = tuple(
            item.strategy_id for item in candidate.strategy_selections
        )
        if len(set(selected_strategy_ids)) != len(selected_strategy_ids):
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "strategy.selection_duplicate",
                "Each authoritative strategy may be selected only once.",
            )
        if set(selected_strategy_ids) != set(manifests):
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "strategy.selection_set_mismatch",
                "The selected strategy set does not match the authoritative inventory.",
            )
        for strategy_selection in candidate.strategy_selections:
            manifest = manifests.get(strategy_selection.strategy_id)
            profile = profiles.get(strategy_selection.strategy_id)
            if manifest is None:
                add(
                    DiagnosticTaskValidationReferenceKind.STRATEGY,
                    strategy_selection.strategy_id,
                    "strategy.identity_unavailable",
                    "The selected strategy identity is not authoritative.",
                )
            else:
                if strategy_selection.strategy_version != str(
                    manifest["strategy_version"]
                ):
                    add(
                        DiagnosticTaskValidationReferenceKind.STRATEGY,
                        strategy_selection.strategy_id,
                        "strategy.version_mismatch",
                        "The selected strategy version is not authoritative.",
                    )
                if strategy_selection.compatibility_manifest_hash != str(
                    manifest["manifest_content_hash"]
                ):
                    add(
                        DiagnosticTaskValidationReferenceKind.STRATEGY,
                        strategy_selection.strategy_id,
                        "strategy.compatibility_manifest_mismatch",
                        "The compatibility manifest identity does not match.",
                    )
            if profile is None:
                add(
                    DiagnosticTaskValidationReferenceKind.STRATEGY,
                    strategy_selection.strategy_id,
                    "strategy.guardrail_profile_unavailable",
                    "The authoritative guardrail profile is unavailable.",
                )
            else:
                if strategy_selection.guardrail_profile_id != str(
                    profile["profile_id"]
                ):
                    add(
                        DiagnosticTaskValidationReferenceKind.STRATEGY,
                        strategy_selection.strategy_id,
                        "strategy.guardrail_profile_id_mismatch",
                        "The selected guardrail profile identity does not match.",
                    )
                if strategy_selection.guardrail_profile_version != str(
                    profile["profile_version"]
                ):
                    add(
                        DiagnosticTaskValidationReferenceKind.STRATEGY,
                        strategy_selection.strategy_id,
                        "strategy.guardrail_profile_version_mismatch",
                        "The selected guardrail profile version does not match.",
                    )

        approved = {
            item.version_id: item
            for item in self.list_approved_scenario_recipes()
        }
        paths = {
            item.artifact_hash: item
            for item in self.list_materialized_market_paths()
        }
        cases = {
            item.case_id: item
            for item in self.list_available_diagnostic_campaign_cases()
        }
        if sum(item.layer == "baseline" for item in cases.values()) != 1:
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "campaign.authoritative_baseline_catalog_invalid",
                "The authoritative Campaign Case inventory must contain one baseline.",
            )
        selected_case_ids = tuple(
            item.campaign_case_id
            for item in candidate.campaign_case_selections
        )
        if not selected_case_ids:
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "campaign.selection_required",
                "At least one authoritative Campaign Case is required.",
            )
        if len(set(selected_case_ids)) != len(selected_case_ids):
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "campaign.case_selection_duplicate",
                "Each Campaign Case may be selected only once.",
            )
        baseline_case_ids = {
            item.campaign_case_id
            for item in candidate.campaign_case_selections
            if item.layer == "baseline"
        }
        baseline_case_id = (
            next(iter(baseline_case_ids))
            if len(baseline_case_ids) == 1
            else None
        )
        if baseline_case_id is None:
            add(
                DiagnosticTaskValidationReferenceKind.CONFIGURATION,
                candidate.content_identity,
                "campaign.baseline_selection_invalid",
                "Exactly one selected Campaign Case must be the baseline.",
            )
        for case_selection in candidate.campaign_case_selections:
            case = cases.get(case_selection.campaign_case_id)
            recipe = approved.get(case_selection.recipe_version_id)
            path = paths.get(case_selection.market_scenario_id)
            reference_kind = (
                DiagnosticTaskValidationReferenceKind.CAMPAIGN_CASE
            )
            reference_identity = case_selection.campaign_case_id
            if case is None:
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.case_identity_unavailable",
                    "The selected Campaign Case identity is not authoritative.",
                )
            if recipe is None:
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.recipe_version_unavailable",
                    "The approved Scenario Recipe version is unavailable.",
                )
            if path is None:
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.market_scenario_unavailable",
                    "The materialized market scenario is unavailable.",
                )
            if (
                case is not None
                and case.recipe_version_id
                != case_selection.recipe_version_id
            ):
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.case_recipe_mismatch",
                    "The Campaign Case is bound to a different recipe version.",
                )
            if (
                case is not None
                and case.materialization_hash
                != case_selection.market_scenario_id
            ):
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.case_market_scenario_mismatch",
                    "The Campaign Case is bound to a different market scenario.",
                )
            if (
                recipe is not None
                and recipe.content_hash
                != case_selection.recipe_content_hash
            ):
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.recipe_content_hash_mismatch",
                    "The approved Scenario Recipe content identity does not match.",
                )
            expected_layer = {
                "baseline": "baseline",
                "isolated": "isolated_sensitivity",
                "compound": "compound",
            }.get(case.layer if case is not None else "")
            if case is not None and expected_layer != case_selection.layer:
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.layer_mismatch",
                    "The Campaign Case layer does not match its authoritative type.",
                )
            is_baseline = case_selection.layer == "baseline"
            expected_role = (
                "control" if is_baseline else "compare_to_baseline"
            )
            expected_baseline_id = (
                None if is_baseline else baseline_case_id
            )
            if (
                case_selection.comparison_role != expected_role
                or case_selection.baseline_campaign_case_id
                != expected_baseline_id
            ):
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.comparison_binding_mismatch",
                    "The comparison role or baseline binding does not match.",
                )
            if recipe is None:
                continue
            execution = recipe.recipe.execution_conditions
            expected_values = {
                "allow_partial_fills": str(
                    execution.allow_partial_fills
                ).lower(),
                "commission_bps": str(execution.commission_bps),
                "decision_cadence_minutes": str(
                    recipe.recipe.decision_cadence_minutes
                ),
                "latency_nodes": str(execution.latency_nodes),
                "max_fill_fraction": str(execution.max_fill_fraction),
                "slippage_bps": str(execution.slippage_bps),
            }
            actual_values = {
                name: (value, version, source)
                for name, value, version, source in (
                    case_selection.execution_policy_values
                )
            }
            if len(actual_values) != len(
                case_selection.execution_policy_values
            ):
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.execution_policy_duplicate",
                    "Execution policy names must be unique.",
                )
            if actual_values != {
                name: (
                    value,
                    recipe.recipe.schema_version,
                    "Approved Scenario Recipe",
                )
                for name, value in expected_values.items()
            }:
                add(
                    reference_kind,
                    reference_identity,
                    "campaign.execution_policy_mismatch",
                    "Execution policy values or provenance do not match.",
                )
        return tuple(findings)

    def _diagnostic_task_validation_policy_identities(
        self,
        candidate: DiagnosticTaskConfiguration,
    ) -> tuple[str, ...]:
        configuration = self.v1_diagnostic_configuration()
        manifests = cast(
            list[Mapping[str, object]],
            configuration["supported_strategies"],
        )
        profiles = cast(
            list[Mapping[str, object]],
            configuration["supported_guardrail_profiles"],
        )
        approved = {
            item.version_id: item
            for item in self.list_approved_scenario_recipes()
        }
        paths = {
            item.artifact_hash: item
            for item in self.list_materialized_market_paths()
        }
        identities = {"diagnostic-task-validation-policy.v1"}
        identities.update(
            f"compatibility-surface:{item['surface_version']}"
            for item in manifests
        )
        identities.update(
            f"guardrail-profile:{item['profile_id']}@{item['profile_version']}"
            for item in profiles
        )
        for selection in candidate.campaign_case_selections:
            recipe = approved.get(selection.recipe_version_id)
            path = paths.get(selection.market_scenario_id)
            if recipe is not None:
                identities.add(
                    f"scenario-recipe-schema:{recipe.recipe.schema_version}"
                )
            if path is not None:
                identities.add(
                    "transformation-catalog:"
                    + path.transformation_catalog_version
                )
                identities.add(
                    "market-rule-profile:"
                    + path.market_rule_profile_version
                )
        return tuple(sorted(identities))

    def _diagnostic_selection_dependency_binding(
        self,
        candidate: DiagnosticTaskConfiguration,
        expected: DiagnosticSelectionDependencyBinding,
    ) -> DiagnosticSelectionDependencyBinding | None:
        if (
            self._diagnostic_setup_observation_initialized
            and self._observed_diagnostic_setup_binding != expected
        ):
            return None
        payload = json.loads(expected.canonical_payload_json)
        if not isinstance(payload, dict):
            return None
        strategy_payload = payload.get("strategy_selection")
        scenario_payload = payload.get("scenario_selection")
        if not isinstance(strategy_payload, dict) or not isinstance(
            scenario_payload, dict
        ):
            return None
        scenario_context_payload = scenario_payload.get("context")
        if not isinstance(scenario_context_payload, dict):
            return None
        scenario_context_identity = scenario_context_payload.get(
            "selection_context_id"
        )
        if isinstance(scenario_context_identity, dict):
            scenario_context_identity = scenario_context_identity.get("value")
        if (
            payload.get("schema_version")
            != "diagnostic-setup-selection-context.v1"
            or payload.get("configuration_content_identity")
            != candidate.content_identity
            or strategy_payload.get("context_identity")
            != expected.strategy_selection_context_id
            or scenario_context_identity != expected.scenario_selection_context_id
            or expected.source_identity != expected.binding_hash
        ):
            return None
        case_ids = tuple(
            item.campaign_case_id for item in candidate.campaign_case_selections
        )
        strategy_ids = tuple(
            item.strategy_id for item in candidate.strategy_selections
        )
        selection = next(
            (
                item
                for item in reversed(self.scenario_lab_selection_contexts())
                if item.selection_context_id
                == expected.scenario_selection_context_id
                and item.status == "current"
                and item.formal_handoff_eligible
                and len(item.case_ids) == len(case_ids)
                and set(item.case_ids) == set(case_ids)
                and len(item.strategy_bindings) == len(strategy_ids)
                and {
                    binding.strategy_id for binding in item.strategy_bindings
                }
                == set(strategy_ids)
            ),
            None,
        )
        if selection is None:
            return None
        scenario_set = next(
            (
                item
                for item in self.scenario_lab_formal_scenario_sets()
                if item.scenario_set_id == selection.scenario_set_id
                and item.projection_revision
                == selection.scenario_set_projection_revision
            ),
            None,
        )
        resolution = next(
            (
                item
                for item in self.scenario_lab_execution_resolutions()
                if item.resolution_id == selection.execution_resolution_id
                and item.projection_revision
                == selection.execution_resolution_projection_revision
            ),
            None,
        )
        if (
            scenario_set is None
            or resolution is None
            or not scenario_set.formal_handoff_eligible
            or not resolution.formal_handoff_eligible
        ):
            return None
        expected_strategies = tuple(
            (
                item.strategy_id,
                item.strategy_version,
                item.compatibility_manifest_hash,
                item.guardrail_profile_id,
                item.guardrail_profile_version,
            )
            for item in selection.strategy_bindings
        )
        actual_strategies = tuple(
            (
                item.strategy_id,
                item.strategy_version,
                item.compatibility_manifest_hash,
                item.guardrail_profile_id,
                item.guardrail_profile_version,
            )
            for item in candidate.strategy_selections
        )
        if tuple(sorted(actual_strategies)) != tuple(sorted(expected_strategies)):
            return None
        cases = (
            scenario_set.baseline_case,
            *scenario_set.isolated_cases,
            *scenario_set.compound_cases,
        )
        baseline_id = scenario_set.baseline_case.case_id
        expected_cases = []
        for case in cases:
            targets = tuple(
                item
                for item in resolution.targets
                if item.campaign_case_id == case.case_id
            )
            if not targets or any(
                item.state != "resolved" or item.resolved_conditions is None
                for item in targets
            ):
                return None
            policy_values = tuple(
                (
                    item.name,
                    item.effective_value,
                    targets[0].execution_policy_version,
                    (
                        "backend-resolved:requested=" + item.requested_value
                        if item.override_reason is None
                        else (
                            "backend-resolved:"
                            + item.override_reason
                            + ";requested="
                            + item.requested_value
                        )
                    ),
                )
                for item in sorted(
                    cast(
                        ResolvedExecutionConditions,
                        targets[0].resolved_conditions,
                    ).resolutions,
                    key=lambda value: value.name,
                )
            )
            if any(
                tuple(
                    (
                        item.name,
                        item.effective_value,
                        target.execution_policy_version,
                        (
                            "backend-resolved:requested=" + item.requested_value
                            if item.override_reason is None
                            else (
                                "backend-resolved:"
                                + item.override_reason
                                + ";requested="
                                + item.requested_value
                            )
                        ),
                    )
                    for item in sorted(
                        cast(
                            ResolvedExecutionConditions,
                            target.resolved_conditions,
                        ).resolutions,
                        key=lambda value: value.name,
                    )
                )
                != policy_values
                for target in targets[1:]
            ):
                return None
            expected_cases.append(
                (
                    {
                        "baseline": "baseline",
                        "isolated": "isolated_sensitivity",
                        "compound": "compound",
                    }[case.layer],
                    case.recipe_version_id,
                    case.recipe_content_hash,
                    case.materialization_hash,
                    case.case_id,
                    (
                        "control"
                        if case.case_id == baseline_id
                        else "compare_to_baseline"
                    ),
                    None if case.case_id == baseline_id else baseline_id,
                    policy_values,
                )
            )
        actual_cases = tuple(
            (
                item.layer,
                item.recipe_version_id,
                item.recipe_content_hash,
                item.market_scenario_id,
                item.campaign_case_id,
                item.comparison_role,
                item.baseline_campaign_case_id,
                item.execution_policy_values,
            )
            for item in candidate.campaign_case_selections
        )
        if tuple(sorted(actual_cases, key=lambda item: item[4])) != tuple(
            sorted(expected_cases, key=lambda item: item[4])
        ):
            return None
        inventory = self.read_strategy_under_test_inventory()
        strategy_source_revision = strategy_payload.get("source_revision")
        if isinstance(strategy_source_revision, dict):
            strategy_source_revision = strategy_source_revision.get("value")
        if strategy_source_revision != inventory.content_hash:
            return None
        return expected

    def _is_authoritative_diagnostic_task_configuration(
        self,
        candidate: DiagnosticTaskConfiguration,
    ) -> bool:
        return not self._diagnostic_task_authority_findings(candidate)

    def recommend_historical_segments(
        self,
        intent: str = "",
        limit: int = 3,
    ) -> tuple[HistoricalSegmentRecommendation, ...]:
        self.status()
        return cast(
            tuple[HistoricalSegmentRecommendation, ...],
            self._historical_segments.recommend(
                intent=intent,
                limit=limit,
            ),
        )

    def latest_segment_admission(self) -> SegmentAdmissionReport | None:
        self.status()
        return self._historical_segments.latest_report()

    def historical_segment_catalog_view(self) -> dict[str, object]:
        self.status()
        segments = self._historical_segments.list_segments()
        latest = self._historical_segments.latest_report()
        if latest is not None:
            catalog_status = latest.status
        elif segments:
            catalog_status = "admitted"
        else:
            catalog_status = "not_checked"
        return {
            "status": catalog_status,
            "segment_count": len(segments),
            "segments": [segment.to_dict() for segment in segments],
            "latest_admission": latest.to_dict() if latest is not None else None,
        }

    def transformation_catalog_view(self) -> dict[str, object]:
        self.status()
        return cast(
            dict[str, object],
            self._transformation_catalog.to_dict(),
        )

    def materialize_baseline_reference_path(
        self,
        recipe_version_id: str,
    ) -> MaterializedMarketPath:
        self.status()
        approved = self._recipe_workbench.get_version(recipe_version_id)
        if approved.recipe.transformations:
            raise ValueError(
                "baseline materialization requires a recipe without transformations"
            )
        return self.materialize_reference_path(recipe_version_id)

    def materialize_reference_path(
        self,
        recipe_version_id: str,
    ) -> MaterializedMarketPath:
        self.status()
        approved = self._recipe_workbench.get_version(recipe_version_id)
        if self._scenario_materializer is None:
            raise RuntimeError(
                "The configured historical source cannot materialize market paths"
            )
        segment = next(
            (
                item
                for item in self._historical_segments.list_segments()
                if item.segment_id == approved.recipe.historical_segment_id
            ),
            None,
        )
        if segment is None:
            raise ValueError("Only an admitted Historical Market Segment can be materialized")
        return self._scenario_materializer.materialize(
            segment,
            transformations=approved.recipe.transformations,
            seed=approved.recipe.materialization_seed,
        )

    def create_isolated_sensitivity_case(
        self,
        recipe_version_id: str,
        materialization_hash: str,
    ) -> SensitivityCampaignCase:
        """Anchor one approved single-family recipe to its exact materialization."""

        self.status()
        approved = self._recipe_workbench.get_version(recipe_version_id)
        if len(approved.recipe.transformations) != 1:
            raise ValueError(
                "A Sensitivity Campaign Case requires exactly one transformation family"
            )
        expected_path = self.materialize_reference_path(recipe_version_id)
        if expected_path.artifact_hash != materialization_hash:
            raise ValueError(
                "Sensitivity Campaign Case materialization does not match its approved recipe"
            )
        path = self._load_reference_path(materialization_hash)
        if len(path.applied_transformations) != 1:
            raise ValueError(
                "A Sensitivity Campaign Case path requires exactly one transformation family"
            )
        requested = approved.recipe.transformations[0]
        applied = path.applied_transformations[0]
        catalog_entry = self._transformation_catalog.get_entry(
            requested.transformation_id
        )
        requested_parameters = (
            self._transformation_catalog.canonical_parameters(
                requested.transformation_id,
                requested.parameters,
            )
        )
        if (
            requested.transformation_id != applied.transformation_id
            or requested_parameters != applied.parameters
            or catalog_entry.family != applied.family
            or catalog_entry.implementation_version
            != applied.implementation_version
            or self._transformation_catalog.catalog_version
            != path.transformation_catalog_version
        ):
            raise ValueError(
                "Sensitivity Campaign Case transformation provenance does not match "
                "its approved recipe and catalog"
            )
        execution = approved.recipe.execution_conditions
        return SensitivityCampaignCase(
            recipe_version_id=approved.version_id,
            recipe_content_hash=approved.content_hash,
            materialization_hash=path.artifact_hash,
            historical_segment_id=path.segment_id,
            historical_segment_content_hash=path.segment_content_hash,
            source_snapshot_id=path.source_snapshot_id,
            materialization_seed=path.seed,
            expander_version=path.expander_version,
            source_resolution=path.source_resolution,
            runtime_resolution=path.runtime_resolution,
            numeric_tolerance=path.numeric_tolerance,
            normalization_provenance=path.normalization_provenance,
            transformation_catalog_version=path.transformation_catalog_version,
            transformation_id=applied.transformation_id,
            transformation_family=applied.family,
            transformation_implementation_version=(
                applied.implementation_version
            ),
            transformation_parameters=tuple(sorted(applied.parameters)),
            market_rule_profile_version=path.market_rule_profile_version,
            decision_cadence_minutes=approved.recipe.decision_cadence_minutes,
            requested_execution_conditions=RequestedExecutionAssumptions(
                commission_bps=execution.commission_bps,
                slippage_bps=execution.slippage_bps,
                max_fill_fraction=execution.max_fill_fraction,
                latency_nodes=execution.latency_nodes,
                allow_partial_fills=execution.allow_partial_fills,
            ),
        )

    def create_diagnostic_campaign_case(
        self,
        recipe_version_id: str,
        materialization_hash: str,
    ) -> DiagnosticCampaignCase:
        """Anchor one approved recipe to its exact immutable Campaign Case."""

        self.status()
        approved = self._recipe_workbench.get_version(recipe_version_id)
        expected_path = self.materialize_reference_path(recipe_version_id)
        if expected_path.artifact_hash != materialization_hash:
            raise ValueError(
                "Diagnostic Campaign Case materialization does not match "
                "its approved recipe"
            )
        path = self._load_reference_path(materialization_hash)
        return self._diagnostic_campaign_case_from_existing_path(approved, path)

    def _diagnostic_campaign_case_from_existing_path(
        self,
        approved: ApprovedScenarioRecipeVersion,
        path: MaterializedMarketPath,
    ) -> DiagnosticCampaignCase:
        recipe = approved.recipe
        if (
            path.segment_id != recipe.historical_segment_id
            or path.seed != recipe.materialization_seed
            or path.market_rule_profile_version != recipe.market_rule_profile
        ):
            raise ValueError(
                "Diagnostic Campaign Case materialization does not match "
                "its approved recipe"
            )
        requested_by_id = {
            item.transformation_id: item
            for item in recipe.transformations
        }
        applied_by_id = {
            item.transformation_id: item
            for item in path.applied_transformations
        }
        if (
            len(requested_by_id) != len(recipe.transformations)
            or len(applied_by_id) != len(path.applied_transformations)
            or set(requested_by_id) != set(applied_by_id)
            or self._transformation_catalog.catalog_version
            != path.transformation_catalog_version
        ):
            raise ValueError(
                "Diagnostic Campaign Case transformation provenance does not "
                "match its approved recipe and catalog"
            )
        transformations: list[CampaignTransformation] = []
        for transformation_id, requested in requested_by_id.items():
            applied = applied_by_id[transformation_id]
            catalog_entry = self._transformation_catalog.get_entry(
                transformation_id
            )
            requested_parameters = (
                self._transformation_catalog.canonical_parameters(
                    transformation_id,
                    requested.parameters,
                )
            )
            if (
                requested_parameters != applied.parameters
                or catalog_entry.family != applied.family
                or catalog_entry.implementation_version
                != applied.implementation_version
            ):
                raise ValueError(
                    "Diagnostic Campaign Case transformation provenance does not "
                    "match its approved recipe and catalog"
                )
            transformations.append(
                CampaignTransformation(
                    transformation_id=transformation_id,
                    transformation_family=applied.family,
                    transformation_implementation_version=(
                        applied.implementation_version
                    ),
                    transformation_parameters=tuple(
                        sorted(applied.parameters)
                    ),
                )
            )
        execution = recipe.execution_conditions
        return DiagnosticCampaignCase(
            recipe_version_id=approved.version_id,
            recipe_content_hash=approved.content_hash,
            materialization_hash=path.artifact_hash,
            historical_segment_id=path.segment_id,
            historical_segment_content_hash=path.segment_content_hash,
            source_snapshot_id=path.source_snapshot_id,
            materialization_seed=path.seed,
            expander_version=path.expander_version,
            source_resolution=path.source_resolution,
            runtime_resolution=path.runtime_resolution,
            numeric_tolerance=path.numeric_tolerance,
            normalization_provenance=path.normalization_provenance,
            transformation_catalog_version=(
                path.transformation_catalog_version
            ),
            transformations=tuple(
                sorted(
                    transformations,
                    key=lambda item: (
                        item.transformation_family,
                        item.transformation_id,
                    ),
                )
            ),
            market_rule_profile_version=path.market_rule_profile_version,
            decision_cadence_minutes=recipe.decision_cadence_minutes,
            requested_execution_conditions=RequestedExecutionAssumptions(
                commission_bps=execution.commission_bps,
                slippage_bps=execution.slippage_bps,
                max_fill_fraction=execution.max_fill_fraction,
                latency_nodes=execution.latency_nodes,
                allow_partial_fills=execution.allow_partial_fills,
            ),
        )

    def plan_isolated_sensitivity_set(
        self,
        case_anchors: tuple[tuple[str, str], ...],
        *,
        initial_cash: Decimal,
        order_shares: int,
        sensitivity_set_replica_id: str,
    ) -> IsolatedSensitivitySetSnapshot:
        """Plan a bounded six-family set from explicitly approved case anchors."""

        cases = tuple(
            self.create_isolated_sensitivity_case(
                recipe_version_id,
                materialization_hash,
            )
            for recipe_version_id, materialization_hash in case_anchors
        )
        if cases:
            requested = cases[0].requested_execution_conditions
            if (
                requested.commission_bps != BASELINE_CAMPAIGN_COMMISSION_BPS
                or requested.slippage_bps != BASELINE_CAMPAIGN_SLIPPAGE_BPS
            ):
                raise ValueError(
                    "Isolated Sensitivity Set requires requested slippage 5 bps "
                    "and commission 3 bps for both representative strategies"
                )
        specification = IsolatedSensitivitySetSpecification(
            sensitivity_set_replica_id=sensitivity_set_replica_id,
            sweeps=tuple(
                SensitivitySweepDefinition(
                    transformation_family=family,
                    transformation_id=family_cases[0].transformation_id,
                    transformation_implementation_version=(
                        family_cases[0].transformation_implementation_version
                    ),
                    levels=family_cases,
                )
                for family in ISOLATED_SENSITIVITY_FAMILIES
                if (
                    family_cases := tuple(
                        case
                        for case in cases
                        if case.transformation_family == family
                    )
                )
            ),
            initial_cash=initial_cash,
            order_shares=order_shares,
        )
        return self._isolated_sensitivity_sets.plan(specification)

    def isolated_sensitivity_set_status(
        self,
        sensitivity_set_id: str,
    ) -> IsolatedSensitivitySetSnapshot:
        self.status()
        return self._isolated_sensitivity_sets.get(sensitivity_set_id)

    def advance_isolated_sensitivity_set(
        self,
        sensitivity_set_id: str,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> IsolatedSensitivitySetSnapshot:
        self.status()
        return self._isolated_sensitivity_sets.advance(
            sensitivity_set_id,
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )

    def resume_isolated_sensitivity_set(
        self,
        sensitivity_set_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> IsolatedSensitivitySetSnapshot:
        self.status()
        return self._isolated_sensitivity_sets.resume(
            sensitivity_set_id,
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )

    def retry_isolated_sensitivity_case(
        self,
        sensitivity_set_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> IsolatedSensitivitySetSnapshot:
        self.status()
        return self._isolated_sensitivity_sets.retry_case(
            sensitivity_set_id,
            case_id,
            nodes_per_batch=nodes_per_batch,
        )

    def plan_diagnostic_campaign(
        self,
        *,
        baseline_anchor: tuple[str, str] | None,
        isolated_sensitivity_set_id: str | None,
        compound_case_anchors: tuple[tuple[str, str], ...],
        initial_cash: Decimal,
        order_shares: int,
        campaign_replica_id: str,
    ) -> DiagnosticCampaignSnapshot:
        """Plan a Formal Diagnostic Campaign or labeled Quick Experiment."""

        self.status()
        baseline_case = (
            self.create_diagnostic_campaign_case(*baseline_anchor)
            if baseline_anchor is not None
            else None
        )
        if baseline_case is not None and baseline_case.layer != "baseline":
            raise ValueError(
                "Baseline Scenario Set requires an approved untransformed recipe"
            )
        isolated_specification = None
        if isolated_sensitivity_set_id is not None:
            isolated_specification = self._isolated_sensitivity_sets.get(
                isolated_sensitivity_set_id
            ).specification
        compound_cases = tuple(
            self.create_diagnostic_campaign_case(
                recipe_version_id,
                materialization_hash,
            )
            for recipe_version_id, materialization_hash in compound_case_anchors
        )
        if any(case.layer != "compound" for case in compound_cases):
            raise ValueError(
                "Compound Scenario Set requires approved recipes with at least "
                "two transformation families"
            )
        specification = DiagnosticCampaignSpecification(
            campaign_replica_id=campaign_replica_id,
            baseline_case=baseline_case,
            isolated_sensitivity_set=isolated_specification,
            compound_cases=compound_cases,
            initial_cash=initial_cash,
            order_shares=order_shares,
        )
        return self._diagnostic_campaigns.plan(specification)

    def diagnostic_campaign_status(
        self,
        campaign_id: str,
    ) -> DiagnosticCampaignSnapshot:
        self.status()
        return self._diagnostic_campaigns.get(campaign_id)

    def advance_diagnostic_campaign(
        self,
        campaign_id: str,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        self.status()
        self._require_linked_campaign_running(campaign_id)
        campaign = self._diagnostic_campaigns.get(campaign_id)
        eligible_case_ids = self._linked_campaign_executable_case_ids(
            campaign,
            max_cases=max_cases,
        )
        if eligible_case_ids == ():
            self._sync_linked_diagnostic_campaign(campaign)
            if campaign.status == "completed":
                self._seal_linked_diagnostic_task_evidence(campaign)
            return campaign
        advanced = self._diagnostic_campaigns.advance(
            campaign_id,
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
            eligible_case_ids=eligible_case_ids,
        )
        self._sync_linked_diagnostic_campaign(advanced)
        if advanced.status == "completed":
            self._seal_linked_diagnostic_task_evidence(advanced)
        return advanced

    def resume_diagnostic_campaign(
        self,
        campaign_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        self.status()
        self._require_linked_campaign_running(campaign_id)
        campaign = self._diagnostic_campaigns.get(campaign_id)
        eligible_case_ids = self._linked_campaign_executable_case_ids(
            campaign,
            max_cases=max_cases,
        )
        if eligible_case_ids == ():
            self._sync_linked_diagnostic_campaign(campaign)
            if campaign.status == "completed":
                self._seal_linked_diagnostic_task_evidence(campaign)
            return campaign
        resumed = self._diagnostic_campaigns.resume(
            campaign_id,
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
            eligible_case_ids=eligible_case_ids,
        )
        self._sync_linked_diagnostic_campaign(resumed)
        if resumed.status == "completed":
            self._seal_linked_diagnostic_task_evidence(resumed)
        return resumed

    def retry_diagnostic_campaign_case(
        self,
        campaign_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        self.status()
        self._require_linked_campaign_running(campaign_id)
        return self._diagnostic_campaigns.retry_case(
            campaign_id,
            case_id,
            nodes_per_batch=nodes_per_batch,
        )

    def strategy_guardrail_profiles(
        self,
    ) -> tuple[StrategyGuardrailProfile, ...]:
        """Return the explicit versioned V1 profiles for selectable strategies."""

        self.status()
        return (
            StrategyGuardrailProfile(
                strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
                profile_version="quentx-balanced-diagnostics.v1",
                thresholds=(
                    GuardrailThreshold(
                        metric_name="total_return",
                        operator="less_than",
                        value=Decimal("-0.05"),
                    ),
                    GuardrailThreshold(
                        metric_name="maximum_drawdown",
                        operator="greater_than",
                        value=Decimal("0.20"),
                    ),
                    GuardrailThreshold(
                        metric_name="turnover",
                        operator="greater_than",
                        value=Decimal("8"),
                    ),
                    GuardrailThreshold(
                        metric_name="instrument_concentration",
                        operator="greater_than",
                        value=Decimal("0.60"),
                    ),
                    GuardrailThreshold(
                        metric_name="execution_erosion_bps",
                        operator="greater_than",
                        value=Decimal("75"),
                    ),
                ),
            ),
            StrategyGuardrailProfile(
                strategy_id=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                strategy_version=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
                profile_version="live-minute-capital-preservation.v1",
                thresholds=(
                    GuardrailThreshold(
                        metric_name="total_return",
                        operator="less_than",
                        value=Decimal("-0.03"),
                    ),
                    GuardrailThreshold(
                        metric_name="maximum_drawdown",
                        operator="greater_than",
                        value=Decimal("0.15"),
                    ),
                    GuardrailThreshold(
                        metric_name="turnover",
                        operator="greater_than",
                        value=Decimal("4"),
                    ),
                    GuardrailThreshold(
                        metric_name="instrument_concentration",
                        operator="greater_than",
                        value=Decimal("0.70"),
                    ),
                    GuardrailThreshold(
                        metric_name="execution_erosion_bps",
                        operator="greater_than",
                        value=Decimal("50"),
                    ),
                ),
            ),
        )

    def read_strategy_under_test_inventory(self) -> StrategyUnderTestInventory:
        """Return the audited backend-owned formal V1 Strategy inventory."""

        self.status()
        return build_strategy_under_test_inventory(
            guardrail_profiles=self.strategy_guardrail_profiles(),
            persistence_migration_revision=DIAGNOSTIC_SCHEMA_REVISION,
        )

    def validate_formal_strategy_set(
        self,
        *,
        candidates: tuple[FormalStrategySelectionCandidate, ...],
        expected_inventory_content_hash: str,
    ) -> FormalStrategySetValidation:
        """Validate an exact Strategy set against a current inventory read."""

        inventory = self.read_strategy_under_test_inventory()
        return validate_formal_strategy_set(
            inventory=inventory,
            candidates=candidates,
            expected_inventory_content_hash=expected_inventory_content_hash,
        )

    def recipe_authoring_capabilities(self) -> dict[str, object]:
        """Report configured authoring surfaces without pretending availability."""

        self.status()
        assistant = self._recipe_assistant
        return {
            "manual_authoring_available": True,
            "ai_authoring_available": assistant is not None,
            "ai_provider": (
                str(getattr(assistant, "provider", "configured"))
                if assistant is not None
                else None
            ),
            "ai_model": (
                str(getattr(assistant, "model", "configured"))
                if assistant is not None
                else None
            ),
        }

    def v1_product_surface_inventory(
        self,
    ) -> V1ProductSurfaceInventory:
        """Inventory the authoritative public application command surface."""

        self.status()
        commands = tuple(
            name
            for name, value in vars(type(self)).items()
            if not name.startswith("_") and callable(value)
        )
        return V1ProductSurfaceInventory(commands)

    def v1_diagnostic_configuration(
        self,
        *,
        selected_strategy_ids: tuple[str, ...] | None = None,
        selected_guardrail_profile_ids: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        """Resolve the explicit, user-visible V1 strategy/guardrail selection."""

        self.status()
        strategy_pairs = (
            (
                QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
            (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
        )
        supported_strategy_ids = tuple(item[0] for item in strategy_pairs)
        requested_strategy_ids = (
            supported_strategy_ids
            if selected_strategy_ids is None
            else selected_strategy_ids
        )
        unknown_strategies = set(requested_strategy_ids) - set(
            supported_strategy_ids
        )
        if unknown_strategies:
            raise ValueError(
                "Unknown V1 strategy selection: "
                + ", ".join(sorted(unknown_strategies))
            )
        if len(requested_strategy_ids) != len(set(requested_strategy_ids)):
            raise ValueError("V1 strategy selections must be unique")
        selected_strategies = tuple(
            strategy_id
            for strategy_id in supported_strategy_ids
            if strategy_id in requested_strategy_ids
        )

        profiles = self.strategy_guardrail_profiles()
        supported_profile_ids = tuple(profile.profile_id for profile in profiles)
        requested_profile_ids = (
            supported_profile_ids
            if selected_guardrail_profile_ids is None
            else selected_guardrail_profile_ids
        )
        unknown_profiles = set(requested_profile_ids) - set(
            supported_profile_ids
        )
        if unknown_profiles:
            raise ValueError(
                "Unknown V1 guardrail profile selection: "
                + ", ".join(sorted(unknown_profiles))
            )
        if len(requested_profile_ids) != len(set(requested_profile_ids)):
            raise ValueError("V1 guardrail profile selections must be unique")
        selected_profiles = tuple(
            profile
            for profile in profiles
            if profile.profile_id in requested_profile_ids
        )
        selected_profile_strategy_ids = {
            profile.strategy_id for profile in selected_profiles
        }

        errors: list[str] = []
        if set(selected_strategies) != set(supported_strategy_ids):
            errors.append("Select both representative V1 strategies.")
        if (
            len(selected_profiles) != len(strategy_pairs)
            or selected_profile_strategy_ids != set(selected_strategies)
        ):
            errors.append(
                "Select one versioned guardrail profile for each V1 strategy."
            )
        supported_strategies = []
        for strategy_id, strategy_version in strategy_pairs:
            manifest = ptrade_manifest_for(strategy_id, strategy_version)
            supported_strategies.append(
                {
                    **manifest.to_dict(),
                    "manifest_content_hash": manifest.content_hash,
                }
            )
        return {
            "status": "complete" if not errors else "incomplete",
            "supported_strategies": supported_strategies,
            "supported_guardrail_profiles": [
                profile.to_dict() for profile in profiles
            ],
            "selected_strategy_ids": list(selected_strategies),
            "selected_guardrail_profile_ids": [
                profile.profile_id for profile in selected_profiles
            ],
            "validation": {
                "complete": not errors,
                "errors": errors,
            },
        }

    def build_selected_diagnostic_evidence(
        self,
        campaign_id: str,
        *,
        selected_strategy_ids: tuple[str, ...],
        selected_guardrail_profile_ids: tuple[str, ...],
    ) -> DiagnosticEvidencePackage:
        """Build evidence only for a complete explicit V1 selection."""

        configuration = self.v1_diagnostic_configuration(
            selected_strategy_ids=selected_strategy_ids,
            selected_guardrail_profile_ids=(
                selected_guardrail_profile_ids
            ),
        )
        if configuration["status"] != "complete":
            raise ValueError(
                "Complete the V1 strategy and guardrail selection before "
                "building evidence"
            )
        selected_ids = set(selected_guardrail_profile_ids)
        selected_profiles = tuple(
            profile
            for profile in self.strategy_guardrail_profiles()
            if profile.profile_id in selected_ids
        )
        return self.build_diagnostic_evidence(
            campaign_id,
            guardrail_profiles=selected_profiles,
        )

    def build_diagnostic_evidence(
        self,
        campaign_id: str,
        *,
        guardrail_profiles: tuple[StrategyGuardrailProfile, ...] | None = None,
    ) -> DiagnosticEvidencePackage:
        self.status()
        try:
            package = self._diagnostic_evidence.build(
                campaign_id,
                (
                    guardrail_profiles
                    if guardrail_profiles is not None
                    else self.strategy_guardrail_profiles()
                ),
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            self._record_linked_diagnostic_evidence_failure(
                campaign_id,
                evidence_package_id=None,
            )
            raise
        try:
            self._reproduction.accept_evidence(package)
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            self._record_linked_diagnostic_evidence_failure(
                campaign_id,
                evidence_package_id=package.evidence_package_id,
            )
            raise
        return package

    def diagnostic_evidence_status(
        self,
        evidence_package_id: str,
    ) -> DiagnosticEvidencePackage:
        self.status()
        return self._diagnostic_evidence.get(evidence_package_id)

    def reproduction_manifests(
        self,
        evidence_package_id: str,
    ) -> tuple[ReproductionManifest, ...]:
        self.status()
        self._diagnostic_evidence.get(evidence_package_id)
        return cast(
            tuple[ReproductionManifest, ...],
            self._reproduction.manifests_for(evidence_package_id),
        )

    def reproduce_strategy_run(
        self,
        manifest_id: str,
    ) -> ReproductionReport:
        self.status()
        return self._reproduction.reproduce(manifest_id)

    def evaluate_v1_acceptance(
        self,
        *,
        campaign_id: str,
        evidence_package_id: str,
        reproduced_manifest_id: str,
        selected_strategy_ids: tuple[str, ...],
        selected_guardrail_profile_ids: tuple[str, ...],
        guided_ui_steps: tuple[str, ...],
        provenance_sections: tuple[str, ...],
        curve_overlays: tuple[str, ...],
    ) -> V1AcceptanceReport:
        """Evaluate V1 from accepted artifacts and authoritative product facts."""

        self.status()
        configuration = self.v1_diagnostic_configuration(
            selected_strategy_ids=selected_strategy_ids,
            selected_guardrail_profile_ids=(
                selected_guardrail_profile_ids
            ),
        )
        campaign = self._diagnostic_campaigns.get(campaign_id)
        evidence = self._diagnostic_evidence.get(evidence_package_id)
        if evidence.campaign_id != campaign.campaign_id:
            raise ValueError(
                "V1 acceptance evidence belongs to another campaign"
            )
        manifests = self._reproduction.manifests_for(evidence_package_id)
        selected_manifest_ids = {
            manifest.manifest_id for manifest in manifests
        }
        if reproduced_manifest_id not in selected_manifest_ids:
            raise ValueError(
                "V1 acceptance reproduction belongs to another evidence package"
            )
        reproduction = self._reproduction.latest_report(
            reproduced_manifest_id
        )
        if reproduction is None:
            raise ValueError(
                "V1 acceptance requires a completed reproduction report"
            )

        baseline_case = campaign.specification.baseline_case
        approved = (
            self._recipe_workbench.get_version(
                baseline_case.recipe_version_id
            )
            if baseline_case is not None
            else None
        )
        segments = self._historical_segments.list_segments()
        historical_segment = (
            next(
                (
                    segment
                    for segment in segments
                    if baseline_case is not None
                    and segment.segment_id
                    == baseline_case.historical_segment_id
                ),
                None,
            )
            if baseline_case is not None
            else None
        )

        catalog_view = self._transformation_catalog.to_dict()
        catalog_entries = cast(
            list[object],
            catalog_view["transformations"],
        )
        transformation_families = tuple(
            sorted(
                str(cast(Mapping[str, object], item)["family"])
                for item in catalog_entries
            )
        )

        strategy_versions_by_id = {
            QUENTX_SCENARIO_NATIVE_STRATEGY_ID: (
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION
            ),
            LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID: (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION
            ),
        }
        selected_strategy_versions = tuple(
            (strategy_id, strategy_versions_by_id[strategy_id])
            for strategy_id in selected_strategy_ids
            if strategy_id in strategy_versions_by_id
        )
        profile_ids = set(selected_guardrail_profile_ids)
        selected_profiles = tuple(
            profile
            for profile in self.strategy_guardrail_profiles()
            if profile.profile_id in profile_ids
        )
        selected_guardrail_profiles = tuple(
            (
                profile.strategy_id,
                profile.strategy_version,
                profile.profile_version,
            )
            for profile in selected_profiles
        )

        completed_layers = tuple(
            sorted(
                {
                    case.layer
                    for case in campaign.cases
                    if case.status == "completed"
                }
            )
        )
        isolated = campaign.specification.isolated_sensitivity_set
        isolated_counts: Counter[str] = Counter()
        if isolated is not None:
            isolated_counts.update(
                case.transformation_family
                for case in isolated.ordered_cases
            )
        isolated_cases = tuple(
            case
            for case in campaign.cases
            if case.layer == "isolated_sensitivity"
        )
        replicas_share_inputs = bool(isolated_cases) and all(
            self._completed_campaign_case_is_comparable(case)
            for case in isolated_cases
        )

        accepted_equity_curves = 0
        for manifest in manifests:
            accepted = manifest.accepted_result
            equity_curve = accepted.get("equity_curve")
            if isinstance(equity_curve, list) and equity_curve:
                accepted_equity_curves += 1
        next_node_activation = (
            self._accepted_orders_use_next_node_activation(manifests)
        )
        evidence_view = evidence.to_dict()
        findings = evidence_view.get("diagnostic_findings")
        finding_count = len(findings) if isinstance(findings, list) else 0
        explanation_authority = evidence_view.get(
            "ai_explanation_authority"
        )
        ai_explanation_is_limited = (
            isinstance(explanation_authority, Mapping)
            and explanation_authority.get("scope")
            == "sealed_findings_only"
            and explanation_authority.get(
                "may_recalculate_measurements"
            )
            is False
            and explanation_authority.get(
                "may_add_or_remove_findings"
            )
            is False
        )
        authoring_capabilities = self.recipe_authoring_capabilities()
        product_surface_inventory = self.v1_product_surface_inventory()
        cadence_proofs = self._completed_v1_cadence_proofs(campaign)

        facts = V1AcceptanceFacts(
            historical_segment_admitted=(
                historical_segment is not None
                and historical_segment.selection.market
                == "mainland-a-share"
                and historical_segment.selection.start_date
                <= historical_segment.selection.end_date
            ),
            source_provenance_available=(
                historical_segment is not None
                and all(
                    (
                        historical_segment.source_provenance.provider.strip(),
                        historical_segment.source_provenance.dataset.strip(),
                        historical_segment.source_provenance.version.strip(),
                    )
                )
            ),
            transformation_families=transformation_families,
            manual_recipe_authoring_available=(
                authoring_capabilities[
                    "manual_authoring_available"
                ]
                is True
            ),
            ai_recipe_authoring_available=(
                authoring_capabilities["ai_authoring_available"] is True
            ),
            recipe_validated=(
                approved is not None
                and approved.validation_result.is_valid
            ),
            recipe_approved=(
                approved is not None
                and bool(approved.approval_actor.strip())
            ),
            recipe_frozen=(
                approved is not None
                and approved.recipe.canonical_json()
                == approved.validation_result.validated_recipe.canonical_json()
                if (
                    approved is not None
                    and approved.validation_result.validated_recipe is not None
                )
                else False
            ),
            recipe_versioned=(
                approved is not None
                and approved.version_number >= 1
                and bool(approved.version_id.strip())
            ),
            recipe_hashed=(
                approved is not None
                and len(approved.content_hash) == 64
            ),
            selected_strategy_versions=selected_strategy_versions,
            selected_guardrail_profiles=selected_guardrail_profiles,
            supported_decision_cadences=tuple(
                proof.decision_cadence_minutes
                for proof in cadence_proofs
            ),
            accelerated_simulation_time=(
                configuration["status"] == "complete"
                and campaign.status == "completed"
                and accepted_equity_curves == len(manifests)
                and bool(manifests)
            ),
            next_node_activation=next_node_activation,
            campaign_type=campaign.specification.campaign_type,
            campaign_status=campaign.status,
            completed_campaign_layers=completed_layers,
            isolated_cases_by_family=tuple(
                sorted(isolated_counts.items())
            ),
            isolated_replicas_share_immutable_inputs=(
                replicas_share_inputs
            ),
            guided_ui_steps=guided_ui_steps,
            provenance_sections=provenance_sections,
            curve_overlays=curve_overlays,
            evidence_status=str(evidence_view.get("status", "unknown")),
            diagnostic_finding_count=finding_count,
            accepted_manifest_count=len(manifests),
            reproduction_status=reproduction.status,
            ai_explanation_is_limited_to_sealed_findings=(
                ai_explanation_is_limited
            ),
            product_surface_inventory=product_surface_inventory,
        )
        subject = V1AcceptanceSubject(
            campaign_id=campaign.campaign_id,
            evidence_package_id=evidence.evidence_package_id,
            evidence_artifact_hash=evidence.artifact_hash,
            measurement_artifact_hash=str(
                evidence_view["measurement_artifact_hash"]
            ),
            reproduction_manifest_id=reproduced_manifest_id,
            reproduction_attempt_id=reproduction.attempt_id,
            selected_strategy_versions=selected_strategy_versions,
            selected_guardrail_profiles=selected_guardrail_profiles,
            cadence_proofs=cadence_proofs,
            product_surface_inventory_hash=(
                product_surface_inventory.content_hash
            ),
        )
        return V1AcceptanceGate().evaluate(facts, subject)

    def _completed_v1_cadence_proofs(
        self,
        campaign: DiagnosticCampaignSnapshot,
    ) -> tuple[V1CadenceProof, ...]:
        baseline = campaign.specification.baseline_case
        if baseline is None:
            return ()
        grouped: dict[
            str,
            dict[str, list[CompletedStrategyRunEvidence]],
        ] = {}
        suffixes = {
            QUENTX_SCENARIO_NATIVE_STRATEGY_ID: ":quentx",
            LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID: ":live-minute",
        }
        versions = {
            QUENTX_SCENARIO_NATIVE_STRATEGY_ID: (
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION
            ),
            LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID: (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION
            ),
        }
        evidence = self._strategy_runs.completed_run_evidence(
            materialization_hash=baseline.materialization_hash,
            strategy_versions=tuple(versions.items()),
            decision_cadences=(30, 60),
        )
        for record in evidence:
            specification = record.specification
            suffix = suffixes.get(specification.strategy_id)
            if (
                suffix is None
                or specification.strategy_version
                != versions[specification.strategy_id]
                or specification.source_snapshot_id
                != baseline.source_snapshot_id
                or not specification.replica_id.endswith(suffix)
            ):
                continue
            campaign_replica_id = specification.replica_id[
                : -len(suffix)
            ]
            if not campaign_replica_id:
                continue
            grouped.setdefault(campaign_replica_id, {}).setdefault(
                specification.strategy_id,
                [],
            ).append(record)

        candidates: dict[int, list[V1CadenceProof]] = {
            30: [],
            60: [],
        }
        for campaign_replica_id, members in grouped.items():
            if set(members) != set(suffixes):
                continue
            for first in members[
                QUENTX_SCENARIO_NATIVE_STRATEGY_ID
            ]:
                for second in members[
                    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID
                ]:
                    ordered = (first, second)
                    try:
                        specification = BaselineCampaignSpecification(
                            campaign_replica_id=campaign_replica_id,
                            strategy_runs=(
                                first.specification,
                                second.specification,
                            ),
                        )
                    except ValueError:
                        continue
                    if (
                        not first.equity_times
                        or first.equity_times != second.equity_times
                        or not all(
                            self._cadence_proof_audit_matches(record)
                            for record in ordered
                        )
                    ):
                        continue
                    cadence = (
                        first.specification.decision_cadence_minutes
                    )
                    candidates[cadence].append(
                        V1CadenceProof(
                            decision_cadence_minutes=cadence,
                            campaign_id=specification.campaign_id,
                            run_ids=(first.run_id, second.run_id),
                            run_artifact_hashes=(
                                first.run_artifact_hash,
                                second.run_artifact_hash,
                            ),
                        )
                    )
        return tuple(
            sorted(proofs, key=lambda proof: proof.campaign_id)[0]
            for cadence in (30, 60)
            if (proofs := candidates[cadence])
        )

    @staticmethod
    def _cadence_proof_audit_matches(
        record: CompletedStrategyRunEvidence,
    ) -> bool:
        audit = record.ptrade_audit
        specification = record.specification
        return (
            audit is not None
            and audit.surface_version
            == specification.ptrade_surface_version
            and audit.manifest_hash
            == specification.ptrade_manifest_hash
            and audit.strategy_id == specification.strategy_id
            and audit.strategy_version == specification.strategy_version
            and audit.host_adapter_versions
            == (specification.ptrade_host_adapter_version,)
        )

    @staticmethod
    def _accepted_orders_use_next_node_activation(
        manifests: tuple[ReproductionManifest, ...],
    ) -> bool:
        if not manifests or any(
            manifest.specification.engine_version
            != STRATEGY_RUN_ENGINE_VERSION
            for manifest in manifests
        ):
            return False
        observed_order = False
        for manifest in manifests:
            orders = manifest.accepted_result.get("orders")
            if not isinstance(orders, list):
                return False
            for order in orders:
                if not isinstance(order, Mapping):
                    return False
                decision_time = order.get("decision_time")
                activation_time = order.get("activation_time")
                if not isinstance(decision_time, str) or not isinstance(
                    activation_time,
                    str,
                ):
                    return False
                try:
                    decision = datetime.fromisoformat(decision_time)
                    activation = datetime.fromisoformat(activation_time)
                    if (
                        (decision.utcoffset() is None)
                        != (activation.utcoffset() is None)
                        or activation <= decision
                    ):
                        return False
                except (TypeError, ValueError):
                    return False
                observed_order = True
        return observed_order

    @staticmethod
    def _completed_campaign_case_is_comparable(
        case: object,
    ) -> bool:
        attempts = getattr(case, "attempts", ())
        if not attempts:
            return False
        attempt = attempts[-1]
        campaign = getattr(attempt, "campaign", None)
        if campaign is None:
            return False
        view = campaign.to_dict()
        pinned = view.get("pinned_conditions")
        shared = view.get("shared_market_nodes")
        isolation = view.get("isolation")
        return (
            view.get("status") == "completed"
            and isinstance(pinned, Mapping)
            and bool(pinned.get("materialization_hash"))
            and bool(pinned.get("source_snapshot_id"))
            and bool(pinned.get("random_source"))
            and isinstance(shared, Mapping)
            and shared.get("identical_observed_timeline") is True
            and isinstance(isolation, Mapping)
            and isolation.get("verification_status") == "verified"
        )

    def reproduction_status(
        self,
        manifest_id: str,
    ) -> ReproductionReport | None:
        self.status()
        return self._reproduction.latest_report(manifest_id)

    def explain_diagnostic_findings(
        self,
        evidence_package_id: str,
    ) -> DiagnosticExplanationBundle:
        self.status()
        if self._finding_explanation_provider is None:
            raise RuntimeError(
                "No Diagnostic Finding explanation provider is configured"
            )
        return self._diagnostic_evidence.explain(
            evidence_package_id,
            self._finding_explanation_provider,
        )

    def create_manual_recipe_draft(
        self,
        payload: Mapping[str, object],
        *,
        author: str,
    ) -> ScenarioRecipeDraft:
        self.status()
        return self._recipe_workbench.create_draft(payload, author=author)

    def create_scenario_recipe_draft_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        payload: Mapping[str, object],
        author: str,
        authoring_mode: ScenarioLabAuthoringMode,
        assistant_attempt_id: str | None,
    ) -> ScenarioLabAuthoringResult:
        self.status()
        audited_draft: ScenarioRecipeDraft | None = None
        if authoring_mode == "ai_assisted":
            if assistant_attempt_id is None:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message="AI-assisted authoring requires an audited attempt.",
                )
            try:
                audit = self._recipe_workbench.get_ai_audit(
                    assistant_attempt_id
                )
            except ValueError:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "The AI Recipe Assistant attempt is unavailable from "
                        "the backend-owned audit history."
                    ),
                )
            if audit.attempt.draft_id is None:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "The audited AI Recipe Assistant attempt produced no "
                        f"typed Draft ({audit.attempt.status})."
                    ),
                )
            audited_draft = self._recipe_workbench.get_draft(
                audit.attempt.draft_id
            )
            payload_hash = hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest()
            if (
                audited_draft.payload_hash != payload_hash
                or audit.attempt.author != author
            ):
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "The typed Draft does not match the audited AI result "
                        "and author identity."
                    ),
                )
        return self._scenario_lab_authoring.create_draft(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            payload=payload,
            author=author,
            authoring_mode=authoring_mode,
            assistant_attempt_id=assistant_attempt_id,
            existing_draft=audited_draft,
        )

    def author_scenario_recipe_draft_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        intent: str,
        author: str,
    ) -> ScenarioLabAuthoringResult:
        """Durably claim one typed AI authoring command before provider I/O."""

        self.status()
        assistant = self._recipe_assistant
        if assistant is None:
            raise RuntimeError("No AI Recipe Assistant is configured")

        def author_once(
            requested_intent: str,
            requested_author: str,
            attempt_id: str,
        ) -> AIRecipeAuthoringResult:
            return self._recipe_workbench.author_with_ai(
                requested_intent,
                author=requested_author,
                assistant=assistant,
                admitted_segments=self._historical_segments.list_segments(),
                attempt_id=attempt_id,
            )

        return self._scenario_lab_authoring.author_draft_with_ai(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            intent=intent,
            author=author,
            author_with_ai=author_once,
        )

    def revise_scenario_recipe_draft_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        predecessor_draft_id: str,
        expected_draft_revision: int,
        payload: Mapping[str, object],
        author: str,
        based_on_version_id: str | None,
    ) -> ScenarioLabAuthoringResult:
        self.status()
        return self._scenario_lab_authoring.revise_draft(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            predecessor_draft_id=predecessor_draft_id,
            expected_draft_revision=expected_draft_revision,
            payload=payload,
            author=author,
            based_on_version_id=based_on_version_id,
        )

    def validate_scenario_recipe_draft_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        draft_id: str,
        expected_draft_revision: int,
        expected_payload_hash: str,
    ) -> ScenarioLabAuthoringResult:
        self.status()
        return self._scenario_lab_authoring.validate_draft(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            draft_id=draft_id,
            expected_draft_revision=expected_draft_revision,
            expected_payload_hash=expected_payload_hash,
        )

    def approve_scenario_recipe_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        draft_id: str,
        expected_draft_revision: int,
        expected_payload_hash: str,
        validation_id: str,
        actor: str,
    ) -> ScenarioLabAuthoringResult:
        """Approve one exact typed Draft validation through durable authority."""

        self.status()
        return self._scenario_lab_authoring.approve_recipe(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            draft_id=draft_id,
            expected_draft_revision=expected_draft_revision,
            expected_payload_hash=expected_payload_hash,
            validation_id=validation_id,
            actor=actor,
        )

    def scenario_recipe_draft_revisions(
        self,
    ) -> tuple[ScenarioRecipeDraftRevisionRecord, ...]:
        self.status()
        return self._scenario_lab_authoring.list_drafts()

    def scenario_recipe_validation_history(
        self,
    ) -> tuple[ScenarioRecipeValidationRecord, ...]:
        self.status()
        return self._scenario_lab_authoring.list_validations()

    def scenario_recipe_approval_history(
        self,
    ) -> tuple[ScenarioRecipeApprovalRecord, ...]:
        self.status()
        return self._scenario_lab_authoring.list_approvals()

    def materialize_scenario_recipe_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        recipe_version_id: str,
        expected_recipe_content_hash: str,
    ) -> ScenarioMaterializationResult:
        self.status()
        return self._scenario_lab_authoring.materialize_recipe(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            recipe_version_id=recipe_version_id,
            expected_recipe_content_hash=expected_recipe_content_hash,
        )

    def retry_scenario_materialization_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        predecessor_attempt_id: str,
        predecessor_task_handle_id: str,
    ) -> ScenarioMaterializationResult:
        self.status()
        return self._scenario_lab_authoring.retry_materialization(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            predecessor_attempt_id=predecessor_attempt_id,
            predecessor_task_handle_id=predecessor_task_handle_id,
        )

    def scenario_materialization_task_handles(
        self,
    ) -> tuple[ScenarioMaterializationTaskRecord, ...]:
        self.status()
        return self._scenario_lab_authoring.list_materialization_tasks()

    def replay_scenario_materialization_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        operation: str,
    ) -> ScenarioMaterializationResult | None:
        self.status()
        return self._scenario_lab_authoring.replay_materialization(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            operation=operation,
        )

    def replay_scenario_lab_authoring_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        operation: str,
    ) -> ScenarioLabAuthoringResult | None:
        self.status()
        return self._scenario_lab_authoring.replay(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            operation=operation,
        )

    def compose_formal_scenario_set_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        baseline_case_id: str,
        isolated_case_ids: tuple[str, ...],
        compound_case_ids: tuple[str, ...],
    ) -> ScenarioLabProjectionCommandResult:
        """Compose one backend-valid Formal Set or typed Quick Experiment."""

        self.status()

        def produce() -> tuple[str, str, object]:
            available_cases = self.list_available_diagnostic_campaign_cases()
            indexed = {
                item.case_id: item
                for item in available_cases
            }
            try:
                baseline = indexed[baseline_case_id]
                isolated = tuple(indexed[item] for item in isolated_case_ids)
                compounds = tuple(indexed[item] for item in compound_case_ids)
            except KeyError as exc:
                raise ValueError(
                    "A selected Campaign Case is no longer authoritative"
                ) from exc
            scenario_set = compose_formal_scenario_set(
                baseline_case=baseline,
                isolated_cases=isolated,
                compound_cases=compounds,
                authoritative_cases=(
                    self._active_formal_scenario_authority_cases(
                        available_cases
                    )
                ),
                projection_revision=(
                    max(
                        (
                            item.projection_revision
                            for item in self.scenario_lab_formal_scenario_sets()
                        ),
                        default=0,
                    )
                    + 1
                ),
            )
            return (
                "formal_scenario_set",
                scenario_set.scenario_set_id,
                scenario_set.to_dict(),
            )

        return self._scenario_lab_authoring.execute_projection_command(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            operation="compose_scenario_set",
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            producer=produce,
        )

    def scenario_lab_formal_scenario_sets(
        self,
    ) -> tuple[FormalScenarioSetRecord, ...]:
        self.status()
        records = tuple(
            FormalScenarioSetRecord.from_dict(
                cast(Mapping[str, object], json.loads(str(item.result_json)))
            )
            for item in self._scenario_lab_authoring.list_projection_commands(
                "formal_scenario_set"
            )
        )
        return tuple(
            sorted(records, key=lambda item: item.projection_revision)
        )

    def resolve_scenario_execution_assumptions_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        scenario_set_id: str,
        targets: tuple[tuple[str, str, datetime | None], ...],
    ) -> ScenarioLabProjectionCommandResult:
        """Resolve exact Strategy/Case assumptions through the run resolver."""

        self.status()

        def produce() -> tuple[str, str, object]:
            scenario_set = self._scenario_set_by_id(scenario_set_id)
            provided: dict[tuple[str, str], datetime | None] = {}
            for strategy_id, case_id, decision_time in targets:
                key = (strategy_id, case_id)
                if key in provided:
                    raise ValueError(
                        "Execution assumption targets must be unique"
                    )
                provided[key] = decision_time
            inventory = self.read_strategy_under_test_inventory()
            strategies = tuple(
                item
                for item in inventory.entries
                if item.required_for_v1_formal_campaign
            )
            expected_keys = {
                (strategy.strategy_id, case_id)
                for strategy in strategies
                for case_id in scenario_set.case_ids
            }
            unknown = tuple(sorted(set(provided) - expected_keys))
            if unknown:
                raise ValueError(
                    "Execution assumption target is not an exact formal "
                    f"Strategy/Case binding: {unknown!r}"
                )
            cases = {
                item.case_id: item
                for item in (
                    scenario_set.baseline_case,
                    *scenario_set.isolated_cases,
                    *scenario_set.compound_cases,
                )
            }
            resolutions = tuple(
                self._scenario_execution_target_resolution(
                    strategy=strategy,
                    case=cases[case_id],
                    decision_time=provided.get(
                        (strategy.strategy_id, case_id)
                    ),
                )
                for strategy in strategies
                for case_id in scenario_set.case_ids
            )
            resolution_id = scenario_execution_resolution_identity(
                scenario_set.scenario_set_id,
                scenario_set.projection_revision,
                resolutions,
            )
            record = ScenarioExecutionResolutionRecord(
                resolution_id=resolution_id,
                scenario_set_id=scenario_set.scenario_set_id,
                scenario_set_projection_revision=(
                    scenario_set.projection_revision
                ),
                targets=resolutions,
                formal_handoff_eligible=(
                    scenario_set.formal_handoff_eligible
                    and all(item.state == "resolved" for item in resolutions)
                ),
                projection_revision=(
                    max(
                        (
                            item.projection_revision
                            for item in self.scenario_lab_execution_resolutions()
                        ),
                        default=0,
                    )
                    + 1
                ),
            )
            return (
                "scenario_execution_resolution",
                record.resolution_id,
                record.to_dict(),
            )

        return self._scenario_lab_authoring.execute_projection_command(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            operation="resolve_execution_assumptions",
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            producer=produce,
        )

    def scenario_lab_execution_resolutions(
        self,
    ) -> tuple[ScenarioExecutionResolutionRecord, ...]:
        self.status()
        records = tuple(
            ScenarioExecutionResolutionRecord.from_dict(
                cast(Mapping[str, object], json.loads(str(item.result_json)))
            )
            for item in self._scenario_lab_authoring.list_projection_commands(
                "scenario_execution_resolution"
            )
        )
        return tuple(
            sorted(records, key=lambda item: item.projection_revision)
        )

    def select_formal_scenario_set_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        scenario_set_id: str,
        case_ids: tuple[str, ...],
        originating_view_revision: int,
        execution_resolution_id: str,
    ) -> ScenarioLabProjectionCommandResult:
        """Persist one immutable, exact, formal handoff selection context."""

        self.status()

        def produce() -> tuple[str, str, object]:
            scenario_set = self._scenario_set_by_id(scenario_set_id)
            resolution = self._scenario_execution_resolution_by_id(
                execution_resolution_id
            )
            selection = create_scenario_selection_context(
                scenario_set=scenario_set,
                execution_resolution=resolution,
                case_ids=case_ids,
                originating_view_revision=originating_view_revision,
                source_revision=expected_source_revision,
                source_generation=expected_source_generation,
                selection_revision=(
                    len(self.scenario_lab_selection_contexts()) + 1
                ),
            )
            return (
                "scenario_selection_context",
                selection.selection_context_id,
                selection.to_dict(),
            )

        return self._scenario_lab_authoring.execute_projection_command(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            operation="select_formal_scenario_set",
            expected_source_revision=expected_source_revision,
            expected_source_generation=expected_source_generation,
            producer=produce,
        )

    def scenario_lab_selection_contexts(
        self,
    ) -> tuple[ScenarioSelectionContextRecord, ...]:
        self.status()
        stored = tuple(
            ScenarioSelectionContextRecord.from_dict(
                cast(Mapping[str, object], json.loads(str(item.result_json)))
            )
            for item in self._scenario_lab_authoring.list_projection_commands(
                "scenario_selection_context"
            )
        )
        stored = tuple(
            sorted(stored, key=lambda item: item.selection_revision)
        )
        if not stored:
            return ()
        scenario_sets = self.scenario_lab_formal_scenario_sets()
        resolutions = self.scenario_lab_execution_resolutions()
        available_cases = self.list_available_diagnostic_campaign_cases()
        authoritative_cases = {
            item.case_id: item
            for item in self._active_formal_scenario_authority_cases(
                available_cases
            )
        }
        authoritative_strategies = {
            item.strategy_id: item
            for item in self.read_strategy_under_test_inventory().entries
            if item.required_for_v1_formal_campaign
        }
        statuses: tuple[ScenarioSelectionContextStatus, ...] = tuple(
            self._scenario_selection_context_authority_status(
                item,
                scenario_sets=scenario_sets,
                resolutions=resolutions,
                authoritative_cases=authoritative_cases,
                authoritative_strategies=authoritative_strategies,
            )
            if index == len(stored) - 1
            else "stale"
            for index, item in enumerate(stored)
        )
        return tuple(
            replace(
                item,
                status=status,
                formal_handoff_eligible=(
                    item.formal_handoff_eligible
                    and index == len(stored) - 1
                    and status == "current"
                ),
            )
            for index, (item, status) in enumerate(
                zip(stored, statuses, strict=True)
            )
        )

    def _scenario_selection_context_authority_status(
        self,
        context: ScenarioSelectionContextRecord,
        *,
        scenario_sets: tuple[FormalScenarioSetRecord, ...],
        resolutions: tuple[ScenarioExecutionResolutionRecord, ...],
        authoritative_cases: Mapping[str, DiagnosticCampaignCase],
        authoritative_strategies: Mapping[
            str, StrategyUnderTestInventoryEntry
        ],
    ) -> ScenarioSelectionContextStatus:
        if not scenario_sets or not resolutions:
            return "unavailable"
        if (
            context.scenario_set_id != scenario_sets[-1].scenario_set_id
            or context.scenario_set_projection_revision
            != scenario_sets[-1].projection_revision
            or context.execution_resolution_id
            != resolutions[-1].resolution_id
            or context.execution_resolution_projection_revision
            != resolutions[-1].projection_revision
        ):
            return "stale"
        scenario_set = scenario_sets[-1]
        resolution = resolutions[-1]
        if (
            not scenario_set.formal_handoff_eligible
            or not resolution.formal_handoff_eligible
            or resolution.scenario_set_id != scenario_set.scenario_set_id
            or resolution.scenario_set_projection_revision
            != scenario_set.projection_revision
            or context.case_ids != scenario_set.case_ids
        ):
            return "conflict"
        selected_cases = (
            scenario_set.baseline_case,
            *scenario_set.isolated_cases,
            *scenario_set.compound_cases,
        )
        expected_case_bindings = tuple(
            ScenarioSelectionCaseBindingRecord.from_case(item)
            for item in selected_cases
        )
        if context.case_bindings != expected_case_bindings:
            return "conflict"
        if any(
            authoritative_cases.get(item.case_id) != item
            for item in selected_cases
        ):
            return "stale"
        current_catalog_version = str(
            self.transformation_catalog_view()["catalog_version"]
        )
        if any(
            item.transformation_catalog_version
            != current_catalog_version
            for item in context.case_bindings
        ):
            return "stale"
        expected_strategy_bindings: list[
            ScenarioSelectionStrategyBindingRecord
        ] = []
        for strategy_id in sorted(authoritative_strategies):
            strategy = authoritative_strategies[strategy_id]
            profile = strategy.guardrail_profile
            if not strategy.formal_campaign_eligible or profile is None:
                return "stale"
            expected_strategy_bindings.append(
                ScenarioSelectionStrategyBindingRecord(
                    strategy_id=strategy.strategy_id,
                    strategy_version=strategy.strategy_version,
                    compatibility_manifest_hash=(
                        strategy.compatibility.content_hash
                    ),
                    guardrail_profile_id=profile.profile_id,
                    guardrail_profile_version=profile.profile_version,
                    execution_policy_version=(
                        BASELINE_EXECUTION_POLICY_VERSION
                    ),
                )
            )
        if context.strategy_bindings != tuple(expected_strategy_bindings):
            return "stale"
        cases_by_id = {item.case_id: item for item in selected_cases}
        recomputed_targets: list[
            ScenarioExecutionTargetResolutionRecord
        ] = []
        try:
            for target in resolution.targets:
                strategy = authoritative_strategies[target.strategy_id]
                case = cases_by_id[target.campaign_case_id]
                recomputed_targets.append(
                    self._scenario_execution_target_resolution(
                        strategy=strategy,
                        case=case,
                        decision_time=target.decision_time,
                    )
                )
        except (KeyError, OSError, TypeError, ValueError):
            return "stale"
        recomputed = tuple(recomputed_targets)
        if (
            recomputed != resolution.targets
            or scenario_execution_resolution_identity(
                scenario_set.scenario_set_id,
                scenario_set.projection_revision,
                recomputed,
            )
            != resolution.resolution_id
        ):
            return "stale"
        return "current"

    def replay_scenario_lab_projection_command(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        operation: str,
    ) -> ScenarioLabProjectionCommandResult | None:
        self.status()
        return self._scenario_lab_authoring.replay_projection_command(
            command_id=command_id,
            idempotency_identity=idempotency_identity,
            canonical_content_identity=canonical_content_identity,
            operation=operation,
        )

    def _scenario_set_by_id(self, identity: str) -> FormalScenarioSetRecord:
        matches = tuple(
            item
            for item in self.scenario_lab_formal_scenario_sets()
            if item.scenario_set_id == identity
        )
        if not matches:
            raise ValueError("Formal Scenario Set is unavailable")
        return matches[-1]

    def _scenario_execution_resolution_by_id(
        self,
        identity: str,
    ) -> ScenarioExecutionResolutionRecord:
        matches = tuple(
            item
            for item in self.scenario_lab_execution_resolutions()
            if item.resolution_id == identity
        )
        if not matches:
            raise ValueError("Scenario execution resolution is unavailable")
        return matches[-1]

    def _scenario_execution_target_resolution(
        self,
        *,
        strategy: StrategyUnderTestInventoryEntry,
        case: DiagnosticCampaignCase,
        decision_time: datetime | None,
    ) -> ScenarioExecutionTargetResolutionRecord:
        strategy_id = strategy.strategy_id
        strategy_version = strategy.strategy_version
        compatibility = strategy.compatibility
        profile = strategy.guardrail_profile
        if not strategy.formal_campaign_eligible or profile is None:
            raise ValueError(
                f"Strategy {strategy_id} is unavailable for a Formal Campaign"
            )
        authoritative = {
            item.case_id: item
            for item in self.list_available_diagnostic_campaign_cases()
        }.get(case.case_id)
        if authoritative != case:
            raise ValueError("Campaign Case identity is no longer authoritative")
        path = self._load_verified_reference_path(case.materialization_hash)
        resolved = self._resolved_execution_conditions_for_case(case, path)
        simulation_times = tuple(
            sorted({item.simulation_time for item in path.nodes})
        )
        after_decision_time: datetime | None = None
        activation_time: datetime | None = None
        reasons: tuple[str, ...] = ()
        state = "resolved"
        if decision_time is None:
            state = "not_yet_resolved"
            reasons = ("Decision Time is required to resolve activation.",)
        else:
            after_index = next(
                (
                    index
                    for index, value in enumerate(simulation_times)
                    if value > decision_time
                ),
                None,
            )
            if after_index is None:
                state = "unavailable"
                reasons = (
                    "No market node exists strictly later than Decision Time.",
                )
            else:
                after_decision_time = simulation_times[after_index]
                activation_index = (
                    after_index + resolved.effective.latency_nodes
                )
                if activation_index >= len(simulation_times):
                    state = "unavailable"
                    reasons = (
                        "Latency moves activation beyond the Reference Market Path.",
                    )
                else:
                    activation_time = simulation_times[activation_index]
        return ScenarioExecutionTargetResolutionRecord(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            compatibility_manifest_hash=compatibility.content_hash,
            guardrail_profile_id=profile.profile_id,
            guardrail_profile_version=profile.profile_version,
            campaign_case_id=case.case_id,
            state=cast(ScenarioExecutionResolutionState, state),
            decision_time=decision_time,
            after_decision_time=after_decision_time,
            activation_time=activation_time,
            decision_cadence_minutes=case.decision_cadence_minutes,
            decision_grid=(
                f"{case.decision_cadence_minutes}-minute simulation-time grid"
            ),
            activation_policy=(
                "first Reference Market Path node strictly later than "
                "Decision Time, then effective latency_nodes"
            ),
            execution_policy_version=BASELINE_EXECUTION_POLICY_VERSION,
            resolved_conditions=resolved,
            reasons=reasons,
        )

    def _scenario_recipe_validation_dependencies(
        self,
        draft: ScenarioRecipeDraft,
        validation: RecipeValidationResult,
    ) -> ScenarioRecipeValidationDependencyRecord:
        segments = {
            item.segment_id: item
            for item in self._historical_segments.list_segments()
        }
        payload = draft.payload
        segment_id = str(payload.get("historical_segment_id") or "")
        try:
            segment = segments[segment_id]
        except KeyError as error:
            raise ValueError(
                "Validated Scenario Recipe dependency segment is unavailable"
            ) from error
        snapshot = self._historical_segments.get_source_snapshot(
            segment.source_snapshot_id
        )
        schema = ScenarioRecipeV1.stable_json_schema()
        schema_json = canonical_json(schema)
        catalog_payload = self._transformation_catalog.to_dict()
        catalog_json = canonical_json(catalog_payload)
        implementations: list[str] = []
        causality_rules: set[str] = set()
        observations: list[tuple[str, str, str]] = [
            (
                f"historical-segment:{segment.segment_id}",
                "compatible",
                "The exact Historical Market Segment is admitted.",
            )
        ]
        transformations = payload.get("transformations", ())
        if isinstance(transformations, Sequence) and not isinstance(
            transformations, (str, bytes)
        ):
            for item in transformations:
                if not isinstance(item, Mapping):
                    continue
                transformation_id = str(item.get("transformation_id") or "")
                try:
                    entry = self._transformation_catalog.get_entry(
                        transformation_id
                    )
                except ValueError:
                    observations.append(
                        (
                            f"transformation:{transformation_id}",
                            "incompatible",
                            "The transformation is not registered.",
                        )
                    )
                    continue
                implementations.append(
                    f"{entry.transformation_id}@{entry.implementation_version}"
                )
                causality_rules.update(entry.causality_constraints)
                observations.append(
                    (
                        f"transformation:{entry.transformation_id}",
                        "compatible",
                        "The registered implementation and policy are bound.",
                    )
                )
        if validation.issues:
            observations.extend(
                (
                    f"validation-rule:{issue.rule}",
                    "incompatible",
                    issue.message,
                )
                for issue in validation.issues
            )
        market_rule_profile = str(
            payload.get("market_rule_profile") or ""
        )
        return ScenarioRecipeValidationDependencyRecord(
            historical_segment_id=segment.segment_id,
            historical_segment_content_hash=segment.content_hash,
            source_snapshot_id=snapshot.snapshot_id,
            source_snapshot_content_hash=snapshot.content_hash,
            recipe_schema_identity=str(schema["$id"]),
            recipe_schema_hash=hashlib.sha256(
                schema_json.encode("utf-8")
            ).hexdigest(),
            transformation_catalog_version=(
                self._transformation_catalog.catalog_version
            ),
            transformation_catalog_hash=hashlib.sha256(
                catalog_json.encode("utf-8")
            ).hexdigest(),
            transformation_implementation_identities=tuple(
                sorted(implementations)
            ),
            data_policy=str(payload.get("data_policy") or ""),
            causality_rule_identities=tuple(sorted(causality_rules)),
            market_rule_profile_version=market_rule_profile,
            market_rule_profile_hash=hashlib.sha256(
                market_rule_profile.encode("utf-8")
            ).hexdigest(),
            compatibility_observations=tuple(observations),
        )

    def author_recipe_with_ai(
        self,
        intent: str,
        *,
        author: str,
    ) -> AIRecipeAuthoringResult:
        self.status()
        if self._recipe_assistant is None:
            raise RuntimeError("No AI Recipe Assistant is configured")
        return self._recipe_workbench.author_with_ai(
            intent,
            author=author,
            assistant=self._recipe_assistant,
            admitted_segments=self._historical_segments.list_segments(),
        )

    def get_ai_recipe_audit(self, attempt_id: str) -> AIRecipeAuditRecord:
        self.status()
        return self._recipe_workbench.get_ai_audit(attempt_id)

    def validate_recipe_draft(self, draft_id: str) -> RecipeValidationResult:
        self.status()
        return self._recipe_workbench.validate_draft(
            draft_id,
            admitted_segments=self._historical_segments.list_segments(),
        )

    def approve_recipe_draft(
        self,
        draft_id: str,
        *,
        actor: str,
    ) -> ApprovedScenarioRecipeVersion:
        self.status()
        return self._recipe_workbench.approve_draft(draft_id, actor=actor)

    def revise_recipe_version(
        self,
        version_id: str,
        payload: Mapping[str, object],
        *,
        author: str,
    ) -> ScenarioRecipeDraft:
        self.status()
        return self._recipe_workbench.revise_version(
            version_id,
            payload,
            author=author,
        )

    def get_recipe_version(
        self,
        version_id: str,
    ) -> ApprovedScenarioRecipeVersion:
        self.status()
        return self._recipe_workbench.get_version(version_id)

    def open_scenario_market_view(
        self,
        artifact_hash: str,
        *,
        at_time: datetime,
    ) -> ScenarioMarketView:
        self.status()
        if self._scenario_materializer is None:
            raise RuntimeError("No Scenario Materializer is configured")
        return ScenarioMarketView(
            self._scenario_materializer.get(artifact_hash),
            initial_cursor=at_time,
        )

    def preview_reference_market_path(
        self,
        artifact_hash: str,
        *,
        at_time: datetime,
    ) -> dict[str, object]:
        self.status()
        if self._scenario_materializer is None:
            raise RuntimeError("No Scenario Materializer is configured")
        path = self._scenario_materializer.get(artifact_hash)
        view = ScenarioMarketView(path, initial_cursor=at_time)
        snapshot = cast(dict[str, object], view.snapshot().to_dict())
        snapshot.update(
            {
                "artifact_hash": view.artifact_hash,
                "reconstructed": path.reconstructed,
                "source_resolution": path.source_resolution,
                "runtime_resolution": path.runtime_resolution,
                "expander_version": path.expander_version,
                "reconstruction_notice": path.reconstruction_notice,
                "applied_transformations": [
                    transformation.to_dict()
                    for transformation in path.applied_transformations
                ],
                "path_statistics": path.path_statistics(at_time=at_time),
            }
        )
        return snapshot

    def compare_reference_market_paths(
        self,
        baseline_artifact_hash: str,
        transformed_artifact_hash: str,
        *,
        at_time: datetime,
    ) -> dict[str, object]:
        self.status()
        if self._scenario_materializer is None:
            raise RuntimeError("No Scenario Materializer is configured")
        baseline_path = self._scenario_materializer.get(baseline_artifact_hash)
        transformed_path = self._scenario_materializer.get(
            transformed_artifact_hash
        )
        if baseline_path.applied_transformations:
            raise ValueError("The baseline preview must use an untransformed path")
        if not transformed_path.applied_transformations:
            raise ValueError("The transformed preview must use a transformed path")
        comparable_identity = (
            baseline_path.segment_id,
            baseline_path.segment_content_hash,
            baseline_path.source_snapshot_id,
            baseline_path.seed,
        )
        if comparable_identity != (
            transformed_path.segment_id,
            transformed_path.segment_content_hash,
            transformed_path.source_snapshot_id,
            transformed_path.seed,
        ):
            raise ValueError(
                "Baseline and transformed previews require the same source and seed"
            )
        baseline = self.preview_reference_market_path(
            baseline_artifact_hash,
            at_time=at_time,
        )
        transformed = self.preview_reference_market_path(
            transformed_artifact_hash,
            at_time=at_time,
        )
        baseline_market = cast(dict[str, object], baseline["market_context"])
        transformed_market = cast(dict[str, object], transformed["market_context"])
        market_return_delta = Decimal(str(transformed_market["return"])) - Decimal(
            str(baseline_market["return"])
        )
        return {
            "status": "ready",
            "simulation_time": at_time.isoformat(),
            "baseline": baseline,
            "transformed": transformed,
            "market_return_delta": format(market_return_delta.normalize(), "f"),
        }

    def start_baseline_strategy_run(
        self,
        recipe_version_id: str,
        materialization_hash: str,
        *,
        initial_cash: Decimal,
        order_shares: int,
        replica_id: str,
        strategy_id: str = REFERENCE_STRATEGY_ID,
        strategy_version: str = REFERENCE_STRATEGY_VERSION,
    ) -> StrategyRunSnapshot:
        """Start one registered strategy on an approved anchored path."""

        specification = self._baseline_strategy_run_specification(
            recipe_version_id,
            materialization_hash,
            initial_cash=initial_cash,
            order_shares=order_shares,
            replica_id=replica_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        return self._strategy_runs.start(specification)

    def run_baseline_campaign(
        self,
        recipe_version_id: str,
        materialization_hash: str,
        *,
        initial_cash: Decimal,
        order_shares: int,
        campaign_replica_id: str,
        nodes_per_batch: int = 10_000,
        approved_strategies: tuple[
            DiagnosticCampaignStrategySelection,
            ...,
        ] = (),
    ) -> BaselineCampaignSnapshot:
        """Run both V1 representative strategies on isolated path replicas."""

        if approved_strategies:
            if len(approved_strategies) != 2:
                raise ValueError(
                    "Baseline Campaign requires exactly two approved Strategies"
                )
            ordered = tuple(
                sorted(
                    approved_strategies,
                    key=lambda candidate: candidate.strategy_id,
                )
            )
            strategy_members = (
                (
                    ordered[0].strategy_id,
                    ordered[0].strategy_version,
                    ordered[0].strategy_id,
                ),
                (
                    ordered[1].strategy_id,
                    ordered[1].strategy_version,
                    ordered[1].strategy_id,
                ),
            )
        else:
            strategy_members = (
                (
                    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
                    "quentx",
                ),
                (
                    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
                    "live-minute",
                ),
            )
        first, second = strategy_members
        specifications = (
            self._baseline_strategy_run_specification(
                recipe_version_id,
                materialization_hash,
                initial_cash=initial_cash,
                order_shares=order_shares,
                replica_id=f"{campaign_replica_id}:{first[2]}",
                strategy_id=first[0],
                strategy_version=first[1],
            ),
            self._baseline_strategy_run_specification(
                recipe_version_id,
                materialization_hash,
                initial_cash=initial_cash,
                order_shares=order_shares,
                replica_id=f"{campaign_replica_id}:{second[2]}",
                strategy_id=second[0],
                strategy_version=second[1],
            ),
        )
        campaign = BaselineCampaignSpecification(
            campaign_replica_id=campaign_replica_id,
            strategy_runs=specifications,
        )
        return BaselineCampaignRunner(self._strategy_runs).run(
            campaign,
            nodes_per_batch=nodes_per_batch,
        )

    def _execute_isolated_sensitivity_case(
        self,
        specification: IsolatedSensitivitySetSpecification,
        case: SensitivityCampaignCase,
        attempt_number: int,
        nodes_per_batch: int,
    ) -> BaselineCampaignSnapshot:
        campaign_replica_id = (
            f"{specification.sensitivity_set_replica_id}:"
            f"{case.case_id}:attempt-{attempt_number}"
        )
        return self.run_baseline_campaign(
            case.recipe_version_id,
            case.materialization_hash,
            initial_cash=specification.initial_cash,
            order_shares=specification.order_shares,
            campaign_replica_id=campaign_replica_id,
            nodes_per_batch=nodes_per_batch,
        )

    def _require_linked_campaign_running(self, campaign_id: str) -> None:
        target = self._diagnostic_tasks.lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            campaign_id,
        )
        if (
            target is not None
            and target.lifecycle is not DiagnosticTaskLifecycle.RUNNING
        ):
            raise ValueError(
                "Linked Formal Diagnostic Campaign is not running."
            )

    def _linked_campaign_executable_case_ids(
        self,
        campaign: DiagnosticCampaignSnapshot,
        *,
        max_cases: int | None,
    ) -> tuple[str, ...] | None:
        campaign_target = self._diagnostic_tasks.lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            campaign.campaign_id,
        )
        if campaign_target is None:
            return None
        if max_cases is not None and max_cases <= 0:
            raise ValueError("max cases must be positive")
        selected: list[str] = []
        for case in campaign.cases:
            if case.status != "planned":
                continue
            target = self._diagnostic_tasks.lifecycle_target(
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                f"{campaign.campaign_id}:{case.case_id}",
            )
            if target is None:
                raise ValueError(
                    "Linked Formal Diagnostic Campaign node is unavailable."
                )
            if target.lifecycle not in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
            }:
                break
            selected.append(case.case_id)
            if max_cases is not None and len(selected) == max_cases:
                break
        return tuple(selected)

    def _sync_linked_diagnostic_campaign(
        self,
        campaign: DiagnosticCampaignSnapshot,
    ) -> None:
        campaign_target = self._diagnostic_tasks.lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            campaign.campaign_id,
        )
        if campaign_target is None:
            return
        task = self._diagnostic_tasks.get(campaign_target.task_id)
        if task is None or task.campaign_handoff is None:
            raise ValueError(
                "Linked Diagnostic Task Campaign is unavailable."
            )
        self._diagnostic_tasks.sync_campaign_progress(
            self._diagnostic_task_campaign_handoff(task, campaign)
        )

    def _seal_linked_diagnostic_task_evidence(
        self,
        campaign: DiagnosticCampaignSnapshot,
    ) -> None:
        campaign_target = self._diagnostic_tasks.lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            campaign.campaign_id,
        )
        if campaign_target is None:
            return
        task = self._diagnostic_tasks.get(campaign_target.task_id)
        if task is None or task.campaign_handoff is None:
            raise ValueError(
                "Linked Diagnostic Task Campaign is unavailable."
            )
        if (
            task.campaign_handoff.campaign_lifecycle
            is not DiagnosticTaskLifecycle.COMPLETED
        ):
            return
        if (
            task.campaign_handoff.evidence_state
            is not DiagnosticEvidenceHandoffState.PENDING
        ):
            return
        package: DiagnosticEvidencePackage | None = None
        try:
            package = self.build_selected_diagnostic_evidence(
                campaign.campaign_id,
                selected_strategy_ids=tuple(
                    item.strategy_id
                    for item in task.configuration.strategy_selections
                ),
                selected_guardrail_profile_ids=tuple(
                    item.guardrail_profile_id
                    for item in task.configuration.strategy_selections
                ),
            )
            manifests = self.reproduction_manifests(
                package.evidence_package_id
            )
            handed_run_ids = tuple(
                run.run_id
                for node in task.campaign_handoff.campaign_nodes
                for attempt in node.attempts
                if attempt.attempt_id == node.active_attempt_id
                for run in attempt.runs
            )
            manifest_run_ids = tuple(
                manifest.run_id for manifest in manifests
            )
            manifest_ids = tuple(
                manifest.manifest_id for manifest in manifests
            )
            if (
                package.campaign_id != campaign.campaign_id
                or not handed_run_ids
                or len(manifests) != len(handed_run_ids)
                or len(set(handed_run_ids)) != len(handed_run_ids)
                or len(set(manifest_run_ids)) != len(manifest_run_ids)
                or len(set(manifest_ids)) != len(manifest_ids)
                or set(manifest_run_ids) != set(handed_run_ids)
                or any(
                    manifest.evidence_package_id
                    != package.evidence_package_id
                    for manifest in manifests
                )
            ):
                raise ValueError(
                    "Diagnostic Evidence identity graph does not match "
                    "the accepted Campaign run identities"
                )
            manifest_by_run_id = {
                manifest.run_id: manifest.manifest_id
                for manifest in manifests
            }
            self._diagnostic_tasks.sync_campaign_progress(
                replace(
                    task.campaign_handoff,
                    campaign_nodes=tuple(
                        replace(
                            node,
                            attempts=tuple(
                                replace(
                                    attempt,
                                    runs=tuple(
                                        replace(
                                            run,
                                            reproduction_manifest_id=(
                                                manifest_by_run_id.get(
                                                    run.run_id
                                                )
                                            ),
                                        )
                                        for run in attempt.runs
                                    ),
                                )
                                for attempt in node.attempts
                            ),
                        )
                        for node in task.campaign_handoff.campaign_nodes
                    ),
                    evidence_state=(
                        DiagnosticEvidenceHandoffState.AVAILABLE
                    ),
                    evidence_package_id=package.evidence_package_id,
                    reproduction_manifest_id=manifests[0].manifest_id,
                )
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            self._record_linked_diagnostic_evidence_failure(
                campaign.campaign_id,
                evidence_package_id=(
                    None
                    if package is None
                    else package.evidence_package_id
                ),
            )

    def _record_linked_diagnostic_evidence_failure(
        self,
        campaign_id: str,
        *,
        evidence_package_id: str | None,
    ) -> None:
        campaign_target = self._diagnostic_tasks.lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            campaign_id,
        )
        if campaign_target is None:
            return
        task = self._diagnostic_tasks.get(campaign_target.task_id)
        if task is None or task.campaign_handoff is None:
            return
        if (
            task.campaign_handoff.campaign_lifecycle
            is not DiagnosticTaskLifecycle.COMPLETED
            or task.campaign_handoff.evidence_state
            is not DiagnosticEvidenceHandoffState.PENDING
        ):
            return
        self._diagnostic_tasks.sync_campaign_progress(
            replace(
                task.campaign_handoff,
                evidence_state=(
                    DiagnosticEvidenceHandoffState.FAILED
                    if evidence_package_id is None
                    else DiagnosticEvidenceHandoffState.PARTIAL
                ),
                evidence_package_id=evidence_package_id,
                evidence_error_code=(
                    "diagnostic_evidence_integrity_failed"
                ),
                evidence_error_message=(
                    "Diagnostic Evidence could not be sealed into an exact "
                    "Evidence and Reproduction Manifest identity graph."
                ),
            )
        )

    def _execute_diagnostic_campaign_case(
        self,
        specification: DiagnosticCampaignSpecification,
        layer: DiagnosticCampaignExecutionLayer,
        case: CampaignCaseSpecification,
        attempt_number: int,
        nodes_per_batch: int,
    ) -> BaselineCampaignSnapshot:
        campaign_replica_id = (
            f"{specification.campaign_replica_id}:{layer}:"
            f"{case.case_id}:attempt-{attempt_number}"
        )
        return self.run_baseline_campaign(
            case.recipe_version_id,
            case.materialization_hash,
            initial_cash=specification.initial_cash,
            order_shares=specification.order_shares,
            campaign_replica_id=campaign_replica_id,
            nodes_per_batch=nodes_per_batch,
            approved_strategies=specification.approved_strategies,
        )

    def _resolved_execution_conditions_for_case(
        self,
        case: DiagnosticCampaignCase,
        path: MaterializedMarketPath,
    ) -> ResolvedExecutionConditions:
        approved = self._recipe_workbench.get_version(case.recipe_version_id)
        authoritative = self._diagnostic_campaign_case_from_existing_path(
            approved,
            path,
        )
        if authoritative != case:
            raise ValueError(
                "Campaign Case execution inputs are no longer authoritative"
            )
        return self._resolved_execution_conditions_for_recipe_path(
            approved,
            path,
        )

    def _resolved_execution_conditions_for_recipe_path(
        self,
        approved: ApprovedScenarioRecipeVersion,
        path: MaterializedMarketPath,
    ) -> ResolvedExecutionConditions:
        execution = approved.recipe.execution_conditions
        requested_conditions = RequestedExecutionAssumptions(
            commission_bps=execution.commission_bps,
            slippage_bps=execution.slippage_bps,
            max_fill_fraction=execution.max_fill_fraction,
            latency_nodes=execution.latency_nodes,
            allow_partial_fills=execution.allow_partial_fills,
        )
        scenario_overrides = dict(
            next(
                (
                    item.parameters
                    for item in path.applied_transformations
                    if item.family == "execution-stress"
                ),
                (),
            )
        )
        resolved_conditions = resolve_execution_conditions(
            requested_conditions,
            scenario_overrides,
        )
        approved_overrides = dict(
            next(
                (
                    item.parameters
                    for item in approved.recipe.transformations
                    if item.transformation_id == "execution-stress.v1"
                ),
                {},
            )
        )
        if resolved_conditions != resolve_execution_conditions(
            requested_conditions,
            approved_overrides,
        ):
            raise ValueError(
                "Materialized execution conditions do not match the approved recipe"
            )
        return resolved_conditions

    def _baseline_strategy_run_specification(
        self,
        recipe_version_id: str,
        materialization_hash: str,
        *,
        initial_cash: Decimal,
        order_shares: int,
        replica_id: str,
        strategy_id: str,
        strategy_version: str,
    ) -> StrategyRunSpecification:
        self.status()
        approved = self._recipe_workbench.get_version(recipe_version_id)
        expected_path = self.materialize_reference_path(recipe_version_id)
        if expected_path.artifact_hash != materialization_hash:
            raise ValueError(
                "Materialized inputs do not match the approved recipe"
            )
        path = self._load_reference_path(materialization_hash)
        if (
            approved.recipe.historical_segment_id,
            approved.recipe.materialization_seed,
            approved.recipe.market_rule_profile,
        ) != (
            path.segment_id,
            path.seed,
            path.market_rule_profile_version,
        ):
            raise ValueError(
                "Approved baseline recipe does not match the materialized market path"
            )
        resolved_conditions = (
            self._resolved_execution_conditions_for_recipe_path(
                approved,
                path,
            )
        )
        manifest = ptrade_manifest_for(strategy_id, strategy_version)
        return StrategyRunSpecification(
            recipe_version_id=approved.version_id,
            recipe_content_hash=approved.content_hash,
            materialization_hash=path.artifact_hash,
            source_snapshot_id=path.source_snapshot_id,
            materialization_seed=path.seed,
            transformation_catalog_version=path.transformation_catalog_version,
            transformation_implementation_versions=tuple(
                f"{item.transformation_id}@{item.implementation_version}"
                for item in path.applied_transformations
            ),
            market_rule_profile_version=path.market_rule_profile_version,
            execution_policy_version=BASELINE_EXECUTION_POLICY_VERSION,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            decision_cadence_minutes=approved.recipe.decision_cadence_minutes,
            initial_cash=initial_cash,
            order_shares=order_shares,
            replica_id=replica_id,
            code_identity=DIAGNOSTIC_CODE_IDENTITY,
            ptrade_surface_version=manifest.surface_version,
            ptrade_manifest_hash=manifest.content_hash,
            ptrade_host_adapter_version=(
                self._strategy_runs.ptrade_host_adapter_version
            ),
            commission_bps=resolved_conditions.effective.commission_bps,
            resolved_execution_conditions=resolved_conditions,
        )

    def strategy_run_status(self, run_id: str) -> StrategyRunSnapshot:
        self.status()
        return self._strategy_runs.get(run_id)

    def advance_strategy_run(
        self,
        run_id: str,
        *,
        node_count: int = 1,
    ) -> StrategyRunSnapshot:
        self.status()
        return self._strategy_runs.advance(run_id, node_count=node_count)

    def complete_strategy_run(
        self,
        run_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> StrategyRunSnapshot:
        self.status()
        return self._strategy_runs.run_to_completion(
            run_id,
            nodes_per_batch=nodes_per_batch,
        )

    def pause_strategy_run(self, run_id: str) -> StrategyRunSnapshot:
        self.status()
        return self._strategy_runs.pause(run_id)

    def resume_strategy_run(self, run_id: str) -> StrategyRunSnapshot:
        self.status()
        return self._strategy_runs.resume(run_id)

    def cancel_strategy_run(self, run_id: str) -> StrategyRunSnapshot:
        self.status()
        return self._strategy_runs.cancel(run_id)

    def _load_reference_path(self, artifact_hash: str) -> MaterializedMarketPath:
        if self._scenario_materializer is None:
            raise RuntimeError("No Scenario Materializer is configured")
        return self._scenario_materializer.get(artifact_hash)

    def _load_verified_reference_path(
        self,
        artifact_hash: str,
    ) -> MaterializedMarketPath:
        if self._scenario_materializer is None:
            raise RuntimeError("No Scenario Materializer is configured")
        return self._scenario_materializer.get_verified(artifact_hash)


def create_diagnostics_application(
    historical_source: HistoricalSource | None = None,
    market_data_source: HistoricalMarketDataSource | None = None,
    artifact_store: MarketPathArtifactStore | None = None,
    recipe_assistant: AIRecipeAssistant | None = None,
    recipe_clock: Callable[[], datetime] | None = None,
    materialization_scheduler: ScenarioMaterializationScheduler | None = None,
    diagnostic_task_clock: Callable[[], datetime] | None = None,
    ptrade_host: PTradeStrategyHost | None = None,
    evidence_artifact_store: DiagnosticEvidenceArtifactStore | None = None,
    finding_explanation_provider: (
        DiagnosticFindingExplanationProvider | None
    ) = None,
) -> DiagnosticsApplication:
    return DiagnosticsApplication(
        historical_source=historical_source,
        market_data_source=market_data_source,
        artifact_store=artifact_store,
        recipe_assistant=recipe_assistant,
        recipe_clock=recipe_clock,
        materialization_scheduler=materialization_scheduler,
        diagnostic_task_clock=diagnostic_task_clock,
        ptrade_host=ptrade_host,
        evidence_artifact_store=evidence_artifact_store,
        finding_explanation_provider=finding_explanation_provider,
    )


__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticCampaignCaseInventory",
    "DiagnosticsApplication",
    "DiagnosticsApplicationState",
    "create_diagnostics_application",
]
