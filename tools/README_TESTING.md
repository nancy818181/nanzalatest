# Testing a copied Nanza company database

These checks are read-only diagnostics. They do not replace the application's
own reports or an accountant's review. Use synthetic data for development and a
verified copy for local owner checks.

## Make a safe copy on Windows

1. Close Nanza completely before copying. Confirm that no Nanza process is
   still using the company database.
2. Copy the entire company data folder to a separate working folder. Copy the
   database and any matching SQLite `-wal` and `-shm` files together. Do not
   copy only the main database while a write-ahead log may contain recent data.
3. Keep the original folder untouched. Do not open the copied database with
   Nanza on the same PC. Application startup can run `initialize()`, schema
   upgrades and account upserts that write to the database. Run only the
   diagnostics below against the copy.
4. Replace `<COPY_DB>` below with the copied database file. The path is a
   command argument only; diagnostic output redacts it.

## Run diagnostics before and after a fix

Run the `before` command before a change. After the fix, point `<COPY_DB>` to a
fresh copy of the same company data and run the matching `after` command.

**4427 account-type diagnostic** (`database_copy` is the only argument):

```powershell
New-Item -ItemType Directory -Force .\compare-4427 | Out-Null
py -3 tools\diagnose_4427.py "<COPY_DB>" > .\compare-4427\before.txt
# After the fix, use the fresh copy:
py -3 tools\diagnose_4427.py "<COPY_DB>" > .\compare-4427\after.txt
```

**Decimal precision diagnostic** (`--confirm-copy` is required):

```powershell
New-Item -ItemType Directory -Force .\compare-decimals | Out-Null
py -3 tools\diagnose_decimals.py "<COPY_DB>" --confirm-copy > .\compare-decimals\before.txt
# After the fix, use the fresh copy:
py -3 tools\diagnose_decimals.py "<COPY_DB>" --confirm-copy > .\compare-decimals\after.txt
```

**Stored-data baseline snapshot** (`--confirm-copy` is required):

```powershell
New-Item -ItemType Directory -Force .\compare-baseline | Out-Null
py -3 tools\baseline_snapshot.py "<COPY_DB>" --confirm-copy > .\compare-baseline\before.txt
# After the fix, use the fresh copy:
py -3 tools\baseline_snapshot.py "<COPY_DB>" --confirm-copy > .\compare-baseline\after.txt
```

`diagnose_4427.py` takes one positional database-copy path and has no
`--confirm-copy` option. `diagnose_decimals.py` and `baseline_snapshot.py`
require `--confirm-copy`.

Compare each script's before/after output with PowerShell:

```powershell
Compare-Object (Get-Content .\compare-4427\before.txt) (Get-Content .\compare-4427\after.txt)
Compare-Object (Get-Content .\compare-decimals\before.txt) (Get-Content .\compare-decimals\after.txt)
Compare-Object (Get-Content .\compare-baseline\before.txt) (Get-Content .\compare-baseline\after.txt)
```

The scripts read stored rows and aggregate values. They do **not** call Nanza's
report-query functions and cannot detect a change made only to a report query,
such as excluding draft entries. The manual application-report comparison
table below is required before and after each fix.

## Manual report comparison

Fill this table from the application's own reports for the same company,
currency and period before and after each fix. Keep the database copy and the
application report period consistent. Do not put client identifiers in shared
test artifacts.

| Measure | Period / currency | Before | After | Reviewer notes |
|---|---|---:|---:|---|
| Trial Balance — debit total |  |  |  |  |
| Trial Balance — credit total |  |  |  |  |
| Assets |  |  |  |  |
| Liabilities |  |  |  |  |
| Equity |  |  |  |  |
| Net income for the year |  |  |  |  |
| VAT payable or credit | Quarter: |  |  |  |
| 4427 balance and side |  |  |  |  |
| Number of draft entries |  |  |  |  |

## Manual UI validation checklist

Run these checks on a disposable copy using authorized test users and synthetic
documents where possible. Record the result and build/version for each check.

- [ ] Edit a sales invoice as an administrator and as a non-administrator.
- [ ] Edit a purchase invoice.
- [ ] Edit a receipt.
- [ ] Edit a payment.
- [ ] Edit an expense.
- [ ] Save a journal voucher as draft, then post it.
- [ ] Attempt edit and cancellation in a closed month, closed quarter and
  closed year for each applicable document type.
- [ ] Save all three VAT-return pages and verify the saved values; reopen and
  explicitly re-save the return.
- [ ] Verify Arabic right-to-left entry and review.
- [ ] Export PDF and Excel and compare totals with the on-screen report.
- [ ] Create a backup and restore it into a separate disposable location.

These scripts and this guide contain no company database, names, balances,
document numbers or other client data. Do not attach real-client screenshots or
database copies to public issues, commits or pull requests.
