"""The optional offline handwriting reader never guesses missing money or posts an invoice."""
import tests_setup  # noqa: F401
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import vision_reader as vr


def payload(**changes):
    data = {"invoice_number": "SYN-9", "date_as_written": "15/07/2026", "currency": "USD",
            "subtotal_as_written": "60.00", "vat_as_written": None, "total_as_written": "60.00",
            "description_as_written": "Repair service", "supplier_as_written": "Example Workshop"}
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


class LiteralInvoiceTest(unittest.TestCase):
    def read(self, **changes):
        with patch.object(vr, "read_text", return_value=payload(**changes)):
            return vr.read_invoice("synthetic.jpg")

    def test_arabic_digits_are_numeric_and_every_reading_requires_review(self):
        result = self.read(subtotal_as_written="٦٠٫٠٠", total_as_written="$٦٠٫٠٠", date_as_written="١٥/٠٧/٢٠٢٦")
        self.assertEqual((result["subtotal"], result["total"]), (60, 60))
        self.assertEqual(result["invoice_date"], "15-07-2026")
        self.assertTrue(result["review_required"])
        self.assertTrue(result["review_warnings"])
        self.assertEqual(result["reader"], "vision-local")

    def test_missing_total_and_vat_are_not_calculated(self):
        result = self.read(total_as_written=None)
        self.assertIsNone(result["vat"])
        self.assertIsNone(result["total"])
        self.assertEqual(result["subtotal"], 60)
        self.assertIn("total", " ".join(result["review_warnings"]))

    def test_zero_vat_stays_zero_but_a_missing_base_is_not_inferred(self):
        result = self.read(subtotal_as_written=None, vat_as_written="٠")
        self.assertEqual(result["vat"], 0)
        self.assertIsNone(result["subtotal"])
        self.assertIsNone(result["acquisition_cost"])

    def test_ambiguous_year_and_unreadable_invoice_number_stay_empty(self):
        result = self.read(date_as_written="1/1/26", invoice_number="[unreadable]")
        self.assertEqual(result["invoice_date"], "")
        self.assertEqual(result["invoice_number"], "")

    def test_nonliteral_and_nonfinite_amounts_are_rejected(self):
        for value in ("NaN", "Infinity", "20 + 40", "1,2,3", True, "[unreadable]", "9" * 400):
            self.assertIsNone(vr._written_money(value), value)
        self.assertEqual(vr._written_money("1,234.50 USD"), 1234.5)

    def test_disagreement_clears_the_amount_and_dependent_asset_cost(self):
        with patch.object(vr, "read_text", return_value=payload()):
            result = vr.read_invoice("synthetic.jpg", previous={"subtotal": 61, "total": 61})
        self.assertIsNone(result["subtotal"])
        self.assertIsNone(result["total"])
        self.assertIsNone(result["acquisition_cost"])
        self.assertIn("disagree", " ".join(result["review_warnings"]))

    def test_equivalent_decimal_formats_do_not_create_a_false_conflict(self):
        with patch.object(vr, "read_text", return_value=payload()):
            result = vr.read_invoice("synthetic.jpg", previous={"subtotal": "60.00", "total": 60})
        self.assertEqual(result["total"], 60)
        self.assertNotIn("disagree", " ".join(result["review_warnings"]))

    def test_bad_json_is_reported_instead_of_filling_fields(self):
        for text in ("A plausible invoice with total 100", "[]", "{broken}"):
            with self.assertRaises(vr.VisionReaderError): vr._decode_invoice("synthetic.jpg", text)


class ReaderProcessTest(unittest.TestCase):
    def test_timeout_and_cancel_kill_the_reader(self):
        real_popen = subprocess.Popen
        for cancelled in (False, True):
            processes = []
            def start(*args, **kwargs):
                child = real_popen(*args, **kwargs); processes.append(child); return child
            event = threading.Event()
            timer = threading.Timer(.2, event.set) if cancelled else None
            if timer: timer.start()
            try:
                with patch.object(vr.subprocess, "Popen", side_effect=start):
                    with self.assertRaises(vr.VisionReadCancelled if cancelled else vr.VisionReaderError):
                        vr._run([sys.executable, "-c", "import time; time.sleep(30)"], 5 if cancelled else .2, event)
            finally:
                if timer: timer.cancel()
            self.assertEqual(len(processes), 1)
            self.assertIsNotNone(processes[0].poll())

    def test_large_and_failed_outputs_are_not_used(self):
        for code in ("print('x'*70000)", "raise SystemExit(3)"):
            with self.assertRaises(vr.VisionReaderError): vr._run([sys.executable, "-c", code], 5)

    def test_photo_preparation_preserves_the_original(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "photo.png"; target = Path(folder) / "prepared.png"
            with Image.new("RGB", (1500, 1200), "white") as image: image.save(source)
            before = source.read_bytes(); vr._prepare_image(source, target)
            self.assertEqual(source.read_bytes(), before)
            with Image.open(target) as result: self.assertLessEqual(result.width * result.height, 1003520)

    def test_large_pdf_is_bounded_before_the_renderer_allocates_pixels(self):
        from PIL import Image
        from types import SimpleNamespace
        image = Image.new("RGB", (1000, 1000), "white")
        rendered = []
        def render(scale):
            self.assertLessEqual((10000 * scale) ** 2, 1100000)
            rendered.append(scale)
            return SimpleNamespace(to_pil=lambda: image, close=lambda: None)
        page = SimpleNamespace(get_size=lambda: (10000, 10000), render=render, close=lambda: None)
        class Document(list):
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with tempfile.TemporaryDirectory() as folder, patch("pypdfium2.PdfDocument", return_value=Document([page])):
            target = Path(folder) / "preview.png"
            vr._prepare_image("large.pdf", target)
            self.assertTrue(target.is_file())
        self.assertEqual(len(rendered), 1)


class ReaderInstallationTest(unittest.TestCase):
    def asset(self, data=b"abcdef", name="model.gguf"):
        return vr.Asset(name, len(data), hashlib.sha256(data).hexdigest(), "https://example.invalid/model")

    def response(self, body, status=200, headers=None):
        result = io.BytesIO(body); result.status = status; result.headers = headers or {}; return result

    def test_partial_download_resumes_and_checks_its_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "model.gguf"; destination.with_name("model.gguf.part").write_bytes(b"abc")
            with patch.object(vr.urllib.request, "urlopen", return_value=self.response(b"def", 206, {"Content-Range": "bytes 3-5/6"})) as request:
                vr._download(self.asset(), destination)
            self.assertEqual(request.call_args.args[0].get_header("Range"), "bytes=3-")
            self.assertEqual(destination.read_bytes(), b"abcdef")

    def test_bad_download_never_becomes_a_model(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "model.gguf"
            with patch.object(vr.urllib.request, "urlopen", return_value=self.response(b"xxxxxx")):
                with self.assertRaises(vr.VisionReaderError): vr._download(self.asset(), destination)
            self.assertFalse(destination.exists())

    def test_cancelled_download_can_resume_later(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "model.gguf"; event = threading.Event()
            def progress(*args): event.set()
            with patch.object(vr.urllib.request, "urlopen", return_value=self.response(b"abc")):
                with self.assertRaises(vr.VisionReadCancelled): vr._download(self.asset(), destination, progress, event)
            self.assertEqual(destination.with_name("model.gguf.part").read_bytes(), b"abc")
            self.assertFalse(destination.exists())

    def test_archive_cannot_write_outside_the_reader_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as package: package.writestr("../escape.exe", "bad")
            with self.assertRaises(vr.VisionReaderError): vr._unpack(archive, Path(folder) / "runtime")
            self.assertFalse((Path(folder) / "escape.exe").exists())

    def test_normal_reading_never_downloads_models(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(vr, "folder", return_value=Path(folder)), \
                patch.object(vr.urllib.request, "urlopen") as download:
            self.assertFalse(vr.ready())
            with self.assertRaises(vr.VisionReaderError): vr.read_text("synthetic.jpg")
            download.assert_not_called()

    def test_setup_marks_ready_only_after_verified_files_and_runtime_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zipped = io.BytesIO()
            with zipfile.ZipFile(zipped, "w") as package: package.writestr("llama-mtmd-cli", "synthetic-runtime")
            runtime = self.asset(zipped.getvalue(), "runtime.zip")
            models = (self.asset(b"one", "one.gguf"), self.asset(b"two", "two.gguf"))
            data = {runtime.url: zipped.getvalue()}
            runtime = vr.Asset(runtime.name, runtime.size, runtime.sha256, "https://example.invalid/runtime")
            data[runtime.url] = zipped.getvalue()
            models = tuple(vr.Asset(a.name, a.size, a.sha256, "https://example.invalid/" + a.name) for a in models)
            data.update({a.url: b"one" if a.name == "one.gguf" else b"two" for a in models})
            def response(request, **kwargs): return self.response(data[request.full_url])
            with patch.object(vr, "folder", return_value=root), patch.object(vr, "MODELS", models), patch.object(vr, "SECONDARY_MODELS", ()), \
                    patch.object(vr, "RUNTIMES", {sys.platform: runtime}), patch.object(vr.platform, "machine", return_value="AMD64"), \
                    patch.object(vr.urllib.request, "urlopen", side_effect=response), patch.object(vr, "_run", return_value="version"):
                vr.install()
                self.assertTrue(vr.ready())
                vr.set_enabled(False); self.assertFalse(vr.ready())
                vr.set_enabled(True); self.assertTrue(vr.ready())
                vr.set_enabled(False)
                (root / models[0].name).unlink()
                with self.assertRaises(vr.VisionReaderError): vr.set_enabled(True)
                self.assertFalse(vr.ready())


class InvoiceDispatchTest(unittest.TestCase):
    def test_enabled_reader_runs_before_legacy_ocr_for_a_photo(self):
        from pdf_import import read_invoice_pdf
        event = threading.Event()
        with patch.object(vr, "ready", return_value=True), patch.object(vr, "read_invoice", return_value={"total": 60}) as read, \
                patch("pdf_import._read_invoice_pdf_local") as legacy:
            self.assertEqual(read_invoice_pdf("synthetic.jpg", cancel=event), {"total": 60})
        read.assert_called_once_with("synthetic.jpg", event); legacy.assert_not_called()

    def test_reader_failure_preserves_legacy_result_with_a_warning(self):
        from pdf_import import read_invoice_pdf
        with patch.object(vr, "ready", return_value=True), patch.object(vr, "read_invoice", side_effect=vr.VisionReaderError("not enough RAM")), \
                patch("pdf_import._read_invoice_pdf_local", return_value={"total": 60, "notes": "Local"}):
            result = read_invoice_pdf("synthetic.jpg")
        self.assertEqual(result["total"], 60)
        self.assertTrue(result["review_required"])
        self.assertIn("not enough RAM", str(result["review_warnings"]))

    def test_cancel_does_not_start_another_reader(self):
        from pdf_import import read_invoice_pdf
        event = threading.Event(); event.set()
        with patch("pdf_import._read_invoice_pdf_local") as legacy:
            with self.assertRaises(vr.VisionReadCancelled): read_invoice_pdf("synthetic.jpg", cancel=event)
        legacy.assert_not_called()


if __name__ == "__main__": unittest.main()
