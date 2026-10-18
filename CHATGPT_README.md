# NANZA Accounting Software

## Enhanced Areas

- Quarterly cashflow aggregation, including historical quarters and five-year monthly/quarterly forecasts.
- Navy `#0a1931` and Gold `#d4a017` desktop theme, with the `#f8fafc` page background.
- Analytic Study tab with profitability, expense, cashflow, budget variance, insights, and report export data.
- AI Accountant module with safe query-intent handling, review-first account suggestions, and an adapter to Nanza's existing invoice OCR reader.

## How to Run

From the project root, install the dependencies in `requirements.txt`, then start the desktop app and server in separate terminals:

```powershell
python run_desktop.py
python run_server.py
```

Configure a Python interpreter with the required dependencies before running. The ChatGPT delivery ZIP contains the reviewed source slice and documentation; run the commands from the full project root.

## Folder Structure

```text
nanzalatest-main/
  run_desktop.py
  run_server.py
  requirements.txt
  nanza/
    accounting/       Accounting rules and posting logic
    core/             Database, API client, and server
    documents/        Invoice and document reading
    reports/          Cashflow, budget, analytic, and export engines
    ui/               Desktop screens and theme
    ai_accountant/    Analytic assistant, classifier, and OCR adapter
  tests/              Existing regression tests
  nanza_delivery/     Curated ChatGPT review package
```

The final ZIP preserves the curated review layout under `nanza_delivery/` and includes the enhanced source modules needed to review the requested work.

## New `nanza/ai_accountant/` Files

- `__init__.py`
- `analytic_study.py`
- `analytic_report.py`
- `chat_engine.py`
- `classifier.py`
- `ocr_reader.py`

Classifier output and OCR results are suggestions only and require human review. The chat engine routes supported report intents; it does not execute arbitrary SQL.