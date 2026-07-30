from app.panels.orders import OrdersPanel


def test_orders_panel_deduplicates_same_trade_event():
    panel = OrdersPanel()
    payload = {
        "trade": {
            "symbol": "AAA",
            "price": 10.0,
            "quantity": 100,
            "side": "buy",
            "ts": 1234567890000,
            "buy_order_id": "B1",
        }
    }

    panel.add_line(payload)
    panel.add_line(payload)

    view = panel.get_view()
    assert view["total"] == 1
    assert view["items"][0]["type"] == "Trade"
