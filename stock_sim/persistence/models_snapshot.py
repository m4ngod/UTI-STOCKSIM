# python
from datetime import datetime
from .models_imports import Base, Column, Integer, String, Float, DateTime, Index, SimTimeMixin

class Snapshot1s(Base, SimTimeMixin):
    __tablename__ = "snapshots_1s"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(32), index=True)
    # 原始核心字段
    last_price = Column(Float)
    bid1 = Column(Float)
    ask1 = Column(Float)
    bid1_qty = Column(Integer)
    ask1_qty = Column(Integer)
    volume = Column(Integer)          # 累计成交量（股 / 手：取决于撮合定义）
    turnover = Column(Float)          # 累计成交额
    # 新增派生指标字段
    prev_close = Column(Float)        # 昨收 / IPO 初始价
    change_pct = Column(Float)        # (last - prev_close)/prev_close*100
    change_speed = Column(Float)      # 每秒涨速（last - prev_last）/ prev_last *100
    volume_delta = Column(Integer)    # 相对上一秒新增量
    turnover_delta = Column(Float)    # 相对上一秒新增额
    turnover_rate = Column(Float)     # 累计换手率（基于 free_float_shares）
    spread = Column(Float)            # ask1 - bid1
    imbalance = Column(Float)         # (bid1_qty-ask1_qty)/(sum)
    trade_count_sec = Column(Integer) # 当前秒内成交笔数
    vwap = Column(Float)              # 成交均价 (turnover/volume)

Index("idx_snapshots_symbol_ts", Snapshot1s.symbol, Snapshot1s.ts)