import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from infra.event_bus import event_bus
from app.event_bridge import subscribe_topic

cnt = {'n': 0}

def h(topic, payload):
    cnt['n'] += 1
    print('handled', topic, payload, flush=True)

# direct subscribe/unsubscribe
h_ref = event_bus.subscribe('x.topic', h)
event_bus.publish('x.topic', {'a':1})
event_bus.unsubscribe('x.topic', h_ref)
event_bus.publish('x.topic', {'a':2})
print('count1', cnt['n'], flush=True)

# helper subscribe_topic
cancel = subscribe_topic('y.topic', h)
event_bus.publish('y.topic', {'b':3})
cancel()
event_bus.publish('y.topic', {'b':4})
print('count2', cnt['n'], flush=True)

