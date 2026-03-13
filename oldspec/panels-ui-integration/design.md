# Design Document

## Overview
将当前以占位面板为主的前端启动流程，替换为“逻辑面板 + Qt 适配器”的真实面板加载方式。核心变化是在 app.main.run_frontend 中于任何面板预加载/打开之前调用 app.panels.register_ui_adapters，使 registry 中的占位工厂被真实工厂 replace，从而在 GUI 与 headless 两种模式下均惰性返回真实实例（GUI 可提供 widget/mount；headless 不依赖 Qt，仅保持实例可用）。

## Steering Document Alignment

### Technical Standards (tech.md)
- 分层解耦：面板注册/替换集中于 app.panels；入口只负责调用注册与窗口搭建。
- 观测优先：沿用 registry 的 metrics（panel_replaced/panel_created）与 MainWindow 的 panel_mount_* 计数。
- 可恢复：适配器导入失败或无 Qt 时 try/except 回退，占位仍可用。

### Project Structure (structure.md)
- 保持既有目录结构：
  - app/panels/__init__.py 提供 register_builtin_panels 与 register_ui_adapters。
  - app/ui/adapters/*_adapter.py 提供适配器，bind(logic) 返回可选 QWidget。
  - app/main.py 作为入口调用注册、预加载与事件循环。

## Code Reuse Analysis

### Existing Components to Leverage
- PanelRegistry（app/panels/registry.py）：使用 replace_panel 实现无缝替换与惰性实例化。
- 适配器（app/ui/adapters/*.py）：Account/Market/Settings/Clock/Leaderboard/Agents 等已实现 headless 降级。
- MainWindow（app/main.py）：已具备占位回退与挂载逻辑。

### Integration Points
- app.main.run_frontend：新增调用 register_ui_adapters() 的时机控制。
- setup_frontend_entry.py：保持不变，run_frontend 内部行为调整后天然受益。

## Architecture

- 启动顺序：register_builtin_panels() → register_ui_adapters() → 根据 headless/GUI 分支创建窗口 → GUI 预加载 → 事件循环。
- 幂等性：register_ui_adapters() 可被多次调用；每次 replace_panel 将更新描述符，旧实例若已创建会触发 on_dispose（当前大多未设置）。
- 降级策略：导入适配器或逻辑/控制器失败时静默跳过，保留对应占位面板。

### Modular Design Principles
- Single File Responsibility：入口只组织启动，面板替换集中在 panels 包内。
- Component Isolation：各面板适配器独立；逻辑层不感知 Qt。
- Service Layer Separation：controller/service/logic/adapter 各司其职。

## Components and Interfaces

### run_frontend (app/main.py)
- Purpose: 初始化并启动前端，提供 headless 选项。
- Interfaces: run_frontend(headless: bool=False) -> MainWindow|HeadlessMainWindow
- Dependencies: app.panels.register_builtin_panels, app.panels.register_ui_adapters, PanelRegistry, PySide6(可选)
- Reuses: metrics flush、预加载列表 _DEFAULT_PRELOAD

### register_ui_adapters (app/panels/__init__.py)
- Purpose: 将占位工厂替换为真实工厂
- Interfaces: register_ui_adapters() -> None
- Dependencies: 各控制器/服务/逻辑与 UI 适配器模块
- Reuses: replace_panel

## Data Models
- N/A（控制流程调整，不引入新数据结构）

## Error Handling

### Error Scenarios
1. 无 PySide6 环境（headless 或未安装）
   - Handling: run_frontend 仍调用 register_ui_adapters，但随后返回 HeadlessMainWindow；适配器降级不依赖 QWidget。
   - User Impact: 无崩溃；list/get 功能可用；GUI 不显示。
2. 某个适配器导入失败
   - Handling: try/except 跳过该面板 replace；保留占位。
   - User Impact: 该面板仍为占位；其余不受影响。
3. replace_panel 替换时机与已创建实例
   - Handling: registry.replace 内部会在旧实例已创建时调用 on_dispose（若存在），再更新描述符。
   - User Impact: 惰性与生命周期语义一致；无资源泄露。

## Testing Strategy

### Unit Testing
- registry.replace 行为（已存在覆盖）。

### Integration Testing
- headless 路径：模拟无 PySide6，调用 run_frontend(headless=True)，验证无 GUI 属性且可 open_panel 与 list。

### End-to-End Testing
- GUI 可用时：预加载 _DEFAULT_PRELOAD 并验证全部挂载键存在（已有 test_e2e_preload_panels_mounted）。
- 回退路径：故意破坏某适配器导入（可选/后续）时，应不崩溃且保留占位。
