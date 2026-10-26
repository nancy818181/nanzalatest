"""Integrated from branch fix/purchase-90-payroll-intact (b04e29c, 18-10-2026), reviewed against 2.9.138 main.

1. OCR account suggestions use the company chart as the program sends it (Database.list_accounts / client.accounts():
   is_active, is_posting, parent_code). The filter read "active" and "id" / "parent_id", which that list does not have,
   so an INACTIVE account or a PARENT (non-posting) account could be suggested.
2. The "90%" coverage notice on a read purchase invoice: how many item lines got an account suggestion. It is a review
   hint only: it never allows posting and never replaces the accountant's review.
"""
import tempfile
import unittest
from pathlib import Path

import invoice_intake as intake


def company_chart(db):
    return db.list_accounts()


class ChartSuggestionUsesCompanyListTest(unittest.TestCase):
    def test_inactive_and_parent_accounts_from_list_accounts_are_never_suggested(self):
        parent = {"code": "6263", "name_en": "Office rent", "type": "expense", "is_active": 1, "is_posting": 0, "parent_code": "626"}
        inactive = {"code": "626300098", "name_en": "Office rent", "type": "expense", "is_active": 0, "is_posting": 1, "parent_code": "6263"}
        posting = {"code": "626300099", "name_en": "Office rent", "type": "expense", "is_active": 1, "is_posting": 1, "parent_code": "6263"}
        for name, chart in (("parent only", [parent]), ("inactive only", [inactive])):
            with self.subTest(chart=name):
                self.assertIsNone(intake.chart_suggestion("Office rent", chart, "operating_expense")["account_code"])
        self.assertEqual(intake.chart_suggestion("Office rent", [parent, inactive, posting], "operating_expense")["account_code"],
                         "626300099")

    def test_real_company_chart_only_gives_active_posting_accounts(self):
        import tests_setup  # noqa: F401
        from database import Database
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "company.db"); db.initialize("Synthetic-Only-2026!")
            try:
                chart = company_chart(db)
                by_code = {a["code"]: a for a in chart}
                for text in ("Office rent", "Electricity", "Telephone", "Fuel", "Stationery", "Insurance", "Maintenance"):
                    code = intake.chart_suggestion(text, chart, "operating_expense")["account_code"]
                    if code:
                        with self.subTest(text=text, code=code):
                            self.assertTrue(by_code[code]["is_active"])
                            self.assertTrue(by_code[code]["is_posting"])
            finally:
                db.release()


class PurchaseCoverageNoticeTest(unittest.TestCase):
    def test_nine_of_ten_is_a_success_notice_that_never_allows_posting(self):
        result = intake.check_90_percent_rule([{"suggested_account": "601100001"}] * 9 + [{}])
        self.assertEqual((result["percent"], result["classified"], result["total"]), (90, 9, 10))
        self.assertEqual(result["type"], "success")
        self.assertIn("9/10", result["message"])
        self.assertFalse(result["can_post"])
        self.assertTrue(result["requires_review"])

    def test_below_threshold_empty_and_incomplete_readings_warn(self):
        for items, complete in (([], True), ([{}] * 10, True),
                                ([{"suggested_account": "626340001"}] * 8 + [{}, {}], True),
                                ([{"suggested_account": "626340001"}], False)):
            with self.subTest(items=len(items), complete=complete):
                result = intake.check_90_percent_rule(items, complete)
                self.assertEqual(result["type"], "warning")
                self.assertFalse(result["can_post"])

    def test_enrich_marks_item_suggestions_and_adds_the_notice(self):
        chart = [{"code": "626300099", "name_en": "Office rent", "type": "expense", "is_active": 1, "is_posting": 1}]
        reading = {"text": "Supplier invoice", "invoice_number": "T-1", "invoice_date": "15-01-2026", "currency": "USD",
                   "subtotal": 100, "vat": 11, "total": 111,
                   "items": [{"description": "Office rent", "quantity": 1, "unit_price": 100, "total": 100}]}
        result = intake.enrich(reading, chart)
        self.assertEqual(result["items"][0]["suggested_account"], "626300099")
        self.assertEqual(result["notification_90"]["classified"], 1)
        self.assertFalse(result["notification_90"]["can_post"])


class PurchaseScreenShowsNoticeTest(unittest.TestCase):
    def test_purchase_pdf_label_shows_the_coverage_notice_and_still_needs_save(self):
        import types
        from unittest.mock import Mock, patch
        from desktop_stage3 import Stage3Mixin

        class Field:
            def __init__(self, value=""): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value
        purchase_vars = {key: Field(value) for key, value in
                         (("type", "Purchases"), ("vat", ""), ("number", ""), ("date", "15-03-2026"),
                          ("currency", "USD"), ("taxable", ""), ("supplier", ""))}
        purchase = types.SimpleNamespace(purchase_form={"id": None, "vars": purchase_vars,
            "items_sheet": types.SimpleNamespace(ordered=lambda: []), "pdf_label": Mock()},
            fiscal_today=lambda: "15-03-2026", purchase_amounts_changed=Mock())
        purchase.add_purchase_pdf_items = lambda data: Stage3Mixin.add_purchase_pdf_items(purchase, data)
        notice = intake.check_90_percent_rule([{"suggested_account": "626300099"}] * 9 + [{}])
        data = {"suggested_type": "Purchases", "vat": 11, "invoice_number": "P-1", "invoice_date": "15-03-2026",
                "currency": "USD", "subtotal": 100, "party_name": "Supplier", "notes": "Read from PDF - please check",
                "notification_90": notice}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "purchase.pdf"; path.write_bytes(b"%PDF-1.4\n")
            with patch("desktop_stage3.filedialog.askopenfilename", return_value=str(path)), \
                 patch("desktop_purchases.read_invoice_pdf", return_value=data), \
                 patch("desktop_stage3_common.review_handwriting", side_effect=lambda _a, _p, value, force=False: {**value, "intake_reviewed": True}), \
                 patch("desktop_stage3.simpledialog.askstring", return_value=None):
                Stage3Mixin.choose_purchase_pdf(purchase)
        text = purchase.purchase_form["pdf_label"].config.call_args.kwargs["text"]
        self.assertTrue(text.startswith(notice["message"]), text)
        self.assertIn("PDF attaches when you press Save", text)
        self.assertEqual(purchase.purchase_form["id"], None)  # nothing saved by reading


if __name__ == "__main__":
    unittest.main()
