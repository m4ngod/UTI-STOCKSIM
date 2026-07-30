# Issue #48 certified-history overlap resolution ledger

This ledger records the semantic resolution of every file changed by both
certified histories:

- merge base: `258ac7b95e22eb565cd53ef3214193391d3cc3d7`
- Frontend V2 candidate: `cb20b8452c960dca6e7de0a07d3895d0da4dd9bb`
- certified Frontend V2 source:
  `d4ec8d426b06b64b527eea8ae2861a254f8cde29`
- Strategy Diagnostics V1 delivery:
  `c60e3502f0e8fd5430084e9d539ea4101d2552d2`
- common-file calculation: intersection of each delivery's `git diff
  --name-only` from the merge base; exactly 32 files

The merge produced 18 Git conflicts. Fourteen additional common files merged
automatically but were still audited below. The final choices are 15
Frontend-authoritative/equivalent results, 15 V1-authoritative/equivalent
results, and 2 additive resolutions. Symbol-set comparison found no public
class or function present on either side but absent from the resolved files.

This is merge-risk isolation evidence only. It does not implement Issue #49,
change either Feature Interface version, connect V1 Run or Evidence data to
QML, or claim a new release certification.

## Resolution entries

| # | Common file | Frontend V2 behavior retained | Strategy Diagnostics V1 behavior retained | Final decision and reason | Regression evidence |
| ---: | --- | --- | --- | --- | --- |
| 1 | `stock_sim/app/core_dto/_compat.py` | Pydantic v1/v2 detection and a `model_dump()` fallback remain available to every Frontend DTO. | V1's typed `Any`/`cast` annotations preserve the same runtime behavior while satisfying strict DTO typing. | V1-equivalent file. It contains every Frontend symbol and only tightens typing; no DTO contract changes. | `tests/frontend/unit/test_dto.py`; all Feature contract tests; `tests/strategy_diagnostics/test_installation.py`. |
| 2 | `stock_sim/app/core_dto/account.py` | `PositionDTO` and `AccountDTO` validation, optional P&L fields, utilization bounds, and serialized account snapshot shape remain unchanged. | V1 used the same DTO contract. | Frontend-equivalent file; the V1 public symbols and validation behavior are identical. | `tests/frontend/unit/test_dto.py`; `test_account_contract.py`; Frontend integration suite. |
| 3 | `stock_sim/app/core_dto/agent.py` | The expanded model metadata (`strategy`, `model_id`, `mode`, `episode_id`, reward/equity/P&L/action) remains available to the certified frontend. | V1's base agent identity, lifecycle status, heartbeat, and parameter-version fields remain a subset of the resolved model. | Frontend-authoritative superset; retaining the extra typed fields does not alter V1 diagnostics semantics. | `test_dto.py`; agent unit/integration tests; packaging contract. |
| 4 | `stock_sim/app/core_dto/clock.py` | Typed clock lifecycle, Simulation Day string, speed, and timestamp remain unchanged. | V1 used the same clock DTO behavior. | Frontend-equivalent file. | `test_dto.py`; clock panel/service tests; integration/E2E. |
| 5 | `stock_sim/app/core_dto/snapshot.py` | Typed immutable snapshot levels, volume, turnover, timestamp, and snapshot identity remain unchanged. | V1 used the same snapshot DTO surface. | Frontend-equivalent file. | `test_dto.py`; market snapshot/adapter tests; performance contract. |
| 6 | `stock_sim/app/core_dto/trade.py` | Read-only typed trade context with nonnegative price, positive quantity, side, and timestamp remains available. | V1 used the same trade DTO and adds no manual-trading action. | Frontend-equivalent file. | `test_dto.py`; live journey integration; no-manual-trading safety gates. |
| 7 | `stock_sim/app/core_dto/versioning.py` | Agent parameter revision identity, author, diff, and rollback linkage remain unchanged. | V1 used the same version DTO behavior. | Frontend-equivalent file. | `test_dto.py`; settings/version-store unit tests. |
| 8 | `stock_sim/app/i18n/en_US.json` | All certified panel labels, including Arena, Agent Config, and Agent Creation, remain available. | V1's Diagnostics and shared panel labels remain present with the same keys. | Frontend-authoritative superset; no V1 translation key was removed. | `test_i18n_loader.py`; `test_panel_i18n_titles.py`; E2E i18n/accessibility. |
| 9 | `stock_sim/app/i18n/zh_CN.json` | The complete certified Chinese panel vocabulary remains available. | V1's `策略诊断` label and shared panel translations remain present. | Frontend-authoritative superset; no V1 translation key was removed. | `test_i18n_loader.py`; `test_panel_i18n_titles.py`; E2E i18n/accessibility. |
| 10 | `stock_sim/app/panels/__init__.py` | AppContext-backed Account/Market/Clock/Leaderboard/Arena/Agents factories, `read_only` Market wiring, placeholders, and rollback-safe behavior remain. | Diagnostics now accepts an injectable V1 Application factory/engine and initializes V1 persistence before constructing the legacy Diagnostics panel. | Additive manual resolution. V1 initialization occurs only outside Frontend rollback `read_only` mode, preserving query-only rollback safety. | `test_diagnostics_panel.py`; `test_panel_registry_main.py`; full safety and packaging-contract suites. |
| 11 | `stock_sim/app/panels/diagnostics/__init__.py` | The legacy Widgets rollback export of `DiagnosticsPanel` and its port remains. | V1 uses the same export surface. | Frontend-equivalent file. | Diagnostics panel unit suite; Widgets packaging contract. |
| 12 | `stock_sim/app/panels/diagnostics/panel.py` | Every early Frontend-side Diagnostics panel method and read model remains present. | The complete V1 guided recipe, materialization, Strategy Run, campaign, evidence, reproduction, and acceptance behavior is retained. | V1-authoritative strict evolution: 1,507 lines versus the Frontend branch's 76-line early implementation, with no Frontend-only symbol lost. | `test_diagnostics_panel.py`; all Strategy Diagnostics suites; packaging rollback tests. |
| 13 | `stock_sim/app/ui/adapters/base_adapter.py` | Lazy Qt creation, logic binding, refresh, view application, and headless fallback remain unchanged. | V1 used the same adapter base. | Frontend-equivalent file. | Frontend adapter/unit suites; integration/E2E. |
| 14 | `stock_sim/app/ui/adapters/diagnostics_adapter.py` | Every early Diagnostics adapter control and view binding remains present. | The complete V1 Widgets adapter for recipe, Run, campaign, evidence, reproduction, and acceptance workflows is retained. | V1-authoritative strict evolution: 2,707 lines versus 226, with no Frontend-only symbol lost. It remains legacy Widgets code and is not connected to the QML Journey. | `test_diagnostics_panel.py`; V1 acceptance tests; Widgets packaging contract. |
| 15 | `stock_sim/app/ui/main_window.py` | Frontend V2 Feature injection, QML Journey mounting, route gating, certified styling/accessibility, read-only rollback isolation, and legacy Widgets fallback remain exact. | The V1 legacy Diagnostics panel remains reachable through the retained panel registry/factory path. | Frontend-authoritative. The V1 side was an older pre-QML window; choosing it would remove the certified Journey. Diagnostics composition is preserved additively in `app/panels/__init__.py`. | `test_mainwindow_layout.py`; journey-route integration; accessible journey; safety; packaging contract; `test_desktop_diagnostics_composition_restores_approved_recipe`. |
| 16 | `stock_sim/pyproject.toml` | PostgreSQL drivers, DB-health entry point, release package data, QML package discovery, and Frontend dependencies remain. | `duckdb`, Strategy Diagnostics package discovery, and the `strategy-diagnostics` entry point remain. | Frontend-authoritative dependency superset; no V1 dependency or entry point is removed. | `test_installation.py`; complete packaging-contract suite; V1 import/subprocess tests. |
| 17 | `stock_sim/strategy_diagnostics/__init__.py` | All early public Strategy Diagnostics exports used by the Frontend branch remain. | The complete V1 public domain/application/recipe/run/campaign/evidence/reproduction surface is retained. | V1-authoritative strict evolution: 442 lines versus 72, with no Frontend-only exported symbol lost. | All 319 V1 tests; installation/architecture tests; Diagnostics panel unit tests. |
| 18 | `stock_sim/strategy_diagnostics/__main__.py` | The installed/headless CLI entry behavior remains unchanged. | V1 uses the same entry behavior. | Frontend-equivalent file. | `test_application.py`; `test_installation.py`; packaging contract. |
| 19 | `stock_sim/strategy_diagnostics/application.py` | Early `DiagnosticsApplication` status, persistence, segment, market-path, and preview behaviors remain. | The real V1 Application authority, including recipes, transformations, Strategy Runs, formal campaigns, sealed evidence, reproduction, and V1 acceptance, is retained. | V1-authoritative strict evolution: 1,960 lines versus 233, with no Frontend-only application symbol lost. No parallel façade or Issue #49 read model is introduced. | `test_application.py`; all V1 domain/acceptance suites; Diagnostics panel unit suite. |
| 20 | `stock_sim/strategy_diagnostics/baostock_source.py` | Historical source admission, deterministic normalization, point-in-time reads, and baseline materialization behavior remain. | V1 price-limit/session logic and the listing trading-day calculation remain. | V1-authoritative evolution; all Frontend-side symbols remain. | `test_baostock_historical_source.py`; `test_historical_segment_admission.py`; market-rule/materialization tests. |
| 21 | `stock_sim/strategy_diagnostics/historical_segments.py` | Segment catalog/admission, immutable snapshot identity, and point-in-time checks remain. | V1 reproduction's `get_source_snapshot` behavior is retained. | V1-authoritative evolution; all Frontend-side symbols remain. | Historical admission/source tests; reproduction manifest tests. |
| 22 | `stock_sim/strategy_diagnostics/market_paths.py` | Immutable Reference Market Path, deterministic reconstruction, causal Scenario Market View, and eligible-universe protections remain. | V1 registered transformations, price-limit references, artifact restart behavior, reconstruction notice, and statistics remain. | V1-authoritative evolution; all Frontend-side symbols remain. | `test_market_path_materialization.py`; market-rule, transformation, Strategy Run, and V1 acceptance tests. |
| 23 | `stock_sim/strategy_diagnostics/persistence.py` | Initial diagnostic schema, segment/source repositories, migrations, and status behavior remain. | The complete versioned V1 schema through reproduction manifests, strategy-run facts, recipes, campaigns, evidence, PTrade audit, and execution audit remains. | V1-authoritative evolution; all Frontend-side symbols remain. | `test_persistence_migrations.py`; recipe/campaign/evidence/reproduction tests; V1 acceptance. |
| 24 | `stock_sim/tests/conftest.py` | SQLite test isolation and the package-qualified model preload needed by the combined Frontend contract collection remain. | V1's lazy event-persistence shutdown avoids import-time database side effects. | Additive manual resolution. The preload canonicalizes the SQLAlchemy model graph only in tests, so production `import stock_sim` stays lazy while combined Feature contracts avoid duplicate table registration. | Complete V1 suite and all 124 Feature contract tests pass in the same integration tree. |
| 25 | `stock_sim/tests/frontend/unit/test_diagnostics_panel.py` | Every early Diagnostics panel/adapter assertion remains represented. | The complete V1 Widgets workflow coverage for recipes, paths, Runs, campaigns, evidence, reproduction, acceptance, and composition is retained. | V1-authoritative strict test evolution: all Frontend test function names remain and V1 adds full acceptance coverage. | File passes within the Frontend unit suite; V1 suite supplies matching headless/domain coverage. |
| 26 | `stock_sim/tests/strategy_diagnostics/test_application.py` | Early headless Application status/CLI contract remains. | V1's current Application version/status expectation is retained. | V1-authoritative one-line semantic update. | File passes within the 319-test V1 suite. |
| 27 | `stock_sim/tests/strategy_diagnostics/test_architecture.py` | Frontend-era architecture boundaries against Arena/training/Qt imports remain. | V1 uses the same architecture boundary contract. | Frontend-equivalent file. | File passes within the V1 suite. |
| 28 | `stock_sim/tests/strategy_diagnostics/test_baostock_historical_source.py` | All early BaoStock admission/materialization cases remain represented. | V1 adds recipe-approved and price-limit/session cases. | V1-authoritative strict test evolution with no Frontend-only test symbol lost. | File passes within the V1 suite. |
| 29 | `stock_sim/tests/strategy_diagnostics/test_historical_segment_admission.py` | Complete historical segment admission coverage remains. | V1 uses the same test contract. | Frontend-equivalent file. | File passes within the V1 suite. |
| 30 | `stock_sim/tests/strategy_diagnostics/test_installation.py` | Source checkout, installed package, headless entry, and subprocess import checks remain. | V1 adds lazy root-package persistence and the full evolved module import surface. | V1-authoritative strict test evolution with all Frontend test symbols retained. | File passes within the V1 suite; packaging contract also passes. |
| 31 | `stock_sim/tests/strategy_diagnostics/test_market_path_materialization.py` | Baseline reconstruction, deterministic identity, causal reads, and eligible-universe cases remain represented. | V1 adds registered transformation families, point-in-time price limits, recomputation, restart identity, and preview coverage. | V1-authoritative strict test evolution with no Frontend-only test symbol lost. | File passes within the V1 suite; performance contract covers immutable chart consumption. |
| 32 | `stock_sim/tests/strategy_diagnostics/test_persistence_migrations.py` | Initial schema and idempotent migration checks remain represented. | V1 adds every later schema revision and current migration-head assertions. | V1-authoritative strict test evolution with no Frontend-only test symbol lost. | File passes within the V1 suite; evidence/reproduction persistence tests also pass. |

## Gate mapping

- Backend V1 authority: `tests/strategy_diagnostics`.
- Frontend Feature contracts: `tests/frontend/contract`.
- QML Journey, E2E, and accessibility:
  `tests/frontend/integration` and `tests/frontend/e2e`.
- No-manual-trading safety: `tests/frontend/safety`.
- Performance contracts: `tests/frontend/performance`.
- Packaging and Widgets rollback contracts: `tests/frontend/packaging`.
- Overlap-focused frontend behavior: `tests/frontend/unit`.

Exact command results and the immutable integration commit are published as
Issue #48 acceptance evidence after the merge commit is created. The parent
Issue #47 remains open, and Issues #49-#53 are not implemented by this ledger.
