# 前端开发指南 (Frontend Dev Guide)

> 适用于基于本项目 PySide6 桌面前端（frontend-trading-ui 规格）的二次开发者。目标：让新贡献者 30 分钟内跑起，1 小时内完成一个简单面板扩展。

---
## 目录
1. 总览与架构
2. 关键目录速览
3. 运行与入口参数
4. 事件流与数据更新生命周期
5. 面板 (Panel) 体系与注册机制
6. 控制器 (Controller) 与服务 (Service)
7. 指标 (Indicators) 扩展
8. 状态与持久化 (State / Store)
9. 国际化 (i18n) 与本地化格式化
10. 安全与脚本上传校验
11. 性能优化与节流策略
12. Metrics & 结构化日志接入
13. 测试金字塔 (Unit / Integration / E2E)
14. 常见扩展示例步骤
15. 代码规范与提交要求
16. FAQ / 排障
17. 附：典型调用序列图
18. 导出体系 (ExportService / ExportButton)
19. 通知与告警体系 (NotificationCenter / alert.triggered)
20. 回滚一致性告警流 (Rollback -> Alert -> UI)
21. 慢操作监控 (slow_op 装饰器)
22. 复用逻辑组件 (ExportButton / NotificationWidget)
23. 面板嵌入与占位机制（Preload / widget() / mount() / Placeholder）

---
## 1. 总览与架构
前端内部层次（简化）：
```
+-------------------------------------------------------+
|                   MainWindow / UI Shell               |
|  (布局/菜单/快捷键/面板容器 + LayoutPersistence)      |
+----------------------+----------------+---------------+
| Panels (Account/Market/Agents/...)    | Shared UI     |
|  轻展示层：订阅 Controller 输出 / 状态快照             |
+----------------------+----------------+---------------+
| Controllers (聚合/合并/过滤/分页/指标触发)            |
+----------------------+----------------+---------------+
| Services (Account / MarketData / Agent / Clock / ...) |
+----------------------+----------------+---------------+
| EventBridge (订阅 EventBus 或 Redis)                  |
+----------------------+--------------------------------+
| EventBus (进程内)  + (可选 Redis Fallback)            |
+----------------------+--------------------------------+
| Core Engine + 后端事件生产 (撮合/账户/回滚/指标)       |
+-------------------------------------------------------+
| State Stores (SettingsStore / VersionStore / Layout)  |
| IndicatorExecutor(ThreadPool) & 缓存                  |
| Security: ScriptValidator / RateLimiter               |
| Observability: metrics_adapter / struct_logger        |
+-------------------------------------------------------+
```
核心思想：事件驱动 + 控制器清洗/聚合 → 面板渲染；最大限度隔离 UI 线程重负计算（指标、排序、大批量合并）。

---
## 2. 关键目录速览
```
app/main.py                入口 MainWindow 创建 & 面板注册
app/panels/                各面板子目录 (account / market / ...)
app/panels/registry.py     register_panel(name, factory) 机制
app/controllers/           控制器：领域数据提炼 (account_controller.py 等)
app/services/              调取后端或缓存封装 (market_data_service.py 等)
app/state/                 Store/持久化 (settings_store.py / version_store.py)
app/indicators/            指标注册与执行 (registry.py / executor.py)
app/i18n/                  翻译资源 en_US.json / zh_CN.json + loader
app/security/              ast_rules.py / script_validator.py / rate_limiter.py
app/utils/                 throttle, formatters, alerts, metrics_adapter
setup_frontend_entry.py    命令行入口 (headless / 语言 / 主题 / 日志等级)
```

---
## 3. 运行与入口参数
命令行（在项目根目录）：
```
python setup_frontend_entry.py --lang zh_CN --theme dark --headless
```
常用参数：
- --headless：仅做无界面初始化（CI 集成测试 / 性能基准）。
- --lang en_US|zh_CN：初始化语言。
- --theme dark|light：主题变量注入（高对比度适配）。

程序主入口调用 `run_frontend()`：
1. 加载 SettingsStore / LayoutPersistence
2. 初始化 EventBridge（Redis 可选）
3. 注册 Panels（延迟实例化）
4. 启动指标执行线程池
5. 进入 Qt 事件循环

---
## 4. 事件流与数据更新生命周期
```
后端/引擎 -> EventBus.publish(Event) -> EventBridge 收集/节流
-> Controller.on_event(event) (合并/分页/统计) -> Panel.refresh(view_model)
```
关键优化：
- EventBridge 可能批量 flush（降低 UI 频率）。
- Controller 内部使用增量合并（如账户/排行）。
- Panel 层尽量无重计算，仅做轻量格式化（格式化委托给 formatters）。

---
## 5. 面板体系与注册机制
新增面板步骤：
1. 目录：`app/panels/my_feature/panel.py`。
2. 定义类（示例伪代码）：
```python
class MyFeaturePanel(BasePanel):
    def __init__(self, controllers): ...  # 依赖注入
    def mount(self): ...  # 创建小部件 / 绑定信号
    def on_tick(self): ...  # 可选心跳
    def apply_settings(self, settings): ...  # 主题/语言
    def update(self, vm): ...  # 接收 view model
    def dispose(self): ...
```
3. 在 `app/panels/registry.py`：
```python
from .my_feature.panel import MyFeaturePanel
register_panel('my_feature', lambda ctx: MyFeaturePanel(ctx.controllers))
```
4. 若需要事件：在相关 Controller 添加生成 view model 逻辑；Panel 通过订阅或轮询 `controller.subscribe(callback)`。
5. 国际化：所有文本使用 `t("key.path")`，新增 key 到 `i18n/en_US.json` & `zh_CN.json`。
6. 测试：
   - Unit：构造虚拟 controller 输出 -> 调用 panel.update 验证 UI 状态字段。
   - Integration：放入 registry，模拟事件流，断言 view model。

生命周期钩子：
- create (factory 被调用)
- mount (实际添加到主窗口)
- update (多次)
- dispose (关闭/注销)

注意：避免在构造函数里启动线程或做重 IO，放到 mount。

---
## 6. 控制器与服务
- Service：纯数据抓取或缓存（市场数据、账户、导出、回滚、版本、日志流）。
- Controller：面向 UI 的聚合与衍生：分页、排序、增量合并、指标触发。
- 扩展控制器：遵循接口 `on_event(event)` & `get_view_model()`；内部尽量 O(Δ) 复杂度。

新增控制器建议：
1. 明确定义输入事件类型集合 (e.g. SNAPSHOT_UPDATED, ACCOUNT_UPDATED)。
2. 使用 RingBuffer / dict + dirty set 合并。
3. 周期性（定时器节流）输出 view model，减少 UI 刷新频率。

---
## 7. 指标扩展
新增指标：
1. 文件：`app/indicators/my_indicator.py`
2. 实现函数：`def compute(bars: pd.DataFrame, **params) -> pd.DataFrame|Series`
3. 在 `registry.py`：`IndicatorRegistry.register("MY_IND", compute, required_columns=[...])`
4. 执行：Controller 发起 `executor.submit(symbol, "MY_IND", params)`
5. 结果缓存 key：`f"{symbol}:{name}:{param_hash}"`
6. 性能：尽量矢量化；确保线程安全与纯函数。

---
## 8. 状态与持久化
- SettingsStore：语言/主题/刷新频率/告警阈值/布局 JSON。
- VersionStore：策略参数版本链 (rollback_of)。
- LayoutPersistence：拖拽/隐藏/尺寸记忆。
写入策略：变更 → debounce 100~300ms → 异步写文件，防止频繁 IO。

---
## 9. 国际化 (i18n)
- `t(key, **fmt)` 懒加载；缺失 key 计数 metrics.i18n_missing++。
- 流程：新增 key -> en_US.json & zh_CN.json -> Panel 使用。
- 避免直接硬编码中文/英文；测试通过统计缺失为 0。

---
## 10. 安全与脚本上传
- ScriptValidator：AST 解析 + 限制 Import/属性访问；拒绝 `exec`, `eval`, `os.system` 等。
- RateLimiter：同策略名 1h 超过 3 次上传拒绝。
- 上传流程：Panel -> Controller -> Service(script_validator.validate) -> 保存 / 错误消息。
- 建议：保持指标/脚本为纯函数；禁止全局副作用。

---
## 11. 性能优化与节流
策略：
- 批量事件：EventBridge flush 聚合 (≤120ms P95)。
- 指标线程池：CPU 密集型转后台；UI 线程仅绑定 future 回调。
- 表格渲染：仅对 dirty 行更新；使用 Qt Model `dataChanged` 范围信号。
- 大量逐笔：RingBuffer 固定长度 (e.g. 5000)；滚动窗口 O(1) 入队 O(1) 出队。
- 避免在 paintEvent 内做聚合/排序。
Profiling：使用时间戳 metrics + struct.log 检查 `ui_render_latency_ms`。

---
## 12. Metrics & 结构化日志
- metrics_adapter：统一 `inc(name, v=1)` / `observe(name, value)`。
- 关键指标：
  - events_queued / events_dropped
  - indicator_latency_ms
  - ui_render_latency_ms
  - i18n_missing
  - redis_fallback
- 结构化日志：`observability/struct_logger.py`，面板/控制器异常统一捕获输出。
- 可扩展：dump_metrics() (任务 49) 计划导出 JSON 给可视化。

---
## 13. 测试金字塔
- Unit (`tests/frontend/unit/`): DTO / 纯函数 / 指标计算 / 校验器。
- Integration (`tests/frontend/integration/`): 事件 → 控制器 → Panel Mock。
- E2E (`tests/frontend/e2e/`): 启动入口 + 多面板用户旅程 + 语言/主题切换。
CI 要点：
1. Headless 模式 (--headless)；
2. 避免真实睡眠，使用 mock 时间或加速器；
3. 断言核心指标 & 状态。

---
## 14. 常见扩展示例
A. 新增“风险告警”面板：
1. 创建 controller: risk_alert_controller.py 监听 ACCOUNT_UPDATED + SNAPSHOT_UPDATED → 计算风险比值。
2. 面板 risk_alert/panel.py 订阅 controller.view_model。
3. registry 注册。
4. i18n 添加文案；添加 unit + integration 测试。

B. 新增指标 VWAP：
1. 实现 compute_vwap(bars)
2. registry 注册 VWAP
3. Controller 增加对 symbol 指标请求
4. Panel 增加指标曲线 toggle

C. 添加导出统计增强：
1. ExportService 增加扩展字段
2. 面板 ExportButton 传递新参数
3. 测试对比 snapshot_id 一致性

---
## 15. 代码规范与提交
- Python 3.11，全部新增函数添加类型注解；复杂结构用 TypedDict / dataclass。
- 命名：类 PascalCase，函数 snake_case，常量 UPPER_SNAKE。
- 文件内顺序：imports -> 常量 -> 数据结构 -> 类/函数 -> main/注册。
- 日志：异常必须捕获并记录结构化字段 (panel=, controller=, err=)。
- 性能敏感区标注 `# PERF:`，待未来 profile。
- PR 模板（若添加）：需说明新增指标/面板对事件流影响。

---
## 16. FAQ / 排障
Q: UI 卡顿？
A: 检查是否在 Panel.update 做重计算；迁移到 Controller 或后台指标。查看 ui_render_latency_ms。

Q: 指标结果延迟？
A: 线程池饱和或 bars 缓存 miss；调节线程数或预拉取。

Q: 语言切换无效？
A: 确认调用 SettingsStore.set_language 后触发广播 & 面板实现 apply_settings。

Q: 上传脚本被拒绝？
A: 查看日志 script_validator reason；修正 import 或危险调用。

Q: 事件丢失？
A: metrics.events_dropped >0；可能 flush 周期过长或队列满，需要调节阈值。

---
## 17. 附：典型调用序列图 (下单��起账户与 UI 更新)
```
User Action -> OrderService.place_order() -> MatchingEngine.match()
 -> AccountService.settle_trades_batch() -> EventBus.publish(ACCOUNT_UPDATED)
 -> EventBridge.queue(event)
 (flush) -> AccountController.on_event() 合并 -> view_model
 -> AccountPanel.update(view_model) -> Qt repaint
```

欢迎补充改进：提交 PR 前可在 issue 提出设计简述。

## 18. 导出体系 (ExportService / ExportButton)
职责:
- ExportService: 数据结构化导出 CSV / Excel, 自动 snapshot_id 绑定, 写入元数据 (CSV 首行注释 / Excel META sheet)。
- Equity 一致性校验: meta.baseline_equity 与首行 equity 相对误差 >=0.0001 抛 EQUITY_INCONSISTENT。
- Excel 依赖: 优先 pandas+xlsxwriter -> 回退 openpyxl -> 否则 PANDAS_MISSING。
- Metrics: export_start / export_success / export_failure / export_csv_success / export_excel_success / export_equity_inconsistent / export_ms。
- ExportButton: 排列列顺序, 可 include_extra_columns, 维护最近状态 (last_snapshot_id / last_error)。
快速用法:
```python
svc = ExportService(snapshot_id_provider=lambda: 'snap-1')
btn = ExportButton(svc)
path = btn.export(rows, ['a','b'], meta={'user':'alice'}, fmt='csv', file_path='out.csv')
```
注意: 传入 file_path 无扩展名会自动补; 目录则生成 export_<snapshot>.ext。

## 19. 通知与告警体系 (NotificationCenter / alert.triggered)
NotificationCenter:
- 订阅 event_bus 主题 'alert.triggered' -> 转换为 level=alert 通知。
- API: publish_* / get_recent / acknowledge / clear_by_code / get_highlight_codes。
- Metrics: ui.notification_published / ui.notification.<level> / ui.notification.code.<code>。
- 严重 code (dialog) 集: backend_timeout / permission_denied / script_violation。
Headless 校验: NotificationWidget(list_items) 将 level 大写便于 E2E 断言。
Alert 事件结构:
```json
{
  "type": "rollback.consistency",
  "message": "rollback consistency mismatch",
  "data": {"checkpoint_id": "cp1"},
  "ts": 1730000000.123
}
```

## 20. 回滚一致性告警流 (Rollback -> Alert -> UI)
触发场景: 回滚校验失败（例如快照数据哈希/余额不一致） → 控制器发布 'alert.triggered'。
时序 (ASCII):
```
[RollbackController] --(publish alert.triggered)--> [event_bus]
[event_bus] --(callback)--> [NotificationCenter._on_alert_event]
[NotificationCenter] --(publish alert)--> store + metrics + event_bus(ui.notification)
[UI Panel / Widget] --(poll/subscribe)--> 展示 ALERT & 高亮
```
最佳实践:
- 业务只需发布 alert.triggered, 不直接操作 NotificationCenter。
- code 采用命名空间风格: <domain>.<category> (例 rollback.consistency)。

## 21. 慢操作监控 (slow_op 装饰器)
目标: 低开销统计超过阈值的函数调用次数 (无分位、仅计数)。
API:
```python
from observability.metrics import slow_op, metrics
@slow_op('price_cache_refresh', 2.5)  # 阈值 2.5ms
def refresh(): ...
```
超阈值计入 metrics.counters['slow_op::price_cache_refresh']。
特点: perf_counter 计时; 仅超阈值时加锁 inc; 异常路径同样统计。
使用建议: 只放在高频短函数; 长任务用现有 timeit/add_timing。

## 22. 复用逻辑组件 (ExportButton / NotificationWidget)
- ExportButton: 面板级“导出”按钮逻辑抽象; 仅处理列重排与状态记录, 不关心 UI 框架; 适合集成到不同数据表 Panel。
- NotificationWidget: 轻量 headless 辅助 (测试/CLI) 获取最近通知列表, 避免直接依赖 UI 层。
模式要点:
1. 逻辑组件 = 无 Qt 依赖 / 线程安全 (RLock) / 明确可测试。
2. 面板持有组件实例, UI 事件 (点击导出 / 查看通知) 调用其方法。
3. 测试优先: 单测模拟输入数据 + 断言组件输出 (路径独立于渲染)。

附加建议:
- 新增逻辑组件时, 遵循: 明确状态字段 -> 公开只读 getter -> 不直接写日志/UI。
- 面板只关心序列化 primitives (dict/list/str/number), 便于 E2E 快速断言。

(至此更新: 导出/告警/回滚慢操作与复用组件文档已补充)

---
## 23. 面板嵌入与占位机制（Preload / widget() / mount() / Placeholder）
适用场景：统一面板挂载流程，保证即使面板未实现可见部件，也能以占位符填充布局，便于 E2E 校验与布局稳定。

核心要点：
- 预加载列表：`app/main.py` 中 `_DEFAULT_PRELOAD = ["account","market","agents","settings","leaderboard","clock"]`。启动时会在确保布局后逐一 `open_panel(name)` 完成挂载。
- 布局保障：`MainWindow._ensure_central_layout()` 幂等创建 central widget 与垂直布局；在 GUI 模式下由入口/`open_panel` 自动调用，通常无需手动触发。
- 嵌入契约（两选一即可）：
  1) 提供 `widget(self) -> QWidget`：返回你的主部件，框架负责 `addWidget`。
  2) 提供 `mount(self, layout: QLayout) -> Optional[QWidget]`：在其中自行创建并添加到传入布局；可返回创建的 QWidget（用于记录）。
- 占位回退：若两者皆未实现或挂载过程异常，框架会插入 `QLabel(f"{name} panel (placeholder)")` 以保证 UI 不留空白，并记录 `panel_mount_success`/`panel_mount_failure` 指标。
- 幂等挂载：同名面板已挂载则 `open_panel(name)` 不会重复添加，内部用 `_panel_widgets[name]` 判重。
- 惰性实例化：`get_panel(name)` 首次调用才创建实例；注册时仅登记元信息，不会构造对象。

注册与热替换：
- 注册：`register_panel(name, factory, title=None, group=None, meta={"i18n_key": "panel.<name>"})`。
- 热替换：`replace_panel(name, factory, ...)` 可用真实实现替换占位版（若已创建会先触发 `on_dispose`）。
- 生命周期钩子：`on_register(inst)` / `on_dispose(inst)`。

最小示例：
```python
# app/panels/my_feature/panel.py
class MyFeaturePanel:
    def __init__(self):
        self._w = None
    def widget(self):  # 也可改为 mount(layout)
        from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
        if self._w is None:
            self._w = QWidget()
            lay = QVBoxLayout(self._w)
            lay.addWidget(QLabel("MyFeature"))
        return self._w

# app/panels/__init__.py（或任一初始化处）
from .registry import register_panel
from .my_feature.panel import MyFeaturePanel
register_panel("my_feature", lambda: MyFeaturePanel(), title="My Feature", meta={"i18n_key":"panel.my_feature"})
```

使用与测试：
- 运行时：`mw.open_panel("my_feature")` 即完成实例化与挂载。
- 预加载：将名称加入 `_DEFAULT_PRELOAD` 可随启动自动挂载（或在后续改为配置项）。
- E2E 校验：`mw._panel_widgets` 中应包含面板名键；即使无可见部件也会有占位符。
- Headless/无 Qt：不会创建布局/部件，但��安全调用 `open_panel()` 触发实例化与逻辑初始化。

最佳实践：
- 避免在 `__init__` 执行重 IO；将 UI 创建放到 `widget()`/`mount()` 内，或延迟到首次展示。
- 提供稳定的 QWidget 所有权与最小重绘；重复打开不应产生新部件。
- 使用 `meta.i18n_key` 与 i18n 资源配合以在列表/菜单中展示本地化标题。
