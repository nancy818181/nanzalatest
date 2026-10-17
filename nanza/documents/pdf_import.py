"""Read invoice details from PDFs and expose reviewable line items.

Text-layer extraction is preferred. Scanned pages use local Tesseract OCR when
the optional OCR runtime is installed; invoice text is never sent elsewhere.
"""
from __future__ import annotations
import logging

import os
import re
import sys
from datetime import datetime
from pathlib import Path

AMOUNT = r"([0-9]{1,3}(?:[,\s][0-9]{3})+(?:\.[0-9]{1,3})?|[0-9]+(?:\.[0-9]{1,3})?)"
DATE_PATTERNS = (
    (r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\b", "dmy"),
    (r"\b(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})\b", "ymd"),
)
ARABIC_SUBTOTAL = ("المجموع الفرعي", "الاجمالي الفرعي", "المجموع قبل الضريبة",
                   "الاجمالي قبل الضريبة", "المبلغ قبل الضريبة",
                   "الاجمالي الخاضع للضريبة", "المبلغ الخاضع للضريبة")
ARABIC_VAT = ("ضريبة القيمة المضافة", "الضريبة على القيمة المضافة",
              "قيمة الضريبة", "مبلغ الضريبة", "ض.ق.م")
ARABIC_TOTAL = ("اجمالي الفاتورة", "المجموع الكلي", "المبلغ الاجمالي",
                "المبلغ المستحق", "الصافي للدفع", "الاجمالي", "المجموع")
ENGLISH_MONTHS = {
    "jan": 1, "january": 1, "janv": 1, "janvier": 1,
    "feb": 2, "fob": 2, "february": 2, "fev": 2, "fevr": 2, "févr": 2, "février": 2,
    "mar": 3, "march": 3, "mars": 3,
    "apr": 4, "april": 4, "avr": 4, "avril": 4,
    "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juin": 6,
    "jul": 7, "july": 7, "juil": 7, "juillet": 7,
    "aug": 8, "august": 8, "aout": 8, "août": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12, "déc": 12, "décembre": 12,
}
CURRENCY_CODE = re.compile(r"\b(USD|EUR|AED|LBP)\b", re.I)

# 2.9.85: the names of the company whose books are open (the buyer on a purchase invoice). Set by the program;
# a line naming it is never taken as the supplier, and a page addressed to someone else is a supporting document.
OWN_COMPANY_NAMES = []


KNOWN_PARTIES = []  # 2.9.85: suppliers / customers already in the books - a name printed on the page is taken first


def set_known_parties(names):
    KNOWN_PARTIES[:] = sorted({n.strip() for n in (str(x or "") for x in names or []) if len(n.strip()) >= 4}, key=len, reverse=True)


def _squash(text):
    return re.sub(r"[^0-9a-z؀-ۿ]+", " ", (text or "").casefold()).strip()


def _known_party_in(text):
    """The known party printed earliest on the page (the longest name wins at the same place); never the open company."""
    page = " " + _squash(text) + " "; best = None
    for name in KNOWN_PARTIES:
        key = _squash(name)
        if len(key) < 4 or mentions_own_company(name): continue
        position = page.find(" " + key + " ")
        if position >= 0 and (best is None or position < best[0]): best = (position, name)
    return best[1] if best else ""


def set_own_company(*names):
    OWN_COMPANY_NAMES[:] = [n for n in (str(x or "").strip() for x in names) if len(n) >= 3]


def _own_words():
    words = set()
    for name in OWN_COMPANY_NAMES:
        for word in re.findall(r"[A-Za-z\u0600-\u06FF]{4,}", name):
            if word.casefold() not in {"international", "company", "group", "trading", "lebanon", "holding", "services", "sarl", "offshore"}:
                words.add(word.casefold())
    return words


def mentions_own_company(text):
    """True when the text names the open company (one distinctive word of its name is enough, OCR is not exact)."""
    words = _own_words(); low = (text or "").casefold()
    return bool(words) and any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low) for w in words)


def _normalize_amount_line(line):
    """Normalize OCR Arabic digits, separators, hamza and vowel marks for label matching."""
    line = line.translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬أإآٱ",
        "01234567890123456789.,اااا",
    ))
    return re.sub(r"[\u0640\u064b-\u065f\u0670]", "", line)


def pdf_text(path, layout=False):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join(_page_text(page, layout) for page in reader.pages)


def _page_text(page, layout=False):
    """2.9.85: layout=True keeps the columns of a table on one line in reading order (plain extraction glues the cells
    of many invoices together: '1193 CHANNA DRIED2.781,529.00 5500.00 %')."""
    try:
        return (page.extract_text(extraction_mode="layout") if layout else page.extract_text()) or ""
    except Exception:
        return (page.extract_text() or "") if layout else ""


def _text_score(path, text):
    parsed = _parse_invoice_text(path, text)
    return _ocr_invoice_score(path, text) + (2 if parsed.get("items") else 0), parsed


def _better_text(path, plain, layout):
    """The text (plain or layout) that reads more of the invoice; plain wins a tie."""
    if len((layout or "").strip()) < 20: return plain
    if len((plain or "").strip()) < 20: return layout
    return layout if _text_score(path, layout)[0] > _text_score(path, plain)[0] else plain


def _ocr_pdf_pages(path, page_numbers=None, progress=None, cancel=None):
    """OCR selected zero-based PDF pages locally, with the bundled engine if frozen.
    2.9.85: progress(done, total) after each page; cancel (an Event) stops before the next page (the rest stay empty)."""
    import pypdfium2 as pdfium
    import pytesseract

    import nanza_paths  # 2.9.117
    bundle_root = nanza_paths.ROOT
    ocr_root = bundle_root / "ocr"
    engine = ocr_root / "engine"
    tessdata = ocr_root / "tessdata"
    if getattr(sys, "frozen", False):
        executable = engine / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
        if not executable.is_file():
            raise RuntimeError("The bundled Tesseract OCR engine is missing")
        pytesseract.pytesseract.tesseract_cmd = str(executable)

    # The bundled language files are found through TESSDATA_PREFIX, not a --tessdata-dir option:
    # pytesseract splits the option text, which breaks Windows paths ("C:\\Program Files\\...")
    # because of the backslashes, the spaces and the quotes, and OCR then reports no languages.
    if tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    config = "--psm 6"
    english_config = "--psm 4"
    try:
        available = set(pytesseract.get_languages(config=config))
    except Exception as exc:
        raise RuntimeError(f"Tesseract language data is unavailable ({exc})") from exc
    languages = [lang for lang in ("eng", "fra", "ara") if lang in available]
    if not languages:
        raise RuntimeError("Install English, French or Arabic Tesseract language data to read scanned invoices")
    language = "+".join(languages)

    def read_image(image):
        if _is_photo(image):  # 2.9.97: a phone photo of a bill (dark background, often sideways)
            return _read_photo(pytesseract, image, language)
        image = _remove_table_lines(image)  # 2.9.97: the table borders hid most item rows from the OCR (1 row of 21 read)
        text = _fix_ocr_text(_tesseract_text(pytesseract, image, lang=language, config=config))
        if _word_count(text) < 25:  # 2.9.97: almost nothing read - the page may be turned
            turned = _upright(pytesseract, image)
            if turned is not None:
                image = turned; text = _fix_ocr_text(_tesseract_text(pytesseract, image, lang=language, config=config))
        # PSM 6 with both languages can mistake a clear English invoice heading for another word. If key invoice
        # fields are missing, retry with English layout analysis and keep the better extraction.
        parsed = _parse_invoice_text(path, text)
        subtotal, vat, total = (parsed.get(key) for key in ("subtotal", "vat", "total"))
        amounts_conflict = all(value is not None for value in (subtotal, vat, total)) and abs(subtotal + vat - total) > max(0.05, abs(total) * 0.005)
        core_fields_missing = any(parsed.get(key) in (None, "") for key in ("invoice_number", "invoice_date", "total"))
        if "eng" in languages and (core_fields_missing or amounts_conflict):
            alternate = _fix_ocr_text(_tesseract_text(pytesseract, image, lang="eng", config=english_config))
            if _ocr_invoice_score(path, alternate) > _ocr_invoice_score(path, text): text = alternate
        if "eng" in languages and not _labelled_invoice_date(text):
            text = text + "\n" + _ocr_header_lines(pytesseract, image, english_config)
        return text

    # 2.9.89: the pages are drawn one by one (PDFium is not thread-safe) but read by several OCR engines at once
    # (each is its own process): a 79-page scanned file took about 11 minutes, now a fraction on a multi-core PC.
    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # one core per engine: OpenMP spinning on all cores made OCR many times slower
    document = pdfium.PdfDocument(str(path))
    selected = list(range(len(document)) if page_numbers is None else page_numbers)
    texts = [""] * len(selected); pending = {}; done = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, page_number in enumerate(selected):
                if cancel is not None and cancel.is_set(): break
                while len(pending) >= workers * 2:  # keep only a few page images in memory
                    first = min(pending); texts[first] = pending.pop(first).result(); done += 1
                    if progress: progress(done, len(selected))
                page = document[int(page_number)]
                try:
                    bitmap = page.render(scale=3.0); image = bitmap.to_pil(); bitmap.close()  # 2.9.97: 3x reads small table digits better
                finally:
                    page.close()
                pending[index] = pool.submit(lambda img: (read_image(img), img.close())[0], image)
            if progress and not done: progress(0, len(selected))
            for index in sorted(pending):
                texts[index] = pending[index].result(); done += 1
                if progress: progress(done, len(selected))
    finally:
        document.close()
    return texts


def _labelled_invoice_date(text):
    return re.search(r"(?im)\b(?:date|dated|le|التاريخ|تاريخ)\b\s*[:.]?\s*\d", normalize_invoice_text(text or ""))


def _ocr_header_lines(pytesseract, image, config):
    """Underlined or right-aligned header fields (Date, Ref No.) are often lost by a full-page pass.
    Read the top quarter again, left and right halves separately, as sparse text; return the new lines."""
    try:
        from PIL import Image
        width, height = image.size
        lines = []
        for box in ((width // 2, 0, width, height // 4), (0, 0, width // 2, height // 4)):
            crop = image.crop(box)
            crop = crop.resize((crop.width * 2, crop.height * 2), getattr(getattr(Image, "Resampling", Image), "LANCZOS"))
            sparse = config.replace("--psm 4", "--psm 11")
            lines += [line.strip() for line in _tesseract_text(pytesseract, crop, lang="eng", config=sparse).splitlines()
                      if re.search(r"(?i)\b(date|ref|invoice|facture|no\.?|nb)\b", line)]
        return "\n".join(lines) + "\n" if lines else ""
    except Exception:
        return ""


def _ocr_pdf(path, page_numbers=None):
    return "\n".join(_without_copies(_ocr_pdf_pages(path, page_numbers)))


def _page_key(text):
    """The invoice number and the amounts of a page."""
    joined = re.sub(r"\b([A-Z]{1,3}) (\d{5,})\b", r"\1\2", text)  # 'SJ 20252445' on the copy = 'SJ20252445'
    number = re.sub(r"\s+", "", _invoice_number(joined) or "")
    amounts = set(re.findall(r"\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}", text))
    return number, amounts


def _without_copies(texts):
    """2.9.97: a scanned file often holds the original and a copy of the same invoice (Diwan: page 2 = page 1 with the PO
    number): reading both doubled every item. A page with the same invoice number and mostly the same amounts as an earlier
    page is left out (a real second page of an invoice has other items, so other amounts). OCR reads a few digits differently
    on each copy, so the amounts are compared by overlap, not exactly."""
    kept, seen = [], []
    for text in texts:
        number, amounts = _page_key(text)
        copy = False
        for earlier_number, earlier in seen:
            union = amounts | earlier
            overlap = len(amounts & earlier) / len(union) if union else 0
            if len(amounts) >= 5 and ((number and number == earlier_number and overlap >= 0.6) or overlap >= 0.9): copy = True; break
        if copy: continue
        seen.append((number, amounts)); kept.append(text)
    return kept


def _trim_ocr_name(name):
    """2.9.97: OCR reads the Arabic half of a bilingual letterhead as Latin noise after the company name
    ('DIWAN GROUP C.S. LS GF Sl gall ASE'): keep the name up to its company form (C.S., S.A.L., SARL, LLC, FZE ...)."""
    match = re.match(r"^(.*?\b(?:s\.a\.r\.l|s\.a\.l|sarl|sal|llc|ltd|limited|inc|c\.s|fze|fzco|co)\.?)(?=\s|$)", name.strip(), re.I)
    return match.group(1).strip() if match and len(match.group(1)) >= 4 else name


def _word_count(text):
    return sum(1 for word in str(text or "").split() if len(word) > 2 and sum(ch.isalnum() for ch in word) >= len(word) * 0.7)


def _is_photo(image):
    """2.9.97: a photo, not a scan: a dark border / background around the paper (a scan is white around the text)."""
    try:
        import numpy as np
        gray = np.array(image.convert("L").resize((200, max(1, int(200 * image.height / max(1, image.width))))))
        edges = np.concatenate([gray[:6].ravel(), gray[-6:].ravel(), gray[:, :6].ravel(), gray[:, -6:].ravel()])
        return float(edges.mean()) < 150 or float((gray < 160).mean()) > 0.35
    except Exception:
        return False


def _upright(pytesseract, image):
    """The page turned upright: Tesseract's orientation check when its data is there, else the better of 90 / 270 degrees."""
    try:
        osd = pytesseract.image_to_osd(image, timeout=30)
        angle = int(re.search(r"Rotate:\s*(\d+)", osd).group(1))
        return image.rotate(-angle, expand=True) if angle else None
    except Exception:
        best, best_words = None, 0
        try:
            for angle in (90, 270, 180):
                turned = image.rotate(angle, expand=True)
                words = _word_count(_tesseract_text(pytesseract, turned.resize((turned.width // 2, turned.height // 2)), lang="eng", config="--psm 6"))
                if words > best_words: best, best_words = turned, words
        except Exception:
            return None  # not an image that can be turned (or no OCR engine): keep the page as it is
        return best if best_words >= 15 else None


def _otsu(gray):
    import numpy as np
    from PIL import Image
    values = np.array(gray); histogram = np.bincount(values.ravel(), minlength=256).astype(float)
    total = values.size; weighted = np.dot(np.arange(256), histogram); best, threshold, w0, s0 = 0.0, 128, 0.0, 0.0
    for level in range(256):
        w0 += histogram[level]
        if w0 == 0 or w0 == total: continue
        s0 += level * histogram[level]; m0 = s0 / w0; m1 = (weighted - s0) / (total - w0)
        between = w0 * (total - w0) * (m0 - m1) ** 2
        if between > best: best, threshold = between, level
    return Image.fromarray(((values > threshold) * 255).astype("uint8"))


def _read_photo(pytesseract, image, language):
    """Turn the photo upright and choose one reading from contrast and layout variants."""
    from PIL import ImageOps
    turned = _upright(pytesseract, image)
    if turned is not None: image = turned
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=2)
    first = _tesseract_text(pytesseract, gray, lang="eng", config="--psm 4")
    second = _tesseract_text(pytesseract, _otsu(gray.resize((gray.width // 2, gray.height // 2))), lang="eng", config="--psm 11")
    arabic = _tesseract_text(pytesseract, gray, lang=language, config="--psm 6") if "ara" in language else ""
    # 2.9.118: dot-matrix amounts on a coloured form (EDL): the red channel drops the pink background, enlarged and
    # softened the dots join into digits
    try:
        from PIL import Image, ImageFilter
        red = image.convert("RGB").split()[0]
        red = red.resize((red.width * 2, red.height * 2), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))
        dots = _tesseract_text(pytesseract, red.point(lambda p: 255 if p > 110 else 0), lang="eng", config="--psm 11")
    except (OSError, ValueError, RuntimeError):
        dots = ""
    candidates=[first,second,arabic,dots]
    prepared=[]
    try:
        from ocr_photo import variants
        prepared=variants(image)
        for candidate in prepared:
            candidates.append(_tesseract_text(pytesseract, candidate,lang=language,config="--psm 6"))
    except (ImportError,OSError,ValueError,RuntimeError):
        logging.getLogger("saber.pdf").debug("Photo preparation unavailable",exc_info=True)
    finally:
        for candidate in prepared: candidate.close()
    # Do not concatenate alternative OCR readings: their digits can form a false balanced total.
    candidates=[_fix_ocr_text(text) for text in candidates if text.strip()]
    return max(candidates,key=_photo_reading_score) if candidates else ""



def _tesseract_text(engine, image, **options):
    """Terminate a stalled OCR subprocess instead of waiting indefinitely."""
    return engine.image_to_string(image, timeout=30, **options)


def _photo_reading_score(text):
    parsed=_parse_invoice_text(Path("photo.pdf"),text)
    score=_ocr_invoice_score(Path("photo.pdf"),text)-4*len(parsed.get("inferred") or [])
    day=parsed.get("invoice_date") or ""
    if day:
        try:
            year = datetime.strptime(day, "%d-%m-%Y").year
            if not 2000 <= year <= 2100: score -= 6
        except ValueError: score -= 6
    return score

def _remove_table_lines(image):
    """2.9.97: whiten the long horizontal / vertical rules of a table before OCR (they make Tesseract skip the rows)."""
    try:
        import numpy as np
        from PIL import Image
        gray = np.array(image.convert("L")); dark = gray < 160
        height, width = dark.shape
        rows, columns = dark.sum(axis=1) > width * 0.35, dark.sum(axis=0) > height * 0.25
        if rows.mean() > 0.2 or columns.mean() > 0.2: return image  # not table rules: a dark photo - leave it
        clean = gray.copy()
        clean[rows, :] = 255
        clean[:, columns] = 255
        return Image.fromarray(clean)
    except Exception:
        return image


def _fix_ocr_text(text):
    """2.9.97: common OCR misreads on invoices: 'SJ2025...' read as '$J2025...', 'Currency' as 'Curreney'."""
    text = re.sub(r"\$(?=[A-Z]\s?\d{6,})", "S", text)
    text = re.sub(r"(?i)\bcurr[ec]n[ec]y\b", "Currency", text)
    return text


def _ocr_invoice_score(path, text):
    parsed = _parse_invoice_text(path, text)
    weights = {
        "invoice_number": 2,
        "invoice_date": 2,
        "currency": 1,
        "subtotal": 1,
        "vat": 1,
        "total": 2,
    }
    score = sum(weight for key, weight in weights.items()
                if parsed.get(key) not in (None, ""))
    subtotal, vat, total = (parsed.get(key) for key in ("subtotal", "vat", "total"))
    if all(value is not None for value in (subtotal, vat, total)):
        tolerance = max(0.05, abs(total) * 0.005)
        score += 4 if abs(subtotal + vat - total) <= tolerance else -1
    return score


def _invoice_text_needs_ocr(path, text):
    """Retry weak text layers with OCR instead of treating any extracted text as usable."""
    if len((text or "").strip()) < 20:
        return True
    if (text or "").count("\x1f") > 5:
        return True   # fonts without a character map: scrambled words, read the page image instead
    parsed = _parse_invoice_text(path, text)
    return parsed.get("total") is None or (
        not parsed.get("invoice_number") and not parsed.get("invoice_date")
    )


def _page_needs_ocr(path, text):
    """2.9.85: one page of a longer PDF. A readable page with the invoice number or date but no total is the first
    page of a multi-page invoice (the total is on its last page): its text is kept, not replaced by OCR."""
    if len((text or "").strip()) < 20 or (text or "").count("\x1f") > 5:
        return True
    parsed = _parse_invoice_text(path, text)
    return not parsed.get("invoice_number") and not parsed.get("invoice_date") and parsed.get("total") is None


_ARABIC_LETTER = re.compile(r"[\u0600-\u06FF]")
_ARABIC_HINTS = ("المجموع", "الضريبة", "فاتورة", "التاريخ", "رقم", "القيمة", "المضافة", "شركة")


def _logical_arabic(line):
    """Some PDFs store Arabic lines in visual (drawn right-to-left) order: put them back in reading order,
    keeping numbers and Latin words as they are."""
    if not _ARABIC_LETTER.search(line) or any(h in line for h in _ARABIC_HINTS): return line
    parts = re.split(r"(\s{3,})", line)
    if len(parts) > 1:  # 2.9.85: columns of a layout line are turned one by one ("DIWAN GROUP C.S.      <Arabic name>")
        return "".join(_logical_arabic(part) if not part.isspace() else part for part in parts)
    reversed_line = line[::-1]
    if not any(h in reversed_line for h in _ARABIC_HINTS): return line
    return re.sub(r"[0-9A-Za-z.,:/%$€#\-]+", lambda m: m.group(0)[::-1], reversed_line)


def normalize_invoice_text(text):
    """Before reading: Arabic presentation forms -> normal letters, visual Arabic -> reading order,
    European decimals (200,00 / 1.234,56) -> 200.00 / 1,234.56."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(str.maketrans("یکھۀ", "يكهه"))  # 2.9.85: Persian yeh / keheh / heh of Lebanese fonts -> Arabic
    lines = [_logical_arabic(line) for line in text.splitlines()]
    # a label alone on its line followed by a line that is only an amount (common with right-to-left layouts): read them together
    joined = []; amount_only = re.compile(r"^\s*[-+]?[\d.,]+\s*(?:USD|LBP|EUR|AED|SAR|L\.?L\.?|\$|€|ل\.ل\.?)?\s*$", re.I)
    for line in lines:
        if joined and amount_only.match(line) and re.search(r"[A-Za-z\u0600-\u06FF]{3}", joined[-1]) and not re.search(r"\d", joined[-1]):
            joined[-1] = f"{joined[-1].rstrip(' :')} : {line.strip()}"
        else: joined.append(line)
    text = "\n".join(joined)
    text = re.sub(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+),(\d{2})(?![\d,])", lambda m: m.group(1).replace(".", ",") + "." + m.group(2), text)
    text = re.sub(r"(?<![\d.,])(\d+),(\d{2})(?![\d,])", r"\1.\2", text)
    return text


def _number(text):
    try: return float(str(text).replace(",", "").replace(" ", ""))
    except ValueError: return None


def _keyword_end(line, keyword):
    """Find a label without matching 'total' in 'subtotal' or 'tax' in 'taxable'."""
    if keyword.isascii():
        for match in re.finditer(rf"(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])", line, re.I):
            if keyword == "total" and re.search(r"sub[\s-]*$", line[:match.start()], re.I):
                continue
            return match.end()
        return None
    position = line.find(keyword)
    return position + len(keyword) if position >= 0 else None


def _amount_after(text, keywords):
    """Last same-line labelled amount (also accepts Arabic RTL number-first OCR)."""
    found = None
    for raw in text.splitlines():
        line = _normalize_amount_line(raw)
        for keyword in keywords:
            end = _keyword_end(line, keyword)
            if end is None: continue
            numbers = re.findall(AMOUNT, line[end:])
            values = [v for v in (_number(n) for n in numbers) if v is not None]
            if values:
                found = values[-1]
            elif not keyword.isascii():
                # Tesseract may emit RTL rows as "١١١٫٠٠ : المجموع الكلي".
                prefix = line[:end - len(keyword)].strip()
                if re.fullmatch(rf"{AMOUNT}\s*(?:\$|€|USD|LBP|EUR|AED)?\s*[:\-]?", prefix):
                    found = _number(re.search(AMOUNT, prefix).group())
    return found


def _vat_amount_after(text, invoice_currency=""):
    """Read the VAT in the invoice currency, not its translated LBP equivalent."""
    if invoice_currency:
        inline = re.compile(
            rf"{AMOUNT}\s*{re.escape(invoice_currency)}\s*VAT\b", re.I
        )
        for line in text.splitlines():
            match = inline.search(line)
            if match:
                value = _number(match.group(1))
                if value is not None:
                    return value

    found = None
    best_score = 0
    for raw in text.splitlines():
        line = _normalize_amount_line(raw)
        line = re.sub(r"(?i)\bv\s*\.?\s*a\s*\.?\s*t\s*\.?\b", "VAT", line)
        if re.search(
            r"\b(?:vat|tva|tax)\b.{0,35}\b(?:account|a/c|no\.?|number|registration|id)\b",
            line, re.I,
        ):
            continue
        if re.search(r"\b(?:vat|tva|tax)\s*#", line, re.I):
            continue
        if re.search(r"(?:\bn\s*[°o]\.?|\bno\.?|\bnum[ée]ro|\bnumber)\s*(?:de\s+)?(?:vat|tva|tax)\b", line, re.I):
            continue  # 2.9.118: "N° TVA : 241559" is the VAT registration number (EDL), not an amount
        if re.search(
            r"\bpaid\s+on\s+behalf\b|\bbefore\s+vat\b|\btotal\s+(?:ht|excl|without)\s+vat\b",
            line, re.I,
        ):
            continue
        if re.search(r"رقم\s*(?:التسجيل\s*)?الضريبة", line):
            continue
        # 2.9.90: the amount in words on the same line ("... Seventeen and 94/100 USD") gave a VAT of 100
        line = re.sub(r"(?i)\b(?:[a-z]+\s+)*(?:thousand|hundred|million)\b[^\d]*(?:\d+\s*/\s*100)?[^\d]*", " ", line)
        line = re.sub(r"\d+\s*/\s*100\b", " ", line)
        for keyword in ("vat amount", "vat 11%", "vat", "tva", "tax", *ARABIC_VAT):
            end = _keyword_end(line, keyword)
            if end is None:
                continue
            suffix = line[end:]
            amount_matches = [
                match for match in re.finditer(AMOUNT, suffix)
                if not suffix[match.end():].lstrip().startswith(("%", "٪"))
            ]
            values = [_number(match.group(1)) for match in amount_matches]
            values = [(match, value) for match, value in zip(amount_matches, values)
                      if value is not None]
            if values:
                currencies = list(CURRENCY_CODE.finditer(suffix))
                matching_currency = [
                    match for match in currencies
                    if match.group(1).upper() == invoice_currency.upper()
                ] if invoice_currency else []
                if matching_currency:
                    currency_position = matching_currency[0].start()
                    amount_match, value = min(
                        values,
                        key=lambda pair: abs(
                            (pair[0].start() + pair[0].end()) / 2 - currency_position
                        ),
                    )
                    score = 3
                elif currencies:
                    first_currency_position = currencies[0].start()
                    before_currency = [
                        (match, value) for match, value in values
                        if match.end() <= first_currency_position
                    ]
                    if before_currency:
                        amount_match, value = before_currency[-1]
                        score = 2
                    elif invoice_currency:
                        # The only amount is explicitly labelled in another
                        # currency, so don't treat an exchange conversion as VAT.
                        continue
                    else:
                        amount_match, value = values[-1]
                        score = 1
                else:
                    amount_match, value = values[-1]
                    score = 1
                if score >= best_score:
                    found = value
                    best_score = score
            elif keyword.isascii() and re.fullmatch(rf"\s*{AMOUNT}\s*[:\-]?\s*", line[:end - len(keyword)] if line[:end].lower().endswith(keyword) else ""):
                value = _number(re.search(AMOUNT, line[:end - len(keyword)]).group(1))  # 2.9.85: amount first, then the label
                if value is not None and 1 >= best_score: found = value; best_score = 1
            elif not keyword.isascii():
                prefix = line[:end - len(keyword)].strip()
                if re.fullmatch(rf"{AMOUNT}\s*[:\-]?", prefix):
                    found = _number(re.search(AMOUNT, prefix).group())
    return found


def _invoice_number(text):
    proforma = re.search(r"(?i)pro-?\s?forma\s*(?:no\.?|number|#)?\s*[:#]\s*([A-Z\d][A-Z\d.\-/]{2,30})", text)  # 2.9.97: PROFORMA#:PF.HO.25.0000005
    if proforma and any(ch.isdigit() for ch in proforma.group(1)): return proforma.group(1).strip(".-/")
    same_line = re.compile(
        r"(?:invoice|inv\b|facture|فاتورة|رقم[^\S\n]*(?:ال)?فاتورة|n°[^\S\n]*facture|bill)"
        r"[^\S\n]*(?:no\.?|number|num|#|n°|رقم)?[^\S\n]*[:#.]?[^\S\n]*([A-Z\d][A-Z\d\-/]{1,24})", re.I)
    for match in same_line.finditer(text):  # 2.9.87
        candidate = _normalize_amount_line(match.group(1)).strip("-/")
        if any(char.isdigit() for char in candidate) and not re.fullmatch(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}", candidate):
            return candidate
    pattern = re.compile(
        r"(?:invoice|inv\b|facture|فاتورة|رقم\s*(?:ال)?فاتورة|n°\s*facture|bill)"
        r"\s*(?:no\.?|number|num|#|n°|رقم)?\s*[:#.]?\s*([A-Z\d][A-Z\d\-/]{1,24})",
        re.I,
    )
    position = 0
    while True:  # overlapping search: "TAX INVOICE / Invoice No: INV-2026-0457" must not stop at the first "INVOICE"
        match = pattern.search(text, position)
        if not match: break
        candidate = _normalize_amount_line(match.group(1)).strip("-/")
        if any(char.isdigit() for char in candidate):
            return candidate
        position = match.start() + 1

    # Some invoice templates visually put the number before the "INVOICE NO"
    # label; pypdf preserves that text order instead of the reading order.
    for match in re.finditer(
        r"(?<![A-Za-z])(?:invoice|inv|facture)\s*(?:no\.?|number|#)", text, re.I
    ):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()]
        leading_number = re.match(
            r"\s*([A-Z\d][A-Z\d\-/]{1,24})\s+"
            r"(?=(?:\d{1,2}\s+[A-Za-zÀ-ÿ]{3,10}[., ]+\d{4}|"
            r"[A-Za-zÀ-ÿ]{3,10}\s+\d{1,2},?\s+\d{4})\b)",
            prefix, re.I,
        )
        if leading_number and any(char.isdigit() for char in leading_number.group(1)):
            return leading_number.group(1)

    reference = _document_reference_number(text)
    if reference:
        return reference
    return ""


def _document_reference_number(text):
    pattern = re.compile(
        r"(?<![A-Za-z])(?:ref(?:erence)?|document\s+(?:ref|reference))"
        r"\s*(?:nb\s*)?(?:no\.?|number|#|n°)?\s*[:#.]?\s*"
        r"([A-Z\d][A-Z\d\-/]{1,24})",
        re.I,
    )
    position = 0
    while True:  # overlapping search: "TAX INVOICE / Invoice No: INV-2026-0457" must not stop at the first "INVOICE"
        match = pattern.search(text, position)
        if not match: break
        candidate = _normalize_amount_line(match.group(1)).strip("-/")
        if any(char.isdigit() for char in candidate):
            return candidate
        position = match.start() + 1
    return ""


def _invoice_date(text):
    # A date on a line labelled "Date" wins over dates in the item table (delivery days, periods).
    for line in str(text or "").splitlines():
        if re.search(r"(?i)^\W*(?:invoice\s+)?(?:date|dated|le|التاريخ|تاريخ)\b", line.strip()):
            found = _any_date(line)
            if found: return found
    return _any_date(text)


def _any_date(text):
    for pattern, order in DATE_PATTERNS:
        for groups in re.findall(pattern, text):
            try:
                day, month, year = (
                    groups if order == "dmy" else (groups[2], groups[1], groups[0])
                )
                return datetime(_expand_year(year), int(month), int(day)).strftime("%d-%m-%Y")
            except ValueError:
                continue

    month_date = re.compile(
        r"\b(?:(\d{1,2})[./\-\s]+([A-Za-zÀ-ÿ]{3,10})[.,/\-\s]+(\d{2}|\d{4})"
        r"|([A-Za-zÀ-ÿ]{3,10})[.,]?\s+(\d{1,2}),?\s+(\d{2}|\d{4}))\b",
        re.I,
    )
    for match in month_date.finditer(text):
        if match.group(1):
            day, month_name, year = match.group(1, 2, 3)
        else:
            month_name, day, year = match.group(4, 5, 6)
        month = ENGLISH_MONTHS.get(month_name.casefold().rstrip("."))
        if month is None:
            continue
        try:
            return datetime(_expand_year(year), month, int(day)).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return ""


def _expand_year(year):
    year = int(year)
    if year < 100:
        return 2000 + year if year <= 49 else 1900 + year
    return year


def _currency_from_total_context(segment):
    """Prefer a currency symbol adjacent to the total over unrelated bank details."""
    if re.search(r"\bUSD\b|\bUS\s*\$", segment, re.I):
        return "USD"
    if "$" in segment:
        return "USD"
    if re.search(r"\bEUR\b|€", segment, re.I):
        return "EUR"
    if re.search(r"\bAED\b|\bDHS\b|د\s*\.?\s*إ", segment, re.I):
        return "AED"
    match = CURRENCY_CODE.search(segment)
    return match.group(1).upper() if match else ""


def _invoice_currency(text):
    codes = r"(USD|EUR|AED|LBP)"
    lines = text.splitlines()
    for line in lines:  # 2.9.85: "Currency: USD" / "Devise : EUR"
        match = re.search(rf"\b(?:currency|devise)\s*[:.]?\s*{codes}\b", line, re.I)
        if match and not re.search(r"(?i)bank|account|iban|swift|a/c", line):
            return match.group(1).upper()
    for line in lines:
        match = re.search(rf"\b(?:the\s+)?sum\s+of\s+{codes}\b", line, re.I)
        if match:
            return match.group(1).upper()
        match = re.search(rf"\btotal\s*\(\s*{codes}\s*\)", line, re.I)
        if match:
            return match.group(1).upper()

    for index, line in enumerate(lines):
        if not re.search(r"\b(?:grand\s+)?total\b|\bamount\s+due\b", line, re.I):
            continue
        if re.search(r"\bsub[\s-]*total\b|\btotal\s+(?:before|ht|excl|without)\b", line, re.I):
            continue
        segment = " ".join(lines[index:index + 4])
        currency = _currency_from_total_context(segment)
        if currency:
            return currency

    upper = text.upper()
    for code, marks in (
        ("LBP", ("LBP", "L.L", "ل.ل", "LL ")),
        ("EUR", ("EUR", "€")),
        ("AED", ("AED", "DHS")),
        ("USD", ("USD", "US$")),
    ):
        if any(bool(re.search(r"\bLL\b",upper)) if mark=="LL " else mark in upper for mark in marks):
            return code
    return ""


def _invoice_total_after(text):
    """Ignore lines that name the before-VAT total rather than the invoice total."""
    lines = [
        line for line in text.splitlines()
        if not re.search(r"\bsub[\s-]*total\b|\btotal\s+(?:ht|before|excl|without)\b", line, re.I)
        and not re.search(r"\btotal\s+(?:net\s+|gross\s+)?(?:weight|qty|quantity|pieces|packages|kgs?|cbm|volume)\b", line, re.I)
        and not any(label in _normalize_amount_line(line) for label in ARABIC_SUBTOTAL)
        and not any(label in _normalize_amount_line(line) for label in ARABIC_VAT)
    ]
    return _amount_after(
        "\n".join(lines),
        ("grand total", "total amount", "amount due", "net to pay", "total ttc",
         "sum of", "total", *ARABIC_TOTAL),
    )


def _subtotal_from_tax_breakdown(text):
    """Read an unqualified Total as pre-tax only when VAT and Grand Total follow."""
    lines = [_normalize_amount_line(line) for line in text.splitlines()]
    grand_total = next(
        (index for index, line in enumerate(lines)
         if re.search(r"\bgrand\s+total\b", line, re.I)),
        None,
    )
    if grand_total is None:
        return None

    for index, line in enumerate(lines[:grand_total]):
        if not re.search(r"\btotal\b", line, re.I):
            continue
        if re.search(r"\b(?:grand|sub[\s-]*)total\b|\btotal\s+(?:before|ht|excl|without)\b",
                     line, re.I):
            continue
        vat_index = next(
            (
                line_index
                for line_index in range(index + 1, grand_total)
                if (
                    re.search(r"\b(?:vat|tva|tax)\b", lines[line_index], re.I)
                    or any(label in lines[line_index] for label in ARABIC_VAT)
                )
                and not re.search(
                    r"\b(?:account|a/c|number|registration|id)\b",
                    lines[line_index],
                    re.I,
                )
            ),
            None,
        )
        if vat_index is None:
            continue

        value = _amount_after(line, ("total",))
        if value is not None:
            return value

        # Some PDF text layers split the label, currency symbol, and amount
        # onto nearby lines. Do not cross the VAT label while looking for it.
        for following in lines[index + 1:min(vat_index, index + 4)]:
            numbers = re.findall(AMOUNT, following)
            values = [value for value in (_number(number) for number in numbers)
                      if value is not None]
            if values:
                return values[-1]
    return None


def _line_items(text):
    """Best-effort extraction of common invoice item rows.

    Invoice layouts differ too much for this to be an automatic posting
    decision.  These rows are only pre-filled into the review screen.  A row
    must end in quantity, unit price and line total, which avoids treating
    supplier address/phone lines as products.
    """
    items = []
    ignored = re.compile(
        r"\b(?:invoice|facture|subtotal|sub-total|total|vat|tva|tax|amount|date|phone|tel|"
        r"page|discount|shipping|freight|currency|due)\b|رقم|فاتورة|ضريبة",  # 2.9.85: whole words ("DATES PITTED" is an item)
        re.I,
    )
    number = r"[0-9]{1,3}(?:[,\s][0-9]{3})*(?:\.[0-9]{1,3})?|[0-9]+(?:\.[0-9]{1,3})?"
    row_pattern = re.compile(
        rf"^\s*(?P<description>.+?)\s+(?P<quantity>{number})\s+"
        rf"(?P<unit_price>{number})\s+(?P<total>{number})\s*$"
    )
    for raw in text.splitlines():
        line = " ".join(_normalize_amount_line(raw).split())
        line = " ".join(re.sub(r"(?<=\d)\s*\$|\$\s*(?=\d)", " ", line).split())  # 2.9.97: 7.10$ 9,585.00$ / $ 7.10
        if len(line) < 5 or ignored.search(line):
            continue
        match = row_pattern.match(line)
        if not match:
            leading = _total_first_row(line)  # 2.9.85: TOTAL | VAT | DISC % | U.PRICE | QTY | UNIT | DESCRIPTION
            if leading: items.append(leading)
            continue
        description = match.group("description").strip(" -:|")
        if len(description) < 2 or not any(ch.isalpha() for ch in description):
            continue
        quantity = _number(match.group("quantity"))
        unit_price = _number(match.group("unit_price"))
        total = _number(match.group("total"))
        if quantity is None or unit_price is None or total is None or quantity <= 0:
            continue
        if abs(quantity * unit_price - total) > max(0.05, abs(total) * 0.03):
            continue
        items.append({
            "description": description[:160],
            "quantity": quantity,
            "unit_price": unit_price,
            "total": total,
            "unit": "unit",
        })
    return items[:200]


_UNIT_TOKEN = re.compile(r"(?i)^\d+(?:\.\d+)?\s*(kg|kgs|gr|g|grams?|ml|l|ltr|pcs|pc|box|ctn|m|cm)$")


def _total_first_row(line):
    """A table row whose amounts come first (total, VAT, discount %, unit price, quantity) and the item last."""
    match = re.match(r"^\s*((?:[\d,]+(?:\.\d+)?\s*%?\s+){3,})(.*[A-Za-z\u0600-\u06FF].*)$", line)
    if not match: return None
    numbers = [_number(n) for n in re.findall(r"([\d,]+(?:\.\d+)?)(?!\s*%)(?=\s|$)", match.group(1) + " ")]
    numbers = [n for n in numbers if n is not None]
    if len(numbers) < 3: return None
    total = numbers[0]
    def lost_dot(value, expected):  # 2.9.97: OCR dropped the decimal point (4.4 read as 44, 4.15 as 415)
        if expected <= 0 or value == expected: return value
        digits = lambda x: re.sub(r"\D", "", f"{x:.4f}".rstrip("0").rstrip("."))
        return expected if digits(value) == digits(expected) and float(value).is_integer() else value
    for i in range(1, len(numbers) - 1):
        price, quantity = numbers[i], numbers[i + 1]
        if quantity > 0 and total > 0: price = lost_dot(price, round(total / quantity, 4))
        if i == 2 and total > 0: numbers[1] = lost_dot(numbers[1], round(total * 0.11, 2))
        if quantity > 0 and price >= 0 and total > 0 and abs(price * quantity - total) <= max(0.05, total * 0.01):
            words = match.group(2).split(); unit = "unit"
            if words and _UNIT_TOKEN.match(words[0]): unit = words.pop(0).upper()
            description = " ".join(words).strip(" -:|")
            if len(description) < 2: return None
            row = {"description": description[:160], "quantity": quantity, "unit_price": price, "total": total, "unit": unit}
            if i == 2 and (numbers[1] == 0 or abs(numbers[1] - total * 0.11) <= max(0.02, total * 0.001)):
                row["vat"] = numbers[1]  # the VAT column of the row (0 or 11%)
            return row
    return None


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


def _page_count(path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 0


def _first_invoice(path, pages):
    """2.9.85: a long PDF (a supplier's invoice with its receipts and customs papers, 79 pages took about 15 minutes
    with the screen frozen, and the text of a later invoice could win): read page by page - its text, or OCR when
    the page is a scan - until the first invoice has its total (at most 3 pages). Returns (text, ocr_used)."""
    from pypdf import PdfReader
    reader = PdfReader(str(path)); texts = []; ocr_used = False
    for index in range(min(pages, 3)):
        page = reader.pages[index]
        text = _better_text(path, _page_text(page), _page_text(page, True))
        if _page_needs_ocr(path, text):
            try:
                scanned = _ocr_pdf_pages(path, [index])[0]
                if scanned.strip(): text = scanned; ocr_used = True
            except Exception:
                pass
        texts.append(text)
        if _parse_invoice_text(path, "\n".join(texts)).get("total") is not None: break
    return "\n".join(texts), ocr_used


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def _image_as_pdf(path):
    """2.9.118: a photo / scan saved as a picture (JPG, PNG ...) becomes a one-page PDF in a temporary folder, so it is read
    like a scanned PDF (OCR, photo handling, EDL bills)."""
    import tempfile
    from PIL import Image, ImageOps
    folder = Path(tempfile.mkdtemp(prefix="nanza_image_"))
    target = folder / (Path(path).stem + ".pdf")
    with Image.open(path) as picture:
        ImageOps.exif_transpose(picture).convert("RGB").save(target, "PDF", resolution=150)
    return target


def read_invoice_pdf(path, cancel=None):
    """Read locally and use the installed neural reader for photos and single-page scans."""
    import vision_reader
    vision_reader._cancelled(cancel)
    use_vision = False
    if vision_reader.ready():
        use_vision = Path(path).suffix.lower() in IMAGE_SUFFIXES
        if Path(path).suffix.lower() == ".pdf":
            from pypdf import PdfReader
            document = PdfReader(str(path))
            use_vision = len(document.pages) == 1 and _page_needs_ocr(path, _page_text(document.pages[0]))
    failure = ""
    if use_vision:
        try: return vision_reader.read_invoice(path, cancel)
        except vision_reader.VisionReadCancelled: raise
        except (vision_reader.VisionReaderError, OSError, ValueError) as exc:
            logging.getLogger("saber.ocr").warning("Handwriting reader unavailable: %s", exc)
            failure = str(exc)
    vision_reader._cancelled(cancel)
    result = _read_invoice_pdf_local(path)
    if failure:
        result.setdefault("review_warnings", []).append("Handwriting reader unavailable: " + failure)
        return _require_ocr_review(result)
    import neural_reader
    if neural_reader.ready() and (Path(path).suffix.lower() in IMAGE_SUFFIXES
                                 or ((result.get("ocr_used") or not (result.get("text") or "").strip())
                                     and _page_count(Path(path)) == 1)):
        result = neural_reader.enhance(path, result)
    return result


def _read_invoice_pdf_local(path):
    """Best guess of invoice number, date, party, currency and amounts. Always review before saving."""
    path = Path(path)
    if path.suffix.lower() in IMAGE_SUFFIXES:  # 2.9.118: a photo of the invoice / bill is read too
        import shutil
        converted = _image_as_pdf(path)
        try: result = _read_invoice_pdf_local(converted)
        finally: shutil.rmtree(converted.parent, ignore_errors=True)
        result["file"], result["path"] = path.name, str(path)
        return result
    text_error = ""
    pages = _page_count(path)
    if pages > 3:
        try:
            text, ocr_used = _first_invoice(path, pages)
            result = _parse_invoice_text(path, text); result["ocr_used"] = ocr_used
            result["notes"] = _invoice_notes(result, text, prefix="Local OCR suggestion - please check" if ocr_used else "")
            result["notes"] += f"; this PDF has {pages} pages: only the first invoice was read - for several invoices use Uploaded Data > Choose PDF Invoice(s)"
            _warn_on_invoice_total_mismatch(result)
            if ocr_used: _require_ocr_review(result)
            return result
        except Exception:
            pass  # read it the usual way
    try:
        text = pdf_text(path)
    except Exception as exc:
        text = ""
        text_error = str(exc)
    if not text_error:
        try: text = _better_text(path, text, pdf_text(path, layout=True))  # 2.9.85
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    result = _parse_invoice_text(path, text)
    if not _invoice_text_needs_ocr(path, text):
        if text_error:
            result["notes"] = f'{result["notes"]}; PDF text extraction failed ({text_error})'.strip("; ")
        return result

    try:
        ocr_text = _ocr_pdf(path)
    except Exception as exc:
        result["ocr_used"] = False
        ocr_note = f"Local OCR unavailable ({exc})"
        if text_error:
            ocr_note += f"; PDF text extraction failed ({text_error})"
        result["notes"] = f'{result.get("notes", "")}; {ocr_note}'.strip("; ")
        return _require_ocr_review(result)

    if not ocr_text.strip():
        result["ocr_used"] = False
        ocr_note = "Local OCR found no readable text"
        if text_error:
            ocr_note += f"; PDF text extraction failed ({text_error})"
        result["notes"] = f'{result.get("notes", "")}; {ocr_note}'.strip("; ")
        return _require_ocr_review(result)

    ocr_result = _parse_invoice_text(path, ocr_text)
    if text.count("\x1f") > 5:
        # Fonts without a character map leave control characters and scrambled Arabic in the text layer:
        # the OCR reading of the page is then the more reliable one.
        result = _merge_invoice_suggestions(ocr_result, result)
    else:
        result = _merge_invoice_suggestions(result, ocr_result)
    combined_text = "\n".join(part for part in (text.strip(), ocr_text.strip()) if part)
    result["text"] = combined_text
    result["ocr_used"] = True
    result["party_name"] = _trim_ocr_name(result.get("party_name") or "")  # 2.9.97
    prefix = "Local English/Arabic OCR suggestion - please check"
    if len(text.strip()) < 20:
        prefix = "Scanned PDF; " + prefix
    if text_error:
        prefix += f"; PDF text extraction failed ({text_error})"
    result["notes"] = _invoice_notes(result, combined_text, prefix=prefix)
    _warn_on_invoice_total_mismatch(result)
    _require_ocr_review(result)
    return result


def _require_ocr_review(result):
    """OCR confidence is an estimate; require explicit review even at 100%."""
    warning = "OCR reading requires review against the original before Save; confidence is not a guarantee"
    warnings = result.setdefault("review_warnings", [])
    if warning not in warnings: warnings.insert(0, warning)
    result["review_required"] = True
    for key, label in (("invoice_number", "invoice number"), ("invoice_date", "invoice date"),
                       ("party_name", "supplier/customer"), ("currency", "currency"),
                       ("subtotal", "subtotal"), ("vat", "VAT"), ("total", "total")):
        if result.get(key) in (None, ""):
            missing = f"Could not reliably read {label}"
            if missing not in warnings: warnings.append(missing)
    if result.get("inferred"):
        inferred = "Some amounts were calculated/inferred, not read directly: check against the original"
        if inferred not in warnings: warnings.append(inferred)
    warning = " | ".join(warnings)
    if warning not in result.get("notes", ""):
        result["notes"] = f'{result.get("notes", "")}; {warning}'.strip("; ")
    return result


def _warn_on_invoice_total_mismatch(result):
    subtotal, vat, total = (result.get(key) for key in ("subtotal", "vat", "total"))
    if any(value is None for value in (subtotal, vat, total)):
        return
    if result.get("exempt_subtotal") and result.get("taxable_subtotal") is not None:  # 2.9.97: + the part without VAT (stamp, rounding)
        subtotal = result["taxable_subtotal"] + result["exempt_subtotal"]
    if abs(subtotal + vat - total) > max(0.05, abs(total) * 0.005):
        result["vat"] = None
        result["acquisition_cost"] = None
        warning = "OCR VAT, subtotal and total do not reconcile; VAT suggestion cleared. Enter and verify the amounts before posting"
        if warning not in result.setdefault("review_warnings", []): result["review_warnings"].append(warning)
        if warning not in result.get("notes", ""):
            result["notes"] = (result.get("notes", "") + "; " + warning).strip("; ")


_MONEY = re.compile(r"(?<![\d.,])(\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,2})?|\d+\.\d{1,2})(?![\d])")


def _subtotal_reconciling_vat(text, vat, total):
    """A total line (e.g. "TOTAL A+B+C", "Total HT") whose amount plus the VAT equals the grand total.
    Used when several section totals exist; the last matching line before the VAT wins."""
    if vat is None or total is None or vat <= 0: return None
    tolerance = max(0.05, abs(total) * 0.005); found = None
    for line in text.splitlines():
        lower = line.casefold()
        if re.search(r"vat|tva|ضريبة|grand|ttc|net\s+payable", lower): 
            if found is not None: break
            continue
        if not re.search(r"total|subtotal|مجموع|montant|ht\b", lower): continue
        for match in _MONEY.finditer(line):
            try: amount = float(match.group(1).replace(",", "").replace(" ", ""))
            except ValueError: continue
            if abs(amount + vat - total) <= tolerance: found = amount
    return found


def _vat_triple(text):
    """Amounts whose labels are unreadable (broken Arabic fonts, boxes without words): find
    before-VAT + VAT = total where VAT is exactly 11% of before-VAT. Dates, percentages and long
    reference numbers are ignored. Returns (subtotal, vat, total) or None."""
    clean = re.sub(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b", " ", normalize_invoice_text(text or ""))
    clean = re.sub(r"\d+(?:[.,]\d+)?\s*[%٪]", " ", clean)
    values = set()
    for token in re.findall(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?(?![\w])|(?<![\w.,])\d+(?:\.\d{1,2})?(?![\w,])", clean):
        digits = token.replace(",", "")
        if len(digits.split(".")[0]) > 9: continue
        try: values.add(round(float(digits), 2))
        except ValueError: pass
    best = None
    for a in values:
        if a <= 0: continue
        for b in values:
            if b <= 0 or abs(b - a * 0.11) > max(0.02, a * 0.0005): continue
            c = round(a + b, 2)
            if any(abs(c - v) <= 0.02 for v in values) and (best is None or c > best[2]): best = (a, b, c)
    return best


def _foreign_currency_from_lbp_vat(text, vat):
    """Foreign-currency invoices in Lebanon also show the VAT in LBP ("VAT 11% LBP 374,110,000").
    If an LBP amount on a VAT line is VAT x a plausible exchange rate, the invoice itself is not in LBP."""
    if not vat: return None
    for line in (text or "").splitlines():
        if not re.search(r"(?i)lbp|l\.l|ل\.ل", line) or not re.search(r"(?i)vat|tva|ضريبة", line): continue
        for token in re.findall(r"\d{1,3}(?:,\d{3})+|\d{5,}", line):
            amount = float(token.replace(",", ""))
            rate = amount / vat
            if 1000 <= rate <= 200000:
                return ("EUR" if re.search(r"(?i)\beur\b|€", text or "") else "USD"), round(rate)
    return None


def _parse_invoice_text(path, text):
    path = Path(path); text = normalize_invoice_text(text)
    result = {"file": path.name, "path": str(path), "text": text, "invoice_number": "", "invoice_date": "", "party_name": "", "currency": "",
              "subtotal": None, "vat": None, "total": None, "items": [], "notes": ""}
    result["suggested_type"] = suggest_invoice_type(text)
    result["suggested_account"] = suggest_expense_account(text)
    result["expense_classification"] = expense_classification(text)
    category = result["expense_classification"]["category"]
    result["expense_category"] = category[0] if category else ""
    result["suggested_account_9"], result["suggested_account_name"] = (category[2], category[3]) if category else ("", "")
    result["supplier_hint"] = supplier_from_email(text)
    if len(text.strip()) < 20:
        result["notes"] = "This PDF is a scanned image (no text inside). The file will be attached; enter the amounts manually."; return result
    result["invoice_number"] = _invoice_number(text)
    if re.fullmatch(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}", result["invoice_number"] or ""):
        result["invoice_number"] = _document_reference_number(text) or ""   # a date is never the invoice number
    result["invoice_date"] = _invoice_date(text)
    result["currency"] = _invoice_currency(text)
    result["total"] = _invoice_total_after(text)
    result["vat"] = _vat_amount_after(text, result["currency"])
    result["subtotal"] = _amount_after(text, ("subtotal", "sub-total", "sub total", "before vat", "total ht", "net amount", "excl", *ARABIC_SUBTOTAL))
    if result["subtotal"] is None:
        result["subtotal"] = _subtotal_from_tax_breakdown(text)
    reconciled = _subtotal_reconciling_vat(text, result["vat"], result["total"])
    if reconciled is not None and (result["subtotal"] is None
            or abs(result["subtotal"] + result["vat"] - result["total"]) > max(0.05, abs(result["total"]) * 0.005)):
        result["subtotal"] = reconciled
    result["party_name"] = _supplier_name(text)
    top = [line for line in text.splitlines() if line.strip()][:4]
    if mentions_own_company("\n".join(top)):  # 2.9.87: the company issued this document (a sales invoice): the party is the customer
        result["party_name"] = _bill_to_name(text) or result["party_name"]
    result["items"] = _line_items(text)
    # 2.9.85: rows with their own VAT column - the subtotal of the taxable rows and of the rows without VAT
    if result["items"] and all("vat" in i for i in result["items"]) and result.get("vat") is not None:
        line_vat = sum(i["vat"] for i in result["items"]); taxable = sum(i["total"] for i in result["items"] if i["vat"])
        if abs(line_vat - result["vat"]) <= 0.05 and taxable:
            result["taxable_subtotal"] = round(taxable, 2)
            result["exempt_subtotal"] = round(sum(i["total"] for i in result["items"] if not i["vat"]), 2)
    # For a fixed-asset register preview, use a description only when the PDF
    # yields one unambiguous item (or an explicitly labelled asset/description).
    if len(result["items"]) == 1:
        result["asset_name"] = result["items"][0]["description"]
    else:
        named = re.search(
            r"(?im)^\s*(?:asset|item|description|equipment|الموجودات|الأصل|الصنف)\s*[:\-]\s*(.{3,100}?)\s*$",
            text,
        )
        result["asset_name"] = named.group(1).strip() if named else ""
    # A labelled subtotal is the conservative acquisition-cost candidate.
    # A grand total is usable only when the PDF explicitly says VAT is zero.
    result["acquisition_cost"] = result["subtotal"]
    if result["acquisition_cost"] is None and result["vat"] == 0:
        result["acquisition_cost"] = result["total"]
    inferred = []
    if result["total"] is None or result["vat"] is None or result["subtotal"] is None:
        triple = _vat_triple(text)
        # A VAT read from the "VAT 11% LBP ..." line of a foreign-currency invoice is the LBP equivalent, not the VAT.
        if triple and result.get("vat") and result.get("total") is None and 1000 <= result["vat"] / triple[1] <= 200000:
            result["vat"] = None
        known = [(key, value) for key, value in zip(("subtotal", "vat", "total"), triple or ()) if result.get(key) is not None]
        if triple and all(abs(result[key] - value) <= 0.02 for key, value in known):
            for key, value in zip(("subtotal", "vat", "total"), triple):
                if result.get(key) is None: result[key] = value; inferred.append(key)
    foreign = _foreign_currency_from_lbp_vat(text, result["vat"])
    if foreign and result.get("currency") in ("", "LBP", None):
        result["currency"] = foreign[0]
        inferred.append(f"currency {foreign[0]} (the LBP amount is the VAT at about {foreign[1]:,} LBP)")
    _reconcile_with_lines(result, text, inferred)  # 2.9.97
    bill = _utility_bill(text)  # 2.9.97: EDL / water / telephone bills: base + 11% VAT + stamp and rounding
    subtotal, vat, total = (result.get(k) for k in ("subtotal", "vat", "total"))
    sensible = None not in (vat, total) and total >= 1000 and vat <= total * 0.12 and (subtotal is None or abs(subtotal + vat - total) <= max(1, total * 0.06))
    if bill and sensible and vat is not None and abs(bill["vat"] - vat) <= 2 and bill["total"] > total: sensible = False  # same VAT, the bill's total adds the stamp
    if bill and not sensible:
        if True:
            result.update(bill); inferred.append("amounts found by the 11% VAT check of a utility bill (base + VAT + stamp / rounding)")
            if not result.get("currency"): result["currency"] = "LBP"
    is_edl = bool(re.search(r"(?i)\bedl\b|ed[li]\W{0,2}[gq]ov|électricité\s+du\s+liban|كهرباء\s+لبنان|\btranches?\b.*\bbranchement|\bbranchement\b.*\btranches?\b", text, re.S))
    if is_edl and not (result.get("supplier_hint") or "").strip():
        result["supplier_hint"] = "Electricité du Liban (EDL)"
    if is_edl and not bill and (result.get("total") is None or result.get("subtotal") is None):
        edl = _edl_from_base(text)  # 2.9.118: a photo where only the base amount could be read
        if edl:
            result.update(edl); result["currency"] = result.get("currency") or "LBP"
            inferred.append("EDL bill: VAT 11% of the base, 100,000 stamp, total rounded up to the thousand - check against the bill")
    result["inferred"] = inferred
    result["review_warnings"] = []
    if inferred: result["review_warnings"].append("Some amounts were calculated/inferred, not read directly: check against the original")
    for key,label in (("invoice_number","invoice number"),("invoice_date","invoice date"),("currency","currency"),("total","total")):
        if result.get(key) in (None,""): result["review_warnings"].append(f"Could not reliably read {label}")
    result["notes"] = _invoice_notes(result, text)
    return result


def _edl_from_base(text):
    """2.9.118: an EDL bill prints its base (total of the tranches) several times: TOTAL TRANCHES, the fixed fees total, the
    energy services total. When OCR could read only that amount: VAT = 11% of it, the stamp 100,000 and the total rounded up
    to the thousand (EDL: 671,250 + 73,838 + 100,000 = 845,088 -> 846,000). Used only when one amount stands out: its total
    is printed too, or it is the only one repeated, or the only amount read."""
    skip = set(re.findall(r"(?i)(?:n\s*[°o]\.?|no\.?)\s*(?:de\s+)?tva\s*[:\-]?\s*(\d{5,9})", text or ""))
    counts = {}
    for found in re.findall(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|[1-9]\d{4,7})(?![\d,])", text or ""):
        if found in skip: continue
        value = int(found.replace(",", ""))
        if 10000 <= value <= 500000000 and value % 50 == 0: counts[value] = counts.get(value, 0) + 1
    def billed(base):
        return -(-(base + int(base * 0.11 + 0.5) + 100000) // 1000) * 1000
    confirmed = [value for value in counts if billed(value) in counts]  # the base whose total is printed too
    repeated = [value for value, count in counts.items() if count >= 2]
    if len(confirmed) == 1: base = confirmed[0]
    elif len(repeated) == 1: base = repeated[0]
    elif len(counts) == 1: base = next(iter(counts))
    else: return None
    vat = int(base * 0.11 + 0.5); total = billed(base)
    return {"subtotal": float(base), "vat": float(vat), "total": float(total), "taxable_subtotal": float(base),
            "exempt_subtotal": float(total - base - vat), "acquisition_cost": float(base)}


def _utility_bill(text):
    """2.9.97: a utility bill in LBP (EDL): find base and VAT with VAT = 11% of the base (to the lira), then the total that adds
    the stamp and the rounding (EDL: 1,816,850 + 199,854 + 100,000 stamp + 296 rounding = 2,117,000)."""
    values = sorted({int(n.replace(",", "")) for n in re.findall(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])|(?<![\d.,])\d{5,9}(?![\d.,])", text or "")})
    values = [v for v in values if v >= 1000]
    best = None
    for base in values:
        for vat in values:
            if vat < base and abs(vat - base * 0.11) <= 2:
                totals = [t for t in values if base + vat <= t <= base + vat + 250000]
                if not totals: continue
                total = totals[0]
                if best is None or base > best[0]: best = (base, vat, total)
    if not best: return None
    base, vat, total = best
    return {"subtotal": float(base), "vat": float(vat), "total": float(total), "taxable_subtotal": float(base),
            "exempt_subtotal": float(total - base - vat), "acquisition_cost": float(base)}


def _reconcile_with_lines(result, text, inferred):
    """2.9.97: the item lines are the strongest evidence. When subtotal + VAT = total does not hold (a weight total such as
    'TOTAL 27045' taken as the amount, the VAT in LBP taken as the VAT), look in the text for the amount that equals the sum of
    the lines and for a total whose difference with it (the VAT) is also printed - and use them."""
    items = result.get("items") or []
    if len(items) < 2: return
    lines = round(sum(float(i["total"]) for i in items), 2)
    subtotal, vat, total = (result.get(k) for k in ("subtotal", "vat", "total"))
    if None not in (subtotal, vat, total) and abs(subtotal + vat - total) <= 0.02 and abs(subtotal - lines) <= 0.02: return
    amounts = sorted({_number(a) for a in re.findall(r"(?<![\d.,])\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)|(?<![\d.,])\d+\.\d{2}(?!\d)", text)} - {None})
    present = lambda value: any(abs(a - value) <= 0.02 for a in amounts)
    best = None
    for candidate in amounts:
        difference = round(candidate - lines, 2)
        if candidate > lines and 0 < difference <= lines * 0.12 and present(difference):
            printed = min(amounts, key=lambda a: abs(a - difference))  # the VAT as printed (Diwan: 90.80 on a 90.81 difference)
            best = (candidate, printed); break  # the smallest total above the lines whose VAT is printed
    if best is None and present(lines) and (total is None or abs((vat or 0) + lines - total) > 0.02):
        best = (lines, 0.0) if vat in (None, 0) else None
    if best is None: return
    new_total, new_vat = best
    changed = [k for k, v in (("subtotal", lines), ("vat", new_vat), ("total", new_total)) if result.get(k) is None or abs(result[k] - v) > 0.02]
    if not changed: return
    result["subtotal"], result["vat"], result["total"] = lines, new_vat, new_total
    result["acquisition_cost"] = lines
    inferred.append("amounts checked against the item lines: " + ", ".join(changed))


_ADDRESS = re.compile(r"\b(?:invoice|facture|date|tel|phone|fax|page|www|street|floor|flr|level|block|bldg|building|towers?|avenue|road|highway|"
                      r"zone|secteur|capital|mof|vat|client|customer|address|original|ref|account|ministry|department|description|"
                      r"statement|period|balance)\b|@|p\.?\s*o\.?\s*box|b\.p\.|imm\.|\br\.?c\.?\b|v\.a\.t|bill\s+to|name\s*:|^copy$|receipts?$|pre-?bill|a/c", re.I)
_COMPANY_FORM = re.compile(r"\b(?:s\.?a\.?l|s\.?a\.?r\.?l|sarl|llc|l\.l\.c|ltd|limited|inc|co\.|c\.s\.?|group|fze|fzco|est\.?|"
                           r"establishment|trading|company|center|centre|shipping|logistics|est)\b|شركة|مؤسسة", re.I)


def _supplier_name(text):
    """2.9.85: the supplier is usually the first company name at the top of the page. Address, contact and
    'Bill to' lines are skipped, the open company (the buyer) is never taken, and a line with a company form
    (SAL, SARL, LLC, Group ...) in the first lines wins over a plain first line."""
    known = _known_party_in(text)
    if known: return known[:60]
    candidates = []; early = 0
    for index, line in enumerate(text.splitlines()[:40]):
        if index == 8: early = len(candidates)
        for segment in re.split(r"\s{3,}|\t", line.strip()):
            clean = re.sub(r"^\W*\w{0,8}\s*[>»|\]}]+\s*", "", segment.strip()).strip() or segment.strip()  # OCR logo junk ("BCC >")
            clean = re.split(r"(?i)\s(?:www\.|e-?mail\b|tel\b|fax\b|phone\b|invoice\b|date\b)", " " + clean)[0].strip()  # name, then contacts on the same line
            clean = clean.strip(" -:|,.")
            if len(clean) < 3 or sum(ch.isalpha() for ch in clean) < 3 or _ADDRESS.search(clean): continue
            if re.fullmatch(r"[\W\d]*\w{1,3}[\W\d]*", clean): continue
            if mentions_own_company(clean): continue
            candidates.append(clean)
        if len(candidates) >= 12: break
    if not candidates: return ""
    formal = [c for c in candidates[:8] if _COMPANY_FORM.search(c)]
    latin = [c for c in formal if re.search(r"[A-Za-z]{3}", c)]
    if latin or formal: return (latin or formal)[0][:60]
    if early == 0 and len(text.splitlines()) > 8: return ""  # no name-like line at the top of the page
    first = candidates[0]  # no company form: the first line only when it reads like a name (not OCR noise)
    letters = sum(ch.isalpha() for ch in first)
    return first[:60] if letters >= 8 and sum(ch.isalpha() or ch == " " for ch in first) >= 0.8 * len(first) else ""


def _bill_to_name(text):
    """The name after 'Bill to / Sold to / Client / Customer / M/s' (same line, or the next line when the label is alone)."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r"(?i)\b(?:bill(?:ed)?\s*to|sold\s*to|invoice\s*to|client|customer|m/s|messrs)\b\s*(?:name)?\s*[:.]?\s*(.*)$", line)
        if not match: continue
        value = re.split(r"\s{3,}", match.group(1).strip())[0].strip(" :-")
        if len(value) < 3 and index + 1 < len(lines): value = re.split(r"\s{3,}", lines[index + 1].strip())[0].strip(" :-")
        if len(value) >= 3 and sum(ch.isalpha() for ch in value) >= 3 and not mentions_own_company(value): return value[:60]
    return ""


def _merge_invoice_suggestions(primary, fallback):
    """Fill gaps from OCR while keeping values read from the PDF text layer preferred."""
    result = dict(primary)
    for key in ("invoice_number", "invoice_date", "party_name", "currency", "subtotal", "vat",
                "total", "items", "suggested_type", "suggested_account", "asset_name", "acquisition_cost",
                "taxable_subtotal", "exempt_subtotal", "expense_category", "suggested_account_9", "suggested_account_name", "supplier_hint"):  # 2.9.97
        value = result.get(key)
        if value is None or value == "" or value == []:
            replacement = fallback.get(key)
            if replacement is not None and replacement != "" and replacement != []:
                result[key] = replacement
    for key in ("inferred", "review_warnings"):
        combined = list(dict.fromkeys(list(primary.get(key) or []) + list(fallback.get(key) or [])))
        if combined: result[key] = combined
    return result


def _invoice_notes(result, text, prefix=""):
    missing = [label for key, label in (("invoice_number", "number"), ("invoice_date", "date"),
                                        ("total", "total")) if not result.get(key)]
    notes = []
    classification = result.get("expense_classification") or {}
    if classification.get("status") == "ambiguous":
        labels = [item["category"][0] for item in classification.get("candidates", [])]
        notes.append("Expense classification unclear: " + ", ".join(labels) + "; choose the account manually")
    if prefix:
        notes.append(prefix)
    notes.append("Read from PDF - please check" +
                 (f"; not found: {', '.join(missing)}" if missing else ""))
    reference = _document_reference_number(text)
    if reference and result.get("invoice_number") == reference:
        notes.append("Document reference suggested as invoice number; verify before posting")
    if result.get("vat") is None and any(
            re.search(r"\b(?:vat|tva|tax)\b|ض\.ق\.م|ضريبة", line, re.I)
            for line in text.splitlines()):
        notes.append("VAT amount not found; enter or confirm it manually")
    if result.get("items"):
        notes.append(f"{len(result['items'])} item row(s) pre-filled for review")
    if result.get("inferred"):
        notes.append("recognised without labels by the 11% VAT check - verify: " + ", ".join(result["inferred"]))
    return "; ".join(notes)


def asset_pdf_details(data):
    """Return conservative fixed-asset suggestions; absent/ambiguous values stay blank."""
    date_text = ""
    raw_date = data.get("invoice_date") or ""
    for pattern in ("%d-%m-%Y", "%Y-%m-%d", "%d%m%Y"):
        try:
            date_text = datetime.strptime(raw_date, pattern).strftime("%d-%m-%Y")
            break
        except ValueError:
            continue
    return {
        "name": (data.get("asset_name") or "").strip(),
        "acquired_on": date_text,
        "currency": (data.get("currency") or "").upper(),
        "cost": data.get("acquisition_cost"),
    }


def read_invoice_pdf_pages(path, progress=None, cancel=None):
    """Preview each distinct invoice in a PDF and retain its page range.

    A repeated invoice number on later pages is treated as a continuation. Pages
    without extractable text stay visible for manual entry, rather than vanishing.
    2.9.85: when the open company is known, a page that does not name it (a receipt, a port bill, a customs paper
    stapled behind the supplier's invoice) is a supporting page of the invoice before it: attached, not read as
    another invoice. progress(done, total, stage) reports the pages read; cancel (an Event) stops the OCR.
    """
    from pypdf import PdfReader
    path = Path(path)
    if path.suffix.lower() in IMAGE_SUFFIXES:  # 2.9.118: a photo is one invoice
        result = read_invoice_pdf(path, cancel=cancel); result.update(pages=[1], support_pages=[], page_range="Page 1")
        return [result]
    reader = PdfReader(str(path))
    page_texts = [_better_text(path, _page_text(page), _page_text(page, True)) for page in reader.pages]  # 2.9.85: plain or layout
    import neural_reader, vision_reader
    if (len(page_texts)==1 and _page_needs_ocr(path,page_texts[0]) and (neural_reader.ready() or vision_reader.ready())
            and not (cancel is not None and cancel.is_set())):
        result=read_invoice_pdf(path, cancel=cancel)
        result.update(pages=[1],support_pages=[],page_range="Page 1")
        if progress:progress(1,1,"Advanced Local OCR")
        return [result]
    blank_pages = {index for index, text in enumerate(page_texts) if len(text.strip()) < 20}
    ocr_candidate_pages = [
        index for index, text in enumerate(page_texts)
        if _page_needs_ocr(path, text)
    ]
    ocr_error = ""
    ocr_pages = set()
    if ocr_candidate_pages:
        try:
            report = (lambda done, total: progress(done, total, "OCR")) if progress else None
            scanned = _ocr_pdf_pages(path, ocr_candidate_pages, report, cancel) if (report or cancel is not None) else _ocr_pdf_pages(path, ocr_candidate_pages)
            for index, text in zip(ocr_candidate_pages, scanned):
                if text.strip():
                    page_texts[index] = text
                    ocr_pages.add(index + 1)
        except Exception as exc:
            ocr_error = str(exc)
    groups = []; own = bool(_own_words()) and any(mentions_own_company(text) for text in page_texts)
    for number, text in enumerate(page_texts, 1):
        parsed = _parse_invoice_text(path, text)
        invoice_number = parsed.get("invoice_number")
        if groups and own and (not mentions_own_company(text) or (not invoice_number and parsed.get("total") is None)):
            groups[-1]["pages"].append(number); groups[-1]["support"].append(number)  # supporting document of that invoice
        elif groups and invoice_number and invoice_number == groups[-1]["invoice_number"]:
            groups[-1]["text"] += "\n" + text
            groups[-1]["pages"].append(number)
        elif groups and not invoice_number and text.strip() and not parsed.get("total"):
            groups[-1]["text"] += "\n" + text
            groups[-1]["pages"].append(number)
        else:
            groups.append({"invoice_number":invoice_number,"text":text,"pages":[number],"support":[]})
    results = []
    for group in groups:
        parsed = _parse_invoice_text(path, group["text"])
        pages = group["pages"]; parsed["pages"] = list(pages); parsed["support_pages"] = list(group["support"])
        parsed["page_range"] = f"Page {pages[0]}" if len(pages)==1 else f"Pages {pages[0]}-{pages[-1]}"
        parsed["ocr_used"] = any(number in ocr_pages for number in pages)
        needs_ocr = any(number - 1 in ocr_candidate_pages for number in pages)
        if parsed["ocr_used"]:
            prefix = ("Scanned PDF; " if any(number - 1 in blank_pages for number in pages) else "")
            parsed["notes"] = _invoice_notes(
                parsed, group["text"], prefix=prefix + "Local OCR suggestion - please check",
            )
            _warn_on_invoice_total_mismatch(parsed)
            _require_ocr_review(parsed)
        elif needs_ocr:
            note = (f"Local OCR unavailable ({ocr_error})" if ocr_error
                    else "Local OCR found no readable text")
            parsed["notes"] = f'{parsed["notes"]}; {note}'.strip("; ")
        if not parsed.get("invoice_number"):
            parsed["notes"] += "; confirm invoice boundaries and number"
        previous = results[-1] if results else None  # 2.9.85: same numbering as the invoice before (000335066 / 000335165): same supplier
        number = parsed.get("invoice_number") or ""
        if (not parsed.get("party_name") and previous and previous.get("party_name") and len(number) >= 5
                and len(number) == len(previous.get("invoice_number") or "") and number[:4] == previous["invoice_number"][:4]):
            parsed["party_name"] = previous["party_name"]
        if group["support"]:
            parsed["notes"] += f"; {len(group['support'])} supporting page(s) not addressed to the company kept with this invoice (not booked)"
        if cancel is not None and cancel.is_set() and needs_ocr:
            parsed["notes"] += "; reading stopped before the end: enter the amounts"
        results.append(parsed)
    return results
