# pytest: unit tests for CreateInstrumentDialog
from __future__ import annotations
import pytest

from app.panels.market.dialog import CreateInstrumentDialog
from app.utils.validators import round_to_price_step


class FakeMarketController:
    def __init__(self):
        self.calls: list[dict] = []

    def create_instrument(self, *, name: str, symbol: str,
                          initial_price, float_shares, market_cap, total_shares, price_step: float):
        # 模拟真实控制器的核心行为：
        price = round_to_price_step(initial_price, step=price_step) if initial_price is not None else None
        fs = int(float_shares) if float_shares is not None else None
        mcap = float(market_cap) if market_cap is not None else None
        if mcap is None and (fs is not None and price is not None):
            mcap = round(fs * price, 2)
        if total_shares is None and fs is not None:
            total_shares = fs
        payload = {
            "name": name,
            "symbol": symbol,
            "initial_price": price,
            "float_shares": fs,
            "market_cap": mcap if market_cap is not None else None,  # 保持原本留空 None
            "total_shares": total_shares,
            "price_step": price_step,
        }
        self.calls.append(payload)
        return payload


def _make_dialog(price_step: float = 0.05):
    ctl = FakeMarketController()
    dlg = CreateInstrumentDialog(ctl, price_step=price_step)
    return ctl, dlg


def test_triad_requires_exactly_one_missing():
    ctl, dlg = _make_dialog()
    # 两个缺失 -> 错误
    dlg.set_fields(name="Acme", symbol="acm", initial_price="10", float_shares="", market_cap="")
    v = dlg.get_view()
    assert v["errors"].get("triad") == "ERR_TRIAD_NEED_EXACTLY_ONE_EMPTY"
    # 都不缺失 -> 错误
    dlg.set_fields(initial_price="10", float_shares="100", market_cap="1000")
    v = dlg.get_view()
    assert v["errors"].get("triad") == "ERR_TRIAD_NEED_EXACTLY_ONE_EMPTY"


def test_preview_derivation_and_submit_missing_market_cap():
    ctl, dlg = _make_dialog(price_step=0.1)
    dlg.set_fields(name="Acme", symbol="acm", initial_price="12.34", float_shares="1000", market_cap="")
    v = dlg.get_view()
    # 预览应派生 market_cap 并四舍五入到 0.01（validators 中）
    assert v["derived"]["field"] == "market_cap"
    assert isinstance(v["normalized"]["market_cap"], float)
    assert pytest.approx(v["normalized"]["market_cap"], rel=1e-6) == 12340.0
    assert v["is_valid"] is True
    # 提交：保持原本缺失���段为 None 传给控制器；控制器对价格按步长取整
    ok = dlg.submit()
    assert ok is True
    assert ctl.calls, "controller should be called"
    payload = ctl.calls[-1]
    assert payload["initial_price"] == pytest.approx(12.3, rel=1e-6)  # price_step=0.1 取整
    assert payload["float_shares"] == 1000
    assert payload["market_cap"] is None  # 原本留空
    # last_result 回显
    view2 = dlg.get_view()
    assert isinstance(view2["last_result"], dict)


def test_field_errors_and_total_lt_float():
    ctl, dlg = _make_dialog()
    # 非法数字
    dlg.set_fields(name=" ", symbol=" ", initial_price="abc", float_shares="-1", market_cap="-5")
    v = dlg.get_view()
    assert v["errors"].get("name") == "ERR_EMPTY_NAME"
    assert v["errors"].get("symbol") == "ERR_EMPTY_SYMBOL"
    assert v["errors"].get("initial_price") == "ERR_PRICE_INVALID"
    assert v["errors"].get("float_shares") == "ERR_FLOAT_SHARES_INVALID"
    assert v["errors"].get("market_cap") == "ERR_MARKET_CAP_INVALID"
    # 合法三元 + total_shares 小于 float_shares -> 错误
    dlg.set_fields(name="Acme", symbol="ACM", initial_price="", float_shares="100", market_cap="1000", total_shares="50")
    v2 = dlg.get_view()
    assert v2["errors"].get("total_shares") == "ERR_TOTAL_LT_FLOAT"
    # 表单无效则 submit 返回 False 且记录 last_error
    ok = dlg.submit()
    assert ok is False
    assert dlg.get_view()["last_error"] == "ERR_FORM_INVALID"
