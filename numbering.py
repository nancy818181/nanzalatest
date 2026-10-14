"""2.9.116: naming series - the prefix of each kind of document, and optionally the branch in the number.

Settings > Numbering (administrator). By default nothing changes: RV-2026-000001, PV-..., JV-..., EXP-..., SAL-...,
PUR-.... The administrator can choose another prefix (REC instead of RV) and, for sales invoices, purchase invoices
and journal vouchers, put the branch in the number: SAL-BEY-2026-000001 (each branch then counts on its own).
Numbers already given never change (Renumber does that, on request)."""
from __future__ import annotations

import json
import re
import sqlite3

DEFAULTS = {"customer_receipt": "RV", "supplier_payment": "PV", "journal_voucher": "JV", "expense": "EXP", "sale": "SAL", "purchase": "PUR"}
LABELS = {"customer_receipt": "Customer receipts", "supplier_payment": "Supplier payments", "journal_voucher": "Journal vouchers",
          "expense": "Expenses", "sale": "Sales invoices", "purchase": "Purchase invoices"}
WITH_BRANCH = ("journal_voucher", "sale", "purchase")  # the documents that carry a branch
HEAD_OFFICE = "Head Office"


def settings(connection):
    """{kind: {"prefix": str, "branch": bool}} for every kind, defaults filled in."""
    try: row = connection.execute("SELECT value FROM app_settings WHERE key='naming_series'").fetchone()
    except sqlite3.Error: row = None  # a file older than the settings table
    try: chosen = json.loads(row[0]) if row else {}
    except (TypeError, ValueError): chosen = {}
    result = {}
    for kind, default in DEFAULTS.items():
        item = chosen.get(kind) if isinstance(chosen.get(kind), dict) else {}
        prefix = clean_prefix(item.get("prefix") or default) or default
        result[kind] = {"prefix": prefix, "branch": bool(item.get("branch")) and kind in WITH_BRANCH}
    return result


def clean_prefix(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:6]


def branch_code(name):
    """Head Office -> HO, Beirut -> BEI, Jounieh Main -> JM."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(name or "")) if w]
    if not words: return "HO"
    code = "".join(w[0] for w in words) if len(words) > 1 else words[0][:3]
    return code.upper()[:4]


def series(connection, kind, branch=None):
    """The part before -YEAR-000001: "RV", or "SAL-BEY" when the branch is in the number."""
    item = settings(connection)[kind]
    if item["branch"]:
        name = branch
        if isinstance(branch, int):
            row = connection.execute("SELECT name FROM branches WHERE id=?", (branch,)).fetchone(); name = row[0] if row else ""
        return f"{item['prefix']}-{branch_code(name or HEAD_OFFICE)}"
    return item["prefix"]


def save_settings(database, values, user_id):
    """values = {kind: {"prefix": "REC", "branch": true}}; unknown kinds are ignored. Two kinds may not share a prefix."""
    cleaned = {}
    for kind, default in DEFAULTS.items():
        item = values.get(kind) or {}
        prefix = clean_prefix(item.get("prefix") or default)
        if not prefix: raise ValueError(f"{LABELS[kind]}: the prefix needs letters or digits")
        cleaned[kind] = {"prefix": prefix, "branch": bool(item.get("branch")) and kind in WITH_BRANCH}
    used = [v["prefix"] for v in cleaned.values()]
    for reserved in ("CN", "DN", "SCN", "SDN", "INV", "VATND"):
        if reserved in used: raise ValueError(f"The prefix {reserved} is used by the program for other documents")
    if len(set(used)) != len(used): raise ValueError("Each kind of document needs its own prefix")
    from database_common import utcnow
    with database.connect() as db:
        db.execute("INSERT INTO app_settings(key,value) VALUES('naming_series',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(cleaned),))
        db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                   (user_id, "save", "naming_series", json.dumps(cleaned), utcnow()))
    return cleaned
