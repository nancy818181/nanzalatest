# Nanza 2.9.138 — release notes

Date: 26-10-2026. Previous version: 2.9.137.

## What changed
- **Layout for a 14-inch laptop (1920x1080, Windows 150%)** on Sales Invoice, Purchase Invoice and Payment & Receipt:
  Purchase header on one line (Find / Import Excel / Excel Template), labels beside fields, rarely used fields under
  More / Posting accounts, one search box on Payment & Receipt, tables fit without a sideways scroll bar when possible.
- **Speed:** `get_invoice` reads one invoice instead of listing every invoice. Measured in the review environment on a
  synthetic file of 3,000 invoices: 0.068 s -> 0.002 s per call (5 calls averaged); list_invoices, trial balance, open
  documents and statement unchanged (0.07 / 0.05 / 0.002 / 0.003 s). The saving grows with the number of invoices.
- **Indexes (no data change):** `idx_invoices_party_status_date (party_id,status,invoice_date,id)`,
  `idx_journal_lines_entry_account_amounts (entry_id,account_id,debit,credit)`; created on start.
- **Test:** `test_invoice_and_payment_pages_fit_high_scaling_laptop_width` (1920x1040, Tk scaling 2.0; restores the
  shared window afterwards). In the review environment (Linux, no Segoe UI) it passes; the Windows CI runner is the real check.

## Not changed
Accounting logic, VAT, rounding, posting, schema columns.

## Validation (review environment, synthetic data only)
- Accounting set (golden ledger, float precision, safety net, phase 2A, report certification, P&L numbers): passed.
- Full unittest suite (Python 3.13 with PIL): same failing list as 2.9.137 in the same environment (missing customtkinter /
  arabic_reshaper, 3 modules that need the desktop path, 2 DOE tests that need online rates), compared by test name.
- Not verified: the real Windows look (fonts) – check after install; the speed of start-up and screen switching was not measured.
