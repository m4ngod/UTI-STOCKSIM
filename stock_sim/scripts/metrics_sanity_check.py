"""指标健全性快速检查脚本 (platform-hardening Task23 补全)

用途:
  启动最小运行环境 (仅内存对象), 人工写入/模拟若干关键指标, 通过 MetricsExporter
  采集 prom 文本并断言核心监控字段存在, 作为回归/CI 的轻量守门脚本。

检查范围 (可扩展):
  - event_queue_size (基础运行队列观测)
  - persistence_failures_total (持久化失败聚合别名)
  - crash_counter (即使=0 也应出现)
  - risk_reject_total (规则聚合)
  - order_latency_hist_count (延迟统计样本数)

设计:
  - 不依赖真实撮合, 直接调用 metrics API 填充。
  - 允许重复运行 (幂等)。
  - 若缺失则打印缺失列表并返回 exit code=2。

扩展指引:
  - 新增强制指标: 在 REQUIRED_METRICS 列表中追加名称。
  - 若需 JSON 校验: 调用 collect(fmt='json') 并解析。
"""
from __future__ import annotations
import sys
import os
from typing import List, Set

# 确保项目根目录加入 sys.path (脚本位于 scripts/ 下)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from services.metrics_exporter import metrics_exporter  # type: ignore
    from observability.metrics import metrics as _local_metrics  # type: ignore  # 仅调试备用
except Exception as e:  # pragma: no cover - 导入失败直接退出
    print(f"[metrics_sanity_check] 导入失败: {e}", file=sys.stderr)
    sys.exit(1)

# 统一引用 exporter 内部使用的 metrics 实例，确保写入可见
metrics = getattr(metrics_exporter, 'metrics', _local_metrics)

# ---- 准备模拟数据 ----
# 基础计数器
metrics.inc('event_persist_failures', 1)              # 触发 persistence_failures_total 映射
metrics.inc('risk_reject_total__DummyRule', 2)        # 聚合 risk_reject_total
metrics.inc('crash_counter', 0)                       # 显式出现 (即便=0)
# 延迟样本 (毫秒)
metrics.add_timing('order_latency', 0.12)
metrics.add_timing('order_latency', 0.34)

# 可选: 模拟队列长度指标 (Exporter 会直接探测 event_bus._queue 长度, 这里不强制)
# 若 event_bus 没有 _queue, exporter 会容错并跳过, 但我们仍然要求 event_queue_size 出现在输出。
# 因此我们确保 event_bus 存在一个 _queue 属性 (最小写入) —— 仅在缺失时补充。
try:  # pragma: no cover - 安全注入
    from infra import event_bus  # type: ignore
    if not hasattr(event_bus, '_queue'):
        setattr(event_bus, '_queue', [])  # 最小占位
except Exception:
    pass

# ---- 收集指标 (Prom 格式) ----
prom_text = metrics_exporter.collect('prom')
# print(prom_text)  # 调试时可打开

# ---- 解析行 -> key/value ----
found: Set[str] = set()
for line in prom_text.splitlines():
    if not line or line.startswith('#'):
        continue
    segment = line
    # 去除标签
    if '{' in segment:
        segment = segment.split('{', 1)[0]
    # 去除数值
    if ' ' in segment:
        segment = segment.split(' ', 1)[0]
    name = segment.strip()
    if name:
        found.add(name)

REQUIRED_METRICS: List[str] = [
    'event_queue_size',
    'persistence_failures_total',
    'crash_counter',
    'risk_reject_total',
    'order_latency_hist_count',
]

missing = [m for m in REQUIRED_METRICS if m not in found]
if missing:
    print('[metrics_sanity_check] 缺失指标: ' + ', '.join(missing), file=sys.stderr)
    # 输出当前收集的键以便排查
    print('[metrics_sanity_check] 已发现指标: ' + ', '.join(sorted(found)), file=sys.stderr)
    sys.exit(2)

print('[metrics_sanity_check] OK 所有必需指标存在; total_keys=', len(found))

if __name__ == '__main__':  # 允许作为脚本执行
    # 主逻辑已经执行; 这里不再重复
    pass
