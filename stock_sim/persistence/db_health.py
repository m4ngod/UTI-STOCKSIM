from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import text


@dataclass(frozen=True)
class DatabaseHealth:
    ok: bool
    dialect: str
    url: str
    schema_checked: bool
    message: str
    error: str | None = None
    required_dialect: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dialect": self.dialect,
            "url": self.url,
            "schema_checked": self.schema_checked,
            "message": self.message,
            "error": self.error,
            "required_dialect": self.required_dialect,
        }


def safe_database_url(url: str) -> str:
    raw = str(url or "")
    if "://" not in raw:
        return raw
    scheme, rest = raw.split("://", 1)
    if "@" not in rest or ":" not in rest.split("@", 1)[0]:
        return raw
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def check_database_health(
    *,
    engine_obj: Any | None = None,
    ensure_schema: bool = False,
    ensure_models_fn: Callable[[], Any] | None = None,
    required_dialect: str | None = None,
) -> DatabaseHealth:
    if engine_obj is None:
        from stock_sim.persistence.models_imports import engine as engine_obj  # type: ignore

    dialect = str(getattr(getattr(engine_obj, "dialect", None), "name", "") or "unknown")
    url = safe_database_url(str(getattr(engine_obj, "url", "") or ""))
    required = str(required_dialect or "").strip().lower() or None
    if required and dialect.lower() != required:
        return DatabaseHealth(
            ok=False,
            dialect=dialect,
            url=url,
            schema_checked=False,
            message=f"database dialect mismatch; required {required}",
            required_dialect=required,
        )
    try:
        with engine_obj.connect() as conn:
            conn.execute(text("SELECT 1"))
        if ensure_schema:
            if ensure_models_fn is None:
                from stock_sim.persistence import models_init

                ensure_models_fn = models_init.ensure_models
            ensure_models_fn()
        return DatabaseHealth(
            ok=True,
            dialect=dialect,
            url=url,
            schema_checked=bool(ensure_schema),
            message="database reachable",
            required_dialect=required,
        )
    except Exception as exc:
        return DatabaseHealth(
            ok=False,
            dialect=dialect,
            url=url,
            schema_checked=False,
            message="database unavailable",
            error=f"{type(exc).__name__}: {exc}",
            required_dialect=required,
        )


def format_database_health(health: DatabaseHealth) -> str:
    status = "ok" if health.ok else "failed"
    parts = [
        f"status={status}",
        f"dialect={health.dialect}",
        f"url={health.url}",
        f"schema_checked={str(health.schema_checked).lower()}",
        f"message={health.message}",
    ]
    if health.required_dialect:
        parts.append(f"required_dialect={health.required_dialect}")
    if health.error:
        parts.append(f"error={health.error}")
    return " ".join(parts)


def main() -> int:
    health = check_database_health(ensure_schema=True)
    print(format_database_health(health))
    return 0 if health.ok else 3


__all__ = [
    "DatabaseHealth",
    "check_database_health",
    "format_database_health",
    "main",
    "safe_database_url",
]


if __name__ == "__main__":
    raise SystemExit(main())
