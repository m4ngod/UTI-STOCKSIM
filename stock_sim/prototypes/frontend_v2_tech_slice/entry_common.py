"""Shared minimal packaging bootstrap for the throwaway candidates."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

PROTOTYPE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROTOTYPE_ROOT.parents[1]
for candidate in (str(PROTOTYPE_ROOT), str(REPOSITORY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", choices=("fake", "runtime"), default="fake")
    parser.add_argument(
        "--state",
        choices=(
            "loading",
            "empty",
            "stale",
            "disconnected",
            "partial",
            "failed",
            "completed",
        ),
        default="completed",
    )
    parser.add_argument("--benchmark-ms", type=int, default=0)
    parser.add_argument("--benchmark-output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--offscreen", action="store_true")
    return parser.parse_args()


def run_packaged(
    technology: str,
    launch: Callable,
) -> int:
    args = _arguments()
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            "--disable-gpu --disable-software-rasterizer --no-sandbox",
        )

    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from adapters import make_adapter
    from benchmarking import BenchmarkSession
    from contract import build_timeline

    started_ns = time.perf_counter_ns()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(f"UTI Frontend V2 {technology} slice")
    for font_path in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/consola.ttf"),
        Path("C:/Windows/Fonts/georgia.ttf"),
    ):
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei UI", 9))
    adapter = make_adapter(args.adapter, args.state)
    timeline = build_timeline()
    benchmark = BenchmarkSession(
        technology=technology,
        adapter=args.adapter,
        ui_state=args.state,
        started_ns=started_ns,
        duration_ms=args.benchmark_ms,
        output_path=args.benchmark_output.resolve()
        if args.benchmark_output is not None
        else None,
    )
    benchmark.finished.connect(
        lambda payload: print(json.dumps(payload, ensure_ascii=False))
    )
    benchmark.finished.connect(lambda _payload: app.quit())
    keep_alive = launch(
        app=app,
        adapter=adapter,
        timeline=timeline,
        benchmark=benchmark,
        request_technology=lambda _technology: None,
        screenshot_path=args.screenshot.resolve()
        if args.screenshot is not None
        else None,
    )
    _keep_alive = [adapter, timeline, benchmark, keep_alive]
    return int(app.exec())
