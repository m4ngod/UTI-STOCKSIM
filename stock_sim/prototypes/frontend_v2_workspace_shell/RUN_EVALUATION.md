# Issue #32 — run monitoring and evidence interpretation evaluation

> THROWAWAY PROTOTYPE EVIDENCE. This document recommends a decision; it does not replace the required human verdict.

## Decision question

After a Formal Diagnostic Campaign starts, how should a Strategy Diagnostics Researcher move from progress and anomalies to evidence, failure causes, cross-candidate comparison, and a bounded conclusion—without recreating Arena, leaderboard, and Evidence Board as competing workbenches?

## Variant comparison

| Variant | Primary reading order | Strongest contribution | Main cost | Recommended role |
| --- | --- | --- | --- | --- |
| A — Interpretation Funnel | research question → task integrity and anomalies → findings → comparison signal | Preserves the live-to-explanation transition and makes the strongest counter-evidence visible before rank | It cannot give every sensitivity dimension equal prominence | Default Run Monitoring surface and the entry into Evidence & Findings |
| B — Sensitivity Field | candidate → paired sensitivity matrix → breakpoint → replicas → gate context | Best for cross-candidate and cross-scenario comparison around a specific robustness question | Too specialized to be the default for every run; a matrix-first shell can hide the causal narrative | Dedicated comparison mode opened from a candidate, finding, or sensitivity breakpoint |
| C — Finding Notebook | finding index → claim → support and contradiction → provenance → comparison appendix | Best durable research record; clearly separates a finding from a leaderboard row | Premature while the run is still producing evidence | Canonical Evidence & Findings record after evidence is interpretable |

## Recommended composition

Adopt **A + B + C as one progressive workflow, not three top-level destinations**:

1. **A is the default Run Monitoring experience.** It leads with the current research question, task completeness, anomalies, and the current interpretation state.
2. **B is an investigation mode.** A researcher reaches it from a selected candidate, Diagnostic Finding, or suspected breakpoint. It does not become a second global workspace.
3. **C is the durable Evidence & Findings record.** It becomes authoritative only when evidence is interpretable; while a task is running it may show provisional observations, never completed findings.

The Journey Rail remains the global navigation decided in #30. Run Monitoring and Evidence & Findings are consecutive stages of the same Strategy Run, with pinned Strategy Under Test, Market Scenario, Formal Diagnostic Campaign, Scenario Replica, Simulation Time, and ViewState revision.

## State behavior

| State | What the researcher sees | What the interface must not imply |
| --- | --- | --- |
| Running | active phase, completed replica count, live anomalies, provisional observations, rolling comparison | no Diagnostic Finding, final gate result, stable breakpoint, or research verdict |
| Partial | completed evidence plus explicit `missing` / `not_available` debts, provisional findings, locked conclusion | missing evidence is never treated as pass and rank cannot fill the gap |
| Failed | failure phase and `failure_type`, retained completed evidence, blocking metrics, next recovery action | execution failure is not presented as a negative strategy result or a completed campaign verdict |
| Completed | complete event chain, Diagnostic Findings, supporting and contradicting evidence, acceptance-lock result | completion alone is not success; a top-ranked candidate may still be No-Go |

## Progressive disclosure contract

The default surface shows only:

- current research question and fixed diagnostic context;
- task phase, completeness, and material anomalies;
- the most decision-relevant observations or findings;
- a clearly subordinated comparison signal.

Selection reveals:

- candidate-level gate summary and first suspected breakpoint;
- paired Scenario Replica and sensitivity comparison;
- finding claim, supporting evidence, contradicting evidence, applicability, and next diagnostic action.

An explicit evidence-detail action reveals:

- `failure_type`;
- `blocking_metrics`;
- evidence source and source run IDs;
- artifact hash and runner version;
- `pass`, `fail`, `missing`, and `not_available` values without collapsing them;
- evidence debt and the next recovery action.

## Leaderboard constraint

The leaderboard is a **comparison signal, never a research conclusion**. It must:

- appear after task integrity, anomalies, and interpretation;
- remain inside the current Strategy Run context;
- display evidence availability and acceptance-lock state beside return;
- never promote a candidate, open a gate, or imply robustness because it ranks first;
- be an appendix in the durable Finding Notebook.

## Delete / do not migrate

- The old Arena screen as a combined Create / Start / Stop / Evaluate control panel.
- A standalone leaderboard destination or rank-first home screen.
- A wide Evidence Board gate table as the default reading surface.
- Raw campaign, task, runner, and artifact identifiers as primary navigation.
- Manual gate override, checkpoint promotion, or any manual-order capability.
- Global account, position, order, fill, or watchlist workbenches. Those records remain read-only diagnostic context under the #31 Market Context decision.

## Downstream constraints

- Feature modules must consume typed, immutable ViewState and expose commands or intents; widgets do not call backend services directly.
- Running, Partial, Failed, and Completed remain explicit states in the shared run contract.
- Diagnostic Finding is a first-class read model with claim, confidence, support, contradiction, scope, provenance, and next action.
- Comparison mode uses paired campaign / replica evidence and stable candidate identities; it cannot compare unrelated contexts silently.
- URLs preserve selected run, candidate, finding, breakpoint, density, and view mode so evidence interpretations are shareable and reproducible.
- The prototype’s run-state selector is evidence tooling only; production state comes from runtime subscriptions.
- No production implementation begins until the human verdict for #32 is recorded.

## Emil design-engineering review

| Before | After | Why |
| --- | --- | --- |
| Arena actions, run status, rank, and gate tables compete on one screen | One dominant interpretation flow with comparison and provenance revealed by intent | Preserves information hierarchy and reduces simultaneous decision load |
| The completed example leaked into Running and Failed states | State-specific verdict, phase, timeline cap, evidence availability, and provisional language | Motion and polish cannot compensate for false state semantics |
| Ranking looked like the primary success signal | “Comparison signal · not a conclusion,” acceptance-lock state, and appendix placement | Makes the risk boundary visible at the moment of interpretation |
| Dense evidence identifiers were always visible | Source run, hash, runner version, and blocking metrics live in a focused provenance dialog | Keeps the main surface calm while preserving auditability |
| Variant and state labels ran together in the floating switcher | Explicit spacing and a separate verdict line | Improves scanability without adding decoration |
| Generic animation risk | Only the provenance dialog uses 180 ms opacity plus scale `0.97`; frequent state and variant switching is immediate; reduced motion is respected | Motion explains hierarchy without slowing repeated research actions |

## Verification evidence

- JavaScript syntax validation passes.
- No `transition: all`, `scale(0)`, or `ease-in` patterns are present.
- No manual order, cancel-order, or backend mutation command is present.
- Desktop validation at 1280×720 has no horizontal overflow.
- Mobile validation at 420×844 has no horizontal overflow for A and C.
- URL state updates for run state, variant, candidate, finding, and breakpoint.
- Candidate selection works with keyboard Enter.
- Provenance opens as a modal, closes with Escape, and exposes the required traceability fields.
- Browser console contains no warnings or errors.

## Human verdict required

Confirm or replace this composition:

> **A is the default Run Monitoring flow; B is the sensitivity / cross-candidate comparison mode; C is the durable Evidence & Findings record.**
