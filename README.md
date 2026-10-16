# Nanza Accounting (formerly Saber Accounting)

## Version 2.9.126 (review fixes: payroll numbers, VAT chain, comparative trial balance, faster reports and OCR)
- **Reviewed by Claude, plan agreed with ChatGPT before the change, and the code reviewed by ChatGPT before release.** Every point was checked in the code first; ChatGPT's conditions and its six review findings were fixed, each with a test.
- **Payroll numbers stay fixed:** saving a draft payroll again (same employee and date, or by its record id) updates that record and keeps its payroll number; before, every re-save gave it a new number (PAY-...-000001 became 000002). A number is allocated only for a new record. An update by id must be for the same employee and date; a posted payroll is never changed. The monthly payroll sheet now sends the record id.
- **VAT credit chain:** the check for earlier VAT activity reads the document dates once per calculation and shares the result with every quarter of the credit chain (measured on 20,000 expenses: about 55 ms for eight quarters, before 70 ms). A date that cannot be read, or an impossible date such as 31-02 or 29-02 outside a leap year, still keeps the chain open. When an earlier, unsaved quarter cannot be calculated (for example a missing exchange rate), the return still opens as a **PROVISIONAL** preview: the reason and the quarter are shown first, the credit brought forward is marked UNKNOWN (also in the later quarters that depend on it), and Save and Settlement are refused until that quarter is corrected (checked again on the server, not taken from the screen).
- **Depreciation vouchers:** each voucher's description names its own asset account and currency (posting several accounts at once no longer wrote the same text, or "None", on every voucher). Amounts and posting accounts were already correct.
- **Comparative Trial Balance:** new tab in Financial Reports, with PDF, Excel and Print. For each account: opening, movement and closing of the period, the closing of the same period one year earlier (from the prior-year file when the company keeps one file per year) and the signed variance (debit positive, credit negative). 29 February compares with 28 February. Balances are in each account's own currency, exact to the cent and without exchange rates (a missing EUR rate cannot stop a USD comparison); when the company keeps one file per year, the prior-year file is always the source of the prior year. When the prior period has no posted entries, its columns are blank and the report says so, instead of showing zero balances. If this report fails, the other financial reports still load and the tab shows why.
- **Financial Reports no longer freeze the screen:** the reports are fetched and calculated in the background; only the tables are filled on the screen. If the dates or filters change while a report is loading, the older result is ignored. Exports print the period, currency, account range and ledger filters the figures were loaded with; export waits until loading has finished and asks for a refresh when the dates, currency or account range were changed after loading (before, June figures could be exported under a July title). The ledger export also no longer fails when ledger filters are chosen.
- **Advanced Local OCR stays loaded:** the PaddleOCR reader now starts once and reads the next invoices without loading its models again; it stops after 5 minutes without use. One invoice at a time; a reading that takes too long stops the reader (the next reading starts a clean one) and is not retried; a reader that cannot start is stopped and the one-shot reader is used. Every reading still needs review before Save.
- **Report precision:** the Comparative Trial Balance keeps exact Decimals from stored amounts through the API client and PDF/Excel export. Its API uses decimal strings, restored to numeric Decimals for display. Other existing numeric report APIs still use floats; detected precision loss in the shared serializer is logged. Logging does not restore lost precision.

## Version 2.9.125 (financial report layout and reconciliation)
- Financial statement PDFs use clear section spacing, subdued table headers and stronger total rules. Arabic columns follow the report language independently of the UI. Company headers repeat on statement pages; totals stay with the preceding detail row. Amounts use two decimals and accounting negatives.
- Financial workbooks repeat statement table headers on printed pages, freeze headings and define print areas. Notes keep their own narrative layout and do not repeat entire note blocks as print headers. Exact Decimal amounts are formatted without binary-float rounding; values exceeding Excel's 15 significant digits are retained as decimal text.
- Added **Financial Statement Reconciliation** to Business Reports and a preparer-only control page in the statement pack: balance-sheet equation, opening/closing cash versus reported cash flows, and gross unmapped balances. Opposite unmapped account balances cannot hide each other. Incomplete cash flow overrides and unreconciled reviewed cash flow amounts are flagged. These checks do not replace an audit or cash flow classification review.
- Normal financial report PDF/Excel/print exports include company, period or reporting date, currency and relevant account/ledger filters, with wrapping column layouts. The Balance Sheet screen now honors the same account range as its export.

## Version 2.9.124 (optional advanced local OCR)
- **Advanced Local OCR:** Settings > Accounting Settings > Install / Repair Advanced Reader installs a separate, per-user Python runtime with CPU PaddleOCR and Arabic/English models. On installed Windows copies, setup downloads Python 3.12.10 from python.org and checks its Authenticode signature against Python Software Foundation before running the per-user installer. No administrator rights or API key are needed. Downloads can be large; setup stays off the UI thread.
- The extra reader runs in a separate process with a 120-second deadline, reuses detected text boxes for Arabic/English recognition, and compares complete readings rather than constructing a balanced total from unrelated guesses. A busy or failed reader falls back to local OCR with a review warning. Ordinary reading requires the downloaded models and does not download missing models in the background.
- Photos and single-page scanned PDFs are supported by the extra reader. Multi-page PDF imports continue to use local Tesseract. The reader can be disabled in Settings without removing the downloaded models. Physical text rows are restored before parsing. Readers disagreeing on invoice number clear that number for manual confirmation; other disagreements are displayed. Every OCR result requires review before automatic posting. Arabic handwriting remains imperfect; this is not a guarantee of correct amounts.
- Installer/runtime setup is covered by mocked process tests; the Windows installation itself must be checked on Windows. Real photo checks are performed locally without committing invoices or OCR output.

## Version 2.9.123 (dated exchange rates, complete VAT returns, cumulative payroll tax)
- **Dated EUR rates:** conversions require a real rate on or before the document date, including inverse and EUR/LBP cross rates. No 1:1 fallback and no future quote. Historical downloads carry rates forward only; today's quote never fills earlier days. Missing or invalid rates explain what must be corrected.
- **Complete VAT returns:** saving is blocked when a posted document has an unreadable date or amount, including NaN/infinity and documents needed for the deduction ratio or an unsaved previous quarter's credit. The error lists documents to correct; preview remains available. A missing exchange rate in the credit chain is no longer silently treated as zero credit.
- **Cumulative salary tax for the whole calendar year:** every month from January through December recalculates year-to-date tax and deducts all earlier withholding in that year. There is no three-month reset: December includes all 12 months, and January starts a new tax year. Prior partial months use their actual tax fraction. Prior withholding offsets the total including a current bonus before a zero floor is applied; retroactive salary tax remains separate. The payroll calculation notes show cumulative tax due, earlier withholding and this month's tax before rounding; the monthly sheet labels the deduction as this month's tax.
- **Report accuracy:** the shared ledger/trial-balance engine reads stored decimal amounts without casting them through binary floats. Invalid dates, unreadable amounts and NaN/infinity stop the report with the entry number instead of disappearing or becoming zero.
- **Photographed invoices:** additional OCR candidates correct a detected paper perspective, uneven lighting and table rules. Alternative readings are scored separately, so unrelated digits are not concatenated into one plausible invoice. Inferred totals and unreadable required fields pause automatic posting for review; original photos are unchanged.
- **Currency recognition:** the printed words "Bill to" no longer falsely identify a document as LBP through the letters "ll". Unknown currency remains unknown until read or confirmed.
- **Arabic expense descriptions:** the classifier recognizes common repair wording (تصليح، إصلاح، بواجي) and advertising wording (دعاية، اعلان، تسويق), once the description is read or entered. This does not make local Tesseract handwriting recognition reliable.
- **Expense upload classification:** expense photos now go through OCR, like PDFs. For a new supplier, the expense form can also apply the account learned from similar previous descriptions when no account was chosen.
- **Asset validation and ledger links:** fractional useful-life months and wrong account classes are refused. An asset links only to a posted Assets purchase, excluding credit notes. Asset currencies follow the company's configured currency list. Depreciation vouchers cannot be edited/deleted independently of their asset posting records. Active asset purchase invoices cannot be edited, cancelled, deleted or removed by bulk invoice replacement while linked.
- **Asset depreciation accuracy:** the monthly table, exports and vouchers separate currencies and depreciation/accumulated accounts. USD and LBP are never summed into one amount or posted in the first asset's currency. Posting a depreciation voucher and linking every asset now happens in one atomic transaction.
- **Payroll sequence protection:** one payroll per employee/month; earlier months cannot change after a later month is posted. Draft tax is recalculated and checked before posting, so an earlier edit cannot leave a stale cumulative deduction. Saving and posting payroll now hold one atomic transaction.
- **NSSF salary base shown in reports:** newly calculated payroll now includes the subject-to-NSSF allowances in the saved/displayed contribution base, as already included in the contribution calculation. Existing saved payroll is not rewritten.
- **Monthly and annual employee tables:** the annual Movement view now covers January-December and totals salary, tax, NSSF and net pay for the whole year instead of showing December in its main columns. R5 and R6 are checked against all twelve monthly tables, separately for employees and managers.
- **Invoice posting memory:** saved supplier purchases and expenses already teach the next invoice its accounts, VAT treatment, dimensions and payment settings. When a scan contains both buyer and supplier tax numbers, the supplier name now disambiguates the rules; conflicting unidentified numbers do not choose an arbitrary supplier.
- **Memory after confirmed PDF imports:** purchase invoices saved from the PDF upload/import screens now teach supplier posting memory too, rather than only invoices saved on Purchases. Opening balances and customs cases are excluded.
- **OCR before automatic posting:** low-confidence or inconsistent Azure readings pause automatic save/posting until the invoice is reviewed. Missing VAT stays blank instead of being filled with a guessed percentage. Item suggestions no longer clear existing lines before confirmation.
- **Handwritten invoice reading:** the existing optional Azure reader reads photos/scans using the company's own configured key. Low-confidence fields and inconsistent subtotal/VAT/total are now named in the reading notes; non-finite amounts are rejected. Reading quality still depends on the original handwriting and must be checked before saving.
- Regression tests cover missing/future/direct/inverse/cross rates, historical downloads, incomplete VAT saves, full-year payroll withholding and January reset, supplier identity conflicts and OCR review warnings.

## Version 2.9.122 (VAT payable rounding confirmed)
- **VAT payable rounded up to the next LBP 10,000 (MoF decision 1195, from 25-11-2024):** confirmed by the accountant (LACPA). The amount is unchanged; the "unverified estimate" warnings on the VAT return, the export and the filing worksheet are removed.

## Version 2.9.121 (every document saved whole; reviewed with ChatGPT; users per company; licence ended = read only)
- **Reviewed by two AIs and checked in the code:** ChatGPT reviewed the architecture and then the posting code (invoices, payments, VAT return, exchange rates); every point was checked in the code before anything was changed. What was confirmed is fixed below; what was not accurate was left as it is.
- **Every document is saved whole, or not at all:** an invoice (with its lines, entry, stock, VAT reclass and payment), a receipt / payment and its allocations, an expense, a journal voucher, a return, a credit note, a cancellation is ONE transaction. Before, an invoice was saved in several steps; a power cut between two steps could leave an invoice without its lines or its stock. A test stops the program in the middle of an invoice and checks that nothing of it is in the file and the file is intact. The data file now writes each saved document to the disk before Save answers (SQLite synchronous FULL).
- **VAT settlement:** posting the settlement of a quarter replaces the closing and settlement vouchers in one transaction (never the old ones deleted without the new ones).
- **No more 1 EUR = 1 USD:** when no EUR rate exists on or before a date, the first rate entered after it is used; an EUR invoice, receipt / payment or expense is refused while no EUR rate at all is entered ("enter the EUR rate first") instead of being converted at 1 EUR = 1 USD. Saving a USD/LBP rate no longer makes an EUR/LBP rate from a missing EUR rate.
- **Allocations never more than what is open:** a receipt / payment can no longer be allocated beyond what is still open on an invoice (all payments together); the rest stays on the account as an advance.
- **VAT return reads amounts exactly:** a 0 stays 0 (no fall-back to another column), and a document whose amount cannot be read ('110,00') is no longer counted as 0: it is left out and listed, with the field, in the notices of the return to be corrected before filing.
- **Books Health Check:** new point "Sales VAT = rate x amount" lists the posted sales lines whose VAT was typed by hand and differs from the rate (typing it stays allowed).
- **Users per company:** Settings > Users > Companies... chooses the companies each user may open (an accounting office: a clerk sees only his clients). None chosen = every company, as before; administrators open every company.
- **Licence ended = read only:** when the licence or the trial ends the books are no longer locked: they open read only (reports, exports, backups), with the window to enter the new code. Nothing new is saved until a new code is entered.
- **Uploaded Data > Choose PDF Invoice(s):** each supplier's invoice is filled the way its last invoice was posted on the Purchases screen (type, account, VAT account), with the note "Posted like ...".
- **Financial statements without the auditor's report:** Financial Reports > Business Reports > Financial Statements has the tick "With the auditor's report" (ticked = as before). Unticked, the pack is the management financial statements: no auditor's report page, no "and independent auditor's report" on the cover, titled "Financial Statements and Notes" (English, French, Arabic).
- **Ageing at a past date:** the note on the Ageing screen now says what the report does: a past date shows what was open on that date (receipts / payments after it are not counted).
- **Lebanese law checked (October 2026):** the program already follows the Budget Law 2026 (Law 40: no input VAT on utilities and passenger cars, the VAT return due one month after the quarter) and Decree 2923 (NSSF family branch: ceiling LBP 28,000,000, spouse 2,100,000, child 1,155,000 from 01-05-2026). The 10,000 LBP rounding of the VAT payable stays marked "unverified" on the return.

## Version 2.9.120 (fast with a big company; posting rules learned per supplier; lines classified; optional Azure reader with your own free key)
- **Fast with a big company:** tested with a made-up year of 1,500 customers, 150 suppliers, 20,000 invoices (3-5 lines each), 8,000 receipts and 2,000 journal vouchers (tools/scale_test.py). Tables no longer slow down with the square of their lines and fill in parts (the first lines at once); exchange rates are looked up once per screen; the report filters are read once; the dashboard charts no longer read every invoice line. With that company: Dashboard charts 2 s (was 4), Financial Reports with all 80,000 ledger lines about 9 s (was more than 5 minutes), Uploaded Data about 4 s (was 46), trial balance 1.3 s, VAT return about 1 s, Books Health Check 2.3 s, saving an invoice 0.02 s. The dashboard leaves the opening invoices (Start with Nanza) out of the year's sales. Nothing else changes.
- **Posting rules (memory per supplier):** when a purchase (Purchases screen) or an expense of a supplier is saved, the way it was posted is remembered for that supplier - cost / asset account, VAT account, Purchases or Assets, VAT use, reverse charge, department / project, how it was paid and from which account, "not deductible for income tax". Choosing the supplier, or uploading its PDF / photo, fills the next invoice the same way, found by its MOF / VAT number (123456-601 = 123456), its name, or a name very close to it (S.A.R.L. = SARL). A note says "Posted like F-123 of X (learned from N invoices) - check before Save": only a suggestion, nothing is saved by itself. Settings > Accounting Settings > Show Posting Rules lists them; any rule can be deleted. Invoices already saved never change.
- **Lines classified:** every word of the lines saved votes for the account they were posted to; a new supplier's lines get the account most used for the same words (e.g. "diesel" -> the fuel account you use), then the keywords of the categories (electricity, rent, fuel...) and then the names of the chart of accounts - with where the suggestion comes from and how sure it is. Free, on this computer, no internet.
- **Optional: read invoices with Azure (your own free key):** for handwritten or hard-to-read invoices, Settings > Accounting Settings > Azure Settings takes the endpoint and key of the company's OWN Microsoft Azure AI Document Intelligence resource, free tier F0 (500 pages a month, the first 2 pages of each file, files up to 4 MB). Then "Read with Azure" appears on Purchases and Expenses (only on that computer). The file goes from the computer straight to the company's Azure resource only when the button is pressed; Nanza receives nothing; the key stays on that computer (protected by Windows), never in the company file or its backups. A counter stops at the monthly limit (500 by default) so the free tier is never passed, and when Azure cannot read (no internet, refused key, limit) the free local reading is used. How well Arabic handwriting is read depends on Azure: try it on a few of your invoices. Without a key nothing changes.
- **Help with pictures:** new topic "Posting rules and reading invoices" (English and Arabic pictures).

## Version 2.9.119 (Books Health Check; no silent errors on the money; Start with Nanza; reports in Arabic)
- **Books Health Check** (Settings > Accounting Settings, and on the dashboard when something is found): read only, at any time - every entry balanced and the trial balance in each currency; every posted invoice, receipt / payment, expense and payroll has its journal entry; no entry left by a deleted document; invoices: subtotal + VAT = total, lines = subtotal, the entry carries the invoice total; no duplicate numbers, supplier invoices entered once, sales invoices numbered without gaps; lines on existing accounts and not on heading accounts; entries inside the fiscal year; saved VAT returns unchanged; the audit trail intact; no EUR rate of 1 USD. Each point: OK / WARNING / ERROR, the document numbers and what to do; Excel / PDF.
- **No silent errors on the money:** where a problem used to be passed over quietly it is now said (or stops the work with its reason): a missing USD rate for the passenger-car VAT rule (the whole VAT was deducted), the credit brought forward of a saved VAT return that could not be read (it became 0), the lock of a quarter whose VAT return is saved, a payroll setting that is not a number (the default was used), a change of invoice missing from the audit trail, the "not deductible" tick not saved, an asset purchase not linked. The number checks catch the exact errors: the broad "except Exception" are down from 733 to 679.
- **EUR rates offline:** before, starting the program without internet wrote 1 EUR = 1 USD for every day since 2024 and kept it. Now no EUR rate is written offline; once online the real rates replace those days, and the Books Health Check lists the EUR documents of such days.
- **Start with Nanza (opening balances from Excel):** Settings > Accounting Settings > Excel Template, then Check & Import. One workbook: Opening balances (one Opening Voucher type 04 per currency, OB-year-currency), Customers & Suppliers, Open invoices (in the ageing and statements, settled by receipts / payments; posted against 479 Opening balances - open documents, not sales or purchases of the year: no revenue, no VAT, not on the dashboard), Items with opening stock. Every line is checked first; nothing is saved while one is wrong; a safety backup is made before.
- **Reports in Arabic:** with the program in Arabic, Excel exports read from right to left with Arabic titles and column titles, PDF reports start from the right, and the printed sales invoice is in Arabic (labels, totals, amount in words first, mirrored layout). English unchanged.
- **Help with pictures:** new topic "Start with Nanza and check the books" (English and Arabic pictures).

## Version 2.9.118 (the program in Arabic, right to left; tidy forms as in Zoho; totals card)
- **The program in Arabic (right to left):** the **عربي** button at the top (or Language = ar at sign-in) turns every screen to Arabic: the menu on the right, buttons, labels, box titles, tabs, table titles, menus, window titles and messages, laid out from right to left (tables start from the right). **English** at the top turns it back, on the same company, year and screen. Nothing changes in English, and the program keeps working with the same values (lists such as Invoice / Services and the data stay as they are). About 1,700 texts in nanza/ui/arabic_texts.py.
- **Tidy forms (as in Zoho / Odoo):** the sales invoice, the customer receipt / supplier payment and the journal voucher show their fields in two columns of label | field that line up. The same fields, made in the same order (the Tab key goes through them as before), with the same keys and actions. The NEW INVOICE badge is at the end of the Find invoice row.
- **Totals card on the sales invoice:** Total, Discount, Total HT, VAT and the TOTAL TTC to pay in a white card at the bottom right.
- **Photos of invoices and bills are read (JPG / PNG):** Purchases (Upload PDF), Expenses and Uploaded Data > Choose PDF Invoice(s) read a phone photo or a picture of a scan like a scanned PDF (before, a picture was only attached).
- **EDL bills photographed:** the dot-matrix amounts on the pink form are read better (an extra reading without the coloured background); the VAT number printed at the top ("N° TVA : 241559") is no longer taken as the VAT amount; and when only the base (total of the tranches) can be read, the VAT 11%, the 100,000 stamp and the total rounded up to the thousand are filled in (671,250 + 73,838 + 100,000 -> 846,000), marked "please check". The supplier is suggested as Electricité du Liban (EDL) and the account as Electricity Expenses.
- **Help with pictures in Arabic too:** in Arabic the help shows pictures of the Arabic screens.
- **Releases:** a GitHub Release (read by the update check) is published only by "Run workflow" on main, as since 2.9.42; pushes build the installer only.

## Version 2.9.117 (the code in folders; code signing in the cloud; commercial register in the wizard)
- **The program is now in folders by subject** - nothing it does changes:

  | Folder | What is in it |
  | --- | --- |
  | nanza/core | data files, data service, users, licences, backups, audit trail |
  | nanza/accounting | charts of accounts, numbering, inventory, fixed assets, bank, year end |
  | nanza/tax | VAT return, VAT ledgers, tax review |
  | nanza/payroll | Lebanese payroll, NSSF / MOF forms |
  | nanza/reports | financial statements, ledgers, management pack, exports |
  | nanza/documents | PDF reading, AI mapping, PDF forms, logos |
  | nanza/ui | every screen of the program |
  | tests | the tests (run: python -m unittest discover -s tests -t . -p "test_*.py") |
  | tools | help pictures (make_help.py) |

  The entry points stay at the top: run_desktop.py, run_server.py, backup_service.py. nanza_paths.py puts the folders on the import path, so every module imports the others by name as before; the Windows build searches every folder.
- **Code signing in the cloud (SSL.com eSigner):** certificates bought since June 2023 are no longer given as a .pfx file. Add the repository secrets ES_USERNAME, ES_PASSWORD, ES_CREDENTIAL_ID and ES_TOTP_SECRET and the build signs NanzaAccounting.exe, NanzaAccountingBackup.exe and NanzaAccountingSetup.exe; without them the build works as before (the .pfx signing of 2.9.52 stays too).
- **New company wizard:** step 1 also asks for the Commercial Register number and place (as in Settings > General Settings; written on the NSSF and MOF forms).

## Version 2.9.116 (Odoo + Zoho + ERP: setup wizard, four charts of accounts, numbering, a clearer look, help with pictures)
- **Help with pictures (English and Arabic):** a **Help** button beside the title of every screen opens the help of that screen: a picture of the screen with numbered steps and a short line for each, in English or Arabic (button at the top). 17 topics (every screen and the new company wizard). The pictures are taken from the program itself by tools/make_help.py and are taken again in every Windows build, so they follow the screens. New folder Assets/help (shipped with the program).
- **New company = a setup wizard (as in Zoho):** 1. company, 2. country and chart of accounts, 3. currencies and VAT (filled from the country), 4. fiscal year and summary.
- **Four charts of accounts to choose from:** Lebanon (the Lebanese chart, exactly as before), International (IFRS), Saudi Arabia (IFRS + VAT 15%, Zakat, GOSI, withholding tax) and UAE (IFRS + VAT 5%, Corporate Tax 9%, GPSSA). Every chart keeps the same classes (1 equity ... 7 income) and every account the program posts to, so the VAT return, ledgers, financial statements, payroll and automatic entries work with all of them; the names follow IFRS in English, Arabic and French. A company keeps its chart (an upgrade never brings the Lebanese chart back, and names the user changed are kept). Companies created before, or without a choice, keep the Lebanese chart.
- **Chart of Accounts > Import from Excel (administrator):** columns Account, Parent, English, French, Arabic, Type (the table exported to Excel has them). New accounts are added and names filled in; nothing is deleted and the type of an account used in entries never changes.
- **Settings > Numbering:** the prefix of each kind of document (RV, PV, JV, EXP, SAL, PUR by default - unchanged) and, for sales invoices, purchase invoices and journal vouchers, the branch in the number (SAL-BEI-2026-000001; each branch counts on its own). Renumber by date (2.9.115) is on the same tab and follows the chosen prefixes and branches.
- **Look:** a row with many light buttons shows the everyday ones (New, Add, Print...) and puts the others in a **More** menu (same commands; the gold main action and the red ones always stay in view); small icons on the side menu and on New / Save / Print / Delete / Excel / PDF; the Dashboard figures as large **KPI cards**; softer navy text on forms.
- Nothing that worked before changes: the Lebanese chart, VAT, NSSF / MOF forms, reports, data and numbers. New modules chart_templates.py, numbering.py, icons.py, desktop_setup_wizard.py, tools/help_topics.py, tools/make_help.py; routes POST /api/accounts/import and GET / POST /api/numbering (administrator).

## Version 2.9.115 (renumber documents by date; a calmer, clearer look)
- **Settings > Renumber (administrator):** puts the numbers back in date order after a document was entered with a wrong date - customer receipts (RV), supplier payments (PV), journal vouchers (JV), expenses (EXP), purchase invoices (PUR) and sales invoices (SAL). Choose the documents and the year, press **Preview** to see every current -> new number, then **Renumber**.
  - Only the program's own numbers change (RV-2026-000012); a number typed by hand or an imported supplier number is never touched.
  - Documents in locked books, a closed fiscal year or a quarter whose VAT return is saved keep their numbers; the documents after them follow on.
  - A safety backup is made first, everything changes in one step, and the Audit Trail keeps every old -> new number. The journal entry of a receipt, payment or expense takes the new number; an invoice's entry mentions it. Amounts, dates, accounts, allocations and attachments do not change.
  - Sales invoices: a warning reminds that invoices already given to customers carry the old number.
  - New module resequence.py, screen desktop_renumber.py; routes GET /api/renumber (preview) and POST /api/renumber (administrator).
- **Look (only the look changes):** buttons by importance as in Odoo / Zoho - one gold main action (Save ...), red for delete, every other action a light button with a thin border (they were all solid navy); table headings light grey-blue with thin column lines instead of solid navy; no grey box around unused tick boxes.

## Version 2.9.114 (the program file is named Nanza)
- **The program file is now NanzaAccounting.exe** (was SaberAccounting.exe), the background backup **NanzaAccountingBackup.exe** and the setup **NanzaAccountingSetup.exe**. Explorer (Properties > Details), the Task Manager and "Open with" now show **Nanza Accounting** with its version, from Windows file details written into each program at build time.
- Updating an installed copy: the setup stops the old and the new programs, removes the old SaberAccounting.exe, SaberAccountingBackup.exe and the old "Saber Accounting Backups" start-up shortcut, and points the Start menu / desktop shortcuts to NanzaAccounting.exe. A taskbar pin made on the old program file must be pinned again once.
- **Every "Saber Accounting" the user sees now says "Nanza Accounting"**: message titles, report and export titles (Dashboard, Trial Balance, General Journal, Profit & Loss, Invoices) and their suggested file names, licence messages, backup and company-file messages, the office server, the file-type names in the open / save boxes, the user guide and the labels that said "before Saber". The suggested OneDrive folder for the second backup copy is "Nanza Accounting Backups" (a folder already chosen is kept). "Saber for Audit" (the publisher) stays.
- **Data folder on a new computer: C:\Users\<name>\NanzaAccounting.** A computer that already has the SaberAccounting folder keeps using it - nothing is moved or renamed, so every company, year, backup, licence and log stays where it is. The messages that name the data folder now say "Nanza data folder", and the error message shows the real path of the log file.
- **File names in a new data folder are Nanza too:** main data file nanza_accounting.db (its backups nanza_accounting_<date>.db), error log logs/nanza.log, and .nanza.lock / .nanza.window. A folder that already has saber_accounting.db, saber.log or .saber.* keeps those names - no file is renamed, so backups, restore and the log keep working as before.
- Nothing else changes: the company files, licences, the office-network and update checks work exactly as before, so old and new copies still work together.
- New installations go to Program Files\Nanza Accounting; an installed copy keeps its folder (same AppId). The company data folder (SaberAccounting) is NOT renamed, so every company, year, backup and licence stays exactly where it was.

## Version 2.9.113 (the "not deductible for income tax" tick on every entry screen)
- **Journal Voucher, Purchases and Payment & Receipt** now have the same tick as Expenses: "Not deductible for income tax (no official invoice) | غير مقبول ضريبياً". It is saved with the entry and shown again when the entry is opened.
- A ticked entry **stays in the books** (journal, ledgers, trial balance, balance sheet, financial statements). Its expense lines (class 6) are listed in Expenses > Non-deductible report (to add back to the taxable profit) and left out of the "P&L tax basis" in Accounts & Statements.
- **Settings > General:** "Show the tick ... on the entry screens" - untick to hide it on every screen at once. Hiding never changes a tick already saved: those entries stay in the add-back report and out of the P&L on the tax basis.
- **Sales: income not subject to income tax** (Settings > General switches it on): on a sales invoice choose the legal reason - interest taxed at source, dividends already taxed, capital gain taxed separately, or exempt by law (the article is required). The income stays in the books; it is listed with its reason in the tax adjustments report (Expenses > Non-deductible) as a deduction and left out of the P&L on the tax basis. An invoice already marked always shows its reason, even when the option is switched off.
- New tables tax_flags and income_exemptions; routes /api/tax-flags and /api/income-exemptions; settings show_tax_tick and enable_exempt_income.

## Version 2.9.112 (every box of the NSSF / MOF forms; forms in Arabic or English; P&L on the tax basis)
- **Every box filled.** CNSS 2AA: salary at the date of entry (الاجر بتاريخ دخول العمل - the current salary when no other is given), registry number and place, caza of birth, sect, the full address box by box (governorate, caza, town, district, street, building and floor), hours per month, full / part time, work permit, other employer (كلا when none is written), the employee's date. Leaving notice: current job (عمل الأجير الحالي), registry number, the employee's date. CNSS 41A: registry number, hours, full / part time, other and previous employer, dates. MOF R3: registry number and place (رقم السجل / مكان السجل).
- **Employee file:** new box "Official forms details | معلومات النماذج الرسمية" for these values (registry place also in Arabic, automatic).
- **Company details in Arabic** on the forms: name (business words translated, legal form last: "Sample Trading SARL" -> "سامبل للتجارة ش.م.م."), address and commercial-register place; the Arabic written in Settings > Company is used first. The commercial register is on every NSSF form that has the line (MOF R3 / R3-1 have no such box).
- **NSSF & MOF Forms tab:** "Fill in | لغة التعبئة" chooses Arabic or English values; every value is listed and can be corrected by double-click before Create Excel (kept until the form, employee or language changes).
- **Accounts & Statements:** "P&L tax basis (without non-deductible expenses)" - the Profit & Loss without the expense lines of expenses ticked "not deductible for income tax"; the report says TAX BASIS. The books, trial balance, balance sheet and financial statements always keep every expense.
- Arabic addresses: "Hamra Street" -> "شارع الحمرا", "Main Road" -> "الطريق العام".

## Version 2.9.111 (the product is named Nanza)
- **New name and logo: Nanza Accounting | نانزا للمحاسبة .** Replaces the short-lived Mizan name. New logo in the Saber for Audit colours (navy #052C5C, gold #D0A557): a white serif N signed with a fine gold tick, in a gold ring on a navy circle; the 16-32 px taskbar icons drop the ring so the N and tick stay readable. The logo itself has no Arabic text on the sign-in screen, the header bar, the window / taskbar icon, the installer and the Start menu / desktop shortcuts; the window title, the messages and the user guide say Nanza Accounting. Nothing else changes: the same installation folder, program file, data folder (SaberAccounting), licences and update check, so an installed copy simply updates; the update check now looks at the releases of nancy818181/nanzalatest (the project's new home); old "Saber Accounting" and "Mizan Accounting" shortcuts are removed. New files Assets/nanza_logo.png, nanza_icon.png, nanza.ico (the mizan files are removed).

## Version 2.9.110 (expenses not deductible for income tax; briefly named Mizan)
- **New name and logo: Mizan Accounting | ميزان للمحاسبة.** New logo (an M holding a balance scale, navy and gold) on the sign-in screen, the header bar, the window / taskbar icon, the installer and the Start menu / desktop shortcuts; the window title, the messages and the user guide say Mizan Accounting. Nothing else changes: the same installation folder, program file, data folder (SaberAccounting), licences and update check, so an installed copy simply updates; the old "Saber Accounting" shortcuts are replaced. New files Assets/mizan_logo.png, mizan_icon.png, mizan.ico.
- Purchases & Expenses > Expenses: new tick **"Not deductible for income tax (no official invoice) | غير مقبول ضريبياً"**. The expense stays in the books and in the profit and loss as usual; it is listed in the new **Non-deductible Expenses Report** (button on the same screen) with its total per currency, the amount to add back to the accounting profit in the income tax computation.

## Version 2.9.109 (Arabic written automatically; spouse details)
- Employee File: type the details in English - the Arabic boxes fill themselves (name, father, mother, place of birth, nationality, job, address). Known Lebanese / Arabic names, places, nationalities and job words come from a list (bassam saber > بسام صابر, hazmieh > الحازمية, sales manager > مدير مبيعات); other names are written letter by letter. Correct an Arabic box when needed: a corrected box is kept. Forms of employees saved before also get their English details written in Arabic.
- New section **Spouse | معلومات خاصة بالزوج/الزوجة** (as on MOF R3): name, name before marriage, father, mother, nationality, place and date of birth (each with its Arabic), ID number, persons for the family deduction, spouse MOF number, spouse's employer and its MOF number, or public administration. Filled on R3 (spouse section) and on the CNSS 2AA family page (wife / husband line).
- New module arabic_names.py.
- Financial Statements + Audit + Notes: new **Language** choice - English, Français or العربية. Every heading, line, note title, the default notes and the auditor's report are written in the chosen language (a text the user rewrote is printed as written); account names use the French / Arabic names of the chart when present; the Arabic pack uses the company's Arabic name and its Excel sheets read right to left. The cover, contents and sheet names follow the language (new module financial_statements_i18n.py).
- Accounts & Statements (Trial Balance and Statement of Account): new **View Year** box - choose another fiscal year of the company (for example 2025 while working in 2026) and run the report on its books, read only, without switching; the dates follow the chosen year, the printout says "Fiscal year 2025 (read only)", and a double-click on a line opens that year's entry.

## Version 2.9.108 (employee window fits the screen)
- Payroll > Employee File: the "Save Employee" button stays at the bottom of the window and is always visible; the window no longer goes under the Windows taskbar (all windows sized with fit_dialog leave room for it).
- Date of Birth, Hire Date and Leave Date show as DD-MM-YYYY (the date of birth showed as YYYY-MM-DD).
- Excel forms: a long value (a salary, a name) shrinks to fit its box instead of breaking on two lines; the salary box of CNSS 2AA is wider.
- Employee File > Leaving reason is a list of the reasons printed on the CNSS leaving notice (استقالة، بلوغ السن، عجز، زواج، وفاة، هجرة، عمل آخر); the chosen one is marked with X on the notice.
- Arabic on the official forms: new Arabic fields in the Employee File (name, father, mother, place of birth, nationality, job, address) and in Settings > Company (name, address), plus trade name and commercial register (number, place). The forms use the Arabic field when it is filled, otherwise the field as written; common nationalities are written in Arabic automatically (lebanese > لبنانية).
- The date next to the company stamp / signature is filled with today's date on every form (leaving notice, 41A, 2AA, R3, R3-1, 190A, 351, 386).
- **Company from another computer**: Switch Company / Year > **"Add Company from File…"** (administrator): choose the company file (.db) copied from the other computer; it is checked, copied into companies\<Company Name>\ (the original is left untouched) and added to the list - as a new company, or as a new year of the company with the same name. A company file copied by hand into the companies folder is also found and added when Saber starts.
- Marital Status also offers widowed and divorced (marked on R3 / CNSS forms; no spouse deduction, as for single).

## Version 2.9.107 (new seller key; NSSF & MOF forms in Excel; select all)
- New seller key: the password of the previous seller key file was lost, so a new key pair was made and its public key is now in the program. Licence codes are made with the new saber_seller.key file; codes made with the old key file are no longer accepted (none had been issued).
- Trials and data of existing installations are unchanged.
- **Payroll > NSSF & MOF Forms (Excel)** (was "CNSS Forms"): the 8 official forms are now editable Excel files in the layout of the printed forms, filled automatically; the PDF copies with typed values are removed.
  - New: **CNSS 190A** (month / quarter), **CNSS 351** (yearly) and **CNSS 386** (annual declaration + employee / month schedule sheet), filled from the posted payroll: employees per branch, wages, rate, contributions, family allowances paid, net due, settlement. Amounts are numbers and totals are formulas (contribution = wages x rate, totals, net, late surcharge, settlement), so the form stays right after a change. The figures equal the NSSF report.
  - 386 section (a): the wages declared each month come from the saved filed wages, or from the posted payroll of the month when none were saved (noted on screen).
  - CNSS 2AA, 41A, leaving notice, MOF R3 and R3-1 (the existing Excel forms) are in the same screen; R3 now also gets the address parts and phones, 41A / 2AA / R3 the pay type, and the leaving notice the leaving reason.
  - Employees > "Official Forms (Excel)" opens this screen with the selected employee.
- Ctrl+A selects all: every row of a table (where several rows can be selected) and all the text of a field. Import has a "Select All" button next to "Apply VAT A/C to selected"; Uploaded Data has "Select All" and "Clear Selection" next to Refresh.

## Version 2.9.106 (customs per item and customs fees)
- Inventory > Items > Customs: "Subject to customs" or "No customs" for each item.
- Help / مساعدة (or F1): the user guide is now complete - every screen, sub-tab, button and report with its options and columns - arranged in tabs like the side menu (Start here, Home, Sales, Purchases & Cash, Inventory, Accounting, Payroll & VAT, Settings), with a search box (English or Arabic, Ctrl+F) that finds the screen or report and jumps to it. The previous guide is kept in "Start here".
- Purchases > Cost on Purchase has two customs boxes: "Customs per item" is shared only by the items subject to customs; "Customs fees" by all the items of the purchase (like freight, insurance, broker fees and other costs). Each share goes into the cost of the item (by value); import VAT stays apart for the VAT return. A "Customs per item" amount on a purchase with no item subject to customs is shared by all its items.

## Version 2.9.105 (errors are no longer hidden)
- The server answers about 150 kinds of request with "error + message" when something fails. A refusal the user caused (a wrong value, no permission, a duplicate, a locked period) is still only answered; any other error (a program error) is now also written to the log with its full details, so it can be found and fixed.
- The 29 places that silently ignored an error ("except: pass") now write it to the log.
- Release test: no new silent "except: pass", and the number of broad "except Exception" can only go down (733 today).
- Nothing changes on screen.

## Version 2.9.104 (the computer's date cannot extend the licence)
- Turning the computer's date back no longer makes a licence or trial last longer: the program keeps the latest date it has already seen (also taken from the licence code and from the audit trail, which cannot be changed). When the computer's date is more than 2 days earlier, it asks to correct the date and time and does not open until then.

## Version 2.9.103 (signed licence instead of a hidden account, duplicate warning, tables, trial balance)
- The hidden owner account of 2.9.101 is removed (switched off on every installation when it upgrades). Instead each installation has an Installation ID and a licence code signed by Saber for Audit: Settings > Users > Licence (administrator). A new installation works 30 days; when the licence ends, the sign-in screen asks for the new code. A code cannot be made without the seller key file (kept only on the seller's computer, protected by a password the seller can change) and works only on the installation it was made for. The seller has no access to a client's books unless the client gives him a user.
- Administrator-only requests are checked in one place (a test fails if a new one is not listed). Sessions end after 12 hours (was 24).
- Same supplier / customer and same invoice number (or the same expense reference) already saved: a warning on every screen - purchases, expenses, sales, assets, PDF and Excel uploads, also when the same invoice is twice in one upload.
- Tables: Windows no longer squeezes the columns back (titles cut); wide tables scroll sideways.
- Trial balance: each currency keeps its columns together - Opening, Debit, Credit, Balance - and with the opening shown, Debit / Credit are the period's movements (they no longer repeat the opening); Balance is the closing balance.
- Fix: the upgrade check of older company files again includes the inventory upgrades (a comment had hidden them in 2.9.101).

## Version 2.9.102 (code health)
- No more `from x import *`: the 26 modules that used it now import, by name, only what they use (a mistake now shows as an error at once instead of a wrong name at run time).
- 418 very long lines were split (lines over 200 characters: 505 -> 106); each file was checked to give exactly the same program before and after.
- The release test stops both from coming back: no new `import *`, and the number of long lines can only go down.
- Network test: five users (each with their own session) save journal vouchers and expenses into the same company at the same moment while others read the trial balance - nothing lost, no voucher number given twice, no "database is locked", the books balance. The same test runs again over HTTPS with the office certificate. It runs on every push.
- Nothing changes on screen.

## Version 2.9.101 (tables that show everything, owner account and licence, category / brand of new items)
- Every table shows its column titles and values in full (no more "Unit Pric", "Discoun", "JV-2026-000") and fills the width of the screen; empty cells no longer show the word "None". A screen opens at its top.
- Owner (seller) account: a hidden sign-in that works on every installation, is not in the client's list of users and never expires. The owner sets the licence of the installation (Settings > Users, box shown only to the owner); when it ends, only the owner can sign in to renew it. The owner password can be changed per installation.
- Inventory > Warehouses & Settings > "New item on a purchase: ask for" Category / Subcategory / Brand: when a purchase creates new items, a table opens to give them their category and brand (pick, Apply to the selected lines or all, Save).
- Company files made before 2.9.100 now get the approval table when opened (the upgrade check missed it).

## Version 2.9.100 (selective approval, adviser confirmation, settings print, clearer menu)
- Accounting Setup > Approval: each company chooses which documents need approval - sales / purchase invoices, journal vouchers, receipts and payments, expenses. A document of a chosen kind saved by a user without "Can approve" waits in "Pending approvals" and is in no report until another user approves it (never the one who prepared it).
- Payroll > Tax & NSSF Settings: Print Settings and Settings PDF (values in force, salary brackets, NSSF periods, family allowance, posting accounts). "Adviser confirmation..." records the tax adviser who checked the rules (name, licence, date); the Rules pack then shows "Confirmed by the tax adviser".
- Financial statements: the contents (with page numbers) are on a page of their own, after the front page - in the PDF and in the printed Excel cover.
- The side menu is as wide as its longest item, so no item is cut off.
- Release check (release_check.py, run by the tests on every push): no symbolic links, no file names Windows cannot have, no cache files, the same version everywhere, every module compiles. A code-health test stops long lines and star imports from growing.

## Version 2.9.99 (scrolling on small screens, family changes with tick boxes)
- Payroll > Tax & NSSF Settings could not be scrolled to the bottom on a small screen: the form scrolls inside a page that also scrolls, and the wheel stopped at the end of the inner one. Now, at the end of a table or of an inner page, the wheel goes on and scrolls the page around it (everywhere in the program). The "Rules (PDF / Excel)" buttons for the tax adviser were hidden under the NSSF periods box: they are next to Load / Save Settings.
- Employee > Family changes: tick boxes and dates instead of typing a list. "Married during the year" + date of marriage; "New child" + date of birth + Add child (the list of children born, with Remove). Adding a child raises Children by one, so the count stays right.
- Changed files: desktop.py, desktop_payroll.py, app_runtime.py, installer.iss, README.md.

## Version 2.9.98 (physical count in the journal, audited statements pack, tax adviser pack, network check, laptop screens)
- Physical Inventory > "Apply Count to Stock + Journal": the stock quantities become the counted quantities (adjustment documents, as before) AND the difference is now posted in the journal (JV, type 06): surplus Dr stock 37 / Cr stock variation 6052, shortage the other way, valued at the item cost on the count date, per stock account. The month-end Stock Variation starts from the ledger, so nothing is counted twice. Example (tested): 40 panels at 80 counted 37 and 10 glue at 5 counted 12 -> JV with shortage 240 and surplus 10.
- Audited financial statements (PDF):
  - CONTENTS with the page of each part (Independent auditor's report 2, Statement of Financial Position 4 ...): the PDF is built twice, the first pass finds the pages.
  - The auditor's LOGO on top of the Independent Auditor's Report (Edit Texts > Company & Auditor > Choose logo...).
  - The auditor's details (firm, partner, licence, address, city) and logo are saved ONCE for every company you audit (main file); the company's own fields stay with the company.
- Payroll > Tax & NSSF Settings > "Rules to Confirm (PDF / Excel)": every payroll and VAT rule the program applies, with the value in this company's settings, its source and its status (law confirmed / to confirm with the tax adviser / announced, not applied), and a sign-off block for the adviser.
- Settings > Backup & Restore > "Network Check": the data service address, encryption (HTTPS), the office certificate on this PC, the answer time of 10 requests (excellent / good / slow) and the 4 steps of an office network.
- Screens: every screen and every inner tab now fits a 1366 x 768 laptop (Payroll Reports buttons on their own row, Bank Reconciliation panes, Accounting Settings, Audit Trail).
- Re-checked as an accountant: the full-year company (78 procedures) agrees with the books; the 3 exceptions are by design (documents of a filed VAT quarter are refused; the deduction ratio is per quarter).
- Fix before release: the first (page-finding) pass of the financial statements PDF wrote stray files named "<_io.BytesIO ...>" next to the program; it now stays in memory (a test checks no file appears). numpy added to the requirements (the scan clean-up of 2.9.97 uses it). The audit report's Beirut time was one hour late in winter on Windows (no time-zone data): tzdata added and Lebanon's summer-time rule used when it is missing.
- Changed files: inventory.py, desktop_inventory.py, financial_statements.py, report_export.py, requirements.txt, audit_report.py, desktop_v22.py, tax_review.py (new), desktop_payroll.py, desktop_settings.py, desktop_final.py, desktop_accounting_setup.py, server.py, client.py, build-windows-installer.yml, app_runtime.py, installer.iss, README.md. Tests added to test_v2_9_97.py.

## Version 2.9.97 (exact money, VAT account per customer / supplier, audit trail, PDFs, attachments)
- Exact money: totals were added as floating-point numbers - 3,000 small vouchers showed 600.0000000000002 in the trial balance. Money is now added exactly (a new DSUM in every report query, Decimal in the trial balance, P&L and cash flow).
- Trial balance fix: a CANCELLED invoice lost its entry from the trial balance while its reversing entry stayed (a cancelled purchase showed as a negative balance). Both entries now count, as in the financial statements and the ledger. The year-end exchange-difference calculations had the same rule and are fixed too.
- VAT account per customer / supplier (Lebanese practice, Accounting Setup > "VAT by customer / supplier (VAT 140)"): supplier 401100025 -> VAT 442100025, client 411100025 -> 442700025, other payable 461900025 -> 442160025, asset supplier 403100025 -> 442130025. The VAT of every invoice goes to its party's own VAT account. "Create VAT Accounts" (with "Start from") makes them for the existing customers / suppliers; "Testing VAT Accounts" lists parties without a VAT account, VAT accounts without a party and VAT posted to another party's account. On by default for NEW companies; existing companies tick the box.
- Automatic VAT closing: when the quarterly return is saved, a "VAT closing by ledger" voucher moves every party VAT account into its closing account (44210 / 44270 / 44265 / 44263), then the settlement closes those into VAT payable 4425 or VAT to recover 4429.
- Asset suppliers already have their own payable accounts (4031...): a fixed-asset purchase is owed on the asset supplier's account.
- Tamper-evident audit trail: every line carries a fingerprint (HMAC-SHA256) of itself and of the line before, with a key kept outside the company file (audit.key in the Saber data folder). The program can no longer change or delete audit lines. Settings > Audit Trail > "Verify Audit Trail" shows if a line was changed, removed or inserted outside the program.
- Audit Report (Excel / PDF, Settings > Audit Trail): integrity, activity per user, changes after saving (before -> after), late / back-dated entries, entries by the administrator, entries outside working hours (Beirut time), manual vouchers on cash / bank.
- Attachments: double-click an attached document to SEE it inside the program (PDF pages with next / previous and zoom, images), on invoices, purchases, expenses and fixed assets; "Open in PDF reader" and Download remain.
- Purchases > "Cancel Purchase": a purchase saved with a wrong total is cancelled (reversing entry, reason kept for the audit); enter it again correctly.
- PDF reading:
  - Scanned invoices: the table lines are removed before OCR (Diwan scan: 21 of 21 rows instead of 1), drawn at 3x; lost decimal points repaired (44 -> 4.4); "$J2025..." -> "SJ2025..."; a second page that is a copy of the first is not read twice.
  - Phone photos (EDL bill taken sideways): turned upright, cleaned and read twice; utility bills found by the 11% VAT check: 1,816,850 + VAT 199,854 + stamp / rounding 100,296 = 2,117,000 LBP.
  - Amounts with "$" after them (7.10$ 9,585.00$) and a proforma number (PROFORMA#:PF.HO.25.0000005) are read; the amounts are checked against the item lines (a weight "TOTAL 27045" is no longer the total; Diwan VAT 90.80 as printed).
  - Expenses: no VAT on the document (air tickets, commissions) -> the total goes in "Without VAT", VAT 0; the category is scored (travel tickets with "travel insurance" are Travel) and gets its own 9-digit account, opened when missing: Travel 626420000, Electricity 626340000, Commissions 626520000, Rent 626310000 ...; the description is "Category - Supplier", the supplier from its e-mail address (Pegasus), not the buyer named on the document.
- Screens: titled boxes whose row wraps (Cash Budget / Budget "from a year + %") were cut in half - fixed; the Budget page is in four cards (Budget / Budget from a year + % / Forecast and 5-year projection / Budget lines).
- Changed files: database_common.py, database.py, db_reports.py, db_journal.py, db_invoices.py, db_payments.py, db_accounts.py, db_rates.py, business_reports.py, accounting_setup.py, vat_return.py, vat_ledgers.py (new), audit_chain.py (new), audit_report.py (new), company_manager.py, server.py, client.py, pdf_import.py, desktop_attachments.py (new), desktop_accounting_setup.py, desktop_invoices.py, desktop_purchases.py, desktop_expenses.py, desktop_asset_register.py, desktop_common.py, desktop_dimensions.py, build-windows-installer.yml (orientation data for OCR), app_runtime.py, installer.iss, README.md. New test: test_v2_9_97.py. Tests changed on purpose: test_pdf_ocr.py (pages are drawn at 3x).

## Version 2.9.96 (payroll: marriage and new child during the year)
- Employee card > new "Family changes" box: Date of marriage, and Children's birth dates (DD-MM-YYYY, separated by commas).
- Payroll follows them month by month: the spouse is counted from the month of the marriage, each new child from the month of birth. This changes the salary-tax family deduction (spouse LBP 225M, child LBP 45M a year), the NSSF family allowance paid with the salary, and the retro-salary months (each month uses the family of that month). The payslip notes say it ("Married from ...", "New child born ...: counted from this month").
- Example (tested): married 15-04-2026, baby born 10-05-2026, one older child: March = single + 1 child, April = married + 1 child, May = married + 2 children.
- "Children" stays the number today; a child born after the payroll month is not counted yet; a child listed in the dates is always included in Children. A marriage date wins over the Marital Status box for months before it.
- To confirm with your tax adviser / NSSF office: counting from the month of the event (some apply it from the next month, or from the NSSF registration of the child).
- Changed files: db_payroll.py, desktop_payroll.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_96.py.

## Version 2.9.95 (one professional design on every screen, same Saber colours)
- One design system (desktop_theme.py), applied to every screen and every window when it opens:
  - Buttons by role: gold = the main action of the screen (Save), navy = the other actions, red = Delete / Cancel only; same font, height and spacing everywhere. Sales Invoice: Save is now gold (Return and Import are navy); Purchases, Uploaded Data, Journal Voucher and VAT have one gold button each.
  - Content in white cards with a thin border on the light page; inputs flat with a thin border that turns gold while typing.
  - Every screen has a title above it: SECTION › Screen (e.g. PURCHASES & CASH › Purchases & Expenses); the currency filter moved to the right of that line.
- Fits a laptop screen (1366 x 768): rows of buttons or fields that are too wide wrap onto a second line, long notes wrap, wide tables scroll sideways inside their box (they made the whole screen wider). Sales Invoice: "Find invoice" is a slim row above the form; Purchases: the invoice buttons on one row, the PDF buttons on the next; Journal Voucher: the toolbar wraps and the totals show.
- No change in calculations; the design pass takes about 0.03 s.
- Changed files: desktop_theme.py, desktop.py, desktop_sales_invoice.py, desktop_purchases.py, desktop_invoices.py, desktop_brains.py, desktop_final.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_95.py.

## Version 2.9.94 (office network tested, easier screens, code split)
- Office network (2-3 PCs): tested as it is really used. The server runs in its own program on the network with an office certificate (HTTPS), and three PCs (three separate programs) work on the same company at the same time with approval on: 45 invoices, 45 different numbers, the 15 drafts approved from another PC, the trial balance balanced. Then the server is stopped and started again: nothing is lost and the PCs sign in again. A PC without the office certificate, plain HTTP and a wrong password are all refused. This test also runs on Windows on every push.
- New: making the office certificate is one command on the server PC: `python run_server.py --make-certificate OFFICE-PC,192.168.1.10`. Copy `server-cert.pem` (never the key) to each PC's Saber data folder as `office-server-cert.pem`, and the program trusts that server. Nothing leaves the office.
- Screens (checked on a 1366 x 768 laptop screen):
  - Purchases: the New / Auto Calculate / Save Purchase / Delete buttons were pushed off the right edge of a laptop screen (Save could not be seen); they now sit under the fields.
  - Uploaded Data: the 20 buttons are in labelled rows (Edit / Accounts & VAT / Documents), Cancel and Delete apart in red; amounts show as 1,637.25 (were 1637.25 / 1475.0); the invoice number column is wider.
  - Every table: every second row lightly shaded (easier to follow a line across), softer blue for the selected row; a row's own colour (red for deleted) is kept.
  - Calmer look in one place (desktop_theme.py): flat tabs, inputs with a gold line when typing, lighter scroll bars, gold progress bars.
  - Sales Invoice: the arrow buttons say "Previous" / "Next".
- Code: the largest files were split, with no change in behaviour: inventory reports moved to inventory_reports.py (inventory.py 1,628 -> about 1,070 lines; every old name still works), the sales invoice screen moved to desktop_sales_invoice.py (desktop_invoices.py 1,278 -> about 680 lines), the look moved to desktop_theme.py.
- Changed files: office_tls.py (new), client.py, server.py, inventory.py, inventory_reports.py (new), desktop_invoices.py, desktop_sales_invoice.py (new), desktop_theme.py (new), desktop.py, desktop_purchases.py, requirements.txt (cryptography, for the office certificate), build-windows-installer.yml, app_runtime.py, installer.iss, README.md. New test: test_v2_9_94.py. Tests changed on purpose: test_v2_9_54.py (reads the sales invoice screen from its new file), test_v2_9_93.py (the "draft not in the books" check now reads the trial balance's real column name, so it really checks).

## Version 2.9.93 (approval step: one person prepares, another approves; before/after audit trail)
- Accounting Setup > "Approval (internal control)": tick "Invoices need approval before posting". Then an invoice saved, imported or edited by a user without the new "Can approve" permission (Users screen) is kept as a draft (status review): it is not in the journal, the trial balance or VAT until approved.
- Sales Invoices > "Approve Selected": a user with "Can approve" posts the selected drafts. Nobody can approve a draft he prepared himself (the administrator can, for a one-person office). Period lock and filed VAT quarters are checked again at approval.
- Audit trail: each approval records who prepared and who approved; each edit of an invoice records the fields that changed with their value before and after (date, party, total, VAT, status, lines...).
- Off by default: companies that do not tick the box work exactly as before.
- Changed files: database_common.py, database.py, server.py, db_invoices.py, accounting_setup.py, desktop_accounting_setup.py, desktop_final.py, desktop_invoices.py, client.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_93.py.

## Version 2.9.92 (Budget Law 2026 items)
- VAT: two new purchase uses. "Utilities" (electricity, water, telephone, internet): from 10-02-2026 their VAT is no longer recovered (Budget Law 2026, Art. 30). "Passenger car": VAT recovered only on the first USD 30,000 of the car's price; the VAT on the part above is not recovered. The non-recovered VAT goes to the VAT-not-deductible account in the VAT settlement and is shown in the annex and worksheet. Invoices dated before 10-02-2026 are not affected.
- Payroll: from 10-02-2026 "Food - not taxable" is exempt up to LBP 300,000 a working day (Art. 26); the part above is moved to "Food - taxable" with a note on the payslip.
- To confirm with your tax adviser before filing (the program uses these values; all can be changed in Payroll Rules): salary-tax brackets 2%-25% and family deductions (Law 324/2024); salary tax rounded up to LBP 10,000; schooling allowance limits; NSSF sickness ceiling LBP 120M from 01-08-2025 (Decree 887; an earlier Memo 801 said 140M); transport LBP 450,000 a day exempt; the reading of Art. 26 (food) and Art. 30 (utilities / cars) above. Announced but not law at the time of this version: VAT 12% and a transport allowance of LBP 500,000-800,000 - not applied.
- Changed files: vat_return.py, db_vat.py, desktop_stage3_common.py, lebanese_payroll.py, db_payroll.py, README.md. New test: test_v2_9_92.py.

## Version 2.9.91 (faster with large books; full company re-checked)
- Measured with a company of 3,000 invoices and 750 receipts (about 25,000 journal lines), then made faster:
  - Dates are read once (one screen read 300,000 dates one by one): every report, list and sort is quicker.
  - VAT return: the documents are read once per calculation instead of 16 times (Q4 also builds Q1-Q3 for the credit chain): 2.9 s -> 1.4 s on the screen.
  - Dashboard charts and sales reports read only the item lines of their own invoices; account codes are read once.
  - Exchange-rate list: one query instead of one count per rate (it is shown on several screens).
  - General Journal table shows the first 5,000 lines (narrow the dates or search for the rest); the totals, the balance check and Excel / PDF still use every line.
  - The other screens are prepared while you are not typing or clicking (they made the screen stutter right after a company was opened); a screen you open is still built at once.
  - Lists that rarely change (chart of accounts, customers / suppliers, settings) are kept for 60 seconds instead of 10; any change made on this computer refreshes them at once.
  - The sales invoice amount in words (English and Arabic) is drawn once per amount.
- Re-checked as an accountant: the full-year company (78 procedures), every PDF tab and the bank reconciliation (26 checks), and a project company (two projects and a department: revenue, purchases, expenses and payroll per project) - all agree with the books. The 3 remaining exceptions are by design (documents of a filed VAT quarter are refused; the deduction ratio is per quarter since 2.9.83).
- Changed files: database_common.py, desktop_common.py, ledger_reports.py, business_reports.py, vat_return.py, db_rates.py, desktop.py, desktop_reports.py, desktop_invoices.py, client.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_91.py.

## Version 2.9.90 (owner requests: totals, item accounts, new company, attachments)
- PDF totals: the amount in words on the VAT line ("Eighty One Thousand ... and 94/100 USD") gave a VAT of 100 and a wrong subtotal; it is now ignored (Diwan SJ20251714: 78,948.89 + VAT 2,269.05 = 81,217.94).
- Purchases > new button "Auto Calculate": taxable / exempt from the item lines (VAT Yes / No), VAT = (taxable - discount) x VAT %, and the total. A PDF whose item lines do not make its total (a page missing from the file) keeps the invoice amounts and says so; its lines are not added.
- New items: right after an upload creates items, a window asks their cost account (class 6, purchases) and sales account (class 7, sales) - for all of them or the selected ones. Items now have a sales account: a sales invoice line of that item is posted to it (other lines keep the invoice's account).
- New company: starts with the standard chart only; the accounts, customers / suppliers, branches and settings of other companies are no longer copied (the users are).
- Attachments: a sales invoice read from a PDF keeps the PDF attached when it is saved (purchases, expenses, assets and Uploaded Data already did); open them with "Attachments" on each screen.
- Changed files: pdf_import.py, desktop_purchases.py, desktop_stage3_common.py, inventory.py, db_invoices.py, server.py, client.py, company_manager.py, desktop_invoices.py, desktop_v22.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_90.py.

## Version 2.9.89 (scanned PDFs much faster, Auto Calculate Totals)
- Scanned PDFs: the OCR engine used every core of the computer for each page and lost most of its time waiting (OpenMP); it now uses one core per engine and several pages are read side by side on a multi-core PC. An 8-page scanned bundle went from 84 seconds to 17 seconds on one core and 11 seconds on two; the 79-page BCC file is read in a few minutes instead of about 15.
- Uploaded Data > "Auto Calculate Totals" (selected rows, or all): Total = Subtotal + VAT; a missing amount is worked out from the other two; with the subtotal only, VAT at the company's rate (11%); with the total only, subtotal and VAT are taken out of it. Each changed row says so in Check.
- Changed files: pdf_import.py, desktop_stage3.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_89.py.

## Version 2.9.88 (tested on Windows, several users at once, Lebanese rules checked)
- Several users at the same time: 4 users saving 80 invoices and 20 receipts at once (plus a second program writing to the same file) got only 36 different invoice numbers - the same number was given twice. Changes are now made one at a time by the data service (reading is never blocked); now 80 invoices, 80 numbers, no voucher number twice, every entry balanced.
- Windows: the whole test suite now also runs on Windows (GitHub windows-latest) at every change. On Windows a data file whose -shm file is held by another program answers "unable to open database file" (not only "disk I/O error"): the program waits and opens it once the other program lets go (tested by holding the file for 1.5 s). Speed on Windows is measured (300 invoices saved, journal and trial balance).
- Lebanese rules checked against public sources (MoF, CNSS, Budget Laws 2024 / 2026): minimum wage, NSSF rates and ceilings, family benefits 2026, VAT 11%, quarterly VAT deadline one month after the quarter (2026), salary-tax exchange rate 89,500 - confirmed. Decree 887 cited correctly (14-08-2025, Official Gazette 21-08-2025, NSSF Memo 805). To confirm with a tax adviser: the 15 / 20 / 25% brackets and the spouse / child deductions, the LBP 10,000 rounding, the schooling allowance, the August 2025 ceiling (140M under Memo 801 before Decree 887), and Budget Law 2026 items not built in yet (food allowance LBP 300,000 / day, no VAT recovery on utilities, VAT on passenger cars capped at USD 30,000).
- Changed files: server.py, database.py, lebanese_payroll.py, .github/workflows/tests.yml, app_runtime.py, installer.iss, README.md. New test: test_v2_9_88.py.

## Version 2.9.87 (PDF on every tab, bank reconciliation, program start and setup)
- Program start / setup (important):
  - The background backup program (SaberAccountingBackup, started with Windows) also upgraded the company files. After an update the old backup kept running and fought the new version over the same files: "database is locked", "could not start its local data service", and the setup could not replace the backup program (in use). Now the backup only copies files (never upgrades them); the setup stops the backup and Saber before installing and starts the backup again after; uninstall stops them too.
  - The data files wait up to 30 seconds for another writer instead of failing at once.
  - The first start after an update (every company file is brought up to date) shows "Preparing your company files..." and waits, instead of stopping after 60 seconds; if the service really stops, the message gives the reason.
  - Reading PDFs in the background no longer touches the window from the reading thread (Tk is not thread-safe); the same for the local PDF assistance.
- Bank Reconciliation:
  - "Import Statement (Excel / CSV / PDF)": a bank statement in PDF (text or scan) is read - date, description, cheque number, amount with its sign from the running balance; opening and closing balance lines are not movements. The closing balance fills "Statement ending balance", and the program checks opening + movements = closing (a warning when a line was not read).
  - The same statement imported twice is not doubled.
  - An opening balance brought forward (opening voucher) is no longer an outstanding deposit (the reconciliation showed a 10,000 difference); book items of earlier months still not matched stay outstanding once earlier statements were imported.
  - Post Line: money in (interest) is proposed to 773 Interests & Similar Revenues Earned instead of the bank-charges account.
- Purchases: each item line has VAT Yes / No; the lines without VAT make the Exempt amount and carry no VAT when posted (an invoice with spices at 11% and nuts at 0% is posted exactly).
- Sales > Import PDF: the item lines of the PDF are filled (not one "As per file" line); the customer is taken from "Bill To" when the invoice is ours.
- Expenses > PDF: the expense account is suggested from the text (rent 6263.1, maintenance 6262, telephone / internet 6261.5, insurance 6268, advertising 6269.3, stationery 6269.4, legal / consulting 6265.3, travel 6264.2, subscriptions 6266.2, bank charges 6739, transport 6261.1) - check it before saving; the expense entry shows the supplier's invoice number.
- Fixed Assets > Fill from PDF: after the register item is created, the program offers to book the supplier's invoice (Dr asset + VAT / Cr supplier) and links it to the asset - the register item alone posts nothing.
- PDF reading: the invoice number is taken on the line of its label first ("TAX INVOICE" followed by the address no longer gives "W38"); supplier names containing address words (TECHZONE) are kept.
- Checked through the real screens with real and test PDFs: Purchases (54-line text invoice), Expenses (scanned), Fixed Assets, Sales, Uploaded Data (8-page bundle: 2 invoices + supporting papers), Bank Reconciliation (PDF and scanned statement) - 26 checks, all passed; the trial balance balances.
- Changed files: pdf_import.py, bank_rec.py, database.py, db_payments.py, company_manager.py, backup_service.py, run_desktop.py, installer.iss, desktop_stage3_common.py, desktop_stage3.py, desktop_purchases.py, desktop_expenses.py, desktop_asset_register.py, desktop_v22.py, app_runtime.py, README.md. New test: test_v2_9_87.py.

## Version 2.9.87 (program start, setup, PDF on every tab, bank reconciliation)
- Program start / setup (important, from the user's log):
  - "Saber Accounting could not start its local data service": the log showed "disk I/O error" when the data file was switched to WAL - its -wal / -shm files were held by another Saber program (the background backup) or a sync folder. The program now tries again for a few seconds, then opens the file in its current mode (slower, nothing lost) instead of stopping.
  - The background backup (SaberAccountingBackup, started with Windows) also upgraded the company files; after an update the old backup kept running and fought the new version over the same files, and the setup could not replace it (in use). Now the backup only copies files; the setup stops the backup and Saber before installing and starts the backup again after; uninstall stops them too.
  - The data files wait up to 30 seconds for another writer instead of failing at once with "database is locked".
  - The first start after an update shows "Preparing your company files..." and waits instead of stopping after 60 seconds; if the service really stops, the message gives the reason.
  - Reading PDFs in the background no longer touches the window from the reading thread (Tk is not thread-safe); the same for the local PDF assistance.
- Bank Reconciliation:
  - "Import Statement (Excel / CSV / PDF)": a bank statement in PDF (text or scan) is read - date, description, cheque number, amount with its sign from the running balance; opening / closing balance lines are not movements. The closing balance fills "Statement ending balance" and the program checks opening + movements = closing (warning when a line was not read).
  - The same statement imported twice is not doubled.
  - An opening balance brought forward (opening voucher) is no longer an outstanding deposit (the report showed a 10,000 difference); book items of earlier months still not matched stay outstanding once earlier statements were imported.
  - Post Line: money in (interest) is proposed to 773 Interests & Similar Revenues Earned, not the bank-charges account.
- Purchases: each item line has VAT Yes / No; lines without VAT make the Exempt amount and carry no VAT (an invoice with spices at 11% and nuts at 0% is posted exactly).
- Sales > Import PDF: the item lines of the PDF are filled (not one "As per file" line); the customer comes from "Bill To" when the invoice is ours.
- Expenses > PDF: the expense account is suggested from the text (rent 6263.1, maintenance 6262, telephone / internet 6261.5, insurance 6268, advertising 6269.3, stationery 6269.4, legal / consulting 6265.3, travel 6264.2, subscriptions 6266.2, bank charges 6739, transport 6261.1) - check it; the expense entry shows the supplier's invoice number.
- Fixed Assets > Fill from PDF: after the register item is created, the program offers to book the supplier's invoice (Dr asset + VAT / Cr supplier) and links it to the asset.
- PDF reading: the invoice number is taken on its label line first ("TAX INVOICE" + address no longer gives "W38"); supplier names with address words (TECHZONE) are kept.
- Checked through the real screens with real and test PDFs: Purchases (54-line invoice), Expenses (scan), Fixed Assets, Sales, Uploaded Data (8-page bundle), Bank Reconciliation (PDF and scanned statement): 26 checks passed, trial balance balanced.
- Changed files: database.py, pdf_import.py, bank_rec.py, db_payments.py, company_manager.py, backup_service.py, run_desktop.py, installer.iss, desktop_stage3_common.py, desktop_stage3.py, desktop_purchases.py, desktop_expenses.py, desktop_asset_register.py, desktop_v22.py, app_runtime.py, README.md. New test: test_v2_9_87.py.

## Version 2.9.87 (program start, setup, speed, PDF on every tab, bank reconciliation)
- Program start (from the user's log): "could not start its local data service" came from "disk I/O error" when the data file was opened - its -wal / -shm files were held for a moment (antivirus scan, backup or sync tool, a program closed by force). The program now retries for a few seconds, removes a left-over -shm file when nothing holds it (SQLite rebuilds it from the -wal), and carries on; the data files wait up to 30 seconds for another writer instead of failing with "database is locked".
- The first start after an update shows "Preparing your company files..." and waits instead of stopping after 60 seconds; if the service really stops, the message gives the reason.
- Setup: the setup stops Saber and the background backup before replacing the files ("file in use" / stuck setup) and starts the backup again after; uninstall stops them too. The background backup only copies the files (it used to upgrade them too, fighting the new version after an update).
- Speed: the header logo is drawn once per run (a third of a second every time the main screen opened); the PDF reading thread never touches the window (it could freeze it).
- Bank Reconciliation: "Import Statement (Excel / CSV / PDF)" reads a PDF statement (text or scan) - date, description, cheque number, amount signed by the running balance; the closing balance fills "Statement ending balance" and opening + movements = closing is checked. The same statement is not imported twice. An opening balance brought forward is no longer an outstanding deposit (the report showed a 10,000 difference). Money in (interest) is proposed to 773 instead of the bank-charges account.
- Purchases: each item line has VAT Yes / No; lines without VAT make the Exempt amount and carry no VAT when posted.
- Sales > Import PDF: the item lines of the PDF are filled; the customer comes from "Bill To" when the invoice is ours.
- Expenses > PDF: the expense account is suggested from the text (rent 6263.1, maintenance 6262, telephone 6261.5, insurance 6268, advertising 6269.3, stationery 6269.4, legal / consulting 6265.3, travel 6264.2, subscriptions 6266.2, bank charges 6739, transport 6261.1); the entry shows the supplier's invoice number.
- Fixed Assets > Fill from PDF: offers to book the supplier's invoice (Dr asset + VAT / Cr supplier) and links it to the asset.
- PDF reading: invoice number on its label line first (no more "W38"); supplier names with address words (TECHZONE) kept.
- Checked through the real screens (Purchases, Expenses scan, Fixed Assets, Sales, Uploaded Data 8-page bundle, Bank Reconciliation PDF and scan): 26 checks passed, trial balance balanced.
- Changed files: database.py, brand_images.py, run_desktop.py, installer.iss, backup_service.py, company_manager.py, pdf_import.py, bank_rec.py, db_payments.py, desktop_stage3_common.py, desktop_stage3.py, desktop_purchases.py, desktop_expenses.py, desktop_asset_register.py, desktop_v22.py, app_runtime.py, README.md. New test: test_v2_9_87.py.

## Version 2.9.86 (new items on upload: notice and 90% warning)
- Uploading an invoice (Purchases > PDF, Uploaded Data PDF, Import Purchases from Excel): an item that does not exist in Inventory is created, and a notice then lists the new items (code, name, unit) so they can be checked (category, unit, stock account).
- When an item with 90% or more of the same name exists (e.g. "HPL Panel 4mm Wht" and "HPL Panel 4mm White"), a warning asks what to do: use the existing item or create a new one (the answer is kept for the rest of the session). Names less alike are created without a question; the same name written differently (case, spaces, dashes) is still the same item.
- Uploaded Data: a PDF whose rows carry their own VAT (some rows 11%, some 0%) is posted with each line's own VAT instead of one average rate.
- Changed files: inventory.py, desktop_stage3_common.py, desktop_purchases.py, desktop_stage3.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_86.py.

## Version 2.9.85 (purchase PDFs read correctly)
- Purchase PDFs (Purchases > PDF, Uploaded Data > Choose PDF Invoice(s), Expenses, Assets):
  - Tables whose amounts come first (TOTAL | VAT | DISC % | U.PRICE | QTY | WEIGHT | ITEM) are read: every item row with its quantity, unit price, unit (2KG, 100GR ...) and its VAT. Item names with "date" in them (DATES PITTED) are no longer skipped.
  - The columns of the page are read in order (layout text) when that reads more of the invoice; before, the cells of a row were glued together and no item was found.
  - "Currency: USD" is read (bank-account currencies are ignored); the VAT printed before its label ("1,923.65 V.A.T. 11%") is read, and the VAT in LBP is no longer taken as the VAT; the total is never a "TOTAL NET WEIGHT"; Arabic labels written with Persian letters (الضریبة) are recognised.
  - When only some rows carry VAT, the Taxable and Exempt amounts are filled from the rows (example: taxable 17,487.75 + exempt 49,527.30, VAT 1,923.65).
  - Supplier: the company printed at the top (SAL, SARL, Group, Center ...) or a supplier already in the books whose name is on the page - never your own company (the buyer). OCR noise is left empty instead of being taken as a name; an invoice with the same numbering as the one before takes its supplier.
  - A PDF with an invoice and its supporting papers (receipts, port bills, customs papers addressed to someone else) gives one row per invoice; the other pages stay with their invoice (attached, not booked).
  - Long scanned PDFs no longer freeze the program: Uploaded Data reads them in the background with "page x of y" and a Stop button; the Purchases screen reads only the first invoice (up to 3 pages) - a 79-page file now takes seconds instead of about 15 minutes.
- Changed files: pdf_import.py, desktop_stage3_common.py, desktop_stage3.py, desktop_purchases.py, desktop_expenses.py, desktop_asset_register.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_85.py.

## Version 2.9.84 (fixes from a full-year audit of the program)
A full year of a test company (sales in USD / EUR / LBP, exempt and zero-rated sales, stock, payroll, assets, VAT, DOE, closing) was audited like a client file. Every finding is fixed:
- Year close after a DOE (important): after a DOE in the USD books (or EUR ...) on a foreign-currency balance, "Close & Open next year" stopped with "OPEN-<year>-USD is not balanced" (nothing was saved). The revaluation is now carried into the next year's opening as the same kind of line, so every opening voucher balances and the next DOE starts from the revalued amount.
- Close & Open now carries into the new year: employees (with their end-of-service contributions of the year added to "contributions before Saber" and their leave balance at 31-12 as "leave carried in"), the fixed-asset register and asset accounts, exchange rates, departments, projects and the payroll settings / posting accounts. Creating a year also carries them.
- VAT: a document dated in a quarter whose VAT return is saved can no longer be added, changed, cancelled or deleted (it used to be accepted and only flagged "changed after saving"). Sales / purchase invoices, credit notes, expenses, VAT classification and deductibility, and account changes on uploaded invoices all say "The Qn YYYY VAT return is saved; an administrator must reopen it". Reopen the return, correct, save it again.
- Fixed assets bought before Saber: new field "Booked before Saber up to" (Asset Data Entry). The months up to that date count as already depreciated (their depreciation is in the opening balance), so the monthly table shows the old depreciation and the net value, and the first month in Saber posts without "post the earlier months first".
- Cash flow statement: the movement of the provisions (15, e.g. the end-of-service provision) is now an operating adjustment ("movement in provisions"), no longer under financing; depreciation is the movement of the accumulated depreciation (28 / 29). The net change in cash is unchanged.
- Settings > new tab "Audit Trail" (administrator): every change recorded by the program - who, when, what record, the details - with filters (dates, user, record, action, text) and Excel / PDF.
- Supplier payments and expenses: before saving, a warning when the payment would make the cash / bank account (class 5) negative in its currency on that date (Save anyway or go back).
- Payroll in USD: the salary tax line now carries the exact LBP tax of the payslip as its LBP value, so 4411 in LBP agrees with the tax due (the rounding of the USD tax was left on 4411); the LBP rounding goes to the salary expense line.
- Statement of account (/api/statement): now shows receipts and payments, credit notes on the right side, and leaves out cancelled / deleted / review documents.
- Financial statements: can be prepared in any currency of the company (EUR ...), each line translated through its USD value at the entry date.
- Year-End Check: also checks the DOE in the main currency of the books when it is not LBP (USD books, EUR books).
- Annual leave earned now uses the days of the year (365 / 366): a full year earns exactly 15 days (365.25 gave 14.99).
- Tests changed on purpose: test_final_features (QuarterlyVatTest) - an invoice added after the Q1 return is saved is now refused until the return is reopened (it used to be accepted and flagged); test_v2_9_82 (leave) - earned leave at 30-06 is 7.44 days (181 / 365 x 15) instead of 7.43.
- Changed files: year_end.py, company_manager.py, database.py, db_invoices.py, db_payments.py, db_vat.py, db_accounts.py, db_payroll.py, db_reports.py, fixed_assets.py, financial_statements.py, accounting_setup.py, payroll_extras.py, server.py, client.py, desktop_asset_register.py, desktop_settings.py, desktop_accounting_setup.py, desktop_expenses.py, desktop_stage3.py, desktop_v22.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_84.py.

## Version 2.9.83 (audit report pack and VAT Art. 31 by quarter)
- Financial Statements (audit report pack):
  - Centred front page: company, "Financial Statements and Independent Auditor's Report", period, currency, contents and audit firm. The auditor's report and the four statements have centred titles; the sub-titles of the report (OPINION, BASIS FOR OPINION ...) are bold; the signature stays on the same page as the last paragraph.
  - Tables: totals and headings in bold, negative amounts in brackets (1,234), note tables across the whole page.
  - Excel: a print-ready workbook - Cover, Auditor's Report, Financial Position, Profit or Loss, Changes in Equity, Cash Flows, Notes, Review Points - A4 portrait fitted to the page width, no grid lines, accounting format with brackets, single / double lines under totals, page numbers.
  - Edit Texts > new tab "Company & Auditor": legal form, commercial register number, date of incorporation, tax number, activities, shareholders, directors, share capital, approval date, audit firm, partner, LACPA licence, address, city and date of the report. Entered once: they go automatically into the notes and the auditor's report (as {legal_form}, {auditor_firm} ...). A field left empty shows as [label] and is listed in the review points.
  - Information, texts and account mapping are now saved for every fiscal year of the company (each year is its own file): no need to enter them again for the next year. The cash flow / OCI amounts stay with their own year. A year without settings takes them from another year. A text left as the standard one follows the standard text (texts saved unchanged by older versions get the new ones).
  - New notes: Share capital (under the share capital table), Income tax, Financial risk management, Approval of the financial statements.
  - Test changed on purpose (owner request): test_financial_statements - the texts saved for one year now apply to the other years too, and the Excel pack has one sheet per statement.
- VAT, partial deduction (Art. 31) - owner decision: by default each quarter uses the ratio of its own turnover (taxable + zero-rated / all supplies of that quarter), calculated automatically, with no year-end adjustment in Q4 and no provisional %. The earlier method (provisional / year-to-date for Q1-Q3, final annual ratio with the adjustment of Q1-Q3 in Q4) can still be chosen in the VAT tab ("Deduction ratio (Art. 31)" = Annual); the two older VAT tests now choose it explicitly.

## Version 2.9.82 (stock, payroll and reports for the accountant)
- Stock:
  - Inventory Reports > "Stock vs Ledger": the stock valuation (Stock Card costs) against the balance of each stock account (31 / 33 / 35 / 37) in the books at a date, with the difference and how to read it.
  - Monthly Stock Variation (Inventory > Warehouses & Settings, month MM-YYYY): the Lebanese periodic method month by month - the stock in the ledger is cancelled and the month-end stock booked (6051 / 6052, 6151 / 6152 ...) for each stock account, so the P&L shows the cost of sales and the gross margin of each month. Posting a month again posts the later months again, in order. The year-end Stock Variation is unchanged (it cancels and books the same stock).
  - Landed costs (freight, insurance, customs duties, broker fees, other - not the import VAT) of a purchase now go into the cost of the items received with it, spread by value (IAS 2). Deleting the landed cost takes it out again.
- Payroll > new tab "End of Service & Leave":
  - End-of-service provision at a date: last salary x years of service (1 month per year) less the end-of-service contributions paid (Saber's posted payroll + "End-of-service contributions before Saber" on the employee); "Post Provision" brings 1552.1 to it (Dr 6355 / Cr 1552.1, or Dr 1552.1 / Cr 7552.2 when it goes down). An estimate for the accounts, not the NSSF settlement.
  - Annual leave: leave taken (annual / sick / unpaid / other) and the balance of each employee - carried in + earned this year (15 days a year unless set on the employee, pro rata) - annual leave taken, with its value (balance x monthly salary / 30).
  - "All Payslips (PDF)": every payslip of a month in one PDF, one page each.
  - Employee file: new fields "End-of-service contributions before Saber (LBP)", "Annual leave days / year", "Leave days carried in".
- Reports:
  - Financial Reports > new tab "Management Pack" (month, currency): results of the month and the year to date against the budget and against last year, balance sheet summary (with its check), cash and banks, customers / suppliers ageing, VAT position of the quarter and key ratios (margins, current ratio, DSO / DPO, cash months), every currency converted. Excel / PDF.
  - Drill-down: double-click an account in Profit & Loss, Balance Sheet or Comparative P&L to see its entries; double-click an entry to open its document.
  - Dashboard: accounts off budget (costs above / revenue below the company budget of the year to date) by more than the % set in Accounting Settings (10% by default) are shown in "Needs attention".
- Changed files: inventory.py, payroll_extras.py (new), management_pack.py (new), desktop_payroll_extras.py (new), desktop_reports_extras.py (new), database.py, db_payroll.py, db_accounts.py, accounting_setup.py, server.py, client.py, desktop.py, desktop_inventory.py, desktop_payroll.py, desktop_reports.py, desktop_layout.py, desktop_accounting_setup.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_82.py.

## Version 2.9.81 (Accounting Settings and the Year-End Check)
- Settings > new tab "Accounting Settings":
  - "This company uses" (administrator): tick what the company uses - Sales Invoice, Uploaded Data, Journal Voucher, Import, Payment & Receipt, Purchases & Expenses, Inventory, Payroll, Quarterly VAT, Profit & Loss, Financial Reports, Fixed Assets, Production, Bank Reconciliation, and each Financial Report (General Ledger ... Business Reports). What is unticked leaves the menu / the report tabs for everybody in this company.
  - "I see (only for me)": each user hides more for himself (kept with his user, in every company). The company's choice comes first, and users' permissions (payroll, VAT, delete) still apply. Nothing is deleted; Dashboard, General Journal, Accounts & Statements and Settings are always shown. A screen hidden while another screen links to it says so.
  - "Default posting accounts": the accounts the program uses when a document does not name one, in one list (number - name): purchases, purchases without VAT, expenses imported without an account, sales / services, sales of goods, output VAT, deductible VAT (purchases / expenses), cash, bank commission, exchange gain / loss, VAT payable / credit and non-deductible VAT of the VAT settlement. Each is checked against the chart and its class; "Program Defaults" puts the original ones back. Documents already saved are not changed. Payroll accounts stay in Payroll > Settings (named there).
- Year-End Check (Accounting Settings, Profit & Loss > Year-end closing, and automatically when you press Close & Open next year): trial balance, documents in Review, payroll not posted, each VAT quarter saved and agreeing with the books, VAT accounts settled, receipts / payments not allocated, negative stock, negative cash / bank, suspense accounts 47 left, depreciation months not posted, LBP revaluation (DOE) needed at 31-12, customers in credit / suppliers in debit. Each line says what to do; Excel / PDF. Errors (red) must be corrected before closing; warnings can be accepted.
- The closing screen now says what the program does: result to 138 (profit) / 139 (loss) (it said 121 / 125).
- Changed files: accounting_setup.py (new), desktop_accounting_setup.py (new), database.py, db_invoices.py, db_payments.py, db_journal.py, vat_return.py, server.py, client.py, desktop.py, desktop_common.py, desktop_settings.py, desktop_reports.py, desktop_stage3.py, desktop_final.py, desktop_expenses.py, desktop_brains.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_81.py.

## Version 2.9.80 (fixes from a full-year accounting test)
A test company was run through a whole year (opening, purchases into stock, sales, credit note, receipts / payments with commission and exchange difference, expenses, fixed asset, LBP payroll, quarterly VAT and settlement, stock variation, closing, next-year opening) and every figure checked. The problems found are fixed:
- Payroll (important): an employee saved without a Salary Expense Account got 621100001 automatically, and that account won over the Standard Posting Accounts, so salaries were posted to 6211 (Purchase of Works from Sub-Contractors in the Lebanese chart) instead of 6311. The employer NSSF share was fixed in the program to 621100002. Now: an empty Salary Expense Account follows the Standard Posting Accounts (6311 staff, 6316 managers); the employer NSSF share has its own line "Employer NSSF (expense)", 6351 Social Security Fund Contributions by default. Employees that still had the automatic 621100001 are cleared once when the books are opened. The managers' accounts had been written as a copy of the staff accounts (6311); where they were identical, managers go to 6316 again. Payroll already posted is not changed (Chart of Accounts > Move / Transfer can move it).
- Quarterly VAT (important): when the previous quarter's return was not saved (a quiet quarter, or forgotten), its credit was lost: the next quarter showed VAT payable while an older credit existed. Now the credit is carried through the unsaved quarters (calculated), with a warning to save that quarter.
- Projection & Budget, Budget from a year, Budget Projection / Forecast, 5-Year Projection, Cash Flow Outlook and Cash Budget: in USD (or another currency) they read only what was ENTERED in that currency, so LBP payroll and LBP expenses were missing. They now use every transaction converted into the chosen currency (the reports screens keep their "Show currency" filter as before). The Cash Budget no longer counts the opening balances as cash received, and with All Currencies it is made in the company's main currency.
- Ageing (Financial Reports): receipts / payments not allocated to an invoice, and open credit notes, now settle the oldest invoices of the same customer / supplier and currency; what is left shows as "On account (not allocated)". The ageing of each party now agrees with its account.
- Expenses: no automatic expense account any more (it was 601100000 Purchase of Goods, so rent or fuel went into purchases); the account is chosen once and kept for the next expense.
- Purchases of items use the item's cost account on every path (before: only the Purchases screen).
- Asset accounts: the example now reads 2251 vehicles / 6512.5 depreciation / 2825 accumulated (681 is the book value of assets sold).
- Test changed on purpose: test_v2_9_50_projection's stub client accepts the new convert option.
- Changed files: chart_extra.py, db_payroll.py, database.py, vat_return.py, db_reports.py, db_invoices.py, server.py, client.py, desktop_payroll.py, desktop_expenses.py, desktop_assets.py, desktop_dimensions.py, desktop_projection.py, desktop_reports.py, app_runtime.py, installer.iss, README.md, test_v2_9_50_projection.py. New test: test_v2_9_80.py.

## Version 2.9.79 (account number + name everywhere, commission / exchange accounts, stock linked to cost, VAT check & settlement, budget from a year + %)
- Accounts are shown as "number - name" everywhere: every account field (after choosing, and when the program fills it), the account cells of the sheets (Uploaded Data preview, Journal Voucher), the Cash / Bank column of Payments & Receipts, the asset accounts and the DOE gain / loss column. Only the number is saved: the data service keeps the number of any "...account" field.
- Payments & Receipts: the bank commission and the exchange difference each go to the account chosen on the screen (Commission A/C, Exchange Gain A/C, Exchange Loss A/C; 673900000 / 775100000 / 675100000 by default). Any class 6 account for the commission and the loss, class 7 for the gain; an account not in the chart is refused. A "Journal entry" preview under the form shows the lines (number - name, Dr / Cr) before saving. Editing a receipt keeps its accounts.
- Items: new Stock Account (class 3) linked to its cost account and to the year-end variation accounts of the Lebanese chart: 37 goods -> purchases 6011 (601100000), variation 6051 / 6052; 31 raw materials -> purchases 6111 (611100000, created), variation 6151 / 6152; 33 work in progress -> 7211; 35 products -> 7255. Choosing the stock account fills the Cost Account; the link is shown under the form. Goods (37) with no cost account keep the account of the purchase screen, as before. The Stock Variation voucher is now made for each stock account used by the items (only 37 when all items are goods, exactly as before). Items keep their stock and cost accounts in the next fiscal year.
- Quarterly VAT: year from a list, quarter arrows (< >) and the quarter list generate the return at once. New tab "Check with the Books": the VAT accounts of the quarter (number - name, debit, credit), the return's output and deductible VAT against the books, and the documents whose VAT in the journal is not the VAT on the document (Excel / PDF). New "VAT Settlement Entry...": preview, then post the quarter-end voucher of a saved return - Dr 4427 / Cr 442... (as in the books), non-deductible VAT of Art. 31 to an expense (6459 by default), credit brought forward used (4429), VAT payable Cr 4425 or VAT to recover Dr 4429; the accounts can be changed; posting again replaces it. The VAT rules of the return are unchanged.
- Budget: "Budget from a year + %" - choose the base year (actual, also an earlier fiscal year file), the Revenue % and the Expenses %: every account keeps the months of the base year (seasonality) x (1 + %) per year up to the budget year. Review, then Save Budget.
- Financial Reports > new tab "Cash Budget" (next to Cash Flow Outlook): base year, cash budget year, Cash in % and Cash out %: month by month opening cash, cash in, cash out, net and closing cash (opening = class 5 at the end of the base year, + the years in between), the lowest month is shown (red when negative). Excel / PDF.
- Tests changed on purpose: test_ui_v2_9_18 - account fields and Uploaded Data cells now show "number - name", so the tests compare the number part (what is saved is still the number alone); test_saber_accounting counts one more account in a new chart (611100000 Raw Materials Purchases).
- Changed files: desktop_common.py, desktop.py, desktop_brains.py, desktop_stage3.py, desktop_assets.py, desktop_inventory.py, desktop_final.py, desktop_dimensions.py, desktop_reports.py, db_payments.py, db_accounts.py, database.py, inventory.py, chart_extra.py, vat_return.py, financial_projection.py, server.py, client.py, app_runtime.py, installer.iss, README.md, test_ui_v2_9_18.py, test_saber_accounting.py. New test: test_v2_9_79.py.

## Version 2.9.78 (retro tax, DOE in EUR and several currencies, AED / SAR daily, Search everywhere, Edit window)
- Payroll: a retroactive salary is now added to what was REALLY paid in its month: tax on (pay of that month + retro) less the tax already withheld that month (shown in the notes). Before, this month's salary stood in for the old month (wrong when the retro is a raise). Without a saved payroll for that month, the old way is kept and a note says so.
- Automatic DOE: "Revalue in" LBP, USD, EUR or another currency of the company; "Currencies" is a tick list (USD + EUR + SAR ... or All). A EUR DOE moves only the EUR value: the account keeps its own balance, USD and LBP do not change, the gain / loss is in EUR (journal lines carry the EUR revaluation; reports in EUR read it).
- Exchange rates: SAR is a standard currency; AED and SAR get their rate to USD and to LBP every day automatically (fixed to the US dollar, no internet needed); rates typed by hand are kept.
- Uploaded Data > One Account for Selected: "Cash / Bank account (paid invoices)" moves the payment of the selected paid invoices to another cash / bank account (unpaid ones are listed).
- Uploaded Data > Edit: rebuilt as lines - VAT, purchases / sales with VAT, without VAT, customer / supplier - each with account, D / C and amount, then Payment (account, method, amount). VAT follows the amount at the company rate (until typed), the Total is the sum, and Cash / Bank Transfer / Cheque / Card fill 531 / 512 and the amount paid with the Total.
- Search: every search window (customers, items, purchases, vouchers) - Up / Down / Page Up / Page Down move, Enter takes the highlighted row; the Search box of Uploaded Data is now also on the asset register, depreciation, DOE, warehouses, recipes, bank reconciliation and every report.
- Restore All Currencies lists the currencies in the same (alphabetical) order on every PC (the Windows build listed SAR before AED).
- Tests changed on purpose: test_ui_v2_9_18 finds the Edit window's account boxes by their account (the order changed), and its USD-books DOE test ticks the currency in the new "Currencies" tick list instead of a drop-down; test_final_features and test_v2_9_71 know that SAR is now a standard currency.
- Changed files: db_payroll.py, db_journal.py, db_accounts.py, db_rates.py, database.py, ledger_reports.py, desktop_common.py, desktop.py, desktop_brains.py, desktop_invoices.py, desktop_inventory.py, desktop_purchases.py, desktop_v22.py, desktop_final.py, desktop_assets.py, desktop_asset_register.py, desktop_production.py, app_runtime.py, installer.iss, README.md, test_ui_v2_9_18.py, test_final_features.py, test_v2_9_71.py. New test: test_v2_9_78.py.

## Version 2.9.77 (sales on the right accounts)
- Fixed (important): a sale imported from Excel was booked Dr 4011 SUPPLIERS / Cr 601100000 expenses / Cr 442660000 deductible VAT - the importer put the purchase defaults on every row. A sale is now always booked Dr the customer's own account / Cr a class 7 revenue account (713 when none is given) / Cr output VAT 4427, whatever the way it comes in (Excel import, sales import, sales screen, returns).
- Fixed: sales entered without a party account (Excel / sales import, a new customer typed by hand) went to the general 4111 instead of the customer's own account, so the customer's statement and ageing missed them. An account chosen on purpose (41...) is kept. Items sold from stock without a revenue account go to sales of goods (701100001), not services.
- New: Uploaded Data > "Check Sales Accounts..." lists the sales that earlier versions booked on wrong accounts (customer on 40... or 4111, revenue not class 7, VAT on deductible VAT) with what will be corrected; Correct Selected / Correct All moves only those accounts on the invoice and its journal lines (amounts, dates and VAT unchanged; closed periods are refused). Make a backup first.
- Purchases are unchanged.
- Fixed: Refresh opening (next year's opening balances) stopped with "Account ... was not found in the chart of accounts" when a customer or supplier account was opened in the previous year after the new year had been created. The account and its customer / supplier are now copied into the new year first.
- Test changed on purpose: test_saber_accounting.py expected an imported sale on the general 4111; it now expects the customer's own account (4111xxxxx), like the supplier's (4011xxxxx) for a purchase.
- Changed files: db_invoices.py, db_accounts.py, importer.py, year_end.py, server.py, client.py, desktop_invoices.py, app_runtime.py, installer.iss, README.md, test_saber_accounting.py. New test: test_v2_9_77.py.

## Version 2.9.76 (test documents made anonymous)
- The real supplier documents kept for the PDF-reader tests no longer show real people or companies: supplier names, workers' names, project, bank accounts / IBAN / SWIFT, registration and VAT numbers, phone numbers and e-mail replaced by samples. Amounts, dates and layout are unchanged, so the reader is checked exactly as before.
- Files renamed: tests_data/ocr_contractor_variation_order.txt, tests_data/ocr_supplier_invoice.txt, tests_data/text_supplier_invoice_broken_arabic.txt (test_pdf_real_scans.py follows). These files are not part of the installer.
- No change in the program. Changed files: tests_data/*.txt, test_pdf_real_scans.py, app_runtime.py, installer.iss, README.md.

## Version 2.9.75 (data folder copied to a new computer)
- Fixed: after copying the SaberAccounting folder to another computer or another Windows user (C:\Users\<name>\SaberAccounting), the companies were listed but would not open ("Company database path must be inside the application data directory"), because the company list kept the old full path. The program now finds each file in the new folder and saves the new place. A path outside the data folder is still refused.
- Checked: moving with only the backups works too - create the company with the same name and fiscal year, its backups appear in Backup & Restore, restore.
- Changed files: company_manager.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_75.py.

## Version 2.9.74 (a new installation starts with no company)
- A new installation no longer shows a company: the list is empty and the administrator creates the first one with Create Company (the screen says so). Installations that already have companies keep them exactly as they are. A main file from a version before the company list (books kept in the main file) still opens, as a company under the name saved in its settings.
- Real company names and numbers removed from the tests, the test documents and this README (made-up samples instead).
- Tests: the tests written for the old start-up (one company in the main file, 2024) now ask for a made-up "Sample Company SARL" through tests_setup.py (imported by those test files only; not part of the program). New test: test_v2_9_74.py.
- Changed files: company_manager.py, server.py, desktop.py, app_runtime.py, installer.iss, README.md, tests_setup.py (new), test_v2_9_74.py (new), tests_data/*.txt, and the tests that import tests_setup.

## Version 2.9.73 (GitHub build kept working)
- Tests workflow pinned to Ubuntu 24.04: GitHub moves "ubuntu-latest" to Ubuntu 26 from 19-10-2026, which could break the Tk tests without any change in the program.
- Installer workflow: actions/upload-artifact v4 -> v6 (v4 ran on the deprecated Node.js 20).
- No change in the program itself. Changed files: .github/workflows/tests.yml, .github/workflows/build-windows-installer.yml, app_runtime.py, installer.iss, README.md.

## Version 2.9.72 (VAT rate and VAT return currencies per company)
- Companies: Create Company asks for the company's VAT Rate % (11 by default; for example 5 in the Emirates, 15 in Saudi Arabia) and the two VAT Return Currencies (LBP with USD by default; for example AED with USD, EUR with USD). Settings > General shows them next to "Registered in VAT" and they can be changed there.
- The company's VAT rate is used everywhere 11% was fixed: sales invoice lines, totals and printed invoice ("VAT 5%"), purchases, expenses, imported sales, invoice lines saved without a rate, items (standard rate or 0%). The sale type "Taxable 11%" is now "Taxable (standard rate)". Documents already saved keep their VAT.
- Quarterly VAT return: added up in the VAT return currency 1 (LBP: whole pounds and the LBP 10,000 rounding as before; another currency: 2 decimals, no LBP rounding), with the payable / credit also in currency 2 at the rate of the last day of the quarter. Screens, Excel and PDF name the currency. The Lebanese MoF forms (Q11-2, recoverable-rate sheet) stay LBP-only: a return in another currency shows a note.
- Fixed: selecting several Purchases, Expenses or Payments and pressing Delete stopped with "bulk_action is not defined" (since 2.9.69).
- Changed files: company_manager.py, database.py, database_common.py, db_invoices.py, inventory.py, vat_return.py, report_export.py, desktop.py, desktop_common.py, desktop_settings.py, desktop_invoices.py, desktop_v22.py, desktop_purchases.py, desktop_expenses.py, desktop_inventory.py, desktop_final.py, desktop_stage3_common.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_72.py.

## Version 2.9.71 (two main currencies per company, rates of every currency, faster voucher accounts, one account for selected rows)
- Companies: Create Company asks for the company's two main currencies (USD + LBP by default; for example EUR + USD or AED + USD). Settings > General shows them as "Main Currency 1 (base)" and "Main Currency 2" and they can be changed there. New journal vouchers, sales invoices, purchases, expenses, payments, customers / suppliers and imports start in Main Currency 1; the 2nd column of the Trial Balance / Statement starts in Main Currency 2. The books keep their USD and LBP equivalents as before (VAT and NSSF stay in LBP). A new fiscal year keeps the company's currencies.
- Exchange rates: "Restore ALL Currencies 2024-Today" (Settings > Exchange Rates) fills the daily rate of every currency of Settings: EUR, GBP, CHF, CAD ... from the European Central Bank, AED / SAR / QAR / BHD / OMR / JOD at their fixed US dollar rate, LBP 89,500. Rates typed by hand are kept; a currency without an automatic source is listed to be entered by hand. "Restore EUR Rates" stays.
- Journal Voucher: type the account number and it is taken - the full number, or the first digits when only one account starts with them (5310 -> 531000001). Otherwise the account search opens with what was typed: the first match is highlighted, Up / Down / Page Up / Page Down move, Enter selects.
- Uploaded Data: "One Account for Selected..." - select rows (Ctrl / Shift / drag), choose which account (Purchases / Expense / Sales, VAT, Non-deductible, Customer / Supplier) and the new account: it replaces that account on every selected invoice and on its journal lines; amounts and the other lines stay as they are. Rows that cannot change (cancelled, deleted, closed period, same account used twice) are listed.
- Financial Statements (audit report): the notes show the account names without the account numbers.
- Changed files: company_manager.py, database.py, db_rates.py, db_accounts.py, financial_statements.py, server.py, client.py, desktop.py, desktop_common.py, desktop_settings.py, desktop_brains.py, desktop_invoices.py, desktop_expenses.py, desktop_purchases.py, desktop_stage3.py, desktop_parties.py, desktop_balance_reports.py, app_runtime.py, installer.iss, README.md. New test: test_v2_9_71.py.

## Version 2.9.70 (restore of older backups, NSSF ceiling text)
- Fixed: restoring a backup made by an older version brought back "no such column: i.payment_account" (and similar) until the program was restarted. The restored file is now upgraded at once (new tables / columns added; data and the admin password kept).
- Fixed: the payroll help ("Load Lebanese Payroll Rules") and these notes said the NSSF sickness & maternity ceiling is LBP 140M from 08-2025. The calculation already used the correct LBP 120M (Decree 887 of 21-08-2025); only the texts were wrong.
- Removed: an unused screen that asked for an OpenAI API key (PDF reading and account suggestions are local only). AI_RULES.md section 6 updated.
- Changed files: database.py, desktop_payroll.py, lebanese_payroll.py, desktop_stage3.py, app_runtime.py, AI_RULES.md, installer.iss, README.md. New test: test_v2_9_70.py.

## Version 2.9.69 (multi-select delete, show / hide columns, audit report pack)
- Delete works on the whole selection (Ctrl / Shift / drag, or the Delete key): Uploaded Data, Purchases & Expenses, Payments & Receipts, Journal Vouchers. One question before, one summary after.
- Uploaded Data: "Show:" ticks next to Search hide / show the Branch, Type, D and C columns (kept on this computer).
- Business Reports > Top Clients / Top Suppliers: the VAT number (or MOF number) replaces the account number.
- Financial Statements are now an audit report pack: Independent Auditor's Report (ISA 700 wording), Statement of Financial Position, Statement of Profit or Loss and OCI, Statement of Changes in Equity, Statement of Cash Flows (indirect method), Accounting Policies and Explanatory Notes with account breakdowns. For 2 years, or for a period (From - As of) with the same period of the previous year as comparative. All texts can be edited (Edit Texts).
- Tests: test_v2_9_69.py, test_financial_statements.py updated.

## Version 2.9.68 (Uploaded Data filters)
- Uploaded Data: Branch and Type are tick lists (one, several or All), and D / C ticks show the debit rows (sales), the credit rows (purchases, expenses) or both.
- Tests: test_v2_9_68.py.

## Version 2.9.67 (move chosen transactions between accounts)
- Chart of Accounts > Move / Transfer...: "Move the CHOSEN transactions" lists the transactions of the From account (date range), choose some (Ctrl / Shift / drag, their total shows) and Run: those same entries are booked on the To account (replacement, no new voucher). The invoice / payment / expense behind each line names the new account too (editing it later keeps the change); when both accounts are customers / suppliers, those documents move to the new customer / supplier (can be unticked).
- Tests: test_v2_9_67.py.

## Version 2.9.66 (accounts tools, several rows, trial balance options)
- Fixed: Financial Reports opened before the Inventory page was ready ("no attribute 'ageing_tab'").
- Fixed: Switch Company / Year while pages were still loading showed up to 17 "page could not be loaded" messages.
- Chart of Accounts: Delete Selected (one or many, any kind: clients, suppliers, expenses...; only accounts without transactions, and a customer / supplier file that only holds that account goes with it), Delete Unused Accounts... (list by kind, select some or all), Move / Transfer... (move all the transactions of an account to another - and merge the customer / supplier - or transfer its balance with a journal voucher). Official chart accounts are never deleted.
- Every table: select several rows with Ctrl / Shift or by dragging the mouse; the count and the totals of the amount columns appear above the table.
- Trial Balance / Statement: "Without Opening entries" and "Without Closing entries".
- Tests: test_v2_9_66.py.

## Version 2.9.65 (Production)
- Inventory > Production:
  - Recipes: the materials (and an extra cost per unit) that make a quantity of a product. A material can have its own recipe; a recipe can never go round in a circle.
  - Production Orders (PRD-YYYY-000001): product + quantity, materials calculated from the recipe. For a special order the quantities can be changed or materials added / removed on the order only. Red = not enough stock, amber = different from the recipe. Materials leave one warehouse, the product enters another (or the same).
  - Cost of the product = materials at their real cost (average or FIFO) + extra cost, recomputed by the costing engine (a purchase entered later with an earlier date updates it).
  - Production Report: orders, products made (average unit cost), materials used; Print / Excel / PDF. The Stock Card shows production lines.
  - Periodic method of the Lebanese chart: no journal entry; the year-end stock (37) includes the products at their production cost.
- The upgrade marker of 2.9.64 now also follows the inventory, fixed-asset and bank upgrades (the new recipe tables reach every company file).
- User guide: new section 6. Production.
- Tests: test_v2_9_65.py.

## Version 2.9.64 (old company files upgraded again)
- Fixed "no such column: i.payment_account" (Edit from the General Journal, Uploaded Data, Purchases ...): company / year files made before 2.9.54 were marked as up to date and never received the new columns. The upgrade marker is now computed from the upgrade code, so every file is upgraded once when a new version adds a column or table. Data is kept.
- Tests: test_v2_9_64.py.

## Version 2.9.63 (stability, speed, tidier code)
- Stability check on real company data (purchases and sales), as admin, accountant and viewer: every screen, every data request, and every entry opened for editing and saved again without changes (the books stay identical).
- Fixed: a user without the VAT right got an error on Financial Reports and saw no ledger / balance sheet / cash flow. Now only the VAT part is hidden.
- Fixed: reports given a DD-MM-YYYY date (journal, trial balance, ledger, balance sheet, P&L, cash flow, VAT) now filter the right days.
- Faster: exchange rates are read once and kept in memory (a trial balance of 20,000 invoices: 28 s -> under 1 s).
- database.py (4,300 lines) split into database.py + database_common.py + db_invoices, db_payments, db_journal, db_reports, db_payroll, db_rates, db_vat, db_dimensions, db_documents. Same code, same Database class.
- Tests: test_v2_9_63.py.

## Version 2.9.62 (Trial Balance / Statement: tick several branches, departments, projects)
- Trial Balance and Statement of Account: Branch, Department and Project are tick lists like the inventory filters - one, several or All. The chosen filters are printed in the report header.
- Tests: test_v2_9_62.py.

## Version 2.9.61 (clear error messages)
- "The data service could not complete the request" now also shows which request failed and the error (for example GET /api/invoices - KeyError: 'EUR'), and opening an entry from the General Journal names the step that failed. Full details stay in SaberAccounting/logs/saber.log.
- Values that could not be written in the answer (amount, date or file data saved by an older version) no longer stop the request.
- Tests: test_v2_9_61.py.

## Version 2.9.60 (side menu and Dashboard "Needs attention")
- Menu on the left, in groups: Home, Sales, Purchases & Cash, Inventory, Accounting, Payroll & VAT, Settings. Click a group title to fold it. The old buttons above the pages: Settings > General Settings > Screen layout (kept on this computer).
- Dashboard: Quick actions (Sales Invoice, Purchase / Expense, Import, Journal Voucher, Statement, Financial Reports) and a "Needs attention" list (overdue invoices, legal documents expired / expiring, unbalanced entries, last backup) with a button for each.
- Tables fit the window: columns share the width (still resizable by dragging), so the toolbars above them wrap instead of going off the screen.
- Tests: test_v2_9_60.py. 499 tests pass.

## Version 2.9.59 (cleaner layout)
- Dates in every table are shown DD-MM-YYYY (the data and exports keep the real date).
- Toolbars wrap onto a second line on small screens (1366 px) instead of hiding buttons: General Journal, Uploaded Data, Import (Save button), Financial Reports, Inventory reports.
- Amount columns (Debit, Credit, Total, VAT, Balance...) are right-aligned; table font 10 pt with taller rows.
- One colour palette on every screen (navy #102A43, gold #B78B45, light #F4F7FA).
- Tests: test_v2_9_59.py. 492 tests pass.

## Version 2.9.58 (sharp logo, much faster with big files, all invoices listed)

- The header logo was shrunk by dropping pixels and could not be read. It is now the "SA" monogram alone, resized with filtering, in white and gold on the navy bar; the login card shows the full logo, sharp. New file brand_images.py (Pillow, already installed with ReportLab; listed in requirements.txt).
- Speed: exchange rates are looked up once per currency and day and kept until a rate changes (the trial balance and the account statements of a big company were slowed by a rate query for every journal line: 3,000 invoices took 40 seconds, now under 1 second); the trial balance is summed by the database. The internet is asked for EUR rates at most once every 6 hours (offline, each refresh of the Uploaded Data or the sales invoice could wait up to 30 seconds).
- Fix: the Uploaded Data list, the purchases list, opening an entry and other screens showed only the newest 500 invoices; every invoice is listed now. The import preview shows up to 20,000 rows (was 2,000).
- Shortcuts: the installer gives the Desktop / Start menu shortcuts the Saber icon (2.9.57).
- Tests: test_v2_9_55.py extended, test_v2_9_58.py. 487 tests pass.

## Version 2.9.57 (icon without changing the workflow)

- The icon no longer depends on the GitHub workflow: the installer copies saber.ico next to the program and uses it for the Desktop / Start menu shortcuts, Add / Remove Programs and the window. With the 2.9.56 workflow pasted, SaberAccounting.exe itself also carries it (Explorer); without it the build still passes.
- Changed files: installer.iss, desktop.py, app_runtime.py, test_v2_9_55.py, README.md. 484 tests pass.

## Version 2.9.56 (Saber icon)

- The program, the backup service, the installer and the window / taskbar now carry the Saber for Audit "SA" icon (Assets/saber.ico, 16 to 256 pixels), made from the logo. THE WORKFLOW FILE MUST BE PASTED BY HAND on GitHub (it adds --icon and the icon file to the build).
- Tests: test_v2_9_55.py extended. 484 tests pass.

## Version 2.9.55 (Excel currency fix)

- Excel import: a price cell formatted in a currency the company does not use (for example EUR in a USD / LBP company) stopped the whole import with "KeyError: 'EUR'". The row is now imported in the default currency, marked "unsupported:EUR" and kept for review.
- Logo: Assets/Saber_for_Audit_logo.png was not a valid picture (damaged since 2.9.40), so the login / header logo and the default invoice logo were missing. Replaced with the Saber for Audit logo.
- Excel files without an invoice number column: a row with the same supplier, date and total as another row of the file, or as an invoice already in the books, is kept in the preview with the reason (or imported anyway when you choose).
- Purchases: "Paid" (On Account / Cash / Bank Transfer / Cheque / Card) and "from A/C": a purchase paid on the spot gets its payment entry to 531 / 512 or the chosen account, and shows in that statement.
- Tests: test_v2_9_54.py extended, test_v2_9_55.py. 483 tests pass.

## Version 2.9.54 (journal edit fix, returns on the sales / purchase screens, 3D analysis with any 3 dimensions, Excel import of incomplete files, cash on uploaded invoices, stability)

- Fix: General Journal > Edit Selected Entry on a receipt / payment (and other screens kept in a scrolled page) stopped with "<tkinter.Frame ...> is not in list". The screen now opens.
- Sales Invoice: Document = Invoice / Return / Credit Note / Debit Note. Return = goods come back into stock (returns account 709 / 719, reversed entry); Credit Note = discount; Debit Note = extra charge (no stock).
- Purchases: Document = Invoice / Return / Credit Note / Debit Note. Return = goods go back to the supplier (stock out at average cost, Dr supplier / Cr purchases and VAT).
- Inventory Analysis (3D): choose any three dimensions - Rows, Columns and Layers - among Item, Category, Subcategory, Brand, Supplier, Unit, Warehouse, Month, Project and Branch, in Quantity or Value. One table per layer, the totals, and a "3D Chart" button (also in PDF / Excel).
- Excel import: rows where only formulas were copied down are skipped; rows missing the name, the date or the amount, with an invalid date (e.g. 02-05-20204) or formulas without saved values stay in the preview with the reason, and the other rows are imported. Rows dated in another fiscal year are kept for that year (or imported anyway when you choose).
- Uploaded Data > Edit: choosing Cash / Bank with Amount Paid 0 asks to mark it paid in full; the payment is posted to 531 / 512 (or the account chosen) and shows in the cash / bank statement.
- Stability: Python's memory clean-up now runs on the screen thread only; before, it could run on the data-service thread and stop the program ("main thread is not in main loop").
- Tests: test_v2_9_54.py. 478 tests pass.

## Version 2.9.53 (renamed company: second backup copy follows)

- Renaming a company (Companies screen) already moved every year file and the backups folder to the new name, and the years stay linked by the company id, so last year is still found. Now the second backup copy folder (OneDrive / USB) is renamed as well, instead of starting a new folder.
- Tests: test_v2_9_53.py. 472 tests pass.

## Version 2.9.52 (warehouse multi-select, earlier fiscal years, second backup copy, delete permission, optional code signing)

- Inventory reports: the Warehouse filter takes any combination (e.g. MAIN + W3) in every report - valuation, stock card, movements, brands, health, ageing, 3D analysis.
- Earlier fiscal years: reports can read another year's own file. Comparative P&L shows the prior year from last year's file (it showed 0 when each year has its own file). The projection shows the earlier actual years, completes a year in progress with last year's months (last 12 months), and "% from past years" sets the revenue growth from the actual history.
- Backups: Settings > Backup & Restore > "Second copy of every backup": OneDrive (found automatically), USB or network folder. Every checked backup is copied there (company / year), the newest 30 automatic copies are kept, manual and safety copies are never removed. The status (last copy or the error) is shown; a failed copy never stops the backup.
- Users: new "Can delete / cancel" permission (delete or cancel posted documents, replace all invoices). Off for new users; existing users keep what they could do until the administrator changes it.
- Fix: an accountant (non-administrator) can save in a company file - the user is copied into the company-year file (saving failed with "FOREIGN KEY constraint failed").
- Build: optional code signing. Add the GitHub secrets SIGN_CERT_PFX_BASE64 and SIGN_CERT_PASSWORD (a code-signing certificate) and the program, the backup service and the installer are signed; without them the build works as before. THE WORKFLOW FILE MUST BE PASTED BY HAND on GitHub.
- New file backup_copy.py. Tests: test_v2_9_52.py. 471 tests pass.

## Version 2.9.51 (no duplicate invoices or items from uploads, no hidden journal lines, build version check)

- Duplicate invoices: before an upload or import is saved, Saber looks for an invoice already in the books with the same type, the same customer / supplier and the same number (INV-0045 = inv 45; cancelled ones ignored). Automatic saving skips it and says why; a manual save or import asks (skip / save again / stop).
- Items: a purchase line whose name is written differently ("HPL Panel 4mm White" / "hpl panel - 4 MM white") uses the existing item. When only a close name exists, a small window asks once: use the existing item or create a new one.
- Reports read every journal line: the General Journal, General Ledger, Cash Flow, "open transaction" and the voucher list used to stop at 5,000 / 20,000 / 50,000 lines. Cash Flow is now summed by the database.
- GitHub build: a first step stops with a clear message when the files were uploaded inside a sub-folder or when installer.iss and app_runtime.py carry different versions; the run summary shows the version built and the artifact is named SaberAccountingSetup-<version>. THIS WORKFLOW CHANGE MUST BE PASTED BY HAND in .github/workflows/build-windows-installer.yml on GitHub.
- Tests: new test_v2_9_51.py. 464 tests pass.

## Version 2.9.50 (recoverable VAT rate sheet, professional projection & budget with 3D charts, automatic upload posting, multi-select filters)

- VAT: new "Taux Récupérable" PDF / Excel on the Quarterly VAT screen, in the layout of the accountants' worksheet "Calcul du taux récupérable": revenues taxable / export / exempt / outside the scope (quarter and year-to-date base of the rate), the recoverable rate, the VAT on fixed assets, goods, packaging and overheads split into recoverable and non-recoverable, VAT collected and VAT payable. The deduction ratio now keeps 6 decimals (the 2018 example matches to the LBP).
- Financial Reports > "Projection & Budget (3D)": built from the books (base year, or the current year annualised from its complete months), growth % per line and per year (revenue, cost of sales - empty follows revenue, personnel, operating expenses, other income, financial charges), investments and financing per year, tax rate, customer / supplier days, three scenarios. Reports: assumptions, projected income statement, projected cash flow (indirect method), key indicators (margins, break-even, cash runway), scenario comparison, budget by account per year, monthly budget and monthly cash plan. 3D charts on screen (angle / depth sliders), in the PDF and as native 3D charts in Excel. "Save as Budget" writes the chosen projected year into the Budget tab. The existing Cash Flow Outlook and Budget tabs are unchanged.
- Upload: "Save automatically after upload" (on by default, remembered). A purchase PDF that has supplier, number, date, amount and VAT is saved, posted (journal entry) and its items received at once; items that do not exist are created in Inventory. On the Import tab, complete rows are posted right after reading; PDF purchase rows whose item lines were read create the missing items and receive them in stock. Rows needing a check stay in the preview with the reason.
- Filters: Financial Reports filters and Inventory Report filters (category, subcategory, unit, supplier, brand, project, branch) accept any combination of values (tick list with search, All, Clear).
- New files: chart3d.py, projection_model.py, desktop_projection.py, multi_select.py. Tests: test_v2_9_50_vat.py, test_v2_9_50_projection.py, test_v2_9_50_upload.py, test_v2_9_50_filters.py. 456 tests pass. The GitHub workflow does not need any change (modules are added automatically since 2.9.46).

## Version 2.9.49 (VAT form Q1-2 with Art. 31 annex, returns from the invoice screens, voucher edit, report filters)

- **VAT: "Official Form Q1-2 (PDF)" / "Official Form Excel"** (Quarterly VAT). The return in the layout of the Ministry's periodic declaration: boxes 100-190 (revenues: amount / VAT due), 200-250 (purchases, charges, fixed assets: amount / deductible VAT), settlement 300-370; annex **Q11-2** partial right of deduction (boxes 600-710): purchases, charges and fixed assets used only for deductible operations, only for non-deductible operations, and whose use cannot be determined - for these the deductible VAT = VAT paid x ratio (Art. 31), computed automatically; annex **Q13-2** ten largest suppliers and customers with their MOF numbers. Boxes Saber does not record separately (advances, withholding at source, fixed-asset sales, penalties) show 0 to be completed by hand.
- **Deduction ratio corrected to the form's definition:** total revenues now include revenues outside the scope of VAT (box 150), as the note of Q11-2 states (revenues giving the right of deduction / total revenues). Before, they were left out, which gave a ratio that was too high when such revenues existed.
- **Return (goods back)** buttons on the Sales Invoice and Purchases screens, for the invoice that is open (the same quantity-reviewed return as in Uploaded Data; stock moves back).
- **Journal Voucher: "Edit..."** opens a searchable list of saved vouchers; double-click / Enter opens one to change, then Save.
- **Financial Reports: "Choose filters..."** - tick which filters appear (Branch, Project, Department, Customer / Supplier, Section); they filter the General Ledger. The choice is kept on this computer.
- **Reports keep all their columns again** (owner request): only the payroll worksheets hide all-zero columns; financial statements, ledgers, trial balance, VAT and inventory are as before 2.9.45.
- Payroll > Employees: the R3 / R3-1 worksheet and CNSS Employee Forms buttons are removed (the forms remain in "Official Forms (Excel)"); empty dates and job titles no longer show "None".
- Tests: new `test_v2_9_49.py` (form boxes, annex and partial deduction, ratio with out-of-scope revenues, largest suppliers, all-currencies rule, columns kept, journal project / department). 438 tests pass.
- Changed files: vat_return.py, desktop_final.py, desktop_invoices.py, desktop_purchases.py, desktop_brains.py, desktop_reports.py, desktop_payroll.py, desktop_common.py, report_export.py, payroll_reports.py, database.py, app_runtime.py, installer.iss, README.md, test_v2_9_49.py (new), test_inventory_v2_9_45.py.

## Version 2.9.48 (Payment & Receipt: customer / supplier always found)

- Saving a receipt or payment said "Choose the customer / supplier from the list" even with a customer chosen: the box had to hold exactly "Name | account number", so a typed name, or a customer created after the screen was opened, was refused. Saber now finds the party from the full text, the name alone, the account number, or a part of the name that matches one party only (the list is reloaded once for new parties). When several match, it lists them. The box then shows the full choice and the open invoices load (leaving the box with the same party keeps the allocations already typed).
- Tests: new `test_payment_party.py`. 434 tests pass.
- Changed files: desktop_stage3.py, app_runtime.py, installer.iss, README.md, test_payment_party.py (new).

## Version 2.9.47 (cash invoices settled, edit entries, chart of accounts edit, Escape in reports)

- **Invoices paid on the spot now post their payment.** When an invoice (uploaded, added as a row, or from the Sales Invoice screen) has a payment method other than "On Account" and an Amount Paid, Saber makes the settlement entry `PINV-<id>`: sale Dr cash / bank - Cr customer; purchase Dr supplier - Cr cash / bank. Before, the amount was only stored and the customer / supplier stayed open in the ledger.
- **Choose the account:** new field "Cash / Bank Account (paid)" in Edit Selected and Add Invoice Row, and "Paid into" on the Sales Invoice screen. Empty = 531 for Cash, 512 for the other methods. The choice is kept with the invoice (`invoices.payment_account`). Editing the invoice rebuilds the entry; On Account / zero paid removes it; cancelling or deleting the invoice removes it.
- **Invoices uploaded before this version:** Uploaded Data > "Create Missing Payment Entries" makes the missing entries once (invoices in a locked or closed period are listed and left as they are).
- **General Journal: "Edit Selected Entry"** (or double-click a line) opens the entry where it can be changed: Journal Voucher, Sales Invoice, Purchases, Uploaded Data edit window, Payment & Receipt or Expense. Automatic entries (opening, closing, depreciation, stock variation) say so and are corrected with a Journal Voucher.
- **Chart of accounts: "Edit Selected Account"** (or double-click / Enter) opens a window with the English, French and Arabic names and the type, and a **Save** button (Enter saves, Escape cancels). Each change is in the audit log.
- **Trial Balance / Statement of Account:** Escape now steps back one level and closes nothing (a statement opened from a trial balance line goes back to that trial balance; a report goes back to Options). It no longer jumps to the Dashboard. A transaction window has "Edit this entry" (or double-click / Enter) and Escape closes it. After editing an entry opened from a report, Escape returns to the same report tab, refreshed.
- Uploaded Data: "Create Return / Credit Note" renamed "Create Return (goods back)".
- Tests: new `test_v2_9_47.py` (cash sale and bank purchase entries with the chosen account, on account / unpaid none, edit / cancel / delete follow the invoice, customer balance settled, missing entries created once and locked periods skipped, account names and type saved and checked, the account edit window, journal edit). The statement navigation test now checks the new Escape. 431 tests pass.
- Changed files: database.py, server.py, client.py, desktop_invoices.py, desktop_settings.py, desktop_reports.py, desktop_balance_reports.py, app_runtime.py, installer.iss, README.md, test_v2_9_47.py (new), test_statement_navigation.py.

## Version 2.9.46 (Windows build: every program file included automatically)

- The 2.9.45 build failed only because GitHub still had the 2.9.43 workflow (uploading files does not replace the `.github` folder), so the new payroll modules were missing from the build and the safety test stopped it.
- The build step now adds every program module of the repository by itself (all `*.py` except tests), so new files never need a workflow edit again. The list is printed in the build log. The safety test accepts this.
- Replace `.github/workflows/build-windows-installer.yml` on GitHub once more (Edit, paste, Commit); after that, uploading the ZIP is enough.
- Changed files: .github/workflows/build-windows-installer.yml, test_v2_9_42.py, installer.iss, app_runtime.py, README.md.

## Version 2.9.45 (negative stock alert, returns vs notes, brand, project / branch, report check-up)

- **Negative stock: alert and continue.** When a sale, stock issue, transfer or cancellation would take an item below zero in a warehouse, Saber now shows the item, warehouse, date, quantity available and requested, and asks "Save anyway?". Yes saves it (the documents concerned are marked, so later work is not blocked); No saves nothing. Average and FIFO costing both handle negative stock: the missing quantity goes out at the last known cost and the next receipt in that warehouse settles it. Works from every screen (the data service asks through the X-Allow-Negative-Stock confirmation).
- **Return vs Credit Note vs Debit Note.** A **Return** (Return Selected Invoice) brings goods back / sends them back and moves stock. A **Credit Note** or **Debit Note** is a discount or price adjustment: it never moves stock, even when its lines name items. New column `invoices.is_return`; returns made earlier are recognised automatically. Lists show Sales / Purchase Return, Credit Note, Debit Note; the PDF title is RETURN NOTE for returns.
- **Brand** on items (Items screen, list column, combobox of existing brands), report filter, and the new report **Stock by Brand & Warehouse**.
- **Project and branch on stock documents** (Stock Documents screen) and **Brand / Project / Branch filters** on the inventory reports (movements and sales margin also filter by the document's project / branch).
- **Choose what appears**: Warehouses & Settings > "Show in the inventory screens": Brand, Warehouse, Project, Branch. Unticked ones disappear from items, stock documents and report filters.
- **Report check-up (all reports, screen, PDF and Excel):** columns that are empty or zero on every line are left out (code and name always stay; official layouts keep every column); zero amounts show as "-"; amounts are right-aligned in PDF; total lines are bold. The R10 worksheet now fits on one page width. The official payroll statements show English and Arabic in separate columns with clean header lines.
- Fixed: the 2.9.41 error handler no longer shows a message when the session has expired (the sign-in screen is shown, as before 2.9.41).
- Note found during the check-up: `Assets/Saber_for_Audit_logo.png` is not a valid PNG image (the program falls back to the text logo). Replace it with the real logo file.
- Tests: new `test_inventory_v2_9_45.py` (shortage asks then saves when confirmed; sale invoice alert with nothing half-saved; FIFO negative stock settles on the next receipt; the real client asks and resends; return moves stock but credit / debit notes do not; brand filter and report; project / branch on documents and in movements; screen settings; tidy reports). Two tests of goods coming back on a credit note now mark it as a return. 422 tests pass.
- Changed files: inventory.py, database.py, server.py, client.py, report_export.py, payroll_official.py, desktop.py, desktop_inventory.py, desktop_invoices.py, desktop_final.py, app_runtime.py, installer.iss, Assets/user_guide.html, README.md, test_inventory_v2_9_45.py (new), test_final_features.py, test_payroll_declaration.py.

## Version 2.9.44 (payroll like the official salary declaration workbooks)

Built on the layout of the MOF salary declaration workbooks (employees register, monthly & cumulative movement, R10, R5, R6, audit statement, leavers register). The NSSF statements, NSSF format and NSSF payments are unchanged (owner request).

- **Allowances by R6 line** (`payroll_lines.py`): cost of living and extra indemnity (100), representation taxable / not (110), car (160), housing (170), food (180), clothing (190), cash handling (200), health insurance (210), education (220), marriage (230), birth (240), sickness (250), death (260), other (300). Most exist twice (taxable / not taxable): the amount is entered in the right one, as in the paper workbook. Taxable recurring allowances are taxed with the salary; grants (220-300) are taxed like a bonus. Taxable allowances are subject to NSSF unless listed in the setting `payroll_allowances_not_nssf`; not-taxable ones are not. Saved with each payroll (`payroll_records.allowances`) and posted to the Allowances account (empty = salary account). The cumulative tax method counts earlier months' taxable allowances.
- **Employee register** (employee window, new box): unit code / unit, cost of living, extra indemnity, representation (taxable / not) per month, "not subject to NSSF" for end of service / family allowances / sickness & maternity (used by the calculation), structured address, second phone, leaving reason. Saving without these fields keeps them.
- **Monthly Payroll Sheet | الحركة الشهرية** (Payroll Entry): every employee working in the month in one table (saved payroll, or the register amounts for a new month). Calculate All, Save All (draft), Post All, Export Excel. Posted rows are locked; one employee's error does not stop the others.
- **New statements** (Payroll Reports): R5_BOXES and R10_BOXES (boxes 70-90, 100-190 for (1) board / managers and (2) employees, 240-270, and tax withheld per quarter for the payments box), R6_LINES (lines 100-300 x total / not taxable / taxable, then 310, 330, 340, 350, 360), AUDIT (sum of all R6 against R5, each check OK or CHECK), MOVEMENT (month and year-to-date per employee), REGISTER and LEAVERS. Box 100 = R6 lines 100-150, box 110 = lines 160-300, 130 / 140 / 150 = not-taxable transport / representation / other; 170 = 160 - 180.
- Not included: the electronic DAS file for the MOF portal (its file specification is needed) and lump-sum workers (boxes 90 / 240 / 250 show 0).
- Database: STARTUP_SCHEMA_VERSION 4 (new employee columns and payroll_records.allowances, added on opening; existing data unchanged).
- Tests: new `test_payroll_declaration.py` (16 tests: allowances taxed / exempt / one-off / not NSSF, register NSSF flags, bad amounts refused, save + post balanced, cumulative tax, register fields kept, R6 lines, R5 boxes add up, R10 = R5 for one quarter, audit reconciles, movement YTD, registers, sheet rows and payloads, the sheet window calculates / saves / posts). 413 tests pass.
- Changed files: payroll_lines.py, payroll_official.py, desktop_payroll_sheet.py (new), database.py, payroll_reports.py, desktop.py, desktop_payroll.py, desktop_final.py, app_runtime.py, installer.iss, .github/workflows/build-windows-installer.yml, Assets/user_guide.html, README.md, test_payroll_declaration.py (new).

## Version 2.9.43 (every journal entry must balance)

- **No journal entry can be saved with total Debit different from total Credit**, whatever writes it: invoices, expenses, payments, payroll, depreciation, inventory, imports, year-end, journal vouchers. The rule sits in the database layer: every connection notes (TEMP triggers on journal_lines) each entry whose lines are added, changed or deleted, and just before the change is saved the whole entry is checked. If any entry is off by more than 0.01, nothing of the change is saved and the message names the entry, both totals and the difference (also written to the log). Changing both sides in one save is allowed; removing a whole entry is allowed.
- Entries written by older versions are not touched and never block an upgrade (the check is paused only while the program repairs old data on opening). **General Journal > "Check Balance"** lists any entry that was saved unbalanced before 2.9.43, with the difference, so it can be corrected with a Journal Voucher.
- Note: the rule covers everything the program writes. Copying files with outside tools (SQLite programs) is not covered.
- User guide updated (English and Arabic).
- Tests: new `test_balance_guard.py` (balanced saved; unbalanced and one-sided refused with nothing saved; a saved entry cannot be unbalanced by changing or deleting a line; both sides changed together allowed; whole entry deleted allowed; 0.01 rounding accepted; old unbalanced entries listed and never block an upgrade; a refusal does not block the next save). The year-end test that sets up an old one-sided closing now writes it the way an older version did. 397 tests pass.
- Changed files: database.py, server.py, client.py, desktop_reports.py, app_runtime.py, installer.iss, Assets/user_guide.html, README.md, test_balance_guard.py (new), test_final_features.py.

## Version 2.9.42 (every backup checked, update check, user guide, screens split further)

- **Every backup is checked as soon as it is made** (automatic, manual and safety copies): it is opened, SQLite's integrity check runs, and it must have the same tables as the original. Backup & Restore has a new **Checked** column (ok / FAILED / not checked for copies made before 2.9.42). A copy that fails is set aside as `.damaged` (never listed, restored or counted in the 30 automatic copies), the error is shown and logged, and an automatic backup is tried again next time. A lock, unlock or restore stops if its safety copy cannot be verified.
- **Update check:** the installed program looks once a day (in the background, never blocking) for the newest GitHub Release of nancy818181/nanzalatest. When a newer version exists a gold **"New version … available"** button appears at the top; it opens the download page and reminds to back up first. Nothing is downloaded or installed by itself. Offline or a private repository: no message, a line in the log. Another address can be written in `SaberAccounting\update_url.txt` (a GitHub release address or a JSON file `{"version": "...", "url": "..."}`), or `off`.
- **Releases:** "Run workflow" on main now also publishes a GitHub Release `vX.Y.Z` with the installer and its SHA-256 (pushes and pull requests do not). The workflow needs `contents: write` for this.
- **User guide** in English and Arabic, shipped with the program: **Help / مساعدة** button at the top. Covers start, invoices, PDF import, payroll and official forms, VAT, closing the books, backups, problems and updates.
- **Screens split further, no change in behaviour:** desktop_stage3.py (1,916 lines) -> desktop_stage3.py (import, payments), desktop_purchases.py, desktop_asset_register.py, desktop_expenses.py, desktop_stage3_common.py; desktop_brains.py (1,034) -> desktop_brains.py (journal voucher), desktop_balance_reports.py (trial balance, statement), desktop_brains_common.py.
- **Errors ignored on purpose are now logged** at debug level (20 places). Set the Windows variable `SABER_DEBUG_LOG=1` to write them to saber.log when support needs the details. A failing sign-out screen is now a warning.
- **Installer warning (free):** the installer is not code-signed (a certificate is paid). Windows SmartScreen may show "Windows protected your PC": More info > Run anyway. The SHA-256 published with each Release lets anyone check the file is the original. The user guide explains this.
- Tests: new `test_v2_9_42.py` (backup check ok / damaged / missing tables / older copies, update check newer / same / offline / once a day / address and off, installer and program versions equal, guide shipped, every desktop module in the build, moved screens still in the window). Two tests in test_pdf_ocr.py now patch the PDF reader in its new module. 390 tests pass.
- Changed files: database.py, app_runtime.py, desktop.py, desktop_settings.py, desktop_stage3.py, desktop_brains.py, client.py, company_manager.py, desktop_dimensions.py, desktop_payroll.py, desktop_v22.py, desktop_stage3_common.py, desktop_purchases.py, desktop_asset_register.py, desktop_expenses.py, desktop_brains_common.py, desktop_balance_reports.py (new), Assets/user_guide.html (new), .github/workflows/build-windows-installer.yml, installer.iss, README.md, test_pdf_ocr.py, test_v2_9_42.py (new).

## Version 2.9.41 (safety and upkeep: private data service, one copy open, error log, file rename, screens split)

- **Private data service:** the window and its built-in data service now talk on a **free port chosen by Windows** (no more fixed 8765, so another program using that port can no longer stop Saber from opening) and with a **secret key made at every start**. Any request without the key is refused (403), so no other program on the PC can read or change the data. The key is sent only to that private address, never to a shared server typed in the Server field.
- **One copy open:** starting Saber a second time brings the open window to the front instead of opening a second copy on the same data.
- **Error log:** errors are written with full details to `SaberAccounting\logs\saber.log` (5 files of 1 MB kept). A failed button or screen shows the message and writes the details to the log. New button **Settings > Backup & Restore > "Open Log Folder"**. Errors that were silently ignored are now logged (VAT in LBP not worked out for an invoice, header logo, EUR rate download).
- **Main data file renamed** from `saber_accounting_v0_7.db` to `saber_accounting.db`, once, on the first start of 2.9.41: the file is copied with SQLite's backup, checked (integrity check, same tables), the company list is updated (a copy is kept as `companies.json.before-2.9.41`), and the old file is kept as `saber_accounting_v0_7.db.before-2.9.41`. If anything fails, the old file keeps being used and the reason is in the log. The background backup service follows the new name.
- **desktop.py split by section, no change in behaviour:** `desktop_common.py` (shared helpers), `desktop_invoices.py`, `desktop_parties.py`, `desktop_payroll.py`, `desktop_reports.py`, `desktop_settings.py`. desktop.py goes from 3,600 to about 1,050 lines. All new modules are in the build.
- If the first-time admin password is cancelled, the program now closes quietly instead of crashing.
- Tests: new `test_runtime_v2_9_41.py` (free port, key refused / accepted, key never sent to other servers, one copy only, log file, safe rename incl. interrupted and damaged-file cases, screens still part of the window). 377 tests pass.
- Changed files: app_runtime.py (new), desktop_common.py, desktop_invoices.py, desktop_parties.py, desktop_payroll.py, desktop_reports.py, desktop_settings.py (new, moved from desktop.py), desktop.py, run_desktop.py, server.py, client.py, backup_service.py, database.py, desktop_v22.py, .github/workflows/build-windows-installer.yml, installer.iss, README.md, test_runtime_v2_9_41.py (new).

## Version 2.9.40 (employee sex for the official forms)

- Employee record: new field **Sex (for official forms)** (male / female) in the employee window. It marks ذكر / أنثى on MOF R3 and CNSS 2AA, 41A and the leave notice. Existing employees keep an empty value until it is chosen; saving an employee without the field does not clear it. Arabic values (ذكر / أنثى) are accepted from imports.
- Database: column `employees.sex` added on opening (STARTUP_SCHEMA_VERSION 3).
- Tests: employee sex saved, changed, kept, and marked on the form. 366 tests pass.
- Changed files: database.py, desktop.py, installer.iss, README.md, test_payroll_excel_forms.py.

## Version 2.9.39 (official payroll forms as editable Excel, filled automatically)

- **Payroll > Employees > "Official Forms (Excel)"**: select an employee, choose the form and save. Five forms, laid out like the printed ones (right-to-left, A4, one page per sheet):
  - MOF **R3** - new employee registration; MOF **R3-1** - covering letter (company only, no employee needed);
  - CNSS **2AA** - employment declaration (2 sheets: declaration and family members); CNSS **41A** - employment notice; CNSS **leave notice**.
- Filled from Settings > Company (name, MOF and NSSF numbers, address, phone, e-mail) and the employee record (name / surname, father, mother, birth date and place, nationality, ID, NSSF and MOF numbers, marital status, children, spouse working, hire / leave date, job, salary). Registration numbers go one digit per box, dates into day / month / year, and options are marked with X. Anything Saber does not hold (for example the sex, which is not in the employee record) stays empty for the user; light-yellow cells stay editable.
- New module `payroll_excel_forms.py` (added to the build as a hidden import). Tests: `test_payroll_excel_forms.py` and a window test for the dialog. 365 tests pass.
- Changed files: payroll_excel_forms.py (new), desktop.py, .github/workflows/build-windows-installer.yml, installer.iss, README.md, test_payroll_excel_forms.py (new), test_ui_v2_9_18.py.

## Version 2.9.38 (PDF invoices with unreadable labels; USD invoices showing the VAT in LBP)

- Some PDFs use fonts without a character map: the text layer holds control characters and scrambled Arabic words. Such pages are now read with OCR, and the OCR reading is preferred.
- When the amounts have no readable label (a summary box with numbers only), the reader recognises **before VAT + VAT = total with VAT exactly 11% of before VAT**; dates, percentages and long reference numbers are ignored. The Check note says "recognised without labels by the 11% VAT check - verify".
- A line such as "VAT 11% LBP 374,110,000" on a foreign-currency invoice is the VAT in LBP: it is no longer taken as the VAT amount, and the invoice currency is set to USD (EUR when the invoice mentions EUR / €), with the implied rate shown in the Check note.
- A date is never taken as the invoice number.
- Checked on a real supplier invoice: number 16, date 01-11-2024, supplier, USD, 38,000 / 4,180 / 42,180 - 7 / 7 fields. Tests added with the real text and OCR kept in `tests_data/`. 361 tests pass.
- Changed files: pdf_import.py, test_pdf_real_scans.py, tests_data/ (2 new files), installer.iss, desktop.py, README.md.

## Version 2.9.37 (scanned PDF import fixed on Windows)

- **Cause of empty rows for scanned PDFs in the installed program:** the bundled OCR language files were passed to Tesseract as `--tessdata-dir "C:\Program Files\...\tessdata"`. pytesseract splits that text in a way that breaks Windows paths (backslashes, spaces, quotes), so Tesseract found no language and every scanned PDF showed "scanned image (no text inside)". The folder is now given through `TESSDATA_PREFIX`, which needs no splitting.
- Better reading of real scans (checked on a real contractor variation order: 7 / 7 fields right):
  - **Date:** a date on a line labelled "Date" wins over dates in the item table; when the full-page OCR misses an underlined or right-aligned date / reference, the top of the page is read again (left and right halves separately).
  - **Before VAT:** when there are several section totals, the total line whose amount + VAT = Grand Total is used (e.g. "TOTAL A+B+C").
  - **Supplier:** junk read from a logo before the company name is removed.
- **Import preview:** selecting a row shows its full **Check** note under the buttons (the column is too narrow for long notes).
- Tests: `test_pdf_real_scans.py` with the real OCR text kept in `tests_data/`. 360 tests pass.
- Changed files: pdf_import.py, desktop_stage3.py, installer.iss, desktop.py, README.md, test_pdf_real_scans.py (new), tests_data/ocr_contractor_variation_order.txt (new).

## Version 2.9.36 (automatic backups and closing the books)

- **Automatic backups, on by default:** every time a company / year is opened, a backup is made in the background if the last one is older than the backup interval (24 hours by default). The installer task "Start automatic daily backups with Windows" is now ticked by default. Only the newest **30 automatic** copies are kept; manual ("Create Backup Now") and safety copies are never deleted. Backup & Restore shows the type "automatic".
- **Close the books (period lock):** Settings > Backup & Restore > "Close the books" (administrator). Enter the last date to lock (for example 31-03-2026 after filing Q1) and press Lock: no invoice, expense, payment, payroll, depreciation or journal entry dated on or before that date can be added, changed or deleted, from any screen or import. The rule is enforced by database triggers, so no path can bypass it. Unlock reopens all periods. A safety backup is made before every lock / unlock, and both are written to the audit log. Program upgrades pause the lock only while they repair old entries, then restore it.
- AI_RULES.md updated with both rules (owner decision).
- Tests: new `test_books_lock_backups.py` (lock refuses insert / change / delete of entries and lines on or before the date, nothing is half-posted, unlock works, the lock survives reopening; automatic backup once per interval, 30 kept, manual copies kept; restore brings the data back) and a window test for Lock / Unlock. 357 tests pass.
- Changed files: database.py (STARTUP_SCHEMA_VERSION 2), server.py, client.py, desktop.py, installer.iss, AI_RULES.md, README.md, test_books_lock_backups.py (new), test_ui_v2_9_18.py.

## Version 2.9.35 (Windows build: UTF-8 test output)

- On the Windows runner the console is cp1252: when a test failed with an Arabic or special character in its message, printing the GitHub annotation crashed the whole test run (UnicodeEncodeError). The annotation print is now encoding-safe and the Windows workflow runs Python in UTF-8 mode (`PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`).
- Changed files: test_000_ci_annotations.py, .github/workflows/build-windows-installer.yml, installer.iss, desktop.py (title), README.md.

## Version 2.9.34 (build fix)

- `requirements.txt` listed `pypdfium2`, `pytesseract` and `PyMuPDF` twice with different versions (left over from the 2.9.32 merge), so `pip install` stopped and both GitHub workflows failed. It now has one line per package, the same versions as the last green build (2.9.31). No code change.
- Changed files: requirements.txt, installer.iss, desktop.py (title), README.md.

## Version 2.9.33 (clear NSSF table; simpler Assets & Depreciation)

- **Payroll > Official Reports > "NSSF - Contributions table (all employees)"**: the first table now has **one line per employee** for the chosen period (Monthly, Quarterly or Yearly): number of months, salary subject, sickness base, employee 3%, employer 8%, family base and 6%, end-of-service base and 8.5%, total, allowances paid and net due, with a TOTAL line. Each month is calculated with the ceilings and rates in force that month, so a quarter or a year that crosses a change (for example 08-2025: sickness ceiling 120,000,000, minimum wage 28,000,000) is right without any manual split.
- Below it: the payment summary by branch, then **"Rules applied in this period"** (one line per group of months with the same ceilings and rates), then the monthly detail for checking, then the employee list. Column titles are shorter so the table fits on screen. Quarterly is the default period (Auto is still available).
- The CNSS forms and the annual settlement read the monthly detail (`monthly_detail` in the report) as before, so their figures do not change.
- **Purchases & Expenses > Assets & Depreciation**, tab **2. Asset Data Entry** is simplified: choose the asset account (from tab 1, it fills the rate, life and accounts), one "Asset" box (code, description, currency, purchase date, value, residual, start date, invoice), one "Depreciation" box, the buttons Save / New / Delete, and the asset register. The schedule of one asset opens with "Schedule of this asset"; **Annual Rollforward** moved to tab 3 next to the monthly posting.
- Tests: new test for the NSSF table (one line per employee = sum of its months, rules grouped by month, monthly / quarterly / yearly) and a window test for the three asset tabs; two NSSF tests now read the monthly detail / employee list by name instead of by position. 352 tests pass.
- Changed files: payroll_reports.py, cnss_forms.py, desktop_final.py, desktop_stage3.py, desktop_assets.py, desktop.py, installer.iss, README.md, test_final_features.py, test_employee_r3.py, test_ui_v2_9_18.py.

## Version 2.9.32 (the two lines of development merged - nothing lost)

- After version 2.9.23 the project split in two: the Replit line (2.9.24-2.9.27: VAT filing worksheet, invoice returns, warehouse transfer screen, statement navigation, account lookup create, asset attachments, CNSS forms, PDF form editor, party similarity, OCR review) and the ChatGPT line (2.9.24-2.9.31: payroll tax forms, faster tabs, payroll periods, lighter startup, PDF reading, assets depreciation, OCR in the installer). When 2.9.30 was uploaded the Replit line was lost from GitHub.
- 2.9.32 is a 3-way merge of both lines on their common base 2.9.23. Every feature and every test of both lines is kept; the 14 tests in `tests_pending/` are back in the root and pass. All 350 tests pass.
- PDF import: the Replit import screen (Type per row, VAT / party / cost accounts, asset rows routed to the register, attachment retry) with the newer ChatGPT PDF reader (2.9.29-2.9.30). `ai_service.py` stays fully local (no OpenAI call).
- **Payroll rules confirmed by the accountant** (where the two lines disagreed):
  - NSSF sickness & maternity ceiling from 01-08-2025: **LBP 120,000,000** (Decree 887 of 21-08-2025). The Replit line used 140,000,000.
  - Minimum wage LBP 28,000,000 from **01-08-2025**.
  - Transport and schooling allowances are **outside the NSSF base** (the Replit line included them). The reported NSSF base now matches the contributions.
  - Kept from the Replit line: NSSF family allowance amounts by period (600,000 / 330,000 / 2,250,000; from 07-2025 1,200,000 / 660,000 / 4,500,000; from 05-2026 2,100,000 / 1,155,000 / 7,875,000).
  - Tests that assumed other values were changed to these confirmed values (test_final_features.py, test_employee_r3.py).
- Payroll: the old "Official form" download buttons are replaced by **CNSS Employee Forms** (filled official PDFs); the R3 / declaration worksheets stay.
- Build: `--hidden-import` added for cnss_forms, cnss_forms_ui, party_similarity, pdf_form_editor, desktop_assets, report_export; `Assets/payroll_forms` is packaged. Temporary files removed.

## Version 2.9.31 (repository repaired - the build passes again)

- The repository mixed newer tests with older code (version 2.9.30 was uploaded on top of newer Replit work), so 14 test files failed and the Windows build stopped.
- Those 14 test files are kept unchanged in `tests_pending/` (renamed `pending_test_*.py`) and replaced in the root by skipped placeholders, so the build runs: 197 tests pass.
- To bring back the newer features (CNSS forms, invoice returns, PDF form editor, VAT filing worksheet, warehouse transfer screen, ...): restore their code from the GitHub commit history, move the tests back from `tests_pending/`, and run all tests.

## Version 2.9.30 (assets depreciation, PDF reading, OCR in the installer)

- **Purchases & Expenses > Assets & Depreciation** now has 3 tabs: **1. Asset Accounts & Depreciation %** (asset account, name, yearly %, depreciation expense account, accumulated depreciation account); **2. Asset Data Entry** (the asset form; choosing the asset account fills the accounts, the % and the useful life); **3. Monthly Depreciation Table** (by asset account: purchase date, value, old depreciation, depreciation of the month, total depreciation, net value - never below zero - and ONE depreciation entry per account and month: Dr expense / Cr accumulated; earlier months must be posted first). Print preview, Excel, PDF.
- **PDF reading**: invoice number after "TAX INVOICE", European decimals (1.234,56) and HT / TTC labels, Arabic presentation forms and visually reversed Arabic lines, amounts on the line after their label. Tested on English, French, LBP, Arabic and scanned invoices (30 / 30 fields).
- **OCR in the installer**: the build now downloads Tesseract (English, French, Arabic) and bundles it, and `pytesseract` / `pypdfium2` are in requirements.txt - scanned PDFs are read on Windows with nothing else to install.
- Note: the ZIP this version was built from did not contain the latest `desktop_stage3.py`; tests in `test_pdf_ocr.py` / `test_asset_pdf_upload.py` that need it still fail until that file is added.

## Version 2.9.29 (PDF import review corrections; 30 September 2026)

- Supports short-year dates and document references as review-only invoice-number suggestions, with a warning to verify the reference before posting.
- Selects currency from the invoice-total context instead of unrelated bank details; a stray dollar symbol is not enough to infer currency.
- Reads an unqualified pre-tax “Total” only when a VAT line and a later “Grand Total” establish that summary sequence.
- Validation: all 332 automated tests passed locally. The Windows installer build still requires a manual GitHub Actions run.
- Changed files: `pdf_import.py`, `test_pdf_ocr.py`, `test_asset_pdf_upload.py`, `installer.iss`, `desktop.py`, and this README.

## Version 2.9.28 (Lighter startup)

- Unused tabs wait until opened instead of building every report in the background. F2 lookups are bound as each page loads; cross-page access still loads required controls.
- Existing company files skip repeated schema migration, account reseeding and full ANALYZE on startup once this revision has completed successfully. Older files and restored databases without the current marker still migrate before use.
- Developers: bump Database.STARTUP_SCHEMA_VERSION whenever schema, initialization, seed accounts or migration helpers change. Explicit initialize() still performs the full initialization.
- Changed files: desktop.py, database.py, server.py, company_manager.py, installer.iss, test_performance_tuning.py, test_ui_v2_9_18.py, README.md.


## Version 2.9.27 (Local PDF reader and payroll corrections)

- PDF invoice previews use local text extraction. For scanned images, install free Tesseract OCR with English/French/Arabic language data; the app never requests an OpenAI key or sends invoices to a cloud AI service.
- Purchase PDF item lines populate the editable purchase form. Items without an existing stock code are created when the purchase is saved. Sales PDF lines populate the sales form where reliably detected; review every field.
- Payroll tax now uses a 30-day tax month for partial periods and cumulative prior saved payrolls for variable pay. The salary amount itself still uses actual calendar days.
- The schooling tax exemption is an annual remaining balance, distinct from public/private schooling grant rates. An older company database with auto-seeded payroll rules reads current schooling amounts without overwriting stored settings.
- PDF layouts vary. Review extracted date, supplier, item lines, VAT and TTC before saving. Scanned OCR requires Tesseract to be installed on the Windows computer.

## Version 2.9.26 (Payroll periods and import review)

- Payroll prorates salary and annual tax amounts by worked calendar days for an employee hired or leaving during the selected month.
- Dated schooling grant limits for public and private schools can be reviewed and edited in Payroll Settings, separately from the taxable income exemption.
- PDF and Excel invoice imports preview date, supplier/customer, items where detectable, deductible and non-deductible base, VAT and TTC. Missing VAT on a PDF must be entered or confirmed as 0 before importing; the importer no longer invents 11%.
- Text extraction from PDF remains best effort. Scanned image PDFs and ambiguous layouts require manual review before saving.

## Version 2.9.25 (Faster tabs and dashboard)

- Opening a tab builds only that tab immediately; other screens continue loading between UI events instead of forcing every remaining page to build at once.
- Dashboard totals are grouped in SQLite, avoiding loading every expense and invoice into Python just to calculate the cards. The currencies, overdue count and monthly figures keep their previous meaning.
- Changed files: `desktop.py`, `database.py`, `test_dashboard_aggregation.py`, `installer.iss`, and this README. The existing full test suite and Windows build validate the change.


## Version 2.9.24 (Payroll tax and editable employee forms)

- Salary tax: each worker keeps the personal deduction. The spouse deduction applies only if the spouse does not work; when both parents work, the child deduction is split in half. Retroactive salary uses the allowances and brackets of each original month. Existing effective dated 2024–2026 tax brackets and editable periods remain available in Tax & NSSF Settings.
- Payroll > Employees: R3, R3-1, NSSF employment and leaving worksheets open a review screen populated from saved company and employee details. Entries can be corrected for this export, then previewed or saved as PDF/Excel. The official blank forms remain available separately and the worksheets are not an electronic filing.
- Changed files: `database.py`, `desktop.py`, `test_employee_r3.py`, `installer.iss`, and this README.


## Version 2.9.27 (PDF invoice import corrections; 30 September 2026)

- Improved invoice-number and English month-name date extraction, invoice-currency selection, and total/VAT parsing for scanned and text-based PDFs.
- Retained combined English/Arabic OCR as the primary pass. A local English layout retry is used when key fields are missing or the extracted amounts do not reconcile. VAT registration numbers, “paid on behalf” charges, and LBP conversion amounts are not mistaken for invoice VAT.
- The supplied one-page scan now extracts its invoice number, date, currency, subtotal, VAT, and total. The 38-page mixed bundle keeps adjacent invoices separate and yields 20 review rows; unclear/supporting pages remain marked for manual review.
- Validation: all 329 automated tests passed.
- Changed files: `pdf_import.py`, `test_pdf_ocr.py`, `installer.iss`, `desktop.py`, and this README.

## VAT exchange rates and payable rounding review (29 September 2026)

- The quarterly schedule converts each foreign-currency document at the saved accounting rate for its document date, rounds each converted VAT amount to whole LBP, and applies a legacy ceiling to the positive balance after credits: to LBP 10,000 for quarters ending on/after 25 November 2024. These are **worksheet estimates**, not verified rules for every VAT transaction or the official payable box. Exports now explicitly flag that limitation.
- [MoF Decree 11230 of 9 May 2023](https://www.finance.gov.lb/en-us/Taxation/LRT/VAT/Documents/11230.pdf), amending Article 18 of Decree 7308, is **not** a blanket document-date accounting-rate rule: it distinguishes imports at the jointly set customs rate, foreign-currency supplies to professional (non-consumer) customers at the then-Sayrafa rate, telecommunications invoices and airport/port fees; where VAT actually collected exceeds the amount under those rules, the collected amount is declarable. The decree also conditions input deduction/refund on further rules. It says these arrangements apply pending a unified exchange rate. The Ministry's [VAT legislation index](https://www.finance.gov.lb/ar-lb/Taxation/LRT/VAT) lists this decree, but does not establish that the former Sayrafa rate is usable in 2026. Confirm the rate and tax-point date for each kind of supply/import and any later changes with the VAT Directorate before filing; the software does not automatically classify counterparties or select the statutory rates.
- The previously cited “MoF decision 1195” and effective date 25 November 2024 could **not** be confirmed in the Ministry's VAT legislation index as authority to round VAT payable upward to LBP 10,000. Do not rely on that ceiling as an official filing or payment rule without the current Directorate instructions. No automatic calculation was changed without verified replacement instructions; tests pin the existing dates, currency conversions, credit order and rounding boundaries so a later confirmed rule can be changed safely.

## Version 2.9.26 (Security protections, asset rollforward, and OCR review checks)

- Restricted company database paths to the app's data area, limited API request size, and kept raw database backup access unavailable to viewer accounts. Accountant backup export remains available.
- Added an annual fixed-asset rollforward by currency with opening cost, additions, posted depreciation, closing values, and unposted scheduled depreciation. Preview and export to Excel or PDF are available from Fixed Assets.
- OCR-extracted invoice amounts remain review-only. The app now warns when OCR-read subtotal, VAT, and total do not reconcile; an image-only PDF using a clearly labeled VAT amount was also checked through the full reader.
- Added Windows DPI awareness and display-scaled startup sizing. Verification on physical 125% and 150% Windows displays remains pending.
- Validation: 192 automated tests passed. The Windows installer workflow is configured to bundle English/Arabic Tesseract data; running that installer build remains pending.
- Changed files: `company_manager.py`, `server.py`, `client.py`, `desktop.py`, `desktop_stage3.py`, `fixed_assets.py`, `pdf_import.py`, their focused tests, `installer.iss`, and this README.

## VAT worksheet verification (29 September 2026)

- The Filing Worksheet now groups taxpayer/period details, revenue/output VAT, purchases/input VAT, partial-deduction review, and balance/credit in the broad order of the Ministry's published Q1-2 and Q11-2 specimens. This is a **specimen-inspired preparation layout**, not the forms themselves. The public specimens are marked 2010; the partial-deduction review does not reproduce Q11-2's purchase/expense/asset-use boxes. No A-F worksheet reference has been mapped to a current issued form box, and the worksheet cannot be submitted as a declaration. Obtain the current issued forms from the VAT Directorate and reconcile the required schedules manually.
- The Ministry of Finance (MoF) Forms page lists the periodic declaration (form Q1-2) and the partial-deduction supplement (Q11-2). It says the adopted forms are effective from 1 January 2012, and that downloadable copies must not be used for filing: filers must obtain the issued forms from the VAT Directorate. The public Q1-2 specimen is marked 2010. Neither source certifies the worksheet's A-F references as current Ministry box numbers, so they remain internal references; the worksheet is not a populated official form or an electronic filing.
- The MoF's VAT guidance supports the calculation structure: output VAT less deductible input VAT; excess deductible VAT carries to later periods or may be refunded under the applicable rules; partial deduction is based on turnover that grants deduction rights divided by all turnover. The guidance describes semiannual refunds after Q2 or annual refunds after year-end; quarterly requests require qualifying exporter status and are limited by the export proportion. The app does not store enough information to validate refund eligibility and now flags every refund request for manual review. The worksheet's mixed-use adjustment follows the pro-rata principle. These are conceptual cross-checks, not confirmation that its row layout matches the issued declaration.
- The Ministry's 2026 Citizen Budget says the periodic VAT declaration deadline is one month instead of 20 days (Article 51); the VAT website's older Payable VAT page still says 20 days. The software's 2026 due-date calculation follows the 2026 budget change.
- Source pages checked: [MoF VAT forms](https://www.finance.gov.lb/en-us/Taxation/Companies/VAT/Pages/Forms.aspx), [MoF declaration guidance](https://www.finance.gov.lb/en-us/Taxation/Companies/VAT/Pages/Declaration.aspx), [MoF deduction/refund guidance](https://www.finance.gov.lb/en-us/Taxation/Companies/VAT/Pages/Refunding-VAT.aspx), [MoF payable VAT page](https://www.finance.gov.lb/en-us/Taxation/Companies/VAT/Pages/Payable-VAT.aspx), and [MoF Citizen Budget 2026](https://www.finance.gov.lb/en-us/Finance/BI/ABDP/Annual%20Budget%20Documents%20and%20Process/Citizen%20Budget%202026-Apr26-En-final.pdf).
- Rate-source warning: the MoF Tax Rate page still says 10%, while the [Lebanese University Legal Information Center's amendment to Article 25 of VAT Law 379](http://77.42.251.205/PrintArticle.aspx?LawArticleID=0&LawID=273985&Law_Tree_Section_ID=286534) states 11%. The worksheet uses the 11% rate, but the stale MoF rate page is not treated as confirmation of the current rate. Check the applicable law and any later amendment before filing.

## Version 2.9.25 (Offline purchase PDF OCR and complete review)

- Scanned purchase PDFs now use local English/Arabic Tesseract OCR when available. OCR suggestions are still review-only; no invoice is posted automatically and the document is not sent to an external service. The Windows installer build bundles the OCR engine and language data.
- Text-based PDF extraction remains the first choice. If OCR components are missing or a scan is unreadable, the purchase can still be attached and entered manually. The optional AI reader remains separate and consent-based.
- Includes the quarterly VAT filing worksheet, purchase line-item suggestions and VAT fixes described in 2.9.24, plus the existing payroll/NSSF reporting and responsive navigation.
- Changed files: `pdf_import.py`, `requirements.txt`, `.github/workflows/build-windows-installer.yml`, `desktop.py`, `installer.iss`, `test_pdf_ocr.py`, and this README.

## Version 2.9.24 (Quarterly VAT filing worksheet and purchase PDF review)

- Quarterly VAT now has a separate **Filing Worksheet** preview and PDF/Excel export. It fills the employer details, selected quarter, taxable bases, output VAT, input VAT, partial deduction, credit brought forward, payable and credit carried forward from posted records. The existing Supporting Documents and Manual Adjustments remain available for reconciliation. A filtered or Review-inclusive report cannot be exported as a filing worksheet.
- The A-F references are internal worksheet references, **not certified Ministry of Finance box numbers**. This is a preparation worksheet, not a populated official government PDF or electronic filing; compare it with the current official declaration and confirm employer details, period, deduction ratio, exchange rates and excluded documents before submission.
- Purchase PDF reading suggests common item rows in the reviewable purchase screen; unmatched items are found or created on Save and stock receipts remain linked to the invoice. The optional AI reader can suggest items from scanned PDFs after the user approves sending the first page to OpenAI. PDF values and item rows require review before posting; the basic text parser alone does not OCR scanned PDFs.
- Exempt-use purchase input VAT now remains visible on the original supplier invoice and quarterly return, while a separate balanced journal entry transfers it from input VAT to non-deductible cost. Mixed-use VAT continues to use the existing VAT return's provisional/final deduction ratio; do not apply a second item-level ratio to the same tax.
- Changed files: `vat_return.py`, `desktop_final.py`, `desktop_stage3.py`, `database.py`, `pdf_import.py`, `ai_service.py`, `test_vat_filing_worksheet.py`, `desktop.py`, `installer.iss`, and this README.

## Version 2.9.23 (Payroll: family allocation shown at once and editable)

- Payroll > Payroll Entry: the **Family Allocation** field now shows the automatic amount as soon as the employee (or the period date) is chosen, and after Calculate: spouse and children allowances of the period (Tax & NSSF Settings), within the maximum. Type in the field to use another amount for this payroll; Calculate and Save then use your amount (with a compliance note). Choosing another employee shows the automatic amount again.
- Includes everything from 2.9.19 - 2.9.22. Changed files: `desktop.py`, `test_ui_v2_9_18.py`, `installer.iss` and this README. Validation: 178 automated tests passed.

## Version 2.9.22 (Payroll: transport filled from the transport days)

- Payroll > Payroll Entry: typing the **Transport Days** fills **Transport** at once = days x the daily transport of the payroll period (Tax & NSSF Settings > Transport Exempt / Day, LBP 450,000 under the Lebanese rules), converted to the employee's currency at the period's rate for USD / other-currency employees. The amount can still be changed by hand afterwards.
- Includes everything from 2.9.19 - 2.9.21. Changed files: `desktop.py`, `test_ui_v2_9_18.py`, `installer.iss` and this README. Validation: 177 automated tests passed.

## Version 2.9.21 (Fix: Windows build test failure; switching company / year)

- Fixed the Windows build failure in "Run all tests" (`test_program_opens_on_the_dashboard_first_and_builds_the_rest`). On a slower PC the previous company's pages had finished building, and their (destroyed) widgets were still remembered, so after Switch Company / Year the program could think a page was already built. Every page widget of the previous screen is now forgotten when the screen is rebuilt, so the pages are rebuilt for the newly opened company / year. The test now reproduces the slower-PC case.
- Changed files: `desktop.py`, `test_ui_v2_9_18.py`, `installer.iss` and this README. Validation: 176 automated tests passed.

## Version 2.9.20 (Company data files named after the company, like the backups)

- Each company's data is now kept in a folder with the company's name, one file per fiscal year, named like its backups:
  - Data: `SaberAccounting\companies\<Company Name>\<Company Name>_<year>.db` (for example `companies\My Company SAL\My Company SAL_2025.db`).
  - Backups (unchanged): `SaberAccounting\backups\<Company Name>\<year>\<Company Name>_<year>_<date>.db`.
  - Deleted fiscal years: `companies\<Company Name>\deleted_years\`.
- Existing files are moved automatically the first time 2.9.20 starts. Each file is copied with SQLite's backup, checked (integrity check and the number of rows of every table), the company list is updated, and only then the old file is removed. A file that is in use by another program is left where it is, keeps working, and is moved on a later start. A company year that was stored inside the main file `saber_accounting_v0_7.db` is copied out to its company folder; the main file stays (it holds the users and passwords).
- Renaming a company (Manage Selected > Company Name) renames its data files and its backups folder to the new name.
- New companies and new fiscal years (Create Separate Year, year closing) are created directly in the company-named folder. Two companies with the same name get their company id added to the folder name.
- Tests changed on purpose because the file locations changed: `test_final_features.py` (deleted-years folder) and `test_regressions.py` (company data is read from the company file, not the main file).
- Validation: 176 automated tests passed (173 previous + 3 new in `test_company_named_files.py`: existing files moved with their data, new company / year named after the company, rename moves the files and the backups folder).
- Changed files: `company_manager.py`, `server.py`, `desktop.py` (version), `test_company_named_files.py` (new), `test_final_features.py`, `test_regressions.py`, `test_ui_v2_9_18.py` (frees window objects on the main thread), `installer.iss` and this README.

## Version 2.9.19 (Faster opening, DOE in LBP or USD books, payroll periods / director remuneration / family allocation, date dashes, item cost link)

- **Faster opening.** The program now shows the Dashboard as soon as a company is opened (measured about 10x faster to the first screen) and builds the other pages in the background right after; a page you click first is built at once. The Excel / PDF libraries are loaded the first time you export instead of when the program starts (the program's own code now loads about 4x faster).
- **Automatic DOE: choose the books and the currency.** "Revalue in" LBP (as before: foreign-currency class 4/5 balances revalued in LBP) or **USD** (LBP and other non-USD class 4/5 balances revalued in USD). "Currency" = All currencies or one currency. One DOE voucher is posted per currency. A USD DOE changes only the USD equivalent: the account's own balance and the LBP books do not move. From this version an LBP DOE also changes only the LBP books (earlier LBP DOE vouchers also moved the USD equivalent by the LBP difference converted at the day's rate; the USD DOE corrects that). Rates: LBP books "1 USD / 1 EUR = x LBP"; USD books "1 USD = x LBP" for LBP balances and "1 EUR = x USD" for others.
- **Payroll > Tax & NSSF Settings: periods can be edited freely.** Save Periods now saves the whole list together, so Date From / Date To can be changed and a period split (for example 01-05-2025 - 30-06-2025 with its own ceiling). The list is checked for overlaps and gaps first; if something is wrong nothing is saved and the message says which days. Each period keeps its tax brackets, allowances and accounts.
- **Payroll: Director Remuneration** (Payroll Entry): paid with the payroll, part of gross and net pay, **not subject to salary tax and not to NSSF**, posted to its own account (default 6316; set in Standard Posting Accounts for employees and managers). The payroll shows a compliance note.
- **Payroll: Family Allocation.** Payroll Entry has a Family Allocation field (empty = calculated automatically from the NSSF family allowance settings, as before; a number = that amount for this payroll). Standard Posting Accounts has a Family Allocation account (empty = offset on the NSSF account, as before).
- **Dates typed as digits get their dashes in every date field** (31122025 becomes 31-12-2025), including the payroll period cells, Journal Voucher date cells, the DOE date and the company VAT registration date.
- **Items: the cost price is a link.** Click it to open the item's Stock Card, which shows every purchase / sale and the running average cost.
- Validation: 173 automated tests passed (163 previous + new: payroll periods split / edit / overlap and gap refused, director remuneration not taxed and posted to 6316, manual family allocation on its own account, USD DOE moving only the USD equivalent, and on the program window: USD-books DOE for one selected currency, date dashes, the item cost link, dashboard-first opening).
- Changed files: `desktop.py`, `desktop_brains.py`, `desktop_final.py`, `desktop_inventory.py`, `database.py`, `server.py`, `client.py`, `chart_extra.py`, `report_export.py`, `importer.py`, `test_assets_doe.py`, `test_ui_v2_9_18.py`, `test_payroll_periods_director.py` (new), `installer.iss` and this README.

## Version 2.9.18 (Automatic DOE for all currencies, legal documents "Applies" + dates, fixes, faster program, wheel scrolling, right-click search)

- **Automatic DOE for all currencies at once.** Journal Voucher > Automatic DOE now loads every foreign-currency class 4/5 balance (USD, EUR, SAR, ...) in one screen, with one DOE date rate per currency (the suggested rate is filled in). Post DOE vouchers creates **one DOE voucher per currency** (one for USD, one for EUR, ...) holding all that currency's accounts, instead of one voucher per account. Each voucher credits the total gains to 775100000 and debits the total losses to 675100000 on separate lines; each account line says its foreign balance and carrying LBP. The DOE rule itself is unchanged (revaluation in LBP, gains credit 7751, losses debit 6751); a DOE voucher may now hold several class 4/5 accounts. The Journal Voucher has no "Calculate DOE" button (removed in 2.9.17).
- **Customers / Suppliers > Legal Documents.** Each document has an **Applies** tick and Issue / Expiry dates that can be **saved without a file** (attach the scan later with Attach / Replace File). Click a saved document to change its tick, dates or notes and press Save. The list shows a status (Valid, Expires in N days, EXPIRED, Not applicable). Documents whose tick is removed no longer raise expiry alerts. Dates are checked (DD-MM-YYYY, expiry not before issue). Existing documents keep their files and count as applying.
- **Fixed: Items > Stock Card crashed** and **Inventory Reports > Inventory Analysis (3D) could not run.** The code that builds the 3D options (rows / columns / measure) had been pasted into the Stock Card button instead of the Inventory Reports page, so Stock Card raised an error and the 3D report had no options. The options are back on the Inventory Reports page (shown only for the 3D report) and Stock Card opens the item's card again.
- **Fixed: page scrolling with the mouse wheel.** One wheel handler now scrolls whatever is under the pointer: tables and lists scroll themselves, everywhere else the page scrolls (Shift + wheel scrolls sideways). The old handler of some long forms switched the wheel off for the whole program when the mouse left them. Turning the wheel over a drop-down list no longer changes its value by accident; the page scrolls instead.
- **New: right-click search in any field.** Right-click in an account field and the account search opens (same as F2); in a customer / supplier field the parties search; on the account cell of the Journal Voucher, or an item cell, the matching search. Any other field shows a menu: Search accounts, Search customers / suppliers, Search items (the choice is written into the field), plus Cut, Copy, Paste and Select all. Listing tables keep their Search / Clear search menu.
- **Faster.** Measured on a test company (300 invoices): posting invoices is about 7x faster and opening a company about 40% faster; the gain is larger on Windows. How:
  - The program keeps one connection to its data service open and reuses it (HTTP keep-alive, no Nagle delay) instead of opening a new connection for every request.
  - The data service keeps each company file open instead of opening, configuring and closing it on every request (the file is released before a restore or a deleted year is moved).
  - Lists the screens request repeatedly (chart of accounts ~40 times when a company opens, branches, parties, currencies, rates...) are kept for 10 seconds and dropped at once after any change is saved.
  - A request that fails inside the data service now returns its error message instead of a "cannot reach the data service" message.
- Housekeeping: README note on DOE corrected (see 2.9.17); duplicate 2.9.5 heading clarified; removed `temp.txt` files and the `workflows - Shortcut.lnk` file; removed six unused imports; the background backup program must now build successfully (it was allowed to fail silently, leaving the "daily backups" option without its program); the Linux test workflow installs the same pinned versions as `requirements.txt`; installer paths use the real `Assets` folder name. The README has no sections for 2.9.12 and 2.9.13 (they were not recorded in earlier versions).
- No accounting rule, feature or test was removed or changed.
- Validation: 163 automated tests passed (151 previous tests + new tests in `test_ui_v2_9_18.py` on the real program window: Stock Card, 3D report options, wheel scrolling, right-click on account and plain fields, Automatic DOE posting one voucher per currency, a legal document saved with dates and no file; `test_legal_documents_applies.py`; and a grouped-DOE test in `test_assets_doe.py`).
- Changed files: `desktop.py`, `desktop_inventory.py`, `desktop_brains.py`, `desktop_final.py`, `client.py`, `server.py`, `database.py`, `company_manager.py`, `ai_service.py`, `bank_rec.py`, `inventory.py`, `year_end.py`, `test_assets_doe.py`, `test_ui_v2_9_18.py` (new), `test_legal_documents_applies.py` (new), `installer.iss`, `.github/workflows/build-windows-installer.yml`, `.github/workflows/tests.yml` and this README. Removed: `Assets/fonts/temp.txt`, `.github/workflows/temp.txt`, `workflows - Shortcut.lnk`.

## Version 2.9.17 (Remove Calculate DOE button + Linux CI test job)

- Removed the "Calculate DOE" button from the Journal Voucher screen and its underlying `prepare_doe` handler, per user request (the manual button was redundant). Exchange differences are still handled by the **Automatic DOE** screen (Journal Voucher > Automatic DOE): load the foreign class 4/5 balances for the DOE date (the suggested rate is filled in), preview, then post the selected lines. Gains credit `775100000` and losses debit `675100000`. Nothing is posted without the accountant pressing "Post selected DOE". *(Wording corrected in 2.9.18: the first version of this note said DOE was posted automatically, which is not the case.)*
- Added a dedicated Linux CI workflow (`.github/workflows/tests.yml`) that runs the full unit-test suite on `ubuntu-latest` on every push and pull request to `main`. It uses the system Python + system Tk (not `actions/setup-python`) to avoid a tkinter/Tk version mismatch, installs the runtime requirements, adds a lowercase `assets` symlink for the case-sensitive Linux filesystem, and runs the tests headlessly under `xvfb`. This complements the existing Windows build workflow, which already ran the tests on Windows.
- Removed the now-unused `simpledialog` import from `desktop_brains.py`.
- Changed files: `desktop_brains.py`, `desktop.py`, `installer.iss`, `.github/workflows/tests.yml` and this README.

## Version 2.9.16 (Fix Windows installer build)

- Fixed the Windows installer build failure `Source file "dist\SaberAccounting.exe" does not exist`. The application is now built with PyInstaller `--onedir`, which produces `dist\SaberAccounting\SaberAccounting.exe` inside a folder (not a single `dist\SaberAccounting.exe`). `installer.iss` was still packaging the old single-file path, so Inno Setup could not find the program. The `[Files]` section now packages the whole `dist\SaberAccounting\` folder (recurses subdirectories); `SaberAccounting.exe` still installs to `{app}\SaberAccounting.exe`, so all shortcuts, the uninstaller icon and the post-install "Open" action keep working.
- Added a "Verify the application was built" CI step so that if PyInstaller ever fails to produce the executable, the build now fails immediately with a clear message at the build step instead of a confusing error later in the Inno Setup step.
- No application feature or test was changed; this is a packaging/CI fix only.
- Changed files: `installer.iss`, `.github/workflows/build-windows-installer.yml`, `desktop.py` and this README.

## Version 2.9.15 (Speed / performance tuning)

- Database performance indexes added on the columns used for filtering and joins (invoices by party/kind/date/branch, invoice items, journal entries by source/date and journal lines by entry/account/party, stock movements, payments and allocations, expenses, payroll records, audit log, budgets and more). Previously only one index existed, so these lookups did full-table scans that got slow as data grew; now they use indexes. This applies automatically to every company database on next start.
- SQLite is now opened in WAL journal mode with `synchronous=NORMAL`, an in-memory temp store and a larger page cache. Reads stay fast while writing and disk churn is reduced. Foreign-key enforcement is unchanged.
- `ANALYZE` runs at the end of setup so the query planner actually uses the new indexes.
- The shared table search box is now debounced (~180 ms): typing a filter rebuilds the list once after you stop typing instead of on every keystroke, so large tables no longer feel laggy while searching. The filtering result is identical.
- Validation: 151 automated tests passed (147 previous + 4 new that guard the WAL journal mode, the required indexes, that an index is actually chosen for an invoice lookup, and that foreign keys stay enforced). No existing feature or test was removed.
- Changed files: `database.py`, `desktop.py`, `test_performance_tuning.py`, `installer.iss` and this README.

## Version 2.9.14 (Right-click search on every table)

- Every listing table now opens a right-click menu (Windows/Linux right button, macOS trackpad two-finger) with "Search…" and "Clear search". "Search…" jumps to and selects the table's search box so you can type immediately; "Clear search" empties it and shows all rows again. This is an additional way to reach the search bar that was already on top of every table (Ctrl+F still works) — no existing behaviour was changed.
- Validation: 147 automated tests passed (143 previous + 4 new that guard the right-click context menu, its Search / Clear search entries, and both right-click bindings). No existing feature or test was removed.
- Changed files: `desktop.py`, `test_table_context_menu.py`, `installer.iss` and this README.

## Version 2.9.11 (Payroll fairness rules and per-year projections)

- Family income-tax deduction is now split in half for a married employee whose spouse also works, so the spouse and children deduction is shared between the two working spouses instead of being claimed twice. A compliance note reminds you to confirm the split with your accountant. When the spouse does not work the full deduction is kept as before.
- The NSSF family allowance paid with the salary is shown explicitly on the individual salary statement (R6): a dedicated "NSSF Family Allowance" column reports the allowance already paid on behalf of the NSSF for each month, alongside gross, tax, NSSF and net.
- The employer end-of-service contribution (8.5%) is automatically exempted for foreign nationals (not covered by the end-of-service scheme) and for employees over 64 (past the end-of-service retirement age), based on the nationality and date of birth in the employee file. A compliance note states the reason; confirm eligibility with your accountant. Lebanese employees under 64 still owe the contribution.
- R3 / R3-1 registration and the NSSF employment (إعلام استخدام أجير) and termination (إعلام ترك أجير) declaration worksheets are auto-filled from the company (employer name, address, phone, MOF/VAT and NSSF employer numbers) and the selected employee file. Missing employer or employee fields are flagged. The official blank forms remain downloadable.
- The 5-Year Projection for both Cash Flow and Budget accepts a per-year growth override (for example `2027=10, 2028=5`) in addition to the single flat growth rate. Each future year can grow at its own rate; a saved budget for a year still wins over any growth assumption.
- Validation: 143 automated tests passed (138 previous + 5 new for the family-deduction split, end-of-service exemption, NSSF family allowance on the statement, and per-year projection growth). No existing feature or test was removed.
- Changed files: `database.py`, `payroll_reports.py`, `financial_projection.py`, `desktop.py`, `desktop_dimensions.py`, `test_final_features.py`, `test_financial_projection.py`, `installer.iss` and this README.

## Version 2.9.10 (Combined payroll and financial reporting update)

- Integrates PR #4 payroll/NSSF, journal-entry, visibility and login updates with PR #5 financial reporting. Version markers are unified; both change histories are retained.
- Business Reports > Financial Statements + Audit + Notes: enter one or two years (for example `2025` or `2024,2025`). Each year comes from the selected company's own database, latest year first. Annual calendar-year periods use posted entries, opening balances and exclude closing P&L transfers.
- Includes financial position, profit/loss and OCI, changes in equity by component, cash flow reconciliation, account schedules, editable notes and an editable audit-report draft. Print, PDF and Excel use the same selected-year pack; exports refresh to prevent stale results.
- Edit Notes / Audit / Mapping saves disclosures and account-prefix classification overrides per company/year, with an audit log. Presentation settings may be edited for closed years without unlocking or changing their books; viewers cannot save them.
- This is a preparation/review pack, not a compliance certification or issued audit opinion. Single-year or nonconsecutive comparisons are labelled. OCI and classified cash-flow totals must be supplied and reconciled; blanks remain REVIEW REQUIRED. Book equivalents do not automatically implement IAS 21 translation or IAS 29 restatement. Direct equity movements need disclosure of owner transactions, OCI and restatements. Review all classifications, disclosures and applicable standards, including IFRS 18 for periods from 2027.
- Validation: 130 automated tests passed, including separate-year API routing, closed-year draft permissions, closing-entry exclusion, cash reconciliation, saved disclosures, and PDF/Excel exports. PDF pages were visually reviewed.
- Changed files: `financial_statements.py`, `desktop_v22.py`, `server.py`, `client.py`, `report_export.py`, `test_financial_statements.py`, `installer.iss`, the Windows build workflow and this README.
- References: [IAS 1](https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/), [IAS 7](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/), [ISA 700](https://www.iaasb.org/publications/international-standard-auditing-isa-700-revised-forming-opinion-and-reporting-financial-statements).

## Version 2.9.9 (NSSF reporting and employee forms)

- NSSF contributions report defaults to Auto by employee count: fewer than ten employees in the selected month gives the full quarter; ten or more gives that month. The report shows the roster count and chosen declaration period. Monthly, quarterly and yearly remain selectable for review.
- Payroll > Employees offers blank official CNSS forms for registering a new employee, hiring an employee already registered with CNSS, and notifying CNSS that an employee left. R3 and R3-1 remain available.
- The annual NSSF settlement automatically shows monthly posted payroll contributions and wage bases alongside the filed wage bases and payments entered by the accountant. Unknown filed amounts remain blank instead of being guessed.
- Tax & NSSF Settings already provides editable, dated Family Ceiling and Sickness Ceiling. Default Family Ceiling is LBP 18,000,000 through April 2026 and LBP 28,000,000 from May 2026, with the effective May family allowances. Payroll tax and retroactive pay use the saved settings for their periods.

## Version 2.9.8 (Employee dates in Payroll)

- Payroll > Employees shows Starting Date and Leaving Date in the employee list, using the dates saved in each employee file. Double-click an employee or use Edit Selected to change them.

## Version 2.9.7 (Independent Department and Project controls)

- Departments and Projects now each have their own visibility checkbox in their respective Security data sheets. Either field can be hidden independently in entry forms, report filters, and Journal Voucher without deleting saved values. The application title matches the installer version.

## Version 2.9.6 (Department and Project visibility)

- The Departments and Projects data sheets under Security each have a Show Department / Project checkbox for entry forms, budget and report filters, and the Journal Voucher sheet.
- Hiding fields only changes the display; saved department and project data remains intact. Report filters return to All when hidden so an unseen filter cannot narrow the report.

## Version 2.9.5 (Journal entry and shared-server login protection)

- In Journal Voucher, the first letter selects a currency in the voucher header and the line currency cell. The line detail copies into the next line; editing the next line leaves the first unchanged.
- New Account in Journal Voucher creates an account immediately and places it on an available line without saving the voucher. Accounts created on the Accounts page are immediately recognized by an already-open Journal Voucher.
- Failed logins are audited without passwords or tokens. Five failures per username or 30 per client IP within 15 minutes trigger a 15-minute lockout; the server returns HTTP 429 while blocked.
- The shared server accepts a trusted TLS certificate and key. Plaintext is limited to localhost unless `--allow-insecure-lan` is deliberately specified for a trusted VPN/LAN.
## Version 2.9.5 - second update (5-Year Projection for Budget and Cash Flow)

- Budget page: a "5-Year Projection" section next to the existing quarterly/6-month/yearly forecast. Enter a target date up to 5 years after the "Actual report year" and, optionally, a yearly growth % applied to that year's posted income/expense actuals. For any future year that already has a saved budget, the saved budget is used instead of the growth %. The final (partial) year is prorated to the target date. Shown as net income/expense by year and by account, exportable like the existing forecast.
- Cash Flow Outlook page: the same "5-Year Projection" idea for cash inflow/outflow, projected per currency from the "Report year" actuals and a yearly growth %; the final year is prorated to the target date the same way.
- Both build on a new `financial_projection.long_term_projection()` helper (unit tested), capped at 5 years ahead of the base year.

## Version 2.9.4 (Equal height navigation rows)

- Navigation tabs in every row share the same height, including rows with labels that wrap onto two lines.

## Version 2.9.3 (Navigation and invoice controls alignment)

- The navigation tabs have visible spacing, stretch across the application window and automatically wrap into more rows as the window gets narrower; horizontal scrolling remains available on exceptionally narrow windows.
- On Uploaded Data, the Branch selector and both rows of invoice action buttons begin at the left edge below the table.

## Version 2.9.2 (Payroll registration worksheet)

- Employee files now retain nationality, parents' names, date of birth and place of birth. Existing company files add these empty fields automatically without changing saved payroll.
- Employees > R3 Registration Worksheet can preview, export PDF or export Excel with the saved employee details and highlights missing information. This worksheet helps prepare the Ministry of Finance's R3 new-employee registration; it is not the official form or an electronic submission. Complete the official form and its supporting documents separately.
- Employees has download buttons for the original Ministry of Finance R3 and R3-1 PDF forms. The original blank forms are downloaded from the Ministry website when requested.
- NSSF contributions report lists the employees in the selected period, counts both registered employees and employees with payroll, and shows missing NSSF numbers. The report's Employee List / Edit button opens the editable employee list.
- Payroll > Payroll Reports & Worksheets > SETTLEMENT builds an annual NSSF reconciliation from posted payroll. Use Filed NSSF Wages to enter the wages already declared for each month and actual payments; unknown values stay blank and the settlement remains incomplete. The difference uses the effective rates saved for each month. The entries have an audit log and do not post a journal voucher automatically.
- The original blank CNSS contributions, annual settlement and annual employee declaration PDFs can be downloaded from the CNSS links. Those public templates show a preprinted 9% sickness rate; compare the template with the period's saved rates before submission. The application's reconciliation is a review worksheet, not an official CNSS filing.
- The Employee File dialog scrolls on smaller screens, with Save always visible.
- Main navigation grows to fit both rows of tabs; outer page scrollbars appear only when the content exceeds the available space.

## Version 2.9.1

- Main window opens within the available screen dimensions and its minimum size respects smaller displays.
- Every main page now has vertical and horizontal scrollbars so forms, tables, and action buttons remain reachable on smaller screens or with larger Windows display scaling. The two-row navigation can scroll horizontally as well.
- General Journal action buttons and totals now appear above the table, so they are immediately visible instead of being squeezed against the bottom of the window.

## Version 2.9.0

- **Bank Reconciliation** (Payment & Receipt > Bank Reconciliation): import the bank statement (Excel or CSV: Date, Description, Reference, Debit / Credit or Amount) for a bank account (511 / 512 / 519 / 53), Auto Match (same amount, dates within 5 days), Match / Unmatch by hand, post statement-only items (bank charges 6739, interest...) as a voucher that is matched at once, and the reconciliation: book balance, deposits not yet at the bank, payments not yet cleared, statement items not booked, expected bank balance and the difference with the statement balance. Report in PDF / Excel / print.
- **Dashboard charts** for the fiscal year (USD or LBP): sales vs purchases and expenses by month, receivables by age, top 5 clients, cash and bank balances.
- **AI_RULES.md**: the rules for anyone (people, ChatGPT, Claude) who changes the program - start from the latest version, never remove features or tests, run the tests, deliver the whole project, accounting rules.
- VAT declaration box numbers: kept as the section layout (A / B / C / E / F) until the official Ministry of Finance form is provided.

## Version 2.8.3 (review)

- New currencies (for example SAR) now work everywhere: payroll converts LBP -> USD -> the new currency when there is no direct rate, and VAT adjustments accept any currency set up under Exchange Rates.
- Layout at 1366 x 768: "Due days from invoice" moved so its box is visible on Customers / Suppliers; Sales Invoice "Amount Paid", "Branch" and "VAT Treatment" moved to their own row so nothing is cut off.

## Version 2.8.2

- Purchase Invoice actions sit beside the shorter entry form; the item table has more height and a wider description column.
- In Inventory Reports, Stock Card has Item From / Item To selectors and the existing date From / To fields. The Ageing buckets entry box is removed; Stock Ageing uses its standard ageing buckets.
- The main navigation takes less space above the working area.
- Customer / Supplier Ageing lists invoice due dates and overdue days. Business Reports has Today and +30 days shortcuts and an expected collection/payment summary due by the chosen as-of date.
- Inventory Analysis (3D) compares item/category/supplier by warehouse or month, using quantity or cost value. Inventory Health lists stock issues needing review, including reorder levels, missing supplier or unit cost, and no recent issue.
- The Customers / Suppliers page links directly to Customer / Supplier Ageing and Client Items: Qty & Value; the latter lists each client's purchased items, quantity, sales before VAT, VAT, and TTC.

## Version 2.8.1

- Customer and supplier files include **Due days from invoice**. New invoices automatically use invoice date plus the saved term when Due Date is blank; an explicit Due Date takes precedence. Existing invoices keep their saved due dates.
- Purchase Invoice header is shorter so more item rows fit. Cost on Purchase uses predefined expense accounts, with an Edit Cost Accounts dialog for a particular posting.
- Inventory Reports adds Stock Turnover, Stock by Supplier, and Physical Count Variances. Stock Ageing can filter by item; Stock Card continues to use the selected item and From/To dates. Physical Inventory can add an item to its count sheet.
- Each manually entered exchange rate is saved separately. The daily rate used in reports is the arithmetic mean of entered rates for that date and currency pair. Automatic reference rates no longer overwrite a manual daily average.

Saber Accounting is a Windows desktop accounting application with a central shared database for three users. This first version includes:

- English, Arabic, and French interface
- Automatic USD, EUR, LBP, and AED detection from currency and amount cells
- Missing currency defaults to USD; conflicting or unsupported currencies are flagged for review
- Currency filter for the dashboard, invoices, trial balance, and exported reports
- Lebanese VAT at 11%
- Purchase and sales invoice import from Excel
- Manual purchase and sales invoice entry with multiple items
- Invoice deletion retains the invoice number and marks it DELETED; it removes the journal and stock effect. Linked allocations and active dependent invoices must be resolved first.
- Purchases and sales show gross total, discount, total after discount before VAT, VAT, and final total. Purchase discounts reduce the posted invoice amount and stock line costs.
- Journal Voucher Find searches each line's detail; each line detail can be edited in its own table column.
- Bank commissions on receipts and payments post to the nine-digit account 673900000.
- Stock Card accepts an item and From Date / To Date and includes the range in the report heading.
- Stock Ageing groups the on-hand value by receipt date in configurable ageing buckets, as of the selected To Date.
- Trial Balance can show EUR and AED equivalents as either reporting column. Add a three-letter currency under Security / Backup / Rates → Exchange Rates, then enter its exchange rate before cross-currency reporting.
- The dashboard uses compact currency summaries; purchase invoice entry keeps the items and totals on one page, while landed costs have a separate tab.
- Optional AI buttons suggest expense accounts and preview page 1 of a PDF invoice. The existing local account suggestion and PDF reader work without AI. For online assistance enter an OpenAI API key when prompted (kept in memory for that session), or set `SABER_AI_API_KEY` before starting the app. Each request needs confirmation, sends the description or first PDF page to OpenAI, may incur API charges, and never saves an invoice automatically. Review all amounts and the account before Save.
- Automatic 11% VAT per item, with editable VAT rate and VAT amount
- Editable total before VAT per item with automatic invoice totals
- Original invoice number when supplied; otherwise original Excel row number
- Completely empty rows skipped; duplicate invoices retained
- Automatic double-entry journal posting
- Invoice register, dashboard, and trial balance
- User authentication, roles, audit log, customer/supplier, inventory, and stock database foundations

## Important status

This is an MVP for controlled testing. TLS is available for shared access but requires a trusted certificate and secure server configuration. Fiscal-year closing blocks later edits, while finer monthly period locks remain to be added. Before production use, complete encrypted backup and restore, exchange-rate revaluation, and independent validation of Lebanese tax/NSSF reporting by the firm's accountant.

## Quick start on one computer

Install Python 3.11 or newer. Open Command Prompt in this folder and run:

```bat
python -m pip install -r requirements.txt
python run_server.py --admin-password YourStrongPassword
```

Open a second Command Prompt in the same folder:

```bat
python run_desktop.py
```

Sign in with username `admin`, your chosen server password, and server address `http://127.0.0.1:8765`.

## Three synchronized computers

1. Choose one always-on office computer or Windows server to host the shared database.
2. Give that computer a fixed local IP address.
3. Allow TCP port `8765` only on the trusted office network. Make the office certificate on the server computer: `python run_server.py --make-certificate SERVER-NAME,SERVER-IP` (2.9.94), then copy `server-cert.pem` to each client computer's Saber data folder as `office-server-cert.pem` (or use a certificate from your own trusted CA).
4. Run `python run_server.py --host SERVER-IP --tls-cert server-cert.pem --tls-key server-key.pem` only on the server computer. Keep the private key restricted to the server account.
5. Run the desktop client on each of the three computers.
6. Enter `https://SERVER-NAME:8765` on the sign-in screen, using the name on the certificate.

For access outside the office, do not expose port 8765 directly to the internet. Use a professionally configured HTTPS reverse proxy or VPN. When TLS terminates at a reverse proxy, bind the Python server to `127.0.0.1` and proxy only to that loopback address. Existing trusted VPN/LAN installations that intentionally need plaintext must pass `--allow-insecure-lan`; HTTP traffic on such networks exposes passwords and tokens to anyone able to observe it.

## Excel import rules

The first worksheet is imported. Recognized English, Arabic, and French headings include Invoice Number, Date, Supplier/Customer Name, Total Before VAT, VAT, Total After VAT, Currency, and Type.

- If an invoice-number column contains a value, that value is used.
- Otherwise the original Excel row number is used. Excel row 24 becomes invoice 24.
- Completely empty rows are ignored.
- Duplicate invoices are deliberately retained.
- The original filename and Excel row number are stored for audit tracking.
- Missing VAT is calculated at 11% when the subtotal exists.
- Existing VAT values are preserved, even when they differ from 11%.
- Source totals that do not equal subtotal plus VAT are preserved, marked `review`, and posted against Import Variance so the ledger remains balanced.

## Build the Windows installer

Use the included Windows build workflow for a release. It runs the tests, bundles
the desktop app with its local data service and offline OCR files, checks required
PDF/OCR assets, and creates `SaberAccountingSetup.exe`. A bare PyInstaller command
does **not** produce the same complete installer. The Windows installer cannot be
built or verified on a Linux runner.

## Build a one-click installer online

Upload the **contents of this folder** to the root of a private GitHub repository (so `.github/workflows/build-windows-installer.yml` is at the repository root). The included workflow runs the tests, creates the standalone app with its local data service, and packages it as `SaberAccountingSetup.exe`. Open the repository's Actions tab, select **Build Saber Accounting Installer**, run the workflow, and download the **SaberAccountingSetup** artifact. End users do not need Python or GitHub.

## Version 0.7.1 fresh start

The default server database is `SaberAccounting/saber_accounting_v0_7.db`. This gives the upgraded application a completely fresh company file with only the default admin account. The previous `saber_accounting.db` is not loaded and remains available as a safety archive. New entries in v0.7.1 persist normally after the application is closed and reopened.

## Version 0.7.2 Excel currency formats

Excel imports detect USD, EUR, LBP, and AED from both cell contents and Excel Accounting/Custom number formats. This supports sheets where currency symbols are displayed beside numeric values without a separate Currency column. Imported dashboards, invoice lists, trial balances, and exports remain separated by currency.

## Version 0.7.3 currency page filter

The Import Excel preview includes an All/USD/EUR/LBP/AED selector and Apply button. Only rows assigned to the selected currency are displayed. Blank cells with leftover number formatting are ignored during detection; genuinely mixed rows are assigned using Total, Before VAT, and VAT evidence and remain flagged for review.

## Version 1.12.0 final release

### Payroll reports and worksheets (Payroll > Payroll Reports & Worksheets)
- **R10** quarterly salary tax withholding, **R5** annual employer declaration, **R6** individual annual statement.
- Any **month, quarter or year**; employees and managers in **separate sections**, plus a grand total.
- NSSF **employee 3%** and employer medical, family and end-of-service contributions.
- Rates and ceilings are **effective-dated (Date From to Date To)**: each month uses the rules in force on its own date. Saving a new Date From automatically ends the previous period the day before; overlapping periods are rejected.
- Separate columns for **retro salary (with its own retro tax)**, transport, schooling, bonus and 13th salary. R6 shows each retro period.
- Official amounts in LBP (other currencies converted at the payroll month's rate). Posted payroll only, with an optional draft preview.
- **Excel and PDF** export.

### Quarterly VAT (Quarterly VAT tab)
- **Q1-Q4** dates set automatically.
- Sales (output) VAT; deductible VAT on purchases, fixed assets, expenses and customs/imports; **non-deductible VAT** shown separately.
- VAT **payable or credit** carried forward to the next quarter (including into Q1 from the previous fiscal-year file).
- Totals **by currency with LBP equivalents**.
- **Manual adjustments** with a mandatory reason. Saving a return locks the quarter; only an administrator can reopen it.
- Marking VAT non-deductible (Uploaded Data > "VAT Deductible / Non-Deductible", or the expense checkbox) moves that VAT into cost, so the ledger always equals the return.
- **Excel and PDF** export.

### Security and polish
- New non-admin users are valid for **1 year** ("Renew 1 Year" in Security > Users). Expired users cannot sign in. Sessions end after 24 hours.
- Per-user **Payroll** and **VAT** access. At least one active administrator is always kept.
- **Legal document alerts** at sign-in and from the header button, for expired documents and documents expiring within 30 days.
- Backups use SQLite's online backup (safe while others work). Restore validates the file and creates a safety backup first.
- Clearer error messages. A page that fails to load no longer stops the others.

### Fixes
- Payroll saved from the desktop app now stores the period correctly (this previously affected payroll numbering and rate lookups).
- Exchange-rate lookups now pick the latest rate on or before the date, chronologically.
- Users created in Settings are saved to the sign-in database.

### To confirm with your accountant
The salary tax method is unchanged: transport and schooling are included in taxable salary, and one-off bonus / 13th salary are annualized ×12 in the month paid. Adjust in Tax & NSSF Settings or ask for a rule change if your practice differs.

### Build the installer (final workflow)
1. Upload the contents of this folder to the GitHub repository root (replace the old files, not the user's saved company databases).
2. Open **Actions**, select **Build Saber Accounting Installer**, click **Run workflow**. It also runs automatically on every push to `main`.
3. When it finishes, download the **SaberAccountingSetup** artifact and run `SaberAccountingSetup.exe`.

One installer only: no Python, no manual server. The data service starts automatically inside the app, and company data stays in the user's `SaberAccounting` folder across upgrades. On a new computer, the app asks you to create the initial administrator password (at least 10 characters); sign in as `admin` with that password.


---

# Version 2.0.0 - complete release

## Modules
| Tab | What it does |
|---|---|
| Sales Invoice | Automatic number, editable lines (Item, description, qty, price, VAT), VAT treatment (taxable / zero-rated / exempt / out of scope), New / Save / Save & Post, reopen and edit |
| Journal Voucher | BRAINS-style voucher: multi-currency lines with LBP and USD amounts and rates, due date, reference, department, project, navigation |
| Import | Excel or PDF invoices as Purchases, Sales, Expenses or Assets. PDFs are read automatically and attached. Adds to existing data (replace is optional) |
| Customers / Suppliers | Account number first; type 4 digits and the full number fills in |
| Payment & Receipt | Customer receipts (RV-) and supplier payments (PV-) on the page, with balance, edit and delete |
| Purchases & Expenses | Purchases with PDF, cost on purchase (customs, freight, insurance, import VAT - manual, Excel or PDF), VAT use; expenses with PDF, Excel import, New / Edit / Delete / Search |
| Inventory | Items, warehouses, stock documents (opening, receipt, issue, adjustments, transfer), weighted average or FIFO, reports, stock variation |
| Payroll | Lebanese rules 2024-2026, R5 / R6 / R10 reports |
| Quarterly VAT | Lebanese periodic declaration with the partial deduction right |
| Trial Balance / Statement | Balance des Comptes options (BRAINS) |
| Profit & Loss | Fiscal-year dates, closing 6 & 7 as a Journal Voucher, automatic opening of the next year |
| Financial Reports | Ledger, balance sheet, cash flow, aging, comparative P&L, budget |
| Security / Backup / Rates | Users with 1-year validity and permissions, departments, projects, backups, exchange rates |

## Inventory (Lebanese periodic method)
- Purchases stay in 601. Stock quantities and costs come from the stock documents.
- Costing: company-wide moving weighted average (default), allocating each warehouse's on-hand units at the current company-wide average, or FIFO by warehouse (transfers carry the oldest source warehouse cost layers). Stock can never go negative in a warehouse.
- A Sales Invoice line with an Item code issues the stock automatically (Stock Issue linked to the invoice; deleting or cancelling the invoice removes it).
- Reports: Stock Valuation (at any date, by warehouse, at cost and at sales price), Stock Card, Stock Movements, Sales Margin (COGS), Reorder, Slow-moving stock. Excel, PDF and print.
- Year end: the Stock Variation voucher (type 06) cancels account 37 against 6051 and books the closing stock (Dr 37 / Cr 6052). It is posted automatically when the year is closed, and the closing stock becomes the Opening Stock of the next year.

## Year-end order
1. Enter the last documents of the year and check the stock (Inventory > Reports > Stock Valuation at 31-12).
2. Profit & Loss > Preview Closing 6&7.
3. Close the year: stock variation, closing 6 & 7 (result to 121 / 125), and the opening of the next year (balances and stock) are made automatically.
4. "Delete Closing & Reopen Year" undoes everything if a correction is needed.

## Points to confirm with the accountant
- NSSF branch contribution percentages against the current implementing decrees (the configured 3% employee, 8% employer medical, 6% family, and 8.5% end-of-service rates are not fully primary-source verified here).
- Exact start dates of the January-April 2024 NSSF ceilings and any minimum-wage change applied partway through a month.
- VAT declaration box numbers against the official MoF form; rounding of the deduction ratio.

# Version 2.1.0

## Arabic in PDF
Every PDF (reports, statements, invoices, VAT declaration, R5 / R6 / R10, NSSF statement) prints Arabic text correctly - joined letters, right-to-left - using the Amiri font (SIL Open Font License, `assets/fonts/Amiri-OFL.txt`). Reports carry Arabic labels next to the English.

## NSSF ceilings - automatic and monthly
- A new or never-configured company loads the app's Lebanese payroll defaults for 2024-2026 (ceilings, configurable rates, family allowances, tax rounding). Settings you changed yourself are never overwritten; the "Load Lebanese Payroll Rules" action reloads them on request.
- Payroll is monthly: each payroll uses the rules in force on the **last day of its month** (for example the 90M -> 120M sickness-and-maternity ceiling change of August 2025, or the LBP 10,000 rounding from 25-11-2024 for November). Retroactive pay uses the ceilings of each of its own months.
- Payroll > Payroll Reports & Worksheets > "CEILINGS - NSSF ceilings by month" shows the ceilings and rates of every month of a year.

## NSSF payment format
Payroll > Payroll Reports & Worksheets > "NSSF - Contributions statement (payment)", monthly or quarterly, Arabic / English:
- per employee and month: NSSF number, salary subject, capped bases and contributions for sickness & maternity, family allowances and end of service using the saved rates, family allowances already paid, net due;
- payment summary by branch and the net amount payable to the NSSF (LBP);
- the monthly ceilings and rates applied; employer NSSF number from General Settings.
"Record NSSF Payment" books the payment voucher (Dr NSSF payable / Cr cash or bank).

## Payroll and NSSF compliance limits
- The sickness-and-maternity ceiling is LBP 120M from 1 August 2025 (Decree 887 of 21-08-2025) and the minimum wage LBP 28M (Memo 801), and the family-branch ceiling of LBP 28M plus revised allowances from 1 May 2026 (Memo 831). The family ceiling of LBP 18M begins 1 July 2025 (Memo 793).
- CNSS Contribution System 11, Article 1, defines covered earnings broadly. Accordingly, the NSSF base includes transport and schooling allowances even when part of those amounts is exempt from salary tax. Supporting expense reimbursements are different and require proof.
- The consolidated Social Security Law (through 31 August 2026) delegates contribution percentages to implementing decrees. The app’s configurable 3% employee, 8% sickness-and-maternity employer, 6% family, and 8.5% end-of-service rates have not been fully verified here against the current primary decrees; verify the applicable rates before filing or paying. Existing user-saved settings are preserved, so inspect old company files for legacy rates before use.
- Foreign-worker EOS eligibility is category- and agreement-dependent; nationality alone is not sufficient. The app’s nationality/age shortcut is warning-bearing and must not be relied on without checking the employee’s CNSS category. Spouse-working family-tax deduction allocation and minimum-wage treatment for a partial month also require confirmation.
- R5, R6, and R10 exports are preparation/reconciliation worksheets, not the current MoF forms or electronic submissions. The Ministry lists R5/R6/R7 XML filing resources; this app does not generate those official submissions (including R7). NSSF statements and annual settlements are also review worksheets, not CNSS filings. The app’s automatic 10-employee monthly/quarterly period choice is only a suggestion: CNSS Law Article 72 addresses fixed contributions for small establishments, not a verified filing-frequency threshold.
- Primary references checked: [CNSS Memo 801](https://www.cnss.gov.lb/59-%D9%83%D8%B1%D9%83%D9%8A-%D8%A2%D9%84%D9%8A%D9%91%D8%A9-%D8%A7%D8%AD%D8%AA%D8%B3%D8%A7%D8%A8-%D8%A7%D8%B4%D8%AA%D8%B1%D8%A7%D9%83%D8%A7%D8%AA-%D8%A7%D9%84%D8%B6%D9%85%D8%A7%D9%86-%D8%A8%D8%B9), [CNSS Memo 831](https://www.cnss.gov.lb/41-%D9%83%D8%B1%D9%83%D9%8A-%D8%B2%D9%8A%D8%A7%D8%AF%D8%A9-%D8%A7%D9%84%D8%AA%D8%B9%D9%88%D9%8A%D8%B6%D8%A7%D8%AA-%D8%A7%D9%84%D8%B9%D8%A7%D8%A6%D9%84%D9%8A%D9%91%D8%A9-%D9%84%D9%84%D8%B9%D9%85-2), [CNSS laws and systems](https://www.cnss.gov.lb/%D8%A7%D9%84%D9%82%D9%88%D8%A7%D9%86%D9%8A%D9%86-%D9%88%D8%A7%D9%84%D8%A3%D9%86%D8%B8%D9%85%D8%A9), [MoF wages page](https://www.finance.gov.lb/ar-lb/Taxation/Individuals/D-S/Pages/Tax-on-DASS.aspx), and [MoF Citizen Budget 2024](https://finance.gov.lb/en-us/Finance/BI/ABDP/Annual%20Budget%20Documents%20and%20Process/Citizen%20Budget%202024-ENG.pdf).

## Fix
Company files created by older versions are brought up to date automatically when they are opened.

# Version 2.2.0

## Sales Invoice, Debit Note, Credit Note
- Document type: Invoice (SAL-), Debit Note (DN-), Credit Note (CN-, reverses the sale and reduces the VAT of the period).
- Lines: Item, Description, Qty, Unit, Unit Price, Total Amount, Discount %, VAT %, Net.
- Totals: Total, Discount (% or amount), **Total HT**, VAT 11% (struck through for zero-rated / exempt), TOTAL, and the **amount in words** in English and Arabic (tafqeet).
- Find by number only (type 12 for SAL-2026-000012), Duplicate, Print Preview, PDF, Print, Import Excel (template provided), Import PDF, Excel Template.

## General Journal
Find by voucher number and by details; Print Preview, PDF and Print.

## Payment & Receipt
Cash / bank accounts from 511, 512, 519 and 53 only; customers and suppliers in both tabs; **allocation** of each receipt / payment to open invoices (auto: oldest first), open balance per document.

## Purchases & Expenses
- Find instead of the lists. Purchases: items received into stock with warehouse (F2 item search; an item that does not exist is created automatically), Excel import with template, PDF.
- Cost on purchase: each cost to its own 9-digit 6018 account (601800001 freight, 601800002 insurance, 601800003 customs duties, 601800004 broker, 601800005 other); import VAT to 44210.
- Expense account chosen from accounts 626 to 69.

## Accounts
VAT: 44210 purchases, 44211 export-related purchases, 44216 expenses, 4427 sales. Payroll: 6311 salaries, 6312 bonus / 13th, 6313 commission, 6315 schooling, 6316 managers' salaries, 6319 transport, 4411 salary tax, 4431 NSSF.
Year-end result to **138** (profit) / **139** (loss); the closing voucher is "CLOSING 6&7" in the General Journal.

## Inventory
Items with cost price (average of purchases), supplier, category / subcategory, unit and location. New tabs: Categories & Units, Stock In / Stock Out (at average cost), Physical Inventory (stock on hand, count, difference, save, print, Excel sheet, upload, post the differences). Reports filter by category, subcategory, unit, supplier and warehouse together.

## F2
F2 opens the list that fits the field: items in item fields, customers / suppliers in party fields, accounts elsewhere.

# Version 2.3.0 - Statement of Account / Trial Balance
- Account From / To: search by number or name among all accounts (parents too); the account name shows beside each box (like BRAINS). "Same as From" copies the account.
- The options are in their own "Options" tab; every Show opens its own full-page tab with Print Preview, Print, Excel, PDF and Close Tab. Several statements can stay open side by side.
- Double-click a statement line to see the transaction (all its lines) and "Open in its screen" (journal voucher, sales invoice, purchase, receipt / payment, expense). In the Trial Balance, double-click an account to open its statement in a new tab.

# Version 2.4.0
- Profit & Loss > "Delete Year" (administrators): deletes the last fiscal year of a company (for example 2025, to redo the opening). A backup copy of the file is kept in `companies/<company>/deleted_years`, and the previous year is reopened with its closing removed. Type "DELETE <year>" to confirm. Then close the previous year again to make a new opening.
- NSSF statement: sickness & maternity shown as employee 3% + employer 8% = total 11% (as in the NSSF declaration).

# Version 2.5.0 - Backups per company and per year
- Backups are made automatically each day while signed in to Windows. You can also press "Create Backup Now"; safety backups are made before restore and replacement imports.
- Each company and each fiscal year has its own folder and file name: `SaberAccounting\backups\<Company>\<Year>\<Company>_<Year>_<date>_<time>.db`.
- Security / Backup / Rates > Backup & Restore shows the backups of the company and year you are in, with "Save Backup As..." (copy to a USB key or a drive folder) and "Open Backup Folder". Backups made by older versions still appear and can be restored.

# Data safety and automatic backups update

- The first standalone launch asks you to set an admin password. Existing installations keep their current password.
- Any signed-in user can create, view, and save a backup of the selected company/year from **My Backups**. Only administrators can restore a backup.
- The Windows installer installs a background backup process in the shared Startup folder. It runs after Windows sign-in, checks once per hour, and creates one backup per company/year when 24 hours have passed. The desktop window does not need to be open. The computer must be on and a Windows user must be signed in. On the first new-company launch, a backup is made immediately. Backup files live in `SaberAccounting/backups/<Company>/<Year>` under that Windows user's profile; copy this folder to another drive if you need protection from drive failure.
- Replacing imported invoices now validates the complete batch before changing the live file and keeps manual journal vouchers. If any row fails, the replacement is cancelled. A safety backup is made before a successful replacement.
- Replacement is refused when payments, stock documents, or a saved VAT return are linked to existing invoices, when a fiscal year is closed, or when existing invoices record amounts paid. Review those records first.
- Invalid company/year selections return an error. Payment and expense edits are prepared on a database snapshot before replacing the live file. Stock checks no longer temporarily remove saved movements.
- The PDF import preview scans every page and creates separate preview rows when invoice numbers change. Repeated invoice numbers on following pages are grouped. Scanned pages stay visible for manual entry. Invoices sharing one page still require manual separation and review.

# Version 2.6.0 - review of the ChatGPT changes + inventory reports
Kept from the ChatGPT changes (all tests pass): initial admin password (10+ characters) instead of admin/admin, safer invoice / payment edits (nothing lost if a save fails), year closing with automatic rollback, stricter company / year checks, local expense-account suggestions (ai_mapper) and optional OpenAI assistance (ai_service - needs an API key; it sends page 1 of the chosen invoice PDF to OpenAI).
Adjusted: the background daily backup is now an OPTIONAL installer task, unchecked by default (backups are made on request from Backup & Restore); leftover files removed (temp.txt, shortcut).

## Inventory reports
- **Inventory Summary**: key figures (items, value at cost and at sales price, potential margin, items to reorder, slow-moving and old-stock value), value by category and by warehouse, top 10 items, ageing, items to reorder.
- **Stock Ageing**: stock on hand by age of receipt (first in - first out): 0-30, 31-60, 61-90, 91-180, 181-365, over 365 days (buckets can be changed), value per bucket, average age, oldest receipt, last issue, % of old stock, category subtotals, ageing summary, and the list of stock older than 180 days to review.
- **Stock Valuation**: grouped by category with subtotals.
All with the filters (warehouse, category, subcategory, unit, supplier, costing method) and Excel / PDF / Print.

# Version 2.7.0
- Merged: the latest ChatGPT changes + version 2.6.0 (stock ageing, inventory summary, valuation by category, optional automatic backup were missing from the upload and are back).
- **Financial Reports > Business Reports** (Excel, PDF, print, preview):
  - Receivables Ageing (customers) and Payables Ageing (suppliers): open documents by days after the due date (not due, 1-30, 31-60, 61-90, 91-180, over 180 - buckets can be changed), receipts / payments not allocated, net due, % overdue, detail of open documents.
  - Item Sales by Client, and Client Quantities by Item: quantity, average price, HT, VAT, TTC.
  - Sales Analysis (3D pivot): rows (client / item / category) x columns (month / quarter / client / item / category) x measure (quantity / HT / VAT / TTC).
  - Top Clients and Top Suppliers (purchases and expenses): HT + VAT = TTC, share, cumulative share, number of documents.
  - Amounts in USD or LBP (converted at each document date) or one currency only; credit notes deducted.
- **Payroll > Tax & NSSF Settings**: the NSSF ceilings and rates by period (Date From - Date To) are edited directly in the table (double-click), with Add / Delete / Save Periods; a new Date From closes the previous period automatically.
- Lighter, calmer layout: shorter table rows (more lines on screen), soft headings, clean input borders, buttons that light up under the mouse.

OCR always requires review before automatic posting, including high model confidence. Expense, asset and sales PDF reading runs away from the UI thread; each Tesseract call has a 30-second timeout.
