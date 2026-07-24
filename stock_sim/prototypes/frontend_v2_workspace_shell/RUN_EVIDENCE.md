# Diagnostic run monitoring and evidence-interpretation prototype

> THROWAWAY PROTOTYPE — evidence for GitHub issue #32, not production UI.

Question: how should Arena, run monitoring, leaderboard, and Evidence Board become one workflow for understanding a diagnostic result without mixing experiment controls, raw identifiers, live status, returns, and gate tables on one screen?

Three structurally different variants live on one route:

- A — Interpretation Funnel: current research question → run progress and anomalies → Diagnostic Findings → comparison signal and gate context.
- B — Sensitivity Field: scenario-replica comparison and sensitivity breakpoints are the primary surface; selecting a cell explains the evidence.
- C — Finding Notebook: Diagnostic Findings are the primary index and article; run status, provenance, and leaderboard context become supporting material.

All variants:

- use the already-decided #30 Journey Rail shell;
- preserve Strategy Under Test, Market Scenario, Formal Diagnostic Campaign, Strategy Run, Scenario Replica, Simulation Time, and ViewState revision;
- model Running, Partial, Failed, and Completed/No-Go states without invoking a real backend;
- make `pass`, `fail`, `missing`, and `not_available` distinct;
- keep return ranking explicitly subordinate to evidence and Research Acceptance Lock;
- progressively disclose artifact hash, runner version, source run IDs, source, blocking metrics, and next action;
- contain no experiment mutation and no manual-order capability.

Run from the repository root:

```powershell
python stock_sim/prototypes/frontend_v2_workspace_shell/serve.py
```

Then open <http://127.0.0.1:4173/evidence.html?variant=A&run=completed>.

Use the floating arrows or keyboard `←` / `→` to switch variants. Use the run-state control to inspect Running, Partial, Failed, and Completed behavior. Candidate and finding selections are persisted in the URL.

Evaluation prompts:

1. Can the researcher distinguish “the task finished” from “the evidence supports a research conclusion”?
2. Is the most important failure or sensitivity breakpoint visible before the leaderboard?
3. Can the researcher move from a Diagnostic Finding to its supporting and contradicting evidence?
4. Are missing and not-available evidence treated as debt, not as passes?
5. Does the selected structure remain legible while a task is running, partially available, failed, or complete?
