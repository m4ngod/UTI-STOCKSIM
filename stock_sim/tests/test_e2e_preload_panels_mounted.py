import pytest

# 无 PySide6 时跳过
try:
    from PySide6.QtWidgets import QApplication  # type: ignore
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False


@pytest.mark.skipif(not HAS_QT, reason="无 Qt 环境，跳过")
def test_e2e_preload_panels_all_mounted():
    from app.panels import reset_registry, register_builtin_panels
    from app.main import MainWindow, _DEFAULT_PRELOAD

    # 确保 QApplication
    app = QApplication.instance() or QApplication([])

    # 预注册内置面板
    reset_registry()
    register_builtin_panels()

    # 构建主窗体并确保布局
    mw = MainWindow()
    mw._ensure_central_layout()

    # 逐一打开预加载面板
    for name in _DEFAULT_PRELOAD:
        mw.open_panel(name)

    # 成功标准：所有预期面板 key 存在
    keys = set(mw._panel_widgets.keys())
    for name in _DEFAULT_PRELOAD:
        assert name in keys, f"缺少预期面板: {name}, 已有: {keys}"

