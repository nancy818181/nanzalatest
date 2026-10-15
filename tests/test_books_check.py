"""2.9.119: Books Health Check - consistent books pass; each kind of damage is found."""
import tests_setup  # noqa: F401
import sqlite3
import tempfile
import unittest

import books_check
from test_final_features import new_db


def status(check, name):
    return next(r for r in check["results"] if r["check"] == name)["status"]


class BooksCheckTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)
        db, user = self.db, self.user
        self.customer = db.save_party({"kind": "customer", "name": "Cedar Trading", "currency": "USD"}, user)
        self.sales = [db.create_manual_invoice({"invoice_number": f"SAL-2026-00000{n}", "invoice_date": f"1{n}-02-2026", "party_name": "Cedar Trading",
                                                "kind": "sale", "currency": "USD"}, [{"description": "Consulting", "quantity": 1, "unit_price": 100 * n}], user)
                      for n in (1, 2, 3)]
        db.create_manual_invoice({"invoice_number": "F-77", "invoice_date": "05-02-2026", "party_name": "Office Supplies", "kind": "purchase", "currency": "USD"},
                                 [{"description": "Paper", "quantity": 2, "unit_price": 30}], user)
        self.payment = db.add_payment({"kind": "customer_receipt", "payment_date": "20-02-2026", "party_id": self.customer["id"], "currency": "USD",
                                       "amount": "111", "cash_account": "531", "party_account": self.customer["account_number"]}, user)
        db.add_expense({"expense_date": "21-02-2026", "description": "Fuel", "currency": "USD", "with_vat_subtotal": "100", "vat": "11"}, user)

    def damage(self):
        """A raw connection, as a file changed outside the program (or written by an old version) would be."""
        connection = sqlite3.connect(self.db.path); self.addCleanup(connection.close)
        return connection

    def ids(self, value):
        return value["id"] if isinstance(value, dict) else int(value)

    def test_clean_books_pass(self):
        check = books_check.run(self.db, 2026)
        bad = [(r["check"], r["detail"]) for r in check["results"] if r["status"] != "OK" and r["check"] != "No lines on heading accounts"]
        self.assertEqual(bad, [])
        self.assertTrue(books_check.sections(check)[0]["rows"])

    def test_damage_is_found(self):
        first, second = (self.ids(i) for i in self.sales[:2])
        with self.damage() as connection:
            connection.execute("DELETE FROM journal_entries WHERE source_type='invoice' AND source_id=?", (first,))  # document without entry
            connection.execute("UPDATE invoices SET total='999' WHERE id=?", (second,))  # arithmetic broken
            connection.execute("DELETE FROM invoices WHERE invoice_number='SAL-2026-000003'")  # entry left behind + gap? (last one: no gap)
            connection.execute("UPDATE invoices SET invoice_number='SAL-2026-000005' WHERE id=?", (second,))  # gap 2..4
            entry = connection.execute("SELECT id FROM journal_entries WHERE source_type='payment'").fetchone()[0]
            connection.execute("UPDATE journal_lines SET debit='1' WHERE id=(SELECT MIN(id) FROM journal_lines WHERE entry_id=? AND CAST(debit AS REAL)>0)", (entry,))
        check = books_check.run(self.db, 2026)
        self.assertEqual(status(check, "Every document in the books"), "ERROR")
        self.assertEqual(status(check, "Invoices: subtotal + VAT = total"), "ERROR")
        self.assertEqual(status(check, "No entry without its document"), "ERROR")
        self.assertEqual(status(check, "Sales invoices numbered without gaps"), "WARNING")
        self.assertEqual(status(check, "Every entry balanced"), "ERROR")
        self.assertEqual(status(check, "Trial balance in each currency"), "ERROR")
        gaps = next(r for r in check["results"] if r["check"] == "Sales invoices numbered without gaps")["items"]
        self.assertEqual([g["number"] for g in gaps], ["SAL-2026-000002", "SAL-2026-000003", "SAL-2026-000004"])
        self.assertGreater(check["errors"], 3)

    def test_dates_and_duplicates(self):
        with self.damage() as connection:
            connection.execute("UPDATE invoices SET invoice_number='SAL-2026-000001' WHERE invoice_number='SAL-2026-000002'")
            connection.execute("UPDATE journal_entries SET entry_date='31-12-2025' WHERE id=(SELECT MIN(id) FROM journal_entries)")
        check = books_check.run(self.db, 2026)
        self.assertEqual(status(check, "No duplicate numbers"), "ERROR")
        self.assertEqual(status(check, "Entries inside the fiscal year"), "WARNING")


    def test_offline_start_writes_no_euro_rate_of_one(self):
        from unittest import mock
        with self.damage() as connection:  # what an offline start of an earlier version left
            connection.execute("INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_at) VALUES('03-03-2026','EUR','USD','1','x')")
        self.assertEqual(status(books_check.run(self.db, 2026), "EUR rates look right"), "WARNING")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.db.sync_historical_exchange_rates()
        with self.db.connect() as connection:
            ones = connection.execute("SELECT COUNT(*) FROM exchange_rates WHERE from_currency='EUR' AND to_currency='USD' AND CAST(rate AS REAL)=1").fetchone()[0]
            loaded = connection.execute("SELECT value FROM app_settings WHERE key='exchange_history_loaded_through'").fetchone()
        self.assertEqual(ones, 1)  # nothing new written offline (the old day stays until the rates can be downloaded)
        self.assertIsNone(loaded)  # tried again next time
        class Answer:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *_a): return False
            def read(self): return self.body
        import json
        def online(request, timeout=0):
            url = request.full_url
            if "latest" in url: return Answer(json.dumps({"rates": {"USD": 1.08}}).encode())
            return Answer(json.dumps({"rates": {"2026-03-03": {"USD": 1.09}}}).encode())
        with mock.patch("urllib.request.urlopen", side_effect=online):
            self.db.sync_historical_exchange_rates()
        with self.db.connect() as connection:
            rate = connection.execute("SELECT rate FROM exchange_rates WHERE rate_date='03-03-2026' AND from_currency='EUR' AND to_currency='USD'").fetchone()[0]
        self.assertEqual(float(rate), 1.09)  # repaired once online
        self.assertEqual(status(books_check.run(self.db, 2026), "EUR rates look right"), "OK")


if __name__ == "__main__":
    unittest.main()
