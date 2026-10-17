"""Local-first intake. Advisory matching scores are not measured OCR accuracy."""

from __future__ import annotations
import copy
import re
import unicodedata
from decimal import Decimal, InvalidOperation

FIELDS = ("invoice_number", "invoice_date", "party_name", "party_tax_number", "currency", "subtotal", "vat", "total")
ALIASES = {
    "party_name": "VendorName",
    "party_tax_number": "VendorTaxId",
    "invoice_number": "InvoiceId",
    "invoice_date": "InvoiceDate",
    "subtotal": "SubTotal",
    "vat": "TotalTax",
    "total": "InvoiceTotal",
}
WORDS = {
    "utility_bill": (
        "electricity",
        "electricite",
        "edl",
        "water",
        "internet",
        "telecom",
        "كهرباء",
        "مياه",
        "هاتف",
        "انترنت",
    ),
    "fixed_asset": (
        "laptop",
        "computer",
        "ordinateur",
        "vehicle",
        "vehicule",
        "machine",
        "equipment",
        "معدات",
        "حاسوب",
        "سيارة",
    ),
    "operating_expense": (
        "rent",
        "loyer",
        "maintenance",
        "repair",
        "reparation",
        "consulting",
        "honoraires",
        "fuel",
        "carburant",
        "office",
        "ايجار",
        "صيانة",
        "محروقات",
        "اتعاب",
    ),
    "purchase": (
        "merchandise",
        "inventory",
        "stock",
        "raw materials",
        "marchandises",
        "matieres premieres",
        "بضاعة",
        "بضائع",
        "مواد اولية",
    ),
}


def normalized(value):
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(value or "").casefold()) if not unicodedata.combining(c)
    )


def number(value):
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def document_kind(text):
    for kind, pattern in (
        ("credit_note", r"credit\s+note|avoir|اشعار\s*دائن"),
        ("debit_note", r"debit\s+note|note\s+de\s+debit|اشعار\s*مدين"),
        ("quotation", r"quotation|devis|عرض\s*سعر"),
        ("delivery_note", r"delivery\s+note|bon\s+de\s+livraison|سند\s*تسليم"),
        ("invoice", r"invoice|facture|فاتورة|فاتوره"),
        ("receipt", r"receipt|recu|ايصال"),
    ):
        if re.search(pattern, normalized(text)):
            return kind
    return "unknown"


def category_for(text):
    value = normalized(text)
    hits = [(kind, [w for w in words if normalized(w) in value]) for kind, words in WORDS.items()]
    hits = [(kind, words) for kind, words in hits if words]
    if len(hits) != 1:
        return {
            "category": "other",
            "confidence": None,
            "reason": "No unique category; accountant review required",
            "alternatives": [kind for kind, _ in hits],
        }
    kind, words = hits[0]
    return {
        "category": kind,
        "confidence": 0.65,
        "reason": "Local keyword suggestion: " + ", ".join(words),
        "score_type": "heuristic, not calibrated accuracy",
    }


def chart_suggestion(text, accounts, category):
    """Only suggest active accounts supplied from this company's chart."""
    from difflib import SequenceMatcher

    words = set(re.findall(r"\w+", normalized(text)))
    choices = []
    prefixes = ("2",) if category == "fixed_asset" else ("6",)
    expected_type = "asset" if category == "fixed_asset" else "expense"
    parent_ids = {a.get("parent_id") for a in accounts or [] if isinstance(a, dict) and a.get("parent_id")}
    for account in accounts or []:
        if not isinstance(account, dict):
            continue
        code = str(account.get("code") or "")
        account_type = str(account.get("type") or "").casefold()
        eligible = account_type == expected_type if account_type else code.startswith(prefixes)
        if not eligible or not code or not account.get("active", True) or account.get("id") in parent_ids:
            continue
        names = [normalized(account.get(k)) for k in ("name_en", "name_fr", "name_ar") if account.get(k)]
        score = max(
            (
                max(
                    len(words & set(re.findall(r"\w+", name))) / max(1, len(words)),
                    SequenceMatcher(None, normalized(text), name).ratio(),
                )
                for name in names
            ),
            default=0,
        )
        if score >= 0.45:
            choices.append((score, len(code), code, account))
    choices.sort(key=lambda row: (row[0], row[1]), reverse=True)
    if not choices or (len(choices) > 1 and choices[0][0] - choices[1][0] < 0.05):
        return {"account_code": None, "confidence": None, "reason": "No unique active company account; choose manually"}
    score, _, code, account = choices[0]
    return {
        "account_code": code,
        "account_name": account.get("name_en") or account.get("name_ar") or account.get("name_fr"),
        "confidence": round(min(score, 0.95), 2),
        "score_type": "heuristic, not calibrated accuracy",
        "reason": "Description matched an active company account; verify its use",
    }


def enrich(reading, accounts=(), suppliers=(), existing_documents=()):
    result = copy.deepcopy(reading)
    text = result.get("text") or ""
    warnings = list(result.get("review_warnings") or [])
    accounts = list(accounts)
    suppliers = list(suppliers)
    raw_confidence = result.get("field_confidence") or {}
    inferred = result.get("inferred") or []
    inferred_text = " ".join(map(str, inferred)).casefold()
    fields = {}
    for key in FIELDS:
        value = result.get(key)
        origin = "missing" if value in (None, "") else "read"
        if value not in (None, "") and (
            key in inferred
            or key in inferred_text
            or (
                inferred
                and key in ("subtotal", "vat", "total")
                and any(w in inferred_text for w in ("amount", "utility", "edl", "item"))
            )
        ):
            origin = "inferred"
        provenance = (result.get("field_provenance") or {}).get(key) or {}
        origin = provenance.get("origin", origin)
        confidence = raw_confidence.get(key, raw_confidence.get(ALIASES.get(key)))
        if (
            not isinstance(confidence, (float, int))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
            or origin in ("missing", "inferred")
        ):
            confidence = None
        fields[key] = {
            "value": value,
            "origin": origin,
            "confidence": confidence,
            "requires_review": True,
            "evidence": provenance.get("evidence")
            or ("Reader transcription; verify original" if origin == "read" else "Not directly read; verify source"),
        }
    candidate = re.search(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?!\d)", text)
    if candidate and 1 <= int(candidate[1]) <= 12 and 1 <= int(candidate[2]) <= 12 and candidate[1] != candidate[2]:
        fields["invoice_date"]["requires_confirmation"] = True
        warnings.append("Ambiguous numeric date: confirm day/month against original")
    result["fields"] = fields
    kind = document_kind(text)
    declared = result.get("document_type")
    if declared in ("invoice", "receipt", "credit_note", "debit_note", "quotation", "delivery_note"):
        kind = declared
    result["document_type"] = kind
    result["classification"] = category_for(text)
    if kind in ("credit_note", "debit_note"):
        result["classification"] = {
            "category": kind,
            "confidence": None,
            "reason": "Confirm direction and linked original invoice",
        }
    result["account_suggestion"] = chart_suggestion(text, accounts, result["classification"]["category"])
    result["suggested_account"] = result["account_suggestion"].get("account_code") or ""
    result["suggested_account_9"] = result["suggested_account"]
    result["suggested_account_name"] = result["account_suggestion"].get("account_name") or ""
    name = normalized(result.get("party_name"))
    matches = [p for p in suppliers if name and normalized(p.get("name")) == name]
    result["supplier_match"] = (
        {
            "id": matches[0].get("id"),
            "name": matches[0].get("name"),
            "reason": "Exact name match; confirm tax identity",
            "requires_review": True,
        }
        if len(matches) == 1
        else None
    )
    if len(matches) > 1:
        warnings.append("Supplier name matches multiple records; choose correct supplier")
    evidence = result.get("transcription_evidence") or {}
    if not result.get("items") and evidence.get("line_evidence"):
        result["items"] = [
            {
                "description": row.get("literal", {}).get("description_as_written") or "",
                "quantity": row.get("numbers", {}).get("quantity_as_written"),
                "unit_price": row.get("numbers", {}).get("unit_price_as_written"),
                "total": row.get("numbers", {}).get("total_as_written"),
                "origin": "vision_unverified",
            }
            for row in evidence["line_evidence"]
        ]
    if evidence.get("items_truncated"):
        warnings.append("Reader omitted some item rows; verify the complete original before using any lines")
    items = []
    for index, raw in enumerate(result.get("items") or [], 1):
        item = copy.deepcopy(raw)
        category = category_for(item.get("description"))
        item["classification"] = category
        item["account_suggestion"] = chart_suggestion(item.get("description"), accounts, category["category"])
        item["vat_suggestion"] = {
            "treatment": None,
            "confidence": None,
            "reason": "Eligibility depends on business use and statutory evidence; accountant must select it",
        }
        item["fields"] = {
            key: {
                "value": item.get(key),
                "confidence": None,
                "origin": "missing" if item.get(key) in (None, "") else "unverified",
                "requires_review": True,
            }
            for key in ("description", "quantity", "unit_price", "total")
        }
        qty, price, total = (number(item.get(k)) for k in ("quantity", "unit_price", "total"))
        if None not in (qty, price, total) and abs(qty * price - total) > Decimal(".02"):
            warnings.append(f"Item {index}: quantity × price differs from total")
        items.append(item)
    result["items"] = items
    sub, tax, total = (number(result.get(k)) for k in ("subtotal", "vat", "total"))
    line_totals = [number(item.get("total")) for item in items]
    if line_totals and sub is not None and all(value is not None for value in line_totals):
        if abs(sum(line_totals, Decimal(0)) - sub) > Decimal(".02"):
            warnings.append("Sum of item totals differs from subtotal; review omitted lines, discount and charges")
    if None not in (sub, tax, total) and abs(sub + tax - total) > Decimal(".02"):
        warnings.append("Subtotal + VAT differs from total; review discount, charges and original figures")
    invoice_number = normalized(result.get("invoice_number"))
    duplicate = [
        {"id": d.get("id"), "invoice_number": d.get("invoice_number")}
        for d in existing_documents
        if invoice_number
        and normalized(d.get("invoice_number")) == invoice_number
        and normalized(d.get("party_name")) == name
    ]
    result["duplicate_candidates"] = duplicate
    if duplicate:
        warnings.append("Possible existing invoice: verify duplicates before saving")
    if kind in ("quotation", "delivery_note", "unknown"):
        warnings.append("Confirm document type before creating an accounting invoice")
    warnings.insert(0, "Human review required: reading/classification never authorize posting or payment status")
    result["review_warnings"] = list(dict.fromkeys(warnings))
    result["review_required"] = True
    result["payment_status"] = None
    result["payment_method"] = None
    result["vat_suggestion"] = {
        "treatment": None,
        "confidence": None,
        "reason": "Accountant confirmation required; tax treatment cannot be determined from VAT amount alone",
    }
    result["intake_version"] = 1
    return result


def read(path, accounts=(), suppliers=(), existing_documents=(), reader="local", cancel=None):
    if reader == "local":
        from pdf_import import read_invoice_pdf

        reading = read_invoice_pdf(path, cancel=cancel)
    elif reader == "azure":
        from azure_reader import read_invoice

        reading = read_invoice(path)
    else:
        raise ValueError("Choose local or explicitly selected Azure reading")
    return enrich(reading, accounts, suppliers, existing_documents)
