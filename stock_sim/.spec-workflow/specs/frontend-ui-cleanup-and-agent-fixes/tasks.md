# Tasks: frontend-ui-cleanup-and-agent-fixes

Follow the tasks in order where dependencies exist. Mark status using [ ], [-], [x]. Each task includes an _Prompt to execute during Implementation phase.

- [x] T1 Remove Settings panel from registry and menu
  - Files: app/panels/__init__.py, app/ui/main_window.py, tests/test_panels_e2e_view_models.py
  - Description: Stop registering the Settings panel, remove it from placeholder names/menu, and update tests to not expect it.
  - _Requirements: FR1, NFR1, AC1
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: UI shell/registry engineer
    Task: Remove settings panel registration. In app/panels/__init__.py, delete 'settings' from _PLACEHOLDER_NAMES and remove the settings factory in register_ui_adapters(). Ensure MainWindow menus reflect list_panels() and no longer show settings. Adjust tests expecting settings in core panels.
    Restrictions: Do not break other panel registrations. Keep imports lazy. Preserve i18n meta keys for remaining panels.
    _Leverage: app/panels/__init__.py, app/ui/main_window.py, app/panels/registry.py
    Success: list_panels() no longer includes settings; menu has no Settings entry; tests updated.

- [x] T2 Default language to zh_CN and freeze language switching
  - Files: app/i18n/loader.py, tests/frontend/unit/test_i18n_loader.py, tests/frontend/unit/test_panel_i18n_titles.py
  - Description: Set default current language to zh_CN and use zh_CN as fallback where practical. Ensure set_language remains but is unused by Settings panel (since removed). Adapt tests to assert default zh_CN strings load and switching is optional.
  - _Requirements: FR2, NFR1, AC1
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: i18n engineer
    Task: In app/i18n/loader.py, change _current_language default to 'zh_CN'. Set _DEFAULT_FALLBACK to 'zh_CN'. Keep en_US as secondary fallback inside translate() if zh_CN missing keys. Update panel-title tests to assert zh_CN by default.
    Restrictions: Backward-compatible API names. Avoid breaking metrics.
    _Leverage: app/i18n/zh_CN.json, app/i18n/en_US.json, app/ui/i18n_bind.py
    Success: t('panel.market') returns Chinese by default; tests pass.

- [x] T3 Account panel: add dropdown to select agent/multi-retail accounts; wire to switch_account()
  - Files: app/ui/adapters/account_adapter.py, app/panels/account/panel.py (no change), app/panels/__init__.py (factory context if needed)
  - Description: Add a QComboBox at top of Account panel to list available accounts. Subscribe to agent batch/create/status events to populate list dynamically. On selection change, call bound logic.switch_account(selected_id) and refresh.
  - _Requirements: FR3, AC2
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: Qt adapter developer
    Task: Modify AccountPanelAdapter to render a QComboBox for account/agent selection. Populate from events 'agent.batch.create.completed' and 'agent-status-changed' if available; also allow manual entry via editable combo. On change, call bound logic.switch_account(account_id) and refresh table.
    Restrictions: Maintain headless fallback stubs. Do not introduce hard dependency on Agents panel instance.
    _Leverage: infra.event_bus, app.event_bridge.subscribe_topic, AccountPanel.switch_account
    Success: Dropdown appears; selecting an ID loads positions for that account.

- [x] T4 Orders per account: support filtering by account_id and show in Account panel
  - Files: app/panels/orders/panel.py, app/ui/adapters/orders_adapter.py, app/ui/adapters/account_adapter.py
  - Description: Extend OrdersPanel logic with set_account_filter(account_id) and normalize payloads to include account_id where present. Expose in OrdersPanelAdapter API, and embed a minimal orders table view under the Account panel filtered by selected account.
  - _Requirements: FR4, AC2
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: Event-driven UI engineer
    Task: In OrdersPanel, add account filter field and apply it in get_view. Update _normalize to extract 'account_id' from typical payload shapes (trade.order.account_id, order.account_id). In OrdersPanelAdapter, add set_account_filter(account_id). In AccountPanelAdapter, when account selection changes, set the orders adapter's account filter and render a compact orders table below positions.
    Restrictions: Keep existing filters (symbol/type) functional. Headless stubs must still work.
    _Leverage: app/ui/adapters/orders_adapter.py, infra.event_bus topics Trade/OrderRejected/OrderCanceled
    Success: Account panel shows only orders for the chosen account when events contain account_id.

- [x] T5 Agents Start should affect all selected agents
  - Files: app/ui/adapters/agents_adapter.py
  - Description: Update Start/Pause/Stop handlers to iterate over selected rows. If selection not available, fall back to starting all visible items.
  - _Requirements: FR5, AC3
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: Agents UI adapter developer
    Task: In AgentsPanelAdapter, modify _do_control('start'|'pause'|'stop') to collect selected agent_ids (via QTableWidget.selectionModel().selectedRows()) and call logic.control for each. If selection model is missing (headless), start all items from current view. Refresh view after actions.
    Restrictions: Avoid blocking UI; keep current threading model; no global state.
    _Leverage: existing table, _row_index, view['agents']['items']
    Success: After batch create, pressing Start starts all selected (not only the first).

- [x] T6 Market symbol double-click opens detail view reliably
  - Files: app/ui/adapters/market_adapter.py, app/panels/market/panel.py
  - Description: Ensure itemDoubleClicked handler calls select_symbol and refreshes detail view. Add defensive checks and a tiny smoke test hook.
  - _Requirements: FR7, AC5
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: Market panel engineer
    Task: Verify and harden _on_dbl in MarketPanelAdapter to always call _handle_select(symbol). Ensure MarketPanel.select_symbol loads symbol and detail_view reflects K-line and top-5 L2 via snapshot. Add a minimal unit test (if test infra present) to simulate dblclick handler call.
    Restrictions: Keep existing create-instrument dialog logic intact.
    _Leverage: app/panels/market/panel.py SymbolDetailPanel, MarketDataService.request_detail
    Success: Double-click reliably updates right-side detail.

- [x] T7 Remove placeholder SettingsSync language switching and set default on startup
  - Files: app/ui/settings_sync.py, app/ui/i18n_bind.py
  - Description: Ensure SettingsSync no longer attempts runtime language toggles; instead, on app startup call i18n loader to set zh_CN once. Keep theme synchronization intact.
  - _Requirements: FR2, NFR1
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: App bootstrap engineer
    Task: In SettingsSync, noop language-change paths or guard behind a feature flag defaulting to disabled. On initialization, set language to zh_CN via app.i18n.loader.set_language if not already. Ensure I18nManager still works for applying translations.
    Restrictions: Do not delete SettingsSync class; maintain tests that import it.
    _Leverage: app/i18n/loader.py, app/ui/i18n_bind.py
    Success: No language toggle side effects at runtime; default Chinese.

- [x] T8 Update panel lists/docs and fix tests
  - Files: docs/frontend_dev_guide.md, tests/test_panels_e2e_view_models.py, tests/frontend/unit/test_panel_i18n_titles.py
  - Description: Reflect removal of Settings panel in docs and tests. Ensure e2e view models test expected list excludes settings.
  - _Requirements: NFR1
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: Test/doc maintainer
    Task: Update tests that assert core panels list to remove 'settings'. Update docs to list account/market/agents/leaderboard/clock/orders.
    Restrictions: Keep test structure consistent; avoid brittle assertions.
    _Leverage: app/panels/__init__.py register_builtin_panels
    Success: Tests green.

- [x] T9 Quality gates and smoke tests
  - Files: N/A (scripts/test)
  - Description: Run unit tests and a small smoke run for panels. Verify no syntax/type errors.
  - _Requirements: NFR1, NFR3
  - _Prompt:
    Implement the task for spec frontend-ui-cleanup-and-agent-fixes, first run spec-workflow-guide to get the workflow guide then implement the task:
    Role: QA engineer
    Task: Run pytest -q. If failures relate to removed settings or i18n defaults, update expectations accordingly. Ensure market dblclick and agents batch start behaviors have coverage.
    Restrictions: Keep CI-friendly.
    _Leverage: pytest.ini
    Success: All tests pass; smoke scenario works.
