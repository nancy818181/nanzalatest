"""Score saved reader JSON against manually verified invoice transcriptions.

Usage: python tools/benchmark_invoice_reader.py labels.json predictions.json
Labels: [{"id":"sample1", "verified":true, "expected":{"total":40,...}}]
Predictions: {"sample1":{"total":40,...}}
Keep both files private and outside the source repository. Blank answers count as
missed fields, not successes; model confidence never substitutes for ground truth.
"""
import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import unicodedata

FIELDS = ("invoice_number", "invoice_date", "party_name", "currency", "subtotal", "vat", "total", "items", "expense_category")
NUMBERS = {"subtotal", "vat", "total"}


def equal(field, expected, actual):
    if expected in (None, "") or expected == [] or actual in (None, "") or actual == []:
        return (expected in (None, "") or expected == []) and (actual in (None, "") or actual == [])
    if isinstance(actual, bool): return False
    if field in NUMBERS:
        try:
            first, second = Decimal(str(expected)), Decimal(str(actual))
            return first.is_finite() and second.is_finite() and first == second
        except (InvalidOperation, ValueError, TypeError): return False
    if field == "items": return expected == actual  # strict complete lines, no omitted rows
    if field == "invoice_date":
        def date(value):
            for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try: return datetime.strptime(str(value), pattern).date()
                except ValueError: continue
            return None
        return date(expected) is not None and date(expected) == date(actual)
    normalize = lambda value: " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())
    return normalize(expected) == normalize(actual)


def score(labels, predictions):
    counts = {}; errors = []; verified_ids = set(); exact_documents = 0
    for sample in labels:
        if sample.get("verified") is not True: raise ValueError("Every label must be manually verified before scoring")
        key = sample["id"]
        if key in verified_ids: raise ValueError("Duplicate benchmark sample id")
        verified_ids.add(key)
        expected = sample["expected"]; actual = predictions.get(key, {})
        if not expected or set(expected) - set(FIELDS): raise ValueError("Use supported invoice fields in the labels")
        document_ok = True
        for field, value in expected.items():
            record = counts.setdefault(field, {"present": 0, "correct": 0, "absent": 0, "false_fills": 0})
            absent = value in (None, "") or value == []
            matched = equal(field, value, actual.get(field))
            if absent:
                record["absent"] += 1
                if not matched: record["false_fills"] += 1
            else:
                record["present"] += 1
                if matched: record["correct"] += 1
            if not matched:
                document_ok = False
                errors.append({"id": key, "field": field})
        if document_ok: exact_documents += 1
    present = sum(v["present"] for v in counts.values())
    correct = sum(v["correct"] for v in counts.values())
    return {"documents": len(verified_ids), "exact_documents": exact_documents, "fields": counts,
            "reading_accuracy": correct / present if present else None,
            "false_fills": sum(v["false_fills"] for v in counts.values()), "errors": errors,
            "note": "Reading accuracy excludes blank ground-truth fields. Inspect each field, false fills and complete-document results separately; this is not a posting approval."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels"); parser.add_argument("predictions")
    args = parser.parse_args()
    with open(args.labels, encoding="utf-8") as stream: labels = json.load(stream)
    with open(args.predictions, encoding="utf-8") as stream: predictions = json.load(stream)
    print(json.dumps(score(labels, predictions), ensure_ascii=False, indent=2))
