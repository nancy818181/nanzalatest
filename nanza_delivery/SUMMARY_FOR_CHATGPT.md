# Nanza ERP Review Bundle

## Status

This is an enhancement snapshot with the first implementation pass complete. No source code was deleted. Runtime tests and GUI screenshots remain outstanding because no Python interpreter was available in the authoring shell.

## What Existed Before

- Cash Flow and Cash Flow Outlook report tabs, plus a monthly Cash Budget.
- Account budgets with month/annual amounts, departments/projects, budget-from-year, budget-vs-actual, and forecast actions.
- Separate generic cash/budget projection helpers and an account-level three-scenario projection model.
- Management Pack, Executive Dashboard, Business Reports, VAT reporting, and PDF/Excel report export paths.
- Default company VAT of 11% with configurable rate and LBP/USD VAT currencies.

See `EXISTING_AUDIT.md` for detailed files, report tabs, risks, and gaps.

## Implemented Enhancements

- Continuous quarterly actual cashflow and five-year monthly/quarterly scenarios with three cases and shortage thresholds.
- Quarterly account budget-vs-actual with variance status, exports, and source invoice/journal drill-down. Existing annual five-year budget projection remains in place.
- Analytic study/report with posted-ledger profitability, expense, budget, cashflow, saved insight, and PDF chart sections.
- AI Accountant intent handling, rule-based account suggestions, and a human-review OCR adapter using Nanza's existing invoice reader.
- Historical monthly cashflow and budget actuals use fiscal-year-specific books where available.

## Colors

The desktop constants and shared theme use Blue `#0a1931`, Gold `#d4a017`, Background `#f8fafc`, and white cards. Danger/status colors remain distinct.

## How to Run

This ZIP is source for review, not a runnable installer. To run the application, use the repository's Windows launch scripts from the project root after installing dependencies from `requirements.txt`. No local Python interpreter was available in the authoring shell to verify startup or run pytest.

## Tabs and Screenshot Descriptions

`TABS_AND_SCREENSHOT_NOTES.md` lists the existing report tabs and describes the expected screen captures. Descriptions are not screenshots; no GUI capture was made.

## What Still Needs Testing

- Run focused quarterly forecast, budget, currency conversion, VAT, and accounting regression tests in a configured Python environment.
- Verify quarterly sums equal their three monthly inputs, including partial current quarters, across USD and LBP.
- Validate opening/closing cash, 2027–2031 forecast periods, seasonality, growth, scenarios, and shortage thresholds against fixture data.
- Validate monthly/quarterly/yearly budget variance and invoice drill-down without changing existing budget persistence.
- Exercise desktop tabs, popups, exports, hidden-tab settings, Arabic labels, and purchase/sales windows; validate classifier integration with those forms.
- Benchmark report queries on large datasets and verify query plans/indexes before claiming a sub-two-second target.

## Questions for ChatGPT Review

- Is the split between generic cash/budget projection and account-level three-scenario projection clear enough, or should one layer own quarterly aggregation?
- What additional controls should prevent double-counting openings, closings, or converted multicurrency cash movements across quarter boundaries?
- Which assumptions and uncertainty labels are needed before presenting a five-year forecast as CFO-grade?
- What is the safest way to add invoice-level budget drill-down while preserving existing account and dimension filters?
- Which tests are essential before enabling classifier suggestions inside purchase/sales entry forms?
- Should investing/financing classification be configured by account mapping or inferred only from reviewed counterpart accounts?