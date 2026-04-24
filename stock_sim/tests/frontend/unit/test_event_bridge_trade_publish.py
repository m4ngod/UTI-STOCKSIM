from __future__ import annotations

from infra.event_bus import event_bus

from app.event_bridge import (
    ACCOUNT_CREATED_TOPIC,
    ACCOUNT_UPDATED_TOPIC,
    AGENT_STATUS_CHANGED_TOPIC,
    INSTRUMENT_CREATED_TOPIC,
    ORDER_SUBMITTED_TOPIC,
    ORDER_CANCELED_TOPIC,
    ORDER_REJECTED_TOPIC,
    TRADE_EXECUTED_TOPIC,
    on_account_created,
    publish_account_created,
    on_account_updated,
    publish_account_updated,
    on_order_submitted,
    publish_order_submitted,
    on_order_canceled,
    on_order_rejected,
    on_trade_executed,
    publish_agent_status_changed,
    publish_instrument_created,
    publish_trade_payload,
)


def test_publish_trade_payload_emits_trade_topics_to_app_bus():
    seen = []

    def _rec(topic, payload):
        seen.append((topic, payload))

    event_bus.subscribe("Trade", _rec, async_mode=False)
    event_bus.subscribe("TradeEvent", _rec, async_mode=False)
    try:
        payload = {"trade": {"symbol": "AAA", "price": 10.0, "qty": 100}}
        publish_trade_payload(payload)
    finally:
        try:
            event_bus.unsubscribe("Trade", _rec)
        except Exception:
            pass
        try:
            event_bus.unsubscribe("TradeEvent", _rec)
        except Exception:
            pass

    assert ("Trade", payload) in seen
    assert ("TradeEvent", payload) in seen


def test_on_trade_executed_receives_single_canonical_trade_event():
    seen = []

    cancel = on_trade_executed(lambda topic, payload: seen.append((topic, payload)), async_mode=False)
    try:
        payload = {"trade": {"symbol": "BBB", "price": 11.0, "qty": 200}}
        publish_trade_payload(payload)
    finally:
        cancel()

    assert seen == [(TRADE_EXECUTED_TOPIC, payload)]


def test_order_submitted_helper_covers_canonical_and_legacy_topics():
    seen = []

    cancel = on_order_submitted(lambda topic, payload: seen.append((topic, payload)), async_mode=False)
    try:
        legacy_payload = {"order_id": "OID-LEGACY", "symbol": "AAA", "qty": 10, "status": "NEW"}
        canonical_payload = {"order_id": "OID-CANON", "symbol": "BBB", "qty": 20, "status": "NEW"}
        event_bus.publish("frontend.order.submitted", legacy_payload)
        publish_order_submitted(canonical_payload)
    finally:
        cancel()

    assert ("frontend.order.submitted", legacy_payload) in seen
    assert (ORDER_SUBMITTED_TOPIC, canonical_payload) in seen


def test_order_event_helpers_receive_legacy_backend_topics_through_canonical_subscription():
    rejected_seen = []
    canceled_seen = []

    cancel_rejected = on_order_rejected(lambda topic, payload: rejected_seen.append((topic, payload)), async_mode=False)
    cancel_canceled = on_order_canceled(lambda topic, payload: canceled_seen.append((topic, payload)), async_mode=False)
    try:
        reject_payload = {"order": {"order_id": "OID-1"}, "reason": "RISK"}
        cancel_payload = {"order_id": "OID-2", "reason": "USER"}
        event_bus.publish("OrderRejected", reject_payload)
        event_bus.publish("OrderCanceled", cancel_payload)
    finally:
        cancel_rejected()
        cancel_canceled()

    assert rejected_seen == [("OrderRejected", reject_payload)]
    assert canceled_seen == [("OrderCanceled", cancel_payload)]


def test_account_event_helpers_cover_canonical_and_legacy_topics():
    seen = []

    cancel = on_account_updated(lambda topic, payload: seen.append((topic, payload)), async_mode=False)
    try:
        legacy_payload = {"account": {"id": "ACC-LEGACY", "cash": 1000.0}}
        canonical_payload = {"account": {"id": "ACC-CANON", "cash": 2000.0}}
        event_bus.publish("AccountUpdated", legacy_payload)
        publish_account_updated(canonical_payload)
    finally:
        cancel()

    assert ("AccountUpdated", legacy_payload) in seen
    assert (ACCOUNT_UPDATED_TOPIC, canonical_payload) in seen


def test_account_created_helper_covers_canonical_and_legacy_topics():
    seen = []

    cancel = on_account_created(lambda topic, payload: seen.append((topic, payload)), async_mode=False)
    try:
        legacy_payload = {"account_id": "ACC-LEGACY", "initial_cash": 1000.0}
        canonical_payload = {"account_id": "ACC-CANON", "initial_cash": 2000.0}
        event_bus.publish("account.created", legacy_payload)
        publish_account_created(canonical_payload)
    finally:
        cancel()

    assert ("account.created", legacy_payload) in seen
    assert (ACCOUNT_CREATED_TOPIC, canonical_payload) in seen


def test_publish_helpers_emit_agent_and_instrument_topics():
    seen = []

    def _rec(topic, payload):
        seen.append((topic, payload))

    event_bus.subscribe(AGENT_STATUS_CHANGED_TOPIC, _rec, async_mode=False)
    event_bus.subscribe(INSTRUMENT_CREATED_TOPIC, _rec, async_mode=False)
    try:
        agent_payload = {"agent_id": "mean_revert001", "status": "RUNNING"}
        instrument_payload = {"symbol": "AAA", "name": "AAA Corp"}
        publish_agent_status_changed(agent_payload)
        publish_instrument_created(instrument_payload)
    finally:
        try:
            event_bus.unsubscribe(AGENT_STATUS_CHANGED_TOPIC, _rec)
        except Exception:
            pass
        try:
            event_bus.unsubscribe(INSTRUMENT_CREATED_TOPIC, _rec)
        except Exception:
            pass

    assert (AGENT_STATUS_CHANGED_TOPIC, agent_payload) in seen
    assert (INSTRUMENT_CREATED_TOPIC, instrument_payload) in seen
