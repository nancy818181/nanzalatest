"""Deterministic anomaly checks over company-scoped accounting data."""
from __future__ import annotations

from datetime import date, datetime


def _iso_day(value):
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def find_duplicates(database, today=None):
    """Find posted/review supplier invoices with matching amount and dates within seven days."""
    reference = today or date.today()
    if not isinstance(reference, date):
        reference = date.fromisoformat(str(reference)[:10])
    with database.connect() as connection:
        invoices = [dict(row) for row in connection.execute("""SELECT i.id,i.invoice_number,
            i.invoice_date,i.currency,i.total,i.status,p.name vendor
            FROM invoices i JOIN parties p ON p.id=i.party_id
            WHERE i.kind='purchase' AND i.status IN ('posted','review')
            ORDER BY p.name,i.currency,CAST(i.total AS REAL),i.id""")]
    normalized = []
    for invoice in invoices:
        day = _iso_day(invoice.get("invoice_date"))
        if day is None or day > reference:
            continue
        invoice["normalized_date"] = day
        normalized.append(invoice)
    duplicates = []
    groups = {}
    for invoice in normalized:
        key = (invoice["vendor"], invoice["currency"], round(float(invoice["total"] or 0), 2))
        groups.setdefault(key, []).append(invoice)
    for (vendor, currency, amount), group in groups.items():
        group.sort(key=lambda invoice: (invoice["normalized_date"], invoice["id"]))
        for index, first in enumerate(group):
            for second in group[index+1:]:
                gap = (second["normalized_date"]-first["normalized_date"]).days
                if gap > 7:
                    break
                if gap <= 7:
                    duplicates.append({
                        "vendor": vendor, "currency": currency,
                        "amount": amount, "date_gap_days": gap,
                        "invoices": [
                            {"id": first["id"], "number": first["invoice_number"],
                             "date": first["normalized_date"].isoformat(), "status": first["status"]},
                            {"id": second["id"], "number": second["invoice_number"],
                             "date": second["normalized_date"].isoformat(), "status": second["status"]},
                        ],
                    })
    return duplicates
