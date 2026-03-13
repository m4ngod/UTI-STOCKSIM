from stock_sim.services.recovery_service import recovery_service
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType

def test_recovery_service_emits_event():
    captured = []
    event_bus.subscribe(EventType.RECOVERY_RESUMED, lambda t,p: captured.append(p))
    rep = recovery_service.recover()
    assert rep['status'] == 'ok'
    assert captured and captured[0]['status'] == 'ok'

