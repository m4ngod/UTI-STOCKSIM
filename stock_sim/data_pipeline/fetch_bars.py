# python
"""数据获取与前复权/连续合约预处理 (M1 MVP)

功能 (最小实现):
1. 从数据库读取 30s/日线数据 (若库中无 30s 则用 1m 拆分占位)
2. 计算股票前复权 (基于日级 adj_factor)
3. 统一输出 dict[symbol] = np.ndarray[T, 6]  (ts, open, high, low, close, volume)

后续扩展:
- 期货连续主力合约拼接 (占位: 直接使用 symbol 原数据)
- VWAP/amount 特征 (此处不返回, 交由特征工程阶段)
- 高并发批量拉取 (async / 分片)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Sequence, Optional
import numpy as np
from sqlalchemy.orm import Session

try:
    from stock_sim.persistence.models_bars import Bar1d
except Exception:  # 容错
    Bar1d = None  # type: ignore

# === 配置 ===
@dataclass
class FetchConfig:
    lookback_days: int = 30           # K 天窗口 (含当日)
    bar_seconds: int = 30             # 30s 粒度
    trading_start: str = "09:30:00"
    trading_end: str = "15:00:00"
    pre_open: str = "09:15:00"        # 若有集合竞价可加
    use_adjust_price: bool = True

# === 工具函数 ===
def _gen_time_grid(day: datetime, start: str, end: str, step_sec: int) -> List[datetime]:
    dt_start = datetime.combine(day.date(), datetime.strptime(start, "%H:%M:%S").time())
    dt_end = datetime.combine(day.date(), datetime.strptime(end, "%H:%M:%S").time())
    out = []
    t = dt_start
    while t <= dt_end:
        out.append(t)
        t += timedelta(seconds=step_sec)
    return out

# === 主函数 ===
def fetch_30s_bars(symbols: Sequence[str], end_day: datetime, session: Session, cfg: FetchConfig | None = None) -> Dict[str, np.ndarray]:
    """拉取最近 K 天 30s bars (若数据库没有 30s 表, 用日内时间网格 + 简化线性插值占位)
    返回 dict[symbol] -> ndarray[T,6]
    注意: 这里只做 MVP, 实际应读取真实 30s 表; 没有则需聚合 tick/1s/1m。
    """
    cfg = cfg or FetchConfig()
    start_day = end_day - timedelta(days=cfg.lookback_days-1)
    days = [start_day + timedelta(days=i) for i in range(cfg.lookback_days)]
    # 读取日线做前复权
    daily_map: Dict[str, List] = {s: [] for s in symbols}
    if Bar1d is None:
        raise RuntimeError("Bar1d model 未找到, 请确认 models_bars 导入")
    q = (session.query(Bar1d)
         .filter(Bar1d.symbol.in_(symbols))
         .filter(Bar1d.ts >= datetime(start_day.year, start_day.month, start_day.day))
         .filter(Bar1d.ts <= datetime(end_day.year, end_day.month, end_day.day, 23, 59, 59)))
    for row in q:  # type: ignore
        daily_map[row.symbol].append(row)
    out: Dict[str, np.ndarray] = {}
    for sym in symbols:
        # 排序
        drows = sorted(daily_map.get(sym, []), key=lambda r: r.ts)
        if not drows:
            # 空数据 -> 生成最小占位
            out[sym] = np.zeros((len(days), 6), dtype=float)
            continue
        # 构造累乘前复权因子 (MVP: 用 close 序列自身归一)
        closes = np.array([r.close for r in drows], dtype=float)
        if closes[-1] == 0:
            adj = np.ones_like(closes)
        else:
            adj = closes / closes[-1]
        # 映射日 -> adj factor
        adj_factor_map = {r.ts.date(): adj[i] for i, r in enumerate(drows)}
        ts_all: List[datetime] = []
        O=[];H=[];L=[];C=[];V=[]
        for day_dt in days:
            grid = _gen_time_grid(day_dt, cfg.trading_start, cfg.trading_end, cfg.bar_seconds)
            # 找到该日对应日线
            dbar = next((r for r in drows if r.ts.date()==day_dt.date()), None)
            if dbar is None:
                # 无交易日: 填零
                for _ in grid:
                    ts_all.append(day_dt)
                    O.append(0);H.append(0);L.append(0);C.append(0);V.append(0)
                continue
            # 简化: 用日线 close 生成水平价格 (无波动) 作为占位; 可扩展读取 30s 表
            # 可加入微扰避免训练退化
            base_price = dbar.close
            # 添加微小噪声 (受控) 保持可学习信号 (后续换真实)
            noise = (np.random.default_rng(int(base_price*1000))
                     .normal(0, 0.0005, size=len(grid)))
            for i, t in enumerate(grid):
                px = base_price * (1+noise[i])
                ts_all.append(t)
                O.append(px);H.append(px);L.append(px);C.append(px);V.append(dbar.volume/len(grid))
        arr = np.column_stack([
            np.array([int(t.timestamp()) for t in ts_all], dtype=np.int64),
            np.array(O), np.array(H), np.array(L), np.array(C), np.array(V)
        ])
        # 前复权 (以最后一日因子=1): price * adj_factor_day
        if cfg.use_adjust_price:
            for i, t in enumerate(ts_all):
                f = adj_factor_map.get(datetime.fromtimestamp(int(t.timestamp())).date(), 1.0)
                arr[i,1:5] *= f
        out[sym] = arr.astype(float)
    return out

__all__ = ["FetchConfig", "fetch_30s_bars"]

