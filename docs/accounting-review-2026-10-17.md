# Accounting and desktop review - 17 October 2026

Local working changes, not a published release. Existing posted accounting entries are not rewritten.

## Purchase costs

- Separate USD and LBP inputs for each component, one explicit reviewed conversion rate,
  original-currency evidence stored alongside posted amounts, and an exportable cost breakdown.
- Customs allocation remains the existing value-based distribution among designated items,
  as confirmed by the user. Import VAT remains separate from inventory cost.
- Customs broker/payee starts blank. The user enters the name. Payment method and an
  explicit cash/bank account are available; paid costs require a valid active cash account.
- Costs in different currencies are not summed as though they shared one currency.
- Under company approval settings, an approver records purchase costs requiring approval;
  this endpoint does not silently bypass invoice/payment approval policies.

## Sales, numbering, reports

- User clarified that the sales checkbox means income exempt from income tax, not a VAT
  deduction certificate for the buyer. An existing legal reason is required. Save is atomic
  with the invoice; the usual sales number sequence and VAT treatment remain unchanged.
- Preserve a recorded exemption when an invoice is replaced without a new tax instruction.
- Numbering is the first administrator Settings tab and reachable from the Sales screen.
- Existing comparative trial balance, equity changes, cash flow, notes and aged AR/AP were
  found; these are not newly invented reports. Added purchase cost source/FX breakdown.
- Payroll worksheets include arithmetic and duplicate-month controls. These checks are
  not independent recalculation of all statutory tax eligibility. VAT preparation status
  distinguishes blocked/provisional/filtered previews from a return still needing review.
- Short payroll summary tables can remain with their headings in PDF output.

## Payroll additions

- Family allocation defaults to social-security receivables account 438, retaining an
  explicitly configured alternative and leaving old posted payroll unchanged.
- Extra benefits retain their own expense accounts through save, posting and monthly-sheet
  editing. The new entry dialog offers taxable benefits by default. An account selection
  does not itself grant a tax or NSSF exemption.
- Salary payment date and salary month are distinct. Allocations permit partial payment,
  refuse amounts above the unreserved salary, retain history and permit dated reversal.
- Linked payment/reversal vouchers cannot be independently edited/deleted through the
  general journal. Company voucher/payment approvals reserve pending amounts without
  presenting them as approved payments. Payment records are in the payroll's company file;
  cross-file prior-year opening-payable settlement is not implemented by this feature.
- Base salary uses actual calendar days between hire/leave dates within the selected month.
  The existing statutory 30-day convention for tax bands/deductions remains separate.
  Transport days cannot exceed the employment period or contain a fractional day.

## Handwritten invoices and free local assistance

- Human review preserves the original photograph detail and supports rotate/fit/zoom.
- Existing supplier posting memory, expense classification suggestions, and optional local
  OCR remain available. No paid inference service or new paid API is introduced.
- Benchmark tool scores manually verified labels against saved reader outputs; abstentions
  count as missed nonblank fields, and invented values in blank fields are reported separately.
- This is not proof of 80% handwriting accuracy. Prior real-photo trials produced incorrect
  amounts and dates. No trustworthy 80% target or all-item extraction claim is made.

## Validation and limits

- Broad run: 953 tests, 62 skipped; two failures were report-section ordering and line-length
  checks introduced during the work. Both were corrected and revalidated with focused tests.
- A later focused run of 68 tests passed before the final salary-payment additions. Additional
  focused runs cover salary allocations/reversals/approval, 438 and extra-benefit postings,
  partial months (28/29/30/31 days), purchase payments and transaction rollback.
- Real Linux/Tk checks opened cost, tax-option, additional-benefit and salary-payment screens;
  sales field bounds were checked at 1920/1366/1024 in both UI directions. PDF/Excel export
  was exercised, and the payroll summary pagination was inspected. Windows installer and
  Windows glyph/layout validation remain outstanding.
- Monetary limits are not adopted from old ministry web-page examples. Exemption eligibility
  and current statutory limits require the effective rules and supporting documentation.
  Official reference checked: https://finance.gov.lb/ar-lb/Taxation/Companies/D-S/Pages/Tax-on-DASS.aspx
- Private photos, QA outputs, caches and model weights are excluded from source control.
