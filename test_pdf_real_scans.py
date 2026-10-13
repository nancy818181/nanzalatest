"""Real scanned invoices: OCR text kept as fixtures so the reader can be checked without Tesseract."""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pdf_import import _ocr_pdf_pages, _parse_invoice_text

DATA = Path(__file__).resolve().parent / "tests_data"


class RealScanTests(unittest.TestCase):
    def test_contractor_variation_order_all_fields(self):
        # Full-page OCR of a real scan: three section totals, then TOTAL A+B+C, VAT 11% and Grand Total;
        # the underlined date was read by the header pass.
        text = (DATA / "ocr_contractor_variation_order.txt").read_text(encoding="utf-8") + "\nRef Nb: SMP-30-24\nDate: 26-Jun-24\n"
        parsed = _parse_invoice_text("reference 4.pdf", text)
        self.assertEqual(parsed["invoice_number"], "SMP-30-24")
        self.assertEqual(parsed["invoice_date"], "26-06-2024")  # not a delivery date from the table
        self.assertEqual(parsed["party_name"], "SAMPLE CONTRACTORS S.A.L")  # logo junk removed
        self.assertEqual(parsed["currency"], "USD")
        self.assertEqual((parsed["subtotal"], parsed["vat"], parsed["total"]), (18878.5, 2076.64, 20955.14))

    def test_unlabelled_amounts_and_lbp_vat_line_of_a_usd_invoice(self):
        # Text layer with broken Arabic labels: the summary box shows 38000 / 4180 / 0 / 42,180.00
        # without readable words, and "VAT 11% LBP 374,110,000" is the VAT in LBP of a USD invoice.
        text = (DATA / "text_supplier_invoice_broken_arabic.txt").read_text(encoding="utf-8")
        parsed = _parse_invoice_text("5000290336.pdf", text)
        self.assertEqual((parsed["invoice_number"], parsed["invoice_date"]), ("16", "01-11-2024"))
        # The scrambled text layer is sent to OCR; the OCR reading gives the supplier.
        from pdf_import import _invoice_text_needs_ocr
        self.assertTrue(_invoice_text_needs_ocr("5000290336.pdf", text))
        ocr = _parse_invoice_text("5000290336.pdf", (DATA / "ocr_supplier_invoice.txt").read_text(encoding="utf-8"))
        self.assertEqual((ocr["invoice_number"], ocr["invoice_date"], ocr["party_name"], ocr["currency"]), ("16", "01-11-2024", "Sample K. Supplier", "USD"))
        self.assertEqual((ocr["subtotal"], ocr["vat"], ocr["total"]), (38000.0, 4180.0, 42180.0))
        self.assertEqual(parsed["currency"], "USD")
        self.assertEqual((parsed["subtotal"], parsed["vat"], parsed["total"]), (38000.0, 4180.0, 42180.0))
        self.assertIn("11% VAT check - verify", parsed["notes"])

    def test_section_total_is_not_taken_as_subtotal_when_another_total_reconciles(self):
        text = ("Supplier SAL\nInvoice No: 9\nDate: 01-02-2026\nTOTAL USD $ 100.00\nTOTAL USD $ 50.00\n"
                "TOTAL A+B $ 150.00\nVAT 11% $ 16.50\nGrand Total: $ 166.50")
        parsed = _parse_invoice_text("x.pdf", text)
        self.assertEqual((parsed["subtotal"], parsed["vat"], parsed["total"]), (150.0, 16.5, 166.5))

    def test_bundled_language_files_use_tessdata_prefix_not_a_windows_path_option(self):
        image = Mock(); image.size = (1000, 1400); image.crop.return_value = image
        bitmap = Mock(); bitmap.to_pil.return_value = image
        page = Mock(); page.render.return_value = bitmap
        document = Mock(); document.__len__ = lambda _s: 1; document.__getitem__ = lambda _s, _i: page
        pdfium = types.ModuleType("pypdfium2"); pdfium.PdfDocument = Mock(return_value=document)
        tess = types.ModuleType("pytesseract"); tess.pytesseract = types.SimpleNamespace(tesseract_cmd="")
        tess.get_languages = Mock(return_value=["eng", "ara"])
        tess.image_to_string = Mock(return_value="Invoice No: 1\nDate: 01-01-2026\nTotal: 10.00")
        folder = Path(__file__).resolve().parent / "ocr" / "tessdata"
        with patch.dict(sys.modules, {"pypdfium2": pdfium, "pytesseract": tess}), \
             patch.object(Path, "is_dir", lambda self: self == folder or Path.is_dir.__wrapped__(self) if hasattr(Path.is_dir, "__wrapped__") else self == folder), \
             patch.dict("os.environ", {}, clear=False):
            import os
            _ocr_pdf_pages("scan.pdf", [0])
            self.assertEqual(os.environ.get("TESSDATA_PREFIX"), str(folder))
        for call in tess.image_to_string.call_args_list + tess.get_languages.call_args_list:
            self.assertNotIn("tessdata-dir", str(call))


if __name__ == "__main__":
    unittest.main()
