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
import argparse
from typing import Optional

try:
    from app.main import run_frontend
    from app.state.settings_store import SettingsStore
except Exception as e:  # pragma: no cover
    print("Failed to import frontend modules:", e, file=sys.stderr)
    sys.exit(2)

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

def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    store, changes = _init_settings(args.lang, args.theme)
    # 仅在传入 --headless 时 headless=True, 不再强制
    mw = run_frontend(headless=args.headless)
    # 打开默认几个常用面板 (若注册完成)
    try:
        for name in ["account", "market", "agents", "settings"]:
            try:
                mw.open_panel(name)
            except Exception:
                pass
    except Exception:
        pass
    print(
        f"frontend started headless={args.headless} lang={store.get_state().language} "
        f"theme={store.get_state().theme} opened={list(mw.opened_panels.keys())} changes={list(changes.keys())}"  # noqa: E501
    )
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
