"""Synthetic tests for local, presentation-only financial report preferences."""
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tests_setup  # noqa: F401
import app_runtime
from desktop_reports import ReportsMixin


class ReportPreferenceScopeTest(unittest.TestCase):
    def test_preferences_are_scoped_by_company_year_and_user(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app_runtime,"data_dir",return_value=Path(folder)):
            class App(ReportsMixin): pass
            app=App(); app.current_company={"id":17}; app.current_fiscal_year=2026; app.current_user={"id":4}
            app.client=SimpleNamespace(company_id=17,fiscal_year=2026)
            path=ReportsMixin._financial_filter_file(app)
            ReportsMixin._write_financial_preferences(app,{"shown_filters":["branch"],"presets":{"Quarter close":{"date_from":"01-01-2026"}}})
            self.assertEqual(ReportsMixin._read_financial_preferences(app)["presets"]["Quarter close"]["date_from"],"01-01-2026")

            other_company=App(); other_company.current_company={"id":18}; other_company.current_fiscal_year=2026
            other_company.current_user={"id":4}; other_company.client=SimpleNamespace(company_id=18,fiscal_year=2026)
            other_year=App(); other_year.current_company={"id":17}; other_year.current_fiscal_year=2025
            other_year.current_user={"id":4}; other_year.client=SimpleNamespace(company_id=17,fiscal_year=2025)
            other_user=App(); other_user.current_company={"id":17}; other_user.current_fiscal_year=2026
            other_user.current_user={"id":5}; other_user.client=SimpleNamespace(company_id=17,fiscal_year=2026)
            self.assertNotEqual(path,ReportsMixin._financial_filter_file(other_company))
            self.assertNotEqual(path,ReportsMixin._financial_filter_file(other_year))
            self.assertNotEqual(path,ReportsMixin._financial_filter_file(other_user))
            self.assertEqual(ReportsMixin._read_financial_preferences(other_company),{})

    def test_legacy_visible_filter_choice_is_carried_forward(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app_runtime,"data_dir",return_value=Path(folder)):
            (Path(folder)/"report_filters.json").write_text(json.dumps(["project","section"]),encoding="utf-8")
            class App(ReportsMixin): pass
            app=App(); app.current_company={"id":17}; app.current_fiscal_year=2026; app.current_user={"id":4}
            app.client=SimpleNamespace(company_id=17,fiscal_year=2026)
            self.assertEqual(ReportsMixin._read_financial_preferences(app)["shown_filters"],["project","section"])


if __name__ == "__main__":
    unittest.main()
