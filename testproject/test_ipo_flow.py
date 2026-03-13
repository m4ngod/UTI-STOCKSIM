"""
测试 IPO 集合竞价 + 简单连续撮合
"""
from stock_sim.account.manager import AccountManager
from stock_sim.core.const import Phase, OrderType
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.order import Order, OrderSide
from stock_sim.core.call_auction import CallAuction   # 若 MatchingEngine 未外露
# ----------------------------------------------------------------------
SYMBOL = "NEWSTK"

# ① 初始化账户
acc_mgr = AccountManager()
acc_mgr.create_account("A1", 1_000_000)
acc_mgr.create_account("A2", 1_000_000)
acc_mgr.create_account("IPO_POOL", 0)          # 承销账户（卖方）

# 给 IPO_POOL 注入 100 万股库存，便于卖出
pos = acc_mgr._get_or_create_position("IPO_POOL", SYMBOL)    # 私有接口 OK 于测试 [T1](1)
pos.quantity = 1_000_000
acc_mgr.db.commit()

# ② 创建撮合引擎并进入 PREOPEN
engine = MatchingEngine(SYMBOL)
engine.phase = Phase.PREOPEN                       # 处于集合竞价阶段

# ③ 提交买／卖订单（全部限价单）
engine.submit_order(Order(SYMBOL, OrderSide.BUY,  10.50, 30_000, account_id="A1"))
engine.submit_order(Order(SYMBOL, OrderSide.BUY,  10.30, 50_000, account_id="A2"))
engine.submit_order(Order(SYMBOL, OrderSide.SELL,  10.00, 80_000, account_id="IPO_POOL"))

# ④ 手动执行集合竞价并结算至账户
auction: CallAuction = engine._auction             # 直接拿到内部 CallAuction
trades = auction.run()                             # [(buy, sell, qty, price), ...]

for buy_o, sell_o, qty, px in trades:
    acc_mgr.on_trade(buy_o.account_id, SYMBOL, "BUY",  px, qty)   # 更新账户 [T0](2)
    acc_mgr.on_trade(sell_o.account_id, SYMBOL, "SELL", px, qty)

engine.phase = Phase.CONTINUOUS                    # 开盘，进入连续竞价

print("=== IPO 集合竞价完成 ===")
for t in trades:
    print(f"清算价 {t[3]:.2f}, 数量 {t[2]} -- 买:{t[0].account_id} 卖:{t[1].account_id}")

# ⑤ 连续竞价：A1 卖、A2 买（以同价成交）
engine.submit_order(Order(SYMBOL, OrderSide.SELL, 10.60, 1_000, account_id="A1"))
engine.submit_order(Order(SYMBOL, OrderSide.BUY,  10.60, 1_000, account_id="A2"))

# ⑥ 打印结果
for aid in ("A1", "A2", "IPO_POOL"):
    acc = acc_mgr.get_account(aid)
    qty = acc.positions[0].quantity if acc.positions else 0
    print(f"{aid} 现金:{acc.cash:,.2f}  持仓:{qty}")
