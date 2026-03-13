# python
"""订单撮合诊断脚本
执行:  python -m stock_sim.diag_orders  (或 python diag_orders.py)
输出步骤 A-F 对应结果。
"""
import os
os.environ.setdefault("DB_URL", "mysql+pymysql://root:yu20010402@127.0.0.1:3308/test_dataset?charset=utf8mb4")

from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_order_event import OrderEvent
from stock_sim.core.const import OrderStatus
from sqlalchemy import func

ACTIVE_STATUSES = (OrderStatus.NEW, OrderStatus.PARTIAL)

def main(limit_sample: int = 20):
    s = SessionLocal()
    try:
        print("A) 订单状态分布")
        rows = s.query(OrderORM.status, func.count()).group_by(OrderORM.status).all()
        for st, cnt in rows:
            print(f"  {st.name if st else st}: {cnt}")
        print("\nB) 活动订单盘口聚合 (status NEW/PARTIAL)")
        agg = (s.query(OrderORM.symbol, OrderORM.side, OrderORM.price,
                       func.sum(OrderORM.quantity - OrderORM.filled).label("remaining"))
                 .filter(OrderORM.status.in_(ACTIVE_STATUSES))
                 .group_by(OrderORM.symbol, OrderORM.side, OrderORM.price)
                 .order_by(OrderORM.side, OrderORM.price)
                 .all())
        if not agg:
            print("  (无活动订单，可能全部被拒绝或成交/取消)")
        else:
            for r in agg[:100]:
                print(f"  {r.symbol} {r.side.name} px={r.price} rem={int(r.remaining)}")
        print("\nC) 最早 20 条订单样本")
        sample = (s.query(OrderORM)
                    .order_by(OrderORM.ts_created.asc())
                    .limit(limit_sample).all())
        for o in sample:
            print(f"  id={o.id} side={o.side.name} px={o.price} qty={o.quantity} filled={o.filled} st={o.status.name}")
        print("\nD) 活动买卖价格区间")
        buy_minmax = s.query(func.min(OrderORM.price), func.max(OrderORM.price))\
            .filter(OrderORM.side=='BUY', OrderORM.status.in_(ACTIVE_STATUSES)).first()
        sell_minmax = s.query(func.min(OrderORM.price), func.max(OrderORM.price))\
            .filter(OrderORM.side=='SELL', OrderORM.status.in_(ACTIVE_STATUSES)).first()
        print(f"  BUY  min/max: {buy_minmax}")
        print(f"  SELL min/max: {sell_minmax}")
        cross_issue = False
        if buy_minmax and sell_minmax and buy_minmax[1] is not None and sell_minmax[0] is not None:
            if buy_minmax[1] < sell_minmax[0]:
                cross_issue = True
                print("  >>> 提示: 最高买价 < 最低卖价, 没有价格交叉")
        print("\nE) 拒单原因统计")
        rej = (s.query(OrderEvent.detail, func.count())
                 .filter(OrderEvent.event=='REJECT')
                 .group_by(OrderEvent.detail)
                 .order_by(func.count().desc())
                 .all())
        if not rej:
            print("  (无 REJECT 事件)")
        else:
            for d, c in rej:
                print(f"  {d}: {c}")
        print("\nF) ORDER_RATE_LIMIT 触发次数")
        rate_cnt = (s.query(func.count())
                      .filter(OrderEvent.event=='REJECT', OrderEvent.detail=='ORDER_RATE_LIMIT')
                      .scalar())
        print(f"  ORDER_RATE_LIMIT: {rate_cnt}")
        print("\n诊断结论初步:")
        if rows and sum(cnt for _, cnt in rows) == 0:
            print("  无订单记录")
        if agg:
            print("  存在未成交活动订单, 需检查买卖价是否交叉以及撮合逻辑")
        else:
            print("  无活动订单, 大概率大量拒单或全部取消")
        if rej:
            top = rej[0]
            print(f"  首要拒单原因: {top[0]} ({top[1]} 次)")
        if rate_cnt and rate_cnt > 0:
            print("  风控限速大量触发, 建议提升 ORDER_RATE_MAX 或扩大账户池")
        if cross_issue:
            print("  买卖价区间不交叉, 需检查价格生成/归一逻辑")
    finally:
        s.close()

if __name__ == '__main__':
    main()

