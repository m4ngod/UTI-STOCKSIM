# python
"""Agent Meta Listener
负责:
 1. 订阅 EventType.AGENT_META_UPDATE: 实时持久化单个或全部智能体元数据(meta)
 2. 订阅 EventType.SIM_DAY: 按模拟交易日(压缩 4h->30s) 执行:
      - 刷新全部智能体 meta 持久化
      - 调用所有 OrderService.daily_reset() 重置日内风险 / T+1 统计
 可由 StrategyPage 注册 provider, provider 返回上下文 dict:
   {
     'agents': list[agent],
     'binding': AgentBindingService,
     'order_services': dict[str, OrderService],
     'main_order_service': OrderService | None,
   }
"""
from __future__ import annotations
from typing import Callable, Any, Dict
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.persistence.models_account import Account as AccountORM  # 新增
from stock_sim.persistence.models_position import Position as PositionORM  # noqa: F401 (类型提示)

_provider: Callable[[], dict] | None = None
_started = False

# -------- Public API --------

def register_agent_provider(fn: Callable[[], dict]):
    global _provider
    _provider = fn

# -------- Internal Helpers --------

def _capture_meta(agent) -> dict:
    meta = {}
    try:
        meta['cls'] = agent.__class__.__name__
        for attr in ('interval','lot_size','multi_symbol','symbol'):
            if hasattr(agent, attr):
                v = getattr(agent, attr)
                if v is not None:
                    meta[attr] = v
        # 策略字段兼容两种实现
        stg = None
        if hasattr(agent, 'stats') and hasattr(agent.stats, 'strategy'):
            stg = getattr(agent.stats, 'strategy')
        if not stg and hasattr(agent, 'strategy_name'):
            stg = getattr(agent, 'strategy_name')
        if stg:
            meta['strategy'] = stg
    except Exception:
        pass
    return meta

def _capture_account_snapshot(binding, agent_name: str) -> dict | None:
    if not binding or not hasattr(binding, '_get_session'):
        return None
    try:
        # 获取绑定记录以拿到账户ID
        rec = binding.get(agent_name)
        acct_id = None
        if rec:
            if isinstance(rec, dict):
                acct_id = rec.get('account_id') or rec.get('acct') or rec.get('account')
            else:
                acct_id = getattr(rec, 'account_id', None)
        if not acct_id:
            return None
        with binding._get_session() as s:  # 使用服务内部上下文
            acc = s.get(AccountORM, acct_id)
            if not acc:
                return None
            positions = []
            nav = float(getattr(acc, 'cash', 0.0))
            for p in getattr(acc, 'positions', [])[:20]:  # 限制最多20条
                qty = int(getattr(p, 'quantity', 0))
                avg = float(getattr(p, 'avg_price', 0.0) or 0.0)
                if qty <= 0 and getattr(p, 'frozen_qty', 0) <= 0:
                    continue
                nav += qty * avg
                positions.append({
                    'symbol': getattr(p, 'symbol', ''),
                    'qty': qty,
                    'avg': avg,
                    'frozen': int(getattr(p, 'frozen_qty', 0) or 0)
                })
            return {
                'account_id': acct_id,
                'cash': float(getattr(acc, 'cash', 0.0)),
                'nav': nav,
                'positions': positions
            }
    except Exception:
        return None

def _persist_agent(agent, binding):
    if not binding:
        return
    try:
        if not hasattr(binding, 'set_meta'):
            return
        meta = _capture_meta(agent)
        acct_snap = _capture_account_snapshot(binding, getattr(agent, 'name', ''))
        if acct_snap:
            # 合并账户关键信息 (避免过大 JSON，可只保留摘要)
            meta['account'] = {
                'id': acct_snap['account_id'],
                'cash': round(acct_snap['cash'], 2),
                'nav': round(acct_snap['nav'], 2),
                'positions': acct_snap['positions'][:10]  # 前10条
            }
        binding.set_meta(getattr(agent, 'name'), meta)
    except Exception:
        pass

# -------- Event Handlers --------

def _on_agent_meta_update(topic: str, payload: dict):  # noqa: ARG001
    ctx = _provider() if _provider else None
    if not ctx:
        return
    agents = ctx.get('agents') or []
    binding = ctx.get('binding')
    target = payload.get('agent') if isinstance(payload, dict) else None
    if target:
        # 只更新指定
        for ag in agents:
            if getattr(ag, 'name', None) == target:
                _persist_agent(ag, binding)
                break
    else:
        # 全量
        for ag in agents:
            _persist_agent(ag, binding)


def _on_sim_day(topic: str, payload: dict):  # noqa: ARG001
    ctx = _provider() if _provider else None
    if not ctx:
        return
    agents = ctx.get('agents') or []
    binding = ctx.get('binding')
    # 1) 全量 meta 刷新
    for ag in agents:
        _persist_agent(ag, binding)
    # 2) daily_reset
    order_services: Dict[str, Any] = ctx.get('order_services') or {}
    root = ctx.get('main_order_service')
    seen = set()
    for svc in order_services.values():
        if not svc or svc in seen:
            continue
        seen.add(svc)
        try:
            if hasattr(svc, 'daily_reset'):
                svc.daily_reset()
        except Exception:
            pass
    if root and root not in seen and hasattr(root, 'daily_reset'):
        try:
            root.daily_reset()
        except Exception:
            pass

# -------- Bootstrap --------

def ensure_agent_meta_listener_started():
    global _started
    if _started:
        return
    event_bus.subscribe(EventType.AGENT_META_UPDATE, _on_agent_meta_update, async_mode=False)
    event_bus.subscribe(EventType.SIM_DAY, _on_sim_day, async_mode=False)
    _started = True
    return True
