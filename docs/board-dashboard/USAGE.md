# Complete Board Dashboard / لوحة الإدارة الشاملة

Open the existing application with `python run_desktop.py`, sign in and choose a company/year.
Use the **📊 Board Dashboard** navigation button or **Ctrl+B**. The operational dashboard and
all four workflow features from 2.9.129 remain available. Past fiscal years default to 31 December;
the active fiscal year defaults to the current fiscal date.

## Clean board
The black/gold board uses the supplied reference's four KPI cards and three columns:
- Revenue, book cash, net income and historic year-end cash, with YoY only when comparable data exists.
- Executive summary, EBITDA/SG&A metrics and the last six months' revenue/gross margin.
- Funded debt covenant, direct cash movement bridge, and a net-income-to-EBITDA bridge.
- Capital structure, ratios versus targets, FCF by month, and year-end cash/interest coverage.

No QR, advertising, social bar, footer links or footer text is rendered. The geographic marketing
map is replaced by an accounting earnings bridge. PDF exports the complete board in one vector
page with the same panel layout. Figures are from the selected company's posted SQLite books;
the screenshot's example dollar balances are not copied into application data.

Use **↻** to refresh after changing date/currency. **PDF** or **Ctrl+E** exports the board.
Background workers fetch data and write PDF; stale company/session responses are ignored.
The company name, period and currency are carried in the board header.

## One-time accountant configuration
Use **⚙** as an administrator. Select active posting accounts from the actual chart for COGS,
SG&A, interest, D&A, income tax, funded debt, current assets/liabilities and cash-flow counterparts.
Type to search the account list. Account codes are exact matches, not prefix rollups.
Enter the agreed covenant/ratio targets, then explicitly confirm review and Save.
Empty reviewed groups mean the accountant confirmed no applicable balance; they are not AI guesses.
Changes are stored inside the company/year database with an audit-log entry. Other users can view
but cannot save board mappings. Board mappings are reporting metadata: administrators may edit them even in closed years, like the existing financial-report configuration. Journal/book locks remain enforced.

## Formulas and unavailable data
- Revenue: signed posted income; net income: income less signed posted expenses.
- Cash: posted cash/bank accounts under the same 51/53 convention as the existing dashboard.
- EBITDA: net income + reviewed interest + income tax + depreciation/amortisation.
- Debt/EBITDA compliance: reviewed funded debt / positive full-year EBITDA, compared with an
  entered limit; only a completed fiscal year qualifies. Unknown is never labelled compliant.
- Equity includes unclosed earnings. Current ratio = mapped current assets / positive mapped
  current liabilities. Debt/equity uses funded debt / positive equity.
- ROIC = (EBIT − mapped income tax) / average opening-and-ending invested capital, ×100;
  invested capital = funded debt + equity − cash. It is withheld for incomplete years or
  non-positive invested capital. This is an explicit convention for accountant review.
- FCF = classified operating cash + net capex cash. Every material non-opening cash journal must
  have noncash counterparts wholly within one reviewed cash-flow category. Mixed/unclassified
  entries block FCF even when their net amounts cancel. Opening balances are not operating FCF.
- A valid classified cash bridge uses operating/capex/financing buckets. Otherwise the bridge
  still reconciles by actual document source. It does not invent AR/AP changes or conversion days.
- DSCR stays unavailable without a debt-service schedule. No approved year-end forecast feed is
  configured: the year-end KPI is actual historic 31 December cash only, not a future prediction.
- Missing prior-year files/rates are not represented as zero growth. Missing denominators and
  unreviewed mappings show an em dash. Hover for Arabic guidance; use ⚙ to resolve mappings.

بالعربي: اللوحة مستقلة عن شاشة العمل اليومية. افتحها بالزر أو Ctrl+B، واربط الحسابات من ⚙
بعد مراجعة المحاسب. الشرطة — تعني أن البيانات أو الإعدادات غير متاحة، وليست صفراً.
التصدير PDF نظيف بلا تذييل أو روابط. لا يوجد ترحيل آلي أو خدمة ذكاء اصطناعي مدفوعة.

## Deployment and GitHub
Install the updated requirements before running source. CustomTkinter 5.2.2 and Matplotlib 3.10.9
are explicitly included in the Windows build workflow. A new Windows installer must still be
built and acceptance-tested; the ZIP alone is not a tested installer or live-data certification.
The requested repository is `nancy818181/nanza-accounting-final`; it returned GitHub 404 during
this task (missing or unavailable to the connected account). No alternative repository is used.
A 9/10 competitive rating is a goal, not a validated benchmark or a claim that competitors lack BI.
