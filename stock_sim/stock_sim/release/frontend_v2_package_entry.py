"""Minimal installed-package entry point for the Frontend V2 T02 gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Sequence


class RendererLane(str, Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"


@dataclass(frozen=True, slots=True)
class SmokeStateObservation:
    state: str
    headline: str
    detail: str
    screenshot: str | None


@dataclass(frozen=True, slots=True)
class PackageSmokeResult:
    renderer_lane: RendererLane
    graphics_api: str
    observations: tuple[SmokeStateObservation, ...]
    errors: tuple[str, ...]
    clean_exit: bool


def configure_renderer_environment(renderer_lane: RendererLane) -> None:
    if renderer_lane is RendererLane.SOFTWARE:
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QSG_RHI_BACKEND"] = "software"
        return
    os.environ.pop("QT_QUICK_BACKEND", None)
    os.environ["QSG_RHI_BACKEND"] = "d3d11"


def run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    capture_images: bool = True,
) -> PackageSmokeResult:
    from PySide6.QtWidgets import QApplication, QMainWindow

    from app.features import (
        DeterministicFakeRunMonitoringAdapter,
        RunMonitoringContext,
    )
    from app.ui.journey_workspace import JourneyWorkspaceHost

    report_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    feature = DeterministicFakeRunMonitoringAdapter()
    window = QMainWindow()
    window.setObjectName("frontendV2PackageWindow")
    host = JourneyWorkspaceHost(feature, parent=window)
    window.setCentralWidget(host)
    window.resize(1024, 640)
    window.show()
    app.processEvents()

    root = host.rootObject()
    errors: list[str] = []
    observations: list[SmokeStateObservation] = []
    if root is None:
        errors.append("Journey Workspace root object is unavailable")
    else:
        observations.append(
            _observe_state(
                root,
                host,
                report_dir,
                "loading",
                capture_images,
            )
        )
        feature.advance_to_empty(RunMonitoringContext.no_selection())
        app.processEvents()
        observations.append(
            _observe_state(
                root,
                host,
                report_dir,
                "empty",
                capture_images,
            )
        )
        feature.advance_to_disconnected(RunMonitoringContext.no_selection())
        app.processEvents()
        observations.append(
            _observe_state(
                root,
                host,
                report_dir,
                "disconnected",
                capture_images,
            )
        )

    graphics_api = _graphics_api_name(host)
    host.close_adapter()
    window.close()
    feature.close()
    app.processEvents()
    result = PackageSmokeResult(
        renderer_lane=renderer_lane,
        graphics_api=graphics_api,
        observations=tuple(observations),
        errors=tuple(errors),
        clean_exit=True,
    )
    _write_smoke_report(result, report_dir / "smoke-report.json")
    return result


def _observe_state(
    root: Any,
    host: Any,
    report_dir: Path,
    expected_state: str,
    capture_images: bool,
) -> SmokeStateObservation:
    from PySide6.QtCore import QObject

    state = str(root.property("screenState"))
    if state != expected_state:
        raise RuntimeError(
            f"Expected visible state {expected_state!r}, observed {state!r}"
        )
    headline = str(root.property("headline"))
    detail_object = root.findChild(QObject, "runMonitoringDetail")
    detail = (
        str(detail_object.property("text"))
        if detail_object is not None
        else ""
    )
    screenshot_name = None
    if capture_images:
        screenshot_name = f"{expected_state}.png"
        screenshot_path = report_dir / screenshot_name
        _capture_qml_frame(host, screenshot_path)
    return SmokeStateObservation(
        state=state,
        headline=headline,
        detail=detail,
        screenshot=screenshot_name,
    )


def _capture_qml_frame(host: Any, screenshot_path: Path) -> None:
    image = host.grabFramebuffer()
    if image.isNull() or not image.save(str(screenshot_path), "PNG"):
        raise RuntimeError(f"Failed to capture {screenshot_path}")


def _graphics_api_name(host: Any) -> str:
    quick_window = host.quickWindow()
    if quick_window is None:
        return "unavailable"
    graphics_api = quick_window.rendererInterface().graphicsApi()
    return getattr(graphics_api, "name", str(graphics_api))


def _write_smoke_report(
    result: PackageSmokeResult,
    report_path: Path,
) -> None:
    payload = asdict(result)
    payload["renderer_lane"] = result.renderer_lane.value
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _run_interactive() -> int:
    from PySide6.QtWidgets import QApplication, QMainWindow

    from app.features import DeterministicFakeRunMonitoringAdapter
    from app.ui.journey_workspace import JourneyWorkspaceHost

    app = QApplication.instance() or QApplication([])
    feature = DeterministicFakeRunMonitoringAdapter()
    window = QMainWindow()
    host = JourneyWorkspaceHost(feature, parent=window)
    window.setCentralWidget(host)
    window.resize(1024, 640)
    app.aboutToQuit.connect(host.close_adapter)
    app.aboutToQuit.connect(feature.close)
    window.show()
    return int(app.exec())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--renderer-lane",
        choices=tuple(lane.value for lane in RendererLane),
        default=RendererLane.HARDWARE.value,
    )
    parser.add_argument("--smoke-report-dir", type=Path)
    parser.add_argument("--no-images", action="store_true")
    arguments = parser.parse_args(argv)
    renderer_lane = RendererLane(arguments.renderer_lane)
    configure_renderer_environment(renderer_lane)
    if arguments.smoke_report_dir is not None:
        result = run_smoke_journey(
            report_dir=arguments.smoke_report_dir,
            renderer_lane=renderer_lane,
            capture_images=not arguments.no_images,
        )
        return 0 if not result.errors and result.clean_exit else 1
    return _run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
