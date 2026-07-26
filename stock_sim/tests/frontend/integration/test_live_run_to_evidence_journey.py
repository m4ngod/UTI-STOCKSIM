from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeId,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringSelection,
    StrategyRunId,
    StrategyUnderTestId,
)
from app.runtime_gateway import RuntimeGateway
from app.ui.main_window import MainWindow


UTC = timezone.utc
NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


class _DirectExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


class _LiveJourneyQueries:
    def get_run_monitoring_snapshot(self, run_id):
        if run_id != "RUN-LIVE-41":
            return None
        return {
            "run_id": run_id,
            "scenario_name": "SCENARIO-LIVE-41",
            "scenario_set_id": "SET-LIVE-41",
            "strategy_id": "STRATEGY-LIVE-41",
            "reproduction_manifest_id": "RM-LIVE-41",
            "status": "completed",
            "started_at": NOW - timedelta(minutes=3),
            "updated_at": NOW,
            "last_sim_day": 5,
            "last_sim_dt": NOW - timedelta(days=1),
            "completed_nodes": 5,
            "total_nodes": 5,
            "current_node_id": "NODE-COMPLETE",
            "current_node_label": "Evidence ready",
            "requested_execution": {"fee_multiplier": "1.0x"},
            "effective_execution": {"fee_multiplier": "1.6x"},
            "execution_override_reasons": {
                "fee_multiplier": "Recipe override"
            },
            "alerts": [],
            "market_context": ["600519.SH"],
            "account_context": ["MODEL-LIVE-41"],
            "position_context": ["600519.SH · +100"],
            "order_context": ["ORD-LIVE-41 · 600519.SH · filled"],
            "fill_context": ["FILL-LIVE-41 · 600519.SH · 100 @ 1500"],
        }

    def get_evidence_and_findings_snapshot(self, run_id):
        if run_id != "RUN-LIVE-41":
            return None
        return {
            "run_id": run_id,
            "revision": 41,
            "updated_at": NOW.isoformat(),
            "status": "completed",
            "selection": {
                "campaign_id": "FDC-LIVE-41",
                "run_id": run_id,
                "strategy_id": "STRATEGY-LIVE-41",
                "market_scenario_id": "SCENARIO-LIVE-41",
                "approved_recipe_id": "RECIPE-LIVE-41",
                "reproduction_manifest_id": "RM-LIVE-41",
            },
            "candidates": [
                {
                    "candidate_id": "MODEL-LIVE-41",
                    "label": "Live candidate 41",
                    "evidence": [
                        {
                            "id": "E-LIVE-41-BASE",
                            "coverage": "baseline",
                            "dimension": "return",
                            "label": "Live baseline return",
                            "value": "7.4",
                            "unit": "%",
                            "availability": "complete",
                            "interpretation": "Persisted baseline evidence.",
                        },
                        {
                            "id": "E-LIVE-41-FEE",
                            "coverage": "isolated_sensitivity",
                            "dimension": "execution",
                            "label": "Live fee sensitivity",
                            "value": "-1.8",
                            "comparison_evidence_id": "E-LIVE-41-BASE",
                            "comparison_value": "7.4",
                            "unit": "return delta points",
                            "availability": "complete",
                            "interpretation": "Fees reduce the live return.",
                        },
                    ],
                    "comparisons": [
                        {
                            "id": "CMP-LIVE-41-FEE",
                            "label": "Live baseline versus fees",
                            "reference_evidence_id": "E-LIVE-41-BASE",
                            "observed_evidence_id": "E-LIVE-41-FEE",
                            "interpretation": "Fees reduce the result.",
                        }
                    ],
                    "findings": [
                        {
                            "id": "F-LIVE-41",
                            "title": "Live fee sensitivity finding",
                            "disposition": "concern",
                            "comparison_summary": "The live fee case is weaker.",
                            "failure_reason": "Effective fees exceed baseline.",
                            "evidence_ids": [
                                "E-LIVE-41-BASE",
                                "E-LIVE-41-FEE",
                            ],
                            "comparison_ids": ["CMP-LIVE-41-FEE"],
                            "sensitivity_breakpoints": [
                                {
                                    "id": "BP-LIVE-41-FEE",
                                    "assumption_name": "fee_multiplier",
                                    "threshold": "1.6x",
                                    "outcome": "Return falls below the gate.",
                                    "evidence_ids": [
                                        "E-LIVE-41-BASE",
                                        "E-LIVE-41-FEE",
                                    ],
                                }
                            ],
                        }
                    ],
                    "execution_assumptions": [
                        {
                            "name": "fee_multiplier",
                            "requested_value": "1.0x",
                            "effective_value": "1.6x",
                            "override_reason": "Recipe override",
                        }
                    ],
                    "provenance": {
                        "artifact_hashes": ["sha256:live-41"],
                        "source_run_ids": [run_id],
                        "runner_version": "evidence-runner/live-41",
                        "build_version": "uti-stocksim/live-41",
                        "dependencies": [
                            {
                                "name": "reproduction-manifest",
                                "version": "RM-LIVE-41",
                                "artifact_hash": "sha256:rm-live-41",
                            }
                        ],
                    },
                }
            ],
            "read_only_context": {
                "market": ["600519.SH"],
                "account": ["MODEL-LIVE-41"],
                "positions": ["600519.SH · +100"],
                "orders": [
                    {
                        "id": "ORD-LIVE-41",
                        "instrument": "600519.SH",
                        "status": "filled",
                        "diagnostic_note": "Read-only trace.",
                    }
                ],
                "fills": [
                    {
                        "id": "FILL-LIVE-41",
                        "order_id": "ORD-LIVE-41",
                        "instrument": "600519.SH",
                        "quantity": 100,
                        "price": "1500",
                    }
                ],
            },
        }


def _visible_text(root: QObject) -> str:
    return " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("visible")
        and item.property("text")
    )


def test_live_monitored_run_navigates_to_matching_evidence_and_back():
    app = QApplication.instance() or QApplication([])
    gateway = RuntimeGateway()
    gateway._queries = _LiveJourneyQueries()
    bridge = EventBridge(subscribe_backend=False)
    run_context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-LIVE-41"),
            run_id=StrategyRunId("RUN-LIVE-41"),
        )
    )
    evidence_context = EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-LIVE-41"),
            run_id=StrategyRunId("RUN-LIVE-41"),
            strategy_id=StrategyUnderTestId("STRATEGY-LIVE-41"),
            market_scenario_id=MarketScenarioId("SCENARIO-LIVE-41"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-LIVE-41"),
            reproduction_manifest_id=ReproductionManifestId("RM-LIVE-41"),
        )
    )
    run_feature = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    evidence_feature = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    window = MainWindow(
        run_monitoring_feature=run_feature,
        run_monitoring_context=run_context,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=evidence_context,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    evidence_revision = evidence_feature.snapshot(
        evidence_context
    ).revision

    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    evidence_text = _visible_text(root)

    assert root.property("evidenceScreenState") == "ready"
    for expected in (
        "FDC-LIVE-41",
        "RUN-LIVE-41",
        "STRATEGY-LIVE-41",
        "SCENARIO-LIVE-41",
        "RECIPE-LIVE-41",
        "RM-LIVE-41",
        "MODEL-LIVE-41",
        "CMP-LIVE-41-FEE",
        "Live baseline return",
        "Live fee sensitivity",
        "Live fee sensitivity finding",
        "BP-LIVE-41-FEE",
    ):
        assert expected.casefold() in evidence_text.casefold()

    root.setProperty("activeRoute", "run_monitoring")
    app.processEvents()
    run_text = _visible_text(root)
    assert "RUN-LIVE-41" in run_text
    assert "STRATEGY-LIVE-41" in run_text
    assert evidence_feature.snapshot(evidence_context).revision == (
        evidence_revision
    )
    assert run_context.selection is not None
    assert evidence_context.selection is not None
    assert (
        run_context.selection.campaign_id
        == evidence_context.selection.campaign_id
    )
    assert (
        run_context.selection.run_id
        == evidence_context.selection.run_id
    )
    normalized = f"{evidence_text} {run_text}".casefold()
    for forbidden in (
        "buy",
        "sell",
        "submit order",
        "cancel order",
        "replace order",
        "bulk order",
        "launch experiment",
    ):
        assert forbidden not in normalized

    window.close()
    run_feature.close()
    evidence_feature.close()
