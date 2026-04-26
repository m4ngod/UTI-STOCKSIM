from __future__ import annotations

from typing import Any


class ObservationBuilder:
    """Build minimal obs.v1 payloads from runtime-truth services.

    Current scope:
    - single account
    - single or multi-symbol universe
    - in-process runtime state only
    """

    contract_version = "obs.v1"

    def __init__(self, order_service):
        self.order_service = order_service

    def build(self, *, account_id: str, symbol: str, run_id: str | None = None,
              episode_id: str | None = None, step_index: int | None = None) -> dict[str, Any]:
        return self.build_many(
            account_id=account_id,
            symbols=[symbol],
            run_id=run_id,
            episode_id=episode_id,
            step_index=step_index,
        )

    def build_many(self, *, account_id: str, symbols: list[str], run_id: str | None = None,
                   episode_id: str | None = None, step_index: int | None = None) -> dict[str, Any]:
        symbols = [str(sym) for sym in symbols if str(sym)]
        if not symbols:
            raise ValueError("NO_SYMBOLS")
        primary_symbol = symbols[0]
        acc = self.order_service.accounts.get_or_create(account_id)
        market_by_symbol: dict[str, dict[str, Any]] = {}
        positions = []
        total_position_value = 0.0
        gross_exposure = 0.0
        net_exposure = 0.0
        primary_market: dict[str, Any] | None = None

        for symbol in symbols:
            pos = self.order_service.accounts.get_position(acc, symbol)
            market = self._market_snapshot(symbol, pos)
            market_by_symbol[symbol] = market
            if primary_market is None:
                primary_market = market
            qty = int(getattr(pos, "quantity", 0) or 0)
            last_price = float(market.get("last_price") or 0.0)
            value = qty * last_price
            total_position_value += value
            gross_exposure += abs(value)
            net_exposure += value
            positions.append({
                "symbol": symbol,
                "quantity": qty,
                "frozen_qty": int(getattr(pos, "frozen_qty", 0) or 0),
                "avg_price": float(getattr(pos, "avg_price", 0.0) or 0.0),
                "borrowed_qty": int(getattr(pos, "borrowed_qty", 0) or 0),
            })

        equity = float(getattr(acc, "cash", 0.0) or 0.0) + total_position_value
        market_payload = dict(primary_market or {})
        market_payload["symbol"] = primary_symbol
        market_payload["symbols"] = symbols
        market_payload["snapshots"] = market_by_symbol
        market_payload["bars"] = {sym: {} for sym in symbols}
        market_payload["order_books"] = {
            sym: {
                "bids": market_by_symbol[sym].get("bid_levels", []),
                "asks": market_by_symbol[sym].get("ask_levels", []),
            }
            for sym in symbols
        }

        return {
            "contract_version": self.contract_version,
            "market": market_payload,
            "account": {
                "account_id": account_id,
                "cash": float(getattr(acc, "cash", 0.0) or 0.0),
                "frozen_cash": float(getattr(acc, "frozen_cash", 0.0) or 0.0),
                "frozen_fee": float(getattr(acc, "frozen_fee", 0.0) or 0.0),
                "equity": float(equity),
                "gross_exposure": float(gross_exposure),
                "net_exposure": float(net_exposure),
                "positions": positions,
            },
            "context": {
                "sim_day": getattr(acc, "sim_day", None),
                "sim_dt": getattr(acc, "sim_dt", None),
                "run_id": run_id,
                "episode_id": episode_id,
                "step_index": step_index,
                "symbol_universe": symbols,
                "agent_id": account_id,
            },
            "features": {
                "bars_window": {"timeframe": None, "rows": []},
                "indicators": {},
                "feature_vector": [],
            },
        }

    def _market_snapshot(self, symbol: str, pos: Any) -> dict[str, Any]:
        eng = self.order_service._get_engine(symbol)
        book = eng.get_book(symbol)
        snap = getattr(book, "snapshot", None)

        bid_levels = []
        ask_levels = []
        last_price = None
        volume = 0
        turnover = 0.0
        market_phase = getattr(getattr(book, "phase", None), "name", None) or "UNKNOWN"

        if snap is not None:
            bid_levels = [[float(px), int(qty)] for px, qty in (getattr(snap, "bid_levels", None) or [])]
            ask_levels = [[float(px), int(qty)] for px, qty in (getattr(snap, "ask_levels", None) or [])]
            last_price = getattr(snap, "last_price", None) or getattr(snap, "last", None)
            volume = int(getattr(snap, "volume", 0) or getattr(snap, "vol", 0) or 0)
            turnover = float(getattr(snap, "turnover", 0.0) or 0.0)

        if not last_price:
            if ask_levels:
                last_price = ask_levels[0][0]
            elif bid_levels:
                last_price = bid_levels[0][0]
            else:
                instrument = getattr(eng, "instrument", None)
                last_price = (
                    float(getattr(pos, "avg_price", 0.0) or 0.0)
                    or float(getattr(instrument, "initial_price", 0.0) or 0.0)
                )

        best_bid = bid_levels[0][0] if bid_levels else None
        best_ask = ask_levels[0][0] if ask_levels else None
        spread = None
        if best_bid is not None and best_ask is not None:
            spread = float(best_ask - best_bid)

        return {
            "symbol": symbol,
            "last_price": float(last_price or 0.0),
            "volume": volume,
            "turnover": turnover,
            "bid_levels": bid_levels,
            "ask_levels": ask_levels,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "market_phase": market_phase,
        }


__all__ = ["ObservationBuilder"]
