# python
# 重写: 移除对缺失 base_agent 的依赖，内联简单 BaseAgent / Observation。
from __future__ import annotations
import random
from dataclasses import dataclass, field
from collections import deque
from typing import Deque, List, Dict
from datetime import datetime

from stock_sim.core.const import OrderSide, OrderType, TimeInForce, EventType
from stock_sim.core.order import Order
from stock_sim.infra.event_bus import event_bus
from stock_sim.settings import settings


"""DEPRECATED: retail_trader 模块已弃用。请使用 MultiStrategyRetail。
保留占位以兼容旧引用，实例化时将抛出 RuntimeError。
"""

class RetailTrader:
    def __init__(self, *_, **__):  # type: ignore
        raise RuntimeError("RetailTrader 已弃用，请改用 MultiStrategyRetail")

class RetailTraderPool:
    def __init__(self, *_, **__):  # type: ignore
        raise RuntimeError("RetailTraderPool 已弃用，请批量创建 MultiStrategyRetail 代理")
