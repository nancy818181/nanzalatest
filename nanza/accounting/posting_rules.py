"""2.9.120: the program learns how the accountant posts each supplier's invoices - free, on this computer, no internet.

1. Posting rules (as the "rules" of Zoho / QuickBooks): when a purchase invoice (Purchases screen) or an expense is saved, the
   way it was posted is remembered for that supplier - cost / asset account, VAT account, Purchases or Assets, VAT use,
   reverse charge, department / project, how it was paid and from which account, "not deductible for income tax".
   The next invoice of the same supplier (found by its MOF / VAT number, or its name) is filled in the same way.
2. Classification of the lines: every word of the lines saved votes for the account they were posted to; a new invoice's
   lines get the account most used for the same words. When nothing was learned yet, the keywords of the categories
   (electricity, rent, fuel ...) and then the names of the chart of accounts are used.

Only suggestions: the accountant sees them (with where they come from and how sure they are) and saves. Settings > Accounting
Settings > Posting rules lists what was learned; any rule can be deleted.
"""
from __future__ import annotations

import json
import re
import sqlite3

from database_common import utcnow

SCOPES = ("purchase", "expense")
LEGAL_WORDS = {"sarl", "sal", "s", "a", "l", "sa", "llc", "ltd", "co", "company", "est", "establishment", "group", "holding", "the", "and",
               "ش", "م", "ل", "شركة", "مؤسسة"}
STOP_WORDS = {"the", "and", "for", "with", "from", "of", "to", "in", "on", "per", "unit", "pcs", "piece", "pieces", "box", "kg", "total", "invoice",
              "item", "items", "qty", "service", "services", "vat", "tva", "lbp", "usd", "eur"}


def migrate(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS posting_rules(id INTEGER PRIMARY KEY, scope TEXT NOT NULL, key TEXT NOT NULL, label TEXT,
        data TEXT NOT NULL, times INTEGER NOT NULL DEFAULT 1, last_reference TEXT, last_date TEXT, updated_at TEXT NOT NULL, UNIQUE(scope, key))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS line_memory(token TEXT NOT NULL, account TEXT NOT NULL, times INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(token, account))""")


# ---------------------------------------------------------------- keys and words
def name_key(name):
    text = str(name or "").casefold().replace(".", "")  # S.A.R.L. = SARL
    words = [w for w in re.findall(r"\w+", text) if w not in LEGAL_WORDS and not w.isdigit()]
    return "name:" + " ".join(words) if words else ""


def number_key(number):
    """MOF 123456-601 (the VAT suffix) and 123456 are the same supplier."""
    text = str(number or "").strip()
    main = re.fullmatch(r"(\d{4,})\s*-\s*\d{1,4}", text)
    digits = main.group(1) if main else re.sub(r"\D", "", text)
    return f"mof:{digits}" if len(digits) >= 4 else ""


def keys_for(name=None, number=None):
    """Number keys first (one or several numbers, comma separated - a PDF shows the buyer's number too), then the name."""
    numbers = [number_key(n) for n in str(number or "").split(",")]
    return [k for k in (*numbers, name_key(name)) if k]


MOF_NUMBER = re.compile(r"(?:mof|vat|tva|tax|registration|r\.?c\.?|الرقم المالي|رقم التسجيل|الرقم الضريبي)[^\d\n]{0,25}(\d[\d\- /]{3,16}\d)", re.I)


def numbers_in(text):
    """The MOF / VAT numbers printed on a document (the supplier's, and often the buyer's): '123456,998877'."""
    found = []
    for match in MOF_NUMBER.finditer(str(text or "")):
        number = re.sub(r"\s+", "", match.group(1))
        if 4 <= len(re.sub(r"\D", "", number)) <= 15 and number not in found: found.append(number)
    return ",".join(found)


def tokens(text):
    """The words of a line that say what was bought (no numbers, units or small words)."""
    found = []
    for word in re.findall(r"[^\W\d_]{3,}", str(text or "").casefold()):
        if word not in STOP_WORDS and word not in found: found.append(word)
    return found


# ---------------------------------------------------------------- learning
def _store(connection, scope, keys, label, data, reference, date):
    for key in keys:
        connection.execute("""INSERT INTO posting_rules(scope,key,label,data,times,last_reference,last_date,updated_at) VALUES(?,?,?,?,1,?,?,?)
            ON CONFLICT(scope,key) DO UPDATE SET label=excluded.label,data=excluded.data,times=posting_rules.times+1,
            last_reference=excluded.last_reference,last_date=excluded.last_date,updated_at=excluded.updated_at""",
                           (scope, key, label, json.dumps(data, sort_keys=True), reference, date, utcnow()))


def _remember_lines(connection, descriptions, account):
    account = str(account or "").split(" - ", 1)[0].strip()
    if not account: return
    for description in descriptions:
        for token in tokens(description):
            connection.execute("""INSERT INTO line_memory(token,account,times) VALUES(?,?,1)
                ON CONFLICT(token,account) DO UPDATE SET times=line_memory.times+1""", (token, account))


def _code(connection, table, row_id):
    if not row_id: return ""
    try: found = connection.execute(f"SELECT code FROM {table} WHERE id=?", (int(row_id),)).fetchone()
    except (sqlite3.Error, ValueError, TypeError): return ""
    return found[0] if found else ""


def learn_invoice(db, invoice_id, allow_imported=False):
    """A purchase saved on the Purchases screen: remember how it was posted. Returns the keys stored ([] when not learned)."""
    with db.connect() as connection:
        migrate(connection)
        row = connection.execute("""SELECT i.*, p.name party_name, p.mof_number, p.tax_number FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
            WHERE i.id=?""", (int(invoice_id),)).fetchone()
        if not row or row["kind"] != "purchase" or row["status"] != "posted": return []
        source=str(row["source_file"] or "")
        if source in ("Opening balances", "Customs Case"): return []
        if source != "Purchase Invoice" and not allow_imported: return []
        if str(row["doc_subtype"] if "doc_subtype" in row.keys() else "") in ("credit_note",): return []
        keys = keys_for(row["party_name"], row["mof_number"] or row["tax_number"])
        if not keys: return []
        flagged = connection.execute("SELECT 1 FROM tax_flags WHERE source_type='invoice' AND source_id=?", (int(invoice_id),)).fetchone() is not None
        data = {"entry_type": row["entry_type"], "expense_account": row["expense_account"], "vat_account": row["vat_account"],
                "vat_use": row["vat_use"] if "vat_use" in row.keys() else "mixed",
                "vat_treatment": row["vat_treatment"] if "vat_treatment" in row.keys() else "standard",
                "payment_method": row["payment_method"] or "", "payment_account": (row["payment_account"] if "payment_account" in row.keys() else "") or "",
                "department": _code(connection, "departments", row["department_id"] if "department_id" in row.keys() else None),
                "project": _code(connection, "projects", row["project_id"] if "project_id" in row.keys() else None),
                "not_deductible": flagged, "currency": row["currency"]}
        _store(connection, "purchase", keys, row["party_name"], data, row["invoice_number"], row["invoice_date"])
        lines = [r[0] for r in connection.execute("SELECT description FROM invoice_items WHERE invoice_id=?", (int(invoice_id),))]
        _remember_lines(connection, lines, row["expense_account"])
    return keys


def learn_expense(db, expense_id, supplier=None):
    """An expense saved: remember its accounts for its supplier (read on its PDF). Without a supplier only the words of its description
    are remembered (for the classification), no rule."""
    with db.connect() as connection:
        migrate(connection)
        row = connection.execute("SELECT * FROM expenses WHERE id=?", (int(expense_id),)).fetchone()
        if not row: return []
        keys = keys_for(supplier)
        if not keys:
            _remember_lines(connection, [row["description"]], row["expense_account"] or row["expense_without_vat_account"])
            return []
        data = {"expense_account": row["expense_account"], "expense_without_vat_account": row["expense_without_vat_account"],
                "vat_account": row["vat_account"], "payment_account": row["payment_account"], "category": row["category"] or "",
                "tax_deductible": bool(row["tax_deductible"]) if "tax_deductible" in row.keys() else True,
                "vat_recoverable": bool(row["vat_recoverable"]) if "vat_recoverable" in row.keys() else True,
                "vat_use": row["vat_use"] if "vat_use" in row.keys() else "mixed",
                "department": _code(connection, "departments", row["department_id"] if "department_id" in row.keys() else None),
                "project": _code(connection, "projects", row["project_id"] if "project_id" in row.keys() else None), "currency": row["currency"]}
        _store(connection, "expense", keys, supplier, data, row["expense_number"] or row["reference"], row["expense_date"])
        _remember_lines(connection, [row["description"]], row["expense_account"] or row["expense_without_vat_account"])
    return keys


def learn_tax_flag(db, source_type, source_id, not_deductible):
    """The "not deductible for income tax" tick is saved after the purchase: the supplier's rule follows it."""
    if source_type != "invoice": return
    with db.connect() as connection:
        migrate(connection)
        row = connection.execute("""SELECT p.name, p.mof_number, p.tax_number, i.source_file, i.kind FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
            WHERE i.id=?""", (int(source_id),)).fetchone()
        if not row or row["kind"] != "purchase" or str(row["source_file"] or "") != "Purchase Invoice": return
        for key in keys_for(row["name"], row["mof_number"] or row["tax_number"]):
            found = connection.execute("SELECT id, data FROM posting_rules WHERE scope='purchase' AND key=?", (key,)).fetchone()
            if not found: continue
            data = json.loads(found["data"]); data["not_deductible"] = bool(not_deductible)
            connection.execute("UPDATE posting_rules SET data=? WHERE id=?", (json.dumps(data, sort_keys=True), found["id"]))


# ---------------------------------------------------------------- suggestions
def find_rule(db, scope, name=None, number=None):
    """The rule of this supplier: by its MOF / VAT number first, then its name, then a name very close to it."""
    with db.connect() as connection:
        migrate(connection)
        candidates = []
        name_match = None
        for key in keys_for(name, number):
            row = connection.execute("SELECT * FROM posting_rules WHERE scope=? AND key=?", (scope, key)).fetchone()
            if not row: continue
            if key.startswith("mof:"): candidates.append(row)
            else: name_match = row
        if candidates:
            # A scanned invoice may show both buyer and supplier tax numbers.
            # Prefer the supplier's named rule; never select an arbitrary first number.
            identities = {row["label"] for row in candidates}
            if len(identities) > 1:
                matching = [row for row in candidates if name_key(row["label"]) == name_key(name)]
                if len(matching) != 1: return None
                row = matching[0]
            else: row = candidates[0]
            return {**dict(row), "data": json.loads(row["data"]), "matched": "number"}
        if name_match:
            return {**dict(name_match), "data": json.loads(name_match["data"]), "matched": "name"}
        wanted = name_key(name)
        if not wanted: return None
        from difflib import SequenceMatcher
        best = None
        for row in connection.execute("SELECT * FROM posting_rules WHERE scope=? AND key LIKE 'name:%'", (scope,)):
            score = SequenceMatcher(None, wanted, row["key"]).ratio()
            if score >= 0.88 and (best is None or score > best[0]): best = (score, row)
        if best: return {**dict(best[1]), "data": json.loads(best[1]["data"]), "matched": f"similar name ({best[0]:.0%})"}
    return None


def classify_lines(db, descriptions):
    """[{description, account, confidence, source}] - the account of each line from the lines saved before."""
    result = []
    with db.connect() as connection:
        migrate(connection)
        for description in descriptions:
            votes = {}
            words = tokens(description)
            for word in words:
                for row in connection.execute("SELECT account, times FROM line_memory WHERE token=?", (word,)):
                    votes[row["account"]] = votes.get(row["account"], 0) + row["times"]
            if votes:
                account, best = max(votes.items(), key=lambda item: (item[1], item[0]))
                confidence = round(best / sum(votes.values()), 2)
                result.append({"description": description, "account": account, "confidence": confidence, "source": "lines saved before"})
            else: result.append({"description": description, "account": "", "confidence": 0.0, "source": ""})
    return result


def _posting_accounts(db):
    """2.9.132: the active posting accounts of the company (None when no database is given - unit tests)."""
    if db is None: return None
    try: return {str(a["code"]): a for a in db.list_accounts() if a.get("is_active") and a.get("is_posting")}
    except (AttributeError, sqlite3.Error): return None


def suggest(db, scope="purchase", name=None, number=None, text="", lines=()):
    """Everything the program can propose for a new invoice of this supplier:
    {"rule": rule or None, "account": {code, confidence, source} or None, "lines": [...]}."""
    result = _suggest(db, scope, name, number, text, lines)
    accounts = _posting_accounts(db); account = result.get("account")
    if accounts is not None and account and str(account.get("code") or "").split(" - ", 1)[0].strip() not in accounts:
        # 2.9.132 (Phase 2): never propose an account that is not an active posting account of this chart
        warning = f"The account {account.get('code')} ({account.get('source')}) is not an active posting account of this chart; choose the account."
        result = {**result, "account": None, "review_required": True, "review_warnings": [*result.get("review_warnings", []), warning]}
    return result


def _suggest(db, scope="purchase", name=None, number=None, text="", lines=()):
    rule = find_rule(db, scope, name, number)
    lines = [str(line) for line in lines or () if str(line or "").strip()]
    classified = classify_lines(db, lines) if lines else []
    account = None
    if rule:
        code = rule["data"].get("expense_account") or ""
        if scope == "expense" and code:
            import pdf_import
            current = pdf_import.expense_classification(" ".join([text or "", *lines]))
            category = current["category"]
            digits = lambda value: re.sub(r"\D", "", str(value))
            differs = category and not digits(code).startswith(digits(category[1]))
            if current["status"] == "ambiguous" or differs:
                return {"rule": None, "account": None, "lines": classified, "review_required": True,
                        "conflicting_rule": rule,
                        "review_warnings": ["The current expense description conflicts with the supplier's saved posting rule; choose the accounts manually"]}
        account = {"code": code, "confidence": 0.95, "source": f"rule of {rule['label']} ({rule['times']} time(s), last {rule['last_reference'] or '-'})"}
    else:
        votes = {}
        for line in classified:
            if line["account"]: votes[line["account"]] = votes.get(line["account"], 0) + line["confidence"]
        if votes:
            code, score = max(votes.items(), key=lambda item: (item[1], item[0]))
            account = {"code": code, "confidence": round(min(0.9, score / max(1, len(classified))), 2), "source": "lines saved before"}
        else:
            import pdf_import
            classification = pdf_import.expense_classification(" ".join([text or "", *lines, name or ""]))
            category = classification["category"]
            if category:
                # 2.9.132: the code that exists in this chart (6263.4 in the Lebanese chart; the 9-digit form was proposed before)
                accounts = _posting_accounts(db) or {}
                code = category[1] if category[1] in accounts else category[2]
                account = {"code": code, "confidence": 0.7, "source": f"keywords: {category[0]}", "parent": category[1], "name": category[3]}
            elif classification["status"] != "ambiguous":
                import ai_mapper
                found = ai_mapper.suggest_account(" ".join(lines) or text)
                if found: account = {"code": found["code"], "confidence": found["confidence"], "source": "chart of accounts names", "name": found["name"]}
    return {"rule": rule, "account": account, "lines": classified}


# ---------------------------------------------------------------- the list (Settings)
def list_rules(db):
    with db.connect() as connection:
        migrate(connection)
        return [{**dict(r), "data": json.loads(r["data"])} for r in connection.execute("SELECT * FROM posting_rules ORDER BY scope, label, key")]


def delete_rule(db, rule_id):
    with db.connect() as connection:
        migrate(connection)
        connection.execute("DELETE FROM posting_rules WHERE id=?", (int(rule_id),))
    return {"deleted": int(rule_id)}
