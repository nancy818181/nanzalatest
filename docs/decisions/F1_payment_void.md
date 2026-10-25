# F1 – Posted receipts / payments are never removed (owner decision, 25-10-2026)

Decided by the owner (Bassam Saber, LACPA). Implemented in 2.9.136 for **receipts / payments**.

| Case | Who | What happens |
|---|---|---|
| Delete a **posted** receipt / payment | Administrator only | **Void**: the record, its number and its posted journal entry stay. A reason is required. It leaves the statement of account, the ageing and the open allocations (allocations are released; the audit log keeps them). Only in an open period. |
| Delete a posted receipt / payment | Any other user | Refused – correct it by editing instead. |
| **Edit** a posted receipt / payment | Everyone allowed to edit | The original entry is **reversed** (new entry `REV-<number>`, dated on the edit date, linked by `reversal_of`) and a **new document with a new number** is posted. The original shows status *Reversed*. |
| Delete a **draft** (never posted) | Users with delete permission | Removed as before; the audit log keeps its full content. |

## Accepted consequence
A voided payment (without reversal) keeps its entry in the general ledger / trial balance while the statement of account and
ageing leave it out. The owner accepted this. It is never silent: **Books Health Check** shows the warning
"Voided receipts / payments still in the ledger" with the list (`Database.voided_payments_in_gl()`).

## Not changed in this release
- Posted **invoices** keep the existing rule (2.9.132): only an administrator deletes one, in an open period, and the audit log
  keeps its amounts and journal lines. Moving invoices to *void / reverse* touches stock, VAT returns and credit notes and
  needs its own design and accountant sign-off.

## Schema
`payments` gets `voided_at, voided_by, void_reason, reversal_entry_number, replaced_by` (added on start, existing data kept).

## Tests
`tests/test_f1_payment_void.py` – void keeps record/entry and releases allocations, non-admin refused, edit = reversal +
new number with balanced entries, closed year blocks void, migration columns.
