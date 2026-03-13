from app.controllers import LeaderboardController, ClockController, SettingsController
from app.services.leaderboard_service import LeaderboardService
from app.services.export_service import ExportService
from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService
from app.state.settings_store import SettingsStore
import os


def test_leaderboard_controller_refresh_and_export(tmp_path):
    svc = LeaderboardService(ttl_seconds=0.0, agent_count=10)
    export = ExportService()
    ctl = LeaderboardController(svc, export)
    # 首次刷新
    rows1 = ctl.refresh('7d', limit=5)
    assert len(rows1) == 5
    assert all(r.rank >= 1 for r in rows1)
    # 第二次刷新 (force_refresh) 应产生 rank_delta (除首次出现的)
    rows2 = ctl.refresh('7d', limit=5, force_refresh=True)
    # 至少一个 row 的 rank_delta 不为 None
    assert any(r.rank_delta is not None for r in rows2)
    # 导出 CSV
    out_path = ctl.export('7d', 'csv', limit=5, file_path=str(tmp_path / 'lb.csv'))
    assert os.path.exists(out_path)
    with open(out_path, 'r', encoding='utf-8') as f:
        head = f.readline().strip()
    assert head.startswith('# meta') and 'window=7d' in head


def test_clock_controller_rollback_and_restart():
    clock = ClockService()
    rollback = RollbackService(clock)
    ctl = ClockController(clock, rollback)
    st1 = ctl.start('2024-12-20')
    assert st1.status == 'RUNNING' and st1.sim_day == '2024-12-20'
    cp1 = ctl.create_checkpoint('before-switch')
    # 切换交易日 (仍 RUNNING)
    st2 = ctl.start('2024-12-21')
    assert st2.sim_day == '2024-12-21'
    cp2 = ctl.create_checkpoint('after-switch')
    # 回滚到 cp1 -> 应恢复 2024-12-20
    ctl.rollback(cp1)
    st_after = ctl.state()
    assert st_after.sim_day == '2024-12-20' and st_after.status == 'RUNNING'
    # 再次启动(同日) 不改变 sim_day
    st_restart = ctl.start('2024-12-20')
    assert st_restart.sim_day == '2024-12-20'


def test_settings_controller_hot_update(tmp_path):
    store = SettingsStore(path=str(tmp_path / 'settings.json'))
    ctl = SettingsController(store)
    events = []
    ctl.on_language(lambda k, v, full: events.append((k, v)))
    ctl.set_language('en_US')
    ctl.set_theme('dark')
    ctl.set_refresh_interval(2000)
    ctl.update_alert_threshold('drawdown_pct', 0.2)
    state = ctl.get_state()
    assert state.language == 'en_US'
    assert state.theme == 'dark'
    assert state.refresh_interval_ms == 2000
    assert state.alert_thresholds['drawdown_pct'] == 0.2
    assert any(e[1] == 'en_US' for e in events)

