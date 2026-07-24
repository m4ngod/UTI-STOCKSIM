"""Shared measurement collector for the three issue #33 views."""

from __future__ import annotations

import ctypes
import json
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _working_set_mb() -> float:
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = wintypes.HANDLE
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    get_process_memory_info.restype = wintypes.BOOL
    handle = get_current_process()
    ok = get_process_memory_info(
        handle,
        ctypes.byref(counters),
        counters.cb,
    )
    if not ok:
        return 0.0
    return counters.WorkingSetSize / (1024.0 * 1024.0)


@dataclass(slots=True)
class BenchmarkResult:
    technology: str
    adapter: str
    ui_state: str
    startup_ms: float
    duration_ms: float
    source_events: int
    visual_updates: int
    coalesced_updates: int
    event_to_visible_p50_ms: float | None
    event_to_visible_p95_ms: float | None
    event_to_visible_max_ms: float | None
    frame_interval_p50_ms: float | None
    frame_interval_p95_ms: float | None
    main_thread_stalls_over_50ms: int
    input_latency_p50_ms: float | None
    input_latency_p95_ms: float | None
    idle_memory_mb: float
    peak_memory_mb: float
    chart_engine: str
    chart_source_points: int
    chart_visual_points: int
    overlays: int
    keyboard_path: str
    keyboard_probe: dict[str, bool]
    semantic_chart_equivalent: str


class BenchmarkSession(QObject):
    finished = Signal(object)

    def __init__(
        self,
        *,
        technology: str,
        adapter: str,
        ui_state: str,
        started_ns: int,
        duration_ms: int,
        output_path: Path | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.technology = technology
        self.adapter = adapter
        self.ui_state = ui_state
        self.started_ns = started_ns
        self.duration_ms = duration_ms
        self.output_path = output_path
        self.startup_ms = 0.0
        self.source_events = 0
        self.visual_updates = 0
        self.pending: dict[int, int] = {}
        self.painted_event_ids: set[int] = set()
        self.event_latencies: list[float] = []
        self.frame_intervals: list[float] = []
        self.input_latencies: list[float] = []
        self.memory_samples: list[float] = []
        self.keyboard_probe: dict[str, bool] = {}
        self.main_thread_stalls = 0
        self._last_heartbeat_ns: int | None = None
        self._last_paint_ns: int | None = None
        self._memory_timer = QTimer(self)
        self._memory_timer.setInterval(100)
        self._memory_timer.timeout.connect(self._sample_memory)
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.timeout.connect(self.finish)
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(10)
        self._heartbeat_timer.timeout.connect(self._heartbeat)

    def mark_usable(self) -> None:
        if self.startup_ms == 0.0:
            self.startup_ms = (time.perf_counter_ns() - self.started_ns) / 1_000_000.0
            self._sample_memory()
            self._memory_timer.start()
            self._last_heartbeat_ns = time.perf_counter_ns()
            self._heartbeat_timer.start()
            if self.duration_ms > 0:
                self._finish_timer.start(self.duration_ms)

    def source(self, event_id: int, emitted_ns: int) -> None:
        self.source_events += 1
        self.pending[event_id] = emitted_ns
        if len(self.pending) > 500:
            oldest = sorted(self.pending)[:-500]
            for key in oldest:
                self.pending.pop(key, None)

    def painted(self, event_id: int) -> None:
        if event_id <= 0 or event_id in self.painted_event_ids:
            return
        self.painted_event_ids.add(event_id)
        now_ns = time.perf_counter_ns()
        emitted_ns = self.pending.pop(event_id, None)
        if emitted_ns is not None:
            self.event_latencies.append((now_ns - emitted_ns) / 1_000_000.0)
        if self._last_paint_ns is not None:
            self.frame_intervals.append((now_ns - self._last_paint_ns) / 1_000_000.0)
        self._last_paint_ns = now_ns
        self.visual_updates += 1

    def schedule_input_probe(self, callback) -> None:
        started = time.perf_counter_ns()

        def invoke() -> None:
            callback()
            self.input_latencies.append(
                (time.perf_counter_ns() - started) / 1_000_000.0
            )

        QTimer.singleShot(0, invoke)

    def set_keyboard_probe(self, result: dict[str, bool]) -> None:
        self.keyboard_probe = dict(result)

    def _sample_memory(self) -> None:
        self.memory_samples.append(_working_set_mb())

    def _heartbeat(self) -> None:
        now_ns = time.perf_counter_ns()
        if self._last_heartbeat_ns is not None:
            interval_ms = (now_ns - self._last_heartbeat_ns) / 1_000_000.0
            if interval_ms > 50.0:
                self.main_thread_stalls += 1
        self._last_heartbeat_ns = now_ns

    def finish(self) -> None:
        self._memory_timer.stop()
        self._heartbeat_timer.stop()
        self._sample_memory()
        idle_memory = self.memory_samples[0] if self.memory_samples else 0.0
        peak_memory = max(self.memory_samples) if self.memory_samples else 0.0
        result = BenchmarkResult(
            technology=self.technology,
            adapter=self.adapter,
            ui_state=self.ui_state,
            startup_ms=round(self.startup_ms, 3),
            duration_ms=float(self.duration_ms),
            source_events=self.source_events,
            visual_updates=self.visual_updates,
            coalesced_updates=max(0, self.source_events - self.visual_updates),
            event_to_visible_p50_ms=_percentile(self.event_latencies, 50),
            event_to_visible_p95_ms=_percentile(self.event_latencies, 95),
            event_to_visible_max_ms=max(self.event_latencies)
            if self.event_latencies
            else None,
            frame_interval_p50_ms=_percentile(self.frame_intervals, 50),
            frame_interval_p95_ms=_percentile(self.frame_intervals, 95),
            main_thread_stalls_over_50ms=self.main_thread_stalls,
            input_latency_p50_ms=_percentile(self.input_latencies, 50),
            input_latency_p95_ms=_percentile(self.input_latencies, 95),
            idle_memory_mb=round(idle_memory, 3),
            peak_memory_mb=round(peak_memory, 3),
            chart_engine={
                "widgets": "QPainter fallback; pyqtgraph compatibility probe blocked",
                "qml": "QQuickPaintedItem",
                "web": "Canvas 2D inside QWebEngineView",
            }.get(self.technology, "unknown"),
            chart_source_points=100_000,
            chart_visual_points=4_000,
            overlays=3,
            keyboard_path="Ctrl+K -> filter -> arrows -> Enter detail -> Escape -> state",
            keyboard_probe=self.keyboard_probe,
            semantic_chart_equivalent="12-row sampled table + textual min/max/breakpoint summary",
        )
        payload = asdict(result)
        for key, value in list(payload.items()):
            if isinstance(value, float):
                payload[key] = round(value, 3)
        if self.output_path is not None:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self.finished.emit(payload)
