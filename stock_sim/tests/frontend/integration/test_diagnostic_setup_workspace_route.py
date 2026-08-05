from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtTest import QSignalSpy

from app.features import DeterministicFakeDiagnosticTasksAdapter
from app.features.diagnostic_setup import (
    DiagnosticSetupSelectionCoordinator,
    compose_diagnostic_setup_selection_context,
)
from app.ui.journey_workspace import DiagnosticTasksQtAdapter
from tests.frontend.contract.test_diagnostic_setup_selection_context import (
    _scenario_selection,
    _strategy_context,
)


def test_diagnostic_tasks_adapter_gates_and_uses_exact_upstream_selection(
    monkeypatch,
) -> None:
    coordinator = DiagnosticSetupSelectionCoordinator()
    feature = DeterministicFakeDiagnosticTasksAdapter(
        setup_selection_provider=coordinator.current,
    )
    setup = compose_diagnostic_setup_selection_context(
        _strategy_context(),
        _scenario_selection(),
    )
    current = {"setup": None}
    adapter = DiagnosticTasksQtAdapter(
        feature,
        setup_selection_provider=lambda: current["setup"],
        setup_selection_coordinator=coordinator,
    )
    adapter.refresh()

    assert not adapter.canCreate
    assert not adapter.setupSelectionReady
    assert "Select one current formal Strategy set" in adapter.setupSelectionText

    spy = QSignalSpy(adapter.stateChanged)
    current["setup"] = setup
    adapter.upstreamSelectionChanged()

    assert spy.count() == 1
    assert adapter.canCreate
    assert adapter.setupSelectionReady
    for identity in (
        setup.context_identity,
        setup.strategy_selection.context_identity,
        setup.scenario_selection.context.selection_context_id.value,
        setup.scenario_selection.context.scenario_set_id.value,
        setup.scenario_selection.context.execution_resolution_id.value,
        setup.configuration.content_identity.value,
    ):
        assert identity in adapter.setupSelectionText

    captured = []
    original = feature.create_diagnostic_task

    def capture(command):
        captured.append(command.configuration)
        return original(command)

    monkeypatch.setattr(feature, "create_diagnostic_task", capture)
    adapter.createTask()
    assert captured == [setup.configuration]

    adapter.refresh()
    assert adapter.canValidate
    remounted = DiagnosticTasksQtAdapter(
        feature,
        setup_selection_provider=lambda: current["setup"],
        setup_selection_coordinator=coordinator,
    )
    remounted.refresh()
    assert not remounted.canValidate
    assert not remounted.canApprove
    assert not remounted.canStartCampaign
    remounted.close()

    successor_strategy = replace(
        setup.strategy_selection,
        context_identity=setup.strategy_selection.context_identity + "-successor",
        originating_view_revision=(
            setup.strategy_selection.originating_view_revision + 1
        ),
    )
    successor = compose_diagnostic_setup_selection_context(
        successor_strategy,
        setup.scenario_selection,
    )
    assert successor.configuration == setup.configuration
    current["setup"] = successor
    adapter.upstreamSelectionChanged()
    assert adapter.canRevise
    assert not adapter.canValidate
    assert not adapter.canApprove
    assert not adapter.canStartCampaign

    adapter.reviseTask()
    adapter.refresh()
    assert adapter.canValidate

    current["setup"] = None
    adapter.upstreamSelectionChanged()
    assert not adapter.canCreate
    assert not adapter.canRevise
    assert not adapter.canValidate
    assert not adapter.canApprove
    assert not adapter.canStartCampaign

    adapter.close()
    feature.close()


def test_qml_exposes_exact_setup_identity_and_accessible_handoff() -> None:
    source = (
        Path(__file__).parents[3]
        / "app"
        / "ui"
        / "qml"
        / "DiagnosticTasksPage.qml"
    ).read_text(encoding="utf-8")

    assert 'heading: "EXACT SETUP SELECTION"' in source
    assert "detail: adapter.setupSelectionText" in source
    assert "Accessible.description: adapter.setupSelectionText" in source
    assert (
        "Create one durable task from the exact current Strategy and Scenario "
        "setup selection"
    ) in source
