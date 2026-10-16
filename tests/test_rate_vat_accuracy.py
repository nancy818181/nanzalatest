"""Regression coverage for dated FX and incomplete VAT returns (2.9.123)."""
import tests_setup  # noqa: F401
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

import vat_return
from db_rates import RatesStore
from test_final_features import new_db


class DatedRateTest(unittest.TestCase):
    def setUp(self):
        self.store = RatesStore()
        self.table = {}
        self.store._rate_table = lambda: self.table
        self.store._rate_cache = lambda: {}

    def rate(self, source, target, day, value):
        self.table[source, target] = ([day], [(day, 1, value)])

    def convert(self, source, target, day="15-03-2026"):
        return self.store._converted_amount(100, source, target, day)

    def test_missing_and_future_eur_rates_raise_in_both_directions(self):
        for future in (False, True):
            self.table.clear()
            if future: self.rate("EUR", "USD", "20260320", "1.2")
            for source, target in (("EUR", "USD"), ("USD", "EUR"), ("EUR", "LBP"), ("LBP", "EUR")):
                with self.subTest(future=future, source=source, target=target):
                    with self.assertRaisesRegex(ValueError, "No exchange rate"):
                        self.convert(source, target)

    def test_dated_direct_inverse_and_lbp_cross_rates(self):
        for source, target, value in (("EUR", "USD", "1.25"), ("USD", "EUR", "0.8"), ("EUR", "LBP", "111875"), ("LBP", "EUR", str(Decimal(1)/Decimal(111875)))):
            with self.subTest(source=source, target=target):
                self.table.clear(); self.rate(source, target, "20260315", value)
                self.assertAlmostEqual(self.convert("EUR", "USD"), Decimal("125"), places=20)
                self.assertAlmostEqual(self.convert("USD", "EUR"), Decimal("80"), places=20)

    def test_invalid_saved_rates_fail_instead_of_poisoning_calculations(self):
        for value in ("NaN", "Infinity", "0", "-1"):
            with self.subTest(value=value):
                self.rate("EUR", "USD", "20260315", value)
                with self.assertRaisesRegex(ValueError, "Invalid exchange rate"):
                    self.convert("EUR", "USD")

    def test_non_eur_conversions_do_not_need_eur(self):
        self.assertAlmostEqual(self.convert("USD", "LBP"), Decimal("8950000"), places=15)
        self.assertEqual(self.convert("EUR", "EUR"), Decimal("100"))


class VATSaveGuardTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)
        self.db.add_expense({"expense_date": "12-02-2026", "description": "Office", "currency": "USD",
                             "with_vat_subtotal": "100", "vat": "11", "expense_account": "6263.2"}, self.user)

    def damage(self, value="110,00"):
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("UPDATE expenses SET vat=?", (value,))

    def test_bad_number_nonfinite_and_bad_date_block_save_without_writes(self):
        for value in ("110,00", "NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.damage(value)
                with self.db.connect() as connection:
                    before = connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
                preview = vat_return.build_vat_return(self.db, 2026, 1)
                self.assertTrue(preview["skipped"])
                with self.assertRaisesRegex(ValueError, "Cannot save VAT return"):
                    vat_return.save_return(self.db, 2026, 1, self.user)
                self.assertIsNone(vat_return.saved_return(self.db, 2026, 1))
                with self.db.connect() as connection:
                    self.assertEqual(before, connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
        self.damage("11")
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("UPDATE expenses SET expense_date='bad date'")
        with self.assertRaisesRegex(ValueError, "Cannot save VAT return"):
            vat_return.save_return(self.db, 2026, 1, self.user)

    def test_previous_unsaved_quarter_cannot_supply_partial_credit(self):
        for value in ("110,00", "NaN", "bad amount", "1e9999"):
            with self.subTest(value=value):
                self.damage(value)
                with self.assertRaisesRegex(ValueError, "Cannot save VAT return"):
                    vat_return.save_return(self.db, 2026, 2, self.user)
                self.assertIsNone(vat_return.saved_return(self.db, 2026, 2))

    def test_correction_allows_save(self):
        self.damage(); self.damage("11")
        result = vat_return.save_return(self.db, 2026, 1, self.user)
        self.assertFalse(result["blocking_documents"])
        self.assertIsNotNone(vat_return.saved_return(self.db, 2026, 1))

    def test_future_rate_refuses_eur_document_before_any_invoice_write(self):
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("DELETE FROM exchange_rates WHERE from_currency='EUR' OR to_currency='EUR'")
        self.db.__dict__.pop("_rate_state", None)
        self.db.save_exchange_rate({"rate_date": "20-03-2026", "from_currency": "EUR", "to_currency": "USD", "rate": "1.2"}, self.user)
        with self.assertRaisesRegex(ValueError, "No EUR exchange rate on or before"):
            self.db.create_manual_invoice({"invoice_number": "FUTURE", "invoice_date": "15-03-2026", "party_name": "Buyer", "kind": "sale", "currency": "EUR"},
                                          [{"description": "Service", "quantity": 1, "unit_price": 100}], self.user)
        with self.db.connect() as connection:
            self.assertIsNone(connection.execute("SELECT id FROM invoices WHERE invoice_number='FUTURE'").fetchone())

    def test_history_download_does_not_backfill_from_future_or_latest(self):
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("DELETE FROM exchange_rates WHERE from_currency='EUR' OR to_currency='EUR'")
        payload = b'{"rates":{"2024-01-03":{"USD":1.2}}}'
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = payload
        with patch("db_rates.urllib.request.urlopen", return_value=response):
            self.db.sync_historical_exchange_rates()
        with self.db.connect() as connection:
            self.assertIsNone(connection.execute("SELECT id FROM exchange_rates WHERE from_currency='EUR' AND rate_date='01-01-2024'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT id FROM exchange_rates WHERE from_currency='EUR' AND rate_date='03-01-2024'").fetchone())
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("DELETE FROM exchange_rates WHERE from_currency='EUR' OR to_currency='EUR'")
        response.__enter__.return_value.read.return_value = b'{"rates":{}}'
        with patch("db_rates.urllib.request.urlopen", return_value=response):
            self.db.sync_historical_exchange_rates()
        with self.db.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exchange_rates WHERE from_currency='EUR'").fetchone()[0], 0)
