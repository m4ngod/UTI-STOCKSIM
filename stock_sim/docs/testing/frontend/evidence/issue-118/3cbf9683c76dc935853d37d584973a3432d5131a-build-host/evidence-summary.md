# Issue #118 build-host candidate evidence

This evidence is bound to source commit
`3cbf9683c76dc935853d37d584973a3432d5131a` and the schema-3 production
dependency/toolchain lock. It records a successful production build and
package-assembly verification only. It is **not** clean-offline Windows
installed certification and does not make a release claim.

## Final archives

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `qml-journey-3cbf9683c76d.zip` | 158,210,835 | `39a2362b55562851c9adf3458a5a568064575b09ffd3fddf660281ce80c0533c` |
| `widgets-rollback-3cbf9683c76d.zip` | 145,315,837 | `a77c9f33b4d5aa600223034f412a7e0cab7236ebfb84fd903006d3976b5dbe50` |

The archives remain outside Git. Their host-specific absolute locator is
intentionally omitted; names, sizes, hashes, package trees, and the external
canonical summary/report hashes are bound by `build-host-verification.json`.

## Locked build identity

- Python 3.11.9; PySide6/Qt 6.9.1; NumPy 2.3.1; Nuitka 4.1.3.
- MinGW64 GCC 15.2.0; compiler-tree file count 11,602.
- Toolchain identity:
  `sha256:dea775b6fa19a4d1967be09ed4630503cd0480d87931869c1fe79076807129d0`.
- QML distribution: 2,142 files, 446,268,298 bytes,
  tree `sha256:7cd68d9b1c79c304cc11d56a1970c30cf1669d15f61ca916e2c6a262009aada9`.
- Widgets distribution: 1,743 files, 405,352,676 bytes,
  tree `sha256:f056bd6bbe639a876ee31771e197245ed7eb0968a14aa4e4f6656359d511a074`.
- All 3,885 distribution entries were independently recomputed: zero
  missing, mismatched, or duplicate paths.

## Package-assembly gates

- QML package delta: 40,915,622 bytes; limit: 52,428,800 bytes.
- WebEngine payload count: zero.
- Hardware assembly smoke: Direct3D11, six routes, zero errors, zero manual
  trading actions, clean exit.
- Software assembly smoke: Software, six routes, zero errors, zero manual
  trading actions, clean exit.

These package-assembly results do not substitute for installed evidence. No
performance waiver is applied to build-host evidence.
