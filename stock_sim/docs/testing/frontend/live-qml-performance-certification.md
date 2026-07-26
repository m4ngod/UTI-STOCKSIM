# Frontend V2 live-QML performance certification

Issue #45 certifies the Wave 0/1 Run Monitoring and Evidence & Findings
vertical slice against the hard release gates inherited from #29, #34, and
#35. It does not redefine those decisions.

## Certified production seam

Both renderer lanes exercise the same in-process path:

`EventBridge` → live Feature Adapters → internal Qt Adapters → centralized
`JourneyWorkspaceHost` → QML scene-graph `EvidenceChart`.

The renderer receives a deterministic 4,000-point viewport sample and three
overlays. The immutable 100,000-point evidence source remains outside the
renderer. Revision-only updates reuse the existing immutable chart geometry;
they do not move calculation into QML or mutate full-fidelity evidence.

No third external Seam, separate UI process, `QQuickPaintedItem`, pyqtgraph,
WebEngine, or Widgets chart is permitted.

## Locked fixture and gates

Each independent process uses:

- 100,000 source points;
- 4,000 visible points;
- three overlays;
- 50 candidate rows;
- a 50 ms source cadence;
- a 20 fps chart paint cap;
- one continuous 60-second measurement window.

Hardware must report `Direct3D11`; fallback must report `Software`. Each lane
must satisfy:

- event-to-visible p95 at or below 20 ms;
- input p95 at or below 16 ms;
- usable state at or below 750 ms;
- no main-thread interval above 50 ms;
- peak process working set at or below 180 MiB;
- strictly increasing accepted QML revisions;
- a final completed or failed revision visible within 100 ms.

## Measurement protocol

The report retains the exact protocol in its `measurement` object.

- Usable-state time starts immediately before `QApplication` construction,
  after the locked runtime has loaded.
- Event latency starts when the production `EventBridge` accepts a batch.
  Immediately before scene-graph synchronization, the harness snapshots the
  accepted QML revision; latency ends only when `QQuickWindow.afterRendering`
  confirms that exact synchronized revision completed a frame. Property-change
  notification alone is not treated as visible output.
- Input latency starts when a Return key event is posted to a real QML tab and
  ends when that event commits the corresponding internal Adapter state. QML
  frame visibility is measured separately by the event-to-visible probe.
- The main-thread heartbeat is sampled every 5 ms.
- Win32 `WorkingSetSize` is sampled every 100 ms.
- Garbage collection and `EmptyWorkingSet` run before the explicit start
  marker. This removes cold initialization pages from the continuous-run
  window without hiding their cost: usable-state timing still includes
  application and QML initialization. Any page needed by the 60-second
  workload returns to the sampled working set.
- The host is 1,280 × 800 and the duration clock is `perf_counter_ns`.

Changing any protocol field invalidates the report.

## Reproduce and retain evidence

First commit all implementation and test changes. The resulting immutable
commit is the measurement source. Do not change production or harness code
after measuring; if it changes, create a new source commit and rerun both
lanes. Certifying commands reject a mismatched `HEAD`, any tracked worktree or
index change, and any untracked file other than the four named evidence
artifacts passed to the command. This check runs before either renderer or the
aggregate safety audit.

Run the renderer processes separately:

```powershell
python -m stock_sim.release.frontend_v2_performance run-lane `
  --lane hardware `
  --duration-seconds 60 `
  --source-commit <source-commit> `
  --output <evidence-directory>\hardware.json

python -m stock_sim.release.frontend_v2_performance run-lane `
  --lane software `
  --duration-seconds 60 `
  --source-commit <source-commit> `
  --output <evidence-directory>\software.json
```

Bind those reports to a fresh #44 no-manual-trading audit:

```powershell
python -m stock_sim.release.frontend_v2_performance certify `
  --project-root . `
  --source-commit <source-commit> `
  --hardware-report <evidence-directory>\hardware.json `
  --software-report <evidence-directory>\software.json `
  --safety-output <evidence-directory>\no-manual-trading.json `
  --output <evidence-directory>\certification.json
```

The aggregate is certified only when both lane files are independent,
checksum-bound to the same source and exact dependency lock, all thresholds
pass, every raw timing sample reproduces its stored digest and
count/p50/p95/max summary, and the fresh safety report passes. Retain all four
JSON files under:

`docs/testing/frontend/evidence/issue-45/<source-commit>/`

Commit only those evidence files and documentation after the measured source
commit. Link the source commit, evidence commit, four raw reports, test
results, and review result from issue #45.

## Invalidation and safety

Any Python, PySide6/Qt, NumPy, or Nuitka lock change invalidates affected
evidence. A fixture, measurement protocol, renderer, sampling policy, source
commit, safety policy, or production-path change also requires a complete
rerun of both lanes and certification.

Market, account, position, order, and fill information remains immutable
diagnostic context. The fixture, instrumentation, QML object tree, telemetry,
and optimization paths expose no order entry, manual order/cancel/replace, or
generic transaction dispatch. Any such capability blocks certification.
