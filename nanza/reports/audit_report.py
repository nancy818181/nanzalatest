"""2.9.97: the audit report - what an external auditor asks for first, for a period.

1. Integrity of the audit trail (fingerprint chain).
2. Activity per user: documents entered, approved, changed, cancelled / deleted.
3. Changes to documents after they were saved (with before / after where recorded).
4. Late entries: entered more than N days after their date (back-dated), or after the period end.
5. Entries made by the administrator.
6. Entries made outside working hours (before 07:00, after 20:00 or on Sunday, Beirut time).
7. Manual journal vouchers that touch cash or bank (51 / 53)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import audit_chain
from database_common import display_date, iso_date

CHANGE_ACTIONS = ("change", "update", "delete", "cancel", "reopen", "replace")
ENTRY_ACTIONS = ("create", "save", "import", "post", "add")


def control_sheet_sections(report):
    """Build an auditor workpaper checklist from the selected company's audit report, without asserting conclusions."""
    summary=report.get("summary") or {}; integrity=report.get("integrity") or {}
    system_rows=[
        ["Audit trail integrity",integrity.get("message","Not available"),"Audit Report: Integrity of the audit trail",
         "Review system flag" if not integrity.get("ok") else "Auditor review pending"],
    ]
    for key,label,section in (("late","Late entries","4. Late entries"),("admin","Administrator entries","5. Entries made by the administrator"),
                              ("outside_hours","Outside-hours entries","6. Entries made outside working hours"),("manual_cash","Manual cash/bank vouchers","7. Manual journal vouchers on cash or bank")):
        count=int(summary.get(key) or 0)
        system_rows.append([label,f"{count} system flag(s)" if count else "No rows flagged by this check",f"Audit Report: {section}",
                            "Review system flags" if count else "Auditor review pending"])
    checks=[
        ("General ledger", "Trial Balance debit / credit", "Financial Reports > Trial Balance", "Recalculate debit and credit totals and investigate any difference.", "Trial Balance export and ledger detail"),
        ("General ledger", "General Ledger to Trial Balance", "Financial Reports > General Ledger; Trial Balance", "Agree selected account movements and closing balances between reports.", "General Ledger and Trial Balance exports"),
        ("Profit and loss", "P&L to Trial Balance", "Financial Reports > P&L; Trial Balance", "Agree revenue and expense report totals to the mapped ledger accounts.", "P&L, Trial Balance, account mapping"),
        ("Balance sheet", "Balance Sheet to Trial Balance", "Financial Reports > Balance Sheet; Trial Balance", "Agree balance sheet balances to the corresponding Trial Balance accounts.", "Balance Sheet and Trial Balance exports"),
        ("Cash", "Cash Flow to cash / bank ledger", "Financial Reports > Cash Flow; General Ledger", "Trace selected cash-flow movements to cash and bank ledger activity.", "Cash Flow, cash/bank ledgers, bank reconciliations"),
        ("VAT", "VAT report to invoice registers", "Financial Reports > Lebanese VAT Report; Sales and Purchases", "Reconcile report totals to invoice registers and inspect selected source documents.", "VAT report, sales/purchase registers, source invoices"),
        ("Receivables and payables", "Customer / supplier statements to aging", "Statements of Account; Aging", "Agree selected party balances and investigate aged or unreconciled items.", "Party statements, aging report, subsequent receipts/payments"),
        ("Inventory", "Inventory valuation to ledger", "Inventory reports; General Ledger", "Compare inventory report totals to ledger balances and inspect count/valuation support.", "Inventory valuation, stock count records, ledger"),
        ("Fixed assets", "Fixed asset register to ledger", "Assets & Depreciation > Register vs Ledger", "Trace selected additions, disposals, and depreciation to register and ledger evidence.", "Asset register, invoices, disposal support, depreciation schedule"),
        ("Payroll", "Payroll reports to posted payroll entries", "Payroll reports; General Ledger", "Agree selected payroll totals to posted entries and supporting payroll records.", "Payroll reports, approved payroll records, ledger"),
    ]
    reconciliation_rows=[[area,name,"Not calculated by this audit report",source,"Not performed"] for area,name,source,_procedure,_evidence in checks]
    procedure_rows=[[area,name,procedure,evidence,"","","","Not started"] for area,name,_source,procedure,evidence in checks]
    return [
        {"heading":"Auditor Control Sheet - system-generated flags (review required)",
         "headers":["Check","System result","Source reference","Status"],"rows":system_rows},
        {"heading":"Reconciliation checklist - not calculated by this audit report",
         "headers":["Area","Control objective","System result","Source report","Status"],"rows":reconciliation_rows},
        {"heading":"Suggested procedures and evidence requests - reviewer to complete",
         "headers":["Area","Control objective","Suggested procedure","Evidence to request","Auditor result","Reviewer notes","Responsible","Status"],"rows":procedure_rows},
        {"heading":"Control sheet scope and limitations","headers":["Notice"],"rows":[
            ["System-generated flags are prompts for review. They are not an auditor conclusion, audit opinion, or proof of compliance."],
            ["Reconciliations above are not calculated by this control sheet; record evidence and conclusions only after checking the referenced reports."],
            ["No verified legal, tax, IFRS, or IAS reference pack is attached. NEEDS ACCOUNTANT SIGN-OFF."],
        ]},
    ]


def _local(created_at):
    """created_at (UTC, ISO) -> Beirut local time."""
    try: moment = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError: return None
    if moment.tzinfo is None: moment = moment.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo("Asia/Beirut"))
    except Exception:  # 2.9.98: Windows without the time-zone data: Lebanon's rule (UTC+3 from the last Sunday of March
        return moment.astimezone(timezone(timedelta(hours=_beirut_offset(moment))))  # to the last Sunday of October, else UTC+2)


def _beirut_offset(moment):
    utc = moment.astimezone(timezone.utc)
    def last_sunday(month):
        day = datetime(utc.year, month, 31 if month in (3, 10) else 30, tzinfo=timezone.utc)
        return day - timedelta(days=(day.weekday() + 1) % 7)
    summer_start = last_sunday(3) - timedelta(hours=2)   # 00:00 Beirut winter time
    summer_end = last_sunday(10) - timedelta(hours=3)    # 00:00 Beirut summer time
    return 3 if summer_start <= utc < summer_end else 2


def _entry_day(value):
    try: return iso_date(value)
    except ValueError: return None


def build(db, date_from, date_to, late_days=30):
    start, end = iso_date(date_from, "From"), iso_date(date_to, "To")
    late_days = max(0, int(late_days or 30))
    with db.connect() as connection:
        users = {row["id"]: (row["username"], row["role"]) for row in connection.execute("SELECT id,username,role FROM users")}
        audit = [dict(r) for r in connection.execute("""SELECT id,user_id,action,entity,entity_id,details,created_at FROM audit_log
            WHERE substr(created_at,1,10)>=? AND substr(created_at,1,10)<=? ORDER BY id""", (start, end))]
        entries = [dict(r) for r in connection.execute("""SELECT e.id,e.entry_number,e.entry_date,e.description,e.source_type,e.created_by,e.created_at,
            (SELECT DSUM(CAST(debit AS REAL)) FROM journal_lines WHERE entry_id=e.id) amount,e.currency,
            (SELECT GROUP_CONCAT(DISTINCT a.code) FROM journal_lines j JOIN accounts a ON a.id=j.account_id WHERE j.entry_id=e.id) accounts
            FROM journal_entries e""")]
    name = lambda user_id: users.get(user_id, ("system" if user_id is None else f"#{user_id}", ""))[0]
    in_period = [e for e in entries if (_entry_day(e["entry_date"]) or "") and start <= _entry_day(e["entry_date"]) <= end]

    # 2. activity per user
    activity = {}
    for row in audit:
        item = activity.setdefault(name(row["user_id"]), Counter())
        if row["action"] == "approve": item["approved"] += 1
        elif row["action"] in ("delete", "cancel"): item["cancelled / deleted"] += 1
        elif row["action"] in CHANGE_ACTIONS: item["changed"] += 1
        elif row["action"] in ENTRY_ACTIONS: item["entered"] += 1
        else: item["other"] += 1
    for entry in in_period: activity.setdefault(name(entry["created_by"]), Counter())["journal entries"] += 1
    columns = ("journal entries", "entered", "approved", "changed", "cancelled / deleted", "other")
    activity_rows = [[user] + [counts.get(c, 0) for c in columns] for user, counts in sorted(activity.items())]

    # 3. changes after saving
    changes = []
    for row in audit:
        if row["action"] not in CHANGE_ACTIONS: continue
        detail = row["details"] or ""
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict) and isinstance(parsed.get("changes"), dict):
                detail = "; ".join(f"{field}: {value.get('before')} -> {value.get('after')}" for field, value in parsed["changes"].items())
        except (TypeError, ValueError): pass
        changes.append([str(row["created_at"])[:16].replace("T", " "), name(row["user_id"]), row["action"], row["entity"], row["entity_id"] or "", detail[:400]])

    # 4. late entries, 5. administrator, 6. outside hours, 7. manual cash / bank
    late, admin, night, cash = [], [], [], []
    for entry in in_period:
        day = _entry_day(entry["entry_date"]); created = str(entry["created_at"] or "")[:10]
        row = [entry["entry_number"], display_date(day), str(entry["created_at"] or "")[:16].replace("T", " "), name(entry["created_by"]),
               entry["source_type"] or "", (entry["description"] or "")[:80], entry["currency"], entry["amount"] or 0]
        try: delay = (datetime.strptime(created, "%Y-%m-%d") - datetime.strptime(day, "%Y-%m-%d")).days
        except ValueError: delay = 0
        if delay > late_days or created > end: late.append(row + [delay])
        if users.get(entry["created_by"], ("", ""))[1] == "admin": admin.append(row)
        local = _local(entry["created_at"])
        if local and (local.hour < 7 or local.hour >= 20 or local.weekday() == 6): night.append(row + [local.strftime("%a %H:%M")])
        if entry["source_type"] == "journal_voucher" and any(code.startswith(("51", "53")) for code in str(entry["accounts"] or "").split(",")) \
                and not str(entry["description"] or "").startswith("VAT SETTLEMENT"):
            cash.append(row)

    integrity = audit_chain.verify(db)
    base = ["Entry", "Date", "Entered (UTC)", "User", "Source", "Description", "Currency", "Amount"]
    sections = [
        {"heading": "1. Integrity of the audit trail", "headers": ["Result", "Lines checked"], "rows": [[integrity["message"], integrity["checked"]]]
         + [[f"Line {b['id']}: {b['problem']}", ""] for b in integrity["broken"][:20]]},
        {"heading": "2. Activity per user", "headers": ["User"] + [c.title() for c in columns], "rows": activity_rows},
        {"heading": "3. Changes to documents after they were saved", "headers": ["When (UTC)", "User", "Action", "Record", "No.", "Details (before -> after)"], "rows": changes},
        {"heading": f"4. Late entries (entered more than {late_days} days after their date, or after {display_date(end)})", "headers": base + ["Days late"], "rows": late},
        {"heading": "5. Entries made by the administrator", "headers": base, "rows": admin},
        {"heading": "6. Entries made outside working hours (before 07:00, after 20:00, Sunday - Beirut time)", "headers": base + ["Local time"], "rows": night},
        {"heading": "7. Manual journal vouchers on cash or bank (51 / 53)", "headers": base, "rows": cash},
    ]
    summary = {"integrity_ok": integrity["ok"], "users": len(activity_rows), "changes": len(changes), "late": len(late), "admin": len(admin),
               "outside_hours": len(night), "manual_cash": len(cash), "entries": len(in_period)}
    try: company = str(db.settings().get("company_name") or "")  # 2.9.132: the company in the report header
    except (AttributeError, KeyError): company = ""
    return {"from": display_date(start), "to": display_date(end), "summary": summary, "integrity": integrity, "sections": sections, "company": company}
