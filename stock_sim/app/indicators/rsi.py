from __future__ import annotations
from typing import Dict, Any
import numpy as np

__all__ = ["indicator_rsi"]

def _ensure_window(param_name: str, params: Dict[str, Any], default: int) -> int:
    v = int(params.get(param_name, default))
    if v <= 0:
        raise ValueError(f"{param_name} must be >0")
    return v

def indicator_rsi(arr: np.ndarray, params: Dict[str, Any]):
    period = _ensure_window("period", params, 14)
    out = np.full_like(arr, np.nan, dtype=np.float64)
    n = len(arr)
    if n < period + 1:
        return out
    diff = np.diff(arr)
    gains = np.clip(diff, 0, None)
    losses = -np.clip(diff, None, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    rs_list = []
    rs = np.inf if avg_loss == 0 else avg_gain / avg_loss
    rs_list.append(rs)
    for i in range(period, len(diff)):
        g = gains[i]
        l = losses[i]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        rs = np.inf if avg_loss == 0 else avg_gain / avg_loss
        rs_list.append(rs)
    rsi_series = 100 - (100 / (1 + np.array(rs_list)))
    out[period:] = rsi_series
    return out

