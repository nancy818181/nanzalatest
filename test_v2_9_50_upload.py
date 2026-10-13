"""2.9.50: an uploaded purchase invoice is saved and posted at once; items it lists are created and received in stock."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import inventory
from database import Database


class _Client:
    def __init__(self, db, user): self.db = db; self.user = user
    def find_or_create_item(self, name, unit="unit", sku=None, supplier_id=None): return inventory.find_or_create_item(self.db, name, unit, sku, self.user, supplier_id)
    def create_manual_invoice(self, invoice, items): return {"invoice_id": self.db.create_manual_invoice(invoice, items, self.user)}


class ImportPdfItemsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "u.db"); self.db.initialize("secret")
        self.user = self.db.user_for_token(self.db.login("admin", "secret")["token"])["id"]
        import desktop_stage3
        self.mixin = desktop_stage3.Stage3Mixin
        self.app = SimpleNamespace(client=_Client(self.db, self.user), import_mode="pdf")

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()

    def row(self, **extra):
        r = {"invoice_number": "F-77", "invoice_date": "05-03-2026", "party_name": "Panel Trading", "currency": "USD", "subtotal": 500.0, "vat": 55.0, "total": 555.0,
             "entry_type": "Purchases", "expense_account": "601100000", "vat_account": "442660000", "supplier_account": "", "source": "f.pdf - Page 1",
             "_items": [{"description": "Brand New Panel", "quantity": 4, "unit_price": 100, "total": 400, "unit": "unit"},
                        {"description": "Edge Tape", "quantity": 10, "unit_price": 10, "total": 100, "unit": "m"}]}
        r.update(extra); return r

    def test_new_items_are_created_and_received_with_the_entry(self):
        invoice_id = self.mixin._post_pdf_purchase_with_items(self.app, self.row())
        items = {i["name"]: i for i in inventory.list_items(self.db)}
        self.assertEqual((items["Brand New Panel"]["quantity"], items["Edge Tape"]["quantity"]), (4, 10))
        with self.db.connect() as db:
            entry = db.execute("SELECT COUNT(*) FROM journal_entries WHERE source_type='invoice' AND source_id=?", (invoice_id,)).fetchone()[0]
        self.assertEqual(entry, 1); self.assertEqual(self.db.unbalanced_entries(), [])
        self.assertEqual(self.db.get_invoice(invoice_id)["status"], "posted")
        # the same item on the next invoice is matched, not created twice
        self.mixin._post_pdf_purchase_with_items(self.app, self.row(invoice_number="F-78"))
        self.assertEqual(sum(1 for i in inventory.list_items(self.db) if i["name"] == "Brand New Panel"), 1)

    def test_items_not_matching_the_amount_fall_back_to_the_amount_only(self):
        self.assertIsNone(self.mixin._post_pdf_purchase_with_items(self.app, self.row(subtotal=900.0, total=999.0, vat=99.0)))

    def test_only_complete_rows_are_saved_without_questions(self):
        good = self.row(); bad = self.row(invoice_number="", vat=None); asset = self.row(entry_type="Assets")
        ready, waiting = self.mixin.split_ready_import_rows(self.app, [good, bad, asset])
        self.assertEqual(ready, [good]); self.assertEqual(len(waiting), 2)
        self.assertIn("invoice number", bad["notes"]); self.assertIn("account review", asset["notes"])


class PurchaseUploadTest(unittest.TestCase):
    def test_missing_fields_stop_the_automatic_save(self):
        try: import tkinter as tk
        except ImportError as exc: self.skipTest(str(exc))
        import desktop_purchases
        try: root = tk.Tk()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            root.withdraw()
            names = ("supplier", "number", "date", "taxable", "exempt", "vat", "type")
            v = {k: tk.StringVar(master=root) for k in names}
            v["supplier"].set("Panel Trading"); v["date"].set("05-03-2026"); v["taxable"].set("500"); v["vat"].set("55"); v["type"].set("Purchases")
            label = tk.Label(root)
            app = SimpleNamespace(purchase_form={"vars": v, "id": None, "pdf_suggested_type": "", "pdf_label": label}, saved=[])
            app.purchase_upload_missing = lambda: desktop_purchases.PurchasesMixin.purchase_upload_missing(app)
            app.save_purchase = lambda auto=False: app.saved.append(auto)
            desktop_purchases.PurchasesMixin.auto_save_purchase_upload(app)
            self.assertEqual(app.saved, []); self.assertIn("invoice number", label.cget("text"))
            v["number"].set("F-1"); desktop_purchases.PurchasesMixin.auto_save_purchase_upload(app)
            self.assertEqual(app.saved, [True])
            app.purchase_form["pdf_suggested_type"] = "Expenses"; app.saved.clear()
            desktop_purchases.PurchasesMixin.auto_save_purchase_upload(app)
            self.assertEqual(app.saved, []); self.assertIn("Expenses", label.cget("text"))
        finally: root.destroy()


if __name__ == "__main__":
    unittest.main()
