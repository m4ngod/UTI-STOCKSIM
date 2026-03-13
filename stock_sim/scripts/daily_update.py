# python
"""每日滚动训练流水线脚本 (M1 MVP)
Steps:
1. 拉取新数据 (fetch_bars)
2. 事件节点生成 (build_event_nodes)
3. 构建环境 & 收集 rollout
4. PPO 更新
5. 评估 (可选)
6. 保存模型/指标

运行方式: python -m stock_sim.scripts.daily_update --symbols 000001.SZ,600000.SH
"""
from __future__ import annotations
import argparse, json, os
from datetime import datetime
from pathlib import Path
import numpy as np
import torch

from stock_sim.data_pipeline.fetch_bars import fetch_30s_bars, FetchConfig
from stock_sim.data_pipeline.build_event_nodes import build_event_nodes, EventConfig, EventNodes
from stock_sim.rl.trading_env import EventTradingEnv, EnvConfig
from stock_sim.rl.models.lstm_ppo import PPORecurrentPolicy, ModelConfig
from stock_sim.rl.ppo_agent import PPOAgent, PPOConfig
from stock_sim.persistence.models_imports import SessionLocal

ARTIFACT_ROOT = Path("models")
ARTIFACT_ROOT.mkdir(exist_ok=True)


def make_envs(symbols, bars_dict, event_nodes: EventNodes, num_envs: int):
    envs = []
    indices = event_nodes.indices
    flags = event_nodes.event_flags
    for i in range(num_envs):
        def bars_provider(_symbols):
            return bars_dict
        def event_provider(_bars):
            return indices
        cfg = EnvConfig(symbols=symbols)
        env = EventTradingEnv(cfg, bars_provider=bars_provider, event_nodes_provider=event_provider,
                               seed=42+i, event_flags=flags)
        obs,_ = env.reset()
        envs.append((env, obs))
    return envs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbols', type=str, required=True, help='逗号分隔符号')
    parser.add_argument('--lookback_days', type=int, default=5)
    parser.add_argument('--num_envs', type=int, default=8)
    parser.add_argument('--rollout', type=int, default=512)
    parser.add_argument('--epochs', type=int, default=4)
    parser.add_argument('--device', type=str, default='cpu')
    parser.add_argument('--out', type=str, default='latest')
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
    day = datetime.utcnow()
    session = SessionLocal()
    bars = fetch_30s_bars(symbols, day, session, FetchConfig(lookback_days=args.lookback_days))
    events = build_event_nodes(bars, EventConfig())
    # Env 构建
    env_wrappers = make_envs(symbols, bars, events, args.num_envs)
    envs = [e for e,_ in env_wrappers]
    obs_init = [o for _,o in env_wrappers]

    # 模型
    first_obs = obs_init[0]
    # 拆分维度: account_feat = 6 与 env 定义一致; per_symbol_feat 需根据 lookback_nodes*每节点特征数
    # 这里无法直接得出, 简化: 通过 symbols 数量反推
    n_symbols = len(symbols)
    total_feat = first_obs.shape[0]
    account_feat = 6
    # 假设 feature_list len=5, lookback=10 => per_symbol_flat=50
    per_symbol_feat = (total_feat - account_feat) // n_symbols
    mcfg = ModelConfig(n_symbols=n_symbols, per_symbol_feat=per_symbol_feat, account_feat=account_feat)
    policy = PPORecurrentPolicy(mcfg)
    pcfg = PPOConfig(rollout_length=args.rollout, epochs=args.epochs, device=args.device)
    agent = PPOAgent(policy, pcfg)

    # 收集 rollout
    data = agent.collect_rollout(envs, obs_init)
    # 训练
    losses = agent.update(data)

    # 保存
    out_dir = ARTIFACT_ROOT / args.out
    out_dir.mkdir(exist_ok=True, parents=True)
    torch.save(policy.state_dict(), out_dir / 'model.pt')
    with open(out_dir / 'metrics.json', 'w', encoding='utf-8') as f:
        json.dump({'losses': losses, 'symbols': symbols, 'time': day.isoformat()}, f, ensure_ascii=False, indent=2)
    print('保存完成', losses)

if __name__ == '__main__':
    main()
