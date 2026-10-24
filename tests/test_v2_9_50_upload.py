"""PDF purchase line handling; OCR output stays in review until explicitly saved."""
import tempfile
import secrets
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
        self.test_password = secrets.token_urlsafe(24)
        self.db = Database(Path(self.temp.name) / "u.db"); self.db.initialize(self.test_password)
        self.user = self.db.user_for_token(self.db.login("admin", self.test_password)["token"])["id"]
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
    def test_ocr_callback_never_saves_automatically(self):
        import desktop_purchases
        from unittest.mock import Mock, patch
        label=Mock(); save=Mock()
        app=SimpleNamespace(purchase_form={"id":None,"pdf_label":label},save_purchase=save)
        desktop_purchases.PurchasesMixin.auto_save_purchase_upload(app)
        save.assert_not_called()
        self.assertIn("review",label.config.call_args.kwargs["text"].casefold())
        with patch.object(desktop_purchases.messagebox,"showwarning") as warning:
            desktop_purchases.PurchasesMixin.save_purchase(app,auto=True)
        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
