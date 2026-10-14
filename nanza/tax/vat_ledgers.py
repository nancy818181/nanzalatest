"""2.9.97: one VAT account for every customer / supplier (Lebanese practice), and the quarter-end VAT closing by ledger.

Each payable / receivable ledger has a VAT prefix and a closing account (Accounting Setup > VAT by customer / supplier):

    ledger (party accounts)    VAT of each party        closed at the quarter end into
    40110xxxx suppliers        44210xxxx                44210
    41110xxxx clients          44270xxxx                44270
    46190xxxx other payables   44216xxxx                44265
    40310xxxx asset suppliers  44213xxxx                44263

Supplier 401100025 -> VAT account 442100025 (same last digits). The VAT of an invoice of that party is posted to its own VAT
account; at the quarter end the VAT closing voucher moves every party VAT account into its closing account, and the settlement
closes the closing accounts into VAT payable (4425) / VAT to recover (4429)."""
from __future__ import annotations

import json

DEFAULT_LEDGERS = (
    {"ledger": "40110", "vat": "44210", "main": "401", "closing": "44210", "label": "Suppliers", "side": "input"},
    {"ledger": "41110", "vat": "44270", "main": "411", "closing": "44270", "label": "Clients", "side": "output"},
    {"ledger": "46190", "vat": "44216", "main": "4619", "closing": "44265", "label": "Other payables", "side": "input"},
    {"ledger": "40310", "vat": "44213", "main": "403", "closing": "44263", "label": "Asset suppliers", "side": "input"},
)
ACCOUNT_NAMES = {
    "44210": "VAT on Purchases - Deductible", "44270": "VAT Collected - Clients", "44216": "VAT on Expenses - Deductible",
    "44265": "VAT on Expenses / Other Payables - Closing", "44213": "VAT on Fixed Assets Purchases - Deductible",
    "44263": "VAT on Fixed Assets - Closing",
}
# VAT accounts that are "the general one": a party's own VAT account replaces them (anything else chosen on purpose stays)
GENERAL_VAT = {"4427", "44270", "44210", "44216", "44213", "4426.6", "4426.2", "442660000", "44263", "44265"}
SETTING_ON, SETTING_LEDGERS, SETTING_AUTO = "vat_by_party", "vat_ledgers", "vat_auto_close"


def _get(connection, key, default=""):
    row = connection.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def _put(connection, key, value):
    connection.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def ledgers_of(connection):
    try: rows = json.loads(_get(connection, SETTING_LEDGERS) or "null")
    except (TypeError, ValueError): rows = None
    if not rows: return [dict(row) for row in DEFAULT_LEDGERS]
    clean = []
    for row in rows:
        ledger, vat, closing = (str(row.get(k) or "").strip() for k in ("ledger", "vat", "closing"))
        if ledger.isdigit() and vat.isdigit() and closing.replace(".", "").isdigit() and len(ledger) == len(vat):
            clean.append({"ledger": ledger, "vat": vat, "main": str(row.get("main") or ledger[:3]), "closing": closing,
                          "label": str(row.get("label") or ""), "side": "output" if vat.startswith("4427") else "input"})
    return clean or [dict(row) for row in DEFAULT_LEDGERS]


def enabled(connection):
    return _get(connection, SETTING_ON, "0") == "1"


def auto_close(connection):
    return enabled(connection) and _get(connection, SETTING_AUTO, "1") == "1"


def settings(db):
    with db.connect() as connection:
        return {"enabled": enabled(connection), "auto_close": _get(connection, SETTING_AUTO, "1") == "1", "ledgers": ledgers_of(connection)}


def save_settings(db, item):
    with db.connect() as connection:
        if "enabled" in item: _put(connection, SETTING_ON, "1" if item["enabled"] in (True, 1, "1", "true", "yes") else "0")
        if "auto_close" in item: _put(connection, SETTING_AUTO, "1" if item["auto_close"] in (True, 1, "1", "true", "yes") else "0")
        if item.get("ledgers") is not None:
            for row in item["ledgers"]:
                ledger, vat = str(row.get("ledger") or ""), str(row.get("vat") or "")
                if not (ledger.isdigit() and vat.isdigit() and len(ledger) == len(vat)):
                    raise ValueError(f"Ledger {ledger or '?'} / VAT {vat or '?'}: both are digits of the same length (e.g. 40110 / 44210)")
            _put(connection, SETTING_LEDGERS, json.dumps(item["ledgers"]))
        if enabled(connection): _ensure_control_accounts(connection, ledgers_of(connection))
    return settings(db)


def _account_type(connection, code, default="asset"):
    row = connection.execute("SELECT type FROM accounts WHERE code=?", (code,)).fetchone()
    return row["type"] if row else default


def _ensure_control_accounts(connection, ledgers):
    for row in ledgers:
        for code in (row["vat"], row["closing"]):
            if not connection.execute("SELECT 1 FROM accounts WHERE code=?", (code,)).fetchone():
                parent = "4427" if code.startswith("4427") else "442"
                connection.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code=?))",
                                   (code, ACCOUNT_NAMES.get(code, f"VAT {code}"), _account_type(connection, parent), parent))


def vat_code_for(ledgers, party_account):
    """The party's own VAT account number and its ledger row, or (None, None) when the account is not in a ledger."""
    code = "".join(ch for ch in str(party_account or "") if ch.isdigit())
    for row in ledgers:
        if code.startswith(row["ledger"]) and len(code) > len(row["ledger"]):
            return row["vat"] + code[len(row["ledger"]):], row
    return None, None


def party_vat_account(connection, party_account, chosen_vat, kind):
    """The VAT account to post for this party: its own VAT account when the rule is on and the chosen VAT account is the general
    one; the chosen account otherwise (export VAT 44211, a sale to a supplier-ledger party, the rule off ...)."""
    if not enabled(connection): return chosen_vat
    chosen = str(chosen_vat or "").split(" - ", 1)[0].strip()
    ledgers = ledgers_of(connection)
    own, row = vat_code_for(ledgers, party_account)
    if not own: return chosen_vat
    is_sale = str(kind or "").lower() in ("sale", "sales")
    if is_sale != (row["side"] == "output"): return chosen_vat  # e.g. a sale to a party kept in the suppliers ledger
    if chosen and chosen not in GENERAL_VAT and chosen not in {r["vat"] for r in ledgers} and not any(chosen.startswith(r["vat"]) and len(chosen) == len(own) for r in ledgers):
        return chosen_vat
    ensure_party_vat_account(connection, party_account, ledgers)
    return own


def ensure_party_vat_account(connection, party_account, ledgers=None):
    ledgers = ledgers or ledgers_of(connection)
    own, row = vat_code_for(ledgers, party_account)
    if not own: return None
    _ensure_control_accounts(connection, [row])
    if not connection.execute("SELECT 1 FROM accounts WHERE code=?", (own,)).fetchone():
        party = connection.execute("SELECT name_en FROM accounts WHERE code=?", (str(party_account),)).fetchone()
        name = party["name_en"] if party else str(party_account)
        connection.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code=?))",
                           (own, f"VAT - {name}", _account_type(connection, row["vat"]), row["vat"]))
    return own


def create_vat_accounts(db, start_from=0):
    """'Create VAT Accounts': one VAT account for every party account above `start_from` (0 = all). Returns how many were made."""
    with db.connect() as connection:
        ledgers = ledgers_of(connection); _ensure_control_accounts(connection, ledgers)
        made = 0
        for row in connection.execute("SELECT account_number FROM parties WHERE account_number IS NOT NULL AND account_number<>''").fetchall():
            number = str(row["account_number"])
            if start_from and number.isdigit() and int(number) <= int(start_from): continue
            own, _ledger = vat_code_for(ledgers, number)
            if own and not connection.execute("SELECT 1 FROM accounts WHERE code=?", (own,)).fetchone():
                ensure_party_vat_account(connection, number, ledgers); made += 1
        return made


def test_vat_accounts(db):
    """'Testing VAT Accounts': parties without their VAT account, VAT accounts without a party, and VAT posted to another party's
    VAT account (the VAT line of an invoice on an account that is not its party's)."""
    problems = []
    with db.connect() as connection:
        ledgers = ledgers_of(connection)
        codes = {row["code"]: row["name_en"] for row in connection.execute("SELECT code,name_en FROM accounts")}
        parties = {}
        for row in connection.execute("SELECT name,account_number FROM parties WHERE account_number IS NOT NULL AND account_number<>''"):
            own, _ledger = vat_code_for(ledgers, row["account_number"])
            if not own: continue
            parties[own] = row["name"]
            if own not in codes: problems.append({"type": "missing", "account": own, "detail": f"{row['name']} ({row['account_number']}) has no VAT account {own}"})
        for code, name in codes.items():
            for ledger in ledgers:
                if code.startswith(ledger["vat"]) and len(code) == 9 and code not in parties:
                    problems.append({"type": "orphan", "account": code, "detail": f"{code} {name}: no customer / supplier with this number"})
        wrong = connection.execute("""SELECT i.invoice_number,i.supplier_account,i.vat_account,p.name FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
            WHERE i.status NOT IN ('cancelled','deleted') AND CAST(COALESCE(i.vat,'0') AS REAL)<>0""").fetchall()
        for row in wrong:
            own, _ledger = vat_code_for(ledgers, row["supplier_account"])
            vat = str(row["vat_account"] or "")
            if own and len(vat) == 9 and any(vat.startswith(l["vat"]) for l in ledgers) and vat != own:
                problems.append({"type": "other_party", "account": vat, "detail": f"Invoice {row['invoice_number']} of {row['name']}: VAT on {vat}, its own VAT account is {own}"})
    return {"ok": not problems, "problems": problems}


def closing_lines(connection, balances):
    """Quarter-end VAT closing by ledger: {code: balance} of the party VAT accounts -> lines that move each one into its closing
    account (the settlement then closes the closing accounts). Returns (closing_lines, balances by closing account)."""
    ledgers = ledgers_of(connection); lines = []; moved = {}
    for code, balance in sorted(balances.items()):
        row = next((r for r in ledgers if code.startswith(r["vat"]) and len(code) > len(r["vat"]) and code != r["closing"]), None)
        if row is None or not balance:
            moved[code] = moved.get(code, 0) + balance; continue
        lines.append((code, -balance, f"VAT closed into {row['closing']}"))
        lines.append((row["closing"], balance, f"VAT of {row['label'].lower() or 'the ledger'} closed"))
        moved[row["closing"]] = moved.get(row["closing"], 0) + balance
    return lines, moved
