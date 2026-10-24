"""2.9.116: charts of accounts to choose from when a company is created (Lebanon, IFRS, Saudi Arabia, UAE).

Every chart keeps the same numbering by class (1 equity and long-term debts, 2 fixed assets, 3 inventory,
4 third parties, 5 cash, 6 expenses, 7 income): the VAT return, the ledgers, the financial statements, payroll and the
automatic entries find the accounts they post to in every chart, so every feature works with every chart.
What changes from one chart to another: the names (IFRS wording in English, Arabic and French) and the accounts the
country needs (VAT 15% and Zakat in Saudi Arabia, VAT 5% and Corporate Tax in the UAE, IFRS 9 / 16 accounts...).

- "lebanon" is the Lebanese chart exactly as before (Decision 111/1, 572 accounts): a Lebanese company sees no change.
- Other charts start from the SPINE (the class headings and every account the program posts to) and add their own.
- A company keeps its chart; more accounts are added in Chart of Accounts (one by one, or from Excel).
"""
from __future__ import annotations

import sqlite3

from lebanese_accounts import LEBANESE_ACCOUNTS

# The accounts the program itself uses (and the headings above them). A test checks that every account number written
# in the program is here, so a new feature cannot post to an account a non-Lebanese chart does not have.
SPINE = (
    "1", "10", "11", "12", "13", "138", "139", "14", "15", "155", "1552", "1552.1", "16", "18", "2", "21", "22",
    "25", "251", "28", "281", "282", "29", "291", "292", "3", "31", "33", "35", "37", "39", "4", "40", "401",
    "4011", "403", "4031", "41", "411", "4111", "42", "4211", "43", "438", "44", "4411", "442", "4425", "4426.2", "4426.6", "4427",
    "4429", "443", "4431", "45", "46", "4619", "47", "48", "49", "5", "51", "511", "512", "519", "53", "531", "6",
    "60", "6011", "605", "6051", "6052", "61", "615", "6151", "6152", "62", "626", "6261.1", "6261.5", "6262", "6263.1",
    "6263.3", "6263.4", "6264.1", "6264.2", "6265.2", "6265.3", "6266.2", "6268", "6269.3", "6269.4", "63", "631", "6311",
    "6312", "6316", "6351", "6355", "64", "645", "6459", "65", "66", "67", "673", "6739", "675", "6751", "68", "681", "6811", "6812", "69",
    "7", "70", "701", "709", "71", "711", "713", "72", "7211", "725", "7255", "73", "75", "755", "7552.2", "77",
    "7751", "78", "781", "7811", "7812", "8", "80",  # 2.9.132: 681x / 781x for asset disposals (IAS 16)
)


TEMPLATES = {
    "lebanon": {"label": "Lebanon - Lebanese chart (PCGL, Decision 111/1)", "country": "Lebanon",
                "currencies": ("USD", "LBP"), "vat_rate": "11", "vat_currencies": ("LBP", "USD")},
    "ifrs": {"label": "International - IFRS chart", "country": "International",
             "currencies": ("USD", "EUR"), "vat_rate": "0", "vat_currencies": ("USD", "EUR")},
    "ksa": {"label": "Saudi Arabia - IFRS chart with VAT 15%, Zakat and GOSI", "country": "Saudi Arabia",
            "currencies": ("SAR", "USD"), "vat_rate": "15", "vat_currencies": ("SAR", "USD")},
    "uae": {"label": "United Arab Emirates - IFRS chart with VAT 5% and Corporate Tax", "country": "United Arab Emirates",
            "currencies": ("AED", "USD"), "vat_rate": "5", "vat_currencies": ("AED", "USD")},
}
DEFAULT = "lebanon"

# IFRS wording for the main accounts (English, Arabic, French), used by every chart except the Lebanese one.
IFRS_NAMES = {
    "1": ("Equity and Non-current Liabilities", "حقوق الملكية والمطلوبات غير المتداولة", "Capitaux propres et passifs non courants"),
    "10": ("Share Capital", "رأس المال", "Capital social"),
    "11": ("Reserves", "الاحتياطيات", "Réserves"),
    "12": ("Retained Earnings", "الأرباح المدورة", "Résultats reportés"),
    "13": ("Profit or Loss for the Year", "ربح أو خسارة السنة", "Résultat de l'exercice"),
    "15": ("Provisions", "المخصصات", "Provisions"),
    "1552.1": ("Employee End-of-Service Benefits", "مخصص مكافأة نهاية الخدمة", "Indemnités de fin de service"),
    "16": ("Borrowings - Non-current", "القروض غير المتداولة", "Emprunts non courants"),
    "2": ("Non-current Assets", "الموجودات غير المتداولة", "Actifs non courants"),
    "21": ("Intangible Assets", "الموجودات غير الملموسة", "Immobilisations incorporelles"),
    "22": ("Property, Plant and Equipment", "الممتلكات والآلات والمعدات", "Immobilisations corporelles"),
    "25": ("Financial Assets - Non-current", "الموجودات المالية غير المتداولة", "Actifs financiers non courants"),
    "28": ("Accumulated Depreciation and Amortisation", "الاستهلاكات والإطفاءات المتراكمة", "Amortissements cumulés"),
    "29": ("Impairment of Non-current Assets", "انخفاض قيمة الموجودات غير المتداولة", "Dépréciation des actifs non courants"),
    "3": ("Inventories", "المخزون", "Stocks"),
    "37": ("Inventory - Goods for Resale", "مخزون البضائع المعدة للبيع", "Stock de marchandises"),
    "4": ("Receivables and Payables", "الذمم المدينة والدائنة", "Créances et dettes"),
    "40": ("Trade Payables", "الذمم الدائنة التجارية", "Fournisseurs"),
    "41": ("Trade Receivables", "الذمم المدينة التجارية", "Clients"),
    "42": ("Employees", "الموظفون", "Personnel"),
    "44": ("Taxes and Government", "الضرائب والجهات الحكومية", "État et collectivités"),
    "47": ("Prepayments and Accruals", "المصاريف المدفوعة مقدماً والمستحقات", "Charges constatées d'avance et à payer"),
    "5": ("Cash and Cash Equivalents", "النقد وما يعادله", "Trésorerie et équivalents"),
    "512": ("Bank Accounts", "الحسابات المصرفية", "Banques"),
    "531": ("Cash on Hand", "النقد في الصندوق", "Caisse"),
    "6": ("Expenses", "المصاريف", "Charges"),
    "60": ("Cost of Goods Sold and Purchases", "تكلفة البضاعة المباعة والمشتريات", "Achats et variation de stocks"),
    "63": ("Employee Benefits Expense", "مصاريف الموظفين", "Charges de personnel"),
    "65": ("Depreciation, Amortisation and Impairment", "الاستهلاكات والإطفاءات وانخفاض القيمة", "Dotations aux amortissements et dépréciations"),
    "67": ("Finance Costs", "تكاليف التمويل", "Charges financières"),
    "69": ("Income Tax Expense", "مصروف ضريبة الدخل", "Impôt sur le résultat"),
    "7": ("Revenue and Other Income", "الإيرادات والدخل الآخر", "Produits"),
    "70": ("Revenue from Sale of Goods", "إيرادات بيع البضائع", "Ventes de marchandises"),
    "71": ("Revenue from Services and Production", "إيرادات الخدمات والإنتاج", "Prestations de services et production"),
    "77": ("Finance Income", "إيرادات التمويل", "Produits financiers"),
}
IFRS_ACCOUNTS = [  # code, English, Arabic, French, type, parent
    ("226000001", "Right-of-Use Assets (IFRS 16)", "موجودات حق الاستخدام", "Actifs au titre du droit d'utilisation", "asset", "22"),
    ("168100001", "Lease Liabilities (IFRS 16)", "مطلوبات عقود الإيجار", "Dettes locatives", "equity", "16"),
    ("491100001", "Expected Credit Loss Allowance (IFRS 9)", "مخصص الخسائر الائتمانية المتوقعة", "Provision pour pertes de crédit attendues", "asset", "49"),
    ("443200001", "Deferred Tax (IAS 12)", "الضريبة المؤجلة", "Impôt différé", "asset", "443"),
]
COUNTRY = {
    "ifrs": {"names": {}, "accounts": []},
    "ksa": {
        "names": {
            "43": ("Social Insurance (GOSI)", "التأمينات الاجتماعية", "Assurances sociales (GOSI)"),
            "6351": ("Social Insurance Contributions (GOSI)", "اشتراكات التأمينات الاجتماعية", "Cotisations GOSI"),
            "1552.1": ("End-of-Service Benefits (Saudi Labour Law)", "مكافأة نهاية الخدمة (نظام العمل السعودي)", "Indemnités de fin de service"),
            "69": ("Zakat and Income Tax", "الزكاة وضريبة الدخل", "Zakat et impôt sur le résultat"),
        },
        "accounts": [
            ("442700015", "Output VAT 15% (ZATCA)", "ضريبة القيمة المضافة على المبيعات 15%", "TVA collectée 15%", "liability", "4427"),
            ("442660015", "Input VAT 15% (ZATCA)", "ضريبة القيمة المضافة على المشتريات 15%", "TVA déductible 15%", "asset", "4426.6"),
            ("443300001", "Zakat Payable", "الزكاة المستحقة", "Zakat à payer", "asset", "443"),
            ("695000001", "Zakat Expense", "مصروف الزكاة", "Charge de zakat", "expense", "69"),
            ("431100001", "GOSI Payable", "التأمينات الاجتماعية المستحقة", "GOSI à payer", "asset", "43"),
            ("635200001", "GOSI Contributions - Employer", "اشتراكات التأمينات - حصة صاحب العمل", "Cotisations GOSI - employeur", "expense", "63"),
            ("441200001", "Withholding Tax Payable", "ضريبة الاستقطاع المستحقة", "Retenue à la source à payer", "asset", "44"),
        ],
    },
    "uae": {
        "names": {
            "43": ("Pension Contributions (GPSSA)", "اشتراكات المعاشات والتأمينات", "Cotisations de retraite (GPSSA)"),
            "1552.1": ("End-of-Service Gratuity (UAE Labour Law)", "مكافأة نهاية الخدمة (قانون العمل الإماراتي)", "Indemnité de fin de service"),
            "69": ("Corporate Tax Expense", "مصروف ضريبة الشركات", "Impôt sur les sociétés"),
        },
        "accounts": [
            ("442700005", "Output VAT 5% (FTA)", "ضريبة القيمة المضافة على المبيعات 5%", "TVA collectée 5%", "liability", "4427"),
            ("442660005", "Input VAT 5% (FTA)", "ضريبة القيمة المضافة على المشتريات 5%", "TVA déductible 5%", "asset", "4426.6"),
            ("443400001", "Corporate Tax Payable (9%)", "ضريبة الشركات المستحقة (9%)", "Impôt sur les sociétés à payer (9%)", "asset", "443"),
            ("696000001", "Corporate Tax Expense (9%)", "مصروف ضريبة الشركات (9%)", "Charge d'impôt sur les sociétés (9%)", "expense", "69"),
            ("431200001", "Pension Contributions Payable (GPSSA)", "اشتراكات المعاشات المستحقة", "Cotisations de retraite à payer", "asset", "43"),
        ],
    },
}


def choices():
    """[(key, label)] in the order they are offered."""
    return [(key, spec["label"]) for key, spec in TEMPLATES.items()]


def template_key(value):
    value = str(value or "").strip().lower()
    for key, spec in TEMPLATES.items():
        if value in (key, spec["label"].lower()): return key
    return DEFAULT


def rows(template):
    """Every account of the chart: [(code, English, Arabic, French, type, parent code)], parents before children."""
    template = template_key(template)
    if template == "lebanon": return [tuple(r) for r in LEBANESE_ACCOUNTS]
    keep = set(SPINE); names = {**IFRS_NAMES, **COUNTRY[template]["names"]}; result = []
    for code, en, ar, fr, kind, parent in LEBANESE_ACCOUNTS:
        if code not in keep: continue
        en, ar, fr = names.get(code, (en, ar, fr))
        result.append((code, en, ar, fr, kind, parent))
    return result + list(IFRS_ACCOUNTS) + list(COUNTRY[template]["accounts"])


def current(connection):
    """The chart of a company file (an open sqlite connection); '' / missing = the Lebanese chart."""
    try: row = connection.execute("SELECT value FROM app_settings WHERE key='chart_template'").fetchone()
    except sqlite3.Error: return DEFAULT  # a file older than the settings table
    return template_key(row[0] if row else "")


def ensure(connection, template):
    """Add the chart's accounts that are missing (an upgrade). Names a user changed are kept; nothing is removed."""
    chart = rows(template)
    connection.executemany("INSERT INTO accounts(code,name_en,name_ar,name_fr,type) VALUES(?,?,?,?,?) ON CONFLICT(code) DO NOTHING",
                           [row[:5] for row in chart])
    for code, *_rest, parent in chart:
        if parent:
            connection.execute("UPDATE accounts SET parent_id=(SELECT id FROM accounts WHERE code=?) WHERE code=? AND parent_id IS NULL", (parent, code))


def apply(database, template):
    """Give a NEW company its chart (right after it was created with the standard chart). Lebanese accounts that the
    chart does not use are removed while nothing posts to them; the program's own accounts and their headings stay."""
    template = template_key(template)
    with database.connect() as db:
        db.execute("INSERT INTO app_settings(key,value) VALUES('chart_template',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (template,))
        if template == "lebanon": return template
        chart = rows(template); wanted = {r[0] for r in chart}; lebanese = {r[0] for r in LEBANESE_ACCOUNTS}
        accounts = {r["id"]: (r["code"], r["parent_id"]) for r in db.execute("SELECT id, code, parent_id FROM accounts")}
        keep_ids = {i for i, (code, _p) in accounts.items() if code in wanted or code not in lebanese}
        for i in list(keep_ids):  # the headings above every account kept
            parent = accounts[i][1]
            while parent and parent in accounts and parent not in keep_ids: keep_ids.add(parent); parent = accounts[parent][1]
        used = {r[0] for r in db.execute("SELECT DISTINCT account_id FROM journal_lines")}
        drop = [i for i in accounts if i not in keep_ids and i not in used]
        if drop:
            marks = ",".join("?" * len(drop))
            db.execute(f"UPDATE accounts SET parent_id=NULL WHERE id IN ({marks})", drop)
            db.execute(f"DELETE FROM accounts WHERE id IN ({marks})", drop)
        for code, en, ar, fr, kind, _parent in chart:
            db.execute("UPDATE accounts SET name_en=?, name_ar=?, name_fr=? WHERE code=?", (en, ar, fr, code))
        ensure(db, template)
    return template


# ---------------------------------------------------------------- chart from Excel (Chart of Accounts > Import from Excel)
HEADINGS = {"code": ("account", "code", "account no", "account number", "رقم الحساب"), "parent": ("parent", "parent code", "parent account"),
            "name_en": ("english", "name", "name en", "english name", "account name"), "name_fr": ("french", "name fr", "french name"),
            "name_ar": ("arabic", "name ar", "arabic name", "اسم الحساب"), "type": ("type", "account type")}
TYPES = {"asset": "asset", "assets": "asset", "liability": "liability", "liabilities": "liability", "equity": "equity",
         "income": "income", "revenue": "income", "expense": "expense", "expenses": "expense"}


def read_excel(path):
    """Rows of an Excel file with a heading row: Account, Parent, English, French, Arabic, Type (the Chart of Accounts
    table exported to Excel has exactly these). Returns [{code, parent, name_en, name_fr, name_ar, type}]."""
    from openpyxl import load_workbook
    sheet = load_workbook(path, read_only=True, data_only=True).active
    columns = None; found = []
    for values in sheet.iter_rows(values_only=True):
        cells = [str(v).strip() if v is not None else "" for v in values]
        if columns is None:
            lowered = [c.lower() for c in cells]
            guess = {key: next((i for i, c in enumerate(lowered) if c in names), None) for key, names in HEADINGS.items()}
            if guess["code"] is not None and guess["name_en"] is not None: columns = guess
            continue
        item = {key: (cells[i] if i is not None and i < len(cells) else "") for key, i in columns.items()}
        if item["code"].endswith(".0") and item["code"][:-2].isdigit(): item["code"] = item["code"][:-2]
        if item["parent"].endswith(".0") and item["parent"][:-2].isdigit(): item["parent"] = item["parent"][:-2]
        if item["code"]: found.append(item)
    if columns is None: raise ValueError("The first row must name the columns: Account, Parent, English, French, Arabic, Type")
    return found


def import_accounts(database, items, user_id):
    """Add the accounts of the list and fill in the names of accounts already there. Nothing is deleted, and the type of an
    account already used in entries is never changed. Returns {added, updated, skipped: [reasons]}."""
    import json
    from database_common import utcnow
    added = updated = 0; skipped = []
    with database.connect() as db:
        known = {r["code"]: dict(r) for r in db.execute("SELECT id, code, type FROM accounts")}
        used = {r[0] for r in db.execute("SELECT DISTINCT account_id FROM journal_lines")}
        pending = list(items)
        for _round in range(len(pending) + 1):  # parents first, whatever the order of the file
            later = []
            for item in pending:
                code = str(item.get("code") or "").strip(); parent = str(item.get("parent") or "").strip()
                kind = TYPES.get(str(item.get("type") or "").strip().lower(), "")
                if not code or len(code) > 20 or not all(ch.isdigit() or ch == "." for ch in code): skipped.append(f"{code or '(empty)'}: the account number must be digits"); continue
                if code in known:
                    row = known[code]; changes = {k: str(item.get(k) or "").strip() for k in ("name_en", "name_ar", "name_fr") if str(item.get(k) or "").strip()}
                    if kind and kind != row["type"] and row["id"] not in used: changes["type"] = kind
                    if changes:
                        db.execute(f"UPDATE accounts SET {', '.join(k + '=?' for k in changes)} WHERE code=?", (*changes.values(), code)); updated += 1
                    continue
                if parent and parent not in known: later.append(item); continue
                name = str(item.get("name_en") or "").strip()
                if not name: skipped.append(f"{code}: the English name is missing"); continue
                if not kind: kind = known[parent]["type"] if parent else ""
                if not kind: skipped.append(f"{code}: choose a type (asset, liability, equity, income, expense)"); continue
                cursor = db.execute("INSERT INTO accounts(code,name_en,name_ar,name_fr,type,parent_id) VALUES(?,?,?,?,?,?)",
                                    (code, name, str(item.get("name_ar") or "").strip() or None, str(item.get("name_fr") or "").strip() or None, kind,
                                     known[parent]["id"] if parent else None))
                known[code] = {"id": cursor.lastrowid, "code": code, "type": kind}; added += 1
            if len(later) == len(pending): break
            pending = later
        skipped += [f"{i.get('code')}: parent {i.get('parent')} was not found" for i in later]
        db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                   (user_id, "import", "accounts", json.dumps({"added": added, "updated": updated, "skipped": len(skipped)}), utcnow()))
    return {"added": added, "updated": updated, "skipped": skipped}
