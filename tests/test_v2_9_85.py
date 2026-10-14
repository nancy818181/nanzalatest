"""2.9.85: purchase PDFs - table rows with the amounts first, VAT printed before its label, "Currency: USD",
the supplier (never the company's own name), layout text, supporting pages kept with their invoice, long PDFs read
page by page off the screen (only the first invoice on the purchase screen)."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pdf_import
from desktop_stage3_common import run_with_progress

INVOICE = """ACME FOODS S.A.L.                                           . ل.م.ش ةيذغالأ مكأ
Spices - Nuts                                                 Tel : +961 1 000000
13/10/2025            Invoice # : AF-2025-77      Page: 1
Code:   BUY       Name:Buyer Trading Co                          MOF#:  123
Address  : Free zone                             Phone:              Currency:USD
  TOTAL        VAT      DISC.   U.PRICE     Q.    WEIGHT         ITEM DESCRIPTION      CODE
  1,529.00     0.00    0.00 %        2.78   550     2KG          1193 CHANNA DRIED      CH04
   568.00      0.00    0.00 %        3.55   160     1KG          4116 DATES PITTED      FD08
   200.00     22.00    0.00 %        0.50   400     100GR        4202 TURMERIC          ST01
 TOTAL NET WEIGHT (KG)           13960
           V.A.T. (LBP)   1,969,000
     2,297.00    المجموع قبل الضریبة
       22.00        V.A.T. 11%
     2,319.00      $ المجموع الصافي
"""


class ParserTest(unittest.TestCase):
    def setUp(self):
        pdf_import.set_own_company("Buyer Trading Co"); pdf_import.set_known_parties([])
        self.addCleanup(pdf_import.set_own_company); self.addCleanup(pdf_import.set_known_parties, [])

    def test_layout_invoice_with_amounts_first(self):
        parsed = pdf_import._parse_invoice_text("acme.pdf", INVOICE)
        self.assertEqual((parsed["invoice_number"], parsed["invoice_date"], parsed["currency"]), ("AF-2025-77", "13-10-2025", "USD"))
        self.assertEqual((parsed["subtotal"], parsed["vat"], parsed["total"]), (2297.0, 22.0, 2319.0))  # not the weight, not the VAT in LBP
        self.assertEqual(parsed["party_name"], "ACME FOODS S.A.L")  # the seller, not "Buyer Trading Co"
        self.assertEqual([(i["description"], i["quantity"], i["unit_price"], i["unit"]) for i in parsed["items"]],
                         [("1193 CHANNA DRIED CH04", 550.0, 2.78, "2KG"), ("4116 DATES PITTED FD08", 160.0, 3.55, "1KG"), ("4202 TURMERIC ST01", 400.0, 0.5, "100GR")])
        self.assertEqual(round(sum(i["total"] for i in parsed["items"]), 2), parsed["subtotal"])
        self.assertEqual((parsed["taxable_subtotal"], parsed["exempt_subtotal"]), (200.0, 2097.0))  # VAT 22 = 11% of the taxable row

    def test_supplier_names(self):
        self.assertEqual(pdf_import._supplier_name("BEIRUT CARGO CENTER SARL www.example.com Email: a@b.com\nBill To:\nBuyer Trading Co"), "BEIRUT CARGO CENTER SARL")
        self.assertEqual(pdf_import._supplier_name("plow oe. Tel: 01\nRef: 12\n" + "x\n" * 9), "")  # OCR noise is not a supplier
        pdf_import.set_known_parties(["Merit Shipping SAL", "Buyer Trading Co"])
        self.assertEqual(pdf_import._supplier_name("Client: Buyer Trading Co\nMERIT SHIPPING SAL invoice"), "Merit Shipping SAL")
        self.assertEqual(pdf_import._invoice_currency("Bank Account Currency: LBP\nTotal $ 10"), "USD")


class _Page:
    def __init__(self, text): self.text = text
    def extract_text(self, extraction_mode=None): return self.text


class PagesTest(unittest.TestCase):
    def setUp(self):
        pdf_import.set_own_company("Buyer Trading Co"); self.addCleanup(pdf_import.set_own_company)

    def reader(self, *texts):
        fake = types.ModuleType("pypdf"); fake.PdfReader = lambda _path: types.SimpleNamespace(pages=[_Page(t) for t in texts]); return fake

    def test_supporting_pages_stay_with_their_invoice(self):
        invoice = "SUPPLIER ONE SARL\nBill To: Buyer Trading Co\nInvoice: {n}\nDate: 02/02/2024\nSub Total: 100.00\nVAT: 11.00\nTotal: 111.00 USD"
        receipt = "PORT OF BEIRUT\nReceipt 553\nCustomer: Somebody Else\nDate: 01/02/2024\nTotal: 50.00 USD"
        with patch.dict(sys.modules, {"pypdf": self.reader(invoice.format(n="000335066"), receipt, invoice.format(n="000335165"))}):
            rows = pdf_import.read_invoice_pdf_pages(Path("bundle.pdf"))
        self.assertEqual([(r["invoice_number"], r["pages"], r["support_pages"], r["total"]) for r in rows],
                         [("000335066", [1, 2], [2], 111.0), ("000335165", [3], [], 111.0)])
        self.assertIn("supporting page", rows[0]["notes"])

    def test_progress_and_stop_while_reading_scans(self):
        seen = []; stop = types.SimpleNamespace(is_set=lambda: False)
        with patch.dict(sys.modules, {"pypdf": self.reader("", "")}), \
             patch("pdf_import._ocr_pdf_pages", side_effect=lambda path, pages, progress=None, cancel=None: [progress(i, len(pages)) or "" for i in range(len(pages))]):
            pdf_import.read_invoice_pdf_pages(Path("scan.pdf"), progress=lambda done, total, stage: seen.append((done, total, stage)), cancel=stop)
        self.assertEqual(seen, [(0, 2, "OCR"), (1, 2, "OCR")])

    def test_long_pdf_reads_only_the_first_invoice(self):
        first = "SUPPLIER ONE SARL\nBill To: Buyer Trading Co\nInvoice: 1001\nDate: 02/02/2024\nSub Total: 100.00\nVAT: 11.00\nTotal: 111.00 USD"
        later = "SUPPLIER TWO SARL\nInvoice: 2002\nDate: 05/03/2024\nTotal: 999.00 USD"
        with patch.dict(sys.modules, {"pypdf": self.reader(first, later, later, later, later)}), patch("pdf_import._ocr_pdf_pages") as ocr:
            result = pdf_import.read_invoice_pdf(Path("bundle.pdf"))
        ocr.assert_not_called()
        self.assertEqual((result["invoice_number"], result["total"]), ("1001", 111.0))
        self.assertIn("this PDF has 5 pages", result["notes"])


class RealPdfTest(unittest.TestCase):
    def test_columns_read_in_layout_order(self):
        from reportlab.pdfgen import canvas
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup); path = Path(folder.name) / "table.pdf"
        page = canvas.Canvas(str(path)); page.setFont("Helvetica", 9)
        page.drawString(40, 800, "ACME FOODS S.A.L."); page.drawString(300, 780, "Invoice # : AF-9"); page.drawString(40, 780, "13/10/2025")
        page.drawString(400, 760, "Currency:USD")
        for row, (total, price, qty, name) in enumerate((("1,529.00", "2.78", "550", "CHANNA DRIED"), ("568.00", "3.55", "160", "DATES PITTED"))):
            y = 730 - row * 14
            for x, value in ((40, total), (110, "0.00"), (160, "0.00 %"), (230, price), (280, qty), (330, "1KG"), (380, name)): page.drawString(x, y, value)
        page.drawString(40, 680, "2,097.00   Sub Total"); page.drawString(40, 666, "0.00   VAT"); page.drawString(40, 652, "Total: 2,097.00 USD")
        page.save()
        result = pdf_import.read_invoice_pdf(path)
        self.assertEqual([(i["description"], i["quantity"]) for i in result["items"]], [("CHANNA DRIED", 550.0), ("DATES PITTED", 160.0)])
        self.assertEqual((result["invoice_number"], result["currency"], result["total"]), ("AF-9", "USD", 2097.0))


class ProgressRunnerTest(unittest.TestCase):
    def test_without_a_window_the_work_runs_at_once(self):
        done = []
        run_with_progress(types.SimpleNamespace(), "PDF", lambda progress, cancel: (progress, cancel, 7), done.append)
        self.assertEqual(done, [(None, None, 7)])


if __name__ == "__main__":
    unittest.main()
