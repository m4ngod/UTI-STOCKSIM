# python
from datetime import datetime, date, timedelta
from .models_imports import Base, Column, String, DateTime, Index, SimTimeMixin
from stock_sim.services.sim_clock import current_sim_day

class AgentBinding(Base, SimTimeMixin):
    __tablename__ = "agent_bindings"
    agent_name = Column(String(128), primary_key=True)  # 智能体 / 散户名称（唯一）
    agent_type = Column(String(32), default="GENERIC", index=True)  # ALT / RETAIL / OTHER
    account_id = Column(String(64), unique=True, index=True)  # 一账户只允许被一个绑定占用
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)
    meta = Column(String(4096), nullable=True)  # 新增: 持久化智能体配置 (JSON 字符串)

    def touch(self):
        self.updated_at = datetime.utcnow()
        # 同步模拟时钟字段
        try:
            d = current_sim_day()
            if d:
                self.sim_day = d
                # 虚拟日期从公元 1 年起逐日推进
                self.sim_dt = datetime(1,1,1) + timedelta(days=d-1)
        except Exception:
            pass

Index("idx_agent_bindings_account", AgentBinding.account_id)
