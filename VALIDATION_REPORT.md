# NANZA 2.9.130 — Board Dashboard validation

## Results
- Full suite: **1111 tests executed; 1109 passed, 2 Windows-only skips, 0 failures, 0 errors**.
- All 1111 unique test IDs match fresh unittest discovery exactly; no test was dropped.
- Execution used four completed batches and 30 isolated modules for the remaining batch. The original monolithic GUI run stalled with legacy Tk timer/callback issues and is not claimed as successful. Isolation preserved every test assertion.
- Included payroll/salary/employee regression: **95 cases passed**. All 23 protected source/test files remain byte-identical; all four 2.9.129 feature modules also remain byte-identical.
- Final focused feature/release checks: **50 passed, 16 subtests passed**, 22.24 seconds.
- Manual Arabic probe: board rendering, account-mapping dialog, PDF export and logged-out shortcut guard passed.
- Graphical tests used real Tk/Xvfb, including a 1366×768 focused pass. Arabic PDF and synthetic board preview were inspected.

Exact case IDs, per-batch results and logs are in `test-results/`; see `full-suite-summary.json`. Legacy Tk teardown diagnostics and expected unavailable-prior-year logs remain visible rather than suppressed.

## Scope and limits
This is a source release validated on Linux/Python 3.12, not approval to deploy an untested Windows installer to live books. The two Windows-only file-lock/startup tests need Windows CI. Back up and validate a copy of the company's books before live rollout.

Board formulas, active-account mappings, cash classification safeguards and unsupported metrics are documented in USAGE.md. No payroll, VAT or posting rules were changed. No OCR accuracy improvement or competitive 9/10 rating is claimed by this board release.

The owner subsequently authorized GitHub delivery to nancy818181/nanzalatest. See GITHUB_STATUS.md in docs/board-dashboard for the source-upload target. GitHub Actions and Windows installer results are separate from these local tests.

Previous 2.9.129 validation is retained in docs/ux-upgrade/VALIDATION.md.
