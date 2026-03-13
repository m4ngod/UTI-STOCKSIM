import time, os, pytest
from infra.event_bus import event_bus
from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC
from app.services.market_data_service import MarketDataService
from app.controllers.market_controller import MarketController
from app.controllers.agent_creation_controller import AgentCreationController
from app.services.agent_service import AgentService
from app.controllers.agent_config_controller import AgentConfigController
from app.state.version_store import VersionStore
from app.security.script_validator import ScriptValidator
from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService
from app.services.leaderboard_service import LeaderboardService
from app.controllers.leaderboard_controller import LeaderboardController
from app.indicators.executor import indicator_executor

def test_full_journey_v2(tmp_path):
    bridge = EventBridge(flush_interval_ms=30, max_batch_size=128)
    market_ctrl = MarketController(MarketDataService())
    def on_batch(_t, payload):
        snaps = payload.get('snapshots') or []
        market_ctrl.merge_batch([{k:v for k,v in s.items() if k!='_t'} for s in snaps])
    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, on_batch)
    bridge.start()
    for i in range(80):
        bridge.on_snapshot({
            'symbol': f'SYM{i%5:02d}',
            'last': 100 + (i%30)*0.05,
            'bid_levels':[(100,5)], 'ask_levels':[(100.1,6)],
            'volume': i, 'turnover': float(i)*3.0,
            'ts': int(time.time()*1000), 'snapshot_id': f'sj-{i}', '_t': time.perf_counter_ns()})
    time.sleep(0.25)
    bridge.stop()
    view = market_ctrl.list_snapshots()
    assert view['total'] >= 5

    agent_service = AgentService()
    creation = AgentCreationController(agent_service)
    r = creation.batch_create(agent_type='Retail', count=3, name_prefix='rt')
    assert len(r['success_ids']) == 3 and not r['failed']

    symbol = market_ctrl.list_snapshots()['items'][0].symbol
    done = {'flag': False}
    def cb(result, *, symbol, name, params, error, duration_ms, cache_key):
        done['flag']=True; done['error']=error; done['dur']=duration_ms; done['res']=result
    fut = market_ctrl.request_indicator(symbol=symbol, timeframe='1m', name='ma', callback=cb, window=5)
    fut.result(timeout=5)
    t0=time.time()
    while not done['flag'] and time.time()-t0<5:
        indicator_executor.poll_callbacks(); time.sleep(0.02)
    assert done['flag'], 'indicator_cb_timeout'
    assert done['error'] is None and done['res'] is not None

    vs=VersionStore(str(tmp_path/'version_store.json'))
    validator=ScriptValidator()
    cfg=AgentConfigController(agent_service, vs, validator)
    aid=agent_service.list_agents()[0].agent_id
    v1=cfg.add_version(aid, {'p':1}, author='u'); v2=cfg.add_version(aid, {'p':2}, author='u'); v3=cfg.rollback(aid,1,'u')
    assert (v1.version,v2.version,v3.version)==(1,2,3) and v3.rollback_of==1

    clock=ClockService(); rb=RollbackService(clock)
    clock.start('2025-09-01'); cp=rb.create_checkpoint('base'); clock.start('2025-09-02'); rb.rollback(cp)
    assert clock.get_state().sim_day=='2025-09-01'

    lb=LeaderboardController(LeaderboardService())
    lb.refresh('1d', limit=10)
    path=lb.export('1d','csv',limit=10)
    assert os.path.isfile(path)
    with open(path,'r',encoding='utf-8') as f: first=f.readline().strip()
    assert first.startswith('# meta ') and 'window=1d' in first

    print('journey_v2_status', {'snapshots': view['total'], 'agents': len(agent_service.list_agents()), 'indicator_ms': done['dur'], 'versions':[x.version for x in cfg.list_versions(aid)], 'export': path})

