# Tasks Document

- [x] 1. 添加 central widget 与主布局初始化
  - File: app/main.py (更新 MainWindow.__init__)
  - 动作: 引入 _ensure_central_layout() 创建 self._central QWidget + QVBoxLayout(名称 self._layout) 并 setCentralWidget; GUI 模式首次调用执行, 再次调用幂等
  - 目的: 满足 Requirement 1 (central widget)
  - _Requirements: Requirement 1 AC1, AC2_
  - _Prompt: Role: Python Qt 开发者 | Task: 在 MainWindow 中实现 _ensure_central_layout 创建并缓存 central QWidget+QVBoxLayout, 保证幂等 (多次调用不重复添加) | Restrictions: 不影响 headless 模式, 不引入额外全局状态 | Success: GUI 启动后 centralWidget 非空且重复调用不增加子控件层级_

- [x] 2. 提供面板挂载辅助与映射
  - File: app/main.py (新增 _panel_widgets: Dict[str,QWidget])
  - 动作: 新增 _mount_panel(name, inst) -> QWidget|None: 若 name 已在映射中直接返回; 否则解析 widget()/mount(); 无则 fallback QLabel(f"{name} panel (placeholder)"); 添加到布局
  - 目的: 面板契约与幂等挂载
  - _Requirements: Requirement 2 AC1, AC2, Requirement 5 AC3_
  - _Prompt: Role: Python Qt 架构 | Task: 实现 _mount_panel 依据面板实例接口选择挂载策略，缺失接口创建 QLabel 占位，记录 self._panel_widgets 幂等 | Restrictions: 不修改面板注册 API, 捕获异常并返回占位 | Success: 多次 open_panel 只挂载一次且有占位或真实部件_

- [x] 3. 改造 open_panel 集成挂载
  - File: app/main.py
  - 动作: open_panel 调用 get_panel 后在 GUI 模式下执行 _ensure_central_layout + _mount_panel
  - 目的: 用户调用即可见
  - _Requirements: Requirement 2 AC1, Requirement 3_
  - _Prompt: Role: Python 开发 | Task: 修改 open_panel 在 GUI 模式执行挂载逻辑 (headless 保持原状) | Restrictions: 不改变 open_panel 返回值 | Success: GUI 模式返回实例并在窗口中可见占位_

- [x] 4. run_frontend 预加载调用前确保布局
  - File: app/main.py
  - 动作: 在循环预加载面板前调用 _ensure_central_layout
  - _Requirements: Requirement 3 AC1_
  - _Prompt: Role: Python Qt 开发者 | Task: 调整 run_frontend 在预加载之前创建布局确保可挂载 | Restrictions: 不影响 headless 分支 | Success: 预加载面板均在显示前挂载_

- [x] 5. 异常捕获与 metrics 计数
  - File: app/main.py / observability/metrics.py (可选计数名直接复用 metrics.inc)
  - 动作: _mount_panel 中 try/except 捕获挂载异常 inc('panel_mount_failure'); 成功 inc('panel_mount_success')
  - _Requirements: Requirement 3 AC2, Requirement 5 AC1_
  - _Prompt: Role: 观测性工程师 | Task: 在挂载流程中添加成功/失败计数 | Restrictions: 不影响性能 (< 微秒级分支) | Success: 正常与异常挂载分别更新对应计数_

- [x] 6. 性能与重复挂载保护
  - File: app/main.py
  - 动作: 在 _mount_panel 开始处 O(1) 检查 name in _panel_widgets 提前返回; 添加简单注释 # PERF:
  - _Requirements: Requirement 5 AC1, AC3_
  - _Prompt: Role: 性能工程师 | Task: 添加幂等检查减少重复处理与布局操作 | Restrictions: 不额外引入锁 (主线程) | Success: 二次 open_panel 无额外 QLabel 产生_

- [x] 7. 单元测试: 布局幂等
  - File: tests/frontend/unit/test_mainwindow_layout.py (新建)
  - 内容: 模拟 GUI 不可用 -> 跳过; 若 PySide6 可用: 创建 MainWindow，调用 _ensure_central_layout 两次，断言 centralWidget 恒定 & 子控件计数不增
  - _Requirements: Requirement 1 AC2_
  - _Prompt: Role: 测试工程师 | Task: 编写测试验证布局幂等逻辑 | Restrictions: PySide6 缺失需 skip | Success: 测试通过并在有 PySide6 环境下验证幂等_

- [x] 8. 单元测试: 挂载逻辑与 fallback
  - File: tests/frontend/unit/test_panel_mounting.py
  - 内容: 构造假 panel1 提供 widget(); panel2 无接口 -> fallback; 验证 _panel_widgets 映射和占位文本
  - _Requirements: Requirement 2 AC1, AC2_
  - _Prompt: Role: QA 工程师 | Task: 测试 widget 优先和 fallback 占位行为 | Restrictions: 环境缺 PySide6 时 skip | Success: 分别断言映射包含两个 name 且第二个部件文本包含 placeholder_

- [x] 9. 单元测试: open_panel 幂等
  - File: tests/frontend/unit/test_panel_mounting.py (追加)
  - 内容: 调用 open_panel 两次同名; 验证布局子项数量不变
  - _Requirements: Requirement 2 AC3_
  - _Prompt: Role: QA 工程师 | Task: 验证重复 open_panel 不重复挂载 | Restrictions: 同上 | Success: 子项计数保持一致_

- [x] 10. 单元测试: headless 不触发 GUI
  - File: tests/frontend/unit/test_headless_mount_no_qt.py
  - 内容: run_frontend(headless=True) 返回 HeadlessMainWindow 且实例无 _panel_widgets 属性
  - _Requirements: Requirement 4 AC1, AC2_
  - _Prompt: Role: 测试工程师 | Task: 确认 headless 路径无 GUI 属性 | Restrictions: 不导入 PySide6 | Success: 测试通过且无 GUI 相关属性_

- [x] 11. 预加载可见性集成测试 (可选)
  - File: tests/frontend/integration/test_gui_preload_visible.py
  - 内容: 若 PySide6 可用: run_frontend(headless=False) 启动后检查 mw._panel_widgets keys ⊇ _DEFAULT_PRELOAD 成功集; 若不可用 skip
  - _Requirements: Requirement 3 AC1_
  - _Prompt: Role: 集成测试工程师 | Task: 验证预加载面板全部挂载 | Restrictions: Skip 无 Qt | Success: 所有预期面板 key 存在_

- [x] 12. 文档更新
  - File: docs/frontend_dev_guide.md (追加面板嵌入说明)
  - 内容: 新增“窗口面板嵌入”小节，描述 widget()/mount() 契约与占位 fallback
  - _Requirements: Usability_
  - _Prompt: Role: 技术文档作者 | Task: 更新开发指南描述新的面板嵌入与占位机制 | Restrictions: 保持简洁 ≤150 行新增 | Success: 文档出现新小节并说明使用方式_

- [x] 13. 可选微性能基准 (将来)
  - File: tests/perf/test_panel_mount_perf.py (可后续)
  - 内容: 记录首次 vs 重复挂载耗时 <10ms 与 <1ms
  - _Requirements: Performance (参考)_
  - _Prompt: Role: 性能工程师 | Task: 编写性能测试 (可跳过 CI) 供本地验证 | Restrictions: 标记 pytest.mark.slow | Success: 在具备 Qt 环境本地验证性能达标_

**Note**: 以上任务完成后实现应满足所有需求与非功能要求。