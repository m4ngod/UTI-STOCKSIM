"""Embedded WebEngine implementation of the issue #33 vertical slice."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from adapters import SliceAdapter
from benchmarking import BenchmarkSession
from contract import SliceViewState, TimelineArtifact, UI_STATES, state_to_dict


class WebSliceBridge(QObject):
    stateReady = Signal(str, int)
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
        self.pending_state = adapter.state
        self.pending_event_id = 0
        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(0)
        self._paint_timer.timeout.connect(self._publish_pending)
        self.adapter.state_ready.connect(self._on_state)

    @Property(str, constant=True)
    def initialPayload(self) -> str:
        x, candidate, baseline, stress = self.timeline.display_points()
        payload = state_to_dict(self.adapter.state)
        payload["stateNames"] = list(UI_STATES)
        payload["timeline"] = {
            "x": x.tolist(),
            "candidate": [round(float(value), 4) for value in candidate],
            "baseline": [round(float(value), 4) for value in baseline],
            "stress": [round(float(value), 4) for value in stress],
            "sourcePointCount": self.timeline.point_count,
        }
        payload["semanticRows"] = self.timeline.semantic_rows()
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @Slot()
    def ready(self) -> None:
        self.benchmark.mark_usable()
        self.adapter.start()

    @Slot(int)
    def reportPaint(self, event_id: int) -> None:
        self.benchmark.painted(event_id)

    @Slot(str)
    def setState(self, state: str) -> None:
        if state in UI_STATES:
            self.adapter.set_ui_state(state)

    @Slot(str)
    def chooseTechnology(self, technology: str) -> None:
        self.requestTechnology.emit(technology)

    def stop(self) -> None:
        self.adapter.stop()

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
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    def _publish_pending(self) -> None:
        self.stateReady.emit(
            json.dumps(
                state_to_dict(self.pending_state),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            self.pending_event_id,
        )


def run_web(
    *,
    app: QApplication,
    adapter: SliceAdapter,
    timeline: TimelineArtifact,
    benchmark: BenchmarkSession,
    request_technology: Callable[[str], None],
    screenshot_path: Path | None,
    html_path: Path,
) -> tuple[QWebEngineView, WebSliceBridge, QWebChannel]:
    view = QWebEngineView()
    view.setWindowTitle("UTI Diagnostics — embedded Web UI vertical slice prototype")
    view.resize(1280, 800)
    view.setMinimumSize(860, 620)
    view.setAccessibleName("Embedded Web diagnostic vertical slice")
    bridge = WebSliceBridge(
        adapter=adapter,
        benchmark=benchmark,
        timeline=timeline,
    )
    bridge.requestTechnology.connect(request_technology)
    channel = QWebChannel(view.page())
    channel.registerObject("sliceBridge", bridge)
    view.page().setWebChannel(channel)

    def loaded(ok: bool) -> None:
        if not ok:
            raise RuntimeError(f"Unable to load Web prototype: {html_path}")
        if screenshot_path is not None:
            QTimer.singleShot(
                1_000,
                lambda: (
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True),
                    view.grab().save(str(screenshot_path)),
                ),
            )

    view.loadFinished.connect(loaded)
    view.load(QUrl.fromLocalFile(str(html_path)))
    view.show()
    input_probe = QTimer(bridge)
    input_probe.setInterval(250)

    def probe_input() -> None:
        started_ns = time.perf_counter_ns()
        view.page().runJavaScript(
            "document.querySelector('#filter').getAttribute('aria-label')",
            lambda _result: benchmark.input_latencies.append(
                (time.perf_counter_ns() - started_ns) / 1_000_000.0
            ),
        )

    input_probe.timeout.connect(probe_input)
    input_probe.start()

    def probe_keyboard() -> None:
        script = """
        (() => {
          try {
            const filter = document.querySelector('#filter');
            filter.blur();
            document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true}));
            const ctrlK = document.activeElement === filter;
            const first = document.querySelector('#candidate-rows tr');
            first?.focus();
            first?.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}));
            const moved = document.querySelector('#candidate-rows tr[aria-selected="true"]') !== first;
            const selected = document.querySelector('#candidate-rows tr[aria-selected="true"]');
            selected?.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
            const opened = document.querySelector('#details').open;
            document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
            const closed = !document.querySelector('#details').open;
            return JSON.stringify({ctrl_k_focus: ctrlK, arrow_navigation: moved, enter_details: opened, escape_close: closed});
          } catch (error) {
            return JSON.stringify({error: String(error)});
          }
        })()
        """

        def record_probe(result) -> None:
            try:
                payload = json.loads(result) if isinstance(result, str) else result
            except json.JSONDecodeError:
                payload = None
            if not isinstance(payload, dict) or payload.get("error"):
                benchmark.set_keyboard_probe(
                    {
                        "ctrl_k_focus": False,
                        "arrow_navigation": False,
                        "enter_details": False,
                        "escape_close": False,
                    }
                )
                return
            benchmark.set_keyboard_probe(
                {key: bool(value) for key, value in payload.items()}
            )

        view.page().runJavaScript(
            script,
            record_probe,
        )

    QTimer.singleShot(850, probe_keyboard)
    app.aboutToQuit.connect(bridge.stop)
    return view, bridge, channel
