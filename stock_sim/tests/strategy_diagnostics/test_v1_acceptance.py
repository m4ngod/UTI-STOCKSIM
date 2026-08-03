from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

from strategy_diagnostics import (
    DiagnosticsApplication,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    V1_REQUIRED_APPLICATION_COMMANDS,
    V1AcceptanceFacts,
    V1AcceptanceGate,
    V1AcceptanceSubject,
    V1CadenceProof,
    V1ProductSurfaceInventory,
)
from strategy_diagnostics.strategy_runs import STRATEGY_RUN_ENGINE_VERSION


def _passing_facts() -> V1AcceptanceFacts:
    return V1AcceptanceFacts(
        historical_segment_admitted=True,
        source_provenance_available=True,
        transformation_families=(
            "execution-stress",
            "liquidity",
            "market-structure",
            "shock-recovery",
            "trend-regime",
            "volatility",
        ),
        manual_recipe_authoring_available=True,
        ai_recipe_authoring_available=True,
        recipe_validated=True,
        recipe_approved=True,
        recipe_frozen=True,
        recipe_versioned=True,
        recipe_hashed=True,
        selected_strategy_versions=(
            (
                QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
            (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
        ),
        selected_guardrail_profiles=(
            (
                QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
                "quentx-balanced-diagnostics.v1",
            ),
            (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
                "live-minute-capital-preservation.v1",
            ),
        ),
        supported_decision_cadences=(30, 60),
        accelerated_simulation_time=True,
        next_node_activation=True,
        campaign_type="formal_diagnostic_campaign",
        campaign_status="completed",
        completed_campaign_layers=(
            "baseline",
            "compound",
            "isolated_sensitivity",
        ),
        isolated_cases_by_family=(
            ("execution-stress", 2),
            ("liquidity", 2),
            ("market-structure", 2),
            ("shock-recovery", 2),
            ("trend-regime", 2),
            ("volatility", 2),
        ),
        isolated_replicas_share_immutable_inputs=True,
        guided_ui_steps=(
            "approve_recipe",
            "build_evidence",
            "configure_guardrails",
            "configure_strategies",
            "inspect_findings",
            "materialize_recipe",
            "reproduce_run",
            "run_formal_campaign",
            "select_segment",
        ),
        provenance_sections=(
            "campaign",
            "evidence",
            "effective_execution",
            "recipe",
            "reproduction",
            "requested_execution",
            "source",
            "strategy",
            "transformation",
        ),
        curve_overlays=("drawdown", "equity", "sensitivity"),
        evidence_status="sealed",
        diagnostic_finding_count=1,
        accepted_manifest_count=28,
        reproduction_status="reproduced_exactly",
        ai_explanation_is_limited_to_sealed_findings=True,
        product_surface_inventory=V1ProductSurfaceInventory(
            V1_REQUIRED_APPLICATION_COMMANDS
        ),
    )


def _subject(facts: V1AcceptanceFacts) -> V1AcceptanceSubject:
    return V1AcceptanceSubject(
        campaign_id="diagnostic-campaign-fixture",
        evidence_package_id="diagnostic-evidence-fixture",
        evidence_artifact_hash="a" * 64,
        measurement_artifact_hash="b" * 64,
        reproduction_manifest_id="reproduction-manifest-fixture",
        reproduction_attempt_id="reproduction-attempt-fixture",
        selected_strategy_versions=facts.selected_strategy_versions,
        selected_guardrail_profiles=facts.selected_guardrail_profiles,
        cadence_proofs=tuple(
            V1CadenceProof(
                decision_cadence_minutes=cadence,
                campaign_id=f"baseline-campaign-{cadence}",
                run_ids=(
                    f"strategy-run-{cadence}-quentx",
                    f"strategy-run-{cadence}-live-minute",
                ),
                run_artifact_hashes=("c" * 64, "d" * 64),
            )
            for cadence in facts.supported_decision_cadences
        ),
        product_surface_inventory_hash=(
            facts.product_surface_inventory.content_hash
        ),
    )


def test_complete_v1_facts_produce_a_canonical_passing_report() -> None:
    facts = _passing_facts()
    report = V1AcceptanceGate().evaluate(facts, _subject(facts))

    assert report.status == "passed"
    assert len(report.checks) == 10
    assert all(check.passed for check in report.checks)
    assert len(report.excluded_capabilities) == 7
    assert all(
        item.status == "absent"
        for item in report.excluded_capabilities
    )
    view = report.to_dict()
    assert view["report_id"].startswith("v1-acceptance-")
    assert len(str(view["content_hash"])) == 64
    assert V1AcceptanceGate().evaluate(
        facts,
        _subject(facts),
    ).to_dict() == view
    assert view["subject"]["campaign_id"] == (
        "diagnostic-campaign-fixture"
    )
    assert view["evaluated_facts"]["accepted_manifest_count"] == 28


def test_report_identity_changes_with_the_accepted_artifact_subject() -> None:
    facts = _passing_facts()
    first = V1AcceptanceGate().evaluate(facts, _subject(facts))
    second_subject = replace(
        _subject(facts),
        campaign_id="diagnostic-campaign-another",
        evidence_package_id="diagnostic-evidence-another",
        evidence_artifact_hash="c" * 64,
    )
    second = V1AcceptanceGate().evaluate(facts, second_subject)
    first_proof, second_proof = _subject(facts).cadence_proofs
    cadence_subject = replace(
        _subject(facts),
        cadence_proofs=(
            replace(
                first_proof,
                campaign_id="baseline-campaign-30-replacement",
                run_ids=(
                    "strategy-run-30-replacement-quentx",
                    "strategy-run-30-replacement-live-minute",
                ),
                run_artifact_hashes=("e" * 64, "f" * 64),
            ),
            second_proof,
        ),
    )
    cadence_report = V1AcceptanceGate().evaluate(
        facts,
        cadence_subject,
    )

    assert first.report_id != second.report_id
    assert first.content_hash != second.content_hash
    assert first.report_id != cadence_report.report_id
    assert first.content_hash != cadence_report.content_hash


def test_missing_transformation_family_fails_only_the_profile_check() -> None:
    facts = _passing_facts()
    incomplete = replace(
        facts,
        transformation_families=tuple(
            family
            for family in facts.transformation_families
            if family != "liquidity"
        ),
    )
    report = V1AcceptanceGate().evaluate(
        incomplete,
        _subject(incomplete),
    )

    failures = [check.check_id for check in report.checks if not check.passed]
    assert report.status == "failed"
    assert failures == ["transformation_profile"]
    assert report.checks[1].missing == ("liquidity",)


def test_present_excluded_capability_fails_the_release_boundary() -> None:
    facts = _passing_facts()
    unsafe = replace(
        facts,
        product_surface_inventory=V1ProductSurfaceInventory(
            V1_REQUIRED_APPLICATION_COMMANDS + ("start_live_trading",)
        ),
    )
    subject = replace(
        _subject(unsafe),
        product_surface_inventory_hash=(
            unsafe.product_surface_inventory.content_hash
        ),
    )
    report = V1AcceptanceGate().evaluate(
        unsafe,
        subject,
    )

    assert report.status == "failed"
    assert report.checks[-1].check_id == "first_version_boundary"
    assert report.checks[-1].passed is False
    by_id = {
        item.capability_id: item
        for item in report.excluded_capabilities
    }
    assert by_id["live_trading"].status == "present"
    assert by_id["live_trading"].evidence == (
        "live_trading is present in the accepted V1 product surface"
    )


def test_incomplete_surface_inventory_cannot_claim_exclusions_absent() -> None:
    facts = _passing_facts()
    incomplete = replace(
        facts,
        product_surface_inventory=V1ProductSurfaceInventory(
            ("admit_historical_segment",)
        ),
    )
    report = V1AcceptanceGate().evaluate(
        incomplete,
        _subject(incomplete),
    )

    assert report.status == "failed"
    assert report.checks[-1].passed is False
    assert all(
        item.status == "unverified"
        for item in report.excluded_capabilities
    )


def test_unclassified_public_command_makes_surface_incomplete() -> None:
    facts = _passing_facts()
    unclassified = replace(
        facts,
        product_surface_inventory=V1ProductSurfaceInventory(
            V1_REQUIRED_APPLICATION_COMMANDS + ("connect_broker",)
        ),
    )

    report = V1AcceptanceGate().evaluate(
        unclassified,
        _subject(unclassified),
    )

    assert unclassified.product_surface_inventory.status == "incomplete"
    assert unclassified.product_surface_inventory.unclassified_commands == (
        "connect_broker",
    )
    assert report.status == "failed"
    assert report.checks[-1].missing == ("unclassified:connect_broker",)
    assert all(
        item.status == "unverified"
        for item in report.excluded_capabilities
    )


def test_wave_2_diagnostic_commands_are_classified_without_becoming_v1_required() -> None:
    wave_2_commands = (
        "approve_diagnostic_task_configuration",
        "cancel_diagnostic_target",
        "create_diagnostic_task",
        "get_diagnostic_task",
        "list_approved_scenario_recipes",
        "list_available_diagnostic_campaign_cases",
        "list_materialized_market_paths",
        "pause_diagnostic_target",
        "read_diagnostic_campaign_case_inventory",
        "resume_diagnostic_target",
        "retry_failed_diagnostic_campaign_node",
        "revise_diagnostic_task_configuration",
        "start_formal_diagnostic_task_campaign",
        "validate_diagnostic_task_configuration",
    )
    inventory = V1ProductSurfaceInventory(
        V1_REQUIRED_APPLICATION_COMMANDS + wave_2_commands
    )

    assert inventory.status == "verified"
    assert inventory.missing_required_commands == ()
    assert inventory.unclassified_commands == ()
    assert inventory.present_excluded_capabilities == ()
    assert not set(wave_2_commands).intersection(
        V1_REQUIRED_APPLICATION_COMMANDS
    )


def test_one_observed_cadence_cannot_claim_30_and_60_minute_support() -> None:
    facts = _passing_facts()
    incomplete = replace(facts, supported_decision_cadences=(30,))

    report = V1AcceptanceGate().evaluate(
        incomplete,
        _subject(incomplete),
    )

    failed = [check for check in report.checks if not check.passed]
    assert [check.check_id for check in failed] == [
        "accelerated_simulation_time"
    ]
    assert failed[0].missing == ("30_and_60_minute_cadences",)


def test_no_observed_order_cannot_claim_next_node_activation() -> None:
    facts = _passing_facts()
    incomplete = replace(facts, next_node_activation=False)

    report = V1AcceptanceGate().evaluate(
        incomplete,
        _subject(incomplete),
    )

    failed = [check for check in report.checks if not check.passed]
    assert [check.check_id for check in failed] == [
        "accelerated_simulation_time"
    ]
    assert failed[0].missing == ("next_node_order_activation",)


def test_next_node_fact_requires_nonempty_well_formed_accepted_orders() -> None:
    def manifest(orders: object) -> Any:
        return SimpleNamespace(
            specification=SimpleNamespace(
                engine_version=STRATEGY_RUN_ENGINE_VERSION
            ),
            accepted_result={"orders": orders},
        )

    empty = cast(tuple[Any, ...], (manifest([]),))
    malformed = cast(
        tuple[Any, ...],
        (manifest([{"decision_time": "not-a-time"}]),),
    )
    mixed_timezones = cast(
        tuple[Any, ...],
        (
            manifest(
                [
                    {
                        "decision_time": "2024-01-02T10:00:00",
                        "activation_time": (
                            "2024-01-02T10:00:30+08:00"
                        ),
                    }
                ]
            ),
        ),
    )
    observed = cast(
        tuple[Any, ...],
        (
            manifest(
                [
                    {
                        "decision_time": "2024-01-02T10:00:00",
                        "activation_time": "2024-01-02T10:00:30",
                    }
                ]
            ),
        ),
    )

    assert (
        DiagnosticsApplication._accepted_orders_use_next_node_activation(
            empty
        )
        is False
    )
    assert (
        DiagnosticsApplication._accepted_orders_use_next_node_activation(
            malformed
        )
        is False
    )
    assert (
        DiagnosticsApplication._accepted_orders_use_next_node_activation(
            mixed_timezones
        )
        is False
    )
    assert (
        DiagnosticsApplication._accepted_orders_use_next_node_activation(
            observed
        )
        is True
    )


def test_ai_explanation_with_execution_authority_is_an_excluded_capability() -> None:
    facts = _passing_facts()
    unsafe = replace(
        facts,
        ai_explanation_is_limited_to_sealed_findings=False,
    )

    report = V1AcceptanceGate().evaluate(
        unsafe,
        _subject(unsafe),
    )

    assert report.status == "failed"
    assert report.checks[-1].check_id == "first_version_boundary"
    assert report.checks[-1].passed is False
    by_id = {
        item.capability_id: item
        for item in report.excluded_capabilities
    }
    assert by_id["ai_executable_logic"].status == "present"
