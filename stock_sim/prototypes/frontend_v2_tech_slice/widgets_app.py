"""Qt Widgets + pyqtgraph implementation of the issue #33 slice."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from adapters import SliceAdapter
from benchmarking import BenchmarkSession
from contract import CandidateRow, SliceViewState, TimelineArtifact, UI_STATES


TOKENS = {
    "bg": "#070a0e",
    "surface": "#0d1218",
    "surface2": "#111820",
    "line": "#24303b",
    "text": "#f1f4f7",
    "muted": "#8c98a5",
    "quiet": "#687582",
    "green": "#82dec0",
    "red": "#ff928d",
    "amber": "#e7bd77",
    "blue": "#9fbfff",
}


class CandidateTableModel(QAbstractTableModel):
    HEADERS = (
        "Rank",
        "Candidate",
        "Model",
        "Return",
        "Drawdown",
        "Evidence",
        "Research lock",
        "Scenario",
    )

    def __init__(self) -> None:
        super().__init__()
        self.rows: tuple[CandidateRow, ...] = ()

    def replace_rows(self, rows: tuple[CandidateRow, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row = self.rows[index.row()]
        values = (
            row.rank,
            row.candidate_id,
            row.model,
            f"{row.return_pct:+.2f}%",
            f"{row.drawdown_pct:.2f}%",
            row.evidence_status,
            row.research_lock,
            row.scenario_family,
        )
        if role == Qt.DisplayRole:
            return values[index.column()]
        if role == Qt.TextAlignmentRole and index.column() in {0, 3, 4}:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and index.column() == 5:
            colors = {
                "pass": TOKENS["green"],
                "fail": TOKENS["red"],
                "missing": TOKENS["blue"],
                "warning": TOKENS["amber"],
            }
            return QColor(colors.get(row.evidence_status, TOKENS["muted"]))
        if role == Qt.UserRole:
            return row.candidate_id
        return None


class TechSwitcher(QFrame):
    def __init__(self, request_technology: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("techSwitcher")
        self.setAccessibleName("Technology prototype switcher")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        previous = QPushButton("←")
        previous.setAccessibleName("Previous technology prototype")
        label = QLabel("W — Qt Widgets + QPainter fallback")
        label.setObjectName("switcherLabel")
        evidence = QLabel("same contract · native model/view")
        evidence.setObjectName("switcherEvidence")
        following = QPushButton("→")
        following.setAccessibleName("Next technology prototype")
        previous.clicked.connect(lambda: request_technology("web"))
        following.clicked.connect(lambda: request_technology("qml"))
        layout.addWidget(previous)
        layout.addWidget(label)
        layout.addWidget(evidence)
        layout.addWidget(following)


class TimelinePaintWidget(QWidget):
    def __init__(self, timeline: TimelineArtifact) -> None:
        super().__init__()
        self.timeline = timeline
        self.setMinimumHeight(230)
        self.setAccessibleName("Evidence timeline chart")
        self.setAccessibleDescription(
            "Candidate, baseline, and stress overlays. A sampled data table is available in candidate details."
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(TOKENS["surface"]))
        width = max(1.0, float(self.width()))
        height = max(1.0, float(self.height()))
        painter.setPen(QPen(QColor(TOKENS["line"]), 1.0))
        for fraction in (0.25, 0.5, 0.75):
            y = int(height * fraction)
            painter.drawLine(0, y, int(width), y)
        x, candidate, baseline, stress = self.timeline.display_points()
        minimum = min(candidate.min(), baseline.min(), stress.min())
        maximum = max(candidate.max(), baseline.max(), stress.max())
        span = max(0.001, float(maximum - minimum))
        x_span = max(1.0, float(x[-1] - x[0]))
        for values, color, line_width in (
            (candidate, TOKENS["green"], 1.4),
            (baseline, TOKENS["blue"], 1.0),
            (stress, TOKENS["red"], 1.0),
        ):
            path = QPainterPath()
            path.moveTo(
                0,
                height - ((float(values[0]) - minimum) / span) * height,
            )
            for index in range(1, len(x)):
                px = (float(x[index] - x[0]) / x_span) * width
                py = height - ((float(values[index]) - minimum) / span) * height
                path.lineTo(px, py)
            painter.setPen(QPen(QColor(color), line_width))
            painter.drawPath(path)


class WidgetsSliceWindow(QMainWindow):
    def __init__(
        self,
        *,
        adapter: SliceAdapter,
        timeline: TimelineArtifact,
        benchmark: BenchmarkSession,
        request_technology: Callable[[str], None],
        screenshot_path: Path | None,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self.timeline = timeline
        self.benchmark = benchmark
        self.screenshot_path = screenshot_path
        self.pending_state = adapter.state
        self.pending_event_id = 0
        self.paint_timer = QTimer(self)
        self.paint_timer.setSingleShot(True)
        self.paint_timer.setInterval(0)
        self.paint_timer.timeout.connect(self._render_pending)
        self.setWindowTitle("UTI Diagnostics — Qt Widgets vertical slice prototype")
        self.resize(1280, 800)
        self.setMinimumSize(860, 620)
        self.setAccessibleName("Qt Widgets diagnostic vertical slice")
        self._build_ui(request_technology)
        self._apply_style()
        self.adapter.state_ready.connect(self._on_state)
        self.adapter.start()
        QTimer.singleShot(0, self._mark_usable)
        self.input_probe = QTimer(self)
        self.input_probe.setInterval(250)
        self.input_probe.timeout.connect(
            lambda: self.benchmark.schedule_input_probe(self.table.viewport().update)
        )
        self.input_probe.start()
        QTimer.singleShot(850, self._probe_keyboard)

    def _build_ui(self, request_technology: Callable[[str], None]) -> None:
        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 76)
        root.setSpacing(14)

        top = QHBoxLayout()
        brand = QLabel("UTI Diagnostics")
        brand.setObjectName("brand")
        context = QLabel(
            "Breakout v4.2  /  Liquidity stress × 1.8  /  DGN-24-0719-A"
        )
        context.setObjectName("context")
        runtime = QLabel("● runtime adapter ready")
        runtime.setObjectName("runtime")
        top.addWidget(brand)
        top.addWidget(context)
        top.addStretch(1)
        top.addWidget(runtime)
        root.addLayout(top)

        state_row = QHBoxLayout()
        state_caption = QLabel("PROTOTYPE STATES")
        state_caption.setObjectName("eyebrow")
        state_row.addWidget(state_caption)
        self.state_buttons: dict[str, QPushButton] = {}
        for state in UI_STATES:
            button = QPushButton(state.title())
            button.setCheckable(True)
            button.setAccessibleName(f"Show {state} state")
            button.clicked.connect(
                lambda _checked=False, value=state: self.adapter.set_ui_state(value)
            )
            self.state_buttons[state] = button
            state_row.addWidget(button)
        state_row.addStretch(1)
        root.addLayout(state_row)

        self.banner = QFrame()
        self.banner.setObjectName("statusBanner")
        banner_layout = QHBoxLayout(self.banner)
        banner_copy = QVBoxLayout()
        self.state_label = QLabel()
        self.state_label.setObjectName("eyebrow")
        self.headline = QLabel()
        self.headline.setObjectName("headline")
        self.detail = QLabel()
        self.detail.setObjectName("detail")
        banner_copy.addWidget(self.state_label)
        banner_copy.addWidget(self.headline)
        banner_copy.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(250)
        self.progress.setAccessibleName("Campaign progress")
        banner_layout.addLayout(banner_copy, 1)
        banner_layout.addWidget(self.progress)
        root.addWidget(self.banner)

        controls = QHBoxLayout()
        question = QLabel("Can the apparent return lead survive hidden and fee stress?")
        question.setObjectName("question")
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter 50 candidates…  Ctrl+K")
        self.filter.setAccessibleName("Filter candidates")
        self.filter.setClearButtonEnabled(True)
        controls.addWidget(question, 1)
        controls.addWidget(self.filter)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        table_panel = QFrame()
        table_panel.setObjectName("panel")
        table_layout = QVBoxLayout(table_panel)
        table_header = QLabel("COMPARISON SIGNAL · NOT A CONCLUSION")
        table_header.setObjectName("eyebrow")
        table_layout.addWidget(table_header)
        self.model = CandidateTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAccessibleName("50 candidate comparison table")
        self.table.doubleClicked.connect(self._open_details)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        table_layout.addWidget(self.table)
        splitter.addWidget(table_panel)

        chart_panel = QFrame()
        chart_panel.setObjectName("panel")
        chart_layout = QVBoxLayout(chart_panel)
        chart_header = QHBoxLayout()
        title_block = QVBoxLayout()
        chart_eyebrow = QLabel("100K-POINT EVIDENCE TIMELINE · 3 OVERLAYS")
        chart_eyebrow.setObjectName("eyebrow")
        chart_title = QLabel("Candidate vs baseline under stress")
        chart_title.setObjectName("sectionTitle")
        title_block.addWidget(chart_eyebrow)
        title_block.addWidget(chart_title)
        self.frame_budget = QLabel("paint cap 20 fps")
        self.frame_budget.setObjectName("metric")
        chart_header.addLayout(title_block)
        chart_header.addStretch(1)
        chart_header.addWidget(self.frame_budget)
        chart_layout.addLayout(chart_header)
        self.chart = TimelinePaintWidget(self.timeline)
        chart_layout.addWidget(self.chart)
        self.chart_summary = QLabel()
        self.chart_summary.setObjectName("detail")
        self.chart_summary.setWordWrap(True)
        chart_layout.addWidget(self.chart_summary)
        splitter.addWidget(chart_panel)
        splitter.setSizes([620, 620])
        root.addWidget(splitter, 1)

        boundary = QLabel(
            "READ-ONLY PROTOTYPE · no Create/Start/Stop/Evaluate, gate override, promotion, or manual order capability"
        )
        boundary.setObjectName("boundary")
        root.addWidget(boundary)

        switcher = TechSwitcher(request_technology)
        switcher.setParent(central)
        switcher.adjustSize()
        switcher.move(
            max(12, (central.width() - switcher.width()) // 2),
            max(12, central.height() - switcher.height() - 12),
        )
        switcher.raise_()
        self.switcher = switcher
        self.setCentralWidget(central)

        self.detail_dock = QDockWidget("Candidate evidence detail", self)
        self.detail_dock.setObjectName("candidateDetails")
        self.detail_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.detail_dock.setAccessibleName("Candidate evidence details")
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        self.detail_title = QLabel("Select a candidate")
        self.detail_title.setObjectName("sectionTitle")
        self.detail_copy = QLabel(
            "Claim, support, contradiction, provenance, and next action remain read-only."
        )
        self.detail_copy.setWordWrap(True)
        self.semantic_table = QTableWidget(0, 4)
        self.semantic_table.setHorizontalHeaderLabels(
            ["Step", "Candidate", "Baseline", "Stress"]
        )
        self.semantic_table.setAccessibleName("Evidence timeline text and table equivalent")
        for row_index, row in enumerate(self.timeline.semantic_rows()):
            self.semantic_table.insertRow(row_index)
            for column, key in enumerate(("step", "candidate", "baseline", "stress")):
                self.semantic_table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem(str(row[key])),
                )
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_copy)
        detail_layout.addWidget(self.semantic_table)
        self.detail_dock.setWidget(detail_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.detail_dock)
        self.detail_dock.hide()

        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.filter.setFocus)
        QShortcut(QKeySequence(Qt.Key_Return), self.table, activated=self._open_details)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.detail_dock.hide)
        QShortcut(
            QKeySequence(Qt.Key_Left),
            self,
            activated=lambda: request_technology("web"),
        )
        QShortcut(
            QKeySequence(Qt.Key_Right),
            self,
            activated=lambda: request_technology("qml"),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "switcher"):
            self.switcher.adjustSize()
            self.switcher.move(
                max(12, (self.centralWidget().width() - self.switcher.width()) // 2),
                max(12, self.centralWidget().height() - self.switcher.height() - 12),
            )

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            * {{
                font-family: "Segoe UI";
                font-size: 10px;
                color: {TOKENS["text"]};
            }}
            QMainWindow, QWidget#central {{
                background: {TOKENS["bg"]};
            }}
            QLabel#brand {{
                font-size: 16px;
                font-weight: 700;
                color: {TOKENS["green"]};
            }}
            QLabel#context, QLabel#detail {{
                color: {TOKENS["muted"]};
            }}
            QLabel#runtime {{
                color: {TOKENS["green"]};
            }}
            QLabel#eyebrow {{
                color: {TOKENS["quiet"]};
                font-size: 9px;
                font-weight: 700;
            }}
            QLabel#headline {{
                font-size: 16px;
                font-weight: 650;
            }}
            QLabel#question {{
                font-family: Georgia;
                font-size: 22px;
            }}
            QLabel#sectionTitle {{
                font-family: Georgia;
                font-size: 17px;
            }}
            QLabel#metric {{
                color: {TOKENS["amber"]};
                font-family: Consolas;
            }}
            QLabel#boundary {{
                color: {TOKENS["quiet"]};
                font-size: 9px;
            }}
            QFrame#statusBanner, QFrame#panel {{
                background: {TOKENS["surface"]};
                border: 1px solid {TOKENS["line"]};
                border-radius: 7px;
            }}
            QLineEdit {{
                min-width: 260px;
                border: 1px solid {TOKENS["line"]};
                border-radius: 6px;
                background: {TOKENS["surface2"]};
                padding: 8px 10px;
                selection-background-color: {TOKENS["blue"]};
            }}
            QPushButton {{
                border: 1px solid {TOKENS["line"]};
                border-radius: 5px;
                background: {TOKENS["surface"]};
                padding: 6px 9px;
                color: {TOKENS["muted"]};
            }}
            QPushButton:pressed, QPushButton:checked {{
                border-color: {TOKENS["green"]};
                background: #13241f;
                color: {TOKENS["green"]};
            }}
            QTableView, QTableWidget {{
                border: 0;
                background: {TOKENS["surface"]};
                alternate-background-color: {TOKENS["surface2"]};
                gridline-color: {TOKENS["line"]};
                selection-background-color: #183029;
                selection-color: {TOKENS["text"]};
            }}
            QHeaderView::section {{
                border: 0;
                border-bottom: 1px solid {TOKENS["line"]};
                background: {TOKENS["surface"]};
                padding: 7px;
                color: {TOKENS["quiet"]};
                font-size: 9px;
            }}
            QProgressBar {{
                height: 8px;
                border: 0;
                background: {TOKENS["line"]};
                text-align: center;
                color: transparent;
            }}
            QProgressBar::chunk {{
                background: {TOKENS["green"]};
            }}
            QFrame#techSwitcher {{
                background: #f2efe8;
                border: 1px solid #c5c0b6;
                border-radius: 18px;
            }}
            QFrame#techSwitcher QLabel {{
                background: transparent;
                color: #1a2026;
            }}
            QLabel#switcherLabel {{
                font-family: Consolas;
                font-weight: 700;
            }}
            QLabel#switcherEvidence {{
                color: #67717b;
            }}
            QFrame#techSwitcher QPushButton {{
                border: 0;
                background: transparent;
                color: #1a2026;
                padding: 4px 8px;
            }}
            QDockWidget {{
                color: {TOKENS["text"]};
                background: {TOKENS["surface"]};
            }}
            """
        )

    def _on_state(
        self,
        state: SliceViewState,
        event_id: int,
        emitted_ns: int,
    ) -> None:
        self.benchmark.source(event_id, emitted_ns)
        if state.revision < self.pending_state.revision:
            return
        self.pending_state = state
        self.pending_event_id = event_id
        if not self.paint_timer.isActive():
            self.paint_timer.start()

    def _render_pending(self) -> None:
        state = self.pending_state
        event_id = self.pending_event_id
        self.state_label.setText(
            f"{state.ui_state.upper()} · revision {state.revision} · {state.freshness}"
        )
        self.headline.setText(state.headline)
        self.detail.setText(state.detail)
        self.progress.setValue(state.progress_pct)
        self.progress.setFormat(
            f"{state.progress_pct}% · {state.completed_replicas}/{state.total_replicas}"
        )
        for name, button in self.state_buttons.items():
            button.setChecked(name == state.ui_state)
        self.model.replace_rows(state.candidates)
        if state.candidates:
            self.table.selectRow(0)
        candidate = self.timeline.candidate
        baseline = self.timeline.baseline
        stress = self.timeline.stress
        self.chart_summary.setText(
            "Text equivalent: candidate "
            f"{candidate.min():.2f}–{candidate.max():.2f}; baseline "
            f"{baseline.min():.2f}–{baseline.max():.2f}; stress "
            f"{stress.min():.2f}–{stress.max():.2f}; first fee breakpoint 1.6×."
        )
        self.chart.update()
        QTimer.singleShot(0, lambda: self.benchmark.painted(event_id))

    def _open_details(self, *_args) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        source_index = self.proxy.mapToSource(index)
        row = self.model.rows[source_index.row()]
        self.detail_title.setText(f"{row.candidate_id} · {row.evidence_status}")
        self.detail_copy.setText(
            f"{row.scenario_family}. Return {row.return_pct:+.2f}% does not override "
            f"the {row.research_lock} Research Acceptance Lock. Source run, artifact "
            "hash, failure_type, blocking_metrics, and next_action remain traceable."
        )
        self.detail_dock.show()
        self.detail_dock.raise_()

    def _mark_usable(self) -> None:
        self.paint_timer.stop()
        self._render_pending()
        self.benchmark.mark_usable()
        if self.screenshot_path is not None:
            QTimer.singleShot(600, self._save_screenshot)

    def _save_screenshot(self) -> None:
        assert self.screenshot_path is not None
        self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.grab().save(str(self.screenshot_path))

    def _probe_keyboard(self) -> None:
        self.activateWindow()
        self.setFocus()
        QTest.keyClick(self, Qt.Key_K, Qt.ControlModifier)
        filter_focused = self.filter.hasFocus()
        self.table.setFocus()
        self.table.selectRow(0)
        QTest.keyClick(self.table, Qt.Key_Down)
        moved = self.table.currentIndex().row() == 1
        QTest.keyClick(self.table, Qt.Key_Return)
        details_opened = self.detail_dock.isVisible()
        QTest.keyClick(self, Qt.Key_Escape)
        details_closed = not self.detail_dock.isVisible()
        self.benchmark.set_keyboard_probe(
            {
                "ctrl_k_focus": filter_focused,
                "arrow_navigation": moved,
                "enter_details": details_opened,
                "escape_close": details_closed,
            }
        )

    def closeEvent(self, event) -> None:
        self.input_probe.stop()
        self.adapter.stop()
        super().closeEvent(event)


def run_widgets(
    *,
    app: QApplication,
    adapter: SliceAdapter,
    timeline: TimelineArtifact,
    benchmark: BenchmarkSession,
    request_technology: Callable[[str], None],
    screenshot_path: Path | None,
) -> WidgetsSliceWindow:
    window = WidgetsSliceWindow(
        adapter=adapter,
        timeline=timeline,
        benchmark=benchmark,
        request_technology=request_technology,
        screenshot_path=screenshot_path,
    )
    window.show()
    return window
