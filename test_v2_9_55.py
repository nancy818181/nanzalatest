"""2.9.55: the logo, repeated Excel rows without invoice numbers, purchases paid on the spot."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database

HERE = Path(__file__).resolve().parent


class LogoTest(unittest.TestCase):
    def test_logo_is_a_real_png(self):
        data = (HERE / "Assets" / "Saber_for_Audit_logo.png").read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")


class IconTest(unittest.TestCase):
    def test_icon_is_built_into_the_programs_and_the_installer(self):
        """2.9.111: the product is named Nanza - its icon on the programs, the installer and the shortcuts."""
        data = (HERE / "Assets" / "nanza.ico").read_bytes()
        self.assertEqual(data[:4], b"\x00\x00\x01\x00")                    # Windows icon
        self.assertGreaterEqual(int.from_bytes(data[4:6], "little"), 5)        # several sizes (16 to 256)
        installer = (HERE / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("SetupIconFile=Assets\\nanza.ico", installer)
        self.assertIn('Source: "Assets\\nanza.ico"; DestDir: "{app}"', installer)
        self.assertEqual(installer.count('IconFilename: "{app}\\nanza.ico"'), 2)
        self.assertIn("AppId={{4C848D44-EF69-47C0-86F1-5A5AA3C34E8D}", installer)       # same product: updates keep working
        workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("--icon Assets/nanza.ico"), 2); self.assertIn('--add-data "Assets/nanza.ico;assets"', workflow)


class SharpLogoTest(unittest.TestCase):
    def test_header_mark_and_login_logo_are_resized_cleanly(self):
        import brand_images
        mark = brand_images.header_mark(HERE / "Assets" / "Saber_for_Audit_logo.png", 46)
        self.assertEqual(mark.size[1], 46); self.assertLess(mark.size[0], 80)            # the monogram only, not the whole logo
        self.assertEqual(mark.getpixel((0, 0))[3], 0)                                     # transparent corner on the navy bar
        logo = brand_images.full_logo(HERE / "Assets" / "Saber_for_Audit_logo.png", 250)
        self.assertEqual(logo.size[0], 250)
        mark = brand_images.full_logo(HERE / "Assets" / "nanza_icon.png", 44)              # 2.9.110: the header mark
        self.assertEqual(mark.size, (44, 44)); self.assertEqual(mark.getpixel((0, 0))[3], 0)


class RepeatsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c.db"); self.db.initialize("secret")

    def tearDown(self):
        self.db.release(); self.temp.cleanup()

    def test_same_supplier_date_and_total_is_found_when_there_is_no_number(self):
        self.db.import_invoice({"invoice_number": "3", "invoice_date": "2024-02-08", "party_name": "BEIRUT CARGO CENTER SARL", "kind": "purchases",
                                "currency": "USD", "subtotal": 2038, "vat": 127.93, "total": 2165.93}, 1)
        found = self.db.find_invoice_duplicates([
            {"kind": "purchases", "party_name": "beirut cargo center sarl", "invoice_number": "10", "by_amount": True, "invoice_date": "08-02-2024", "total": 2165.93},
            {"kind": "purchases", "party_name": "BEIRUT CARGO CENTER SARL", "invoice_number": "11", "by_amount": True, "invoice_date": "09-02-2024", "total": 2165.93},
            {"kind": "purchases", "party_name": "BEIRUT CARGO CENTER SARL", "invoice_number": "10"}])
        self.assertEqual([len(f) for f in found], [1, 0, 0])

    def test_excel_rows_know_when_the_number_is_the_row(self):
        from openpyxl import Workbook
        from importer import read_invoices
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.xlsx"; wb = Workbook(); ws = wb.active
            ws.append(["Date", "Supplier Name", "Total Before VAT", "VAT", "Total After VAT"])
            for _ in range(2): ws.append(["08-02-2024", "BEIRUT CARGO", 2038, 127.93, 2165.93])
            wb.save(path)
            rows = read_invoices(path, allowed_currencies=["USD"])
        self.assertTrue(all(r["number_from_row"] for r in rows))

    def test_purchase_paid_in_full_goes_to_cash(self):
        invoice_id = self.db.create_manual_invoice({"invoice_number": "P9", "invoice_date": "05-03-2026", "party_name": "Supplier", "kind": "purchases", "currency": "USD",
                                                    "status": "posted", "expense_account": "601100000", "vat_account": "44210", "payment_method": "Cash", "amount_paid": "full"},
                                                   [{"description": "x", "quantity": 3, "unit_price": 3.33, "vat_rate": 11}], 1)
        with self.db.connect() as db:
            lines = [(r["code"], Decimal(r["debit"]), Decimal(r["credit"])) for r in db.execute("""SELECT a.code,l.debit,l.credit FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id
                JOIN accounts a ON a.id=l.account_id WHERE e.source_type='invoice_payment' AND e.source_id=? ORDER BY l.id""", (invoice_id,))]
        self.assertEqual(lines[1][0], "531"); self.assertEqual(lines[1][2], Decimal(str(self.db.get_invoice(invoice_id)["total"])))


if __name__ == "__main__":
    unittest.main()
