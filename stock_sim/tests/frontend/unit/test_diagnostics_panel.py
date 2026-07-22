from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.panels.diagnostics.panel import DiagnosticsPanel
from app.ui.adapters.diagnostics_adapter import DiagnosticsPanelAdapter
from strategy_diagnostics import (
    AdmissionCheck,
    FiveMinuteBar,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryMarketPathArtifactStore,
    InMemoryHistoricalSource,
    InstrumentState,
    ScenarioDataWorldInput,
    SourceArtifact,
    SourceProvenance,
    UnapprovedScenarioRecipeError,
    create_diagnostics_application,
)


REQUIRED_CHECKS = (
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


class _WorkspaceSource:
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
                    label="Visible diagnostic interval",
                    provenance=SourceProvenance(
                        provider="BaoStock",
                        dataset="workspace-fixture",
                        version="v1",
                        observed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    ),
                    artifacts=(SourceArtifact("bars", "f" * 64, 48),),
                    eligible_instrument_count=1,
                    trading_day_count=1,
                    bar_count=48,
                    checks=tuple(
                        AdmissionCheck(code, True, f"{code} passed")
                        for code in REQUIRED_CHECKS
                    ),
                ),
            )
        )

    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        return self._source.inspect(selection)

    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
        return ScenarioDataWorldInput(
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
            bars=(
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=datetime(2024, 1, 2, 9, 35),
                    open=Decimal("10"),
                    high=Decimal("10.2"),
                    low=Decimal("9.9"),
                    close=Decimal("10.1"),
                    volume=100,
                    amount=Decimal("1005"),
                ),
            ),
            instrument_states=(
                InstrumentState(
                    instrument="sh.600000",
                    effective_at=datetime(2024, 1, 2, 9, 30),
                    eligible=True,
                    trading_status="trading",
                    is_st=False,
                    industry="banking",
                    decision_adjustment_factor=Decimal("1"),
                    decision_adjustment_provenance="fixture-v1",
                ),
            ),
        )


def _admittable_application() -> object:
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )
    source = _WorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


def _ensure_qapp() -> object | None:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    return QApplication.instance() or QApplication([])


def test_diagnostics_panel_uses_the_headless_application_interface() -> None:
    application = create_diagnostics_application()
    panel = DiagnosticsPanel(application)

    view = panel.get_view()

    assert {
        key: view[key] for key in application.status().to_dict()
    } == application.status().to_dict()
    assert view["workspace"] == "Diagnostics"
    assert view["status"] == "ready"
    assert view["historical_segment_catalog"] == {
        "status": "not_checked",
        "segment_count": 0,
        "segments": [],
        "latest_admission": None,
        "recommendations": [],
    }


def test_diagnostics_adapter_renders_the_logic_panel_view() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(create_diagnostics_application())
    adapter = DiagnosticsPanelAdapter().bind(panel)

    widget = adapter.widget()

    assert widget is not None
    assert adapter.current_view() == panel.get_view()


def test_diagnostics_workspace_admits_and_displays_segment_provenance() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]

    admission = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    view = panel.get_view()
    catalog = view["historical_segment_catalog"]

    assert admission["status"] == "admitted"
    assert catalog["status"] == "admitted"
    assert catalog["segment_count"] == 1
    assert catalog["segments"][0]["provenance"] == {
        "provider": "BaoStock",
        "dataset": "workspace-fixture",
        "version": "v1",
        "observed_at": "2026-07-21T00:00:00+00:00",
    }
    visible_payload = repr(catalog).lower()
    assert "storage_path" not in visible_payload
    assert "duckdb" not in visible_payload
    assert "parquet" not in visible_payload


def test_diagnostics_workspace_returns_a_bounded_recommendation_shortlist() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )

    recommendations = panel.recommend_historical_segments(
        intent="visible interval",
        limit=10,
    )

    assert len(recommendations) == 1
    assert recommendations[0]["rank"] == 1
    assert panel.get_view()["historical_segment_catalog"]["recommendations"] == (
        recommendations
    )


def test_diagnostics_workspace_completes_the_manual_recipe_lifecycle() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]

    draft = panel.create_baseline_recipe(
        name="Thirty minute baseline",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    assert draft["status"] == "untrusted"
    assert panel.get_view()["scenario_recipe_workbench"]["status"] == "draft"

    validation = panel.validate_current_recipe()
    assert validation["is_valid"] is True
    assert validation["issues"] == []

    approved = panel.approve_current_recipe(actor="owner")
    assert approved["approval_actor"] == "owner"
    assert approved["approved_at"] == "2026-07-22T08:00:00+00:00"

    materialized = panel.materialize_current_recipe()
    assert materialized["segment_id"] == segment_id
    workbench = panel.get_view()["scenario_recipe_workbench"]
    assert workbench["status"] == "materialized"
    assert workbench["approved_version"]["version_id"] == approved["version_id"]
    assert workbench["materialization"]["artifact_hash"]


def test_diagnostics_workspace_shows_actionable_recipe_validation_feedback() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Unsupported cadence",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=15,
        seed=17,
    )

    validation = panel.validate_current_recipe()

    assert validation["is_valid"] is False
    assert validation["issues"][0]["rule"] == "bounds.invalid"
    assert validation["issues"][0]["correction"]
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        panel.approve_current_recipe(actor="owner")


def test_diagnostics_adapter_drives_recipe_review_approval_and_materialization() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()

    adapter._recipe_name_input.setText("UI baseline")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    workbench = adapter.current_view()["scenario_recipe_workbench"]
    assert workbench["status"] == "materialized"
    assert workbench["validation"]["is_valid"] is True
    assert workbench["approved_version"]["approval_actor"] == "owner"


def test_diagnostics_adapter_can_admit_and_recommend_without_storage_controls() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()

    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()

    admitted_view = adapter.current_view()
    assert admitted_view["historical_segment_catalog"]["status"] == "admitted"

    adapter._intent_input.setText("visible interval")
    adapter._recommend_button.click()

    catalog = adapter.current_view()["historical_segment_catalog"]
    assert len(catalog["recommendations"]) == 1
    visible_controls = repr(adapter.widget()).lower()
    assert "storage" not in visible_controls
    assert "duckdb" not in visible_controls


def test_desktop_shell_registers_diagnostics_as_a_primary_workspace() -> None:
    from app import panels
    from app.i18n import set_language
    from app.panels import (
        get_panel,
        list_panels,
        register_builtin_panels,
        register_ui_adapters,
        reset_registry,
    )
    from app.ui.main_window import (
        DEFAULT_PRELOAD_PANELS,
        MainWindow,
    )

    set_language("zh_CN")
    reset_registry()
    register_builtin_panels()
    register_ui_adapters()

    descriptors = {item["name"]: item for item in list_panels()}
    assert descriptors["diagnostics"]["title"] in {"Diagnostics", "策略诊断"}
    assert isinstance(get_panel("diagnostics"), DiagnosticsPanelAdapter)
    assert "diagnostics" in DEFAULT_PRELOAD_PANELS

    _ensure_qapp()
    window = MainWindow()
    assert window.open_panel("diagnostics") is not None
    assert window.serialize_layout()["panels"]["diagnostics"]["open"] is True
    diagnostics_page = window._workspace_pages["diagnostics"]
    diagnostics_index = window._workspace_stack.indexOf(diagnostics_page)
    assert window._nav_list.item(diagnostics_index).text() == "策略诊断"


def test_diagnostics_adapter_failure_preserves_the_legacy_shell(
    monkeypatch: object,
) -> None:
    from app import panels
    from app.panels import list_panels, register_builtin_panels, reset_registry

    original_replace_panel = panels.replace_panel

    def fail_diagnostics_registration(name: str, *args: object, **kwargs: object) -> object:
        if name == "diagnostics":
            raise RuntimeError("diagnostics adapter unavailable")
        return original_replace_panel(name, *args, **kwargs)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        panels,
        "replace_panel",
        fail_diagnostics_registration,
    )
    reset_registry()
    register_builtin_panels()

    panels.register_ui_adapters()

    descriptors = {item["name"]: item for item in list_panels()}
    assert descriptors["diagnostics"]["created"] is False
    assert "account" in descriptors
