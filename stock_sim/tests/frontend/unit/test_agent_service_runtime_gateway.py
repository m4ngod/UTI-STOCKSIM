from __future__ import annotations

from app.services.agent_service import AgentService, BatchCreateConfig


class _FakeRuntimeGateway:
    def __init__(self):
        self.bootstrap_calls = []
        self.allocate_if_running_calls = 0

    def bootstrap_agent_account(self, *, account_id, initial_cash, agent_type=None, strategy=None):
        self.bootstrap_calls.append(
            {
                "account_id": account_id,
                "initial_cash": initial_cash,
                "agent_type": agent_type,
                "strategy": strategy,
            }
        )

    def allocate_pending_ipo_distributions_if_running(self):
        self.allocate_if_running_calls += 1


def test_agent_service_bootstrap_uses_runtime_gateway():
    gateway = _FakeRuntimeGateway()
    svc = AgentService(
        retail_agent_factory=lambda **_kwargs: None,
        runtime_gateway=gateway,
    )

    result = svc.batch_create_retail(
        BatchCreateConfig(
            count=1,
            agent_type="Retail",
            strategies=["mean_revert"],
            initial_cash=12345.0,
        )
    )

    assert result["success_ids"] == ["mean_revert001"]
    assert gateway.bootstrap_calls == [
        {
            "account_id": "mean_revert001",
            "initial_cash": 12345.0,
            "agent_type": "Retail",
            "strategy": "mean_revert",
        }
    ]
    assert gateway.allocate_if_running_calls == 1
