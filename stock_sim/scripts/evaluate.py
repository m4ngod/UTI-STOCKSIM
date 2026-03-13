# python
"""评估脚本 evaluate.py (M1)
用法:
  python -m stock_sim.scripts.evaluate --symbols 000001.SZ,600000.SH --model models/latest/model.pt

流程:
1. 读取 env_m1.yaml & train_m1.yaml (可选) 合并参数
2. 拉取近 lookback_days 数据构建 bars
3. 生成事件节点
4. 创建评估环境(无训练、禁用随机噪声可选)
5. 加载模型, rollout (max_eval_steps 或直到 done)
6. 计算指标: 累计收益、年化收益、波动、夏普、最大回撤、换手、胜率、平均事件标记率、平均杠杆
7. 输出 metrics_eval.json
"""
from __future__ import annotations
import argparse, json, math, yaml
from pathlib import Path
from datetime import datetime
import numpy as np
import torch

from stock_sim.data_pipeline.fetch_bars import fetch_30s_bars, FetchConfig
from stock_sim.data_pipeline.build_event_nodes import build_event_nodes, EventConfig
from stock_sim.rl.trading_env import EventTradingEnv, EnvConfig
from stock_sim.rl.models.lstm_ppo import PPORecurrentPolicy, ModelConfig
from stock_sim.persistence.models_imports import SessionLocal

# 简单工具

def load_yaml(path: str | Path):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def sharpe_ratio(returns: np.ndarray, rf_daily: float = 0.0):
    if returns.size == 0:
        return 0.0
    excess = returns - rf_daily
    vol = excess.std(ddof=1)
    if vol < 1e-12:
        return 0.0
    return excess.mean() / vol


def max_drawdown(equity_curve: np.ndarray):
    if equity_curve.size == 0:
        return 0.0
    peak = -1e30
    mdd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd
    return mdd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', type=str, required=False, help='逗号分隔符号(若不指定则使用 env_m1.yaml)')
    ap.add_argument('--model', type=str, required=True, help='模型权重路径')
    ap.add_argument('--env_cfg', type=str, default='configs/env_m1.yaml')
    ap.add_argument('--train_cfg', type=str, default='configs/train_m1.yaml')
    ap.add_argument('--lookback_days', type=int, default=None)
    ap.add_argument('--max_eval_steps', type=int, default=None)
    ap.add_argument('--device', type=str, default='cpu')
    ap.add_argument('--output', type=str, default='metrics_eval.json')
    args = ap.parse_args()

    env_cfg_yaml = load_yaml(args.env_cfg)
    train_cfg_yaml = load_yaml(args.train_cfg)
    symbols = [s.strip() for s in (args.symbols.split(',') if args.symbols else env_cfg_yaml.get('symbols', [])) if s.strip()]
    if not symbols:
        raise SystemExit('未指定 symbols')
    lookback_days = args.lookback_days or env_cfg_yaml.get('lookback_days', 5)
    max_eval_steps = args.max_eval_steps or train_cfg_yaml.get('train', {}).get('max_eval_steps', 2000)

    # Risk-free
    risk_free_rate = train_cfg_yaml.get('metrics', {}).get('risk_free_rate', 0.02)
    trading_days = train_cfg_yaml.get('metrics', {}).get('trading_days_per_year', 252)
    rf_daily = risk_free_rate / trading_days

    # 数据
    day = datetime.utcnow()
    session = SessionLocal()
    bars = fetch_30s_bars(symbols, day, session, FetchConfig(lookback_days=lookback_days))
    events_nodes = build_event_nodes(bars, EventConfig())

    indices = events_nodes.indices
    event_flags = events_nodes.event_flags

    # Env
    env_conf_section = env_cfg_yaml.get('env', {})
    env_conf = EnvConfig(symbols=symbols,
                         max_position_leverage=env_conf_section.get('max_position_leverage', 3.0),
                         weight_low=env_conf_section.get('weight_low', -2.0),
                         weight_high=env_conf_section.get('weight_high', 1.5),
                         lookback_nodes=env_conf_section.get('lookback_nodes', 10),
                         commission_rate=env_conf_section.get('commission_rate', 0.0005),
                         stamp_duty=env_conf_section.get('stamp_duty', 0.001),
                         slippage=env_conf_section.get('slippage', 0.0003),
                         reward_cost_alpha=env_conf_section.get('reward_cost_alpha', 1.0),
                         leverage_penalty_beta=env_conf_section.get('leverage_penalty_beta', 0.0),
                         leverage_target=env_conf_section.get('leverage_target', 2.0),
                         clip_reward=env_conf_section.get('clip_reward', 0.05),
                         seed=env_conf_section.get('seed', 42))

    def bars_provider(_symbols):
        return bars
    def event_provider(_bars):
        return indices

    env = EventTradingEnv(env_conf, bars_provider=bars_provider, event_nodes_provider=event_provider,
                          seed=env_conf.seed, event_flags=event_flags)
    obs,_ = env.reset()

    # 模型装载
    total_feat = obs.shape[0]
    account_feat = 6
    per_symbol_feat = (total_feat - account_feat) // len(symbols)
    model_cfg = ModelConfig(n_symbols=len(symbols), per_symbol_feat=per_symbol_feat, account_feat=account_feat)
    model = PPORecurrentPolicy(model_cfg).to(args.device)
    sd = torch.load(args.model, map_location=args.device)
    model.load_state_dict(sd, strict=False)
    model.eval()

    h, c = model.initial_state(batch_size=1)
    h = h.to(args.device); c = c.to(args.device)

    equity_curve = []
    rewards = []
    turnovers = []
    event_hits = []
    leverages = []
    wins = 0; losses = 0

    step = 0
    last_account_value = None
    with torch.no_grad():
        while step < max_eval_steps:
            obs_tensor = torch.tensor(obs, dtype=torch.float32, device=args.device).unsqueeze(0).unsqueeze(1)
            acts, vals, logits, (h, c) = model(obs_tensor, (h, c))
            action = acts.squeeze(0).squeeze(0).cpu().numpy()
            obs, reward, done, trunc, info = env.step(action)
            rewards.append(reward)
            equity_curve.append(info['account_value'])
            turnovers.append(info.get('turnover', 0.0))
            event_hits.append(info.get('event_flag', 0))
            gross = info.get('gross_exposure', 0.0)
            av = info.get('account_value', 0.0)
            leverages.append(gross / av if av>0 else 0.0)
            if last_account_value is not None:
                pnl = av - last_account_value
                if pnl > 0: wins += 1
                elif pnl < 0: losses += 1
            last_account_value = av
            step += 1
            if done:
                break

    eq_arr = np.array(equity_curve)
    ret_steps = np.diff(eq_arr) / eq_arr[:-1]
    cum_return = eq_arr[-1]/eq_arr[0]-1 if eq_arr.size>1 else 0.0
    avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0
    event_rate = float(np.mean(event_hits)) if event_hits else 0.0
    avg_leverage = float(np.mean(leverages)) if leverages else 0.0
    sharpe = sharpe_ratio(ret_steps, rf_daily)
    ann_factor = math.sqrt(trading_days * (len(ret_steps)/max(1,len(ret_steps))))  # 近似
    ann_vol = ret_steps.std(ddof=1) * math.sqrt(trading_days) if ret_steps.size>1 else 0.0
    ann_return = (1+ret_steps.mean())**trading_days -1 if ret_steps.size>0 else 0.0
    mdd = max_drawdown(eq_arr)
    win_rate = wins / max(1, wins+losses)

    metrics = {
        'symbols': symbols,
        'steps': step,
        'cum_return': cum_return,
        'ann_return': ann_return,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'max_drawdown': mdd,
        'avg_turnover': avg_turnover,
        'event_rate': event_rate,
        'avg_leverage': avg_leverage,
        'win_rate': win_rate,
        'equity_curve': eq_arr.tolist(),
        'ret_steps_mean': float(ret_steps.mean()) if ret_steps.size>0 else 0.0,
        'ret_steps_std': float(ret_steps.std(ddof=1)) if ret_steps.size>1 else 0.0,
        'timestamp': datetime.utcnow().isoformat()
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print("评估完成 ->", args.output)

if __name__ == '__main__':
    main()

