# Frontend V2 workspace shell evaluation

> THROWAWAY PROTOTYPE EVIDENCE — GitHub issue #30. This document recommends a decision but does not replace the required human verdict.

## Evidence basis

All three variants were exercised with the same deterministic state:

- Strategy Under Test: `Breakout v4.2 · 7ec31a`
- Market Scenario: `2021 Q1 / 流动性压力 × 1.8`
- Strategy Run: `DGN-24-0719-A`
- Active workspace: Run Monitoring
- Shared content: campaign progress, evidence signals, freshness, Reproduction Manifest, and read-only market/account/order/trade context

Verified interactions:

- URL-stable variant, task, stage, and density state
- explicit task switching with complete context replacement
- backward and forward stage navigation without changing task lifecycle
- comfortable and compact density
- modal dismissal and keyboard variant switching
- desktop and narrow viewport rendering
- zero page console errors during the observed paths
- no discretionary manual order capability

## Structural comparison

| Criterion | A — Journey Rail | B — Focus Ribbon | C — Research Chronicle |
| --- | --- | --- | --- |
| “Where am I in the journey?” | Strongest: all six stages remain visible beside the work | Strong: all stages remain visible above the work | Moderate: stages are document chapters rather than the dominant shell |
| Pinned diagnostic context | Strongest: permanent inspector on wide screens, breadcrumbs when narrow | Strong: compact dock, but it competes for vertical space on short screens | Strong: context is embedded in the record and task index |
| Current research question | Strong | Strongest: one dominant question controls the hierarchy | Moderate: provenance and chronology compete with the current question |
| Backtracking | Strongest: earlier stages are one stable rail action away | Strong: horizontal ribbon remains available | Strong for audit history, slower for routine navigation |
| Switching diagnostic tasks safely | Strong: explicit modal | Strong: explicit modal | Strongest: task index is continuously visible, with the same explicit modal available |
| Information density | Balanced at desktop and compact density | Calmest at desktop, longest on narrow screens | Densest research record, longest on narrow screens |
| Auditability | Moderate: context is visible but history is not the shell's main structure | Moderate: prioritizes the present question | Strongest: provenance and prior checkpoints are first-class |
| Risk of becoming a panel launcher | Lowest: navigation names workflow stages, never resources | Low: workflow ribbon and research question dominate | Low, but task list can become the primary mental model if used globally |
| Best role | Global workspace shell | Local focus mode for monitoring/evidence | Evidence audit and finding-trace view |

## Narrow viewport evidence

At a `420 × 844` viewport in compact density, all variants avoided horizontal overflow (`scrollWidth` remained within the viewport). Observed document heights for the same Run Monitoring state were:

| Variant | Document height | Interpretation |
| --- | ---: | --- |
| A — Journey Rail | `1271 px` | The 2×3 journey grid remains visible without duplicating the primary content hierarchy |
| B — Focus Ribbon | `2042 px` | The ribbon, current-question block, evidence horizon, and context dock serialize into a longer page |
| C — Research Chronicle | `2397 px` | Task index, chapter navigation, current entry, and prior checkpoint produce the longest scroll |

These measurements are prototype evidence, not production performance budgets.

## Emil design review

| Before | After | Why |
| --- | --- | --- |
| Treat A, B, and C as mutually exclusive full-shell candidates | Use A as the shell, B as a focus hierarchy inside Run Monitoring/Evidence, and C as the evidence audit view | Each structure is strongest at a different frequency and scope; composing their strengths avoids forcing one hierarchy onto every task |
| Keep B's pinned context dock sticky on short viewports | Make pinned context non-overlay or collapsible below the wide-screen breakpoint | A persistent dock is useful on wide screens but consumes scarce vertical space when content is serialized |
| Use C's continuously visible task index as global navigation | Keep explicit task switching in the shell and surface Chronicle only where provenance is the task | A permanently dominant task list can pull attention away from the six-stage diagnostic journey |
| Render A's complete six-stage rail as a 2×3 block on every narrow screen | Show the current stage and journey progress first, with the full six-stage map available on demand | The full map is valuable, but repeated mobile use should prioritize the current research question |
| Animate high-frequency stage and keyboard navigation | Keep stage and keyboard navigation immediate; animate only the occasional centered task-switch modal at 180 ms from `scale(0.97)` plus opacity | Frequent navigation should never feel delayed; the modal animation explains a rare, context-changing action |
| Allow context changes to look like ordinary navigation | Preserve the explicit task-switch dialog and name every context field that changes | Invisible context replacement is dangerous in diagnostic research; the confirmation surface prevents cross-run interpretation |

## Recommendation awaiting confirmation

Adopt **A — Journey Rail** as the global Frontend V2 workspace shell, with these scoped borrowings:

1. Use B's dominant “current research question” hierarchy inside Run Monitoring and Evidence & Findings.
2. Use C's chronological Chronicle as an Evidence & Findings audit mode, not as the global shell.
3. Retain explicit task switching, pinned Strategy Run context, freshness, and Reproduction Manifest across every workspace.
4. On narrow screens, collapse the full journey map after orientation so the active research question remains above the fold.

This combination best satisfies the representative journey without turning the product into a resource-panel launcher, and it preserves the explicit exclusion of discretionary manual order entry.

## Resolution acceptance criteria

Once the human verdict is recorded, issue #30 can close when its resolution:

1. names the selected base shell and any scoped borrowed elements;
2. records why the losing full-shell structures were rejected;
3. defines persistent task context and explicit task-switch semantics;
4. defines forward, back, and cross-workspace navigation behavior;
5. defines wide, compact, and narrow-screen shell behavior;
6. keeps runtime health and freshness visible but subordinate to the research task;
7. preserves read-only diagnostic context and excludes all discretionary manual order capability;
8. points to the prototype branch and this evaluation as primary-source evidence.
