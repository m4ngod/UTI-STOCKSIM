from __future__ import annotations

from stock_sim.persistence.db_health import check_database_health, format_database_health, safe_database_url


class _Dialect:
    name = "postgresql"


class _Url:
    def __str__(self):
        return "postgresql+psycopg://user:secret@localhost:5432/stock_sim"


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _stmt):
        return object()


class _Engine:
    dialect = _Dialect()
    url = _Url()

    def connect(self):
        return _Conn()


class _FailEngine(_Engine):
    def connect(self):
        raise RuntimeError("boom")


def test_safe_database_url_masks_password():
    assert (
        safe_database_url("postgresql+psycopg://user:secret@localhost:5432/stock_sim")
        == "postgresql+psycopg://user:***@localhost:5432/stock_sim"
    )


def test_check_database_health_success_runs_schema_callback():
    called = {}

    health = check_database_health(
        engine_obj=_Engine(),
        ensure_schema=True,
        ensure_models_fn=lambda: called.setdefault("schema", True),
    )

    assert health.ok is True
    assert health.dialect == "postgresql"
    assert health.schema_checked is True
    assert called == {"schema": True}
    assert "secret" not in health.url


def test_check_database_health_failure():
    health = check_database_health(engine_obj=_FailEngine(), ensure_schema=True)

    assert health.ok is False
    assert health.schema_checked is False
    assert "RuntimeError" in str(health.error)


def test_format_database_health_is_human_readable():
    health = check_database_health(engine_obj=_Engine())

    text = format_database_health(health)

    assert "status=ok" in text
    assert "dialect=postgresql" in text
