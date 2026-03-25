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
import time  # 新增：节流

_TRACE_MARKET_ADAPTER = os.environ.get("STOCKSIM_TRACE_MARKET_ADAPTER", "").strip().lower() in {"1", "true", "yes", "on"}

_DETAIL_ENABLE_CHART = os.environ.get("STOCKSIM_DETAIL_ENABLE_CHART", "1").lower() in ("1", "true", "yes", "on")
_DETAIL_ENABLE_ORDER_BOOK = os.environ.get("STOCKSIM_DETAIL_ENABLE_ORDER_BOOK", "1").lower() in ("1", "true", "yes", "on")
_DETAIL_ENABLE_PIE = os.environ.get("STOCKSIM_DETAIL_ENABLE_PIE", "1").lower() in ("1", "true", "yes", "on")

_CHART_STAGE = os.environ.get("STOCKSIM_CHART_STAGE", "candles").strip().lower()
if _CHART_STAGE not in ("plot-only", "line", "candles"):
    _CHART_STAGE = "candles"

from .base_adapter import PanelAdapter
from .runtime_mode import ui_runtime_enabled
from app.panels.market.dialog import CreateInstrumentDialog  # 新增：逻辑对话框
from infra.event_bus import event_bus  # 新增：回退订阅
try:
    from stock_sim.infra.event_bus import event_bus as runtime_event_bus  # type: ignore
except Exception:  # pragma: no cover
    runtime_event_bus = event_bus  # type: ignore

# 显式双总线订阅，避免 app/runtime 导入路径导致的消息丢失。
def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
    event_bus.subscribe(topic, handler, async_mode=async_mode)
    if runtime_event_bus is not event_bus:
        runtime_event_bus.subscribe(topic, handler, async_mode=async_mode)
    def _cancel():
        try:
            event_bus.unsubscribe(topic, handler)
        except Exception:
            pass
        if runtime_event_bus is not event_bus:
            try:
                runtime_event_bus.unsubscribe(topic, handler)
            except Exception:
                pass
    return _cancel

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
            QDialog, QLineEdit, QPushButton, QGraphicsView, QGraphicsScene, QGraphicsEllipseItem
        )  # type: ignore
        from PySide6.QtGui import QBrush, QPen, QColor  # type: ignore
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
    class QGraphicsView:  # type: ignore
        def __init__(self, *_, **__): pass
    class QGraphicsScene:  # type: ignore
        def __init__(self, *_, **__): pass
        def clear(self): pass
        def addItem(self, *_): pass
    class QGraphicsEllipseItem:  # type: ignore
        def __init__(self, *_, **__): pass
        def setRect(self, *_): pass
        def setStartAngle(self, *_): pass
        def setSpanAngle(self, *_): pass
        def setBrush(self, *_): pass
        def setPen(self, *_): pass
    class QBrush:  # type: ignore
        def __init__(self, *_): pass
    class QPen:  # type: ignore
        def __init__(self, *_): pass
    class QColor:  # type: ignore
        def __init__(self, *_): pass

# pyqtgraph（可选）
try:  # pragma: no cover
    import pyqtgraph as pg  # type: ignore
    from pyqtgraph import GraphicsLayoutWidget  # type: ignore
    from pyqtgraph import ErrorBarItem, BarGraphItem  # type: ignore
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
    class ErrorBarItem:  # type: ignore
        def __init__(self, *_, **__): pass
    class BarGraphItem:  # type: ignore
        def __init__(self, *_, **__): pass


class _SafeCandlestickItem:
    def __init__(self, candles):
        self._candles = candles
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
                                    p.drawLine(QPointF(float(x) - 0.3, float(o)), QPointF(float(x) + 0.3, float(c)))
                                else:
                                    p.setBrush(brush)
                                    p.drawRect(QRectF(float(x) - 0.3, y0, 0.6, height))
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


class SymbolDetailAdapter:
    """详情适配: 展示 snapshot / order_book / series K 线 / 持仓饼图。"""
    def __init__(self):
        self._symbol_label: Optional[Any] = None
        self._snapshot_label: Optional[Any] = None
        self._debug_label: Optional[Any] = None
        self._order_book_table: Optional[Any] = None
        self._trades_table: Optional[Any] = None
        self._chart_widget: Optional[Any] = None
        self._chart_plot: Optional[Any] = None
        self._chart_items: List[Any] = []
        self._pie_view: Optional[Any] = None
        self._pie_scene: Optional[Any] = None
        self._chart_fallback_label: Optional[Any] = None
        self._root: Optional[Any] = None

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
            if _DETAIL_ENABLE_CHART and pg is not None:
                try:
                    self._chart_widget = GraphicsLayoutWidget()  # type: ignore
                    try:
                        if hasattr(self._chart_widget, 'setMinimumHeight'):
                            self._chart_widget.setMinimumHeight(260)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    self._chart_plot = self._chart_widget.addPlot(title="K")  # type: ignore
                    try:
                        self._chart_plot.showGrid(x=True, y=True)
                    except Exception:
                        pass
                    layout.addWidget(self._chart_widget, 1)  # type: ignore
                    chart_ok = True
                except Exception:
                    self._chart_widget = None
                    self._chart_plot = None
            if not chart_ok:
                fallback_text = "K: disabled" if not _DETAIL_ENABLE_CHART else "K: (pyqtgraph not available)"
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
            if _DETAIL_ENABLE_PIE:
                try:
                    self._pie_scene = QGraphicsScene()  # type: ignore[attr-defined]
                    self._pie_view = QGraphicsView(self._pie_scene)  # type: ignore[attr-defined]
                    layout.addWidget(self._pie_view)  # type: ignore
                except Exception:
                    self._pie_scene = None
                    self._pie_view = None
                    layout.addWidget(QLabel("Pie: (graphics not available)"))  # type: ignore
            else:
                self._pie_scene = None
                self._pie_view = None
                layout.addWidget(QLabel("Pie: disabled"))  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    def _plot_candles(self, series: Dict[str, List[float]]):
        if self._chart_plot is None:
            if self._chart_fallback_label is not None:
                try:
                    n = len(series.get('close') or [])
                    self._chart_fallback_label.setText(f"K: {n} bars")  # type: ignore
                except Exception:
                    pass
            return
        try:
            self._chart_plot.clear()
        except Exception:
            pass
        # 取数据
        open_ = series.get('open') or []
        high = series.get('high') or []
        low = series.get('low') or []
        close = series.get('close') or []
        n = min(len(open_), len(high), len(low), len(close))
        if n <= 0:
            return
        x = list(range(n))
        try:
            self._chart_plot.setLabel('bottom', 'Index')
            self._chart_plot.setLabel('left', 'Price')
        except Exception:
            pass
        # 分阶段恢复图表，逐步逼近崩点
        if _CHART_STAGE == 'plot-only':
            return
        if _CHART_STAGE == 'line':
            try:
                if hasattr(self._chart_plot, 'plot'):
                    self._chart_plot.plot(x, close, pen=(33, 150, 243))  # type: ignore[attr-defined]
                else:
                    if self._chart_fallback_label is not None:
                        self._chart_fallback_label.setText(f"K(line): {n} bars")  # type: ignore
            except Exception:
                pass
            return
        if _CHART_STAGE == 'candles':
            try:
                candles = [(i, open_[i], high[i], low[i], close[i]) for i in range(n)]
                safe_item = _SafeCandlestickItem(candles).graphics_item()
                if safe_item is not None:
                    self._chart_plot.addItem(safe_item)
                    return
            except Exception:
                pass
            # fallback: 若安全蜡烛图构造失败，再退回 line，避免炸进程
            try:
                if hasattr(self._chart_plot, 'plot'):
                    self._chart_plot.plot(x, close, pen=(33, 150, 243))  # type: ignore[attr-defined]
            except Exception:
                pass

    def _draw_pie(self, holdings: Optional[Dict[str, Any]]):
        if self._pie_scene is None:
            return
        try:
            self._pie_scene.clear()
        except Exception:
            pass
        if not holdings:
            return
        labels = holdings.get('labels') or []
        pct = holdings.get('pct') or []
        if not labels or not pct:
            return
        total = float(sum(float(p) for p in pct))
        if total <= 0:
            return
        start_angle = 0  # Qt 单位: 1/16 度
        rect_size = 200
        rect_x = -rect_size/2
        rect_y = -rect_size/2
        colors = [QColor(244, 67, 54), QColor(33, 150, 243), QColor(255, 193, 7), QColor(76, 175, 80), QColor(156, 39, 176)]  # type: ignore[attr-defined]
        for i, p in enumerate(pct):
            try:
                frac = float(p) / total if total else 0.0
            except Exception:
                frac = 0.0
            span_angle = int(360 * 16 * frac)
            try:
                item = QGraphicsEllipseItem()  # type: ignore[attr-defined]
                item.setRect(rect_x, rect_y, rect_size, rect_size)
                item.setStartAngle(start_angle)
                item.setSpanAngle(span_angle)
                brush = QBrush(colors[i % len(colors)])  # type: ignore[attr-defined]
                pen = QPen(QColor(30,30,30))  # type: ignore[attr-defined]
                item.setBrush(brush)
                item.setPen(pen)
                self._pie_scene.addItem(item)
            except Exception:
                pass
            start_angle += span_angle

    def apply_detail(self, detail: Dict[str, Any]):
        if not isinstance(detail, dict):
            return
        symbol = detail.get('symbol') or '-'
        snapshot = detail.get('snapshot') or {}
        snapshot_meta = detail.get('snapshot_meta') or {}
        series = detail.get('series') or None
        series_meta = detail.get('series_meta') or {}
        ob = detail.get('order_book') or None
        order_book_meta = detail.get('order_book_meta') or {}
        trades = detail.get('trades') or []
        trades_meta = detail.get('trades_meta') or {}
        indicators_meta = detail.get('indicators_meta') or {}
        holdings = detail.get('holdings') or None
        holdings_meta = detail.get('holdings_meta') or {}
        detail_health = detail.get('detail_health') or {}
        # 顶部标签
        if self._symbol_label is not None:
            try: self._symbol_label.setText(f"symbol: {symbol}")  # type: ignore
            except Exception: pass
        chart_mode = 'pyqtgraph' if self._chart_plot is not None else 'fallback'
        bars_count = 0
        try:
            if isinstance(series, dict):
                bars_count = len(series.get('close') or [])
        except Exception:
            bars_count = 0
        if self._snapshot_label is not None:
            last = snapshot.get('last') if isinstance(snapshot, dict) else None
            order_book_status = detail_health.get('order_book_status') or order_book_meta.get('status') or ('available' if ob else 'missing')
            overall = detail_health.get('overall') or 'unknown'
            series_status = detail_health.get('series_status') or ('stale' if detail.get('is_stale') else 'available')
            snap_status = detail_health.get('snapshot_status') or ('available' if snapshot else 'missing')
            core_summary = f"state={overall} | snap={snap_status} | book={order_book_status} | series={series_status}"
            try: self._snapshot_label.setText(
                f"last={last} | bars={bars_count} | {core_summary}"
            )  # type: ignore
            except Exception: pass
        if self._debug_label is not None:
            trades_status = detail_health.get('trades_status') or trades_meta.get('status') or ('available' if trades else 'empty')
            holdings_status = detail_health.get('holdings_status') or holdings_meta.get('status') or 'unknown'
            indicators_status = detail_health.get('indicators_status') or indicators_meta.get('status') or 'unknown'
            holdings_auth = holdings_meta.get('authoritative')
            holdings_tag = 'auth' if holdings_auth else 'non-auth'
            holdings_note = ''
            try:
                if isinstance(holdings, dict) and holdings.get('placeholder'):
                    holdings_note = ' | holdings_ui=placeholder'
            except Exception:
                holdings_note = ''
            try: self._debug_label.setText(
                f"detail debug: mode={chart_mode} symbol={symbol} bars={bars_count} trades={trades_status} indicators={indicators_status} holdings={holdings_status}/{holdings_tag}{holdings_note}"
            )  # type: ignore
            except Exception: pass
        # K 线
        if _DETAIL_ENABLE_CHART:
            if series:
                self._plot_candles(series)
                try:
                    if self._chart_fallback_label is not None:
                        self._chart_fallback_label.setText(f"K: {len(series.get('close') or [])} bars")  # type: ignore
                except Exception:
                    pass
            else:
                # 清空或占位
                if self._chart_plot is not None:
                    try: self._chart_plot.clear()
                    except Exception: pass
                if self._chart_fallback_label is not None:
                    try: self._chart_fallback_label.setText("K: no data")  # type: ignore
                    except Exception: pass
        else:
            if self._chart_fallback_label is not None:
                try: self._chart_fallback_label.setText(f"K: disabled | bars: {bars_count}")  # type: ignore
                except Exception: pass
        # 饼图
        if _DETAIL_ENABLE_PIE:
            # 仅在 holdings 至少有可视化数据时绘制；
            # 对显式 placeholder / non-authoritative empty payload 保持空图，避免 UI 伪装成真实持仓分布。
            try:
                labels = (holdings or {}).get('labels') if isinstance(holdings, dict) else None
                pct = (holdings or {}).get('pct') if isinstance(holdings, dict) else None
                placeholder = bool((holdings or {}).get('placeholder')) if isinstance(holdings, dict) else False
                if labels and pct and not placeholder:
                    self._draw_pie(holdings)
                elif self._pie_scene is not None:
                    try:
                        self._pie_scene.clear()
                    except Exception:
                        pass
                    try:
                        if self._debug_label is not None and placeholder:
                            base = getattr(self._debug_label, '_text', None)
                    except Exception:
                        pass
            except Exception:
                self._draw_pie(holdings)
        # 更新盘口表 (仅展示前 5 档)
        if _DETAIL_ENABLE_ORDER_BOOK and self._order_book_table is not None and ob:
            bids = ob.get('bids') or []
            asks = ob.get('asks') or []
            rows = min(5, max(len(bids), len(asks)))
            try:
                self._order_book_table.setRowCount(rows * 2)  # type: ignore
                for i in range(rows):
                    # bid
                    if i < len(bids):
                        bp, bq = bids[i]
                        self._order_book_table.setItem(i, 0, QTableWidgetItem('BID'))  # type: ignore
                        self._order_book_table.setItem(i, 1, QTableWidgetItem(str(bp)))  # type: ignore
                        self._order_book_table.setItem(i, 2, QTableWidgetItem(str(bq)))  # type: ignore
                    # ask
                    if i < len(asks):
                        ap, aq = asks[i]
                        r = rows + i
                        self._order_book_table.setItem(r, 0, QTableWidgetItem('ASK'))  # type: ignore
                        self._order_book_table.setItem(r, 1, QTableWidgetItem(str(ap)))  # type: ignore
                        self._order_book_table.setItem(r, 2, QTableWidgetItem(str(aq)))  # type: ignore
            except Exception:  # pragma: no cover
                pass
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
                        # 先只做当前面板内选中与详情刷新；
                        # 暂不打开独立 symbol 页面，避免动态页面挂载/切换导致 GUI 进程退出。
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
                    trade = None
                    if isinstance(payload, dict):
                        trade = payload.get('trade') or payload
                    if _TRACE_MARKET_ADAPTER:
                        try:
                            print(f"[market-adapter:on_trade] topic={_topic} selected={self._selected_symbol} payload_symbol={getattr(trade, 'get', lambda *_: None)('symbol') if isinstance(trade, dict) else None}", flush=True)
                        except Exception:
                            pass
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
                                if _TRACE_MARKET_ADAPTER:
                                    try:
                                        dv = getattr(self._logic, 'detail_view', lambda: {})()
                                        trades = (dv or {}).get('trades') or []
                                        print(f"[market-adapter:on_trade:added] symbol={sym} trades_len={len(trades)}", flush=True)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        # 仅刷新详情（轻量），不改变主列表
                        self._refresh_detail()
                except Exception:
                    pass
            self._cancel_trade = [
                subscribe_topic("Trade", _on_trade, async_mode=False),
                subscribe_topic("TradeEvent", _on_trade, async_mode=False),
            ]
        except Exception:
            self._cancel_trade = None
        # 新增：订阅前端批量快照并节流刷新
        try:
            def _on_batch(_topic: str, _payload: Dict[str, Any]):
                try:
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
                        self._refresh_detail()
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
        def _dbg(msg: str):
            try:
                if os.environ.get("STOCKSIM_DEBUG_CREATE_DIALOG", "").lower() in ("1", "true", "yes", "on"):
                    print(f"[create-dialog] {msg}", flush=True)
            except Exception:
                pass
        logic = self._logic
        if logic is None:
            _dbg("logic missing")
            return
        # 优先 Qt 对话框
        try:
            dlg = QDialog()  # type: ignore
            layout = QVBoxLayout(dlg)  # type: ignore
            lbl = QLabel("Name / Symbol / (价格:元，流通股:亿，市值:亿)")  # type: ignore
            layout.addWidget(lbl)  # type: ignore
            # 为避免重复创建同名 symbol，默认给出顺序编号：001, 002, 003 ...
            default_sym = "001"
            try:
                current_view = getattr(logic, 'get_view', None)
                watch = []
                if callable(current_view):
                    try:
                        view = current_view()
                        watch = ((view or {}).get('watchlist') or {}).get('symbols') or []
                    except Exception:
                        watch = []
                used_nums = set()
                for s in watch:
                    try:
                        text = str(s).strip()
                        if len(text) == 3 and text.isdigit():
                            used_nums.add(int(text))
                    except Exception:
                        pass
                n = 1
                while n in used_nums:
                    n += 1
                default_sym = f"{n:03d}"
            except Exception:
                default_sym = "001"
            name_edit = QLineEdit("NewCo")  # type: ignore
            sym_edit = QLineEdit(default_sym)  # type: ignore
            price_edit = QLineEdit("")  # type: ignore
            fs_edit = QLineEdit("")  # type: ignore  # 流通股(亿)
            mcap_edit = QLineEdit("")  # type: ignore  # 市值(亿)
            layout.addWidget(QLabel("Name"))  # type: ignore
            layout.addWidget(name_edit)  # type: ignore
            layout.addWidget(QLabel("Symbol"))  # type: ignore
            layout.addWidget(sym_edit)  # type: ignore
            layout.addWidget(QLabel("Initial Price (optional)"))  # type: ignore
            layout.addWidget(price_edit)  # type: ignore
            layout.addWidget(QLabel("Float Shares (optional"))  # type: ignore
            layout.addWidget(fs_edit)  # type: ignore
            layout.addWidget(QLabel("Market Cap (optional)"))  # type: ignore
            layout.addWidget(mcap_edit)  # type: ignore
            # 实时派生与校验提示
            derived_label = QLabel("Derived: -")  # type: ignore
            error_label = QLabel("")  # type: ignore
            layout.addWidget(derived_label)  # type: ignore
            layout.addWidget(error_label)  # type: ignore
            btn_row = QHBoxLayout()  # type: ignore
            ok_btn = QPushButton("Create")  # type: ignore
            cancel_btn = QPushButton("Cancel")  # type: ignore
            btn_row.addWidget(ok_btn)  # type: ignore
            btn_row.addWidget(cancel_btn)  # type: ignore
            layout.addLayout(btn_row)  # type: ignore
            # 逻辑对话框用于推导与最终提交
            cid = CreateInstrumentDialog(logic._ctl)  # type: ignore[attr-defined]
            # 递归更新保护 & 最近变更字段
            _updating = {"flag": False, "last": None}
            def _apply_fields():
                cid.set_fields(
                    name=getattr(name_edit, 'text', lambda: '')(),
                    symbol=getattr(sym_edit, 'text', lambda: '')(),
                    initial_price=getattr(price_edit, 'text', lambda: '')() or None,
                    float_shares=getattr(fs_edit, 'text', lambda: '')() or None,
                    market_cap=getattr(mcap_edit, 'text', lambda: '')() or None,
                )
            def _refresh_preview():
                v = cid.get_view()
                der = v.get('derived') or {}
                field = der.get('field')
                val = der.get('value')
                getattr(derived_label, 'setText', lambda *_: None)(f"Derived: {field} = {val}" if field else "Derived: -")
                errs = v.get('errors') or {}
                msg = ", ".join(f"{k}:{code}" for k, code in errs.items()) if errs else ""
                getattr(error_label, 'setText', lambda *_: None)(msg)
                try:
                    ok_btn.setEnabled(bool(v.get('is_valid')))  # type: ignore[attr-defined]
                except Exception:
                    pass
            # 规则: 仅允许三者中恰好一个为空；
            # - 当修改 float_shares 或 market_cap 时 -> 清空 price
            # - 当修改 price 时 -> 清空 float_shares
            def _on_price_changed():
                if _updating["flag"]: return
                _updating["flag"] = True
                _updating["last"] = 'initial_price'
                try:
                    # 改价 -> 清空 float_shares
                    try:
                        fs_edit.setText("")  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    _apply_fields()
                    _refresh_preview()
                finally:
                    _updating["flag"] = False
            def _on_fs_changed():
                if _updating["flag"]: return
                _updating["flag"] = True
                _updating["last"] = 'float_shares'
                try:
                    # 改流通股 -> 清空 price
                    try:
                        price_edit.setText("")  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    _apply_fields()
                    _refresh_preview()
                finally:
                    _updating["flag"] = False
            def _on_mcap_changed():
                if _updating["flag"]: return
                _updating["flag"] = True
                _updating["last"] = 'market_cap'
                try:
                    # 改市值 -> 清空 price
                    try:
                        price_edit.setText("")  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    _apply_fields()
                    _refresh_preview()
                finally:
                    _updating["flag"] = False
            # 文本变更联动（含 triad 规则）
            try:
                price_edit.textChanged.connect(_on_price_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                fs_edit.textChanged.connect(_on_fs_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                mcap_edit.textChanged.connect(_on_mcap_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            # 其它字段直接刷新
            def _on_simple_changed():
                if _updating["flag"]: return
                _updating["flag"] = True
                try:
                    _apply_fields()
                    _refresh_preview()
                finally:
                    _updating["flag"] = False
            for w in (name_edit, sym_edit):
                try:
                    w.textChanged.connect(_on_simple_changed)  # type: ignore[attr-defined]
                except Exception:
                    pass
            # 初始预览
            try:
                _apply_fields()
                _refresh_preview()
            except Exception:
                pass
            result_holder = {"ok": False, "submitted": False}
            def _after_submit_success(sym: str):
                _dbg(f"_after_submit_success enter sym={sym}")
                try:
                    add = getattr(logic, 'add_symbol', None)
                    if callable(add):
                        try:
                            add(sym)
                            _dbg("logic.add_symbol done")
                        except Exception as e:
                            _dbg(f"logic.add_symbol exception: {e!r}")
                    # 先仅刷新主列表，避免提交成功后的立即选中/详情渲染引发 UI 重入或对象生命周期问题
                    try:
                        self.refresh()
                        _dbg("refresh done")
                    except Exception as e:
                        _dbg(f"refresh exception: {e!r}")
                    # 创建成功后仍不自动切详情，避免把创建链路和详情链路重新耦合在一起。
                    _dbg("skip auto _handle_select after create")
                except Exception as e:
                    _dbg(f"_after_submit_success exception: {e!r}")

            def _ok():
                _dbg("_ok enter")
                try:
                    _apply_fields()
                    _dbg("fields applied")
                    if not cid.submit():
                        _dbg("submit returned false")
                        _refresh_preview()
                        return
                    _dbg("submit returned true")
                    result_holder["ok"] = True
                    result_holder["submitted"] = True
                    sym = getattr(sym_edit, 'text', lambda: default_sym)().upper()
                    _dbg(f"post-submit sym={sym}")
                    try:
                        dlg.accept()  # type: ignore[attr-defined]
                        _dbg("dlg.accept done")
                    except Exception as e:
                        _dbg(f"dlg.accept exception: {e!r}")
                    try:
                        from PySide6.QtCore import QTimer  # type: ignore
                        QTimer.singleShot(0, lambda s=sym: _after_submit_success(s))  # type: ignore
                        _dbg("scheduled _after_submit_success")
                    except Exception as e:
                        _dbg(f"QTimer.singleShot exception: {e!r}")
                        _after_submit_success(sym)
                except Exception as e:
                    _dbg(f"_ok exception: {e!r}")
                    try:
                        getattr(error_label, 'setText', lambda *_: None)(f"Create failed: {e}")
                    except Exception:
                        pass
                    raise
            def _cancel():
                try:
                    dlg.reject()  # type: ignore[attr-defined]
                except Exception as e:
                    _dbg(f"_cancel exception: {e!r}")
            try:
                ok_btn.clicked.connect(_ok)  # type: ignore[attr-defined]
                cancel_btn.clicked.connect(_cancel)  # type: ignore[attr-defined]
                _dbg("button signals connected")
            except Exception as e:
                _dbg(f"button connect exception: {e!r}")
                raise
            try:
                dlg.exec()  # type: ignore[attr-defined]
            except Exception as e:
                _dbg(f"dlg.exec exception: {e!r}")
                raise
            return
        except Exception:
            pass
        # 无 Qt：直接使用默认参数
        try:
            ctl = getattr(logic, '_ctl', None)
            if ctl is not None:
                payload = ctl.create_instrument(name="NewCo", symbol="NEW001", initial_price=None, float_shares=1_000_000, market_cap=50_000_000)
                sym = payload.get('symbol', 'NEW001')
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
        # 调用逻辑 select_symbol (若存在)
        if self._logic is not None:
            sel = getattr(self._logic, 'select_symbol', None)
            if callable(sel):
                try:
                    sel(symbol)
                except Exception:  # pragma: no cover
                    pass
        # 恢复详情刷新视图（尽量放到 UI 线程）
        try:
            from PySide6.QtCore import QTimer  # type: ignore
            QTimer.singleShot(0, self._refresh_detail)  # type: ignore
        except Exception:
            self._refresh_detail()

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
        if sel:
            self._selected_symbol = sel
        # 确保列表高亮与内部一致
        if self._symbol_list is not None and self._selected_symbol in watch:
            try:
                idx = watch.index(self._selected_symbol)
                self._symbol_list.setCurrentRow(idx)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        # 刷新详情
        self._refresh_detail()


class SymbolDetailPanelAdapter(PanelAdapter):
    """PanelAdapter wrapper for per-symbol detail pages.
    It composes the lightweight SymbolDetailAdapter for actual rendering,
    while providing the standard PanelAdapter contract (bind/widget/refresh).
    """
    def __init__(self):
        super().__init__()
        self._detail = SymbolDetailAdapter()

    def _create_widget(self):  # type: ignore[override]
        return self._detail.widget()

    def _apply_view(self, view: Dict[str, Any]):  # type: ignore[override]
        try:
            if isinstance(view, dict):
                self._detail.apply_detail(view)
        except Exception:
            pass

__all__ = ["MarketPanelAdapter", "SymbolDetailAdapter", "SymbolDetailPanelAdapter"]
