"""Reviewable IAS 1 reporting pack from each company's separate fiscal-year books.

No ledger mutations or automatic audit opinion. Saved presentation mappings are
explicit; cash flow classifications and disclosures require accountant review.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
from database import iso_date, utcnow

ZERO = Decimal('0')
KEY = 'financial_statement_draft'
GROUPS = {
    'ppe': 'Property, plant and equipment (net)',
    'intangible': 'Intangible assets (net)',
    'noncurrent_assets': 'Other non-current assets',
    'inventory': 'Inventories', 'receivables': 'Trade and other receivables',
    'cash': 'Cash and cash equivalents', 'current_assets': 'Other current assets',
    'capital': 'Share capital', 'reserves': 'Reserves', 'retained': 'Retained earnings / accumulated results',
    'noncurrent_liabilities': 'Non-current liabilities and provisions',
    'payables': 'Trade and other payables', 'current_liabilities': 'Other current liabilities',
    'revenue': 'Revenue (net of discounts)', 'other_income': 'Other income',
    'materials': 'Purchases and inventory movement', 'services': 'External services',
    'staff': 'Employee benefits expense', 'taxes': 'Other taxes and duties',
    'finance': 'Net finance costs', 'depreciation': 'Depreciation, amortisation and provisions',
    'other_expenses': 'Other expenses', 'income_tax': 'Income tax expense',
    'unmapped': 'Unmapped accounts - classification required',
}
ASSETS = ['ppe','intangible','noncurrent_assets','inventory','receivables','cash','current_assets']
EQUITY = ['capital','reserves','retained']
LIABILITIES = ['noncurrent_liabilities','payables','current_liabilities']
INCOME = ['revenue','other_income']
EXPENSES = ['materials','services','staff','taxes','finance','depreciation','other_expenses','income_tax']
NARRATIVES = {
 'Entity and activities': '{company} (the "Company") is a {legal_form} registered in Lebanon{address_text} under commercial register number {cr_number}, incorporated on {incorporation_date}. Its tax (MoF) number is {tax_number}.\nThe principal activities of the Company are: {activities}.\nShareholders / partners: {shareholders}.\nDirectors / managers: {directors}.',
 'Basis of preparation': 'The financial statements have been prepared in accordance with International Financial Reporting Standards (IFRS) under the historical cost convention, and are presented in {basis}. Amounts recorded in other currencies are translated at the exchange rates recorded in the books.\nThe financial statements were approved for issue by management on {approval_date}. [Confirm the going concern basis.]',
 'Material accounting policies': 'Revenue is recognised when control of the goods or services passes to the customer, net of discounts and value added tax.\nInventories are measured at the lower of cost and net realisable value; cost is determined using the {inventory_method} method.\nProperty, plant and equipment are stated at cost less accumulated depreciation; depreciation is charged on a straight-line basis over the useful lives of the assets.\nTrade receivables are stated at their invoiced amounts less an allowance for expected credit losses.\nCash and cash equivalents comprise cash on hand and balances with banks.\nTrade payables are stated at the amounts payable for goods and services received.\nTransactions in foreign currencies are recorded at the exchange rates of the transaction dates; monetary balances are translated at the rates recorded at the reporting date.\nValue added tax is accounted for in accordance with Lebanese VAT law; recoverable VAT is presented with receivables and VAT payable with payables.\nIncome tax is provided in accordance with Lebanese tax law.\nProvisions are recognised when the Company has a present obligation that can be measured reliably; end-of-service indemnities follow Lebanese labour law and NSSF regulations.',
 'Judgements and estimates': 'Preparing the financial statements requires management to make judgements and estimates, mainly for the expected credit losses on receivables, the net realisable value of inventories, the useful lives of property and equipment, and provisions. [Complete with entity-specific judgements.]',
 'Share capital': 'The share capital of the Company is {share_capital}, fully paid. [Confirm the number and nominal value of the shares and any change during the year.]',
 'Income tax': 'Income tax is calculated in accordance with the Lebanese Income Tax Law on the taxable profit for the period, after adding back the expenses that are not deductible for tax purposes. [Insert the reconciliation between the accounting profit and the taxable profit, and the tax rate applied.]',
 'Currency and inflation': 'The functional and presentation currency is {basis}. Balances in other currencies are translated using the rates recorded in the books. [Assess the effect of the Lebanese economic situation, multiple exchange rates and IAS 29 if relevant.]',
 'Financial risk management': 'The Company is exposed to credit risk, mainly on trade receivables and bank balances; to liquidity risk; and to currency risk on balances and transactions in currencies other than {basis}, including the effect of the multiple exchange rates in Lebanon. Management monitors these risks regularly. [Complete with the Company\'s policies and the main amounts exposed.]',
 'Related parties and commitments': '[List related parties (shareholders, directors, companies under common control), the transactions and balances with them, commitments and contingent liabilities.]',
 'Events and going concern': '[Describe events after the reporting date (IAS 10) and the going concern assessment.]',
 'Additional disclosures': '[Add other disclosures where relevant: leases, capital management, comparative figures reclassified.]',
 'Approval of the financial statements': 'The financial statements were approved for issue by management on {approval_date}.',
}
AUDIT = {
 'Addressee': 'To the Shareholders of {company}',
 'Opinion': 'We have audited the financial statements of {company} (the "Company"), which comprise the statement of financial position as at {end_text}, and the statement of profit or loss and other comprehensive income, the statement of changes in equity and the statement of cash flows for the {period_text} then ended, and notes to the financial statements, including material accounting policy information.\nIn our opinion, the accompanying financial statements present fairly, in all material respects, the financial position of the Company as at {end_text}, and its financial performance and its cash flows for the {period_text} then ended in accordance with International Financial Reporting Standards (IFRS).',
 'Basis for opinion': 'We conducted our audit in accordance with International Standards on Auditing (ISAs). Our responsibilities under those standards are further described in the Auditor\'s Responsibilities for the Audit of the Financial Statements section of our report. We are independent of the Company in accordance with the International Ethics Standards Board for Accountants\' International Code of Ethics for Professional Accountants (IESBA Code), together with the ethical requirements that are relevant to our audit of the financial statements in Lebanon, and we have fulfilled our other ethical responsibilities in accordance with these requirements and the IESBA Code. We believe that the audit evidence we have obtained is sufficient and appropriate to provide a basis for our opinion.',
 'Going concern / key audit matters': '',
 'Other information': '',
 'Management and governance responsibilities': 'Management is responsible for the preparation and fair presentation of the financial statements in accordance with IFRS, and for such internal control as management determines is necessary to enable the preparation of financial statements that are free from material misstatement, whether due to fraud or error.\nIn preparing the financial statements, management is responsible for assessing the Company\'s ability to continue as a going concern, disclosing, as applicable, matters related to going concern and using the going concern basis of accounting unless management either intends to liquidate the Company or to cease operations, or has no realistic alternative but to do so.\nThose charged with governance are responsible for overseeing the Company\'s financial reporting process.',
 'Auditor responsibilities': 'Our objectives are to obtain reasonable assurance about whether the financial statements as a whole are free from material misstatement, whether due to fraud or error, and to issue an auditor\'s report that includes our opinion. Reasonable assurance is a high level of assurance, but is not a guarantee that an audit conducted in accordance with ISAs will always detect a material misstatement when it exists. Misstatements can arise from fraud or error and are considered material if, individually or in the aggregate, they could reasonably be expected to influence the economic decisions of users taken on the basis of these financial statements.\nAs part of an audit in accordance with ISAs, we exercise professional judgement and maintain professional scepticism throughout the audit. We identify and assess the risks of material misstatement, obtain an understanding of internal control relevant to the audit, evaluate the appropriateness of accounting policies used and the reasonableness of accounting estimates, conclude on the appropriateness of management\'s use of the going concern basis of accounting, and evaluate the overall presentation, structure and content of the financial statements.\nWe communicate with those charged with governance regarding, among other matters, the planned scope and timing of the audit and significant audit findings, including any significant deficiencies in internal control that we identify during our audit.',
 'Other legal and regulatory requirements': '',
 'Signature, address and report date': '{auditor_firm}\n{auditor_partner} - Licence No. {auditor_license}\n{auditor_address}\n{report_city}, {report_date}',
}
# 2.9.83: the default texts of 2.9.82 and before. A section still holding one of them (saved unchanged) gets the new text,
# which takes the company and auditor information entered once.
PREVIOUS_DEFAULTS = {
 '{company} (the "Company") is registered in Lebanon{address_text}. [Complete: legal form, commercial register number, date of incorporation, shareholders and principal activities.]',
 'The financial statements have been prepared in accordance with International Financial Reporting Standards (IFRS) under the historical cost convention, and are presented in {basis}. Amounts recorded in other currencies are translated at the exchange rates recorded in the books. [Confirm the applicable framework, going concern and the date of authorisation for issue.]',
 '[Add other disclosures: financial risk management, taxation, leases, capital management.]',
 '[Audit firm name]\n[Partner name - License No.]\n[Address]\n[Date]',
}
# 2.9.83: company and auditor information - entered once (Edit Texts > Company & Auditor) and used by every year and every text.
INFO_FIELDS = {
 'legal_form': 'Legal form (e.g. S.A.L., S.A.R.L.)',
 'cr_number': 'Commercial register number',
 'incorporation_date': 'Date of incorporation',
 'tax_number': 'Tax (MoF) number',
 'activities': 'Principal activities',
 'shareholders': 'Shareholders / partners',
 'directors': 'Directors / managers',
 'share_capital': 'Share capital (amount)',
 'approval_date': 'Date approved for issue',
 'auditor_firm': 'Audit firm',
 'auditor_partner': 'Signing partner',
 'auditor_license': 'Licence number (LACPA)',
 'auditor_address': 'Auditor address',
 'report_city': 'City of the report',
 'report_date': "Date of the auditor's report",
}
# 2.9.97: the auditor's details (and logo) are the AUDITOR's, the same for every company he audits: saved once in the main file.
AUDITOR_KEYS = ('auditor_firm', 'auditor_partner', 'auditor_license', 'auditor_address', 'report_city')
PROFILE_KEY = 'auditor_profile'


def auditor_profile(master):
    if master is None: return {}
    try:
        with master.connect() as conn:
            row = conn.execute('SELECT value FROM app_settings WHERE key=?', (PROFILE_KEY,)).fetchone()
        return json.loads(row['value']) if row and row['value'] else {}
    except Exception:
        return {}


def save_auditor_profile(master, info, logo=None):
    """info: the auditor fields typed (empty ones are kept as they were); logo: base64 PNG/JPEG, '' to remove, None to keep."""
    if master is None: return {}
    profile = auditor_profile(master)
    for key in AUDITOR_KEYS:
        if str((info or {}).get(key) or '').strip(): profile[key] = str(info[key]).strip()
    if logo is not None:
        if logo and len(logo) > 2_000_000: raise ValueError('The logo is too large (keep it under about 1.5 MB)')
        profile['logo_b64'] = logo
    with master.connect() as conn:
        conn.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (PROFILE_KEY, json.dumps(profile)))
    return profile


def _with_profile(cfg, master):
    """The company's report settings with the auditor's details filled from the profile where the company has none."""
    profile = auditor_profile(master)
    if not profile: return cfg
    cfg = dict(cfg); info = dict(cfg.get('info') or {})
    for key in AUDITOR_KEYS:
        if not str(info.get(key) or '').strip() and profile.get(key): info[key] = profile[key]
    cfg['info'] = info
    if profile.get('logo_b64'): cfg['auditor_logo'] = profile['logo_b64']
    return cfg


# Saved once for the company: copied to every fiscal-year file (each year is its own database).
SHARED_KEYS = ('info', 'notes', 'audit', 'mapping')
# The placeholders of 2.9.68 and before: a section still holding one of them gets the full text above.
OLD_DEFAULTS = {
 '[Complete legal form, domicile, registered address, activities and ownership.]',
 '[Confirm applicable IFRS requirements, measurement basis, going concern and authorisation date. This draft does not assert compliance.]',
 '[Describe policies relevant to this entity: IFRS 15 revenue, IFRS 9 financial instruments, IFRS 16 leases, IAS 2 inventory, IAS 12 taxes, IAS 16 assets and IAS 19 employee benefits.]',
 '[Describe material judgements, estimation uncertainty and impairment assessments.]',
 '[Confirm functional and presentation currencies, IAS 21 translation and applicability of IAS 29. Recorded book equivalents are used; no automatic IAS 21/IAS 29 restatement is performed.]',
 '[Complete IAS 24 relationships, transactions, balances, commitments and contingencies; do not assume none.]',
 '[Complete IAS 10 events after the reporting period, going concern assessment and authorisation for issue.]',
 '[Add entity-specific IFRS disclosures, financial risks, leases, tax reconciliation, asset roll-forwards and other material information.]',
 '[Shareholders / appropriate addressee]',
 '[Auditor to insert the opinion after completing the audit. No opinion has been generated.]',
 '[Auditor to complete applicable ISAs, ethics and independence requirements, and evidence supporting the opinion.]',
 '[Auditor to assess applicable reporting requirements and complete or remove sections as appropriate.]',
 '[Auditor to assess ISA 720 applicability and insert appropriate wording.]',
 '[Complete responsibilities for preparation, internal control, going concern and oversight.]',
 '[Auditor to insert engagement-appropriate ISA reporting wording.]',
 '[Complete where applicable.]',
 '[Auditor name, signature, address and date - to be completed by the auditor.]',
}
SUPPLEMENTS = {
 'oci': 'Other comprehensive income (net of tax, signed)',
 'cf_operating': 'Net operating cash flows (signed)',
 'cf_investing': 'Net investing cash flows (signed)',
 'cf_financing': 'Net financing cash flows (signed)',
 'cf_fx': 'Exchange effect on cash (signed)',
}

def number(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite(): raise ValueError()
        return result
    except (InvalidOperation, ValueError): raise ValueError('Enter a finite numeric amount')

def money(value):
    return value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if value else ZERO

def years_from(value):
    parts = re.split(r'[,;\s]+', value.strip()) if isinstance(value, str) else value
    if not isinstance(parts, (list, tuple)) or not parts: raise ValueError('Choose one or two fiscal years, e.g. 2025 or 2024,2025')
    if any(not re.fullmatch(r'\d{4}', str(x)) for x in parts): raise ValueError('Years must be four digits')
    years = sorted({int(x) for x in parts}, reverse=True)
    if len(years) > 2 or any(y < 2000 or y > 2100 for y in years): raise ValueError('Choose one or two years between 2000 and 2100')
    return years

def config(db, others=(), master=None):
    """Report settings of one fiscal-year file. 2.9.83: a shared part (information, texts, mapping) missing in this year
    is taken from the other years of the company, so what was entered once is never asked again.
    2.9.97: the auditor's details and logo come from the main file (the same for every company)."""
    cfg = json.loads(db.settings().get(KEY) or '{}')
    if master is not None:
        base = config(db, others)
        return _with_profile(base, master)
    for other in others or ():
        if other is None or other is db: continue
        try: theirs = json.loads(other.settings().get(KEY) or '{}')
        except Exception: continue
        for key in SHARED_KEYS:
            if not cfg.get(key) and theirs.get(key): cfg[key] = theirs[key]
    return cfg

def save_config(db, data, user_id, others=(), master=None):
    if not isinstance(data, dict): raise ValueError('Invalid financial report settings')
    data = dict(data); logo = data.pop('auditor_logo', None)
    if master is not None:  # 2.9.97: the auditor's details and logo are saved once, for every company
        save_auditor_profile(master, data.get('info') or {}, logo)
    if str(data.get('basis','USD')).upper() not in db.currency_codes(): raise ValueError('Choose a currency of the company')
    for field in ('mapping','supplements'):
        if not isinstance(data.get(field,{}),dict): raise ValueError('Invalid '+field)
    for code, group in data.get('mapping', {}).items():
        if not re.fullmatch(r'\d{1,12}', code) or group not in GROUPS: raise ValueError('Invalid account mapping')
    for name in ('notes', 'audit'):
        if not isinstance(data.get(name, {}), dict): raise ValueError('Invalid report text')
        for value in data.get(name, {}).values():
            if not isinstance(value, str) or len(value) > 20000: raise ValueError('Report text must be under 20,000 characters per section')
    for key, value in data.get('supplements', {}).items():
        if key not in SUPPLEMENTS: raise ValueError('Invalid supplementary amount')
        if value != '': number(value)
    info = data.get('info', {})
    if not isinstance(info, dict) or any(k not in INFO_FIELDS or not isinstance(v, str) or len(v) > 2000 for k, v in info.items()):
        raise ValueError('Invalid company / auditor information')
    _store(db, data, user_id)
    # 2.9.83: the information, texts and mapping are the company's: every other fiscal year gets them too
    # (the cash flow / OCI amounts and the currency stay with their own year).
    for other in others or ():
        if other is None or other is db: continue
        theirs = json.loads(other.settings().get(KEY) or '{}')
        theirs.update({key: data[key] for key in SHARED_KEYS if key in data})
        _store(other, theirs, user_id)
    return data


def _store(db, data, user_id):
    text = json.dumps(data, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY,text))
        conn.execute('INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)', (user_id,'update','financial_statement_draft',text,utcnow()))

def default_group(code, amount):
    # Lebanese chart; overrides can be applied to exact accounts or prefixes.
    if code.startswith(('21','281','291')): return 'intangible'
    if code.startswith(('22','23','282','283','292','293')): return 'ppe'
    if code.startswith('2'): return 'noncurrent_assets'
    if code.startswith('3'): return 'inventory'
    if code.startswith('10'): return 'capital'
    if code.startswith(('11','14')): return 'reserves'
    if code.startswith(('12','13')): return 'retained'
    if code.startswith(('15','16','17','18')): return 'noncurrent_liabilities'
    if code.startswith('49'): return 'receivables'
    if code.startswith('4'): return 'receivables' if amount >= 0 else 'payables'
    if code.startswith(('51','53')): return 'cash' if amount >= 0 else 'current_liabilities'
    if code.startswith('5'): return 'current_assets' if amount >= 0 else 'current_liabilities'
    if code.startswith(('70','71')): return 'revenue'
    if code.startswith('77'): return 'finance'
    if code.startswith('7'): return 'other_income'
    for prefix, group in [('60','materials'),('61','materials'),('62','services'),('63','staff'),('64','taxes'),('67','finance'),('65','depreciation'),('69','income_tax'),('6','other_expenses')]:
        if code.startswith(prefix): return group
    return 'unmapped'

# ---------------------------------------------------------------- 2.9.69: audit-report layout, two years or a period
CASH_GROUPS = ['cash']
WORKING = ['inventory', 'receivables', 'current_assets', 'payables', 'current_liabilities', 'unmapped']
INVESTING = ['ppe', 'intangible', 'noncurrent_assets']
FINANCING = ['capital', 'reserves', 'retained', 'noncurrent_liabilities']
LINE_TITLES = {'ppe': 'Property, plant and equipment', 'intangible': 'Intangible assets', 'noncurrent_assets': 'Other non-current assets',
               'inventory': 'Inventories', 'receivables': 'Trade and other receivables', 'cash': 'Cash and cash equivalents',
               'current_assets': 'Other current assets', 'capital': 'Share capital', 'reserves': 'Reserves', 'retained': 'Retained earnings',
               'noncurrent_liabilities': 'Non-current liabilities and provisions', 'payables': 'Trade and other payables',
               'current_liabilities': 'Other current liabilities', 'revenue': 'Revenue', 'other_income': 'Other income',
               'materials': 'Cost of materials and goods', 'services': 'External services', 'staff': 'Staff costs', 'taxes': 'Taxes and duties',
               'finance': 'Finance costs, net', 'depreciation': 'Depreciation and provisions', 'other_expenses': 'Other expenses',
               'income_tax': 'Income tax', 'unmapped': 'Accounts to classify'}


def _day(value):
    return iso_date(value)


def _fill(text, values):
    for key, value in values.items(): text = text.replace('{' + key + '}', str(value))
    return text


def _text(cfg, kind, name, defaults, values, language='en'):
    saved = (cfg.get(kind, {}) or {}).get(name)
    unchanged = saved is None or not str(saved).strip() or str(saved).strip() in OLD_DEFAULTS or str(saved).strip() in PREVIOUS_DEFAULTS \
        or str(saved).strip() == str(defaults[name]).strip()
    if unchanged:  # 2.9.109: the default text in the chosen language; a text the user rewrote is printed as written
        import financial_statements_i18n as i18n
        saved = (i18n.NARRATIVES if defaults is NARRATIVES else i18n.AUDIT).get(language, {}).get(name, defaults[name])
    return _fill(saved, values)


def load_period(db, start, end, basis):
    """Balances of one company-year file for the period start..end (inclusive), in `basis`.
    Returns opening and closing balances (balance-sheet accounts), the P&L of the period, the profit of the year before the period."""
    fy_start = end[:4] + '-01-01'
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("""SELECT j.*,a.code,a.name_en,a.name_fr,a.name_ar,e.entry_date,e.source_type,e.voucher_type,e.description entry_description,e.currency
          FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
          LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
          WHERE (e.source_type!='invoice' OR i.status IN ('posted','cancelled') OR i.status IS NULL)""")]
    closing = defaultdict(lambda: ZERO); opening = defaultdict(lambda: ZERO); pnl = defaultdict(lambda: ZERO); before = defaultdict(lambda: ZERO)
    names = {}; names_all = {}; count = 0
    for row in rows:
        day = _day(row['entry_date'])
        if day > end: continue
        if day >= fy_start and (row['source_type'] == 'year_close' or (row['voucher_type'] == '05' and (row['entry_description'] or '').startswith('CLOSING 6&7 - '))): continue
        code = row['code']; names[code] = row['name_en']; names_all[code] = {'en': row['name_en'], 'fr': row.get('name_fr'), 'ar': row.get('name_ar')}
        value = number(row['debit']) - number(row['credit'])
        if row['line_currency'] and row['amount'] not in (None, ''):
            stored = basis if basis in ('USD', 'LBP') else 'USD'
            raw = row['amount_usd'] if stored == 'USD' else row['amount_lbp']
            if raw in (None, ''): raise ValueError(f'Missing {stored} equivalent for account {code}, {day}')
            value = number(raw) * (1 if value >= 0 else -1)
            if stored != basis: value = db._converted_amount(value, 'USD', basis, day)
        elif row['currency'] != basis:
            value = db._converted_amount(value, row['currency'], basis, day)
        is_opening = day < fy_start or row['source_type'] == 'opening' or row['voucher_type'] == '04'
        if code[:1] in '67':
            if is_opening: continue  # profit of earlier years is already in retained earnings
            if day < start: before[code] += value
            else: pnl[code] += value; count += 1
            continue
        closing[code] += value
        if is_opening or day < start: opening[code] += value
        else: count += 1
    return dict(closing=closing, opening=opening, pnl=pnl, before=before, names=names, names_all=names_all, count=count)


def period_data(db, start, end, basis, label, cfg=None):
    cfg = config(db) if cfg is None else cfg; raw = load_period(db, start, end, basis); mapping = cfg.get('mapping', {})
    def group(code, value):
        found = [p for p in mapping if code.startswith(p)]
        return mapping[max(found, key=len)] if found else default_group(code, value)
    close_g = defaultdict(lambda: ZERO); open_g = defaultdict(lambda: ZERO); pnl_g = defaultdict(lambda: ZERO); accounts = defaultdict(dict)
    for code in sorted(set(raw['closing']) | set(raw['opening'])):
        g = group(code, raw['closing'][code])
        close_g[g] += raw['closing'][code]; open_g[group(code, raw['opening'][code])] += raw['opening'][code]
        if raw['closing'][code]: accounts[g][code] = (raw['names'][code], raw['closing'][code])
    for code in sorted(raw['pnl']):
        g = group(code, raw['pnl'][code]); pnl_g[g] += raw['pnl'][code]
        if raw['pnl'][code]: accounts[g][code] = (raw['names'][code], raw['pnl'][code])
    profit = -sum(raw['pnl'].values(), ZERO); profit_before = -sum(raw['before'].values(), ZERO)
    def delta(groups): return sum((close_g[g] - open_g[g] for g in groups), ZERO)
    # 2.9.84: the non-cash adjustment is the movement of the accumulated depreciation / amortisation (28, 29) and of the
    # provisions (15, e.g. end-of-service): they stay in operating activities instead of investing / financing.
    def moved(prefixes, groups):
        return sum((raw['closing'][c] - raw['opening'][c] for c in set(raw['closing']) | set(raw['opening'])
                    if c.startswith(prefixes) and group(c, raw['closing'][c]) in groups), ZERO)
    accumulated = moved(('28', '29'), INVESTING); provisions = moved(('15',), FINANCING)
    depreciation = -(accumulated + provisions)
    supplements = cfg.get('supplements', {}) if cfg.get('basis', basis) == basis else {}
    extra = {k: number(v) for k, v in supplements.items() if v != ''}
    cash_flow = {'profit': profit, 'depreciation': depreciation, 'depreciation_only': -accumulated, 'provisions': -provisions,
                 'working': {g: -(close_g[g] - open_g[g]) for g in WORKING},
                 'operating': profit + depreciation - delta(WORKING),
                 'investing': -(delta(INVESTING) - accumulated),
                 'financing': -(delta(FINANCING) - provisions)}
    reviewed = all(k in extra for k in ('cf_operating', 'cf_investing', 'cf_financing'))
    if reviewed:
        cash_flow.update(operating=extra['cf_operating'], investing=extra['cf_investing'], financing=extra['cf_financing'], fx=extra.get('cf_fx', ZERO))
    cash_flow['reviewed'] = reviewed
    equity_open = -sum((open_g[g] for g in EQUITY), ZERO) + profit_before
    equity_close = -sum((close_g[g] for g in EQUITY), ZERO) + profit_before + profit
    return dict(label=label, start=start, end=end, config=cfg, close=close_g, open=open_g, pnl=pnl_g, accounts=accounts, profit=profit,
                profit_before=profit_before, equity_open=equity_open, equity_close=equity_close, cash=cash_flow, extra=extra, count=raw['count'],
                names_all=raw.get('names_all', {}))


def periods_from(options, available_years):
    """[(year of the file, start, end, label)] - newest first. Two years: full calendar years. Period: From / As of
    (inside one fiscal year), and the same period one year before when asked and available."""
    if options.get('fs_mode') == 'period':
        start, end = _day(options.get('date_from')), _day(options.get('date_to'))
        if start > end: raise ValueError('From must be on or before As of')
        if start[:4] != end[:4]: raise ValueError('A period must stay inside one fiscal year (each year has its own books)')
        year = int(end[:4]); result = [(year, start, end, f'{start[8:]}-{start[5:7]} to {end[8:]}-{end[5:7]}-{end[:4]}')]
        if options.get('fs_compare') and (year - 1) in available_years:
            ps, pe = f'{year - 1}{start[4:]}', f'{year - 1}{end[4:]}'
            if pe[5:] == '02-29': pe = pe[:8] + '28'
            result.append((year - 1, ps, pe, f'{ps[8:]}-{ps[5:7]} to {pe[8:]}-{pe[5:7]}-{pe[:4]}'))
        return result
    return [(y, f'{y}-01-01', f'{y}-12-31', f'31-12-{y}') for y in years_from(options.get('years'))]


def info_values(cfg, settings):
    """2.9.83: the company / auditor information entered once; a field left empty shows as [its label] to complete."""
    info = dict(cfg.get('info') or {})
    if not str(info.get('tax_number') or '').strip() and settings.get('company_mof'): info['tax_number'] = settings['company_mof']
    return {key: (str(info.get(key) or '').strip() or f'[{label}]') for key, label in INFO_FIELDS.items()}


def build(databases, options, others=(), master=None):
    import financial_statements_i18n as i18n  # 2.9.109: English, French or Arabic
    language = str(options.get('language') or 'en').lower()[:2]
    if language not in i18n.LANGUAGES: language = 'en'
    t = i18n.translator(language); titles = {**LINE_TITLES, **i18n.LINE_TITLES.get(language, {})}
    basis = str(options.get('basis') or 'USD').upper()
    # 2.9.84: any currency of the company (EUR books...): lines are translated through their USD value at the entry date
    if basis not in ('USD', 'LBP') and not any(basis in d.currency_codes() for d in databases.values()):
        raise ValueError(f'{basis} is not a currency of the company')
    periods = periods_from(options, set(databases))
    missing = [str(y) for y, *_rest in periods if y not in databases]
    if missing: raise ValueError('Fiscal year not found: ' + ', '.join(missing))
    # 2.9.83: what is shared (information, texts, mapping) comes from any year of the company where it was entered
    pool = list(databases.values()) + [o for o in (others or ()) if o is not None]
    data = [period_data(databases[y], s, e, basis, label, config(databases[y], pool, master)) for y, s, e, label in periods]
    current = data[0]; settings = databases[periods[0][0]].settings(); cfg = current['config']
    company = settings.get('company_name') or '[Company name]'
    full_year = current['start'][5:] == '01-01' and current['end'][5:] == '12-31'
    end_text = f"{int(current['end'][8:])} {i18n.MONTHS[language][int(current['end'][5:7]) - 1]} {current['end'][:4]}"
    start_text = f"{current['start'][8:]}-{current['start'][5:7]}-{current['start'][:4]}"
    period_text = t('year') if full_year else t('period from {start}', start=start_text)
    for_period = t('for the year ended {end_text}', end_text=end_text) if full_year else t('for the period from {start} to {end_text}', start=start_text, end_text=end_text)
    values = {'company': company, 'end_text': end_text, 'period_text': period_text, 'basis': basis,
              'address_text': f", {settings['company_address']}" if settings.get('company_address') else '',
              'inventory_method': t('first-in first-out (FIFO)') if settings.get('inventory_method') == 'fifo' else t('weighted average cost')}
    values.update(info_values(cfg, settings))
    if language != 'en':  # 2.9.109: the Arabic company name for the Arabic report; what to complete in the report's language
        labels = i18n.INFO_LABELS.get(language, {})
        if language == 'ar' and str(settings.get('company_name_ar') or '').strip(): company = values['company'] = settings['company_name_ar'].strip()
        if language == 'ar' and str(settings.get('company_address_ar') or '').strip(): values['address_text'] = f"، {settings['company_address_ar'].strip()}"
        if company == '[Company name]': company = values['company'] = f"[{labels.get('company', 'Company name')}]"
        for key, label in INFO_FIELDS.items():
            if values.get(key) == f'[{label}]' and key in labels: values[key] = f'[{labels[key]}]'

    heads = [f"{d['label']} ({basis})" for d in data]
    as_at = [f"{d['end'][8:]}-{d['end'][5:7]}-{d['end'][:4]} ({basis})" for d in data]
    sections = []; warnings = []
    q = lambda v: money(v) if isinstance(v, Decimal) else v

    # ---- Independent auditor's report
    audit_rows = [[_text(cfg, 'audit', 'Addressee', AUDIT, values, language)]]
    for name, title in (('Opinion', 'Opinion'), ('Basis for opinion', 'Basis for Opinion'), ('Going concern / key audit matters', 'Key Audit Matters'),
                        ('Other information', 'Other Information'), ('Management and governance responsibilities',
                                'Responsibilities of Management and Those Charged with Governance for the Financial Statements'),
                        ('Auditor responsibilities', "Auditor's Responsibilities for the Audit of the Financial Statements"),
                        ('Other legal and regulatory requirements', 'Report on Other Legal and Regulatory Requirements'), ('Signature, address and report date', '')):
        text = _text(cfg, 'audit', name, AUDIT, values, language).strip()
        if not text: continue
        if title: audit_rows.append([t(title).upper()])
        audit_rows += [[line] for line in text.splitlines() if line.strip()]
    signature = [line for line in _text(cfg, 'audit', 'Signature, address and report date', AUDIT, values, language).splitlines() if line.strip()]
    if options.get('auditor_report', True) is False:  # 2.9.121: management financial statements - no auditor's report at all
        audit_rows = None
    if audit_rows is not None:
        sections.append(dict(kind='audit', heading=t("INDEPENDENT AUDITOR'S REPORT"), headers=['Text'], rows=audit_rows, total_rows=[], narrative=True, page_break=True, center=True,
                         keep_last=len(signature), logo_b64=cfg.get('auditor_logo') or ''))  # 2.9.97: the auditor's logo on top of his report

    # ---- note numbers for the statement lines that have amounts
    note_no = {}; next_note = [5]
    def note_for(group):
        if not any(d['accounts'].get(group) for d in data): return ''
        if group not in note_no: note_no[group] = next_note[0]; next_note[0] += 1
        return str(note_no[group])
    sign = lambda g: -1 if g in EQUITY + LIABILITIES + INCOME else 1

    # ---- Statement of financial position
    rows = []; totals = []
    def line(label, fn, total=False, note=''):
        rows.append([t(label), note] + [q(fn(d)) for d in data])
        if total: totals.append(len(rows) - 1)
    def heading(label): rows.append([t(label), ''] + ['' for _ in data])
    heading('ASSETS'); heading('Non-current assets')
    for g in ['ppe', 'intangible', 'noncurrent_assets']:
        if any(d['close'][g] for d in data): line(titles[g], lambda d, g=g: d['close'][g], note=note_for(g))
    line('Total non-current assets', lambda d: sum((d['close'][g] for g in ['ppe', 'intangible', 'noncurrent_assets']), ZERO), True)
    heading('Current assets')
    for g in ['inventory', 'receivables', 'current_assets', 'cash']:
        if any(d['close'][g] for d in data): line(titles[g], lambda d, g=g: d['close'][g], note=note_for(g))
    line('Total current assets', lambda d: sum((d['close'][g] for g in ['inventory', 'receivables', 'current_assets', 'cash']), ZERO), True)
    line('TOTAL ASSETS', lambda d: sum((d['close'][g] for g in ASSETS), ZERO), True)
    heading('EQUITY AND LIABILITIES'); heading('Equity')
    for g in EQUITY:
        if any(d['close'][g] for d in data): line(titles[g], lambda d, g=g: -d['close'][g], note=note_for(g))
    line('Profit for the year' if full_year else 'Profit for the year to date', lambda d: d['profit'] + d['profit_before'])
    line('Total equity', lambda d: d['equity_close'], True)
    heading('Liabilities')
    for g in LIABILITIES:
        if any(d['close'][g] for d in data): line(titles[g], lambda d, g=g: -d['close'][g], note=note_for(g))
    line('Total liabilities', lambda d: -sum((d['close'][g] for g in LIABILITIES), ZERO), True)
    line('TOTAL EQUITY AND LIABILITIES', lambda d: d['equity_close'] - sum((d['close'][g] for g in LIABILITIES), ZERO), True)
    if any(abs(d['close']['unmapped']) >= Decimal('.01') for d in data):
        line(titles['unmapped'] + t(' (see review points)'), lambda d: d['close']['unmapped'], note=note_for('unmapped'))
    sections.append(dict(kind='position', heading=t('STATEMENT OF FINANCIAL POSITION as at {end_text}', end_text=end_text),
                         headers=['', t('Notes')] + as_at, rows=rows, total_rows=totals, page_break=True, fixed=True, center=True))

    # ---- Statement of profit or loss
    rows = []; totals = []
    for g in INCOME:
        if any(d['pnl'][g] for d in data): line(titles[g], lambda d, g=g: -d['pnl'][g], note=note_for(g))
    line('Total income', lambda d: -sum((d['pnl'][g] for g in INCOME), ZERO), True)
    for g in EXPENSES:
        if g != 'income_tax' and any(d['pnl'][g] for d in data): line(titles[g], lambda d, g=g: -d['pnl'][g], note=note_for(g))
    line('Profit / (loss) before tax', lambda d: d['profit'] + d['pnl']['income_tax'], True)
    if any(d['pnl']['income_tax'] for d in data): line(titles['income_tax'], lambda d: -d['pnl']['income_tax'], note=note_for('income_tax'))
    line('PROFIT / (LOSS) FOR THE YEAR' if full_year else 'PROFIT / (LOSS) FOR THE PERIOD', lambda d: d['profit'], True)
    line('Other comprehensive income', lambda d: d['extra'].get('oci', ZERO))
    line('TOTAL COMPREHENSIVE INCOME', lambda d: d['profit'] + d['extra'].get('oci', ZERO), True)
    sections.append(dict(kind='profit', heading=t("STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME {for_period}", for_period=for_period),
                         headers=['', t('Notes')] + heads, rows=rows, total_rows=totals, page_break=True, fixed=True, center=True))

    # ---- Statement of changes in equity (oldest period first)
    rows = []; totals = []
    for d in reversed(data):
        open_c = {g: -d['open'][g] for g in EQUITY}; close_c = {g: -d['close'][g] for g in EQUITY}
        open_c['retained'] += d['profit_before']; close_c['retained'] += d['profit_before']
        rows.append([t("Balance at start ({date})", date=f"{d['start'][8:]}-{d['start'][5:7]}-{d['start'][:4]}")] + [q(open_c[g]) for g in EQUITY] + [q(d['equity_open'])])
        rows.append([t('Profit / (loss) for the period')] + [ZERO, ZERO, q(d['profit'])] + [q(d['profit'])])
        movement = {g: close_c[g] - open_c[g] for g in EQUITY}
        if any(movement[g] for g in EQUITY):
            rows.append([t('Capital movements, dividends and transfers')] + [q(movement[g]) for g in EQUITY] + [q(sum(movement.values(), ZERO))])
        close_c['retained'] += d['profit']
        rows.append([t("Balance at end ({date})", date=f"{d['end'][8:]}-{d['end'][5:7]}-{d['end'][:4]}")] + [q(close_c[g]) for g in EQUITY] + [q(d['equity_close'])])
        totals.append(len(rows) - 1)
    sections.append(dict(kind='equity', heading=t('STATEMENT OF CHANGES IN EQUITY ({basis})', basis=basis),
                         headers=['', t('Share capital'), t('Reserves'), t('Retained earnings'), t('Total')],
                         rows=rows, total_rows=totals, page_break=True, fixed=True, center=True))

    # ---- Statement of cash flows (indirect method)
    rows = []; totals = []
    heading('CASH FLOWS FROM OPERATING ACTIVITIES')
    line('Profit / (loss) for the period', lambda d: d['cash']['profit'])
    line('Adjustment: depreciation and amortisation', lambda d: d['cash']['depreciation_only'])
    if any(d['cash']['provisions'] for d in data):
        line('Adjustment: movement in provisions (end of service and others)', lambda d: d['cash']['provisions'])
    for g in WORKING:
        if any(d['cash']['working'][g] for d in data):
            label = {'inventory': '(Increase) / decrease in inventories', 'receivables': '(Increase) / decrease in trade and other receivables',
                     'current_assets': '(Increase) / decrease in other current assets', 'payables': 'Increase / (decrease) in trade and other payables',
                     'current_liabilities': 'Increase / (decrease) in other current liabilities', 'unmapped': 'Movement in accounts to classify'}[g]
            line(label, lambda d, g=g: d['cash']['working'][g])
    line('Net cash from operating activities', lambda d: d['cash']['operating'], True)
    heading('CASH FLOWS FROM INVESTING ACTIVITIES')
    line('Acquisition / (disposal) of non-current assets, net', lambda d: d['cash']['investing'])
    line('Net cash used in investing activities', lambda d: d['cash']['investing'], True)
    heading('CASH FLOWS FROM FINANCING ACTIVITIES')
    line('Capital, borrowings and dividends, net', lambda d: d['cash']['financing'])
    line('Net cash from financing activities', lambda d: d['cash']['financing'], True)
    line('NET INCREASE / (DECREASE) IN CASH', lambda d: d['cash']['operating'] + d['cash']['investing'] + d['cash']['financing'] + d['cash'].get('fx', ZERO), True)
    line('Cash and cash equivalents at start', lambda d: d['open']['cash'])
    line('CASH AND CASH EQUIVALENTS AT END', lambda d: d['close']['cash'], True)
    sections.append(dict(kind='cash', heading=t('STATEMENT OF CASH FLOWS {for_period}', for_period=for_period),
                         headers=['', ''] + heads, rows=rows, total_rows=totals, page_break=True, fixed=True, center=True))

    # ---- Notes
    notes = [('1. GENERAL INFORMATION', 'Entity and activities'), ('2. BASIS OF PREPARATION', 'Basis of preparation'),
             ('3. MATERIAL ACCOUNTING POLICIES', 'Material accounting policies'), ('4. JUDGEMENTS AND ESTIMATES', 'Judgements and estimates')]
    first = True
    for title, name in notes:
        sections.append(dict(kind='notes_start' if first else 'notes', heading=t('NOTES TO THE FINANCIAL STATEMENTS - ') + t(title) if first else t(title),
                             headers=[t('Text')],
                             rows=[[p] for p in _text(cfg, 'notes', name, NARRATIVES, values, language).splitlines() if p.strip()], total_rows=[], narrative=True, page_break=first))
        first = False
    for group, number_ in sorted(note_no.items(), key=lambda item: item[1]):
        codes = sorted(set().union(*(d['accounts'].get(group, {}).keys() for d in data)))
        rows = []
        for code in codes:
            name = next((d['accounts'][group][code][0] for d in data if code in d['accounts'].get(group, {})), '')
            name = next((d['names_all'].get(code, {}).get(language) for d in data if d.get('names_all', {}).get(code, {}).get(language)), None) or name
            # 2.9.71: the notes of the audit report show the account names only (no account numbers)
            rows.append([name or code] + [q(sign(group) * d['accounts'].get(group, {}).get(code, ('', ZERO))[1]) for d in data])
        rows.append([t('TOTAL')] + [q(sign(group) * (d['close'][group] if group in ASSETS + EQUITY + LIABILITIES + ['unmapped'] else d['pnl'][group])) for d in data])
        sections.append(dict(kind='notes', heading=f'{number_}. {titles[group].upper()}', headers=[t('Description')] + heads, rows=rows, total_rows=[len(rows) - 1], fixed=True))
        if group == 'capital':  # 2.9.83: the share capital details under its account table
            sections.append(dict(kind='notes', heading='', headers=[t('Text')], rows=[[p] for p in _text(cfg, 'notes', 'Share capital', NARRATIVES, values, language).splitlines()
                                                                         if p.strip()],
                                 total_rows=[], narrative=True))
    n = next_note[0]
    for name in ('Share capital', 'Income tax', 'Currency and inflation', 'Financial risk management', 'Related parties and commitments',
                 'Events and going concern', 'Additional disclosures', 'Approval of the financial statements'):
        if name == 'Share capital' and 'capital' in note_no: continue  # already under the share capital note
        text = _text(cfg, 'notes', name, NARRATIVES, values, language)
        sections.append(dict(kind='notes', heading=f'{n}. {t(name).upper()}', headers=[t('Text')], rows=[[p] for p in text.splitlines() if p.strip()], total_rows=[], narrative=True)); n += 1

    # ---- review points for the preparer (last page, remove before issue)
    for d in data:
        difference = sum((d['close'][g] for g in ASSETS + LIABILITIES), ZERO) - d['equity_close']
        if abs(difference) >= Decimal('.01'): warnings.append(f"{d['label']}: the statement of financial position does not balance ({money(difference)} {basis}) - check classifications.")
        if abs(d['close']['unmapped']) >= Decimal('.01') or d['pnl']['unmapped']: warnings.append(f"{d['label']}: accounts to classify ({money(d['close']['unmapped'] + d['pnl']['unmapped'])} {basis}) - Edit Notes / Audit / Mapping.")
        if not d['count']: warnings.append(f"{d['label']}: no posted movements in the period.")
        if not d['cash']['reviewed']: warnings.append(f"{d['label']}: cash flows are calculated from the balance sheet movements (indirect method); review the classification of investing and financing items.")
    if len(data) == 1: warnings.append('Single period: IAS 1 requires comparative figures for the preceding period.')
    if audit_rows is not None: warnings.append("The auditor's report is a template: the auditor completes and signs it after the audit. Remove this page before issuing.")
    sections.append(dict(kind='review', heading='PREPARER REVIEW POINTS (remove before issue)', headers=['Point'], rows=[[w] for w in warnings], total_rows=[], narrative=True, page_break=True))
    for key, label in INFO_FIELDS.items():
        if values[key] in (f'[{label}]', f"[{i18n.INFO_LABELS.get(language, {}).get(key, label)}]") and key not in ('tax_number',):
            warnings.insert(0, f'Company & auditor information not entered: {label} (Edit Texts > Company & Auditor).'); break
    sections[-1]['rows'] = [[w] for w in warnings]
    meta = [company, t('Year ended ' if full_year else 'Period ended ') + end_text + t(' - with comparative figures') * (len(data) > 1),
            t('Presentation currency: {basis}', basis=basis)]
    firm = str((cfg.get('info') or {}).get('auditor_firm') or '').strip()
    if firm and audit_rows is not None: meta.append(t('Auditor: {firm}', firm=firm))  # 2.9.121: management accounts name no auditor
    title = t('Financial Statements, Notes and Audit Report') if audit_rows is not None else t('Financial Statements and Notes')  # 2.9.121
    return dict(title=title, meta=meta, sections=sections, language=language, rtl=language == 'ar')


def year_data(db, year, basis):
    """Full calendar year (kept for older callers): period_data plus equity_start / equity_end."""
    data = period_data(db, f'{int(year)}-01-01', f'{int(year)}-12-31', basis, f'31-12-{int(year)}')
    data.update(equity_start=data['equity_open'], equity_end=data['equity_close'], totals=data['close'])
    return data
