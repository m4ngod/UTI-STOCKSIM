# Requirements Document

## Introduction
本规范定义 StockSim 桌面前端 (PySide6) 第一阶段交付范围：围绕账户/行情/智能体/排行榜/模拟时钟/设置 六大核心面板与“智能体创建与配置”流程，提供实时可视化、可控仿真驱动操作与可扩展策略接入。目标：让量化研究员与策略工程师在单机即可完成“运行撮合 → 观测 → 调参/热更新 → 回放/读档” 的闭环，提高策略迭代与教学演示效率。

## Alignment with Product Vision
该前端直接支撑 product.md 中的可视化、可追踪、快速迭代与 RL/策略统一执行通道原则：
- Deterministic & Traceable：通过读档(simday) 时间旅行与日志/指标面板重建策略上下文。
- Event-Driven & Extensible：所有 UI 更新依托 EventBus → EventBridge → Qt Signals 解耦，后续可替换为 Web 层。
- Multi-Asset & Strategy Sandbox：批量多策略散户 / PPO 智能体统一管理与热参数更新。
- Observability First：行情、账户、智能体、排行榜及虚拟时钟状态均可可视化与导出。
- 可扩展指标/插件：指标注册表、策略脚本上传、配置模板与版本回滚形成可插拔扩展点。

## Requirements

### R1 账户信息面板 (Account Panel)
**User Story:** 作为量化研究员，我希望实时查看账户资金、持仓与冻结/借券状态，以便评估策略风险敞口与资金利用率。
#### Acceptance Criteria
1. WHEN 收到 ACCOUNT_UPDATED 事件 THEN 面板 SHALL <200ms 内刷新现金、冻结现金、持仓、borrowed_qty、盈亏汇总 (实时/浮动/实现)。
2. IF 无事件 5 秒 THEN 系统 SHALL 触发一次后台拉取 (REST/RPC) 进行一致性校验 (差异>0.5% 记录告警)。
3. WHEN 用户选切换账户下拉框 THEN 面板 SHALL 在 300ms 内完成新账户数据渲染。
4. IF 持仓>50 个 symbol THEN 面板 SHALL 提供分页 / 搜索过滤 (<50ms 过滤响应)。
5. WHEN 账户可用资金 < 预设阈值(配置) THEN 面板 SHALL 产生高亮提醒 (非阻塞)。

### R2 市场行情面板 (Market Data Panel)
**User Story:** 作为策略工程师，我想快速浏览多标的实时行情、K线、Level2 与逐笔成交，以辅助微观结构调试。
#### Acceptance Criteria
1. WHEN SNAPSHOT_UPDATED 事件到达 (≤1000 条/s 峰值) THEN 行情列表 SHALL 节流合并 (批量 ≤100ms 刷新一帧)。
2. WHEN 用户在自选列表新增 symbol THEN 系统 SHALL 调用后端 ensure_symbol / 订阅并在 1s 内出现首个快照。
3. WHEN 用户双击列表行 THEN SHALL 打开或聚焦该 symbol 详细窗口 (包含：分时、K线、成交量柱、盘口前 5 / 10 档、逐笔滚动)。
4. IF 用户勾选技术指标 (MA / MACD / RSI) THEN 图表模块 SHALL 重新计算并在下一帧 (≤150ms) 叠加渲染。
5. WHEN 逐笔成交 > 2000 条窗口容量 THEN 系统 SHALL 丢弃最旧部分并保持 UI 滚动流畅 (帧率≥30FPS)。
6. IF Redis 缓存开启 THEN 行情订阅 SHALL 优先走 Redis pub/sub 通道；若断线回退本地 EventBus 并记录一次告警。

### R3 智能体面板 (Agents Panel)
**User Story:** 作为策略开发者，我希望查看、批量创建与控制智能体运行状态并实时查看日志/参数，以便快速迭代策略。
#### Acceptance Criteria
1. WHEN 面板初始化 THEN SHALL 拉取智能体列表 (字段: id, 名称, 类型, 状态, 运行起始时间, 最近心跳)。
2. WHEN 用户点击“启动/暂停/停止”按钮 THEN 后端操作结果事件 (AGENT_META_UPDATE 或错误) SHALL 在 1s 内反映。
3. WHEN 用户发起“批量创建多策略散户”并输入 N 与初始资金、策略集合 THEN 系统 SHALL 显示进度并在完成后刷新列表 (失败项详细列出)。
4. WHEN 用户展开某智能体详情 THEN SHALL 显示最近日志滚动 (追加模式) 与当前参数 (只读/可编辑标记)。
5. IF 用户修改可热更新参数并提交 THEN 参数版本 SHALL 增加且变更写入版本历史 (含时间、操作者、diff)。
6. WHEN 蒸馏/模型更新 (distill) 触发 THEN 进度与最终摘要 (大小/精度指标) SHALL 展示。
7. IF 心跳超时 (配置阈值) THEN 状态高亮为“失活”并可尝试重启。

### R4 排行榜面板 (Leaderboard)
**User Story:** 作为量化研究员，我希望对不同时间区间内智能体绩效进行排名与导出，以便评估策略稳定性与风险收益特征。
#### Acceptance Criteria
1. WHEN 用户选择时间窗口(日/周/月/自定义起止) THEN SHALL 重新拉取或重算指标 (收益率, 年化, 夏普, 最大回撤, 当前净值, 胜率) 并在 800ms 内渲染。
2. WHEN 用户点击智能体行 THEN SHALL 展示该智能体收益曲线与回撤曲线 (双轴)；曲线数据缓存命中率≥90%。
3. IF 用户点击导出 CSV/Excel THEN 文件 SHALL 包含当前排序 + 指标字段 + 时间窗口元信息。
4. WHEN 用户切换排序指标 THEN 表格 SHALL 在 150ms 内重新排序 (稳定排序保持原相对序)。
5. IF 指标计算失败或数据缺失 THEN 对应行显示“--”并记录错误日志，不阻塞其他行显示。
6. WHEN 用户勾选“显示排名变化” THEN 表格 SHALL 显示相对上一窗口的 Δ 排名列 (箭头+数值)。

### R5 启停/读档 (Sim Clock & Time Travel Panel)
**User Story:** 作为回测操作者，我需要控制虚拟时钟推进与回滚到任意 simday 以复盘历史状态。
#### Acceptance Criteria
1. WHEN 用户点击“启动” THEN 虚拟时钟状态 SHALL 变为 RUNNING 并 500ms 内广播初始 tick。
2. WHEN 用户点击“暂停” THEN SHALL 停止时间推进 (不再触发快照/TRADE 事件)；UI 状态切换 ≤300ms。
3. WHEN 用户选择某 simday 并点击“加载” THEN 所有面板 SHALL 回滚到该日期快照/账户/智能体状态 (一致性校验：账户净值差异≤0.01%)。
4. IF 回滚中断 (异常) THEN 系统 SHALL 恢复回滚前状态并提示用户重试。
5. WHEN 用户点击“停止” THEN 时钟状态进入 STOPPED 并禁止下单/策略步进 (按钮置灰)。
6. WHEN 回滚完成后再次“启动” THEN 新事件流 SHALL 基于回滚后状态继续推进 (非叠加)。

### R6 设置面板 (Settings)
**User Story:** 作为终端使用者，我希望自定义语言、主题、刷新频率与虚拟时钟速度及通知策略，使界面符合个人偏好与性能需求。
#### Acceptance Criteria
1. WHEN 用户切换语言 (中/英) THEN 所有可国际化文本 SHALL 在 300ms 内刷新 (延迟翻译的部分标记“⌛”).
2. WHEN 用户切换主题 (亮/暗) THEN UI SHALL 无闪烁完成样式切换；图表需保持当前视图范围。
3. WHEN 用户调整刷新频率 THEN 行情节流参数 SHALL 动态生效 (下一批刷新周期变更≤1s)。
4. IF 用户保存布局 (拖拽面板排列) THEN SHALL 持久化 JSON 布局并在重启后复现。
5. WHEN 设置虚拟时钟倍速 THEN 下一次推进节奏 SHALL 使用新压缩比 (提示当前 1s=模拟X秒)。
6. WHEN 用户配置告警阈值 (资金/回撤/心跳) THEN 触发满足条件时 SHALL 弹出桌面通知 (去抖 60s)。

### R7 智能体创建 (Agent Creation Flow)
**User Story:** 作为策略工程师，我希望通过可视化表单创建新智能体，选择观测向量、参数与上传自定义脚本并进行语法校验。
#### Acceptance Criteria
1. WHEN 打开“新建智能体”对话框 THEN SHALL 预填默认策略类型、观测字段清单 (checkbox)。
2. WHEN 用户上传 .py 策略脚本 THEN 系统 SHALL 在本地沙箱执行 AST 解析 + 语法检查 + 强制接口 (decide / name) 校验 (≤1s)。
3. IF 校验失败 THEN 阻止创建并显示具体错误行号与简洁描述。
4. WHEN 用户填写参数后点击创建 THEN 后端返回 agent_id 并在列表出现 (≤2s)。
5. WHEN 用户保存为“配置模板” THEN 模板 SHALL 加入下拉可复用 (存储包含参数 schema 版本)。
6. WHEN 创建完成自动打开详情视图 并显示初始日志“Agent Created”。

### R8 智能体配置与版本管理 (Agent Configuration & Versioning)
**User Story:** 作为策略调参与维护人员，我需要查看、热更新参数并回滚到任意历史版本，保证快速试错且可追溯。
#### Acceptance Criteria
1. WHEN 用户进入配置标签 THEN SHALL 展示当前参数/默认值/描述/可写权限标记。
2. WHEN 提交热更新 (diff!=0) THEN 新版本号 v+1 生成并记录 diff JSON 与时间戳、操作者。
3. WHEN 用户请求历史版本列表 THEN SHALL 分页加载 (每页≥20 条) 并支持筛选 (按操作者/时间范围)。
4. WHEN 选中某历史版本回滚 THEN SHALL 触发确认对话框；成功后生成 v+1 (回滚也是新版本) 并应用参数。
5. IF 热更新失败 (后端拒绝或校验不通过) THEN UI SHALL 回退显示旧值并提示。
6. WHEN 参数变更事件广播 (AGENT_META_UPDATE) THEN 其他已打开的同一智能体配置页 SHALL 自动同步。

### R9 上传脚本安全与校验 (Strategy Upload Safety)
**User Story:** 作为系统维护者，我需要在用户上传策略时保证基本安全，避免执行危险系统调用。
#### Acceptance Criteria
1. WHEN 脚本上传 AST 检查 THEN SHALL 禁止 import os/sys/subprocess/socket (白名单模式)；违规则拒绝。
2. WHEN 脚本含相对路径访问或 __file__ 使用 THEN 系统 SHALL 发出警告提示并可选继续 (可配置策略：严格/宽松)。
3. IF 脚本 > 200KB THEN 提示超出大小限制并拒绝。
4. WHEN 多次上传同名策略 (N>3/小时) THEN 触发节流并提示稍后再试。

### R10 导出与数据一致性 (Export & Consistency)
**User Story:** 作为分析师，我希望导出排名 / 账户 / 逐笔成交数据做离线研究，并确保导出数据与当前 UI 状态一致。
#### Acceptance Criteria
1. WHEN 用户导出排行榜 THEN 文件 SHALL 标注生成时间、时间窗口、排序字段，并与当前显示顺序一致。
2. WHEN 用户导出账户持仓 THEN 数据 SHALL 基于最近一次 ACCOUNT_UPDATED 事件快照 (若 >2s 无事件则先主动拉取)。
3. WHEN 用户导出逐笔成交 THEN 行数 SHALL 等于当前内存窗口并按时间升序。
4. IF 导出过程失败 THEN 不生成空文件，提示包含错误上下文 (error_code + 简短说明)。

### R11 国际化 / 本地化 (i18n/L10n)
**User Story:** 作为多语言用户，我希望界面/日期/数字格式根据所选语言/区域自动适配。
#### Acceptance Criteria
1. WHEN 用户切换语言 THEN 所有 UI 文本 (含动态菜单) SHALL 走翻译表查找，未命中字面回退并记录 missing key。
2. WHEN 显示金额 / 数值 THEN SHALL 采用本地化格式 (千分位, 小数精度可配置)。
3. IF 新增面板未注册翻译 key THEN 构建检查脚本 SHALL 发出警告 (CI Hook)。

### R12 可访问性与可用性 (Usability & A11y)
**User Story:** 作为使用键盘操作的用户，我希望关键操作可通过快捷键/焦点导航完成。
#### Acceptance Criteria
1. WHEN 用户按下全局快捷键 (可配置) THEN 可在面板间循环切换。
2. WHEN 焦点在表格中 THEN 上下方向键 SHALL 平滑滚动，不跳过未渲染行。
3. IF 主题为高对比模式 THEN 所有文本对比度 (WCAG 对比比≥4.5:1)。
4. 提供最少 Tab 顺序覆盖所有交互控件。

## Non-Functional Requirements
### Code Architecture & Modularity
- UI 分层：UI组件(app/ui/)、状态/控制器(app/controllers/)、数据访问与事件桥(app/services/, app/event_bridge.py)。
- 每类面板独立模块 + 统一接口 (register_panel / lifecycle hooks: init, load_state, save_state)。
- 指标计算异步线程池 + 主线程只做渲染。
- 严格类型提示 (mypy 基础通过) & 关键 DTO (pydantic) 定义。

### Performance
- 行情批处理渲染：高峰 1000 snapshot/s → UI 刷新 ≤10fps 可配置；CPU 占用≤30%。
- 单次面板初次打开渲染首帧 ≤800ms；后续增量刷新 ≤150ms。
- 逐笔成交追加内存结构使用双端队列；内存窗口大小默认 5000 行 (≈5MB 上限)。
- Redis 订阅延迟 (publish → UI) 中位 ≤80ms。

### Security
- 策略脚本白名单 import + AST 静态规则 + 临时隔离目录执行。
- 禁止 UI 直接拼接 SQL；所有后端调用通过已定义接口或 RPC 客户端。
- 文件导出路径固定至用户家目录下 stocksim_exports/。
- 敏感操作 (回滚/回滚后再启动) 需二次确认对话框。

### Reliability
- EventBridge 内部环形缓冲溢出策略：丢弃最旧并计数 metrics.dropped_events。
- 回滚 (读档) 失败自动重试 1 次；继续失败则提示并保留原状态。
- 行情订阅双通道 (Redis 首选 / 本地回退)。
- 配置热更新失败回退上一个稳定版本。

### Usability
- 统一快捷键提示面板 (F1)。
- 右上角全局搜索 (symbol / agent_id)。
- 面板布局可拖拽 + 一键恢复默认。

### Observability & Logging
- UI 重要交互 (创建/删除/回滚/热更新) 产生结构化日志 (action, actor, ts, result)。
- 指标：渲染帧时延、事件滞后、批量合并大小、丢弃事件数、脚本校验耗时。

### Extensibility
- 新增技术指标：实现 IIndicator 接口并注册到 IndicatorRegistry，前端动态生成配置表单。
- 新增策略脚本上传校验规则：注册 AST Rule 插件。

### Internationalization
- 翻译资源 JSON: i18n/zh_CN.json, i18n/en_US.json；启动时加载并缓存。

### Data Consistency
- 面板显示的账户/排行榜/收益曲线与导出在一次导出操作内使用同一快照版本号 (snapshot_id)。

## Out of Scope (Phase 1)
- Web 浏览器端实现 (仅桌面 PySide6)。
- 分布式多机策略执行调度。
- 高级风控策略在线配置 UI。
- Kafka 外部化事件通道。

## Assumptions
- 后端已提供统一 Agent/Clock/Leaderboard/Account/MarketData API 与事件类型满足需求；若缺口将在设计阶段补列 API 需求。
- Redis 可选，不启用时功能降级但不影响主流程。
- 单用户本地运行（暂不做多租户权限隔离 UI）。

## Risks
- 行情高频刷新引发 UI 卡顿 → 需批处理/虚拟列表。
- 策略脚本潜在安全风险 → 必须 AST 白名单 + 沙箱。
- 回滚操作复杂度高 → 需要一致性校验与错误回退路径。

## Success Metrics (Frontend Phase 1)
- 行情/账户 UI 延迟 (事件到可视) P95 < 250ms。
- 账户面板与导出净值差异 < 0.01%。
- 关键交互 (创建智能体/回滚/切换符号) 成功率 > 99%。
- UI 崩溃率 < 0.1% / 8 小时运行。

