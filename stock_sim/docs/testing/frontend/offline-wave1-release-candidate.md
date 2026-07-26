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
