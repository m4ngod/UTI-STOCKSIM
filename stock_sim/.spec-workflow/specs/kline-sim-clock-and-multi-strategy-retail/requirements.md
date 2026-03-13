# Requirements: kline-sim-clock-and-multi-strategy-retail

## Summary
Implement daily K-line chart driven by the simulation clock, fix account dropdown to include newly created MultiStrategyRetail accounts, enforce MSR auto-naming (MSR0001, MSR0002, ...), update Agent creation flow to allow custom initial cash for MSR while requiring custom name for generic agents, and replace placeholders with concrete implementations where feasible.

## In-Scope
- K-line (candlestick) chart rendering in app UI driven by simulation clock for daily timeframe; color convention: red for bullish (close > open), green for bearish (close < open), neutral style for equal.
- Account panel dropdown population to include accounts generated when creating MultiStrategyRetail via batch create or single create flows.
- Naming rules: MultiStrategyRetail should auto-name using MSR#### sequentially; no user-provided prefix or name required in the modal.
- Agent creation modal UX: for MultiStrategyRetail, expose initial cash input (default 100,000) and hide name; for other agent types, require name input and default initial cash handling unchanged.
- Replace obvious placeholders (mock/temporary logic) for these features with real integrations present in the repository (e.g., sim clock time source, log/event bus, account store refresh).

## Out-of-Scope
- Non-daily K-line intervals (intra-day) and external market data sources.
- Full RPC/backend integration beyond existing local services.
- Historical backfill beyond what’s already available from data pipeline or snapshot services.

## Stakeholders
- Trading UI users viewing K-line charts
- Operators creating MultiStrategyRetail and other agents

## User Stories (EARS)
1. When the simulation clock advances a trading day, the K-line panel shall update to render the latest daily candle using red for up days and green for down days.
2. When a MultiStrategyRetail agent is created, then the system shall create a bound account and the account dropdown shall include it immediately without app restart.
3. When creating MultiStrategyRetail, then the modal shall not ask for a name/prefix and shall auto-name using MSR#### sequence; the displayed created agent/account name shall match.
4. When creating MultiStrategyRetail, then the modal shall allow specifying initial cash and pass it to backend; when creating a general agent type, then the modal shall require a custom name and not expose MSR-only options.
5. When placeholder implementations exist for the above features, they shall be replaced with actual services/modules in this codebase (e.g., sim clock provider, account store update, metrics/events) or otherwise clearly marked with TODO and minimal working code.

## Acceptance Criteria
- AC1: Daily K-line renders from simulation clock with correct color coding and updates on clock tick; verified with a smoke test advancing the clock.
- AC2: After creating an MSR agent, its account ID appears in the account dropdown within one UI refresh cycle; verified by a UI/state test or service-layer test.
- AC3: MSR naming auto-increments (MSR0001, MSR0002, ...) without requiring or accepting a name/prefix in the modal; attempt to enter name is disabled/ignored.
- AC4: MSR creation modal shows Initial Cash field and the backend receives that value; general agent creation shows Name field; both paths succeed and write initial logs.
- AC5: Removed/converted placeholders in the touched modules, including replacement of K-line placeholder with real drawing logic; documented TODOs where external integration is needed.

## Non-Functional
- Thread-safe state updates; no UI freezes.
- Minimal incremental changes; preserve existing public APIs unless required.
- Unit tests for service/state updates; integration tests for modal logic if present.

## Risks/Assumptions
- Assumes sim clock and account store/event bus already exist (observed event_bus, metrics, etc.).
- Some UI code may be placeholder; will adapt to existing framework in app/ui and app/panels.
- If account list uses a cache, ensure invalidation via events or explicit reload.

