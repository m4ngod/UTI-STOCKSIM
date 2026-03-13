import sys
import types
import importlib


def test_headless_run_has_no_gui_attrs_and_no_pyside6_import():
    # 备份原模块引用
    orig_pyside6 = sys.modules.get("PySide6")
    orig_main = sys.modules.get("app.main")

    # 注入一个非 package 的假 PySide6，确保 app.main 导入时走 except 分支
    dummy = types.ModuleType("PySide6")
    # 确保没有 __path__，避免被当作包
    if hasattr(dummy, "__path__"):
        delattr(dummy, "__path__")

    # 清理可能存在的子模块缓存
    sys.modules.pop("PySide6.QtWidgets", None)
    sys.modules.pop("PySide6.QtCore", None)

    # 将假模块放入 sys.modules，并清理 app.main，以便重新导入
    sys.modules["PySide6"] = dummy
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    try:
        # 现在导入 app.main，应走 headless 路径（QApplication 等为 None）
        import app.main as main

        # 明确不导入 PySide6；验证模块内 GUI 依赖被置为 None
        assert main.QApplication is None

        # 注册一个简单面板并在 headless 下打开
        from app.panels import reset_registry, register_panel

        reset_registry()
        class P:
            pass
        register_panel("h", lambda: P())

        mw = main.run_frontend(headless=True)

        # 成功标准：无 GUI 相关属性（仅 headless API 存在）
        assert not hasattr(mw, "_ensure_central_layout")
        assert not hasattr(mw, "_layout")
        assert not hasattr(mw, "_panel_widgets")

        # 确认基本功能可用
        inst = mw.open_panel("h")
        assert isinstance(inst, P)
        assert "h" in mw.opened_panels
        assert isinstance(mw.list_available(), list)
    finally:
        # 恢复 sys.modules 中的 PySide6
        if orig_pyside6 is None:
            sys.modules.pop("PySide6", None)
        else:
            sys.modules["PySide6"] = orig_pyside6
        # 重新加载 app.main 以恢复到原始（可能的 GUI）状态
        if "app.main" in sys.modules:
            import app.main as main2
            importlib.reload(main2)
        elif orig_main is not None:
            sys.modules["app.main"] = orig_main


def test_smoke_headless_collection():
    # 确认 pytest 能收集到本文件
    assert True
