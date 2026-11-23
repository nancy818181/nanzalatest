import tempfile
import unittest

import tests_setup
from test_atomic_saving import INVOICE
from test_final_features import new_db


class DocumentOrgTest(unittest.TestCase):
    def test_existing_and_new_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            db, user = new_db(folder)
            line = [{"description": "Paper", "quantity": 1, "unit_price": 20}]
            invoice = db.create_manual_invoice(INVOICE, line, user)
            expense = {"expense_date": "21-02-2026", "description": "Fuel", "currency": "USD",
                       "with_vat_subtotal": "100", "vat": "11"}
            db.add_expense(expense, user)
            with db.connect() as conn:
                conn.execute("ALTER TABLE invoices DROP COLUMN org")
                conn.execute("ALTER TABLE expenses DROP COLUMN org")
            db.initialize_if_needed("Synthetic-test-account")
            self.assertEqual(db.get_invoice(invoice)["org"], "Yes")
            self.assertEqual(db.list_expenses()[0]["org"], "Yes")
            other = db.create_manual_invoice(dict(INVOICE, org="No", invoice_number="F-2"), line, user)
            self.assertEqual(db.invoice_detail(other)["invoice"]["org"], "No")
            self.assertEqual(db.duplicate_invoice(other, user)["org"], "No")
            db.add_expense(dict(expense, org="No"), user)
            self.assertEqual([r["org"] for r in db.list_expenses()], ["No", "Yes"])
