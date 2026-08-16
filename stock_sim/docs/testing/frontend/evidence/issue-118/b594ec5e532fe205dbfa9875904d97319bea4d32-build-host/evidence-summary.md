# Issue #118 build-host candidate evidence

This evidence is bound to source commit
`b594ec5e532fe205dbfa9875904d97319bea4d32` and the schema-3 production
dependency/toolchain lock. It records a successful production build and
package-assembly verification only. It is **not** clean-offline Windows
installed certification and does not make a release claim.

## Final archives

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `qml-journey-b594ec5e532f.zip` | 158,209,950 | `b49d74245dcb305bd1e6cefbe5dc58f80223c665e782437bb13051160a12fb84` |
| `widgets-rollback-b594ec5e532f.zip` | 145,315,832 | `cba4c65fe9102414b4be3af6bcb01b9acbb9abff749adbd0889c257512a55fef` |

The archives remain outside Git in the immutable external build root. Its
host-specific absolute locator is intentionally omitted. The retained safe
projection and dependency manifest bind the archive names, sizes, and digests.

## Locked build identity

- Python 3.11.9; PySide6/Qt 6.9.1; NumPy 2.3.1; Nuitka 4.1.3.
- MinGW64 GCC 15.2.0; compiler-tree file count 11,602.
- Toolchain identity:
  `sha256:dea775b6fa19a4d1967be09ed4630503cd0480d87931869c1fe79076807129d0`.
- QML distribution: 2,142 files, 446,268,320 bytes,
  tree `sha256:e8f0910a0aef17e47edf9de4fd908423b06e9255274012414b1e3d161675a388`.
- Widgets distribution: 1,743 files, 405,352,745 bytes,
  tree `sha256:7d99680e11a8d47031e0215c043a153c484b3148142dfe1eb8d14811e3f7fe38`.
- All 3,885 distribution entries in the generated SHA-256 inventory were
  independently recomputed with zero mismatches. The machine-readable result
  is retained in `build-host-verification.json`.

## Package-assembly gates

- Automatic source import scanning found `QtQuick`, `QtQuick.Controls`,
  `QtQuick.Layouts`, and `QtQuick.Shapes`; the retained closure records the
  exact deployed QML plugins and scanner-output digest.
- WebEngine payload count: zero.
- QML package delta: 40,915,575 bytes; limit: 52,428,800 bytes.
- Hardware assembly smoke: `Direct3D11`, six routes, zero errors, zero manual
  trading actions, clean exit.
- Software assembly smoke: `Software`, six routes, zero errors, zero manual
  trading actions, clean exit.
- Production renderer, safety, and dependency verifiers returned no findings
  when rerun against the final bytes.

These renderer results have `certification_scope=package-assembly`. They do
not substitute for the required clean, offline Windows 11 installed D3D11 and
Qt Software lanes. No performance waiver is applied to build-host evidence.

The original canonical release summary and renderer report remain unchanged
outside Git. Their size and SHA-256 are bound by
`build-host-verification.json`; repo evidence uses a safe projection so that
host paths and hostnames are not published.

The source-only ten-group gate is retained separately under
`../b594ec5e532fe205dbfa9875904d97319bea4d32/`; it records 1,817 passed,
1 skipped, 57 deselected, zero failures/errors, and `release_claim=false`.
