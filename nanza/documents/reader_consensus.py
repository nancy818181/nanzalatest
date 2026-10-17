"""Compare independent invoice readings without voting, arithmetic repairs or guessed missing values."""
from decimal import Decimal, InvalidOperation
import unicodedata


AMOUNTS = {"subtotal", "vat", "total"}
FIELDS = ("invoice_number", "invoice_date", "party_name", "party_tax_number", "currency", "subtotal", "vat", "total")


def _same(field, first, second):
    if first in (None, "") or second in (None, ""): return False
    if isinstance(first, bool) or isinstance(second, bool): return False
    if field in AMOUNTS:
        try:
            a, b = Decimal(str(first)), Decimal(str(second))
            return a.is_finite() and b.is_finite() and a == b
        except InvalidOperation:
            return False
    normal = lambda value: " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())
    return normal(first) == normal(second)


def merge_invoice_readings(primary, secondary):
    """Agreement is a suggestion, never verification. Disputed or singly read fields stay empty."""
    result = dict(primary)
    result["review_warnings"] = list(primary.get("review_warnings") or [])
    result["reader_candidates"] = {"qwen4b": {key: primary.get(key) for key in FIELDS},
                                   "qwen2b": {key: secondary.get(key) for key in FIELDS}}
    for warning in secondary.get("review_warnings") or []:
        if warning not in result["review_warnings"]: result["review_warnings"].append(warning)
    result["reader_evidence"] = {"qwen4b": primary.get("transcription_evidence") or {},
                                 "qwen2b": secondary.get("transcription_evidence") or {}}
    result["consensus_fields"] = []
    for field in FIELDS:
        first, second = primary.get(field), secondary.get(field)
        if _same(field, first, second):
            result["consensus_fields"].append(field)
            continue
        result[field] = None if field in AMOUNTS else ""
        if first not in (None, "") or second not in (None, ""):
            result["review_warnings"].append(f"Independent readers disagree or cannot both read {field.replace('_', ' ')}; confirm from the image")
    result["supplier_hint"] = result.get("party_name") or ""
    result["acquisition_cost"] = result.get("subtotal")
    if not primary.get("expense_category") or primary.get("expense_category") != secondary.get("expense_category"):
        for field in ("expense_category", "suggested_account", "suggested_account_9", "suggested_account_name"):
            result[field] = ""
    # Line matching needs stable source regions, not a positional merge of two possibly reordered lists.
    if primary.get("items") or secondary.get("items"):
        result["items"] = []
        result["reader_item_candidates"] = {"qwen4b": primary.get("items") or [], "qwen2b": secondary.get("items") or []}
        result["review_warnings"].append("Line items require confirmation against their image regions; they were not automatically merged")
    result["review_required"] = True
    result["review_warnings"].append("Two readers can agree on the same wrong value; verify handwriting against the image before Save")
    return result
