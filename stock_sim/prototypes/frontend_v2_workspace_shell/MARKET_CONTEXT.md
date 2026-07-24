# Market and Symbol Detail diagnostic-context prototype

> THROWAWAY PROTOTYPE — evidence for GitHub issue #31, not production UI.

The global shell is fixed to the #30 Journey Rail decision. This route compares three local Market/Symbol Detail structures:

- A — Evidence Lens: price path and Strategy Action overlays dominate; the causal evidence chain stays beside the chart.
- B — Temporal Trace: market path, Strategy Decision, order activation, fills, position impact, and health share one Simulation Time axis.
- C — Scenario Universe: a cross-sectional diagnostic table drives a selected-symbol evidence drawer.

All variants:

- enter from Strategy Run `DGN-24-0719-A`;
- keep Strategy Under Test, Market Scenario, Scenario Replica, Simulation Time, and ViewState freshness pinned;
- expose fresh, stale, and disconnected states while retaining the last reliable values;
- progressively disclose order-book and trade detail;
- present orders, trades, accounts, and positions only as read-only diagnostic evidence;
- omit Create Instrument, Buy/Sell, discretionary order editing/cancellation, and a global watchlist workspace.

Run from the repository root:

```powershell
python stock_sim/prototypes/frontend_v2_workspace_shell/serve.py
```

Then open <http://127.0.0.1:4173/market.html?variant=A>.

Use the floating arrows or keyboard `←` / `→` to switch variants. Use the Fresh/Stale/Disconnected control to compare ViewState health behavior. In variant C, select a row to change the symbol while preserving the Strategy Run context.

Evaluation prompts:

1. Does the page explain why the Strategy Under Test selected this symbol?
2. Can a researcher trace Strategy Decision → Signed Share Order → activation → fill → position impact?
3. Are K-line, order book, and trade data subordinate to the diagnostic question rather than treated as trading affordances?
4. Is stale or disconnected data impossible to mistake for current data?
5. Which information should be immediately visible, and which should remain progressively disclosed?
