"""Expense category, expense account hint, issuer from e-mail and invoice type suggestion for a read invoice.

Moved unchanged from pdf_import.py (2.9.138 consolidation) - pdf_import re-exports every name, so
`pdf_import.expense_classification(...)` and `from pdf_import import suggest_invoice_type` keep working.
Every result is a suggestion for review, never a posting decision."""
from __future__ import annotations

import re


EXPENSE_ACCOUNT_HINTS = (  # 2.9.87: a starting point for the expense account (Lebanese chart); the user confirms it
    (r"\b(?:office\s+)?rent(?:al)?\b|loyer|إيجار", "6263.1"), (r"\bwater\b|مياه", "6263.3"),
    (r"maintenance|repair|entretien|صيانة", "6262"), (r"telephone|mobile\s+line|internet|telecom|courier|postage|اتصالات|هاتف", "6261.5"),
    (r"insurance|assurance|تأمين", "6268"), (r"advertis|publicit|marketing|إعلان", "6269.3"),
    (r"stationery|office\s+supplies|papeterie|قرطاسية", "6269.4"), (r"legal|lawyer|consult|audit\s+fee|accounting\s+fee|avocat|محام|استشار", "6265.3"),
    (r"travel|hotel|air\s*ticket|flight|accommodation|سفر|فندق", "6264.2"), (r"subscription|abonnement|اشتراك", "6266.2"),
    (r"bank\s+charges?|commission\s+bancaire", "6739"), (r"transport(?:ation)?|freight|shipping|clearance|customs\s+formalities|نقل|شحن", "6261.1"),
)
# 2.9.97: scored categories - every keyword found counts, the strongest category wins ("TRAVEL INSURANCE" on an air-ticket
# invoice is travel, not insurance). Each category has its 9-digit expense account, opened automatically when missing.
EXPENSE_CATEGORIES = (
    ("Travel", "6264.2", "626420000", "Travel & Accommodation Expenses",
     (r"\btravel", r"\btickets?\b", r"\bflights?\b", r"\bair(?:line|ways|\s*ticket)", r"\bhotel", r"accommodation", r"\bvisa\b",
      r"\b[A-Z0-9]{2}-?\d{3,4}\b(?=.*\b[A-Z]{3}/[A-Z]{3})", r"\b[A-Z]{3}/[A-Z]{3}\b", r"سفر", r"تذكرة", r"فندق")),
    ("Electricity", "6263.4", "626340000", "Electricity Expenses",
     (r"electricit", r"électricit", r"\bEDL\b", r"ed[li]\W{0,2}[gq]ov", r"\bkwh\b", r"\bgenerator\b", r"\bampere", r"\btranches?\b", r"\bbranchement",
      r"\bconsommation\b", r"\bcompteur\b", r"كهرباء", r"مولد", r"عداد", r"اشتراك\s+كهرباء")),
    ("Commissions", "6265.2", "626520000", "Commissions Paid to Agents",
     (r"\bcommissions?\b(?!\s+bancaire)", r"\baffiliate", r"\bbrokerage\b", r"\bcourtage", r"عمولة")),
    ("Rent", "6263.1", "626310000", "Rent Expenses", (r"\b(?:office\s+)?rent(?:al)?\b", r"\bloyer", r"إيجار")),
    ("Water", "6263.3", "626330000", "Water Expenses", (r"\bwater\b", r"مياه")),
    ("Telecom", "6261.5", "626150000", "Telephone, Internet & Postage", (r"telephone", r"mobile\s+line", r"internet", r"telecom", r"courier", r"postage", r"اتصالات", r"هاتف")),
    ("Maintenance", "6262", "626200000", "Maintenance & Repairs", (r"maintenance", r"\brepair", r"entretien", r"صيانة", r"تصليح", r"[إا]صلاح", r"بواجي", r"بوجي")),
    ("Insurance", "6268", "626800000", "Insurance Premium", (r"insurance\s+(?:premium|policy)", r"\bpolicy\s+no", r"\bassurance", r"تأمين")),
    ("Advertising", "6269.3", "626930000", "Advertising & Marketing", (r"advertis", r"publicit", r"marketing", r"[إا]علان", r"دعاي[ةه]", r"تسويق")),
    ("Stationery", "6269.4", "626940000", "Stationery & Office Supplies", (r"stationery", r"office\s+supplies", r"papeterie", r"قرطاسية")),
    ("Professional fees", "6265.3", "626530000", "Legal & Consulting Fees", (r"\blegal\b", r"lawyer", r"consult", r"audit\s+fee", r"accounting\s+fee", r"avocat", r"محام", r"استشار")),
    ("Subscriptions", "6266.2", "626620000", "Subscriptions", (r"subscription", r"abonnement")),
    ("Transport", "6261.1", "626110000", "Transport & Shipping", (r"\btransport(?:ation)?\b", r"freight", r"shipping", r"clearance", r"نقل", r"شحن")),
    ("Bank charges", "6739", "673900000", "Bank Commissions", (r"bank\s+charges?", r"commission\s+bancaire")),
)


def expense_classification(text):
    """Explain keyword evidence. Scores rank suggestions; they are not accuracy probabilities."""
    candidates = []
    for category in EXPENSE_CATEGORIES:
        evidence = [match.group(0) for pattern in category[4]
                    if (match := re.search(pattern, text or "", re.I))]
        if evidence and not (category[0] == "Travel" and len(evidence) < 2):
            candidates.append({"category": category[:4], "score": len(evidence),
                               "evidence": list(dict.fromkeys(evidence))})
    candidates.sort(key=lambda item: item["score"], reverse=True)
    ambiguous = len(candidates) > 1 and candidates[0]["score"] == candidates[1]["score"]
    return {"status": "ambiguous" if ambiguous else "suggested" if candidates else "unknown",
            "category": candidates[0]["category"] if candidates and not ambiguous else None,
            "candidates": candidates, "review_required": True}


def expense_category(text):
    """Return a single supported category; ties require a choice by the user."""
    return expense_classification(text)["category"]


def suggest_expense_account(text):
    classification = expense_classification(text)
    if classification["status"] == "ambiguous": return ""
    found = classification["category"]
    if found: return found[1]
    for pattern, code in EXPENSE_ACCOUNT_HINTS:
        if re.search(pattern, text or "", re.I): return code
    return ""


_GENERIC_MAIL = {"info", "support", "sales", "admin", "contact", "accounts", "accounting", "billing", "noreply", "no-reply", "office", "mail", "hello", "finance"}


def supplier_from_email(text):
    """2.9.97: the issuer of the document from its e-mail address ('Pegasus@pegasuslb.com' -> Pegasus, 'support@eaugroup.co' ->
    the 'EAU Group' written in the text). The name printed in the header is often the CUSTOMER (the buyer's company)."""
    for local, domain in re.findall(r"([A-Za-z0-9._-]+)@([A-Za-z0-9-]+)\.", text or ""):
        if domain.lower() in ("gmail", "hotmail", "yahoo", "outlook", "icloud", "live"): continue
        if local.lower() not in _GENERIC_MAIL and len(local) >= 3 and local.isalpha(): return local[0].upper() + local[1:]
        squashed = domain.lower().replace("-", "")
        tokens = re.findall(r"[A-Za-z&]+", re.sub(r"\S+@\S+|www\.\S+|https?://\S+", " ", text))  # not the address itself
        for size in range(1, 5):  # every run of 1-4 words, overlapping ('EAU Group' inside 'EAU Group Affiliate')
            for start in range(len(tokens) - size + 1):
                words = tokens[start:start + size]
                if re.sub(r"[^a-z]", "", "".join(words).lower()) == squashed: return " ".join(words)
        return domain[0].upper() + domain[1:]
    return ""


def suggest_invoice_type(text):
    """Conservative PDF category suggestion, never a posting decision.

    An invoice alone does not establish whether an expense has been paid or
    whether goods are held for resale. Conflicting or weak clues need review.
    """
    clues = {
        "Assets": (
            r"\bfixed assets?\b", r"\bcapital (?:asset|expenditure)\b",
            r"\boffice (?:furniture|equipment)\b", r"أصول ثابتة", r"موجودات ثابتة",
            r"immobilisation(?:s)?",
        ),
        "Purchases": (
            r"\b(?:goods|stock) for resale\b", r"\braw materials?\b",
            r"\bmerchandise\b", r"بضاعة", r"مواد أولية", r"marchandises",
        ),
        "Expenses": (
            r"\b(?:office|monthly) rent\b", r"\belectricity\b", r"\binternet service\b",
            r"\bconsulting (?:fee|service)\b", r"\bmaintenance (?:fee|service)\b",
            r"إيجار", r"كهرباء", r"اشتراك انترنت", r"loyer", r"électricité",
        ),
    }
    found = [category for category, patterns in clues.items()
             if any(re.search(pattern, text or "", re.I) for pattern in patterns)]
    return found[0] if len(found) == 1 else ""
