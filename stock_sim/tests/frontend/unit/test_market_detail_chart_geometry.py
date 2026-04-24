import importlib
from pathlib import Path

import pytest

from app.ui.adapters.market_adapter import _build_candle_plot_geometry


def test_candle_plot_geometry_uses_bar_index_and_tight_price_window():
    geometry = _build_candle_plot_geometry(
        {
            "open": [12.00],
            "high": [12.34],
            "low": [11.98],
            "close": [12.30],
        },
        {
            "reference_price": 12.0,
            "price_step": 0.01,
            "current_sim_day": 128,
            "history_high": 88.0,
        },
    )

    assert geometry["x"] == [0.0]
    assert geometry["x_min"] == -0.5
    assert geometry["x_max"] == 0.5
    assert geometry["y_min"] > 11.0
    assert geometry["y_max"] < 13.0
    assert geometry["y_max"] - geometry["y_min"] < 2.0


def test_detail_chart_widget_paints_visible_series(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("STOCKSIM_ENABLE_REAL_UI", "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    import app.ui.adapters.market_adapter as market_adapter

    market_adapter = importlib.reload(market_adapter)
    QApplication = pytest.importorskip("PySide6.QtWidgets").QApplication

    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"Qt application unavailable: {exc}")

    widget = market_adapter._DetailChartWidget()
    widget.resize(960, 320)
    widget.show()
    widget.set_chart_geometry(
        market_adapter._build_candle_plot_geometry(
            {
                "open": [12.00, 12.04, 12.08, 12.12],
                "high": [12.05, 12.10, 12.14, 12.18],
                "low": [11.98, 12.02, 12.06, 12.10],
                "close": [12.04, 12.08, 12.12, 12.16],
            },
            {
                "reference_price": 12.0,
                "price_step": 0.01,
            },
        )
    )
    app.processEvents()
    image = widget.grab().toImage()

    vivid_pixels = 0
    for x in range(0, image.width(), 4):
        for y in range(0, image.height(), 4):
            color = image.pixelColor(x, y)
            if (
                (color.blue() >= 180 and color.green() >= 180)
                or (color.red() >= 220 and color.green() <= 150)
                or (color.green() >= 180 and color.red() <= 140)
            ):
                vivid_pixels += 1

    assert vivid_pixels > 20
