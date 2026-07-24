"""Fault/reconnect probe for the three throwaway issue #33 candidates."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROTOTYPE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROTOTYPE_ROOT.parents[1]
for candidate in (str(PROTOTYPE_ROOT), str(REPOSITORY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-software-rasterizer --no-sandbox",
)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from adapters import RuntimeEventBridgeAdapter
from benchmarking import BenchmarkSession
from contract import build_timeline
from qml_app import run_qml
from web_app import run_web
from widgets_app import run_widgets


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("technology", choices=("widgets", "qml", "web"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    adapter = RuntimeEventBridgeAdapter("completed")
    timeline = build_timeline()
    benchmark = BenchmarkSession(
        technology=args.technology,
        adapter="runtime",
        ui_state="completed",
        started_ns=time.perf_counter_ns(),
        duration_ms=0,
        output_path=None,
    )
    events: list[dict[str, Any]] = []
    adapter.state_ready.connect(
        lambda state, event_id, _emitted_ns: events.append(
            {
                "event_id": event_id,
                "revision": state.revision,
                "ui_state": state.ui_state,
            }
        )
    )
    load_results: list[bool] = []
    keep_alive: Any
    view: Any = None
    backend: Any = None

    if args.technology == "widgets":
        view = run_widgets(
            app=app,
            adapter=adapter,
            timeline=timeline,
            benchmark=benchmark,
            request_technology=lambda _technology: None,
            screenshot_path=None,
        )
        keep_alive = view
    elif args.technology == "qml":
        engine, backend = run_qml(
            app=app,
            adapter=adapter,
            timeline=timeline,
            benchmark=benchmark,
            request_technology=lambda _technology: None,
            screenshot_path=None,
            qml_path=PROTOTYPE_ROOT / "qml" / "Main.qml",
        )
        keep_alive = (engine, backend)
    else:
        view, backend, channel = run_web(
            app=app,
            adapter=adapter,
            timeline=timeline,
            benchmark=benchmark,
            request_technology=lambda _technology: None,
            screenshot_path=None,
            html_path=PROTOTYPE_ROOT / "web" / "index.html",
        )
        view.loadFinished.connect(load_results.append)
        keep_alive = (view, backend, channel)

    result: dict[str, Any] = {
        "technology": args.technology,
        "adapter": "runtime EventBridge",
        "disconnect_ui_observed": False,
        "recovered_ui_observed": False,
        "renderer_reloaded": args.technology != "web",
    }

    def read_ui_state(callback) -> None:
        if args.technology == "widgets":
            callback(view.state_label.text().split(" · ", 1)[0].lower())
        elif args.technology == "qml":
            callback(backend.stateName)
        else:
            view.page().runJavaScript(
                "document.querySelector('#state-label')?.textContent?.split(' · ')[0]?.toLowerCase() || ''",
                callback,
            )

    def disconnect() -> None:
        result["revision_before_disconnect"] = adapter.state.revision
        adapter.stop()
        adapter.set_ui_state("disconnected")

        def record_disconnected(value: str, attempt: int) -> None:
            result["disconnect_ui_value"] = value
            result["disconnect_ui_observed"] = value == "disconnected"
            result["disconnect_observation_attempts"] = attempt + 1
            if result["disconnect_ui_observed"] or attempt >= 5:
                QTimer.singleShot(200, reconnect)
            else:
                QTimer.singleShot(100, lambda: observe_disconnected(attempt + 1))

        def observe_disconnected(attempt: int = 0) -> None:
            read_ui_state(lambda value: record_disconnected(value, attempt))

        QTimer.singleShot(120, observe_disconnected)

    def reconnect() -> None:
        if args.technology == "web":
            view.reload()
        adapter.set_ui_state("completed")
        adapter.start()
        result["revision_at_reconnect"] = adapter.state.revision
        QTimer.singleShot(1_200, lambda: read_ui_state(finish_with_state))

    def finish_with_state(value: str) -> None:
        result["recovered_ui_value"] = value
        result["recovered_ui_observed"] = value == "completed"
        result["renderer_reloaded"] = (
            len([ok for ok in load_results if ok]) >= 2
            if args.technology == "web"
            else True
        )
        result["revision_after_recovery"] = adapter.state.revision
        result["event_count"] = len(events)
        result["event_states"] = [event["ui_state"] for event in events]
        result["revision_progressed"] = (
            result["revision_after_recovery"]
            > result["revision_before_disconnect"]
        )
        result["passed"] = all(
            (
                result["disconnect_ui_observed"],
                result["recovered_ui_observed"],
                result["renderer_reloaded"],
                result["revision_progressed"],
                "disconnected" in result["event_states"],
                "completed" in result["event_states"],
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        adapter.stop()
        app.exit(0 if result["passed"] else 1)

    QTimer.singleShot(900, disconnect)
    _keep_alive = (keep_alive, adapter, timeline, benchmark, result)
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
