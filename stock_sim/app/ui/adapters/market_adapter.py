"""MarketPanelAdapter & SymbolDetailAdapter (R2 partial, scaffolding for R12,R13,R14)

功能概要:
- 左侧: 自选(symbols) 列表 (QListWidget)
- 右侧: 详情区 (当前 symbol 基本字段 + 占位 K 线/盘口/逐笔)
- 选择列表项 -> 调用 logic.select_symbol(symbol) 并刷新详情
- refresh(): 从 MarketPanel.get_view() 读取 watchlist & selected; detail_view() 读取详情

限制:
- 不绘制真实图表: 使用纯文本占位 (后续接入轻量绘图库)
- 不做指标/逐笔真实渲染: 预留 label 容器
- 不做性能优化: 后续任务添加节流
"""
from __future__ import annotations
from typing import Any, Dict, Optional, List
import os
import threading
import time  # 新增：节流

_DETAIL_ENABLE_CHART = os.environ.get("STOCKSIM_DETAIL_ENABLE_CHART", "1").lower() in ("1", "true", "yes", "on")
_DETAIL_ENABLE_ORDER_BOOK = os.environ.get("STOCKSIM_DETAIL_ENABLE_ORDER_BOOK", "1").lower() in ("1", "true", "yes", "on")
_CHART_STAGE = os.environ.get("STOCKSIM_CHART_STAGE", "candles").strip().lower()
if _CHART_STAGE not in ("plot-only", "line", "candles"):
    _CHART_STAGE = "candles"

from .base_adapter import PanelAdapter
from .runtime_mode import ui_runtime_enabled
from app.services.trading_service import SubmitOrderRequest, TradingService
from app.panels.market.dialog import CreateInstrumentDialog, suggest_next_symbol  # 新增：逻辑对话框
from infra.event_bus import event_bus  # 新增：回退订阅
try:
    from app.event_bridge import on_trade_executed, subscribe_topic  # type: ignore
except Exception:  # pragma: no cover
    def on_trade_executed(handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe("trade.executed", handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe("trade.executed", handler)
    def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe(topic, handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe(topic, handler)

# 显式双总线订阅，避免 app/runtime 导入路径导致的消息丢失。

FRONTEND_SNAPSHOT_BATCH_TOPIC = "frontend.snapshot.batch"  # type: ignore
# UI 桥接：打开独立符号页面 + 兜底打开指定面板
try:
    from app.ui.ui_refresh import open_symbol_page  # type: ignore
except Exception:  # pragma: no cover
    open_symbol_page = None  # type: ignore
try:
    from app.ui.ui_refresh import open_panel as _open_panel  # type: ignore
except Exception:  # pragma: no cover
    _open_panel = None  # type: ignore
# Qt 导入（默认走 headless-safe；仅在显式 real UI 模式下启用真实 Qt）
if ui_runtime_enabled():
    try:
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel, QFrame, QTableWidget, QTableWidgetItem,
            QDialog, QLineEdit, QPushButton, QFormLayout
        )  # type: ignore
        from PySide6.QtCore import Qt, QRectF, QPointF  # type: ignore
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush  # type: ignore
    except Exception:  # pragma: no cover
        ui_runtime = False
    else:
        ui_runtime = True
else:
    ui_runtime = False

if not ui_runtime:
    class _HeadlessRoot:
        pass
    class _DummySignal:  # type: ignore
        def connect(self, *_): pass
    class QWidget:  # type: ignore
        def __init__(self, *_, **__): pass
    class QListWidget:  # type: ignore
        def __init__(self):
            self._items: List[str] = []
            self._current_row = -1
            self.itemClicked = _DummySignal()
            self.itemDoubleClicked = _DummySignal()
        def clear(self): self._items.clear()
        def addItem(self, text): self._items.append(text)
        def currentItem(self):
            if 0 <= self._current_row < len(self._items):
                return _Item(self._items[self._current_row])
            return None
        def setCurrentRow(self, r): self._current_row = r
    class _Item:  # type: ignore
        def __init__(self, text): self._text = text
        def text(self): return self._text
    class QLabel:  # type: ignore
        def __init__(self, text=""): self._text=text
        def setText(self, t): self._text=t
    class QVBoxLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addWidget(self, *_): pass
        def addLayout(self, *_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addWidget(self, *_): pass
        def addLayout(self, *_): pass
    class QFormLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addRow(self, *_): pass
    class QFrame:  # type: ignore
        PanelShape = None
    class QTableWidget:  # type: ignore
        def __init__(self, *_, **__): pass
        def setColumnCount(self, n): pass
        def setHorizontalHeaderLabels(self, labels): pass
        def setRowCount(self, n): pass
        def setItem(self, r,c,item): pass
    class QTableWidgetItem:  # type: ignore
        def __init__(self, text=""): self._text=text
    class QDialog:  # type: ignore
        def __init__(self, *_, **__): pass
        def exec(self): return 0
    class QLineEdit:  # type: ignore
        def __init__(self, text=""): self._text=text
        def text(self): return self._text
        def setText(self, t): self._text=t
        @property
        def textChanged(self): return _DummySignal()
    class QPushButton:  # type: ignore
        def __init__(self, text=""): self._text=text; self.clicked=_DummySignal()
        def setEnabled(self, *_): pass
    class Qt:  # type: ignore
        AlignCenter = 0
        DashLine = 0
        NoPen = 0
    class QRectF:  # type: ignore
        def __init__(self, *_, **__): pass
    class QPointF:  # type: ignore
        def __init__(self, *_, **__): pass
    class QColor:  # type: ignore
        def __init__(self, *_, **__): pass
    class QPainter:  # type: ignore
        Antialiasing = 0
    class QPainterPath:  # type: ignore
        def __init__(self, *_, **__): pass
    class QPen:  # type: ignore
        def __init__(self, *_, **__): pass
    class QBrush:  # type: ignore
        def __init__(self, *_, **__): pass

# pyqtgraph（可选）
try:  # pragma: no cover
    import pyqtgraph as pg  # type: ignore
    from pyqtgraph import GraphicsLayoutWidget  # type: ignore
    from pyqtgraph import AxisItem, InfiniteLine, ViewBox  # type: ignore
except Exception:  # pragma: no cover
    pg = None  # type: ignore
    class GraphicsLayoutWidget:  # type: ignore
        def __init__(self, *_, **__): pass
        def addPlot(self, *_, **__): return _Plot()
    class _Plot:  # type: ignore
        def clear(self): pass
        def addItem(self, *_ , **__): pass
        def setLabel(self, *_ , **__): pass
        def showGrid(self, *_ , **__): pass
    class AxisItem:  # type: ignore
        def __init__(self, *_, **__): pass
    class InfiniteLine:  # type: ignore
        def __init__(self, *_, **__): pass
    class ViewBox:  # type: ignore
        def __init__(self, *_, **__): pass


class _BarAxisItem(AxisItem):
    def tickStrings(self, values, scale, spacing):  # type: ignore[override]
        labels = []
        for value in values:
            try:
                ivalue = int(round(float(value)))
            except Exception:
                labels.append("")
                continue
            if abs(float(value) - ivalue) <= 1e-6 and ivalue >= 0:
                labels.append(str(ivalue))
            else:
                labels.append("")
        return labels


class _BoundedViewBox(ViewBox):
    def __init__(self, *args, **kwargs):
        if pg is not None:
            kwargs.setdefault("enableMenu", False)
        super().__init__(*args, **kwargs)
        self._bounds = {
            "x_min": 0.0,
            "x_max": 1.0,
            "y_min": 0.0,
            "y_max": 1.0,
            "min_x_range": 1e-6,
            "max_x_range": 1.0,
            "min_y_range": 1e-6,
            "max_y_range": 1.0,
        }
        self._clamping = False

    def set_bounds(
        self,
        *,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        min_x_range: float,
        max_x_range: float,
        min_y_range: float,
        max_y_range: float,
    ) -> None:
        self._bounds = {
            "x_min": float(x_min),
            "x_max": float(max(x_max, x_min)),
            "y_min": float(y_min),
            "y_max": float(max(y_max, y_min)),
            "min_x_range": float(max(min_x_range, 1e-9)),
            "max_x_range": float(max(max_x_range, min_x_range, 1e-9)),
            "min_y_range": float(max(min_y_range, 1e-9)),
            "max_y_range": float(max(max_y_range, min_y_range, 1e-9)),
        }
        self._clamp_view()

    def wheelEvent(self, ev, axis=None):  # type: ignore[override]
        try:
            super().wheelEvent(ev, axis=axis)
        finally:
            self._clamp_view()

    def mouseDragEvent(self, ev, axis=None):  # type: ignore[override]
        try:
            super().mouseDragEvent(ev, axis=axis)
        finally:
            self._clamp_view()

    def _clamp_view(self) -> None:
        if self._clamping or not hasattr(self, "viewRange"):
            return
        try:
            self._clamping = True
            xr, yr = self.viewRange()
            x0, x1 = float(xr[0]), float(xr[1])
            y0, y1 = float(yr[0]), float(yr[1])
            x0, x1 = self._clamp_axis(x0, x1, "x")
            y0, y1 = self._clamp_axis(y0, y1, "y")
            if hasattr(self, "setRange"):
                self.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.0, disableAutoRange=True)
        except Exception:
            pass
        finally:
            self._clamping = False

    def _clamp_axis(self, low: float, high: float, axis: str) -> tuple[float, float]:
        axis_low = self._bounds[f"{axis}_min"]
        axis_high = self._bounds[f"{axis}_max"]
        min_range = self._bounds[f"min_{axis}_range"]
        max_range = self._bounds[f"max_{axis}_range"]
        width = max(float(high - low), min_range)
        width = min(width, max_range, max(axis_high - axis_low, min_range))
        if low < axis_low:
            low = axis_low
            high = low + width
        if high > axis_high:
            high = axis_high
            low = high - width
        if low < axis_low:
            low = axis_low
            high = min(axis_high, low + width)
        if high > axis_high:
            high = axis_high
            low = max(axis_low, high - width)
        return low, high


class _SafeCandlestickItem:
    def __init__(self, candles, width: float):
        self._candles = candles
        self._width = max(float(width), 0.1)
        self._item = None
        if pg is not None:
            try:
                from PySide6.QtGui import QPicture, QPainter  # type: ignore
                from PySide6.QtCore import QRectF, QPointF  # type: ignore
                class _Candles(pg.GraphicsObject):  # type: ignore[attr-defined]
                    def __init__(self, data):
                        super().__init__()
                        self._data = data
                        self._picture = QPicture()
                        p = QPainter(self._picture)
                        try:
                            for x, o, h, l, c in data:
                                color = (244, 67, 54) if c >= o else (76, 175, 80)
                                pen = pg.mkPen(color=color, width=1)
                                brush = pg.mkBrush(color)
                                p.setPen(pen)
                                p.drawLine(QPointF(float(x), float(l)), QPointF(float(x), float(h)))
                                y0 = float(min(o, c))
                                height = float(abs(c - o))
                                if height < 1e-9:
                                    p.drawLine(QPointF(float(x) - (width / 2.0), float(o)), QPointF(float(x) + (width / 2.0), float(c)))
                                else:
                                    p.setBrush(brush)
                                    p.drawRect(QRectF(float(x) - (width / 2.0), y0, width, height))
                        finally:
                            p.end()
                    def paint(self, painter, *args):
                        painter.drawPicture(0, 0, self._picture)
                    def boundingRect(self):
                        return self._picture.boundingRect()
                self._item = _Candles(candles)
            except Exception:
                self._item = None
    def graphics_item(self):
        return self._item


class _DetailChartWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._geometry: Dict[str, Any] = {}
        self._empty_text = "K: no data"
        try:
            if hasattr(self, "setMinimumHeight"):
                self.setMinimumHeight(260)  # type: ignore[attr-defined]
        except Exception:
            pass

    def set_chart_geometry(
        self,
        geometry: Dict[str, Any],
        *,
        empty_text: Optional[str] = None,
    ) -> None:
        self._geometry = dict(geometry or {})
        if empty_text is not None:
            self._empty_text = str(empty_text)
        try:
            if hasattr(self, "update"):
                self.update()  # type: ignore[attr-defined]
        except Exception:
            pass

    def clear_chart(self, text: str) -> None:
        self._geometry = {}
        self._empty_text = str(text or "K: no data")
        try:
            if hasattr(self, "update"):
                self.update()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _map_x(self, index: float, left: float, width: float, bars: int) -> float:
        if bars <= 1:
            return left + (width / 2.0)
        return left + (float(index) / float(max(bars - 1, 1))) * width

    def _map_y(self, price: float, top: float, height: float, y_min: float, y_max: float) -> float:
        span = max(float(y_max - y_min), 1e-9)
        normalized = (float(price) - y_min) / span
        normalized = min(max(normalized, 0.0), 1.0)
        return top + height - (normalized * height)

    def paintEvent(self, event):  # type: ignore[override]
        if not ui_runtime_enabled():
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            full = self.rect()
            painter.fillRect(full, QColor(7, 10, 14))
            plot = full.adjusted(52, 16, -18, -34)
            if plot.width() <= 24 or plot.height() <= 24:
                return

            painter.setPen(QPen(QColor(58, 68, 80), 1))
            painter.drawRect(plot)
            grid_pen = QPen(QColor(44, 52, 62), 1)
            grid_pen.setCosmetic(True)
            painter.setPen(grid_pen)
            for row in range(1, 6):
                y = plot.top() + (plot.height() * row / 6.0)
                painter.drawLine(plot.left(), int(round(y)), plot.right(), int(round(y)))

            candles = list(self._geometry.get("candles") or [])
            bars = int(self._geometry.get("n") or len(candles) or 0)
            if bars <= 0:
                painter.setPen(QPen(QColor(194, 201, 211), 1))
                painter.drawText(plot, Qt.AlignCenter, self._empty_text)
                return

            for column in range(bars):
                x = self._map_x(column, float(plot.left()), float(plot.width()), bars)
                painter.drawLine(int(round(x)), plot.top(), int(round(x)), plot.bottom())

            y_min = float(self._geometry.get("y_min") or 0.0)
            y_max = float(self._geometry.get("y_max") or 1.0)
            close = list(self._geometry.get("close") or [])
            ref_price = self._geometry.get("ref_price")

            painter.setPen(QPen(QColor(144, 156, 170), 1))
            for row in range(0, 6):
                value = y_max - ((y_max - y_min) * row / 5.0)
                y = plot.top() + (plot.height() * row / 5.0)
                painter.drawText(6, int(round(y)) + 5, f"{value:.2f}")

            if ref_price is not None:
                try:
                    ref_y = self._map_y(float(ref_price), float(plot.top()), float(plot.height()), y_min, y_max)
                except Exception:
                    ref_y = None
                if ref_y is not None:
                    ref_pen = QPen(QColor(112, 124, 138), 1)
                    ref_pen.setStyle(Qt.DashLine)
                    painter.setPen(ref_pen)
                    painter.drawLine(plot.left(), int(round(ref_y)), plot.right(), int(round(ref_y)))

            body_width = max(min(float(plot.width()) / max(float(bars), 1.0) * 0.55, 18.0), 6.0)
            up_pen = QPen(QColor(255, 109, 97), 2)
            down_pen = QPen(QColor(87, 214, 132), 2)
            up_brush = QBrush(QColor(255, 109, 97))
            down_brush = QBrush(QColor(87, 214, 132))
            line_pen = QPen(QColor(0, 220, 255), 3)
            line_pen.setCosmetic(True)

            path = QPainterPath()
            first_point = True
            for index, candle in enumerate(candles):
                try:
                    _, open_price, high_price, low_price, close_price = candle
                    x = self._map_x(index, float(plot.left()), float(plot.width()), bars)
                    high_y = self._map_y(float(high_price), float(plot.top()), float(plot.height()), y_min, y_max)
                    low_y = self._map_y(float(low_price), float(plot.top()), float(plot.height()), y_min, y_max)
                    open_y = self._map_y(float(open_price), float(plot.top()), float(plot.height()), y_min, y_max)
                    close_y = self._map_y(float(close_price), float(plot.top()), float(plot.height()), y_min, y_max)
                except Exception:
                    continue

                rising = float(close_price) >= float(open_price)
                painter.setPen(up_pen if rising else down_pen)
                painter.drawLine(QPointF(float(x), float(high_y)), QPointF(float(x), float(low_y)))

                body_top = min(open_y, close_y)
                body_height = max(abs(close_y - open_y), 3.0)
                body_rect = QRectF(float(x) - (body_width / 2.0), float(body_top), body_width, float(body_height))
                painter.setBrush(up_brush if rising else down_brush)
                painter.drawRect(body_rect)

                if index < len(close):
                    close_y_line = self._map_y(float(close[index]), float(plot.top()), float(plot.height()), y_min, y_max)
                    point = QPointF(float(x), float(close_y_line))
                    if first_point:
                        path.moveTo(point)
                        first_point = False
                    else:
                        path.lineTo(point)

            painter.setPen(line_pen)
            painter.setBrush(QBrush(QColor(0, 220, 255)))
            painter.drawPath(path)
            for index in range(min(len(close), bars)):
                x = self._map_x(index, float(plot.left()), float(plot.width()), bars)
                y = self._map_y(float(close[index]), float(plot.top()), float(plot.height()), y_min, y_max)
                painter.drawEllipse(QPointF(float(x), float(y)), 3.5, 3.5)

            painter.setPen(QPen(QColor(144, 156, 170), 1))
            step = max(int(round(bars / 6.0)), 1)
            for column in range(0, bars, step):
                x = self._map_x(column, float(plot.left()), float(plot.width()), bars)
                painter.drawText(int(round(x)) - 6, full.bottom() - 10, str(column))
            painter.drawText(plot.center().x() - 14, full.bottom() - 10, "Bars")
        finally:
            painter.end()


def _extract_trade_payload(payload: Any) -> Dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    trade = payload.get("trade") or payload
    return trade if isinstance(trade, dict) else None


def _subscribe_trade_topics(handler):
    return on_trade_executed(handler, async_mode=False)


def _build_candle_plot_geometry(
    series: Dict[str, List[float]],
    chart_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    open_ = list(series.get('open') or [])
    high = list(series.get('high') or [])
    low = list(series.get('low') or [])
    close = list(series.get('close') or [])
    n = min(len(open_), len(high), len(low), len(close))
    if n <= 0:
        return {
            "n": 0,
            "x": [],
            "candles": [],
            "body_width": 0.7,
            "x_min": -0.5,
            "x_max": 0.5,
            "y_min": 0.0,
            "y_max": 1.0,
            "min_x_range": 1.0,
            "max_x_range": 1.0,
            "min_y_range": 0.01,
            "max_y_range": 1.0,
            "ref_price": None,
        }
    meta = dict(chart_meta or {})
    ref_price = meta.get('reference_price')
    price_step = max(float(meta.get('price_step') or 0.01), 0.0001)
    x = [float(i) for i in range(n)]
    visible_high = max(float(v) for v in high[:n])
    visible_low = min(float(v) for v in low[:n])
    if ref_price is not None:
        try:
            ref = float(ref_price)
        except Exception:
            ref = None
        else:
            visible_high = max(visible_high, ref)
            visible_low = min(visible_low, ref)
            ref_price = ref
    span = max(visible_high - visible_low, price_step * 4.0)
    pad = max(span * 0.08, price_step * 2.0)
    y_min = max(visible_low - pad, price_step * 0.5)
    y_max = visible_high + pad
    body_width = 0.7 if n > 1 else 0.45
    x_min = -0.5
    x_max = max(float(n) - 0.5, 0.5)
    max_x_range = max(float(n), 1.0)
    max_y_range = max(y_max - y_min, price_step * 8.0)
    candles = [(x[i], open_[i], high[i], low[i], close[i]) for i in range(n)]
    return {
        "n": n,
        "x": x,
        "candles": candles,
        "body_width": body_width,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "min_x_range": 1.0,
        "max_x_range": max_x_range,
        "min_y_range": price_step,
        "max_y_range": max_y_range,
        "ref_price": ref_price,
        "close": close[:n],
    }


def _resolve_detail_status(
    detail_health: Dict[str, Any],
    key: str,
    meta: Dict[str, Any],
    default: str,
) -> str:
    return str(detail_health.get(key) or meta.get("status") or default)


def _build_detail_snapshot_label_text(detail: Dict[str, Any], *, bars_count: int) -> str:
    snapshot = detail.get("snapshot") or {}
    snapshot_meta = detail.get("snapshot_meta") or {}
    order_book_meta = detail.get("order_book_meta") or {}
    detail_health = detail.get("detail_health") or {}
    series_meta = detail.get("series_meta") or {}
    last = snapshot.get("last") if isinstance(snapshot, dict) else None
    overall = str(detail_health.get("overall") or "unknown")
    series_status = _resolve_detail_status(detail_health, "series_status", series_meta, "missing")
    if bool(series_meta.get("placeholder")):
        series_status = "placeholder"
    snapshot_status = _resolve_detail_status(detail_health, "snapshot_status", snapshot_meta, "missing")
    order_book_status = _resolve_detail_status(detail_health, "order_book_status", order_book_meta, "missing")
    snapshot_age_ms = snapshot_meta.get("age_ms")
    snapshot_age_note = f" | snap_age_ms={snapshot_age_ms}" if snapshot_age_ms is not None else ""
    return (
        f"last={last} | bars={bars_count} | state={overall} | "
        f"snap={snapshot_status} | book={order_book_status} | series={series_status}{snapshot_age_note}"
    )


def _build_detail_debug_label_text(
    detail: Dict[str, Any],
    *,
    chart_mode: str,
    symbol: str,
    bars_count: int,
) -> str:
    chart_meta = detail.get("chart_meta") or {}
    detail_health = detail.get("detail_health") or {}
    trades_meta = detail.get("trades_meta") or {}
    indicators_meta = detail.get("indicators_meta") or {}
    holdings_meta = detail.get("holdings_meta") or {}
    snapshot_meta = detail.get("snapshot_meta") or {}
    order_book_meta = detail.get("order_book_meta") or {}
    series_meta = detail.get("series_meta") or {}
    holdings = detail.get("holdings") or None

    trades_status = _resolve_detail_status(detail_health, "trades_status", trades_meta, "empty")
    indicators_status = _resolve_detail_status(detail_health, "indicators_status", indicators_meta, "missing")
    holdings_status = _resolve_detail_status(detail_health, "holdings_status", holdings_meta, "unknown")
    holdings_tag = "auth" if bool(holdings_meta.get("authoritative")) else "non-auth"
    active_run_id = str(chart_meta.get("active_run_id") or "").strip()
    history_scope = str(chart_meta.get("history_scope_resolved") or chart_meta.get("history_scope") or "unknown").strip()
    history_requested = str(chart_meta.get("history_scope_requested") or "unknown").strip()
    series_source = str(series_meta.get("source") or chart_meta.get("series_source") or "unknown").strip()
    snapshot_freshness = str(snapshot_meta.get("freshness_model") or "unknown").strip()
    order_book_freshness = str(order_book_meta.get("freshness_model") or "unknown").strip()
    run_note = f" run={active_run_id}" if active_run_id else " run=none"
    holdings_note = ""
    try:
        if isinstance(holdings, dict) and holdings.get("placeholder"):
            holdings_note = " | holdings_ui=placeholder"
    except Exception:
        holdings_note = ""
    series_note = " | series_ui=placeholder" if bool(series_meta.get("placeholder")) else ""
    return (
        f"detail debug: mode={chart_mode} symbol={symbol} bars={bars_count} "
        f"trades={trades_status} indicators={indicators_status} "
        f"holdings={holdings_status}/{holdings_tag} history={history_scope} "
        f"requested={history_requested} source={series_source} "
        f"snap_model={snapshot_freshness} book_model={order_book_freshness}"
        f"{run_note}{holdings_note}{series_note}"
    )


def _build_chart_empty_text(detail: Dict[str, Any]) -> str:
    detail_health = detail.get("detail_health") or {}
    series_meta = detail.get("series_meta") or {}
    series_status = _resolve_detail_status(detail_health, "series_status", series_meta, "missing")
    if series_status == "placeholder":
        return "K: synthetic placeholder hidden"
    if series_status == "missing":
        return "K: no runtime history"
    if series_status == "stale":
        return "K: stale history"
    return "K: no data"


def _build_symbol_label_text(symbol: Any) -> str:
    return f"symbol: {symbol or '-'}"


def _count_render_bars(series: Any) -> int:
    try:
        if isinstance(series, dict):
            return len(series.get("close") or [])
    except Exception:
        return 0
    return 0


def _build_order_book_rows(order_book: Any, *, depth: int = 5) -> List[tuple[str, str, str]]:
    if not isinstance(order_book, dict):
        return []
    bids = list(order_book.get("bids") or [])
    asks = list(order_book.get("asks") or [])
    rows = min(max(len(bids), len(asks)), max(int(depth), 0))
    rendered: List[tuple[str, str, str]] = []
    for i in range(rows):
        if i < len(bids):
            bp, bq = bids[i]
            rendered.append(("BID", str(bp), str(bq)))
        if i < len(asks):
            ap, aq = asks[i]
            rendered.append(("ASK", str(ap), str(aq)))
    return rendered


class SymbolDetailAdapter:
    """详情适配: 展示 snapshot / order_book / series K 线 / 持仓饼图。"""
    def __init__(self):
        self._symbol_label: Optional[Any] = None
        self._snapshot_label: Optional[Any] = None
        self._debug_label: Optional[Any] = None
        self._order_book_table: Optional[Any] = None
        self._chart_widget: Optional[Any] = None
        self._chart_plot: Optional[Any] = None
        self._chart_view_box: Optional[Any] = None
        self._chart_fallback_label: Optional[Any] = None
        self._root: Optional[Any] = None

    def _apply_order_book_table(self, rows: List[tuple[str, str, str]]) -> None:
        if self._order_book_table is None:
            return
        try:
            self._order_book_table.setRowCount(len(rows))  # type: ignore
            for row_idx, (side, price, qty) in enumerate(rows):
                self._order_book_table.setItem(row_idx, 0, QTableWidgetItem(side))  # type: ignore
                self._order_book_table.setItem(row_idx, 1, QTableWidgetItem(price))  # type: ignore
                self._order_book_table.setItem(row_idx, 2, QTableWidgetItem(qty))  # type: ignore
        except Exception:
            pass

    def _plot_close_line(self, x: List[float], close: List[float]) -> None:
        if self._chart_plot is None or not x or not close:
            return
        try:
            if hasattr(self._chart_plot, 'plot'):
                self._chart_plot.plot(
                    x,
                    close,
                    pen=pg.mkPen((0, 220, 255), width=3),
                    symbol='o',
                    symbolSize=6,
                    symbolBrush=pg.mkBrush((0, 220, 255)),
                    symbolPen=pg.mkPen((0, 220, 255), width=1),
                )  # type: ignore[attr-defined]
        except Exception:
            pass

    def widget(self):  # 创建并返回根组件
        if self._root is not None:
            return self._root
        root = _HeadlessRoot() if not ui_runtime_enabled() else QWidget()  # type: ignore
        try:
            layout = QVBoxLayout(root)  # type: ignore
            try:
                if hasattr(layout, 'setContentsMargins'):
                    layout.setContentsMargins(8, 8, 8, 8)
                if hasattr(layout, 'setSpacing'):
                    layout.setSpacing(10)
            except Exception:
                pass
            # 顶部 symbol / snapshot 简要
            self._symbol_label = QLabel("symbol: -")  # type: ignore
            layout.addWidget(self._symbol_label)  # type: ignore
            self._snapshot_label = QLabel("snapshot: -")  # type: ignore
            layout.addWidget(self._snapshot_label)  # type: ignore
            self._debug_label = QLabel("detail debug: init")  # type: ignore
            layout.addWidget(self._debug_label)  # type: ignore
            # K 线
            chart_ok = False
            if _DETAIL_ENABLE_CHART and ui_runtime_enabled():
                try:
                    self._chart_widget = _DetailChartWidget()  # type: ignore
                    self._chart_plot = None
                    self._chart_view_box = None
                    layout.addWidget(self._chart_widget, 1)  # type: ignore
                    chart_ok = True
                except Exception:
                    self._chart_widget = None
                    self._chart_plot = None
            if not chart_ok:
                fallback_text = "K: disabled" if not _DETAIL_ENABLE_CHART else "K: (chart unavailable)"
                self._chart_fallback_label = QLabel(fallback_text)  # type: ignore
                layout.addWidget(self._chart_fallback_label)  # type: ignore
            # 盘口表 (side, price, qty)
            if _DETAIL_ENABLE_ORDER_BOOK:
                self._order_book_table = QTableWidget(0, 3)  # type: ignore
                self._order_book_table.setColumnCount(3)  # type: ignore
                self._order_book_table.setHorizontalHeaderLabels(["Side","Price","Qty"])  # type: ignore
                try:
                    if hasattr(self._order_book_table, 'setMinimumHeight'):
                        self._order_book_table.setMinimumHeight(180)  # type: ignore[attr-defined]
                except Exception:
                    pass
                layout.addWidget(self._order_book_table)  # type: ignore
            else:
                self._order_book_table = None
                layout.addWidget(QLabel("OrderBook: disabled"))  # type: ignore
            # 持仓饼图
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    def _plot_candles(self, series: Dict[str, List[float]], chart_meta: Optional[Dict[str, Any]] = None):
        geometry = _build_candle_plot_geometry(series, chart_meta)
        n = int(geometry.get("n") or 0)
        if hasattr(self._chart_widget, "set_chart_geometry"):
            try:
                self._chart_widget.set_chart_geometry(geometry, empty_text="K: no data")  # type: ignore[attr-defined]
            except Exception:
                pass
        if self._chart_plot is None:
            if self._chart_fallback_label is not None:
                try:
                    self._chart_fallback_label.setText(f"K: {n} bars")  # type: ignore
                except Exception:
                    pass
            if hasattr(self._chart_widget, "set_chart_geometry"):
                return
            return
        try:
            self._chart_plot.clear()
        except Exception:
            pass
        if n <= 0:
            return
        x = list(geometry.get("x") or [])
        close = list(geometry.get("close") or [])
        candles = list(geometry.get("candles") or [])
        ref_price = geometry.get("ref_price")
        x_min = float(geometry.get("x_min") or -0.5)
        x_max = float(geometry.get("x_max") or 0.5)
        y_min = float(geometry.get("y_min") or 0.0)
        y_max = float(geometry.get("y_max") or 1.0)
        min_x_range = float(geometry.get("min_x_range") or 1.0)
        max_x_range = float(geometry.get("max_x_range") or 1.0)
        min_y_range = float(geometry.get("min_y_range") or 0.01)
        max_y_range = float(geometry.get("max_y_range") or 1.0)
        body_width = float(geometry.get("body_width") or 0.7)
        try:
            self._chart_plot.setLabel('bottom', 'Bars')
            self._chart_plot.setLabel('left', 'Price')
            if hasattr(self._chart_plot, 'showGrid'):
                self._chart_plot.showGrid(x=True, y=True, alpha=0.25)
            if hasattr(self._chart_plot, 'setLimits'):
                self._chart_plot.setLimits(
                    xMin=x_min,
                    xMax=x_max,
                    yMin=y_min,
                    yMax=y_max,
                    minXRange=min_x_range,
                    maxXRange=max_x_range,
                    minYRange=min_y_range,
                    maxYRange=max_y_range,
                )
            if self._chart_view_box is not None and hasattr(self._chart_view_box, 'set_bounds'):
                self._chart_view_box.set_bounds(
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    min_x_range=min_x_range,
                    max_x_range=max_x_range,
                    min_y_range=min_y_range,
                    max_y_range=max_y_range,
                )
            if hasattr(self._chart_plot, 'setXRange'):
                self._chart_plot.setXRange(x_min, x_max, padding=0.0)
            if hasattr(self._chart_plot, 'setYRange'):
                self._chart_plot.setYRange(y_min, y_max, padding=0.0)
            if hasattr(self._chart_plot, 'disableAutoRange'):
                self._chart_plot.disableAutoRange()  # type: ignore[attr-defined]
        except Exception:
            pass
        # 分阶段恢复图表，逐步逼近崩点
        if _CHART_STAGE == 'plot-only':
            return
        try:
            if ref_price:
                self._chart_plot.addItem(InfiniteLine(pos=float(ref_price), angle=0, pen=pg.mkPen((160, 160, 160), width=1)))  # type: ignore[arg-type]
        except Exception:
            pass
        if _CHART_STAGE == 'line':
            self._plot_close_line(x, close)
            if self._chart_fallback_label is not None:
                try:
                    self._chart_fallback_label.setText(f"K(line): {n} bars")  # type: ignore
                except Exception:
                    pass
            return
        if _CHART_STAGE == 'candles':
            rendered_candles = False
            try:
                safe_item = _SafeCandlestickItem(candles, width=body_width).graphics_item()
                if safe_item is not None:
                    self._chart_plot.addItem(safe_item)
                    rendered_candles = True
            except Exception:
                pass
            # Always overlay the close trace so live movement stays visible even
            # if the candlestick graphics item fails to paint clearly.
            self._plot_close_line(x, close)
            if rendered_candles:
                return

        start_angle = 0  # Qt 单位: 1/16 度

    def apply_detail(self, detail: Dict[str, Any]):
        if not isinstance(detail, dict):
            return
        symbol = detail.get('symbol') or '-'
        series = detail.get('series') or None
        series_meta = detail.get('series_meta') or {}
        chart_meta = detail.get('chart_meta') or {}
        series_placeholder = bool(series_meta.get('placeholder'))
        render_series = None if series_placeholder else series
        ob = detail.get('order_book') or None
        order_book_rows = _build_order_book_rows(ob, depth=5)
        # 顶部标签
        if self._symbol_label is not None:
            try: self._symbol_label.setText(_build_symbol_label_text(symbol))  # type: ignore
            except Exception: pass
        chart_mode = 'qt-canvas' if hasattr(self._chart_widget, "set_chart_geometry") else ('pyqtgraph' if self._chart_plot is not None else 'fallback')
        bars_count = _count_render_bars(render_series)
        if self._snapshot_label is not None:
            try: self._snapshot_label.setText(_build_detail_snapshot_label_text(detail, bars_count=bars_count))  # type: ignore
            except Exception: pass
        if self._debug_label is not None:
            try: self._debug_label.setText(
                _build_detail_debug_label_text(
                    detail,
                    chart_mode=chart_mode,
                    symbol=str(symbol),
                    bars_count=bars_count,
                )
            )  # type: ignore
            except Exception: pass
        # K 线
        if _DETAIL_ENABLE_CHART:
            if render_series:
                self._plot_candles(render_series, chart_meta)
                try:
                    if self._chart_fallback_label is not None:
                        self._chart_fallback_label.setText(f"K: {len(render_series.get('close') or [])} bars")  # type: ignore
                except Exception:
                    pass
            else:
                # 清空或占位
                if hasattr(self._chart_widget, "clear_chart"):
                    try:
                        self._chart_widget.clear_chart(_build_chart_empty_text(detail))  # type: ignore[attr-defined]
                    except Exception:
                        pass
                if self._chart_plot is not None:
                    try: self._chart_plot.clear()
                    except Exception: pass
                if self._chart_fallback_label is not None:
                    try:
                        self._chart_fallback_label.setText(_build_chart_empty_text(detail))  # type: ignore
                    except Exception: pass
        else:
            if self._chart_fallback_label is not None:
                try: self._chart_fallback_label.setText(f"K: disabled | bars: {bars_count}")  # type: ignore
                except Exception: pass
        # 饼图
            # 仅在 holdings 至少有可视化数据时绘制；
            # 对显式 placeholder / non-authoritative empty payload 保持空图，避免 UI 伪装成真实持仓分布。
        # 更新盘口表 (仅展示前 5 档)
        if _DETAIL_ENABLE_ORDER_BOOK and self._order_book_table is not None:
            self._apply_order_book_table(order_book_rows)
        # Trades（最多 10 条）保留原占位，不做强制要求


class MarketPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._watch_widget: Optional[Any] = None
        self._detail = SymbolDetailAdapter()
        self._root: Optional[Any] = None
        self._symbol_list: Optional[Any] = None
        self._selected_symbol: Optional[str] = None
        # 新增：创建按钮
        self._btn_create: Optional[Any] = None
        # 新增：取消订阅句柄
        self._cancel_instrument_created = None
        self._cancel_trade = None
        self._cancel_batch = None
        # 新增：clock 订阅取消句柄
        self._cancel_clock_state = None
        self._cancel_clock_tick = None
        # 新增：节流状态
        self._last_refresh_ts: float = 0.0
        self._throttle_sec: float = 0.2
        self._last_detail_refresh_ts: float = 0.0
        self._detail_throttle_sec: float = 0.5
        self._selection_generation: int = 0
        self._trade_ctl = TradingService()

    def _post_to_ui(self, cb) -> bool:
        if not ui_runtime_enabled():
            return False
        try:
            from PySide6.QtCore import QTimer  # type: ignore
            if getattr(self, "_root", None) is not None:
                try:
                    QTimer.singleShot(0, self._root, cb)  # type: ignore[arg-type]
                except Exception:
                    QTimer.singleShot(0, cb)
            else:
                QTimer.singleShot(0, cb)
            return True
        except Exception:
            return False

    def refresh(self):  # type: ignore[override]
        def _do():
            try:
                PanelAdapter.refresh(self)
            except Exception:
                pass
        if not self._post_to_ui(_do):
            _do()

    def bind(self, logic):  # type: ignore[override]
        super().bind(logic)
        try:
            self._detail.bind(logic)
        except Exception:
            pass
        try:
            loader = getattr(logic, "load_persisted_instruments", None)
            if callable(loader):
                loader()
        except Exception:
            pass
        return self

    def _create_widget(self):  # noqa: D401
        root = _HeadlessRoot() if not ui_runtime_enabled() else QWidget()  # type: ignore
        try:
            h = QHBoxLayout(root)  # type: ignore
            # 左侧：自选 + 顶部操作区
            left_v = QVBoxLayout()  # type: ignore
            # 操作条：创建标的按钮
            try:
                self._btn_create = QPushButton("Create Instrument")  # type: ignore
                def _on_create_clicked():
                    self._open_create_dialog()
                self._btn_create.clicked.connect(_on_create_clicked)  # type: ignore[attr-defined]
                left_v.addWidget(self._btn_create)  # type: ignore
            except Exception:
                pass
            # 自选列表
            self._symbol_list = QListWidget()  # type: ignore
            def _on_click(item):
                try:
                    sym = (item.text() or "").strip()  # type: ignore
                    self._handle_select(sym)
                except Exception:
                    pass
            try:
                self._symbol_list.itemClicked.connect(_on_click)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
            # 双击/激活 打开详情（有些平台把双击归为 activated）
            try:
                def _on_dbl(item):
                    try:
                        sym = (item.text() or "").strip()  # type: ignore
                        self._handle_select(sym)
                    except Exception:
                        pass
                self._symbol_list.itemDoubleClicked.connect(_on_dbl)  # type: ignore[attr-defined]
                # 额外接 itemActivated 兼容不同平台
                if hasattr(self._symbol_list, 'itemActivated'):
                    try:
                        self._symbol_list.itemActivated.connect(_on_dbl)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            left_v.addWidget(self._symbol_list)  # type: ignore
            h.addLayout(left_v)  # type: ignore
            # 右侧详情区
            detail_widget = self._detail.widget()
            h.addWidget(detail_widget)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        # 订阅 instrument-created 以刷新视图
        try:
            def _on_ic(_topic: str, _payload: Dict[str, Any]):
                try:
                    # 新标的加入关注列表；避免重复 add_symbol 造成重入链路过重
                    sym = None
                    try:
                        sym = (_payload or {}).get('symbol')
                    except Exception:
                        sym = None
                    if sym and self._logic is not None:
                        add = getattr(self._logic, 'add_symbol', None)
                        current_view = getattr(self._logic, 'get_view', None)
                        already_exists = False
                        if callable(current_view):
                            try:
                                view = current_view()
                                watch = ((view or {}).get('watchlist') or {}).get('symbols') or []
                                already_exists = sym in watch
                            except Exception:
                                already_exists = False
                        if callable(add) and not already_exists:
                            try:
                                add(sym)
                            except Exception:
                                pass
                    self.refresh()
                except Exception:
                    pass
            self._cancel_instrument_created = subscribe_topic("instrument-created", _on_ic, async_mode=False)
        except Exception:
            self._cancel_instrument_created = None
        # 新增：订阅 Trade 事件（仅当匹配当前选中 symbol 时，推给逻辑层）
        try:
            def _on_trade(_topic: str, payload: Dict[str, Any]):
                try:
                    trade = _extract_trade_payload(payload)
                    if not isinstance(trade, dict):
                        return
                    sym = str(trade.get('symbol') or '')
                    if not sym:
                        return
                    if self._selected_symbol and sym == self._selected_symbol and self._logic is not None:
                        add_trade = getattr(self._logic, 'add_trade', None)
                        if callable(add_trade):
                            try:
                                add_trade(trade)
                            except Exception:
                                pass
                        # 仅刷新详情（轻量），不改变主列表
                        self.refresh()
                except Exception:
                    pass
            self._cancel_trade = _subscribe_trade_topics(_on_trade)
        except Exception:
            self._cancel_trade = None
        # 新增：订阅前端批量快照并节流刷新
        try:
            def _on_batch(_topic: str, payload: Dict[str, Any]):
                try:
                    snapshots = []
                    if isinstance(payload, dict):
                        snapshots = payload.get("snapshots") or []
                    ctl = getattr(self._logic, "_ctl", None) if self._logic is not None else None
                    merge_batch = getattr(ctl, "merge_batch", None)
                    if callable(merge_batch) and snapshots:
                        try:
                            merge_batch(snapshots)
                        except Exception:
                            pass
                    now = time.time()
                    if (now - self._last_refresh_ts) >= self._throttle_sec:
                        self._last_refresh_ts = now
                        self.refresh()
                    else:
                        # 丢弃超频事件，保持 <=5Hz
                        pass
                except Exception:
                    pass
            self._cancel_batch = subscribe_topic(FRONTEND_SNAPSHOT_BATCH_TOPIC, _on_batch, async_mode=False)
        except Exception:
            self._cancel_batch = None
        # 新增：订阅时钟事件，驱动日 K 刷新
        try:
            def _on_clock(_topic: str, _payload: Dict[str, Any]):
                try:
                    if not self._selected_symbol or self._logic is None:
                        return
                    # 仅当 timeframe == '1d' 时刷新详情
                    dv = getattr(self._logic, 'detail_view', None)
                    tf = None
                    if callable(dv):
                        try:
                            v = dv()
                            if isinstance(v, dict):
                                tf = v.get('timeframe')
                        except Exception:
                            tf = None
                    if tf == '1d':
                        # 轻量刷新详情
                        self.refresh()
                except Exception:
                    pass
            self._cancel_clock_state = subscribe_topic("clock.state", _on_clock, async_mode=False)
            self._cancel_clock_tick = subscribe_topic("clock.tick", _on_clock, async_mode=False)
        except Exception:
            self._cancel_clock_state = None
            self._cancel_clock_tick = None
        return root

    def __del__(self):  # 释放订阅
        try:
            if callable(self._cancel_instrument_created):
                self._cancel_instrument_created()
        except Exception:
            pass
        try:
            if callable(self._cancel_trade):
                self._cancel_trade()
            elif isinstance(self._cancel_trade, list):
                for c in self._cancel_trade:
                    try:
                        if callable(c):
                            c()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if callable(self._cancel_batch):
                self._cancel_batch()
        except Exception:
            pass
        # 新增：clock 取消
        try:
            if callable(self._cancel_clock_state):
                self._cancel_clock_state()
        except Exception:
            pass
        try:
            if callable(self._cancel_clock_tick):
                self._cancel_clock_tick()
        except Exception:
            pass

    # 新增：打开创建标的对话框（Qt 有则弹窗；无则使用默认参数直接创建并加入关注）
    def _open_create_dialog(self):
        if ui_runtime_enabled():
            try:
                global QWidget, QVBoxLayout, QHBoxLayout, QDialog, QLineEdit, QPushButton, QFormLayout, QFrame, QLabel
                from PySide6.QtWidgets import (  # type: ignore
                    QWidget as _QWidget,
                    QVBoxLayout as _QVBoxLayout,
                    QHBoxLayout as _QHBoxLayout,
                    QDialog as _QDialog,
                    QLineEdit as _QLineEdit,
                    QPushButton as _QPushButton,
                    QFormLayout as _QFormLayout,
                    QFrame as _QFrame,
                    QLabel as _QLabel,
                )
                QWidget = _QWidget  # type: ignore
                QVBoxLayout = _QVBoxLayout  # type: ignore
                QHBoxLayout = _QHBoxLayout  # type: ignore
                QDialog = _QDialog  # type: ignore
                QLineEdit = _QLineEdit  # type: ignore
                QPushButton = _QPushButton  # type: ignore
                QFormLayout = _QFormLayout  # type: ignore
                QFrame = _QFrame  # type: ignore
                QLabel = _QLabel  # type: ignore
            except Exception:
                pass
        logic = self._logic
        if logic is None:
            return

        def _collect_existing_symbols() -> List[str]:
            symbols: List[str] = []
            current_view = getattr(logic, "get_view", None)
            if callable(current_view):
                try:
                    view = current_view()
                    symbols.extend(((view or {}).get("watchlist") or {}).get("symbols") or [])
                except Exception:
                    pass
            svc = getattr(logic, "_svc", None)
            subscribed_symbols = getattr(svc, "subscribed_symbols", None)
            if callable(subscribed_symbols):
                try:
                    symbols.extend(subscribed_symbols() or [])
                except Exception:
                    pass
            ctl = getattr(logic, "_ctl", None)
            list_snapshots = getattr(ctl, "list_snapshots", None)
            if callable(list_snapshots):
                try:
                    rows = (list_snapshots(page=1, page_size=5000, symbol_filter=None, sort_by="symbol") or {}).get("items") or []
                    for row in rows:
                        sym = getattr(row, "symbol", None)
                        if sym:
                            symbols.append(str(sym))
                except Exception:
                    pass
            return symbols

        default_sym = suggest_next_symbol(_collect_existing_symbols())

        def _format_market_cap(value: Any) -> str:
            try:
                number = float(value)
            except Exception:
                return "-"
            if abs(number - round(number)) < 1e-6:
                return f"{int(round(number)):,}"
            return f"{number:,.2f}"

        def _format_price(value: Any) -> str:
            try:
                return f"{float(value):,.2f}"
            except Exception:
                return "-"

        def _humanize_errors(errors: Dict[str, str], *, float_shares: int | None = None) -> str:
            messages: List[str] = []
            error_map = {
                "ERR_EMPTY_NAME": "Name is required.",
                "ERR_EMPTY_SYMBOL": "Symbol is unavailable.",
                "ERR_EMPTY_INITIAL_PRICE": "Initial price is required.",
                "ERR_EMPTY_FLOAT_SHARES": "Float shares are required.",
                "ERR_PRICE_INVALID": "Enter a valid initial price.",
                "ERR_FLOAT_SHARES_INVALID": "Enter a valid float-share count.",
                "ERR_TOTAL_SHARES_INVALID": "Enter a valid total-share count.",
                "ERR_TOTAL_LT_FLOAT": "Total shares cannot be below float shares.",
                "ERR_FORM_INVALID": "Please complete the required fields.",
                "ERR_SUBMIT_FAILED": "Instrument creation failed.",
            }
            for code in errors.values():
                message = error_map.get(str(code), str(code))
                if message and message not in messages:
                    messages.append(message)
            if float_shares is not None and float_shares > 0:
                if float_shares == 1:
                    messages.append("A single tradable share will make the market feel broken.")
                elif float_shares < 100:
                    messages.append("Very low float can cause cold-start liquidity problems.")
            return " ".join(messages)

        try:
            try:
                parent = self._root if isinstance(self._root, QWidget) else None
            except Exception:
                parent = None
            dlg = QDialog(parent)  # type: ignore[arg-type]
            try:
                dlg.setWindowTitle("Create Instrument")  # type: ignore[attr-defined]
                dlg.setModal(True)  # type: ignore[attr-defined]
                if hasattr(dlg, "setMinimumSize"):
                    dlg.setMinimumSize(520, 420)  # type: ignore[attr-defined]
                if hasattr(dlg, "setSizeGripEnabled"):
                    dlg.setSizeGripEnabled(True)  # type: ignore[attr-defined]
                dlg.resize(560, 520)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                dlg.setStyleSheet(
                    """
                    QDialog {
                        background: #f4f7fb;
                        color: #142033;
                    }
                    QFrame#createInstrumentCard {
                        background: #ffffff;
                        border: 1px solid #dbe5f0;
                        border-radius: 16px;
                    }
                    QLabel#dialogTitle {
                        font-size: 22px;
                        font-weight: 700;
                        color: #10233b;
                    }
                    QLabel#dialogSubtitle {
                        color: #5f7188;
                        font-size: 12px;
                    }
                    QLabel#fieldLabel {
                        color: #42556e;
                        font-weight: 600;
                        min-width: 110px;
                    }
                    QLabel#summaryLabel {
                        color: #33506e;
                        font-size: 12px;
                        padding-top: 6px;
                    }
                    QLabel#errorLabel {
                        color: #b42318;
                        font-size: 12px;
                        padding-top: 2px;
                    }
                    QLineEdit {
                        background: #fbfdff;
                        border: 1px solid #cfd9e6;
                        border-radius: 10px;
                        padding: 10px 12px;
                        color: #10233b;
                        selection-background-color: #16b7d9;
                    }
                    QLineEdit:focus {
                        border: 1px solid #16b7d9;
                        background: #ffffff;
                    }
                    QLineEdit[readOnly="true"] {
                        background: #eef4fa;
                        color: #51657d;
                        border: 1px solid #d9e5f0;
                    }
                    QPushButton {
                        border-radius: 11px;
                        padding: 10px 18px;
                        font-weight: 600;
                    }
                    QPushButton#primaryAction {
                        background: #16b7d9;
                        color: #ffffff;
                        border: 1px solid #16b7d9;
                    }
                    QPushButton#primaryAction:disabled {
                        background: #9fd9e6;
                        border-color: #9fd9e6;
                        color: #edf7fa;
                    }
                    QPushButton#secondaryAction {
                        background: #ffffff;
                        color: #233247;
                        border: 1px solid #cfd9e6;
                    }
                    """
                )  # type: ignore[attr-defined]
            except Exception:
                pass

            layout = QVBoxLayout(dlg)  # type: ignore
            try:
                layout.setContentsMargins(22, 20, 22, 20)
                layout.setSpacing(14)
            except Exception:
                pass

            title = QLabel("Create Instrument")  # type: ignore
            subtitle = QLabel("Name is editable. Symbol is assigned automatically in sequence.")  # type: ignore
            try:
                title.setObjectName("dialogTitle")  # type: ignore[attr-defined]
                subtitle.setObjectName("dialogSubtitle")  # type: ignore[attr-defined]
                subtitle.setWordWrap(True)  # type: ignore[attr-defined]
            except Exception:
                pass
            layout.addWidget(title)  # type: ignore
            layout.addWidget(subtitle)  # type: ignore

            card = QFrame()  # type: ignore
            try:
                card.setObjectName("createInstrumentCard")  # type: ignore[attr-defined]
            except Exception:
                pass
            card_layout = QVBoxLayout(card)  # type: ignore
            try:
                card_layout.setContentsMargins(18, 18, 18, 18)
                card_layout.setSpacing(12)
            except Exception:
                pass

            form = QFormLayout()  # type: ignore
            try:
                form.setContentsMargins(0, 0, 0, 0)
                form.setHorizontalSpacing(16)
                form.setVerticalSpacing(12)
            except Exception:
                pass

            name_edit = QLineEdit(f"Instrument {default_sym}")  # type: ignore
            sym_edit = QLineEdit(default_sym)  # type: ignore
            price_edit = QLineEdit("10.00")  # type: ignore
            fs_edit = QLineEdit("1000000")  # type: ignore
            mcap_edit = QLineEdit("")  # type: ignore
            try:
                name_edit.setPlaceholderText("e.g. Huaxia Tech")  # type: ignore[attr-defined]
                price_edit.setPlaceholderText("e.g. 12.50")  # type: ignore[attr-defined]
                fs_edit.setPlaceholderText("e.g. 1000000")  # type: ignore[attr-defined]
                sym_edit.setReadOnly(True)  # type: ignore[attr-defined]
                mcap_edit.setReadOnly(True)  # type: ignore[attr-defined]
            except Exception:
                pass

            for text_value, widget in (
                ("Name", name_edit),
                ("Symbol", sym_edit),
                ("Initial Price", price_edit),
                ("Float Shares", fs_edit),
                ("Market Cap", mcap_edit),
            ):
                label = QLabel(text_value)  # type: ignore
                try:
                    label.setObjectName("fieldLabel")  # type: ignore[attr-defined]
                except Exception:
                    pass
                form.addRow(label, widget)  # type: ignore[attr-defined]
            card_layout.addLayout(form)  # type: ignore

            summary_label = QLabel("Market cap updates automatically from price x float shares.")  # type: ignore
            error_label = QLabel("")  # type: ignore
            try:
                summary_label.setObjectName("summaryLabel")  # type: ignore[attr-defined]
                summary_label.setWordWrap(True)  # type: ignore[attr-defined]
                error_label.setObjectName("errorLabel")  # type: ignore[attr-defined]
                error_label.setWordWrap(True)  # type: ignore[attr-defined]
            except Exception:
                pass
            card_layout.addWidget(summary_label)  # type: ignore
            card_layout.addWidget(error_label)  # type: ignore
            layout.addWidget(card)  # type: ignore

            btn_row = QHBoxLayout()  # type: ignore
            ok_btn = QPushButton("Create")  # type: ignore
            cancel_btn = QPushButton("Cancel")  # type: ignore
            try:
                ok_btn.setObjectName("primaryAction")  # type: ignore[attr-defined]
                cancel_btn.setObjectName("secondaryAction")  # type: ignore[attr-defined]
            except Exception:
                pass
            btn_row.addWidget(ok_btn)  # type: ignore
            btn_row.addWidget(cancel_btn)  # type: ignore
            layout.addLayout(btn_row)  # type: ignore

            cid = CreateInstrumentDialog(logic._ctl)  # type: ignore[attr-defined]

            def _apply_fields():
                cid.set_fields(
                    name=getattr(name_edit, "text", lambda: "")(),
                    symbol=getattr(sym_edit, "text", lambda: "")(),
                    initial_price=getattr(price_edit, "text", lambda: "")() or None,
                    float_shares=getattr(fs_edit, "text", lambda: "")() or None,
                )

            def _refresh_preview():
                view = cid.get_view()
                normalized = view.get("normalized") or {}
                market_cap = normalized.get("market_cap")
                getattr(mcap_edit, "setText", lambda *_: None)(_format_market_cap(market_cap))
                price = normalized.get("initial_price")
                float_shares = normalized.get("float_shares")
                if market_cap is not None and price is not None and float_shares is not None:
                    summary = (
                        f"Estimated float market cap: {_format_market_cap(market_cap)}"
                        f" = {_format_price(price)} x {_format_market_cap(float_shares)}"
                    )
                else:
                    summary = "Market cap updates automatically from price x float shares."
                getattr(summary_label, "setText", lambda *_: None)(summary)
                try:
                    float_shares_value = int(float_shares or 0)
                except Exception:
                    float_shares_value = 0
                errors = view.get("errors") or {}
                getattr(error_label, "setText", lambda *_: None)(
                    _humanize_errors(errors, float_shares=float_shares_value)
                )
                try:
                    ok_btn.setEnabled(bool(view.get("is_valid")))  # type: ignore[attr-defined]
                except Exception:
                    pass

            def _on_input_changed():
                _apply_fields()
                _refresh_preview()

            for widget in (name_edit, price_edit, fs_edit):
                try:
                    widget.textChanged.connect(_on_input_changed)  # type: ignore[attr-defined]
                except Exception:
                    pass

            try:
                _apply_fields()
                _refresh_preview()
            except Exception:
                pass

            def _after_submit_success(sym: str):
                try:
                    add = getattr(logic, "add_symbol", None)
                    if callable(add):
                        add(sym)
                    self.refresh()
                except Exception:
                    pass

            def _ok():
                _apply_fields()
                if not cid.submit():
                    _refresh_preview()
                    return
                sym = getattr(sym_edit, "text", lambda: default_sym)().upper()
                try:
                    dlg.accept()  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    from PySide6.QtCore import QTimer  # type: ignore
                    QTimer.singleShot(0, lambda s=sym: _after_submit_success(s))  # type: ignore
                except Exception:
                    _after_submit_success(sym)

            def _cancel():
                try:
                    dlg.reject()  # type: ignore[attr-defined]
                except Exception:
                    pass

            try:
                ok_btn.clicked.connect(_ok)  # type: ignore[attr-defined]
                cancel_btn.clicked.connect(_cancel)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                dlg.exec()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        except Exception:
            pass

        try:
            ctl = getattr(logic, "_ctl", None)
            if ctl is not None:
                payload = ctl.create_instrument(
                    name=f"Instrument {default_sym}",
                    symbol=default_sym,
                    initial_price=10.0,
                    float_shares=1_000_000,
                    market_cap=None,
                )
                sym = payload.get("symbol", default_sym)
                logic.add_symbol(sym)
                self._handle_select(sym)
                self.refresh()
        except Exception:
            pass

    def _handle_select(self, symbol: str):
        symbol = (symbol or "").strip()
        if not symbol:
            return
        self._selected_symbol = symbol
        self._selection_generation += 1
        generation = self._selection_generation
        # 调用逻辑 select_symbol (若存在)
        if self._logic is not None:
            sel = getattr(self._logic, 'select_symbol', None)
            if callable(sel):
                if ui_runtime_enabled() and not os.environ.get("PYTEST_CURRENT_TEST"):
                    def _worker():
                        try:
                            sel(symbol)
                        except Exception:  # pragma: no cover
                            pass
                        if generation != self._selection_generation:
                            return
                        self._post_to_ui(lambda: self._refresh_detail_throttled(force=True))

                    threading.Thread(
                        target=_worker,
                        name=f"MarketAdapter-Select-{symbol}",
                        daemon=True,
                    ).start()
                    return
                try:
                    sel(symbol)
                except Exception:  # pragma: no cover
                    pass
        # 恢复详情刷新视图（尽量放到 UI 线程）
        if ui_runtime_enabled():
            self._post_to_ui(lambda: self._refresh_detail_throttled(force=True))
            return
        self._refresh_detail_throttled(force=True)

    def _refresh_detail_throttled(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_detail_refresh_ts) < self._detail_throttle_sec:
            return
        self._last_detail_refresh_ts = now
        self._refresh_detail()

    def _open_trade_dialog(self, side: str) -> None:
        symbol = (self._selected_symbol or "").strip()
        if not symbol and self._logic is not None:
            try:
                detail = getattr(self._logic, "detail_view", lambda: {})()
                if isinstance(detail, dict):
                    symbol = str(detail.get("symbol") or "").strip()
            except Exception:
                symbol = ""
        if not symbol:
            return
        price = 10.0
        try:
            detail = getattr(self._logic, "detail_view", lambda: {})() if self._logic is not None else {}
            snapshot = detail.get("snapshot") if isinstance(detail, dict) else None
            if isinstance(snapshot, dict):
                price = float(snapshot.get("last") or snapshot.get("last_price") or price)
        except Exception:
            price = 10.0
        payload = {
            "symbol": symbol,
            "side": str(side or "buy").lower(),
            "price": price,
            "qty": 100,
            "account_id": "manual",
        }
        try:
            self._trade_ctl.submit_order(**payload)
        except TypeError:
            try:
                self._trade_ctl.submit_order(SubmitOrderRequest(**payload))
            except Exception:
                pass
        except Exception:
            pass

    def _refresh_detail(self):
        if self._logic is None:
            return
        detail_view_fn = getattr(self._logic, 'detail_view', None)
        if callable(detail_view_fn):
            try:
                dv = detail_view_fn()
                if isinstance(dv, dict):
                    self._detail.apply_detail(dv)
            except Exception:  # pragma: no cover
                pass

    def _apply_view(self, view: Dict[str, Any]):  # noqa: D401
        # watchlist symbols
        watch = []
        try:
            watch = view.get('watchlist', {}).get('symbols', []) if isinstance(view, dict) else []
        except Exception:
            watch = []
        # 列表组件刷新 (全量简单策略; 后续可 diff)
        if self._symbol_list is not None:
            try:
                self._symbol_list.clear()  # type: ignore
                for sym in watch:
                    self._symbol_list.addItem(sym)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        # 若之前选中的 symbol 不在新列表 -> 重置
        if self._selected_symbol and self._selected_symbol not in watch:
            self._selected_symbol = None
        # 若逻辑中提供 selected 字段, 优先用其
        sel = None
        try:
            sel = view.get('selected') if isinstance(view, dict) else None
        except Exception:
            sel = None
        selection_changed = False
        if sel:
            selection_changed = sel != self._selected_symbol
            self._selected_symbol = sel
        # 确保列表高亮与内部一致
        if self._symbol_list is not None and self._selected_symbol in watch:
            try:
                idx = watch.index(self._selected_symbol)
                self._symbol_list.setCurrentRow(idx)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        # 刷新详情
        self._refresh_detail_throttled(force=selection_changed)


class SymbolDetailPanelAdapter(PanelAdapter):
    """PanelAdapter wrapper for per-symbol detail pages.
    It composes the lightweight SymbolDetailAdapter for actual rendering,
    while providing the standard PanelAdapter contract (bind/widget/refresh).
    """
    def __init__(self):
        super().__init__()
        self._detail = SymbolDetailAdapter()
        self._root: Optional[Any] = None
        self._cancel_trade = None
        self._cancel_batch = None

    def _create_widget(self):  # type: ignore[override]
        root = self._detail.widget()
        self._root = root
        try:
            def _on_trade(_topic: str, payload: Dict[str, Any]):
                trade = _extract_trade_payload(payload)
                if not isinstance(trade, dict) or self._logic is None:
                    return
                add_trade = getattr(self._logic, "add_trade", None)
                if callable(add_trade):
                    try:
                        add_trade(trade)
                    except Exception:
                        pass
                self.refresh()

            self._cancel_trade = _subscribe_trade_topics(_on_trade)
        except Exception:
            self._cancel_trade = None
        try:
            def _on_batch(_topic: str, payload: Dict[str, Any]):
                snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
                ctl = getattr(self._logic, "_ctl", None) if self._logic is not None else None
                merge_batch = getattr(ctl, "merge_batch", None)
                if callable(merge_batch) and snapshots:
                    try:
                        merge_batch(snapshots)
                    except Exception:
                        pass
                self.refresh()

            self._cancel_batch = subscribe_topic(FRONTEND_SNAPSHOT_BATCH_TOPIC, _on_batch, async_mode=False)
        except Exception:
            self._cancel_batch = None
        return root

    def _post_to_ui(self, cb) -> bool:
        try:
            from PySide6.QtCore import QTimer  # type: ignore
            if getattr(self, "_root", None) is not None:
                try:
                    QTimer.singleShot(0, self._root, cb)  # type: ignore[arg-type]
                except Exception:
                    QTimer.singleShot(0, cb)
            else:
                QTimer.singleShot(0, cb)
            return True
        except Exception:
            return False

    def refresh(self):  # type: ignore[override]
        def _do():
            try:
                PanelAdapter.refresh(self)
            except Exception:
                pass
        if not self._post_to_ui(_do):
            _do()

    def _apply_view(self, view: Dict[str, Any]):  # type: ignore[override]
        try:
            if isinstance(view, dict):
                self._detail.apply_detail(view)
        except Exception:
            pass

    def __del__(self):
        for cancel in (self._cancel_batch,):
            try:
                if callable(cancel):
                    cancel()
            except Exception:
                pass
        try:
            if isinstance(self._cancel_trade, list):
                for cancel in self._cancel_trade:
                    try:
                        if callable(cancel):
                            cancel()
                    except Exception:
                        pass
            elif callable(self._cancel_trade):
                self._cancel_trade()
        except Exception:
            pass

__all__ = ["MarketPanelAdapter", "SymbolDetailAdapter", "SymbolDetailPanelAdapter"]
