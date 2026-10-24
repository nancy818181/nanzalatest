# Nanza 2.9.134 - trial readiness review and trial plan

Updated 24-10-2026 (2.9.134, supersedes the 2.9.133 text of F-04, F-06, F-07, F-08, F-11 and D2-D7) for the owner (certified accountant, LACPA). Basis: the source archive `nanzalatest-main` (2.9.132).
This is an engineering and accounting review of the code and of executed scenarios. It is **not** an audit opinion, a legal
opinion, a security certification or approval to run live books.

Evidence labels used below: **[E]** executed in the review sandbox (Linux, Python 3.13, no Tk) - **[R]** code read, not executed -
**[I]** independent Decimal calculation (no Nanza code produced the expected figure) - **[O]** opinion - **[U]** unverified.

## 1. Verdict

[O] Nanza can start a **controlled trial** (parallel run on a copy of real data, or a sample company) once the conditions in
section 6 are met. It should **not** yet be the only book of record, because three accounting controls are not enforced
(section 4) and the Windows desktop was not executed in this review (section 7).

What held up under execution **[E][I]**: the double-entry core (every journal entry and every currency balanced), the trial
balance, VAT quarter 1 (net and the round-up to LBP 10,000 reproduce an independent calculation), credit notes, LBP and USD
invoices, receipts and payments with allocation, year-end closing (classes 6 and 7 net to zero, trial balance still balanced),
backup copy identical to the live file, audit-trail hash chain, books lock, closed fiscal year, posted voucher immutability.

## 2. What was examined and how

| Area | How | Result |
|---|---|---|
| Existing unit tests, 166 modules, one process each | **[E]** `unittest`, per-module, timeout 240 s | 108 modules passed. 49 failed only on `import tkinter`, 1 only on `arabic_reshaper`; `test_final_features` ran 75 tests with 4 failures, all Tk / arabic-reshaper (environment). `test_release_check` failed only because the review created the `assets` link and `__pycache__` folders (environment). After the fixes (2.9.133): 167 modules, 1,067 tests ran (1,060 before + 7 new), failures/errors identical to the baseline except `test_vat_child_accounts_characterization`, whose pinned values encoded the old `asset` type and were updated with a documented reason. No new failure. **2.9.134:** 169 modules, 1,082 tests ran; the set of failing tests (compared test by test with the unchanged 2.9.132 tree, 72 vs 73) has no new member - every remaining failure is `import tkinter` / `arabic_reshaper` in this environment, and `test_release_check` now passes on the clean tree. Tests that created passwords shorter than 10 characters or read the session table directly were updated for D7. |
| Function-style tests (pytest) - the CI `unittest` job imports but never runs them | **[E]** small pytest-compatible runner written for the review (pytest is not installable here); 5 files, 183 cases | Before: 145 pass, 14 expected failures, 24 runner artefacts (fixed in the runner). After 2.9.133: 149 pass, 34 documented `xfail`, 0 fail. After 2.9.134: 151 pass, 32 `xfail`, 0 fail (POST-DUPLICATE-001 and the duplicate-identity gap test are now fixed). |
| Independent trial scenario (`tools/trial_simulation.py`) | **[E][I]** 35 checks | 33 pass, 0 fail, 2 GAP (section 4; D3 is implemented in 2.9.134). |
| Chart of accounts, posting, triggers, locks, login, API permissions, payroll defaults, licence, backup | **[R]** | Findings in section 3. |
| Tk desktop screens, Arabic PDF shaping, OCR, Windows installer, mobile app, LAN multi-user | **not executed** | See section 7. |

`pip` could not reach pypi.org from the sandbox (policy block), so `arabic-reshaper`, `python-bidi`, `PyMuPDF`, `customtkinter`
and `pytest` were not installed. Nothing was bypassed.

## 3. Findings

Severity is [O]. "Fixed" means changed in 2.9.133 and covered by `tests/test_v2_9_133.py`, which fails on 2.9.132 (checked).

| ID | Sev | Finding | Evidence | Status |
|---|---|---|---|---|
| F-01 | High | Output VAT 4427 (and sub-accounts) typed `asset` in the Lebanese chart and in the KSA/UAE templates. The account-type balance sheet showed the VAT payable as a negative asset: in the scenario (USD) the sheet showed assets 10,744 / liabilities 244 instead of 10,843 / 343 (both understated by the 99 net output VAT; equity unchanged). The IFRS statements group by balance sign and were not affected. Owner had already confirmed 4427 is a liability (`tests/golden_ledger_expected.py`). | [E] repo's strict `xfail` RPT-BS-001 + scenario | **Fixed** (seed, templates, one-time migration, audit line). Entries untouched. |
| F-02 | Medium | P&L returned float residue (`110.47999999999999`, `0.19999999999999998`). Display rounds it, but exports and any comparison do not. | [E] MONEY-FLOAT-001 | **Fixed** (exact Decimal subtraction in `profit_and_loss` and `profit_and_loss_converted`). |
| F-03 | Medium | `delete_invoice` removed a posted invoice and its journal lines but logged only number, party and total. | [E] | **Improved**: the audit trail now keeps every removed line. The delete itself is still allowed (D4). |
| F-04 | High | **Posted invoices can be hard-deleted** (invoice row, journal entries, lines) by an authorised user while the period, fiscal year and VAT quarter are open. | [E] | **Re-assessed in 2.9.134:** the application path is a *soft* delete under the owner's rule H-02 (administrator only, open period, audit log keeps every line); this finding overstated it. Raw SQL is still F-05 / F-10. |
| F-05 | High | **Immutability trigger covers only `source_type='journal_voucher'`.** Posted entries from invoices, payments, payroll are protected by the API and by a per-commit balance guard, but a *balanced* raw SQL change (one debit and one credit line raised by the same amount) succeeded on a copy. | [E] | **Open - decision D4.** |
| F-06 | High | **Duplicate invoice numbers are accepted** (a second `S-1` posted). Code comment: duplicates are "intentionally retained". Voucher numbers are unique; invoice numbers are not. | [E] | **Fixed in 2.9.134 (D3)**: a second posted sales invoice with the same number (or purchase with the same supplier + supplier invoice number) is refused with a message naming the existing document; administrators can override after confirmation. A read-only `duplicate_invoice_report` lists duplicates already in a company file. |
| F-07 | Medium | Posting tolerance: an imbalance below 0.005 is accepted on invoice paths and no rounding line is shown (voucher path rounds to 2 decimals and requires exact equality). | [E] repo `xfail` POST-DECIMAL-001 / POST-ROUNDING-LINE-001 | **Not changed (owner rule H-03, 2.9.132)**: amounts are rounded half-up to 2 decimals before any check and a difference of up to 1 unit is booked to `import_variance`. D2 as first proposed conflicts with that rule. |
| F-08 | Medium | The account-type balance sheet (`db.balance_sheet`) classifies by the account's stored type. About 40 class-4 accounts whose names are payables / creditors / taxes due / social security (421, 4211, 431, 4311, 4411, 453 ...) are typed `asset`; only 15 accounts in the whole chart are `liability`. A credit balance there shows as a negative asset, as 4427 did. Count by English-name keywords **[U]** (heuristic, to be confirmed by the accountant). | [R] chart seed | **Fixed in 2.9.134 (D5)** for the layout: class 4 follows the balance sign in `balance_sheet` / `balance_sheet_converted`; stored account types are unchanged. |
| F-09 | Medium | Payroll default mapping: `payroll_tax_account='4411'`, `nssf_payable_account='4431'` (and AI_RULES says 4411 salary tax, 4431 NSSF), but the seed chart names 4431 "Income Tax on Net Operating Profits" and 431 "Social Security Fund". | [R] | **Open - accountant to confirm D6.** Not changed. |
| F-10 | Medium | Raw SQL can still change or delete rows of `invoices`, `payments`, `expenses` in a locked period / closed year / saved VAT quarter (the journal tables are protected). Only reachable by someone with file access, not through the application. | [E] repo `xfail` DOC-LOCK-* (25 cases) | Open - part of D4. |
| F-11 | Low | Passwords: users need 6 characters (admin initial password 10); scrypt cost N=2^14 (below the current common recommendation of 2^17 [U]); session tokens are stored in clear in the company file. Login lock-out (5 users / 30 IP failures per 15 minutes), 12-hour sessions, TLS for LAN, admin-only routes are present. | [R] | **Fixed in 2.9.134 (D7)**: minimum password 10, scrypt N=2^17 with versioned hash (old hashes still verify and are re-hashed at next login), session tokens stored as SHA-256 only. Note: users created with 6-9 characters can still sign in; only *new/changed* passwords need 10. |
| F-12 | Low | Licence: new installations run 30 days then become read-only. One VAT quarter plus close is ~100 days, so a 30-day trial cannot exercise a full cycle without a seller licence code. | [R] `TRIAL_DAYS=30` | Open - business decision D8. |
| F-13 | Low | Repository hygiene: README points to `audit/TOP_20_FINDINGS.md` and `ANALYTIC REPORT.md` (absent); version text disagreed (2.9.131 vs 2.9.132); stray 1-byte `.github/workflows/.tem.txt`; `nanza/nanza_backup` (70 .py) and `nanza_delivery/nanza` are copies that can be edited by mistake; `tests` has no pytest job on the main CI so 5 files run only in two other workflows. | [R] | README version text corrected; rest left (AI_RULES: do not delete). |
| F-14 | Info | Money is Decimal-first (stored as text, DSUM aggregate, Decimal in posting, VAT, payroll). Floats appear at the screen/API edge and are exact below ~10^13. Documented by the owner. | [R] | No action. |

Previously reported AUD-01..AUD-08 (approvals as one transaction, held receipts, ageing, VAT credit notes ...) have regression
tests in `tests/test_accounting_integrity_regressions.py`; those tests pass in this review **[E]**. Not re-derived independently.

## 4. Decisions still open (owner / accountant)

Status after 2.9.134: D3, D5, D7 implemented and tested headless; D2 deliberately not implemented (conflicts with owner rule H-03); D4 not implemented (high risk, and its delete part conflicts with owner rule H-02); D6 and D8 are owner/accountant decisions. Each remaining item alters accounting behaviour and cannot be tested end to end here without the Tk screens.

| ID | Question | Recommendation [O] | Impact if adopted |
|---|---|---|---|
| D2 | Posting tolerance: reject any non-zero imbalance (no 0.005 tolerance) and show a separate rounding-difference line when a rounding is intended? | Reject exact imbalance; add an explicit rounding line (a dedicated account) only for documented rounding cases. | Some imports/invoices that balance only within 0.005 will be refused; tests `POST-DECIMAL-001`, `POST-ROUNDING-LINE-001`. |
| D3 | Invoice identity: reject a second posted sales invoice with the same number; for purchases reject the same (supplier, supplier invoice number)? | Yes, with an override only for administrators and a message naming the existing document. | Lebanese sales invoices are sequential; duplicates are an audit finding. Existing data containing duplicates must be listed first (a report, not a block). Test `POST-DUPLICATE-001`. |
| D4 | Posted documents: stop hard deletion of posted invoices / payments and make posted invoice-source entries immutable like vouchers; correction only by credit note or reversal. | Yes. Implement as: triggers on all posted source types + a controlled maintenance path (administrator, audited, period open) for the screens that legitimately rewrite entries today (invoice edit while in review, account merge, renumbering, year re-close). | Largest change: touches `delete_invoice`, `mark_invoice_deleted`, `clear_invoices`, payment edit, VAT reclass, resequence, account merge. Needs Tk/Windows regression; not done blind. Tests `POST-IMMUTABILITY-001`, `DOC-LOCK-*`. |
| D5 | Balance sheet by type: group class 4 by balance sign (as the IFRS statements do) instead of the stored type? | Yes, keep the stored type as default and let class 4 follow the sign. | Changes the layout of the account-type balance sheet screen/PDF only. |
| D6 | Confirm the payroll liability accounts (4411 / 4431 / 431) against the chart actually used by the client. | Accountant check before the first payroll posting. | None until confirmed. |
| D7 | Raise user password minimum to 10, scrypt N to 2^17 with a versioned hash re-written at next login, hash session tokens. | Yes (backward compatible). | Existing users keep logging in; tests that create short passwords need updating. |
| D8 | Trial length / trial licence code for a 3-4 month pilot. | Issue a dated licence code for the pilot installation. | None in code. |

## 5. Expected figures (trial scenario, synthetic)

Run `python tools/trial_simulation.py` (exit 0 = no failed check). It is also test `TrialSimulationTest`. To repeat by hand in the
application: set USD -> LBP = 89,500 for 2026 (synthetic rate, not a recommended rate), create a customer and a supplier, post:

| # | Date | Entry | USD / LBP |
|---|---|---|---|
| 1 | 01-01-2026 | Voucher T-001: Dr 531 cash / Cr 1013 capital | USD 10,000.00 |
| 2 | 05-01-2026 | Sales invoice S-1, 1 x 1,000.00 + 11% VAT = 1,110.00 | USD |
| 3 | 06-01-2026 | Purchase invoice P-1, 1 x 400.00 + 11% VAT = 444.00 | USD |
| 4 | 10-01-2026 | Customer receipt 500.00 allocated to S-1 (cash 531) | USD |
| 5 | 12-01-2026 | Supplier payment 200.00 (cash 531) | USD |
| 6 | 15-01-2026 | Voucher T-002: Dr 601100000 / Cr 531 | LBP 8,950,000 |
| 7 | 20-01-2026 | Sales credit note CN-1, 100.00 + 11% = 111.00 on the customer | USD |
| 8 | 25-02-2026 | Sales invoice S-LBP-1, 10,000,000 + 11% VAT | LBP |

Expected trial balance at 31-12-2026 (debit / credit, as produced by the run **[E]**, equal to the independent sums **[I]**):

| Currency | Account | Debit | Credit |
|---|---|---:|---:|
| USD | 1013 Capital | | 10,000.00 |
| USD | 401100001 Supplier | 200.00 | 444.00 |
| USD | 411100001 Customer | 1,110.00 | 611.00 |
| USD | 44210 VAT on purchases | 44.00 | |
| USD | 4427 VAT collected | 11.00 | 110.00 |
| USD | 531 Cash on hand | 10,500.00 | 200.00 |
| USD | 601100000 Expenses | 400.00 | |
| USD | 713 Sales of services | 100.00 | 1,000.00 |
| **USD total** | | **12,365.00** | **12,365.00** |
| LBP | 411100001 Customer | 11,100,000 | |
| LBP | 4427 VAT collected | | 1,100,000 |
| LBP | 531 Cash | | 8,950,000 |
| LBP | 601100000 Expenses | 8,950,000 | |
| LBP | 713 Sales | | 10,000,000 |
| **LBP total** | | **20,050,000** | **20,050,000** |

Other expected results: customer USD 499 debit; supplier USD 244 credit; balance sheet USD assets 10,843 = liabilities 343
(supplier 244 + VAT 99) + equity 10,500 (capital 10,000 + result 500); P&L result USD 500, LBP 1,050,000; VAT Q1 net LBP 6,022,500,
payable LBP 6,030,000 (rounded up to 10,000, the rule recorded in AI_RULES section 5 - **[U]** by this review: confirm the current
Ministry of Finance rule and the 2026 due-date rule before filing); year close net results USD 500 / LBP 1,050,000.

## 6. Trial plan

**Prerequisites (before day 0)**
1. Install on a Windows PC like the client's, from the Windows installer built by `build-windows-installer.yml`; start, create a
   company, sign in, change the initial administrator password (10+ characters). The GUI was not run in this review.
2. Obtain a pilot licence code if the trial is longer than 30 days (D8).
3. Work on a **copy** of real data. Take a manual backup, restore it on a second PC, compare the trial balance (backup/restore
   was verified headless only).
4. Confirm with the accountant: chart of accounts used, payroll liability accounts (D6), VAT rate and rounding rule, base currency.
5. Decide D3 / D4 before the pilot or accept the interim controls: administrators only for delete, books lock after each month
   close, weekly backup check.

**Phases**
- Day 0: install, company setup wizard, opening balances (trial balance of the old system = Nanza opening trial balance, debit = credit per currency).
- Week 1: post one real week of invoices, receipts, payments, expenses in parallel with the old system. Daily: trial balance debit = credit; customer and supplier balances agree with the old system.
- Month end: bank reconciliation, ageing vs ledger, VAT worksheet vs old system, payroll for one month vs the manual calculation (the payroll brackets, NSSF rates and ceilings were **not** verified against the law in this review), lock the books to the month end.
- Quarter end: VAT return Q-n compared with the previous filing method; saved return and reopen test; fiscal-year close rehearsal on a copy and reopen.
- Exit review.

**Acceptance criteria** (each must be evidenced, with the screen or report attached)
1. Opening trial balance and each month-end trial balance: total debit = total credit in every currency and equal to the old system's totals.
2. Customer and supplier control accounts equal the sum of open documents (ageing) at each month end.
3. VAT quarter: output, input, deduction ratio, net and payable equal an independent manual calculation.
4. Balance sheet balances; output VAT appears under liabilities; P&L equals the trial balance classes 6-7.
5. Backup restores to an identical trial balance on another PC.
6. No entry is changed or deleted after posting except through a reversal / credit note (check the audit trail for `delete` and `mark_deleted` actions).
7. `tools/trial_simulation.py` passes on the installed Python build (core and control checks).
8. Arabic PDFs (trial balance, invoices) render and totals agree with the screen (needs arabic-reshaper; not tested here).

**Rollback**: the old system remains the book of record during the pilot; Nanza company files are copies; keep the pre-pilot backup.

## 7. Limits of this review

- **Not executed:** Tk desktop, Windows installer and Windows-only tests (2 skipped by the owner's own report), Arabic PDF shaping
  (`arabic-reshaper` missing: 2 further tests fail here), OCR engines, mobile app, LAN / multi-user / TLS behaviour, performance with large files.
- **Not verified against law or official sources:** Lebanese VAT rate and rounding rule, the VAT due dates, payroll tax brackets,
  NSSF rates and ceilings, end-of-service rules, IFRS paragraph references quoted in code comments. They are used as the owner's
  documented rules (AI_RULES section 5). Verify before filing.
- The exchange rates in all tests and in the scenario are synthetic fixtures.
- Class-4 account typing count (F-08) is a name heuristic.
- No client data was used; no network call left the sandbox; nothing was sent or published.
