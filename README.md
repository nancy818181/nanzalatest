# NANZA Accounting

Python desktop accounting, company-scoped data service, and a Flutter mobile companion.

## Version 2.9.132 (phase 1 test: VAT, fixed assets, reports, IFRS)

Tested end to end on a synthetic company (Q1-Q4 2026, USD and LBP, test rate 89,500): 1036 tests, no regression
(the 72 environment-only failures of a computer without Tk / arabic-reshaper are unchanged). New tests: `tests/test_v2_9_132.py`.

- VAT: the ledger check no longer lists an exempt-use purchase as "not on the return"; the Art. 31 prorata is in whole LBP
  like the settlement and the credit carried forward; from 2026 the due date is the last day of the month after the quarter
  (Q2 31-07, Q3 31-10 - owner decision); the deduction ratio stays between 0 and 1.
- Fixed assets (IAS 16 / IAS 21): disposal / scrapping (Dr accumulated depreciation, Dr 6812 book value, Cr cost; the sale
  by a sales invoice to 7812 so its VAT is declared) with disposals in the rollforward; register against ledger check;
  reversing a depreciation or disposal voucher updates the register; depreciation and disposals use the purchase-date rate
  (IAS 21.23(b)). Schema: two added columns `fixed_assets.disposed_on`, `disposal_entry_id` (existing rows unchanged).
  Accounts 681, 6811, 6812, 78, 781, 7811, 7812 added to every chart template.
- Invoices: an Assets invoice needs a class 2 account (import / API, as the screen already required); a POSTED invoice
  whose total differs from subtotal + VAT by more than 1 is refused (no silent balancing on 6851.6); manual invoice
  amounts are kept as exact decimal text (was float; test_v2_9_93 updated: "111.00" instead of "111.0", same value).
- Financial statements (IAS 7.8 / 7.45): a cash or bank account with a credit balance stays a liability in the balance
  sheet but is part of cash and cash equivalents in the cash flow, with the reconciliation lines; a review point flags cash
  on hand with a credit balance.
- PDF layout (no figure changed): columns sized on the longest header word plus padding (a 10-column trial balance fits one
  band, amounts never break over two lines); a column with cents shows 2 decimals on every amount; one date line;
  negative amounts in brackets (1,234.00) in every report; the period of the P&L and cash flow on its own line;
  "Total expenses" in the P&L (IAS 1.102); the company name in the audit report header.
- Ageing (owner decision): receipts / payments not allocated to an invoice settle the oldest open invoices first (FIFO by
  due date); the net balance is unchanged; `fifo=False` keeps the earlier gross presentation (test_final_features updated).
- The saved VAT return snapshot keeps exact decimal text (was float).
- Not changed on purpose: the core report queries (trial balance, balance sheet, cash flow) still return float to the
  screens; DSUM adds exactly and a float keeps cents exact up to about 10^13 (LBP 10 trillion). Changing the type would
  touch every screen.

## Version 2.9.131 (merged audit fixes and AR/EN resources)

Merged CLEAN_FIXED onto the complete source. Installer/runtime versions match.
The invalid-date regression fixture now temporarily marks its corrupt entry posted:
posted reports deliberately exclude draft/rejected entries. Original assertions remain.
Translation resources are included in the Windows build; no legacy.yml is added.

### Local OCR and AI source update

Added `nanza/ocr/`: Falcon Arabic adapter, Paddle printed-text routing, English
TrOCR lines, Arabic handwriting preprocessing and an actual-image benchmark CLI.
Added local ExpenseClassifier learning, safe books chat and duplicate/high-VAT
flags while preserving the original AI functions. No payroll/VAT formulas changed.

The final light source package removes the large vision-model backend and its
extra utilities. Torch remains required for Falcon/TrOCR inference. See
[OCR_AI_SETUP.md](OCR_AI_SETUP.md) for one-time online setup and subsequent offline use.
Model weights are not included. Recognition accuracy, speed and installed footprint
require measurement; 15 contract tests are not an OCR accuracy benchmark.

## What is implemented

- Double-entry journals, invoices, vendor bills, payments, credit notes, fiscal-year closing and locked periods.
- Lebanese chart of accounts, multicurrency reporting, historical exchange rates, AR/AP ageing and bank reconciliation.
- Lebanese payroll: effective-dated salary-tax/NSSF settings, allowances, retroactive pay, posting, payroll forms, EOS provision estimates, leave balances and PDF payslips.
- Lebanese VAT classifications, reverse-charge return calculations, partial recovery, filing worksheets and settlement controls.
- Inventory, fixed assets, commercial documents, management reports, budgets and executive dashboards.
- Local rule-based account suggestions, duplicate checks, invoice intake and optional OCR engines.
- Flutter companion source for approvals, expense capture and accountant queries.

## Install and run

Python 3.12 is the CI reference. Work from the repository root. Tk support is required for the desktop app.

```bash
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_desktop.py
# Separate terminal, if running a standalone server:
python run_server.py --help
python run_server.py
```

Standalone server defaults to loopback. For LAN access supply TLS certificate and key:

```bash
python run_server.py --host 0.0.0.0 --tls-cert /path/server.crt --tls-key /path/server.key
```

Use the generated initial admin password or configure `SABER_ADMIN_PASSWORD` securely. Never put credentials or company data in Git. The desktop starts its own private service; a standalone server is a separate deployment choice, not a requirement for every desktop session.

## Tests

Install development dependencies, then run the new APIs' focused suite:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_ocr.py tests/test_ai_accountant.py -v
```

Integration templates are in `templates/ocr_ai/`. These APIs do not install a new
OCR screen or automatically post bills. Existing attachment UI remains intact.


On a case-sensitive Linux filesystem create `assets` pointing to `Assets` once, then run:

```bash
ln -s Assets assets
python -m unittest discover -s tests -t . -p 'test_*.py'
# GUI verification on Linux with the required system packages:
xvfb-run -a python -m unittest discover -v -s tests -t . -p 'test_*.py'
```

CI definitions: `.github/workflows/tests.yml` and `build-windows-installer.yml`. Test results depend on system Tk/X display, optional OCR runtimes and installed dependencies. See the audit's validation log for the checks actually executed.

## Mobile companion

See `mobile/README.md`. The ZIP contains `lib/main.dart` and `pubspec.yaml`, not a complete verified Android/iOS release project. Platform scaffolding, signing, permission declarations and Flutter device testing are still required. No mobile release validation is implied.

## Architecture

| Path | Responsibility |
|---|---|
| `nanza/core/` | SQLite persistence, API service, approvals, company/year isolation |
| `nanza/accounting/` | Posting, inventory, assets, banking, commercial documents |
| `nanza/payroll/` | Lebanese payroll rules, forms and supporting calculations |
| `nanza/tax/` | Lebanese VAT return and tax review |
| `nanza/reports/` | Financial statements, analytic reports, forecasts and exports |
| `nanza/documents/` | OCR, invoice intake and evidence |
| `nanza/ai_accountant/` | Local query routing, suggestions and duplicate checks |
| `nanza/ui/` | Desktop UI |
| `nanza_delivery/*.py` | Runtime workbench/dashboard extensions imported by the active app |
| `tests/` | Regression tests |
| `Assets/` | Required fonts, logos and help; preserve exact case |

`nanza_paths.py` supports legacy flat module imports. Nested `nanza_delivery/nanza/` and `nanza/nanza_backup/` copies are historical/reference copies, not the canonical runtime implementation.

## Compliance and known limits

NANZA is Lebanon-oriented. No ZATCA Phase 2, UAE FAF, Saudi GOSI or other GCC statutory certification is claimed. Payroll rules are aids requiring category/date-specific review; EOS is an accounting estimate. Existing custom reports are constrained sales reports, not a general formula/pivot designer. Mobile OCR queue processing is incomplete in this snapshot. See `audit/TOP_20_FINDINGS.md` for verified defects and release blockers.

Optional external OCR exists in `azure_reader.py`; do not describe all available OCR modes as permanently local. Enable external transfer only through the existing explicit opt-in flow. The proposed free AI path needs no paid API, but model downloads, compute and licenses still need review.

## Contributing and releases

Read `AI_RULES.md`. Preserve existing features and tests. New financial calculations require regression tests and reviewed legal rules. Use staged migrations, verified backups and reconciliation; never mass-rewrite posted transactions. Application version markers are 2.9.131 for this additive source change. Confirm a complete installer/device acceptance before deployment.

Historical version notes remain in `CHANGELOG_LEGACY.md`. The supplied source archive contained no project-wide LICENSE; obtain the owner's licensing terms before redistribution. Bundled third-party assets keep their own notices.

## Analytic audit and Arabic handwriting status

Read [ANALYTIC REPORT.md](ANALYTIC%20REPORT.md) for the payroll/VAT check-up tables,
custom-report status and the explicit handwritten-Arabic OCR benchmark limitation.
The supplied handwritten Arabic image and ground truth are in `tests/data/`. The review-policy test passes; real model accuracy is not yet measured.
The original snapshot audit, 161-row matrix, architecture/schema proposals and
candidate fixes are under `audit/`. Real-model CER/WER is not represented by the
mocked-inference unit-test pass count.
