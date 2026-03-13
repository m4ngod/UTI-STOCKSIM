# Design: kline-sim-clock-and-multi-strategy-retail

## Overview
Implement a daily K-line (candlestick) chart driven by the simulation clock, fix the account dropdown to immediately include newly created MultiStrategyRetail (MSR) accounts, enforce MSR auto-naming without prefix input, and allow initial cash input for MSR creation in the agent creation modal. Replace placeholders with concrete implementations by wiring event bus notifications and adapters.

## Goals
- Daily K-line chart renders with red/green bodies and updates on sim clock events.
- Account dropdown reflects newly created MSR accounts without restart.
- MSR creation flow: auto-naming (MSR####), hide name/prefix in modal, allow initial cash input and propagate to backend.
- Replace/augment placeholders with concrete event-driven code while keeping headless compatibility.

## Non-Goals
- Intra-day intervals and external market data integrations.
- Persisting account lists or global AppState orchestration beyond lightweight event publishing.

## Architecture Changes
- Event flow additions
  - Publish clock events from ClockService:
    - clock.state on start/pause/resume/stop or sim_day switch
    - clock.tick on tick()
  - Market UI subscription:
    - MarketPanelAdapter subscribes to clock.tick/state to trigger detail refresh when timeframe is "1d" and a symbol is selected.
  - Account UI subscription:
    - AccountPanelAdapter subscribes to account.created to add the new account ID to the dropdown immediately.
- UI adaptations
  - SymbolDetailAdapter._plot_candles renders red (close>open), green (close<open), gray (equal) bodies. Implement using pyqtgraph BarGraphItem split into up/down groups when available; fallback label remains for headless.
  - SymbolDetailPanel default timeframe switched to "1d".
  - AgentCreationModal hides name/prefix for MSR, adds Initial Cash input with default 100,000; passes initial_cash through AgentsPanel.start_batch_create -> AgentService.BatchCreateConfig.
- Service layer
  - AgentService already auto-names MSR#### and publishes account.created with initial_cash; no backend change needed besides ensuring initial_cash flows from UI.

## Data Flow
- Clock
  - User or system advances clock via ClockPanel/controller -> ClockService.
  - ClockService publishes clock.state/clock.tick events with payload {status, sim_day, speed, ts}.
  - MarketPanelAdapter receives event; if current detail timeframe == "1d", calls MarketPanel.detail_view() and applies to SymbolDetailAdapter.
- Account
  - AgentService.batch_create_retail publishes account.created {account_id, initial_cash} when type==MSR.
  - AccountPanelAdapter listens and adds account_id to the QComboBox if not present.
- Agents
  - AgentCreationModal collects inputs. For MSR, hides name/prefix, adds initial_cash. Submit calls AgentsPanel.start_batch_create(count, agent_type, name_prefix?, strategies?, initial_cash?).
  - AgentsPanel calls AgentService.batch_create_retail with BatchCreateConfig including initial_cash.

## Interfaces & Contracts
- Event payloads
  - clock.state: { status: "RUNNING|PAUSED|STOPPED", sim_day: str, speed: float, ts: int }
  - clock.tick: same structure as above
  - account.created (existing): { account_id: str, initial_cash: float }
- UI behavior
  - K-line body color: red if close > open; green if close < open; gray if equal
  - Default timeframe for SymbolDetailPanel: "1d"
  - Agent modal for MSR: show Initial Cash (float > 0), hide Name/Prefix
  - Agent modal for other types: show Name/Prefix, hide Initial Cash, require name/prefix

## File-level Changes
- app/services/clock_service.py
  - Add event_bus publish calls in start/pause/resume/stop/tick to broadcast clock.state and clock.tick.
- app/ui/adapters/market_adapter.py
  - SymbolDetailAdapter._plot_candles: implement red/green coloring, split BarGraphItems by up/down.
  - MarketPanelAdapter: subscribe to clock.state and clock.tick; on event, if a symbol is selected and detail timeframe == "1d", refresh detail.
- app/panels/market/panel.py
  - Set SymbolDetailPanel default timeframe to "1d" (_DEFAULT_TIMEFRAME = "1d").
- app/ui/adapters/account_adapter.py
  - Subscribe to account.created and add new account_id to dropdown.
- app/ui/agent_creation_modal.py
  - Add initial_cash input to internal state for MSR; hide name_prefix for MSR; extend submit(...) to accept initial_cash and pass into AgentsPanel.start_batch_create.
- app/panels/agents/panel.py
  - Extend start_batch_create and _run_batch to accept and forward initial_cash to AgentService.BatchCreateConfig.

## Edge Cases
- pyqtgraph not available: use fallback label; color coding is no-op (shows count only) but still satisfies non-graph environments.
- clock events frequent: throttle handled implicitly by Adapter; refresh detail is light (request_detail uses cache).
- duplicate account.created: adapter checks existing combo items before adding.
- invalid initial_cash: default to 100000 if missing; optional validation (>= 0); do not block batch if omitted.
- switching symbol/timeframe: subscriptions remain; only refresh when current timeframe == "1d".

## Telemetry
- Add metrics counters for clock publishes (optional: reuse existing metrics in ClockService).
- Existing metrics in MarketPanel/Adapters preserved.

## Testing Strategy
- Unit
  - ClockService publishes events: subscribe to event_bus, call start/pause/resume/stop/tick, assert events received with fields.
  - AccountPanelAdapter reacts to account.created: simulate event, check combo updated (headless fallback behavior via stub QComboBox).
  - AgentsPanel passes initial_cash: call start_batch_create(..., initial_cash=200000) and assert AgentService publishes payload with initial_cash and created account IDs; validate no name/prefix for MSR.
  - SymbolDetailAdapter color logic: with simple series arrays, ensure separation of up/down bars (test via internal computed groups; if pyqtgraph absent, validate fallback updates the label to show count).
- Integration (lightweight)
  - Simulate selecting a symbol, set timeframe "1d", trigger clock.tick event, assert MarketPanelAdapter refreshes detail view at least once.

## Migration/Compatibility
- New event publishes in ClockService are additive; should not break existing tests.
- AgentsPanel/AgentCreationModal signatures extended; retain defaults for non-MSR types to avoid breaking existing callers.

## Rollback Plan
- If clock events cause issues, guard subscriptions behind try/except and feature-flag the publish; revert to previous non-event-driven refresh.

## Open Questions
- If a global AppState instance were available, we could also update it on clock changes; current design uses event_bus directly for simplicity.

