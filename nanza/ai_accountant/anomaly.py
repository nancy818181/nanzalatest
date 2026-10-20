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


def detect_anomalies(invoices):
    """Return duplicate/high-VAT review flags, not allegations of fraud.

    Accepts dict records with vendor/vendor_id, date/invoice_date, currency,
    subtotal (tax-exclusive) or total (VAT-inclusive), vat, optional vat_rate and
    country. Missing or invalid amounts are flagged rather than coerced to zero.
    """
    from decimal import Decimal, InvalidOperation
    import re
    import unicodedata

    def money(value):
        try:
            amount = Decimal(str(value))
            return amount if amount.is_finite() and amount >= 0 else None
        except (InvalidOperation, ValueError, TypeError):
            return None

    def canonical(value):
        return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())

    flags = []; seen = {}
    for index, invoice in enumerate(invoices):
        if not isinstance(invoice, dict):
            raise ValueError("Invoices must be dictionaries")
        identifier = invoice.get("id", index)
        total = money(invoice.get("total")); vat = money(invoice.get("vat"))
        if total is None or vat is None or vat > total:
            flags.append({"type": "invalid_amount", "invoice_id": identifier, "requires_review": True})
            continue
        base = money(invoice.get("subtotal")) if invoice.get("subtotal") is not None else total-vat
        if base is None:
            flags.append({"type": "invalid_amount", "invoice_id": identifier, "requires_review": True})
            continue
        country = canonical(invoice.get("country")).upper()
        standard = {"LB": Decimal(11), "LEBANON": Decimal(11),
                    "SA": Decimal(15), "KSA": Decimal(15), "AE": Decimal(5), "UAE": Decimal(5)}.get(country)
        declared = money(invoice.get("vat_rate"))
        threshold = standard if standard is not None else declared if declared is not None else Decimal(15)
        treatment = canonical(invoice.get("vat_treatment"))
        if treatment in ("exempt", "zero_rated", "out_of_scope"):
            threshold = Decimal(0)
        expected = (base*threshold/100).quantize(Decimal("0.01"))
        if vat > expected+Decimal("0.02"):
            flags.append({"type": "high_vat", "invoice_id": identifier,
                          "actual_vat": str(vat), "expected_max_vat": str(expected),
                          "requires_review": True})
        vendor = canonical(invoice.get("vendor_id") or invoice.get("vendor") or invoice.get("supplier"))
        currency = canonical(invoice.get("currency")).upper()
        number = canonical(invoice.get("invoice_number") or invoice.get("number"))
        day = _iso_day(invoice.get("invoice_date") or invoice.get("date"))
        if not vendor or not currency:
            continue  # Unknown suppliers/currencies must not all be treated as duplicates.
        kind = canonical(invoice.get("doc_subtype") or "invoice")
        key = (vendor, currency, total, kind)
        for previous in seen.get(key, []):
            same_number = bool(number) and number == previous["number"]
            near = day is not None and previous["day"] is not None and abs((day-previous["day"]).days) <= 7
            if same_number or near:
                flags.append({"type": "duplicate", "invoice_ids": [previous["id"], identifier],
                              "reason": "same_vendor_reference_amount" if same_number else "same_vendor_amount_near_date",
                              "requires_review": True})
        seen.setdefault(key, []).append({"id": identifier, "number": number, "day": day})
    return flags
