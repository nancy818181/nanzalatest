"""2.9.132 Phase 2: the AI Accountant's account suggestions - one reviewable answer for a purchase, an expense or a sale.

What it does (and only this):
- Suggests an account from THIS company's chart of accounts (active posting accounts only), with the transaction type,
  the cost centre (department / project) and the VAT use when they come from the supplier's / customer's earlier POSTED
  documents. Nothing is invented: every value says where it comes from (evidence) and whether it was READ from the
  document (extracted) or INFERRED (history, keywords).
- Gives a confidence between 0 and 1, a level (high / medium / low) and a plain-language explanation. The confidence is
  a rule score (how much consistent evidence there is), NOT a measured accuracy.
- Abstains, with its reason, when the evidence is missing, conflicting or under the company's threshold
  (Settings key ai_min_confidence, default 0.75).
- Learns only from documents that were reviewed and posted: the history is read live from posted invoices, so a
  cancelled, deleted, Review or credit-note document never teaches anything.
- Never writes, posts, approves or pays anything. A VAT use copied from history carries NEEDS ACCOUNTANT CONFIRMATION;
  no Lebanese tax rule is applied here.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

RULE_VERSION = "advisor-2.9.132"
DEFAULT_THRESHOLD = Decimal("0.75")
TAX_NOTE = ("VAT use / treatment copied from this party's earlier posted documents - NEEDS ACCOUNTANT CONFIRMATION. "
            "The suggestion applies no tax rule.")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_LEGAL = {"sarl", "sal", "sa", "llc", "ltd", "co", "company", "est", "group", "holding", "the", "and", "شركة", "مؤسسة", "ش", "م", "ل"}


def threshold(db):
    """The company's minimum confidence for a suggestion (0.50 to 0.99); anything else falls back to 0.75."""
    try: value = Decimal(str((db.settings() or {}).get("ai_min_confidence") or DEFAULT_THRESHOLD))
    except (InvalidOperation, ValueError, TypeError, AttributeError): return DEFAULT_THRESHOLD
    return value if Decimal("0.50") <= value <= Decimal("0.99") else DEFAULT_THRESHOLD


def _level(confidence):
    return "high" if confidence >= Decimal("0.90") else "medium" if confidence >= Decimal("0.75") else "low"


def _party_key(name):
    text = unicodedata.normalize("NFKC", str(name or "")).casefold().replace(".", "")
    words = [w for w in re.findall(r"\w+", text) if w not in _LEGAL and not w.isdigit()]
    return " ".join(words)


def languages(text):
    text = str(text or "")
    found = []
    if _ARABIC.search(text): found.append("arabic")
    if _LATIN.search(text): found.append("latin (English / French)")
    return found


def chart(db):
    """{code: account} of the active POSTING accounts of the company's own chart."""
    return {str(a["code"]): a for a in db.list_accounts() if a.get("is_active") and a.get("is_posting")}


def _money(value):
    if value in (None, ""): return None
    try: return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError): return None


def _name(account):
    return account.get("name_en") or account.get("name_fr") or account.get("name_ar") or ""


def _history(db, kind, party):
    """Accounts of this party's POSTED documents (reviewed, not cancelled / deleted / Review, no credit notes), newest first."""
    wanted = _party_key(party)
    if not wanted: return []
    with db.connect() as connection:
        rows = [dict(r) for r in connection.execute(
            """SELECT i.invoice_number,i.invoice_date,i.expense_account,i.entry_type,i.vat_use,i.vat_treatment,i.department_id,i.project_id,p.name party_name
               FROM invoices i JOIN parties p ON p.id=i.party_id
               WHERE i.kind=? AND i.status='posted' AND COALESCE(i.doc_subtype,'invoice')<>'credit_note'
                 AND COALESCE(i.source_file,'') NOT IN ('Opening balances') ORDER BY i.id DESC LIMIT 200""", (kind,))]
    return [r for r in rows if _party_key(r["party_name"]) == wanted][:20]


def _possible_duplicate(db, kind, party, number):
    if not party or not number: return None
    from db_invoices import InvoicesStore as InvoiceStore
    key = InvoiceStore.invoice_number_key(number); wanted = _party_key(party)
    with db.connect() as connection:
        for row in connection.execute("""SELECT i.id,i.invoice_number,i.invoice_date,i.total,i.currency,i.status,p.name FROM invoices i
                JOIN parties p ON p.id=i.party_id WHERE i.kind=? AND i.status NOT IN ('cancelled','deleted','void')""", (kind,)):
            if _party_key(row["name"]) == wanted and InvoiceStore.invoice_number_key(row["invoice_number"]) == key:
                return {"invoice_id": row["id"], "invoice_number": row["invoice_number"], "date": row["invoice_date"], "status": row["status"]}
    return None


def _keyword_candidates(text, accounts):
    """Keyword categories (English / French / Arabic) resolved to an account that exists in this chart."""
    import pdf_import
    found = pdf_import.expense_classification(text)
    out = []
    for item in found["candidates"]:
        label, dotted, nine, _default_name = item["category"]
        code = dotted if dotted in accounts else nine if nine in accounts else None
        out.append({"category": label, "account_code": code, "evidence": item["evidence"], "score": item["score"]})
    return found["status"], out


def suggest(db, scope="purchase", party=None, text="", lines=(), invoice_number=None, subtotal=None, vat=None, total=None):
    """One reviewable suggestion. scope: purchase | expense | sale. Read only."""
    scope = str(scope or "purchase").lower()
    if scope not in ("purchase", "expense", "sale"): raise ValueError("scope must be purchase, expense or sale")
    lines = [str(x) for x in lines or () if str(x or "").strip()]
    words = " ".join([str(text or ""), *lines]).strip()
    accounts = chart(db); limit = threshold(db)
    kind = "sale" if scope == "sale" else "purchase"
    result = {"status": "abstain", "abstain": True, "abstain_reason": "", "suggestion": None, "candidates": [], "warnings": [],
              "extracted": {"party": party or "", "invoice_number": invoice_number or "", "subtotal": _money(subtotal), "vat": _money(vat),
                            "total": _money(total), "lines": lines},
              "original_text": words, "languages": languages(words), "threshold": limit, "rule_version": RULE_VERSION,
              "requires_review": True, "posts_nothing": True}
    # ---- facts that need a person, whatever the account
    s, v, t = result["extracted"]["subtotal"], result["extracted"]["vat"], result["extracted"]["total"]
    if s is not None and v is not None and t is not None and s + v != t:
        result["warnings"].append(f"Totals do not agree: subtotal {s} + VAT {v} = {s + v}, but the total read is {t}. Check the document.")
    duplicate = _possible_duplicate(db, kind, party, invoice_number)
    if duplicate:
        result["possible_duplicate"] = duplicate
        result["warnings"].append(f"Possible duplicate: {duplicate['invoice_number']} of {duplicate['date']} from the same party is already saved ({duplicate['status']}).")
    # ---- 1. the party's posted history
    evidence = []; choice = None
    history = _history(db, kind, party) if scope != "expense" else []
    if history:
        counts = {}
        for row in history: counts[row["expense_account"]] = counts.get(row["expense_account"], 0) + 1
        code, times = max(counts.items(), key=lambda item: (item[1], item[0]))
        share = Decimal(times) / Decimal(len(history))
        if code not in accounts:
            result["warnings"].append(f"The account {code} used on this party's earlier documents is no longer an active posting account.")
        elif share < Decimal("0.6"):
            result["candidates"] += [{"account_code": c, "account_name": _name(accounts.get(c, {})), "times": n, "source": "posted history"}
                                     for c, n in sorted(counts.items(), key=lambda item: -item[1]) if c in accounts]
            result["abstain_reason"] = "This party's posted documents use different accounts; choose one."
        else:
            confidence = min(Decimal("0.97"), Decimal("0.70") + Decimal("0.08") * min(times, 3) + Decimal("0.05") * (share - Decimal("0.6")) / Decimal("0.4"))
            latest = next(r for r in history if r["expense_account"] == code)
            choice = {"account_code": code, "confidence": confidence.quantize(Decimal("0.01")),
                      "transaction_type": latest["entry_type"], "source": "posted history"}
            if scope != "sale" and latest.get("vat_use"):
                choice.update(vat_use=latest["vat_use"], vat_treatment=latest.get("vat_treatment") or "standard", tax_note=TAX_NOTE)
            if latest.get("department_id") or latest.get("project_id"):
                choice.update(department_id=latest.get("department_id"), project_id=latest.get("project_id"))
            evidence.append({"kind": "inferred", "source": "history",
                             "text": f"{times} of the last {len(history)} posted documents of this party used {code} (latest {latest['invoice_number']})."})
    # ---- 2. keywords of the document (purchases and expenses only)
    if choice is None and scope != "sale" and words and not result["candidates"]:
        status, found = _keyword_candidates(words, accounts)
        usable = [c for c in found if c["account_code"]]
        if status == "ambiguous":
            result["candidates"] += [{"account_code": c["account_code"], "account_name": _name(accounts.get(c["account_code"], {})), "category": c["category"],
                                      "evidence": c["evidence"], "source": "keywords"} for c in usable]
            result["abstain_reason"] = "The document mentions several kinds of expense with the same weight; split the lines or choose the account."
        elif usable:
            best = usable[0]
            choice = {"account_code": best["account_code"], "confidence": Decimal("0.86") if best["score"] >= 2 else Decimal("0.78"),
                      "transaction_type": "expenses" if scope == "expense" else "purchases", "source": "keywords"}
            evidence.append({"kind": "extracted", "source": "document", "text": "Words read on the document: " + ", ".join(best["evidence"])})
            evidence.append({"kind": "inferred", "source": "keywords", "text": f"These words are the '{best['category']}' category, posted to {best['account_code']} in this chart."})
        elif found:
            result["warnings"].append(f"The '{found[0]['category']}' category has no matching active posting account in this chart.")
    # ---- decision
    if choice is None:
        result["abstain_reason"] = result["abstain_reason"] or ("No posted history for this party and no recognised words: choose the account."
                                                                 if words or party else "Nothing to go on: enter the party or the description.")
        return result
    choice["account_name"] = _name(accounts[choice["account_code"]]); choice["level"] = _level(choice["confidence"])
    choice["evidence"] = evidence
    choice["explanation"] = " ".join(e["text"] for e in evidence) + f" Confidence {choice['confidence']} (rule score, not a measured accuracy)."
    if choice["confidence"] < limit:
        result["candidates"].insert(0, {k: choice[k] for k in ("account_code", "account_name", "confidence", "source")})
        result["abstain_reason"] = f"Confidence {choice['confidence']} is under the company's threshold {limit}; confirm the account."
        return result
    result.update(status="needs_review" if result["warnings"] else "suggested", abstain=False, suggestion=choice)
    return result
