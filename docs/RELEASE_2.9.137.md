# Nanza 2.9.137 — release notes

Date: 26-10-2026. Previous version: 2.9.136.

## What changed
- **F1 – posted invoices are voided, never removed** (owner decision, `docs/decisions/F1_invoice_void.md`): administrator only,
  reason required, original entry kept plus a linked reversal (`invoice_void`) dated on the void date and a stock reversal;
  refused when the VAT return is saved, the period is closed or the books are locked; drafts deleted as before; bulk void from
  the invoice list asks one reason.
- **Void invoices in every reader:** GL readers (trial balance, financial statements `load_period`, ledger reports, AI accountant,
  Books Health Check, revaluation) include `void` with its reversal; VAT return / ledger, open documents, ageing, duplicate
  checks, customs costs exclude it.
- **F4 exact report totals:** `DSUM_EXACT` (Decimal, returned as text) in trial balance, balance sheet, P&L, statement, ageing.
- **G3 custom report builder certification:** bound filter parameters (one `?` per IN value), Decimal totals equal the TB per
  account and currency, drafts excluded, voided payment + reversal reconcile.
- **F7:** HTTP tests for company / fiscal-year isolation (no leak found; reading earlier years of the selected company stays allowed).
- **Payment reversals** copy every `journal_lines` column (multi-currency amounts kept).
- **Layout:** compact purchase and payment forms. Fixed in review: the Purchases & Expenses page referenced a removed
  `paid_row` frame and failed to open.

- **Fixed before publishing (CI):** the Profit & Loss page failed to open ("Unknown format code 'f' for object of type
  'str'") because the exact sums came back as text; P&L rows are numbers again and the page formats exact text safely
  (`tests/test_v2_9_137_pnl_numbers.py`).

## Schema
`invoices`: `voided_at`, `voided_by`, `void_reason` (idempotent `ALTER TABLE` on start, existing data kept).

## Not changed
VAT rules, rounding (2 decimals, half-up), other posting logic. No monthly close (books lock + fiscal-year close).

## Validation (review environment, synthetic data only)
- Accounting set (golden ledger, float precision, accounting safety net, phase 2A VAT/rounding and storage cases, report
  certification, F1 payment and invoice void): 183 passed, 32 xfailed (pytest).
- Full unittest suite: 1221 tests. The failing/erroring tests are the same list as on 2.9.136 in the same environment
  (missing PIL / cv2 / pypdfium2 / arabic_reshaper), compared by test name; no new failure.
- Not verified: Arabic visual rendering and Windows display scaling – check on Windows with `tools/run_ui_check.py`.
  GitHub CI is the reference.
