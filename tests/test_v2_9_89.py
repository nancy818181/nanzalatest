"""2.9.89: Uploaded Data > Auto Calculate Totals; OCR engines limited to one core each and run side by side."""
import types
import unittest
from unittest import mock

from desktop_stage3 import Stage3Mixin


class _Sheet:
    def __init__(self, rows): self.rows = rows; self.tree = types.SimpleNamespace(selection=lambda: ()); self.refreshed = []
    def refresh(self, iid): self.refreshed.append(iid)


class AutoCalculateTest(unittest.TestCase):
    def test_missing_or_wrong_amounts_are_worked_out(self):
        rows = {"a": {"subtotal": 215.0, "vat": 23.65, "total": 2.0},      # wrong total
                "b": {"subtotal": None, "vat": 127.93, "total": 2165.93},  # subtotal missing
                "c": {"subtotal": 1000.0, "vat": None, "total": None},     # only the subtotal: VAT 11%
                "d": {"subtotal": 100.0, "vat": 11.0, "total": 111.0}}     # already right
        screen = types.SimpleNamespace(import_sheet=_Sheet(rows), client=types.SimpleNamespace(settings=lambda: {"vat_rate": "11"}),
                                       import_status=mock.Mock(), import_cell_changed_display=lambda row: None)
        self.assertEqual(Stage3Mixin.import_auto_calculate(screen), 3)
        self.assertEqual([(r["subtotal"], r["vat"], r["total"]) for r in rows.values()],
                         [(215.0, 23.65, 238.65), (2038.0, 127.93, 2165.93), (1000.0, 110.0, 1110.0), (100.0, 11.0, 111.0)])
        self.assertIn("auto-calculated", rows["a"]["notes"])


class OcrSettingsTest(unittest.TestCase):
    def test_one_core_per_ocr_engine(self):
        import os, sys, pdf_import
        fake = types.SimpleNamespace(get_languages=lambda config=None: ["eng"], image_to_string=lambda *a, **k: "", pytesseract=types.SimpleNamespace())
        document = mock.MagicMock(); document.__len__.return_value = 0
        with mock.patch.dict(sys.modules, {"pytesseract": fake, "pypdfium2": types.SimpleNamespace(PdfDocument=lambda path: document)}), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OMP_THREAD_LIMIT", None)
            self.assertEqual(pdf_import._ocr_pdf_pages("x.pdf", []), [])
            self.assertEqual(os.environ.get("OMP_THREAD_LIMIT"), "1")


if __name__ == "__main__":
    unittest.main()
