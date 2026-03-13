# Tasks: kline-sim-clock-and-multi-strategy-retail

- [x] Task 1: Publish clock events in ClockService
  - Files: app/services/clock_service.py
  - Description: Publish `clock.state` on start/pause/resume/stop and `clock.tick` on tick(). Payload: {status, sim_day, speed, ts}. Use infra.event_bus. Keep existing metrics.
  - _Requirements: AC1, AC5
  - Success criteria:
    - Emitting `clock.state` after each state mutation and `clock.tick` on tick().
    - No API changes; no exceptions leak; existing tests remain green.
  - Instructions:
    - Before starting: mark this task as in-progress by changing `[ ]` to `[-]`.
    - After finishing and tests pass: change `[-]` to `[x]`.
  - _Prompt:
    Implement the task for spec kline-sim-clock-and-multi-strategy-retail, first run spec-workflow-guide to get the workflow guide then implement the task:
    - Role: Backend Python developer
    - Task: In `app/services/clock_service.py`, import event_bus and publish `clock.state` after state changes in start/pause/resume/stop, and publish `clock.tick` in tick(). Do not change public API. Ensure no exceptions bubble; guard publishes.
    - Restrictions: Keep thread-safety and metrics; no breaking changes to DTOs or signatures.
    - _Leverage: infra.event_bus.event_bus; app.core_dto.clock.ClockStateDTO
    - Success: New events are emitted with correct payload and no test regressions. Update tasks.md markers accordingly.

- [x] Task 2: Default daily timeframe and K-line coloring
  - Files: app/panels/market/panel.py, app/ui/adapters/market_adapter.py
  - Description: Change SymbolDetailPanel default timeframe to "1d". In SymbolDetailAdapter._plot_candles, render candlestick bodies colored red if close>open, green if close<open, gray if equal. Use separate BarGraphItems for up/down/eq; keep wicks.
  - _Requirements: AC1, AC5
  - Success criteria:
    - `_DEFAULT_TIMEFRAME` set to "1d".
    - Bodies colored correctly when pyqtgraph is available; fallback label still shows bar count.
  - Instructions:
    - Mark task as in-progress `[-]` before coding; mark as complete `[x]` after verifying.
  - _Prompt:
    Implement the task for spec kline-sim-clock-and-multi-strategy-retail, first run spec-workflow-guide to get the workflow guide then implement the task:
    - Role: UI Python developer with pyqtgraph experience
    - Task: Update `_DEFAULT_TIMEFRAME` to "1d". Update `_plot_candles` to draw up/down/eq bodies with appropriate colors; keep wicks; be robust when pg unavailable.
    - Restrictions: Preserve current API and fallback behavior. Avoid heavy dependencies.
    - _Leverage: pyqtgraph.BarGraphItem, ErrorBarItem; existing adapter structure.
    - Success: Bodies colored correctly; no crash without pyqtgraph. Update tasks.md markers accordingly.

- [ ] Task 3: MarketPanelAdapter refresh on clock events for daily timeframe
  - Files: app/ui/adapters/market_adapter.py
  - Description: Subscribe to `clock.state` and `clock.tick`. On event, if a symbol is selected and current detail timeframe is "1d", call `_refresh_detail()`.
  - _Requirements: AC1
  - Success criteria:
    - Subscriptions established and canceled in destructor; handler refreshes detail only for timeframe "1d".
  - Instructions:
    - Mark task as in-progress `[-]` before coding; mark as complete `[x]` after verifying.
  - _Prompt:
    Implement the task for spec kline-sim-clock-and-multi-strategy-retail, first run spec-workflow-guide to get the workflow guide then implement the task:
    - Role: UI adapter developer
    - Task: Add subscriptions and a handler that fetches `logic.detail_view()` to inspect timeframe, and refreshes detail only when timeframe=="1d".
    - Restrictions: Use existing subscribe_topic helper; guard errors; avoid excessive refresh (低影响)。
    - _Leverage: app.event_bridge.subscribe_topic; current adapter pattern for trades/batch。
    - Success: Detail refreshes on clock events for daily timeframe. Update tasks.md markers accordingly.

- [ ] Task 4: Account dropdown listens to account.created
  - Files: app/ui/adapters/account_adapter.py
  - Description: Subscribe to `account.created` and add new account_id to QComboBox if not present. Keep existing batch completion wiring.
  - _Requirements: AC2
  - Success criteria:
    - Newly published `account.created` events cause the account ID to appear in the dropdown without restart.
  - Instructions:
    - Mark task as in-progress `[-]` before coding; mark as complete `[x]` after verifying.
  - _Prompt:
    Implement the task for spec kline-sim-clock-and-multi-strategy-retail, first run spec-workflow-guide to get the workflow guide then implement the task:
    - Role: UI adapter developer
    - Task: Subscribe to `account.created` and update the account combo list accordingly; ensure unsubscribe on destruction.
    - Restrictions: Headless fallback must not crash; check attributes.
    - _Leverage: infra.event_bus via subscribe_topic helper used in this file.
    - Success: New MSR accounts appear immediately in the dropdown. Update tasks.md markers accordingly。

- [ ] Task 5: Agent creation modal supports initial cash for MSR and hides name/prefix
  - Files: app/ui/agent_creation_modal.py, app/panels/agents/panel.py, app/ui/adapters/agents_adapter.py
  - Description: For MultiStrategyRetail: hide name/prefix in modal; add `initial_cash` input (default 100000) and pass it through AgentsPanel.start_batch_create to AgentService.BatchCreateConfig. For other types: keep name/prefix and do not ask for initial_cash.
  - _Requirements: AC3, AC4
  - Success criteria:
    - MSR path: name/prefix inputs hidden/ignored; initial_cash captured and passed; service receives and emits in events。
    - Other types: no change in behavior; require name/prefix; no initial_cash field shown。
  - Instructions:
    - Mark task as in-progress `[-]` before coding; mark as complete `[x]` after verifying。
  - _Prompt:
    Implement the task for spec kline-sim-clock-and-multi-strategy-retail, first run spec-workflow-guide to get the workflow guide then implement the task:
    - Role: Full-stack Python developer (UI adapters + panel logic)
    - Task: Extend AgentCreationModal to track `initial_cash` and accept it in `submit()`. In AgentsPanel, add optional `initial_cash` param to `start_batch_create` and forward it to AgentService.BatchCreateConfig. Update AgentsPanelAdapter batch dialog to show an Initial Cash field only when type is MultiStrategyRetail and hide/disable Name Prefix in that mode; pass values into modal.submit。
    - Restrictions: Backward compatible defaults; headless fallback must still work。
    - _Leverage: app/services/agent_service.BatchCreateConfig; event topics already emitted by service。
    - Success: Creating MSR uses MSR#### names, allows custom initial cash, and account appears in dropdown (Task 4). Update tasks.md markers accordingly。

- [ ] Task 6: Lightweight tests and run suite
  - Files: tests/test_kline_and_account_events.py (new), reuse existing tests
  - Description: Add minimal tests to validate: (a) ClockService emits events; (b) AccountPanelAdapter processes account.created in headless mode; (c) AgentsPanel passes initial_cash to AgentService and service emits payload with initial_cash. Run pytest and ensure all pass。
  - _Requirements: AC1, AC2, AC4, Non-Functional
  - Success criteria:
    - New tests pass, existing suite remains green; no UI dependency required. (Note: Ran focused tests successfully; unrelated legacy tests currently fail due于 pre-existing import/layout issues; see report.)
  - Instructions:
    - Mark task as in-progress `[-]` before coding; mark as complete `[x]` after verifying。
  - _Prompt:
    Implement the task for spec kline-sim-clock-and-multi-strategy-retail, first run spec-workflow-guide to get the workflow guide then implement the task:
    - Role: Test-focused Python developer
    - Task: Write small tests to cover event publication and UI adapter reactions in headless mode. Then run `pytest`。
    - Restrictions: Keep tests fast and isolated; avoid requiring Qt。
    - _Leverage: infra.event_bus; existing adapters’ headless stubs。
    - Success: New tests pass, existing suite remains green. Update tasks.md markers accordingly。
