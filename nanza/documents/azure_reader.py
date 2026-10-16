"""2.9.120: optional - read an invoice (printed or handwritten, Arabic / English / French) with Microsoft Azure AI Document Intelligence.

Zero cost: the company opens its OWN free Azure resource (tier F0: 500 pages a month, the first 2 pages of each document) and
types its endpoint and key in Settings > Accounting Settings. Nanza has no account of its own and receives nothing.

- Nothing is sent unless the user presses "Read with Azure". The file goes from this computer straight to the company's
  Azure resource (in the region it chose) and the reading comes back. Without a key the free local reading is used, as before.
- The key stays on this computer (protected by Windows for this Windows user), never in the company file or its backups.
- A counter of the pages sent this month stops at the limit (500 by default), so the free tier is never exceeded
  (Azure itself refuses an F0 resource over its quota: nothing is ever billed).
- The reading is a suggestion, filled in the screen for the accountant to check before Save - as the local reading.
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

API_VERSION = "2024-11-30"
MODEL = "prebuilt-invoice"
FREE_PAGES = 500           # F0: 500 pages a month
FREE_PAGES_PER_FILE = 2    # F0 reads the first 2 pages of a document
FREE_MAX_BYTES = 4 * 1024 * 1024
SETTINGS_FILE = "azure_reader.json"
SUFFIXES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp"}
PRIVACY = ("The invoice is sent from this computer to YOUR Azure resource (Microsoft) only when you press Read with Azure. "
           "The key stays on this computer. Nanza receives nothing.")


class AzureReaderError(RuntimeError):
    """Azure could not read the document (no key, limit reached, network, refused...): the message says why."""


# ---------------------------------------------------------------- the key on this computer
def _folder():
    import app_runtime
    return app_runtime.data_dir()


def _dpapi(data, protect):
    """Windows protects the key for this Windows user (another user or computer cannot read it)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    source, target = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), Blob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not function(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(target)):
        raise OSError("Windows could not protect / open the Azure key")
    try: return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def _protect(key):
    if os.name == "nt": return "dpapi:" + base64.b64encode(_dpapi(key.encode("utf-8"), True)).decode("ascii")
    return "plain:" + base64.b64encode(key.encode("utf-8")).decode("ascii")


def _unprotect(stored):
    kind, _, body = str(stored or "").partition(":")
    try:
        if kind == "dpapi": return _dpapi(base64.b64decode(body), False).decode("utf-8")
        if kind == "plain": return base64.b64decode(body).decode("utf-8")
    except (OSError, ValueError, AttributeError): return ""  # another Windows user / computer: the key must be typed again
    return ""


def load(folder=None):
    """{"endpoint", "key", "limit", "used": {"YYYY-MM": pages}} of this computer ({} when not set up)."""
    path = Path(folder or _folder()) / SETTINGS_FILE
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    if not isinstance(data, dict): return {}
    data["key"] = _unprotect(data.get("key"))
    return data


def _write(data, folder=None):
    folder = Path(folder or _folder()); folder.mkdir(parents=True, exist_ok=True)
    stored = {**data, "key": _protect(data["key"]) if data.get("key") else ""}
    (folder / SETTINGS_FILE).write_text(json.dumps(stored, indent=1), encoding="utf-8")


def clean_endpoint(endpoint):
    text = str(endpoint or "").strip().rstrip("/")
    if not text: return ""
    if not text.lower().startswith("https://") or " " in text:
        raise ValueError("The endpoint is the https:// address of your Azure resource, e.g. https://my-company.cognitiveservices.azure.com")
    return text


def save(endpoint, key, limit=FREE_PAGES, folder=None):
    """Keep the endpoint and key on this computer (an empty key removes them)."""
    data = load(folder)
    endpoint, key = clean_endpoint(endpoint), str(key or "").strip()
    if key and not endpoint: raise ValueError("Type the endpoint of your Azure resource")
    try: limit = int(limit)
    except (TypeError, ValueError): raise ValueError("The monthly limit is a number of pages, e.g. 500") from None
    if not 1 <= limit <= 100000: raise ValueError("The monthly limit is between 1 and 100,000 pages")
    data.update(endpoint=endpoint if key else "", key=key, limit=limit)
    _write(data, folder)
    return status(folder)


def ready(folder=None):
    data = load(folder)
    return bool(data.get("endpoint") and data.get("key"))


def _month(today=None):
    return (today or date.today()).strftime("%Y-%m")


def status(folder=None, today=None):
    data = load(folder)
    used = int((data.get("used") or {}).get(_month(today), 0))
    return {"ready": bool(data.get("endpoint") and data.get("key")), "endpoint": data.get("endpoint") or "",
            "limit": int(data.get("limit") or FREE_PAGES), "used": used}


def _count(pages, folder=None, today=None):
    data = load(folder); month = _month(today)
    used = {k: v for k, v in (data.get("used") or {}).items() if k >= f"{(today or date.today()).year - 1}"}  # a year of history
    used[month] = int(used.get(month, 0)) + pages
    data["used"] = used; _write(data, folder)


# ---------------------------------------------------------------- the reading
def pages_of(path):
    """The pages Azure F0 reads (and counts) for this file: an image 1, a PDF its pages but at most 2."""
    path = Path(path)
    if path.suffix.lower() != ".pdf": return 1
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    try: return max(1, min(FREE_PAGES_PER_FILE, len(PdfReader(str(path)).pages)))
    except (PyPdfError, OSError, ValueError) as exc:
        raise AzureReaderError(f"This PDF cannot be opened: {exc}") from exc


def _request(method, url, key, body=None, content_type=None, opener=None, timeout=60):
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
    headers = {"Ocp-Apim-Subscription-Key": key, "User-Agent": "NanzaAccounting"}
    if content_type: headers["Content-Type"] = content_type
    try:
        with (opener or urlopen)(Request(url, data=body, headers=headers, method=method), timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        detail = ""
        try: detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, OSError, AttributeError): detail = ""
        if exc.code in (401, 403): raise AzureReaderError("Azure refused the key or the endpoint - check them in Settings > Accounting Settings") from exc
        if exc.code == 429: raise AzureReaderError("Azure says the free quota is used (or too many requests): try later, or read it with the free local reading") from exc
        raise AzureReaderError(f"Azure answered {exc.code}: {detail or exc.reason}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise AzureReaderError(f"Azure could not be reached (internet?): {getattr(exc, 'reason', exc)}") from exc


def analyze(path, folder=None, opener=None, sleep=time.sleep, today=None, wait_seconds=90):
    """Send the file to the company's Azure resource and return Azure's raw analyzeResult."""
    settings = load(folder)
    if not (settings.get("endpoint") and settings.get("key")):
        raise AzureReaderError("Azure is not set up on this computer (Settings > Accounting Settings > Read invoices with Azure)")
    path = Path(path); kind = SUFFIXES.get(path.suffix.lower())
    if not kind: raise AzureReaderError("Choose a PDF or a photo (JPG, PNG, TIFF, BMP)")
    try: content = path.read_bytes()
    except OSError as exc: raise AzureReaderError(f"The file cannot be read: {exc}") from exc
    if not content: raise AzureReaderError("The file is empty")
    if len(content) > FREE_MAX_BYTES: raise AzureReaderError("The free Azure tier reads files up to 4 MB: make the scan smaller, or use the free local reading")
    pages = pages_of(path); state = status(folder, today)
    if state["used"] + pages > state["limit"]:
        raise AzureReaderError(f"This month's Azure limit is reached ({state['used']} of {state['limit']} pages): "
                               "the free local reading is used until next month (the limit can be changed in Settings)")
    url = f"{settings['endpoint']}/documentintelligence/documentModels/{MODEL}:analyze?api-version={API_VERSION}"
    code, headers, _ = _request("POST", url, settings["key"], content, kind, opener)
    _count(pages, folder, today)  # Azure counts the pages once it accepted the document
    location = {k.lower(): v for k, v in headers.items()}.get("operation-location")
    if code != 202 or not location: raise AzureReaderError(f"Azure did not accept the document (answer {code})")
    started = time.monotonic()
    while True:
        _, headers, body = _request("GET", location, settings["key"], opener=opener)
        try: answer = json.loads(body.decode("utf-8"))
        except ValueError as exc: raise AzureReaderError("Azure sent an answer that cannot be read") from exc
        state = answer.get("status")
        if state == "succeeded": return answer.get("analyzeResult") or {}
        if state == "failed":
            raise AzureReaderError("Azure could not read this document: " + str((answer.get("error") or {}).get("message") or "no reason given"))
        if time.monotonic() - started > wait_seconds: raise AzureReaderError("Azure took too long to read the document: try again")
        try: wait = float({k.lower(): v for k, v in headers.items()}.get("retry-after") or 1)
        except ValueError: wait = 1
        sleep(min(max(wait, 0.5), 5))


def _text(field):
    if not isinstance(field, dict): return ""
    return str(field.get("valueString") or field.get("content") or "").strip()


def _amount(field):
    if not isinstance(field, dict): return None, ""
    money = field.get("valueCurrency") or {}
    value = money.get("amount") if money else field.get("valueNumber")
    try: return (round(float(value), 2) if value is not None else None), str(money.get("currencyCode") or "").upper()
    except (TypeError, ValueError): return None, ""


def _date(field):
    if not isinstance(field, dict) or not field.get("valueDate"): return ""
    try: return datetime.strptime(field["valueDate"][:10], "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError: return ""


def to_result(path, analysis):
    """Azure's reading in the shape of the local reading (pdf_import.read_invoice_pdf), so every screen fills it the same way."""
    import pdf_import
    content = str(analysis.get("content") or "")
    result = pdf_import._parse_invoice_text(path, content)  # the local reading of Azure's text: categories, EDL rules, ...
    documents = analysis.get("documents") or []
    fields = (documents[0].get("fields") or {}) if documents else {}
    vendor = _text(fields.get("VendorName"))
    if vendor: result["party_name"] = vendor; result["supplier_hint"] = vendor
    number = _text(fields.get("InvoiceId"))
    if number: result["invoice_number"] = number
    for key, name in (("invoice_date", "InvoiceDate"), ("due_date", "DueDate")):
        value = _date(fields.get(name))
        if value: result[key] = value
    tax_number = _text(fields.get("VendorTaxId"))
    if tax_number: result["party_tax_number"] = tax_number
    currency = ""
    for key, name in (("subtotal", "SubTotal"), ("vat", "TotalTax"), ("total", "InvoiceTotal")):
        value, code = _amount(fields.get(name))
        if value is not None: result[key] = value
        currency = currency or code
    if currency in ("USD", "LBP", "EUR", "SAR", "AED", "GBP"): result["currency"] = currency
    if result.get("subtotal") is None and None not in (result.get("total"), result.get("vat")):
        result["subtotal"] = round(result["total"] - result["vat"], 2)
    items = []
    for entry in ((fields.get("Items") or {}).get("valueArray") or []):
        values = entry.get("valueObject") or {}
        description = _text(values.get("Description")) or _text(values.get("ProductCode"))
        total, _ = _amount(values.get("Amount"))
        if not description or total is None: continue
        quantity = (values.get("Quantity") or {}).get("valueNumber") or 1
        price, _ = _amount(values.get("UnitPrice"))
        try: quantity = float(quantity)
        except (TypeError, ValueError): quantity = 1.0
        if price is None or abs(quantity * price - total) > 0.02: quantity, price = 1.0, total
        items.append({"description": description, "quantity": quantity, "unit_price": price, "total": total})
    if items: result["items"] = items
    confidence = documents[0].get("confidence") if documents else None
    sure = f", {float(confidence):.0%} sure" if isinstance(confidence, (int, float)) else ""
    result["ocr_used"] = True; result["reader"] = "azure"
    result["notes"] = f"Read by Azure (your key{sure}) - please check every amount before Save"
    return result


def read_invoice(path, folder=None, opener=None, sleep=time.sleep, today=None):
    """The invoice read by Azure, in the shape of the local reading. Raises AzureReaderError (the caller then reads it locally)."""
    return to_result(path, analyze(path, folder, opener, sleep, today))
