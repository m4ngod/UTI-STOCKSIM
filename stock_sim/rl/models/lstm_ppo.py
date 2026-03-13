# python
"""Recurrent PPO Policy (LSTM) for multi-symbol weight allocation (M1)."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Tuple, Optional
import torch
import torch.nn as nn
import torch.nn.functional as F

@dataclass
class ModelConfig:
    n_symbols: int
    per_symbol_feat: int          # 单个 symbol 展平特征长度 (含 lookback)
    account_feat: int             # 账户特征长度
    embed_dim: int = 64
    lstm_hidden: int = 128
    lstm_layers: int = 1
    action_low: float = -2.0
    action_high: float = 1.5

class SymbolEncoder(nn.Module):
    def __init__(self, in_dim: int, embed_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, embed_dim), nn.LayerNorm(embed_dim), nn.GELU(),
            nn.Linear(embed_dim, embed_dim), nn.LayerNorm(embed_dim), nn.GELU(),
        )

    def forward(self, x):  # x: (B, S, F)
        B,S,F = x.shape
        x = self.net(x)
        return x  # (B,S,E)

class PPORecurrentPolicy(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        self.symbol_encoder = SymbolEncoder(cfg.per_symbol_feat, cfg.embed_dim)
        self.account_encoder = nn.Sequential(
            nn.Linear(cfg.account_feat, cfg.embed_dim), nn.LayerNorm(cfg.embed_dim), nn.GELU()
        )
        self.reduce = nn.Sequential(
            nn.Linear(cfg.embed_dim * cfg.n_symbols, cfg.embed_dim), nn.GELU()
        )
        self.lstm = nn.LSTM(input_size=cfg.embed_dim * 2, hidden_size=cfg.lstm_hidden,
                            num_layers=cfg.lstm_layers, batch_first=True)
        # 策略输出 raw mean （未 squash, 对每 symbol 一个）
        self.policy_head = nn.Linear(cfg.lstm_hidden, cfg.n_symbols)
        # 共享 log_std 可训练参数 (每标的独立)
        self.log_std = nn.Parameter(torch.zeros(cfg.n_symbols))
        self.value_head = nn.Linear(cfg.lstm_hidden, 1)
        self.register_buffer('act_low', torch.tensor(cfg.action_low))
        self.register_buffer('act_high', torch.tensor(cfg.action_high))
        self._eps = 1e-6

    def forward(self, obs: torch.Tensor, hidden: Optional[Tuple[torch.Tensor, torch.Tensor]] = None):
        """返回: (deterministic_actions, value, raw_mean, hidden)
        deterministic_actions = tanh(raw_mean)*scale + mid
        训练时外部使用 raw_mean 与 self.log_std 进行采样与 log_prob 计算。
        """
        B,T,F = obs.shape
        psf = self.cfg.per_symbol_feat
        sym_block = self.cfg.n_symbols * psf
        sym_flat = obs[...,:sym_block]
        acct = obs[...,sym_block:]
        sym = sym_flat.view(B,T,self.cfg.n_symbols, psf)
        sym_2d = sym.view(B*T, self.cfg.n_symbols, psf)
        sym_emb = self.symbol_encoder(sym_2d)
        sym_emb = sym_emb.view(B,T,self.cfg.n_symbols,-1)
        sym_cat = sym_emb.reshape(B,T,-1)
        sym_red = self.reduce(sym_cat)
        acct_emb = self.account_encoder(acct)
        x = torch.cat([sym_red, acct_emb], dim=-1)
        out, hidden_out = self.lstm(x, hidden)
        raw_mean = self.policy_head(out)  # (B,T,S)
        value = self.value_head(out).squeeze(-1)  # (B,T)
        act_mid = (self.act_high + self.act_low) / 2.0
        act_amp = (self.act_high - self.act_low) / 2.0
        actions = torch.tanh(raw_mean) * act_amp + act_mid
        return actions, value, raw_mean, hidden_out

    # 供外部计算 log_prob（含 tanh squash 修正）
    def log_prob(self, raw_mean: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """actions: 已经 scale 到实际区间的最终动作 (B,S)
        raw_mean: (B,S) 未 squash 均值
        使用共享 log_std；需逆向还原 pre_tanh raw_action。
        y = (a - mid)/amp => raw = atanh(y)
        log_prob = Normal(raw_mean, std).log_prob(raw) - log(amp) - log(1 - y^2)
        返回 (B,) 各样本总 log_prob (对 S 维求和)
        """
        act_mid = (self.act_high + self.act_low) / 2.0
        act_amp = (self.act_high - self.act_low) / 2.0
        y = torch.clamp((actions - act_mid) / act_amp, -1 + self._eps, 1 - self._eps)
        raw = 0.5 * torch.log((1 + y) / (1 - y))  # atanh(y)
        std = torch.exp(self.log_std)  # (S,)
        var = std * std
        # Normal log_prob per dim
        lp = -0.5 * (((raw - raw_mean)/std)**2 + 2*self.log_std + math.log(2*math.pi))
        # squash 修正项: -log(amp) - log(1 - y^2)
        squash = torch.log(act_amp) + torch.log(1 - y * y + self._eps)
        lp_adjusted = lp - squash
        return lp_adjusted.sum(dim=-1)  # (B,)

    def initial_state(self, batch_size: int = 1):
        h = torch.zeros(self.cfg.lstm_layers, batch_size, self.cfg.lstm_hidden)
        c = torch.zeros(self.cfg.lstm_layers, batch_size, self.cfg.lstm_hidden)
        return (h, c)

__all__ = ["ModelConfig", "PPORecurrentPolicy"]
