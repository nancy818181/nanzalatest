# Nanza 2.9.134 - release notes and pre-push checklist

Date: 24-10-2026. Previous: 2.9.133 (delivered), base archive 2.9.132. Prepared for the owner to review **before** pushing.
Nothing was pushed, sent or published. Evidence labels: **[E]** executed here, **[R]** code read only, **[U]** unverified.

## 1. What changed

### Accounting / security (headless-tested [E])
| ID | Change | Files | Tests |
|---|---|---|---|
| D3 | Duplicate invoice guard: same number (sales) / same supplier + supplier invoice number (purchases) is refused, message names the existing document. Administrators may override (`allow_duplicate`, stripped by the server for other roles). `replace_manual_invoice` is exempt for the invoice it replaces. `duplicate_invoice_report` lists legacy duplicates (read only). | `db_invoices.py`, `server.py`, `client.py`, `desktop_stage3.py` | `tests/test_v2_9_134.py` |
| D5 | Balance sheet by account type: class 4 follows the balance sign (a credit balance is a liability). Stored account types unchanged. | `db_reports.py` | `test_v2_9_134.py`, characterization tests |
| D7 | Password minimum 10 for new/changed passwords; scrypt N=2^17 (versioned hash, old hashes verify and are re-hashed at next login); session tokens stored as SHA-256 (`h1:` prefix), legacy sessions converted once. | `database_common.py`, `database.py` | `test_v2_9_134.py` |
| Payroll | Non-taxable benefits in *Additional payments*: car, housing, health insurance, sickness aid (not taxable). They go to the not-taxable column of the R6 lines and enter neither the tax base nor the NSSF base. The existing food exempt cap is unchanged. | `payroll_lines.py`, `desktop_payroll.py` | `NotTaxableBenefitsTest` |

### Screens (layout only; **not run - no Tk in the review environment**)
- New `desktop_design.py`: panels, banners, chips, stat tiles, section labels, scrolling tab bar.
- Financial Reports: tabs no longer cut off (scrolling bar with arrows and an "All tabs" list; falls back to the normal tabs on any error).
- Payroll Entry: card layout with Gross / Tax / NSSF / Net tiles and a status banner (stale-calculation warning).
- Payment & Receipt: grouped sections (Document / Payment / Bank commission and exchange difference), wider account boxes.
- Purchases: framed panel, account boxes widened (no truncated "number - name"), payment row split from the accounts row.
- Bank Reconciliation: one framed panel (account / period / balance row, action row, searchable "Book to" account box), result banner coloured by the difference (green = 0, red = difference, blue = no balance entered).
- Sales Invoice: framed panel, wider customer / paid-into / client-account fields.
- 20 Arabic strings added. Same fields, same Tab order, same variables and actions.

## 2. Not changed on purpose
- **D2 (strict posting tolerance)**: conflicts with owner rule H-03 (round half-up to 2 decimals, up to 1 unit to `import_variance`).
- **D4 (immutable posted documents)**: not implemented (high risk without Windows regression). Its delete part conflicts with owner rule H-02 (administrator may delete in an open period, audit log keeps all lines). Raw-SQL changes to `invoices` / `payments` / `expenses` (F-05, F-10) remain possible for someone with file access.
- **D6** payroll liability accounts (4411 / 4431 / 431) and **D8** pilot licence: owner / accountant decisions.

## 3. Test evidence [E]
- Full run, one process per module (see section 3 of `TRIAL_PLAN.md` for the environment). The failing set is compared test by test against the unchanged 2.9.132 tree; any difference is listed below.
- Tests updated because of D7 (they created passwords shorter than 10 characters or read the session table directly): `test_final_features`, `test_financial_statements`, `test_v2_9_52`. One pinned-type test changed in 2.9.133 (`test_vat_child_accounts_characterization`).
- UI code: `py_compile`, and stand-in `tkinter` tests for the new helper blocks (`test_ui_design_blocks`). **That is not a visual test.**

## 4. Check before push (please do)
1. On Windows: open every screen listed in section 1, in English **and** Arabic (mirrored layout), at 100 % and 125 % scaling and on a laptop-width window. Send screenshots of anything cut off or misaligned.
2. Financial Reports: click through every tab; use the "All tabs" list; switch language and confirm the tab names update.
3. Payroll: add one taxable and one not-taxable additional payment; Calculate; check the R6 not-taxable column and that tax / NSSF base exclude the not-taxable line.
4. Save a customer receipt and a supplier payment with a bank commission and an exchange difference; trial balance still balanced.
5. Try to save a second sales invoice with an existing number: refused for an accountant, confirmation for an administrator.
6. Create a user with a 6-9 character password: refused. Sign in with an existing short-password user: works, and the next login still works (re-hash).
7. Run `python tools/trial_simulation.py` on the installed Python (expects 0 failed checks).
8. Run `python -m unittest` on Windows (Tk tests included) - these could not run here.
9. Decide D6 and D8; accept or schedule D4 knowing the interim controls (administrators only, books lock, backups).

## 5. Known limits
Tk desktop, Windows installer, Arabic PDF shaping, OCR, mobile app and LAN multi-user were not executed. Payroll brackets, NSSF rates, VAT rounding and due dates were not verified against the law. FX rates in tests are synthetic. Legal/standards references in older code comments were not re-verified.
