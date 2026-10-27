# Nanza Accounting 2.9.139 — speed and navigation stabilization

Date: 27 October 2026. Previous version: 2.9.138.

## Scope

No new product features. This release carries the speed improvements reviewed in draft PR #8:

- Decorate only the screen being built; preserve full-notebook fallback for unknown builder types.
- Restrict hidden-tab permission traversal to the constructed screen; preserve security rules.
- Skip online historical EUR-rate fetch when displaying invoice rows; use saved rates for invoice-list equivalents. Empty invoice lists do not fetch rates. Default exchange-rate API behavior, posting and valuation paths remain unchanged.
- Cache sample rows and duplicate font measurements when auto-sizing Treeview columns.
- Prevent unknown public UI attribute probes from constructing every pending page; recognized lazy widgets still load.
- Add regression tests for navigation, scoped permissions, cached FX display, table sizing, and lazy loading.

## Validation gates

- Speed-source baseline `a74b3280b94acb633cc70bc6b561dc93399d76ae`: GitHub Linux and Windows full-test workflows passed; accounting safety net and golden ledger passed.
- An earlier version of the same application code (`dd783d59`) completed the Windows installer workflow successfully. Since then the changes were in tests, not program logic.
- **Release candidate `2.9.139`: MUST pass the Windows installer/full unittest workflow, packaged startup smoke test, Linux/Windows tests, and accounting certifications before it is treated as approved.** CI and installer output, not this document, are the authoritative results.
- Historical local measurements on an older source snapshot: 500 mocked invoice rows, opening Invoices ~4.36 s to ~0.71 s; 150 warm switches median 9.17 ms. These are NOT benchmarks of the new Windows installer. Do not claim production performance improvements from these figures.

## Installation and safety

- The existing Inno Setup AppId is unchanged, and the installer is an in-place application upgrade; company database files are stored separately. Still take a verified backup and restore-check on a disposable company before upgrading active client data.
- No database schema, historical journal entry, VAT or rounding migration was added to this release.
- Known limitations outside this stabilization release: posted invoice-source entries lack full raw-SQL immutability enforcement; older audits document expected failures. A test-only trial must not be treated as production statutory certification.
- The release is created only by GitHub's main-branch installer workflow **after** all its required steps pass. Build artifacts on pull requests are not signed-off production releases.
