# python
"""stocksimctl - 平台运维/诊断 CLI (platform-hardening Task13)

子命令:
  replay         : 回放事件 (需 ReplayService 实现)
  recover        : 执行恢复流程 (需 RecoveryService 实现)
  metrics        : 导出当前指标 (prom / json)
  risk-diagnose  : 风险规则/拒单统计与基本健康信息
  borrow-fee-run : 触发一次借券费用计提

设计目标:
  - 纯同步, 不启动后台线程
  - 软依赖: 若服务未实现或导入失败, 给予友好提示与非零退出码 (除 metrics)
  - 最小副作用: 只读操作除显式的 recover / borrow-fee-run
  - 兼容包方式与源码直接运行 (双路径导入 try/except)

退出码:
  0 成功
  1 服务缺失或未实现
  2 参数错误
  3 运行时内部错误
"""
from __future__ import annotations
import argparse
import json
import sys
import traceback
from typing import Any, List

# ---- 动态导入工具 ----

def _try_import(path_a: str, path_b: str):  # path_a 优先 (包内)
    try:
        return __import__(path_a, fromlist=['*'])
    except Exception:
        try:
            return __import__(path_b, fromlist=['*'])
        except Exception:
            return None

# 常用模块
settings_mod = _try_import('stock_sim.settings', 'settings')
metrics_exporter_mod = _try_import('stock_sim.services.metrics_exporter', 'services.metrics_exporter')
replay_service_mod = _try_import('stock_sim.services.replay_service', 'services.replay_service')
recovery_service_mod = _try_import('stock_sim.services.recovery_service', 'services.recovery_service')
risk_registry_mod = _try_import('stock_sim.services.risk_rule_registry', 'services.risk_rule_registry')
risk_engine_mod = _try_import('stock_sim.services.risk_engine', 'services.risk_engine')
borrow_fee_mod = _try_import('stock_sim.services.borrow_fee_scheduler', 'services.borrow_fee_scheduler')
metrics_mod = _try_import('stock_sim.observability.metrics', 'observability.metrics')

# ---- 子命令实现 ----

def cmd_metrics(args: argparse.Namespace) -> int:
    if not metrics_exporter_mod or not hasattr(metrics_exporter_mod, 'metrics_exporter'):
        print('错误: metrics_exporter 模块缺失, 仅输出基础计数器 (降级)。', file=sys.stderr)
        if metrics_mod and hasattr(metrics_mod, 'metrics'):
            # 简单序列化 counters
            counters = getattr(metrics_mod.metrics, 'counters', {})
            print(json.dumps({'metrics': counters}, ensure_ascii=False, indent=2))
            return 0
        return 1
    exporter = metrics_exporter_mod.metrics_exporter
    try:
        text = exporter.collect(fmt=args.fmt)
        print(text)
        return 0
    except Exception:
        traceback.print_exc()
        return 3

def cmd_borrow_fee_run(args: argparse.Namespace) -> int:
    if not borrow_fee_mod or not hasattr(borrow_fee_mod, 'borrow_fee_scheduler'):
        print('错误: borrow_fee_scheduler 不可用', file=sys.stderr)
        return 1
    scheduler = borrow_fee_mod.borrow_fee_scheduler
    try:
        count, total = scheduler.run()
        print(json.dumps({'positions_fees': count, 'total_fee': total}, ensure_ascii=False))
        return 0
    except Exception:
        traceback.print_exc()
        return 3

def cmd_recover(args: argparse.Namespace) -> int:
    if not recovery_service_mod:
        print('错误: recovery_service 模块缺失', file=sys.stderr)
        return 1
    # 寻找类或实例
    service = None
    for attr in ('recovery_service', 'service', 'RecoveryService'):
        if hasattr(recovery_service_mod, attr):
            service = getattr(recovery_service_mod, attr)
            break
    if service is None:
        print('错误: RecoveryService 未实现', file=sys.stderr)
        return 1
    # 若是类则实例化
    if isinstance(service, type):
        try:
            service = service()
        except Exception:
            traceback.print_exc()
            return 3
    if not hasattr(service, 'recover'):
        print('错误: 对象缺少 recover() 方法', file=sys.stderr)
        return 1
    try:
        result = service.recover()
        print(json.dumps({'recover_result': result}, ensure_ascii=False))
        return 0
    except Exception:
        traceback.print_exc()
        return 3

def cmd_replay(args: argparse.Namespace) -> int:
    if not replay_service_mod:
        print('错误: replay_service 模块缺失', file=sys.stderr)
        return 1
    service = None
    for attr in ('replay_service', 'service', 'ReplayService'):
        if hasattr(replay_service_mod, attr):
            service = getattr(replay_service_mod, attr)
            break
    if service is None:
        print('错误: ReplayService 未实现', file=sys.stderr)
        return 1
    if isinstance(service, type):
        try:
            service = service()
        except Exception:
            traceback.print_exc(); return 3
    # 假设接口 load_events(start,end) -> iterator
    start = args.start
    end = args.end
    limit = args.limit
    if not hasattr(service, 'load_events'):
        print('错误: ReplayService 缺少 load_events(start,end)', file=sys.stderr)
        return 1
    try:
        it = service.load_events(start, end)
        count = 0
        for ev in it:
            print(json.dumps(ev, ensure_ascii=False))
            count += 1
            if limit and count >= limit:
                break
        print(f'# events={count}', file=sys.stderr)
        return 0
    except Exception:
        traceback.print_exc(); return 3

def _collect_risk_rules() -> List[str]:
    names: List[str] = []
    if risk_registry_mod:
        # 可能有 registry 对象 / list_rules 方法
        for attr in ('registry', 'risk_rule_registry', 'RULES', 'rules'):
            obj = getattr(risk_registry_mod, attr, None)
            if obj is None:
                continue
            # list-like
            try:
                for r in obj:  # type: ignore
                    nm = getattr(r, 'name', None) or getattr(r, '__name__', str(r))
                    names.append(str(nm))
            except Exception:
                pass
        if hasattr(risk_registry_mod, 'list_rules'):
            try:
                for r in risk_registry_mod.list_rules():  # type: ignore
                    nm = getattr(r, 'name', None) or getattr(r, '__name__', str(r))
                    names.append(str(nm))
            except Exception:
                pass
    return sorted(set(names))

def cmd_risk_diagnose(args: argparse.Namespace) -> int:
    # 输出: 已注册规则列表 + metrics 中风险拒单统计
    rule_names = _collect_risk_rules()
    counters = {}
    if metrics_mod and hasattr(metrics_mod, 'metrics'):
        counters = getattr(metrics_mod.metrics, 'counters', {})
    risk_reject_per_rule = {}
    for k, v in counters.items():
        if k.startswith('risk_reject_total__'):
            risk_reject_per_rule[k.split('__', 1)[1]] = v
    summary = {
        'registered_rules': rule_names,
        'risk_reject_total': counters.get('risk_reject_total'),
        'risk_reject_per_rule': risk_reject_per_rule,
        'raw_counter_keys': sorted(list(counters.keys())),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0

# ---- Argparse ----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='stocksimctl', description='StockSim 平台硬化运维/诊断 CLI')
    sub = p.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('metrics', help='导出指标')
    sp.add_argument('--fmt', choices=['prom', 'json'], default='prom')
    sp.set_defaults(func=cmd_metrics)

    sp = sub.add_parser('borrow-fee-run', help='立即跑一次借券费用计提')
    sp.set_defaults(func=cmd_borrow_fee_run)

    sp = sub.add_parser('recover', help='执行恢复流程')
    sp.set_defaults(func=cmd_recover)

    sp = sub.add_parser('replay', help='事件回放 (打印 JSON 行)')
    sp.add_argument('--start', type=str, required=False, help='起始事件时间/ID (实现依赖)')
    sp.add_argument('--end', type=str, required=False, help='结束事件时间/ID (实现依赖)')
    sp.add_argument('--limit', type=int, default=0, help='最多输出条数 (0 不限制)')
    sp.set_defaults(func=cmd_replay)

    sp = sub.add_parser('risk-diagnose', help='风险规则与拒单统计')
    sp.set_defaults(func=cmd_risk_diagnose)
    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))  # type: ignore
    except SystemExit as e:
        return int(e.code or 0)
    except AttributeError:
        parser.print_help(sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        return 3

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())

