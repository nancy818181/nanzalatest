"""Commercial source -> stock receipt -> invoice -> payment acceptance."""

import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from database import Database
import commercial_documents as c
import inventory


class CommercialTest(unittest.TestCase):
    def test_report_language_controls_rtl_independently_of_desktop_language(self):
        import report_export
        from openpyxl import load_workbook

        doc = self.order("quotation")
        for language, desktop_arabic in (("ar", False), ("en", True)):
            report = c.sections(doc, language)
            path = Path(self.tmp.name) / f"quotation-{language}.xlsx"
            with patch.object(
                report_export, "arabic_reports", return_value=desktop_arabic
            ):
                report_export.export_sections_excel(
                    path, report["title"], report["meta"], report["sections"]
                )
            self.assertEqual(
                load_workbook(path).active.sheet_view.rightToLeft, language == "ar"
            )

    def test_matching_arabic_preserves_amounts_and_explicit_rtl(self):
        doc = self.confirm(self.order())
        self.receipt(doc)
        self.invoice(doc, price="12")
        en = c.matching(self.db, doc["id"])
        ar = c.matching(self.db, doc["id"], "ar")
        self.assertEqual(ar["sections"][0]["report_language"], "ar")
        self.assertEqual(
            ar["sections"][0]["rows"][0][3:8], en["sections"][0]["rows"][0][3:8]
        )
        self.assertEqual(ar["sections"][1]["rows"][0][6], Decimal("8"))
        self.assertIn("مطابقة", ar["title"])

    def test_conversion_preserves_dual_role_supplier_identity(self):
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE parties SET kind='both' WHERE id=?", (self.supplier["id"],)
            )
        doc = self.receipt(self.confirm(self.order()))
        inv = self.invoice(doc)["invoice"]
        with self.db.connect() as connection:
            saved_party = connection.execute(
                "SELECT party_id FROM invoices WHERE id=?", (inv["id"],)
            ).fetchone()[0]
        self.assertEqual(saved_party, self.supplier["id"])
        with self.db.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM parties WHERE name='Test supplier'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_quotation_conversion_preserves_customer_and_requires_matching_direction(
        self,
    ):
        doc = self.confirm(self.order("quotation"))
        result = self.invoice(doc)["invoice"]
        with self.db.connect() as connection:
            saved_party = connection.execute(
                "SELECT party_id FROM invoices WHERE id=?", (result["id"],)
            ).fetchone()[0]
        self.assertEqual(saved_party, doc["party_id"])
        wrong = self.confirm(self.order("consignment"))
        with self.assertRaises(ValueError):
            self.invoice(wrong)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "books.db", pooled=True)
        self.db.initialize("Commercial-Test-2026!")
        self.addCleanup(self.db.release)
        self.supplier = self.db.save_party(
            {"kind": "supplier", "name": "Test supplier", "currency": "USD"}, 1
        )
        inventory.save_item(
            self.db, {"sku": "PAPER", "name": "Paper", "unit": "unit"}, 1
        )

    def order(self, kind="purchase_order"):
        party = (
            self.supplier
            if kind != "quotation"
            else self.db.save_party(
                {"kind": "customer", "name": "Test customer", "currency": "USD"}, 1
            )
        )
        return c.save(
            self.db,
            {
                "kind": kind,
                "doc_date": "15-01-2026",
                "party_id": party["id"],
                "currency": "USD",
            },
            [
                {
                    "sku": "PAPER",
                    "description": "ورق / Papier",
                    "quantity": "10",
                    "unit_price": "10",
                    "vat_rate": "11",
                }
            ],
            1,
        )

    def confirm(self, document):
        return c.set_status(
            self.db, document["id"], "confirmed", document["revision"], 1
        )

    def receipt(self, doc, quantity="4", reference="GRN-1"):
        return c.receive(
            self.db,
            doc["id"],
            {
                "doc_date": "16-01-2026",
                "reference": reference,
                "warehouse_id": "MAIN",
                "rows": [{"line": 1, "quantity": quantity}],
            },
            1,
        )

    def invoice(self, doc, qty="4", ref="INV-1", price="10"):
        return c.invoice(
            self.db,
            doc["id"],
            {
                "doc_date": "17-01-2026",
                "reference": ref,
                "invoice_number": ref,
                "rows": [{"line": 1, "quantity": qty, "unit_price": price}],
            },
            1,
        )

    def quantity(self):
        return next(
            r["quantity"] for r in inventory.list_items(self.db) if r["sku"] == "PAPER"
        )

    def test_commercial_document_and_confirmation_never_post_or_move_stock(self):
        doc = self.confirm(self.order())
        self.assertEqual(self.quantity(), 0)
        with self.db.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0
            )
        self.assertEqual(doc["status"], "confirmed")

    def test_partial_receipt_draft_approval_and_payment_do_not_double_stock(self):
        doc = self.receipt(self.confirm(self.order()))
        self.assertEqual(doc["lines"][0]["received"], "4")
        self.assertEqual(self.quantity(), 4)
        invoice = self.invoice(doc)["invoice"]
        iid = invoice["id"]
        self.assertEqual(invoice["status"], "review")
        self.assertEqual(self.quantity(), 4)
        self.assertEqual(
            self.db.approve_invoices([iid], {"id": 1, "role": "admin"}, False)[
                "skipped"
            ],
            [],
        )
        self.assertEqual(self.quantity(), 4)
        payment = self.db.add_payment(
            {
                "kind": "supplier_payment",
                "payment_date": "18-01-2026",
                "party_id": self.supplier["id"],
                "currency": "USD",
                "amount": "44.40",
                "cash_account": "531",
                "party_account": self.supplier["account_number"],
            },
            1,
        )
        self.db.save_allocations(payment, [{"invoice_id": iid, "amount": "44.40"}], 1)
        self.assertEqual(self.db.get_invoice(iid)["payment_status"], "paid")

    def test_receipt_retry_is_idempotent_and_reference_reuse_different_body_fails(self):
        doc = self.confirm(self.order())
        self.receipt(doc)
        self.receipt(doc)
        self.assertEqual(self.quantity(), 4)
        with self.assertRaisesRegex(ValueError, "different values"):
            self.receipt(doc, "5")

    def test_cannot_over_receive_or_invoice_unreceived_goods(self):
        doc = self.confirm(self.order())
        with self.assertRaisesRegex(ValueError, "maximum"):
            self.invoice(doc, "1")
        self.receipt(doc)
        with self.assertRaisesRegex(ValueError, "maximum"):
            self.receipt(doc, "7", "GRN-2")
        with self.assertRaisesRegex(ValueError, "maximum"):
            self.invoice(doc, "5")
        self.assertEqual(self.quantity(), 4)

    def test_invoice_retry_and_cancelled_draft_release_reservation(self):
        doc = self.receipt(self.confirm(self.order()))
        first = self.invoice(doc)["invoice"]
        again = self.invoice(doc)["invoice"]
        self.assertEqual(first["id"], again["id"])
        with self.assertRaisesRegex(ValueError, "maximum"):
            self.invoice(doc, "1", "INV-2")
        self.db.cancel_invoice(first["id"], "Wrong supplier invoice", 1)
        self.assertEqual(self.invoice(doc, "4", "INV-2")["invoice"]["status"], "review")

    def test_receipt_failure_rolls_back_stock_and_event(self):
        doc = self.confirm(self.order())
        with patch.object(c, "_event", side_effect=ValueError("audit failed")):
            with self.assertRaisesRegex(ValueError, "audit failed"):
                self.receipt(doc)
        self.assertEqual(self.quantity(), 0)
        self.assertEqual(c.get(self.db, doc["id"])["events"], [])

    def test_linked_stock_and_invoice_cannot_be_edited_around_order_controls(self):
        doc = self.receipt(self.confirm(self.order()))
        stock_id = doc["events"][0]["stock_document_id"]
        with self.assertRaisesRegex(ValueError, "linked"):
            inventory.delete_document(self.db, stock_id, 1)
        inv = self.invoice(doc)["invoice"]
        with self.assertRaisesRegex(ValueError, "Linked"):
            self.db.add_invoice_item(inv["id"], {}, 1)
        with self.assertRaisesRegex(ValueError, "Linked"):
            self.db.delete_invoice(inv["id"], 1)

    def test_confirmation_rejects_stale_revision_and_edit(self):
        doc = self.order()
        header = {**doc, "revision": doc["revision"]}
        newer = c.save(self.db, header, doc["lines"], 1, doc["id"])
        with self.assertRaisesRegex(ValueError, "changed"):
            self.confirm(doc)
        self.confirm(newer)
        with self.assertRaisesRegex(ValueError, "draft"):
            c.save(self.db, {**newer}, newer["lines"], 1, newer["id"])

    def test_print_formats_preserve_language_totals_and_non_posting_warning(self):
        for kind in ("quotation", "consignment"):
            doc = self.order(kind)
            report = c.sections(doc, "ar")
            self.assertTrue(report["title"])
            self.assertIn("ورق / Papier", str(report))
            self.assertEqual(report["sections"][0]["rows"][-1][-1], Decimal("111.00"))
            self.assertTrue(any("لا يرحّل" in text for text in report["meta"]))

    def test_price_variance_is_visible_and_not_automatically_revalued(self):
        doc = self.receipt(self.confirm(self.order()))
        self.invoice(doc, price="12")
        report = c.matching(self.db, doc["id"])
        self.assertEqual(report["sections"][1]["rows"][0][-2], Decimal("8"))

    def test_bad_numbers_and_missing_currency_are_rejected(self):
        for value in ("NaN", "Infinity", "-1", None):
            with self.assertRaises(ValueError):
                c.money(value, "amount")
        doc = self.order()
        with self.assertRaisesRegex(ValueError, "currency"):
            c.save(self.db, {**doc, "currency": ""}, doc["lines"], 1)


if __name__ == "__main__":
    unittest.main()
