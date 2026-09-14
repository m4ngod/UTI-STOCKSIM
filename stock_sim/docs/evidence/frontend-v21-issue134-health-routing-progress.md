# Frontend V2.1 #134 — legacy health overlay checkpoint

Date: 2026-09-14. This is implementation progress, **not ticket acceptance**.
The full #133–#171 goal remains active. No remote publication, main merge,
release, production-default switch or system configuration change was performed.

## Source and scope

- Fixed predecessor: `b662dc73f9c7c5620da605f39e6890a19262c517`.
- Initial implementation: `4c96d10432818dbf5a7146a14e9ee70fe4b69bc2`.
- Missing-health review fix: `e75ce98080cf6458d0057d3591e15b020b0889a3`.
- Isolated CJK evidence fixture: `5dd9bd98ab6455937e51e5a394c6b278bda8fefe`.
- Specification: published #132 v1.0, especially D14/D15; source SHA-256
  `A4D64B033E55DCD5203B6204AA01932501EEBD06AE55BAB45EDF2FCDF48C839E`.
  ADR0038 requires explained health-parent recovery and untouched old bookmarks;
  ADR0039 requires usable keyboard reading at logical size/text-scale limits.

The public `JourneyWorkspaceHost.activate_route(SYSTEM_HEALTH)` now opens the
read-only overlay in the opt-in research shell without replacing the active page
or its observation. A selected exact Run Monitoring context can receive completion
while the overlay is open. Escape closes it and returns focus to the top trigger.
This particular completion test uses deterministic fake events, **not proof of
real background execution continuity**.

When the initial route is legacy health, an available non-health page explicitly
supplied in the typed bookmark can be retained. A bookmark whose only route is
health contains no reliable parent and falls back to Combination Library with an
explanation. No parent is guessed from arbitrary resource IDs or a latest-version
lookup. If Combination Library itself is unavailable, the existing available-route
fallback is explained. Startup opens the overlay only once; hide/show does not
replay a dismissed health entry. A missing health Feature keeps the safe page and
explicitly explains why no overlay was opened; it is not reported as EXACT.

The research host no longer invokes the legacy Journey bookmark sink. This prevents
its translated page/focus state from overwriting Wave 3/4 navigation. The default
six-route host still writes through its original sink. This is an opt-in host
write guard, **not completed generation-3 durable migration**: the new shell's
navigation is currently session-only, and the existing AppContext legacy decoder
and its version-1-to-2 normalization are not changed or certified here.

The health facts TextArea exposes its actual read-only state through QAccessible
and supports keyboard selection/navigation. Tab and Shift+Tab cycle between facts
and Close; Ctrl+End reaches the real end, with the cursor inside the viewport.
No health command, task lifecycle operation or new Feature Interface was added.

## Red/green and visual evidence

Reports live under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.
Tests use the already agreed public AppContext/Feature, Host and QML-input seams.

| Behavior | Red | Green |
| --- | --- | --- |
| Old health entry must not replace the observed run. | `health-route-red.xml`: 1 failure, active route incorrectly became health. | `health-route-green.xml`: 3 health cases passed. |
| Initial health uses a safe parent or explained Combination fallback. | `health-startup-red.xml`: 2 failures. | `health-startup-green.xml`: 5 health cases passed. |
| Opt-in routing must not write to the legacy bookmark sink. | `health-bookmark-red.xml`: 2 failures, 2 old-entry passes. | `health-bookmark-green.xml`: 4 live/fake × research/legacy cases passed. |
| Read-only keyboard reading must be accessible. | `health-keyboard-red.xml`: 2 missing QAccessible readOnly failures; after fixing that, `health-keyboard-cursor-red.xml`: 2 inert Ctrl+End failures. | `health-keyboard-green.xml`: 2 passed. |
| Missing health must be explained even with a safe parent. | `health-unavailable-review-red.xml`: 2 failures. | `health-unavailable-review-green.xml`: 13 health cases passed. |

Initial source regression `health-routing-full-regression.xml`: 130 passed in
90.98 s (23 shell, 31 resource, 25 Journey Rail, 30 old health, 21 exact-query
contract cases). SHA-256:
`C03ABBF22E4F66D09EA16940CD6642ABBAAF5E6CA5D03251AF1A6899BD3DC6A0`.
The separate initial exact-inspector run passed 39 cases in 15.43 s.
These initial reports precede the missing-health fix and are not the final report.

Final source `5dd9bd9`: `health-routing-reviewed-full-regression.xml`, **171 passed
in 104.19 s**, no failures, errors or warnings. Counts: 25 research shell, 31
resource pages (including reopened sealed live evidence), 25 legacy Journey Rail,
30 legacy health route, 21 exact-query contracts, 39 exact-inspector integration.
SHA-256: `6D0F3DE024859D32EE64C0CF177AF95C2474093E7A33ABE4E1F3D5E018AB76BC`.
The isolated font loading is included, so this result is not dependent on a
different fixture running first to populate the font database.

The first isolated screenshot run produced missing-glyph boxes because no font
was enumerated. Its `health-keyboard-frames/` images and report are retained for
diagnosis, **not accepted as visual or representative font-layout evidence**.
The research fixture now loads the same existing CJK font as the other QML fixtures
when offscreen enumeration is empty. Loading an application font is confined to
the test process; it does not install a font or modify Windows preferences.

`health-keyboard-readable-frames.xml`: 2 passed in 1.90 s; SHA-256
`9FD7D6C02918CB605BB9D84C4BBCB370B9E6D7BEB67EBE2A0A376AAAB5A0AFB1`.
Both images in `health-keyboard-readable-frames/` were inspected: 1426×786/text100%
and 960×480/text200%, DPR1. Chinese is readable; the text end and Close remain
inside the client. This is offscreen Software QML/QAccessible evidence, not native
Windows UIA/Narrator, system text-scale, DPI, Direct3D11 or full visual acceptance.

## Independent review

### Standards

Fixed initial range: `git diff b662dc73f9c7c5620da605f39e6890a19262c517...4c96d10432818dbf5a7146a14e9ee70fe4b69bc2`.
One hard-standard P2: with a safe parent but no health Feature, startup silently
reported EXACT without opening the requested overlay or explaining the missing
capability. This violated ADR0038's explained read-only fallback. It was reproduced
and fixed. Follow-up range
`git diff 4c96d10432818dbf5a7146a14e9ee70fe4b69bc2...5dd9bd98ab6455937e51e5a394c6b278bda8fefe`
was independently rechecked: P2 resolved; no new hard-standard issue or concrete
baseline smell. The reviewer inspected the 13-case local report but did not rerun
tests or certify the whole ticket.

### Spec

One P2, independently identifying the same missing-capability explanation under
D15. The fixed branch retains the safe page/existing recovery reason while
explicitly explaining that health observations are unavailable and no popup
opened. The reviewer confirmed it resolved on the same follow-up range, with no
new scope deviation. This was a read-only review, not an independent test rerun.

Summary by axis: Standards 1 hard-standard P2 resolved, 0 outstanding; Spec 1 P2
resolved, 0 outstanding. Their counts are separate, not two different defects.

## Remaining work

Do not close #134 on this checkpoint. Real application-owned execution and late
completion across observation disposal, full exact-context health updates/clearing,
generation-3 bookmark persistence and broader focus recovery, live empty/error/
waiting states, native per-page accessibility/reflow, normal/package entry and
startup gates remain. The previous startup measurements bind to older `6d33e71`
and exceed 750 ms; they are neither current-source nor formal acceptance passes.
