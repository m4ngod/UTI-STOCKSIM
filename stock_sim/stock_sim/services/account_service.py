# 适配器: 使 from stock_sim.services.account_service 导入顶层实现
from services.account_service import AccountService  # type: ignore
__all__ = ["AccountService"]

