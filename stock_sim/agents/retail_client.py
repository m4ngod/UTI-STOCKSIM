"""retail_client 已移除: 使用 MultiStrategyPage.add_pool_agent 创建多策略散户池。
保留存根类以避免旧代码 import 崩溃。"""
from __future__ import annotations
import time, random
class RetailClient:  # type: ignore
    def __init__(self, *_, **__):  # noqa: D401
        raise RuntimeError("RetailClient 已移除，请改用 MultiStrategyPage.add_pool_agent(...) 创建池散户。")
from stock_sim.infra.event_bus import event_bus  # 新增事件总线
    # 兼容性占位
    def start(self): raise RuntimeError("RetailClient 已移除")
    def stop(self): raise RuntimeError("RetailClient 已移除")
    def tick(self): raise RuntimeError("RetailClient 已移除")
    def status_dict(self): return {"removed": True}
    strategy_registry = None
    IRetailStrategy = object  # type: ignore
try:
    from stock_sim.services.universe_provider import UniverseProvider
except Exception:
    UniverseProvider = None  # type: ignore

@dataclass
class RetailClientStats:
    orders: int = 0
    last_side: Optional[str] = None
    last_ts: float = 0.0

class RetailClient:
    """散户占位类 (静态/可扩展策略)。
    允许延迟绑定 symbol: 创建时 symbol 可以为 None; 启动后按 multi_symbol 策略自选。
    """
    def __init__(self,
                 name: str,
                 symbol: str | None,
                 account_id: str,
                 order_service_provider: Callable[[str | None], object],  # 修改: 传入 symbol
                 snapshot_provider: Callable[[str | None], object],      # 修改: 传入 symbol
                 lot_size: int = 10,
                 interval: float = 2.0,
                 strategy: str | None = None,
                 universe_provider: UniverseProvider | None = None,
                 multi_symbol: bool = True):  # 默认开启多标模式
        self.name = name
        self.symbol: str | None = symbol
        self.account_id = account_id
        self._osp = order_service_provider
        self._ssp = snapshot_provider
        self.interval = max(0.5, float(interval))
        self.lot_size = max(1, lot_size)
        self.enabled = False
        self._last_run = 0.0
        self.stats = RetailClientStats()
        self._price_windows: Dict[str, List[float]] = {}
        # 原单窗口保持引用以兼容
        self._price_window: list[float] = []
        # 策略相关
        self.strategy_name: str = strategy or 'momentum_chase'
        self._strategy: IRetailStrategy | None = None
        self.universe_provider = universe_provider
        self.multi_symbol = multi_symbol
        self._init_strategy()
        # 调试新增
        self.debug: bool = False
        self.debug_counters: Dict[str, int] = {}

    def _init_strategy(self):
        if strategy_registry is None:
            return
        try:
            self._strategy = strategy_registry.create(self.strategy_name)
        except Exception:
            # 回退默认
            try:
                self._strategy = strategy_registry.create('momentum_chase')
                self.strategy_name = 'momentum_chase'
            except Exception:
                self._strategy = None
import time, random
    def set_strategy(self, name: str) -> bool:
        """热切换策略 (保持窗口数据)。"""
        if strategy_registry is None:
            return False
        if name == self.strategy_name:
            return True
        try:
            self._strategy = strategy_registry.create(name)
            self.strategy_name = name
            try:
                event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
            except Exception:
                pass
            return True
        except Exception:
            return False
from stock_sim.infra.event_bus import event_bus  # 新增事件总线
    def set_interval(self, sec: float):
        self.interval = max(0.5, float(sec))
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    # ---- strategy placeholder ----
    def decide_action(self):
        """委托给当前策略 (兼容旧逻辑)。"""
        if self._strategy:
            try:
                return self._strategy.decide(self._price_window, self._price_window[-1] if self._price_window else None, self.lot_size)
            except Exception:
                pass
        # ===== 下面为旧 fallback 逻辑 =====
        if len(self._price_window) < 3:
            return None
        p1, p2, p3 = self._price_window[-3:]
        if p1 < p2 < p3:  # 上升
            return OrderSide.BUY, self.lot_size
        if p1 > p2 > p3:  # 下降
            return OrderSide.SELL, self.lot_size
        # 低概率随机噪声单（演示用，可去掉）
        if random.random() < 0.03:
            return (OrderSide.BUY if random.random() < 0.5 else OrderSide.SELL, self.lot_size)
        return None

    def set_symbol(self, symbol: str):
        self.symbol = symbol
        self._price_window = self._price_windows.setdefault(symbol, [])
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    # ---- 内部辅助 ----
    def _pick_symbol(self) -> str | None:
        # multi_symbol=True: 每次 tick 可能重新评估; 仍保持简单随机 + 20% 轮换概率
        if not self.multi_symbol:
            return self.symbol
        symbols: list[str] = []
        if self.universe_provider:
            try:
                symbols = self.universe_provider.symbols()
            except Exception:
                symbols = []
        if not symbols:
            symbols = engine_registry.symbols()
        if not symbols:
            return None
        if self.symbol not in symbols or random.random() < 0.2:
            old = self.symbol
            self.symbol = random.choice(symbols)
            self._price_window = self._price_windows.setdefault(self.symbol, [])
            if self.symbol != old:
                try:
                    event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
                except Exception:
                    pass
        return self.symbol

    def start(self) -> bool:
        if self.enabled:
            return False
        # 没有 symbol 时允许先启动（不会下单），后续赋值
        self.enabled = True
        return True

    def stop(self) -> bool:
        if not self.enabled:
            return False
        self.enabled = False
        return True

    def enable_debug(self, on: bool = True):
        self.debug = on
        return self

    def _debug_hit(self, reason: str):
        if not self.debug:
            return
        self.debug_counters[reason] = self.debug_counters.get(reason, 0) + 1
        try:
            print(f"[RetailClientDbg] {self.name} reason={reason} symbol={self.symbol} orders={self.stats.orders}")
        except Exception:
            pass

    def tick(self):
        if not self.enabled:
            self._debug_hit('DISABLED')
            return
        active_symbol = self._pick_symbol()
        if not active_symbol:
            self._debug_hit('NO_SYMBOL')
            return
        now = time.time()
        if now - self._last_run < self.interval:
            self._debug_hit('INTERVAL_WAIT')
            return
        self._last_run = now
        snap = None
        try:
            snap = self._ssp(active_symbol)
        except TypeError:
            try:
                snap = self._ssp(None)
            except Exception:
                snap = None
        # 回退: 若服务快照无效，直接从 engine_registry 获取
        if (snap is None or getattr(snap, 'last_price', None) in (None, 0, 0.0)):
            try:
                eng = engine_registry.get(active_symbol)
                if eng:
                    snap2 = getattr(eng, 'snapshot', None)
                    if snap2 and getattr(snap2, 'last_price', None) and getattr(snap2, 'last_price') > 0:
                        snap = snap2
                    # 仍无 last_price 时尝试使用 instrument.initial_price 进���一次性引导
                    if (snap is None or getattr(snap, 'last_price', None) in (None, 0, 0.0)) and eng and hasattr(eng, 'instrument'):
                        ip = getattr(eng.instrument, 'initial_price', None)
                        if ip and ip > 0:
                            snap = getattr(eng, 'snapshot', None)
                            if snap:
                                snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = float(ip)
            except Exception:
                pass
        # ------ 新增: 若仍无价格，注入种子价格打破死循环 ------
        last_px = getattr(snap, 'last_price', None) if snap else None
        if (not last_px) or last_px <= 0:
            try:
                eng = engine_registry.get(active_symbol)
                seed = None
                if eng:
                    inst = getattr(eng, 'instrument', None)
                    seed = getattr(inst, 'initial_price', None)
                    if not seed or seed <= 0:
                        # 尝试从 metadata 中取
                        try:
                            meta = engine_registry.metadata(active_symbol) or {}
                            seed = meta.get('initial_price')
                        except Exception:
                            pass
                if not seed or seed <= 0:
                    # 兜底默认 100，可配置化（后续可放 settings）
                    seed = 100.0 + random.random() * 0.5
                if eng:
                    snap = getattr(eng, 'snapshot', snap)
                if snap:
                    snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = float(seed)
                    last_px = float(seed)
                    self._debug_hit('SEED_PRICE')
            except Exception:
                pass
        else:
            # 正常路径: 维护窗口
            pass
        # 维护价格窗口
        if last_px and last_px > 0:
            self._price_window.append(last_px)
            if len(self._price_window) > 30:
                self._price_window[:] = self._price_window[-30:]
        else:
            self._debug_hit('NO_PRICE')
        # 决策（窗口太短时给一次启动单）
        decision = self.decide_action()
        if not decision:
            if len(self._price_window) < 3 and last_px and last_px > 0:
                # 初始冷启动: 随机首单提高后续价格波动
                side = OrderSide.BUY if random.random() < 0.5 else OrderSide.SELL
                decision = (side, self.lot_size)
                self._debug_hit('BOOTSTRAP_ORDER')
            else:
                self._debug_hit('NO_DECISION')
                return
        side, qty = decision
        if not last_px or last_px <= 0:
            self._debug_hit('PRICE_INVALID')
            return
        tick_sz = 0.01
        px_adj = last_px * (1 + (0.001 * random.random() if side is OrderSide.BUY else -0.001 * random.random()))
        price = float(f"{px_adj:.4f}")
        try:
            order = Order(symbol=active_symbol,
                          side=side,
                          price=price,
                          quantity=qty,
                          account_id=self.account_id,
                          order_type=OrderType.LIMIT,
                          tif=TimeInForce.GFD)
        except Exception:
            self._debug_hit('ORDER_BUILD_FAIL')
            return
        try:
            svc = None
            try:
                svc = self._osp(active_symbol)  # 新签名
            except TypeError:
                svc = self._osp()  # 回退旧
            if not svc:
                self._debug_hit('NO_SERVICE')
                return
            svc.place_order(order)
            self.stats.orders += 1
            self.stats.last_side = side.name
            self.stats.last_ts = now
            self._debug_hit('ORDER_PLACED')
        except Exception:
            self._debug_hit('ORDER_FAIL')
            pass

    def status_dict(self) -> dict:
        d = {
            'name': self.name,
            'account': self.account_id,
            'enabled': self.enabled,
            'interval': self.interval,
            'orders': self.stats.orders,
            'last_side': self.stats.last_side or '-',
            'strategy': self.strategy_name,
            'symbol': self.symbol or '-',
            'multi': self.multi_symbol
        }
        if self.debug:
            d['dbg'] = self.debug_counters.copy()
        return d

    strategy_registry = None
    IRetailStrategy = object  # type: ignore
try:
    from stock_sim.services.universe_provider import UniverseProvider
except Exception:
    UniverseProvider = None  # type: ignore

@dataclass
class RetailClientStats:
    orders: int = 0
    last_side: Optional[str] = None
    last_ts: float = 0.0

class RetailClient:
    """散户占位类 (静态/可扩展策略)。
    允许延迟绑定 symbol: 创建时 symbol 可以为 None; 启动后按 multi_symbol 策略自选。
    """
    def __init__(self,
                 name: str,
                 symbol: str | None,
                 account_id: str,
                 order_service_provider: Callable[[str | None], object],  # 修改: 传入 symbol
                 snapshot_provider: Callable[[str | None], object],      # 修改: 传入 symbol
                 lot_size: int = 10,
                 interval: float = 2.0,
                 strategy: str | None = None,
                 universe_provider: UniverseProvider | None = None,
                 multi_symbol: bool = True):  # 默认开启多标模式
        self.name = name
        self.symbol: str | None = symbol
        self.account_id = account_id
        self._osp = order_service_provider
        self._ssp = snapshot_provider
        self.interval = max(0.5, float(interval))
        self.lot_size = max(1, lot_size)
        self.enabled = False
        self._last_run = 0.0
        self.stats = RetailClientStats()
        self._price_windows: Dict[str, List[float]] = {}
        # 原单窗口保持引用以兼容
        self._price_window: list[float] = []
        # 策略相关
        self.strategy_name: str = strategy or 'momentum_chase'
        self._strategy: IRetailStrategy | None = None
        self.universe_provider = universe_provider
        self.multi_symbol = multi_symbol
        self._init_strategy()
        # 调试新增
        self.debug: bool = False
        self.debug_counters: Dict[str, int] = {}

    def _init_strategy(self):
        if strategy_registry is None:
            return
        try:
            self._strategy = strategy_registry.create(self.strategy_name)
        except Exception:
            # 回退默认
            try:
                self._strategy = strategy_registry.create('momentum_chase')
                self.strategy_name = 'momentum_chase'
            except Exception:
                self._strategy = None

    def set_strategy(self, name: str) -> bool:
        """热切换策略 (保持窗口数据)。"""
        if strategy_registry is None:
            return False
        if name == self.strategy_name:
            return True
        try:
            self._strategy = strategy_registry.create(name)
            self.strategy_name = name
            try:
                event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
            except Exception:
                pass
            return True
        except Exception:
            return False

    def set_interval(self, sec: float):
        self.interval = max(0.5, float(sec))
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    # ---- strategy placeholder ----
    def decide_action(self):
        """委托给当前策略 (兼容旧逻辑)。"""
        if self._strategy:
            try:
                return self._strategy.decide(self._price_window, self._price_window[-1] if self._price_window else None, self.lot_size)
            except Exception:
                pass
        # ===== 下面为旧 fallback 逻辑 =====
        if len(self._price_window) < 3:
            return None
        p1, p2, p3 = self._price_window[-3:]
        if p1 < p2 < p3:  # 上升
            return OrderSide.BUY, self.lot_size
        if p1 > p2 > p3:  # 下降
            return OrderSide.SELL, self.lot_size
        # 低概率随机噪声单（演示用，可去掉）
        if random.random() < 0.03:
            return (OrderSide.BUY if random.random() < 0.5 else OrderSide.SELL, self.lot_size)
        return None

    def set_symbol(self, symbol: str):
        self.symbol = symbol
        self._price_window = self._price_windows.setdefault(symbol, [])
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    # ---- 内部辅助 ----
    def _pick_symbol(self) -> str | None:
        # multi_symbol=True: 每次 tick 可能重新评估; 仍保持简单随机 + 20% 轮换概率
        if not self.multi_symbol:
            return self.symbol
        symbols: list[str] = []
        if self.universe_provider:
            try:
                symbols = self.universe_provider.symbols()
            except Exception:
                symbols = []
        if not symbols:
            symbols = engine_registry.symbols()
        if not symbols:
            return None
        if self.symbol not in symbols or random.random() < 0.2:
            old = self.symbol
            self.symbol = random.choice(symbols)
            self._price_window = self._price_windows.setdefault(self.symbol, [])
            if self.symbol != old:
                try:
                    event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
                except Exception:
                    pass
        return self.symbol

    def start(self) -> bool:
        if self.enabled:
            return False
        # 没有 symbol 时允许先启动（不会下单），后续赋值
        self.enabled = True
        return True

    def stop(self) -> bool:
        if not self.enabled:
            return False
        self.enabled = False
        return True

    def enable_debug(self, on: bool = True):
        self.debug = on
        return self

    def _debug_hit(self, reason: str):
        if not self.debug:
            return
        self.debug_counters[reason] = self.debug_counters.get(reason, 0) + 1
        try:
            print(f"[RetailClientDbg] {self.name} reason={reason} symbol={self.symbol} orders={self.stats.orders}")
        except Exception:
            pass

    def tick(self):
        if not self.enabled:
            self._debug_hit('DISABLED')
            return
        active_symbol = self._pick_symbol()
        if not active_symbol:
            self._debug_hit('NO_SYMBOL')
            return
        now = time.time()
        if now - self._last_run < self.interval:
            self._debug_hit('INTERVAL_WAIT')
            return
        self._last_run = now
        snap = None
        try:
            snap = self._ssp(active_symbol)
        except TypeError:
            try:
                snap = self._ssp(None)
            except Exception:
                snap = None
        # 回退: 若服务快照无效，直接从 engine_registry 获取
        if (snap is None or getattr(snap, 'last_price', None) in (None, 0, 0.0)):
            try:
                eng = engine_registry.get(active_symbol)
                if eng:
                    snap2 = getattr(eng, 'snapshot', None)
                    if snap2 and getattr(snap2, 'last_price', None) and getattr(snap2, 'last_price') > 0:
                        snap = snap2
                    # 仍无 last_price 时尝试使用 instrument.initial_price 进���一次性引导
                    if (snap is None or getattr(snap, 'last_price', None) in (None, 0, 0.0)) and eng and hasattr(eng, 'instrument'):
                        ip = getattr(eng.instrument, 'initial_price', None)
                        if ip and ip > 0:
                            snap = getattr(eng, 'snapshot', None)
                            if snap:
                                snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = float(ip)
            except Exception:
                pass
        # ------ 新增: 若仍无价格，注入种子价格打破死循环 ------
        last_px = getattr(snap, 'last_price', None) if snap else None
        if (not last_px) or last_px <= 0:
            try:
                eng = engine_registry.get(active_symbol)
                seed = None
                if eng:
                    inst = getattr(eng, 'instrument', None)
                    seed = getattr(inst, 'initial_price', None)
                    if not seed or seed <= 0:
                        # 尝试从 metadata 中取
                        try:
                            meta = engine_registry.metadata(active_symbol) or {}
                            seed = meta.get('initial_price')
                        except Exception:
                            pass
                if not seed or seed <= 0:
                    # 兜底默认 100，可配置化（后续可放 settings）
                    seed = 100.0 + random.random() * 0.5
                if eng:
                    snap = getattr(eng, 'snapshot', snap)
                if snap:
                    snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = float(seed)
                    last_px = float(seed)
                    self._debug_hit('SEED_PRICE')
            except Exception:
                pass
        else:
            # 正常路径: 维护窗口
            pass
        # 维护价格窗口
        if last_px and last_px > 0:
            self._price_window.append(last_px)
            if len(self._price_window) > 30:
                self._price_window[:] = self._price_window[-30:]
        else:
            self._debug_hit('NO_PRICE')
        # 决策（窗口太短时给一次启动单）
        decision = self.decide_action()
        if not decision:
            if len(self._price_window) < 3 and last_px and last_px > 0:
                # 初始冷启动: 随机首单提高后续价格波动
                side = OrderSide.BUY if random.random() < 0.5 else OrderSide.SELL
                decision = (side, self.lot_size)
                self._debug_hit('BOOTSTRAP_ORDER')
            else:
                self._debug_hit('NO_DECISION')
                return
        side, qty = decision
        if not last_px or last_px <= 0:
            self._debug_hit('PRICE_INVALID')
            return
        tick_sz = 0.01
        px_adj = last_px * (1 + (0.001 * random.random() if side is OrderSide.BUY else -0.001 * random.random()))
        price = float(f"{px_adj:.4f}")
        try:
            order = Order(symbol=active_symbol,
                          side=side,
                          price=price,
                          quantity=qty,
                          account_id=self.account_id,
                          order_type=OrderType.LIMIT,
                          tif=TimeInForce.GFD)
        except Exception:
            self._debug_hit('ORDER_BUILD_FAIL')
            return
        try:
            svc = None
            try:
                svc = self._osp(active_symbol)  # 新签名
            except TypeError:
                svc = self._osp()  # 回退旧
            if not svc:
                self._debug_hit('NO_SERVICE')
                return
            svc.place_order(order)
            self.stats.orders += 1
            self.stats.last_side = side.name
            self.stats.last_ts = now
            self._debug_hit('ORDER_PLACED')
        except Exception:
            self._debug_hit('ORDER_FAIL')
            pass

    def status_dict(self) -> dict:
        d = {
            'name': self.name,
            'account': self.account_id,
            'enabled': self.enabled,
            'interval': self.interval,
            'orders': self.stats.orders,
            'last_side': self.stats.last_side or '-',
            'strategy': self.strategy_name,
            'symbol': self.symbol or '-',
            'multi': self.multi_symbol
        }
        if self.debug:
            d['dbg'] = self.debug_counters.copy()
        return d
