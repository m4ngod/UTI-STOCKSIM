# python
"""简化版 PPO + LSTM 训练脚手架 (M1)

功能:
- Rollout 收集 (向量 env 接口需用户自行封装, 这里假设 list[env])
- GAE 计算
- PPO Clip 更新
- 观测 / 奖励归一 (可选)

限制:
- 不含多进程; 用户可自行用 subprocess / ray / torch.multiprocessing 包装
- 未集成混合精度与分布式; 可后续扩展
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
import numpy as np
import torch
import torch.nn.functional as F
from torch.optim import Adam
import math

from .utils.normalizer import RunningMeanStd
from .models.lstm_ppo import PPORecurrentPolicy, ModelConfig

@dataclass
class PPOConfig:
    rollout_length: int = 2048
    minibatches: int = 8
    epochs: int = 4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    entropy_coef: float = 0.005
    value_coef: float = 0.5
    lr: float = 3e-4
    grad_clip: float = 0.5
    normalize_obs: bool = True
    normalize_reward: bool = True
    device: str = 'cuda'

class PPOAgent:
    def __init__(self, model: PPORecurrentPolicy, cfg: PPOConfig):
        self.model = model.to(cfg.device)
        self.cfg = cfg
        self.opt = Adam(self.model.parameters(), lr=cfg.lr)
        self.obs_rms: Optional[RunningMeanStd] = None
        self.rew_rms: Optional[RunningMeanStd] = None

    def _prep_norm(self, obs_shape, device):
        if self.cfg.normalize_obs and self.obs_rms is None:
            self.obs_rms = RunningMeanStd(obs_shape)
        if self.cfg.normalize_reward and self.rew_rms is None:
            self.rew_rms = RunningMeanStd(())

    def _norm_obs(self, obs: np.ndarray) -> np.ndarray:
        if self.obs_rms is None:
            return obs
        self.obs_rms.update(obs)
        return self.obs_rms.normalize(obs)

    def _norm_reward(self, rewards: np.ndarray) -> np.ndarray:
        if self.rew_rms is None:
            return rewards
        self.rew_rms.update(rewards)
        std = np.sqrt(self.rew_rms.var + self.rew_rms.epsilon)
        return rewards / max(1e-8, std)

    def collect_rollout(self, envs: List, initial_obs: List[np.ndarray]) -> Dict[str, Any]:
        """envs: list of gym-like env (已 reset)
        返回一次完整 rollout 数据
        """
        device = self.cfg.device
        n_env = len(envs)
        obs_list = []
        actions_list = []
        values_list = []
        rewards_list = []
        dones_list = []
        logit_list = []
        h, c = self.model.initial_state(batch_size=n_env)
        h = h.to(device); c = c.to(device)
        obs = np.stack(initial_obs, axis=0)
        self._prep_norm(obs.shape[1:], device)
        logp_list = []
        mean_list = []
        for t in range(self.cfg.rollout_length):
            obs_norm = self._norm_obs(obs) if self.cfg.normalize_obs else obs
            obs_tensor = torch.tensor(obs_norm, dtype=torch.float32, device=device).unsqueeze(1)
            with torch.no_grad():
                det_actions, vals, raw_mean, (h, c) = self.model(obs_tensor, (h, c))  # det_actions:(N,1,A) raw_mean:(N,1,A)
                std = torch.exp(self.model.log_std)  # (A,)
                eps = torch.randn_like(raw_mean)
                raw_sample = raw_mean + eps * std  # (N,1,A)
                # squash + scale
                act_mid = (self.model.act_high + self.model.act_low)/2.0
                act_amp = (self.model.act_high - self.model.act_low)/2.0
                sampled = torch.tanh(raw_sample) * act_amp + act_mid  # 最终动作
                logp = self.model.log_prob(raw_mean.squeeze(1), sampled.squeeze(1))  # (N,)
            acts_np = sampled.squeeze(1).cpu().numpy()
            vals_np = vals.squeeze(1).cpu().numpy()
            raw_mean_np = raw_mean.squeeze(1).cpu().numpy()
            logp_np = logp.cpu().numpy()
            next_obs=[]; rew_arr=[]; done_arr=[]
            for i, env in enumerate(envs):
                o,r,d,trunc,info = env.step(acts_np[i])
                next_obs.append(o); rew_arr.append(r); done_arr.append(d or trunc)
                if d or trunc:
                    o2,_ = env.reset(); next_obs[-1]=o2
            obs_list.append(obs.copy())
            actions_list.append(acts_np)
            values_list.append(vals_np)
            rewards_list.append(rew_arr)
            dones_list.append(done_arr)
            logit_list.append(raw_mean_np)  # 这里存 raw_mean 供更新时重算 log_prob
            logp_list.append(logp_np)
            mean_list.append(raw_mean_np)
            obs = np.array(next_obs)
        # 转换
        obs_arr = np.stack(obs_list)
        act_arr = np.stack(actions_list)
        val_arr = np.stack(values_list)
        rew_arr = np.stack(rewards_list)
        done_arr = np.stack(dones_list)
        mean_arr = np.stack(mean_list)  # (T,N,A)
        logp_arr = np.stack(logp_list)  # (T,N)
        # GAE
        adv, ret = self._compute_gae(rew_arr, val_arr, done_arr)
        if self.cfg.normalize_reward:
            adv = self._norm_reward(adv)
        data = {
            'obs': obs_arr,
            'actions': act_arr,
            'values': val_arr,
            'advantages': adv,
            'returns': ret,
            'raw_mean': mean_arr,
            'logp': logp_arr
        }
        return data

    def _compute_gae(self, rewards, values, dones):
        T, N = rewards.shape
        adv = np.zeros_like(rewards)
        last_gae = np.zeros(N, dtype=np.float32)
        for t in reversed(range(T)):
            nonterminal = 1.0 - dones[t]
            next_values = values[t+1] if t < T-1 else values[t]
            delta = rewards[t] + self.cfg.gamma * next_values * nonterminal - values[t]
            last_gae = delta + self.cfg.gamma * self.cfg.gae_lambda * nonterminal * last_gae
            adv[t] = last_gae
        returns = adv + values
        return adv, returns

    def update(self, data: Dict[str, Any]):
        device = self.cfg.device
        obs = data['obs']; actions = data['actions']; old_values = data['values']
        advantages = data['advantages']; returns = data['returns']
        old_raw_mean = data['raw_mean']; old_logp = data['logp']
        T,N,F = obs.shape; A = actions.shape[-1]; B = T*N
        obs_f = obs.reshape(B,F)
        act_f = actions.reshape(B,A)
        adv_f = advantages.reshape(B)
        ret_f = returns.reshape(B)
        old_logp_f = old_logp.reshape(B)
        # 标准化 advantage
        adv_mean = adv_f.mean(); adv_std = adv_f.std()+1e-8; adv_f = (adv_f-adv_mean)/adv_std
        batch_idx = np.arange(B); mb_size = B // self.cfg.minibatches
        losses = {}
        for ep in range(self.cfg.epochs):
            np.random.shuffle(batch_idx)
            for start in range(0,B,mb_size):
                end = start+mb_size; idx = batch_idx[start:end]
                obs_tensor = torch.tensor(obs_f[idx], dtype=torch.float32, device=device).unsqueeze(1)
                act_tensor = torch.tensor(act_f[idx], dtype=torch.float32, device=device)
                old_logp_tensor = torch.tensor(old_logp_f[idx], dtype=torch.float32, device=device)
                adv_tensor = torch.tensor(adv_f[idx], dtype=torch.float32, device=device)
                ret_tensor = torch.tensor(ret_f[idx], dtype=torch.float32, device=device)
                det_actions, values_pred, raw_mean_new, _ = self.model(obs_tensor)
                values_pred = values_pred.squeeze(1)
                # 重新计算 log_prob
                new_logp = self.model.log_prob(raw_mean_new.squeeze(1), act_tensor)
                ratio = torch.exp(new_logp - old_logp_tensor)
                surr1 = ratio * adv_tensor
                surr2 = torch.clamp(ratio, 1.0 - self.cfg.clip_range, 1.0 + self.cfg.clip_range) * adv_tensor
                policy_loss = -torch.mean(torch.min(surr1, surr2))
                value_loss = F.mse_loss(values_pred, ret_tensor)
                # 近似熵: raw Gaussian 熵 (忽略 squash Jacobian 期望项)
                std = torch.exp(self.model.log_std)
                entropy_val = 0.5 + 0.5*math.log(2*math.pi) + torch.log(std)
                entropy = entropy_val.sum() / act_tensor.shape[0]
                loss = policy_loss + self.cfg.value_coef * value_loss - self.cfg.entropy_coef * entropy
                self.opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg.grad_clip); self.opt.step()
                losses = {'policy': float(policy_loss.item()), 'value': float(value_loss.item()), 'entropy': float(entropy.item())}
        return losses

__all__ = ["PPOConfig", "PPOAgent"]
