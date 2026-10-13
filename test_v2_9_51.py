"""2.9.51: no invoice saved twice by an upload, the same item written differently is not created twice,
reports read every journal line (no 5,000 / 20,000 / 50,000 line limits), build checks the version."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import inventory
from database import Database

HERE = Path(__file__).resolve().parent


class _Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c.db"); self.db.initialize("secret")
        self.user = self.db.user_for_token(self.db.login("admin", "secret")["token"])["id"]

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()


class DuplicateInvoiceTest(_Base):
    def test_same_party_and_number_is_found_whatever_the_spelling(self):
        self.db.import_invoice({"invoice_number": "INV-0045", "invoice_date": "05-03-2026", "party_name": "Panel Trading", "kind": "purchases",
                                "currency": "USD", "subtotal": 100, "vat": 11, "total": 111}, self.user)
        found = self.db.find_invoice_duplicates([
            {"kind": "purchases", "party_name": "panel trading ", "invoice_number": "inv 45"},          # same invoice
            {"kind": "purchases", "party_name": "Panel Trading", "invoice_number": "INV-0046"},        # another number
            {"kind": "purchases", "party_name": "Other Supplier", "invoice_number": "INV-0045"},       # another supplier
            {"kind": "sales", "party_name": "Panel Trading", "invoice_number": "INV-0045"},            # a sale, not a purchase
            {"kind": "purchases", "party_name": "Panel Trading", "invoice_number": "INV-0045", "doc_subtype": "credit_note"},
            {"kind": "purchases", "party_name": "Panel Trading", "invoice_number": ""}])
        self.assertEqual([len(f) for f in found], [1, 0, 0, 0, 0, 0])
        self.assertEqual(found[0][0]["total"], 111)

    def test_cancelled_invoice_is_not_a_duplicate(self):
        invoice_id = self.db.import_invoice({"invoice_number": "A1", "invoice_date": "05-03-2026", "party_name": "S", "kind": "purchases",
                                             "currency": "USD", "subtotal": 100, "vat": 0, "total": 100}, self.user)
        self.db.cancel_invoice(invoice_id, "wrong", self.user)
        self.assertEqual(self.db.find_invoice_duplicates([{"kind": "purchases", "party_name": "S", "invoice_number": "A1"}]), [[]])

    def test_import_skips_rows_already_saved(self):
        import desktop_stage3
        rows = [{"invoice_number": "X1", "party_name": "S", "entry_type": "Purchases", "line": "001"}, {"invoice_number": "X2", "party_name": "S", "entry_type": "Purchases", "line": "002"}]
        app = SimpleNamespace(import_mode="pdf", client=SimpleNamespace(invoice_duplicates=lambda items: [[{"id": 9, "invoice_date": "01-03-2026", "total": 5}], []]))
        found = desktop_stage3.Stage3Mixin.import_duplicates(app, rows)
        self.assertEqual([r["invoice_number"] for r, _m in found.values()], ["X1"])
        app.client = SimpleNamespace(invoice_duplicates=lambda items: (_ for _ in ()).throw(RuntimeError("offline")))
        self.assertEqual(desktop_stage3.Stage3Mixin.import_duplicates(app, rows), {})   # never blocks when the check cannot run


class ItemMatchingTest(_Base):
    def test_same_name_written_differently_is_the_same_item(self):
        first = inventory.find_or_create_item(self.db, "HPL Panel 4mm White", "sheet", None, self.user)
        again = inventory.find_or_create_item(self.db, "hpl panel - 4 MM white", "sheet", None, self.user)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(sum(1 for i in inventory.list_items(self.db) if "anel" in i["name"]), 1)

    def test_close_names_are_offered_not_merged(self):
        inventory.find_or_create_item(self.db, "HPL Panel 4mm White", "sheet", None, self.user)
        inventory.find_or_create_item(self.db, "Aluminium Profile", "m", None, self.user)
        close = inventory.similar_items(self.db, "HPL Panel 4mm Wht")
        self.assertEqual([c["name"] for c in close], ["HPL Panel 4mm White"]); self.assertLess(close[0]["score"], 1)
        self.assertEqual(inventory.similar_items(self.db, "Office chair"), [])
        self.assertEqual(inventory.similar_items(self.db, "hpl-panel 4mm white")[0]["score"], 1.0)

    def test_resolver_asks_once_and_remembers(self):
        try: import tkinter as tk
        except ImportError as exc: self.skipTest(str(exc))
        import desktop_stage3_common as common
        from unittest.mock import patch
        try: root = tk.Tk()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            root.withdraw()
            existing = {"id": 1, "sku": "ITM-1", "name": "HPL Panel 4mm White", "unit": "sheet", "score": 0.9}
            calls = []
            root.client = SimpleNamespace(similar_items=lambda name: [existing],
                                          find_or_create_item=lambda *a: calls.append(a) or {"sku": "NEW", "name": a[0], "unit": a[1]})
            with patch.object(common, "choose_similar_item", return_value=existing) as asked:
                self.assertEqual(common.resolve_item(root, "HPL Panel 4mm Wht")["sku"], "ITM-1")
                self.assertEqual(common.resolve_item(root, "hpl panel 4mm wht")["sku"], "ITM-1")
                self.assertEqual(asked.call_count, 1); self.assertEqual(calls, [])
            with patch.object(common, "choose_similar_item", return_value=None):
                self.assertEqual(common.resolve_item(root, "Something else close")["sku"], "NEW")
        finally: root.destroy()


class NoLineLimitTest(_Base):
    def test_reports_read_every_line(self):
        count = 6000
        with self.db.connect() as db:
            cash = db.execute("SELECT id FROM accounts WHERE code='531'").fetchone()[0]
            sales = self.db._account_id(db, "701100001")
            for n in range(count):
                entry = db.execute("INSERT INTO journal_entries(entry_number,entry_date,description,source_type,currency,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                                   (f"JV-{n}", "2026-03-01", "cash sale", "journal_voucher", "USD", self.user, "2026-03-01")).lastrowid
                db.execute("INSERT INTO journal_lines(entry_id,account_id,debit,credit) VALUES(?,?,?,?)", (entry, cash, "10", "0"))
                db.execute("INSERT INTO journal_lines(entry_id,account_id,debit,credit) VALUES(?,?,?,?)", (entry, sales, "0", "10"))
        self.assertEqual(len(self.db.journal()), count * 2)
        flow = self.db.cash_flow("2026-01-01", "2026-12-31", "USD")
        self.assertEqual(sum(r["inflow"] for r in flow), count * 10)
        ledger = self.db.general_ledger("531", "2026-01-01", "2026-12-31", "USD")
        items = ledger["items"] if isinstance(ledger, dict) else ledger
        self.assertEqual(round(items[-1]["balance"]), count * 10)
        self.assertEqual([r["entry_number"] for r in self.db.journal(entry_number="JV-5999")], ["JV-5999", "JV-5999"])


class BuildCheckTest(unittest.TestCase):
    def test_workflow_stops_on_a_nested_upload_or_a_version_mismatch(self):
        workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn("Check repository layout and version", workflow)
        self.assertIn("SaberAccountingSetup-${{ steps.version.outputs.version }}", workflow)


if __name__ == "__main__":
    unittest.main()
