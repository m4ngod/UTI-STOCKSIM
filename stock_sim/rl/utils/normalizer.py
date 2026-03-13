# python
"""Running mean/std normalizer for observations & rewards (M1)."""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass

@dataclass
class RunningMeanStd:
    shape: tuple
    epsilon: float = 1e-8

    def __post_init__(self):
        self.count = 0.0
        self.mean = np.zeros(self.shape, dtype=np.float64)
        self.var = np.ones(self.shape, dtype=np.float64)

    def update(self, x: np.ndarray):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim == len(self.shape):
            x = x.reshape((1,) + self.shape)
        batch_mean = x.mean(axis=0)
        batch_var = x.var(axis=0)
        batch_count = x.shape[0]
        self._update_from_moments(batch_mean, batch_var, batch_count)

    def _update_from_moments(self, batch_mean, batch_var, batch_count):
        if batch_count == 0:
            return
        delta = batch_mean - self.mean
        tot_count = self.count + batch_count
        new_mean = self.mean + delta * batch_count / tot_count if tot_count > 0 else batch_mean
        m_a = self.var * self.count
        m_b = batch_var * batch_count
        M2 = m_a + m_b + delta**2 * self.count * batch_count / tot_count
        new_var = M2 / tot_count
        self.mean = new_mean
        self.var = new_var
        self.count = tot_count

    def normalize(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / (np.sqrt(self.var) + self.epsilon)

__all__ = ["RunningMeanStd"]

