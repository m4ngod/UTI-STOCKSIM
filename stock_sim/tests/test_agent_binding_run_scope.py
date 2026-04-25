import json

from app.runtime_gateway import RuntimeGateway
from stock_sim.persistence import models_init
from stock_sim.persistence.models_agent_binding import AgentBinding
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.runtime_query_service import RuntimeQueryService
from stock_sim.services.runtime_command_service import RuntimeCommandService
from stock_sim.services.sim_clock import ensure_sim_clock_started


def test_runtime_query_service_returns_only_active_run_agent_bindings():
    models_init.init_models()
    clk = ensure_sim_clock_started()
    if hasattr(clk, "configure"):
        clk.configure(run_id="RUN-AGENT-SCOPE-A")

    sess = SessionLocal()
    try:
        sess.add(
            AgentBinding(
                agent_name="mean_revert001",
                agent_type="RETAIL",
                account_id="mean_revert001",
                run_id="RUN-AGENT-SCOPE-A",
                meta=json.dumps({"strategy": "mean_revert", "run_id": "RUN-AGENT-SCOPE-A"}),
            )
        )
        sess.add(
            AgentBinding(
                agent_name="momentum_chase001",
                agent_type="RETAIL",
                account_id="momentum_chase001",
                run_id="RUN-AGENT-SCOPE-B",
                meta=json.dumps({"strategy": "momentum_chase", "run_id": "RUN-AGENT-SCOPE-B"}),
            )
        )
        sess.commit()
    finally:
        sess.close()

    rows = RuntimeQueryService().list_agent_bindings()

    assert [row["agent_name"] for row in rows] == ["mean_revert001"]
    assert rows[0]["run_id"] == "RUN-AGENT-SCOPE-A"
    assert rows[0]["meta"]["strategy"] == "mean_revert"

    all_rows = RuntimeQueryService().list_agent_bindings(include_all_runs=True)
    assert {"mean_revert001", "momentum_chase001"} <= {row["agent_name"] for row in all_rows}

    if hasattr(clk, "configure"):
        clk.configure(run_id="")


def test_runtime_gateway_bootstrap_agent_binding_stamps_current_desktop_run():
    models_init.init_models()
    gateway = RuntimeGateway()
    run_id = gateway.ensure_desktop_run()

    gateway.bootstrap_agent_account(
        account_id="liquidity_noise001",
        initial_cash=100000.0,
        agent_type="Retail",
        strategy="liquidity_noise",
    )

    rows = RuntimeQueryService().list_agent_bindings()

    assert run_id
    assert [row["agent_name"] for row in rows] == ["liquidity_noise001"]
    assert rows[0]["run_id"] == run_id
    assert rows[0]["meta"]["run_id"] == run_id
    assert rows[0]["meta"]["strategy"] == "liquidity_noise"

    clk = ensure_sim_clock_started()
    if hasattr(clk, "configure"):
        clk.configure(run_id="")


def test_runtime_command_updates_binding_run_id_from_meta_update():
    models_init.init_models()
    sess = SessionLocal()
    try:
        row = sess.get(AgentBinding, "claimable001")
        if row is not None:
            sess.delete(row)
            sess.commit()
        sess.add(
            AgentBinding(
                agent_name="claimable001",
                agent_type="RETAIL",
                account_id="claimable001",
                run_id="RUN-OLD",
                meta=json.dumps({"strategy": "mean_revert", "run_id": "RUN-OLD"}),
            )
        )
        sess.commit()
    finally:
        sess.close()

    RuntimeCommandService().update_agent_binding_meta("claimable001", run_id="RUN-CURRENT", status="RUNNING")

    sess = SessionLocal()
    try:
        row = sess.get(AgentBinding, "claimable001")
        assert row is not None
        assert row.run_id == "RUN-CURRENT"
        assert json.loads(row.meta)["run_id"] == "RUN-CURRENT"
        assert json.loads(row.meta)["status"] == "RUNNING"
        sess.delete(row)
        sess.commit()
    finally:
        sess.close()
