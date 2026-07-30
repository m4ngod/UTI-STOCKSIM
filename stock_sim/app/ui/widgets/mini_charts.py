"""Lightweight chart widgets used by the desktop panels.

The widgets keep their own headless fallback so adapter unit tests can inspect
state without requiring a QApplication.
"""
from __future__ import annotations

from math import ceil, floor, sin, pi
from typing import Any, Dict, Iterable, List, Tuple

try:  # pragma: no cover - exercised by desktop UI
    from PySide6.QtCore import QPointF, QRectF, Qt  # type: ignore
    from PySide6.QtGui import QColor, QFont, QPainter, QPen  # type: ignore
    from PySide6.QtWidgets import QWidget  # type: ignore
except Exception:  # pragma: no cover - headless tests
    QPointF = None  # type: ignore
    QRectF = None  # type: ignore
    Qt = None  # type: ignore
    QColor = None  # type: ignore
    QFont = None  # type: ignore
    QPainter = None  # type: ignore
    QPen = None  # type: ignore
    QWidget = object  # type: ignore


_PALETTE = [
    (20, 148, 132),
    (229, 93, 80),
    (95, 111, 197),
    (236, 169, 61),
    (52, 134, 204),
    (89, 170, 96),
    (181, 86, 157),
    (95, 112, 128),
]

_SURFACE = (17, 25, 34)
_SURFACE_SOFT = (35, 45, 58)
_BORDER = (47, 61, 78)
_TEXT = (232, 239, 247)
_MUTED = (168, 181, 194)


def _color(idx: int, alpha: int = 255):
    if QColor is None:
        return _PALETTE[idx % len(_PALETTE)]
    r, g, b = _PALETTE[idx % len(_PALETTE)]
    return QColor(r, g, b, alpha)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _family_name(row: Dict[str, Any]) -> str:
    typ = str(row.get("type") or "").lower()
    if "model" in typ:
        return "model"
    value = str(row.get("family_model") or row.get("strategy") or "").strip()
    return value or "retail"


def _format_money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


class _HeadlessChartState:
    def __init__(self, *_, **__):
        self._data: Dict[str, Any] = {}

    def setMinimumHeight(self, *_):
        return None

    def update(self):
        return None

    def set_data(self, *args, **kwargs):
        self._data = {"args": args, "kwargs": kwargs}


class HeadlessAgentInsightsWidget(_HeadlessChartState):
    pass


class HeadlessModelEquityChartWidget(_HeadlessChartState):
    pass


class AgentInsightsWidget(QWidget if QWidget is not object else _HeadlessChartState):  # type: ignore[misc]
    """Compact dashboard for agent population composition and behavior."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._family_counts: List[Tuple[str, int]] = []
        self._buy_count = 0
        self._sell_count = 0
        self._pnl_values: List[float] = []
        if hasattr(self, "setMinimumHeight"):
            self.setMinimumHeight(230)

    def set_data(
        self,
        rows: Iterable[Dict[str, Any]],
        *,
        order_events: Iterable[Dict[str, Any]] | None = None,
    ) -> None:
        family: Dict[str, int] = {}
        pnl_values: List[float] = []
        buy_count = 0
        sell_count = 0
        for row in rows or []:
            name = _family_name(row)
            family[name] = family.get(name, 0) + 1
            pnl_values.append(_safe_float(row.get("pnl")))
            action = str(row.get("last_action") or "").lower()
            if "buy" in action:
                buy_count += 1
            elif "sell" in action:
                sell_count += 1
        for event in order_events or []:
            side = str(event.get("side") or "").lower()
            if side == "buy":
                buy_count += 1
            elif side == "sell":
                sell_count += 1
        self._family_counts = sorted(family.items(), key=lambda item: (-item[1], item[0]))
        self._buy_count = buy_count
        self._sell_count = sell_count
        self._pnl_values = pnl_values
        if hasattr(self, "update"):
            self.update()

    def paintEvent(self, _event):  # pragma: no cover - visual Qt path
        if QPainter is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(14, 12, -14, -12)
        painter.fillRect(rect, _qcolor(*_SURFACE))
        _draw_panel_outline(painter, rect)
        w = rect.width() / 3.0
        sections = [
            QRectF(rect.left(), rect.top(), w, rect.height()),
            QRectF(rect.left() + w, rect.top(), w, rect.height()),
            QRectF(rect.left() + 2 * w, rect.top(), w, rect.height()),
        ]
        _draw_title(painter, sections[0], "Family Mix")
        _draw_donut(painter, sections[0].adjusted(8, 34, -8, -8), self._family_counts)
        _draw_title(painter, sections[1], "Buy / Sell")
        _draw_buy_sell(painter, sections[1].adjusted(20, 48, -20, -28), self._buy_count, self._sell_count)
        _draw_title(painter, sections[2], "PnL Distribution")
        _draw_histogram(painter, sections[2].adjusted(18, 48, -18, -28), self._pnl_values)
        painter.end()


class ModelEquityChartWidget(QWidget if QWidget is not object else _HeadlessChartState):  # type: ignore[misc]
    """Line chart with stable colors and legend for Arena model equity."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._series: Dict[str, List[float]] = {}
        self._labels: Dict[str, str] = {}
        self._colors: Dict[str, Any] = {}
        if hasattr(self, "setMinimumHeight"):
            self.setMinimumHeight(220)

    def set_data(self, rows: Iterable[Dict[str, Any]], *, selected: Dict[str, Any] | None = None) -> None:
        selected = selected or {}
        series: Dict[str, List[float]] = {}
        labels: Dict[str, str] = {}
        for row in rows or []:
            agent_id = str(row.get("agent_id") or row.get("model_id") or "").strip()
            if not agent_id:
                continue
            model_id = str(row.get("model_id") or agent_id)
            equity_return = _safe_float(row.get("equity_return"), 0.0)
            score = _safe_float(row.get("score"), equity_return)
            end = 100_000.0 * (1.0 + equity_return)
            curve = row.get("equity_curve")
            if isinstance(curve, list) and curve:
                values = [_safe_float(v, 100_000.0) for v in curve]
            else:
                values = _synthetic_curve(100_000.0, end, score)
            series[agent_id] = values
            labels[agent_id] = model_id
        if not series:
            for agent_id in selected.get("model_agent_ids") or []:
                aid = str(agent_id)
                series[aid] = [100_000.0]
                labels[aid] = aid
        self._series = series
        self._labels = labels
        for idx, agent_id in enumerate(sorted(series)):
            if agent_id not in self._colors:
                self._colors[agent_id] = _color(len(self._colors) + idx)
        if hasattr(self, "update"):
            self.update()

    def paintEvent(self, _event):  # pragma: no cover - visual Qt path
        if QPainter is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(14, 12, -14, -12)
        painter.fillRect(rect, _qcolor(*_SURFACE))
        _draw_panel_outline(painter, rect)
        _draw_title(painter, rect, "Model Equity")
        plot = rect.adjusted(44, 42, -150, -30)
        legend = QRectF(plot.right() + 16, plot.top(), 128, plot.height())
        _draw_line_chart(painter, plot, self._series, self._colors)
        _draw_legend(painter, legend, self._series, self._labels, self._colors)
        painter.end()


def _qcolor(r: int, g: int, b: int, a: int = 255):
    return QColor(r, g, b, a)


def _draw_panel_outline(painter, rect) -> None:
    painter.setPen(QPen(_qcolor(*_BORDER), 1))
    painter.drawRoundedRect(rect, 8, 8)


def _draw_title(painter, rect, text: str) -> None:
    font = painter.font()
    font.setPointSize(10)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(_qcolor(*_TEXT))
    painter.drawText(rect.adjusted(14, 8, -8, -8), Qt.AlignLeft | Qt.AlignTop, text)


def _draw_donut(painter, rect, items: List[Tuple[str, int]]) -> None:
    total = sum(v for _, v in items)
    if total <= 0:
        _draw_empty(painter, rect, "No agents")
        return
    size = min(rect.width() * 0.55, rect.height() * 0.72)
    cx = rect.left() + rect.width() * 0.32
    cy = rect.top() + rect.height() * 0.52
    circle = QRectF(cx - size / 2, cy - size / 2, size, size)
    angle = 90 * 16
    for idx, (_name, value) in enumerate(items):
        span = int(-360 * 16 * value / total)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_color(idx))
        painter.drawPie(circle, angle, span)
        angle += span
    inner = circle.adjusted(size * 0.23, size * 0.23, -size * 0.23, -size * 0.23)
    painter.setBrush(_qcolor(*_SURFACE))
    painter.drawEllipse(inner)
    painter.setPen(_qcolor(*_TEXT))
    painter.drawText(inner, Qt.AlignCenter, str(total))
    y = rect.top() + 38
    x = rect.left() + rect.width() * 0.62
    for idx, (name, value) in enumerate(items[:6]):
        painter.setBrush(_color(idx))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(x, y + 4, 8, 8))
        painter.setPen(_qcolor(*_MUTED))
        pct = value * 100.0 / total
        painter.drawText(QRectF(x + 14, y, rect.right() - x - 16, 18), Qt.AlignLeft, f"{name} {pct:.0f}%")
        y += 20


def _draw_buy_sell(painter, rect, buy: int, sell: int) -> None:
    total = max(buy + sell, 1)
    bars = [("Buy", buy, _qcolor(36, 155, 123)), ("Sell", sell, _qcolor(222, 86, 76))]
    y = rect.top() + rect.height() * 0.22
    for label, value, color in bars:
        painter.setPen(_qcolor(*_MUTED))
        painter.drawText(QRectF(rect.left(), y - 18, rect.width(), 18), Qt.AlignLeft, f"{label} {value}")
        bar_rect = QRectF(rect.left(), y, rect.width(), 18)
        painter.setBrush(_qcolor(*_SURFACE_SOFT))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bar_rect, 4, 4)
        fill = QRectF(bar_rect.left(), bar_rect.top(), bar_rect.width() * value / total, bar_rect.height())
        painter.setBrush(color)
        painter.drawRoundedRect(fill, 4, 4)
        y += 58
    ratio = buy / total
    painter.setPen(_qcolor(*_TEXT))
    painter.drawText(rect.adjusted(0, rect.height() - 36, 0, 0), Qt.AlignCenter, f"Buy share {ratio:.0%}")


def _draw_histogram(painter, rect, values: List[float]) -> None:
    if not values:
        _draw_empty(painter, rect, "No PnL")
        return
    min_v = min(values)
    max_v = max(values)
    if abs(max_v - min_v) < 1e-9:
        max_v = min_v + 1.0
    bins = 8
    counts = [0] * bins
    for value in values:
        idx = min(bins - 1, max(0, int((value - min_v) / (max_v - min_v) * bins)))
        counts[idx] += 1
    max_count = max(counts) or 1
    gap = 4
    bar_w = max(2.0, (rect.width() - gap * (bins - 1)) / bins)
    zero_x = None
    if min_v < 0 < max_v:
        zero_x = rect.left() + rect.width() * ((0 - min_v) / (max_v - min_v))
    for idx, count in enumerate(counts):
        h = rect.height() * 0.72 * count / max_count
        x = rect.left() + idx * (bar_w + gap)
        y = rect.bottom() - h - 20
        painter.setBrush(_color(idx, 220))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(x, y, bar_w, h), 3, 3)
    if zero_x is not None:
        painter.setPen(QPen(_qcolor(*_MUTED), 1))
        painter.drawLine(QPointF(zero_x, rect.top() + 4), QPointF(zero_x, rect.bottom() - 16))
    painter.setPen(_qcolor(*_MUTED))
    painter.drawText(QRectF(rect.left(), rect.bottom() - 18, rect.width(), 18), Qt.AlignLeft, _format_money(min_v))
    painter.drawText(QRectF(rect.left(), rect.bottom() - 18, rect.width(), 18), Qt.AlignRight, _format_money(max_v))


def _draw_line_chart(painter, rect, series: Dict[str, List[float]], colors: Dict[str, Any]) -> None:
    if not series:
        _draw_empty(painter, rect, "No model equity")
        return
    values = [v for curve in series.values() for v in curve]
    lo = min(values)
    hi = max(values)
    if abs(hi - lo) < 1e-9:
        lo -= 1
        hi += 1
    painter.setPen(QPen(_qcolor(*_SURFACE_SOFT), 1))
    for i in range(4):
        y = rect.top() + rect.height() * i / 3
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
    painter.setPen(_qcolor(*_MUTED))
    painter.drawText(QRectF(rect.left() - 42, rect.top() - 2, 38, 18), Qt.AlignRight, _format_money(hi))
    painter.drawText(QRectF(rect.left() - 42, rect.bottom() - 16, 38, 18), Qt.AlignRight, _format_money(lo))
    for agent_id, curve in series.items():
        if not curve:
            continue
        pen = QPen(colors.get(agent_id) or _color(0), 2.2)
        painter.setPen(pen)
        points = []
        count = max(len(curve) - 1, 1)
        for idx, value in enumerate(curve):
            x = rect.left() + rect.width() * idx / count
            y = rect.bottom() - rect.height() * ((value - lo) / (hi - lo))
            points.append(QPointF(x, y))
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)
        if len(points) == 1:
            painter.drawEllipse(points[0], 3, 3)


def _draw_legend(painter, rect, series: Dict[str, List[float]], labels: Dict[str, str], colors: Dict[str, Any]) -> None:
    y = rect.top()
    for agent_id in list(series.keys())[:8]:
        painter.setBrush(colors.get(agent_id) or _color(0))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(rect.left(), y + 4, 8, 8))
        painter.setPen(_qcolor(*_MUTED))
        label = labels.get(agent_id, agent_id)
        painter.drawText(QRectF(rect.left() + 14, y, rect.width() - 14, 18), Qt.AlignLeft, label[:20])
        y += 21


def _draw_empty(painter, rect, text: str) -> None:
    painter.setPen(_qcolor(*_MUTED))
    painter.drawText(rect, Qt.AlignCenter, text)


def _synthetic_curve(start: float, end: float, score: float, points: int = 24) -> List[float]:
    out: List[float] = []
    wobble = min(max(abs(score), 0.0), 0.2) * start * 0.08
    for idx in range(points):
        x = idx / max(points - 1, 1)
        base = start + (end - start) * x
        out.append(base + sin(pi * 2 * x) * wobble)
    return out


__all__ = [
    "AgentInsightsWidget",
    "HeadlessAgentInsightsWidget",
    "ModelEquityChartWidget",
    "HeadlessModelEquityChartWidget",
]
