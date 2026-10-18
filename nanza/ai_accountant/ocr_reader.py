"""Review-first OCR adapter for the existing Arabic/English invoice reader."""
from __future__ import annotations


def read_invoice(path, cancel=None):
    """Read a printed or handwritten invoice using Nanza's configured OCR stack.

    This adapter deliberately returns suggestions only. The existing invoice flow
    must still validate and approve every extracted field before posting.
    """
    from pdf_import import read_invoice_pdf
    result = read_invoice_pdf(path, cancel=cancel)
    warnings = list(result.get("review_warnings") or [])
    if result.get("notes"):
        warnings.append(str(result["notes"]))
    return {"vendor": result.get("party_name") or "", "date": result.get("invoice_date") or "",
            "invoice_number": result.get("invoice_number") or "", "currency": result.get("currency") or "",
            "subtotal": result.get("subtotal"), "vat": result.get("vat"), "total": result.get("total"),
            "items": result.get("items") or [], "warnings": warnings, "source": "existing Nanza OCR",
            "requires_human_review": True}
