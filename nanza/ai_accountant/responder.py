"""Answers with totals and source journal entries returned by the filtered query."""
from __future__ import annotations


def respond(result):
    if not result.get("ok"):
        return {"message": result.get("message", "The request could not be answered."),
                "filters_applied": result.get("filters_applied", []),
                "sources": [], "confidence": "Unavailable"}
    rows = result.get("rows") or []
    totals = result.get("totals") or {}
    labels = ", ".join(result.get("filters_applied") or []) or "no additional filters"
    intent = result.get("intent")
    if intent in ("ar_aging", "ap_aging"):
        reconciliation = result.get("reconciliation") or {}
        mismatches = [f"{currency}: aging {value['aging']:,.2f}, GL {value['gl']:,.2f}, "
                      f"difference {value['difference']:,.2f}"
                      for currency, value in reconciliation.items() if not value["matches"]]
        total_text = "; ".join(f"{code} {amount:,.2f}" for code, amount in sorted(totals.items())) or "0.00"
        message = f"{'AR' if intent == 'ar_aging' else 'AP'} aging as of {result['as_of']}: {total_text}."
        message += (" UNRECONCILED - " + "; ".join(mismatches) if mismatches
                    else " Aging agrees with the selected GL control accounts.")
        return {"message": message, "filters_applied": result.get("filters_applied", []),
                "sources": [], "rows": rows, "reconciliation": reconciliation,
                "totals": totals, "confidence": "Exact ledger query"}
    if intent == "cash_forecast":
        currencies = sorted({str(row.get("currency") or "") for row in rows})
        message = f"13-week cash forecast: {len(rows)} weekly currency rows across {len(currencies)} currencies."
        return {"message": message, "filters_applied": result.get("filters_applied", []),
                "sources": [], "rows": rows, "assumptions": result.get("assumptions", []),
                "confidence": "Exact ledger query"}
    if intent == "duplicate_check":
        pairs = [
            f"{row['vendor']}: {row['invoices'][0]['number']} ({row['invoices'][0]['date']}) "
            f"/ {row['invoices'][1]['number']} ({row['invoices'][1]['date']}), "
            f"{row['currency']} {row['amount']:,.2f}"
            for row in rows
        ]
        message = ("Possible duplicate invoices: " + "; ".join(pairs)) if pairs else "No possible duplicate invoices found."
        return {"message": message, "filters_applied": result.get("filters_applied", []),
                "sources": [], "rows": rows, "confidence": "Exact ledger query"}
    if intent == "profit_why":
        changes = sorted(rows, key=lambda row: abs(row["change"]), reverse=True)[:10]
        lines = [f"{row['account_code']} {row['account_name']}: "
                 f"{row['currency']} {row['current_month']:,.2f} this month vs "
                 f"{row['previous_month']:,.2f} last month (change {row['change']:+,.2f})"
                 for row in changes]
        message = "Profit and loss account movements: " + (
            "; ".join(lines) if lines else "no posted activity in either month.")
        return {"message": message, "filters_applied": result.get("filters_applied", []),
                "sources": [], "rows": rows, "totals": totals,
                "confidence": "Exact ledger query"}
    amounts = "; ".join(f"{currency} {amount:,.2f}" for currency, amount in sorted(totals.items()))
    if not amounts:
        amounts = "0.00"
    source_lines = [
        f"- {row['entry_number']}: {row['currency']} {row['amount']:,.2f} on "
        f"{row['entry_date']} {row['description'] or ''} ({row['account_code']})"
        for row in rows
    ]
    source_text = "\n".join(source_lines) if source_lines else "- No matching journal entries"
    return {
        "message": (f"Filtered expense total: {amounts}.\nSources:\n{source_text}\n"
                    f"Filters: {labels}.\nExact ledger query ({len(rows)} source line(s))."),
        "filters_applied": result.get("filters_applied", []),
        "sources": [{
            "journal_id": row["journal_id"], "entry_number": row["entry_number"],
            "date": row["entry_date"], "description": row["description"] or "",
            "account_code": row["account_code"], "account_name": row["account_name"],
            "vendor": row["vendor"], "project": row["project"],
            "currency": row["currency"], "amount": row["amount"],
        } for row in rows],
        "totals": totals,
        "confidence": "Exact ledger query" if rows else "Unavailable",
    }
