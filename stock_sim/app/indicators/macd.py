from __future__ import annotations
from typing import Dict, Any
import numpy as np
try:  # 可选 pandas
    import pandas as _pd  # type: ignore
except Exception:  # pragma: no cover
    _pd = None

__all__ = ["indicator_macd"]

def _ensure_window(param_name: str, params: Dict[str, Any], default: int) -> int:
    v = int(params.get(param_name, default))
    if v <= 0:
        raise ValueError(f"{param_name} must be >0")
    return v

def _ema(a: np.ndarray, span: int) -> np.ndarray:
    alpha = 2 / (span + 1)
    out = np.empty_like(a, dtype=np.float64)
    if len(a) == 0:
        return out
    out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = alpha * a[i] + (1 - alpha) * out[i - 1]
    return out

def indicator_macd(arr: np.ndarray, params: Dict[str, Any]):
    fast = _ensure_window("fast", params, 12)
    slow = _ensure_window("slow", params, 26)
    signal = _ensure_window("signal", params, 9)
    if fast >= slow:
        raise ValueError("fast must < slow")
    n = len(arr)
    if n == 0:
        empty = np.array([], dtype=np.float64)
        return {"macd": empty, "signal": empty, "hist": empty}
    # 优先使用 pandas ewm
    if _pd is not None:
        try:
            s = _pd.Series(arr)
            ema_fast = s.ewm(span=fast, adjust=False).mean().to_numpy(dtype=np.float64)
            ema_slow = s.ewm(span=slow, adjust=False).mean().to_numpy(dtype=np.float64)
            macd_line = ema_fast - ema_slow
            signal_line = _pd.Series(macd_line).ewm(span=signal, adjust=False).mean().to_numpy(dtype=np.float64)
            hist = macd_line - signal_line
            return {"macd": macd_line, "signal": signal_line, "hist": hist}
        except Exception:  # pragma: no cover 回退
            pass
    ema_fast = _ema(arr, fast)
    ema_slow = _ema(arr, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "hist": hist}
