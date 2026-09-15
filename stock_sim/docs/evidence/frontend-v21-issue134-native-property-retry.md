# Frontend V2.1 #134 — fresh native property retry

Date: 2026-09-15 (Asia/Shanghai). Source:
`11905607ce8057f366bdf40ee14d63092b10c0ad`. The user explicitly requested a renewed
attempt to obtain trustworthy official native observations. This is the first
turn of the resumed audit; previous blocked-run counts are not reused.

## Fresh process and tool session

The unchanged public `setup_frontend_entry.main(['--research-shell'])` ran with
isolated SQLite/artifact/settings inputs through the existing `observe_product.py`.
Actual client and QML size: 1426x786; Software renderer; text100%; DPR1.
All native input and native accessibility reads used the official `@oai/sky`
entry through `node_repl`. The desktop was active and the product was visible.
No alternative native helper or product change was introduced.

Native snapshots consistently named `researchAssetDetails` as `focused_element`
while these targets had visible focus and matching, separately labelled Qt
telemetry:

| Native interaction | Visible / supplementary Qt target | Native reported target |
| --- | --- | --- |
| Initial public entry | `strategyLibraryRouteNavigation` | `researchAssetDetails` |
| Open health | `researchHealthCloseButton` | `researchAssetDetails` |
| Tab into health facts | `researchHealthFacts` | `researchAssetDetails` |
| Escape from health | `researchHealthButton` | `researchAssetDetails` |
| Reset official JavaScript session, import sky again, rediscover and activate product | `researchHealthButton` | `researchAssetDetails` |
| Reopen health by click | `researchHealthCloseButton` | `researchAssetDetails` |
| Escape, with no intervening property probe | `researchHealthButton` | `researchAssetDetails` |
| Space immediately after that return | `researchHealthCloseButton` | `researchAssetDetails` |

The reset removes old JavaScript bindings and observations. It is not evidence
of restarting the underlying native helper or changing its implementation.
These readings do not distinguish an observer defect from a Qt native provider
defect. Correct visible behavior does not certify the native focus property.

## Readonly result and probe side effect

Two same-observed-value `sky.set_value` calls targeted health facts and, after the
tool-session reset, Combination details. Both failed with:

`read UIA value read-only state: 所需属性不在 CacheRequest 中 (0x80070057)`

Neither provides an IsReadOnly value. Fresh reads retain the original displayed
text. The current bundled supported API has no standalone readonly-property getter
or cache-control argument.

The failed Combination probe did move actual focus from the health trigger into
Combination details. Therefore a subsequent Space did not reopen health. The raw
label `fresh-kernel-space-reopens-health` records the intended operation, not a
successful outcome. It is excluded from the return-success evidence. A subsequent
new click → Escape → Space sequence, with a snapshot after every action and no
intervening property probe, did reopen health. Do not treat failed property probes
as having no UI side effects or combine them into an uninterrupted focus test.

## Reproducible result and next observation route

Artifact root:
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/native-properties-resume-1190560-01/`.
There are 12 native snapshots, two exact error records, four screenshots,
supplementary Qt telemetry, and initial/settled post-close inventories. The
immediate post-close inventory still listed the window; the subsequent inventory
is empty and the product process exited 0 with its bridge released.

`audit_native_properties_resume.py` verifies the eight conflicting phases,
unchanged values, both errors, the interrupted versus uninterrupted sequence,
source/geometry/renderer and clean closure. The manifest records 14 session files.
Audit SHA-256: `6A70D2388B3A48EBB0ABE892B164F4D642FBC49B1490C18A6653B134FC6B8951`.

The official [Computer Use guidance](https://learn.chatgpt.com/docs/computer-use)
requires a visible target on the active Windows desktop; that condition was met.
Its current public guidance and [troubleshooting page](https://learn.chatgpt.com/docs/reference/troubleshooting)
do not document a fix for this exact property-cache error. No app, security,
privacy or operating-system configuration was changed.

Microsoft's [Accessibility Insights Live Inspect](https://accessibilityinsights.io/docs/windows/getstarted/inspect/)
provides native UIA property and pattern inspection, including keyboard-selected
elements. Its [official setup instructions](https://accessibilityinsights.io/docs/windows/getstarted/setup/)
require installing the application. The current official app inventory and
checked standard SDK/Insights locations exposed no installed inspector.
Adding that Microsoft application, operated only through official Computer Use,
is a proposed next route subject to the user's tool-scope/install authorization;
it has not been installed or used, and is not a claimed solution or PASS.

#134 remains incomplete with native readonly and focus properties UNVERIFIED.
No production/test code changed; the previous 112-case affected regression remains
the latest such run. No remote issue state changed and no successor was claimed.
