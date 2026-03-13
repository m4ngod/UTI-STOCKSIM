import sys, time
ROOT = r"F:\PythonProjects\stock_sim"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.agent_service import AgentService
from app.controllers.agent_creation_controller import AgentCreationController
from app.panels.agent_creation.dialog import AgentCreationDialog

svc = AgentService()
ctl = AgentCreationController(svc)
dlg = AgentCreationDialog(ctl)

# 设置批量参数并启动
dlg.set_batch_params(count=5, name_prefix="demo")
print("params:", dlg.get_view()["params"])  # 期望 count=5

ok = dlg.start_batch(agent_type="Retail")
print("start ok:", ok)

# 等待后台线程完成 (最多3秒)
for _ in range(30):
    v = dlg.get_view()
    if not v["progress"]["running"]:
        break
    time.sleep(0.1)

view = dlg.get_view()
print("running:", view["progress"]["running"], "last_error:", view["last_error"])  # 期望 False, None
print("result keys:", sorted(list(view["last_result"].keys())) if view["last_result"] else None)
print("success count:", len(view["last_result"]["success_ids"]) if view["last_result"] else None)

