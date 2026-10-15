"""2.9.118: EDL bills photographed with a phone (dot-matrix amounts, the VAT number printed at the top) and photos read as
invoices (JPG / PNG)."""
import tests_setup  # noqa: F401
import tempfile
import unittest
from pathlib import Path

import pdf_import


class EdlBillTest(unittest.TestCase):
    def test_vat_registration_number_is_not_the_vat(self):
        text = "N° TVA : 241559-601\nTOTAL TRANCHES 671250\nTVA 11% 73838\nTIMBRE 100000\nTOTAL 846000"
        self.assertNotEqual(pdf_import._vat_amount_after(text, "LBP"), 241559)

    def test_base_only_gives_vat_stamp_and_rounded_total(self):
        # what OCR read of a photographed bill: the base once, the VAT number, the account numbers
        text = "electricite du liban\nN° TVA : 241559\n042651 73 664 400 01\n671250\n76983 400007"
        self.assertEqual(pdf_import._edl_from_base(text)["vat"], 73838.0)
        self.assertEqual(pdf_import._edl_from_base(text)["total"], 846000.0)  # 671,250 + 73,838 + 100,000 rounded up
        self.assertEqual(pdf_import._edl_from_base("2026 EDL 1816850 1816850 120000")["total"], 2117000.0)

    def test_parse_edl_text(self):
        result = pdf_import._parse_invoice_text("edl.pdf", "Electricité du Liban\nwww.edl.gov.lb\nN° TVA : 241559\n06/08/2026\n"
                                                           "TOTAL TRANCHES 671250\nBRANCHEMENT INSTALLATION 042651")
        self.assertEqual((result["subtotal"], result["vat"], result["total"]), (671250.0, 73838.0, 846000.0))
        self.assertEqual(result["currency"], "LBP")
        self.assertIn("EDL", result["supplier_hint"])

    def test_photo_becomes_a_pdf(self):
        from PIL import Image
        folder = Path(tempfile.mkdtemp())
        picture = folder / "bill.jpg"; Image.new("RGB", (300, 200), "white").save(picture)
        converted = pdf_import._image_as_pdf(picture)
        self.assertEqual(converted.suffix, ".pdf"); self.assertTrue(converted.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
