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
    except Exception: return None


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
    return {"from": display_date(start), "to": display_date(end), "summary": summary, "integrity": integrity, "sections": sections}
