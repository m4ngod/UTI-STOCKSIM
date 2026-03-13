# python
# file: settings.py

class Settings:
    # 数据库配置
    DB_HOST: str = "localhost"
    DB_PORT: int = 3308
    DB_USER: str = "root"
    DB_PASSWORD: str = "yu20010402"
    DB_NAME: str = "stock_sim"
    DB_URL: str | None = None  # 若为空使用内置 sqlite 回退
    ECHO_SQL: bool = False

    # 账户/系统参数
    DEFAULT_CASH: float = 1_000_000.0

    # Redis / 功能开关
    REDIS_ENABLED: bool = False

    # 借券 / 费用
    BORROW_FEE_ENABLED: bool = True
    BORROW_RATE_DAILY: float = 0.0005  # 日费率 5bps
    BORROW_FEE_MIN_NOTIONAL: float = 0.0

    # 费用 (占位，可扩展)
    MAKER_FEE_BPS: float = 0.0

    # 风控参数
    MAX_SINGLE_ORDER_NOTIONAL: float = 1_000_000_000.0
    MAX_ORDER_QTY: int = 10_000_000
    MAX_POSITION_RATIO: float = 1.0
    RISK_DISABLE_SHORT: bool = False
    BROKER_UNLIMITED_LENDING: bool = True
    MAX_NET_EXPOSURE_NOTIONAL: float = 5_000_000_000.0
    MAX_GROSS_EXPOSURE_NOTIONAL: float = 10_000_000_000.0

    # 事务控制
    TXN_MAX_SECONDS: float = 2.0
    TXN_EARLY_MIN_ORDERS: int = 10
    TXN_LOCK_TIMEOUT_CODES: tuple[int, ...] = (1205, 1213)

    # 集合竞价 / 快照
    AUCTION_ENABLED: bool = True
    AUCTION_SIM_FAST: bool = True
    AUCTION_DEFAULT_PREV_CLOSE: float = 100.0

    SNAPSHOT_THROTTLE_N_PER_SYMBOL: int = 5
    SNAPSHOT_DIR: str = "snapshots"
    SNAPSHOT_ENABLE: bool = True

    # 回放 / 性能
    ORDER_RATE_WINDOW_SEC: int = 3
    ORDER_RATE_MAX: int = 50

    # 强平 (简化)
    LIQUIDATION_ENABLED: bool = True
    MAINTENANCE_MARGIN_RATIO: float = 0.25
    LIQUIDATION_ORDER_SLICE_RATIO: float = 0.25
    LIQUIDATION_MAX_ORDERS_PER_ACCOUNT: int = 3

    JSON_LOG_PATH: str = "logs/struct.log"

    def build_db_url(self) -> str:
        if self.DB_URL:
            return self.DB_URL
        return "sqlite:///stock_sim_test.db"

    # 兼容旧代码
    def assembled_db_url(self) -> str:  # noqa: D401
        """Backward compatible wrapper for build_db_url()."""
        return self.build_db_url()


settings = Settings()
__all__ = ["Settings", "settings"]
