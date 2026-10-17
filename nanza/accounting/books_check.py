"""2.9.119: Books Health Check - is every number in the books where it should be?

Read only: nothing is changed. Each point says OK / WARNING / ERROR, what was found (with the document numbers) and what
to do. Complements the Year-End Check (accounting_setup.year_end_check), which looks at closing work (VAT settled, DOE,
depreciation...); this one looks at the consistency of the data itself and can run at any time:

 1. every journal entry balanced, and the trial balance in each currency
 2. every posted document (invoice, receipt / payment, expense, payroll) has its journal entry
 3. no journal entry left behind by a document that was deleted
 4. invoice arithmetic: subtotal + VAT = total, lines = subtotal, and the entry carries the invoice total
 5. no duplicate number, and the sales invoices numbered without gaps (Lebanese law: one unbroken sequence)
 6. every line on an account that exists, none on a heading account that has sub-accounts
 7. entries dated inside the fiscal year of this file
 8. saved VAT returns still match the documents (nothing changed after filing)
 9. the audit trail chain is intact
10. no EUR rate of 1 USD left by an offline start of an earlier version (and the EUR documents of those days)
"""
from __future__ import annotations

import re
import sqlite3
from decimal import Decimal, InvalidOperation

OK, WARNING, ERROR = "OK", "WARNING", "ERROR"
TOLERANCE = Decimal("0.01")
SHOWN = 8  # document numbers quoted in a result line (all of them are in "items")
DOCUMENT_SOURCES = {"invoice": "invoices", "payment": "payments", "expense": "expenses"}


def _d(value):
    try: return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError): return Decimal(0)


def _iso(value):
    text = str(value or "")
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", text): return f"{text[6:]}-{text[3:5]}-{text[:2]}"
    return text[:10]


def _quote(items, key="number"):
    names = [str(i.get(key) or i.get("id")) for i in items]
    return ", ".join(names[:SHOWN]) + (f" (+{len(names) - SHOWN} more)" if len(names) > SHOWN else "")


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def run(db, year=None, quick=False):
    """{"results": [{status, check, detail, fix, items}], "errors", "warnings", "summary"}.
    quick=True (the dashboard) leaves out the two slower points: the saved VAT returns and the audit trail."""
    results = []

    def add(status, check, detail, fix="", items=None):
        results.append({"status": status, "check": check, "detail": detail, "fix": fix if status != OK else "", "items": items or []})

    with db.connect() as connection:
        connection.row_factory = sqlite3.Row
        if not quick:
            try: integrity=[str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
            except sqlite3.Error as exc: integrity=[str(exc)]
            if integrity != ["ok"]:
                add(ERROR,"Database physical integrity","; ".join(integrity),
                    "Stop writing to this file. Preserve the original and restore a verified backup; do not repair it automatically.")
                return {"results":results,"errors":1,"warnings":0,"summary":"Database integrity failed; accounting checks stopped"}
            add(OK,"Database physical integrity","SQLite integrity_check passed (including indexes)")
        _entries(db, connection, add)
        _documents_have_entries(connection, add)
        _orphan_entries(connection, add)
        _invoice_arithmetic(connection, add)
        _numbering(connection, add)
        _accounts(connection, add)
        _dates(connection, add, year)
        _rates(connection, add)
    if not quick:
        _vat_returns(db, add)
        _audit_trail(db, add)
    errors = sum(1 for r in results if r["status"] == ERROR); warnings = sum(1 for r in results if r["status"] == WARNING)
    summary = ("The books are consistent" if not errors and not warnings
               else f"{errors} error(s), {warnings} warning(s) to look at")
    return {"results": results, "errors": errors, "warnings": warnings, "summary": summary}


def sections(check, title="Books Health Check"):
    rows = [[r["status"], r["check"], r["detail"], r["fix"]] for r in check["results"]]
    return [{"heading": f"{title} - {check['summary']}", "headers": ["Status", "Check", "Result", "What to do"], "rows": rows, "total_rows": []}]


# ---------------------------------------------------------------- 1. balance
def _entries(db, connection, add):
    unbalanced = db.unbalanced_entries()
    if unbalanced:
        add(ERROR, "Every entry balanced", f"{len(unbalanced)} entr{'y' if len(unbalanced) == 1 else 'ies'} with debit different from credit: "
            + _quote(unbalanced, "entry_number"), "General Journal: open each entry and correct it (Reports > Check Balance lists them)",
            [{"number": u["entry_number"], "difference": u.get("difference")} for u in unbalanced])
    else: add(OK, "Every entry balanced", "Debit = credit in every journal entry")
    totals = connection.execute("""SELECT e.currency, SUM(CAST(l.debit AS REAL)) debit, SUM(CAST(l.credit AS REAL)) credit
        FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id GROUP BY e.currency""").fetchall()
    off = [(r["currency"], round((r["debit"] or 0) - (r["credit"] or 0), 2)) for r in totals if abs((r["debit"] or 0) - (r["credit"] or 0)) > 0.01]
    if off: add(ERROR, "Trial balance in each currency", "Debit and credit differ: " + ", ".join(f"{c} {v:,.2f}" for c, v in off),
                "Correct the unbalanced entries above", [{"number": c, "difference": v} for c, v in off])
    else: add(OK, "Trial balance in each currency", "Total debit = total credit in " + (", ".join(r["currency"] for r in totals) or "every currency"))
    empty = [dict(r) for r in connection.execute("""SELECT e.entry_number number FROM journal_entries e
        WHERE NOT EXISTS (SELECT 1 FROM journal_lines l WHERE l.entry_id=e.id AND (CAST(l.debit AS REAL)<>0 OR CAST(l.credit AS REAL)<>0))""")]
    if empty: add(WARNING, "Entries with amounts", f"{len(empty)} entr{'y' if len(empty) == 1 else 'ies'} without any amount: " + _quote(empty),
                  "General Journal: complete or delete them", empty)
    else: add(OK, "Entries with amounts", "Every entry has amounts")


# ---------------------------------------------------------------- 2. documents -> entries
def _documents_have_entries(connection, add):
    missing = []
    missing += [dict(r, type="Invoice") for r in connection.execute("""SELECT i.id, i.invoice_number number FROM invoices i
        WHERE i.status IN ('posted','cancelled') AND NOT EXISTS (SELECT 1 FROM journal_entries e WHERE e.source_type='invoice' AND e.source_id=i.id)""")]
    payment_number = "COALESCE(x.payment_number, 'payment ' || x.id)" if "payment_number" in _columns(connection, "payments") else "'payment ' || x.id"
    missing += [dict(r, type="Receipt / payment") for r in connection.execute(f"""SELECT x.id, {payment_number} number FROM payments x
        WHERE NOT EXISTS (SELECT 1 FROM journal_entries e WHERE e.source_type='payment' AND e.source_id=x.id)""")]
    expense_number = "COALESCE(x.expense_number, 'expense ' || x.id)" if "expense_number" in _columns(connection, "expenses") else "'expense ' || x.id"
    missing += [dict(r, type="Expense") for r in connection.execute(f"""SELECT x.id, {expense_number} number FROM expenses x
        WHERE NOT EXISTS (SELECT 1 FROM journal_entries e WHERE e.source_type='expense' AND e.source_id=x.id)""")]
    missing += [dict(r, type="Payroll") for r in connection.execute("""SELECT p.id, p.payroll_number number FROM payroll_records p
        WHERE p.status='posted' AND (p.journal_entry_id IS NULL OR NOT EXISTS (SELECT 1 FROM journal_entries e WHERE e.id=p.journal_entry_id))""")]
    if missing:
        add(ERROR, "Every document in the books", f"{len(missing)} posted document(s) without their journal entry: " + _quote(missing),
            "Open each document and save it again (the entry is written again); if it should not count, delete or cancel it", missing)
    else: add(OK, "Every document in the books", "Every posted invoice, receipt / payment, expense and payroll has its journal entry")


# ---------------------------------------------------------------- 3. entries -> documents
def _orphan_entries(connection, add):
    orphans = []
    for source, table in DOCUMENT_SOURCES.items():
        orphans += [dict(r) for r in connection.execute(f"""SELECT e.id, e.entry_number number FROM journal_entries e
            WHERE e.source_type=? AND e.source_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {table} d WHERE d.id=e.source_id)""", (source,))]
    if orphans:
        add(ERROR, "No entry without its document", f"{len(orphans)} entr{'y' if len(orphans) == 1 else 'ies'} of a document that no longer exists: " + _quote(orphans),
            "General Journal: check them with the documents; delete the entry if the document was deleted on purpose", orphans)
    else: add(OK, "No entry without its document", "Every invoice, receipt / payment and expense entry has its document")


# ---------------------------------------------------------------- 4. invoice arithmetic
def _invoice_arithmetic(connection, add):
    invoices = [dict(r) for r in connection.execute("""SELECT id, invoice_number number, currency, subtotal, vat, total FROM invoices
        WHERE status='posted'""")]
    sums = {r["invoice_id"]: (_d(r["subtotal"]), r["lines"]) for r in connection.execute(
        "SELECT invoice_id, SUM(CAST(subtotal AS REAL)) subtotal, COUNT(*) lines FROM invoice_items GROUP BY invoice_id")}
    wrong_total, wrong_lines = [], []
    for invoice in invoices:
        subtotal, vat, total = _d(invoice["subtotal"]), _d(invoice["vat"]), _d(invoice["total"])
        if invoice["subtotal"] not in (None, "") and abs(subtotal + vat - total) > TOLERANCE:
            wrong_total.append({**invoice, "difference": str(subtotal + vat - total)})
        lines = sums.get(invoice["id"])
        if lines and invoice["subtotal"] not in (None, "") and abs(abs(lines[0]) - abs(subtotal)) > TOLERANCE:
            wrong_lines.append({**invoice, "difference": str(lines[0] - subtotal)})
    if wrong_total: add(ERROR, "Invoices: subtotal + VAT = total", f"{len(wrong_total)} invoice(s) where they differ: " + _quote(wrong_total),
                        "Uploaded Data: open each invoice and correct the amounts", wrong_total)
    else: add(OK, "Invoices: subtotal + VAT = total", f"{len(invoices)} posted invoice(s) checked")
    if wrong_lines: add(WARNING, "Invoices: lines = subtotal", f"{len(wrong_lines)} invoice(s) whose lines do not add up to the subtotal: " + _quote(wrong_lines),
                        "Open each invoice: a line or the discount was changed without the totals", wrong_lines)
    else: add(OK, "Invoices: lines = subtotal", "The lines add up to the subtotal")
    entries = {}
    for r in connection.execute("""SELECT e.source_id, e.id, e.currency, SUM(CAST(l.debit AS REAL)) debit FROM journal_entries e
            JOIN journal_lines l ON l.entry_id=e.id WHERE e.source_type='invoice' GROUP BY e.id"""):
        entries.setdefault(r["source_id"], []).append(r)
    differ = []
    for invoice in invoices:
        found = entries.get(invoice["id"]) or []
        if len(found) != 1 or found[0]["currency"] != invoice["currency"] or invoice["total"] in (None, ""): continue
        if abs(_d(round(found[0]["debit"] or 0, 2)) - abs(_d(invoice["total"]))) > TOLERANCE:
            differ.append({**invoice, "entry": str(round(found[0]["debit"] or 0, 2))})
    if differ: add(WARNING, "Invoices equal their entries", f"{len(differ)} invoice(s) whose entry does not carry the invoice total: " + _quote(differ),
                   "Open each invoice and save it again so the entry is written from the invoice", differ)
    else: add(OK, "Invoices equal their entries", "Each invoice entry carries the invoice total")
    # 2.9.121: sales lines whose VAT was typed by hand and is not the rate (allowed on purpose - shown so it is a choice)
    typed = [dict(r) for r in connection.execute("""SELECT DISTINCT i.id, i.invoice_number number FROM invoice_items l JOIN invoices i ON i.id=l.invoice_id
        WHERE i.kind='sale' AND i.status='posted' AND COALESCE(l.vat_rate,'')<>'' AND
        ABS(CAST(l.vat AS REAL) - ROUND(CAST(COALESCE(NULLIF(l.deductible_subtotal,''), l.subtotal) AS REAL) * CAST(l.vat_rate AS REAL) / 100.0, 2)) > 0.05""")]
    if typed: add(WARNING, "Sales VAT = rate x amount", f"{len(typed)} sales invoice(s) with a VAT typed by hand that is not the rate: " + _quote(typed),
                  "Open each invoice: keep the typed VAT only when it is right (e.g. the VAT shown on a contract), otherwise retype the line", typed)
    else: add(OK, "Sales VAT = rate x amount", "Every sales line has the VAT of its rate")


# ---------------------------------------------------------------- 5. numbering
def _numbering(connection, add):
    duplicates = [dict(r) for r in connection.execute("""SELECT invoice_number number, COUNT(*) n FROM invoices
        WHERE kind='sale' AND status<>'review' GROUP BY invoice_number HAVING COUNT(*)>1""")]
    if "payment_number" in _columns(connection, "payments"):
        duplicates += [dict(r) for r in connection.execute("""SELECT payment_number number, COUNT(*) n FROM payments
            WHERE COALESCE(payment_number,'')<>'' GROUP BY payment_number HAVING COUNT(*)>1""")]
    supplier = [dict(r) for r in connection.execute("""SELECT i.invoice_number || ' (' || COALESCE(p.name,'') || ')' number, COUNT(*) n
        FROM invoices i LEFT JOIN parties p ON p.id=i.party_id WHERE i.kind='purchase' AND i.status<>'cancelled'
        GROUP BY i.party_id, i.invoice_number HAVING COUNT(*)>1""")]
    if duplicates: add(ERROR, "No duplicate numbers", f"{len(duplicates)} number(s) used twice: " + _quote(duplicates),
                       "Settings > Numbering > Renumber, or correct the document", duplicates)
    else: add(OK, "No duplicate numbers", "Every sales invoice and receipt / payment number is used once")
    if supplier: add(WARNING, "Supplier invoices entered once", f"{len(supplier)} supplier invoice number(s) entered twice: " + _quote(supplier),
                     "Uploaded Data: check whether the same supplier invoice was entered twice", supplier)
    else: add(OK, "Supplier invoices entered once", "No supplier invoice entered twice")
    numbers = [r["invoice_number"] for r in connection.execute("SELECT invoice_number FROM invoices WHERE kind='sale' AND status<>'review'")]
    groups = {}
    for number in numbers:
        match = re.fullmatch(r"(.*?)(\d+)", str(number or "").strip())
        if match and len(match.group(2)) >= 3: groups.setdefault(match.group(1), set()).add(int(match.group(2)))
    gaps = []
    for prefix, values in sorted(groups.items()):
        if len(values) < 2: continue
        width = max(len(str(v)) for v in values)
        width = max(width, max(len(m.group(2)) for n in numbers if (m := re.fullmatch(r"(.*?)(\d+)", str(n or "").strip())) and m.group(1) == prefix))
        missing = sorted(set(range(min(values), max(values) + 1)) - values)
        gaps += [{"number": f"{prefix}{value:0{width}d}"} for value in missing]
    if gaps: add(WARNING, "Sales invoices numbered without gaps", f"{len(gaps)} number(s) missing in the sequence: " + _quote(gaps),
                 "A deleted invoice leaves a gap: cancel invoices instead of deleting them, or renumber (Settings > Numbering)", gaps)
    else: add(OK, "Sales invoices numbered without gaps", "Every sequence of sales invoice numbers is unbroken")


# ---------------------------------------------------------------- 6. accounts
def _accounts(connection, add):
    lost = [dict(r) for r in connection.execute("""SELECT DISTINCT e.entry_number number FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id
        WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.id=l.account_id)""")]
    if lost: add(ERROR, "Lines on existing accounts", f"{len(lost)} entr{'y' if len(lost) == 1 else 'ies'} with a line on an account that no longer exists: " + _quote(lost),
                 "Chart of Accounts: create the account again, or correct the entries", lost)
    else: add(OK, "Lines on existing accounts", "Every line is on an account of the chart")
    headings = [dict(r) for r in connection.execute("""SELECT a.code number, COUNT(*) n FROM journal_lines l JOIN accounts a ON a.id=l.account_id
        WHERE EXISTS (SELECT 1 FROM accounts c WHERE c.parent_id=a.id) AND (CAST(l.debit AS REAL)<>0 OR CAST(l.credit AS REAL)<>0)
        GROUP BY a.code ORDER BY a.code""")]
    if headings: add(WARNING, "No lines on heading accounts", f"{len(headings)} heading account(s) with amounts posted on them (not on a sub-account): " + _quote(headings),
                     "Usually fine when the heading is the account you use; otherwise move the amounts to the sub-accounts (Journal Voucher)", headings)
    else: add(OK, "No lines on heading accounts", "Amounts are on the detail accounts")


# ---------------------------------------------------------------- 7. dates
def _dates(connection, add, year):
    if not year:
        row = connection.execute("SELECT year FROM fiscal_years ORDER BY year DESC LIMIT 1").fetchone()
        year = row[0] if row else None
    if not year: return
    outside = [dict(r) for r in connection.execute("SELECT entry_number number, entry_date FROM journal_entries")
               if _iso(r["entry_date"])[:4] != str(year)]
    if outside: add(WARNING, "Entries inside the fiscal year", f"{len(outside)} entr{'y' if len(outside) == 1 else 'ies'} dated outside {year}: " + _quote(outside),
                    "Check the date: an entry of another year belongs in that year's file", outside)
    else: add(OK, "Entries inside the fiscal year", f"Every entry is dated in {year}")


# ---------------------------------------------------------------- 10. exchange rates
def _rates(connection, add):
    bad = [r[0] for r in connection.execute("""SELECT rate_date FROM exchange_rates WHERE from_currency='EUR' AND to_currency='USD'
        AND CAST(rate AS REAL)=1 AND created_by IS NULL ORDER BY rate_date""")]
    if not bad:
        add(OK, "EUR rates look right", "No EUR rate of 1 USD"); return
    days = {_iso(d) for d in bad}
    documents = [dict(r) for r in connection.execute("SELECT invoice_number number, invoice_date FROM invoices WHERE currency='EUR'")
                 if _iso(r["invoice_date"]) in days]
    add(WARNING, "EUR rates look right", f"{len(bad)} day(s) with 1 EUR = 1 USD (written when the computer was offline)"
        + (f"; EUR invoices on those days: {_quote(documents)}" if documents else ""),
        "Settings > Exchange Rates > Restore EUR Rates 2024-Today (online), then open and save again the EUR documents of those days",
        documents or [{"number": d} for d in bad])


# ---------------------------------------------------------------- 8. VAT returns
def _vat_returns(db, add):
    import vat_return
    with db.connect() as connection:
        saved = [(r[0], r[1]) for r in connection.execute("SELECT year, quarter FROM vat_returns ORDER BY year, quarter")]
    if not saved:
        add(OK, "Saved VAT returns unchanged", "No VAT return saved yet"); return
    changed, failed = [], []
    for year, quarter in saved:
        try:
            if vat_return.build_vat_return(db, year, quarter).get("changed_since_saved"): changed.append({"number": f"{year} Q{quarter}"})
        except (ValueError, KeyError, TypeError, ArithmeticError, sqlite3.Error) as exc:
            failed.append({"number": f"{year} Q{quarter}", "error": str(exc)})
    if changed: add(ERROR, "Saved VAT returns unchanged", "Documents changed after the VAT return was saved: " + _quote(changed),
                    "Quarterly VAT: compare, then file an amended return or put the documents back", changed)
    elif failed: add(WARNING, "Saved VAT returns unchanged", "Could not be checked: " + "; ".join(f"{f['number']}: {f['error']}" for f in failed[:3]),
                     "Quarterly VAT: open the quarter (an exchange rate may be missing)", failed)
    else: add(OK, "Saved VAT returns unchanged", f"{len(saved)} saved return(s) still match the documents")


# ---------------------------------------------------------------- 9. audit trail
def _audit_trail(db, add):
    import audit_chain
    try: result = audit_chain.verify(db)
    except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        add(WARNING, "Audit trail intact", f"Could not be checked: {exc}"); return
    if result.get("ok"): add(OK, "Audit trail intact", result.get("message") or f"{result.get('checked', 0)} line(s) checked")
    elif not result.get("sealed_by_this_computer", True) and not result.get("broken"):
        add(WARNING, "Audit trail intact", result.get("message") or "Sealed on another computer",
            "Run the check on the computer that runs the data service")
    else: add(ERROR, "Audit trail intact", result.get("message") or "The audit trail was changed outside the program",
              "Restore a backup from before the change, and find out who opened the data file outside Nanza",
              [{"number": f"line {b.get('id')}", "problem": b.get("problem")} for b in result.get("broken", [])])
