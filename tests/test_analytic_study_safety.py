"""Guard signed analytic totals, P&L reconciliation, and cautious account suggestions."""
import inspect
import unittest
from unittest.mock import patch

import nanza_paths  # noqa: F401
import ledger_reports
from nanza.ai_accountant.classifier import suggest_account
from nanza.ai_accountant.chat_engine import answer_question, classify_question
from nanza.reports.analytic_report import build_report
from nanza.reports.analytic_study import analyze_rows, build_study


class _StudyDatabase:
    def __init__(self, pnl_rows=None):
        self.pnl_rows = pnl_rows or [
            {"code": "701100001", "type": "income", "amount": 80},
            {"code": "601100000", "type": "expense", "amount": 40},
            {"code": "631000000", "type": "expense", "amount": 15},
        ]

    def budget_for_period(self, _currency, _start, _end):
        return {}

    def profit_and_loss_converted(self, _start, _end, _currency):
        return self.pnl_rows

    def cash_flow_monthly(self, *_args):
        return []

    def balance_sheet_converted(self, _date, _currency):
        return []


class AnalyticStudySafetyTests(unittest.TestCase):
    def test_study_builder_has_no_save_side_effect_option(self):
        self.assertNotIn("save", inspect.signature(build_study).parameters)

    def _rows(self):
        return [
            {"iso_date": "2025-01-10", "account_type": "income", "code": "701100001",
             "signed": {"USD": -100}},
            {"iso_date": "2025-01-11", "account_type": "income", "code": "701100001",
             "signed": {"USD": 20}},
            {"iso_date": "2025-01-12", "account_type": "expense", "code": "601100000",
             "signed": {"USD": 50}},
            {"iso_date": "2025-01-13", "account_type": "expense", "code": "601100000",
             "signed": {"USD": -10}},
            {"iso_date": "2025-01-14", "account_type": "expense", "code": "631000000",
             "signed": {"USD": 20}},
            {"iso_date": "2025-01-15", "account_type": "expense", "code": "631000000",
             "signed": {"USD": -5}},
        ]

    def test_revenue_reversals_and_expense_credits_remain_signed(self):
        result = analyze_rows(self._rows(), "2025-01-01", "2025-01-31")
        self.assertEqual(result["totals"]["revenue"], 80)
        self.assertEqual(result["totals"]["cost_of_sales"], 40)
        self.assertEqual(result["totals"]["expenses"], 15)

    def test_study_reports_reconciliation_against_pnl_without_saving(self):
        database = _StudyDatabase()
        with patch.object(ledger_reports, "_load_lines", return_value=self._rows()):
            result = build_study(database, "2025-01-01", "2025-01-31")
        self.assertTrue(result["pnl_check"]["matches"])
        self.assertIsNone(result["opening_balance"])
        self.assertIn("Opening balance unavailable - no prior year", result["warnings"])
        self.assertEqual(
            {key: item["difference"] for key, item in result["pnl_check"]["totals"].items()},
            {"revenue": 0, "cost_of_sales": 0, "expenses": 0},
        )

    def test_missing_2025_opening_is_unavailable_not_zero_for_2026(self):
        database = _StudyDatabase()
        with patch.object(ledger_reports, "_load_lines", return_value=[]):
            result = build_study(
                database, "2026-01-01", "2026-12-31",
                sources=[(database, "2026-01-01", "2026-12-31")],
            )
        self.assertIsNone(result["opening_balance"])
        self.assertFalse(result["comparative_2025"]["available"])
        self.assertEqual(result["comparative_2025"]["status"], "unavailable")
        report = build_report(result)
        self.assertIn("Opening balance unavailable - no prior year", report["warnings"])
        self.assertIn("Opening balance unavailable - no prior year", report["meta"])
        self.assertTrue(result["cashflow"]["quarters"] == [] or all(
            row["opening"] is None and row["closing"] is None
            for row in result["cashflow"]["quarters"]
        ))

    def test_study_flags_totals_that_do_not_match_pnl(self):
        database = _StudyDatabase()
        database.pnl_rows[0]["amount"] = 79
        with patch.object(ledger_reports, "_load_lines", return_value=self._rows()):
            result = build_study(database, "2025-01-01", "2025-01-31")
        self.assertFalse(result["pnl_check"]["matches"])
        self.assertEqual(result["pnl_check"]["totals"]["revenue"]["difference"], 1)

    def test_classifier_abstains_without_an_active_posting_account(self):
        result = suggest_account("fuel", [
            {"code": "601100000", "name_en": "Fuel", "type": "expense",
             "is_active": False, "is_posting": True},
            {"code": "601100001", "name_en": "Fuel", "type": "expense",
             "is_active": True, "is_posting": False},
        ])
        self.assertTrue(result["abstain"])
        self.assertIsNone(result["account_code"])
        self.assertNotIn("confidence", result)
        self.assertEqual(result["heuristic_score"], 0.0)

    def test_classifier_selects_only_active_posting_accounts(self):
        result = suggest_account("fuel", [
            {"code": "601100000", "name_en": "Fuel", "type": "expense",
             "is_active": True, "is_posting": True},
        ])
        self.assertFalse(result["abstain"])
        self.assertEqual(result["account_code"], "601100000")

    def test_classifier_matches_multilingual_terms_and_reports_ambiguity(self):
        accounts = [
            {"code": "601100000", "name_fr": "Carburant", "type": "expense",
             "is_active": True, "is_posting": True},
            {"code": "601100001", "name_en": "Fuel", "type": "expense",
             "is_active": True, "is_posting": True},
        ]
        result = suggest_account("carburant", accounts)
        self.assertTrue(result["abstain"])
        self.assertTrue(result["ambiguous"])
        self.assertEqual({item["account_code"] for item in result["candidates"]},
                         {"601100000", "601100001"})

    def test_fuel_filter_is_never_ignored(self):
        for question in ("fuel", "fuel report", "rapport carburant", "تقرير وقود",
                         "fuel cashflow Q3 2027"):
            with self.subTest(question=question):
                answer = answer_question(question, study={"totals": {}})
                self.assertEqual(answer["message"], "Fuel filter not yet supported")
                self.assertIsNone(answer["report"])
                self.assertEqual(classify_question(question)["topic"], "fuel")

    def test_unreconciled_report_has_a_prominent_warning_section(self):
        report = build_report({
            "totals": {},
            "pnl_check": {"matches": False, "totals": {"revenue": {"difference": 12.5}}},
        })
        self.assertIn("UNRECONCILED", report["warning"])
        self.assertEqual(report["sections"][0]["heading"], report["warning"])
        self.assertIn(report["warning"], report["meta"][0])


if __name__ == "__main__":
    unittest.main()
