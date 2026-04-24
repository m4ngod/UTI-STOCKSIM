from __future__ import annotations

from stock_sim.persistence.db_config import (
    POSTGRES_DEFAULT_URL,
    SQLITE_FALLBACK_URL,
    build_database_config,
    database_dialect,
    normalize_database_url,
    resolve_database_url,
)


def test_resolve_database_url_uses_postgres_default(monkeypatch):
    monkeypatch.delenv("STOCKSIM_DB_URL", raising=False)
    monkeypatch.delenv("DB_URL", raising=False)

    assert resolve_database_url() == POSTGRES_DEFAULT_URL


def test_stocksim_db_url_overrides_legacy_db_url(monkeypatch):
    monkeypatch.setenv("DB_URL", "sqlite:///legacy.db")
    monkeypatch.setenv("STOCKSIM_DB_URL", "postgresql://u:p@localhost:5432/stock_sim")

    assert resolve_database_url() == "postgresql+psycopg://u:p@localhost:5432/stock_sim"


def test_postgres_url_normalization_and_dialect():
    assert normalize_database_url("postgres://u:p@localhost/db") == "postgresql+psycopg://u:p@localhost/db"
    assert normalize_database_url("postgresql://u:p@localhost/db") == "postgresql+psycopg://u:p@localhost/db"
    assert normalize_database_url("postgresql+psycopg2://u:p@localhost/db") == "postgresql+psycopg2://u:p@localhost/db"
    assert database_dialect("postgresql+psycopg://u:p@localhost/db") == "postgresql"


def test_database_config_builds_postgres_pool_options(monkeypatch):
    monkeypatch.setenv("STOCKSIM_DB_URL", "postgresql://u:p@localhost:5432/stock_sim")
    monkeypatch.setenv("STOCKSIM_DB_POOL_SIZE", "7")
    monkeypatch.setenv("STOCKSIM_DB_MAX_OVERFLOW", "11")

    cfg = build_database_config()

    assert cfg.dialect == "postgresql"
    assert cfg.url == "postgresql+psycopg://u:p@localhost:5432/stock_sim"
    assert cfg.engine_kwargs["pool_pre_ping"] is True
    assert cfg.engine_kwargs["pool_size"] == 7
    assert cfg.engine_kwargs["max_overflow"] == 11


def test_database_config_builds_sqlite_connect_args(monkeypatch):
    monkeypatch.setenv("STOCKSIM_DB_URL", SQLITE_FALLBACK_URL)
    monkeypatch.delenv("DB_URL", raising=False)

    cfg = build_database_config()

    assert cfg.dialect == "sqlite"
    assert cfg.engine_kwargs["connect_args"]["check_same_thread"] is False


def test_settings_build_db_url_reads_environment_at_call_time(monkeypatch):
    from stock_sim.settings import settings

    monkeypatch.setenv("STOCKSIM_DB_URL", "postgresql://u:p@localhost:5432/stock_sim")

    assert settings.build_db_url() == "postgresql+psycopg://u:p@localhost:5432/stock_sim"


def test_settings_build_db_url_defaults_to_postgres(monkeypatch):
    from stock_sim.settings import settings

    monkeypatch.delenv("STOCKSIM_DB_URL", raising=False)
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setattr(settings, "DB_URL", None)

    assert settings.build_db_url() == POSTGRES_DEFAULT_URL
