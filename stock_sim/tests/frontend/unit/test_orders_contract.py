from app.panels.orders.panel import OrdersPanel


def test_orders_panel_exposes_lifecycle_stage_and_line_meta():
    panel = OrdersPanel(capacity=10)

    panel.add_line({
        'order_id': 'O0',
        'symbol': 'AAA',
        'price': 10.0,
        'qty': 5,
        'side': 'buy',
        'status': 'NEW',
        'account_id': 'ACC1',
        'ts': 0,
    })
    panel.add_line({'trade': {'symbol': 'AAA', 'price': 10.5, 'qty': 2, 'side': 'buy', 'ts': 1}})
    panel.add_line({
        'order': {'order_id': 'O1', 'symbol': 'AAA', 'price': 10.5, 'qty': 1, 'side': 'buy', 'status': 'REJECTED', 'account_id': 'ACC1'},
        'reason': 'risk',
    })
    panel.add_line({'order_id': 'O2', 'reason': 'IOC_UNFILLABLE', 'status': 'CANCELED', 'account_id': 'ACC1'})

    items = panel.get_view()['items']
    assert len(items) == 4

    for item in items:
        assert 'lifecycle_stage' in item
        assert 'line_meta' in item
        assert item['line_meta']['source'] == 'frontend-order-event-stream'
        assert item['line_meta']['authoritative'] is False
        assert item['line_meta']['lifecycle_summary'] == item['lifecycle_stage']
        assert 'account_semantic_hint' in item['line_meta']
        assert 'account_effect_summary' in item['line_meta']

    assert items[0]['type'] == 'OrderSubmitted'
    assert items[0]['lifecycle_stage'] == 'active'

    assert items[1]['type'] == 'Trade'
    assert items[1]['lifecycle_stage'] == 'filled-event'

    assert items[2]['type'] == 'OrderRejected'
    assert items[2]['lifecycle_stage'] == 'rejected'

    assert items[3]['type'] == 'OrderCanceled'
    assert items[3]['lifecycle_stage'] == 'canceled-residual'
