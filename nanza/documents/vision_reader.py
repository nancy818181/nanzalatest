"""Optional free, offline invoice transcription. Models are installed explicitly, never during a read."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

log = logging.getLogger("saber.ocr")
_LOCK = threading.RLock()
READ_TIMEOUT = 180
RUNTIME_REVISION = "b11669"
MODEL_REVISION = "1cd86afb9a95c410a6038ab3b40d8b578c892266"
MODEL_REPO = "Qwen/Qwen3-VL-4B-Instruct-GGUF"
SECONDARY_REVISION = "52d6c8ffea26cc873ac5ad116f8631268d7eb503"
from invoice_evidence import PROMPT



@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str
    url: str


def _model(name, size, checksum):
    return Asset(name, size, checksum, f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}")


MODELS = (
    _model("Qwen3VL-4B-Instruct-Q4_K_M.gguf", 2497281664,
           "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"),
    _model("mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf", 453974304,
           "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d"),
)
_SECONDARY_URL = f"https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/{SECONDARY_REVISION}"
SECONDARY_MODELS = (
    Asset("Qwen3VL-2B-Instruct-Q4_K_M.gguf", 1107409952,
          "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae",
          f"{_SECONDARY_URL}/Qwen3VL-2B-Instruct-Q4_K_M.gguf"),
    Asset("mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", 445053216,
          "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82",
          f"{_SECONDARY_URL}/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"),
)
_RELEASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{RUNTIME_REVISION}"
RUNTIMES = {
    "win32": Asset("llama-b11669-bin-win-cpu-x64.zip", 19537886,
                   "37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b",
                   f"{_RELEASE}/llama-b11669-bin-win-cpu-x64.zip"),
    "linux": Asset("llama-b11669-bin-ubuntu-x64.tar.gz", 17851611,
                   "cf07c1c112d709bd67e522017471de57ed0ec8bea031d732c5422351c07f65ac",
                   f"{_RELEASE}/llama-b11669-bin-ubuntu-x64.tar.gz"),
}


class VisionReaderError(RuntimeError):
    pass


class VisionReadCancelled(VisionReaderError):
    pass


def folder():
    import app_runtime
    return app_runtime.data_dir() / "handwriting_reader"


def binary():
    name = "llama-mtmd-cli.exe" if sys.platform == "win32" else "llama-mtmd-cli"
    root = folder() / f"runtime-{RUNTIME_REVISION}"
    return next((p for p in root.rglob(name) if p.is_file()), root / name)


def available_memory():
    """Available RAM, including reclaimable file cache; None when the OS cannot report it."""
    try:
        if sys.platform == "linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"): return int(line.split()[1]) * 1024
        elif sys.platform == "win32":
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            *((name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available",
                                                                     "virtual_total", "virtual_available", "extended"))]
            status = MemoryStatus(); status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)): return status.available
    except (OSError, ValueError, AttributeError):
        log.debug("Available memory could not be checked", exc_info=True)
    return None


def _installed(state):
    return (isinstance(state, dict) and state.get("model_revision") == MODEL_REVISION
            and state.get("runtime_revision") == RUNTIME_REVISION and state.get("secondary_revision") == SECONDARY_REVISION
            and binary().is_file() and all((folder() / a.name).stat().st_size == a.size for a in (*MODELS, *SECONDARY_MODELS)))


def ready():
    try:
        state = json.loads((folder() / "ready.json").read_text(encoding="utf-8"))
        return isinstance(state, dict) and state.get("enabled") is True and _installed(state)
    except (OSError, ValueError, TypeError):
        return False


def set_enabled(enabled):
    marker = folder() / "ready.json"
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(state, dict): raise ValueError("Invalid reader settings")
        if enabled and not _installed(state): raise ValueError("Reader setup is incomplete")
    except (OSError, ValueError) as exc:
        raise VisionReaderError("Install the free handwriting reader first") from exc
    state["enabled"] = bool(enabled)
    _write_state(state)


def _write_state(state):
    temporary = folder() / "ready.json.tmp"
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(folder() / "ready.json")


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise VisionReadCancelled("Stopped. No invoice was saved; you can try again later.")


def _matches(path, asset):
    if not path.is_file() or path.stat().st_size != asset.size: return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == asset.sha256


def _download(asset, destination, progress=None, cancel=None):
    """Resume a partial public download; only a complete, SHA-256 verified file becomes usable."""
    _cancelled(cancel)
    if _matches(destination, asset): return
    partial = destination.with_name(destination.name + ".part")
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset > asset.size:
        partial.unlink(); offset = 0
    if offset < asset.size:
        request = urllib.request.Request(asset.url, headers={"User-Agent": "Nanza-Local-Reader/1"})
        if offset: request.add_header("Range", f"bytes={offset}-")
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise VisionReaderError("The download server returned an invalid partial file; try Repair")
            elif response.status == 200:
                offset = 0
            else:
                raise VisionReaderError("The handwriting reader could not be downloaded")
            mode = "ab" if offset else "wb"
            with partial.open(mode) as output:
                while True:
                    _cancelled(cancel)
                    block = response.read(1024 * 1024)
                    if not block: break
                    offset += len(block)
                    if offset > asset.size:
                        raise VisionReaderError("The downloaded reader file is larger than expected")
                    output.write(block)
                    if progress: progress(offset, asset.size, "Downloading the free handwriting reader")
    _cancelled(cancel)
    if not _matches(partial, asset):
        partial.unlink(missing_ok=True)
        raise VisionReaderError("Reader download failed its integrity check; retry Install / Repair")
    partial.replace(destination)


def _safe_name(name):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts):
        raise VisionReaderError("Unsafe path in the reader download")
    return path


def _unpack(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            members = package.infolist()
            if sum(m.file_size for m in members) > 300 * 1024 * 1024 or len(members) > 500:
                raise VisionReaderError("Reader archive exceeds the installation limit")
            for member in members:
                path = _safe_name(member.filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise VisionReaderError("Unexpected link in the reader download")
                destination = target.joinpath(*path.parts)
                if member.is_dir(): destination.mkdir(parents=True, exist_ok=True); continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    else:
        with tarfile.open(archive, "r:gz") as package:
            members = package.getmembers()
            if sum(m.size for m in members) > 300 * 1024 * 1024 or len(members) > 500:
                raise VisionReaderError("Reader archive exceeds the installation limit")
            for member in members: _safe_name(member.name)
            package.extractall(target, filter="data")


def install(progress=None, cancel=None):
    if not _LOCK.acquire(blocking=False): raise VisionReaderError("The handwriting reader is busy; try setup after it finishes")
    try:
        if platform.machine().lower() not in ("amd64", "x86_64") or sys.platform not in RUNTIMES:
            raise VisionReaderError("The free handwriting reader currently needs 64-bit Windows or Linux")
        base = folder(); base.mkdir(parents=True, exist_ok=True)
        assets = (RUNTIMES[sys.platform], *MODELS, *SECONDARY_MODELS)
        needed = sum(a.size for a in assets if not _matches(base / a.name, a)) + 200 * 1024 * 1024
        if shutil.disk_usage(base).free < needed:
            raise VisionReaderError("Not enough free disk space: allow about 5 GB for the two handwriting readers")
        for asset in assets: _download(asset, base / asset.name, progress, cancel)
        _cancelled(cancel)
        if progress: progress(0, 0, "Checking the handwriting reader")
        _unpack(base / assets[0].name, base / f"runtime-{RUNTIME_REVISION}")
        executable = binary()
        if not executable.is_file():
            raise VisionReaderError("Reader archive is missing the executable for this operating system; retry Install / Repair")
        _run([str(executable), "--version"], 20, cancel)
        _write_state({"enabled": True, "model_revision": MODEL_REVISION, "secondary_revision": SECONDARY_REVISION,
                      "runtime_revision": RUNTIME_REVISION})
        return "Free handwriting reader installed. Invoices stay on this computer. Check all amounts and dates before Save."
    except (OSError, urllib.error.URLError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise VisionReaderError(f"Handwriting reader setup did not finish: {exc}. Retry Install / Repair to resume.") from exc
    finally:
        _LOCK.release()


def _run(command, timeout, cancel=None):
    """File-backed pipes prevent a stalled reader from blocking the UI; stop and timeout always kill it."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_") and k != "HF_TOKEN"}
    process = None
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            _cancelled(cancel)
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                       env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                _cancelled(cancel)
                if time.monotonic() >= deadline:
                    raise VisionReaderError("The handwriting reader took too long. Use normal reading or enter unclear fields manually.")
                time.sleep(.1)
            errors.seek(0)
            if process.returncode:
                log.warning("Local handwriting reader stopped (%s): %s", process.returncode, errors.read(6000).decode("utf-8", "replace"))
                raise VisionReaderError("The handwriting reader could not finish; try Install / Repair or normal reading")
            output.seek(0); text = output.read(65537)
            if len(text) > 65536: raise VisionReaderError("The handwriting reader returned too much text")
            return text.decode("utf-8", "replace").strip()
        except OSError as exc:
            raise VisionReaderError(f"The handwriting reader could not start: {exc}") from exc
        finally:
            if process is not None and process.poll() is None:
                try: process.kill(); process.wait(timeout=5)
                except (OSError, subprocess.SubprocessError): log.warning("Handwriting reader cleanup failed", exc_info=True)


def _prepare_image(path, target):
    from PIL import Image, ImageOps
    with ExitStack() as stack:
        if Path(path).suffix.lower() == ".pdf":
            import pypdfium2 as pdfium
            document = stack.enter_context(pdfium.PdfDocument(path))
            if len(document) != 1: raise VisionReaderError("Read one handwritten invoice page at a time")
            page = document[0]; stack.callback(page.close)
            width, height = page.get_size()
            if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                raise VisionReaderError("The invoice PDF has an invalid page size")
            scale = min(2, math.sqrt(1003520 / (width * height)))
            bitmap = page.render(scale=scale); stack.callback(bitmap.close)
            original = bitmap.to_pil(); stack.callback(original.close)
        else:
            original = stack.enter_context(Image.open(path))
        if original.width * original.height > 25000000:
            raise VisionReaderError("This photo is too large; use a smaller copy for handwriting reading")
        image = ImageOps.exif_transpose(original).convert("RGB"); stack.callback(image.close)
        scale = min(1, math.sqrt(1003520 / (image.width * image.height)))
        if scale < 1:
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
            stack.callback(image.close)
        image.save(target, "PNG")


def read_text(path, cancel=None, secondary=False):
    if not ready(): raise VisionReaderError("Install and enable the free handwriting reader in Accounting Settings first")
    if not _LOCK.acquire(timeout=2): raise VisionReaderError("The handwriting reader is busy; try again after it finishes")
    try:
        available = available_memory()
        if available is not None and available < 6 * 1024 ** 3:
            raise VisionReaderError("The handwriting reader needs about 6 GB of free RAM. Close other programs or use normal reading.")
        with tempfile.TemporaryDirectory(prefix="nanza_handwriting_") as temporary:
            image = Path(temporary) / "invoice.png"
            _cancelled(cancel); _prepare_image(path, image)
            models = SECONDARY_MODELS if secondary else MODELS
            command = [str(binary()), "-m", str(folder() / models[0].name), "--mmproj", str(folder() / models[1].name),
                       "--image", str(image), "-p", PROMPT, "-n", "1536", "-c", "4096", "-t", "2", "--temp", "0", "--seed", "0",
                       "--repeat-penalty", "1.1", "--no-mmproj-offload", "--n-gpu-layers", "0",
                       "--jinja", "--verbosity", "1", "--log-colors", "off", "--offline"]
            text = _run(command, READ_TIMEOUT, cancel)
            if len(text.strip()) < 20: raise VisionReaderError("Could not read enough handwriting; use normal reading or enter the fields manually")
            return text
    finally:
        _LOCK.release()


def _written_money(value):
    """Only literal numeric amounts; no arithmetic, missing-value defaults or repairs of unrecognised characters."""
    from decimal import Decimal, InvalidOperation
    from pdf_import import _normalize_amount_line, normalize_invoice_text
    if value is None or isinstance(value, bool): return None
    text = normalize_invoice_text(_normalize_amount_line(str(value))).strip()
    text = text.replace("\u202f", " ").replace("\u00a0", " ")
    explicit_grouping = "٬" in str(value) or bool(re.search(r"(?i)USD|LBP|GBP|AED|SAR|[$£]", str(value)))
    text = re.sub(r"(?i)\b(?:USD|LBP|EUR|AED|SAR|GBP)\b|[$€£]", "", text).strip()
    if re.fullmatch(r"[-+]?(?:\d{1,3}(?:[. ]\d{3})+|\d+),\d{1,2}", text):
        text = text.replace(".", "").replace(" ", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3},\d{3}", text) and not explicit_grouping:
        return None  # 1,234 could mean a decimal or a thousands group: abstain.
    if not re.fullmatch(r"[-+]?(?:\d{1,3}(?:[, ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)", text): return None
    try:
        amount = Decimal(text.replace(",", "").replace(" ", ""))
        number = float(amount)
        return number if amount.is_finite() and math.isfinite(number) else None
    except InvalidOperation:
        return None


def _decode_invoice(path, text):
    from pdf_import import _invoice_currency, _invoice_date, _normalize_amount_line, _parse_invoice_text, mentions_own_company
    if len(text) > 65536: raise VisionReaderError("Invoice transcription is too large; review the document manually")
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I).strip()
    try: values = json.loads(clean)
    except (ValueError, TypeError) as exc: raise VisionReaderError("The handwriting reader could not identify clear invoice fields") from exc
    if not isinstance(values, dict): raise VisionReaderError("The handwriting reader returned an invalid invoice")
    from invoice_evidence import literal_schema, PROMPT_VERSION
    values = literal_schema(values)
    def literal(key):
        value = values.get(key)
        if value is None: return ""
        if not isinstance(value, (str, int, float)) or isinstance(value, bool): return ""
        value = str(value).strip()[:500]
        if value.lower() in ("unknown", "unreadable", "unclear", "n/a", "none", "null") or "[unreadable]" in value.lower(): return ""
        return value
    lines = [f"Invoice No: {literal('invoice_number')}", f"Date: {literal('date_as_written')}",
             f"Currency: {literal('currency')}", f"Description: {literal('description_as_written')}"]
    for field, label in (("subtotal", "Subtotal"), ("vat", "VAT"), ("total", "Grand Total")):
        lines.append(f"{label}: {literal(field + '_as_written')}")
    # Reuse classification, not the printed-document amount inference rules.
    classified = _parse_invoice_text(path, "Description: " + literal("description_as_written"))
    categories = ("suggested_type", "suggested_account", "expense_category", "suggested_account_9", "suggested_account_name", "asset_name")
    digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    number = literal("invoice_number").translate(digits)
    if not re.fullmatch(r"[\w./-]{1,64}", number): number = ""
    result = {"file": Path(path).name, "path": str(path), "text": "\n".join(lines), "notes": "Read by the free local handwriting reader",
              "invoice_number": number, "invoice_date": "", "currency": _invoice_currency("Currency: " + literal("currency")),
              **{field: _written_money(values.get(field + "_as_written")) for field in ("subtotal", "vat", "total")},
              **{field: classified.get(field, "") for field in categories}}
    result["acquisition_cost"] = result["subtotal"]
    result["inferred"] = []; result["items"] = []; result["review_warnings"] = []
    result["party_name"] = literal("supplier_as_written")
    result["party_tax_number"] = literal("supplier_tax_id_as_written").translate(digits)
    result["prompt_version"] = PROMPT_VERSION
    if result["party_name"] and mentions_own_company(result["party_name"]): result["party_name"] = ""
    result["supplier_hint"] = result["party_name"]
    date = _normalize_amount_line(literal("date_as_written"))
    if re.search(r"(?<!\d)\d{4}(?!\d)", date): result["invoice_date"] = _invoice_date("Date: " + date)
    from invoice_evidence import analyze
    evidence = analyze(values, _written_money)
    result["transcription_evidence"] = evidence
    if values.get("document_type") in ("invoice","receipt","credit_note","debit_note","quotation","delivery_note"):
        result["document_type"]=values["document_type"]
    result["review_warnings"].extend(evidence["warnings"])
    for field in evidence["uncertain_fields"]:
        if field in ("invoice_number", "invoice_date", "party_name", "party_tax_number", "currency", "subtotal", "vat", "total"):
            result[field] = None if field in ("subtotal", "vat", "total") else ""
            result["review_warnings"].append(f"Reader marked {field} uncertain; confirm from the image")
    result["supplier_hint"] = result["party_name"]
    result["acquisition_cost"] = result["subtotal"]
    result["handwriting_fields"] = {key: literal(key) for key in values}
    return result


def read_invoice(path, cancel=None, previous=None):
    from decimal import Decimal
    from pdf_import import _require_ocr_review, _warn_on_invoice_total_mismatch
    from reader_consensus import merge_invoice_readings
    if not _LOCK.acquire(timeout=2): raise VisionReaderError("The handwriting reader is busy; try again after it finishes")
    try:
        primary = _decode_invoice(path, read_text(path, cancel))
        _cancelled(cancel)
        secondary = _decode_invoice(path, read_text(path, cancel, secondary=True))
        result = merge_invoice_readings(primary, secondary)
    finally:
        _LOCK.release()
    result.update(reader="vision-local", ocr_used=True)
    warnings = result.setdefault("review_warnings", [])
    warnings.append("Handwriting read locally: verify every amount and date against the original image before Save")
    for field in ("invoice_number", "invoice_date", "currency", "subtotal", "vat", "total"):
        old = (previous or {}).get(field); new = result.get(field)
        differs = old not in (None, "") and new not in (None, "") and str(old) != str(new)
        if differs and field in ("subtotal", "vat", "total"):
            differs = Decimal(str(old)) != Decimal(str(new))
        if differs:
            result[field] = None if field in ("subtotal", "vat", "total") else ""
            warnings.append(f"Readers disagree on {field.replace('_', ' ')}: confirm it from the image")
    _warn_on_invoice_total_mismatch(result)
    result["acquisition_cost"] = result.get("subtotal")
    return _require_ocr_review(result)
