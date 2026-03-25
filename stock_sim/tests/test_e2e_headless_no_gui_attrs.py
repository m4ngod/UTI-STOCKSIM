from app.headless import run_headless_frontend


def test_e2e_headless_widget_has_no_gui_attrs_and_no_pyside6_import():
    from app.panels import reset_registry, register_panel

    reset_registry()

    class P:
        ...

    register_panel("h", lambda: P())

    mw = run_headless_frontend()

    assert not hasattr(mw, "_ensure_central_layout")
    assert not hasattr(mw, "_layout")
    assert not hasattr(mw, "_panel_widgets")

    inst = mw.open_panel("h")
    assert isinstance(inst, P)
    assert "h" in mw.opened_panels
    assert isinstance(mw.list_available(), list)
