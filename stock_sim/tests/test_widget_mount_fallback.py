import pytest

# 条件导入：无 PySide6 则跳过整个测试
try:
    from PySide6.QtWidgets import QApplication, QLabel  # type: ignore
    HAS_PYSIDE = True
except Exception:  # pragma: no cover
    HAS_PYSIDE = False


@pytest.mark.skipif(not HAS_PYSIDE, reason="PySide6 不可用，跳过 GUI 相关测试")
def test_widget_priority_and_placeholder_fallback():
    from app.panels import reset_registry, register_panel
    from app.main import MainWindow

    # 确保有 QApplication 实例
    app = QApplication.instance() or QApplication([])

    # 重置注册表，注册两个测试面板
    reset_registry()

    class PrimaryPanel:
        def widget(self):
            return QLabel("PRIMARY_WIDGET")

    class FallbackPanel:
        # 不提供 widget()/mount()，触发占位
        pass

    register_panel("p1", lambda: PrimaryPanel())
    register_panel("p2", lambda: FallbackPanel())

    # 构建主窗体并挂载两个面板
    mw = MainWindow()
    mw._ensure_central_layout()
    mw.open_panel("p1")
    mw.open_panel("p2")

    # 成功标准 1：映射包含两个 name
    assert set(mw._panel_widgets.keys()) == {"p1", "p2"}

    # 成功标准 2：第二个部件文本包含 placeholder（fallback 占位）
    w1 = mw._panel_widgets["p1"]
    w2 = mw._panel_widgets["p2"]

    # p1 使用自带 widget 优先
    assert hasattr(w1, "text") and w1.text() == "PRIMARY_WIDGET"

    # p2 为占位 QLabel，文本包含 placeholder
    assert hasattr(w2, "text") and "placeholder" in w2.text().lower()


@pytest.mark.skipif(not HAS_PYSIDE, reason="PySide6 不可用，跳过 GUI 相关测试")
def test_open_panel_idempotent_mount_no_duplicate_widgets():
    from app.panels import reset_registry, register_panel
    from app.main import MainWindow

    # 确保有 QApplication 实例
    app = QApplication.instance() or QApplication([])

    reset_registry()

    class Panel:
        def widget(self):
            return QLabel("ONE_WIDGET")

    register_panel("only", lambda: Panel())

    mw = MainWindow()
    mw._ensure_central_layout()

    # 首次挂载
    mw.open_panel("only")
    count_after_first = mw._layout.count()  # type: ignore[union-attr]
    widget_first = mw._panel_widgets["only"]

    # 重复打开同名面板
    mw.open_panel("only")
    count_after_second = mw._layout.count()  # type: ignore[union-attr]
    widget_second = mw._panel_widgets["only"]

    # 成功标准：子项计数保持一致且未新增重复，引用相同
    assert count_after_second == count_after_first
    assert set(mw._panel_widgets.keys()) == {"only"}
    assert widget_first is widget_second


@pytest.mark.skipif(not HAS_PYSIDE, reason="PySide6 不可用，跳过 GUI 相关测试")
def test_widget_preload_panels_all_mounted_via_mainwindow():
    from app.panels import reset_registry, register_builtin_panels
    from app.main import MainWindow, _DEFAULT_PRELOAD

    app = QApplication.instance() or QApplication([])

    reset_registry()
    register_builtin_panels()

    mw = MainWindow()
    mw._ensure_central_layout()

    for name in _DEFAULT_PRELOAD:
        mw.open_panel(name)

    keys = set(mw._panel_widgets.keys())
    missing = [n for n in _DEFAULT_PRELOAD if n not in keys]
    assert not missing, f"缺少预期面板: {missing}, 已有: {keys}"
