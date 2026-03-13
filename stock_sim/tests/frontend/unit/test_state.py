from app.state import AppState, SettingsState, APP_STATE_INIT, APP_STATE_UPDATED, SETTINGS_STATE_INIT, SETTINGS_STATE_UPDATED
from app.core_dto import AccountDTO, PositionDTO, ClockStateDTO
from infra.event_bus import event_bus
import pytest
import json


def test_app_state_events():
    events = []
    event_bus.subscribe(APP_STATE_INIT, lambda t, p: events.append((t, p)))
    event_bus.subscribe(APP_STATE_UPDATED, lambda t, p: events.append((t, p)))

    app_state = AppState()  # 触发 INIT
    assert events[0][0] == APP_STATE_INIT
    assert events[0][1]["full"] is True

    acc = AccountDTO(
        account_id="acc-test",
        cash=10_000.0,
        frozen_cash=0.0,
        positions=[PositionDTO(symbol="AAA", quantity=1, frozen_qty=0, avg_price=10.0, borrowed_qty=0)],
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        equity=10_000.0,
        utilization=0.0,
        snapshot_id="s1",
        sim_day="2025-09-08",
    )
    app_state.update_account(acc)
    # 最近一次事件
    last_field = [e for e in events if e[0] == APP_STATE_UPDATED][-1][1]["field"]
    assert last_field == "account"

    clock = ClockStateDTO(status="RUNNING", sim_day="2025-09-08", speed=1.0, ts=1)
    app_state.update_clock(clock)
    last_field = [e for e in events if e[0] == APP_STATE_UPDATED][-1][1]["field"]
    assert last_field == "clock"

    app_state.apply_settings_overlay(language="en_US", theme="dark")
    last_evt = [e for e in events if e[0] == APP_STATE_UPDATED][-1][1]
    assert last_evt["field"] == "settings_overlay"
    assert last_evt["value"]["language"] == "en_US"

    key_before = app_state.indicator_cache_key
    new_key = app_state.bump_indicator_cache()
    assert new_key != key_before
    last_evt = [e for e in events if e[0] == APP_STATE_UPDATED][-1][1]
    assert last_evt["field"] == "indicator_cache_key"


def test_settings_state_persistence(tmp_path):
    events = []
    event_bus.subscribe(SETTINGS_STATE_INIT, lambda t, p: events.append((t, p)))
    event_bus.subscribe(SETTINGS_STATE_UPDATED, lambda t, p: events.append((t, p)))

    path = tmp_path / "settings.json"
    st = SettingsState.load(str(path))  # 不存在 -> 默认
    assert events[0][0] == SETTINGS_STATE_INIT
    assert st.language == "zh_CN"

    st.set_language("en_US")
    st.set_theme("dark")
    st.set_refresh_interval(500)
    st.set_playback_speed(2.0)
    st.update_alert_threshold("drawdown_pct", 0.2)

    # 保存再加载
    st.persist_path = str(path)
    st.save()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["language"] == "en_US"
    st2 = SettingsState.load(str(path))
    assert st2.language == "en_US"
    assert st2.alert_thresholds["drawdown_pct"] == 0.2

    changed_events = [p for (t, p) in events if t == SETTINGS_STATE_UPDATED]
    # 应至少包含语言与主题修改
    fields_flat = json.dumps(changed_events)
    assert "en_US" in fields_flat and "dark" in fields_flat

