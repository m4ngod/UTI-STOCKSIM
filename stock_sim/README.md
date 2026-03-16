# StockSim 全面说明文档

> 一个面向撮合 / 账户 / 风险控制 / 融资融券(卖空) / IPO / 策略仿真 与 回测 + 强化学习环境 的多标的股票/衍生品撮合与账户结算模拟平台。
>
> 设计目标：在尽量贴近真实交易撮合与账户资金/持仓演化细节的前提下，提供快速可扩展的研究/教学/策略实验底座。

---
## 目录导航
- [1. 特性概览](#1-特性概览)
- [2. 架构总览](#2-架构总览)
- [3. 目录结构说明](#3-目录结构说明)
- [4. 核心领域模型与概念](#4-核心领域模型与概念)
- [5. 多标的撮合引擎 (MatchingEngine)](#5-多标的撮合引擎-matchingengine)
- [6. IPO 集合竞价外部化流程](#6-ipo-集合竞价外部化流程)
- [7. 卖空 / 融券机制](#7-卖空--融券机制)
- [8. 账户与结算(AccountService)](#8-账户与结算accountservice)
- [9. 风险控制(RiskEngine)](#9-风险控制riskengine)
- [10. 费用模型(FeeEngine)](#10-费用模型feeengine)
- [11. 快照节流与行情事件](#11-快照节流与行情事件)
- [12. 事件总线 & 事件类型](#12-事件总线--事件类型)
- [13. 模拟时钟与日切](#13-模拟时钟与日切)
- [14. 强化学习 (RL) 与策略执行](#14-强化学习-rl-与策略执行)
- [15. 前端可视化 (PySide6 + pyqtgraph)](#15-前端可视化-pyside6--pyqtgraph)
- [16. 数据持久化与数据库结构](#16-数据持久化与数据库结构)
- [17. 配置系统(settings)](#17-配置系统settings)
- [18. 典型订单生命周期](#18-典型订单生命周期)
- [19. 使用入门 (Quick Start)](#19-使用入门-quick-start)
- [20. 代码示例碎片](#20-代码示例碎片)
- [21. 测试与验证](#21-测试与验证)
- [22. 性能与扩展方向](#22-性能与扩展方向)
- [23. 常见问题 FAQ](#23-常见问题-faq)
- [24. Roadmap / 下一步计划](#24-roadmap--下一步计划)
- [25. 贡献指南](#25-贡献指南)
- [26. 数据库 ER 图](#26-数据库-er-图)
- [27. 事件 JSON 示例](#27-事件-json-示例)
- [28. RL 环境观测与动作空间定义](#28-rl-环境观测与动作空间定义)
- [29. 自适应快照节流 (Adaptive Snapshot Policy)](#29-自适应快照节流-adaptive-snapshot-policy)
- [30. 事件持久化与回放 (Event Sourcing & Replay)](#30-事件持久化与回放-event-sourcing--replay)
- [31. 恢复与状态重建 (Recovery)](#31-恢复与状态重建-recovery)
- [32. 借券费用与强平 (Borrow Fee & Liquidation)](#32-借券费用与强平-borrow-fee--liquidation)
- [33. 扩展风险规则注册表 (Risk Rule Registry)](#33-扩展风险规则注册表-risk-rule-registry)
- [34. RL 账户融合与向量化 (AccountAdapter & Vectorized RL)](#34-rl-账户融合与向量化-accountadapter--vectorized-rl)

---
## 1. 特性概览
- 多标的(Multi-Book)单引擎管理：一个 MatchingEngine 实例内维护多个 symbol 的独立簿 (BookState)。
- 支持集合竞价 → 连续竞价阶段切换；IPO 自动开盘逻辑外部化（ipo_service.maybe_auto_open_ipo）。
- 限价单 / 市价单；TimeInForce: GFD / IOC / FOK（可扩展 GTC / DAY 语义）。
- 可扩展的订单撮合：价格优先 + 时间优先；市价多档逐次吃单；FOK 预检查。
- 卖空 / 融券：LendingPool + AccountService + RiskEngine 协同；借券库存(或无限模式)；回补自动归还。
- 账户结算：冻结资金 / 释�� / 手续费预冻结 / 借券数量 borrowed_qty 维护 / 逐笔与批量结算。
- 事件驱动：统一 EventBus 发布订单、成交、快照、账户、IPO、K线、策略切换等事件。
- 快照节流：按簿独立计数 ops_since_snapshot，阈值(settings.SNAPSHOT_THROTTLE_N_PER_SYMBOL) 或有成交立即刷新。
- 模拟时钟：支持虚拟交易日推进 (SIM_DAY 事件) 与对象时间戳写入。
- 数据持久化：SQLAlchemy ORM，账户 / 持仓 / 订单 / 订单事件 / 成交 / 快照 / 资金流水 (Ledger)。
- 可选 Redis 集成：行情 / 状态推送或共享（后续扩展）。
- 强化学习环境：rl/ 内部 TradingEnv / PPO Agent（示例代码骨架）。
- 前端 GUI（PySide6 + pyqtgraph）快速查看行情簿与策略状态（开发中）。

---
## 2. 架构总览
逻辑分层（简化）：

```
+--------------------------------------------------------------+
|                        前端 / 可视化 (app)                   |
+---------------------+----------------------+-----------------+
|   策略层 / RL (agents, rl) |  监控 & 指标 (observability)   |  Scripts  |
+---------------------+----------------------+-----------------+
|            服务层 (services/*)  - Orchestrators              |
| 订单(OrderService) / 风控(RiskEngine) / 账户(AccountService) |
| 费用(FeeEngine) / IPO / LendingPool / Snapshot / Clock ...   |
+--------------------------------------------------------------+
|                  核心撮合 (core/* MatchingEngine)             |
| 订单/撮合/簿/集合竞价/快照/校验/常量/行情                     |
+--------------------------------------------------------------+
|                基础设施 (infra) 事件总线 / UoW / Repo         |
+--------------------------------------------------------------+
|                    持久化 (persistence ORM)                   |
+--------------------------------------------------------------+
|                        外部依赖: MySQL / Redis               |
+--------------------------------------------------------------+
```

---
## 3. 目录结构说明 (截取关键路径)
```
core/                撮合与基础领域模型 (matching_engine, order, trade, snapshot, const ...)
services/            各类业务服务：order_service / account_service / risk_engine / ipo_service / lending_pool ...
infra/               通用基础设施：event_bus, repository, unit_of_work
persistence/         SQLAlchemy ORM 模型定义 (accounts, positions, orders, trades, ledger ...)
observability/       指标(metrics) + 结构化日志(struct_logger)
rl/                  强化学习环境 (trading_env.py) 与 PPO 示例
agents/              策略/代理封装 (多策略、零售/机构示例)
app/                 桌面端前端与可视化入口 (当前实现)
configs/             配置样例 (env_m1.yaml 等)
scripts/             运行/评估脚本
settings.py          Pydantic BaseSettings 全局配置
pyproject.toml       项目依赖与构建元数据
README.md            本文档
```

---
## 4. 核心领域模型与概念
- Order：订单请求；字段含 symbol / side / price / quantity / tif / status / filled / remaining / meta。
- BookState：某一 symbol 的撮合上下文（bids, asks, index, trades, snapshot, phase, instrument_meta, ops_since_snapshot）。
- Snapshot：盘口快照（多档买卖、最近价、量、成交额、开收盘价）。
- Trade：撮合成交记录（价、量、买单ID、卖单ID、账户对）。
- Phase：市场阶段（CALL_AUCTION / CONTINUOUS / PREOPEN / CLOSED）。
- Instrument Meta：tick_size / lot_size / min_qty / settlement_cycle / IPO & 股本信息。
- Position：账户持仓（quantity / frozen_qty / avg_price / borrowed_qty）。
- Ledger：资金流水（买/卖，费用，税费，现金变动，真实盈利 pnl_real）。

---
## 5. 多标的撮合引擎 (MatchingEngine)
特点：
- 通过内部字典 `_books: Dict[symbol, BookState]` 管理多标的簿。
- `register_symbol()` 注册并创建独立 BookState；`ensure_symbol()` 懒加载（下单时自动）。
- 集合竞价阶段：若订单为市价 → 价格替换为无穷 (BUY=inf / SELL=0) 以模拟市场订单。
- 成交过程：价格交叉检测、逐笔生成 Trade、更新 snapshot（last/volume/turnover）。
- IOC / FOK：撮合后剩余部分按规则撤销/拒绝；FOK 预判是否可一次满足。
- Snapshot 节流：簿操作（加入/移除/撮合）计数达到阈值或出现成交强制刷新。
- IPO 自动开盘：进入 `ipo_service.maybe_auto_open_ipo` 外部逻辑判断（集合竞价阶段、仅买单、initial_price 等条件）。

---
## 6. IPO 集合竞价外部化流程
触发条件：
1. 处于 CALL_AUCTION；
2. 仅有买单（无卖单）；
3. instrument_meta 包含 `initial_price` 与流通股本信息 (free_float_shares / total_shares)。
逻辑：
- 按时间优先 & 价格一致（发行价）撮合分配；
- 生成 TRADE + IPO_OPENED 事件；
- 剩余买单迁移至连续竞价簿；
- 标记 `ipo_opened=True`，阶段切换为 CONTINUOUS。

---
## 7. 卖空 / 融券机制
组件：LendingPool + RiskEngine + AccountService。
流程摘要：
1. 卖出下单：若可用多头 position.quantity - frozen_qty 不足且允许卖空 (settings.RISK_DISABLE_SHORT=False)，尝试借券 (LendingPool.borrow)。
2. 借券成功：position.borrowed_qty += 借入量；同时把目标数量冻结（frozen_qty）。
3. 成交结算：
   - 卖方 position.quantity 减少（可转负，表示形成空头），borrowed_qty 设为 max(0, -quantity)。
   - 买方回补：若其买入导致原负仓头寸向 0 靠近 → 自动归还借券 (LendingPool.repay)。
4. 回补规则：仅在买方成交后检测净仓位是否覆盖空头；借券库存恢复。

---
## 8. 账户与结算(AccountService)
职责：
- 账户创建 / 获取 (默认初始现金 settings.DEFAULT_CASH)。
- 订单冻结：买单冻结资金(含预冻结手续费)；卖单冻结持仓或触发借券；撤单/未成交释放。
- 成交结算：更新买卖双方现金 / 持仓 / 平均成本 / 借券回补 / 手续费 / 税费；写入 Ledger；发布 ACCOUNT_UPDATED 事件。
- 批量结算：聚合多笔成交后统一写入，减少数据库写放大；处理借券归还逻辑。
- 时间戳：模拟时钟写入 sim_day/sim_dt 字段（SimTimeMixin）。

账户事件字段（每个 position）：
`symbol / quantity / frozen_qty / avg_price / borrowed_qty / settlement_cycle`。

---
## 9. 风险控制(RiskEngine)
可扩展的检查：
- 单笔名义金额上限 (MAX_SINGLE_ORDER_NOTIONAL)。
- 订单数量上限 (MAX_ORDER_QTY)。
- 持仓比例限制 (MAX_POSITION_RATIO)。
- 卖空可用库存 / 融券可借验证（与 LendingPool 协同）。
- 日内成交额、净风险敞口 (MAX_NET_EXPOSURE_NOTIONAL / DAY_NOTIONAL_LIMIT)。
- 订单速率 (ORDER_RATE_WINDOW_SEC + ORDER_RATE_MAX)。
- T+1 限制：根据 settlement_cycle 判断可卖数量；日切时重置基准。

---
## 10. 费用模型(FeeEngine)
- 依据 side/price/quantity 估算撮合基数金额 basis_notional。
- 计算 taker/maker 费率、印花税、过户费 (当前印花 / 过户默认为 0，可配置)。
- 预冻结：买单 est_fee 预冻结，部分未成交撤单按比例退还。
- 成交结算：实际费用从冻结转实扣，差额（若预估过高）退还。

---
## 11. 快照节流与行情事件
- 每个 symbol 独立 `ops_since_snapshot` 计数。
- settings.SNAPSHOT_THROTTLE_N_PER_SYMBOL：超过阈值刷新 snapshot 并发布 SNAPSHOT_UPDATED。
- 有成交(force=True) 时即时刷新。
- Snapshot 字段：买卖档 bid_levels / ask_levels（默认截取前 5 档），best_bid/ask 以及 last / volume / turnover / open / close。

---
## 12. 事件总线 & 事件类型
事件总线：`infra/event_bus.py`（发布订阅模式，进程内分发；可扩展到 Redis / MQ）。

主要事件（core.const.EventType）：
- ORDER_ACCEPTED
- ORDER_REJECTED
- ORDER_FILLED
- ORDER_PARTIALLY_FILLED
- ORDER_CANCELED
- TRADE
- ACCOUNT_UPDATED
- SNAPSHOT_UPDATED
- BAR_UPDATED
- STRATEGY_CHANGED
- IPO_OPENED
- SIM_DAY
- AGENT_META_UPDATE

扩展思路：事件序列化后写入日志或消息队列用于回放 / 回测 / 监控。

---
## 13. 模拟时钟与日切
- sim_clock 服务生成虚拟交易日 (SIM_DAY)；对象写入 sim_day/sim_dt。
- AccountService / RiskEngine 在日切时：重置 T+1 基准、清空日内风险计数。
- 可用于加速回测（例如压缩真实 4 小时到 30 秒）。

---
## 14. 强化学习 (RL) 与策略执行
- rl/trading_env.py：封装环境（状态=账户/行情/仓位；动作=下单/撤单/保持）。
- rl/ppo_agent.py：PPO 策略样例（结合 PyTorch 2.8.0）。
- agents/ 多策略调度、零售账户批量生成 (account_service.create_retail_batch)。
- 可将事件流作为训练样本；或将环境步进与撮合同步。

---
## 15. 前端可视化 (PySide6 + pyqtgraph)
- 目标：提供盘口/快照/深度图/K线/账户与策略状态面板。
- services/engine_registry.py：全局撮合引擎注册表，供前端与服务层共享。
- 后续将补充：
  - 图形化订单流展示
  - IPO 状态指示
  - 账户实时盈亏、借券情况

参考: 更完整的前端结构、面板注册、性能与测试说明见 docs/frontend_dev_guide.md。

---
## 16. 数据持久化与数据库结构
使用 SQLAlchemy ORM + MySQL。
关键表（persistence/）：
- accounts / positions (含 borrowed_qty) / orders / order_events / trades / ledger / snapshots / instruments。
- positions 表新增字段：`borrowed_qty INT NOT NULL DEFAULT 0`（如历史库需迁移）。

示例迁移 SQL：
```sql
ALTER TABLE positions ADD COLUMN borrowed_qty INT NOT NULL DEFAULT 0;
ALTER TABLE positions ADD CONSTRAINT uq_positions_account_symbol UNIQUE (account_id, symbol);
```

Ledger 记录真实现金 delta、手续费、税费、真实盈亏(pnl_real)。

---
## 17. 配置系统(settings)
基于 Pydantic BaseSettings：支持环境变量覆盖。
部分关键字段：
- 数据库：DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME / DB_URL
- 风险：MAX_SINGLE_ORDER_NOTIONAL / MAX_ORDER_QTY / RISK_DISABLE_SHORT / BROKER_UNLIMITED_LENDING
- 费用：TAKER_FEE_BPS / MAKER_FEE_BPS / STAMP_DUTY_BPS / TRANSFER_FEE_BPS
- 快照：SNAPSHOT_THROTTLE_N_PER_SYMBOL / SNAPSHOT_ENABLE
- 集合竞价：AUCTION_ENABLED / AUCTION_SIM_FAST
- Redis：REDIS_ENABLED / REDIS_URL

示例（Linux/macOS）:
```bash
export DB_HOST=127.0.0.1
export RISK_DISABLE_SHORT=false
export SNAPSHOT_THROTTLE_N_PER_SYMBOL=10
```

---
## 18. 典型订单生命周期
```
客户端发单 -> OrderService.place_order()
  1. 基础校验 (tick/lot/min_qty)
  2. 风险校验 (RiskEngine)
  3. 费用估算 + 预冻结 (买单)
  4. 名义金额 / 持仓冻结 (AccountService.freeze)
  5. 初始持久化 (orders + order_event)
  6. 撮合引擎 submit_order() (多簿路由)
      - 集合竞价阶段: 加入 CallAuction 队列 / 尝试 IPO 自动开盘
      - 连续竞价阶段: 尝试撮合 -> 生成成交 -> 更新簿与快照
  7. 成交后 AccountService.settle_trade/settle_trades_batch
  8. IOC/FOK 逻辑 -> 可能取消剩余 -> 释放冻结
  9. 事件广播 (订单 / 成交 / 快照 / 账户)
 10. 返回成交列表
```

---
## 19. 使用入门 (Quick Start)
### 19.1 环境准备
1. 安装 Python 3.11+（建议虚拟环境）。
2. 安装 MySQL 并创建数据库 `stock_sim`；执行必要迁移（见第 16 节）。
3. 可选：启动 Redis (若启用 REDIS_ENABLED)。

### 19.2 安装依赖
```bash
pip install -e .
```
(Pytorch 版本固定为 2.8.0+cu129，若本机无匹配 CUDA 可在 pyproject.toml 中调整或使用 CPU 版本。)

### 19.3 最小示例
```python
from stock_sim.core.instruments import create_instrument
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce
from stock_sim.services.order_service import OrderService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from stock_sim.settings import settings

# 数据库会话
engine_db = create_engine(settings.assembled_db_url(), echo=False, future=True)
Session = sessionmaker(bind=engine_db, autoflush=False, expire_on_commit=False)
s = Session()

# 初始标的 & 引擎
inst = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
match_engine = MatchingEngine('AAA', inst)

# OrderService
svc = OrderService(s, engine=match_engine)

order1 = Order(symbol='AAA', side=OrderSide.BUY, order_type=OrderType.LIMIT, price=10.00, quantity=500, tif=TimeInForce.GFD, account_id='ACC1')
trades = svc.place_order(order1)
print('trades=', trades)
```

### 19.4 运行测试
```bash
pytest -q
```
或针对核心多标的测试：
```bash
pytest -q tests/test_multi_symbol_match.py
```

---
## 20. 代码示例碎片
### 20.1 动态注册新 symbol
```python
# 下单前未注册 BBB，order_service 会自动 ensure_symbol
order_bbb = Order(symbol='BBB', side=OrderSide.SELL, order_type=OrderType.LIMIT, price=20.5, quantity=100, account_id='ACC2')
svc.place_order(order_bbb)
```

### 20.2 卖空示例
```python
# 假设 ACC2 持仓不足仍想卖出 1000 股
short_order = Order(symbol='AAA', side=OrderSide.SELL, order_type=OrderType.LIMIT, price=10.2, quantity=1000, account_id='ACC2')
svc.place_order(short_order)
# 若 BROKER_UNLIMITED_LENDING=True 且风险校验通过，将借券 -> position.quantity 变负，borrowed_qty = |quantity|
```

### 20.3 IPO 自动开盘 (仅买单)
```python
# 在 CALL_AUCTION 阶段提交多笔买单，满足 ipo_service 条件后自动开盘 -> 生成 IPO_OPENED + 首笔成交
```

### 20.4 快照节流参数调整
```python
from stock_sim.settings import settings
settings.SNAPSHOT_THROTTLE_N_PER_SYMBOL = 2  # 更频繁刷新
```

---
## 21. 测试与验证
推荐使用 pytest：
- test_multi_symbol_match.py：多标的撮合 + IPO + 快照节流基础验证。
- test_smoke / test_e2e_new：可作为端到端初步验证。
注意：直接 `python -m tests.test_xxx` 只会导入文件，不会执行 pytest 收集；请使用 `pytest`。

覆盖检查要点：
- 订单簿隔离与价格时间优先
- IPO 自动开盘状态转换
- 卖空 borrowed_qty 增减与回补
- Snapshot 节流阈值触发与成交立即刷新

---
## 22. 性能与扩展方向
当前：
- 单线程撮合（RLock 保证同一进程安全）。
- 批量结算降低大量成交的数据库写放大。
未来：
- 多线程 / 分区撮合：按 symbol hash 分区或拆分多个引擎实例。
- 撮合回放：重放 TRADE / ORDER 事件用于策略复现。
- 更细粒度节流（时间窗口 / 自适应）。
- 借券费率、强平风险、保证金模型。
- 分布式事件总线（Redis Stream / Kafka）。

---
## 23. 常见问题 FAQ
Q: 下单报 LOT_INVALID / MIN_QTY？
A: 检查 lot_size, min_qty；或 price 未对齐 tick_size（会自动 normalize）。

Q: symbol 参数缺失或未找到？
A: 先确保 instruments 表存在记录；否则会用默认 tick/lot 注册（可能与期望不符）。

Q: IPO 没自动开盘？
A: 确认集合竞价阶段、仅买单、initial_price / free_float_shares 设置。检查 ipo_service 日志。

Q: 卖空 borrowed_qty 不减少？
A: 仅在买入成交覆盖空头时归还；查看 ACCOUNT_UPDATED 事件中的 borrowed_qty。

Q: 手续费为何未全退？
A: 预冻结基于假设“全部吃单”；部分成交按未成交比例退回。（可扩展为动态估计）

Q: Snapshot 没刷新？
A: 检查���否达到阈值 ops_since_snapshot��成交一定会强制刷新。

Q: 订单速率被拒？
A: 调整 ORDER_RATE_WINDOW_SEC / ORDER_RATE_MAX 或优化策略节奏。

---
## 24. Roadmap / 下一步计划
- [ ] 更精细的快照节流（时间+事件双因子）
- [ ] 实盘风控规则映射（多维限额、黑白名单）
- [ ] 保证金与杠杆支持
- [ ] 借券利率与按日计息 / 强制平仓
- [ ] K 线聚合与回放重建工具
- [ ] Kafka / Redis Stream 事件外部化
- [ ] Web 前端仪表盘 (替换/补充 PySide6)
- [ ] 策略沙盒资源隔离 (多进程 + 限制 API) 
- [ ] 优化 RL 环境向量化支持

---
## 25. 贡献指南
1. Fork & 建立 feature 分支：`feat/xxx`。
2. 遵循现有代码风格（保持 imports 顺序与最小修改范围）。
3. 新增功能需：
   - 补充/更新 README 或内联注释
   - 添加最少 1~2 条单元/集成测试
4. PR 描述需包含：动机 / 方案概要 / 测试覆盖点。
5. 不确定的设计可先开 issue 讨论（附示意伪代码）。

---
## 致谢
感谢所有提供反馈、测试用例与性能建议的贡献者。欢迎提出改进意见或新特性需求。

---
如需���多特定示例（如大规模回测脚本 / 策略接入 / 自定义风险插件），请在 issue 中详细描述场景。

---
## 26. 数据库 ER 图

文本 ER（主键*，外键→）：
```
Account* (id) ──< Position* (id, account_id→Account.id, symbol, quantity, frozen_qty, avg_price, borrowed_qty)
Account* (id) ──< OrderORM* (order_id, account_id→Account.id, symbol, side, price, quantity, filled, status)
OrderORM* (order_id) ──< OrderEvent* (id, order_id→OrderORM.order_id, type, detail, created_at)
OrderORM* (order_id) ──< TradeORM* (id, order_id_buy?, order_id_sell?, symbol, price, qty)
Account* (id) ──< Ledger* (id, account_id→Account.id, symbol, side, price, qty, cash_delta, pnl_real, fee, tax)
Instrument* (id/symbol) ──< Snapshot* (id, symbol→Instrument.symbol, last, volume, turnover, bid_json, ask_json)
Instrument* (symbol) ──< Bars* (id, symbol→Instrument.symbol, ts, open, high, low, close, volume)
AgentBinding* (id)  (账户与策略/智能体绑定，扩展表)
FeatureBuffer* (id) (特征缓存)
```
关系说明：
- 一个 Account 拥有多条 Position / Order / Ledger。
- Order 与 Trade 是多对多（通过买单/卖单双引用），简化为 TradeORM 存买卖订单号。
- Snapshot 保存最新盘口状态（或历史快照）。
- Bars/FeatureBuffer 为训练/回测特征支撑。

建议索引：
- positions(account_id, symbol) UNIQUE（已实现 uq_positions_account_symbol）
- orders(symbol, status), trades(symbol, price), ledger(account_id, symbol, ts)

## 27. 事件 JSON 示例
以下为运行期发布到 event_bus 的典型结构（字段可能随版本扩展）：

### 27.1 TRADE
```json
{
  "type": "TradeEvent",
  "trade": {
    "symbol": "AAA",
    "price": 10.05,
    "quantity": 500,
    "buy_order_id": "OID_BUY_123",
    "sell_order_id": "OID_SELL_456",
    "buy_account_id": "ACC1",
    "sell_account_id": "ACC2",
    "ts": 1735891200000
  }
}
```

### 27.2 SNAPSHOT_UPDATED
```json
{
  "type": "SnapshotUpdated",
  "symbol": "AAA",
  "snapshot": {
    "bids": [[10.05, 1200], [10.04, 800], [10.03, 400]],
    "asks": [[10.06, 600], [10.07, 700]],
    "last": 10.05,
    "vol": 150000,
    "turnover": 1509000.0,
    "bid1": 10.05,
    "ask1": 10.06,
    "bid1_qty": 1200,
    "ask1_qty": 600
  }
}
```

### 27.3 ACCOUNT_UPDATED
```json
{
  "type": "AccountUpdated",
  "account": {
    "id": "ACC1",
    "cash": 988765.12,
    "frozen_cash": 5000.0,
    "frozen_fee": 12.5,
    "positions": [
      {"symbol": "AAA", "quantity": 1500, "frozen_qty": 0, "avg_price": 9.97, "borrowed_qty": 0, "settlement_cycle": 1},
      {"symbol": "BBB", "quantity": -300, "frozen_qty": 0, "avg_price": 20.10, "borrowed_qty": 300, "settlement_cycle": 0}
    ],
    "sim_day": "2025-01-06",
    "sim_dt": "2025-01-06T09:30:15"
  }
}
```

### 27.4 IPO_OPENED
```json
{
  "type": "IPOOpened",
  "symbol": "NEW1",
  "open_price": 18.50,
  "allocated_volume": 500000,
  "ts": 1735891205000
}
```

说明：
- 时间戳 ts 若未内置由外层包装器添加。
- positions 中 borrowed_qty>0 表示净空头绝对量。
- Snapshot 中 bids/asks 仅截取前 N 档。

## 28. RL 环境观测与动作空间定义

### 28.1 LegacyTradingEnv
- 动作 (shape=(3,))：`[side_bias, qty_ratio, price_offset_ratio]`
  - side_bias ∈ [-1,1]：≥0 代表买，否则卖。
  - qty_ratio ∈ [0,1]：映射为下单数量：`qty = 100 * max(1, round(10*qty_ratio))`。
  - price_offset_ratio ∈ [0,1]：价格偏移：买价 `ref*(1+0.001*off)` / 卖价 `ref*(1-0.001*off)`。
- 观测向量组成（长度 = 1 + 5档*4 + 6 + K*4，默认K=10）：
  1. last_price
  2. 每档：bid_px, bid_qty, ask_px, ask_qty (共 n_levels*4)
  3. 持仓/资金特征：pos_qty, cash, frozen_cash, unrealized_pnl(占位), utilization, time_norm
  4. K 线占位：K*(open, high, low, close)
- 奖励：`ΔNAV - cost_weight*0`（当前 cost_weight=ENV_REWARD_COST_WEIGHT）。

### 28.2 EventTradingEnv (M1)
- 动作：目标权重向量 `w ∈ [weight_low, weight_high]^N`（N=标的数）。
  - 若 gross(∑|w|) 超过 `max_position_leverage` 等比例缩放。
  - 不允许做空的标的权重 clip 至 ≥0。
- 事件节点：由 event_nodes_provider 或内置阈值算法 `_simple_event_nodes` 生成；step=节点间跳转。
- 观测结构：拼接 (每标的特征块 + 账户特征)
  - 每标的特征块：`lookback_nodes * len(feature_list)` + 2（当前权重, 横截面 return zscore）
    - 默认 feature_list = (ret, vol, event, time_sin, time_cos)
  - 账户特征 (6)：`[equity_norm, cash_ratio, gross_exposure_ratio, net_exposure_ratio, leverage, drawdown]`
  - 维度：`obs_dim = N * ((F * L) + 2) + 6`
- 成本/滑点：commission_rate, stamp_duty(卖出), slippage；执行价使用下一节点 close ± 滑点。
- 奖励：
  ```
  raw_r = (equity_t - equity_{t-1}) / equity_{t-1}
  reward = raw_r - reward_cost_alpha * (cost/equity_{t-1}) - leverage_penalty_beta * max(0, leverage - leverage_target)
  clip 到 [-clip_reward, clip_reward]
  ```
- 关键内部变量：
  - positions_qty：当前头寸数量（按 lot 对齐）
  - positions_value：按当前价格估值
  - position_weights：最新目标权重缓存
  - margin_used：占位（可扩展保证金逻辑）

### 28.3 扩展建议
- 为 LegacyTradingEnv 增加真实账户查询 (AccountService) 以替换占位 pos_qty/cash。
- 为 EventTradingEnv 增加：��仓久期、换手率滑动窗口、行业/风险因子暴露、借券成本。
- 增加动作平滑罚项：`λ * ||w_t - w_{t-1}||_1`。

### 28.4 快速计算示例
假设：N=8, lookback_nodes=10, feature_list=5 项。
- 每标的特征 = 5*10 + 2 = 52
- 总观测维度 = 8*52 + 6 = 422

---
## 29. 自适应快照节流 (Adaptive Snapshot Policy)
目标：在高频撮合阶段减少冗余快照写入 / 发布；在低活跃度阶段保持及时性。

核心组件：`services/adaptive_snapshot_service.py` (AdaptiveSnapshotPolicyManager)

机制概述：
1. 每 symbol 维护最近窗口内簿操作(订单加入/撮合/取消)时间戳队列。
2. 根据操作速率区间动态调整该 symbol 的 `effective_threshold`，始终介于 `[baseline, max_cap]`。
3. 一旦出现成交 (trade) → 强制立即刷新 snapshot（不受阈值限制）。
4. 长时间(>冷却窗口)无活动 → 阈值回落到 baseline，保证重新活跃时快速同步。
5. 每次阈值变化发布事件 `SNAPSHOT_POLICY_CHANGED`，payload 含 symbol / old / new / reason。

配置（示例，可在 settings 或后续热更新中扩展）：
| 字段 | 含义 |
|------|------|
| SNAPSHOT_THROTTLE_N_PER_SYMBOL | 初始基线阈值 |
| ADAPTIVE_SNAPSHOT_MAX | 上限（示例：= 基线 * 5）|
| ADAPTIVE_SNAPSHOT_WINDOW_SEC | 速率统计窗口秒数 |

性能预期：在极端 1k+ orders/sec 情况下，快照输出频率显著下降(<5% 额外开销)。

---
## 30. 事件持久化与回放 (Event Sourcing & Replay)
目标：完整记录撮合/订单/账户/快照事件，实现离线重放 → 状态重建与审计。

关键文件：
- `persistence/models_event_log.py`：`event_log` 表结构（id, ts_ms, type, symbol, payload）。
- `services/event_persistence_service.py`：批量队列 + 定时/阈值 flush (<=256 条或 50ms)。
- `services/replay_service.py`：按时间或 ID 范围加载事件，dry-run 重建内存引擎与账户。
- `scripts/replay.py`：CLI 入口。

容错：
1. DB 写失败 → 进入内存重试队列（指数退避，超过上限丢弃并计数 `persistence_dropped_total`）。
2. 回放检测到缺口 / 乱序 → 中止并报告首个异常 ID。
3. 回放完成生成一致性报告 (订单数 / 成交数 / 最终持仓 / 现金 差异=0)。

使用示例：
```bash
python -m scripts.replay --start-ts 1735891200000 --end-ts 1735894800000 --mode dry-run
```

---
## 31. 恢复与状态重建 (Recovery)
目标：异常崩溃后快速、幂等地重建撮��与账户状态，降低停机影响。

组件：`services/recovery_service.py`

流程：
1. 启动（恢复模式） → 读取最新 snapshot + orders + positions + 未结交易。
2. 若快照缺失但有完整事件流 → 通过事件回放重建。
3. 校验：未完成订单数 / 现金合计 / 持仓数量 与数据库原值一致，否则进入只读模式 (拒绝新订单) 发布 `RECOVERY_FAILED`。
4. 首笔新订单成功处理后发布 `RECOVERY_RESUMED`（仅一次）。

幂等性：重复执行 recover() 不会产生重复订单或资金偏差。

---
## 32. 借券费用与强平 (Borrow Fee & Liquidation)
目标：模拟卖空成本与维持保证金风险，提升空头/杠杆场景真实��。

组件：
- `services/borrow_fee_scheduler.py`：日度遍历空头持仓，按 `borrowed_qty * price * borrow_rate_daily` 计提，写 Ledger (extra_json.kind="BORROW_FEE").
- `services/forced_liquidation_service.py`：检测 `equity/gross_exposure < MAINTENANCE_MARGIN_RATIO` 账户，分批生成强平订单。

参数（settings）示例：
| 字段 | 说明 |
|------|------|
| BORROW_FEE_ENABLED | 是否启用借券计提 |
| BORROW_RATE_DAILY | 日借券费率 |
| MAINTENANCE_MARGIN_RATIO | 维持保证金阈值 |
| LIQUIDATION_ORDER_SLICE_RATIO | 单轮强平切片比例 |

事件：
- `BORROW_FEE_ACCRUED`（可扩展）
- `LIQUIDATION_TRIGGERED`

---
## 33. 扩展风险规则注册表 (Risk Rule Registry)
目标：插件化添加/移除风险规则，支持运行期扩展与组合。

组件：`services/risk_rule_registry.py` + 对 `risk_engine.py` 的轻量增强。

示例内置规则：
1. MaxGrossExposureRule：总名义敞口上限。
2. FOKPreCheckRule：FOK 订单簿深度一次性满足检查。
3. ShortInventoryRule：卖空��存 / 融券可借检查。

接口：`register(rule)` / `evaluate(order, ctx)->List[RiskReject]`。
风险拒绝结构包含：rule_id / code / message / severity。

---
## 34. RL 账户融合与向量化 (AccountAdapter & Vectorized RL)
目标：RL 训练直接使用真实 AccountService/OrderService 数据与撮合路径，提高策略可迁移性与吞吐。

新增：
- `rl/account_adapter.py`：`AccountAdapter.get_account_state()` 与 `rebalance_to_weights()` 下单调仓，返回成本与拒单摘要。
- `rl/vectorized_env.py`：`VectorizedEnvWrapper` 同步批量 step，多环境一次 forward。
- `rl/trading_env.py`：`EventTradingEnv` 支持注入 `account_adapter`，动作即目标权重；拒绝卖空时施加 penalty (`EnvConfig.short_penalty`)。

特性：
1. 权重动作裁剪 + 杠杆缩放（gross 超限等比例）
2. 卖空禁止 → `SHORT_DISABLED:<symbol>` 记录在 info.rejects 并罚分。
3. 向量化收集：结合 PPO rollout 时显著提升 step 吞吐（多环境并发）。
4. 真实账户现金 / 持仓 / borrowed_qty 注入观测，替换原占位字段。

后续扩展建议：
- 异步多进程环境池 (Ray / multiprocessing)。
- 行业/因子暴露、交易成本拆分 (手续费/滑点/冲击)。
- 动作平滑正则 (L1/L2) 与 风险约束软惩罚。

使用（简例）：
```python
from stock_sim.rl.account_adapter import AccountAdapter
from stock_sim.rl.trading_env import EventTradingEnv, EnvConfig
from stock_sim.rl.vectorized_env import VectorizedEnvWrapper

cfg = EnvConfig(symbols=["AAA","BBB","CCC"], lookback_nodes=10)
adapter = AccountAdapter(order_service, account_id="ACC1")
envs = [EventTradingEnv(cfg, bars_provider=my_bars, account_adapter=adapter) for _ in range(4)]
vec = VectorizedEnvWrapper(envs)
obs = vec.reset()
for _ in range(100):
    actions = np.random.uniform(cfg.weight_low, cfg.weight_high, size=(len(envs), len(cfg.symbols)))
    obs, rew, done, info = vec.step(actions)
```
