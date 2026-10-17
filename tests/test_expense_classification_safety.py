"""Expense suggestions must expose conflicting evidence rather than select an arbitrary account."""
import tests_setup  # noqa: F401
import unittest
from unittest.mock import patch
import pdf_import
import posting_rules


class ExpenseClassificationSafetyTest(unittest.TestCase):
    def test_supplier_memory_does_not_override_a_different_current_expense(self):
        rule = {"data": {"expense_account": "6263.1"}, "label": "Example", "times": 2, "last_reference": "OLD"}
        with patch.object(posting_rules, "find_rule", return_value=rule):
            result = posting_rules.suggest(None, scope="expense", text="Vehicle repair maintenance")
        self.assertTrue(result["review_required"])
        self.assertIsNone(result["rule"])
        self.assertIsNone(result["account"])
        self.assertEqual(result["conflicting_rule"], rule)

    def test_matching_expense_parent_and_subaccount_keep_the_saved_rule(self):
        rule = {"data": {"expense_account": "626310001"}, "label": "Example", "times": 2, "last_reference": "OLD"}
        with patch.object(posting_rules, "find_rule", return_value=rule):
            result = posting_rules.suggest(None, scope="expense", text="Office rent")
        self.assertIs(result["rule"], rule)

    def test_conflicting_supplier_memory_does_not_replace_form_values(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from desktop_expenses import ExpensesMixin
        field = Mock()
        app = SimpleNamespace(expense_form={"vars": {"account": field}},
            client=SimpleNamespace(posting_suggestion=Mock(return_value={"review_required": True,
                "review_warnings": ["Choose the accounts manually"], "rule": None, "account": None})))
        note = ExpensesMixin.apply_expense_rule(app, "Example", text="Repair")
        field.set.assert_not_called()
        self.assertIn("manually", note)

    def test_equal_evidence_requires_manual_choice(self):
        text = "Invoice No: 9\nDate: 12-10-2026\nOffice rent and water\nGrand Total USD 100"
        reading = pdf_import._parse_invoice_text("bill.jpg", text)
        self.assertEqual(reading["expense_classification"]["status"], "ambiguous")
        self.assertEqual(reading["suggested_account"], "")
        self.assertEqual(reading["suggested_account_9"], "")
        self.assertIn("choose the account manually", reading["notes"])

    def test_repeated_headers_do_not_outvote_another_expense(self):
        result = pdf_import.expense_classification("Water\nWater\nWater\nOffice rent")
        self.assertEqual(result["status"], "ambiguous")

    def test_clear_arabic_expenses_have_visible_evidence(self):
        for text, expected in (("تصليح دواليب وبواجي", "Maintenance"),
                               ("دعاية وتسويق", "Advertising"), ("اشتراك كهرباء مولد", "Electricity")):
            with self.subTest(text=text):
                result = pdf_import.expense_classification(text)
                self.assertEqual(result["category"][0], expected)
                self.assertTrue(result["candidates"][0]["evidence"])
                self.assertTrue(result["review_required"])

    def test_unknown_text_stays_unknown(self):
        result = pdf_import.expense_classification("Invoice 005 Total 90 USD")
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["category"])

    def test_keyword_conflict_does_not_fall_back_to_chart_name_guess(self):
        with patch.object(posting_rules, "find_rule", return_value=None), \
             patch("ai_mapper.suggest_account") as mapper:
            result = posting_rules.suggest(None, scope="expense", text="Water and office rent")
        self.assertIsNone(result["account"])
        mapper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
