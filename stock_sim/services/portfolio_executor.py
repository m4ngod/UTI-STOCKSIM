from __future__ import annotations
"""PortfolioExecutor
将目标权重映射为实际订单:
流程:
 1. 输入: target_weights {symbol: target_weight}
 2. 读取当前账户现金/持仓与最新价格 -> 计算当前权重 current_w
 3. 差值 delta_w -> 目标调整价值 delta_value = delta_w * equity
 4. 转换为数量: qty = floor( delta_value / (price * contract_multiplier) / lot_size ) * lot_size
 5. 忽略 |qty| == 0 或 price<=0
 6. 方向: qty>0 BUY, qty<0 SELL
 7. 生成 Order 交给 order_service.place_order (风控仍在 order_service 内部执行)

注意: 不做高级库存/借券检查; 需要时扩展 risk_engine 钩子。
"""
from typing import Dict, List
from dataclasses import dataclass
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce
from FE.engine_registry import engine_registry
import os
TRACE_REBAL = os.environ.get('DEBUG_TRACE_REBAL') == '1'

@dataclass
class ExecResult:
    orders: int
    gross_notional: float
    skipped: int
    details: List[dict]

class PortfolioExecutor:
    def __init__(self, order_service, account_fetcher, instrument_info_provider=None):
        self.order_service = order_service
        self._account_fetcher = account_fetcher  # callable(account_id)->dict{cash, positions:[{symbol,quantity,avg_price}]}
        self._info = instrument_info_provider or (lambda s: {})

    def rebalance(self, account_id: str, target_weights: Dict[str, float], min_notional: float = 0.0) -> ExecResult:
        if TRACE_REBAL:
            print(f"[TRACE Rebalance.begin] acct={account_id} targets={len(target_weights)} min_notional={min_notional}")
        acct = self._account_fetcher(account_id) or {}
        cash = float(acct.get('cash', 0.0))
        pos_list = acct.get('positions', []) or []
        if TRACE_REBAL:
            try:
                print(f"[TRACE Rebalance.account] cash={cash} positions={[ (p.get('symbol'), p.get('quantity')) for p in pos_list ]}")
            except Exception:
                pass
        pos_map = {p.get('symbol'): p for p in pos_list}
        # 收集价格
        prices = {}
        for sym in target_weights.keys():
            eng = engine_registry.get(sym)
            px = None
            if eng:
                snap = getattr(eng, 'snapshot', None)
                px = getattr(snap, 'last_price', None) or getattr(snap, 'close_price', None)
            prices[sym] = px or 0.0
            if TRACE_REBAL:
                print(f"[TRACE Rebalance.price] {sym} px={prices[sym]}")
        # 计算市值 equity
        mv = 0.0
        for sym, p in pos_map.items():
            px = prices.get(sym)
            if not px:
                eng = engine_registry.get(sym)
                if eng:
                    snap = eng.snapshot; px = snap.last_price or snap.close_price or 0.0
            mv += p.get('quantity', 0) * (px or 0.0)
        equity = mv + cash
        if TRACE_REBAL:
            print(f"[TRACE Rebalance.equity] mv={mv} cash={cash} equity={equity}")
        if equity <= 0:
            if TRACE_REBAL:
                print("[TRACE Rebalance.abort] equity<=0")
            return ExecResult(0,0.0, len(target_weights), [])
        details=[]; orders=0; gross=0.0; skipped=0
        for sym, tw in target_weights.items():
            px = prices.get(sym, 0.0)
            if px <= 0:
                skipped +=1
                if TRACE_REBAL:
                    print(f"[TRACE Rebalance.skip.no_price] {sym}")
                continue
            pos = pos_map.get(sym, {'quantity':0})
            cur_qty = pos.get('quantity',0)
            cur_val = cur_qty * px
            cur_w = cur_val / equity if equity>0 else 0.0
            dw = tw - cur_w
            if abs(dw) < 1e-4:
                skipped +=1
                if TRACE_REBAL:
                    print(f"[TRACE Rebalance.skip.small_dw] {sym} dw={dw}")
                continue
            target_val = tw * equity
            delta_val = target_val - cur_val
            side = OrderSide.BUY if delta_val>0 else OrderSide.SELL
            lot = 1
            info = self._info(sym) or {}
            lot = int(info.get('lot_size') or info.get('lot') or 1)
            mult = float(info.get('contract_multiplier', 1.0))
            raw_qty = abs(delta_val) / max(1e-9, px*mult)
            qty = int(raw_qty // lot * lot)
            if qty <=0:
                skipped +=1
                if TRACE_REBAL:
                    print(f"[TRACE Rebalance.skip.qty0] {sym} raw_qty={raw_qty}")
                continue
            notional = qty * px * mult
            if notional < min_notional:
                skipped +=1
                if TRACE_REBAL:
                    print(f"[TRACE Rebalance.skip.min_notional] {sym} notional={notional}")
                continue
            if TRACE_REBAL:
                print(f"[TRACE Rebalance.order] sym={sym} side={side.name} qty={qty} px={px} notional={notional} cur_w={cur_w:.6f} target_w={tw} delta_val={delta_val}")
            order = Order(symbol=sym, side=side, price=px, quantity=qty, account_id=account_id,
                          order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            try:
                self.order_service.place_order(order)
                orders +=1; gross += notional
                details.append({'symbol':sym,'side':side.name,'qty':qty,'notional':notional,'target_w':tw,'cur_w':cur_w})
                if TRACE_REBAL:
                    print(f"[TRACE Rebalance.placed] sym={sym} oid={order.order_id} status={order.status.name}")
            except Exception as e:
                skipped +=1
                if TRACE_REBAL:
                    print(f"[TRACE Rebalance.error] sym={sym} err={e}")
        if TRACE_REBAL:
            print(f"[TRACE Rebalance.result] orders={orders} skipped={skipped} gross={gross}")
        return ExecResult(orders=orders, gross_notional=gross, skipped=skipped, details=details)
