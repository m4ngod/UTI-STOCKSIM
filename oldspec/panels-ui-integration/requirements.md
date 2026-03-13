# Requirements Document

## Introduction
本规范旨在将当前前端 GUI 中的“占位面板”替换为真实可用的“业务逻辑面板 + Qt UI 适配器”组合，确保在启动 GUI 或 headless 模式时，通过面板注册表实现惰性加载、按需实例化与安全回退（缺依赖仍显示占位）。目标是让用户不再看到“panel (placeholder)”文本，而是实际可交互的面板组件。

## Alignment with Product Vision
- 符合平台“分层解耦、可插拔扩展、观测优先”的原则：逻辑与 UI 通过适配器绑定，经由面板注册表统一暴露。
- 改善可用性与上手体验，支持教学/演示场景快速展示行情、账户、时钟等核心信息。
- 保持稳定性与可恢复：当缺少 PySide6 或某些依赖时，系统不崩溃，自动回退为占位面板。

## Requirements

### Requirement 1: 面板替换与启动时机
**User Story:** 作为前端用户，我希望启动应用时能自动将占位面板替换为真实面板，从而直接看到可交互的账户、行情、时钟等内容。

#### Acceptance Criteria
1. WHEN 调用 run_frontend(headless=False) THEN 系统 SHALL 在预加载/打开面板前调用 register_ui_adapters() 替换占位。
2. WHEN 调用 run_frontend(headless=True) THEN 系统 SHALL 亦在任何面板首次打开前完成替换，使 get_panel 返回真实适配后的实例。
3. IF 适配器导入失败（缺少依赖或 GUI 不可用） THEN 系统 SHALL 保留占位，不崩溃。

### Requirement 2: 惰性加载与替换语义
**User Story:** 作为开发者，我希望面板在首次访问前不实例化，以降低启动成本，并在替换后保持既有惰性语义。

#### Acceptance Criteria
1. WHEN list_panels() THEN 系统 SHALL 不触发实例化，仅返回元数据（name/title/created）。
2. WHEN 第一次 get_panel(name) THEN 系统 SHALL 调用替换后的 factory() 创建实例，后续复用该实例。
3. WHEN replace_panel 被调用且旧实例已创建 THEN 系统 SHALL 优先调用旧 on_dispose（若存在），再以新 factory 更新描述符。

### Requirement 3: i18n 与显示一致性
**User Story:** 作为多语言用户，我希望面板标题按照当前语言显示，并避免 GUI 中出现“(placeholder)”字样。

#### Acceptance Criteria
1. IF 描述符 meta 含 i18n_key THEN list_panels() SHALL 使用 i18n 翻译后的标题。
2. WHEN GUI 模式挂载面板 THEN 系统 SHALL 优先使用逻辑面板提供的 widget()/mount()，若不可用再退回占位标签；正常情况下不出现“(placeholder)”字样。

### Requirement 4: 可观测性与指标
**User Story:** 作为维护者，我希望有基础的指标以度量面板生命周期事件。

#### Acceptance Criteria
1. WHEN 完成替换 THEN metrics SHALL 计数 panel_replaced。
2. WHEN 首次实例化 THEN metrics SHALL 计数 panel_created。
3. WHEN GUI 挂载成功/失败 THEN metrics SHALL 分别计数 panel_mount_success / panel_mount_failure。

### Requirement 5: 兼容入口脚本与预加载
**User Story:** 作为使用者，我希望通过 setup_frontend_entry.py 指定语言/主题启动时，同样获得真实面板与默认预加载。

#### Acceptance Criteria
1. WHEN 通过入口脚本启动 THEN 系统 SHALL 在打开默认面板前已完成适配器替换。
2. WHEN 指定 --lang / --theme THEN 系统 SHALL 正确生效并不影响面板替换流程。

## Non-Functional Requirements

### Code Architecture and Modularity
- Single Responsibility: 面板注册、替换逻辑集中在 app.panels 包；入口仅触发注册/替换与窗口搭建。
- Modular Design: 各面板逻辑与 UI 适配器在 app.panels.* 与 app.ui.adapters.* 下按模块分离，遵循清晰接口（bind(logic) → adapter 实例）。
- Dependency Management: 适配器导入失败不影响整体（try/except 静默回退）。
- Clear Interfaces: PanelRegistry 提供 register/replace/get/list/dispose 合同，GUI MainWindow 仅依赖 get_panel 与 list_panels。

### Performance
- 冷启动替换阶段总体额外开销 ≤ 100ms（非强制上限，面向本地开发机）。
- 惰性实例化，避免在 list/替换阶段构造重量对象。

### Security
- 不引入外部网络调用；不加载未授权插件代码。

### Reliability
- 缺失 PySide6 或适配器模块时，系统稳定回退；不影响 headless 模式与测试运行。

### Usability
- 默认预加载面板：account、market、agents、settings、leaderboard、clock。
- GUI 中不应显示“panel (placeholder)”文本（除非回退情形）。
