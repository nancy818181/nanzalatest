"""Review gates and background dispatch for document reading."""
import tests_setup  # noqa: F401
import tempfile
import unittest
import numpy  # Load before OCR tests patch sys.modules; native modules must not be re-imported.
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class ReadingSafetyTest(unittest.TestCase):
    def test_expense_reading_is_dispatched_before_ocr_starts(self):
        from desktop_expenses import ExpensesMixin
        app = SimpleNamespace(expense_form={"id": None})
        with patch("desktop_expenses.filedialog.askopenfilename", return_value="invoice.jpg"), \
             patch("desktop_expenses.prepare_pdf_reading"), \
             patch("desktop_expenses.run_with_progress") as background, \
             patch("desktop_expenses.read_invoice_pdf", return_value={"total": 40}) as read:
            ExpensesMixin.choose_expense_pdf(app)
            read.assert_not_called()
            self.assertEqual(background.call_args.args[2](None, None), {"total": 40})
            read.assert_called_once_with("invoice.jpg")

    def test_asset_reading_is_dispatched_before_ocr_starts(self):
        from desktop_asset_register import AssetRegisterMixin
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invoice.pdf"; path.write_bytes(b"test")
            with patch("desktop_asset_register.filedialog.askopenfilename", return_value=str(path)), \
                 patch("desktop_stage3_common.prepare_pdf_reading"), \
                 patch("desktop_asset_register.run_with_progress") as background, \
                 patch("desktop_asset_register.read_invoice_pdf", return_value={}) as read:
                AssetRegisterMixin.choose_asset_pdf(SimpleNamespace())
                read.assert_not_called()
                background.call_args.args[2](None, None)
                read.assert_called_once_with(str(path))

    def test_sales_reading_is_dispatched_before_ocr_starts(self):
        from desktop_v22 import V22Mixin
        with patch("desktop_v22.filedialog.askopenfilename", return_value="invoice.pdf"), \
             patch("desktop_stage3_common.prepare_pdf_reading"), \
             patch("desktop_stage3_common.run_with_progress") as background, \
             patch("pdf_import.read_invoice_pdf", return_value={}) as read:
            V22Mixin.import_sales_pdf(SimpleNamespace())
            read.assert_not_called()
            background.call_args.args[2](None, None)
            read.assert_called_once_with("invoice.pdf")

    def test_utility_total_is_not_fabricated_from_base_plus_vat(self):
        from pdf_import import _utility_bill
        self.assertIsNone(_utility_bill("TOTAL TRANCHES 671,250 TVA 73,838"))

    def test_photo_preparation_preserves_original(self):
        from PIL import Image, ImageDraw
        from ocr_photo import variants
        original=Image.new("RGB", (400, 500), "white")
        ImageDraw.Draw(original).text((40, 40), "Invoice 42", fill="black")
        before=original.tobytes()
        prepared=variants(original)
        self.assertEqual(original.tobytes(), before)
        self.assertEqual(len(prepared), 2)
        for image in prepared:
            self.assertGreater(image.width, 100)
            self.assertGreater(image.height, 100)
            image.close()

    def test_local_review_warning_is_idempotent(self):
        from pdf_import import _require_ocr_review
        result={"notes": "Read locally"}
        _require_ocr_review(result); _require_ocr_review(result)
        self.assertTrue(result["review_required"])
        self.assertEqual(len(result["review_warnings"]), len(set(result["review_warnings"])))
        self.assertTrue(any("VAT" in warning for warning in result["review_warnings"]))

    def test_merging_readings_preserves_inference_warnings(self):
        from pdf_import import _merge_invoice_suggestions, _require_ocr_review
        result = _merge_invoice_suggestions({}, {"total": 111, "inferred": ["total calculated"],
                                                 "review_warnings": ["Check inferred amount"]})
        _require_ocr_review(result)
        self.assertEqual(result["inferred"], ["total calculated"])
        self.assertIn("Check inferred amount", result["review_warnings"])
