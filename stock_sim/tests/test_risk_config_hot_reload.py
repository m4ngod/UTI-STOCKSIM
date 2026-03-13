from stock_sim.services.risk_rule_registry import risk_rule_registry
from stock_sim.services.risk_engine import RiskEngine
from stock_sim.services.config_hot_reload import config_hot_reloader
from stock_sim.settings import settings
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType, OrderSide, OrderType

# 集成测试: 风险规则 + 配置热更新
# 目标: 验证通过热更新动态修改 settings 后, 已注册风险规则的判定结果实时生效, 并发布 CONFIG_CHANGED 事件。

def test_risk_rules_with_config_hot_reload_integration():
    # 保存原值以便还原 (避免污染其他测试)
    orig_disable_short = settings.RISK_DISABLE_SHORT
    orig_max_notional = settings.MAX_SINGLE_ORDER_NOTIONAL
    try:
        # 事件捕获
        cfg_events: list[dict] = []
        event_bus.subscribe(EventType.CONFIG_CHANGED, lambda t, p: cfg_events.append(p))

        # 定义并注册依赖 settings 的动态规则
        class ShortDisableRule:
            name = "ShortDisableRule"
            def evaluate(self, **kwargs):
                side = kwargs.get("side")
                if side == OrderSide.SELL and settings.RISK_DISABLE_SHORT:
                    return type("R", (), {"ok": False, "reason": "SHORT_DISABLED"})()
                return None

        class MaxSingleOrderNotionalRule:
            name = "MaxSingleOrderNotionalRule"
            def evaluate(self, **kwargs):
                price = kwargs.get("price", 0.0) or 0.0
                qty = kwargs.get("qty", 0) or 0
                notional = price * qty
                if notional > settings.MAX_SINGLE_ORDER_NOTIONAL:
                    return type("R", (), {"ok": False, "reason": "NOTIONAL_LIMIT"})()
                return None

        risk_rule_registry.register(ShortDisableRule())
        risk_rule_registry.register(MaxSingleOrderNotionalRule())

        engine = RiskEngine()

        # Step1: 初始状态允许卖空 (默认 False)
        r1 = engine.validate(symbol="ABC", side=OrderSide.SELL, price=10.0, qty=5, order_type=OrderType.LIMIT)
        assert r1.ok, "初始应允许卖空"

        # Step2: 热更新关闭卖空
        res_patch1 = config_hot_reloader.apply({"RISK_DISABLE_SHORT": "true"})
        assert "RISK_DISABLE_SHORT" in res_patch1["changed"], "应成功热更新 RISK_DISABLE_SHORT"
        r2 = engine.validate(symbol="ABC", side=OrderSide.SELL, price=10.0, qty=5, order_type=OrderType.LIMIT)
        assert not r2.ok and r2.rule == "ShortDisableRule", "卖空被禁用后应被规则拒绝"

        # Step3: 热更新下调单笔名义限制并测试规则实时读取新值
        # 设置一个很小的限制, 先通过一笔小单, 再拒绝大单
        res_patch2 = config_hot_reloader.apply({"MAX_SINGLE_ORDER_NOTIONAL": 40})
        assert res_patch2["changed"].get("MAX_SINGLE_ORDER_NOTIONAL") == 40
        ok_small = engine.validate(symbol="ABC", side=OrderSide.BUY, price=5.0, qty=5, order_type=OrderType.LIMIT)
        assert ok_small.ok, "小单应通过 (5*5=25 <= 40)"
        rej_big = engine.validate(symbol="ABC", side=OrderSide.BUY, price=10.0, qty=10, order_type=OrderType.LIMIT)
        assert not rej_big.ok and rej_big.rule == "MaxSingleOrderNotionalRule", "大单应被名义限制拒绝"

        # Step4: 验证已发布配置变更事件 (至少两次) 且包含字段
        assert len(cfg_events) >= 2, "应至少收到两次 CONFIG_CHANGED 事件"
        changed_fields_all = {k for ev in cfg_events for k in ev.get("changed", {}).keys()}
        assert {"RISK_DISABLE_SHORT", "MAX_SINGLE_ORDER_NOTIONAL"}.issubset(changed_fields_all)
    finally:
        # 还原设置
        settings.RISK_DISABLE_SHORT = orig_disable_short
        settings.MAX_SINGLE_ORDER_NOTIONAL = orig_max_notional

