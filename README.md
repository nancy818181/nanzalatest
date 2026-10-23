# NANZA Accounting

Python desktop accounting, company-scoped data service, and a Flutter mobile companion.

## Version 2.9.132 (PDF parser security update)

Updated the pinned `pypdf` dependency from 5.9.0 to 6.21.2 to address known
crafted-PDF denial-of-service vulnerabilities. CI now audits declared runtime
dependencies for known vulnerabilities. No accounting calculations or database
formats changed.

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

NANZA is Lebanon-oriented. No ZATCA Phase 2, UAE FAF, Saudi GOSI or other GCC statutory certification is claimed. Payroll rules are aids requiring category/date-specific review; EOS is an accounting estimate. Existing custom reports are constrained sales reports, not a general formula/pivot designer. Mobile OCR queue processing is incomplete in this snapshot. See the [historical accounting engineering audit](docs/accountant-engineering-audit-2026-10-17.md) and [handwriting-reader validation notes](docs/handwriting-reader-work.md); both document earlier checkpoints and must be read with their dates and limitations.

Optional external OCR exists in `azure_reader.py`; do not describe all available OCR modes as permanently local. Enable external transfer only through the existing explicit opt-in flow. The proposed free AI path needs no paid API, but model downloads, compute and licenses still need review.

## Contributing and releases

Read `AI_RULES.md`. Preserve existing features and tests. New financial calculations require regression tests and reviewed legal rules. Use staged migrations, verified backups and reconciliation; never mass-rewrite posted transactions. Application version markers are 2.9.132 for this release. Confirm a complete installer/device acceptance before deployment.

Historical version notes remain in `CHANGELOG_LEGACY.md`. The supplied source archive contained no project-wide LICENSE; obtain the owner's licensing terms before redistribution. Bundled third-party assets keep their own notices.

## Analytic audit and Arabic handwriting status

The [handwriting-reader work log](docs/handwriting-reader-work.md) records the
current OCR experiments and explicitly states that real-model accuracy is not
measured. The supplied handwritten Arabic image and ground truth are in
`tests/data/`; mocked-inference tests do not establish real-model CER/WER.
