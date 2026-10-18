"""Fast ageing presentation over the existing as-of settlement engine.

No currencies are added together; advances remain visible separately.
The last bucket is >90 (91+): day 90 belongs to 61-90.
"""

from decimal import Decimal
from database_common import iso_date

BUCKETS = ("0-30", "31-60", "61-90", "90+")
COLORS = dict(zip(BUCKETS, ("#dff3e4", "#fff4bf", "#ffe0bb", "#ffd9df")))


def bucket_for(days):
    days = max(0, int(days))
    return BUCKETS[0 if days <= 30 else 1 if days <= 60 else 2 if days <= 90 else 3]


def get_ageing_buckets(as_of_date, database=None, *, kind="sale", currency=None):
    """Use an explicitly selected company database, never a global/default DB."""
    if database is None:
        raise ValueError("Select a company database first")
    if kind not in ("sale", "purchase"):
        raise ValueError("Choose sale or purchase")
    as_of = iso_date(as_of_date)
    details = []
    grouped = {}
    for source in database.aging_report(as_of, kind, currency):
        row = dict(source)
        amount = Decimal(str(row["outstanding"]))
        bucket = bucket_for(row["days_overdue"])
        row.update(bucket=bucket, outstanding=amount)
        details.append(row)
        key = (row.get("account_number") or row.get("party_id") or row.get("party_name"), row["currency"])
        item = grouped.setdefault(
            key,
            {
                "party_name": row.get("party_name") or "",
                "account_number": row.get("account_number"),
                "currency": row["currency"],
                "buckets": {b: Decimal(0) for b in BUCKETS},
                "overdue": Decimal(0),
                "not_due": Decimal(0),
                "credit": Decimal(0),
                "total": Decimal(0),
                "invoices": [],
                "severity": "0-30",
            },
        )
        item["total"] += amount
        item["invoices"].append(row)
        if amount < 0:
            item["credit"] += amount
        else:
            item["buckets"][bucket] += amount
            item["overdue" if row["days_overdue"] > 0 else "not_due"] += amount
            if BUCKETS.index(bucket) > BUCKETS.index(item["severity"]):
                item["severity"] = bucket
    parties = sorted(grouped.values(), key=lambda r: (r["currency"], r["party_name"].casefold()))
    totals = {}
    for item in parties:
        target = totals.setdefault(
            item["currency"], {b: Decimal(0) for b in (*BUCKETS, "overdue", "not_due", "credit", "total")}
        )
        for b in BUCKETS:
            target[b] += item["buckets"][b]
        for b in ("overdue", "not_due", "credit", "total"):
            target[b] += item[b]
    return {
        "as_of": as_of,
        "kind": kind,
        "parties": parties,
        "details": details,
        "totals": totals,
        "note": "0-30 includes not-yet-due balances; 90+ means more than 90 days. Credits shown separately.",
    }
