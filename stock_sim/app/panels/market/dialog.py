# // filepath: f:\PythonProjects\stock_sim\app\panels\market\dialog.py
from __future__ import annotations
from threading import RLock
from typing import Any, Dict, Optional, Literal

from app.controllers.market_controller import MarketController
from app.utils.validators import safe_float, safe_int, derive_third_value

try:  # 可选 metrics
    from observability.metrics import metrics  # type: ignore
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *_, **__):
            pass
    metrics = _Dummy()

__all__ = ["CreateInstrumentDialog", "register_create_instrument_dialog"]

TriadField = Literal["initial_price", "float_shares", "market_cap"]


class CreateInstrumentDialog:
    """纯逻辑对话框：创建新标的

    字段：name, symbol, initial_price, float_shares, market_cap, total_shares
    规则：initial_price/float_shares/market_cap 三者中必须有且仅有一个留空，用其余两项推导第三项。
    - 就地校验：记录 errors 映射（错误码），不抛异常到 UI 层。
    - 提交：调用 MarketController.create_instrument，并把“原本留空”的字段仍置为 None 交由控制器最终推导。
    """

    def __init__(self, controller: MarketController, *, price_step: float = 0.01):
        self._ctl = controller
        self._lock = RLock()
        # 表单字段（字符串原值，便于就地回显）
        self._name: str = ""
        self._symbol: str = ""
        self._initial_price: Optional[str] = None
        self._float_shares: Optional[str] = None
        self._market_cap: Optional[str] = None
        self._total_shares: Optional[str] = None
        # 归一化后的数值（解析成功才填充）
        self._norm_price: Optional[float] = None
        self._norm_float_shares: Optional[int] = None
        self._norm_market_cap: Optional[float] = None
        self._norm_total_shares: Optional[int] = None
        # 哪个字段是原始留空（用于 submit 阶段保持 None）
        self._original_missing: Optional[TriadField] = None
        # 最近一次派生出的字段（便于 UI 高亮）
        self._derived_field: Optional[TriadField] = None
        self._derived_value: Optional[float | int] = None
        # 其它状态
        self._price_step: float = price_step
        self._errors: Dict[str, str] = {}
        self._last_error: Optional[str] = None
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------- Mutations -------------
    def set_fields(self, *, name: Optional[str] = None, symbol: Optional[str] = None,
                   initial_price: Optional[str] = None, float_shares: Optional[str] = None,
                   market_cap: Optional[str] = None, total_shares: Optional[str] = None):
        with self._lock:
            if name is not None:
                self._name = name
            if symbol is not None:
                self._symbol = symbol
            if initial_price is not None:
                self._initial_price = initial_price if initial_price != "" else None
            if float_shares is not None:
                self._float_shares = float_shares if float_shares != "" else None
            if market_cap is not None:
                self._market_cap = market_cap if market_cap != "" else None
            if total_shares is not None:
                self._total_shares = total_shares if total_shares != "" else None
            # 每次更新都重新校验与尝试推导
            self._recompute()

    def clear(self):
        with self._lock:
            self.__init__(self._ctl, price_step=self._price_step)  # reset 所有字段

    # ------------- Internal -------------
    def _recompute(self):
        self._errors.clear()
        self._last_error = None
        self._last_result = None
        self._derived_field = None
        self._derived_value = None
        # 解析 name/symbol
        name = (self._name or "").strip()
        symbol = (self._symbol or "").strip().upper()
        if not name:
            self._errors["name"] = "ERR_EMPTY_NAME"
        if not symbol:
            self._errors["symbol"] = "ERR_EMPTY_SYMBOL"
        # 解析数值（允许为空）
        norm_price = None
        norm_fs = None
        norm_mcap = None
        norm_ts = None
        price_err = fs_err = mcap_err = ts_err = None
        # price
        if self._initial_price is not None:
            try:
                norm_price = safe_float(self._initial_price, min_value=0)
            except Exception:
                price_err = "ERR_PRICE_INVALID"
        # float_shares
        if self._float_shares is not None:
            try:
                norm_fs = safe_int(self._float_shares, min_value=0)
            except Exception:
                fs_err = "ERR_FLOAT_SHARES_INVALID"
        # market_cap
        if self._market_cap is not None:
            try:
                norm_mcap = safe_float(self._market_cap, min_value=0)
            except Exception:
                mcap_err = "ERR_MARKET_CAP_INVALID"
        # total_shares
        if self._total_shares is not None:
            try:
                norm_ts = safe_int(self._total_shares, min_value=0)
            except Exception:
                ts_err = "ERR_TOTAL_SHARES_INVALID"
        if price_err:
            self._errors["initial_price"] = price_err
        if fs_err:
            self._errors["float_shares"] = fs_err
        if mcap_err:
            self._errors["market_cap"] = mcap_err
        if ts_err:
            self._errors["total_shares"] = ts_err
        # 三元规则：必须有且仅有一个为空
        provided = {
            "initial_price": norm_price if self._initial_price is not None and price_err is None else None,
            "float_shares": norm_fs if self._float_shares is not None and fs_err is None else None,
            "market_cap": norm_mcap if self._market_cap is not None and mcap_err is None else None,
        }
        triad_field_errors = any([price_err, fs_err, mcap_err])
        if not triad_field_errors:
            none_cnt = sum(v is None for v in provided.values())
            if none_cnt != 1:
                self._errors["triad"] = "ERR_TRIAD_NEED_EXACTLY_ONE_EMPTY"
            else:
                # 确定 original_missing（仅当首次或改变为新的缺失字段时更新）
                missing_field: TriadField = next(k for k, v in provided.items() if v is None)  # type: ignore[assignment]
                self._original_missing = missing_field
                # 执行推导（就地预览）
                try:
                    d = derive_third_value(
                        float_shares=provided["float_shares"],
                        market_cap=provided["market_cap"],
                        price=provided["initial_price"],
                        price_step=self._price_step,
                    )
                    if "float_shares" in d:
                        self._derived_field = "float_shares"
                        self._derived_value = int(d["float_shares"])  # type: ignore[index]
                        norm_fs = int(d["float_shares"])  # type: ignore[index]
                    elif "market_cap" in d:
                        self._derived_field = "market_cap"
                        self._derived_value = float(d["market_cap"])  # type: ignore[index]
                        norm_mcap = float(d["market_cap"])  # type: ignore[index]
                    elif "price" in d:
                        self._derived_field = "initial_price"
                        self._derived_value = float(d["price"])  # type: ignore[index]
                        norm_price = float(d["price"])  # type: ignore[index]
                except Exception:
                    self._errors["triad"] = "ERR_TRIAD_DERIVE_FAILED"
        # total_shares 与 float_shares 约束
        if norm_ts is not None and norm_fs is not None and norm_ts < norm_fs:
            self._errors["total_shares"] = "ERR_TOTAL_LT_FLOAT"
        # 保存归一化值
        self._norm_price = norm_price
        self._norm_float_shares = norm_fs
        self._norm_market_cap = norm_mcap
        self._norm_total_shares = norm_ts
        # 保存回 name/symbol（标准化）
        self._name = name
        self._symbol = symbol

    # ------------- Public API -------------
    def get_view(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "fields": {
                    "name": self._name,
                    "symbol": self._symbol,
                    "initial_price": self._initial_price,
                    "float_shares": self._float_shares,
                    "market_cap": self._market_cap,
                    "total_shares": self._total_shares,
                },
                "normalized": {
                    "initial_price": self._norm_price,
                    "float_shares": self._norm_float_shares,
                    "market_cap": self._norm_market_cap,
                    "total_shares": self._norm_total_shares,
                },
                "derived": {
                    "field": self._derived_field,
                    "value": self._derived_value,
                    "original_missing": self._original_missing,
                },
                "errors": dict(self._errors),
                "is_valid": len(self._errors) == 0,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def submit(self) -> bool:
        with self._lock:
            # 再次校验
            self._recompute()
            if self._errors:
                self._last_error = "ERR_FORM_INVALID"
                return False
            missing = self._original_missing
            name = self._name
            symbol = self._symbol
            price = self._norm_price
            fs = self._norm_float_shares
            mcap = self._norm_market_cap
            ts = self._norm_total_shares if self._norm_total_shares is not None else fs
        # 构造提交参数：保持“原本留空”的字段为 None
        submit_price = None if missing == "initial_price" else price
        submit_fs = None if missing == "float_shares" else fs
        submit_mcap = None if missing == "market_cap" else mcap
        try:
            payload = self._ctl.create_instrument(
                name=name,
                symbol=symbol,
                initial_price=submit_price,
                float_shares=submit_fs,
                market_cap=submit_mcap,
                total_shares=ts,
                price_step=self._price_step,
            )
            with self._lock:
                self._last_result = payload
                self._last_error = None
            metrics.inc("create_instrument_dialog_submit")
            return True
        except Exception:  # noqa: BLE001
            with self._lock:
                self._last_error = "ERR_SUBMIT_FAILED"
            metrics.inc("create_instrument_dialog_error")
            return False


# 可选：注册到面板注册表（保持与其他对话框一致的用法）
from app.panels import replace_panel  # noqa: E402

def register_create_instrument_dialog(controller: MarketController):
    replace_panel("create_instrument", lambda: CreateInstrumentDialog(controller), title="CreateInstrument", meta={"i18n_key": "dialog.create_instrument"})
