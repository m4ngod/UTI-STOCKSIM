from __future__ import annotations
from typing import Dict, Any
import numpy as np
try:  # 可选 pandas
    import pandas as _pd  # type: ignore
except Exception:  # pragma: no cover
    _pd = None

__all__ = ["indicator_ma"]

def _ensure_window(param_name: str, params: Dict[str, Any], default: int) -> int:
    v = int(params.get(param_name, default))
    if v <= 0:
        raise ValueError(f"{param_name} must be >0")
    return v

def indicator_ma(arr: np.ndarray, params: Dict[str, Any]):
    window = _ensure_window("window", params, 5)
    out = np.full_like(arr, np.nan, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return out
    if _pd is not None and n >= window:  # 使用 pandas rolling
        try:
            s = _pd.Series(arr)
            r = s.rolling(window=window, min_periods=window).mean()
            out[:] = r.to_numpy(dtype=np.float64)
            return out
        except Exception:  # pragma: no cover - 回退
            pass
    if n < window:
        return out
    cumsum = np.cumsum(arr, dtype=float)
    out[window-1:] = (cumsum[window-1:] - np.concatenate(([0.0], cumsum[:-window])))/window
    return out
