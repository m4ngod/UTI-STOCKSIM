"""Console script entry for frontend trading UI (Task46).

Usage (after install or via python -m):
  frontend-trading-ui --headless

Options:
  --headless   Run without GUI event loop (for CI / tests)
  --lang XX    Set initial language (default zh_CN)
  --theme THEME  Set initial theme (default light)
"""
from __future__ import annotations
import sys
import os
import argparse
from typing import Optional

try:
    from app.app_context import reset_app_context
    from app.headless import run_headless_frontend
    from app.event_bridge import start_frontend_bridge, stop_frontend_bridge
    from app.state.settings_store import SettingsStore
    from app.panels import register_builtin_panels, register_ui_adapters
    from app.runtime_bootstrap import start_runtime_support_services
    from app.ui.main_window import DEFAULT_PRELOAD_PANELS, MainWindow
    try:
        from PySide6.QtWidgets import QApplication  # type: ignore
    except Exception:  # pragma: no cover
        QApplication = None  # type: ignore
except Exception as e:  # pragma: no cover
    print("Failed to import frontend modules:", e, file=sys.stderr)
    sys.exit(2)

_DEBUG_GUI_START = os.environ.get("STOCKSIM_DEBUG_GUI_START", "").strip().lower() in {"1", "true", "yes", "on"}

def _init_settings(lang: str, theme: str):
    # 临时 settings.json 放在当前目录 (可扩展为 XDG 路径)
    store = SettingsStore(path="frontend_settings.json", auto_save=False)
    # 仅在不同才更新
    changes = {}
    if store.get_state().language != lang:
        changes.update(store.set_language(lang))
    if store.get_state().theme != theme:
        changes.update(store.set_theme(theme))
    return store, changes

def parse_args(argv: Optional[list[str]] = None):
    p = argparse.ArgumentParser(prog="frontend-trading-ui", add_help=True)
    p.add_argument("--headless", action="store_true", help="run without GUI event loop")
    p.add_argument("--lang", default="zh_CN", help="initial language")
    p.add_argument("--theme", default="light", help="initial theme")
    return p.parse_args(argv)

def _start_frontend(*, headless: bool):
    """Entry-local startup wrapper.

    Product-entry rule:
    - headless uses the dedicated `app.headless` surface
    - GUI startup is owned locally here using the real `MainWindow`
    - the console entry should not depend on `app.main` as a GUI fallback
    """
    if headless:
        return run_headless_frontend()

    if QApplication is None:
        raise RuntimeError("GUI runtime unavailable: PySide6/QApplication is not available")

    # Real GUI path must explicitly opt into real Qt widgets.
    os.environ.setdefault("STOCKSIM_ENABLE_REAL_UI", "1")
    reset_app_context()
    start_frontend_bridge()
    start_runtime_support_services()

    register_builtin_panels()
    try:
        register_ui_adapters()
    except Exception as e:
        if _DEBUG_GUI_START:
            print(f"[frontend-start] register_ui_adapters failed: {e!r}", file=sys.stderr)
        raise
    app = QApplication.instance() or QApplication([])
    try:
        app.aboutToQuit.connect(stop_frontend_bridge)  # type: ignore[attr-defined]
    except Exception:
        pass
    mw = MainWindow()
    try:
        from app.ui.ui_refresh import register_main_window as _ui_register_main_window  # type: ignore
        _ui_register_main_window(mw)
    except Exception:
        pass
    for name in DEFAULT_PRELOAD_PANELS:
        try:
            mw.open_panel(name)
            if _DEBUG_GUI_START:
                print(f"[frontend-start] opened preload panel: {name}", file=sys.stderr)
        except Exception as e:
            if _DEBUG_GUI_START:
                print(f"[frontend-start] failed preload panel {name}: {e!r}", file=sys.stderr)
    try:
        mw.show()
        app.exec()
    except Exception:
        pass
    return mw


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    store, changes = _init_settings(args.lang, args.theme)
    mw = _start_frontend(headless=args.headless)
    # 注意：GUI 路径已在 _start_frontend() 内完成默认预加载。
    # 这里不再重复 open_panel()，避免同一面板被 workspace/dock 双重挂载，
    # 生成一组有内容、一组空白的重复工作区项。
    opened = []
    try:
        if hasattr(mw, 'opened_panels') and isinstance(getattr(mw, 'opened_panels', None), dict):
            opened = list(mw.opened_panels.keys())
        elif hasattr(mw, 'list_open') and callable(getattr(mw, 'list_open', None)):
            opened = list(mw.list_open())
    except Exception:
        opened = []
    print(
        f"frontend started headless={args.headless} lang={store.get_state().language} "
        f"theme={store.get_state().theme} opened={opened} changes={list(changes.keys())}"  # noqa: E501
    )
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
