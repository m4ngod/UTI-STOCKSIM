import os
import time
from app.services.leaderboard_service import LeaderboardService
from app.controllers.leaderboard_controller import LeaderboardController
from app.services.export_service import ExportService
from app.panels import reset_registry, register_builtin_panels, get_panel
from app.panels.leaderboard import register_leaderboard_panel


def _build_panel():
    reset_registry()
    register_builtin_panels()
    svc = LeaderboardService(ttl_seconds=0.1, agent_count=15)
    ctl = LeaderboardController(svc, ExportService())
    register_leaderboard_panel(ctl)
    panel = get_panel('leaderboard')
    return panel, ctl, svc


def test_leaderboard_panel_basic_refresh_and_selection():
    panel, ctl, svc = _build_panel()
    v1 = panel.get_view()
    assert v1['window'] in v1['windows']
    assert len(v1['rows']) > 0
    assert v1['selected'] is not None
    # equity / drawdown 曲线长度
    assert len(v1['selected']['equity_curve']) == 50
    assert len(v1['selected']['drawdown_curve']) == 50 or v1['selected']['drawdown_curve'] == [0.0]


def test_leaderboard_panel_rank_delta_after_second_refresh():
    panel, ctl, svc = _build_panel()
    # 第一刷新已在 __init__ 完成; 等待 TTL 过期再刷新
    time.sleep(0.12)
    panel.refresh(force=False)
    v2 = panel.get_view()
    # 期望部分行出现 rank_delta (可能为正/负/0)
    deltas = [r['rank_delta'] for r in v2['rows'] if r['rank_delta'] is not None]
    assert len(deltas) > 0


def test_leaderboard_panel_sort_and_window_switch():
    panel, ctl, svc = _build_panel()
    # 切换窗口 (存在窗口之一)
    windows = panel.get_view()['windows']
    tgt = '7d' if '7d' in windows else windows[0]
    panel.set_window(tgt)
    v = panel.get_view()
    assert v['window'] == tgt
    # 设置排序 return_pct
    panel.set_sort('return_pct')
    v2 = panel.get_view()
    rows = v2['rows']
    if len(rows) >= 2:
        assert rows[0]['return_pct'] >= rows[1]['return_pct']


def test_leaderboard_panel_export_csv(tmp_path="."):
    panel, ctl, svc = _build_panel()
    path = panel.export('csv')
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        head = f.readline()
    assert head.startswith('# meta ')

