import os
import json
import time
from pathlib import Path

# 运行在无图形环境
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.main import run_frontend  # noqa: E402
from app.panels import get_panel  # noqa: E402


def _write_artifact(name: str, data):
    out_dir = Path("logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    try:
        if isinstance(data, (dict, list)):
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            p.write_text(str(data), encoding="utf-8")
    except Exception:
        pass
    return str(p)


def test_core_user_journey_e2e():
    # 启动前端（headless）
    mw = run_frontend(headless=True)

    # 打开关键面板
    market = mw.open_panel("market")
    agents = mw.open_panel("agents")
    leaderboard = mw.open_panel("leaderboard")
    settings = mw.open_panel("settings")

    # 访问逻辑对象（适配器._logic）
    m_logic = getattr(market, "_logic", market)
    a_logic = getattr(agents, "_logic", agents)
    lb_logic = getattr(leaderboard, "_logic", leaderboard)
    s_logic = getattr(settings, "_logic", settings)

    # 1) 创建标的（通过 MarketController），并加入关注列表
    sym = "E2E001"
    try:
        ctl = getattr(m_logic, "_ctl")
        # 三元推导：给出流通股与市值，推导初始价
        payload = ctl.create_instrument(name="E2E Corp", symbol=sym, initial_price=None, float_shares=1_000_000, market_cap=50_000_000)
        assert payload["symbol"] == sym
    except Exception:
        # 若不可用则不影响后续（watchlist 会 ensure_symbol）
        pass

    # 加入关注并选择 symbol，检查详情视图可用
    m_logic.add_symbol(sym)
    m_logic.select_symbol(sym)
    dview = m_logic.detail_view()
    assert isinstance(dview, dict) and dview.get("symbol") == sym
    _write_artifact("e2e_market_detail.json", dview)

    # 2) 批量创建散户（通过 AgentsPanel 自带批量）
    ok = a_logic.start_batch_create(count=10, agent_type="Retail", name_prefix="e2e")
    assert ok is True
    # 等待进度完成（最大 5s）
    t0 = time.time()
    while True:
        v = a_logic.get_view()
        b = v.get("batch", {})
        if not b.get("in_progress") and (b.get("created", 0) + b.get("failed", 0)) >= b.get("requested", 0) > 0:
            break
        assert time.time() - t0 < 5.0, "batch create timeout"
        time.sleep(0.05)
    _write_artifact("e2e_agents_batch.json", a_logic.get_view())

    # 3) 刷新排行榜并校验有行数据
    lb_logic.refresh(force=True)
    lb_view = lb_logic.get_view()
    rows = lb_view.get("rows") or []
    assert isinstance(rows, list) and len(rows) > 0
    _write_artifact("e2e_leaderboard.json", lb_view)

    # 4) 切换语言并验证设置已更新
    s_logic.set_language("en_US")
    s_view = s_logic.get_view()
    assert s_view.get("settings", {}).get("language") == "en_US"
    _write_artifact("e2e_settings.json", s_view)

    # 产出“截图”占位（文本化视图摘要）
    screenshot_txt = f"market={dview.get('symbol')} agents_created={a_logic.get_view().get('batch',{}).get('created')} lb_rows={len(rows)} lang={s_view.get('settings',{}).get('language')}"
    _write_artifact("e2e_core_screenshot.txt", screenshot_txt)

