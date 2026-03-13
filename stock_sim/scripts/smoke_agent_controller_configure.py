from app.services.agent_service import AgentService, BatchCreateConfig, AgentServiceError
from app.controllers.agent_controller import AgentController

svc = AgentService()
ctrl = AgentController(svc)

# 创建一个 agent 供测试
res = svc.batch_create_retail(BatchCreateConfig(count=1, agent_type="Retail", name_prefix="smk"))
aid = res['success_ids'][0]
print("aid", aid)

# 正常路径：configure 与 distill
cfg = ctrl.configure(aid, {"lr": 0.1})
dst = ctrl.distill(aid, {"epochs": 10})
print("cfg_done", cfg['status']['done'], "dst_done", dst['status']['done'])

# 错误路径：不存在的 agent
try:
    ctrl.configure("unknown-agent", {})
except AgentServiceError as e:
    print("err", e.code)

