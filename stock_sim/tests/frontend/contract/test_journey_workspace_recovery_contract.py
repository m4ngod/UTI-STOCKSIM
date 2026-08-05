from __future__ import annotations

import json

import pytest

from app.app_context import build_app_context
from app.features import (
    DiagnosticTaskId,
    DiagnosticTasksContext,
    ScenarioLabContext,
    ScenarioLabFocusTarget,
)
from app.journey_recovery import (
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
    decode_journey_workspace_bookmark,
    encode_journey_workspace_bookmark,
)


def test_workspace_bookmark_codec_is_strict_typed_and_immutable() -> None:
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
        diagnostic_task_id=DiagnosticTaskId("diagnostic-task-85"),
        scenario_focus_target=ScenarioLabFocusTarget.REFERENCE_PATH,
        scenario_focus_identity="reference-path-85",
    )

    encoded = encode_journey_workspace_bookmark(bookmark)

    assert decode_journey_workspace_bookmark(encoded) == bookmark
    assert json.loads(encoded) == {
        "diagnostic_task_id": "diagnostic-task-85",
        "last_route": "evidence_and_findings",
        "scenario_focus_identity": "reference-path-85",
        "scenario_focus_target": "reference_path",
        "schema_version": "1.0",
    }
    with pytest.raises(AttributeError):
        bookmark.last_route = JourneyWorkspaceRoute.SCENARIO_LAB  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    (
        "",
        "[]",
        '{"schema_version":"2.0"}',
        (
            '{"schema_version":"1.0","last_route":"scenario_lab",'
            '"diagnostic_task_id":null,"scenario_focus_target":"search",'
            '"scenario_focus_identity":null,"unexpected":true}'
        ),
        (
            '{"schema_version":"1.0","last_route":"unknown",'
            '"diagnostic_task_id":null,"scenario_focus_target":"search",'
            '"scenario_focus_identity":null}'
        ),
        (
            '{"schema_version":"1.0","last_route":"scenario_lab",'
            '"diagnostic_task_id":42,"scenario_focus_target":"search",'
            '"scenario_focus_identity":null}'
        ),
    ),
)
def test_workspace_bookmark_decoder_fails_closed(payload: str) -> None:
    assert decode_journey_workspace_bookmark(payload) is None


def test_workspace_bookmark_rejects_incoherent_focus() -> None:
    with pytest.raises(ValueError, match="detail focus requires an identity"):
        JourneyWorkspaceBookmark(
            scenario_focus_target=ScenarioLabFocusTarget.MARKET_SCENARIO,
        )
    with pytest.raises(ValueError, match="search focus cannot carry an identity"):
        JourneyWorkspaceBookmark(
            scenario_focus_target=ScenarioLabFocusTarget.SEARCH,
            scenario_focus_identity="not-authoritative-search-state",
        )


def test_app_context_reopens_only_typed_route_focus_and_task_identity(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    settings_path = tmp_path / "frontend-settings.json"
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.SCENARIO_LAB,
        diagnostic_task_id=DiagnosticTaskId("diagnostic-task-durable-85"),
        scenario_focus_target=ScenarioLabFocusTarget.MARKET_SCENARIO,
        scenario_focus_identity="market-scenario-durable-85",
    )
    settings_path.write_text(
        json.dumps(
            {
                "journey_workspace_bookmark_json": (
                    encode_journey_workspace_bookmark(bookmark)
                )
            }
        ),
        encoding="utf-8",
    )

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    try:
        assert context.journey_workspace_bookmark == bookmark
        assert context.diagnostic_tasks_context == DiagnosticTasksContext(
            task_id=DiagnosticTaskId("diagnostic-task-durable-85")
        )
        assert context.scenario_lab_context == ScenarioLabContext(
            focus_target=ScenarioLabFocusTarget.MARKET_SCENARIO,
            focus_identity="market-scenario-durable-85",
        )

        updated = JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.RUN_MONITORING,
            diagnostic_task_id=bookmark.diagnostic_task_id,
            scenario_focus_target=bookmark.scenario_focus_target,
            scenario_focus_identity=bookmark.scenario_focus_identity,
        )
        context.persist_journey_workspace_bookmark(updated)
        persisted = json.loads(settings_path.read_text(encoding="utf-8"))
        assert decode_journey_workspace_bookmark(
            persisted["journey_workspace_bookmark_json"]
        ) == updated
    finally:
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
