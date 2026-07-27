# Offline Wave 1 release-candidate certification

This gate certifies the Wave 0 Foundation plus the Wave 1 Run Monitoring and
Evidence & Findings vertical slice. It inherits the Interface, migration,
accessibility, safety, performance, and packaging decisions in issues #29,
#34, and #35.

The release remains a read-only Strategy Diagnostics workspace. It contains
no discretionary transaction controls. Orders and fills are retained only as
diagnostic context, and all legacy routes remain available.

## Source and toolchain boundary

Run every certifying command from one clean Windows 11 x64 checkout. Record
the full `HEAD` commit and use it for every `--source-commit` argument. The
locked toolchain is:

- Python 3.11.9
- PySide6 6.9.1
- Qt 6.9.1
- NumPy 2.3.1
- Nuitka 2.6.8

Any source or locked dependency change invalidates the build and its T08,
T09, and T10 evidence.

## Evidence sequence

1. Run the focused T08 accessibility suite with `--junitxml`. The XML must
   include the keyboard, Narrator, chart alternative, 200 percent scaling,
   reduced-motion, contrast, remount, and hardware/software renderer
   sentinels.
2. Run both 60-second T10 renderer lanes and certify their raw reports. The
   T10 certifier writes a fresh T09 no-manual-trading report for the same
   commit.
3. Build the QML Journey and Widgets rollback packages with
   `python -m stock_sim.release.frontend_v2_packaging`. The command rejects a
   dirty or mismatched source checkout.
4. Run `scripts/run_frontend_v2_windows_sandbox.ps1` against the checksummed
   QML archive. The generated Sandbox configuration disables networking,
   maps the archive and validation script read-only, and maps only the
   evidence directory read-write.
5. Certify the returned `clean-room-report.json` with
   `--certify-clean-room-report`, `--accessibility-junit`, and
   `--performance-evidence-dir`.

The final certification recomputes the T10 aggregate from raw hardware,
software, and T09 reports; rejects missing T08 coverage; verifies the
installed archive checksum; and retains all mandatory gate inputs under
`evidence/gates`.

## Installed black-box journey

Both renderer lanes must prove this sequence through the production
EventBridge and live Feature Adapters:

1. launch into an existing active Strategy Run;
2. render Run Monitoring;
3. render Evidence & Findings;
4. disconnect while retaining the last reliable read-only state;
5. reconnect on a new source generation;
6. render the completed terminal revision;
7. exit without runtime errors or leaked workers.

The report must come from Windows Sandbox as `WDAGUtilityAccount`, show no
Python, compiler, dependency cache, or active network adapter, and contain no
missing module, DLL, QML import, or renderer errors.

## Certified release candidate

The Wave 1 release candidate was certified on 2026-07-27 from source commit
`d4ec8d426b06b64b527eea8ae2861a254f8cde29` on branch
`codex/issue-46-offline-release-candidate`.

- Release tag: `frontend-v2-wave1-rc-d4ec8d426b06`
- Release page:
  <https://github.com/m4ngod/UTI-STOCKSIM/releases/tag/frontend-v2-wave1-rc-d4ec8d426b06>
- Toolchain identity:
  `sha256:0868789918094ea360bf7a636d90a15f655e60725a0c2dd700f4fb05af1eb737`
- Final status: `certified`

### Published offline archives

| Archive | Size | SHA-256 | Stable download |
| --- | ---: | --- | --- |
| QML Journey | 76,060,962 bytes | `sha256:9a810d48b760d0d97a9c52a851f480917887bcf5ab91bc234c302c648c43885a` | [qml-journey-d4ec8d426b06.zip](https://github.com/m4ngod/UTI-STOCKSIM/releases/download/frontend-v2-wave1-rc-d4ec8d426b06/qml-journey-d4ec8d426b06.zip) |
| Widgets rollback | 131,696,670 bytes | `sha256:5bd61586f70905f758d1033f30afe292272a9149c6c29e9dcd6aeaf01eb45f5f` | [widgets-rollback-d4ec8d426b06.zip](https://github.com/m4ngod/UTI-STOCKSIM/releases/download/frontend-v2-wave1-rc-d4ec8d426b06/widgets-rollback-d4ec8d426b06.zip) |

The extracted QML package contains 826 files and 212,892,575 bytes. The
Widgets rollback package contains 1,736 files and 371,881,741 bytes. The QML
package is 158,989,166 bytes smaller than the rollback package, remaining
within the 50 MiB delta gate.

### Mandatory gate results

| Gate | Result |
| --- | --- |
| T08 accessibility and representative journey | 13 passed; keyboard, Narrator, chart alternative, 200 percent scaling, reduced motion, contrast, remount, and both renderer sentinels covered |
| T09 no manual trading | Passed in deterministic-fake and live adapter modes; zero transaction telemetry; orders and fills remained read-only context |
| T10 hardware lane | 60.001 seconds; event-to-visible p95 7.845 ms; input p95 0.601 ms; peak memory 80.211 MiB; zero over-budget stalls |
| T10 software lane | 60.000 seconds; event-to-visible p95 10.953 ms; input p95 0.555 ms; peak memory 36.754 MiB; zero over-budget stalls |
| Offline packaging | QML and Widgets archives built from the same locked source and toolchain; dependency closure and WebEngine exclusion passed |
| Windows Sandbox | Offline install passed with no Python, compiler, dependency cache, or active network adapter |
| Installed black-box journey | Direct3D11 and Software lanes each rendered eight distinct stage screenshots; observed state matched every captured frame; zero runtime errors and clean exit |

### Retained audit evidence

All reviewable evidence is retained under
`docs/testing/frontend/evidence/issue-46/d4ec8d426b06b64b527eea8ae2861a254f8cde29/`.
It includes the final release summaries, complete dependency manifest,
checksums, T08 JUnit XML, raw and certified T09/T10 reports, clean-room report,
hardware/software screenshots, renderer smoke evidence, Sandbox exit code, and
`release-asset-verification.json`. The latter records each GitHub asset ID,
stable URL, uploaded state, server-computed full size and SHA-256, matching
local size and SHA-256, plus byte-identical start, middle, and tail
`206 Partial Content` probes.

The complete Nuitka dependency reports are retained at
`qml-journey/nuitka-report.xml` and
`widgets-rollback/nuitka-report.xml` below that evidence directory. Their
SHA-256 digests are respectively
`sha256:58b4e401d7f12ed77174a77acc464a9bc17e3a5f50559809c42b7b79ad6e7eda`
and
`sha256:3f76bb86c0606a1730b1720e70180ca12e1b5ff2eba1388373d7444dc5b5eb87`,
matching the paths, sizes, and digests recorded by the dependency manifest.
