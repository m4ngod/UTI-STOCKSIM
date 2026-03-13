import sys, time
ROOT = r"F:\PythonProjects\stock_sim"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from infra.event_bus import event_bus
from app.services.agent_service import AgentService
from app.controllers.agent_creation_controller import AgentCreationController

progress_events = []
completed_event = None

def on_progress(topic, payload):
    st = payload.get('status', {})
    print("[EVT]", topic, st)
    progress_events.append(st)


def on_completed(topic, payload):
    global completed_event
    st = payload.get('status', {})
    print("[DONE]", topic, st)
    completed_event = st

# 订阅事件
event_bus.subscribe("agent.batch.create.progress", on_progress)
event_bus.subscribe("agent.batch.create.completed", on_completed)

# 构造控制器
svc = AgentService()
ctl = AgentCreationController(svc)

# 启动任务
res = ctl.batch_create_multi_strategy(count=60, name_prefix="demo", agent_type="Retail", chunk_size=10, concurrency=2)
job_id = res["job_id"]
print("job_id:", job_id)

# 等待第一个进度到来
for _ in range(20):
    if progress_events:
        break
    time.sleep(0.1)

# 发起取消（验证及时停止）
ctl.cancel_job(job_id)

# 等待完成事件
for _ in range(50):
    if completed_event is not None:
        break
    time.sleep(0.1)

print("progress count:", len(progress_events))
print("completed:", completed_event is not None)
print("final status:", completed_event)

