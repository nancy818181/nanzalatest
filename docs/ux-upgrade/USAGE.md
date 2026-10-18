# Daily workflow workbench / أدوات العمل اليومية

Open NANZA with `python run_desktop.py`, log in and select a company/fiscal year.
The existing analytic reports remain available.

## Ageing / أعمار الذمم
Dashboard → **Ageing / أعمار الذمم**. Choose sale/purchase and an as-of date, then Refresh.
The coloured bucket buttons filter immediately. Double-click a customer/supplier to view open
invoices and their balances. Excel exports the visible party view; the drill-down has its own export.
Amounts and dashboard overdue badges stay separate by native currency. 0–30 includes not due;
90+ means >90. Credit balances remain separate.

## WhatsApp summary / ملخّص واتساب
Dashboard → **Copy WhatsApp Summary**, or **Ctrl+W**. Review date/currency/text, then Copy.
The app never opens WhatsApp or sends the text. Enable the 6pm **local reminder** to reopen the
preview while NANZA is running. This is saved for the selected user/company/year.
**Auto-send is disabled:** an authorized, configured messaging transport is still required.
Do not enter recipients or API credentials into accounting descriptions.

## Custom reports / تقارير مخصصة
Dashboard → **Custom reports**. Posted sales lines appear automatically after a 350ms typing pause.
Type into customer/product/warehouse/currency selectors to search, then choose a matching result.
Drag filter headings to reorder them. Dates accept the existing ISO and DD-MM-YYYY formats.
Use arrows for preview pages of 500 lines. Excel/PDF exports the complete filtered result up to
50,000 lines. Larger exports require narrower filters; there is no silent truncation.
**Ctrl+E** exports from the report window. Save a name such as **My Monthly Sales** and select it
from the template dropdown later. Templates store filters, not copies of accounting data.
Only actual linked stock movements qualify for a warehouse filter. Invoices without item lines
are explicitly excluded from this line-level report. Totals are native-currency line totals.

## Offline assistance / المساعد المحلي
Expense descriptions receive a debounced inline account suggestion using the selected company's
active posting expense accounts. Suggestions never overwrite a field or post an entry.
Existing pre-save duplicate confirmations remain active on invoice forms. The additional duplicate
inspection endpoint matches normalized invoice number, exact amount and date, with optional
party/currency/direction and edit exclusion.
Dashboard **Explain P&L** compares the current month-to-date with the preceding equal-length period.
It does not invent prior-year data or claim causal certainty. The 30-day mini chart extrapolates
historical native-currency cash movement and is explicitly an illustration. Existing longer-term
forecast/analytic modules are preserved.

## Runtime and packaging
`nanza/` is the active application source selected by `nanza_paths.py`.
The four new modules are `nanza_delivery/ageing_report.py`, `whatsapp_daily_summary.py`,
`custom_report_builder.py` and `ai_accountant.py`. The nested older `nanza_delivery/nanza/` copy
has not been substituted for active code. The active GUI is Tk/ttk; no UI-framework migration
was made. New modules are included explicitly in the Windows installer workflow.

The target repository returned GitHub 404 (missing or not accessible to the connected account).
Create/grant access to `nancy818181/nanza-accounting-final` before pushing. No other repository
was modified as a substitute. The supplied ZIP is source code, not a tested new Windows installer.
