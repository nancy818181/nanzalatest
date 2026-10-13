"""2.9.47: invoices paid on the spot get their settlement entry (chosen cash / bank account), account editing,
editing entries from the journal and reports."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class CashSettlementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c.db"); self.db.initialize("secret")
        self.user = self.db.user_for_token(self.db.login("admin", "secret")["token"])["id"]

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()

    def invoice(self, number, kind="sales", method="Cash", paid="111", **extra):
        item = {"invoice_number": number, "invoice_date": "05-03-2026", "party_name": "Client A" if kind == "sales" else "Supplier B", "kind": kind,
                "currency": "USD", "status": "posted", "payment_method": method, "amount_paid": paid,
                "supplier_account": "411100001" if kind == "sales" else "401100001", "vat_account": "4427" if kind == "sales" else "442660000",
                "expense_account": "711000001" if kind == "sales" else "601100000"}
        item.update(extra)
        return self.db.create_manual_invoice(item, [{"description": "Goods", "quantity": 1, "unit_price": 100, "vat_rate": 11}], self.user)

    def entry(self, invoice_id):
        with self.db.connect() as db:
            rows = db.execute("""SELECT e.entry_number,a.code,l.debit,l.credit FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id
                JOIN accounts a ON a.id=l.account_id WHERE e.source_type='invoice_payment' AND e.source_id=? ORDER BY l.id""", (invoice_id,)).fetchall()
        return [(r["code"], Decimal(r["debit"]), Decimal(r["credit"])) for r in rows], (rows[0]["entry_number"] if rows else None)

    def test_cash_sale_debits_cash_and_credits_the_customer(self):
        invoice_id = self.invoice("S-1")
        lines, number = self.entry(invoice_id)
        self.assertEqual(number, f"PINV-{invoice_id}")
        self.assertEqual(lines, [("531", Decimal("111"), Decimal("0")), ("411100001", Decimal("0"), Decimal("111"))])
        self.assertEqual(self.db.unbalanced_entries(), [])

    def test_purchase_paid_by_bank_into_the_chosen_account(self):
        invoice_id = self.invoice("P-1", kind="purchases", method="Bank Transfer", paid="50", cash_account="5121 - Bank Audi")
        lines, _ = self.entry(invoice_id)
        self.assertEqual(lines, [("401100001", Decimal("50"), Decimal("0")), ("5121", Decimal("0"), Decimal("50"))])
        self.assertEqual(self.db.get_invoice(invoice_id)["payment_account"], "5121")

    def test_on_account_or_unpaid_has_no_payment_entry(self):
        self.assertEqual(self.entry(self.invoice("S-2", method="On Account (Not Cash)"))[0], [])
        self.assertEqual(self.entry(self.invoice("S-3", paid="0"))[0], [])

    def test_editing_cancelling_and_deleting_follow_the_invoice(self):
        invoice_id = self.invoice("S-4", paid="60", cash_account="5122")
        row = self.db.get_invoice(invoice_id)
        update = {k: row[k] for k in ("invoice_number", "invoice_date", "party_name", "currency", "supplier_account", "vat_account", "expense_account",
                                      "deductible_subtotal", "non_deductible_subtotal", "vat", "total", "status")}
        update.update(kind="sales", amount_paid="111", payment_method="Cash")
        self.db.update_invoice(invoice_id, update, self.user)
        self.assertEqual(self.entry(invoice_id)[0][0], ("5122", Decimal("111"), Decimal("0")))  # stored account kept
        update.update(payment_method="On Account (Not Cash)", amount_paid="0")
        self.db.update_invoice(invoice_id, update, self.user)
        self.assertEqual(self.entry(invoice_id)[0], [])
        other = self.invoice("S-5")
        self.db.cancel_invoice(other, "wrong customer", self.user)
        self.assertEqual(self.entry(other)[0], [])
        third = self.invoice("S-6")
        self.db.delete_invoice(third, self.user)
        with self.db.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM journal_entries WHERE source_type='invoice_payment' AND source_id=?", (third,)).fetchone())

    def test_invoices_saved_before_get_their_missing_entry_once(self):
        old = self.invoice("OLD-1"); locked = self.invoice("OLD-2", invoice_date="05-01-2026")
        with self.db.connect() as db:  # as saved by 2.9.46: paid, but no settlement entry
            db.execute("DELETE FROM journal_entries WHERE source_type='invoice_payment'")
        self.db.set_books_lock("31-01-2026", self.user)
        result = self.db.create_missing_invoice_payments(self.user)
        self.assertEqual(result["created"], ["OLD-1"]); self.assertEqual([s["invoice_number"] for s in result["skipped"]], ["OLD-2"])
        self.assertEqual(self.entry(old)[0][0], ("531", Decimal("111"), Decimal("0")))
        self.assertEqual(self.db.create_missing_invoice_payments(self.user)["created"], [])  # nothing done twice
        self.assertIsNotNone(locked)

    def test_customer_balance_is_settled(self):
        self.invoice("S-7")
        with self.db.connect() as db:
            balance = db.execute("""SELECT SUM(CAST(l.debit AS REAL))-SUM(CAST(l.credit AS REAL)) FROM journal_lines l JOIN accounts a ON a.id=l.account_id
                WHERE a.code='411100001'""").fetchone()[0]
        self.assertEqual(round(balance, 2), 0.0)


class AccountEditTest(unittest.TestCase):
    def test_names_and_type_saved_and_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret")
            saved = db.rename_account("531", "Cash on hand", 1, "Caisse", "الصندوق", "asset")
            self.assertEqual((saved["name_en"], saved["name_fr"], saved["name_ar"], saved["type"]), ("Cash on hand", "Caisse", "الصندوق", "asset"))
            self.assertEqual(db.rename_account("531", "Cash", 1)["name_fr"], "Caisse")  # only the name changed
            with self.assertRaises(ValueError): db.rename_account("531", "", 1)
            with self.assertRaises(ValueError): db.rename_account("531", "Cash", 1, account_type="weird")
            with self.assertRaises(KeyError): db.rename_account("99999999", "X", 1)
            db.release()


class ScreensTest(unittest.TestCase):
    def test_account_edit_window_and_entry_navigation(self):
        try:
            import tkinter as tk
            import desktop
        except ImportError as exc: self.skipTest(f"tkinter not available: {exc}")
        from unittest.mock import MagicMock, patch
        class App(tk.Tk):
            pass
        try: root = App()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            root.withdraw(); app = root
            app.client = MagicMock(); app.client.update_account.return_value = {"code": "531"}
            app.load_accounts = MagicMock()
            tree = tk.ttk.Treeview(root, columns=("a", "b", "c", "d", "e", "f"), show="headings"); tree.insert("", "end", iid="x", values=("531", "53", "Cash", "", "", "asset"))
            tree.selection_set("x"); app.accounts_tree = tree
            with patch("desktop_settings.messagebox"):
                window = desktop.SaberApp.edit_selected_account(app)
                entries = [w for w in window.winfo_children() if isinstance(w, tk.Entry)]
                entries[0].delete(0, "end"); entries[0].insert(0, "Main cash")
                next(w for w in window.winfo_children()[-1].winfo_children() if w.cget("text") == "Save").invoke()
            code, payload = app.client.update_account.call_args[0]
            self.assertEqual((code, payload["name_en"], payload["type"]), ("531", "Main cash", "asset"))
            # Journal "Edit Selected Entry" opens the entry's own screen.
            app2 = MagicMock(); jt = tk.ttk.Treeview(root, columns=("n",), show="headings"); jt.insert("", "end", iid="1", values=("JV-1",)); jt.selection_set("1")
            app2.journal_tree = jt; app2.client.journal.return_value = [{"entry_number": "JV-1", "source_type": "journal_voucher", "source_id": None, "entry_id": 7}]
            desktop.SaberApp.edit_journal_selection(app2)
            app2.open_entry_source.assert_called_once()
        finally: root.destroy()


if __name__ == "__main__":
    unittest.main()
