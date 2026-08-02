"""File-backed Strategy Diagnostics V1 fixture for release certification.

The fixture is deliberately built through public ``DiagnosticsApplication``
behavior.  It is production release evidence, not a dictionary-shaped
frontend substitute: the first Application and database engine are closed,
then a fresh Application, engine, JSON evidence store, and Parquet market-path
store reopen the same durable state.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from strategy_diagnostics import (
    AdmissionCheck,
    ApprovedScenarioRecipeVersion,
    DiagnosticCampaignSnapshot,
    DiagnosticEvidencePackage,
    FiveMinuteBar,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    InstrumentState,
    MaterializedMarketPath,
    ReproductionManifest,
    ScenarioDataWorldInput,
    SessionPriceLimitReference,
    SourceArtifact,
    SourceProvenance,
    StrategyRunSnapshot,
    create_diagnostics_application,
)
from strategy_diagnostics.application import DiagnosticsApplication
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from strategy_diagnostics.market_paths import ParquetMarketPathArtifactStore
from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION
from strategy_diagnostics.ptrade_host import (
    EmbeddedProductionPTradeStrategyHost,
    InProcessPTradeStrategyHost,
    PTradeStrategyHost,
    SubprocessPTradeStrategyHost,
)

UTC = timezone.utc
RELEASE_FIXTURE_CLOCK = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
FORMAL_V1_RELEASE_FIXTURE_DIRNAME = "strategy-diagnostics-v1-fixture"
FORMAL_V1_RELEASE_FIXTURE_ARCHIVE = "strategy-diagnostics-v1-fixture.zip"
FORMAL_V1_RELEASE_FIXTURE_MANIFEST = "fixture-manifest.json"
WAVE2_RELEASE_INPUT_FIXTURE_DIRNAME = (
    "strategy-diagnostics-v1-wave2-input-fixture"
)
WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE = (
    "strategy-diagnostics-v1-wave2-input-fixture.zip"
)
WAVE2_RELEASE_INPUT_FIXTURE_MANIFEST = "wave2-input-fixture-manifest.json"
_FORMAL_V1_RELEASE_FIXTURE_DATABASE = "strategy-diagnostics-v1.sqlite3"
_FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS = "artifacts"
_SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_ADMISSION_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


class DeterministicReleaseMarketSource:
    """Small deterministic historical source with cross-sectional structure."""

    def __init__(self) -> None:
        selection = HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
        self._source = InMemoryHistoricalSource(
            (
                HistoricalSourceInspection(
                    selection=selection,
                    label="Integrated release certification interval",
                    provenance=SourceProvenance(
                        provider="local-release-fixture",
                        dataset="strategy-diagnostics-v1-frontend-v2",
                        version="v1",
                        observed_at=RELEASE_FIXTURE_CLOCK,
                    ),
                    artifacts=(
                        SourceArtifact(
                            "market-structure-bars",
                            "d" * 64,
                            28,
                        ),
                    ),
                    eligible_instrument_count=4,
                    trading_day_count=1,
                    bar_count=28,
                    checks=tuple(
                        AdmissionCheck(code, True, f"{code} passed")
                        for code in _REQUIRED_ADMISSION_CHECKS
                    ),
                ),
            )
        )

    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = self._source.inspect(selection)
        if inspection is None:
            return None
        return replace(
            inspection,
            artifacts=(
                SourceArtifact(
                    "market-structure-bars",
                    "d" * 64,
                    28,
                ),
            ),
            eligible_instrument_count=4,
            bar_count=28,
        )

    def load_scenario_data_world(
        self,
        segment: object,
    ) -> ScenarioDataWorldInput:
        instruments = (
            ("sh.600000", "banking", "sh-main"),
            ("sh.600001", "banking", "sh-main"),
            ("sz.000001", "technology", "sz-main"),
            ("sz.000002", "technology", "sz-main"),
        )
        closes_by_time = (
            (datetime(2024, 1, 2, 9, 35), ("10", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 40), ("10", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 45), ("10", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 50), ("9.90", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 55), ("9.75", "10", "10", "10")),
            (datetime(2024, 1, 2, 10, 0), ("9.82", "10", "10", "10")),
            (datetime(2024, 1, 2, 10, 5), ("9.84", "10", "10", "10")),
        )
        previous_closes = {
            instrument: Decimal("10")
            for instrument, _industry, _board in instruments
        }
        bars: list[FiveMinuteBar] = []
        for end_time, closes in closes_by_time:
            for (instrument, _industry, _board), close_text in zip(
                instruments,
                closes,
                strict=True,
            ):
                opening = previous_closes[instrument]
                close = Decimal(close_text)
                bars.append(
                    FiveMinuteBar(
                        instrument=instrument,
                        end_time=end_time,
                        open=opening,
                        high=max(opening, close),
                        low=min(opening, close),
                        close=close,
                        volume=100,
                        amount=close * 100,
                    )
                )
                previous_closes[instrument] = close
        return ScenarioDataWorldInput(
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
            bars=tuple(bars),
            instrument_states=tuple(
                InstrumentState(
                    instrument=instrument,
                    effective_at=datetime(2024, 1, 2, 9, 30),
                    eligible=True,
                    trading_status="trading",
                    is_st=False,
                    industry=industry,
                    decision_adjustment_factor=Decimal("1"),
                    decision_adjustment_provenance="release-fixture-v1",
                )
                for instrument, industry, _board in instruments
            ),
            price_limit_references=tuple(
                SessionPriceLimitReference(
                    instrument=instrument,
                    session_date=date(2024, 1, 2),
                    previous_close=Decimal("10"),
                    effective_at=datetime(2024, 1, 2, 9, 30),
                    provenance="release-fixture-preclose-v1",
                    profile_version="a-share-cash-equity.v1",
                    board=board,
                    is_st=False,
                    listing_stage="continuous",
                    limit_fraction=Decimal("0.10"),
                    rule_code=f"release-fixture.{board}.ordinary.10pct",
                )
                for instrument, _industry, board in instruments
            ),
        )


@dataclass(frozen=True, slots=True)
class FileBackedFormalV1ReleaseFixture:
    """Reopened, sealed Formal Campaign and its exact selected journey."""

    application: DiagnosticsApplication
    engine: Engine
    campaign: DiagnosticCampaignSnapshot
    selected_run: StrategyRunSnapshot
    evidence_package: DiagnosticEvidencePackage
    selected_manifest: ReproductionManifest
    manifests: tuple[ReproductionManifest, ...]
    database_path: Path
    artifact_root: Path
    _closed: bool = field(default=False, init=False, compare=False)

    @property
    def artifact_hashes(self) -> tuple[str, ...]:
        return tuple(
            f"sha256:{value}" for value in self.raw_artifact_hashes
        )

    @property
    def raw_artifact_hashes(self) -> tuple[str, ...]:
        values = {
            self.evidence_package.artifact_hash,
            str(
                self.evidence_package.sealed_payload()[
                    "measurement_artifact_hash"
                ]
            ),
        }
        for manifest in self.manifests:
            values.update(
                (
                    manifest.run_artifact_hash,
                    manifest.evidence_artifact_hash,
                    manifest.measurement_artifact_hash,
                    manifest.manifest_content_hash,
                    manifest.specification.materialization_hash,
                    manifest.specification.recipe_content_hash,
                )
            )
        return tuple(sorted(values))

    @property
    def evidence_identity_sets(self) -> dict[str, tuple[str, ...]]:
        payload = self.evidence_package.sealed_payload()
        return {
            "candidates": tuple(
                sorted(
                    {
                        (
                            f"{item['strategy_id']}@"
                            f"{item['strategy_version']}"
                        )
                        for item in payload["metrics"]
                    }
                )
            ),
            "metrics": tuple(
                sorted(
                    {
                        str(item["metric_id"])
                        for item in payload["metrics"]
                    }
                )
            ),
            "comparisons": tuple(
                sorted(
                    {
                        str(item["comparison_id"])
                        for item in payload["comparisons"]
                    }
                )
            ),
            "curves": tuple(
                sorted(
                    {
                        str(item["curve_id"])
                        for item in payload["sensitivity_curves"]
                    }
                )
            ),
            "breakpoints": tuple(
                sorted(
                    {
                        str(item["breakpoint_id"])
                        for item in payload["sensitivity_breakpoints"]
                    }
                )
            ),
            "findings": tuple(
                sorted(
                    {
                        str(item["finding_id"])
                        for item in payload["diagnostic_findings"]
                    }
                )
            ),
        }

    @property
    def expected_identity_graph(self) -> tuple[str, ...]:
        specification = self.selected_run.specification
        values = {
            self.campaign.campaign_id,
            self.selected_manifest.case_id,
            self.selected_run.run_id,
            specification.strategy_id,
            specification.recipe_version_id,
            self.evidence_package.evidence_package_id,
            self.selected_manifest.manifest_id,
            *(manifest.manifest_id for manifest in self.manifests),
            *(manifest.run_id for manifest in self.manifests),
            *self.raw_artifact_hashes,
            *(
                identity
                for identities in self.evidence_identity_sets.values()
                for identity in identities
            ),
        }
        return tuple(sorted(values))

    def close(self) -> None:
        if self._closed:
            return
        self.engine.dispose()
        object.__setattr__(self, "_closed", True)

    @property
    def closed(self) -> bool:
        return self._closed


@dataclass(frozen=True, slots=True)
class SealedFormalV1ReleaseFixtureFile:
    """One immutable file retained in the packaged V1 release fixture."""

    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SealedFormalV1ReleaseFixtureManifest:
    """Identity and storage seal for a build-time Formal Campaign."""

    schema_version: int
    source_commit: str
    campaign_id: str
    selected_run_id: str
    evidence_package_id: str
    selected_manifest_id: str
    artifact_hashes: tuple[str, ...]
    expected_identity_graph: tuple[str, ...]
    files: tuple[SealedFormalV1ReleaseFixtureFile, ...]


@dataclass(frozen=True, slots=True)
class FileBackedWave2ReleaseInputFixture:
    """Reopened writable authoritative inputs and persisted Wave 2 state."""

    application: DiagnosticsApplication
    engine: Engine
    database_path: Path
    artifact_root: Path
    authoritative_input_identities: tuple[str, ...]
    persisted_diagnostic_task_count: int
    persisted_formal_campaign_count: int
    _closed: bool = field(default=False, init=False, compare=False)

    def close(self) -> None:
        if self._closed:
            return
        self.engine.dispose()
        object.__setattr__(self, "_closed", True)

    @property
    def closed(self) -> bool:
        return self._closed


@dataclass(frozen=True, slots=True)
class SealedWave2ReleaseInputFixtureManifest:
    """Build-time seal for writable installed Wave 2 input state."""

    schema_version: int
    source_commit: str
    initial_diagnostic_task_count: int
    initial_formal_campaign_count: int
    authoritative_input_identities: tuple[str, ...]
    files: tuple[SealedFormalV1ReleaseFixtureFile, ...]


def create_file_backed_formal_v1_release_fixture(
    *,
    database_path: Path,
    artifact_root: Path,
    ptrade_host: PTradeStrategyHost | None = None,
) -> FileBackedFormalV1ReleaseFixture:
    """Create, close, and reopen the real V1 release fixture."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)
    source = DeterministicReleaseMarketSource()
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    try:
        application = _new_application(
            source=source,
            artifact_root=artifact_root,
            ptrade_host=ptrade_host,
        )
        application.start()
        application.initialize_persistence(engine)
        campaign, package, manifests = _create_completed_formal_campaign(
            application
        )
        selected_manifest = next(
            (
                item
                for item in sorted(
                    manifests,
                    key=lambda candidate: candidate.manifest_id,
                )
                if item.layer == "compound"
            ),
            sorted(
                manifests,
                key=lambda candidate: candidate.manifest_id,
            )[0],
        )
        selected_run = application.strategy_run_status(
            selected_manifest.run_id
        )
    except BaseException:
        engine.dispose()
        raise

    engine.dispose()
    reopened_fixture = _open_file_backed_formal_v1_release_fixture(
        database_path=database_path,
        artifact_root=artifact_root,
        campaign_id=campaign.campaign_id,
        evidence_package_id=package.evidence_package_id,
        selected_manifest_id=selected_manifest.manifest_id,
        ptrade_host=ptrade_host,
    )
    try:
        _require(
            reopened_fixture.campaign == campaign,
            "The Formal Diagnostic Campaign changed after reopen.",
        )
        _require(
            reopened_fixture.evidence_package == package,
            "The sealed Diagnostic Evidence changed after reopen.",
        )
        _require(
            reopened_fixture.selected_manifest == selected_manifest,
            "The selected Reproduction Manifest changed after reopen.",
        )
        _require(
            reopened_fixture.selected_run == selected_run,
            "The selected Strategy Run changed after reopen.",
        )
    except BaseException:
        reopened_fixture.close()
        raise
    return reopened_fixture


def create_file_backed_wave2_release_input_fixture(
    *,
    database_path: Path,
    artifact_root: Path,
) -> FileBackedWave2ReleaseInputFixture:
    """Create and reopen only the authoritative inputs for installed Wave 2."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)
    source = DeterministicReleaseMarketSource()
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    try:
        application = _new_application(
            source=source,
            artifact_root=artifact_root,
            ptrade_host=EmbeddedProductionPTradeStrategyHost(),
        )
        application.start()
        migration = application.initialize_persistence(engine)
        _require(
            migration.current_revision == DIAGNOSTIC_SCHEMA_REVISION,
            "The Wave 2 input persistence revision is incompatible.",
        )
        _prepare_wave2_authoritative_inputs(application)
        identities = _wave2_authoritative_input_identities(application)
        _require(
            application.get_diagnostic_task() is None,
            "The Wave 2 input fixture contains a Diagnostic Task.",
        )
    except BaseException:
        engine.dispose()
        raise
    engine.dispose()

    reopened = _open_file_backed_wave2_release_input_fixture(
        database_path=database_path,
        artifact_root=artifact_root,
    )
    try:
        _require(
            reopened.authoritative_input_identities == identities,
            "Wave 2 authoritative input identities changed after reopen.",
        )
    except BaseException:
        reopened.close()
        raise
    return reopened


def create_sealed_wave2_release_input_fixture(
    *,
    bundle_root: Path,
    source_commit: str,
) -> SealedWave2ReleaseInputFixtureManifest:
    """Seal authoritative inputs while leaving installed persistence writable."""

    _validate_source_commit(source_commit)
    if bundle_root.exists():
        raise RuntimeError(
            f"Wave 2 release input bundle already exists: {bundle_root}"
        )
    bundle_root.mkdir(parents=True)
    fixture = create_file_backed_wave2_release_input_fixture(
        database_path=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_DATABASE,
        artifact_root=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS,
    )
    try:
        manifest = SealedWave2ReleaseInputFixtureManifest(
            schema_version=1,
            source_commit=source_commit,
            initial_diagnostic_task_count=(
                fixture.persisted_diagnostic_task_count
            ),
            initial_formal_campaign_count=(
                fixture.persisted_formal_campaign_count
            ),
            authoritative_input_identities=(
                fixture.authoritative_input_identities
            ),
            files=(),
        )
    finally:
        fixture.close()

    manifest = replace(
        manifest,
        files=_fixture_file_inventory(
            bundle_root,
            manifest_name=WAVE2_RELEASE_INPUT_FIXTURE_MANIFEST,
        ),
    )
    manifest_path = bundle_root / WAVE2_RELEASE_INPUT_FIXTURE_MANIFEST
    manifest_path.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return load_sealed_wave2_release_input_fixture_manifest(bundle_root)


def create_sealed_formal_v1_release_fixture(
    *,
    bundle_root: Path,
    source_commit: str,
) -> SealedFormalV1ReleaseFixtureManifest:
    """Create and seal a real Formal Campaign for packaged read-only use."""

    _validate_source_commit(source_commit)
    if bundle_root.exists():
        raise RuntimeError(
            f"Release fixture bundle already exists: {bundle_root}"
        )
    bundle_root.mkdir(parents=True)
    fixture = create_file_backed_formal_v1_release_fixture(
        database_path=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_DATABASE,
        artifact_root=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS,
        # A Formal Campaign owns this backend execution policy: PTrade
        # strategies must run through the production isolation boundary.
        # Consumers of the sealed fixture reopen it read-only in-process.
        ptrade_host=SubprocessPTradeStrategyHost(),
    )
    try:
        manifest = SealedFormalV1ReleaseFixtureManifest(
            schema_version=1,
            source_commit=source_commit,
            campaign_id=fixture.campaign.campaign_id,
            selected_run_id=fixture.selected_run.run_id,
            evidence_package_id=fixture.evidence_package.evidence_package_id,
            selected_manifest_id=fixture.selected_manifest.manifest_id,
            artifact_hashes=fixture.artifact_hashes,
            expected_identity_graph=fixture.expected_identity_graph,
            files=(),
        )
    finally:
        fixture.close()

    manifest = replace(
        manifest,
        files=_fixture_file_inventory(bundle_root),
    )
    manifest_path = bundle_root / FORMAL_V1_RELEASE_FIXTURE_MANIFEST
    manifest_path.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return load_sealed_formal_v1_release_fixture_manifest(bundle_root)


def load_sealed_formal_v1_release_fixture_manifest(
    bundle_root: Path,
) -> SealedFormalV1ReleaseFixtureManifest:
    """Load and validate the immutable release-fixture manifest."""

    manifest_path = bundle_root / FORMAL_V1_RELEASE_FIXTURE_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"Cannot read sealed V1 release fixture manifest: {manifest_path}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("Sealed V1 release fixture manifest is not an object")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise RuntimeError("Sealed V1 release fixture files are not a list")
    raw_artifact_hashes = payload.get("artifact_hashes")
    raw_identity_graph = payload.get("expected_identity_graph")
    if not isinstance(raw_artifact_hashes, list) or not isinstance(
        raw_identity_graph, list
    ):
        raise RuntimeError(
            "Sealed V1 release fixture identity evidence is invalid"
        )
    files: list[SealedFormalV1ReleaseFixtureFile] = []
    try:
        for raw_file in raw_files:
            if not isinstance(raw_file, dict):
                raise RuntimeError(
                    "Sealed V1 release fixture file entry is not an object"
                )
            files.append(
                SealedFormalV1ReleaseFixtureFile(
                    relative_path=str(raw_file.get("relative_path", "")),
                    size_bytes=int(raw_file.get("size_bytes", -1)),
                    sha256=str(raw_file.get("sha256", "")),
                )
            )
        manifest = SealedFormalV1ReleaseFixtureManifest(
            schema_version=int(payload.get("schema_version", -1)),
            source_commit=str(payload.get("source_commit", "")),
            campaign_id=str(payload.get("campaign_id", "")),
            selected_run_id=str(payload.get("selected_run_id", "")),
            evidence_package_id=str(
                payload.get("evidence_package_id", "")
            ),
            selected_manifest_id=str(
                payload.get("selected_manifest_id", "")
            ),
            artifact_hashes=tuple(
                str(item) for item in raw_artifact_hashes
            ),
            expected_identity_graph=tuple(
                str(item) for item in raw_identity_graph
            ),
            files=tuple(files),
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "Sealed V1 release fixture manifest fields are invalid"
        ) from error
    _validate_sealed_manifest(manifest)
    _verify_fixture_file_inventory(bundle_root, manifest.files)
    return manifest


def load_sealed_wave2_release_input_fixture_manifest(
    bundle_root: Path,
) -> SealedWave2ReleaseInputFixtureManifest:
    """Load and validate a source-bound Wave 2 input fixture seal."""

    manifest_path = bundle_root / WAVE2_RELEASE_INPUT_FIXTURE_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Cannot read sealed Wave 2 input fixture manifest: "
            f"{manifest_path}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("Wave 2 input fixture manifest is not an object")
    raw_files = payload.get("files")
    raw_identities = payload.get("authoritative_input_identities")
    if not isinstance(raw_files, list) or not isinstance(
        raw_identities,
        list,
    ):
        raise RuntimeError("Wave 2 input fixture identity evidence is invalid")
    files: list[SealedFormalV1ReleaseFixtureFile] = []
    try:
        for raw_file in raw_files:
            if not isinstance(raw_file, dict):
                raise TypeError
            files.append(
                SealedFormalV1ReleaseFixtureFile(
                    relative_path=str(raw_file["relative_path"]),
                    size_bytes=int(raw_file["size_bytes"]),
                    sha256=str(raw_file["sha256"]),
                )
            )
        manifest = SealedWave2ReleaseInputFixtureManifest(
            schema_version=int(payload.get("schema_version", -1)),
            source_commit=str(payload.get("source_commit", "")),
            initial_diagnostic_task_count=int(
                payload.get("initial_diagnostic_task_count", -1)
            ),
            initial_formal_campaign_count=int(
                payload.get("initial_formal_campaign_count", -1)
            ),
            authoritative_input_identities=tuple(
                str(item) for item in raw_identities
            ),
            files=tuple(files),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "Wave 2 input fixture manifest fields are invalid"
        ) from error
    _validate_wave2_input_manifest(manifest)
    _verify_fixture_file_inventory(
        bundle_root,
        manifest.files,
        manifest_name=WAVE2_RELEASE_INPUT_FIXTURE_MANIFEST,
    )
    return manifest


def open_sealed_formal_v1_release_fixture(
    *,
    bundle_root: Path,
    expected_source_commit: str,
) -> FileBackedFormalV1ReleaseFixture:
    """Reopen a copied sealed fixture through the real V1 Application."""

    _validate_source_commit(expected_source_commit)
    manifest = load_sealed_formal_v1_release_fixture_manifest(bundle_root)
    _require(
        manifest.source_commit == expected_source_commit,
        "Sealed V1 release fixture source commit does not match the package.",
    )
    fixture = _open_file_backed_formal_v1_release_fixture(
        database_path=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_DATABASE,
        artifact_root=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS,
        campaign_id=manifest.campaign_id,
        evidence_package_id=manifest.evidence_package_id,
        selected_manifest_id=manifest.selected_manifest_id,
        ptrade_host=InProcessPTradeStrategyHost(),
    )
    try:
        _require(
            fixture.selected_run.run_id == manifest.selected_run_id,
            "Sealed V1 release fixture selected Strategy Run changed.",
        )
        _require(
            fixture.artifact_hashes == manifest.artifact_hashes,
            "Sealed V1 release fixture artifact identities changed.",
        )
        _require(
            fixture.expected_identity_graph
            == manifest.expected_identity_graph,
            "Sealed V1 release fixture identity graph changed.",
        )
    except BaseException:
        fixture.close()
        raise
    return fixture


def open_sealed_wave2_release_input_fixture(
    *,
    bundle_root: Path,
    expected_source_commit: str,
) -> FileBackedWave2ReleaseInputFixture:
    """Open the verified installed input copy as writable real persistence."""

    _validate_source_commit(expected_source_commit)
    manifest = load_sealed_wave2_release_input_fixture_manifest(bundle_root)
    _require(
        manifest.source_commit == expected_source_commit,
        "Wave 2 input fixture source commit does not match the package.",
    )
    fixture = _open_file_backed_wave2_release_input_fixture(
        database_path=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_DATABASE,
        artifact_root=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS,
    )
    try:
        _require(
            fixture.authoritative_input_identities
            == manifest.authoritative_input_identities,
            "Wave 2 authoritative input identities changed after extraction.",
        )
        _require(
            fixture.application.get_diagnostic_task() is None,
            "Installed Wave 2 input persistence already contains a task.",
        )
        _require(
            fixture.persisted_diagnostic_task_count
            == manifest.initial_diagnostic_task_count,
            "Installed Wave 2 Diagnostic Task count changed after extraction.",
        )
        _require(
            fixture.persisted_formal_campaign_count
            == manifest.initial_formal_campaign_count,
            "Installed Wave 2 Formal Campaign count changed after extraction.",
        )
    except BaseException:
        fixture.close()
        raise
    return fixture


def reopen_completed_wave2_release_fixture(
    *,
    bundle_root: Path,
    campaign_id: str,
    evidence_package_id: str,
    selected_manifest_id: str,
) -> FileBackedFormalV1ReleaseFixture:
    """Reopen installed command results through public Application behavior."""

    return _open_file_backed_formal_v1_release_fixture(
        database_path=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_DATABASE,
        artifact_root=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS,
        campaign_id=campaign_id,
        evidence_package_id=evidence_package_id,
        selected_manifest_id=selected_manifest_id,
        ptrade_host=EmbeddedProductionPTradeStrategyHost(),
    )


def reopen_active_wave2_release_input_fixture(
    *,
    bundle_root: Path,
    diagnostic_task_id: str,
    campaign_id: str,
) -> FileBackedWave2ReleaseInputFixture:
    """Reopen a nonterminal installed task and Campaign for continuation."""

    fixture = _open_file_backed_wave2_release_input_fixture(
        database_path=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_DATABASE,
        artifact_root=bundle_root / _FORMAL_V1_RELEASE_FIXTURE_ARTIFACTS,
        require_empty=False,
    )
    try:
        task = fixture.application.get_diagnostic_task(diagnostic_task_id)
        _require(
            task is not None and task.task_id == diagnostic_task_id,
            "The active Wave 2 Diagnostic Task did not survive reopen.",
        )
        _require(
            task.campaign_handoff is not None
            and task.campaign_handoff.campaign_id == campaign_id,
            "The active Wave 2 Campaign handoff did not survive reopen.",
        )
        campaign = fixture.application.diagnostic_campaign_status(campaign_id)
        _require(
            campaign.status != "completed",
            "The active Wave 2 Campaign reached terminal state before reopen.",
        )
        _require(
            fixture.persisted_diagnostic_task_count == 1,
            "The active Wave 2 persistence contains an unexpected task count.",
        )
        _require(
            fixture.persisted_formal_campaign_count == 1,
            "The active Wave 2 persistence contains an unexpected Campaign "
            "count.",
        )
    except BaseException:
        fixture.close()
        raise
    return fixture


def write_sealed_formal_v1_release_fixture_archive(
    *,
    bundle_root: Path,
    archive_path: Path,
) -> str:
    """Write a deterministic single-file transport for a sealed fixture."""

    load_sealed_formal_v1_release_fixture_manifest(bundle_root)
    if archive_path.exists():
        raise RuntimeError(
            f"Sealed V1 release fixture archive already exists: {archive_path}"
        )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    retained_files = tuple(
        sorted(path for path in bundle_root.rglob("*") if path.is_file())
    )
    with zipfile.ZipFile(
        archive_path,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for retained_file in retained_files:
            archive_name = retained_file.relative_to(
                bundle_root
            ).as_posix()
            info = zipfile.ZipInfo(
                filename=archive_name,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            archive.writestr(info, retained_file.read_bytes())
    return _sha256_file(archive_path)


def write_sealed_wave2_release_input_fixture_archive(
    *,
    bundle_root: Path,
    archive_path: Path,
) -> str:
    """Write the deterministic transport for Wave 2 authoritative inputs."""

    load_sealed_wave2_release_input_fixture_manifest(bundle_root)
    return _write_fixture_archive(
        bundle_root=bundle_root,
        archive_path=archive_path,
        label="Wave 2 release input fixture",
    )


def extract_sealed_formal_v1_release_fixture_archive(
    *,
    archive_path: Path,
    bundle_root: Path,
) -> SealedFormalV1ReleaseFixtureManifest:
    """Safely extract and verify a packaged sealed-fixture archive."""

    if bundle_root.exists():
        raise RuntimeError(
            f"Sealed V1 release fixture destination exists: {bundle_root}"
        )
    bundle_root.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        members = archive.infolist()
        names = tuple(member.filename for member in members)
        _require(
            bool(names) and len(names) == len(set(names)),
            "Sealed V1 release fixture archive members are invalid.",
        )
        for member in members:
            relative_path = PurePosixPath(member.filename)
            unix_mode = member.external_attr >> 16
            _require(
                bool(member.filename)
                and "\\" not in member.filename
                and not relative_path.is_absolute()
                and ".." not in relative_path.parts
                and not any(":" in part for part in relative_path.parts)
                and (unix_mode & 0o170000) != 0o120000,
                "Sealed V1 release fixture archive path is unsafe.",
            )
            if member.is_dir():
                continue
            destination = bundle_root.joinpath(*relative_path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with (
                archive.open(member, mode="r") as source,
                destination.open("xb") as target,
            ):
                shutil.copyfileobj(source, target)
    return load_sealed_formal_v1_release_fixture_manifest(bundle_root)


def extract_sealed_wave2_release_input_fixture_archive(
    *,
    archive_path: Path,
    bundle_root: Path,
) -> SealedWave2ReleaseInputFixtureManifest:
    """Safely extract and verify a packaged Wave 2 input fixture."""

    _extract_fixture_archive(
        archive_path=archive_path,
        bundle_root=bundle_root,
        label="Wave 2 release input fixture",
    )
    return load_sealed_wave2_release_input_fixture_manifest(bundle_root)


def _write_fixture_archive(
    *,
    bundle_root: Path,
    archive_path: Path,
    label: str,
) -> str:
    if archive_path.exists():
        raise RuntimeError(f"{label} archive already exists: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    retained_files = tuple(
        sorted(path for path in bundle_root.rglob("*") if path.is_file())
    )
    with zipfile.ZipFile(
        archive_path,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for retained_file in retained_files:
            archive_name = retained_file.relative_to(
                bundle_root
            ).as_posix()
            info = zipfile.ZipInfo(
                filename=archive_name,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            archive.writestr(info, retained_file.read_bytes())
    return _sha256_file(archive_path)


def _extract_fixture_archive(
    *,
    archive_path: Path,
    bundle_root: Path,
    label: str,
) -> None:
    if bundle_root.exists():
        raise RuntimeError(f"{label} destination exists: {bundle_root}")
    bundle_root.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        members = archive.infolist()
        names = tuple(member.filename for member in members)
        _require(
            bool(names) and len(names) == len(set(names)),
            f"{label} archive members are invalid.",
        )
        for member in members:
            relative_path = PurePosixPath(member.filename)
            unix_mode = member.external_attr >> 16
            _require(
                bool(member.filename)
                and "\\" not in member.filename
                and not relative_path.is_absolute()
                and ".." not in relative_path.parts
                and not any(":" in part for part in relative_path.parts)
                and (unix_mode & 0o170000) != 0o120000,
                f"{label} archive path is unsafe.",
            )
            if member.is_dir():
                continue
            destination = bundle_root.joinpath(*relative_path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with (
                archive.open(member, mode="r") as source,
                destination.open("xb") as target,
            ):
                shutil.copyfileobj(source, target)


def _open_file_backed_wave2_release_input_fixture(
    *,
    database_path: Path,
    artifact_root: Path,
    require_empty: bool = True,
) -> FileBackedWave2ReleaseInputFixture:
    source = DeterministicReleaseMarketSource()
    reopened_engine = create_engine(
        f"sqlite:///{database_path}",
        future=True,
    )
    try:
        reopened_paths = ParquetMarketPathArtifactStore(
            artifact_root / "market-paths"
        )
        reopened = _new_application(
            source=source,
            artifact_root=artifact_root,
            market_path_store=reopened_paths,
            ptrade_host=EmbeddedProductionPTradeStrategyHost(),
        )
        reopened.start()
        migration = reopened.initialize_persistence(reopened_engine)
        _require(
            migration.current_revision == DIAGNOSTIC_SCHEMA_REVISION,
            "The reopened Wave 2 input persistence revision is incompatible.",
        )
        task_count, campaign_count = _persisted_wave2_entity_counts(
            reopened_engine
        )
        if require_empty:
            _require(
                reopened.get_diagnostic_task() is None,
                "The reopened Wave 2 input fixture contains a Diagnostic Task.",
            )
            _require(
                task_count == 0,
                "The reopened Wave 2 input fixture contains a pre-created "
                "Diagnostic Task.",
            )
            _require(
                campaign_count == 0,
                "The reopened Wave 2 input fixture contains a pre-created "
                "Formal Campaign.",
            )
        identities = _wave2_authoritative_input_identities(reopened)
    except BaseException:
        reopened_engine.dispose()
        raise
    return FileBackedWave2ReleaseInputFixture(
        application=reopened,
        engine=reopened_engine,
        database_path=database_path,
        artifact_root=artifact_root,
        authoritative_input_identities=identities,
        persisted_diagnostic_task_count=task_count,
        persisted_formal_campaign_count=campaign_count,
    )


def _persisted_wave2_entity_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        task_count = int(
            connection.execute(
                text("SELECT COUNT(*) FROM diagnostic_tasks")
            ).scalar_one()
        )
        campaign_count = int(
            connection.execute(
                text("SELECT COUNT(*) FROM diagnostic_campaigns")
            ).scalar_one()
        )
    return task_count, campaign_count


def _open_file_backed_formal_v1_release_fixture(
    *,
    database_path: Path,
    artifact_root: Path,
    campaign_id: str,
    evidence_package_id: str,
    selected_manifest_id: str,
    ptrade_host: PTradeStrategyHost | None,
) -> FileBackedFormalV1ReleaseFixture:
    source = DeterministicReleaseMarketSource()
    reopened_engine = create_engine(
        f"sqlite:///{database_path}",
        future=True,
    )
    try:
        reopened_paths = ParquetMarketPathArtifactStore(
            artifact_root / "market-paths"
        )
        reopened = _new_application(
            source=source,
            artifact_root=artifact_root,
            market_path_store=reopened_paths,
            ptrade_host=ptrade_host,
        )
        reopened.start()
        migration = reopened.initialize_persistence(reopened_engine)
        _require(
            migration.current_revision == DIAGNOSTIC_SCHEMA_REVISION,
            "The reopened V1 persistence revision is incompatible.",
        )
        reopened_campaign = reopened.diagnostic_campaign_status(
            campaign_id
        )
        reopened_package = reopened.diagnostic_evidence_status(
            evidence_package_id
        )
        reopened_manifests = tuple(
            reopened.reproduction_manifests(evidence_package_id)
        )
        reopened_manifest = next(
            (
                item
                for item in reopened_manifests
                if item.manifest_id == selected_manifest_id
            ),
            None,
        )
        _require(
            reopened_manifest is not None,
            "The selected Reproduction Manifest did not survive reopen.",
        )
        assert reopened_manifest is not None
        reopened_run = reopened.strategy_run_status(
            reopened_manifest.run_id
        )
        persisted_path = reopened_paths.get(
            reopened_run.specification.materialization_hash
        )
        _require(
            persisted_path.artifact_hash
            == reopened_run.specification.materialization_hash,
            "The selected market-path artifact did not survive reopen.",
        )
    except BaseException:
        reopened_engine.dispose()
        raise

    return FileBackedFormalV1ReleaseFixture(
        application=reopened,
        engine=reopened_engine,
        campaign=reopened_campaign,
        selected_run=reopened_run,
        evidence_package=reopened_package,
        selected_manifest=reopened_manifest,
        manifests=reopened_manifests,
        database_path=database_path,
        artifact_root=artifact_root,
    )


def _fixture_file_inventory(
    bundle_root: Path,
    *,
    manifest_name: str = FORMAL_V1_RELEASE_FIXTURE_MANIFEST,
) -> tuple[SealedFormalV1ReleaseFixtureFile, ...]:
    files: list[SealedFormalV1ReleaseFixtureFile] = []
    for path in sorted(bundle_root.rglob("*")):
        if path == bundle_root / manifest_name:
            continue
        if path.is_symlink():
            raise RuntimeError(
                f"Release fixture bundle contains a symbolic link: {path}"
            )
        if not path.is_file():
            continue
        files.append(
            SealedFormalV1ReleaseFixtureFile(
                relative_path=path.relative_to(bundle_root).as_posix(),
                size_bytes=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    _require(bool(files), "Sealed V1 release fixture contains no files.")
    return tuple(files)


def _verify_fixture_file_inventory(
    bundle_root: Path,
    expected: tuple[SealedFormalV1ReleaseFixtureFile, ...],
    *,
    manifest_name: str = FORMAL_V1_RELEASE_FIXTURE_MANIFEST,
) -> None:
    observed = _fixture_file_inventory(
        bundle_root,
        manifest_name=manifest_name,
    )
    _require(
        observed == expected,
        "Sealed V1 release fixture file inventory does not match its manifest.",
    )


def _validate_sealed_manifest(
    manifest: SealedFormalV1ReleaseFixtureManifest,
) -> None:
    _require(
        manifest.schema_version == 1,
        "Unsupported sealed V1 release fixture manifest version.",
    )
    _validate_source_commit(manifest.source_commit)
    for label, value in (
        ("campaign", manifest.campaign_id),
        ("run", manifest.selected_run_id),
        ("evidence package", manifest.evidence_package_id),
        ("reproduction manifest", manifest.selected_manifest_id),
    ):
        _require(bool(value.strip()), f"Sealed V1 {label} identity is empty.")
    _require(
        bool(manifest.artifact_hashes)
        and all(
            _SHA256_PATTERN.fullmatch(item)
            for item in manifest.artifact_hashes
        ),
        "Sealed V1 release fixture artifact hashes are invalid.",
    )
    _require(
        bool(manifest.expected_identity_graph)
        and manifest.expected_identity_graph
        == tuple(sorted(set(manifest.expected_identity_graph))),
        "Sealed V1 release fixture identity graph is invalid.",
    )
    _require(
        bool(manifest.files)
        and manifest.files
        == tuple(sorted(manifest.files, key=lambda item: item.relative_path)),
        "Sealed V1 release fixture file inventory is invalid.",
    )
    for item in manifest.files:
        relative_path = Path(item.relative_path)
        _require(
            bool(item.relative_path)
            and not relative_path.is_absolute()
            and ".." not in relative_path.parts,
            "Sealed V1 release fixture contains an unsafe file path.",
        )
        _require(
            item.size_bytes >= 0
            and _SHA256_PATTERN.fullmatch(item.sha256) is not None,
            "Sealed V1 release fixture contains invalid file evidence.",
        )


def _validate_wave2_input_manifest(
    manifest: SealedWave2ReleaseInputFixtureManifest,
) -> None:
    _require(
        manifest.schema_version == 1,
        "Unsupported Wave 2 input fixture manifest version.",
    )
    _validate_source_commit(manifest.source_commit)
    _require(
        manifest.initial_diagnostic_task_count == 0,
        "Wave 2 input fixture contains a pre-created Diagnostic Task.",
    )
    _require(
        manifest.initial_formal_campaign_count == 0,
        "Wave 2 input fixture contains a pre-created Formal Campaign.",
    )
    _require(
        bool(manifest.authoritative_input_identities)
        and manifest.authoritative_input_identities
        == tuple(sorted(set(manifest.authoritative_input_identities))),
        "Wave 2 authoritative input identities are invalid.",
    )
    _require(
        bool(manifest.files)
        and manifest.files
        == tuple(sorted(manifest.files, key=lambda item: item.relative_path)),
        "Wave 2 input fixture file inventory is invalid.",
    )
    for item in manifest.files:
        relative_path = Path(item.relative_path)
        _require(
            bool(item.relative_path)
            and not relative_path.is_absolute()
            and ".." not in relative_path.parts,
            "Wave 2 input fixture contains an unsafe file path.",
        )
        _require(
            item.size_bytes >= 0
            and _SHA256_PATTERN.fullmatch(item.sha256) is not None,
            "Wave 2 input fixture contains invalid file evidence.",
        )


def _validate_source_commit(source_commit: str) -> None:
    _require(
        _SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is not None,
        "Sealed V1 release fixture source commit must be a full Git SHA.",
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def _new_application(
    *,
    source: DeterministicReleaseMarketSource,
    artifact_root: Path,
    market_path_store: ParquetMarketPathArtifactStore | None = None,
    ptrade_host: PTradeStrategyHost | None = None,
) -> DiagnosticsApplication:
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=(
            market_path_store
            if market_path_store is not None
            else ParquetMarketPathArtifactStore(
                artifact_root / "market-paths"
            )
        ),
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(
            artifact_root
        ),
        recipe_clock=lambda: RELEASE_FIXTURE_CLOCK,
        ptrade_host=ptrade_host,
    )


def _prepare_wave2_authoritative_inputs(
    application: DiagnosticsApplication,
) -> None:
    admitted = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
    )
    segment_id = admitted.segment.segment_id
    _approve_and_materialize(
        application,
        segment_id=segment_id,
        name="Installed Wave 2 baseline",
        transformations=(),
    )
    for name, transformations in _sensitivity_recipe_inputs():
        _approve_and_materialize(
            application,
            segment_id=segment_id,
            name=f"Installed Wave 2 {name}",
            transformations=transformations,
        )
    _approve_and_materialize(
        application,
        segment_id=segment_id,
        name="Installed Wave 2 compound",
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.20",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.25"},
            },
        ),
    )
    _require(
        bool(application.list_available_diagnostic_campaign_cases()),
        "Wave 2 release inputs produced no available Campaign Cases.",
    )


def _wave2_authoritative_input_identities(
    application: DiagnosticsApplication,
) -> tuple[str, ...]:
    values = {
        *(
            item.segment_id
            for item in application.list_historical_segments()
        ),
        *(
            item.version_id
            for item in application.list_approved_scenario_recipes()
        ),
        *(
            item.content_hash
            for item in application.list_approved_scenario_recipes()
        ),
        *(
            item.artifact_hash
            for item in application.list_materialized_market_paths()
        ),
        *(
            item.case_id
            for item in application.list_available_diagnostic_campaign_cases()
        ),
    }
    identities = tuple(sorted(values))
    _require(
        bool(identities),
        "Wave 2 release input identity inventory is empty.",
    )
    return identities


def _create_completed_formal_campaign(
    application: DiagnosticsApplication,
) -> tuple[
    DiagnosticCampaignSnapshot,
    DiagnosticEvidencePackage,
    tuple[ReproductionManifest, ...],
]:
    admitted = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
    )
    segment_id = admitted.segment.segment_id
    baseline_version, baseline_path = _approve_and_materialize(
        application,
        segment_id=segment_id,
        name="Integrated release baseline",
        transformations=(),
    )
    application.run_baseline_campaign(
        baseline_version.version_id,
        baseline_path.artifact_hash,
        initial_cash=Decimal("100000"),
        order_shares=1000,
        campaign_replica_id="integrated-release-baseline",
    )
    baseline_anchor = (
        baseline_version.version_id,
        baseline_path.artifact_hash,
    )

    sensitivity_anchors: list[tuple[str, str]] = []
    for name, transformations in _sensitivity_recipe_inputs():
        version, path = _approve_and_materialize(
            application,
            segment_id=segment_id,
            name=name,
            transformations=transformations,
        )
        case = application.create_isolated_sensitivity_case(
            version.version_id,
            path.artifact_hash,
        )
        _require(
            case.case_id,
            "An Isolated Sensitivity Case lacks its durable identity.",
        )
        sensitivity_anchors.append(
            (version.version_id, path.artifact_hash)
        )
    sensitivity = application.plan_isolated_sensitivity_set(
        tuple(sensitivity_anchors),
        initial_cash=Decimal("100000"),
        order_shares=1000,
        sensitivity_set_replica_id="integrated-release-isolated",
    )

    compound_version, compound_path = _approve_and_materialize(
        application,
        segment_id=segment_id,
        name="Integrated release compound",
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.20",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.25"},
            },
        ),
    )
    compound_case = application.create_diagnostic_campaign_case(
        compound_version.version_id,
        compound_path.artifact_hash,
    )
    _require(
        compound_case.layer == "compound",
        "The release Compound Campaign Case was not classified as compound.",
    )
    planned = application.plan_diagnostic_campaign(
        baseline_anchor=baseline_anchor,
        isolated_sensitivity_set_id=sensitivity.sensitivity_set_id,
        compound_case_anchors=(
            (
                compound_version.version_id,
                compound_path.artifact_hash,
            ),
        ),
        initial_cash=Decimal("100000"),
        order_shares=1000,
        campaign_replica_id="integrated-release-formal",
    )
    _require(
        planned.specification.campaign_type
        == "formal_diagnostic_campaign",
        "The release fixture is not a Formal Diagnostic Campaign.",
    )
    completed = application.resume_diagnostic_campaign(
        planned.campaign_id
    )
    _require(
        completed.status == "completed",
        "The release Formal Diagnostic Campaign did not complete.",
    )
    package = application.build_diagnostic_evidence(
        completed.campaign_id
    )
    _require(
        package.sealed_payload().get("status") == "sealed",
        "The release Diagnostic Evidence package is not sealed.",
    )
    manifests = tuple(
        application.reproduction_manifests(
            package.evidence_package_id
        )
    )
    _require(
        bool(manifests),
        "The release Diagnostic Evidence has no Reproduction Manifests.",
    )
    # Normalize the just-executed in-memory campaign through the public
    # persistence boundary before comparing it with a fresh process view.
    # Completed case outcomes are deliberately rehydrated as immutable stored
    # payloads rather than live BaselineCampaignSnapshot instances.
    persisted_campaign = application.diagnostic_campaign_status(
        completed.campaign_id
    )
    return persisted_campaign, package, manifests


def _approve_and_materialize(
    application: DiagnosticsApplication,
    *,
    segment_id: str,
    name: str,
    transformations: tuple[dict[str, object], ...],
) -> tuple[ApprovedScenarioRecipeVersion, MaterializedMarketPath]:
    draft = application.create_manual_recipe_draft(
        {
            "schema_version": "scenario_recipe.v1",
            "name": name,
            "historical_segment_id": segment_id,
            "transformations": list(transformations),
            "execution_conditions": {
                "commission_bps": "3",
                "slippage_bps": "5",
                "max_fill_fraction": "1",
                "latency_nodes": 0,
                "allow_partial_fills": True,
            },
            "decision_cadence_minutes": 30,
            "materialization_seed": 17,
            "data_policy": "point-in-time",
            "market_rule_profile": "a-share-cash-equity.v1",
        },
        author="release-certifier",
    )
    validation = application.validate_recipe_draft(draft.draft_id)
    _require(
        validation.is_valid,
        f"The release recipe {name!r} failed validation.",
    )
    approved = application.approve_recipe_draft(
        draft.draft_id,
        actor="release-owner",
    )
    materialized = application.materialize_reference_path(
        approved.version_id
    )
    return approved, materialized


def _sensitivity_recipe_inputs(
) -> tuple[tuple[str, tuple[dict[str, object], ...]], ...]:
    inputs: list[tuple[str, tuple[dict[str, object], ...]]] = []
    for index, strength in enumerate(("0.10", "0.20"), start=1):
        inputs.append(
            (
                f"Integrated release trend {index}",
                (
                    {
                        "transformation_id": "trend-regime.v1",
                        "parameters": {
                            "direction": "bullish",
                            "strength": strength,
                        },
                    },
                ),
            )
        )
    for index, multiplier in enumerate(("0.75", "1.25"), start=1):
        inputs.append(
            (
                f"Integrated release volatility {index}",
                (
                    {
                        "transformation_id": "volatility-scaling.v1",
                        "parameters": {"multiplier": multiplier},
                    },
                ),
            )
        )
    for index, fraction in enumerate(("0.02", "0.04"), start=1):
        inputs.append(
            (
                f"Integrated release shock {index}",
                (
                    {
                        "transformation_id": "shock-recovery.v1",
                        "parameters": {
                            "direction": "bearish",
                            "gap_fraction": "0.01",
                            "shock_fraction": fraction,
                            "shock_duration_bars": 1,
                            "persistence_duration_bars": 0,
                            "recovery_duration_bars": 1,
                        },
                    },
                ),
            )
        )
    for index, breadth in enumerate(("0.25", "0.75"), start=1):
        inputs.append(
            (
                f"Integrated release structure {index}",
                (
                    {
                        "transformation_id": "market-structure.v1",
                        "parameters": {
                            "breadth_target": breadth,
                            "dispersion_fraction": "0.02",
                            "sector_concentration": "0.75",
                        },
                    },
                ),
            )
        )
    for index, multiplier in enumerate(("0.50", "1.50"), start=1):
        inputs.append(
            (
                f"Integrated release liquidity {index}",
                (
                    {
                        "transformation_id": "liquidity-stress.v1",
                        "parameters": {
                            "volume_multiplier": multiplier,
                            "cross_sectional_concentration": "0.50",
                        },
                    },
                ),
            )
        )
    for index, slippage in enumerate(("25", "100"), start=1):
        inputs.append(
            (
                f"Integrated release execution {index}",
                (
                    {
                        "transformation_id": "execution-stress.v1",
                        "parameters": {
                            "commission_bps": "8",
                            "slippage_bps": slippage,
                            "max_fill_fraction": "1",
                            "latency_nodes": 0,
                            "allow_partial_fills": "true",
                            "rejection_mode": "none",
                        },
                    },
                ),
            )
        )
    return tuple(inputs)


def _require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


__all__ = [
    "FORMAL_V1_RELEASE_FIXTURE_ARCHIVE",
    "FORMAL_V1_RELEASE_FIXTURE_DIRNAME",
    "FORMAL_V1_RELEASE_FIXTURE_MANIFEST",
    "RELEASE_FIXTURE_CLOCK",
    "WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE",
    "WAVE2_RELEASE_INPUT_FIXTURE_DIRNAME",
    "WAVE2_RELEASE_INPUT_FIXTURE_MANIFEST",
    "DeterministicReleaseMarketSource",
    "FileBackedFormalV1ReleaseFixture",
    "FileBackedWave2ReleaseInputFixture",
    "SealedFormalV1ReleaseFixtureFile",
    "SealedFormalV1ReleaseFixtureManifest",
    "SealedWave2ReleaseInputFixtureManifest",
    "create_file_backed_formal_v1_release_fixture",
    "create_file_backed_wave2_release_input_fixture",
    "create_sealed_formal_v1_release_fixture",
    "create_sealed_wave2_release_input_fixture",
    "extract_sealed_formal_v1_release_fixture_archive",
    "extract_sealed_wave2_release_input_fixture_archive",
    "load_sealed_formal_v1_release_fixture_manifest",
    "load_sealed_wave2_release_input_fixture_manifest",
    "open_sealed_formal_v1_release_fixture",
    "open_sealed_wave2_release_input_fixture",
    "reopen_active_wave2_release_input_fixture",
    "reopen_completed_wave2_release_fixture",
    "write_sealed_formal_v1_release_fixture_archive",
    "write_sealed_wave2_release_input_fixture_archive",
]
