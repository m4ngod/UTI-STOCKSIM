from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from strategy_diagnostics import (
    AdmissionCheck,
    AIRecipeAssistantRequest,
    AIRecipeDraftOutputV1,
    DeterministicFakeAIRecipeAssistant,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    OpenAIResponsesRecipeAssistant,
    ScenarioRecipeV1,
    SourceArtifact,
    SourceProvenance,
    TransformationProposalV1,
    UnapprovedScenarioRecipeError,
    create_diagnostics_application,
)


class _ProviderFixtureTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def create_response(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class _ProviderFailureTransport:
    def create_response(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        raise RuntimeError("provider unavailable")


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


def _admitted_segment_fixture() -> tuple[
    InMemoryHistoricalSource,
    HistoricalSegmentSelection,
    str,
]:
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    inspection = HistoricalSourceInspection(
        selection=selection,
        label="AI recipe fixture",
        provenance=SourceProvenance(
            provider="Fixture",
            dataset="ai-recipe-assistant",
            version="v1",
            observed_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        ),
        artifacts=(SourceArtifact("bars", "a" * 64, 100),),
        eligible_instrument_count=2,
        trading_day_count=2,
        bar_count=100,
        checks=tuple(
            AdmissionCheck(code, True, f"{code} passed")
            for code in _REQUIRED_ADMISSION_CHECKS
        ),
    )
    source = InMemoryHistoricalSource((inspection,))
    probe = create_diagnostics_application(historical_source=source)
    probe.start()
    admission = probe.admit_historical_segment(selection)
    assert admission.segment is not None
    return source, selection, admission.segment.segment_id


def test_deterministic_fake_emits_the_model_independent_draft_contract() -> None:
    output = AIRecipeDraftOutputV1(
        recipe=ScenarioRecipeV1(
            name="Bullish trend diagnostic",
            historical_segment_id="segment_fixture",
            transformations=(
                {
                    "transformation_id": "trend-regime.v1",
                    "parameters": {
                        "direction": "bullish",
                        "strength": "0.4",
                    },
                },
            ),
            decision_cadence_minutes=30,
            materialization_seed=17,
        ),
        transformation_proposals=(
            TransformationProposalV1(
                capability="intraday-order-book-imbalance",
                description="Model an order-book imbalance regime.",
                rationale="The registered catalog has no order-book transform.",
            ),
        ),
    )
    request = AIRecipeAssistantRequest(
        intent="Create a bullish trend regime and note missing breadth support.",
        scenario_recipe_schema=ScenarioRecipeV1.stable_json_schema(),
        admitted_segments=(
            {
                "segment_id": "segment_fixture",
                "label": "Fixture segment",
            },
        ),
        transformation_catalog={
            "catalog_version": "scenario-transformation-catalog.v1",
            "transformations": [
                {
                    "transformation_id": "trend-regime.v1",
                    "parameters": ["direction", "strength"],
                }
            ],
        },
    )

    assistant = DeterministicFakeAIRecipeAssistant(output=output)
    response = assistant.draft(request)

    assert response.output.to_dict() == {
        "schema_version": "ai_recipe_draft_output.v1",
        "recipe": {
            "data_policy": "point-in-time",
            "decision_cadence_minutes": 30,
            "execution_conditions": {
                "allow_partial_fills": True,
                "commission_bps": "3",
                "latency_nodes": 0,
                "max_fill_fraction": "1",
                "slippage_bps": "0",
            },
            "historical_segment_id": "segment_fixture",
            "market_rule_profile": "a-share-cash-equity.v1",
            "materialization_seed": 17,
            "name": "Bullish trend diagnostic",
            "schema_version": "scenario_recipe.v1",
            "transformations": [
                {
                    "parameters": {
                        "direction": "bullish",
                        "strength": "0.4",
                    },
                    "transformation_id": "trend-regime.v1",
                }
            ],
        },
        "transformation_proposals": [
            {
                "capability": "intraday-order-book-imbalance",
                "description": "Model an order-book imbalance regime.",
                "rationale": "The registered catalog has no order-book transform.",
                "schema_version": "transformation_proposal.v1",
                "status": "non_executable",
            }
        ],
    }
    assert response.output == output
    assert assistant.provider == "deterministic-fake"
    assert assistant.model == "deterministic-recipe-fixture.v1"
    assert assistant.prompt_template_version == "ai-recipe-assistant.v1"
    assert response.response_id.startswith("fake_response_")


def test_openai_responses_adapter_emits_the_same_draft_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = AIRecipeDraftOutputV1(
        recipe=ScenarioRecipeV1(
            name="Bullish trend diagnostic",
            historical_segment_id="segment_fixture",
            transformations=(
                {
                    "transformation_id": "trend-regime.v1",
                    "parameters": {
                        "direction": "bullish",
                        "strength": "0.4",
                    },
                },
            ),
            decision_cadence_minutes=30,
            materialization_seed=17,
        ),
        transformation_proposals=(),
    )
    transport = _ProviderFixtureTransport(
        {
            "id": "resp_fixture_001",
            "model": "gpt-5.6-sol",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": expected.canonical_json(),
                        }
                    ],
                }
            ],
        }
    )
    scenario_recipe_schema = ScenarioRecipeV1.stable_json_schema()
    scenario_recipe_schema["properties"]["name"]["maxLength"] = 37
    ai_output_schema = copy.deepcopy(AIRecipeDraftOutputV1.schema())
    ai_output_schema["definitions"]["TransformationProposalV1"]["properties"][
        "capability"
    ]["maxLength"] = 73
    monkeypatch.setattr(
        AIRecipeDraftOutputV1,
        "schema",
        classmethod(lambda cls: ai_output_schema),
    )
    request = AIRecipeAssistantRequest(
        intent="Create a bullish trend regime.",
        scenario_recipe_schema=scenario_recipe_schema,
        admitted_segments=(
            {
                "segment_id": "segment_fixture",
                "label": "Fixture segment",
            },
        ),
        transformation_catalog={
            "catalog_version": "scenario-transformation-catalog.v1",
            "transformations": [
                {
                    "transformation_id": "trend-regime.v1",
                    "family": "trend-regime",
                    "implementation_version": "trend-regime.v1",
                    "parameters": [
                        {
                            "name": "direction",
                            "value_type": "enum",
                            "required": True,
                            "choices": ["bearish", "bullish"],
                        },
                        {
                            "name": "strength",
                            "value_type": "decimal",
                            "required": True,
                            "minimum": "0",
                            "maximum": "1",
                        },
                    ],
                    "compatibility_rules": [
                        "a-share-cash-equity.v1",
                        "one-transform-per-family",
                    ],
                    "causality_constraints": [
                        "point-in-time-inputs-only",
                        "deterministic-no-future-reads",
                    ],
                },
                {
                    "transformation_id": "shock-recovery.v1",
                    "family": "shock-recovery",
                    "implementation_version": "shock-recovery.v1",
                    "parameters": [
                        {
                            "name": "shock_duration_bars",
                            "value_type": "integer",
                            "required": True,
                            "minimum": "1",
                            "maximum": "12",
                        }
                    ],
                    "compatibility_rules": [
                        "a-share-cash-equity.v1",
                        "one-transform-per-family",
                    ],
                    "causality_constraints": [
                        "point-in-time-inputs-only",
                        "deterministic-no-future-reads",
                    ],
                },
            ],
        },
    )

    assistant = OpenAIResponsesRecipeAssistant(
        transport=transport,
        model="gpt-5.6-sol",
        prompt_template_version="ai-recipe-assistant.v1",
    )
    response = assistant.draft(request)

    assert response.response_id == "resp_fixture_001"
    assert response.output == expected
    assert assistant.provider == "openai"
    assert assistant.model == "gpt-5.6-sol"
    assert assistant.prompt_template_version == "ai-recipe-assistant.v1"
    assert len(transport.requests) == 1
    provider_request = transport.requests[0]
    assert provider_request["model"] == "gpt-5.6-sol"
    assert provider_request["store"] is False
    assert "tools" not in provider_request
    text_format = provider_request["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "ai_recipe_draft_output_v1"
    assert text_format["strict"] is True
    assert text_format["schema"]["additionalProperties"] is False
    recipe_schema = text_format["schema"]["properties"]["recipe"]
    assert recipe_schema["properties"]["name"]["maxLength"] == 37
    assert recipe_schema["properties"]["historical_segment_id"]["enum"] == [
        "segment_fixture"
    ]
    execution_schema = recipe_schema["properties"]["execution_conditions"]
    assert set(execution_schema["required"]) == set(
        execution_schema["properties"]
    )
    assert "default" not in execution_schema["properties"]["commission_bps"]
    proposal_schema = text_format["schema"]["properties"][
        "transformation_proposals"
    ]["items"]
    assert proposal_schema["properties"]["capability"]["maxLength"] == 73
    transformation_schema = recipe_schema["properties"]["transformations"]["items"]
    variants = transformation_schema["anyOf"]
    variants_by_id = {
        variant["properties"]["transformation_id"]["enum"][0]: variant
        for variant in variants
    }
    assert set(variants_by_id) == {"shock-recovery.v1", "trend-regime.v1"}
    shock_parameters = variants_by_id["shock-recovery.v1"]["properties"][
        "parameters"
    ]
    assert shock_parameters["properties"]["shock_duration_bars"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 12,
    }


def test_openai_production_adapter_uses_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-sent")
    monkeypatch.setenv("STRATEGY_DIAGNOSTICS_AI_MODEL", "gpt-5.6-sol")

    assistant = OpenAIResponsesRecipeAssistant.from_environment()

    assert assistant.provider == "openai"
    assert assistant.model == "gpt-5.6-sol"
    assert assistant.prompt_template_version == "ai-recipe-assistant.v1"


def test_application_turns_ai_intent_into_a_valid_but_untrusted_draft() -> None:
    source, selection, segment_id = _admitted_segment_fixture()
    assistant = DeterministicFakeAIRecipeAssistant(
        output=AIRecipeDraftOutputV1(
            recipe=ScenarioRecipeV1(
                name="Bullish trend diagnostic",
                historical_segment_id=segment_id,
                transformations=(
                    {
                        "transformation_id": "trend-regime.v1",
                        "parameters": {
                            "direction": "bullish",
                            "strength": "0.4",
                        },
                    },
                ),
                decision_cadence_minutes=30,
                materialization_seed=17,
            ),
            transformation_proposals=(
                TransformationProposalV1(
                    capability="intraday-order-book-imbalance",
                    description="Model an order-book imbalance regime.",
                    rationale="The registered catalog has no order-book transform.",
                ),
            ),
        )
    )
    application = create_diagnostics_application(
        historical_source=source,
        recipe_assistant=assistant,
        recipe_clock=lambda: datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
    )
    application.start()
    admitted = application.admit_historical_segment(selection)
    assert admitted.segment is not None

    result = application.author_recipe_with_ai(
        "Create a bullish trend regime and retain the missing breadth idea.",
        author="scenario-researcher",
    )

    assert result.status == "draft_valid"
    assert result.draft is not None
    assert result.draft.status == "untrusted"
    assert result.validation is not None
    assert result.validation.is_valid
    assert result.attempt.provider == "deterministic-fake"
    assert result.attempt.model == "deterministic-recipe-fixture.v1"
    assert result.attempt.prompt_template_version == "ai-recipe-assistant.v1"
    assert len(result.attempt.response_hash or "") == 64
    assert result.attempt.transformation_proposals[0].status == "non_executable"
    with pytest.raises(UnapprovedScenarioRecipeError, match="approved"):
        application.materialize_reference_path(result.draft.draft_id)


@pytest.mark.parametrize(
    ("invalid_kind", "expected_rule"),
    (
        ("unadmitted-segment", "data.admitted-segment-required"),
        ("unregistered-transformation", "transformation.not-registered"),
    ),
)
def test_ai_draft_rejects_unadmitted_segments_and_unregistered_transformations(
    invalid_kind: str,
    expected_rule: str,
) -> None:
    source, selection, admitted_segment_id = _admitted_segment_fixture()
    selected_segment_id = (
        "segment_not_admitted"
        if invalid_kind == "unadmitted-segment"
        else admitted_segment_id
    )
    selected_transformation_id = (
        "invented-transform.v1"
        if invalid_kind == "unregistered-transformation"
        else "trend-regime.v1"
    )
    assistant = DeterministicFakeAIRecipeAssistant(
        output=AIRecipeDraftOutputV1(
            recipe=ScenarioRecipeV1(
                name="Rejected AI diagnostic",
                historical_segment_id=selected_segment_id,
                transformations=(
                    {
                        "transformation_id": selected_transformation_id,
                        "parameters": {
                            "direction": "bullish",
                            "strength": "0.4",
                        },
                    },
                ),
                decision_cadence_minutes=30,
            ),
        )
    )
    application = create_diagnostics_application(
        historical_source=source,
        recipe_assistant=assistant,
    )
    application.start()
    admitted = application.admit_historical_segment(selection)
    assert admitted.segment is not None

    result = application.author_recipe_with_ai(
        "Create an unsupported diagnostic condition.",
        author="scenario-researcher",
    )

    assert result.status == "draft_invalid"
    assert result.draft is not None
    assert result.validation is not None
    assert not result.validation.is_valid
    assert expected_rule in {issue.rule for issue in result.validation.issues}
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        application.approve_recipe_draft(
            result.draft.draft_id,
            actor="owner",
        )
    with pytest.raises(UnapprovedScenarioRecipeError, match="approved"):
        application.materialize_reference_path(result.draft.draft_id)


def test_provider_failure_is_visible_and_creates_no_recipe_draft() -> None:
    source, selection, _ = _admitted_segment_fixture()
    assistant = OpenAIResponsesRecipeAssistant(
        transport=_ProviderFailureTransport(),
        model="gpt-5.6-sol",
    )
    application = create_diagnostics_application(
        historical_source=source,
        recipe_assistant=assistant,
        recipe_clock=lambda: datetime(2026, 7, 22, 6, 30, tzinfo=timezone.utc),
    )
    application.start()
    admitted = application.admit_historical_segment(selection)
    assert admitted.segment is not None

    result = application.author_recipe_with_ai(
        "Create a bullish trend regime.",
        author="scenario-researcher",
    )

    assert result.status == "provider_error"
    assert result.draft is None
    assert result.validation is None
    assert result.attempt.draft_id is None
    assert result.attempt.response_id is None
    assert result.attempt.response_hash is None
    assert result.attempt.error_code == "provider_error"
    assert "provider unavailable" in (result.attempt.error_message or "")
    with pytest.raises(ValueError, match="Unknown Scenario Recipe Draft"):
        application.approve_recipe_draft(
            result.attempt.attempt_id,
            actor="owner",
        )
    with pytest.raises(UnapprovedScenarioRecipeError, match="approved"):
        application.materialize_reference_path(result.attempt.attempt_id)


@pytest.mark.parametrize(
    ("response_id", "output_text"),
    [
        ("resp_malformed_json_001", "{not-json"),
        (
            "resp_schema_mismatch_001",
            '{"schema_version":"ai_recipe_draft_output.v1","recipe":{}}',
        ),
    ],
)
def test_malformed_provider_output_is_visible_and_creates_no_recipe_draft(
    response_id: str,
    output_text: str,
) -> None:
    source, selection, _ = _admitted_segment_fixture()
    transport = _ProviderFixtureTransport(
        {
            "id": response_id,
            "model": "gpt-5.6-sol",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                        }
                    ],
                }
            ],
        }
    )
    application = create_diagnostics_application(
        historical_source=source,
        recipe_assistant=OpenAIResponsesRecipeAssistant(
            transport=transport,
            model="gpt-5.6-sol",
        ),
        recipe_clock=lambda: datetime(2026, 7, 22, 6, 45, tzinfo=timezone.utc),
    )
    application.start()
    admitted = application.admit_historical_segment(selection)
    assert admitted.segment is not None

    result = application.author_recipe_with_ai(
        "Create a bullish trend regime.",
        author="scenario-researcher",
    )

    assert result.status == "malformed_output"
    assert result.draft is None
    assert result.validation is None
    assert result.attempt.draft_id is None
    assert result.attempt.response_id == response_id
    assert len(result.attempt.response_hash or "") == 64
    assert result.attempt.error_code == "malformed_output"
    assert "valid AI recipe draft" in (result.attempt.error_message or "")


def test_ai_audit_survives_restart_and_links_subsequent_approval(
    tmp_path: Path,
) -> None:
    source, selection, segment_id = _admitted_segment_fixture()
    assistant = DeterministicFakeAIRecipeAssistant(
        output=AIRecipeDraftOutputV1(
            recipe=ScenarioRecipeV1(
                name="Persistent bullish diagnostic",
                historical_segment_id=segment_id,
                transformations=(
                    {
                        "transformation_id": "trend-regime.v1",
                        "parameters": {
                            "direction": "bullish",
                            "strength": "0.4",
                        },
                    },
                ),
                decision_cadence_minutes=30,
                materialization_seed=17,
            ),
            transformation_proposals=(
                TransformationProposalV1(
                    capability="intraday-order-book-imbalance",
                    description="Model an order-book imbalance regime.",
                    rationale="The registered catalog has no order-book transform.",
                ),
            ),
        )
    )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ai-recipe-audit.db'}",
        future=True,
    )
    first = create_diagnostics_application(
        historical_source=source,
        recipe_assistant=assistant,
        recipe_clock=lambda: datetime(2026, 7, 22, 7, 0, tzinfo=timezone.utc),
    )
    first.start()
    migration = first.initialize_persistence(engine)
    admitted = first.admit_historical_segment(selection)
    assert admitted.segment is not None
    authored = first.author_recipe_with_ai(
        "Create a persistent bullish trend diagnostic.",
        author="scenario-researcher",
    )
    assert authored.draft is not None
    approved = first.approve_recipe_draft(
        authored.draft.draft_id,
        actor="diagnostics-owner",
    )

    restarted = create_diagnostics_application(
        historical_source=source,
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )
    restarted.start()
    restarted.initialize_persistence(engine)
    audit = restarted.get_ai_recipe_audit(authored.attempt.attempt_id)

    assert (
        migration.current_revision
        == "0020_scenario_lab_commands_and_materialization_handles"
    )
    assert audit.attempt.provider == "deterministic-fake"
    assert audit.attempt.model == "deterministic-recipe-fixture.v1"
    assert audit.attempt.prompt_template_version == "ai-recipe-assistant.v1"
    assert audit.attempt.response_hash == authored.attempt.response_hash
    assert audit.attempt.transformation_proposals == (
        TransformationProposalV1(
            capability="intraday-order-book-imbalance",
            description="Model an order-book imbalance regime.",
            rationale="The registered catalog has no order-book transform.",
        ),
    )
    assert audit.validation is not None
    assert audit.validation.is_valid
    assert audit.approval_actor == "diagnostics-owner"
    assert audit.approved_at == datetime(
        2026,
        7,
        22,
        7,
        0,
        tzinfo=timezone.utc,
    )
    assert audit.approved_recipe_hash == approved.content_hash
    assert audit.approved_version_id == approved.version_id
