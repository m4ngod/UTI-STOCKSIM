from __future__ import annotations

from app.services.leaderboard_service import LeaderboardService


class _FakeRuntimeGateway:
    def list_leaderboard_snapshots(self):
        return [
            {
                "agent_id": "retail001",
                "equity": 110000.0,
                "initial_cash": 100000.0,
                "gross_exposure": 20000.0,
                "long_count": 2,
                "short_count": 0,
            },
            {
                "agent_id": "retail002",
                "equity": 95000.0,
                "initial_cash": 100000.0,
                "gross_exposure": 10000.0,
                "long_count": 1,
                "short_count": 0,
            },
        ]

    def get_leaderboard_history(self, agent_id: str, *, window: str, points: int = 50):
        if agent_id != "retail001":
            return None
        return {
            "agent_id": agent_id,
            "equity_curve": [100000.0, 103000.0, 110000.0],
            "drawdown_curve": [0.0, -0.01, 0.0],
            "source": "runtime-account-equity-snapshots",
            "authoritative": True,
            "active_run_id": "RUN-LB-001",
        }


def test_leaderboard_service_builds_runtime_rows_from_gateway():
    svc = LeaderboardService(use_runtime=True, runtime_gateway=_FakeRuntimeGateway())

    rows = svc.get_leaderboard("1d", limit=10, force_refresh=True)

    assert [row.agent_id for row in rows] == ["retail001", "retail002"]
    assert rows[0].return_pct > rows[1].return_pct
    assert rows[0].equity == 110000.0


def test_leaderboard_service_prefers_runtime_curves_from_gateway():
    svc = LeaderboardService(use_runtime=True, runtime_gateway=_FakeRuntimeGateway())
    svc.get_leaderboard("1d", limit=10, force_refresh=True)

    curves = svc.get_agent_curves("retail001", "1d", points=50)

    assert curves is not None
    assert curves["equity_curve"] == [100000.0, 103000.0, 110000.0]
    assert curves["drawdown_curve"] == [0.0, -0.01, 0.0]
    assert curves["source"] == "runtime-account-equity-snapshots"
    assert curves["authoritative"] is True
