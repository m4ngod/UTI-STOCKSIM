"""One-command launcher for the issue #33 technology comparison.

THROWAWAY PROTOTYPE. Run from the repository root:

    python prototypes/frontend_v2_tech_slice/run.py --technology widgets

Use ``--technology all --benchmark-ms 3000`` for a deterministic comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROTOTYPE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROTOTYPE_ROOT.parents[1]
for candidate in (str(PROTOTYPE_ROOT), str(REPOSITORY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Frontend V2 technology vertical-slice throwaway prototype"
    )
    parser.add_argument(
        "--technology",
        choices=("widgets", "qml", "web", "all"),
        default="widgets",
    )
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
    parser.add_argument(
        "--benchmark-ms",
        type=int,
        default=0,
        help="Auto-exit after this duration and write comparable metrics.",
    )
    parser.add_argument("--benchmark-output", type=Path)
    parser.add_argument("--output-dir", type=Path, default=PROTOTYPE_ROOT / "artifacts")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="Use Qt's offscreen platform for automated evidence capture.",
    )
    return parser.parse_args()


def run_all(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for technology in ("widgets", "qml", "web"):
        result_path = output_dir / f"{technology}-{args.adapter}.json"
        screenshot_path = output_dir / f"{technology}-{args.adapter}.png"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--technology",
            technology,
            "--adapter",
            args.adapter,
            "--state",
            args.state,
            "--benchmark-ms",
            str(args.benchmark_ms or 3_000),
            "--benchmark-output",
            str(result_path),
            "--screenshot",
            str(screenshot_path),
            "--offscreen",
        ]
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            timeout=max(60, int((args.benchmark_ms or 3_000) / 1_000) + 45),
            check=False,
        )
        if completed.returncode != 0 or not result_path.exists():
            failures.append(
                {
                    "technology": technology,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-2_000:],
                    "stderr": completed.stderr[-4_000:],
                }
            )
            continue
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["process_wall_ms"] = round(
            (time.perf_counter() - started) * 1_000.0,
            3,
        )
        payload["screenshot"] = screenshot_path.name
        payload["runtime_warning_count"] = len(
            [line for line in completed.stderr.splitlines() if line.strip()]
        )
        results.append(payload)
    comparison = {
        "prototype": "issue-33-technology-vertical-slice",
        "adapter": args.adapter,
        "state": args.state,
        "results": results,
        "failures": failures,
    }
    comparison_path = output_dir / f"comparison-{args.adapter}.json"
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def run_one(args: argparse.Namespace) -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            "--disable-gpu --disable-software-rasterizer --no-sandbox",
        )

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QFontDatabase

    from adapters import make_adapter
    from benchmarking import BenchmarkSession
    from contract import build_timeline

    started_ns = time.perf_counter_ns()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("UTI Frontend V2 technology slice prototype")
    app.setOrganizationName("UTI Research")
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
    output_path = (
        args.benchmark_output.resolve() if args.benchmark_output is not None else None
    )
    screenshot_path = (
        args.screenshot.resolve() if args.screenshot is not None else None
    )
    benchmark = BenchmarkSession(
        technology=args.technology,
        adapter=args.adapter,
        ui_state=args.state,
        started_ns=started_ns,
        duration_ms=args.benchmark_ms,
        output_path=output_path,
    )
    benchmark.finished.connect(lambda payload: print(json.dumps(payload, ensure_ascii=False)))
    benchmark.finished.connect(lambda _payload: app.quit())
    keep_alive: list[object] = [adapter, benchmark, timeline]

    def request_technology(technology: str) -> None:
        if args.benchmark_ms > 0 or technology == args.technology:
            return
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--technology",
            technology,
            "--adapter",
            args.adapter,
            "--state",
            adapter.state.ui_state,
        ]
        subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        app.quit()

    if args.technology == "widgets":
        from widgets_app import run_widgets

        keep_alive.append(
            run_widgets(
                app=app,
                adapter=adapter,
                timeline=timeline,
                benchmark=benchmark,
                request_technology=request_technology,
                screenshot_path=screenshot_path,
            )
        )
    elif args.technology == "qml":
        from qml_app import run_qml

        keep_alive.extend(
            run_qml(
                app=app,
                adapter=adapter,
                timeline=timeline,
                benchmark=benchmark,
                request_technology=request_technology,
                screenshot_path=screenshot_path,
                qml_path=PROTOTYPE_ROOT / "qml" / "Main.qml",
            )
        )
    else:
        from web_app import run_web

        keep_alive.extend(
            run_web(
                app=app,
                adapter=adapter,
                timeline=timeline,
                benchmark=benchmark,
                request_technology=request_technology,
                screenshot_path=screenshot_path,
                html_path=PROTOTYPE_ROOT / "web" / "index.html",
            )
        )

    exit_code = app.exec()
    if args.benchmark_ms == 0:
        adapter.stop()
    return int(exit_code)


def main() -> int:
    args = parse_args()
    if args.technology == "all":
        return run_all(args)
    return run_one(args)


if __name__ == "__main__":
    raise SystemExit(main())
