import numpy as np
from app.indicators import indicator_registry


def test_ma_shape_and_values():
    data = np.arange(1, 11, dtype=float)  # 1..10
    out = indicator_registry.compute("ma", data, window=3)
    assert out.shape == data.shape
    # 第三个位置应为 (1+2+3)/3 = 2
    assert np.isnan(out[:2]).all()
    assert out[2] == 2
    assert not np.isnan(out[5:]).any()


def test_rsi_shape():
    rng = np.linspace(1, 30, 30)
    out = indicator_registry.compute("rsi", rng, period=14)
    assert out.shape == rng.shape
    assert np.isnan(out[:14]).all()
    assert not np.isnan(out[20:]).all()  # 后半段应出现数值


def test_macd_shapes():
    data = np.linspace(10, 20, 50)
    res = indicator_registry.compute("macd", data, fast=12, slow=26, signal=9)
    assert set(res.keys()) == {"macd", "signal", "hist"}
    for k, v in res.items():
        assert v.shape == data.shape
    # hist = macd - signal 近似验证（前几位会逐步收敛）
    assert np.allclose(res["hist"], res["macd"] - res["signal"], atol=1e-9)
