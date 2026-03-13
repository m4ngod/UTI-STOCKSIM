import time
import pytest

from app.services.leaderboard_service import LeaderboardService, LeaderboardServiceError
from observability.metrics import metrics

def test_invalid_window():
    svc = LeaderboardService()
    with pytest.raises(LeaderboardServiceError):
        svc.get_leaderboard("2d")

def test_limit_non_positive():
    svc = LeaderboardService()
    assert svc.get_leaderboard("1d", 0) == []
    assert svc.get_leaderboard("1d", -5) == []

def test_cache_hit_and_miss():
    svc = LeaderboardService(ttl_seconds=5.0)
    base_hit = metrics.counters.get("leaderboard_cache_hit", 0)
    base_miss = metrics.counters.get("leaderboard_cache_miss", 0)
    rows1 = svc.get_leaderboard("1d", 10)  # miss
    assert len(rows1) == 10
    rows2 = svc.get_leaderboard("1d", 10)  # hit
    assert len(rows2) == 10
    # 内容应相同 (缓存命中)
    assert [r.agent_id for r in rows1] == [r.agent_id for r in rows2]
    assert metrics.counters.get("leaderboard_cache_miss", 0) == base_miss + 1
    assert metrics.counters.get("leaderboard_cache_hit", 0) == base_hit + 1


def test_force_refresh_ignores_ttl():
    svc = LeaderboardService(ttl_seconds=30.0)  # 大 TTL
    rows1 = svc.get_leaderboard("7d", 5)
    ts1 = svc._cache["7d"][0]
    counter_before = svc._refresh_counter["7d"]
    rows2 = svc.get_leaderboard("7d", 5, force_refresh=True)
    ts2 = svc._cache["7d"][0]
    assert ts2 >= ts1
    assert svc._refresh_counter["7d"] == counter_before + 1
    # 由于重新构建, 序列可能不同
    assert len(rows2) == 5


def test_rank_delta_after_second_refresh():
    svc = LeaderboardService(ttl_seconds=0.0)  # 立即过期以便重建
    first = svc.get_leaderboard("30d", 20, force_refresh=True)
    assert all(r.rank_delta is None for r in first)
    second = svc.get_leaderboard("30d", 20, force_refresh=True)
    # 第二次应有 rank_delta (可能为0 或 正/负)
    deltas = [r.rank_delta for r in second]
    assert any(d is not None for d in deltas)
    # rank 值应为 1..20 且唯一
    ranks = [r.rank for r in second]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)

