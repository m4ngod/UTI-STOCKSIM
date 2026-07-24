# Frontend V2 workspace shell prototype

> THROWAWAY PROTOTYPE — this is evidence for GitHub issue #30, not production UI.

Question: which workspace shell best preserves a Strategy Diagnostics Researcher's task context across Strategy Library → Scenario Lab → Diagnostic Tasks → Run Monitoring → Evidence & Findings → System Health without becoming a panel launcher?

Three structurally different variants live on one route and are switched with `?variant=A`, `?variant=B`, or `?variant=C`:

- A — Journey Rail: persistent workflow rail, active workspace, pinned diagnostic context.
- B — Focus Ribbon: horizontal journey ribbon, one dominant task surface, collapsible context dock.
- C — Research Chronicle: task index plus an audit-oriented chronological research document.

All variants use the same deterministic in-memory prototype state. They contain no backend mutations and no manual order capability.

The evidence matrix and recommended composition are recorded in [EVALUATION.md](./EVALUATION.md).

Issue #31 extends the selected Journey Rail shell with a Market/Symbol Detail route. See [MARKET_CONTEXT.md](./MARKET_CONTEXT.md) and the [Market evaluation matrix](./MARKET_EVALUATION.md).

Issue #32 extends the same shell with a diagnostic run monitoring and evidence-interpretation route. See [RUN_EVIDENCE.md](./RUN_EVIDENCE.md) and the [run evidence evaluation matrix](./RUN_EVALUATION.md).

Run from the repository root:

```powershell
python stock_sim/prototypes/frontend_v2_workspace_shell/serve.py
```

Then open <http://127.0.0.1:4173/?variant=A>.

Evaluation prompts:

1. Can you always answer “which Strategy Under Test, Market Scenario, Strategy Run, and evidence context am I looking at?”
2. Can you move forward and backward in the diagnostic journey without losing task context?
3. Is switching between diagnostic tasks explicit enough to prevent accidental cross-run interpretation?
4. Are runtime health and data freshness visible without dominating the research task?
5. Does the shell stay useful at compact information density?
