"""Qt Quick/QML implementation of the issue #33 vertical slice."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtTest import QTest

from adapters import SliceAdapter
from benchmarking import BenchmarkSession
from contract import CandidateRow, SliceViewState, TimelineArtifact, UI_STATES, build_timeline


class CandidateListModel(QAbstractListModel):
    RankRole = Qt.UserRole + 1
    CandidateRole = RankRole + 1
    ModelRole = CandidateRole + 1
    ReturnRole = ModelRole + 1
    DrawdownRole = ReturnRole + 1
    EvidenceRole = DrawdownRole + 1
    LockRole = EvidenceRole + 1
    ScenarioRole = LockRole + 1

    def __init__(self) -> None:
        super().__init__()
        self._all_rows: tuple[CandidateRow, ...] = ()
        self._rows: list[CandidateRow] = []
        self._filter = ""
        self._sort_key = "rank"
        self._descending = False

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.RankRole: b"rank",
            self.CandidateRole: b"candidateId",
            self.ModelRole: b"modelName",
            self.ReturnRole: b"returnText",
            self.DrawdownRole: b"drawdownText",
            self.EvidenceRole: b"evidenceStatus",
            self.LockRole: b"researchLock",
            self.ScenarioRole: b"scenarioFamily",
        }

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def data(self, index: QModelIndex, role: int):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        return {
            self.RankRole: row.rank,
            self.CandidateRole: row.candidate_id,
            self.ModelRole: row.model,
            self.ReturnRole: f"{row.return_pct:+.2f}%",
            self.DrawdownRole: f"{row.drawdown_pct:.2f}%",
            self.EvidenceRole: row.evidence_status,
            self.LockRole: row.research_lock,
            self.ScenarioRole: row.scenario_family,
        }.get(role)

    def replace_rows(self, rows: tuple[CandidateRow, ...]) -> None:
        self._all_rows = rows
        self._rebuild()

    @Slot(str)
    def setFilter(self, value: str) -> None:
        self._filter = value.casefold()
        self._rebuild()

    @Slot(str)
    def sortBy(self, value: str) -> None:
        if self._sort_key == value:
            self._descending = not self._descending
        else:
            self._sort_key = value
            self._descending = False
        self._rebuild()

    @Slot(int, result="QVariant")
    def rowObject(self, index: int):
        if index < 0 or index >= len(self._rows):
            return {}
        row = self._rows[index]
        return {
            "candidateId": row.candidate_id,
            "evidenceStatus": row.evidence_status,
            "scenarioFamily": row.scenario_family,
            "returnText": f"{row.return_pct:+.2f}%",
            "researchLock": row.research_lock,
        }

    def _rebuild(self) -> None:
        rows = [
            row
            for row in self._all_rows
            if not self._filter
            or self._filter
            in " ".join(
                (
                    row.candidate_id,
                    row.model,
                    row.evidence_status,
                    row.scenario_family,
                )
            ).casefold()
        ]
        accessors = {
            "rank": lambda row: row.rank,
            "candidate": lambda row: row.candidate_id,
            "return": lambda row: row.return_pct,
            "evidence": lambda row: row.evidence_status,
        }
        rows.sort(
            key=accessors.get(self._sort_key, accessors["rank"]),
            reverse=self._descending,
        )
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class EvidenceTimelineItem(QQuickPaintedItem):
    """A deliberately simple QML chart candidate over the shared 100k artifact."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(False)
        self._timeline = build_timeline()

    def paint(self, painter: QPainter) -> None:
        width = max(1.0, self.width())
        height = max(1.0, self.height())
        painter.fillRect(0, 0, int(width), int(height), QColor("#0d1218"))
        x, candidate, baseline, stress = self._timeline.display_points()
        minimum = min(candidate.min(), baseline.min(), stress.min())
        maximum = max(candidate.max(), baseline.max(), stress.max())
        span = max(0.001, float(maximum - minimum))
        x_span = max(1.0, float(x[-1] - x[0]))
        painter.setPen(QPen(QColor("#24303b"), 1.0))
        for fraction in (0.25, 0.5, 0.75):
            y = height * fraction
            painter.drawLine(0, int(y), int(width), int(y))
        for values, color, line_width in (
            (candidate, "#82dec0", 1.4),
            (baseline, "#9fbfff", 1.0),
            (stress, "#ff928d", 1.0),
        ):
            path = QPainterPath()
            first_x = (float(x[0] - x[0]) / x_span) * width
            first_y = height - ((float(values[0]) - minimum) / span) * height
            path.moveTo(first_x, first_y)
            for index in range(1, len(x)):
                px = (float(x[index] - x[0]) / x_span) * width
                py = height - ((float(values[index]) - minimum) / span) * height
                path.lineTo(px, py)
            painter.setPen(QPen(QColor(color), line_width))
            painter.drawPath(path)


class SliceBackend(QObject):
    stateChanged = Signal()
    detailsChanged = Signal()
    requestTechnology = Signal(str)

    def __init__(
        self,
        *,
        adapter: SliceAdapter,
        benchmark: BenchmarkSession,
        timeline: TimelineArtifact,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self.benchmark = benchmark
        self.timeline = timeline
        self.model = CandidateListModel()
        self._state = adapter.state
        self._pending_state = adapter.state
        self._pending_event_id = 0
        self._paint_event_id = 0
        self._details_open = False
        self._details_title = "Select a candidate"
        self._details_copy = ""
        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(0)
        self._paint_timer.timeout.connect(self._render_pending)
        self.adapter.state_ready.connect(self._on_state)

    @Property(QObject, constant=True)
    def candidates(self) -> QObject:
        return self.model

    @Property("QStringList", constant=True)
    def stateNames(self) -> list[str]:
        return list(UI_STATES)

    @Property(str, notify=stateChanged)
    def stateName(self) -> str:
        return self._state.ui_state

    @Property(str, notify=stateChanged)
    def revisionText(self) -> str:
        return f"revision {self._state.revision} · {self._state.freshness}"

    @Property(str, notify=stateChanged)
    def headline(self) -> str:
        return self._state.headline

    @Property(str, notify=stateChanged)
    def detail(self) -> str:
        return self._state.detail

    @Property(int, notify=stateChanged)
    def progress(self) -> int:
        return self._state.progress_pct

    @Property(str, notify=stateChanged)
    def replicaText(self) -> str:
        return (
            f"{self._state.completed_replicas} / {self._state.total_replicas} replicas"
        )

    @Property(str, notify=stateChanged)
    def chartSummary(self) -> str:
        values = self.timeline
        return (
            "Text equivalent: candidate "
            f"{values.candidate.min():.2f}–{values.candidate.max():.2f}; baseline "
            f"{values.baseline.min():.2f}–{values.baseline.max():.2f}; stress "
            f"{values.stress.min():.2f}–{values.stress.max():.2f}; first fee breakpoint 1.6×."
        )

    @Property(bool, notify=detailsChanged)
    def detailsOpen(self) -> bool:
        return self._details_open

    @Property(str, notify=detailsChanged)
    def detailsTitle(self) -> str:
        return self._details_title

    @Property(str, notify=detailsChanged)
    def detailsCopy(self) -> str:
        return self._details_copy

    @Slot(str)
    def setState(self, state: str) -> None:
        if state in UI_STATES:
            self.adapter.set_ui_state(state)

    @Slot(str)
    def filterCandidates(self, value: str) -> None:
        self.model.setFilter(value)

    @Slot(str)
    def sortCandidates(self, key: str) -> None:
        self.model.sortBy(key)

    @Slot(int)
    def openDetails(self, index: int) -> None:
        row = self.model.rowObject(index)
        if not row:
            return
        self._details_title = f"{row['candidateId']} · {row['evidenceStatus']}"
        self._details_copy = (
            f"{row['scenarioFamily']}. Return {row['returnText']} does not override "
            f"the {row['researchLock']} Research Acceptance Lock. Source run, artifact "
            "hash, failure_type, blocking_metrics, and next_action remain traceable."
        )
        self._details_open = True
        self.detailsChanged.emit()

    @Slot()
    def closeDetails(self) -> None:
        if self._details_open:
            self._details_open = False
            self.detailsChanged.emit()

    @Slot(str)
    def chooseTechnology(self, technology: str) -> None:
        self.requestTechnology.emit(technology)

    def start(self) -> None:
        self.adapter.start()

    def stop(self) -> None:
        self.adapter.stop()

    def after_rendering(self) -> None:
        if self._paint_event_id:
            self.benchmark.painted(self._paint_event_id)
            self._paint_event_id = 0

    def _on_state(
        self,
        state: SliceViewState,
        event_id: int,
        emitted_ns: int,
    ) -> None:
        self.benchmark.source(event_id, emitted_ns)
        if state.revision < self._pending_state.revision:
            return
        self._pending_state = state
        self._pending_event_id = event_id
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    def _render_pending(self) -> None:
        self._state = self._pending_state
        self._paint_event_id = self._pending_event_id
        self.model.replace_rows(self._state.candidates)
        self.stateChanged.emit()


def run_qml(
    *,
    app: QGuiApplication,
    adapter: SliceAdapter,
    timeline: TimelineArtifact,
    benchmark: BenchmarkSession,
    request_technology: Callable[[str], None],
    screenshot_path: Path | None,
    qml_path: Path,
) -> tuple[QQmlApplicationEngine, SliceBackend]:
    qmlRegisterType(EvidenceTimelineItem, "UTI.Prototype", 1, 0, "EvidenceTimeline")
    backend = SliceBackend(adapter=adapter, benchmark=benchmark, timeline=timeline)
    backend.requestTechnology.connect(request_technology)
    engine = QQmlApplicationEngine()
    load_errors: list[str] = []
    engine.warnings.connect(
        lambda warnings: load_errors.extend(error.toString() for error in warnings)
    )
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        details = "\n".join(load_errors) or "No QQmlEngine warning was emitted."
        raise RuntimeError(f"Unable to load QML prototype: {qml_path}\n{details}")
    window = engine.rootObjects()[0]
    window.afterRendering.connect(backend.after_rendering, Qt.QueuedConnection)
    backend.start()

    def mark_usable() -> None:
        benchmark.mark_usable()
        if screenshot_path is not None:
            QTimer.singleShot(
                700,
                lambda: (
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True),
                    window.grabWindow().save(str(screenshot_path)),
                ),
            )

    QTimer.singleShot(0, mark_usable)

    def probe_keyboard() -> None:
        filter_item = window.findChild(QObject, "filterField")
        list_item = window.findChild(QObject, "candidateList")
        if filter_item is None or list_item is None:
            benchmark.set_keyboard_probe(
                {
                    "ctrl_k_focus": False,
                    "arrow_navigation": False,
                    "enter_details": False,
                    "escape_close": False,
                }
            )
            return
        window.requestActivate()
        QTest.keyClick(window, Qt.Key_K, Qt.ControlModifier)
        filter_focused = bool(filter_item.property("activeFocus"))
        list_item.forceActiveFocus()
        list_item.setProperty("currentIndex", 0)
        QTest.keyClick(window, Qt.Key_Down)
        moved = int(list_item.property("currentIndex")) == 1
        QTest.keyClick(window, Qt.Key_Return)
        details_opened = backend.detailsOpen
        QTest.keyClick(window, Qt.Key_Escape)
        details_closed = not backend.detailsOpen
        benchmark.set_keyboard_probe(
            {
                "ctrl_k_focus": filter_focused,
                "arrow_navigation": moved,
                "enter_details": details_opened,
                "escape_close": details_closed,
            }
        )

    QTimer.singleShot(850, probe_keyboard)
    input_probe = QTimer(backend)
    input_probe.setInterval(250)
    input_probe.timeout.connect(
        lambda: benchmark.schedule_input_probe(lambda: backend.model.rowCount())
    )
    input_probe.start()
    app.aboutToQuit.connect(backend.stop)
    return engine, backend
