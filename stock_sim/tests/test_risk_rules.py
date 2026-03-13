from stock_sim.services.risk_rule_registry import risk_rule_registry
from stock_sim.core.const import OrderSide, OrderType

def test_risk_rule_registry_contains_noop_and_evaluates():
    rules = risk_rule_registry.list_rules()
    assert any(getattr(r, 'name', '') == 'NoopAllowAll' for r in rules)
    # 规则 evaluate 返回 None 代表通过
    for r in rules:
        res = r.evaluate(account=None, positions=[], symbol='AAA', side=OrderSide.BUY, price=0.0, qty=0, order_type=OrderType.LIMIT)
        assert res is None or getattr(res, 'ok', True) is True

