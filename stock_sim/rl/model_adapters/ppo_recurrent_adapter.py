from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import json
import math

import numpy as np
import torch
import torch.nn.functional as F
from torch.optim import Adam

from rl.models.lstm_ppo import ModelConfig, PPORecurrentPolicy


@dataclass
class RecurrentPPOPolicyConfig:
    max_symbols: int = 8
    per_symbol_feat: int = 6
    account_feat: int = 8
    embed_dim: int = 64
    lstm_hidden: int = 128
    lstm_layers: int = 1
    action_low: float = 0.0
    action_high: float = 0.60
    max_gross_leverage: float = 1.0
    cash_buffer_ratio: float = 0.05
    deterministic: bool = False
    min_update_steps: int = 16
    gamma: float = 0.99
    clip_ratio: float = 0.2
    entropy_coef: float = 0.005
    value_coef: float = 0.5
    lr: float = 3e-4
    grad_clip: float = 0.5
    device: str = "cpu"


class RecurrentPPOPolicyAdapter:
    """PyTorch recurrent actor-critic policy that emits act.v1 target weights.

    This is the first real model adapter for the platform. It intentionally keeps
    training modest: `learn(...)` performs a bounded PPO-style actor-critic update
    over the latest on-policy mini rollout, while full league scheduling remains
    outside the model object.
    """

    def __init__(
        self,
        *,
        model_id: str = "ppo_lstm_v1",
        config: RecurrentPPOPolicyConfig | dict[str, Any] | None = None,
        seed: int | None = None,
    ):
        self.model_id = str(model_id or "ppo_lstm_v1")
        self.config = _coerce_config(config)
        if seed is not None:
            torch.manual_seed(int(seed))
            np.random.seed(int(seed) % (2**32 - 1))
        model_cfg = ModelConfig(
            n_symbols=self.config.max_symbols,
            per_symbol_feat=self.config.per_symbol_feat,
            account_feat=self.config.account_feat,
            embed_dim=self.config.embed_dim,
            lstm_hidden=self.config.lstm_hidden,
            lstm_layers=self.config.lstm_layers,
            action_low=self.config.action_low,
            action_high=self.config.action_high,
        )
        self.model = PPORecurrentPolicy(model_cfg).to(self.config.device)
        self.optimizer = Adam(self.model.parameters(), lr=self.config.lr)
        self._hidden = None
        self._buffer: list[dict[str, Any]] = []
        self._update_count = 0
        self._last_loss: dict[str, float] = {}

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        obs_vec, symbols = self._featurize(observation)
        if not symbols:
            return self._hold_action(observation, reason="NO_SYMBOLS")
        obs_tensor = torch.tensor(obs_vec, dtype=torch.float32, device=self.config.device).view(1, 1, -1)
        with torch.no_grad():
            if self._hidden is None:
                self._hidden = self.model.initial_state(batch_size=1)
                self._hidden = tuple(item.to(self.config.device) for item in self._hidden)
            det_actions, values, raw_mean, self._hidden = self.model(obs_tensor, self._hidden)
            action_tensor = det_actions.squeeze(0).squeeze(0)
            if not self.config.deterministic:
                std = torch.exp(self.model.log_std)
                raw_sample = raw_mean.squeeze(0).squeeze(0) + torch.randn_like(action_tensor) * std
                mid = (self.model.act_high + self.model.act_low) / 2.0
                amp = (self.model.act_high - self.model.act_low) / 2.0
                action_tensor = torch.tanh(raw_sample) * amp + mid
            logp = self.model.log_prob(raw_mean.squeeze(0), action_tensor.view(1, -1)).squeeze(0)
        action_vec = action_tensor.detach().cpu().numpy().astype(np.float32)
        weights = self._weights_from_action_vec(action_vec, symbols)
        if not weights:
            return self._hold_action(observation, reason="EMPTY_WEIGHTS")
        context = observation.get("context") if isinstance(observation, dict) else {}
        return {
            "contract_version": "act.v1",
            "action_type": "target_weight",
            "target": {
                "account_id": (context or {}).get("agent_id"),
                "symbols": symbols,
            },
            "payload": {
                "weights": weights,
                "cash_buffer_ratio": self.config.cash_buffer_ratio,
                "rebalance_mode": "market",
            },
            "constraints": {
                "allow_short": False,
                "max_gross_leverage": self.config.max_gross_leverage,
                "clip_to_limits": True,
            },
            "meta": {
                "model_id": self.model_id,
                "policy_type": "ppo_recurrent",
                "adapter_type": "torch_lstm",
                "old_logp": float(logp.item()),
                "value_estimate": float(values.squeeze().item()),
                "symbols": symbols,
                "obs_schema": "stock_sim.ppo_features.v1",
                "update_count": self._update_count,
                "last_loss": dict(self._last_loss),
            },
        }

    def learn(self, transition: dict[str, Any]) -> dict[str, Any]:
        row = self._transition_to_rollout_row(transition)
        if row is None:
            return {"ok": False, "reason": "INVALID_TRANSITION", "model_id": self.model_id}
        self._buffer.append(row)
        if len(self._buffer) < max(1, int(self.config.min_update_steps)):
            return {
                "ok": False,
                "reason": "BUFFER_NOT_READY",
                "buffer_size": len(self._buffer),
                "required": int(self.config.min_update_steps),
                "model_id": self.model_id,
            }
        result = self._update_from_buffer(self._buffer)
        self._buffer.clear()
        return result

    def save_checkpoint(self, path: str) -> dict[str, Any]:
        manifest_path = Path(path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path = manifest_path.with_suffix(".pt")
        torch.save(
            {
                "schema": "stock_sim.ppo_recurrent_checkpoint.v1",
                "model_id": self.model_id,
                "config": asdict(self.config),
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "update_count": self._update_count,
                "last_loss": self._last_loss,
            },
            weights_path,
        )
        manifest = {
            "schema": "stock_sim.ppo_recurrent_checkpoint_manifest.v1",
            "model_id": self.model_id,
            "weights_file": weights_path.name,
            "config": asdict(self.config),
            "update_count": self._update_count,
            "last_loss": dict(self._last_loss),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return {"ok": True, "path": str(manifest_path), "weights_path": str(weights_path), "update_count": self._update_count}

    def tensor_state(self) -> dict[str, np.ndarray]:
        return {name: tensor.detach().cpu().numpy() for name, tensor in self.model.state_dict().items()}

    def _transition_to_rollout_row(self, transition: dict[str, Any]) -> dict[str, Any] | None:
        observation = transition.get("observation")
        action = transition.get("action") or {}
        reward = transition.get("reward") or {}
        if not isinstance(observation, dict) or not isinstance(action, dict):
            return None
        obs_vec, symbols = self._featurize(observation)
        action_vec = np.zeros(self.config.max_symbols, dtype=np.float32)
        weights = ((action.get("payload") or {}).get("weights") or {})
        for idx, symbol in enumerate(symbols[: self.config.max_symbols]):
            action_vec[idx] = float(weights.get(symbol) or 0.0)
        old_logp = ((action.get("meta") or {}).get("old_logp"))
        return {
            "obs_vec": obs_vec,
            "action_vec": action_vec,
            "old_logp": float(old_logp if old_logp is not None else 0.0),
            "reward": float(reward.get("step_reward") or 0.0),
        }

    def _update_from_buffer(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        obs = torch.tensor(
            np.stack([row["obs_vec"] for row in rows], axis=0),
            dtype=torch.float32,
            device=self.config.device,
        ).view(1, len(rows), -1)
        actions = torch.tensor(
            np.stack([row["action_vec"] for row in rows], axis=0),
            dtype=torch.float32,
            device=self.config.device,
        )
        old_logp = torch.tensor([row["old_logp"] for row in rows], dtype=torch.float32, device=self.config.device)
        returns = torch.tensor(
            _discounted_returns([row["reward"] for row in rows], self.config.gamma),
            dtype=torch.float32,
            device=self.config.device,
        )

        _det, values, raw_mean, _hidden = self.model(obs, None)
        values = values.squeeze(0)
        raw_mean = raw_mean.squeeze(0)
        new_logp = self.model.log_prob(raw_mean, actions)
        advantages = returns - values.detach()
        if advantages.numel() > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std(unbiased=False) + 1e-8)
        ratio = torch.exp(torch.clamp(new_logp - old_logp, -8.0, 8.0))
        unclipped = ratio * advantages
        clipped = torch.clamp(ratio, 1.0 - self.config.clip_ratio, 1.0 + self.config.clip_ratio) * advantages
        policy_loss = -torch.mean(torch.min(unclipped, clipped))
        value_loss = F.mse_loss(values, returns)
        std = torch.exp(self.model.log_std)
        entropy = (0.5 + 0.5 * math.log(2 * math.pi) + torch.log(std)).sum()
        loss = policy_loss + self.config.value_coef * value_loss - self.config.entropy_coef * entropy
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.grad_clip)
        self.optimizer.step()
        self._update_count += 1
        self._last_loss = {
            "policy_loss": float(policy_loss.detach().cpu().item()),
            "value_loss": float(value_loss.detach().cpu().item()),
            "entropy": float(entropy.detach().cpu().item()),
            "loss": float(loss.detach().cpu().item()),
        }
        return {
            "ok": True,
            "model_id": self.model_id,
            "update_count": self._update_count,
            "buffer_size": len(rows),
            **self._last_loss,
        }

    def _featurize(self, observation: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        market = observation.get("market") if isinstance(observation, dict) else {}
        account = observation.get("account") if isinstance(observation, dict) else {}
        symbols = [str(sym) for sym in ((context or {}).get("symbol_universe") or (market or {}).get("symbols") or [])]
        symbols = [sym for sym in symbols if sym][: self.config.max_symbols]
        features: list[float] = []
        bars_by_symbol = (market or {}).get("bars") or {}
        snapshots = (market or {}).get("snapshots") or {}
        for idx in range(self.config.max_symbols):
            symbol = symbols[idx] if idx < len(symbols) else None
            if symbol is None:
                features.extend([0.0] * self.config.per_symbol_feat)
                continue
            features.extend(_symbol_features(bars_by_symbol.get(symbol) or {}, snapshots.get(symbol) or {}))
        features.extend(_account_features(account or {}, context or {}, max_symbols=self.config.max_symbols))
        return np.asarray(features, dtype=np.float32), symbols

    def _weights_from_action_vec(self, action_vec: np.ndarray, symbols: list[str]) -> dict[str, float]:
        raw: dict[str, float] = {}
        for idx, symbol in enumerate(symbols[: self.config.max_symbols]):
            value = float(action_vec[idx])
            if not math.isfinite(value):
                value = 0.0
            value = max(0.0, value)
            if value > 1e-4:
                raw[symbol] = value
        gross = sum(abs(value) for value in raw.values())
        budget = max(0.0, min(self.config.max_gross_leverage, 1.0 - self.config.cash_buffer_ratio))
        if gross > budget and gross > 0:
            raw = {symbol: value * budget / gross for symbol, value in raw.items()}
        return {symbol: round(value, 6) for symbol, value in raw.items() if value > 1e-6}

    def _hold_action(self, observation: dict[str, Any], *, reason: str) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        return {
            "contract_version": "act.v1",
            "action_type": "hold",
            "target": {"account_id": (context or {}).get("agent_id")},
            "payload": {},
            "constraints": {},
            "meta": {"model_id": self.model_id, "policy_type": "ppo_recurrent", "reason": reason},
        }


def _coerce_config(value: RecurrentPPOPolicyConfig | dict[str, Any] | None) -> RecurrentPPOPolicyConfig:
    if isinstance(value, RecurrentPPOPolicyConfig):
        return value
    raw = dict(value or {})
    allowed = {field.name for field in RecurrentPPOPolicyConfig.__dataclass_fields__.values()}
    return RecurrentPPOPolicyConfig(**{key: raw[key] for key in raw.keys() & allowed})


def _symbol_features(bars: dict[str, Any], snapshot: dict[str, Any]) -> list[float]:
    day_bars = list((bars or {}).get("1d") or [])
    closes = []
    for item in day_bars[-8:]:
        try:
            closes.append(float(item.get("close") or item.get("last") or item.get("price") or 0.0))
        except Exception:
            closes.append(0.0)
    closes = [value for value in closes if value > 0]
    last = closes[-1] if closes else 0.0
    prev = closes[-2] if len(closes) >= 2 else last
    returns = [(closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-6) for i in range(1, len(closes))]
    mean_return = float(np.mean(returns)) if returns else 0.0
    vol = float(np.std(returns)) if returns else 0.0
    ret = 0.0 if prev <= 0 else (last - prev) / prev
    mean_price = float(np.mean(closes)) if closes else max(last, 1.0)
    price_z = 0.0 if mean_price <= 0 else (last / mean_price) - 1.0
    recent_trades = list((snapshot or {}).get("recent_trades") or [])
    trade_count = min(len(recent_trades), 10) / 10.0
    return [
        _clip(ret, -1.0, 1.0),
        _clip(mean_return, -1.0, 1.0),
        _clip(vol, 0.0, 1.0),
        _clip(price_z, -1.0, 1.0),
        trade_count,
        1.0,
    ]


def _account_features(account: dict[str, Any], context: dict[str, Any], *, max_symbols: int) -> list[float]:
    cash = float(account.get("cash") or 0.0)
    equity = float(account.get("equity") or cash or 1.0)
    gross = float(account.get("gross_exposure") or 0.0)
    positions = list(account.get("positions") or [])
    net = 0.0
    for pos in positions:
        qty = float(pos.get("quantity") or 0.0)
        price = float(pos.get("last_price") or pos.get("avg_price") or 0.0)
        net += qty * price
    return [
        _clip(cash / max(equity, 1.0), -5.0, 5.0),
        _clip(gross / max(equity, 1.0), 0.0, 5.0),
        _clip(net / max(equity, 1.0), -5.0, 5.0),
        min(len(positions), max_symbols) / max(max_symbols, 1),
        _clip(float(context.get("step_index") or 0) / 10_000.0, 0.0, 1.0),
        _clip(float(context.get("sim_day") or 0) / 10_000.0, 0.0, 1.0),
        1.0 if context.get("clock_running") else 0.0,
        1.0,
    ]


def _discounted_returns(rewards: list[float], gamma: float) -> list[float]:
    out = [0.0] * len(rewards)
    running = 0.0
    for idx in reversed(range(len(rewards))):
        running = float(rewards[idx]) + float(gamma) * running
        out[idx] = running
    return out


def _clip(value: float, low: float, high: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(low, min(high, float(value)))


__all__ = ["RecurrentPPOPolicyAdapter", "RecurrentPPOPolicyConfig"]
