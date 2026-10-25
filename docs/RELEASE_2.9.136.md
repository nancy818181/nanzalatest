# Nanza 2.9.136 — release notes

Date: 25-10-2026. Previous version: 2.9.135.

## What changed

- **F1 – posted receipts / payments are never deleted** (owner decision, `docs/decisions/F1_payment_void.md`):
  administrator void with reason (record, number and posted entry kept; out of statement, ageing and open allocations;
  open period and books lock respected); non-administrators are refused; editing a posted one reverses it (`REV-<number>`,
  `reversal_of` link, dated on the edit date) and posts a new document with a new number; drafts deleted as before.
  Books Health Check warns about voided payments whose entry stays in the ledger.
- **Layout:** PR #7 responsive layouts; side-menu scroll bar (mirrored in Arabic); multi-select arrow attached to its box;
  Due days not stretched; PDF form review window fitted to the screen (`nanza/ui/window_fit.py`).
- **F3:** release check accepts only the documented `assets -> Assets` link in a copy without git.
- **Tool:** `tools/run_ui_check.py` – pictures of every screen on a temporary demo company.

## Schema
`payments`: `voided_at`, `voided_by`, `void_reason`, `reversal_entry_number`, `replaced_by` (idempotent `ALTER TABLE` on start).

## Not changed
Posted invoices (2.9.132 rule), VAT rules, rounding (2 decimals, half-up), other posting logic.

## Validation (build environment, synthetic data only)
- Golden-ledger CI set (golden ledger, float precision, accounting safety net, phase 2A VAT/rounding and storage cases)
  plus F1 tests: 156 passed, 32 xfailed; F1 tests 12/12 (pytest and unittest).
- Release check tests 8/8; window_fit tests 2/2.
- Full unittest suite: the remaining failures/errors also occur without these changes (missing PIL / pypdfium2 / numpy in
  that environment); GitHub CI is the reference.
- Not verified: Arabic visual rendering and Windows display scaling – check on Windows with `tools/run_ui_check.py`.
