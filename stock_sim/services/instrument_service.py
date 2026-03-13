# python
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import List, Optional
from sqlalchemy.orm import Session
from stock_sim.persistence.models_instrument import Instrument
from stock_sim.core.instruments import create_instrument, Stock
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.FE.engine_registry import engine_registry
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # 新增: 模拟时钟
from stock_sim.settings import settings  # 添加以获取 IPO_CALL_AUCTION_SECONDS
import os  # 调试
import time  # 新增: 重试等待
from sqlalchemy.exc import OperationalError  # 新增: 捕获 locked
TRACE_SIMDAY = os.environ.get('DEBUG_TRACE_SIMDAY') == '1'

@dataclass
class InstrumentDTO:
    symbol: str
    name: str
    tick_size: float
    lot_size: int
    min_qty: int
    settlement_cycle: int
    market_cap: float | None
    total_shares: float | None
    free_float_shares: float | None
    initial_price: float | None  # 新增
    created_at: str | None
    is_active: bool
    ipo_opened: bool  # 新增

    @staticmethod
    def from_model(m: Instrument) -> 'InstrumentDTO':
        return InstrumentDTO(
            symbol=m.symbol,
            name=m.name or m.symbol,
            tick_size=m.tick_size,
            lot_size=m.lot_size,
            min_qty=m.min_qty,
            settlement_cycle=m.settlement_cycle,
            market_cap=m.market_cap,
            total_shares=m.total_shares,
            free_float_shares=m.free_float_shares,
            initial_price=getattr(m, 'initial_price', None),
            created_at=m.created_at.isoformat() if getattr(m, 'created_at', None) else None,
            is_active=bool(getattr(m, 'is_active', True)),
            ipo_opened=bool(getattr(m, 'ipo_opened', False)),
        )

class InstrumentService:
    """封装 instruments 表 CRUD + 引擎注册逻辑。"""
    def __init__(self, session: Session):
        self.s = session

    def _stamp(self, inst_row: Instrument):  # 新增: 打模拟时钟戳
        try:
            sd = current_sim_day()
            if TRACE_SIMDAY:
                print(f"[TRACE InstrumentService.stamp] symbol={getattr(inst_row,'symbol',None)} sim_day={sd}")
            if not sd:
                return
            if hasattr(inst_row, 'sim_day') and not getattr(inst_row, 'sim_day', None):
                inst_row.sim_day = sd
            if hasattr(inst_row, 'sim_dt') and not getattr(inst_row, 'sim_dt', None):
                inst_row.sim_dt = virtual_datetime(sd)
        except Exception as e:
            if TRACE_SIMDAY:
                print(f"[TRACE InstrumentService.stamp.error] {e}")
            pass

    # -------- Create / Upsert --------
    def create(self, *, symbol: str, name: str = "", tick_size: float = 0.01, lot_size: int = 1,
               min_qty: int = 1, settlement_cycle: int | None = None,
               market_cap: float | None = None,
               total_shares: float | None = None, free_float_shares: float | None = None,
               initial_price: float | None = None,
               ipo_opened: bool | None = None,
               overwrite: bool = False) -> InstrumentDTO:
        sym = symbol.upper().strip()
        if not sym:
            raise ValueError("symbol 不能为空")
        inst_row = self.s.get(Instrument, sym)
        if inst_row and not overwrite and not inst_row.is_active:
            # 软删除状态下直接恢复并更新字段
            inst_row.is_active = True
        if inst_row is None:
            inst_row = Instrument(symbol=sym)
            self.s.add(inst_row)
        # 更新字段
        inst_row.name = name or sym
        inst_row.tick_size = tick_size
        inst_row.lot_size = lot_size
        inst_row.min_qty = min_qty
        if settlement_cycle is not None:
            inst_row.settlement_cycle = settlement_cycle
        if market_cap is not None: inst_row.market_cap = market_cap
        if total_shares is not None: inst_row.total_shares = total_shares
        if free_float_shares is not None: inst_row.free_float_shares = free_float_shares
        if initial_price is not None:
            setattr(inst_row, 'initial_price', initial_price)
        if ipo_opened is not None:
            setattr(inst_row, 'ipo_opened', bool(ipo_opened))
        inst_row.is_active = True
        self._stamp(inst_row)
        # 重试 flush 以避免 sqlite locked (测试并发订阅事件导致临时锁)
        attempts = 0
        while True:
            try:
                self.s.flush()
                break
            except OperationalError as e:
                msg = str(e).lower()
                if 'locked' in msg and attempts < 4:
                    attempts += 1
                    time.sleep(0.02 * attempts)
                    continue
                raise
        # 注册撮合引擎（���未存在）
        if engine_registry.get(sym) is None:
            if TRACE_SIMDAY:
                print(f"[TRACE InstrumentService.create] register_engine symbol={sym} ipo_opened={getattr(inst_row,'ipo_opened',False)} initial_price={initial_price}")
            stock_obj: Stock = create_instrument(sym, tick_size=tick_size, lot_size=lot_size, min_qty=min_qty, initial_price=initial_price)
            # 注入 IPO 相关属性供 MatchingEngine 判定
            try:
                stock_obj.total_shares = inst_row.total_shares or 0
                stock_obj.free_float_shares = inst_row.free_float_shares or 0
                stock_obj.initial_price = inst_row.initial_price
                stock_obj.ipo_opened = getattr(inst_row, 'ipo_opened', False)
            except Exception:
                pass
            from stock_sim.core.const import Phase
            eng = MatchingEngine(sym, instrument=stock_obj)
            # 根据 ipo_opened 标志设置初始阶段
            if getattr(inst_row, 'ipo_opened', False):
                eng.phase = Phase.CONTINUOUS
                try:
                    bk = eng._books[sym]
                    bk.phase = Phase.CONTINUOUS
                    bk.has_continuous_started = True
                except Exception:
                    pass
            else:
                eng.phase = Phase.CALL_AUCTION
            if TRACE_SIMDAY:
                print(f"[TRACE InstrumentService.phase.init] symbol={sym} phase={eng.phase.name}")
            engine_registry.register(sym, eng, name=inst_row.name, pe=inst_row.pe, market_cap=inst_row.market_cap, initial_price=initial_price)
            # 若提供 initial_price，仍写入 snapshot（集合竞价阶段仅作为参考价，不代表成交）
            if initial_price is not None and initial_price > 0:
                try:
                    snap = eng.snapshot
                    # 仅在连续阶段或允许展示参考价时写入 last_price；集合竞价阶段留 last_price 为 initial_price 便于 UI 展示
                    snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = float(initial_price)
                except Exception:
                    pass
            # IPO 计时保持原逻辑
            try:
                from stock_sim.services.sim_clock import ensure_sim_clock_started
                ensure_sim_clock_started()
                # 使用全局 time 模块 (顶部已 import time)
                dur = float(getattr(settings, 'IPO_CALL_AUCTION_SECONDS', 3.75))
                eng._ipo_end_ts = time.time() + dur
                if TRACE_SIMDAY:
                    print(f"[TRACE InstrumentService.ipo_timer] symbol={sym} real_secs={dur:.3f} end_ts={eng._ipo_end_ts:.3f}")
            except Exception as e:
                if TRACE_SIMDAY:
                    print(f"[TRACE InstrumentService.ipo_timer.error] symbol={sym} err={e}")
                pass
        return InstrumentDTO.from_model(inst_row)

    # -------- Update --------
    def update(self, symbol: str, **patch) -> InstrumentDTO:
        sym = symbol.upper()
        inst_row = self.s.get(Instrument, sym)
        if not inst_row:
            raise ValueError(f"标的不存在: {sym}")
        mutable = {"name","market_cap","total_shares","free_float_shares","initial_price","ipo_opened"}
        structural = {"tick_size","lot_size","min_qty","settlement_cycle"}
        initial_price_before = getattr(inst_row, 'initial_price', None)
        for k, v in patch.items():
            if k in mutable:
                setattr(inst_row, k, v)
            elif k in structural:
                setattr(inst_row, k, v)
        self._stamp(inst_row)
        self.s.flush()
        engine_registry.update_meta(sym, **{k: getattr(inst_row, k) for k in ("name","pe","market_cap","initial_price")})
        # 若 initial_price 更新且引擎存在, 补同步 instrument + snapshot (仅当 snapshot 尚未产生真实成交)
        try:
            if 'initial_price' in patch and patch['initial_price'] and patch['initial_price'] > 0:
                eng = engine_registry.get(sym)
                if eng:
                    if hasattr(eng, 'instrument'):
                        try: eng.instrument.initial_price = patch['initial_price']
                        except Exception: pass
                    snap = getattr(eng, 'snapshot', None)
                    if snap and (snap.last_price is None or snap.last_price <= 0):
                        p = float(patch['initial_price'])
                        snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = p
        except Exception:
            pass
        if TRACE_SIMDAY:
            try:
                print(f"[TRACE InstrumentService.update.after] symbol={sym} initial_price={getattr(inst_row,'initial_price',None)} ipo_opened={getattr(inst_row,'ipo_opened',None)}")
            except Exception:
                pass
        return InstrumentDTO.from_model(inst_row)

    # -------- Soft Delete --------
    def soft_delete(self, symbol: str) -> bool:
        sym = symbol.upper()
        inst_row = self.s.get(Instrument, sym)
        if not inst_row or not inst_row.is_active:
            return False
        inst_row.is_active = False
        self.s.flush()
        # 引擎仍保留（历史引用），不强制 remove；如需彻底释��可调用 engine_registry.remove(sym)
        return True

    def restore(self, symbol: str) -> bool:
        sym = symbol.upper()
        inst_row = self.s.get(Instrument, sym)
        if not inst_row:
            return False
        if not inst_row.is_active:
            inst_row.is_active = True
            self.s.flush()
        return True

    # -------- Query --------
    def get(self, symbol: str) -> InstrumentDTO | None:
        m = self.s.get(Instrument, symbol.upper())
        return InstrumentDTO.from_model(m) if m else None

    def list(self, *, active_only: bool = True) -> List[InstrumentDTO]:
        q = self.s.query(Instrument)
        if active_only:
            q = q.filter(Instrument.is_active.is_(True))
        return [InstrumentDTO.from_model(m) for m in q.order_by(Instrument.symbol.asc()).all()]

# 简单工厂函数
from stock_sim.persistence.models_imports import SessionLocal

def instrument_service_factory() -> InstrumentService:
    return InstrumentService(SessionLocal())
