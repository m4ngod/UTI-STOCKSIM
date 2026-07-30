from __future__ import annotations

from services import redis_client


def _reset_client_state() -> None:
    redis_client._cached = None
    redis_client._last_fail_ts = None


def test_get_redis_disabled_returns_none(monkeypatch):
    _reset_client_state()
    monkeypatch.setattr(redis_client.settings, "REDIS_ENABLED", False, raising=False)

    assert redis_client.get_redis() is None


def test_get_redis_success_is_cached(monkeypatch):
    _reset_client_state()
    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def ping(self):
            return True

    client = FakeClient()

    class FakeRedis:
        class Redis:
            @staticmethod
            def from_url(url, **kwargs):
                calls.append((url, kwargs))
                return client

    monkeypatch.setattr(redis_client.settings, "REDIS_ENABLED", True, raising=False)
    monkeypatch.setattr(redis_client.settings, "REDIS_URL", "redis://unit-test:6379/7", raising=False)
    monkeypatch.setattr(redis_client.settings, "REDIS_CONN_TIMEOUT", 2.5, raising=False)
    monkeypatch.setattr(redis_client, "redis", FakeRedis)

    assert redis_client.get_redis() is client
    assert redis_client.get_redis() is client
    assert len(calls) == 1
    assert calls[0][0] == "redis://unit-test:6379/7"
    assert calls[0][1]["socket_timeout"] == 2.5


def test_get_redis_failure_returns_none_and_backs_off(monkeypatch):
    _reset_client_state()
    calls = 0

    class FakeRedis:
        class Redis:
            @staticmethod
            def from_url(url, **kwargs):
                nonlocal calls
                calls += 1
                raise RuntimeError("redis unavailable")

    monkeypatch.setattr(redis_client.settings, "REDIS_ENABLED", True, raising=False)
    monkeypatch.setattr(redis_client, "redis", FakeRedis)

    assert redis_client.get_redis() is None
    assert redis_client.get_redis() is None
    assert calls == 1
