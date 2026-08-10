# Issue #117 source-seam acceptance evidence

This record is bound to implementation commit
`514ac791396ef9beebf29989b3bf817b3bf6ca0d`, based on the closed #114
baseline `ff9da228fadecb59dac0954a29308d6c2d3d71be`.

Status: the #117 implementation and supported-data-copy Test Seam are
complete. This is not a formal release, does not start the 14-day observation
window, and does not claim installed-binary, clean-Windows, or formal renderer
certification.

## Implemented contracts

- Versioned machine-readable daily ledger, rollback evidence, and legacy
  inventory JSON schemas.
- Strict validator and collision-safe collector with reproducible UTC date,
  build, package, route, artifact, metric-set, and reset identities.
- Complete-day and formal-day qualification, fixed 14-consecutive-day
  calculator, hardware/software lane coverage, immutable active-window metric
  identity, interruption/reset history, and restart behavior.
- Exact reset derivation for unresolved Sev1/Sev2, forced rollback,
  loss/corruption/destructive migration, identity or TaskHandle continuity,
  duplicate diagnostic work, bad old-generation/duplicate/lower-revision
  acceptance, reopen failure, manual trading, WebEngine, security/redaction,
  and V2-caused forced legacy fallback.
- Source-level candidate to retained Widgets to recovered candidate rollback
  evidence. The retained Widgets execution directly opens the supported data
  copy and returns only the exact eight artifact identity classes, TaskHandles,
  order-state hash/count, panel inventory, and clean-exit status.
- Cross-validator tying daily ledgers to the exact candidate/Widgets artifact
  hashes, dependency lock, source commit, rollback evidence, and legacy
  inventory.

## Test evidence

- `57 passed in 0.49s`: ledger and rollback validator/collector contracts,
  malformed/incomplete/selectively omitted/non-formal/RC input, all reset
  reasons, fixed 14-day calculation, secret and transaction-payload rejection,
  JSON key-order independence, and Windows-safe ledger filenames.
- `2 passed in 119.43s`: fresh initialization; copied Wave 3 persistence and
  bookmark compatibility; deterministic/idempotent reopen; exact durable
  identity graph; and candidate to Widgets-on-copy to candidate recovery. This
  replay injected the actual implementation commit and dependency-lock SHA
  recorded in `acceptance-summary.json`.
- `43 passed in 252.32s`: package manifests, checksums, retained Widgets source
  entry, archive, and rollback contracts.
- `140 passed in 165.75s`: exact #114 durable identity, remount, disconnect,
  generation/revision quarantine, retry, reopen, and clean-exit suite.
- `69 passed in 15.34s`: persistence migration, System Health observational
  behavior, and release-evidence identity/checksum regressions.
- Strict isolated mypy passed for seven #117 source modules; all three JSON
  schemas parsed successfully; Python compilation passed.
- Independent Standards and Spec reviews ended with no residual actionable
  findings.

## Migration and rollback evidence

Fresh initialization reached persistence revision
`0021_diagnostic_selection_dependency_invalidation`; a second initialization applied no
revision. The copied formal Wave 3 input remained readable across two opens.
The bookmark migration from 1.0 to 2.0 was deterministic and idempotent and
preserved the exact task and focus identities. #117 adds no product-persistence
table, so the copied persistence needs no destructive schema rewrite.

The reversible drill used the same source identity and dependency lock for the
candidate and retained Widgets source artifacts. Strategy, Recipe, Task,
Campaign, Run, Evidence, Finding, Manifest, and TaskHandle identities matched
at all three stages. Order-state hashes matched, yielding zero order mutations.
All three stages exited cleanly. This proves the supported source seam only;
`installed_binary_gate_verified` remains false.

## Safety and legacy state

The ledger validator rejects credentials, tokens, database URLs or paths, SQL,
commands, raw tracebacks, privacy data, and market/account/order/fill payloads
without echoing the unsafe value. No manual-trading or WebEngine capability and
no System Health remediation path were added.

The canonical inventory contains eight retained Widgets routes: diagnostics,
account, market, agents, arena, leaderboard, clock, and orders.
`legacy_route_count` is 8; every stakeholder exit record and route rollback
record remains unset; deletion authorization is false; no route, panel, or
Widgets shell was deleted.

## Explicitly unverified or blocked external gates

- Installed Wave 4 and retained Widgets binaries on a clean Windows machine.
- Formal hardware D3D11 and installed software renderer lanes.
- Offline Windows certification, remote release artifact, formal publication,
  and the real 14-consecutive-day observation window.
- Full-suite collection is blocked by missing optional `torch` in
  `tests/runtime/test_recurrent_ppo_adapter.py` (1994 tests collected before
  the collection error). Excluding that file, the suite later hit an existing
  integration-gate documentation failure after 392 passes, and a non-summary
  run aborted in QML host teardown. These are outside the #117 diff.
- The pre-existing release-candidate file remains `48 passed, 3 failed,
  1 warning in 1093.39s`; failures are the sealed fixture freshness assertion,
  Windows SQLite cleanup handle, and owned-QApplication subprocess/encoding
  case. No installed release gate is claimed.

#117 remains open and parent #107 is untouched. No formal release or legacy
deletion is authorized by this evidence.
