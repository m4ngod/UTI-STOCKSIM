# Frontend V2.1 #134 — Microsoft native property observation

Later correction: [catalog native remediation](frontend-v21-issue134-catalog-native-remediation.md)
resolves the focusability, committed-selection and mouse/keyboard return defects
on subsequent source commits. This document preserves the original observations.

Observed 2026-09-15, 12:47–13:10 Asia/Shanghai, source
`5ad64b6e281855bb95f82fcc7c9434d05bbc5803`. This increment establishes a supported
native property observation path. It also exposes a remaining catalog state
inconsistency, so it does **not** close #134 or the full #132 / #133–171 goal.

## Official tool and provenance

The user explicitly authorized installing Microsoft Accessibility Insights for
Windows and checking StockSim. The official v1.1.2924.01 MSI was obtained from
[Microsoft's release](https://github.com/microsoft/accessibility-insights-windows/releases/tag/v1.1.2924.01).
The 8,732,672-byte file has SHA-256
`BF4DE9AC631BDAC8A6CD5F5E7963BC6F9C1BC6261371AE7CD7170531CA6BA9A5`.
Authenticode verification returned `Valid`, signer Microsoft Corporation,
timestamp signer Microsoft Time-Stamp Service. The user handled the Windows
elevation prompt; the final MSI process exited 0. Installation logs retain the
earlier path and insufficient-privilege failures separately.

Only official Computer Use `@oai/sky` drove StockSim and the Microsoft inspector.
No custom UIA reader, alternate input injector or UIAccess configuration was used.
The installed executable is
`C:/Program Files (x86)/AccessibilityInsights/1.1/AccessibilityInsights.exe`.

The unchanged observation launcher invoked the public
`setup_frontend_entry.main --research-shell` entry with isolated SQLite. Actual
client size was 960 × 540, Software renderer, text 100%, DPR 1, PID 293596.
Each accepted inspector record identifies that PID and the `qwindows.dll`
provider. Qt telemetry independently records source, dimensions and input
sequence; it is explicitly **not** the native property oracle.

## Native results

Values below were read from Microsoft's Properties / ValuePattern display,
with the matching target name and native AutomationId retained in raw records.

| Target / AutomationId suffix | Native result | Assessment |
| --- | --- | --- |
| `researchHealthFacts` | `ValuePattern.IsReadOnly=True`, `HasKeyboardFocus=True`, `IsKeyboardFocusable=True`, `Edit(50004)` | Readonly and focused text confirmed; repeated with frozen inspector and same-screen visible ValuePattern. |
| `researchAssetDetails` | Same three Boolean values, `Edit(50004)` | Exact-version/identity/limitations text is natively readonly. This sample displays the pre-selection explanation. |
| `researchScenarioPageDetails` | Same three Boolean values, `Edit(50004)` | Shared resource details are natively readonly in the real-empty Scenario state. |
| `strategyLibraryRouteNavigation` | `HasKeyboardFocus=True`, `IsKeyboardFocusable=True`, `TabItem(50019)` | Native navigation focus confirmed. |
| `researchHealthCloseButton` | `HasKeyboardFocus=True`, `IsKeyboardFocusable=True`, `Button(50000)` | Native popup entry focus confirmed. |
| `researchHealthButton`, after Escape | `HasKeyboardFocus=True`, `IsKeyboardFocusable=True`, `Button(50000)` | Native modal return confirmed; subsequent Space reopened the popup without any intervening readonly guard. |
| Catalog row 2 of 2, `researchAssetList.ItemDelegate_QMLTYPE_3_QML_14` | `HasKeyboardFocus=True`, **`IsKeyboardFocusable=False`**, `ListItem(50007)` | Remaining native state inconsistency. Direction-key focus and both native values are retained; the False value was separately made visible in the frozen inspector. |

The catalog row's full native name includes
`QuentX Live Minute Scenario-native · quentx-live-minute-scenario-native.v1`,
position 2 of 2. Its `SelectionItemPattern.IsSelected=False` was measured before
Enter committed the choice; keyboard cursor and committed selection must not be
conflated. Enter did choose that exact version and visibly focused the read
button. However, the inspector highlighter remained on the list trigger for
that transition. A native return-property PASS is not claimed for it.

## Observation discipline and exclusions

The documented [keyboard workflow](https://accessibilityinsights.io/docs/windows/reference/keyboard/)
uses Shift+F9 to switch between the target and inspector, and Shift+F5 to pause
UIA tree updates. After selecting the StockSim target, pausing preserves its
native snapshot while Properties / ValuePattern are examined. `HasKeyboardFocus`
here describes that captured target state, not ongoing foreground focus while
the inspector itself is active.

Immediate official Computer Use text snapshots sometimes lagged the inspector
screenshot or were null. Accepted records therefore require settled identity,
PID, property rows and matching visible target. The first attempt to scroll
Properties while live followed the Computer Use cursor overlay instead of
StockSim. Its misleadingly named `health-facts-readonly-visible.png` is retained
but **excluded**. The early `health-escape-trigger-native-focus-settled` text still
described health facts despite the trigger screenshot; the subsequent
`health-escape-trigger-paused-verified` record supersedes it.

The original `sky.focused_element` conflict and CacheRequest failure are not
declared repaired. The successful route reads the Microsoft inspector's native
results, using official Computer Use to operate and capture its UI. Ctrl+S
produced no save dialog in this inspect mode; no `.a11ytest` export is claimed.

## Retained evidence and boundary

Scratch root: `F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.
Session: `native-insights-software-01/`, including full `inspector-uia.jsonl`,
`product-uia.jsonl`, labelled non-UIA telemetry, screenshots and isolated data.
The product closed normally, its bridge released, launcher exited 0 and a
settled official window inventory contained no StockSim window.

`audit_accessibility_insights.py` only parses saved evidence and hashes files;
it does not query or automate Windows. Its audit accepts **9 property records**
from 19 retained inspector records, covering **3 distinct readonly controls**.
The manifest hashes 23 files. `accessibility-insights-audit.json` SHA-256:
`00de68dcf5aadbfa75f8ee6b233e1dfcf23555040bf9713a1aaa7eabf1a8ff01`.

Principal screenshots are `health-facts-paused-valuepattern-verified.png`,
`asset-details-paused-valuepattern-verified.png`,
`scenario-details-paused-valuepattern-verified.png`,
`health-escape-trigger-paused-verified.png`,
`catalog-second-row-native-focus-verified.png` and
`catalog-focusable-false-visible-verified.png`.

The previous lack of a supported native readonly/focus reader is resolved for
these observed targets. The catalog focusable-state inconsistency now has a
concrete native reproduction and needs diagnosis, correction where appropriate,
and a repeated official observation. Other unsampled native transitions remain
unverified. Full Narrator, physical-DPI, installed A41 and later implementation
tickets retain their separate gates. This increment changes evidence only;
the earlier 112 affected tests are historical evidence, not a new test run.
