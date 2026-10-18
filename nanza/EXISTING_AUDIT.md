# Existing Cashflow, Budget, and Reporting Audit

Audit date: 2026-10-18

Scope: static inspection of the existing implementation under `nanza/` and its adjacent tests. No data or runtime files were modified. “Missing” means not found in the reviewed code paths; “possible risk” is not a confirmed accounting defect.

## Existing Files

### Cashflow and budget owners

- `ui/desktop_reports.py` builds the Financial Reports notebook, Cash Flow, Cash Flow Outlook, Cash Budget, and their export actions.
- `ui/desktop_dimensions.py` builds the account budget editor, budget-from-actual draft, short forecast, long-term projection, and budget-vs-actual action.
- `ui/desktop_projection.py` owns the separate Projection & Budget (3D) screen and its assumptions, three scenarios, cash flow, and account budget generation.
- `ui/desktop_reports_extras.py` owns the Management Pack and drill-down entry points.
- `ui/desktop_v22.py` owns the Business Reports screen.
- `core/db_reports.py` owns ledger-derived P&L, cashflow, balance sheet, management and reporting data methods.
- `core/db_dimensions.py` owns dimension budgets, their persistence, and period budget lookup.
- `core/client.py` and `core/server.py` expose cashflow, fiscal-year, budget, and report requests to the desktop UI.
- `core/database.py` and `core/database_common.py` define database initialization, tables, and indexes.
- `reports/financial_projection.py` contains generic monthly forecasts, cash budgets, annual growth projections, and budget-from-year math.
- `reports/projection_model.py` contains the distinct account-level, three-scenario five-year projection and monthly budget spread model.
- `reports/management_pack.py` contains monthly/YTD actual-versus-budget reporting and alerts.
- `reports/executive_dashboard.py` builds the executive dashboard from management-pack data.
- `reports/business_reports.py`, `reports/ledger_reports.py`, and `reports/report_export.py` provide business reports, ledger report calculations, and exports.
- `reports/financial_statements.py` and `reports/financial_statements_i18n.py` contain financial-statement reporting and translations.
- Related tests: `tests/test_financial_projection.py`, `tests/test_v2_9_79.py`, `tests/test_v2_9_80.py`, `tests/test_v2_9_50_projection.py`, `tests/test_v2_9_81.py`, and `tests/test_accounting_integrity_regressions.py`.

## Existing Tabs and Reports

The Financial Reports notebook currently creates these pages (subject to company/user hidden-report settings):

- General Ledger
- Balance Sheet
- Lebanese VAT Report
- Cash Flow
- Cash Flow Outlook
- Cash Budget
- Comparative P&L
- Comparative Trial Balance
- Ageing Report (the page is built by Inventory and attached here)
- Budget
- Projection & Budget (3D)
- Business Reports
- Management Pack

The broader report registry in `accounting/accounting_setup.py` includes General Ledger, Balance Sheet, Lebanese VAT Report, Cash Flow, Cash Flow Outlook, Cash Budget, Comparative P&L, Budget, Projection & Budget (3D), Business Reports, and Management Pack. “Ageing Report” and Comparative Trial Balance are visible in the notebook but are not in that registry list.

Implemented cashflow/report outputs include cash and bank movement by origin, monthly outlook, cash budget by month, annual long-term projection, projected indirect cash flow in Projection & Budget (3D), Management Pack, Executive Financial Dashboard, VAT return/position, comparative statements, ledger reports, and business reports.

Implemented budget/report outputs include monthly account budgets (or annual amounts spread over 12 months), department/project dimensions, budget from a selected actual year with separate revenue/expense growth, budget-vs-actual account report, monthly trailing-average forecast, long-term year projection with per-year growth and saved-budget precedence, three-scenario account projection, monthly management-pack variances, and budget variance alerts.

## Duplicate and Unused-Code Assessment

- No exact duplicate cashflow or budget module/file was identified.
- There are overlapping but non-interchangeable forecast models: `financial_projection.py` handles generic period/growth calculations and cash budgeting; `projection_model.py` handles account-level statements, three scenarios, and indirect cashflow. Their live callers differ. `management_pack.py` also aggregates actuals and budget variances, but is a separate report contract.
- No candidate was confirmed unused in this pass. The files above have direct UI/service imports or registered callers. A complete dead-code determination needs a whole-package reference/runtime audit; no file should be deleted on the current evidence.

## Confirmed Gaps and Enhancements Needed

- Quarterly actual cashflow aggregation (Q1 = Jan + Feb + Mar, through the current date) is not exposed as a cashflow report/table.
- Cashflow history is not presented as quarterly opening, cash-in, cash-out, net, closing, and status. The existing cashflow report groups movements by source, not period.
- Existing long-term cashflow projection is annual, accepts a target date up to five years ahead, and applies growth to a base-year aggregate. It is not a 60-month/20-quarter projection, has no Conservative/Realistic/Optimistic scenarios, and does not use 24 months of seasonality/trend.
- Existing short cashflow outlook uses each of the last three complete months as a trailing average. It has no quarterly operating/investing/financing deep dive, forecast-versus-actual quarterly variance, configurable shortage threshold, or threshold alert.
- Cash budget is monthly for a selected target year and grows a base year’s monthly flows. It does not provide quarterly budget periods or the requested 2027–2031 category growth-rate schedule.
- Budget-vs-actual is an existing account report for the selected year through a selected month. A unified monthly/quarterly/yearly table with variance amount/percent, status colors, and invoice-level overrun drill-down was not found.
- No combined quarter view joining opening cash, forecast inflows, budget outflows, net, and closing cash was found.
- No analytic-study module/report, saved generated insight workflow, AI Accountant chat, account classifier suggestion, or invoice OCR reader under `nanza/ai_accountant/` was found in the inspected package.
- An annual five-year projection already exists in more than one form; “five-year projection missing” would be inaccurate. The requested monthly and quarterly horizons, multiple cashflow scenarios, and five-year budget growth by category are the gaps.

## Layout and Color Review Findings

- The inspected desktop screens use shared constants `NAVY="#102A43"`, `GOLD="#B78B45"`, and `LIGHT="#F4F7FA"` in multiple UI modules. These do not match the requested `#0a1931`, `#d4a017`, and `#f8fafc` palette.
- The UI uses a mix of `tk.Frame`/`LabelFrame`, packed controls, `ttk.Notebook`, editable sheets, and report viewers. Cashflow pages are sibling tabs; the budget page combines editor, projections, and report output vertically rather than the requested subtabs. Detailed popup-by-popup visual review requires opening and exercising the desktop app and is not established by this static audit.
- Report pages and desktop builders have background/lazy loading in the financial-report flow. That is useful existing behavior to preserve when adjusting layouts.

## Performance and Query Risks

- `db_reports.cash_flow()` performs database-side aggregation, avoiding the historical fixed-row cap, and the database creates `idx_journal_entries_date`.
- `cash_flow_converted()` calls `_converted_lines()` and then filters/aggregates returned ledger lines in Python. This can load a broad set of posted lines for a narrow date window and is a priority optimization candidate.
- The date predicates normalize legacy `DD-MM-YYYY` values with SQL `CASE` expressions. The regular `entry_date` index may not help those normalized predicates without a compatible expression/index strategy.
- Cashflow outlook, cash-budget, budget-from-year, and budget forecast paths issue month-by-month client/report requests (up to 12 for one year). The report loaders and row limits should be reviewed before promising a sub-two-second target on large company files.
- The visible budget index in `database.py` is `idx_budgets_year`; budget reads additionally filter by currency, department, project, and account. Confirm the complete index set and query plans before adding indexes.
- No pagination control was identified in the reviewed cash/budget tables. Current projections produce bounded rows, but general ledger/report result sizing should be measured separately.

## VAT and Currency Checks

- The default company VAT setting is 11%; `desktop_common.vat_rate()` reads the company setting with an 11% fallback, invoices use the configured rate, and the Lebanese VAT return defines 11% as its standard-rate constant while also reading company settings. The default and configured VAT currencies include LBP and USD.
- The code also contains valid 0%-rated/exempt treatments; do not force every invoice line to 11%. No confirmed VAT 11% calculation defect was found in this static pass. Regression checks should preserve company-configured rates, 0% treatments, and VAT rounding.
- Cashflow has both native-currency and converted-currency service paths. Conversion uses saved transaction/rate data, and `test_v2_9_80.py` covers a converted cashflow case. No confirmed USD/LBP arithmetic defect was found here; the implementation must retain the distinction between per-currency output and a selected display-currency conversion.
- Multi-currency quarterly aggregation, opening/closing balances, and cross-year forecasts still need explicit USD/LBP regression tests before rollout.

## Audit Conclusion

Enhance the existing cashflow, budget, report, export, and database paths; do not replace them or delete forecast modules. The safest next implementation slice is to add tested pure quarterly aggregation to the existing projection/report model, then connect it to the current Financial Reports tabs. Preserve existing account/dimension budgets, currency conversion, VAT handling, exports, hidden-tab behavior, and asynchronous report loading.