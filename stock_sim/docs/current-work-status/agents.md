# Agents / Retail Strategy Status

## Module

Retail strategy registry, retail population assignment, and agent-facing strategy visibility

## Current state

in-progress

## Task 2026-04-24-agents-06
- **time**: 2026-04-24
- **status**: done
- **goal**: run fixed-seed retail calibration episodes through the real runtime order path and emit JSON metrics
- **files involved**:
  - `scripts/run_retail_calibration_episode.py`
  - `docs/code-index.md`
- **total changed lines**: small executable diagnostics layer

### Change summary
- Added a fixed-seed episode runner for 6, 20, and 100 retail populations.
- The runner creates runtime instruments, bootstraps retail accounts, seeds initial inventory for sell-side participation, manually advances real `RuntimeRetailAgent` steps, and records submitted orders/trades/book samples into `RetailCalibrationReportCollector`.
- Output is written as JSON under `output/retail_calibration/episode_stats.json`.

### First run summary
- 6 retail / 40 steps:
  - buy/sell ratio: `0.5833` (`low`)
  - two-sided book coverage: `0.0` (`low`)
  - trade presence: `1.0` (`inside`)
  - herding index: `0.625` (`inside`)
  - passive share: `0.8947` (`high`)
  - median trade interarrival seconds: `12.855` (`high`)
- 20 retail / 40 steps:
  - buy/sell ratio: `0.1379` (`low`)
  - two-sided book coverage: `0.0` (`low`)
  - trade presence: `1.0` (`inside`)
  - herding index: `0.875` (`high`)
  - passive share: `0.9688` (`high`)
  - median trade interarrival seconds: `4.284` (`high`)
- 100 retail / 40 steps:
  - buy/sell ratio: `0.0435` (`low`)
  - two-sided book coverage: `0.0` (`low`)
  - trade presence: `1.0` (`inside`)
  - herding index: `1.0` (`high`)
  - passive share: `0.9894` (`high`)
  - median trade interarrival seconds: `0.891` (`inside`)

### Interpretation
- The report path is now working against the real order runtime.
- The current seeded episode setup and retail behavior produce real trades, but larger populations become strongly sell-dominant.
- The immediate calibration issue is not trade absence; it is sell pressure, poor standing two-sided book coverage, and overly passive submissions.

### Next actions
- Add a calibration scenario knob for initial inventory distribution instead of seeding half the agents uniformly.
- Reduce cold-start sell pressure from inventory holders, especially `liquidity_noise`, `mean_revert`, and `trend_follow`.
- Add a bounded quote-support behavior so some agents maintain non-crossing bids and asks after the opening burst.

## Task 2026-04-24-agents-05
- **time**: 2026-04-24
- **status**: done
- **goal**: add the first episode-level retail calibration report collector so persona tuning can move from static bands to measured run output
- **files involved**:
  - `agents/retail_calibration_report.py`
  - `tests/test_retail_calibration_report.py`
  - `docs/architecture/runtime/retail-persona-calibration-blueprint.md`
  - `docs/code-index.md`
- **total changed lines**: small focused diagnostics layer

### Change summary
- Added normalized calibration samples for orders, trades, post-open book observations, and holding durations.
- Added a collector that computes the market acceptance metrics from `agents/retail_calibration.py`:
  - `buy_sell_order_ratio`
  - `post_open_two_sided_book_coverage`
  - `post_open_trade_presence`
  - `order_flow_herding_index`
  - `median_passive_submission_share`
  - `median_trade_interarrival_seconds`
- Added per-family diagnostics for order count, buy/sell imbalance, passive share, median holding bars, and expected-price capture.
- Added target-band evaluations so a report can immediately say whether a metric is inside, low, high, or missing.

### Purpose
- Turn the persona calibration blueprint into a measurable episode artifact.
- Keep metric math in one reusable module before wiring it to runtime event capture.
- Preserve a clean boundary between runtime execution and calibration analysis.

### Verification note
- Targeted tests passed:
  - `tests/test_retail_calibration_report.py`
  - `tests/test_retail_calibration_defaults.py`
  - `tests/test_retail_persona_model.py`

### Next actions
- Wire runtime order/trade/book events into `RetailCalibrationReportCollector`.
- Add a fixed-seed smoke runner for 6, 20, and 100 retail populations that emits the report as JSON.
- Use report deltas before changing family share defaults again.

## Task 2026-04-24-agents-04
- **time**: 2026-04-24
- **status**: done
- **goal**: upgrade runtime-backed retail from strategy-name heuristics into a persona-driven decision layer, and establish a durable calibration baseline for later market-realism tuning
- **files involved**:
  - `agents/retail_persona.py`
  - `agents/retail_strategy.py`
  - `agents/retail_calibration.py`
  - `app/services/runtime_retail_agent.py`
  - `docs/architecture/runtime/retail-persona-calibration-blueprint.md`
  - `docs/code-index.md`
  - `tests/test_retail_persona_model.py`
  - `tests/test_retail_calibration_defaults.py`
- **total changed lines**: medium focused runtime/design batch

### Change summary
- Added a dedicated retail persona model with:
  - static personality parameters such as `loss_aversion_raw`, `courage_raw`, `entry_selectiveness`, `target_conservatism`, `execution_patience`, and `position_budget`
  - dynamic state such as `courage_delta`, `recent_pnl_pressure`, `drawdown_stress`, and `thesis_validation_score`
  - a per-decision `expected_price` plan that now acts as the center of runtime buy/sell reasoning
- Wired runtime retail execution to consume persona plans instead of only direct strategy-name signal heuristics.
- Added `slow_fundamental_allocator` as a first-class strategy/family in the retail registry and cold-start mix vocabulary.
- Added a calibration defaults module that records:
  - family share targets
  - family parameter target bands
  - market-level acceptance metrics
  - recommended calibration sequence
- Added a formal runtime architecture blueprint for retail persona calibration.

### Purpose
- Make retail populations feel like "many different people inside a few behavior families" rather than a small set of cloned strategy bots.
- Create a stable place to tune realism through distributions and family mix rather than ad hoc rule edits.
- Keep loss aversion and courage aligned with their dedicated design documents and map them consistently into runtime behavior.

### Impact / risk
- Positive: runtime retail now has a more explainable bridge from personality to order flow.
- Positive: `expected_price` is now explicit and can be inspected, calibrated, and later exported in diagnostics.
- Positive: calibration work now has a documented and code-backed baseline instead of only conversational guidance.
- Risk: the current persona/planning layer is still only the first calibrated baseline; family weights and parameter bands will need iterative tuning against real episode metrics.
- Risk: market realism can still drift if the code baseline and blueprint document are edited separately in future changes.

### Verification note
- Targeted tests passed:
  - `tests/test_retail_persona_model.py`
  - `tests/test_retail_calibration_defaults.py`
  - `tests/frontend/unit/test_runtime_retail_clock_gating.py`
  - `tests/frontend/unit/test_agent_service_strategy_assignment.py`
- Real runtime smoke checks after the persona upgrade:
  - small population (`6` retail) still produced two-sided order flow and real trades
  - medium population (`20` retail) still produced real trades and a recognizable mixed family tape

### Next actions
- Add an episode-level calibration report that measures the market metrics defined in `agents/retail_calibration.py`.
- Compare multiple fixed-seed batches before changing any family mix defaults again.
- Use the calibration blueprint as the acceptance baseline for future realism work rather than tuning individual heuristics in isolation.

## Task 2026-03-25-agents-01
- **time**: 2026-03-25
- **status**: done
- **goal**: make retail strategy assignment explicit, visible, and testable instead of leaving batch-created retail agents strategy-less at the app layer
- **files involved**:
  - `agents/retail_strategy.py`
  - `app/core_dto/agent.py`
  - `app/services/agent_service.py`
  - `app/panels/agents/panel.py`
  - `app/ui/adapters/agents_adapter.py`
  - `tests/frontend/unit/test_agent_service_strategy_assignment.py`
- **total changed lines**: moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `class MomentumChaseStrategy:`
- **last line**: `return {"mode": "post_ipo_cold_start",`

#### fragment 2
- **first line**: `class AgentMetaDTO(BaseModel):`
- **last line**: `strategy: Optional[str] = None`

#### fragment 3
- **first line**: `def batch_create_retail(self, cfg: BatchCreateConfig) -> Dict[str, Any]:`
- **last line**: `return {"success_ids": success, "failed": failed, "strategies": assigned_strategies}`

#### fragment 4
- **first line**: `return {`
- **last line**: `'heartbeat_stale': stale,`

#### fragment 5
- **first line**: `def test_allocate_retail_strategies_uses_explicit_list_round_robin():`
- **last line**: `assert "momentum_chase" in profile["strategy_mix"]`

### Change summary
- Rebuilt `agents/retail_strategy.py` into a clean strategy registry with named retail behaviors:
  - `mean_revert`
  - `momentum_chase`
  - `buy_the_dip`
  - `profit_taking`
  - `breakout`
  - `vol_scaling`
  - `liquidity_noise`
  - `noise`
- Added weighted retail-population helpers so batch-created retail agents can be assigned a realistic noise mix rather than all appearing strategy-less.
- Added a `post_ipo_cold_start` strategy mix profile biased toward `liquidity_noise`, `momentum_chase`, and `buy_the_dip`.
- Extended app-layer `AgentMetaDTO` with an optional `strategy` field.
- Wired `AgentService.batch_create_retail()` to assign and return strategies, and surfaced the field through `AgentsPanel` and the Agents table.
- Added focused unit coverage for strategy allocation and batch-created retail strategy visibility.

### Purpose
- Make it obvious where retail strategies are defined and how a batch of retail agents gets its strategy mix.
- Create a stable base for later runtime wiring, where the actual order-submitting retail executor can consume the same named strategies.
- Provide a concrete app-layer answer to “what retail mix are we using now?” before continuing deeper runtime automation work.

### Impact / risk
- Positive: strategy names are now visible from the app-layer agents list instead of being implicit or missing.
- Positive: retail population assignment is no longer an untracked placeholder concern.
- Positive: there is now an explicit cold-start-oriented strategy mix reference for IPO-following noise populations.
- Risk: current frontend batch creation still mainly manages app-layer/meta agents; actual runtime auto-ordering still needs a cleaner execution owner to consume these strategies end-to-end.

### Next actions
- Decide whether frontend-created `Retail` agents should remain app-layer metadata only or should begin instantiating a real runtime retail executor.
- If runtime retail execution is connected next, reuse the named strategy registry from `agents/retail_strategy.py` instead of introducing another parallel strategy vocabulary.
- For IPO cold-start specifically, prefer real micro-order noise from a bounded retail pool over fake bar fabrication, and keep any synthetic data paths explicitly labeled as non-authoritative.

## Task 2026-03-26-agents-02
- **time**: 2026-03-26
- **status**: done
- **goal**: connect frontend-created `Retail` agents to a real runtime order loop, remove prefix-based retail naming from the desktop flow, and let the user choose a retail strategy at creation time
- **files involved**:
  - `app/services/runtime_retail_agent.py`
  - `app/services/agent_service.py`
  - `app/ui/agent_creation_modal.py`
  - `app/ui/adapters/agents_adapter.py`
  - `tests/frontend/unit/test_agent_service_strategy_assignment.py`
  - `tests/frontend/unit/test_agent_creation_modal.py`
  - `tests/frontend/unit/test_agents_panel.py`
- **total changed lines**: medium cross-layer change set

### Code fragment anchors
#### fragment 1
- **first line**: `class RuntimeRetailAgent:`
- **last line**: `__all__ = ["RuntimeRetailAgent", "RuntimeStateCallback"]`

#### fragment 2
- **first line**: `class AgentService:`
- **last line**: `return {"success_ids": success, "failed": failed, "strategies": assigned_strategies}`

#### fragment 3
- **first line**: `class AgentCreationModal:`
- **last line**: `return clean`

#### fragment 4
- **first line**: `def _open_batch_dialog(self):`
- **last line**: `start(count=10, agent_type='Retail', name_prefix='agent', strategies=None)`

#### fragment 5
- **first line**: `class _FakeRuntimeRetailAgent:`
- **last line**: `assert modal.get_view()['input']['name_prefix'] is None`

### Change summary
- Added a clean app-owned retail runtime executor that submits real orders through `TradingService` instead of faking front-end-only activity.
- Wired `AgentService` to create runtime retail executors, bootstrap same-name accounts, preserve runtime heartbeat/state updates, and emit strategy-based retail IDs like `mean_revert001`.
- Kept `MultiStrategyRetail` on the metadata-first path, with its existing `MSR0001` naming style.
- Simplified `AgentCreationModal` so retail creation no longer depends on prefix input, while `Retail` accepts at most one chosen strategy and `MultiStrategyRetail` still validates a multi-line strategy list.
- Updated the Agents batch-create dialog so the UI now shows:
  - a retail strategy selector with `Auto (cold-start mix)`
  - no retail prefix input
  - the multi-strategy textbox only for `MultiStrategyRetail`
- Added tests covering strategy-based retail naming, runtime control delegation, and the no-prefix retail creation flow.

### Purpose
- Make retail agents created from the desktop app actually contribute real market noise after they are started.
- Reduce naming ambiguity by tying retail names directly to their configured strategy instead of a manual prefix.
- Give the operator a direct creation-time handle for choosing a retail behavior when a specific noise profile is needed.

### Impact / risk
- Positive: IPO-following continuous trading now has a real micro-order bootstrap path instead of depending on placeholder chart data.
- Positive: Agents and Accounts align better because retail agent IDs, names, and account IDs are the same strategy-based identifier.
- Positive: the front-end creation flow is simpler and closer to the user mental model of “create N mean-reversion retail traders”.
- Risk: the new retail runtime is intentionally lightweight and heuristic; it is suitable for noise seeding and early desktop validation, but not yet a full production-grade agent orchestration subsystem.
- Risk: `MultiStrategyRetail` is still not on the real runtime loop, so mixed-population simulations currently have one runtime-backed retail path and one metadata-first path.

### Next actions
- Smoke-test the GUI path manually with created instruments and started retail populations to confirm that IPO-to-continuous cold-start now produces real trades on screen.
- Decide whether `MultiStrategyRetail` should be upgraded onto the same runtime execution base or retired in favor of explicit per-strategy retail groups.
- If the retail runtime remains the base path, add guardrails for exposure caps, per-symbol participation limits, and more explicit phase-aware throttling.

### Verification note
- 2026-03-26 offscreen smoke test rerun after the cold-start fixes:
  - created a fresh continuous symbol with `settlement_cycle=1`
  - batch-created 9 retail agents with explicit strategy mix `liquidity_noise + momentum_chase + buy_the_dip`
  - confirmed strategy rotation was preserved at the panel path (`liquidity_noise001`, `momentum_chase001`, `buy_the_dip001`, ...)
  - confirmed all 9 agents reached live heartbeat `RUNNING`
  - confirmed the engine produced real trades on the fresh symbol during cold start (`engine_trade_count=2`, recent prices `10.01`, `10.02`)
- Interpretation:
  - the previous no-trade cold-start failure came from two combined issues:
    - progressive batch creation collapsed explicit strategy rotation into the first strategy only
    - T+1 blocked flat sell-side noise on a fresh symbol, so no opening offers appeared
  - the current fix keeps risk semantics intact and instead seeds a tiny IPO-style opening inventory for cold-start sell-side retail when needed.

## Task 2026-03-26-agents-03
- **time**: 2026-03-26
- **status**: done
- **goal**: stop runtime-backed retail agents from repeatedly re-sending same-day sell orders after a T+1 rejection, and reduce one likely cross-thread GUI crash source during batch account creation/startup
- **files involved**:
  - `app/services/runtime_retail_agent.py`
  - `app/ui/adapters/account_adapter.py`
  - `tests/frontend/unit/test_orders_panel_dedup.py`
  - `tests/frontend/unit/test_market_runtime_trade_series.py`
- **total changed lines**: small targeted runtime/UI hardening

### Change summary
- Added a same-`sim_day` sell-stop guard in `RuntimeRetailAgent`:
  - after a T+1-style rejected `sell` on a `settlement_cycle >= 1` symbol, that retail agent stops trying to sell the same symbol again for the remainder of the current runtime `sim_day`
- This prevents the previous pattern where retail bought once, then spammed rejected sell orders for the rest of the session.
- Hardened `AccountPanelAdapter` so runtime event callbacks no longer mutate Qt combo-box state directly from background threads; updates are now posted back onto the UI thread.

### Purpose
- Keep retail behavior closer to realistic same-day settlement constraints instead of letting it loop on an already-known invalid action.
- Remove one more Qt cross-thread write path that could contribute to the desktop app flashing closed when many retail agents/accounts are created quickly.

### Impact / risk
- Positive: rejected-order noise is lower and the order stream is easier to reason about.
- Positive: GUI stability should improve when many runtime-backed retail accounts are added in a burst.
- Risk: the stop-sell guard currently keys off runtime `sim_day`, and that day is still not driven by the desktop Clock panel yet.

### Open architectural gap
- The project still has two clock universes:
  - frontend/app clock: `app/services/clock_service.py`
  - runtime simulation clock: `services/sim_clock.py`
- The new T+1 guard intentionally trusts the runtime clock, because settlement legality belongs to runtime semantics rather than panel-local UI state.
- A future follow-up should make the desktop Clock panel drive runtime `sim_day` advancement directly, otherwise “same day” remains effectively sticky unless runtime clock code is advanced elsewhere.

## Runtime participation note (2026-03-26)

### status
done

### goal
Make retail-agent `start` mean “allowed to trade when market time is running”, rather than “immediately begin placing orders even if the simulation clock has not started”.

### files involved
- `app/services/runtime_retail_agent.py`
- `tests/frontend/unit/test_runtime_retail_clock_gating.py`

### change summary
- Added runtime clock gating to `RuntimeRetailAgent._step()`.
- Retail agents now check runtime `sim_clock.snapshot()["running"]` before placing any order.
- This preserves the desktop operator semantics:
  - `Agents -> Start`: arm/enable the participant
  - `Clock -> Start`: open the simulation time flow that allows trading behavior to execute

### impact / risk
- Positive: agent lifecycle is now subordinate to clock lifecycle, which matches the simulation mental model much better.
- Positive: avoids accidental pre-open order noise when the operator has started participants but not started the simulation day.
- Risk: current UI status still reports the retail agent as `RUNNING` once armed; if later needed, a dedicated `ARMED/WAITING_CLOCK` status could make this clearer.

## Sell-availability note (2026-03-26)

### status
done

### goal
Stop retail agents from submitting sell orders when they do not have available holdings, and clamp sell size to available quantity.

### files involved
- `app/services/runtime_retail_agent.py`

### change summary
- Added a runtime holdings check before retail sell submission.
- If available holdings are `<= 0`, the retail agent no longer submits a sell.
- During cold start, a sell-without-holdings intent is converted into a buy intent instead of using seeded inventory.
- If available holdings are positive but smaller than the intended order size, the submitted sell quantity is clamped to the available lot-adjusted quantity.

## IPO retail distribution note (2026-03-26)

### status
done

### goal
兑现桌面主链里“instrument 首次进入交易日时，向约 20% 随机 retail 无条件发放股票”的 IPO 初始分配逻辑，并保证不把 `free_float_shares` 当成可被扣减的剩余库存字段。

### files involved
- `services/ipo_retail_distribution.py`
- `app/controllers/market_controller.py`
- `app/services/clock_service.py`
- `app/services/agent_service.py`

### change summary
- 新增 runtime IPO retail 分配服务，按约 `20%` 的 retail 账户比例随机选取接收者。
- 单个 symbol 的初始发股总量被限制在 instrument 创建时记录的 `free_float_shares` 以内。
- 分配不再扣减 `instruments.free_float_shares`；该字段继续保留“流通股总量”语义，避免影响 snapshot/turnover 指标。
- instrument 创建后会先登记为待分配；若时钟已在运行，则尝试立即完成分配。
- `Clock -> Start` 会在 sim_day0 开始前处理待分配 symbol，覆盖“先建 instrument、再建 retail、最后启动 clock”的桌面操作路径。
- retail 账户 bootstrap 现在会同步写入 runtime `agent_bindings`，并在时钟已运行时补触发待分配 IPO symbol。

### impact / risk
- Positive: 桌面主链终于兑现了 IPO 首日随机发股，不再只停留在遗留计划代码里。
- Positive: `agent_bindings` 对 retail 账户的 runtime 归属更完整，后续排行/账户归因更稳。
- Risk: “已分配”当前按运行期内存状态和现有持仓检测收束，跨重启的幂等性还没有落到独立持久化标记字段上。

## IPO cold-start sell-side note (2026-03-26)

### status
done

### goal
避免 retail 在冷启动阶段“无仓也尝试卖”导致没有真实双边成交，同时让收到 IPO 初始持仓的账户更容易形成首批卖盘。

### files involved
- `app/services/runtime_retail_agent.py`

### change summary
- cold start 决策现在会先检查当前 symbol 的可卖持仓。
- 若账户已有可卖持仓，则优先形成真实卖单。
- 若账户无仓，则冷启动阶段只会买，不再继续构造空卖方向。

### impact / risk
- Positive: IPO 初始发股后的第一批成交更容易被真正打出来。
- Positive: 不再依赖“卖单被 T+1 拒绝再兜底修正”的被动路径。
## Agent runtime-authority note (2026-04-06)

### status
done

### goal
Reduce `AgentService` dependence on app-process memory by hydrating the agent list from runtime `agent_bindings`.

### files involved
- `services/runtime_query_service.py`
- `app/services/agent_service.py`
- `tests/frontend/unit/test_agent_service_runtime_authority.py`

### change summary
- `RuntimeQueryService.list_agent_bindings()` now returns parsed binding `meta` in addition to `agent_name / agent_type / account_id`.
- `AgentService` now syncs from runtime bindings before `list_agents()`, `get()`, `control()`, and `update_params_version()`.
- Runtime-hydrated agents default to `STOPPED` but retain runtime strategy/type metadata and preserve live in-memory status fields once the current session starts updating them.

### impact / risk
- Positive: restarting the desktop app no longer means the Agents panel must start from a completely empty app-memory list.
- Positive: strategy names and agent identities now come back from runtime authority instead of only from the current process.
- Risk: live execution status is still session-memory-first; this step restores identity/metadata authority, not full persisted runtime lifecycle yet.

## Agent runtime-lifecycle note (2026-04-06)

### status
done

### goal
Persist minimal live agent lifecycle fields into runtime bindings so the desktop can recover recent status across process restarts.

### files involved
- `services/runtime_command_service.py`
- `app/runtime_gateway.py`
- `app/services/agent_service.py`
- `tests/frontend/unit/test_agent_service_runtime_authority.py`

### change summary
- Added `RuntimeCommandService.update_agent_binding_meta(...)` and exposed it through `RuntimeGateway`.
- Agent binding metadata now stores and updates:
  - `status`
  - `start_time`
  - `last_heartbeat`
  - `params_version`
  - baseline identity fields during bootstrap
- `AgentService` now persists lifecycle changes back into runtime whenever:
  - live status changes
  - heartbeat changes
  - params version changes
- Runtime hydration now restores those persisted fields into new desktop-side `AgentMetaDTO` instances.

### impact / risk
- Positive: a fresh desktop session can now recover more than just agent identity; it can also recover the latest persisted lifecycle state.
- Positive: the Agents panel is materially closer to a runtime-authoritative view instead of a pure app-memory list.
- Risk: this is still a lightweight metadata persistence path, not a full dedicated runtime agent lifecycle table with strict session history semantics.

## Agent runtime rehydration note (2026-04-09)

### status
done

### goal
Make previously created retail agents able to submit orders again after the desktop app restarts and the user presses `Start` in a new session.

### files involved
- `app/services/agent_service.py`
- `tests/frontend/unit/test_agent_service_runtime_authority.py`

### change summary
- `AgentService` now recreates lightweight runtime retail executors from runtime-hydrated `agent_bindings` metadata instead of only restoring DTO metadata into the panel.
- `control(..., "start")` now ensures a runtime executor exists before trying to start a persisted retail agent.
- Runtime-binding sync also proactively hydrates missing retail executors for restored `Retail` agents.

### impact / risk
- Positive: retail agents restored from a previous GUI session are no longer "startable in the UI but inert in runtime".
- Positive: this closes an important gap between persisted agent identity and actual runtime execution.
- Risk: executor rehydration still assumes the standard retail runtime implementation; if a future agent type needs a different executor, it should get an explicit factory path.
