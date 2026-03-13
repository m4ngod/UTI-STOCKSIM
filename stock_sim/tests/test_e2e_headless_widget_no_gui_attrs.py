import sys
import types
import importlib


def test_headless_run_has_no_gui_attrs_and_no_pyside6_import():
    orig_pyside6 = sys.modules.get("PySide6")
    orig_main = sys.modules.get("app.main")

    dummy = types.ModuleType("PySide6")
    if hasattr(dummy, "__path__"):
        delattr(dummy, "__path__")

    sys.modules.pop("PySide6.QtWidgets", None)
    sys.modules.pop("PySide6.QtCore", None)

    sys.modules["PySide6"] = dummy
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    try:
        import app.main as main
        assert main.QApplication is None

        from app.panels import reset_registry, register_panel
        reset_registry()
        class P: ...
        register_panel("h", lambda: P())

        mw = main.run_frontend(headless=True)

        assert not hasattr(mw, "_ensure_central_layout")
        assert not hasattr(mw, "_layout")
        assert not hasattr(mw, "_panel_widgets")

        inst = mw.open_panel("h")
        assert isinstance(inst, P)
        assert "h" in mw.opened_panels
        assert isinstance(mw.list_available(), list)
    finally:
        if orig_pyside6 is None:
            sys.modules.pop("PySide6", None)
        else:
            sys.modules["PySide6"] = orig_pyside6
        if "app.main" in sys.modules:
            import app.main as main2
            importlib.reload(main2)
        elif orig_main is not None:
            sys.modules["app.main"] = orig_main

