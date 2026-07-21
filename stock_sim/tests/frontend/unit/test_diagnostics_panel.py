from __future__ import annotations

import os
from datetime import date, datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.panels.diagnostics.panel import DiagnosticsPanel
from app.ui.adapters.diagnostics_adapter import DiagnosticsPanelAdapter
from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
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


def _admittable_application() -> object:
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )
    source = InMemoryHistoricalSource(
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
    return create_diagnostics_application(historical_source=source)


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
