# python
# file: core/const.py
from __future__ import annotations
from enum import Enum, auto

class Phase(Enum):
    PREOPEN = auto()
    CALL_AUCTION = auto()
    CONTINUOUS = auto()
    CLOSED = auto()

class OrderType(Enum):
    LIMIT = auto()
    MARKET = auto()

class OrderSide(Enum):
    BUY = auto()
    SELL = auto()

class OrderStatus(Enum):
    NEW = auto()
    PARTIAL = auto()
    FILLED = auto()
    CANCELED = auto()
    REJECTED = auto()

class TimeInForce(Enum):
    GFD = auto()   # 当日有效 (模拟：到收盘前)
    IOC = auto()
    FOK = auto()
    GTC = auto()   # 可扩展（当前等同 GFD，可在清算日跨日保留）
    DAY = auto()  # 当日有效 (实际：到收盘前)

class EventType(str, Enum):
    ORDER_ACCEPTED = "OrderAccepted"
    ORDER_REJECTED = "OrderRejected"
    ORDER_FILLED = "OrderFilled"
    ORDER_PARTIALLY_FILLED = "OrderPartiallyFilled"
    ORDER_CANCELED = "OrderCanceled"
    TRADE = "TradeEvent"
    ACCOUNT_UPDATED = "AccountUpdated"
    SNAPSHOT_UPDATED = "SnapshotUpdated"
    BAR_UPDATED = "BarUpdated"  # 新增: K线/Bar 更新事件
    STRATEGY_CHANGED = "StrategyChanged"  # 新增: 策略切换事件
    IPO_OPENED = "IPOOpened"  # 新增: IPO 集合竞价完成事件
    SIM_DAY = "SimDay"  # 新增: 模拟时钟触发的“新交易日”事件 (压缩 4h->30s)
    AGENT_META_UPDATE = "AgentMetaUpdate"  # 新增: 智能体元数据需持久化
    # ---- 以下为 platform-hardening 扩展事件 ----
    SNAPSHOT_POLICY_CHANGED = "SnapshotPolicyChanged"  # 自适应节流参数调整
    PERSISTENCE_DEGRADED = "PersistenceDegraded"        # 事件持久化降级/大量失败
    RECOVERY_FAILED = "RecoveryFailed"                  # 恢复失败进入只读
    RECOVERY_RESUMED = "RecoveryResumed"                # 恢复成功后正常撮合恢复
    RISK_RESET = "RiskReset"                            # 日切或重置风险窗口
    BORROW_FEE_ACCRUED = "BorrowFeeAccrued"            # 借券费用计提
    LIQUIDATION_TRIGGERED = "LiquidationTriggered"      # 维持保证金不足触发强平
    CONFIG_CHANGED = "ConfigChanged"                    # 热更新配置生效通知
