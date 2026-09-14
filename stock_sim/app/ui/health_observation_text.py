"""Read-only rendering of the six existing typed health observation groups.

No clocks, reads, lifecycle decisions or inferred component expiry policies live
here. A missing independent fact is shown as missing, not borrowed from a peer.
"""

from datetime import datetime

from app.features.run_monitoring import Freshness
from app.features.system_health import (
    DiagnosticCacheHealthComponent, DiagnosticDataSourceHealthComponent,
    DiagnosticQueueHealthComponent, PersistenceHealthComponent,
    RuntimeHealthComponent, SystemHealthError, SystemHealthViewState,
    VersionHealthComponent,
)


_CLASSIFICATION = {
    "healthy": "正常", "degraded": "受限", "stale": "已过期",
    "unavailable": "不可用", "incompatible": "不兼容", "unknown": "未知",
    "recovering": "恢复中", "fallback": "使用回退", "not_applicable": "不适用",
}
_FRESHNESS = {
    "fresh": "新鲜", "stale": "已过期", "awaiting_first_state": "尚无可靠观察",
}
_SCOPES = {
    "application_runtime": "应用运行时", "diagnostic_persistence": "诊断持久化",
    "version_compatibility": "版本兼容", "diagnostic_task": "旧任务",
    "task_handle": "任务进度", "formal_diagnostic_campaign": "实验批次",
    "campaign_nodes": "运行节点", "strategy_run": "运行",
    "diagnostic_evidence": "证据", "diagnostic_finding": "发现",
    "sensitivity_breakpoint": "敏感度断点", "reproduction_manifest": "复现资料",
    "scenario_inputs": "场景输入", "diagnostic_evidence_interpretation": "证据解释",
    "reference_market_paths": "参考行情路径",
}


def _time(value: datetime | None) -> str:
    return "未提供" if value is None else value.isoformat()


def _diagnostic(error: SystemHealthError | None) -> str:
    if error is None:
        return "诊断 · 未报告该组错误"
    # Feature errors are already safe diagnostic records, not raw exceptions.
    return f"诊断 · {error.code.value} · {error.explanation}"


def _affected_work(state: SystemHealthViewState, component_key: str) -> str:
    if state.diagnostic_context.requested is None:
        return "当前影响 · 未关联任务；仅展示系统事实"
    impact = next((item for item in state.component_impacts
                   if item.component.value == component_key), None)
    if impact is None or not impact.affected_scope:
        return "当前影响 · 未提供此关联对象的影响范围"
    scopes = "、".join(_SCOPES[item.value] for item in impact.affected_scope)
    classification = _CLASSIFICATION[impact.classification.value]
    return f"当前影响 · {scopes}；{classification}"


def health_observation_text(state: SystemHealthViewState | None) -> str:
    """Render only facts in this delivered snapshot, including missing facts."""
    if state is None:
        return "六类观察尚未返回；观察时间、过期条件和当前影响均待确认。"
    core = {item.identity.value: item for item in state.components}
    groups = (
        ("运行时", "application_runtime", core.get("application_runtime")),
        ("数据源", "diagnostic_data_source", state.diagnostic_data_source),
        ("队列", "diagnostic_queue", state.diagnostic_queue),
        ("缓存", "diagnostic_cache", state.diagnostic_cache),
        ("持久化", "diagnostic_persistence", core.get("diagnostic_persistence")),
        ("版本兼容", "version_compatibility", core.get("version_compatibility")),
    )
    sections = []
    for title, key, component in groups:
        if component is None:
            sections.append(f"{title} · 未知\n观察记录 · 未提供\n过期条件 · 未提供\n"
                            + _affected_work(state, key) + "\n诊断 · 尚无该组观察")
            continue
        lines = [f"{title} · {_CLASSIFICATION[component.classification.value]}",
                 component.explanation, f"观察记录 · {_time(component.observed_at)}"]
        if isinstance(component, (DiagnosticDataSourceHealthComponent,
                                  DiagnosticQueueHealthComponent,
                                  DiagnosticCacheHealthComponent, PersistenceHealthComponent)):
            reliable_age = component.freshness in (Freshness.FRESH, Freshness.STALE)
            age = f"{component.age.total_seconds():.1f} 秒" if reliable_age else "未知"
            lines.extend((
                "时效 · " + _FRESHNESS.get(component.freshness.value, "未知"),
                "观察年龄 · " + age,
                f"过期阈值 · {component.freshness_threshold.total_seconds():.1f} 秒；以本组权威时效为准",
            ))
        else:
            # Runtime/version 1.0 do not carry an independent age/threshold.
            lines.extend(("独立过期阈值 · 未提供（旧接口未声明）",
                          "最近成功观察 · " + _time(component.last_successful_observation_at)))
        if isinstance(component, DiagnosticDataSourceHealthComponent):
            reliable = component.last_reliable_observation
            lines.append("最近可靠观察 · " + _time(None if reliable is None else reliable.observed_at))
        elif isinstance(component, PersistenceHealthComponent):
            lines.extend(("最近成功读取 · " + _time(component.last_successful_durable_read_at),
                          "最近成功写入 · " + _time(component.last_successful_durable_write_at)))
        if isinstance(component, RuntimeHealthComponent):
            scope = "应用运行时"
            error = state.error if state.error is not None and state.error.affected_scope.value == key else None
        elif isinstance(component, (PersistenceHealthComponent, VersionHealthComponent)):
            scope = _SCOPES[component.affected_scope.value]
            error = component.error
        else:
            scope = "、".join(_SCOPES[item.value] for item in component.affected_scope) or "未提供"
            error = component.error
        lines.extend(("作用范围 · " + scope, _affected_work(state, key), _diagnostic(error)))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
