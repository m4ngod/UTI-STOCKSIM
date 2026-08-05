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
    from stock_sim.persistence.db_health import check_database_health, format_database_health
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
    p.add_argument("--check-db", action="store_true", help="check database connectivity and schema, then exit")
    p.add_argument("--skip-db-check", action="store_true", help="skip startup database health check")
    p.add_argument("--require-postgres", action="store_true", help="fail unless the configured database is PostgreSQL")
    p.add_argument("--lang", default="zh_CN", help="initial language")
    p.add_argument("--theme", default="light", help="initial theme")
    return p.parse_args(argv)


def _database_check_enabled(*, headless: bool, skip: bool) -> bool:
    if skip:
        return False
    flag = os.environ.get("STOCKSIM_DB_CHECK_ON_START", "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return not headless


def _require_postgres_enabled(cli_value: bool = False) -> bool:
    if cli_value:
        return True
    return os.environ.get("STOCKSIM_REQUIRE_POSTGRES", "").strip().lower() in {"1", "true", "yes", "on"}


def _run_database_check(*, ensure_schema: bool = True, require_postgres: bool = False) -> int:
    health = check_database_health(
        ensure_schema=ensure_schema,
        required_dialect="postgresql" if require_postgres else None,
    )
    print(f"database {format_database_health(health)}", file=sys.stderr)
    return 0 if health.ok else 3

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
    event_bridge = start_frontend_bridge()
    context = reset_app_context(event_bridge=event_bridge)
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
        strategy_library_feature = getattr(
            context,
            "strategy_library_feature",
            None,
        )
        if strategy_library_feature is not None:
            app.aboutToQuit.connect(  # type: ignore[attr-defined]
                strategy_library_feature.close
            )
        diagnostic_tasks_feature = getattr(
            context,
            "diagnostic_tasks_feature",
            None,
        )
        if diagnostic_tasks_feature is not None:
            app.aboutToQuit.connect(  # type: ignore[attr-defined]
                diagnostic_tasks_feature.close
            )
        scenario_lab_feature = getattr(context, "scenario_lab_feature", None)
        if scenario_lab_feature is not None:
            app.aboutToQuit.connect(scenario_lab_feature.close)  # type: ignore[attr-defined]
        app.aboutToQuit.connect(context.run_monitoring_feature.close)  # type: ignore[attr-defined]
        evidence_feature = getattr(
            context,
            "evidence_and_findings_feature",
            None,
        )
        if evidence_feature is not None:
            app.aboutToQuit.connect(evidence_feature.close)  # type: ignore[attr-defined]
    except Exception:
        pass
    mw = MainWindow(
        strategy_library_feature=getattr(
            context,
            "strategy_library_feature",
            None,
        ),
        strategy_library_context=getattr(
            context,
            "strategy_library_context",
            None,
        ),
        strategy_library_bookmark_sink=(
            getattr(context, "persist_strategy_library_bookmark", None)
        ),
        scenario_lab_feature=getattr(
            context,
            "scenario_lab_feature",
            None,
        ),
        scenario_lab_context=getattr(
            context,
            "scenario_lab_context",
            None,
        ),
        diagnostic_tasks_feature=getattr(
            context,
            "diagnostic_tasks_feature",
            None,
        ),
        diagnostic_tasks_context=getattr(
            context,
            "diagnostic_tasks_context",
            None,
        ),
        diagnostic_setup_selection_coordinator=getattr(
            context,
            "diagnostic_setup_selection_coordinator",
            None,
        ),
        run_monitoring_feature=context.run_monitoring_feature,
        run_monitoring_context=getattr(
            context,
            "run_monitoring_context",
            None,
        ),
        evidence_and_findings_feature=getattr(
            context,
            "evidence_and_findings_feature",
            None,
        ),
        evidence_and_findings_context=getattr(
            context,
            "evidence_and_findings_context",
            None,
        ),
    )
    try:
        from app.ui.ui_refresh import register_main_window as _ui_register_main_window  # type: ignore
        _ui_register_main_window(mw)
    except Exception:
        pass
    if not mw.journey_workspace_active:
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
    require_postgres = _require_postgres_enabled(args.require_postgres)
    if args.check_db:
        return _run_database_check(ensure_schema=True, require_postgres=require_postgres)
    if _database_check_enabled(headless=args.headless, skip=args.skip_db_check):
        rc = _run_database_check(ensure_schema=True, require_postgres=require_postgres)
        if rc != 0:
            return rc
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
