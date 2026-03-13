# Requirements Document

## Introduction
本规格聚焦完成现有前端（PySide6 桌面应用）从“逻辑面板 + 控制器”到“完整主窗口 GUI 可视化与交互”落地，并核对《前端需求.md》中列出的全部功能，实现缺口列出与后续设计/任务阶段的输入。目标：
1. 覆盖账户/行情/智能体/排行榜/时钟读档/设置 六大主面板核心功能及智能体创建与配置流程。
2. 明确已实现（代码中存在）与缺失（需实现）功能差距，提供可验收的业务与交互准则。
3. 为后续 Design & Tasks 提供可追踪的需求 ID → 设计 → 任务映射基础。

## Alignment with Product Vision
- 支持多标的撮合与账户演进的可视化呈现（市场、账户、排行榜面板）。
- 快速策略与智能体（模型）迭代（智能体创建/配置/版本管理/脚本校验）。
- 事件驱动 + 可回放（虚拟时钟/读档/回滚/检查点）。
- 可扩展 + 插件化（面板注册机制、指标叠加、脚本策略上传）。
- 观测性优先（metrics + 结构化日志，性能阈值 AC 约束）。
- 国际化 & 低耦合 UI（i18n、主题、布局持久化）。

## Requirements
说明：
- 每个需求以 R<ID> 标识；若现有代码部分覆盖，列出“Implementation Status”。
- 验收标准采用 EARS 风格（WHEN/IF/THEN/SHALL）。
- 新增扩展需求（文档未完全细化但产品愿景需要）补充 R12+。

### R1 账户信息面板（Account Panel）
User Story: 作为量化研究员，我希望查看账户资金、持仓与盈亏高亮，便于快速评估风险与收益。
Acceptance Criteria:
1. WHEN 切换账户 THEN 系统 SHALL 在 <300ms 返回账户摘要与分页持仓。
2. WHEN 输入符号过滤 THEN 系统 SHALL 仅展示符号子串匹配（不区分大小写）的持仓。
3. WHEN 持仓未实现盈亏绝对值/名义仓位价值 ≥ 阈值(drawdown_pct) THEN 持仓行 SHALL 高亮。
4. WHEN 用户修改告警阈值(drawdown_pct) via Settings THEN 更新 SHALL 在 1 次刷新周期内反映。
Implementation Status: 面板/控制器已实现（account_panel.py, account_controller.py）；缺 GUI 表格渲染与高亮样式。

### R2 市场行情面板（Market Panel + Symbol Detail）
User Story: 作为交易者，我需要监控自选列表、查看单个标的 K 线/盘口以及基础逐笔占位。
Acceptance Criteria:
1. WHEN 添加/移除自选 THEN 系统 SHALL 立即更新 watchlist 视图并惰性加载 symbol 数据。
2. WHEN 选择 symbol THEN 系统 SHALL 加载并展示最近 bars 序列 + 最近快照 + 顶层 L2 盘口。
3. WHEN 设置分页/过滤/排序(last 或 symbol) THEN 结果 SHALL 在调用 get_view 时反映。
4. WHEN 切换 timeframe THEN SHALL 重新加载对应 bars。
5. WHEN snapshot 更新 (后续事件接入) THEN MarketPanel SHALL 在 ≤1s 内反映最新 last 价。
Implementation Status: 业务逻辑面板与 detail 已实现；缺：事件驱动实时刷新、指标叠加、真实逐笔、GUI 组件与多图表渲染。

### R3 智能体面板（Agents Panel）
User Story: 作为策略工程师，我希望查看与控制智能体运行状态，并批量创建散户策略实例。
Acceptance Criteria:
1. WHEN 列表请求 THEN 系统 SHALL 返回智能体 meta（状态/心跳/params_version）。
2. WHEN 执行 start/pause/stop THEN 状态 SHALL 更新并追加日志条目。
3. WHEN 批量创建 Retail 或 MultiStrategyRetail THEN 进度 SHALL 逐步递增；不允许类型返回业务错误。
4. WHEN last_heartbeat 超出阈值 AND 状态为 RUNNING THEN SHALL 高亮 stale。
5. WHEN 请求 tail_logs THEN 系统 SHALL 返回最近 N 行日志。
Implementation Status: 服务+面板已实现（agent_service, agents/panel.py）；缺：GUI 表格、心跳定时刷新、初始资金/策略自定义输入。

### R4 排行榜面板（Leaderboard Panel）
User Story: 作为研究员，我希望按时间窗口比较策略表现并导出数据。
Acceptance Criteria:
1. WHEN 切换窗口(day/week/month 等) THEN 系统 SHALL 刷新排名并计算 rank_delta。
2. WHEN 排序字段修改 THEN 视图 SHALL 按字段排序（rank/return_pct/sharpe/equity）。
3. WHEN 选择行 THEN SHALL 显示合成收益曲线与回撤曲线。
4. WHEN 导出为 CSV 或 Excel THEN 文件 SHALL 生成并包含窗口元数据(window, rows)。
5. WHEN 刷新未指定 force 且缓存未过期(设计阶段定义策略) THEN 系统 MAY 复用缓存。
Implementation Status: 控制器+面板逻辑存在；缺：Excel 导出支持(xlsx)、历史真实曲线数据、GUI 绑定。

### R5 启停与读档（虚拟时钟控制 + 回滚）
User Story: 作为量化研究员，我希望使用虚拟时钟启动/暂停/回放并在需要时读档回滚至历史状态。
Acceptance Criteria:
1. WHEN 用户 start/pause/resume/stop THEN 状态 SHALL 更新（status/sim_day/speed/ts）。
2. WHEN 创建 checkpoint(label) THEN 列表 SHALL 包含新记录且标记 current。
3. WHEN rollback 到 checkpoint THEN 当前 sim_day 与状态 SHALL 与 checkpoint 对齐。
4. WHEN 指定新 sim_day start THEN 系统 SHALL 切换交易日并重新驱动数据加载。
5. WHEN 设置速度 THEN speed 字段 SHALL 更新并驱动后端节奏（Design 定义速度 → 时间步放大系数）。
Implementation Status: ClockPanel/Controller 回滚接口存在；缺：后台统一驱动服务、GUI 控件、操作日志落盘与全域刷新链路。

### R6 设置面板（Settings Panel）
User Story: 作为用户，我希望调整语言、主题、刷新频率、回放倍速和告警阈值，并持久化布局。
Acceptance Criteria:
1. WHEN 修改 language THEN 所有文本 SHALL 在 ≤1 个刷新周期内更新（≤300ms 标记慢日志）。
2. WHEN 修改 refresh_interval_ms THEN 周期性刷新调度 SHALL 使用新值。
3. WHEN 修改 playback_speed THEN 虚拟时钟调用 SHALL 使用新值 (R5 联动)。
4. WHEN 批量更新(transaction) THEN 合并一次 update 通知 & 产生单 metrics 计数。
5. WHEN undo / redo THEN 设置 SHALL 回滚/前进；redo 栈语义正确。
6. WHEN 更新布局 THEN layout 持久化文件 SHALL 在延迟写入后存在。
Implementation Status: 面板逻辑已包含（事务/undo/redo），缺：GUI 表单、全局刷新广播、与时钟速度实际联动。

### R7 智能体创建（Agent Creation Dialog / Flow）
User Story: 作为策略工程师，我希望通过对话框创建智能体并指定类型/初始资金/策略参数/观测向量。
Acceptance Criteria:
1. WHEN 打开创建对话框 THEN 系统 SHALL 提供 agent_type / 初始资金 / 策略模板 / 观测因子 选项。
2. WHEN 提交合法配置 THEN 后端 SHALL 返回新智能体 ID 并在列表显示。
3. IF agent_type 不支持批量或创建失败 THEN SHALL 显示业务错误代码。
4. WHEN MultiStrategyRetail 批量创建 THEN 可指定 strategies 列表并逐个显示进度。
Implementation Status: 无完整对话框；服务层部分参数占位；缺：UI、参数校验、观测向量配置与存储。

### R8 智能体配置与参数版本管理（AgentConfig Panel）
User Story: 作为研究员，我希望查看版本链、上传新版本、回滚历史并热更新关联智能体。
Acceptance Criteria:
1. WHEN 新增参数版本 THEN params_version SHALL 自增且版本链追加记录。
2. WHEN 回滚版本(vN) THEN 生成新版本(vN+1 rollback_of=vN) 并更新智能体当前参数。
3. WHEN 脚本校验失败(AST/规则) THEN SHALL 阻断新增并返回 violations 或 error code。
4. WHEN get_view 调用 THEN 返回最新版本列表与脚本校验状态。
Implementation Status: 已实现核心逻辑；缺：GUI 版本树/差异展示、回滚确认流程、脚本编辑器组件。

### R9 热更新与配置模板
User Story: 作为策略工程师，我希望保存常用参数模板并在运行中热更新。
Acceptance Criteria:
1. WHEN 保存模板 THEN 模板 SHALL 存储（文件或 store）并可在创建或更新时选用。
2. WHEN 应用模板到运行智能体 THEN params_version SHALL 自增并立即生效（与 R8 协同）。
3. WHEN 热更新失败(找不到智能体或校验失败) THEN SHALL 给出错误信息并不改变现有版本。
Implementation Status: 模板与热更新快捷 API 缺失；需添加 TemplateStore & 控制器扩展。

### R10 排行榜导出增强
User Story: 作为研究员，我希望将排行榜导出为 CSV 或 Excel 并保留元数据与生成时间戳。
Acceptance Criteria:
1. WHEN 导出 CSV THEN 文件 SHALL UTF-8 并含表头。
2. WHEN 导出 Excel THEN 工作簿第1表含 rows + meta sheet。
3. WHEN 导出后 THEN 系统 SHALL 输出文件路径 & 记录 metrics(export_success)。
Implementation Status: CSV 导出可行；缺：Excel(xlsx) 支持 & meta sheet。

### R11 通知与告警
User Story: 作为用户，我希望在重要事件（心跳超时/阈值触发/回滚完成/脚本校验失败）收到统一通知。
Acceptance Criteria:
1. WHEN 任一事件触发 THEN 通知中心 SHALL 追加结构化条目 (type, ts, message, source)。
2. WHEN 查询通知列表 THEN 返回最近 N 条；支持已读标记。
3. WHEN 阈值告警产生 THEN AccountPanel highlight 与通知条目 SHALL 同步出现。
Implementation Status: 未实现通知中心；需新 NotificationStore + Panel / 或统一托盘组件。

### R12 L2 行情与逐笔成交
User Story: 作为做市或高频策略分析者，我需要查看 L2 及实时逐笔（滚动 5000 行 ring buffer）。
Acceptance Criteria:
1. WHEN 新 L2 更新 THEN 盘口列表 SHALL 在 ≤500ms 刷新 (P95)。
2. WHEN 新逐笔成交到达 THEN 逐笔表格 SHALL 追加一行并维持固定长度（裁剪旧记录）。
3. WHEN 超过 30FPS 刷新负载 THEN 系统 SHALL 自动节流（合并多条到一次 UI 更新）。
Implementation Status: 占位；无 ring buffer 与事件桥接。

### R13 技术指标叠加（MA / MACD 起步）
User Story: 作为研究员，我希望在 K 线中叠加常见技术指标。
Acceptance Criteria:
1. WHEN 用户选择指标(MA[x], MACD) THEN 系统 SHALL 异步计算并缓存。
2. WHEN Bars 变化 THEN 缓存失效并重新计算（节流）。
3. WHEN 指标计算异常 THEN SHALL 记录 metrics 并在 UI 提示“指标不可用”。
Implementation Status: 指标注册框架存在；需 MarketController + DetailPanel 集成 与 GUI 叠加渲染。

### R14 自选股管理持久化
User Story: 作为用户，我希望退出后再次打开仍保留我的自选列表。
Acceptance Criteria:
1. WHEN 添加/移除自选 THEN watchlist SHALL 写入持久化（JSON 或 SettingsStore）。
2. WHEN 应用启动 THEN 若存在持久化文件 SHALL 恢复 watchlist。
Implementation Status: 未持久化；仅内存。

### R15 虚拟时钟播放速度全链路联动
User Story: 作为用户，我希望更改播放速度后仿真事件生产速率即时调整。
Acceptance Criteria:
1. WHEN 设置 playback_speed THEN ClockService 或调度器 SHALL 更新 tick 间隔。
2. WHEN speed 改变 THEN 时钟面板 state.speed SHALL 同步。
3. WHEN speed 设置非法值(≤0) THEN 系统 SHALL 拒绝并提示。
Implementation Status: SettingsPanel 字段存在；服务层尚未联动。

### R16 Checkpoint / 回滚数据一致性验证
User Story: 作为研究员，我希望回滚后数据（账户/行情/智能体）与 checkpoint 内容一致。
Acceptance Criteria:
1. WHEN rollback 完成 THEN 系统 SHALL 比较关键摘要字段并输出校验结果 (all_pass / issues[])。
2. WHEN 不一致 THEN 通知中心 SHALL 发出告警。
Implementation Status: 无一致性校验实现。

### R17 批量多策略散户创建参数化
User Story: 作为策略开发者，我希望批量创建 MultiStrategyRetail 时指定初始资金与策略列表。
Acceptance Criteria:
1. WHEN 批量创建提交 THEN config.initial_cash / strategies SHALL 透传 service 并记录。
2. WHEN 任一实例创建失败 THEN 进度统计失败数，并不中断其余（除不支持类型）。
Implementation Status: BatchCreateConfig 有 initial_cash/strategies 字段；未使用与显示。

### R18 智能体日志查看
User Story: 作为用户，我希望查看智能体运行日志并分页 / 滚动刷新。
Acceptance Criteria:
1. WHEN tail 请求 THEN 返回最近 N 行。
2. WHEN 分页请求(page,size) THEN 返回对应片段。
3. WHEN 日志新增 THEN tail 视图 SHALL 在刷新周期内更新。
Implementation Status: 服务支持；缺：面板 UI + 自动刷新。

### R19 Redis 事件与缓存可选接入
User Story: 作为运维/扩展开发者，我希望在多进程或远程部署时使用 Redis 作为事件桥接与缓存。
Acceptance Criteria:
1. WHEN 配置启用 redis.url THEN EventBridge SHALL 订阅/发布关键事件通道。
2. WHEN Redis 不可用 THEN 系统 SHALL 回退本地队列并记录 redis_fallback 指标。
3. WHEN 使用 Redis 模式 THEN watchlist / 指标缓存 可选存放于 Redis（键空间前缀配置化）。
Implementation Status: redis_subscriber基础存在；需前端桥接与配置注入。

### R20 主窗口与布局管理
User Story: 作为用户，我希望通过拖拽/停靠/关闭面板自定义布局并在下次打开还原。
Acceptance Criteria:
1. WHEN 首次启动 THEN 系统 SHALL 构建默认布局并延迟加载各面板。
2. WHEN 面板打开/关闭 THEN LayoutPersistence SHALL 更新。
3. WHEN 退出后重启 THEN 上次布局 SHALL 还原（包含尺寸/顺序/可见性）。
Implementation Status: MainWindow 占位；缺真实 Dock/Tab 容器与布局序列化。

### R21 国际化与主题
User Story: 作为全球用户，我希望实时切换语言与主题。
Acceptance Criteria:
1. WHEN 切换语言 THEN 新文本 SHALL 来自 i18n 资源，缺失 key 计数。
2. WHEN 切换主题 THEN 所有受支持控件 SHALL 应用新样式表 (QSS) 并在 1s 内完成。
3. WHEN 缺失翻译 THEN SHALL 回退 key 原文 & 记录 metrics.i18n_missing。
Implementation Status: i18n loader 与设置存在；缺：统一 UI 刷新与主题 QSS 注入流程。

### R22 性能与响应性
User Story: 作为用户，我期望界面流畅、关键操作低延迟。
Acceptance Criteria:
1. WHEN 切换账户/窗口/时间框架 THEN 主线程 UI 冻结时间 SHALL < 50ms P95。
2. WHEN 市场快照频率高(≥10Hz) THEN 合并刷新 SHALL 将 UI 刷新频率限制在 5~10Hz。
3. WHEN 指标计算(MA/MACD) THEN 异步执行 SHALL 避免阻塞 UI 线程。
4. WHEN 逐笔 5000 行滚动 THEN 内存增量 SHALL O(1) per insert (ring buffer)。
Implementation Status: 部分逻辑节流概念在文档；缺：实际调度与性能监测埋点。

### R23 脚本安全与校验
User Story: 作为平台维护者，我希望用户上传脚本受限避免恶意代码。
Acceptance Criteria:
1. WHEN 上传脚本 THEN AST 校验 SHALL 拒绝黑名单节点 (exec/eval/os.system 等)。
2. WHEN 校验失败 THEN SHALL 返回 violations 列表或错误码并阻断版本新增。
3. WHEN 通过校验 THEN 内容 SHALL 持久化并记录版本链。
Implementation Status: ScriptValidator 已实现；缺：前端脚本编辑器 + 结果展示（AgentConfigPanel UI）。

### R24 观测性（Metrics & 日志）
User Story: 作为开发者，我需要关键交互与性能指标用于排障。
Acceptance Criteria:
1. WHEN 前端启动 THEN metrics SHALL flush(reason=startup)。
2. WHEN GUI 运行 THEN 每 5s 定时 flush(reason=periodic)。
3. WHEN 退出 THEN forced flush(reason=shutdown)。
4. WHEN 面板关键慢操作 THEN 指标 SHALL 递增对应 *_slow 计数。
Implementation Status: main.py 已部分实现周期 flush；缺：统一慢操作检测与日志聚合面板。

### R25 可扩展面板框架
User Story: 作为贡献者，我希望快速添加新面板无需修改核心架构。
Acceptance Criteria:
1. WHEN 新面板注册 register_panel(name,factory) THEN 惰性实例化。
2. WHEN 替换 panel (replace_panel) THEN 若已实例化 SHALL 调用 dispose hook。
3. WHEN list_panels 调用 THEN 不实例化面板只返回元信息。
Implementation Status: registry 已实现；缺：BasePanel 抽象/生命周期 mount/dispose 回调标准化。

## Non-Functional Requirements

### Code Architecture and Modularity
- 单一职责：Panel 仅做轻量格式化与交互，数据合成在 Controller。
- 模块化：指标、脚本校验、通知、布局独立目录；新增面板不得直接依赖其他面板实例。
- 清晰接口：Controller 暴露 get_view()/refresh()/操作方法；Service 纯数据访问。
- 可测试性：纯逻辑层（面板/控制器）无 GUI 依赖，可 headless 测试。

### Performance
- Account 切换 <300ms；UI 主线程阻塞 <50ms P95。
- 指标计算放后台线程池；单指标计算超时>1s 记录 metrics.indicator_timeout。
- L2 & Tick 合并刷新 ≤500ms；高频事件丢弃/节流策略定义在 Design。

### Security
- 脚本上传 AST 白/黑名单校验；拒绝危险内置与 I/O。
- Redis 模式下频道与键前缀隔离，避免冲突与数据泄漏。
- 参数模板与脚本存储使用最小权限路径（只写策略资源目录）。

### Reliability
- 回滚失败自动回退到先前 state，不污染当前运行。
- 指标计算异常被捕获，不影响行情主流程。
- Redis 不可用自动降级本地模式。

### Usability
- UI 文本 i18n；深浅主题；Dock/Tab 拖拽。
- 批量创建与长操作提供进度与可取消（Design 定义 cancel 语义）。
- 通知中心清晰分类（INFO/WARN/ERROR/ALERT）。

---
追踪矩阵说明：R1~R25 将在 design.md 给出架构与接口方案，并在 tasks.md 细化为原子任务（含文件路径与依赖）。
