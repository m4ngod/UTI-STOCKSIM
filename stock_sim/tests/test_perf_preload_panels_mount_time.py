import os
import time
import pytest

# 无 PySide6 时跳过
try:
    from PySide6.QtWidgets import QApplication  # type: ignore
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False


@pytest.mark.slow
@pytest.mark.skipif(not HAS_QT, reason="无 Qt 环境，跳过")
def test_preload_panels_mount_performance():
    """本地性能验证：预加载面板挂载总耗时与均值在阈值内。

    - 可通过环境变量调整阈值：
      - PANEL_MOUNT_TOTAL_MS (默认 800)
      - PANEL_MOUNT_AVG_MS   (默认 200)
    - 验证 metrics：panel_mount_success == 预加载面板数，panel_mount_failure == 0
    - 在无 Qt 环境被标记跳过，避免 CI 干扰
    """
    from app.panels import reset_registry, register_builtin_panels
    from app.main import MainWindow, _DEFAULT_PRELOAD
    from observability.metrics import metrics

    # 确保 QApplication
    app = QApplication.instance() or QApplication([])

    # 预注册占位面板
    reset_registry()
    register_builtin_panels()

    # 构建主窗体并确保布局
    mw = MainWindow()
    mw._ensure_central_layout()

    # 计时挂载流程
    t0 = time.perf_counter()
    per_panel_ms = []
    for name in _DEFAULT_PRELOAD:
        t1 = time.perf_counter()
        mw.open_panel(name)
        per_panel_ms.append((time.perf_counter() - t1) * 1000.0)
    total_ms = (time.perf_counter() - t0) * 1000.0

    # 阈值（可通过环境变量覆盖）
    total_threshold = float(os.getenv("PANEL_MOUNT_TOTAL_MS", "800"))
    avg_threshold = float(os.getenv("PANEL_MOUNT_AVG_MS", "200"))

    panel_cnt = len(_DEFAULT_PRELOAD) or 1
    avg_ms = total_ms / panel_cnt

    # 性能断言（温和阈值，主要用于本地回归）
    assert total_ms <= total_threshold, (
        f"总挂载耗时 {total_ms:.2f}ms 超过阈值 {total_threshold}ms; per-panel={per_panel_ms}"
    )
    assert avg_ms <= avg_threshold, (
        f"人均挂载耗时 {avg_ms:.2f}ms 超过阈值 {avg_threshold}ms; per-panel={per_panel_ms}"
    )

    # Metrics 断言：应全部成功且无失败
    success = metrics.counters.get('panel_mount_success', 0)
    failure = metrics.counters.get('panel_mount_failure', 0)
    assert success >= panel_cnt, f"panel_mount_success={success} < 预期 {panel_cnt}"
    assert failure == 0, f"panel_mount_failure={failure} 非零"

    # 布局中应存在所有预期挂载的面板
    mounted = set(getattr(mw, '_panel_widgets', {}).keys())
    expected = set(_DEFAULT_PRELOAD)
    assert expected.issubset(mounted), f"已挂载: {mounted}, 预期: {expected}"

