"""Image preparation and Tesseract helpers for invoice OCR: photo detection, turning upright, Otsu threshold,
table-rule removal, common misread fixes and a time-limited Tesseract call.

Moved unchanged from pdf_import.py (2.9.138 consolidation); pdf_import re-exports these names. Reading an invoice
(choosing between OCR readings, parsing amounts) stays in pdf_import."""
from __future__ import annotations

import re


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


def _tesseract_text(engine, image, **options):
    """Terminate a stalled OCR subprocess instead of waiting indefinitely."""
    return engine.image_to_string(image, timeout=30, **options)


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
