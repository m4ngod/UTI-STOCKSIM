import pytest

try:
    from PySide6.QtWidgets import QApplication
    QT_AVAILABLE = True
except Exception:
    QT_AVAILABLE = False

@pytest.mark.skipif(not QT_AVAILABLE, reason="PySide6 not available")
def test_mainwindow_layout_idempotent():
    from app.main import MainWindow

    app = QApplication.instance() or QApplication([])
    mw = MainWindow()

    # 第一次创建 central 与布局
    mw._ensure_central_layout()
    cw1 = getattr(mw, 'centralWidget', lambda: None)()
    layout1 = getattr(mw, '_layout', None)
    count1 = layout1.count() if layout1 is not None else 0

    # 第二次调用应幂等：central 不变、子项数不增加
    mw._ensure_central_layout()
    cw2 = getattr(mw, 'centralWidget', lambda: None)()
    layout2 = getattr(mw, '_layout', None)
    count2 = layout2.count() if layout2 is not None else 0

    assert cw1 is not None, "centralWidget should be created"
    assert cw1 is cw2, "centralWidget should be the same instance after repeated calls"
    assert layout1 is layout2, "layout object should be the same instance"
    assert count2 == count1, "layout children count should not increase on repeated ensure calls"

