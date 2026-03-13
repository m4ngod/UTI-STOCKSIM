# Requirements Document

## Introduction
MainWindow 目前仅实例化占位面板对象并未向 GUI 插入任何可见 QWidget；用户启动 GUI 模式时窗口为空白。该特性旨在为预加载面板提供基础可视占位区（central widget + layout），并定义统一的 Panel → QWidget 挂载契约，使后续真实面板替换最小化改动。目标是在不影响 headless / 现有测试的前提下，让窗口启动时立即显示若干占位标签，验证注册与预加载链路。

## Alignment with Product Vision
该改进提升前端可用性与验证体验，减少“空白窗口”困惑，符合快速可观测与可迭代 UI 骨架的产品愿景：启动后 1 秒内提供结构反馈，并为后续功能面板迭代建立统一嵌入机制。

## Requirements

### Requirement 1: Central Widget & Layout
**User Story:** 作为前端使用者，我希望窗口含有一个中央布局容器，这样面板小部件能被添加并立即显示。
#### Acceptance Criteria
1. WHEN run_frontend 在 GUI 模式启动 THEN 系统 SHALL 创建 central QWidget 并附加一个 QVBoxLayout。
2. IF central widget 已创建 THEN 重复调用不应再次覆盖或泄露现有子控件。
3. WHEN headless=True THEN 系统 SHALL 不创建任何 QWidget。

### Requirement 2: Panel Widget Mount Contract
**User Story:** 作为面板开发者，我希望面板可提供 widget() 或 mount(parent_layout) 接口以注入其可见内容。
#### Acceptance Criteria
1. WHEN open_panel(name) 被调用 AND 目标对象具备 widget() -> QWidget THEN 系统 SHALL 将其返回部件添加到主布局。
2. IF 面板缺失 widget()/mount() 接口 THEN 系统 SHALL 创建一个 QLabel 占位，文本包含面板名称。
3. WHEN 再次打开同名面板 (已存在) THEN 系统 SHALL 不重复添加副本（幂等）。

### Requirement 3: Preload Visible Panels
**User Story:** 作为用户，我希望默认预加载的面板启动时就显示占位，以确认它们已注册。
#### Acceptance Criteria
1. WHEN run_frontend 启动 GUI 模式 THEN 系统 SHALL 在 show() 前对预加载列表执行 open_panel。
2. WHEN open_panel 过程中抛出异常 THEN 系统 SHALL 捕获并记录（日志或 metrics.inc('panel_mount_failure')），其余面板继续。
3. WHEN 启动完成 THEN 窗口中可见的占位标签数量 >= 成功挂载面板数。

### Requirement 4: Non-Intrusive Headless Behavior
**User Story:** 作为 CI / headless 使用者，我不希望引入任何 GUI 依赖。
#### Acceptance Criteria
1. WHEN headless=True THEN 系统 SHALL 继续返回 HeadlessMainWindow 且无 PySide6 依赖调用。
2. WHEN headless=True THEN open_panel 逻辑 SHALL 仅实例化对象，不尝试创建布局或标签。

### Requirement 5: Minimal Overhead & Compatibility
**User Story:** 作为维护者，我希望新增逻辑不破坏现有测试且性能可控。
#### Acceptance Criteria
1. WHEN GUI 启动 THEN central widget 建立与预加载全部完成耗时 < 10ms (空占位情形)。
2. WHEN 现有测试 (headless) 运行 THEN 不需要修改。
3. WHEN 调用 open_panel 对已有面板 THEN SHALL O(1) 提前返回，不重复添加布局项。

## Non-Functional Requirements

### Code Architecture and Modularity
- 单一职责：主窗口仅负责容器与布局；面板自行决定内部 UI。
- 可扩展：未来可替换 QVBoxLayout 为 Dock/Tab，不影响面板契约。
- 低耦合：面板无需直接引用 MainWindow 类型，仅使用提供的 mount 约定。

### Performance
- 预加载 + 挂载开销 < 10ms（无真实复杂组件）。
- open_panel 幂等检查使用字典 O(1)。

### Security
- 不引入外部输入处理；无额外攻击面。

### Reliability
- 异常隔离：单个面板挂载失败不影响其它面板。
- Fallback 占位确保永不出现完全空窗口（除全部失败）。

### Usability
- 可见标签含面板标题 (Title Case) 或原始 name。
- 允许后续真实面板替换而无需修改 MainWindow。
