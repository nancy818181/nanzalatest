"""2.9.54: opening an entry from the General Journal, returns typed on the sales / purchase screens, Inventory
Analysis with any three dimensions, Excel files with formula-only and incomplete rows, cash on uploaded invoices."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import inventory
from database import Database


class _Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c.db"); self.db.initialize("secret"); self.user = 1
        self.item = inventory.save_item(self.db, {"name": "Panel", "unit": "sheet", "brand": "Fundermax", "category": "HPL"}, self.user)

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()

    def qty(self):
        return next(i for i in inventory.list_items(self.db) if i["id"] == self.item["id"])["quantity"]

    def purchase(self, number, quantity, **extra):
        invoice = {"invoice_number": number, "invoice_date": "05-03-2026", "party_name": "Supplier", "kind": "purchases", "currency": "USD", "status": "posted",
                   "source_file": "Purchase Invoice", "expense_account": "601100000", "vat_account": "44210"}
        invoice.update(extra)
        return self.db.create_manual_invoice(invoice, [{"item_code": self.item["sku"], "description": "Panel", "quantity": quantity, "unit_price": 5, "vat_rate": 11, "warehouse": "MAIN"}], self.user)


class ReturnsTypedDirectlyTest(_Base):
    def test_purchase_return_sends_goods_back_and_debits_the_supplier(self):
        self.purchase("P1", 10)
        returned = self.purchase("PR1", 3, invoice_date="06-03-2026", doc_subtype="credit_note", is_return=True,
                                 supplier_side="D", vat_side="C", expense_side="C", expense_no_vat_side="C")
        self.assertEqual(self.qty(), 7)
        with self.db.connect() as db:
            lines = {r["code"]: (Decimal(r["debit"]), Decimal(r["credit"])) for r in db.execute("""SELECT a.code,l.debit,l.credit FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id
                JOIN accounts a ON a.id=l.account_id WHERE e.source_type='invoice' AND e.source_id=?""", (returned,))}
        self.assertEqual(lines["601100000"], (Decimal("0"), Decimal("15.0"))); self.assertEqual(sum(d for d, _c in lines.values()), Decimal("16.65"))
        self.assertEqual(self.db.unbalanced_entries(), [])

    def test_sales_return_brings_goods_back(self):
        self.purchase("P1", 10)
        sale = {"invoice_number": "", "invoice_date": "07-03-2026", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted", "source_file": "Sales Invoice",
                "supplier_account": "411100001", "vat_account": "4427", "expense_account": "701100001"}
        line = [{"item_code": self.item["sku"], "description": "Panel", "quantity": 4, "unit_price": 9, "vat_rate": 11, "warehouse": "MAIN"}]
        self.db.create_manual_invoice(sale, line, self.user); self.assertEqual(self.qty(), 6)
        ret = dict(sale, expense_account="709000001", doc_subtype="credit_note", is_return=True, supplier_side="C - Credit", vat_side="D - Debit", expense_side="D - Debit")
        self.db.create_manual_invoice(ret, [dict(line[0], quantity=1)], self.user)
        self.assertEqual(self.qty(), 7); self.assertEqual(self.db.unbalanced_entries(), [])


class AnalysisThreeDimensionsTest(_Base):
    def test_rows_columns_and_layers_of_any_kind(self):
        inventory.save_warehouse(self.db, {"code": "W2", "name": "Second"}, self.user)
        other = inventory.save_item(self.db, {"name": "Profile", "unit": "m", "brand": "Alucobond", "category": "ALU"}, self.user)
        for sku, code, qty in ((self.item["sku"], "MAIN", 5), (self.item["sku"], "W2", 2), (other["sku"], "MAIN", 3)):
            inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-01", "warehouse_id": code}, [{"sku": sku, "quantity": qty, "unit_cost": 10}], self.user)
        result = inventory.build_report(self.db, "analysis3d", {"date_to": "31-03-2026", "rows": "brand", "columns": "warehouse", "layers": "category", "measure": "quantity"})
        headings = [s["heading"] for s in result["sections"]]
        self.assertTrue(headings[0].startswith("Category x Warehouse")); self.assertTrue(any(h.startswith("Category: HPL") for h in headings))
        total = result["sections"][-1]
        self.assertEqual(total["headers"], ["Brand / Warehouse", "MAIN", "W2", "Total"])
        self.assertEqual([r[0] for r in total["rows"]], ["Alucobond", "Fundermax", "TOTAL"]); self.assertEqual(total["rows"][-1][-1], 10)
        self.assertTrue(total["chart"]["series"])
        monthly = inventory.build_report(self.db, "analysis3d", {"date_from": "01-01-2026", "date_to": "31-03-2026", "rows": "item", "columns": "month", "measure": "value"})
        self.assertIn("2026-03", monthly["sections"][0]["headers"])
        with self.assertRaises(ValueError):
            inventory.build_report(self.db, "analysis3d", {"date_to": "31-03-2026", "rows": "brand", "columns": "brand"})


class ExcelRowsTest(unittest.TestCase):
    def test_formula_only_rows_are_skipped_and_incomplete_rows_flagged(self):
        from openpyxl import Workbook
        from importer import read_invoices
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.xlsx"; wb = Workbook(); ws = wb.active
            ws.append(["Date", "Supplier Name", "Total Before VAT", "VAT", "Total After VAT"])
            ws.append(["02-02-2024", "BEIRUT CARGO", 215, "=C2*11%", "=C2+D2"])
            ws.append([None, None, None, "=C3*11%", "=C3+D3"])                       # formulas copied down only
            ws.append(["08-04-2024", None, 500, 55, 555])                              # no supplier
            ws.append(["02-05-20204", "GENERAL PROMOTION", 100, 11, 111])             # typo in the year
            ws.append([45330, "SERIAL DATE SAL", 10, 1.1, 11.1])                       # Excel date number
            wb.save(path)
            rows = read_invoices(path, allowed_currencies=["USD"])
        self.assertEqual([r["source_row"] for r in rows], [2, 4, 5, 6])
        self.assertIn("open the file in Excel", rows[0]["problem"]); self.assertIn("name missing", rows[1]["problem"]); self.assertIn("date not valid", rows[2]["problem"])
        self.assertEqual(rows[3]["invoice_date"], "2024-02-08"); self.assertNotIn("problem", rows[3])


class CurrencyNotEnabledTest(unittest.TestCase):
    def test_a_currency_the_company_does_not_use_never_stops_the_import(self):
        from openpyxl import Workbook
        from importer import read_invoices
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.xlsx"; wb = Workbook(); ws = wb.active
            ws.append(["Date", "Supplier Name", "Total Before VAT", "VAT", "Total After VAT"])
            ws.append(["02-02-2024", "EURO SUPPLIER", 100, 11, 111])
            for cell in ws[2][2:]: cell.number_format = '€#,##0.00'
            wb.save(path)
            rows = read_invoices(path, allowed_currencies=["USD", "LBP"])   # used to fail with KeyError: 'EUR'
        self.assertEqual((rows[0]["currency"], rows[0]["currency_issue"]), ("USD", "unsupported:EUR"))


class ScreenFixesTest(unittest.TestCase):
    def test_inner_screen_frame_finds_its_tab(self):
        try:
            import tkinter as tk
            import desktop
        except ImportError as exc: self.skipTest(str(exc))
        try: root = tk.Tk()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            root.withdraw(); page = tk.Frame(root); canvas = tk.Canvas(page); inner = tk.Frame(canvas)
            app = SimpleNamespace(main_tab_pages=[page])
            self.assertIs(desktop.SaberApp.main_tab_container(app, inner), page)
            self.assertIs(desktop.SaberApp.main_tab_container(app, page), page)
        finally: root.destroy()

    def test_documents_offered_on_the_screens(self):
        import desktop_purchases
        self.assertEqual(desktop_purchases.PURCHASE_DOCUMENTS, ("Invoice", "Return", "Credit Note", "Debit Note"))
        here = Path(__file__).resolve().parent  # 2.9.94: the sales invoice screen moved to desktop_sales_invoice.py
        source = "".join((here / name).read_text(encoding="utf-8") for name in ("desktop_invoices.py", "desktop_sales_invoice.py"))
        self.assertIn('values=["Invoice","Return","Credit Note","Debit Note"]', source)


if __name__ == "__main__":
    unittest.main()
