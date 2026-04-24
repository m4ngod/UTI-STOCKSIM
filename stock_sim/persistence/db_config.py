from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


SQLITE_FALLBACK_URL = "sqlite:///stock_sim_test.db"


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    dialect: str
    echo: bool
    engine_kwargs: dict[str, Any]


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def normalize_database_url(url: str) -> str:
    candidate = str(url or "").strip()
    if candidate.startswith("postgres://"):
        return "postgresql+psycopg://" + candidate[len("postgres://") :]
    if candidate.startswith("postgresql://"):
        return "postgresql+psycopg://" + candidate[len("postgresql://") :]
    return candidate


def database_dialect(url: str) -> str:
    normalized = normalize_database_url(url)
    scheme = normalized.split(":", 1)[0].split("+", 1)[0].lower()
    if scheme in {"postgres", "postgresql"}:
        return "postgresql"
    if scheme == "sqlite":
        return "sqlite"
    if scheme in {"mysql", "mariadb"}:
        return scheme
    return scheme or "unknown"


def resolve_database_url(default_url: str | None = None) -> str:
    raw = (
        os.environ.get("STOCKSIM_DB_URL")
        or os.environ.get("DB_URL")
        or default_url
        or SQLITE_FALLBACK_URL
    )
    return normalize_database_url(raw)


def build_database_config(*, default_url: str | None = None, default_echo: bool = False) -> DatabaseConfig:
    url = resolve_database_url(default_url)
    dialect = database_dialect(url)
    echo = env_bool("STOCKSIM_ECHO_SQL", env_bool("ECHO_SQL", default_echo))
    if dialect == "sqlite":
        kwargs: dict[str, Any] = {
            "echo": echo,
            "future": True,
            "connect_args": {
                "check_same_thread": False,
                "timeout": env_int("STOCKSIM_SQLITE_BUSY_TIMEOUT", 30),
            },
        }
    else:
        kwargs = {
            "echo": echo,
            "future": True,
            "pool_pre_ping": True,
            "pool_size": env_int("STOCKSIM_DB_POOL_SIZE", 10),
            "max_overflow": env_int("STOCKSIM_DB_MAX_OVERFLOW", 20),
            "pool_recycle": env_int("STOCKSIM_DB_POOL_RECYCLE", 1800),
        }
    return DatabaseConfig(url=url, dialect=dialect, echo=echo, engine_kwargs=kwargs)


__all__ = [
    "DatabaseConfig",
    "SQLITE_FALLBACK_URL",
    "build_database_config",
    "database_dialect",
    "env_bool",
    "env_int",
    "normalize_database_url",
    "resolve_database_url",
]
