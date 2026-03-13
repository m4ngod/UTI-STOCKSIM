# Tasks Document

- [x] 1. 在 app/main.py 中引入并调用 register_ui_adapters
  - File: app/main.py
  - 在 run_frontend 中，调用顺序调整为：register_builtin_panels() → register_ui_adapters() → flush_metrics → headless/GUI 分支；确保在 headless 分支 return 之前已完成替换。
  - 幂等与异常：调用包裹 try/except，失败静默回退。
  - _Leverage: app.panels.register_ui_adapters, app.panels.register_builtin_panels_
  - _Requirements: R1, R5_
  - _Prompt: Role: Python Desktop App Developer (PySide6) | Task: Wire register_ui_adapters at the correct timing in run_frontend so that placeholders are replaced before any panel open/preload and also in headless mode before returning | Restrictions: Do not alter other behaviors, keep metrics flush and preload logic intact, be defensive with try/except | Success: GUI 启动不再显示 placeholder 文本；headless 下 get_panel 返回适配后的实例；相关 E2E 测试通过。

- [x] 2. 代码静态检查与最小变更验证
  - Files: app/main.py
  - 运行快速语法/导入检查，确保无 NameError/ImportError 及类型拼写错误。
  - _Leverage: existing tests and tooling_
  - _Requirements: NFR - Reliability_
  - _Prompt: Role: Python QA | Task: Run quick static checks after the change and fix trivial issues | Restrictions: Keep scope minimal | Success: No import/Name errors in edited files.

- [x] 3. 运行关键 E2E/Headless 测试
  - Files: tests/test_e2e_headless_no_gui_attrs.py, tests/test_e2e_headless_widget_no_gui_attrs.py, tests/test_e2e_preload_panels_mounted.py (Qt 环境存在时)
  - 目的：验证 headless 下不暴露 GUI 属性，open_panel 正常；GUI 存在时预加载面板全部挂载键存在（若环境跳过则忽略）。
  - _Leverage: pytest, existing tests_
  - _Requirements: R1, R2, R5_
  - _Prompt: Role: Test Engineer | Task: Execute the listed tests to validate placeholder replacement timing and behavior in both headless and GUI modes | Restrictions: Prefer targeted tests to keep runtime low | Success: 所列测试全部通过或被预期地跳过（GUI 测试在无 Qt 时跳过）。

- [x] 4. 可选：入口脚本安全加固（幂等）
  - File: setup_frontend_entry.py（仅当需要）
  - 若后续回归发现入口直接 open_panel 时仍有竞态，则在调用 run_frontend 后、open_panel 前增加一次幂等调用（try register_ui_adapters()），默认先不改动。
  - _Leverage: app.panels.register_ui_adapters_
  - _Requirements: R5_
  - _Prompt: Role: Python Application Engineer | Task: Add an optional defensive call if and only if tests show a race in adapter registration when launching via setup_frontend_entry.py | Restrictions: Avoid duplicate behavior; keep idempotent | Success: 不引入重复替换副作用；仅在确有需要时改动。
