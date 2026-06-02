from __future__ import annotations

from typing import Any

from .contracts import REWARD_CONTRACT_VERSION


class RewardBuilder:
    """Build rew.v1 rewards from account deltas and execution costs."""

    def __init__(
        self,
        *,
        drawdown_weight: float = 0.25,
        turnover_weight: float = 0.02,
        open_order_weight: float = 0.001,
        fee_weight: float = 1.0,
        inventory_weight: float = 0.001,
        reward_profile: str = "relative_equity_risk_adjusted_v1",
    ):
        self.drawdown_weight = float(drawdown_weight)
        self.turnover_weight = float(turnover_weight)
        self.open_order_weight = float(open_order_weight)
        self.fee_weight = float(fee_weight)
        self.inventory_weight = float(inventory_weight)
        self.reward_profile = reward_profile

    def build(
        self,
        *,
        previous_account: dict[str, Any] | None,
        current_account: dict[str, Any] | None,
        action: dict[str, Any] | None = None,
        execution_result: dict[str, Any] | None = None,
        benchmark_return: float = 0.0,
        peak_equity: float | None = None,
    ) -> dict[str, Any]:
        prev_equity = _equity(previous_account)
        curr_equity = _equity(current_account)
        base = prev_equity if prev_equity > 0 else curr_equity
        equity_return = 0.0 if base <= 0 else (curr_equity - prev_equity) / base
        relative_alpha = equity_return - float(benchmark_return or 0.0)
        fee_total = _fee_total(execution_result)
        execution_metrics = execution_notional_metrics(execution_result)
        filled_turnover = execution_metrics["filled_notional"] / max(base, 1.0)
        open_order_pressure = execution_metrics["open_order_notional"] / max(base, 1.0)
        submitted_notional_ratio = execution_metrics["submitted_notional"] / max(base, 1.0)
        inventory = _gross_exposure(current_account) / max(curr_equity, 1.0)
        peak = max(float(peak_equity or 0.0), prev_equity, curr_equity)
        drawdown = 0.0 if peak <= 0 else max(0.0, (peak - curr_equity) / peak)

        components = {
            "delta_equity": equity_return,
            "relative_alpha": relative_alpha,
            "realized_pnl": float((current_account or {}).get("realized_pnl") or 0.0),
            "unrealized_pnl": float((current_account or {}).get("unrealized_pnl") or 0.0),
            "fee_penalty": -self.fee_weight * fee_total / max(base, 1.0),
            "drawdown_penalty": -self.drawdown_weight * drawdown,
            "turnover_penalty": -self.turnover_weight * filled_turnover,
            "open_order_pressure_penalty": -self.open_order_weight * open_order_pressure,
            "inventory_penalty": -self.inventory_weight * inventory,
            "filled_turnover": filled_turnover,
            "open_order_pressure": open_order_pressure,
            "submitted_notional_ratio": submitted_notional_ratio,
        }
        step_reward = (
            components["delta_equity"]
            + components["relative_alpha"]
            + components["fee_penalty"]
            + components["drawdown_penalty"]
            + components["turnover_penalty"]
            + components["open_order_pressure_penalty"]
            + components["inventory_penalty"]
        )
        return {
            "reward_version": REWARD_CONTRACT_VERSION,
            "step_reward": float(step_reward),
            "components": components,
            "meta": {
                "reward_profile": self.reward_profile,
                "action_type": (action or {}).get("action_type"),
                "execution_metrics": execution_metrics,
            },
        }


def _equity(account: dict[str, Any] | None) -> float:
    if not account:
        return 0.0
    if account.get("equity") is not None:
        return float(account.get("equity") or 0.0)
    return float(account.get("cash") or 0.0)


def _gross_exposure(account: dict[str, Any] | None) -> float:
    if not account:
        return 0.0
    if account.get("gross_exposure") is not None:
        return float(account.get("gross_exposure") or 0.0)
    total = 0.0
    for pos in account.get("positions") or []:
        qty = float(pos.get("quantity") or 0.0)
        price = float(pos.get("last_price") or pos.get("avg_price") or 0.0)
        total += abs(qty * price)
    return total


def _fee_total(execution_result: dict[str, Any] | None) -> float:
    if not execution_result:
        return 0.0
    total = float(execution_result.get("fee_total") or 0.0)
    for trade in execution_result.get("trades") or []:
        total += float(trade.get("fee") or trade.get("fees") or 0.0)
    return total


def execution_notional_metrics(execution_result: dict[str, Any] | None) -> dict[str, float]:
    if not execution_result:
        return {
            "submitted_notional": 0.0,
            "filled_notional": 0.0,
            "open_order_notional": 0.0,
        }
    submitted_notional = 0.0
    filled_notional = float(execution_result.get("filled_notional") or execution_result.get("notional") or 0.0)
    for trade in execution_result.get("trades") or []:
        qty = float(trade.get("quantity") or trade.get("qty") or 0.0)
        price = float(trade.get("price") or 0.0)
        filled_notional += abs(qty * price)
    has_top_level_fill = filled_notional > 0
    for order in execution_result.get("orders") or []:
        qty = float(order.get("qty") or order.get("quantity") or 0.0)
        price = float(order.get("price") or 0.0)
        submitted = abs(qty * price)
        submitted_notional += submitted
        result = order.get("result") if isinstance(order.get("result"), dict) else {}
        filled_qty = float(result.get("filled") or order.get("filled") or 0.0)
        order_filled = abs(filled_qty * price)
        if order_filled <= 0:
            for trade in result.get("trades") or []:
                t_qty = float(trade.get("quantity") or trade.get("qty") or 0.0)
                t_price = float(trade.get("price") or price or 0.0)
                order_filled += abs(t_qty * t_price)
        if not has_top_level_fill:
            filled_notional += order_filled
    open_order_notional = max(0.0, submitted_notional - filled_notional)
    return {
        "submitted_notional": submitted_notional,
        "filled_notional": filled_notional,
        "open_order_notional": open_order_notional,
    }


__all__ = ["RewardBuilder", "execution_notional_metrics"]
