import sys, inspect
ROOT = r"F:\PythonProjects\stock_sim"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import app.controllers.agent_creation_controller as mod
from app.services.agent_service import AgentService
print('module file:', getattr(mod, '__file__', None))
ctl = mod.AgentCreationController(AgentService())
print('has batch_create:', hasattr(ctl, 'batch_create'))
print('has batch_create_multi_strategy:', hasattr(ctl, 'batch_create_multi_strategy'))
print('dir:', [x for x in dir(ctl) if x.startswith('batch_') or x in ('cancel_job','get_job_status')])
print('class source snippet contains batch_create_multi_strategy:', 'def batch_create_multi_strategy' in inspect.getsource(mod.AgentCreationController))
