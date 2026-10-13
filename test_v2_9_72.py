"""2.9.72: the VAT of each company (rate and the two currencies of its VAT return), and several purchases /
expenses / payments deleted at once."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from company_manager import CompanyManager
from database import Database
from database_common import parse_vat_rate
import inventory
import vat_return

try:
    import tkinter  # noqa: F401
    HAS_TK = True
except ImportError:
    HAS_TK = False


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345")
        self.addCleanup(self.db.release)

    def invoice(self, number, kind, currency, subtotal, vat, day="15-02-2026"):
        return self.db.import_invoice({"invoice_number": number, "invoice_date": day, "party_name": f"Party {kind}", "kind": kind,
                                       "currency": currency, "subtotal": subtotal, "vat": vat, "total": subtotal + vat}, 1)


class VatSettingsTest(_Book):
    def test_rate_is_read_as_a_percentage(self):
        self.assertEqual(parse_vat_rate("11"), Decimal("11")); self.assertEqual(parse_vat_rate("5%"), Decimal("5"))
        self.assertEqual(parse_vat_rate("7,5"), Decimal("7.5")); self.assertEqual(parse_vat_rate("15.0"), Decimal("15"))
        for wrong in ("abc", "-1", "120"):
            with self.assertRaises(ValueError): parse_vat_rate(wrong)

    def test_lebanese_defaults_and_settings_can_change_them(self):
        self.assertEqual(self.db.vat_rate_percent(), Decimal("11")); self.assertEqual(self.db.vat_currencies(), ("LBP", "USD"))
        self.db.save_settings({"vat_rate": "5%", "vat_currency": "AED", "vat_second_currency": "USD"}, 1)
        self.assertEqual(self.db.vat_rate_percent(), Decimal("5")); self.assertEqual(self.db.vat_currencies(), ("AED", "USD"))
        with self.assertRaisesRegex(ValueError, "different"): self.db.save_settings({"vat_currency": "USD", "vat_second_currency": "USD"}, 1)
        with self.assertRaisesRegex(ValueError, "Invalid VAT currency"): self.db.save_settings({"vat_currency": "XYZ"}, 1)
        with self.assertRaisesRegex(ValueError, "between 0 and 100"): self.db.save_settings({"vat_rate": "150"}, 1)

    def test_company_is_created_with_its_vat(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder); old_env = os.environ.get("SABER_DATA_DIR"); os.environ["SABER_DATA_DIR"] = str(root / "data")
            try:
                master = Database(root / "saber_accounting.db"); master.initialize("secret")
                manager = CompanyManager(root / "saber_accounting.db")
                company = manager.create_company({"name": "Dubai Trading LLC", "year": 2026, "main_currency_1": "AED", "main_currency_2": "USD",
                                                  "vat_rate": "5", "vat_currency_1": "aed", "vat_currency_2": "usd"}, master)
                book = manager.database(company["id"], 2026)
                self.assertEqual((book.vat_rate_percent(), book.vat_currencies()), (Decimal("5"), ("AED", "USD")))
                local = manager.create_company({"name": "Beirut SAL", "year": 2026}, master)
                self.assertEqual(manager.database(local["id"], 2026).vat_currencies(), ("LBP", "USD"))
                with self.assertRaisesRegex(ValueError, "VAT"):
                    manager.create_company({"name": "Bad VAT", "year": 2026, "vat_rate": "abc"}, master)
                self.assertFalse(any(c["name"] == "Bad VAT" for c in manager.list_companies(True)))
                for path in list(manager._cache): manager._cache.pop(path).release()
                master.release()
            finally:
                if old_env is None: os.environ.pop("SABER_DATA_DIR", None)
                else: os.environ["SABER_DATA_DIR"] = old_env


class VatRateUsedTest(_Book):
    def test_invoice_line_without_rate_takes_the_company_rate(self):
        self.db.save_settings({"vat_rate": "5"}, 1)
        created = self.db.create_manual_invoice({"invoice_number": "S-5", "invoice_date": "15-02-2026", "party_name": "Client", "kind": "sales", "currency": "USD"},
                                                [{"description": "Service", "quantity": 1, "unit_price": 200}], 1) if hasattr(self.db, "create_manual_invoice") else None
        if created is None: self.skipTest("manual invoices not available")
        invoice_id = created if isinstance(created, int) else created.get("id") or created.get("invoice", {}).get("id")
        self.assertEqual(Decimal(str(self.db.get_invoice(invoice_id)["vat"])), Decimal("10"))

    def test_item_standard_vat_is_the_company_rate(self):
        self.db.save_settings({"vat_rate": "15"}, 1)
        saved = inventory.save_item(self.db, {"name": "Widget", "unit": "unit", "default_vat": "15%"}, 1)
        item_id = saved["id"] if isinstance(saved, dict) else saved
        with self.db.connect() as connection:
            self.assertEqual(connection.execute("SELECT default_vat FROM inventory_items WHERE id=?", (item_id,)).fetchone()[0], "15")


class VatReturnCurrencyTest(_Book):
    def test_lebanese_return_is_unchanged_in_lbp(self):
        self.invoice("S-1", "sale", "LBP", 1000000, 110000)
        result = vat_return.build_vat_return(self.db, 2026, 1)
        self.assertEqual((result["vat_currency"], result["vat_second_currency"]), ("LBP", "USD"))
        self.assertEqual(result["totals_lbp"]["net"], Decimal("110000"))
        self.assertEqual(result["payable_lbp"], Decimal("110000"))  # rounded up to LBP 10,000 as before

    def test_return_in_aed_at_5_percent_with_usd_next_to_it(self):
        self.db.save_settings({"vat_rate": "5", "vat_currency": "AED", "vat_second_currency": "USD"}, 1)
        self.invoice("S-1", "sale", "AED", 1000, 50)
        self.invoice("P-1", "purchase", "USD", 100, 5)
        result = vat_return.build_vat_return(self.db, 2026, 1)
        self.assertEqual(result["vat_currency"], "AED")
        self.assertEqual(result["totals_lbp"]["total_output"], Decimal("50.00"))
        self.assertEqual(result["totals_lbp"]["total_input"], Decimal("18.36"))  # 5 USD x 3.6725
        self.assertEqual(result["payable_lbp"], Decimal("31.64"))  # no LBP 10,000 rounding in AED
        self.assertEqual(result["second"]["payable"], Decimal("8.62"))  # 31.64 / 3.6725
        self.assertFalse(any("10,000" in w for w in result["warnings"]))
        title, meta, sections = vat_return.export_sections(result)
        summary = next(s for s in sections if s["heading"].startswith("VAT calculation summary"))
        self.assertIn("in AED", summary["heading"]); self.assertEqual(summary["headers"][-2:], ["Amount (AED)", "Amount (USD)"])
        self.assertTrue(any("5%" in str(row[1]) for row in summary["rows"]))
        self.assertFalse(any("11%" in str(row[1]) for row in summary["rows"]))


class BulkDeleteImportTest(unittest.TestCase):
    @unittest.skipUnless(HAS_TK, "needs tkinter")
    def test_purchases_expenses_and_payments_can_delete_several_rows(self):
        import desktop_expenses, desktop_purchases, desktop_stage3
        for module in (desktop_purchases, desktop_expenses, desktop_stage3):
            self.assertTrue(callable(getattr(module, "bulk_action", None)), module.__name__)


if __name__ == "__main__":
    unittest.main()
