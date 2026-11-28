# Nanza Accounting2.9.142

This candidate includes the previously unpublished Classic2.9.141 changes plus
the owner's approved new-document currency-cent policy and a VAT form correction.

## Financial scope

On27November2026 Bassam approved HALF_UP cents for new foreign documents in the
existing USD/LBP equivalent columns. Native document amounts are unchanged.
Invoice carrying values and receipt/payment values are frozen when created.
Realized FX allocates the rounded invoice carrying value cumulatively; the final
settlement receives its remaining book cents. Reallocation appends the necessary
adjustment and keeps prior journal history and period locks.

For100.15EUR at1.10, carrying value is110.17USD. Receipts50.08 and50.07EUR at1.20
carry60.10 and60.08USD. Total realized gain is10.01USD and the party closes to
zero in both native and book currencies. Stored equivalents also balance in LBP.
An explicit zero-native FX rounding line balances independently rounded document
lines. Reversal copies and reverses the original stored values.

There is no historical rewrite or blanket corrective posting. Existing documents
without frozen equivalents keep their earlier policy. Historical exceptions need
a separately approved adjustment with document-level support.

## VAT scope

The preparation schedule used156 for the non-taxable disposal row; the official
Q1-2 specimen/guide identifies165. The number and associated totals/captions are
corrected. Bassam confirmed the specimen and the advance example for Q1/Q22026:
box110 base100/VAT11 in Q1; after application to a final300+33 invoice, net Q2
base200/VAT22. This is a scoped accountant approval, not a blanket legal opinion.

Official references:
- [Forms and issued-form requirement](https://finance.gov.lb/ar-lb/Taxation/Individuals/VAT/Pages/Forms.aspx)
- [Q1-2 specimen](https://finance.gov.lb/en-us/Taxation/Na/VAT1/%D9%821-2.pdf)
- [Q1-2 instructions](https://www.finance.gov.lb/en-us/Taxation/Na/VAT/Tifsir/%D9%821-2%D8%AA%D8%B5%D8%B1%D9%8A%D8%AD%20%D8%AF%D9%88%D8%B1%D9%8A.pdf)

Nanza's PDF is a preparation schedule; filing uses the officially issued form.

## Verification and limitations

The focused regression suite is `python -m unittest tests.test_fx_book_cents -v`.
It covers receipt/payment gains and losses, split and grouped allocations,
retries, reallocation, immutable historical rows, frozen rates, public
reverse-and-replace corrections, period locks, dual-currency balance and row165.
Full discovery is `python -m unittest discover -v -s tests -t . -p "test_*.py"`.

The installer workflow runs actual clean installation and2.9.140 upgrade on a
disposable Windows runner, hashes the package, launches the installed executable
and compares preserved records, allocations, journal rows, users, audit and locks.
The attached JSON states its boundaries: seeded service fixtures are distinct
from interactive entry in the installed GUI. A successful build or this smoke
check alone is not acceptance of125% Windows scaling or an accountant-reviewed
month close. The final owner evidence report records the actual execution and
the independently recalculated210,000-document results.
