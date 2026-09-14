# Frontend V2.1 #134 — native navigation and view disposal during real execution

Date: 2026-09-15 (Asia/Shanghai). Incremental evidence for #132/#134, not ticket
acceptance. Production source: `8507b6dac46a1acdb7c9a6f90d6e65b12192c991`.
No production code or test changed for this observation.

## Fixture and lifecycle boundary

The production `MainWindow` receives all six Features from the public live
`AppContext`. The existing real-application fixture creates local synthetic
Scenario inputs and a persisted task, validates its configuration and approves
revision 2 through the public commands. The initial Scenario inventory is warm.
After 90 seconds, the fixture caller submits exactly one public
`StartFormalDiagnosticCampaign` command on a worker thread.

A gate holds the first actual `decision` invocation at the strategy-host boundary.
After release it delegates to `EmbeddedProductionPTradeStrategyHost`; the
calculation and result are not faked. The timer and host gate belong to the source
fixture, not product UI controls or a new automatic Experiment scheduler.

All navigation, selection, health-overlay input and window closure use official
Computer Use `sky`. The launcher only configures the source, builds the production
window and records displayed Qt properties. The session is
`live-execution-1426x786-text100-d3d11-01`, under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.
Measured client is 1426x786, text scale 100%, Direct3D11, DPR 1.

The fixture deliberately retains `AppContext` after the last native window closes
and releases the held host then. This isolates the required view/application
lifetime boundary. It is not evidence that an installed application continues
after its normal full-process shutdown. The production `MainWindow.closeEvent`
still disposes its observation adapter. The context is closed only after the
command result and real execution audit are checked.

## Native sequence and exact context

The native session selects the second Scenario and then opens the approved task
in Lab. While the actual host invocation is held, navigation to Archive succeeds
and shows its honest empty selection. Returning to Scenario displays the waiting
status and retains all 28 objects and the exact previously selected resource.
The full UIA Scenario document text equals its pre-start value.

- Task: `diagnostic-task-964f98fad2b6dcd59ab6c254`, approved revision 2.
- Configuration:
  `sha256:325f7f1c3abfdf68f794e4c6ed45d9974ebd2e9e1dde676ffb12f29b48ef0b7a`.
- Selected Scenario: `campaign-case-21fe58b8ce731d8af34d9351`.
- Recipe: `recipe_version_75c4fa716bbe05216bc61dd6efc79ee097fdece52f56f0c7bc7932d523560c36`.
- Recipe hash: `177a5437162b155d81aa328680261e71b0e485fc346070d8700cd631808bf50d`.
- Reference path: `56a4333f6438b998b3ed1660cb71f72e5508932963befaf88806035577aeadf1`.
- Full Scenario detail SHA-256:
  `BE796AAD5C9C186651F62271E498C529D3196954B2D79A59AD780A903A1A78E4`.

The health overlay opens while the command is still pending. Its UIA document
reports `context exact_match` for the same task revision. Escape returns a visible
outline to the health trigger; separately labelled Qt telemetry records that
focus transition with the command still pending and the host unreleased. Health
sampling is disabled and its fixture data source is historical/stale; this does
not certify live health freshness or native UIA focus properties.

Native Alt+F4 then closes the view. The close event records `command_pending=true`,
`host_entered=true`, `host_expired=false` before releasing the gate. The public
command subsequently succeeds for that exact task and Campaign. No active work
was canceled by page navigation, the overlay or disposing the view.

## Real result and persisted audit

Campaign `diagnostic-campaign-663f3eff12dfca823a11052e` has exactly one completed
case after the first public start. The task remains `running` at revision 2;
this is not full Campaign completion. Both actual members of that completed case
have host adapter audit `ptrade-embedded-production-host.v1`:

- `strategy-run-178e28e79ecab77a4cb3437a`
- `strategy-run-83a2b83dfe40484ab25e130b`

After clean shutdown, a readonly database query confirms one task, one Campaign,
two strategy Runs, one create command, three mutation commands (validation,
approval, start), one validation, one approval and one task/Campaign handoff.
The process exits with code 0 and the final official window inventory is empty.

`audit_live_execution.py` cross-checks the source identity, native view-close and
host-release order, pending command during the observed routes/overlay, exact
Scenario text retention and real persisted result. There is no gate expiry or
audit error. This complements the existing integration case
`test_real_start_completes_after_page_switch_health_overlay_and_view_disposal`.
No duplicate regression or unrelated repeat suite was added for the evidence.

## Artifacts and acceptance limits

`live-execution-artifact-manifest.json` records 11 files, including the launcher,
audit, database, observation logs and four screenshots. SHA-256 references:

| Artifact | SHA-256 |
| --- | --- |
| `observe_live_execution.py` | `A5ECF9BC9EFD36375CC329AEFDD03898286ACF3EC28FE116EE2C43013594473A` |
| `windows-uia.jsonl` | `A17DCDBBABDA15699B785C723CD91696D16BF207014353DF4DCD45E07E9C7DCC` |
| `product-observations.jsonl` | `927367BFC659141C6DC2B2A9C57A919A0AEB0C45E7394D9B61782FCF6C3F4259` |
| `live-execution-audit.json` | `062454F0B55A66CB5DEBDB0128C624E06D044366DA4916FF77086A489AD51267` |

Screenshots: `approved-task.png`, `held-scenario-retained.png`,
`held-health-exact-task.png`, `held-health-return.png`. Native UIA records use
settled observations where immediate navigation trees lag the screenshot.
Their focused-element field remains unreliable; the earlier readonly-property
CacheRequest failure is also unresolved. Neither native property is a PASS.

Together with the [retained live recovery observation](frontend-v21-issue134-native-live-recovery.md),
this closes the previously missing native real-source recovery and pending-work
navigation/view-disposal examples. It does not certify every layout/state
combination, remount during a held command, installed shutdown behavior or full
Narrator/physical-DPI/A41 gates. #134 remains OPEN and the full implementation goal
remains ACTIVE. The prior 112-case affected regression is unchanged.
