"""Headless application boundary for the Strategy Diagnostics Laboratory."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Callable, Mapping, cast

from sqlalchemy.engine import Engine

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
from .execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from .formal_diagnostic_campaigns import (
    CampaignCaseSpecification,
    CampaignTransformation,
    DiagnosticCampaignCase,
    DiagnosticCampaignExecutionLayer,
    DiagnosticCampaignRunner,
    DiagnosticCampaignSnapshot,
    DiagnosticCampaignSpecification,
    SqlDiagnosticCampaignRepository,
)
from .recipes import (
    AIRecipeAuditRecord,
    AIRecipeAssistant,
    AIRecipeAuthoringResult,
    ApprovedScenarioRecipeVersion,
    RecipeValidationResult,
    RecipeWorkbench,
    ScenarioRecipeDraft,
)
from .reproduction import (
    DIAGNOSTIC_CODE_IDENTITY,
    ReproductionManifest,
    ReproductionReport,
    ReproductionService,
)
from .reproduction_storage import SqlReproductionRepository
from .ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    PTradeStrategyHost,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    SubprocessPTradeStrategyHost,
    ptrade_manifest_for,
)
from .strategy_campaigns import (
    BASELINE_CAMPAIGN_COMMISSION_BPS,
    BASELINE_CAMPAIGN_SLIPPAGE_BPS,
    BaselineCampaignRunner,
    BaselineCampaignSnapshot,
    BaselineCampaignSpecification,
)
from .transformations import create_initial_transformation_catalog
from .strategy_runs import (
    BASELINE_EXECUTION_POLICY_VERSION,
    REFERENCE_STRATEGY_ID,
    REFERENCE_STRATEGY_VERSION,
    SqlStrategyRunRepository,
    StrategyRunEngine,
    StrategyRunSnapshot,
    StrategyRunSpecification,
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


class DiagnosticsApplication:
    """Small product interface shared by headless and presentation adapters."""

    def __init__(
        self,
        historical_source: HistoricalSource | None = None,
        market_data_source: HistoricalMarketDataSource | None = None,
        artifact_store: MarketPathArtifactStore | None = None,
        recipe_assistant: AIRecipeAssistant | None = None,
        recipe_clock: Callable[[], datetime] | None = None,
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
        self._recipe_assistant = recipe_assistant
        self._strategy_runs = StrategyRunEngine(
            self._load_reference_path,
            ptrade_host=ptrade_host or SubprocessPTradeStrategyHost(),
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
            self._load_reference_path,
            self._evidence_artifact_store,
        )
        self._reproduction = ReproductionService(
            run_loader=self._strategy_runs.get,
            recipe_hash_loader=lambda version_id: (
                self._recipe_workbench.get_version(version_id).content_hash
            ),
            path_loader=self._load_reference_path,
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
        self._recipe_workbench.replace_repository(
            SqlScenarioRecipeRepository(engine)
        )
        self._strategy_runs.replace_repository(SqlStrategyRunRepository(engine))
        self._isolated_sensitivity_sets.replace_repository(
            SqlIsolatedSensitivitySetRepository(engine)
        )
        self._diagnostic_campaigns.replace_repository(
            SqlDiagnosticCampaignRepository(engine)
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
        return self._historical_segments.list_segments()

    def recommend_historical_segments(
        self,
        intent: str = "",
        limit: int = 3,
    ) -> tuple[HistoricalSegmentRecommendation, ...]:
        self.status()
        return self._historical_segments.recommend(
            intent=intent,
            limit=limit,
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
        requested_by_id = {
            item.transformation_id: item
            for item in approved.recipe.transformations
        }
        applied_by_id = {
            item.transformation_id: item
            for item in path.applied_transformations
        }
        if (
            len(requested_by_id) != len(approved.recipe.transformations)
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
        execution = approved.recipe.execution_conditions
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
            decision_cadence_minutes=approved.recipe.decision_cadence_minutes,
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
        return self._diagnostic_campaigns.advance(
            campaign_id,
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )

    def resume_diagnostic_campaign(
        self,
        campaign_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        self.status()
        return self._diagnostic_campaigns.resume(
            campaign_id,
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )

    def retry_diagnostic_campaign_case(
        self,
        campaign_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        self.status()
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

    def build_diagnostic_evidence(
        self,
        campaign_id: str,
        *,
        guardrail_profiles: tuple[StrategyGuardrailProfile, ...] | None = None,
    ) -> DiagnosticEvidencePackage:
        self.status()
        package = self._diagnostic_evidence.build(
            campaign_id,
            (
                guardrail_profiles
                if guardrail_profiles is not None
                else self.strategy_guardrail_profiles()
            ),
        )
        self._reproduction.accept_evidence(package)
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
        return self._reproduction.manifests_for(evidence_package_id)

    def reproduce_strategy_run(
        self,
        manifest_id: str,
    ) -> ReproductionReport:
        self.status()
        return self._reproduction.reproduce(manifest_id)

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
    ) -> BaselineCampaignSnapshot:
        """Run both V1 representative strategies on isolated path replicas."""

        specifications = (
            self._baseline_strategy_run_specification(
                recipe_version_id,
                materialization_hash,
                initial_cash=initial_cash,
                order_shares=order_shares,
                replica_id=f"{campaign_replica_id}:quentx",
                strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
            self._baseline_strategy_run_specification(
                recipe_version_id,
                materialization_hash,
                initial_cash=initial_cash,
                order_shares=order_shares,
                replica_id=f"{campaign_replica_id}:live-minute",
                strategy_id=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                strategy_version=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
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
        )

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
        requested_conditions = RequestedExecutionAssumptions(
            commission_bps=approved.recipe.execution_conditions.commission_bps,
            slippage_bps=approved.recipe.execution_conditions.slippage_bps,
            max_fill_fraction=(
                approved.recipe.execution_conditions.max_fill_fraction
            ),
            latency_nodes=approved.recipe.execution_conditions.latency_nodes,
            allow_partial_fills=(
                approved.recipe.execution_conditions.allow_partial_fills
            ),
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


def create_diagnostics_application(
    historical_source: HistoricalSource | None = None,
    market_data_source: HistoricalMarketDataSource | None = None,
    artifact_store: MarketPathArtifactStore | None = None,
    recipe_assistant: AIRecipeAssistant | None = None,
    recipe_clock: Callable[[], datetime] | None = None,
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
        ptrade_host=ptrade_host,
        evidence_artifact_store=evidence_artifact_store,
        finding_explanation_provider=finding_explanation_provider,
    )


__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticsApplication",
    "DiagnosticsApplicationState",
    "create_diagnostics_application",
]
