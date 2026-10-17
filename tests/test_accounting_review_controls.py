"""Purchase currency evidence, tax-option atomicity and report preparation controls."""
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

from database import Database
from landed_costs import normalize
from payroll_controls import review
import vat_return


class PurchaseCurrencyTest(unittest.TestCase):
    def test_dual_components_convert_once_and_preserve_sources(self):
        result, sources = normalize({"currency": "USD", "usd_lbp_rate": "89500", "currency_amounts": {
            "freight": {"USD": "10", "LBP": "89500"}, "customs_group_1": {"LBP": "179000"},
            "import_vat": {"LBP": "98450"}}}, "USD")
        self.assertEqual(Decimal(result["freight"]), Decimal("11"))
        self.assertEqual(Decimal(result["customs_group_1"]), Decimal("2"))
        self.assertEqual(Decimal(result["import_vat"]), Decimal("1.10"))
        self.assertEqual(len(sources), 4)
        self.assertEqual(sources[1][:3], ("freight", "LBP", "89500"))

    def test_post_in_lbp_and_round_component_after_adding_sources(self):
        result, _ = normalize({"currency": "LBP", "usd_lbp_rate": "89500", "currency_amounts": {
            "freight": {"USD": "1.25", "LBP": "500"}}}, "USD")
        self.assertEqual(Decimal(result["freight"]), Decimal("112375"))

    def test_bad_rates_amounts_and_unknown_components_are_rejected(self):
        for value in ("NaN", "Infinity", "-1", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize({"freight": value}, "USD")
            with self.subTest(vat=value), self.assertRaises(ValueError):
                normalize({"import_vat": value}, "USD")
        with self.assertRaisesRegex(ValueError, "positive"):
            normalize({"currency_amounts": {"freight": {"LBP": "100"}}}, "USD")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            normalize({"currency_amounts": {"typo": {"USD": "100"}}}, "USD")
        with self.assertRaisesRegex(ValueError, "either"):
            normalize({"freight": "10", "currency_amounts": {}}, "USD")


class InvoiceReviewIntegrationTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "company.db")
        self.db.initialize("secret12345")
        self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026",
            "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)

    def invoice(self, **extra):
        return self.db.create_manual_invoice({"invoice_date": "10-04-2026", "party_name": "Client",
            "kind": "sales", "currency": "USD", "status": "posted", **extra},
            [{"description": "Services", "quantity": 1, "unit_price": "100", "vat_rate": "11"}], 1)

    def test_exemption_uses_one_sales_sequence_and_does_not_remove_vat(self):
        from tax_adjustments import EXEMPT_REASONS
        self.invoice()
        exempt = self.invoice(income_exemption={"reason": EXEMPT_REASONS[0]})
        self.invoice()
        rows = sorted(self.db.list_invoices(), key=lambda row: row["id"])
        self.assertEqual([r["invoice_number"] for r in rows], [f"SAL-2026-{n:06d}" for n in range(1, 4)])
        self.assertTrue(all(Decimal(str(r["vat"])) == 11 for r in rows))
        self.assertEqual(self.db.income_exemptions()[0]["source_id"], exempt)
        self.assertEqual(self.db.next_invoice_number("sale", "10-04-2026"), "SAL-2026-000004")

    def test_invalid_exemption_or_storage_failure_saves_no_invoice(self):
        from tax_adjustments import NEEDS_ARTICLE, EXEMPT_REASONS
        with self.assertRaises(ValueError): self.invoice(income_exemption={"reason": NEEDS_ARTICLE})
        self.assertEqual(self.db.list_invoices(), [])
        with patch.object(self.db, "set_income_exemption", side_effect=ValueError("write failed")):
            with self.assertRaisesRegex(ValueError, "write failed"):
                self.invoice(income_exemption={"reason": EXEMPT_REASONS[0]})
        self.assertEqual(self.db.list_invoices(), [])

    def test_exemption_survives_edit_without_consuming_another_number(self):
        from tax_adjustments import EXEMPT_REASONS
        original = self.invoice(income_exemption={"reason": EXEMPT_REASONS[0]})
        replacement = self.db.replace_manual_invoice(original, {"invoice_date": "10-04-2026", "party_name": "Client",
            "kind": "sales", "currency": "USD", "status": "posted"},
            [{"description": "Services", "quantity": 1, "unit_price": "120", "vat_rate": "11"}], 1)
        self.assertIn(replacement, [r["source_id"] for r in self.db.income_exemptions()])
        self.assertEqual(self.db.next_invoice_number("sale", "10-04-2026"), "SAL-2026-000002")
        self.assertAlmostEqual(sum(r["amount"] for r in self.db.exempt_income(2026)), 120)

    def test_exemption_cannot_reference_a_purchase_or_missing_invoice(self):
        from tax_adjustments import EXEMPT_REASONS
        purchase = self.invoice(kind="purchases")
        for invoice_id in (purchase, 999999):
            with self.assertRaisesRegex(ValueError, "sales invoice"):
                self.db.set_income_exemption(invoice_id, EXEMPT_REASONS[0])

    def test_cost_payment_method_posts_and_requires_the_selected_cash_account(self):
        purchase = self.invoice(kind="purchases")
        with self.assertRaisesRegex(ValueError, "cash or bank"):
            self.db.add_landed_cost(purchase, {"freight": "10", "payment_method": "Cash"}, 1)
        self.assertEqual(self.db.landed_costs(purchase), [])
        cost = self.db.add_landed_cost(purchase, {"freight": "10", "import_vat": "1.10",
            "payment_method": "Cash", "cash_account": "531", "party_name": "Customs broker"}, 1)
        row = next(row for row in self.db.list_invoices() if row["id"] == cost)
        self.assertEqual(row["payment_method"], "Cash")
        self.assertAlmostEqual(row["amount_paid"], 11.1)
        self.assertEqual(self.db.unbalanced_entries(), [])

    def test_dual_cost_sources_and_balanced_posting(self):
        purchase = self.invoice(kind="purchases")
        cost = self.db.add_landed_cost(purchase, {"currency": "USD", "usd_lbp_rate": "89500",
            "currency_amounts": {"freight": {"USD": "10", "LBP": "89500"}, "import_vat": {"LBP": "98450"}}}, 1)
        row = self.db.landed_costs(purchase)[0]
        self.assertEqual(row["id"], cost)
        self.assertAlmostEqual(row["subtotal"], 11)
        self.assertAlmostEqual(row["vat"], 1.1)
        self.assertEqual(len(row["source_amounts"]), 3)
        self.assertEqual(self.db.unbalanced_entries(), [])
        with self.db.connect() as db:
            parts = list(db.execute("SELECT component,amount FROM landed_cost_parts WHERE cost_invoice_id=?", (cost,)))
        self.assertEqual([(p[0], Decimal(p[1])) for p in parts], [("freight", Decimal("11"))])


class PreparationControlTest(unittest.TestCase):
    def test_payroll_checks_each_record_so_errors_cannot_cancel(self):
        base = {"employee_id": 1, "period_date": "2026-01-31", "status": "posted", "currency": "USD",
                "gross_salary": "100", "family_allowance": "10", "employee_nssf": "5", "income_tax": "5", "net_salary": "100"}
        controls, _ = review([base])
        self.assertTrue(controls["arithmetic_agreed"])
        controls, sections = review([{**base, "net_salary": "99"}, {**base, "net_salary": "101", "status": "draft"}])
        self.assertEqual(controls["issue_count"], 3)  # two net errors and one duplicate month
        self.assertEqual(controls["draft_count"], 1)
        self.assertFalse(controls["arithmetic_agreed"])
        self.assertEqual(sections[0]["rows"][0][-1], 0)  # aggregate equality does not hide errors

    def test_vat_readiness_keeps_provisional_and_filtered_returns_distinct(self):
        self.assertEqual(vat_return.preparation_controls({})["status"], "REVIEW REQUIRED")
        self.assertTrue(vat_return.preparation_controls({"currency_filter": "USD"})["preview_only"])
        self.assertEqual(vat_return.preparation_controls({"dependency_errors": ["Q1 failed"]})["status"], "BLOCKED")

    def test_photo_review_retains_original_pixel_detail(self):
        from PIL import Image
        from desktop_stage3_common import handwriting_review_image
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invoice.png"
            Image.new("RGB", (1800, 2400), "white").save(path)
            with handwriting_review_image(path) as picture:
                self.assertEqual(picture.size, (1800, 2400))


if __name__ == "__main__":
    unittest.main()
