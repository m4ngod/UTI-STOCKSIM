# Market and Symbol Detail evaluation

> Decision evidence for GitHub issue #31. This is a throwaway prototype review, not a production specification.

## Decision question

How should Market and Symbol Detail become read-only diagnostic context for the current Strategy Run, while making market path, strategy actions, execution, position impact, data freshness, and health traceable without recreating a trading workstation?

## Structural comparison

| Variant | Primary research question | Strongest quality | Main cost | Recommended role |
| --- | --- | --- | --- | --- |
| A — Evidence Lens | Why did the strategy select this symbol, and what evidence supports the result? | Fastest overview: market path, Strategy Action overlays, core impact, and the causal chain share one screen. | A permanent evidence rail competes with the chart when the workspace is narrow. | Base Symbol Detail structure. Collapse the rail below the chart at narrow breakpoints. |
| B — Temporal Trace | How did a Strategy Decision become execution and position impact over Simulation Time? | Best causal alignment across market path, decision, activation, fills, position impact, and health. | Too tall and specialized to be the default view for every symbol inspection. | Expandable `Execution Trace` mode inside Symbol Detail. |
| C — Scenario Universe | How does this symbol compare with the other relevant symbols in the same scenario? | Best cross-sectional entry point and fastest symbol-to-symbol comparison. | Weakens the selected symbol's evidence hierarchy if treated as the detail page itself. | Market-context entry surface in Run Monitoring; selecting a row opens the A-based Symbol Detail. |

## Recommended composition pending human verdict

1. Use **A — Evidence Lens** as the default local Symbol Detail structure.
2. Reuse **B — Temporal Trace** as an expandable `Execution Trace` mode, not a second shell.
3. Use **C — Scenario Universe** as the Run Monitoring entry surface for Market context, not as the Symbol Detail page.
4. Keep the #30 Journey Rail as the only global shell. These are local views within the current Strategy Run.
5. Preserve the current research context across every transition: Strategy Under Test, Market Scenario, Strategy Run, Scenario Replica, Simulation Time, and ViewState revision.

## Information hierarchy and progressive disclosure

### Always visible

- why the Strategy Under Test selected the symbol;
- the reference market path with Strategy Action and position-exposure overlays;
- Strategy Decision, execution erosion, position impact, and guardrail proximity;
- freshness, authoritative source, last reliable timestamp, and connection health;
- an explicit statement that orders, trades, accounts, and positions are read-only diagnostic evidence.

### One deliberate expansion

- the B-style Simulation Time trace;
- the complete Strategy Decision → Signed Share Order → activation → fill → position-impact chain;
- the subset of order-book and trade records linked to the current diagnostic question.

### Deep evidence only

- full order-book levels and trade log;
- source identifiers, revision, authoritative status, and correlation IDs;
- comparison methodology and the complete scenario universe.

Stale and disconnected states retain the last reliable values, mark them prominently, and pause formation of new evidence conclusions. They must never blank the historical record or silently present it as current.

## Delete instead of migrate

- Create Instrument;
- Buy and Sell controls;
- discretionary order submission;
- manual amend, cancel, or bulk-order actions;
- a global watchlist-led trading workspace;
- standalone account, position, order, or trade workbenches;
- any adapter capability that accepts a manual account or manual-order command.

Strategy-originated orders may appear only after an Execution Policy decision and only as immutable diagnostic evidence.

## Emil design-engineering review

| Area | Before review | After review |
| --- | --- | --- |
| Visual hierarchy | Market data risked reading like a generic trading terminal. | The research question, selection reason, causal evidence, and freshness state dominate; quotes and microstructure are subordinate. |
| Spatial composition | At a 1280 px viewport, A's two table minimum widths overflowed into the evidence rail. | The right inspector now yields at 1360 px and microstructure tracks may shrink; A has no horizontal overflow at desktop or 420 px. |
| Typography | Price and symbol identity could overpower diagnostic meaning. | Large identity type is paired with a plain-language selection reason; metrics remain compact and tabular. |
| Color | Market up/down colors could become the main semantic system. | Accent colors distinguish reference path, strategy action, position exposure, freshness, and failure states; red/green prices remain secondary. |
| Controls | Dense trading controls would imply discretionary execution. | Only state inspection, variant switching, symbol comparison, and evidence disclosure are interactive. |
| Motion | Modal and state changes could feel decorative or slow. | High-frequency navigation is instant; the evidence dialog uses only opacity and `scale(.97)` over 180 ms, with reduced-motion handling. |
| Responsive behavior | Permanent global and local side rails competed for limited width. | The global context inspector hides first, the local evidence rail then stacks, and comparison/detail panels become a single column without horizontal scrolling. |
| Content | Orders and fills could be mistaken for actions the researcher can initiate. | Every order, fill, and position record is labeled as strategy-originated, read-only evidence; removed capabilities are named explicitly. |

## Verification evidence

- JavaScript syntax, Python server compilation, and `git diff --check` pass.
- No `transition: all`, `scale(0)`, `ease-in`, manual `submit_order`, manual `cancel_order`, or manual-account payload appears in the prototype route.
- Desktop browser checks passed for A, B, and C at 1280 × 720 with no horizontal overflow.
- Fresh, Stale, and Disconnected update the URL, active control, banner, chart state, and last-reliable language consistently.
- The evidence dialog opens progressively and closes with `Escape`.
- C updates the selected symbol, URL, drawer heading, and switcher through both pointer and keyboard interaction.
- A and C passed 420 × 844 checks with document scroll width equal to client width.
- Browser console produced no warnings or errors.

## Human verdict required

Confirm the recommended composition — **A as the default Symbol Detail, B as its expandable Execution Trace, and C as the Market-context entry surface** — or name the variant that should replace it.
