"""Offline PaddleOCR invoice extraction with conservative TrOCR line fallback.

The tax rate is evidence/configuration, not a legal determination. Output money
uses decimal strings. Extracted invoices always require review before posting.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import threading

from .handwriting import HandwritingUnavailable, read_handwritten_line, read_handwritten_arabic_line

_LOCK = threading.Lock()
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TOTAL = re.compile(r"grand\s*total|total\s*(?:ttc|due|amount)|amount\s*due|الإجمالي|الاجمالي|المبلغ الإجمالي", re.I)
_VAT = re.compile(r"\bvat\b|\btva\b|ضريبة|القيمة المضافة", re.I)
_NUMBER = r"[+-]?\d[\d\s,٫٬]*(?:[.،]\d+)?"


class OCRUnavailable(RuntimeError):
    """Local Paddle model/runtime is missing or cannot initialize."""


@lru_cache(maxsize=1)
def _get_paddle():
    # Model directories are mandatory so Paddle cannot fetch weights implicitly.
    detection = os.environ.get("NANZA_PADDLE_DET_MODEL_DIR", "")
    recognition = os.environ.get("NANZA_PADDLE_REC_MODEL_DIR", "")
    if not detection or not recognition:
        raise OCRUnavailable("Set local NANZA_PADDLE_DET_MODEL_DIR and NANZA_PADDLE_REC_MODEL_DIR")
    if not Path(detection).is_dir() or not Path(recognition).is_dir():
        raise OCRUnavailable("Configured Paddle model directory does not exist")
    for folder in (Path(detection), Path(recognition)):
        if not (folder/"inference.pdiparams").is_file():
            raise OCRUnavailable("Paddle model weights are not installed in the configured directory")
        if not any((folder/name).is_file() for name in ("inference.json", "inference.pdmodel")):
            raise OCRUnavailable("Paddle inference model definition is missing")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        from paddleocr import PaddleOCR
        return PaddleOCR(
            lang="ar", device="cpu", text_detection_model_dir=detection,
            text_recognition_model_dir=recognition, use_doc_orientation_classify=False,
            use_doc_unwarping=False, use_textline_orientation=False)
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise OCRUnavailable("PaddleOCR CPU runtime/local Arabic models unavailable") from exc


def _normalize(text):
    return str(text).translate(_DIGITS).replace("\u00a0", " ")


def _money(token):
    text = _normalize(token).strip().replace(" ", "").replace("٬", "").replace("٫", ".")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        tail = text.rsplit(",", 1)[-1]
        text = text.replace(",", ".") if len(tail) in (1, 2) and text.count(",") == 1 else text.replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def _amount_after_label(line, label):
    match = label.search(line)
    if not match:
        return None
    tail = line[match.end():]
    # Exclude percentage tokens so 'VAT 11%: 11.00' reads amount 11, not rate.
    tail = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", tail)
    numbers = re.findall(_NUMBER, tail)
    return _money(numbers[-1]) if numbers else None


def _records(result):
    """Normalize pinned Paddle v3 results and legacy v2 fixtures."""
    for page in result or ():
        if isinstance(page, dict) or hasattr(page, "get"):
            data = page.get("res", page)
            texts = data.get("rec_texts", [])
            scores = data.get("rec_scores", [])
            boxes = data.get("rec_boxes", data.get("rec_polys", []))
            for i, text in enumerate(texts):
                score = float(scores[i]) if i < len(scores) else 0.0
                box = boxes[i] if i < len(boxes) else None
                yield str(text), max(0.0, min(1.0, score)) if math.isfinite(score) else 0.0, box
        else:
            for row in page or ():
                if row and len(row) == 2:
                    box, recognition = row
                    yield str(recognition[0]), max(0.0, min(1.0, float(recognition[1]))), box


def _crop(image, box):
    if box is None:
        return None
    values = box.tolist() if hasattr(box, "tolist") else box
    if len(values) == 4 and all(isinstance(x, (int, float)) for x in values):
        left, top, right, bottom = values
    else:
        left = min(p[0] for p in values); right = max(p[0] for p in values)
        top = min(p[1] for p in values); bottom = max(p[1] for p in values)
    left, top = max(0, int(left)), max(0, int(top))
    right, bottom = min(image.width, int(right)), min(image.height, int(bottom))
    return image.crop((left, top, right, bottom)) if right > left and bottom > top else None


def _parse(text, country=None):
    lines = [line.strip() for line in _normalize(text).splitlines() if line.strip()]
    warnings = []; totals = []; taxes = []; dates = []; rates = []
    vendor = None; items = []; item_fields = {}
    subtotal = None
    for line in lines:
        if vendor is None and not re.search(r"invoice|فاتورة|facture|date|تاريخ", line, re.I):
            vendor = re.sub(r"^(?:vendor|supplier|المورد|fournisseur)\s*[:：-]?\s*", "", line, flags=re.I)
        for key, label in (("description", "الصنف"), ("quantity", "الكمية"), ("unit_price", "السعر")):
            match = re.match(r"^"+label+r"\s*[:：]\s*(.+)$", line)
            if match:
                item_fields[key] = match.group(1).strip()
        sub = _amount_after_label(line, re.compile(r"^المجموع|^subtotal", re.I))
        if sub is not None: subtotal = sub
        amount = _amount_after_label(line, _TOTAL)
        if amount is not None:
            totals.append(amount)
        # A simple bare Total label is supported, but Subtotal/HT are not gross.
        if amount is None and re.match(r"^total\s*[:：]", line, re.I):
            value = _money(line.split(":", 1)[-1])
            if value is not None: totals.append(value)
        if _VAT.search(line):
            vat = _amount_after_label(line, _VAT)
            if vat is not None: taxes.append(vat)
            rates += [Decimal(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", line)]
        for raw in re.findall(r"\b(?:\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})\b", line):
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    dates.append(datetime.strptime(raw, fmt).date().isoformat())
                    break
                except ValueError:
                    continue
        # Deliberately narrow line pattern; never invent missing invoice items.
        item = re.match(r"^(.+?)\s+(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)$", line)
        if item:
            description, qty, unit, total = item.groups()
            values = [_money(v) for v in (qty, unit, total)]
            if all(v is not None for v in values):
                items.append(dict(description=description, quantity=str(values[0]),
                                  unit_price=str(values[1]), total=str(values[2])))
    if not items and {"description", "quantity", "unit_price"} <= set(item_fields):
        qty = _money(item_fields["quantity"])
        tokens = re.findall(_NUMBER, item_fields["unit_price"])
        price = _money(tokens[0]) if tokens else None
        if qty is not None and price is not None:
            items.append({"description": item_fields["description"], "quantity": str(qty),
                          "unit_price": str(price), "total": str(subtotal if subtotal is not None else qty*price)})
    profile = str(country or os.environ.get("NANZA_TAX_COUNTRY", "")).upper()
    rate = rates[-1] if rates else None
    if not rates and profile in ("LB", "LEBANON", "SA", "KSA"):
        rate = Decimal(11 if profile in ("LB", "LEBANON") else 15)
        warnings.append("vat_rate_assumed_from_country_requires_review")
    if len(set(totals)) > 1: warnings.append("conflicting_totals")
    if len(set(taxes)) > 1: warnings.append("conflicting_vat_amounts")
    if len(set(dates)) > 1: warnings.append("multiple_dates_require_review")
    if len(set(rates)) > 1: warnings.append("mixed_vat_rates")
    total = totals[-1] if totals else None; vat = taxes[-1] if taxes else None
    expected = {"LB": 11, "LEBANON": 11, "SA": 15, "KSA": 15}.get(profile)
    if expected and rate is not None and rate not in (Decimal(0), Decimal(expected)):
        warnings.append("vat_rate_country_mismatch")
    if total is not None and vat is not None:
        if vat > total: warnings.append("vat_exceeds_total")
        if rate is not None and total > vat:
            implied = ((total-vat)*rate/100).quantize(Decimal("0.01"))
            if abs(implied-vat) > Decimal("0.02"): warnings.append("vat_arithmetic_mismatch")
    for name, value in (("vendor", vendor), ("date", dates), ("total", total), ("vat", vat), ("vat_rate", rate)):
        if value is None or value == [] or value == "": warnings.append("missing_"+name)
    return {"vendor": vendor, "date": dates[0] if dates else None,
            "total": str(total) if total is not None else None,
            "vat": str(vat) if vat is not None else None,
            "vat_rate": float(rate) if rate is not None else None,
            "items": items, "warnings": warnings}


def extract_invoice_data(image_path: str, *, country=None, language=None, handwriting=False) -> dict:
    """Route script/handwriting and return review proposals, never postings.

    Paddle bootstraps language when available. Arabic routes to local Falcon. English low-confidence crops use TrOCR. Explicit language/handwriting
    hints work without bootstrap; unknown script is not guessed from a filename.
    """
    from PIL import Image, ImageOps
    path = Path(image_path)
    if not path.is_file(): raise FileNotFoundError(path)
    if path.stat().st_size > 15 * 1024 * 1024: raise ValueError("Image exceeds 15 MB")
    if language not in (None, "ar", "en", "fr"):
        raise ValueError("language must be ar, en, fr or None")
    alternatives = []; warnings = []; lines = []
    with Image.open(path) as original:
        if original.width * original.height > 25_000_000: raise ValueError("Image exceeds 25 million pixels")
        image = ImageOps.exif_transpose(original).convert("RGB")
    def arabic_result():
        from .arabic import read_arabic_document
        reading = read_arabic_document(image, handwriting=handwriting)
        parsed = _parse(reading["text"], country)
        return {**parsed, "confidence": reading["confidence"], "raw_text": reading["text"],
                "needs_review": True, "language": "ar", "backend": reading["backend"],
                "seconds": reading["seconds"], "warnings": parsed["warnings"]+reading["warnings"],
                "fallback_text": []}
    if language == "ar":
        try:
            answer = arabic_result()
            image.close()
            return answer
        except HandwritingUnavailable as exc:
            warnings.append(str(exc))
    if language == "en" and handwriting:
        try:
            text = read_handwritten_line(image)
            parsed = _parse(text, country)
            image.close()
            return {**parsed, "confidence": None, "raw_text": text, "needs_review": True,
                    "language": "en", "backend": "trocr", "warnings": parsed["warnings"], "fallback_text": []}
        except HandwritingUnavailable as exc:
            warnings.append(str(exc))
    try:
        with _LOCK:
            reader = _get_paddle()
            import numpy as np
            result = reader.predict(np.asarray(image))
            recognized = list(_records(result))[:5000]
    except (OCRUnavailable, OSError, RuntimeError, ValueError) as exc:
        if language != "en" and os.environ.get("NANZA_FALCON_ARABIC_MODEL_DIR"):
            try:
                answer = arabic_result()
                image.close()
                return answer
            except HandwritingUnavailable as arabic_error:
                warnings.append(str(arabic_error))
        image.close()
        answer = _parse("", country)
        return {**answer, "confidence": 0.0, "raw_text": "", "needs_review": True,
                "language": language or "unknown", "backend": "unavailable",
                "warnings": answer["warnings"]+warnings+[str(exc)], "fallback_text": []}
    detected_language = "ar" if any(re.search(r"[\u0600-\u06ff]", text) for text, _, _ in recognized) else "en"
    if detected_language == "ar" and language != "ar":
        try:
            answer = arabic_result()
            image.close()
            return answer
        except HandwritingUnavailable as exc:
            warnings.append("arabic_backend_unavailable: "+str(exc))
    for text, score, box in recognized:
        chosen = text
        if score < .6:
            warnings.append("low_confidence_region")
            crop = _crop(image, box)
            if crop is not None:
                try:
                    fallback = (read_handwritten_arabic_line(crop)
                                if re.search(r"[\u0600-\u06ff]", text) else read_handwritten_line(crop))
                    if fallback:
                        alternatives.append({"original": text, "trocr": fallback})
                        if not re.search(r"[\u0600-\u06ff]", text): chosen = fallback
                        warnings.append("trocr_hypothesis_requires_review")
                except (HandwritingUnavailable, OSError, RuntimeError, ValueError) as exc:
                    warnings.append("trocr_unavailable: "+str(exc))
                finally:
                    crop.close()
        lines.append(chosen)
    raw = "\n".join(lines); parsed = _parse(raw, country)
    confidence = sum(score for _, score, _ in recognized)/len(recognized) if recognized else 0.0
    image.close()
    return {**parsed, "confidence": round(confidence, 4), "raw_text": raw,
            "needs_review": True, "language": language or detected_language, "backend": "paddle",
            "warnings": list(dict.fromkeys(parsed["warnings"]+warnings)),
            "fallback_text": alternatives}
