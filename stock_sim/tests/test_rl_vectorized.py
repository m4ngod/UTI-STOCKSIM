import numpy as np
from stock_sim.rl.vectorized_env import VectorizedEnvWrapper

class DummyEnv:
    def __init__(self, obs_dim=3):
        self.obs_dim = obs_dim
        self._step_count = 0
    def reset(self):
        self._step_count = 0
        return np.zeros(self.obs_dim, dtype=float), {}
    def step(self, action):
        self._step_count += 1
        obs = np.ones(self.obs_dim, dtype=float) * self._step_count
        reward = float(action) * 0.1
        done = self._step_count >= 2
        terminated = False
        info = {'a': action}
        return obs, reward, done, terminated, info

def test_vectorized_env_basic():
    envs = [DummyEnv(), DummyEnv()]
    vec = VectorizedEnvWrapper(envs)
    obs0 = vec.reset()
    assert obs0.shape == (2, 3)
    actions = np.array([1, 2])
    obs, rew, done, infos = vec.step(actions)
    assert obs.shape == (2,3)
    assert rew.tolist() == [0.1, 0.2]
    assert done.dtype == bool
    # 第二次 step 触发 done -> 自动 reset -> 观测重新从 0 或 1 起
    obs2, rew2, done2, _ = vec.step(actions)
    assert obs2.shape == (2,3)

