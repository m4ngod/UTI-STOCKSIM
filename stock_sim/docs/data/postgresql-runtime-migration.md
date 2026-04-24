# PostgreSQL runtime persistence migration

_Last updated: 2026-04-25_

## Status

This document tracks the concrete persistence upgrade described in:

- `docs/data/data-layering-design.md`
- `docs/data/data-layering-table-plan.md`
- `docs/data/run-id-wiring-plan.md`

PostgreSQL is now the default runtime backend for the desktop app and ORM persistence path.
SQLite remains an explicit dev/test compatibility backend only.

## What changed

### Database configuration

Runtime database selection now follows this priority:

1. `STOCKSIM_DB_URL`
2. `DB_URL`
3. built-in PostgreSQL default: `postgresql+psycopg://stock_sim:stock_sim@127.0.0.1:5432/stock_sim`

Recommended PostgreSQL URL:

```powershell
$env:STOCKSIM_DB_URL = "postgresql+psycopg://stock_sim:stock_sim@127.0.0.1:5432/stock_sim"
```

SQLite is still available for tests or local diagnostics by setting:

```powershell
$env:STOCKSIM_DB_URL = "sqlite:///stock_sim_test.db"
```

Compatibility shortcuts are normalized:

- `postgres://...` -> `postgresql+psycopg://...`
- `postgresql://...` -> `postgresql+psycopg://...`

### Engine behavior

SQLite keeps local-development settings:

- WAL mode
- `check_same_thread = False`
- busy timeout

PostgreSQL uses pooled SQLAlchemy connections:

- `pool_pre_ping = True`
- `STOCKSIM_DB_POOL_SIZE`, default `10`
- `STOCKSIM_DB_MAX_OVERFLOW`, default `20`
- `STOCKSIM_DB_POOL_RECYCLE`, default `1800`

### Schema compatibility

The startup schema guard now uses one-column-at-a-time `ALTER TABLE` statements so the same path works for SQLite and PostgreSQL.

It also ensures the run-scoped columns and indexes required by the current design:

- `orders.run_id`
- `trades.run_id`
- `ledgers.run_id`
- `order_events.run_id`
- `event_log.run_id`
- `snapshots_1s.run_id`
- `bars_1m.run_id`
- `bars_1h.run_id`
- `bars_1d.run_id`
- `agent_bindings.run_id`
- `account_equity_snapshots.run_id`

Generated bar tables now treat `run_id` as part of simulation bar identity:

- legacy global unique `(symbol, ts)` bar indexes are downgraded to non-unique lookup indexes when detected
- run-aware unique indexes are created as `(run_id, symbol, ts)`
- `BarAggregator` upserts bars by `(run_id, symbol, ts)` so multiple simulation runs can produce bars for the same symbol/time window

The legacy `TransactionLogger` compatibility surface no longer writes a private `trade_log.db` SQLite file.
It now writes through `SessionLocal` into the authoritative ORM tables:

- trades go to `trades`
- order changes go to `order_events`

### Database health check

Desktop startup now performs a database health check before opening the GUI by default.
If PostgreSQL is configured but unavailable, startup returns a non-zero code instead of continuing into a partially initialized UI.

Manual checks:

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --check-db
..\Quent\.venv\Scripts\python.exe -m stock_sim.persistence.db_health
```

Installed script:

```powershell
stock-sim-db-health
```

Startup control:

- `--skip-db-check` skips the startup check for emergency diagnostics.
- `--require-postgres` fails unless the configured database dialect is PostgreSQL.
- `STOCKSIM_DB_CHECK_ON_START=0` disables automatic startup checks.
- `STOCKSIM_DB_CHECK_ON_START=1` forces checks even in headless mode.
- `STOCKSIM_REQUIRE_POSTGRES=1` enforces PostgreSQL for formal runtime profiles.

## Current boundary

This iteration makes the desktop startup path and ORM persistence path PostgreSQL-first, but it does not yet:

- move latest market state to Redis
- add Alembic-managed production migrations
- migrate existing SQLite data into PostgreSQL

Those are separate follow-up slices.

## Suggested local PostgreSQL smoke

1. Create a database/user in PostgreSQL matching the default URL, or set `STOCKSIM_DB_URL` to your own PostgreSQL database.
2. Start the desktop app or run:

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --check-db
```

4. Start a run with 100+ retail agents and verify:

- agent start does not freeze the UI
- orders/trades/ledgers write without SQLite lock stalls
- Market detail K-line can recover from persisted bars or runtime trade-log fallback

## Next migration slices

1. Introduce Alembic migrations for PostgreSQL and stop relying on startup `ALTER TABLE` for production mode.
2. Move latest snapshot/order-book/leaderboard hot state to Redis or an in-memory service boundary with Redis-compatible interface.
3. Add SQLite-to-PostgreSQL export/import tooling for existing local experiments.
