# python
"""VectorizedEnvWrapper (Req7)

最小实现: 将一组 gym-like 环境列表包装为类似单环境接口, 支持:
  - reset() -> np.ndarray(batch, obs_dim)
  - step(actions_batch) -> (obs_batch, reward_batch, done_batch, info_list)

简化: 不支持异步; 所有子环境同步前进一步。
"""
from __future__ import annotations
from typing import List, Any, Tuple
import numpy as np

class VectorizedEnvWrapper:
    def __init__(self, envs: List[Any]):
        assert len(envs) > 0, 'envs 不能为空'
        self.envs = envs
        self.n = len(envs)
        self._obs_shape = None

    def reset(self):
        obs_list = []
        for e in self.envs:
            o, _info = e.reset()
            obs_list.append(o)
        batch = np.stack(obs_list, axis=0)
        self._obs_shape = batch.shape[1:]
        return batch

    def step(self, actions: np.ndarray):
        assert actions.shape[0] == self.n, '批量 actions 第一维应等于环境数量'
        obs_next = []
        rewards = []
        dones = []
        infos = []
        for i, e in enumerate(self.envs):
            o,r,d,t,info = e.step(actions[i])
            if d or t:
                o2,_ = e.reset(); o=o2
            obs_next.append(o)
            rewards.append(r)
            dones.append(d or t)
            infos.append(info)
        return np.stack(obs_next, axis=0), np.array(rewards, dtype=float), np.array(dones, dtype=bool), infos

__all__ = ["VectorizedEnvWrapper"]

