# Requirements: Frontend UI Cleanup and Agent Fixes

Spec name: frontend-ui-cleanup-and-agent-fixes

## Summary
This spec defines requirements to: (1) remove the Settings panel and embedded functionality with safe defaults (Chinese as default language), (2) enhance the Account panel to support viewing orders per agent or multi-strategy retail account, (3) fix multi-strategy batch start behavior so all selected instances actually start, (4) replace placeholder UI/methods with working implementations, and (5) enable double-clicking a symbol in the Market panel to open a detail subpage with daily K-line and five-level order book.

## Goals and Non-Goals
- In-scope:
  - Remove Settings panel and language switching; set default language to zh_CN
  - Update entry flow and any code paths referencing the Settings panel
  - Account panel: add account/agent selector and show corresponding orders
  - Fix batch start for multi-strategy retail agents
  - Implement currently placeholder UI/methods within the affected areas
  - Market panel: double-click symbol navigates to detail view with K-line and L2 five-level quotes
- Out-of-scope:
  - Theme management beyond setting a static default (light) where required
  - New persistence schemas; reuse existing data models and repositories
  - Performance optimizations beyond correctness and reasonable responsiveness

## Stakeholders
- End users operating the trading UI
- Developers maintaining UI (app/*) and agents (agents/*)

## Assumptions
- The project uses an internal i18n system; with Settings removed, default language becomes zh_CN and remains fixed
- There is a central order repository or in-memory store that can query orders by account/agent
- The Market panel supports symbol item interactions and can host a detail view panel/subpage

## User Stories (EARS style)
1. When the frontend starts without a Settings panel, the system shall default the UI language to zh_CN and not expose language switching controls anywhere.
2. When the frontend starts, the system shall not attempt to open or reference the removed Settings panel.
3. When an operator opens the Account panel, the system shall present a dropdown enabling selection of each agent or multi-strategy retail account.
4. When an operator selects an account or agent in the Account panel dropdown, the system shall display that account’s orders (including status, side, symbol, price, quantity, timestamp).
5. When multiple multi-strategy retail agents are created and the operator presses Start (batch or per-item with a multi-select), the system shall start all targeted agents instead of only the first one.
6. When any placeholder UI or placeholder methods are encountered within the affected panels/services, the system shall replace them with complete implementations that satisfy the visible user flows.
7. When the operator double-clicks a symbol row/item in the Market panel, the system shall open a subpage or detail view displaying the symbol’s daily K-line and five-level order book.

## Functional Requirements
- FR1: Remove Settings panel module, routes, and menu entries; eliminate code paths that try to open it.
- FR2: Set default language to zh_CN at app initialization; ensure no runtime error if language switching is unavailable.
- FR3: Account panel shall contain a dropdown listing all agents and multi-strategy retail accounts, with stable identifiers.
- FR4: Account panel shall query and render orders filtered by the selected account/agent; supports pagination or lazy loading if necessary.
- FR5: Batch start operation for multi-strategy retail agents shall iterate over all targets and start each; UI state shall reflect running status per agent.
- FR6: Replace placeholder methods that currently return dummy data or pass, within panels and services affected by this spec, with working logic wired to existing repositories or engines.
- FR7: Market panel double-click shall navigate to a symbol detail subpage; detail subpage shall render daily K-line and five-level book using existing indicators/components if present, else minimal viable charts.

## Non-Functional Requirements
- NFR1: No regressions in existing panels (Account, Market, Agents) aside from removing Settings.
- NFR2: UI operations complete within 200ms for typical interactions on a commodity workstation.
- NFR3: Code changes covered by unit or integration tests where feasible (panel logic, agent start behavior).

## Dependencies
- app.ui/panels for Account and Market
- agents.multi_strategy_retail and related start/stop services
- core.order and order repositories or services in infra/services

## Acceptance Criteria
- AC1: Building and launching the frontend does not reference or try to open a Settings panel; no errors; UI language is Chinese by default.
- AC2: Account panel shows a dropdown listing agents and multi-strategy retail accounts; selecting one filters orders for that account; orders display correctly.
- AC3: Creating multiple multi-strategy retail agents and clicking Start results in all agents running (none left in STOPPED unless failure is surfaced with error message).
- AC4: No placeholder UI elements or placeholder business logic remain in the touched modules; tests confirm implemented behaviors.
- AC5: Double-clicking a symbol in the Market panel opens a detail subpage with daily K-line and five-level order book rendered.

## Risks and Mitigations
- R1: Removing Settings could break initialization: add safe defaults, guard against None, remove opening code paths.
- R2: Order querying may be slow: provide simple pagination or lazy loading if needed.
- R3: Missing K-line/L2 components: fall back to minimal charts using existing data sources.

## Open Questions
- OQ1: Should theme be permanently set to light or can a CLI flag override? (Default: light, allow CLI flag but no UI toggle.)
- OQ2: Exact order fields required in Account panel? (Default: id, status, side, symbol, price, quantity, timestamp.)

## Traceability Matrix
- RQ1 → FR1, FR2, AC1
- RQ2 → FR3, FR4, AC2
- RQ3 → FR5, AC3
- RQ4 → FR6, AC4
- RQ5 → FR7, AC5

