# Retail Persona Calibration Blueprint

## Goal

Turn the current runtime-backed retail population into a calibration-driven market-participant layer rather than a fixed set of heuristic strategy names.

This blueprint assumes the current architecture:

- retail strategy assignment happens in `agents/retail_strategy.py`
- per-agent personality sampling and decision planning happen in `agents/retail_persona.py`
- real order submission happens in `app/services/runtime_retail_agent.py`

The calibration objective is not "perfect realism". The objective is:

- stable two-sided order flow
- recognizable family-level behavior differences
- realistic within-family diversity
- a market tape that can be tuned by distribution changes instead of one-off rule edits

## Current family model

The current runtime persona layer calibrates these families:

- `trend_follow`
- `mean_revert`
- `buy_the_dip`
- `profit_taking`
- `slow_fundamental_allocator`
- `liquidity_noise`
- `noise`

The mapping from strategy names to family names lives in `agents/retail_persona.py`.

## Calibration order

Always calibrate in this order:

1. market-level acceptance metrics
2. family share mix
3. family parameter distributions
4. dynamic persona state response
5. cold-start and open-window stress tests

Do not start by hand-tuning one formula inside a single family. That makes local behavior prettier while often making the overall market less realistic.

## Market-level acceptance metrics

Use these metrics as the first-pass acceptance panel for each episode batch.

| metric | target band | interpretation |
| --- | --- | --- |
| `buy_sell_order_ratio` | `0.75 - 1.35`, target `1.00` | Total submitted buys divided by total submitted sells. |
| `post_open_two_sided_book_coverage` | `0.85 - 1.00`, target `0.95` | Share of symbols that show both bids and asks in the first calibration window. |
| `post_open_trade_presence` | `0.70 - 1.00`, target `0.88` | Share of symbols that produce at least one real trade in the first calibration window. |
| `order_flow_herding_index` | `0.30 - 0.68`, target `0.48` | Share of bars where one side exceeds 70 percent of submissions. |
| `median_passive_submission_share` | `0.30 - 0.62`, target `0.45` | Share of orders submitted via passive quote logic instead of immediate crossing. |
| `median_trade_interarrival_seconds` | `0.20 - 2.40`, target `0.75` | Median time between trades during active market phases. |

If these metrics are outside band, do not move on to family-level fine tuning yet.

## Baseline family mix

The initial recommended target mix is:

| family | target share | low | high |
| --- | --- | --- | --- |
| `trend_follow` | `0.20` | `0.16` | `0.24` |
| `mean_revert` | `0.22` | `0.18` | `0.26` |
| `buy_the_dip` | `0.12` | `0.10` | `0.15` |
| `profit_taking` | `0.12` | `0.08` | `0.15` |
| `slow_fundamental_allocator` | `0.14` | `0.10` | `0.18` |
| `liquidity_noise` | `0.14` | `0.10` | `0.18` |
| `noise` | `0.06` | `0.04` | `0.10` |

Interpretation:

- `trend_follow + mean_revert` remain the bulk of the retail population.
- `buy_the_dip + profit_taking` provide asymmetry in entry and exit behavior.
- `slow_fundamental_allocator` provides a slower valuation anchor.
- `liquidity_noise + noise` preserve tape continuity and small-scale microstructure randomness.

## Family-level calibration bands

### `trend_follow`

- median holding bars: target `9`, band `5 - 16`
- expected-price capture: target `0.58`, band `0.42 - 0.78`
- execution patience: target `0.32`, band `0.12 - 0.58`
- loss aversion: target `0.32`, band `0.12 - 0.56`
- courage: target `0.65`, band `0.42 - 0.90`

Use this family to generate directional follow-through, not to anchor value.

### `mean_revert`

- median holding bars: target `10`, band `6 - 18`
- expected-price capture: target `0.42`, band `0.25 - 0.62`
- execution patience: target `0.52`, band `0.30 - 0.80`
- loss aversion: target `0.52`, band `0.28 - 0.82`
- courage: target `0.48`, band `0.28 - 0.72`

Use this family to absorb overshoots and reduce one-sided drift.

### `buy_the_dip`

- median holding bars: target `8`, band `5 - 14`
- expected-price capture: target `0.34`, band `0.18 - 0.52`
- execution patience: target `0.38`, band `0.18 - 0.64`
- loss aversion: target `0.40`, band `0.20 - 0.68`
- courage: target `0.58`, band `0.36 - 0.84`

This family should be directionally supportive, but more conservative than pure trend-followers about target depth.

### `profit_taking`

- median holding bars: target `7`, band `4 - 12`
- expected-price capture: target `0.20`, band `0.08 - 0.36`
- execution patience: target `0.44`, band `0.24 - 0.72`
- loss aversion: target `0.62`, band `0.38 - 0.88`
- courage: target `0.36`, band `0.18 - 0.58`

This family is the main short-horizon inventory release mechanism. Too much of it makes the market permanently sell-heavy.

### `slow_fundamental_allocator`

- median holding bars: target `20`, band `12 - 36`
- expected-price capture: target `0.28`, band `0.16 - 0.42`
- execution patience: target `0.72`, band `0.52 - 0.92`
- loss aversion: target `0.38`, band `0.18 - 0.62`
- courage: target `0.56`, band `0.36 - 0.78`

This family should react slowly, size up more steadily, and ignore short-term crowd pressure more than technical families.

### `liquidity_noise`

- median holding bars: target `4`, band `2 - 8`
- expected-price capture: target `0.14`, band `0.05 - 0.24`
- execution patience: target `0.30`, band `0.10 - 0.62`
- loss aversion: target `0.32`, band `0.14 - 0.58`
- courage: target `0.46`, band `0.26 - 0.74`

This family is still "retail", not a dedicated market maker. Its job is to keep small-scale two-sided participation alive.

### `noise`

- median holding bars: target `3`, band `1 - 6`
- expected-price capture: target `0.10`, band `0.04 - 0.18`
- execution patience: target `0.24`, band `0.08 - 0.56`
- loss aversion: target `0.28`, band `0.12 - 0.54`
- courage: target `0.42`, band `0.24 - 0.70`

This family should remain small. Too much pure noise degrades signal structure quickly.

## Persona parameter tuning rules

The current runtime persona model exposes these main axes:

- `loss_aversion_raw`
- `courage_raw`
- `entry_selectiveness`
- `target_conservatism`
- `execution_patience`
- `patience_seconds`
- `position_budget`
- `profit_realization_bias`
- `crowd_susceptibility`

Recommended interpretation:

- tune `target_conservatism` first when expected prices look too shallow or too ambitious
- tune `loss_aversion_raw` first when risk shrinking, panic exits, and add-to-loser behavior feel off
- tune `courage_raw` only after `loss_aversion_raw` is already sensible
- tune `execution_patience` when the passive/aggressive order mix is unrealistic
- tune `patience_seconds` when passive orders or stale positions make the market stop changing; `None` means no extra time-based impatience and the sell decision is left to loss aversion, courage, thesis quality, invalidation, and target logic
- tune `position_budget` when the market moves but trade sizes feel too small or too large

Avoid simultaneously widening every parameter distribution. First set family target means, then widen only the one or two dimensions that produce visible within-family diversity.

## Dynamic state calibration

The current persona state already includes:

- `courage_delta`
- `recent_pnl_pressure`
- `drawdown_stress`
- `thesis_validation_score`
- `adverse_duration_bars`

Recommended calibration logic:

- if agents become permanently timid after one bad episode, reduce the decay memory in `recent_pnl_pressure` and `drawdown_stress`
- if agents hold losers too long, increase the negative contribution of `invalidation_score` into `courage_delta`
- if agents churn too quickly after tiny pullbacks, reduce the sensitivity of `adverse_duration_bars`
- if agents never build differentiated confidence, increase the weight of `thesis_quality` in `update_persona_state()`

In practice, `courage_delta` should move slowly and mean-revert. It should feel like short-to-medium memory, not an on/off mood switch.

## Experiment loop

Use a fixed, repeated loop:

1. fix the random seed set for the experiment batch
2. run 50 to 100 short episodes with the same market template
3. compute market-level metrics first
4. compute family-level metrics next
5. inspect only the metrics that are outside target band
6. change exactly one of:
   - family share target
   - one family parameter mean
   - one family parameter spread
   - one state-response coefficient
7. rerun the same seed batch

This keeps calibration explainable. If multiple groups of settings are changed at once, it becomes hard to attribute why realism improved or degraded.

## Recommended next implementation steps

1. Build an episode-level `retail calibration report` collector that records:
   - per-family order counts
   - per-family buy/sell imbalance
   - per-family median holding duration
   - per-symbol post-open two-sided coverage
   - expected-price capture statistics
2. Wire `agents/retail_calibration.py` as the default baseline source for:
   - family share targets
   - metric acceptance bands
   - first-pass family parameter ranges
3. Add one smoke test suite that runs small and medium populations:
   - 6 retail
   - 20 retail
   - 100 retail
4. Only after the report is stable, consider automated search or Bayesian tuning.

## Source of truth

The current code baseline for these targets is:

- `agents/retail_calibration.py`
- `agents/retail_calibration_report.py`
- `agents/retail_persona.py`
- `agents/retail_strategy.py`
- `app/services/runtime_retail_agent.py`

The calibration blueprint should evolve with the code. If the code moves but this document is not updated, treat the code as authoritative and revise the document in the same change set.

## Episode report collector

The first implementation of the episode-level calibration report lives in `agents/retail_calibration_report.py`.

It accepts normalized samples for:

- orders
- trades
- post-open book observations
- holding-duration observations

It produces:

- market-level metrics aligned with `MARKET_METRIC_TARGETS`
- target-band evaluations for each market metric
- per-family order counts
- per-family buy/sell imbalance
- per-family passive submission share
- per-family median holding bars
- per-family expected-price capture statistics

The collector is intentionally source-agnostic. A future runtime wiring step should translate real order/trade/book events into these samples, rather than duplicating metric logic inside runtime services.

## Runtime large-population practice notes

The first runtime-backed 20-to-100 retail calibration pass found four market-structure issues that matter more than single-agent formula tuning:

- post-IPO strategy allocation must stay close to the family target mix at 100 agents; otherwise `liquidity_noise`, `profit_taking`, and `noise` can dominate the tape
- empty-book passive quotes must seed both sides without crossing: passive buys quote below reference, passive sells quote above reference
- agent symbol rotation must be desynchronized by stable agent key, otherwise larger populations submit into the same symbol cadence
- episode inventory seeding should be a cold-start liquidity scaffold, not a broad artificial position distribution

The current practice baseline therefore uses:

- a post-IPO weighted mix close to the calibration share table: `mean_revert=4`, `momentum_chase=4`, `slow_fundamental_allocator=3`, `liquidity_noise=3`, `buy_the_dip=2`, `profit_taking=2`, `noise=1`
- a small deterministic bootstrap template that exposes every calibrated family before repeating the weighted bag
- per-symbol sell anchors for calibration episodes, selected from sell-capable families and kept out of `mean_revert`, `buy_the_dip`, `momentum_chase`, and pure `noise`
- lower random inventory seeding than the original episode runner, so seeded holdings do not become persistent artificial sell pressure
- a passive same-side cooldown in `RuntimeRetailAgent` so one account does not stack repeated passive orders next to its own unfilled interest

Latest fixed-seed snapshot after this pass, using `scripts/run_retail_calibration_episode.py --sizes 6,20,100 --steps 40`:

| population | buy/sell | two-sided coverage | trade presence | herding | passive share | trade interarrival |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | `0.765` | `1.00` | `1.00` | `1.00` | `0.760` | `8.570s` |
| 20 | `0.667` | `1.00` | `1.00` | `1.00` | `0.760` | `2.856s` |
| 100 | `0.878` | `1.00` | `1.00` | `0.909` | `0.638` | `0.594s` |

Interpretation:

- the 100-agent market is now usable for runtime calibration: buy/sell, two-sided coverage, trade presence, and trade interarrival are inside target bands; passive share is just above band
- 20-agent markets now satisfy the critical "market is alive" requirements, but still need a small-sample tuning pass for buy/sell balance, herding, passive share, and interarrival
- 6-agent episodes are useful as smoke tests, not as full statistical acceptance tests; herding and interarrival are expected to remain noisy at that scale
