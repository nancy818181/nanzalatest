# F1 – Posted invoices are voided, never removed (owner decision, 25-10-2026)

Decided by the owner (Bassam Saber, LACPA). Implemented in 2.9.137 for **sales and purchase invoices** (same rule as receipts / payments in 2.9.136).

| Case | Who | What happens |
|---|---|---|
| Delete a **posted** invoice | Administrator only | **Void**: the invoice, its number and its original journal entry stay; a linked reversing entry (`source_type='invoice_void'`, `reversal_of`) and the stock reversal are posted. A reason is required and kept in the audit log with every original and reversal line. |
| Delete a posted invoice | Any other user | Refused (403). |
| Delete a **draft** / review invoice | Users with delete permission | Removed as before (status `deleted`). |
| Bulk delete (invoice list, multi-select) | Administrator | One reason for the selected posted invoices; drafts in the selection are deleted. |

## Reversal date (owner decision, final)
The reversal is **always dated on the void date**. If the invoice is in an earlier VAT quarter, each quarter shows its own
entry in the general ledger. The VAT return and VAT ledger treat a void invoice like a cancelled one (left out), and a void is
refused when the invoice's VAT return is saved, when the period is closed, or when the books are locked
(`books_locked_until`) on either the invoice date or the void date.

## Closed periods (owner decision, final)
No monthly close. The closed-period mechanism is the books lock (`app_settings.books_locked_until`) plus fiscal-year close.

## Where `void` is counted
- General-ledger readers (trial balance, financial statements, ledger reports, AI accountant, books check, revaluation): **included** - the original entry and its reversal net to zero.
- Open documents, ageing, VAT return / ledger, duplicate-number checks, customs costs: **excluded**.

## Schema
`invoices` gets `voided_at, voided_by, void_reason` (added on start, existing data kept).

## Tests
`tests/test_f1_invoice_void.py`; `tests/test_report_certification_unittest.py::test_voided_sale_gl_readers_reconcile_and_vat_lists_exclude_it`; `tests/test_v2_9_69.py` (bulk void).
